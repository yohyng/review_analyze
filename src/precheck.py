"""KAIZODE に発注する前の確認項目。

**発注は取り消せない**。しかも解析が終われば取り込みで月の枠を減らす。
そこで「施設名を入れたら即発注」ではなく、

    1. 施設名を入れる
    2. Google 上で候補を検索する
    3. 候補を（口コミ数つきで）見せる
    4. これでいい、と決めてから集める

の 3→4 の境目に置く確認がこれ。判定だけをここに置き、
画面の描き方は UI 側に任せる（そうしないとテストが書けない）。

判定は2段階ある:
  blocking …… 押させない。枠が足りないなど、やれば確実に破綻するもの。
  warn     …… 押させるが赤字で出す。取り違えの可能性など、人しか判断できないもの。

**推測で件数を埋めないこと**。Google が件数を返さなかった場合は
「不明」のまま warn にする。0件と決めつけると、枠の判定が嘘になる。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Google 上の件数に対して、KAIZODE が実際に拾える割合の目安。
# 実測（46施設）で 0.6〜0.9 に散った。下振れ側に倒して見積もる。
EXPECT_RATIO = 0.9

# 残枠のうち、これを超えて食うなら警告する。
QUOTA_WARN_RATIO = 0.5

# これ未満なら「分析に足りない」と見なす件数（信頼区間が広くなりすぎる）。
THIN_REVIEWS = 30


@dataclass
class Check:
    key: str
    label: str
    ok: bool
    detail: str = ""
    blocking: bool = False      # ok=False のとき、発注を止めるか


@dataclass
class Preflight:
    checks: list = field(default_factory=list)
    expected: int | None = None     # 取り込みで使いそうな件数（不明は None）
    remaining: int = 0
    limit: int = 0

    @property
    def blocked(self) -> bool:
        return any((not c.ok) and c.blocking for c in self.checks)

    @property
    def warnings(self) -> list:
        return [c for c in self.checks if not c.ok and not c.blocking]

    @property
    def after(self) -> int | None:
        """発注して取り込んだあとの残枠の見込み。不明なら None。"""
        if self.expected is None:
            return None
        return max(0, self.remaining - self.expected)


def expected_reviews(review_count: int | None) -> int | None:
    """Google 上の件数から、KAIZODE が拾えそうな件数を見積もる。

    None（件数不明）を 0 に潰さないこと。枠の判定が嘘になる。
    """
    if review_count is None:
        return None
    return int(max(0, review_count) * EXPECT_RATIO)


def build(*, facility: str, place_id: str = "", review_count: int | None = None,
          remaining: int = 0, limit: int = 0, already: int = 0,
          existing_datasets: list | None = None) -> Preflight:
    """発注前の確認項目を組み立てる。

    facility          … これから集める施設名
    place_id          … Google 上で1件に特定できていれば非空
    review_count      … Google 上の口コミ数（不明なら None）
    remaining / limit … 今月の KAIZODE 残枠と上限
    already           … その施設について DB に既にある口コミ数
    existing_datasets … KAIZODE 側に既にある同名の収集
    """
    exp = expected_reviews(review_count)
    pf = Preflight(expected=exp, remaining=int(remaining), limit=int(limit))
    add = pf.checks.append

    # ── 1. 施設が1件に特定できているか ───────────────────────── #
    add(Check(
        "identity", "施設が特定できている",
        ok=bool(place_id),
        detail=("Google マップ上の1件を指しています"
                if place_id else
                "名前での検索になります。同名の別施設・別館を拾う可能性があります"),
    ))

    # ── 2. 口コミ数が分かっているか ─────────────────────────── #
    if review_count is None:
        add(Check("volume", "口コミ数が分かっている", ok=False,
                  detail="Google から件数を取得できませんでした。"
                         "何件消費するか読めません"))
    elif review_count < THIN_REVIEWS:
        add(Check("volume", "分析に足りる件数がある", ok=False,
                  detail=f"Google 上で {review_count:,} 件。"
                         f"{THIN_REVIEWS} 件未満は信頼区間が広くなり、"
                         f"傾向として読めません"))
    else:
        add(Check("volume", "分析に足りる件数がある", ok=True,
                  detail=f"Google 上で {review_count:,} 件"
                         f"（KAIZODE で拾えるのは概ね {exp:,} 件）"))

    # ── 3. 今月の枠に収まるか ──────────────────────────────── #
    if exp is None:
        add(Check("quota", "今月の枠に収まる", ok=False,
                  detail=f"件数が読めないため判定できません（残枠 {pf.remaining:,} 件）"))
    elif exp > pf.remaining:
        add(Check("quota", "今月の枠に収まる", ok=False, blocking=True,
                  detail=f"見込み {exp:,} 件に対して残枠 {pf.remaining:,} 件。"
                         f"途中で止まります"))
    elif pf.remaining and exp > pf.remaining * QUOTA_WARN_RATIO:
        add(Check("quota", "今月の枠に収まる", ok=False,
                  detail=f"残枠 {pf.remaining:,} 件のうち {exp:,} 件を使います"
                         f"（残り {pf.after:,} 件）"))
    else:
        add(Check("quota", "今月の枠に収まる", ok=True,
                  detail=f"残枠 {pf.remaining:,} 件 → {pf.after:,} 件になる見込み"))

    # ── 4. 二重に集めようとしていないか ─────────────────────── #
    if already > 0:
        add(Check("duplicate", "まだ集めていない施設", ok=False,
                  detail=f"この施設には既に {already:,} 件あります。"
                         f"差分だけが増えます"))
    _ds = existing_datasets or []
    if _ds:
        add(Check("dataset", "KAIZODE に同じ収集が無い", ok=False,
                  detail="KAIZODE 側に同じ名前の収集があります（"
                         + "／".join(str(d) for d in _ds[:3])
                         + "）。二重発注になるかもしれません"))

    return pf
