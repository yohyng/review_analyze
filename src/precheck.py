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
    exact: bool = False             # expected が確定値か（KAIZODE に聞けた）
    remaining: int = 0
    limit: int = 0

    @property
    def volume_note(self) -> str:
        """件数の横に出す但し書き。確定と概算を**必ず区別する**。

        枠を使うかどうかの判断なので、0.9 を掛けた見積もりを確定値の顔で
        出してはいけない。
        """
        if self.expected is None:
            return "件数不明"
        return "確定" if self.exact else "概算"

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
          existing_datasets: list | None = None,
          known_count: int | None = None) -> Preflight:
    """発注前の確認項目を組み立てる。

    facility          … これから集める施設名
    place_id          … Google 上で1件に特定できていれば非空
    review_count      … Google 上の口コミ数（不明なら None）
    remaining / limit … 今月の KAIZODE 残枠と上限
    already           … その施設について DB に既にある口コミ数
    existing_datasets … KAIZODE 側に既にある同名の収集
    known_count       … KAIZODE に直接聞けた**確定**件数（聞けなければ None）

    known_count があるときは Google からの見積もりを使わない。
    EXPECT_RATIO を掛けた概算より、KAIZODE が「これだけ持っている」と
    答えた数のほうが正しい。
    """
    exact = known_count is not None
    exp = (max(0, int(known_count)) if exact
           else expected_reviews(review_count))
    pf = Preflight(expected=exp, exact=exact,
                   remaining=int(remaining), limit=int(limit))
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
    if exact:
        # KAIZODE に既にあるぶんを直接数えた。Google の件数は参考に留める。
        add(Check("volume", "分析に足りる件数がある",
                  ok=exp >= THIN_REVIEWS,
                  detail=(f"KAIZODE 側に {exp:,} 件（確定）"
                          if exp >= THIN_REVIEWS else
                          f"KAIZODE 側に {exp:,} 件（確定）。"
                          f"{THIN_REVIEWS} 件未満は信頼区間が広くなり、"
                          f"傾向として読めません")))
    elif review_count is None:
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
                  detail=f"残枠 {pf.remaining:,} 件 → {pf.after:,} 件になる"
                         + ("" if exact else "見込み")))

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


# ── 取り直すと増えそうか（2026-11-26） ───────────────────────────── #
# KAIZODE の収集は、収集した時点の写し。Google 側ではその後も口コミが
# 増えるが、**増えた件数を取り直す前に正確に知る方法は無い**（Google は
# 今の総数しか返さない）。ここで出すのは目安。取り直した後の確定値は
# UI 側が「取り直す前の件数」と「後の件数」の差で出す。
REFRESH_MIN_GAP = 30          # これ未満の差は誤差として扱う
REFRESH_MIN_RATIO = 0.05      # 既存件数の 5% 未満の差も誤差として扱う


def extra_estimate(google_count: int | None, known_count: int | None) -> int | None:
    """取り直すと増えそうな件数の目安。出せないときは None。

    Google の総数に EXPECT_RATIO を掛けた見込みから、KAIZODE が今持って
    いる件数を引く。Google の総数には本文の無い星だけの評価も入るので、
    **目安以上のものとして扱わないこと**。負になったら 0。
    """
    if google_count is None or known_count is None:
        return None
    return max(0, int(google_count * EXPECT_RATIO) - int(known_count))


def worth_refresh(extra: int | None, known_count: int | None) -> bool:
    """目安の差が、誤差と言えない大きさか。"""
    if not extra or known_count is None:
        return False
    return extra >= max(REFRESH_MIN_GAP, int(known_count * REFRESH_MIN_RATIO))
