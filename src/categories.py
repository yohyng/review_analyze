"""評価軸のカテゴリ分類と、カテゴリ単位の集計。

**原典は利用部門の「20261116 評価軸一覧」**（2026-11-26 受領）。25 軸が
この 7 カテゴリに分類されている。軸名・定義・重みは原典のまま
（`topic_score.DEFAULT_TOPICS`）。

2026-11-15 のデッキの指示:

    「ここは評価軸のカテゴリごとの評価順位と要約が欲しい。
      コンテンツ 空間設計 サービス 価格・決済 アクセス ブランド 総合評価」

**順位の母数に注意**。カテゴリ平均は「そのカテゴリに属する軸の単純平均」で、
軸の重み（TopicDef.weight）は使っていない。重みはトピック単位の総合スコア用で、
カテゴリ内の相対評価に持ち込むと、軸が1本しかないカテゴリ（アクセス）と
7本あるカテゴリ（コンテンツ）で意味が変わるため。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# カテゴリ → 属する評価軸。順序は資料の並びに合わせる。
CATEGORIES: dict[str, tuple[str, ...]] = {
    "コンテンツ": (
        "品質", "多様性", "独自性", "最新性", "更新性", "情報性", "分かりやすさ",
    ),
    "空間設計": (
        "レイアウト", "機能性", "快適さ", "デザインクオリティ", "雰囲気",
        "インパクト",
    ),
    "サービス": ("スタッフ対応", "スタッフ専門性", "サービス種類"),
    "価格・決済": ("料金の適正さ", "料金・決済のサービス多様性"),
    "アクセス": ("アクセスの利便性",),
    "ブランド": ("信頼度", "ロイヤリティ"),
    "総合評価": ("体験満足度", "比較優位性", "推奨意向", "再訪意向"),
}

ORDER: tuple[str, ...] = tuple(CATEGORIES)


def category_of(topic: str) -> Optional[str]:
    """軸 → カテゴリ。知らない軸は None。"""
    for cat, members in CATEGORIES.items():
        if topic in members:
            return cat
    return None


@dataclass
class CategoryScore:
    name: str
    score: Optional[float] = None       # 0-100。属する軸の単純平均
    rank: Optional[int] = None          # 比較母集団での順位
    total: Optional[int] = None         # 比較母集団の施設数
    n_axes: int = 0                     # 実際に値があった軸の数
    axes: list = field(default_factory=list)   # [(軸名, スコア), ...]

    @property
    def computable(self) -> bool:
        return self.score is not None

    @property
    def standing(self) -> str:
        """順位の言い換え。母数が分からないときは空。"""
        if not (self.rank and self.total):
            return ""
        if self.rank == 1:
            return "最上位"
        if self.rank == self.total:
            return "最下位"
        if self.rank <= max(1, self.total // 3):
            return "上位"
        if self.rank > self.total - max(1, self.total // 3):
            return "下位"
        return "中位"


def _mean(vals: list) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def score_one(topic_values: dict) -> dict:
    """{軸: 0-100} → {カテゴリ: 平均}。値の無い軸は平均から外す。"""
    out = {}
    for cat, members in CATEGORIES.items():
        out[cat] = _mean([topic_values.get(m) for m in members])
    return out


def assess(target: str, matrix: dict) -> list:
    """施設ごとの軸スコアから、対象施設のカテゴリ別スコアと順位を出す。

    matrix は {施設名: {軸: 0-100}}。対象施設が入っていなければ空を返す。
    順位は **そのカテゴリの値を持つ施設だけ** を母数にする。値の無い施設を
    母数に含めると、順位が実際より良く見える。
    """
    if target not in matrix:
        return []
    per_fac = {name: score_one(vals) for name, vals in matrix.items()}
    mine = per_fac[target]

    out = []
    for cat in ORDER:
        members = CATEGORIES[cat]
        axes = [(m, matrix[target].get(m)) for m in members
                if matrix[target].get(m) is not None]
        row = CategoryScore(name=cat, score=mine.get(cat),
                            n_axes=len(axes), axes=axes)
        if row.score is not None:
            ranked = sorted(
                (v[cat] for v in per_fac.values() if v.get(cat) is not None),
                reverse=True)
            row.total = len(ranked)
            # 同点は上位の順位に揃える（1位タイが2位にならないように）
            row.rank = next(i + 1 for i, v in enumerate(ranked)
                            if v <= row.score + 1e-9)
        out.append(row)
    return out


def facts_for_prompt(rows: list) -> list:
    """LLM に渡す形。**HTMLも体裁も渡さない。**"""
    return [
        {
            "カテゴリ": r.name,
            "スコア": round(r.score, 1) if r.score is not None else None,
            "順位": r.rank, "比較施設数": r.total,
            "位置": r.standing,
            "評価軸": [{"軸": a, "スコア": round(v, 1)} for a, v in r.axes],
        }
        for r in rows
    ]
