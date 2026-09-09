"""NMSI (Visitor Satisfaction Index) pipeline — adapted from reference implementation."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN
from sklearn.metrics.pairwise import cosine_similarity

from .models import PHASE_LABELS, ClusterNamingInput


DEFAULT_PHASE_WEIGHTS = {
    "pre_visit": 0.10,
    "arrival": 0.12,
    "exhibition": 0.18,
    "experience": 0.22,
    "show_interaction": 0.18,
    "food_retail": 0.10,
    "exit_reflection": 0.10,
}

PHASE_ORDER = list(DEFAULT_PHASE_WEIGHTS)


@dataclass
class NMSIConfig:
    phase_weights: dict[str, float]
    alpha_memory: float = 0.12
    beta_revisit: float = 0.12
    gamma_friction: float = 0.18
    logit_scale: float = 2.0
    star_blend: float = 0.15


def _batched(values: list[dict], size: int):
    for start in range(0, len(values), size):
        yield values[start: start + size]


def analyze_sentences(
    df: pd.DataFrame,
    batch_size: int = 20,
    progress_cb=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from .openai_service import analyze_sentence_batch

    required = {"review_id", "sentence"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"必要な列がありません: {sorted(missing)}")

    source = df.reset_index(drop=True).copy()
    records = [
        {
            "index": int(i),
            "review_id": str(row["review_id"]),
            "sentence": str(row["sentence"]),
            "rating": None if pd.isna(row.get("rating")) else float(row.get("rating")),
        }
        for i, row in source.iterrows()
    ]

    analyses = []
    total_batches = math.ceil(len(records) / batch_size)
    for batch_num, batch in enumerate(_batched(records, batch_size), 1):
        parsed = analyze_sentence_batch(batch)
        analyses.extend(item.model_dump() for item in parsed.items)
        if progress_cb:
            progress_cb("sentence_batch", batch_num, total_batches)

    analysis_df = pd.DataFrame(analyses)
    if analysis_df.empty:
        raise ValueError("分析可能な文章がありませんでした。")
    if analysis_df["source_index"].duplicated().any():
        raise ValueError("GPT出力でsource_indexが重複しました。再実行してください。")
    expected = set(range(len(source)))
    returned = set(analysis_df["source_index"].astype(int))
    if expected != returned:
        missing_i = sorted(expected - returned)
        extra_i   = sorted(returned - expected)
        raise ValueError(
            f"source_indexが入力と一致しません。missing={missing_i}, extra={extra_i}"
        )

    analysis_df = analysis_df.merge(
        source.reset_index(names="source_index"),
        on="source_index",
        how="left",
        validate="one_to_one",
    )

    mention_rows: list[dict[str, Any]] = []
    for _, row in analysis_df.iterrows():
        mentions = row["place_mentions"] or []
        for mention in mentions:
            mention_rows.append({
                "source_index": int(row["source_index"]),
                "review_id": row["review_id"],
                "sentence": row["sentence"],
                "phase": row["phase"],
                "sentiment": float(row["sentiment"]),
                "intensity": float(row["intensity"]),
                "analysis_confidence": float(row["confidence"]),
                "positive_summary": row["positive_summary"],
                "negative_summary": row["negative_summary"],
                "surface_form": mention["surface_form"].strip(),
                "place_function": mention["place_function"].strip(),
                "mention_confidence": float(mention["mention_confidence"]),
            })
    mentions_df = pd.DataFrame(mention_rows)
    return analysis_df, mentions_df


# ─── Clustering helpers ───────────────────────────────────────────────────────

def _adaptive_min_cluster_size(n: int) -> int:
    return max(2, min(12, int(round(math.sqrt(max(n, 1)) * 0.7))))


def _cluster_medoid_indices(
    embeddings: np.ndarray, labels: np.ndarray
) -> dict[int, int]:
    medoids: dict[int, int] = {}
    for label in sorted(set(labels)):
        members = np.flatnonzero(labels == label)
        if len(members) == 1:
            medoids[int(label)] = int(members[0])
            continue
        sim = cosine_similarity(embeddings[members], embeddings[members])
        medoids[int(label)] = int(members[np.argmax(sim.mean(axis=1))])
    return medoids


def _absorb_or_split_noise(
    embeddings: np.ndarray,
    labels: np.ndarray,
    absorb_threshold: float = 0.80,
    noise_join_threshold: float = 0.86,
) -> np.ndarray:
    result = labels.astype(int).copy()
    stable = sorted(label for label in set(result) if label >= 0)
    noise = list(np.flatnonzero(result < 0))
    next_label = (max(stable) + 1) if stable else 0

    if stable:
        centroids = []
        for label in stable:
            centroid = embeddings[result == label].mean(axis=0)
            centroid /= max(np.linalg.norm(centroid), 1e-12)
            centroids.append(centroid)
        centroid_matrix = np.vstack(centroids)
        for idx in noise[:]:
            sims = embeddings[idx] @ centroid_matrix.T
            best = int(np.argmax(sims))
            if sims[best] >= absorb_threshold:
                result[idx] = stable[best]
                noise.remove(idx)

    unvisited = set(noise)
    while unvisited:
        seed = unvisited.pop()
        component = {seed}
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            candidates = list(unvisited)
            if not candidates:
                break
            sims = embeddings[current] @ embeddings[candidates].T
            joined = [candidates[i] for i, v in enumerate(sims) if v >= noise_join_threshold]
            for item in joined:
                unvisited.remove(item)
                component.add(item)
                frontier.append(item)
        for idx in component:
            result[idx] = next_label
        next_label += 1
    return result


def cluster_places(
    mentions_df: pd.DataFrame,
    progress_cb=None,
) -> tuple[pd.DataFrame, np.ndarray]:
    from .openai_service import embed_texts

    if mentions_df.empty:
        return mentions_df.copy(), np.empty((0, 0), dtype=np.float32)

    if progress_cb:
        progress_cb("embedding", 0, 1)

    cluster_texts = (
        mentions_df["surface_form"].fillna("")
        + "｜機能:"
        + mentions_df["place_function"].fillna("")
    ).tolist()
    embeddings = embed_texts(cluster_texts)

    if progress_cb:
        progress_cb("embedding", 1, 1)

    n = len(mentions_df)
    min_cluster_size = _adaptive_min_cluster_size(n)

    if n == 1:
        labels = np.array([0], dtype=int)
    else:
        model = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=max(1, min_cluster_size // 2),
            metric="euclidean",
            cluster_selection_method="eom",
            allow_single_cluster=True,
        )
        labels = model.fit_predict(embeddings)
        labels = _absorb_or_split_noise(embeddings, labels)

    result = mentions_df.copy()
    result["provisional_cluster_id"] = labels
    return result, embeddings


def _top_unique(values: pd.Series, limit: int = 8) -> list[str]:
    output: list[str] = []
    for v in values.fillna("").astype(str):
        v = v.strip()
        if v and v not in output:
            output.append(v)
        if len(output) >= limit:
            break
    return output


def name_place_clusters(
    clustered: pd.DataFrame,
    embeddings: np.ndarray,
    progress_cb=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from .openai_service import name_clusters

    if clustered.empty:
        return clustered.copy(), pd.DataFrame()

    labels = clustered["provisional_cluster_id"].to_numpy(dtype=int)
    medoids = _cluster_medoid_indices(embeddings, labels)
    naming_inputs: list[ClusterNamingInput] = []

    for cluster_id, group in clustered.groupby("provisional_cluster_id", sort=True):
        representative = clustered.iloc[medoids[int(cluster_id)]]["surface_form"]
        naming_inputs.append(ClusterNamingInput(
            provisional_cluster_id=int(cluster_id),
            representative_phrase=str(representative),
            member_phrases=_top_unique(group["surface_form"], 12),
            place_functions=_top_unique(group["place_function"], 8),
            evidence_sentences=_top_unique(group["sentence"], 8),
            positive_evidence=_top_unique(
                group.loc[group["sentiment"] > 0, "positive_summary"], 5),
            negative_evidence=_top_unique(
                group.loc[group["sentiment"] < 0, "negative_summary"], 5),
        ))

    if progress_cb:
        progress_cb("naming", 0, 1)

    parsed = name_clusters([item.model_dump() for item in naming_inputs])
    names = pd.DataFrame(item.model_dump() for item in parsed.items)
    expected = set(clustered["provisional_cluster_id"].astype(int))
    returned = set(names["provisional_cluster_id"].astype(int))
    if expected != returned:
        raise ValueError(f"命名クラスターIDが不一致: expected={expected}, returned={returned}")

    names = names.sort_values(
        by=["phase", "provisional_cluster_id"],
        key=lambda col: col.map({p: i for i, p in enumerate(PHASE_ORDER)})
            if col.name == "phase" else col,
    ).reset_index(drop=True)
    names["place_id"] = [f"L{i:03d}" for i in range(1, len(names) + 1)]

    if progress_cb:
        progress_cb("naming", 1, 1)

    output = clustered.merge(names, on="provisional_cluster_id", how="left",
                             validate="many_to_one")
    location_table = (
        output.groupby(
            ["place_id", "place_name", "upper_place", "phase"],
            as_index=False, dropna=False,
        ).agg(
            mention_count=("source_index", "size"),
            review_count=("review_id", "nunique"),
            positive_mentions=("sentiment", lambda s: int((s > 0).sum())),
            negative_mentions=("sentiment", lambda s: int((s < 0).sum())),
            positive_summary=("positive_summary_y", "first"),
            negative_summary=("negative_summary_y", "first"),
            naming_rationale=("naming_rationale", "first"),
        )
    )
    location_table["phase_label"] = location_table["phase"].map(PHASE_LABELS)
    return output, location_table


# ─── NMSI calculation ─────────────────────────────────────────────────────────

def _mean_top_two(row: pd.Series) -> float:
    signals = sorted([
        float(row["wait"]), float(row["congestion"]),
        float(row["restriction"]), float(row["expectation_gap"]),
        float(row["cost_burden"]), float(row["information_gap"]),
    ], reverse=True)
    return float(np.mean(signals[:2]))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def calculate_nmsi(
    analysis_df: pd.DataFrame,
    config: NMSIConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, float | str]]:
    if config is None:
        config = NMSIConfig(phase_weights=DEFAULT_PHASE_WEIGHTS.copy())
    data = analysis_df.copy()

    data["effective_sentiment"] = data["sentiment"].astype(float)
    if "rating" in data.columns and config.star_blend > 0:
        rating_signal = (
            (pd.to_numeric(data["rating"], errors="coerce") - 3.0) / 2.0
        ).clip(-1, 1)
        has_rating = rating_signal.notna()
        data.loc[has_rating, "effective_sentiment"] = (
            (1.0 - config.star_blend) * data.loc[has_rating, "effective_sentiment"]
            + config.star_blend * rating_signal.loc[has_rating]
        )

    data["evidence_weight"] = (
        data["intensity"].astype(float) * data["confidence"].astype(float)
    ).clip(lower=0.05)
    data["friction"] = data.apply(_mean_top_two, axis=1)

    rows = []
    observed_weights = {
        phase: weight
        for phase, weight in config.phase_weights.items()
        if (data["phase"] == phase).any()
    }
    weight_total = sum(observed_weights.values()) or 1.0

    for phase in PHASE_ORDER:
        group = data[data["phase"] == phase]
        if group.empty:
            continue
        evidence = group["evidence_weight"].to_numpy(float)
        sentiment = group["effective_sentiment"].to_numpy(float)
        total = evidence.sum()
        effect = float(np.sum(sentiment * evidence) / max(total, 1e-12))
        positive = (effect + 1.0) / 2.0
        negative = (1.0 - effect) / 2.0
        normalized_weight = observed_weights.get(phase, 0.0) / weight_total
        rows.append({
            "phase": phase,
            "フェーズ": PHASE_LABELS[phase],
            "重み": normalized_weight,
            "ポジティブ": positive,
            "ネガティブ": negative,
            "E_i": effect,
            "文数": len(group),
            "根拠重み合計": total,
        })

    phase_table = pd.DataFrame(rows)
    base = float((phase_table["重み"] * phase_table["E_i"]).sum())

    evidence = data["evidence_weight"].to_numpy(float)
    denom = max(evidence.sum(), 1e-12)
    memory = float(
        np.sum(
            data["memory"].astype(float).to_numpy()
            * data["self_relation"].astype(float).to_numpy()
            * evidence
        ) / denom
    )
    revisit = float(
        np.sum(
            np.maximum(
                data["revisit"].astype(float).to_numpy(),
                data["recommend"].astype(float).to_numpy(),
            ) * evidence
        ) / denom
    )
    friction = float(np.sum(data["friction"].to_numpy(float) * evidence) / denom)

    adjusted = (
        base
        + config.alpha_memory * memory
        + config.beta_revisit * revisit
        - config.gamma_friction * friction
    )
    score = 100.0 * _sigmoid(config.logit_scale * adjusted)

    if score >= 85:
        interpretation = "強い感動・推奨レベル"
    elif score >= 70:
        interpretation = "高満足"
    elif score >= 55:
        interpretation = "満足だが改善余地あり"
    elif score >= 40:
        interpretation = "期待未達"
    else:
        interpretation = "不満・失望"

    summary: dict[str, float | str] = {
        "NMSI": round(score, 1),
        "解釈": interpretation,
        "フェーズ加重効果": round(base, 4),
        "記憶補正_M": round(memory, 4),
        "再訪推奨補正_R": round(revisit, 4),
        "摩擦補正_F": round(friction, 4),
        "補正後潜在値": round(adjusted, 4),
        "logit_scale": config.logit_scale,
        "alpha_memory": config.alpha_memory,
        "beta_revisit": config.beta_revisit,
        "gamma_friction": config.gamma_friction,
    }
    return phase_table, summary


def run_pipeline(
    source_df: pd.DataFrame,
    batch_size: int = 20,
    config: NMSIConfig | None = None,
    progress_cb=None,
) -> dict[str, Any]:
    analysis_df, mentions_df = analyze_sentences(source_df, batch_size=batch_size,
                                                 progress_cb=progress_cb)
    clustered, embeddings = cluster_places(mentions_df, progress_cb=progress_cb)
    mention_results, location_table = name_place_clusters(clustered, embeddings,
                                                          progress_cb=progress_cb)
    phase_table, nmsi = calculate_nmsi(analysis_df, config=config)
    return {
        "sentence_analysis": analysis_df,
        "place_mentions": mention_results,
        "location_table": location_table,
        "phase_table": phase_table,
        "nmsi": nmsi,
    }


def config_to_dict(config: NMSIConfig) -> dict[str, Any]:
    return asdict(config)
