"""VFFI — 来場者適合指数（Visitor-Facility Fit Index）。

「施設が狙った体験」と「来場者が実際にした体験」がどれだけ一致しているかを測る。
原典は facility-review-analysis スキルの visitor-fit-analysis.txt。

    V_i   口コミ1件から作る体験ベクトル（12要素）
    T     施設が狙う理想体験のベクトル（同じ12要素）
    Fit_i = cos(T, V_i)                      コサイン類似度
    Match = N(Fit_i > θ) / N_all             θ = 0.70
    D_i   = V_i − T                          何がズレたか
    VFFI  = 100 × (α·Match + β·Satisfaction − γ·Gap)

**原典に書かれていないものが2つある。正直に扱う。**

1. 係数 α / β / γ
   原典は「VFFI = α Match + β Satisfaction − γ Gap」という概念式までで、
   数値を与えていない。スキル側も「係数・正規化・施設目標を定義できた場合のみ
   0–100 で出し、仮定と推計を明記」と指示している。
   ここでは下の COEFFS を既定とし、**これはこのプロジェクトの決めであって
   原典の値ではない**ことを vffi_note() が必ず出力に添える。

2. T（施設の狙い）
   本来は施設が公式に持つもの。無い場合、原典は「口コミから仮置きした仮説」
   として扱ってよいとしている。derive_target() がそれを作るが、
   **高評価の口コミだけから作る**。全口コミから作ると T と V が同じ分布になり、
   Fit が構造的に高く出る（自分で自分を採点することになる）。
   高評価だけを「狙いどおりに届いた回」と見なすことで、
   Fit は「平均的な来場が、うまくいった来場にどれだけ近いか」を測る量になる。
   これは原典の T の定義そのものではない。derive_target() を使った場合は
   hypothesis=True が立ち、出力にその旨が残る。

**日本語専用**。22観点スコアと同じくキーワード辞書なので、英語・中国語の
口コミでは要素が立たず、ベクトルがほぼゼロになる。assess() は
language_mismatch を立てて返す。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# 原典の要素例。順序はベクトルの次元順で、変えると過去の値と比較できなくなる。
ELEMENTS: tuple[str, ...] = (
    "学習", "発見", "ノスタルジー", "没入", "体験性", "社会理解",
    "ブランド理解", "家族共有", "静けさ", "エンタメ性", "専門性", "SNS映え",
)

# 各要素を拾うキーワード。部分一致で数えるので、他語に埋もれる短い語は入れない
# （「雑」が「混雑」に当たる類の誤爆を避ける。rare.py で踏んだのと同じ罠）。
KEYWORDS: dict[str, tuple[str, ...]] = {
    "学習": ("勉強", "学べ", "学ぶ", "学習", "知識", "教育", "解説", "説明", "理解でき", "ためになる"),
    "発見": ("発見", "知らなかった", "初めて知", "驚き", "驚いた", "意外", "新鮮", "興味深"),
    "ノスタルジー": ("懐かし", "昔", "子どもの頃", "子供の頃", "レトロ", "当時", "思い出"),
    "没入": ("没入", "引き込まれ", "引き込ま", "世界観", "時間を忘れ", "夢中", "圧倒"),
    "体験性": ("体験", "触れ", "触っ", "参加", "ワークショップ", "作れ", "作って", "実演", "試乗", "試食"),
    "社会理解": ("社会", "歴史", "文化", "環境", "地域", "産業", "SDGs", "公共"),
    "ブランド理解": ("企業", "会社", "ブランド", "こだわり", "理念", "ものづくり", "技術力", "ファンに"),
    "家族共有": ("子ども", "子供", "家族", "親子", "孫", "お子様", "ファミリー", "夏休み"),
    "静けさ": ("静か", "落ち着", "ゆっくり", "のんびり", "混んでいな", "空いてい"),
    "エンタメ性": ("楽し", "面白", "おもしろ", "ワクワク", "わくわく", "飽きな", "エンタメ"),
    "専門性": ("専門", "詳し", "マニア", "本格", "深い", "マニアック", "玄人"),
    "SNS映え": ("写真", "撮影", "映え", "インスタ", "フォトスポット", "SNS"),
}

# コサイン適合の閾値。原典が θ = 0.70 を標準としている。
THETA = 0.70

# **原典に無い。このプロジェクトの決め。** 合計が 1.0 になるよう置いた
# （Match と Satisfaction で押し上げ、Gap で引く）。変えたら過去の値と比較しない。
COEFFS = {"alpha": 0.45, "beta": 0.45, "gamma": 0.30}

# 原典の解釈レンジ。
BANDS: tuple[tuple[int, str], ...] = (
    (85, "狙いと来場者が高度に一致"),
    (70, "良好な適合"),
    (55, "部分適合"),
    (40, "ミスマッチが大きい"),
    (0, "集客・体験設計の再設計が必要"),
)

# T を仮説で作るときに「狙いどおり届いた回」と見なす評点。
HIGH_RATING = 4.0

# これ未満の件数では指数を出さない（原典の「根拠不足なら算出不可」に対応）。
MIN_REVIEWS = 10

# Fit を数えるのに必要な、1口コミあたりの最低要素数。
#   **θ=0.70 は短い口コミでは構造的に届かない。** T が12要素に広がっている
#   とき、1要素しか立たない V とのコサインは概ね 1/√12 ≈ 0.29 にしかならず、
#   0.70 を超えるには6要素前後が要る。実データ（企業ミュージアム 8,000件）では
#   立つ要素数の中央値は 1、6要素以上はわずか 1.5% だった。
#   この閾値を置かずに素で数えると、MatchingRate は「適合度」ではなく
#   「口コミの長さ」を測る量になる。
MIN_ELEMENTS_FOR_FIT = 2

# 適合率を信用してよい下限。Fit を数えられた口コミがこの割合を下回るなら、
# MatchingRate は母集団を代表していないとみなす。
MIN_SCORED_SHARE = 0.30


def experience_vector(text: str) -> list[float]:
    """口コミ1件 → 12要素ベクトル。各要素は「当たったキーワードの異なり数」。

    出現回数ではなく異なり数にするのは、同じ語を繰り返しただけの口コミが
    その要素だけ突出するのを避けるため。
    """
    t = text or ""
    return [float(sum(1 for w in KEYWORDS[e] if w in t)) for e in ELEMENTS]


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def cosine(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """コサイン類似度。どちらかが零ベクトルなら None（0.0 ではない）。

    零ベクトルは「要素が1つも立たなかった」であって「似ていない」ではない。
    0.0 を返すと、日本語以外の口コミが全部「不適合」として集計されてしまう。
    """
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return None
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def derive_target(reviews: Iterable[tuple[Optional[float], str]]) -> list[float]:
    """高評価の口コミだけから T を仮置きする（原典が認めるフォールバック）。

    全件から作らない理由はモジュール冒頭の 2 を参照。
    高評価が1件も無ければ全件から作る（その場合 Fit は構造的に高く出る）。
    """
    high = [t for r, t in reviews if r is not None and r >= HIGH_RATING and t]
    pool = high or [t for _r, t in reviews if t]
    if not pool:
        return [0.0] * len(ELEMENTS)
    acc = [0.0] * len(ELEMENTS)
    for t in pool:
        for i, x in enumerate(experience_vector(t)):
            acc[i] += x
    return [x / len(pool) for x in acc]


@dataclass
class ElementRow:
    """出力表の1行。原典の `| 要素 | T | V | D | 解釈 |`。"""
    element: str
    target: float
    experience: float

    @property
    def gap(self) -> float:
        return self.experience - self.target

    @property
    def reading(self) -> str:
        if abs(self.gap) < 0.05:
            return "狙いどおり"
        return "狙いを上回る" if self.gap > 0 else "狙いに届いていない"


@dataclass
class VFFIResult:
    computable: bool = False
    reason: str = ""                     # computable=False のときの理由
    hypothesis_target: bool = True       # T が仮説か（既定は仮説）
    language_mismatch: bool = False      # 日本語以外が多く、要素が立たない

    n_reviews: int = 0
    n_scored: int = 0                    # Fit を計算できた件数（要素が足りる口コミ）
    mean_elements: float = 0.0           # 1口コミで立った要素数の平均
    match_reliable: bool = False         # 適合率を判定に使ってよいか
    match_rate: float = 0.0
    satisfaction: float = 0.0
    gap: float = 0.0
    score: float = 0.0                   # 0–100
    rows: list = field(default_factory=list)
    quadrants: dict = field(default_factory=dict)
    coeffs: dict = field(default_factory=lambda: dict(COEFFS))

    @property
    def band(self) -> str:
        """解釈レンジ。**適合率が信用できないときは判定しない。**

        VFFI は Match を 45% の重みで含むので、Match が壊れていれば
        指数も壊れている。それを「ミスマッチが大きい」と言い切ると、
        実際には満足度が高い施設を誤って断じることになる。
        """
        if not self.match_reliable:
            return "判定保留（適合率を算出できる口コミが足りない）"
        for lo, label in BANDS:
            if self.score >= lo:
                return label
        return BANDS[-1][1]


def _quadrants(fits: list[float], sats: list[float]) -> dict:
    """適合度 × 満足度の4象限。原典の表どおりの名前を使う。"""
    names = {
        (True, True): "理想顧客",
        (True, False): "施設サービス改善が必要",
        (False, True): "想定外ヒット",
        (False, False): "マーケティング改善が必要",
    }
    out = {v: 0 for v in names.values()}
    for f, s in zip(fits, sats):
        out[names[(f > THETA, s >= 0.5)]] += 1
    n = len(fits) or 1
    return {k: {"count": v, "share": round(v / n * 100, 1)} for k, v in out.items()}


def assess(reviews: Sequence[tuple[Optional[float], str]],
           target: Optional[Sequence[float]] = None,
           coeffs: Optional[dict] = None) -> VFFIResult:
    """口コミ列 → VFFI。

    reviews は [(rating, text), ...]。rating は5点満点か None。
    target を渡さなければ derive_target() で仮置きし、hypothesis_target が立つ。
    """
    c = dict(COEFFS)
    if coeffs:
        c.update(coeffs)
    res = VFFIResult(n_reviews=len(reviews), coeffs=c,
                     hypothesis_target=target is None)

    if len(reviews) < MIN_REVIEWS:
        res.reason = f"口コミが {len(reviews)} 件（{MIN_REVIEWS} 件未満）のため算出しない"
        return res

    T = list(target) if target is not None else derive_target(reviews)
    if _norm(T) == 0:
        res.reason = "施設の狙い T を作れなかった（要素が1つも立たない）"
        res.language_mismatch = True
        return res

    fits, sats = [], []
    acc_v = [0.0] * len(ELEMENTS)
    n_elems = 0
    for rating, text in reviews:
        v = experience_vector(text)
        for i, x in enumerate(v):
            acc_v[i] += x
        live = sum(1 for x in v if x > 0)
        n_elems += live
        # 要素が1つしか立たない口コミを Fit に入れない（MIN_ELEMENTS_FOR_FIT 参照）
        if live < MIN_ELEMENTS_FOR_FIT:
            continue
        f = cosine(T, v)
        if f is None:
            continue
        fits.append(f)
        sats.append(((rating - 1.0) / 4.0) if rating is not None else 0.5)

    res.n_scored = len(fits)
    res.mean_elements = round(n_elems / len(reviews), 2)
    if not fits:
        res.reason = (f"要素が {MIN_ELEMENTS_FOR_FIT} つ以上立つ口コミが無い"
                      f"（平均 {res.mean_elements} 要素）")
        res.language_mismatch = res.mean_elements < 0.5
        return res
    if res.n_scored < MIN_REVIEWS:
        res.reason = (f"要素が足りる口コミが {res.n_scored} 件のみ"
                      f"（{MIN_REVIEWS} 件未満）のため算出しない")
        res.language_mismatch = res.mean_elements < 0.5
        return res

    mean_v = [x / len(reviews) for x in acc_v]
    res.rows = [ElementRow(e, round(T[i], 3), round(mean_v[i], 3))
                for i, e in enumerate(ELEMENTS)]

    res.match_rate = sum(1 for f in fits if f > THETA) / len(fits)
    res.satisfaction = sum(sats) / len(sats)
    # Gap は T と平均 V のズレの大きさ。T の長さで割って尺度を揃える。
    res.gap = min(1.0, _norm([m - t for m, t in zip(mean_v, T)]) / (_norm(T) or 1.0))
    raw = c["alpha"] * res.match_rate + c["beta"] * res.satisfaction - c["gamma"] * res.gap
    res.score = round(max(0.0, min(1.0, raw)) * 100, 1)
    res.quadrants = _quadrants(fits, sats)
    res.match_reliable = (res.n_scored / len(reviews)) >= MIN_SCORED_SHARE
    res.computable = True
    return res


def vffi_note(res: VFFIResult) -> str:
    """出力に必ず添える但し書き。**省略しないこと。**

    原典が「仮定と推計を明記」と求めている部分を、文言として固定する。
    """
    parts = [
        f"VFFI は推計値です。係数 α={res.coeffs['alpha']} β={res.coeffs['beta']} "
        f"γ={res.coeffs['gamma']} は原典に定義が無く、本ツールで定めた値です。",
    ]
    if res.hypothesis_target:
        parts.append(
            "施設の狙い T は公式のものではなく、高評価の口コミから仮置きした仮説です。"
        )
    if res.language_mismatch:
        parts.append(
            "日本語以外の口コミでは要素が立たないため、対象から外れている可能性があります。"
        )
    if not res.match_reliable:
        parts.append(
            f"**適合率は判定に使えません。** 要素が {MIN_ELEMENTS_FOR_FIT} つ以上立つ"
            f"口コミが {res.n_scored} / {res.n_reviews} 件しかなく、"
            f"コサイン適合が口コミの短さに引きずられます"
            f"（1口コミあたり平均 {res.mean_elements} 要素）。"
        )
    parts.append(f"算出に使えた口コミは {res.n_scored} / {res.n_reviews} 件です。")
    return "　".join(parts)
