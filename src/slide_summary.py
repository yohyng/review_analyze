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
from dataclasses import dataclass
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
    from_cache: bool = False

    def __bool__(self) -> bool:
        return bool(self.headline or self.body)


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

    if slide in ("slide2_market_position", "slide2_market_detail"):
        return {**common,
                "順位": b.get("rank"), "母数": b.get("total_fac"),
                "総合スコア5点": (round(b["overall_sentiment"] / 20, 2)
                             if b.get("overall_sentiment") is not None else None),
                "強み弱み": topics(3)}
    if slide.startswith("slide3"):
        return {**common, "競合": b.get("peer_names"), "強み弱み": topics(5)}
    if slide == "slide4_timeline":
        return {**common, "推移": (b.get("review_trend") or [])[-12:],
                "変化点": [c.get("label") if isinstance(c, dict) else str(c)
                        for c in (b.get("change_points") or [])][:4]}
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


def generate(slide: str, b: dict, api_key: str, *,
             model: Optional[str] = None) -> tuple[Summary, str]:
    """1枚ぶん生成する。戻りは (Summary, エラー文字列)。

    **課金される。** 描画から呼ばないこと。
    """
    from . import llm  # noqa: PLC0415

    facts = facts_for(slide, b)
    prompt = PROMPT.format(
        title=SLIDE_TITLES.get(slide, slide),
        facts=json.dumps(facts, ensure_ascii=False, indent=2, default=str),
    )
    data, err = llm.call_json(prompt, api_key, max_tokens=300, temperature=0.2)
    if err or not isinstance(data, dict):
        return Summary(slide=slide), (err or "想定外の応答")
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
        "SELECT headline, body FROM slide_summary "
        "WHERE facility_id = ? AND slide = ? AND fact_hash = ? AND model = ?",
        (fid, slide, fact_hash(facts_for(slide, b)), model_name()),
    ).fetchone()
    if row is None:
        return None
    g = (lambda k, i: row[k] if not isinstance(row, tuple) else row[i])
    return Summary(slide=slide, headline=g("headline", 0), body=g("body", 1),
                   from_cache=True)


def save(conn, facility: str, slide: str, b: dict, s: Summary) -> None:
    fid = _facility_id(conn, facility)
    if fid is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO slide_summary"
        "(facility_id, slide, fact_hash, model, headline, body)"
        " VALUES (?,?,?,?,?,?)",
        (fid, slide, fact_hash(facts_for(slide, b)), model_name(),
         s.headline, s.body),
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
