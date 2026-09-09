"""VoiceBAUM から NMSI を実行する入口。

移植元は Postgres 直結の CLI（run_nmsi.py）だった。ここが置き換え。

**この関数は課金される。** 文ごとに LLM を呼ぶので、口コミが多い施設ほど
素直に費用が増える。だから:
  - 走らせる前に plan() で回数を出せるようにしてある
  - 結果は nmsi_result に保存し、口コミ件数が増えるまで再計算しない
    （移植元にはキャッシュが無く、開き直すたびに課金されていた）
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import source


def model_name() -> str:
    return os.getenv("OPENAI_TEXT_MODEL", "gpt-4o")


def api_key() -> str:
    return (os.getenv("OPENAI_API_KEY")
            or os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY") or "")


@dataclass
class Plan:
    """走らせる前に見せる見積り。"""
    facility: str
    n_reviews: int
    n_sentences: int
    llm_calls: int
    model: str
    cached: bool          # すでに結果があり、課金なしで出せる
    ready: bool           # 鍵があって実行できる
    reason: str = ""


def plan(conn, facility_name: str) -> Plan:
    df = source.sentence_frame(conn, facility_name)
    n_sent = len(df)
    n_rev = int(df["review_id"].nunique()) if n_sent else 0
    cached = get_result(conn, facility_name) is not None
    key = bool(api_key())
    if not n_sent:
        reason = "本文のある口コミがありません。"
    elif not key and not cached:
        reason = "OPENAI_API_KEY が未設定です。"
    else:
        reason = ""
    return Plan(
        facility=facility_name, n_reviews=n_rev, n_sentences=n_sent,
        llm_calls=source.estimate_llm_calls(n_sent), model=model_name(),
        cached=cached, ready=bool(n_sent) and (cached or key), reason=reason,
    )


def _facility_id(conn, name: str):
    row = conn.execute("SELECT id FROM facility WHERE name = ?", (name,)).fetchone()
    if row is None:
        return None
    return row["id"] if not isinstance(row, tuple) else row[0]


def get_result(conn, facility_name: str) -> dict | None:
    """保存済みの結果。口コミ件数とモデルが一致するものだけ返す。"""
    fid = _facility_id(conn, facility_name)
    if fid is None:
        return None
    n_rev = conn.execute(
        "SELECT COUNT(*) FROM review WHERE facility_id = ? "
        "AND text IS NOT NULL AND TRIM(text) != ''", (fid,)).fetchone()
    n_rev = n_rev[0] if isinstance(n_rev, tuple) else n_rev[0]
    row = conn.execute(
        "SELECT nmsi, interpretation, summary_json, phase_json, n_sentences, "
        "llm_calls, created_at FROM nmsi_result "
        "WHERE facility_id = ? AND n_reviews = ? AND model = ?",
        (fid, n_rev, model_name()),
    ).fetchone()
    if row is None:
        return None
    g = (lambda k, i: row[k] if not isinstance(row, tuple) else row[i])
    return {
        "nmsi": g("nmsi", 0),
        "interpretation": g("interpretation", 1),
        "summary": json.loads(g("summary_json", 2) or "{}"),
        "phases": json.loads(g("phase_json", 3) or "[]"),
        "n_sentences": g("n_sentences", 4),
        "llm_calls": g("llm_calls", 5),
        "created_at": g("created_at", 6),
    }


def save_result(conn, facility_name: str, summary: dict, phases: list,
                *, n_sentences: int, llm_calls: int) -> None:
    fid = _facility_id(conn, facility_name)
    if fid is None:
        return
    n_rev = conn.execute(
        "SELECT COUNT(*) FROM review WHERE facility_id = ? "
        "AND text IS NOT NULL AND TRIM(text) != ''", (fid,)).fetchone()
    n_rev = n_rev[0] if isinstance(n_rev, tuple) else n_rev[0]
    conn.execute(
        "INSERT OR REPLACE INTO nmsi_result"
        "(facility_id, n_reviews, model, nmsi, interpretation, summary_json,"
        " phase_json, n_sentences, llm_calls) VALUES (?,?,?,?,?,?,?,?,?)",
        (fid, n_rev, model_name(), float(summary.get("NMSI", 0.0)),
         str(summary.get("解釈", "")),
         json.dumps(summary, ensure_ascii=False),
         json.dumps(phases, ensure_ascii=False),
         int(n_sentences), int(llm_calls)),
    )
    conn.commit()


def analyze(conn, facility_name: str, *, force: bool = False,
            progress_cb=None) -> dict:
    """NMSI を出す。保存済みがあればそれを返す（課金しない）。

    force=True で作り直す。モデルを変えたときは鍵が変わるので自動で再計算。
    """
    if not force:
        hit = get_result(conn, facility_name)
        if hit is not None:
            hit["from_cache"] = True
            return hit

    from .pipeline import analyze_sentences, calculate_nmsi  # noqa: PLC0415

    df = source.sentence_frame(conn, facility_name)
    if df.empty:
        raise ValueError(f"「{facility_name}」に本文のある口コミがありません。")

    analysis_df, _mentions = analyze_sentences(df, progress_cb=progress_cb)
    phase_table, summary = calculate_nmsi(analysis_df)
    phases = phase_table.to_dict(orient="records")
    calls = source.estimate_llm_calls(len(df))
    save_result(conn, facility_name, summary, phases,
                n_sentences=len(df), llm_calls=calls)
    return {
        "nmsi": summary.get("NMSI"),
        "interpretation": summary.get("解釈", ""),
        "summary": summary, "phases": phases,
        "n_sentences": len(df), "llm_calls": calls, "from_cache": False,
    }
