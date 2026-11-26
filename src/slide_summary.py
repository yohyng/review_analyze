"""スライドごとの「このページが示していること」を Gemini に書かせる。

■ 課金の線
  スライドは描画のたびに走る。ここから LLM を呼ぶと歯止めが無いので、
  **生成は事前に1回だけ**行い、slide_summary テーブルに保存する。
  描画側（preview / slides）は保存済みを読むだけ。NMSI と同じ扱い。

■ 鍵の持ち方
  (施設, スライド, 事実のハッシュ, モデル)。
  ハッシュの材料は「そのスライドが示している数字そのもの」なので、
  数字が変われば自然に作り直される。文言だけ変えても作り直されない。

■ 何を渡すか
  スライドのHTMLではなく、**そのページが示している事実だけ**を渡す。
  HTMLを投げると体裁の話をされるし、トークンも無駄になる。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

MODEL_FALLBACK = "gemini-1.5-flash"

# スライド名 → 人が読む見出し。プロンプトに文脈として渡す。
SLIDE_TITLES = {
    "slide2_market_position": "市場内ポジション（順位・強み弱みTOP3）",
    "slide2_market_detail": "市場内ポジション詳細（22観点のスコアとマッピング）",
    "slide3_competitor_compare": "選択競合との比較（指標別の折れ線とヒートマップ）",
    "slide3_competitor_detail": "選択競合との比較 詳細",
    "slide4_timeline": "時間軸分析（口コミ数と評価の推移・変化点）",
    "slide5_space_experience": "空間・体験分析（10観点のレーダー）",
    "slide5_space_detail": "空間・体験分析 詳細",
    "slide6_voices": "特徴的な口コミ",
    "slide7_discussion": "ディスカッションポイント",
    "slide8_nmsi": "体験満足度 NMSI（7フェーズ）",
    "slide9_data_quality": "このデータについて（分母と信頼区間）",
}


@dataclass
class Summary:
    slide: str
    headline: str = ""
    body: str = ""
    bullets: list = field(default_factory=list)   # 箇条書き型のページ用
    categories: dict = field(default_factory=dict)  # {カテゴリ: 1文}
    overall: str = ""                            # 全体評価（1段落）
    peers: list = field(default_factory=list)    # 競合ごとの差分（7P）
    from_cache: bool = False

    def __bool__(self) -> bool:
        return bool(self.headline or self.body or self.bullets
                    or self.categories or self.overall or self.peers)


# --------------------------------------------------------------------------- #
# そのスライドが示している「事実」を bundle から取り出す
# --------------------------------------------------------------------------- #
def facts_for(slide: str, b: dict) -> dict:
    """スライドが示している数字だけを抜く。HTMLは渡さない。"""
    def topics(n=5):
        names = b.get("topic_names") or []
        vals = b.get("topic_values") or []
        base = b.get("overall_topic") or {}
        rows = [{"観点": t, "スコア": round(v / 20, 2),
                 "基準": round(base.get(t, 50.0) / 20, 2)}
                for t, v in zip(names, vals)]
        rows.sort(key=lambda r: r["スコア"] - r["基準"], reverse=True)
        return {"上位": rows[:n], "下位": rows[-n:][::-1]}

    common = {
        "施設": b.get("target"),
        "口コミ件数": b.get("n_reviews"),
        "比較の基準": b.get("baseline_label"),
        "比較の範囲": b.get("scope_label"),
    }

    if slide == "slide2_market_position":
        # カテゴリ別要約と全体評価の両方がこのページ。数字だけを渡す。
        from . import categories as _cat  # noqa: PLC0415

        return {**common,
                "順位": b.get("rank"), "母数": b.get("total_fac"),
                "総合スコア5点": (round(b["overall_sentiment"] / 20, 2)
                             if b.get("overall_sentiment") is not None else None),
                "強み弱み": topics(3),
                "カテゴリ": _cat.facts_for_prompt(b.get("category_scores") or [])}
    if slide == "slide2_market_detail":
        return {**common,
                "順位": b.get("rank"), "母数": b.get("total_fac"),
                "強み弱み": topics(5)}
    if slide == "slide3_competitor_detail":
        # 1施設ずつ突き合わせるページ。**差は LLM に取らせず、ここで取る。**
        # 引き算を任せると桁を間違えた値が本文に出る（点数は本文に書かせない
        # 決まりだが、間違った差から選んだ指標はそのまま残ってしまう）。
        mine = {t: v for t, v in zip(b.get("topic_names") or [],
                                     b.get("topic_values") or [])}
        pts = b.get("peer_topic_scores") or {}
        rows = []
        for name in (b.get("peer_names") or []):
            vals = pts.get(name) or {}
            axes = [{"指標": t,
                     "対象": round(mine[t] / 20, 2),
                     "競合": round(vals[t] / 20, 2),
                     "差": round((mine[t] - vals[t]) / 20, 2)}
                    for t in mine if t in vals]
            # 差の大きい順。LLM が 2〜4 個選ぶときの手がかりにする。
            axes.sort(key=lambda a: abs(a["差"]), reverse=True)
            rows.append({"競合施設": name, "指標": axes})
        return {**common, "比較": rows}
    if slide.startswith("slide3"):
        return {**common, "競合": b.get("peer_names"), "強み弱み": topics(5)}
    if slide == "slide4_timeline":
        # **件数も渡す。** ポジ／ネガのスコアだけ見せると、口コミ1件の月と
        # 50件の月が同じ重みで読まれ、「〜月に不満が増えた」と書かれてしまう。
        rows = [{"月": ym, "口コミ件数": n,
                 "ポジティブ": round(pos, 2), "ネガティブ": round(neg, 2),
                 "差分": round(diff, 2)}
                for (ym, n, pos, neg, diff, *_rest) in (b.get("monthly_series") or [])]
        cps = []
        for c in (b.get("change_points") or []):
            get = (c.get if isinstance(c, dict) else lambda k, d=None: getattr(c, k, d))
            cps.append({"月": get("ym"), "向き": get("direction"),
                        "変化pt": get("delta_pt"), "口コミ件数": get("n_reviews"),
                        "語": list(get("keywords") or [])[:6]})
        return {**common, "分析期間": b.get("period_label"),
                "月次": rows, "変化点": cps}
    if slide.startswith("slide5"):
        return {**common, "空間10観点": topics(5)}
    if slide == "slide6_voices":
        return {**common, "代表口コミ数": len(b.get("voices") or [])}
    if slide == "slide7_discussion":
        return {**common, "課題": [str(i)[:60] for i in (b.get("issues") or [])][:5]}
    if slide == "slide8_nmsi":
        n = b.get("nmsi") or {}
        return {**common, "NMSI": n.get("nmsi"), "解釈": n.get("interpretation"),
                "フェーズ": [{"フェーズ": p.get("フェーズ"), "効果": p.get("E_i"),
                         "文数": p.get("文数")}
                        for p in (n.get("phases") or [])]}
    if slide == "slide9_data_quality":
        r = b.get("reliability") or {}
        return {**common,
                "全件": r.get("total"), "使えた": r.get("usable"),
                "日本語以外": r.get("foreign"),
                "星評価": r.get("rating_mean"),
                "星の95%区間": [r.get("rating_lo"), r.get("rating_hi")]}
    return common


def fact_hash(facts: dict) -> str:
    raw = json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# 生成
# --------------------------------------------------------------------------- #
PROMPT = """あなたは施設の口コミ分析レポートの読み手を助ける編集者です。

以下は、レポート1ページが示している数字です。このページを初めて見る人が
「結局このページは何を言っているのか」を掴めるように、短くまとめてください。

ページ: {title}

数字:
{facts}

制約:
- 数字にない話をしないこと。推測を書かないこと。
- 「〜と思われる」「〜かもしれない」のような曖昧語を使わないこと。
- headline は20文字以内。体言止め。
- body は80文字以内。1文か2文。数字を1つ以上含めること。
- 出力は次のJSONだけ:
{{"headline": "...", "body": "..."}}"""


# ── スライド別のプロンプト ──────────────────────────────────────────── #
#    既定は上の PROMPT（見出し＋1〜2文）。形が違うページだけここで上書きする。
#    slide3 は利用部門が書いた指示をそのまま採用した（2026-11-15 のデッキ由来）。
#    箇条書き3点で、点数・順位を本文に出さず、因果を断定しない、という条件が
#    先に決まっていたので、こちらで言い換えずに原文を使う。
SLIDE3_PROMPT = """あなたは施設の競合比較を行うデータアナリストです。
比較表を俯瞰し、指定競合と並べたときに対象施設がどのような施設として見えるかを、
改善担当者向けに箇条書き3点でまとめてください。

ページ: {title}

数字:
{facts}

### 分析手順
1. **強み** 対象施設が競合を上回る指標から、施設の特徴をよく表すものを選び、
   利用者にとってどのような価値が際立っているかを述べる。
2. **改善余地** 対象施設が競合を下回る指標から、施設のどの側面に弱さがあるかを
   述べる。同じ領域でも評価が分かれる場合は、その違いを取り上げる。
   例として、多様性や更新性が高く、品質の評価が低い組み合わせがある。
3. **評価の特徴** 「体験満足度」「再訪意向」「推奨意向」などを照らし合わせ、
   評価の開きや共通する傾向を述べる。明確な開きがない場合は、表全体から
   読み取れる別の特徴を取り上げる。

### 記述ルール
- 指標は表の正式名称を使い、個別に「」で囲む。見立てには括弧を付けない。
- 各項目は短い見立てから始め、根拠となる指標を1〜3個示す。
- **点数や順位は本文に記載しない。**「競合すべてを上回る」などの表現は、
  比較可能な全施設で確認できた場合に使う。差が小さい場合は近い水準として扱う。
- 比較は同じ指標の施設間で行う。「全体平均」列は施設数に含めない。
- スコアが言及量を示す場合は、話題に上がる傾向として表現する。
- 指標の高低を結びつけて特徴を述べる際は、**因果関係を断定しない。
  表にない原因、口コミの内容、具体的な利用場面は補わない。**

### 出力形式
次のJSONだけを返す。各要素は「**短い見立て。**「指標名」「指標名」を使って、
競合との違いを1文で示す。」の形にする。
{{"bullets": ["...", "...", "..."]}}"""

# SLIDE 2 のページ要約。利用部門が書いた2つの指示を1本にまとめている
# （2026-11-15 のデッキ由来。4P「全体評価」と 4P右下「カテゴリ別評価」）。
# 同じページの同じ数字を見るので、呼び出しを1回にして両方返させる。
# **条件は原文のまま**。順位・点数を本文に書かない、言及の少なさを低評価と
# 決めつけない、一部の口コミを施設全体に広げない、という決めが先にあったため。
SLIDE2_PROMPT = """あなたは施設改善を支援するデータアナリストです。
対象施設の評価項目と比較対象施設のスコアを読み、2つの出力を返してください。

ページ: {title}

数字:
{facts}

══ 出力1: 全体評価 ══

### 分析の観点
1. 施設を特徴づける価値を見極める。比較対象との評価差を照らし合わせ、
   個別の強みを、利用者がこの施設を訪れる理由としてまとめる。
2. 施設の価値がどの場面で十分に届いていないかを捉える。評価の低い項目に
   ついて、どの側面に課題があるかを示す。体験満足度・再訪意向・推奨意向
   との関係は、全体像を説明するうえで重要な場合に取り上げる。
3. 施設改善の観点から、何が主要な課題かを結論づける。施設の魅力そのもの、
   魅力へのアクセス、館内での体験、運営品質など、どこに課題があるのかを
   示す。複数の弱点が同じ課題に結びつく場合は、一つにまとめる。
   明確な弱点が見られない場合は、評価を支えている要素を結論とする。

### 根拠の扱い
- **順位、点数、平均との差は判断材料として使い、本文には記載しない。**
- 要因と結果が同時に観測された場合は、それぞれの傾向として記述する。
- **一部の口コミや特定の利用場面に見られる課題は、施設全体に広げて
  表現しない。**

日本語で150〜180字程度、3文・1段落。
第1文で「どんな価値を持つ施設か」を言い切る。
第2文で、その価値を支える体験と、課題が現れる場面を具体的に示す。
第3文で、施設改善の観点から全体をどう評価するかをまとめる。

══ 出力2: カテゴリ別評価 ══

各カテゴリの順位を見た担当者が、その順位の中身を一読で理解できるように、
カテゴリごとに評価を1文で要約してください。

### 判断手順
1. カテゴリ内の全項目を見て、比較対象との差が目立つ項目と、
   カテゴリの順位だけでは見えにくい項目間のばらつきを確認する。
2. 要約に入れる論点を最大2つに絞る。全体に同じ傾向が見られる場合は
   代表的な特徴を1つ選ぶ。強い項目と弱い項目が混在する場合は、両方を示す。

### 記述ルール
- 順位・点数・平均との差は論点の選定に使う。**要約欄には数値を繰り返さない。**
- カテゴリ内の項目だけで評価する。
- スコアが言及量を表す場合、**言及が少ないことを低評価と判断せず**、
  確認できた範囲を示す。
- 「総合評価」は、体験満足度・比較優位性・再訪意向・推奨意向を扱う
  評価カテゴリとして要約する。
- 入力が不足し、評価傾向を読み取れない場合は「判断材料が限られる」と記載する。

各カテゴリの要約は日本語1文、40〜60字程度。

══ 返す形 ══
次のJSONだけを返す。
{{"overall": "...",
  "categories": {{"コンテンツ": "...", "空間設計": "...", "サービス": "...",
  "価格・決済": "...", "アクセス": "...", "ブランド": "...", "総合評価": "..."}}}}"""

# 7P「指定競合との比較」施設別の差分分析。利用部門が書いた指示をそのまま
# 採用した（2026-11-15 のデッキ由来）。競合を1施設ずつ取り上げる、点数を
# 本文に書かない、仮説は断定しない、という決めが先にあったので言い換えない。
#
# **口コミ原文は渡していない。** 原文の指示は「関連する口コミ原文（提供されて
# いる場合）」と条件付きなので、渡せる材料だけで書かせる。原文を渡すように
# なったら、この但し書きを外すこと。
PEER_DIFF_PROMPT = """あなたは施設の競合比較を行うデータアナリストです。
対象施設と指定競合を1施設ずつ比較し、各競合について「評価差分」「読み解き」
「仮説」を出力してください。**指定された競合は、入力順にすべて取り上げて
ください。**

ページ: {title}

指標別スコアと差（5点満点。差は対象施設−競合）:
{facts}

### 分析手順
1. **評価差分** 同じ指標で2施設を比較し、この相手と並べたときに特徴が出る
   指標を2〜4個選ぶ。対象施設と競合、それぞれがどの指標で上回るかを示す。
   差が小さい項目は、近い水準として扱う。
2. **読み解き** 選んだ指標を組み合わせ、両施設がそれぞれどんな点で評価されて
   いるかを述べる。たとえば「展示の幅と新しさ」「空間の使いやすさと質感」の
   ように、指標名から利用者が感じる価値を具体化する。体験満足度・再訪意向・
   推奨意向に特徴的な開きがあれば取り上げる。
3. **仮説** 評価差分を手がかりに、対象施設では何が評価されやすく、何が競合
   ほど評価に表れにくいのかを、利用者の目線で1文にまとめる。

### 記述ルール
- 個別指標は表の正式名称を使い、指標ごとに「」で囲む。
- **点数や順位は論点を選ぶために使い、本文では評価の方向と意味を伝える。**
- 競合ごとに、その相手との違いを最もよく説明する組み合わせを選ぶ。
- 仮説は「〜が評価されている可能性がある」など、検証できる見立てとして書く。
  **指標の差を根拠に、原因や利用者の心理を断定しない。**
- スコアが言及量を示す場合は、話題に上がる傾向として扱う。
- 比較できる指標が不足している施設も取り上げ、判断できる範囲を示す。
- 口コミ原文は渡していない。**具体的な場面や原文の内容を補わない。**

### 出力形式
次のJSONだけを返す。competitors は入力順。見出しは20字以内、
各項目は1〜2文。ページ全体の総括や施策提案は付けない。
{{"competitors": [{{"name": "競合施設名",
  "headline": "この比較で最も特徴的な違い",
  "diff": "どちらの施設が、どの指標で上回るか",
  "reading": "指標の組み合わせから見える、両施設の評価の違い",
  "hypothesis": "対象施設で評価されやすい体験と、競合ほど評価に表れにくい点"}}]}}"""


# 9P下段「時間軸分析」の要約。利用部門が書いた指示をそのまま採用した
# （2026-11-15 のデッキ由来）。件数と割合を併記させる、1件の口コミを
# 傾向に広げない、スコアが動いた原因と断定しない、という決めが先にあった。
#
# **口コミ原文は渡していない。** 原文の指示には代表口コミを使う手順が
# あるが、ここは月次の数字と変化点の語だけで書かせる。
TIMELINE_PROMPT = """あなたは施設の口コミを分析するデータアナリストです。
月別の推移を読み、期間全体の傾向、評価が動いた月、その前後に何が起きて
いるかを、改善担当者向けに箇条書き3点でまとめてください。

ページ: {title}

月別のスコアと件数:
{facts}

### 分析手順
1. **期間全体の傾向** どちらの評価が優勢な月が多いかを確認し、期間を通じて
   繰り返し現れる傾向を示す。
2. **最も重要な変化とその背景** プラス・マイナスが逆転した月、または差分が
   大きく動いた月を選ぶ。前月と比べ、好評が減ったのか、不満が増えたのか、
   両方が動いたのかを確認する。
3. **直近の状態** 期間の終わりに近い数か月がどちらに向いているかを示す。

### 記述ルール
- 該当する月を明記する。取り上げた語は「」で囲む。
- **1件の口コミは「1件あった」と記述する。口コミ件数が月によって異なる
  場合は、件数をあわせて示す。** 件数の少ない月の動きを、施設全体の傾向に
  広げない。
- 差分がプラスのまま低下した場合は「プラス幅が縮んだ」と書く。
  ネガティブ側が上回った場合に「ネガティブに転じた」と書く。
- **スコアが動いた原因とは断定しない。** 同じ月に見られた変化として書く。
- 要因を特定できる材料がない場合は、確認できた評価の動きまでを記述する。
  口コミ原文は渡していない。**具体的な場面や原文の内容を補わない。**

### 出力形式
次のJSONだけを返す。各要素は「**短い見立て。**該当する月と、確認できた
動きを1〜2文で示す。」の形にする。
{{"bullets": ["...", "...", "..."]}}"""


PROMPTS = {
    "slide3_competitor_compare": SLIDE3_PROMPT,
    "slide2_market_position": SLIDE2_PROMPT,
    "slide3_competitor_detail": PEER_DIFF_PROMPT,
    "slide4_timeline": TIMELINE_PROMPT,
}

# 返ってくる形。ページごとに違うので、判定を1か所にまとめる。
#   bullets    … ["...", ...]            （5P下段）
#   categories … {カテゴリ: 1文} ＋ 全体評価（4P）
#   peers      … [{name, headline, ...}] （7P。競合1施設につき1ブロック）
SHAPES = {
    "slide3_competitor_compare": "bullets",
    "slide2_market_position": "categories",
    "slide3_competitor_detail": "peers",
    "slide4_timeline": "bullets",
}

# 後方互換。**この2つは SHAPES から導く**（別々に持つと必ずずれる）。
CATEGORY_SLIDES = tuple(k for k, v in SHAPES.items() if v == "categories")


def shape_of(slide: str) -> str:
    return SHAPES.get(slide, "default")


def prompt_for(slide: str) -> str:
    return PROMPTS.get(slide, PROMPT)


def is_bullet_slide(slide: str) -> bool:
    """箇条書き型で出すページか。描画側が形を切り替えるのに使う。"""
    return shape_of(slide) == "bullets"


def is_category_slide(slide: str) -> bool:
    """カテゴリ別要約（{カテゴリ: 1文}）で返るページか。"""
    return shape_of(slide) == "categories"


def is_peer_slide(slide: str) -> bool:
    """競合1施設ごとの差分（7P）で返るページか。"""
    return shape_of(slide) == "peers"


def generate(slide: str, b: dict, api_key: str, *,
             model: Optional[str] = None) -> tuple[Summary, str]:
    """1枚ぶん生成する。戻りは (Summary, エラー文字列)。

    **課金される。** 描画から呼ばないこと。
    """
    from . import llm  # noqa: PLC0415

    facts = facts_for(slide, b)
    shape = shape_of(slide)
    bullet, cats = shape == "bullets", shape == "categories"
    prompt = prompt_for(slide).format(
        title=SLIDE_TITLES.get(slide, slide),
        facts=json.dumps(facts, ensure_ascii=False, indent=2, default=str),
    )
    # 7P は競合1施設につき3項目。施設数ぶん必要なので上限を分けている。
    cap = {"default": 300, "peers": 2600}.get(shape, 900)
    data, err = llm.call_json(prompt, api_key, max_tokens=cap, temperature=0.2)
    if err or not isinstance(data, dict):
        return Summary(slide=slide), (err or "想定外の応答")
    if cats:
        from . import categories as _cat  # noqa: PLC0415

        got = data.get("categories")
        if not isinstance(got, dict):
            got = {}
        # 知らないカテゴリ名は捨てる。資料の7カテゴリ以外を増やさない。
        clean = {k: str(v).strip() for k, v in got.items()
                 if k in _cat.ORDER and str(v).strip()}
        overall = str(data.get("overall") or "").strip()
        if not clean and not overall:
            return Summary(slide=slide), "全体評価もカテゴリ別要約も空でした"
        return Summary(slide=slide, categories=clean, overall=overall), ""
    if shape == "peers":
        want = list(b.get("peer_names") or [])
        rows = []
        for got in (data.get("competitors") or []):
            if not isinstance(got, dict):
                continue
            name = str(got.get("name") or "").strip()
            row = {k: str(got.get(k) or "").strip()
                   for k in ("headline", "diff", "reading", "hypothesis")}
            if name and any(row.values()):
                rows.append({"name": name, **row})
        if not rows:
            return Summary(slide=slide), "競合ごとの差分が空でした"
        # **入力順に戻す。** 並びが変わると、左のマッピングと照合できない。
        # 名前を知らないものは落とす（勝手に施設を増やさせない）。
        order = {n: i for i, n in enumerate(want)}
        rows = [r for r in rows if r["name"] in order]
        rows.sort(key=lambda r: order[r["name"]])
        if not rows:
            return Summary(slide=slide), "知らない施設名しか返りませんでした"
        return Summary(slide=slide, peers=rows), ""
    if bullet:
        items = [str(x).strip() for x in (data.get("bullets") or []) if str(x).strip()]
        if not items:
            return Summary(slide=slide), "箇条書きが空でした"
        return Summary(slide=slide, bullets=items[:3]), ""
    return Summary(slide=slide,
                   headline=str(data.get("headline") or "").strip(),
                   body=str(data.get("body") or "").strip()), ""


# --------------------------------------------------------------------------- #
# 保存と読み出し
# --------------------------------------------------------------------------- #
def _facility_id(conn, name: str):
    row = conn.execute("SELECT id FROM facility WHERE name = ?", (name,)).fetchone()
    if row is None:
        return None
    return row["id"] if not isinstance(row, tuple) else row[0]


def model_name() -> str:
    from . import llm  # noqa: PLC0415

    return getattr(llm, "GEMINI_MODEL", MODEL_FALLBACK)


def get(conn, facility: str, slide: str, b: dict) -> Optional[Summary]:
    """保存済みを読む。**通信しない**。無ければ None。"""
    fid = _facility_id(conn, facility)
    if fid is None:
        return None
    row = conn.execute(
        "SELECT headline, body, bullets_json, categories_json, overall_text, "
        "peers_json "
        "FROM slide_summary "
        "WHERE facility_id = ? AND slide = ? AND fact_hash = ? AND model = ?",
        (fid, slide, fact_hash(facts_for(slide, b)), model_name()),
    ).fetchone()
    if row is None:
        return None
    g = (lambda k, i: row[k] if not isinstance(row, tuple) else row[i])
    try:
        bullets = json.loads(g("bullets_json", 2) or "[]")
    except Exception:
        bullets = []
    try:
        cats = json.loads(g("categories_json", 3) or "{}")
    except Exception:
        cats = {}
    try:
        peers = json.loads(g("peers_json", 5) or "[]")
    except Exception:
        peers = []
    return Summary(slide=slide, headline=g("headline", 0), body=g("body", 1),
                   bullets=bullets if isinstance(bullets, list) else [],
                   categories=cats if isinstance(cats, dict) else {},
                   overall=g("overall_text", 4) or "",
                   peers=peers if isinstance(peers, list) else [],
                   from_cache=True)


def save(conn, facility: str, slide: str, b: dict, s: Summary) -> None:
    fid = _facility_id(conn, facility)
    if fid is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO slide_summary"
        "(facility_id, slide, fact_hash, model, headline, body, bullets_json,"
        " categories_json, overall_text, peers_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (fid, slide, fact_hash(facts_for(slide, b)), model_name(),
         s.headline, s.body, json.dumps(s.bullets, ensure_ascii=False),
         json.dumps(s.categories, ensure_ascii=False), s.overall,
         json.dumps(s.peers, ensure_ascii=False)),
    )
    conn.commit()


def build_all(conn, facility: str, b: dict, api_key: str, *,
              slides: Optional[list] = None, force: bool = False,
              progress_cb=None) -> dict:
    """レポート全枚ぶん作る。保存済みは飛ばす（課金しない）。

    戻り: {"created": n, "cached": n, "failed": [(slide, 理由)]}
    """
    names = slides if slides is not None else list(SLIDE_TITLES)
    created = cached = 0
    failed: list = []
    for i, slide in enumerate(names, 1):
        if progress_cb:
            progress_cb(i, len(names), slide)
        if not force and get(conn, facility, slide, b):
            cached += 1
            continue
        s, err = generate(slide, b, api_key)
        if err or not s:
            failed.append((slide, err or "空の応答"))
            continue
        save(conn, facility, slide, b, s)
        created += 1
    return {"created": created, "cached": cached, "failed": failed}
