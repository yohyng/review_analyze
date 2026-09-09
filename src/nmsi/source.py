"""VoiceBAUM の DB から、NMSI/VFFI パイプラインの入力を作る。

移植元は PostgreSQL の kaizode_reviews を直接読んでいた（run_nmsi.py）。
VoiceBAUM は Turso/SQLite なので、ここで同じ形の DataFrame を作る。

pipeline.analyze_sentences が要求する列は review_id と sentence。
rating は calculate_nmsi が星評価を 15% 混ぜるのに使う（任意）。
"""
from __future__ import annotations

import re

import pandas as pd

# 移植元 run_nmsi.py:28 と同じ分割。VoiceBAUM の topic_score._sentences とは
# 別物なので注意（あちらは3文字未満を落とさない）。指標の定義が変わるため、
# 移植元の挙動に合わせてある。
_SPLIT = re.compile(r"[。！？\n]+")
MIN_CHARS = 3


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SPLIT.split((text or "").strip())]
    parts = [p for p in parts if len(p) >= MIN_CHARS]
    return parts or ([text.strip()] if (text or "").strip() else [])


def sentence_frame(conn, facility_name: str) -> pd.DataFrame:
    """施設の口コミを1文1行の DataFrame にする。

    列: review_id / sentence / rating
    本文が空の口コミは落とす（文が作れないため）。
    """
    rows = conn.execute(
        """
        SELECT r.review_id, r.text, r.rating
        FROM review r
        JOIN facility f ON f.id = r.facility_id
        WHERE f.name = ? AND r.text IS NOT NULL AND TRIM(r.text) != ''
        ORDER BY r.id
        """,
        (facility_name,),
    ).fetchall()

    out = []
    for row in rows:
        rid = row["review_id"] if not isinstance(row, tuple) else row[0]
        text = row["text"] if not isinstance(row, tuple) else row[1]
        rating = row["rating"] if not isinstance(row, tuple) else row[2]
        try:
            rating_val = float(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating_val = None
        for sent in split_sentences(text):
            out.append({"review_id": str(rid), "sentence": sent,
                        "rating": rating_val})

    return pd.DataFrame(out, columns=["review_id", "sentence", "rating"])


def estimate_llm_calls(n_sentences: int, batch_size: int = 20) -> int:
    """文の数から LLM 呼び出し回数を出す。実行前に見積りを出すため。

    NMSI は文ごとに16項目を付けさせるので、口コミが多い施設ほど素直に
    比例して費用が増える。黙って走らせない。
    """
    return -(-max(n_sentences, 0) // max(batch_size, 1))
