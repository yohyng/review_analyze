"""Visitor pattern clustering and VFFI pipeline.
Adapted from the reference implementation (replit_location_nmsi_v2).
Uses beta.chat.completions.parse instead of responses.parse.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler, normalize

from .pipeline import (
    _absorb_or_split_noise,
    _adaptive_min_cluster_size,
    _cluster_medoid_indices,
)


FEATURE_GROUPS: dict[str, list[str]] = {
    "A": [
        "family_with_children", "solo", "couple", "friends_group",
        "elderly_companion", "tourist", "local_resident", "enthusiast_professional",
    ],
    "P": [
        "learning", "tourism", "child_experience", "nostalgia",
        "brand_understanding", "architecture_appreciation",
        "photography_sns", "event_participation", "shopping_food",
    ],
    "E": [
        "detailed_explanation", "entertainment", "child_enjoyment",
        "nostalgia_expectation", "low_congestion", "character_interaction",
        "comfort", "price_value",
    ],
    "S": [
        "learning", "discovery", "immersion", "physical_participation",
        "family_sharing", "character_interaction", "show_experience",
        "circulation_comfort", "infant_safety", "price_acceptance",
        "sns_photo", "brand_immersion",
    ],
    "F": [
        "wait", "congestion", "restriction", "cost",
        "information_gap", "expectation_gap", "fatigue", "age_mismatch",
    ],
    "B": [
        "revisit", "recommend", "share", "complaint", "one_time_only",
    ],
}

GROUP_SOURCE_KEYS = {
    "A": "attributes",
    "P": "purposes",
    "E": "expectations",
    "S": "experienced_values",
    "F": "frictions",
    "B": "behavior_intentions",
}

GROUP_WEIGHTS = {
    "A": 0.12, "P": 0.14, "E": 0.14,
    "S": 0.22, "F": 0.22, "B": 0.16,
}

FEATURE_LABELS = {
    "A_family_with_children": "子ども連れ", "A_solo": "一人利用",
    "A_couple": "カップル", "A_friends_group": "友人グループ",
    "A_elderly_companion": "高齢者同行", "A_tourist": "観光客",
    "A_local_resident": "地域住民", "A_enthusiast_professional": "専門家・愛好家",
    "P_learning": "学習目的", "P_tourism": "観光目的",
    "P_child_experience": "子どもの体験目的", "P_nostalgia": "ノスタルジー目的",
    "P_brand_understanding": "ブランド理解目的", "P_architecture_appreciation": "建築鑑賞目的",
    "P_photography_sns": "写真・SNS目的", "P_event_participation": "イベント参加目的",
    "P_shopping_food": "買物・飲食目的",
    "E_detailed_explanation": "詳しい解説への期待", "E_entertainment": "エンタメへの期待",
    "E_child_enjoyment": "子どもの楽しさへの期待", "E_nostalgia_expectation": "懐かしさへの期待",
    "E_low_congestion": "混雑の少なさへの期待", "E_character_interaction": "キャラクター交流への期待",
    "E_comfort": "快適性への期待", "E_price_value": "価格相応価値への期待",
    "S_learning": "学習", "S_discovery": "発見", "S_immersion": "没入",
    "S_physical_participation": "身体参加", "S_family_sharing": "家族共有",
    "S_character_interaction": "キャラクター交流", "S_show_experience": "ショー体験",
    "S_circulation_comfort": "快適な回遊", "S_infant_safety": "幼児安心性",
    "S_price_acceptance": "価格納得感", "S_sns_photo": "SNS・写真",
    "S_brand_immersion": "ブランド没入",
    "F_wait": "待ち時間", "F_congestion": "混雑", "F_restriction": "体験制限",
    "F_cost": "料金負担", "F_information_gap": "情報不足",
    "F_expectation_gap": "期待未達", "F_fatigue": "疲労", "F_age_mismatch": "年齢ミスマッチ",
    "B_revisit": "再訪意向", "B_recommend": "推奨意向", "B_share": "共有意向",
    "B_complaint": "批判・不満投稿", "B_one_time_only": "一度で十分",
}

FEATURE_COLUMNS = [
    f"{prefix}_{name}"
    for prefix, names in FEATURE_GROUPS.items()
    for name in names
]


@dataclass
class VisitorClusteringConfig:
    structured_share: float = 0.75
    semantic_share: float = 0.25
    random_state: int = 42
    gmm_n_init: int = 10
    softmax_temperature: float = 0.15


@dataclass
class VFFIConfig:
    fit_threshold: float = 0.70
    satisfaction_threshold: float = 0.70
    matching_weight: float = 0.30
    satisfaction_weight: float = 0.25
    cosine_weight: float = 0.45
    gap_penalty: float = 0.90


def _batch_items(values: list[dict], size: int):
    for start in range(0, len(values), size):
        yield values[start: start + size]


def _flatten_pattern(item: dict[str, Any], review_text: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "review_id": str(item["review_id"]),
        "review_text": review_text,
        "overall_satisfaction": item.get("overall_satisfaction"),
        "extraction_confidence": float(item["extraction_confidence"]),
        "evidence": "｜".join(item.get("evidence") or []),
    }
    for prefix, source_key in GROUP_SOURCE_KEYS.items():
        values = item[source_key]
        for name in FEATURE_GROUPS[prefix]:
            row[f"{prefix}_{name}"] = values.get(name)
    return row


def extract_visitor_profiles(
    source_df: pd.DataFrame,
    batch_size: int = 10,
    progress_cb=None,
) -> pd.DataFrame:
    from .openai_service import analyze_visitor_patterns

    required = {"review_id", "sentence"}
    missing = required - set(source_df.columns)
    if missing:
        raise ValueError(f"CSVに必要な列がありません: {sorted(missing)}")

    grouped = (
        source_df.assign(
            review_id=source_df["review_id"].astype(str),
            sentence=source_df["sentence"].astype(str),
        )
        .groupby("review_id", sort=True)["sentence"]
        .apply(list)
    )
    records = [
        {"review_id": review_id, "sentences": sentences}
        for review_id, sentences in grouped.items()
    ]

    parsed_items: list[dict[str, Any]] = []
    total_batches = math.ceil(len(records) / batch_size)
    for batch_num, batch in enumerate(_batch_items(records, batch_size), 1):
        parsed = analyze_visitor_patterns(batch)
        parsed_items.extend(item.model_dump() for item in parsed.items)
        if progress_cb:
            progress_cb("visitor_extraction", batch_num, total_batches)

    expected = {item["review_id"] for item in records}
    returned = {str(item["review_id"]) for item in parsed_items}
    if expected != returned or len(parsed_items) != len(returned):
        raise ValueError(
            "来場者パターン抽出のreview_idが入力と一致しません。"
            f" missing={sorted(expected-returned)}, extra={sorted(returned-expected)}"
        )

    text_map = {
        item["review_id"]: "。".join(item["sentences"])
        for item in records
    }
    rows = [
        _flatten_pattern(item, text_map[str(item["review_id"])])
        for item in parsed_items
    ]
    return pd.DataFrame(rows).sort_values("review_id").reset_index(drop=True)


def _impute_feature_frame(profiles: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    numeric = profiles[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    missing = numeric.isna().astype(float)
    imputed = numeric.copy()
    for column in FEATURE_COLUMNS:
        observed = numeric[column].dropna()
        fill = float(observed.median()) if not observed.empty else 0.5
        imputed[column] = numeric[column].fillna(fill)
    return imputed, missing


def build_visitor_matrix(
    profiles: pd.DataFrame,
    config: VisitorClusteringConfig | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    from .openai_service import embed_texts

    config = config or VisitorClusteringConfig()
    if profiles.empty:
        return np.empty((0, 0)), {}

    imputed, missing = _impute_feature_frame(profiles)
    structured_parts = []
    structured_meta = {}
    for prefix, names in FEATURE_GROUPS.items():
        columns = [f"{prefix}_{name}" for name in names]
        scaled = StandardScaler().fit_transform(imputed[columns])
        group_scale = math.sqrt(
            config.structured_share * GROUP_WEIGHTS[prefix] / max(len(columns), 1)
        )
        structured_parts.append(scaled * group_scale)
        structured_meta[prefix] = {"columns": columns, "weight": GROUP_WEIGHTS[prefix]}

    structured = np.hstack(structured_parts)
    semantic_embeddings = embed_texts(profiles["review_text"].astype(str).tolist())
    n_components = min(12, max(1, len(profiles) - 1), semantic_embeddings.shape[1])
    if len(profiles) >= 2:
        semantic = PCA(n_components=n_components, random_state=config.random_state).fit_transform(semantic_embeddings)
        semantic = StandardScaler().fit_transform(semantic)
    else:
        semantic = np.zeros((1, 1), dtype=float)
        n_components = 1
    semantic *= math.sqrt(config.semantic_share / max(n_components, 1))

    matrix = normalize(np.hstack([structured, semantic]), norm="l2")
    metadata = {
        "structured_meta": structured_meta,
        "semantic_components": n_components,
        "missing_rate": float(missing.to_numpy().mean()),
        "structured_share": config.structured_share,
        "semantic_share": config.semantic_share,
    }
    return matrix, metadata


def _canonicalize_labels(
    labels: np.ndarray,
    matrix: np.ndarray,
    review_ids: pd.Series,
) -> tuple[np.ndarray, dict[int, int]]:
    medoids = _cluster_medoid_indices(matrix, labels)
    old_labels = sorted(set(labels))
    ordered = sorted(
        old_labels,
        key=lambda label: (
            str(review_ids.iloc[medoids[int(label)]]),
            -int(np.sum(labels == label)),
        ),
    )
    mapping = {int(old): new for new, old in enumerate(ordered)}
    canonical = np.array([mapping[int(label)] for label in labels], dtype=int)
    return canonical, mapping


def _prototype_probabilities(
    matrix: np.ndarray,
    labels: np.ndarray,
    temperature: float,
) -> np.ndarray:
    clusters = sorted(set(labels))
    centroids = []
    for cluster in clusters:
        centroid = matrix[labels == cluster].mean(axis=0)
        centroid /= max(np.linalg.norm(centroid), 1e-12)
        centroids.append(centroid)
    logits = matrix @ np.vstack(centroids).T / max(temperature, 1e-6)
    logits -= logits.max(axis=1, keepdims=True)
    probabilities = np.exp(logits)
    return probabilities / probabilities.sum(axis=1, keepdims=True)


def _gmm_probabilities(
    matrix: np.ndarray,
    labels: np.ndarray,
    config: VisitorClusteringConfig,
) -> tuple[np.ndarray, str]:
    clusters = sorted(set(labels))
    k = len(clusters)
    if k == 1:
        return np.ones((len(matrix), 1)), "single_cluster"
    if len(matrix) < max(8, 3 * k):
        return (
            _prototype_probabilities(matrix, labels, config.softmax_temperature),
            "prototype_softmax",
        )
    try:
        gmm = GaussianMixture(
            n_components=k, covariance_type="diag", reg_covar=1e-4,
            n_init=config.gmm_n_init, random_state=config.random_state,
        )
        gmm.fit(matrix)
        raw = gmm.predict_proba(matrix)
        hdb_centroids = np.vstack(
            [matrix[labels == cluster].mean(axis=0) for cluster in clusters]
        )
        cost = np.linalg.norm(
            hdb_centroids[:, None, :] - gmm.means_[None, :, :], axis=2,
        )
        hdb_rows, gmm_cols = linear_sum_assignment(cost)
        aligned = np.zeros_like(raw)
        for hdb_index, gmm_index in zip(hdb_rows, gmm_cols):
            aligned[:, hdb_index] = raw[:, gmm_index]
        return aligned, "gmm_diag"
    except Exception:
        return (
            _prototype_probabilities(matrix, labels, config.softmax_temperature),
            "prototype_softmax_fallback",
        )


def cluster_visitor_patterns(
    profiles: pd.DataFrame,
    config: VisitorClusteringConfig | None = None,
    progress_cb=None,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, dict[str, Any]]:
    config = config or VisitorClusteringConfig()
    if profiles.empty:
        return profiles.copy(), pd.DataFrame(), np.empty((0, 0)), {}

    if progress_cb:
        progress_cb("clustering", 0, 1)

    matrix, metadata = build_visitor_matrix(profiles, config=config)
    n = len(profiles)
    if n == 1:
        labels = np.array([0], dtype=int)
    else:
        min_cluster_size = _adaptive_min_cluster_size(n)
        labels = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=max(1, min_cluster_size // 2),
            metric="euclidean",
            cluster_selection_method="eom",
            allow_single_cluster=True,
        ).fit_predict(matrix)
        labels = _absorb_or_split_noise(matrix, labels, absorb_threshold=0.78, noise_join_threshold=0.84)
        metadata["min_cluster_size"] = min_cluster_size

    labels, _ = _canonicalize_labels(labels, matrix, profiles["review_id"])
    probabilities, soft_method = _gmm_probabilities(matrix, labels, config)
    metadata["soft_membership_method"] = soft_method
    metadata["cluster_count"] = int(len(set(labels)))
    metadata["random_state"] = config.random_state

    assigned = profiles.copy()
    assigned["provisional_cluster_id"] = labels
    assigned["visitor_cluster_id"] = [f"C{label+1:03d}" for label in labels]
    assigned["hard_membership_probability"] = probabilities[np.arange(len(labels)), labels]

    membership_rows = []
    for row_index, review_id in enumerate(assigned["review_id"]):
        for cluster_index in range(probabilities.shape[1]):
            membership_rows.append({
                "review_id": review_id,
                "visitor_cluster_id": f"C{cluster_index+1:03d}",
                "membership_probability": float(probabilities[row_index, cluster_index]),
                "method": soft_method,
            })
    membership = pd.DataFrame(membership_rows)

    if progress_cb:
        progress_cb("clustering", 1, 1)

    return assigned, membership, matrix, metadata


def _feature_profile(
    group: pd.DataFrame,
    overall: pd.DataFrame,
    limit: int = 6,
) -> tuple[list[dict], list[dict]]:
    group_means = group[FEATURE_COLUMNS].mean(skipna=True)
    overall_means = overall[FEATURE_COLUMNS].mean(skipna=True)
    differences = (group_means - overall_means).dropna()
    high = []
    low = []
    for key in differences.sort_values(ascending=False).head(limit).index:
        high.append({
            "feature": FEATURE_LABELS.get(key, key),
            "cluster_mean": round(float(group_means[key]), 3),
            "overall_mean": round(float(overall_means[key]), 3),
            "difference": round(float(differences[key]), 3),
        })
    for key in differences.sort_values().head(limit).index:
        low.append({
            "feature": FEATURE_LABELS.get(key, key),
            "cluster_mean": round(float(group_means[key]), 3),
            "overall_mean": round(float(overall_means[key]), 3),
            "difference": round(float(differences[key]), 3),
        })
    return high, low


def name_visitor_pattern_clusters(
    assigned: pd.DataFrame,
    matrix: np.ndarray,
    progress_cb=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from .openai_service import name_visitor_clusters

    labels = assigned["provisional_cluster_id"].to_numpy(int)
    medoids = _cluster_medoid_indices(matrix, labels)
    naming_inputs = []
    for cluster_id, group in assigned.groupby("provisional_cluster_id", sort=True):
        high, low = _feature_profile(group, assigned)
        representative_index = medoids[int(cluster_id)]
        representative_reviews = (
            [str(assigned.iloc[representative_index]["review_text"])]
            + group["review_text"].astype(str).head(4).tolist()
        )
        naming_inputs.append({
            "provisional_cluster_id": int(cluster_id),
            "cluster_size": int(len(group)),
            "cluster_ratio": round(len(group) / len(assigned), 4),
            "top_features": high,
            "low_features": low,
            "mean_satisfaction": (
                None if group["overall_satisfaction"].dropna().empty
                else round(float(group["overall_satisfaction"].mean()), 3)
            ),
            "representative_reviews": list(dict.fromkeys(representative_reviews))[:5],
        })

    if progress_cb:
        progress_cb("cluster_naming", 0, 1)

    parsed = name_visitor_clusters(naming_inputs)
    names = pd.DataFrame(item.model_dump() for item in parsed.items)
    expected = set(assigned["provisional_cluster_id"].astype(int))
    returned = set(names["provisional_cluster_id"].astype(int))
    if expected != returned:
        raise ValueError(f"来場者クラスター命名IDが不一致です: expected={expected}, returned={returned}")

    names["visitor_cluster_id"] = names["provisional_cluster_id"].map(
        lambda value: f"C{int(value)+1:03d}"
    )
    output = assigned.merge(names, on=["provisional_cluster_id", "visitor_cluster_id"],
                            how="left", validate="many_to_one")
    summary = (
        output.groupby(
            ["visitor_cluster_id", "cluster_name", "main_traits",
             "likely_visit_context", "satisfaction_structure", "improvement_direction"],
            as_index=False, dropna=False,
        ).agg(
            review_count=("review_id", "nunique"),
            mean_satisfaction=("overall_satisfaction", "mean"),
            mean_membership=("hard_membership_probability", "mean"),
        )
    )
    summary["ratio"] = summary["review_count"] / len(output)

    if progress_cb:
        progress_cb("cluster_naming", 1, 1)

    return output, summary


def _weighted_mean_available(
    values: pd.Series,
    confidence: pd.Series,
) -> tuple[float | None, float]:
    numeric = pd.to_numeric(values, errors="coerce")
    mask = numeric.notna()
    if not mask.any():
        return None, 0.0
    weights = pd.to_numeric(confidence[mask], errors="coerce").fillna(0.5).clip(0.05, 1.0)
    mean = float(np.average(numeric[mask], weights=weights))
    coverage = float(mask.mean())
    return mean, coverage


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    if denominator <= 1e-12:
        return 0.0
    return float(np.dot(left, right) / denominator)


def calculate_vffi(
    profiles: pd.DataFrame,
    target_df: pd.DataFrame,
    nmsi_score: float,
    config: VFFIConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config = config or VFFIConfig()
    required = {"element", "feature_key", "target_value", "weight"}
    missing = required - set(target_df.columns)
    if missing:
        raise ValueError(f"施設目標データに必要な列がありません: {sorted(missing)}")

    target = target_df.copy()
    unknown = sorted(set(target["feature_key"]) - set(FEATURE_COLUMNS))
    if unknown:
        raise ValueError(f"未定義のfeature_keyがあります: {unknown}")
    target["target_value"] = pd.to_numeric(target["target_value"], errors="raise").clip(0, 1)
    target["weight"] = pd.to_numeric(target["weight"], errors="coerce").fillna(1.0).clip(lower=0)

    v_values = []
    coverages = []
    for feature_key in target["feature_key"]:
        value, coverage = _weighted_mean_available(
            profiles[feature_key], profiles["extraction_confidence"],
        )
        v_values.append(value)
        coverages.append(coverage)
    target["experience_value"] = v_values
    target["experience_value"] = pd.to_numeric(target["experience_value"], errors="coerce")
    target["coverage"] = coverages
    target["gap"] = target["experience_value"] - target["target_value"]

    def optional_text(row: pd.Series, column: str, fallback: str) -> str:
        value = row.get(column)
        if pd.notna(value) and str(value).strip():
            return str(value)
        return fallback

    def interpret(row: pd.Series) -> str:
        if pd.isna(row["experience_value"]):
            return "根拠不足"
        gap = float(row["gap"])
        if abs(gap) <= 0.05:
            return "高度に適合"
        if gap > 0.05:
            return optional_text(row, "positive_interpretation", "狙いを上回る")
        return optional_text(row, "negative_interpretation", "施設の狙いを下回る")

    target["interpretation"] = target.apply(interpret, axis=1)

    review_rows = []
    min_dimensions = max(3, math.ceil(len(target) * 0.30))
    for _, profile in profiles.iterrows():
        available = [
            index for index, feature_key in enumerate(target["feature_key"])
            if pd.notna(profile[feature_key])
        ]
        if len(available) < min_dimensions:
            fit = cosine = gap = None
        else:
            t = target.iloc[available]["target_value"].to_numpy(float)
            v = np.array([float(profile[target.iloc[index]["feature_key"]]) for index in available])
            cosine = _cosine(t, v)
            gap = float(np.mean(np.abs(v - t)))
            fit = float(np.clip(0.45 * cosine + 0.55 * (1.0 - gap), 0, 1))
        satisfaction = profile.get("overall_satisfaction")
        high_fit = fit is not None and fit >= config.fit_threshold
        high_satisfaction = pd.notna(satisfaction) and float(satisfaction) >= config.satisfaction_threshold
        if fit is None or pd.isna(satisfaction):
            quadrant = "判定保留"
        elif high_fit and high_satisfaction:
            quadrant = "高適合・高満足"
        elif high_fit:
            quadrant = "高適合・低満足"
        elif high_satisfaction:
            quadrant = "低適合・高満足"
        else:
            quadrant = "低適合・低満足"
        review_rows.append({
            "review_id": profile["review_id"],
            "visitor_cluster_id": profile.get("visitor_cluster_id"),
            "cluster_name": profile.get("cluster_name"),
            "fit": fit,
            "cosine_fit": cosine,
            "gap_mae": gap,
            "target_dimension_count": len(available),
            "satisfaction": satisfaction,
            "quadrant": quadrant,
        })
    review_fit = pd.DataFrame(review_rows)

    valid_reviews = review_fit["fit"].dropna()
    observed_target = target["experience_value"].notna()
    if not observed_target.any():
        raise ValueError("施設目標と対応する来場者体験値を抽出できませんでした。")

    weights = target.loc[observed_target, "weight"].to_numpy(float)
    weights = weights / max(weights.sum(), 1e-12)
    t_global = target.loc[observed_target, "target_value"].to_numpy(float)
    v_global = target.loc[observed_target, "experience_value"].to_numpy(float)
    cosine_global = _cosine(t_global * np.sqrt(weights), v_global * np.sqrt(weights))
    gap_global = float(np.sum(weights * np.abs(v_global - t_global)))
    coverage_global = float(np.sum(weights * target.loc[observed_target, "coverage"].to_numpy(float)))
    magnitude_fit = float(np.clip(1.0 - gap_global, 0, 1))

    if valid_reviews.empty:
        matching_rate = float(np.clip(0.45 * cosine_global + 0.55 * magnitude_fit, 0, 1))
    else:
        matching_rate = float((valid_reviews >= config.fit_threshold).mean())
    satisfaction_s = float(np.clip(nmsi_score / 100.0, 0, 1))

    # VFFI = 100 * clip(0.30*Q + 0.25*S + 0.45*C - 0.90*G, 0, 1)
    raw_vffi = (
        config.matching_weight * matching_rate
        + config.satisfaction_weight * satisfaction_s
        + config.cosine_weight * cosine_global
        - config.gap_penalty * gap_global
    )
    vffi = float(100 * np.clip(raw_vffi, 0, 1))

    if vffi >= 85:
        interpretation = "狙いと来場者が高度に一致"
    elif vffi >= 70:
        interpretation = "良好な適合"
    elif vffi >= 55:
        interpretation = "部分適合"
    elif vffi >= 40:
        interpretation = "ミスマッチが大きい"
    else:
        interpretation = "集客・体験設計の再設計が必要"

    summary: dict[str, Any] = {
        "VFFI": round(vffi, 1),
        "解釈": interpretation,
        "MatchingRate": round(matching_rate, 4),
        "Satisfaction": round(satisfaction_s, 4),
        "GlobalCosineFit": round(cosine_global, 4),
        "WeightedGap": round(gap_global, 4),
        "TargetCoverage": round(coverage_global, 4),
        "FitThreshold": config.fit_threshold,
        "SatisfactionThreshold": config.satisfaction_threshold,
        "valid_review_count": int(valid_reviews.size),
        "all_review_count": int(len(profiles)),
    }
    return target, review_fit, summary


def build_quadrant_summary(review_fit: pd.DataFrame) -> pd.DataFrame:
    if review_fit.empty:
        return pd.DataFrame()
    return (
        review_fit.groupby(["quadrant", "cluster_name"], dropna=False, as_index=False)
        .agg(review_count=("review_id", "nunique"), mean_fit=("fit", "mean"),
             mean_satisfaction=("satisfaction", "mean"))
        .sort_values(["quadrant", "review_count"], ascending=[True, False])
    )


def run_visitor_vffi_pipeline(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    nmsi_score: float,
    batch_size: int = 10,
    clustering_config: VisitorClusteringConfig | None = None,
    vffi_config: VFFIConfig | None = None,
    progress_cb=None,
) -> dict[str, Any]:
    profiles = extract_visitor_profiles(source_df, batch_size=batch_size,
                                        progress_cb=progress_cb)
    assigned, membership, matrix, clustering_meta = cluster_visitor_patterns(
        profiles, config=clustering_config, progress_cb=progress_cb,
    )
    named_profiles, cluster_summary = name_visitor_pattern_clusters(
        assigned, matrix, progress_cb=progress_cb,
    )
    element_table, review_fit, vffi = calculate_vffi(
        named_profiles, target_df, nmsi_score=nmsi_score, config=vffi_config,
    )
    quadrant_summary = build_quadrant_summary(review_fit)
    if not cluster_summary.empty and not review_fit.empty:
        cluster_fit = (
            review_fit.groupby("visitor_cluster_id", as_index=False)
            .agg(cluster_fit=("fit", "mean"), cluster_satisfaction=("satisfaction", "mean"))
        )
        cluster_summary = cluster_summary.merge(
            cluster_fit, on="visitor_cluster_id", how="left", validate="one_to_one",
        )
    return {
        "visitor_profiles": named_profiles,
        "cluster_membership": membership,
        "visitor_cluster_summary": cluster_summary,
        "vffi_elements": element_table,
        "review_fit": review_fit,
        "quadrant_summary": quadrant_summary,
        "vffi": vffi,
        "clustering_metadata": clustering_meta,
    }
