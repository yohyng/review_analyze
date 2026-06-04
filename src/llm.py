"""Step 8: LLM insight generation via Anthropic API.

Input  : TextProfile (⑦) + score diff Series (⑥)
Output : InsightResult — まとめ / 強み / 弱み / 示唆 / 改善提案
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class InsightResult:
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    implications: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    raw: str = ""
    error: str = ""


def get_api_key() -> str:
    """Resolve API key: env var → streamlit secrets → empty string."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        import streamlit as st  # noqa: PLC0415
        return st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        return ""


def build_prompt(
    facility_name: str,
    score_diff: pd.Series | None,
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
    low_block = "\n".join(f"  ・{r[:200]}" for r in low_reviews[:3]) or "（なし）"
    kw_block = "、".join(tfidf_keywords[:15]) or "（なし）"
    phrase_block = "、".join(bigrams[:10]) or "（なし）"

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


def generate_insights(prompt: str, api_key: str) -> InsightResult:
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return InsightResult(error="anthropic ライブラリが見つかりません。pip install anthropic")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
    except Exception as e:  # noqa: BLE001
        return InsightResult(error=f"API エラー: {e}")

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
