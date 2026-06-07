"""Deterministic quantitative scoring from review text (PLACEHOLDER).

完全に決定論的：辞書マッチ + 星評価 + TF-IDF のみ（乱数・LLM不使用）。
同じ入力に対して常に同じ数値を返す（何度分析しても再現する）。

⚠️ これは「仮」の定量化ロジックです。後で実データ／本番の定量化指標
（BERT埋め込みや独自Excel指標）に差し替える前提で、インターフェース
（compute_axis_scores / compute_tfidf_emphasis）を固定してあります。

2系統の評価を出します：
  1. compute_axis_scores      複数軸の満足度（0-100）= 星評価 × 感情辞書
  2. compute_tfidf_emphasis   各テーマの「語られ度」（0-100）= TF-IDF重み
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from . import text_analysis

# テーマ軸 → キーワード辞書（仮。後で業種別に差し替え可能）
AXES: dict[str, list[str]] = {
    "接客・サービス": ["スタッフ", "接客", "対応", "親切", "丁寧", "従業員", "店員",
                  "サービス", "態度", "気配り", "心遣い", "笑顔", "おもてなし"],
    "清潔感": ["清潔", "きれい", "綺麗", "掃除", "衛生", "汚い", "汚れ", "ほこり",
            "臭い", "におい", "ピカピカ"],
    "食事・料理": ["食事", "料理", "美味", "おいし", "まずい", "味", "朝食", "夕食",
              "ボリューム", "品数", "食材", "グルメ", "ランチ", "ディナー"],
    "設備・部屋": ["設備", "部屋", "客室", "風呂", "温泉", "ベッド", "古い", "新しい",
              "広い", "狭い", "アメニティ", "空調", "館内", "施設"],
    "立地・アクセス": ["立地", "アクセス", "駅", "場所", "便利", "近い", "遠い", "景色",
                 "眺め", "ロケーション", "周辺", "駐車場", "観光"],
    "コスパ": ["価格", "料金", "値段", "コスパ", "高い", "安い", "リーズナブル",
            "お得", "割高", "コストパフォーマンス"],
}

POSITIVE = ["良い", "よい", "最高", "素晴らし", "満足", "おすすめ", "快適", "丁寧",
            "美味", "きれい", "綺麗", "便利", "親切", "嬉し", "感動", "良かっ",
            "また来", "また行", "また利用", "大満足", "おもてなし", "清潔"]
NEGATIVE = ["悪い", "残念", "不満", "最悪", "がっかり", "汚い", "狭い", "遅い",
            "まずい", "古い", "不親切", "二度と", "ひどい", "期待外れ", "微妙",
            "うるさい", "臭い", "割高", "雑"]

DEFAULT_SCALE = 100.0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _sentiment(texts: list[str]) -> float:
    """Net sentiment of a set of texts, in [-1, 1]. Deterministic."""
    pos = sum(t.count(w) for t in texts for w in POSITIVE)
    neg = sum(t.count(w) for t in texts for w in NEGATIVE)
    total = pos + neg
    return (pos - neg) / total if total else 0.0


# --------------------------------------------------------------------------- #
# 1) multi-axis satisfaction score
# --------------------------------------------------------------------------- #
def compute_axis_scores(reviews: list[tuple[float | None, str]]) -> dict[str, float]:
    """reviews = [(rating, text), ...] -> {axis: score 0-100}. Deterministic.

    score = 70% 星評価ベース + 30% 感情辞書ベース（その軸に言及した口コミのみ）.
    """
    out: dict[str, float] = {}

    ratings = [r for r, _ in reviews if r is not None]
    if ratings:
        out["総合満足度"] = round(sum(ratings) / len(ratings) / 5 * 100, 1)

    for axis, kws in AXES.items():
        rel = [(r, t) for r, t in reviews if any(k in t for k in kws)]
        if not rel:
            continue
        rs = [r for r, _ in rel if r is not None]
        star_base = (sum(rs) / len(rs) / 5 * 100) if rs else 50.0
        senti = _sentiment([t for _, t in rel])
        senti_base = 50.0 + senti * 50.0          # -1..1 -> 0..100
        out[axis] = round(_clamp(star_base * 0.7 + senti_base * 0.3), 1)

    return out


# --------------------------------------------------------------------------- #
# 2) TF-IDF emphasis ("how much is each theme talked about")
# --------------------------------------------------------------------------- #
def compute_tfidf_emphasis(
    reviews: list[tuple[float | None, str]]
) -> dict[str, float]:
    """{axis: emphasis 0-100} from how strongly each theme's keywords appear.

    Uses term frequency over tokenized reviews (deterministic). Scaled so the
    most-discussed theme = 100.
    """
    tokens: list[str] = []
    for _, text in reviews:
        tokens.extend(text_analysis.tokenize(text))
    if not tokens:
        return {}

    total = len(tokens)
    raw: dict[str, float] = {}
    for axis, kws in AXES.items():
        hits = sum(tokens.count(k) for k in kws)
        # also count substring presence in original text for kana/inflections
        substr = sum(
            1 for _, t in reviews if any(k in t for k in kws)
        )
        raw[axis] = (hits / total) * 100 + (substr / max(len(reviews), 1)) * 20

    mx = max(raw.values()) if raw else 0
    if mx <= 0:
        return {a: 0.0 for a in raw}
    return {a: round(v / mx * 100, 1) for a, v in raw.items()}


# --------------------------------------------------------------------------- #
# DB integration — store as source='auto' so existing comparison/report
# flows light up even without an Excel upload.
# --------------------------------------------------------------------------- #
def compute_and_store(conn: sqlite3.Connection, facility_id: int) -> int:
    """Compute deterministic axis scores for a facility and upsert them
    into `score` with source='auto'. Returns the number of axes written."""
    from . import db  # local import to avoid circular dependency

    rows = conn.execute(
        """SELECT rating, text FROM review
           WHERE facility_id = ? AND text IS NOT NULL AND text != ''""",
        (facility_id,),
    ).fetchall()
    reviews = [(float(r["rating"]) if r["rating"] is not None else None, r["text"])
               for r in rows]
    if not reviews:
        return 0

    scores = compute_axis_scores(reviews)
    return db.upsert_scores(conn, facility_id, scores, scale=DEFAULT_SCALE,
                            source="auto")
