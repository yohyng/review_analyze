"""この分析がどれだけのデータに支えられているか。

レポートは「空間の快適性 3.8」のような数字を出すが、それが4件の口コミから
出たのか5,877件から出たのかを一切示していなかった。デモの46施設は実際に
4件〜5,877件（中央値166）の幅がある。同じ見た目の数字を並べれば、読み手は
同じ確からしさだと受け取る。

ここが返すのは3つ:
  funnel(conn, name)    全件 → 本文あり → 日本語 → 文、と落ちていく過程
  intervals(conn, name) 星評価とポジ率の信頼区間
  flags(conn, name)     数字を額面どおり読んではいけない条件

■ 信頼区間の取り方について
  - 比率（ポジ率）は **Wilson score interval**。件数が少ないときや比率が
    0/1 に寄ったときに、正規近似だと区間が枠外へ出たり幅0になったりする。
  - 平均（星評価）は n<30 なら t 分布、それ以上は正規で近似。
  - **口コミ単位で計算する**。文単位だと1件の長い口コミが何票も入り、
    区間が実際より狭く出る（同じ人の文は独立でない）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# 統計的に「これ未満は参考値」とする件数。30 は t 分布と正規近似が
# 実用上一致しはじめる目安で、ここでは表示の閾値として使う。
SMALL_N = 30
# 非日本語がこの比率を超えたら警告する。トピック辞書も形態素解析も
# 日本語前提なので、欧文の口コミは観点に当たらず一様ノイズになる。
FOREIGN_WARN = 0.10
SHORT_CHARS = 10


# ─────────────────────────────────────────────────────────────────────────
# 区間推定
# ─────────────────────────────────────────────────────────────────────────
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """比率 k/n の Wilson score interval（既定は95%）。

    正規近似（p ± z√(p(1-p)/n)）は n が小さいと 0 未満や 1 超えを返し、
    p が 0 か 1 のときは幅が 0 になる。Wilson はどちらも起こさない。
    """
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z / d) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def _t_crit(df: int) -> float:
    """両側95%の t 臨界値。scipy があれば使い、無ければ表で近似する。"""
    if df <= 0:
        return float("inf")
    try:
        from scipy import stats  # noqa: PLC0415

        return float(stats.t.ppf(0.975, df))
    except Exception:
        table = {1: 12.71, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
                 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 15: 2.131,
                 20: 2.086, 25: 2.060, 30: 2.042, 60: 2.000}
        for k in sorted(table):
            if df <= k:
                return table[k]
        return 1.96


def mean_ci(values: list[float]) -> tuple[float, float, float] | None:
    """平均と95%信頼区間。2件未満なら None（区間が定義できない）。"""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = math.sqrt(var / n)
    half = _t_crit(n - 1) * se
    return (mean, mean - half, mean + half)


# ─────────────────────────────────────────────────────────────────────────
# データの素性
# ─────────────────────────────────────────────────────────────────────────
_SENT = re.compile(r"[。！？\n]+")


def language_of(text: str) -> str:
    """本文の素性をざっくり分ける。判定は文字種だけで、辞書は引かない。"""
    t = (text or "").strip()
    if not t:
        return "empty"
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return "symbols"          # 「、。！」「6 ^^」のような実質無内容
    jp = sum(1 for c in letters
             if "぀" <= c <= "ヿ" or "一" <= c <= "鿿")
    r = jp / len(letters)
    if r >= 0.5:
        return "ja"
    return "mixed" if r > 0 else "foreign"


@dataclass
class Funnel:
    """全件からどう減っていくか。分母を明示するためのもの。"""
    total: int = 0
    with_text: int = 0
    japanese: int = 0
    usable: int = 0          # 日本語かつ短すぎない＝観点判定に耐える
    sentences: int = 0
    foreign: int = 0
    symbols: int = 0
    empty: int = 0
    short: int = 0
    mixed: int = 0           # 和欧混在。日本語として扱うが内訳では分けて出す

    @property
    def usable_rate(self) -> float:
        return self.usable / self.total if self.total else 0.0

    @property
    def foreign_rate(self) -> float:
        return self.foreign / self.total if self.total else 0.0

    def language_mix(self) -> list[tuple[str, int]]:
        """本文の言語内訳。合計は必ず total に一致する。

        「全件を分析しました」と言えないことを、この内訳で示す。
        """
        ja_only = self.japanese - self.mixed
        return [
            ("日本語", ja_only),
            ("和欧混在", self.mixed),
            ("日本語以外", self.foreign),
            ("記号・数字のみ", self.symbols),
            ("本文なし", self.empty),
        ]


def _reviews(conn, facility_name: str) -> list[tuple]:
    rows = conn.execute(
        """
        SELECT r.text, r.rating FROM review r
        JOIN facility f ON f.id = r.facility_id
        WHERE f.name = ?
        """, (facility_name,),
    ).fetchall()
    out = []
    for row in rows:
        text = row["text"] if not isinstance(row, tuple) else row[0]
        rating = row["rating"] if not isinstance(row, tuple) else row[1]
        out.append((text or "", rating))
    return out


def funnel(conn, facility_name: str) -> Funnel:
    f = Funnel()
    for text, _rating in _reviews(conn, facility_name):
        f.total += 1
        kind = language_of(text)
        if kind == "empty":
            f.empty += 1
            continue
        f.with_text += 1
        if kind == "symbols":
            f.symbols += 1
            continue
        if kind == "foreign":
            f.foreign += 1
            continue
        if kind == "mixed":
            f.mixed += 1     # 和文が混じっていれば観点判定は効くので使う
        f.japanese += 1
        if len(text.strip()) < SHORT_CHARS:
            f.short += 1
            continue
        f.usable += 1
        f.sentences += sum(1 for s in _SENT.split(text) if len(s.strip()) >= 3)
    return f


@dataclass
class Intervals:
    n_rated: int = 0
    rating_mean: float | None = None
    rating_lo: float | None = None
    rating_hi: float | None = None
    n_pos: int = 0
    pos_rate: float | None = None
    pos_lo: float | None = None
    pos_hi: float | None = None


def intervals(conn, facility_name: str) -> Intervals:
    """星評価の平均とポジ率の95%信頼区間。

    口コミ単位で数える。文単位にすると長い口コミが何票も持つことになり、
    区間が実際より狭く出る。
    """
    ratings = [float(r) for _t, r in _reviews(conn, facility_name)
               if r is not None]
    out = Intervals(n_rated=len(ratings))
    m = mean_ci(ratings)
    if m:
        out.rating_mean, out.rating_lo, out.rating_hi = m
    if ratings:
        # 4以上をポジとする（VoiceBAUM の既存の数え方に合わせる）
        k = sum(1 for v in ratings if v >= 4)
        out.n_pos = k
        out.pos_rate = k / len(ratings)
        out.pos_lo, out.pos_hi = wilson(k, len(ratings))
    return out


@dataclass
class Flag:
    key: str
    level: str            # "warn" | "note"
    text: str


@dataclass
class Reliability:
    facility: str
    funnel: Funnel
    intervals: Intervals
    flags: list[Flag] = field(default_factory=list)

    @property
    def small_sample(self) -> bool:
        return self.funnel.usable < SMALL_N


def assess(conn, facility_name: str) -> Reliability:
    """数字を額面どおり読んではいけない条件を洗い出す。"""
    fn = funnel(conn, facility_name)
    iv = intervals(conn, facility_name)
    flags: list[Flag] = []

    if fn.usable < SMALL_N:
        flags.append(Flag(
            "small_n", "warn",
            f"観点判定に使えた口コミが {fn.usable} 件しかありません"
            f"（{SMALL_N} 件未満）。順位や強み・弱みは参考値として扱ってください。"))

    if fn.foreign_rate > FOREIGN_WARN:
        flags.append(Flag(
            "foreign", "warn",
            f"本文の {fn.foreign_rate:.0%} が日本語以外です。トピック判定も"
            f"形態素解析も日本語を前提にしているため、これらは"
            f"どの観点にも当たらず、全観点に薄く配られます。"))

    if fn.total and fn.short / fn.total > 0.15:
        flags.append(Flag(
            "short", "note",
            f"{SHORT_CHARS}文字未満の短い口コミが {fn.short / fn.total:.0%} あります。"
            f"感情は取れても、何について言っているかは判定できません。"))

    if iv.rating_lo is not None and iv.rating_hi is not None:
        width = iv.rating_hi - iv.rating_lo
        if width > 0.5:
            flags.append(Flag(
                "wide_ci", "note",
                f"星評価の95%信頼区間が ±{width / 2:.2f} と広く、"
                f"他施設との小さな差は誤差の範囲です。"))

    return Reliability(facility=facility_name, funnel=fn, intervals=iv,
                       flags=flags)
