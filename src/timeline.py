"""SLIDE 4「時間軸分析」の変化点検出。

月次のポジ／ネガ要因スコアの推移から「評価が動いた月」を拾う。
何が起きたかの説明文は LLM に書かせるが、**影響の大きさ（pt）は必ずここで
算出する**。数値をモデルに作らせると、根拠のない値がレポートに載ってしまう。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChangePoint:
    ym: str                     # 'YYYY-MM'
    index: int                  # series 内の位置
    delta_pt: float             # 直前期間との平均★の差（5点満点のpt）
    n_reviews: int
    direction: str              # 'up' / 'down'
    title: str = ""             # LLM が付ける見出し（例:「新展示導入」）
    body: str = ""              # LLM が書く説明文
    keywords: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """'23/06 のような表示用の時期ラベル。"""
        y, m = self.ym.split("-")
        return f"'{y[2:]}/{m}"


# 変化点と呼ぶ最小の動き（★5点満点）。これ未満は誤差として扱う。
MIN_DELTA = 0.15

# 星評価のばらつきの目安（1〜5点なので概ね 1.0 前後）。月平均の
# 標準誤差 σ/√n を見積もるのに使う。
RATING_SIGMA = 1.0

# 標準誤差の何倍を超えたら「変化」と呼ぶか。
#   件数の少ない月は平均が偶然で大きく振れる。同じ 0.4pt の動きでも、
#   50件の月なら実のある変化、8件の月なら誤差の範囲。**件数に応じて
#   必要な変化量を変える**（2026-11-26。でんきの科学館で7〜11件の月が
#   変化点として拾われていた）。
SE_FACTOR = 2.0

# 最終月が「まだ途中」かを判定する割合。直前6か月の中央値に対して
# これを下回る件数なら、締まっていない月として候補から外す。
PARTIAL_MONTH_RATIO = 0.6


def detect_change_points(
    series: list[tuple], k: int = 3, baseline: int = 3, min_reviews: int = 3
) -> list[ChangePoint]:
    """月次系列から変化の大きい月を**最大** k 件返す（時系列順）。

    series は db.monthly_sentiment_series() の戻り値
    [(ym, n, pos, neg, diff, avg5), ...]。

    各月について「直前 baseline か月の平均★」との差を取り、その絶対値が
    大きい順に選ぶ。口コミが min_reviews 件未満の月は、1〜2件の外れ値で
    大きく振れてしまうので候補から外す。選んだ月どうしは2か月以上離す
    （同じ変化を2回説明させないため）。

    **k 件を無理に埋めない**（2026-11-26）。閾値が 0.05pt と緩く、安定した
    系列でも必ず3件出ていた。MIN_DELTA に加えて、その月の件数から出した
    標準誤差の SE_FACTOR 倍を超えることを求める。件数の少ない月ほど大きく
    動かないと変化と認めない。

    最終月は、件数が直前6か月の中央値の PARTIAL_MONTH_RATIO を下回るなら
    外す。月の途中までしか入っていない月を変化点として出さないため。
    """
    if len(series) < baseline + 1:
        return []

    usable = len(series)
    if usable >= 7:
        last_n = series[-1][1]
        prev_ns = sorted(row[1] for row in series[-7:-1])
        med = prev_ns[len(prev_ns) // 2]
        if med and last_n < med * PARTIAL_MONTH_RATIO:
            usable -= 1          # まだ締まっていない月は見ない

    cands: list[ChangePoint] = []
    for i in range(baseline, usable):
        ym, n, _pos, _neg, _diff, avg5 = series[i]
        if n < min_reviews:
            continue
        prev = [row[5] for row in series[i - baseline:i]]
        prev_n = sum(row[1] for row in series[i - baseline:i])
        if not prev or prev_n < min_reviews:
            continue
        delta = avg5 - sum(prev) / len(prev)
        cands.append(ChangePoint(
            ym=ym, index=i, delta_pt=round(delta, 2), n_reviews=n,
            direction="up" if delta >= 0 else "down",
        ))

    cands.sort(key=lambda c: -abs(c.delta_pt))
    picked: list[ChangePoint] = []
    for c in cands:
        # その月の件数で決まる「偶然でも起きうる幅」。これを超えないものは
        # 変化点にしない。件数が少ない月ほど大きな動きを求める。
        se = RATING_SIGMA / (c.n_reviews ** 0.5)
        if abs(c.delta_pt) < max(MIN_DELTA, SE_FACTOR * se):
            continue
        if any(abs(c.index - p.index) < 2 for p in picked):
            continue                     # 同じ山/谷を二重に拾わない
        picked.append(c)
        if len(picked) == k:
            break

    picked.sort(key=lambda c: c.index)
    return picked


def reviews_for_point(conn, facility_id: int, ym: str, limit: int = 40) -> list[tuple]:
    """変化点の月の口コミを (rating, text) で返す（LLM に渡す材料）。"""
    rows = conn.execute(
        "SELECT rating, text FROM review WHERE facility_id = ? "
        "AND strftime('%Y-%m', review_date) = ? "
        "AND text IS NOT NULL AND text != '' "
        "ORDER BY LENGTH(text) DESC LIMIT ?",
        (facility_id, ym, limit),
    ).fetchall()
    return [(r["rating"], r["text"]) for r in rows]


def fallback_description(cp: ChangePoint) -> tuple[str, str]:
    """LLM を使わない／失敗したときの見出しと説明文。

    憶測を書かず、観測できた事実だけを述べる。
    """
    if cp.direction == "up":
        return ("評価の上昇",
                f"この月の平均評価が直前3か月比で {cp.delta_pt:+.2f}pt 上昇しました"
                f"（口コミ {cp.n_reviews} 件）。要因は口コミ本文からは特定していません。")
    return ("評価の低下",
            f"この月の平均評価が直前3か月比で {cp.delta_pt:+.2f}pt 低下しました"
            f"（口コミ {cp.n_reviews} 件）。要因は口コミ本文からは特定していません。")
