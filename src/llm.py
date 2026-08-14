"""Step 8: LLM insight generation via Google Gemini API (REST).

Uses requests directly — no extra SDK needed (google-generativeai has
heavy gRPC deps that can break in restricted environments).

Free tier: Gemini 1.5 Flash — 15 RPM / 1M tokens per day.
API key  : https://aistudio.google.com/  (Google account, instant)

Input  : TextProfile (⑦) + score diff Series (⑥)
Output : InsightResult — まとめ / 強み / 弱み / 示唆 / 改善提案
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import pandas as pd
import requests

GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


@dataclass
class InsightResult:
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    implications: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    raw: str = ""
    error: str = ""


# --------------------------------------------------------------------------- #
# API key resolution
# --------------------------------------------------------------------------- #
def get_api_key() -> str:
    """Resolve key: env var GEMINI_API_KEY → streamlit secrets → ''."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    try:
        import streamlit as st  # noqa: PLC0415
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Prompt builder
# --------------------------------------------------------------------------- #
def build_prompt(
    facility_name: str,
    score_diff: "pd.Series | None",
    tfidf_keywords: list[str],
    bigrams: list[str],
    high_reviews: list[str],
    low_reviews: list[str],
) -> str:
    def _score_block() -> str:
        if score_diff is None or score_diff.empty:
            return "（スコアデータなし）"
        lines = []
        for metric, val in score_diff.sort_values(ascending=False).items():
            mark = "▲" if val >= 0 else "▼"
            lines.append(f"  {mark} {metric}: {val:+.1f}pt")
        return "\n".join(lines)

    high_block = "\n".join(f"  ・{r[:200]}" for r in high_reviews[:3]) or "（なし）"
    low_block  = "\n".join(f"  ・{r[:200]}" for r in low_reviews[:3])  or "（なし）"
    kw_block   = "、".join(tfidf_keywords[:15]) or "（なし）"
    phrase_block = "、".join(bigrams[:10])       or "（なし）"

    return f"""あなたは施設の口コミ分析の専門家です。以下のデータをもとに分析レポートを作成してください。

【対象施設】{facility_name}

【スコア比較（比較施設との差分 / pt、正=優位）】
{_score_block()}

【特徴的なキーワード（TF-IDF上位）】
{kw_block}

【頻出フレーズ】
{phrase_block}

【高評価の口コミ（抜粋）】
{high_block}

【低評価の口コミ（抜粋）】
{low_block}

以下のJSON形式のみを出力してください（前後に説明文・コードブロック不要）：
{{
  "まとめ": "施設全体の特徴を2〜3文で要約",
  "強み": ["強み1", "強み2", "強み3"],
  "弱み": ["弱み1", "弱み2", "弱み3"],
  "示唆": ["示唆1", "示唆2"],
  "改善提案": ["提案1", "提案2", "提案3"]
}}"""


# --------------------------------------------------------------------------- #
# API call
# --------------------------------------------------------------------------- #
def generate_insights(prompt: str, api_key: str) -> InsightResult:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1500,
        },
    }
    try:
        resp = requests.post(
            GEMINI_ENDPOINT,
            params={"key": api_key},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        msg = _extract_api_error(resp)
        return InsightResult(error=f"API エラー ({resp.status_code}): {msg}")
    except requests.exceptions.RequestException as e:
        return InsightResult(error=f"通信エラー: {e}")

    try:
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        return InsightResult(error=f"レスポンスの解析に失敗: {e}", raw=resp.text)

    # strip ``` fences if the model wrapped the JSON
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = m.group(1).strip() if m else raw

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return InsightResult(raw=raw, error="JSONの解析に失敗しました。rawを確認してください。")

    return InsightResult(
        summary=data.get("まとめ", ""),
        strengths=data.get("強み", []),
        weaknesses=data.get("弱み", []),
        implications=data.get("示唆", []),
        improvements=data.get("改善提案", []),
        raw=raw,
    )


# --------------------------------------------------------------------------- #
# 汎用: Gemini に JSON を返させる
# --------------------------------------------------------------------------- #
def call_json(prompt: str, api_key: str, *, max_tokens: int = 1500,
              temperature: float = 0.3):
    """Gemini を呼び、JSON をパースして返す。失敗時は (None, エラー文字列)。

    Returns (data, error)。data は dict か list。
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    try:
        resp = requests.post(GEMINI_ENDPOINT, params={"key": api_key},
                             json=payload, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        return None, f"API エラー ({resp.status_code}): {_extract_api_error(resp)}"
    except requests.exceptions.RequestException as e:
        return None, f"通信エラー: {e}"

    try:
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        return None, f"レスポンスの解析に失敗: {e}"

    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    try:
        return json.loads(m.group(1).strip() if m else raw), ""
    except json.JSONDecodeError:
        return None, "JSONの解析に失敗しました"


# --------------------------------------------------------------------------- #
# SLIDE 4「時間軸分析」— 変化点で何が起きたかを口コミから説明させる
# --------------------------------------------------------------------------- #
def explain_change_points(facility_name: str, points: list, api_key: str) -> str:
    """変化点の見出し・説明文を LLM に書かせて ChangePoint に埋める。

    points は timeline.ChangePoint のリストで、各要素に `_reviews`
    （[(rating, text), ...]）を持たせておくこと。成功時は cp.title / cp.body /
    cp.keywords を埋めて "" を返し、失敗時はエラー文字列を返す（呼び出し側で
    timeline.fallback_description に落とす）。

    **影響の大きさ（delta_pt）は渡すだけで、生成させない。**
    数値をモデルに作らせると根拠のない値がレポートに載るため。
    """
    if not points:
        return ""

    blocks = []
    for i, cp in enumerate(points, 1):
        revs = getattr(cp, "_reviews", [])[:25]
        body = "\n".join(
            f"  - ★{r if r is not None else '-'}: {str(txt)[:120]}" for r, txt in revs
        ) or "  （本文のある口コミなし）"
        move = "上昇" if cp.direction == "up" else "低下"
        blocks.append(
            f"[変化点{i}] {cp.ym}（口コミ {cp.n_reviews} 件・"
            f"直前3か月比で平均評価が {cp.delta_pt:+.2f}pt {move}）\n{body}"
        )

    prompt = f"""あなたは施設の口コミを分析するアナリストです。
「{facility_name}」について、評価が動いた月とその月の口コミを渡します。
各変化点で「何が起きたか」を口コミの内容だけから読み取ってください。

制約:
- 口コミに書かれていないことを推測しない。読み取れない場合は
  title を「要因は特定できず」とし、body にその旨を書く。
- 数値（pt・件数・割合）は一切書かない。こちらで別途付与する。
- title は8〜14字程度の体言止め（例:「混雑の増加」「新展示の導入」「価格改定」）。
- body は60〜90字で、その月の口コミに現れた具体的な事象を書く。
- keywords は口コミに実際に出てきた語を3つまで。

出力は次の形式のJSONのみ（説明文やコードフェンスは不要）:
[{{"title": "...", "body": "...", "keywords": ["...", "..."]}}, ...]
要素数は変化点の数（{len(points)}件）と同じ順序で返すこと。

{chr(10).join(blocks)}
"""
    data, err = call_json(prompt, api_key, max_tokens=1200)
    if err:
        return err
    if not isinstance(data, list) or len(data) != len(points):
        return "変化点の数と生成結果の数が一致しませんでした"

    for cp, item in zip(points, data):
        if not isinstance(item, dict):
            return "生成結果の形式が不正です"
        cp.title = str(item.get("title", "")).strip()
        cp.body = str(item.get("body", "")).strip()
        kw = item.get("keywords") or []
        cp.keywords = [str(k) for k in kw][:3] if isinstance(kw, list) else []
    return ""


# --------------------------------------------------------------------------- #
# SLIDE 6「特徴的な口コミ」— 4象限の代表口コミを選ばせ、属性を推定させる
# --------------------------------------------------------------------------- #
def pick_voice_quadrants(facility_name: str, reviews: list, api_key: str):
    """4象限それぞれの代表口コミを LLM に選ばせる。

    reviews は [(rating, text), ...]。返り値は (data, error)。
    data は voices.apply_llm_result() に渡す形式。

    **本文を創作させない。** 選ぶのは口コミの index で、quote はその本文
    からの逐語抜粋に限る（呼び出し側で実在を検証する）。属性は口コミの書きぶり
    からの推定であり、書かれていなければ空にさせる。

    summary（見出し用の1行）だけは生成させる。ただしスライドには生データを
    そのまま併記するので、読み手は必ず原文に当たれる。
    """
    from . import voices  # noqa: PLC0415

    pool = [(i, r, str(t).strip()) for i, (r, t) in enumerate(reviews)
            if t and str(t).strip()][:60]
    if not pool:
        return None, "本文のある口コミがありません"

    listing = "\n".join(
        f"[{i}] ★{r if r is not None else '-'} {t[:160]}" for i, r, t in pool
    )
    quads = "\n".join(f"- {name}: {desc}" for name, desc in voices.QUADRANTS)

    prompt = f"""あなたは施設の口コミを分析するアナリストです。
「{facility_name}」の口コミから、次の4つの観点それぞれを最もよく表す口コミを
1件ずつ選んでください。

観点（この順序で返すこと）:
{quads}

制約:
- 選ぶのは番号（index）です。**本文そのものを創作してはいけません。**
- summary は選んだ口コミが何を言っているかを 40 字以内で1行にまとめたもの。
  資料の見出しに使うので、体言止め・簡潔に。**書かれていない事実を足さない。**
- quote は選んだ口コミの本文から、そのまま抜き出した連続する一節にすること
  （語順を変えたり要約したりしない）。60字以内。
- age / gender / companion は口コミの書きぶりから推定できる場合だけ書く。
  推定できない場合は必ず空文字 "" にすること。憶測で埋めない。
  age は「20代」「30代」など、gender は「男性」「女性」、
  companion は「ファミリー」「カップル」「友人」「ひとり」など。
- 同じ口コミを複数の観点に使わないこと。
- 該当する口コミが無い観点は index を -1 にすること。

出力は次の形式のJSONのみ（説明文やコードフェンスは不要）:
[{{"index": 0, "summary": "...", "quote": "...", "age": "", "gender": "", "companion": ""}}, ...]

口コミ一覧:
{listing}
"""
    data, err = call_json(prompt, api_key, max_tokens=1200)
    if err:
        return None, err

    # listing は元の reviews の index をそのまま出しているので変換は不要。
    # （voices.apply_llm_result 側で範囲外の index は空カードに落とす）
    return data, ""


# --------------------------------------------------------------------------- #
# SLIDE 7「ディスカッションポイント」— 企画仮説と打ち手を書かせる
# --------------------------------------------------------------------------- #
def build_discussion_points(facility_name: str, issues: list, api_key: str,
                            samples: list | None = None):
    """課題ごとの根拠・企画仮説・対応領域と、打ち手アクションを生成させる。

    issues は discussion.Issue のリスト（スコアと差は算出済み）。
    返り値は (data, error)。data は discussion.apply_llm_result() に渡す形式。

    **数値・優先度・インパクトは渡すだけで生成させない。**
    LLM が担うのは文章と「実現しやすさ」の見立てだけ。
    """
    if not issues:
        return None, "課題がありません"

    listing = "\n".join(
        f"[{i}] {iss.topic}: 自施設 {iss.score5:.2f} / "
        f"{iss.base_label} {iss.base5:.2f}（差 {iss.gap5:+.2f}pt・優先度 {iss.priority}）"
        for i, iss in enumerate(issues)
    )
    voice = ""
    if samples:
        voice = "\n参考（実際の口コミ抜粋）:\n" + "\n".join(
            f"  - ★{r if r is not None else '-'}: {str(txt)[:110]}"
            for r, txt in samples[:20]
        )

    prompt = f"""あなたは商業・文化施設の企画コンサルタントです。
「{facility_name}」の口コミ分析から、次の課題が抽出されました。
これをもとに、企画会議で議論するための材料を作ってください。

課題（スコアは5点満点。数値はこちらで算出済み）:
{listing}
{voice}

制約:
- **新しい数値（pt・件数・％・順位）を書かないこと。** 数値はこちらで付与する。
- evidence は、その課題を裏づける定性的な事実を口コミから1文で。
  口コミから読み取れない場合は「口コミからは要因を特定できず」と書く。
- hypothesis は、なぜそうなっているかの企画仮説を2文以内で。断定を避ける。
- domains は対応領域のタグを2つ（例:「体験設計・演出」「価格・チケット設計」
  「再訪施策・CRM」「コンテンツ・ストーリー」「情報提供・サイン」）。
- actions は課題と同じ数・同じ順序。title は12字以内の施策名、
  bullets は具体的な打ち手を3つ（各30字以内）。
- feasibility は実現しやすさを 0.0〜1.0 で。大型投資が要るものほど小さく。

出力は次の形式のJSONのみ（説明文やコードフェンスは不要）:
{{"issues": [{{"evidence": "...", "hypothesis": "...", "domains": ["...", "..."]}}],
  "actions": [{{"title": "...", "bullets": ["...", "...", "..."],
                "feasibility": 0.7}}]}}
"""
    return call_json(prompt, api_key, max_tokens=2000)


def _extract_api_error(resp: requests.Response) -> str:
    try:
        return resp.json().get("error", {}).get("message", resp.text[:200])
    except Exception:
        return resp.text[:200]
