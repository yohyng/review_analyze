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


def _extract_api_error(resp: requests.Response) -> str:
    try:
        return resp.json().get("error", {}).get("message", resp.text[:200])
    except Exception:
        return resp.text[:200]
