"""SLIDE 6「特徴的な口コミ」— 4象限に載せる代表口コミの選定。

引用は**必ず実在の口コミの逐語**でなければならない。LLM には「どの口コミを
どの象限に置くか」と「属性の推定」だけを任せ、返ってきた引用が実際にその
口コミに含まれるかを必ず検証する（含まれなければ元本文で置き換える）。
LLM が使えないときは、キーワードと星評価だけで決定論的に選ぶ。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 4象限の定義。順序は PDF の並び（左上→右上→左下→右下）。
QUADRANTS = [
    ("維持すべき価値", "高く評価されていて、今後も維持すべき体験価値"),
    ("重大な不満", "放置すると来場体験を損なう、はっきりした不満"),
    ("潜在的なニーズ", "まだ提供できていないが、求められている要素"),
    ("未来の企画につながる声", "次の企画・施策のヒントになる前向きな要望"),
]

# LLM を使わないときの選定キーワード
_WANT = ("ほしい", "欲しい", "あれば", "できたら", "してほしい", "願わくば",
         "あったら", "望む", "不足")
_FUTURE = ("もっと", "増え", "次は", "また来", "また行", "期待", "楽しみ",
           "今後", "リピート")


@dataclass
class Voice:
    quadrant: str
    quote: str = ""
    age: str = ""            # 「40代」など。推定できなければ空
    gender: str = ""         # 「女性」など
    companion: str = ""      # 「ファミリー」など
    rating: int | None = None
    estimated: bool = False  # 属性が LLM 推定かどうか

    @property
    def chips(self) -> list[str]:
        who = "・".join(x for x in (self.age, self.gender) if x)
        return [x for x in (who, self.companion) if x]


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _clip(s: str, n: int = 70) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def pick_fallback(reviews: list[tuple]) -> list[Voice]:
    """LLM 無しで4象限を選ぶ。星評価とキーワードだけの決定論的な選定。

    属性（年代・性別・同行者）は口コミからは分からないので付けない。
    """
    usable = [(r, t.strip()) for r, t in reviews if t and t.strip()]
    if not usable:
        return [Voice(quadrant=q) for q, _ in QUADRANTS]

    used: set[str] = set()

    def best(pred, allow_any: bool = False):
        """条件に合い、まだ使っていない口コミのうち最も長いもの。"""
        pool = [x for x in usable if x[1] not in used and pred(x)]
        if not pool and allow_any:
            pool = [x for x in usable if x[1] not in used]
        if not pool:
            return None
        pick = max(pool, key=lambda x: len(x[1]))
        used.add(pick[1])
        return pick

    # 同じ口コミを複数の象限に出さない（used で除外していく）
    picks = [
        best(lambda x: (x[0] or 0) >= 4, allow_any=True),
        best(lambda x: (x[0] or 5) <= 3),
        best(lambda x: any(w in x[1] for w in _WANT)),
        best(lambda x: any(w in x[1] for w in _FUTURE)),
    ]

    return [
        Voice(quadrant=name, quote=_clip(src[1]) if src else "",
              rating=src[0] if src else None)
        for (name, _desc), src in zip(QUADRANTS, picks)
    ]


def apply_llm_result(reviews: list[tuple], data: list) -> list[Voice] | None:
    """LLM の返り値を Voice に変換する。引用の実在を検証する。

    data は [{"index": int, "quote": str, "age": str, "gender": str,
              "companion": str}, ...] を想定（4件・象限の順）。
    引用がその口コミに含まれていなければ、口コミ本文そのもので置き換える。
    形式が壊れていれば None を返し、呼び出し側で fallback に落とす。
    """
    if not isinstance(data, list) or len(data) != len(QUADRANTS):
        return None

    out = []
    for (name, _desc), item in zip(QUADRANTS, data):
        if not isinstance(item, dict):
            return None
        try:
            idx = int(item.get("index", -1))
        except (TypeError, ValueError):
            idx = -1
        if not (0 <= idx < len(reviews)):
            out.append(Voice(quadrant=name))
            continue

        rating, text = reviews[idx]
        quote = str(item.get("quote", "")).strip()
        # 生成された引用が本文に無ければ、捏造なので本文で置き換える
        if not quote or _norm(quote) not in _norm(text):
            quote = text
        out.append(Voice(
            quadrant=name, quote=_clip(quote), rating=rating,
            age=str(item.get("age", "") or "").strip(),
            gender=str(item.get("gender", "") or "").strip(),
            companion=str(item.get("companion", "") or "").strip(),
            estimated=True,
        ))
    return out
