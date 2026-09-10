"""n=1 の貴重意見を拾う（資料「レアクチコミ抽出」§9）。

**珍しさではなく「構造的な問題の兆候か」で選ぶ。**
1回しか出ていない表現のうち、運営が動ける示唆を含むものだけを残す。

FinalScore = 0.20·Novelty + 0.25·Specificity + 0.25·Severity
           + 0.20·Actionability + 0.10·Credibility

■ LLM を使わない
  22観点スコアと同じ土俵に置くため。辞書とTF-IDFで組む。
  「何件から出た数字か」を説明できる状態を保ちたいので、
  ここで生成AIに寄せると根拠が追えなくなる。

■ 既存の「N=1」との違い
  slides の N=1 は代表的な口コミをそのまま載せるもの。
  こちらは**選別**で、出力に理由と改善示唆が付く。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

WEIGHTS = {"novelty": 0.20, "specificity": 0.25, "severity": 0.25,
           "actionability": 0.20, "credibility": 0.10}

# ── 具体性の4要素（資料 §9-4 Specificity）─────────────────────────── #
PLACES = ("入口", "受付", "エントランス", "展示室", "常設展", "企画展", "映像",
          "シアター", "体験", "ショップ", "売店", "カフェ", "レストラン",
          "トイレ", "お手洗い", "休憩", "ロッカー", "駐車場", "エレベーター",
          "階段", "通路", "出口", "ロビー", "窓口", "館内")
TIMES = ("朝", "昼", "夕方", "夜", "閉館", "開館", "平日", "休日", "土日",
         "祝日", "夏休み", "連休", "時", "分", "待ち", "並")
SITUATIONS = ("雨", "雪", "暑", "寒", "子連れ", "子ども", "子供", "ベビーカー",
              "車椅子", "団体", "予約", "混雑", "空い", "初めて", "再訪",
              "高齢", "外国", "英語")
PHENOMENA = ("異音", "臭い", "匂いが", "故障", "壊れて", "汚れて", "汚い",
             "滑りやす", "詰ま", "道に迷", "分かりにく", "わかりにく",
             "見えにく", "聞こえにく", "暗すぎ", "眩し", "暑すぎ", "寒すぎ",
             "止まって", "動かな", "つながらな", "売り切れ", "品切れ")

# ── 重大性（資料 §9-4 Severity）──────────────────────────────────── #
# **短い語を単体で入れないこと。** 日本語では部分文字列が頻繁に誤爆する。
# 実データで踏んだもの:
#   「両面において」→ におい / 「落ち着いた」→ 落ち / 「売り切れて」→ 切れて
#   「買おうか迷いました」→ 迷
# それぞれ、曖昧にならない形に直してある。
SEVERITY = {
    "衛生": (("汚れて", "汚い", "臭い", "臭う", "匂いが", "不潔", "ほこり",
             "ホコリ", "カビ", "ベタベタ"), 1.0),
    "安全": (("危ない", "危険", "滑りやす", "転びそう", "壊れて", "ぶつか",
             "落下", "怪我", "段差"), 1.0),
    "設備故障": (("故障", "動かな", "止まって", "使えな", "点かな", "つかな",
                "電源が", "反応しな"), 0.85),
    "会計・案内": (("会計", "料金が違", "案内が無", "案内がな", "説明が無",
                 "説明がな", "予約が取れ", "並び直"), 0.7),
    "休息阻害": (("うるさ", "騒音", "落ち着かな", "眩し", "まぶし", "暗すぎ",
               "暑すぎ", "寒すぎ", "座れな", "休めな"), 0.7),
    "混雑": (("混雑", "行列", "待たさ", "人が多すぎ", "入れな", "待ち時間"), 0.6),
    "導線": (("道に迷", "迷子", "分かりにく", "わかりにく", "たどり着けな",
             "順路が", "動線"), 0.6),
}

# ── 信頼性（資料 §9-4 Credibility）──────────────────────────────── #
CAUSAL = ("ので", "ため", "から", "せいで", "おかげで", "により", "ことで")
OBSERVED = ("あった", "いた", "していた", "見た", "見えた", "聞こえた",
            "書いてあ", "置いてあ", "貼って")
VAGUE = ("なんとなく", "たぶん", "気がする", "かも", "いまいち", "微妙",
         "普通", "まあまあ", "そこそこ")
EMOTION_ONLY = ("最高", "最悪", "良かった", "悪かった", "楽しかった",
                "つまらな", "満足", "残念")

_SENT = re.compile(r"[。！？\n]+")
# 句点の無い口コミは1文として丸ごと通ってしまう。読点でも切る保険。
_SOFT = re.compile(r"[、，]")
MIN_CHARS = 12          # これ未満は文脈が無く、読んでも動けない
MAX_CHARS = 80          # これを超える「文」は分割失敗＝個人事情の塊とみなす

# 打消し。重大性の語の**すぐ後ろ**にこれが来たら、その語は不満ではない。
#   例「タバコ臭さが**ない**」「混雑もし**ない**」を不満として拾わないため。
NEGATIONS = ("ない", "なく", "无", "なかっ", "ません", "ず", "せん", "不要")
NEG_WINDOW = 5          # 語の直後だけ見る。広げると別の節の否定を拾う
                        #（「分かりにくく…たどり着けない」の『ない』など）

# 個人事情（資料の除外ルール）。文の主題がこれなら落とす。
PERSONAL = ("誕生日", "記念日", "友人と", "家族と", "娘", "息子", "母と",
            "父と", "彼氏", "彼女", "出張", "旅行の途中", "ついでに")
_NORM = re.compile(r"[\s　、,．.・…！!？?ー～〜（）()「」『』【】\"']+")


@dataclass
class Rare:
    facility: str
    text: str                       # 原文（該当文）
    novelty: float = 0.0
    specificity: float = 0.0
    severity: float = 0.0
    actionability: float = 0.0
    credibility: float = 0.0
    category: str = ""
    elements: tuple = ()            # 具体性の内訳（場所/時間/状況/現象）

    @property
    def score(self) -> float:
        return (WEIGHTS["novelty"] * self.novelty
                + WEIGHTS["specificity"] * self.specificity
                + WEIGHTS["severity"] * self.severity
                + WEIGHTS["actionability"] * self.actionability
                + WEIGHTS["credibility"] * self.credibility)

    @property
    def reason(self) -> str:
        """なぜ選んだか。数字の根拠が追えるようにする。"""
        parts = []
        if self.elements:
            parts.append("具体性: " + "・".join(self.elements))
        if self.category:
            parts.append(f"重大性: {self.category}")
        if self.actionability >= 0.6:
            parts.append("現場で対処できる記述")
        if self.novelty >= 0.6:
            parts.append("他に例のない言及")
        return " / ".join(parts) or "n=1"


# ── STEP1 前処理 ────────────────────────────────────────────────── #
def sentences(text: str) -> list[str]:
    """文に割り、ノイズを落とす（資料 STEP1）。"""
    out = []
    for chunk in _SENT.split(text or ""):
        parts = [chunk] if len(chunk) <= MAX_CHARS else _SOFT.split(chunk)
        for s in parts:
            s = s.strip("、， 　")
            if len(s) < MIN_CHARS or len(s) > MAX_CHARS:
                continue                      # 短すぎ／分割できない塊は捨てる
            if not re.search(r"[ぁ-んァ-ヶ一-龠]", s):
                continue
            out.append(s)
    return out


def normalize(s: str) -> str:
    """n=1 判定用の軽い正規化（資料 STEP3）。"""
    return _NORM.sub("", s)


# ── STEP4 各軸 ──────────────────────────────────────────────────── #
def _hits(s: str, words) -> int:
    return sum(1 for w in words if w in s)


def specificity_of(s: str) -> tuple[float, tuple]:
    """場所・時間・状況・現象の要素数。2要素以上で高評価（資料）。"""
    found = []
    for label, words in (("場所", PLACES), ("時間", TIMES),
                         ("状況", SITUATIONS), ("現象", PHENOMENA)):
        if _hits(s, words):
            found.append(label)
    return min(1.0, len(found) / 3.0), tuple(found)


def _negated(s: str, word: str) -> bool:
    """その語が打ち消されているか。直後の窓だけ見る。

    「臭さがない」「混雑もしない」を不満として拾わないため。
    文全体で否定語を探すと、別の節の否定を拾って取りこぼす。
    """
    for m in re.finditer(re.escape(word), s):
        tail = s[m.end(): m.end() + NEG_WINDOW]
        if any(n in tail for n in NEGATIONS):
            continue
        return False          # 打ち消されていない出現がある
    return True


def severity_of(s: str) -> tuple[float, str]:
    """重大性。打ち消されている語は数えない。"""
    best, cat = 0.0, ""
    for label, (words, weight) in SEVERITY.items():
        live = [w for w in words if w in s and not _negated(s, w)]
        if live and weight > best:
            best, cat = weight, label
    return best, cat


def actionability_of(s: str, elements: tuple) -> float:
    """原因が推測でき、現場で動けるか。曖昧語は減点（資料の良い例/悪い例）。"""
    v = 0.0
    if "場所" in elements:
        v += 0.45                       # どこの話か分かる
    if "現象" in elements:
        v += 0.35                       # 何が起きたか分かる
    if any(w in s for w in CAUSAL):
        v += 0.20
    if any(w in s for w in VAGUE):
        v -= 0.40
    return max(0.0, min(1.0, v))


def credibility_of(s: str, elements: tuple) -> float:
    v = 0.35
    if any(w in s for w in OBSERVED):
        v += 0.25
    if any(w in s for w in CAUSAL):
        v += 0.20
    v += 0.10 * len(elements)
    if any(w in s for w in VAGUE):
        v -= 0.35
    # 感情語しか無い（具体の要素ゼロ）
    if not elements and any(w in s for w in EMOTION_ONLY):
        v -= 0.30
    return max(0.0, min(1.0, v))


def _novelty_scores(sents: list[str]) -> dict:
    """語の希少さ。TF-IDF の idf 部分だけを使う（資料 Novelty）。"""
    n = len(sents) or 1
    toks = [set(re.findall(r"[ぁ-んァ-ヶ一-龠]{2,}", s)) for s in sents]
    df = Counter(t for ts in toks for t in ts)
    out = {}
    for s, ts in zip(sents, toks):
        if not ts:
            out[s] = 0.0
            continue
        idf = [math.log(n / df[t]) for t in ts]
        idf.sort(reverse=True)
        top = idf[:3]
        out[s] = min(1.0, (sum(top) / len(top)) / math.log(max(n, 2)))
    return out


POSITIVE = ("良い", "良かっ", "よかっ", "素晴らし", "きれい", "綺麗", "美しい",
            "楽しかっ", "満足", "おすすめ", "快適", "丁寧", "親切", "感動",
            "面白", "おもしろ", "好き", "最高", "価値があ", "ありがた",
            "便利", "助かり", "助かっ", "嬉しか", "オススメ", "また来た",
            "また行きた", "見ごたえ", "見応え")


CONDITIONAL = ("れば", "たら、", "なら、", "場合は", "かもしれ", "と思います",
               "でしょう")


def _is_conditional(s: str) -> bool:
    """仮定・推量の文。起きた事実ではないので改善の根拠にならない。

    例「予約が取れれば、絶対に体験する価値があります」
    """
    return any(w in s for w in CONDITIONAL)


def _is_positive(s: str) -> bool:
    """褒め言葉が優勢な文か。改善示唆にならないので候補から外す。

    「臭くない」のような打消しつきの褒めも拾えるよう、重大性が
    立っていないこととあわせて判断する（呼び出し側で severity を見る）。
    """
    pos = _hits(s, POSITIVE)
    if not pos:
        return False
    sev, _ = severity_of(s)
    return sev == 0.0 or pos >= 2


# ── 本体 ────────────────────────────────────────────────────────── #
def extract(reviews: list, facility: str, *, per_facility: int = 3,
            min_score: float = 0.35) -> list:
    """1施設ぶん。reviews は本文の文字列のリスト。

    出現1回の文だけを候補にし、5軸で並べて上位を返す。
    """
    sents: list[str] = []
    for text in reviews:
        sents.extend(sentences(text))
    if not sents:
        return []

    seen = Counter(normalize(s) for s in sents)
    once = [s for s in sents if seen[normalize(s)] == 1]
    if not once:
        return []

    nov = _novelty_scores(sents)
    out = []
    for s in once:
        spec, elems = specificity_of(s)
        sev, cat = severity_of(s)
        r = Rare(facility=facility, text=s,
                 novelty=nov.get(s, 0.0), specificity=spec, severity=sev,
                 actionability=actionability_of(s, elems),
                 credibility=credibility_of(s, elems),
                 category=cat, elements=elems)
        # 資料の除外ルール
        if not elems or ("現象" not in elems and not cat):
            continue
        if any(w in s for w in PERSONAL):     # 個人事情だけの文
            continue
        if _is_positive(s):                   # 褒め言葉は改善示唆にならない
            continue
        if _is_conditional(s):                # 仮定の話は起きた事実ではない
            continue
        if r.score < min_score:
            continue
        out.append(r)

    out.sort(key=lambda r: r.score, reverse=True)
    return out[:per_facility]


def extract_from_db(conn, facility: str, **kw) -> list:
    rows = conn.execute(
        "SELECT r.text FROM review r JOIN facility f ON f.id = r.facility_id "
        "WHERE f.name = ? AND r.text IS NOT NULL AND TRIM(r.text) != ''",
        (facility,),
    ).fetchall()
    texts = [(r["text"] if not isinstance(r, tuple) else r[0]) for r in rows]
    return extract(texts, facility, **kw)
