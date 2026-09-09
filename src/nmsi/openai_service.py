from __future__ import annotations

import json
import os
from collections.abc import Iterable

import numpy as np
from openai import OpenAI

from .models import (
    ClusterNameBatch,
    SentenceBatch,
    VisitorClusterNameBatch,
    VisitorPatternBatch,
)


EXTRACTION_SYSTEM_PROMPT = """
あなたは施設クチコミの構造化抽出器です。
入力済みの各文は、すでに意味単位へ分割されています。

目的:
1. 文の体験フェーズ、感情極性、強度、補正要素を数値化する。
2. 文中に実際に現れる「場所と思われる名詞句」を抽出する。

場所抽出のルール:
- 施設により固有の場所名が異なるため、場所辞書は使わない。
- 原文に明記された建物部分、エリア、展示、遊び場、劇場、店舗、設備、
  サービス地点、外周・駐車場などを抽出する。
- 「ショー」「イベント」は、それが開催空間・体験地点を指す文脈なら抽出可能。
- 人物、感情、商品単体、抽象価値だけを場所として抽出しない。
- 原文に場所がない場合、place_mentionsは空配列にする。
- surface_formには原文の表現をできるだけ保持する。
- place_functionには感情を入れず、その場所の機能だけを書く。
- 1文に複数場所があれば複数抽出する。
- 場所を推測で捏造しない。

フェーズ:
- pre_visit: 来館前の期待、予約、情報収集
- arrival: 交通、駐車、外周、入口、受付、チケット
- exhibition: 展示鑑賞、空間、館内設備、休憩、授乳・おむつ替え
- experience: 遊び、操作、ワークショップ、水遊びなどの身体参加
- show_interaction: ショー、劇場、キャラクター交流、感情ピーク
- food_retail: レストラン、カフェ、食品、土産、ショップ、物販
- exit_reflection: 出口、帰宅後、思い出、再訪・推奨、総支出の振り返り

採点:
- sentimentは-1から+1。事実記述だけなら0。
- intensityは評価表現の強さ。confidenceは文から判断できる確信度。
- memory, self_relation, revisit, recommendは0から1。
- wait, congestion, restriction, expectation_gap, cost_burden,
  information_gapも0から1。
- 根拠がなければ必ず0。推測で埋めない。
- positive_summaryとnegative_summaryは原文根拠を短く要約し、
  該当しなければ空文字。
- source_indexは入力のindexをそのまま返す。
"""


NAMING_SYSTEM_PROMPT = """
あなたは施設の場所クラスター命名器です。
辞書ではなく、クラスタリングで集まった場所表現・機能説明・根拠文だけから命名します。

ルール:
- 各provisional_cluster_idを1件ずつ必ず返す。
- place_nameは、そのクラスターを最もよく代表する簡潔な場所名にする。
- 固有名詞が複数の根拠文に現れる場合は固有名詞を優先する。
- 固有名詞が安定しない場合は「入口・チケット」「レストラン・飲食」のような機能名にする。
- 異なる場所を無理に一つの名前にしない。
- positive_summaryとnegative_summaryは提示された根拠だけを要約する。
- 根拠がなければ空文字にする。
- phaseは来館体験上の位置から選ぶ。
"""


VISITOR_PATTERN_PROMPT_VERSION = "visitor-pattern-v1.0"

VISITOR_PATTERN_SYSTEM_PROMPT = """
あなたは施設クチコミから来場状況・期待・体験パターンを構造化する抽出器です。
この出力は後段の教師なしクラスタリングの入力であり、あなた自身は来場者クラスターを
作成・命名してはいけません。

入力はreview_id単位にまとめられた複数の分割済み文です。

採点ルール:
- 各軸は0から1。0は原文から明確に否定される、1は明確に強く該当する。
- 原文に判断根拠がない軸はnullにする。無言及を0として扱わない。
- 利用者属性、来館目的、期待、実体験、摩擦、行動意向を混同しない。
- 「子どもが夢中」はattributes.family_with_childrenと
  experienced_values.immersionの根拠になり得るが、期待の根拠にはしない。
- 「また来たい」はbehavior_intentions.revisitの根拠であり、実際に再訪した証拠ではない。
- 「高い」は文脈を確認し、料金への不満ならfrictions.costを高くし、
  experienced_values.price_acceptanceを低くする。
- 複数の相反する記述がある場合は両方を考慮した中間値にする。
- overall_satisfactionは0が強い不満、1が強い満足。根拠がなければnull。
- extraction_confidenceは、レビュー全体からこの構造を判断できる確信度。
- evidenceには判断根拠となる原文を最大6件入れる。
- review_idは入力値を正確に返す。
- 人物像やクラスター名称を生成しない。
"""

VISITOR_CLUSTER_NAMING_PROMPT = """
あなたは、教師なしアルゴリズムが生成した来場者体験パターンクラスターの命名器です。
クラスター所属はすでに数値計算で確定しているため、所属変更・再分類をしてはいけません。

入力される上位特徴、低位特徴、摩擦、代表クチコミ、満足度から次を生成してください。
- cluster_name: 「子連れ体験適合層」のような簡潔な名称
- main_traits: 数値特徴に基づく主な特徴
- likely_visit_context: 断定せず、根拠のある来場状況
- satisfaction_structure: 何が満足・不満を作っているか
- improvement_direction: 施設改善またはマーケティング改善の方向

提示されていない年齢・属性・目的を推測で追加しないでください。
各provisional_cluster_idを1回ずつ必ず返してください。
"""


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY が設定されていません。")
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def analyze_sentence_batch(records: list[dict]) -> SentenceBatch:
    model = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o")
    response = _client().beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "次のJSON配列を分析してください。source_indexはindexと同じ値を返してください。\n"
                    + json.dumps(records, ensure_ascii=False)
                ),
            },
        ],
        response_format=SentenceBatch,
    )
    result = response.choices[0].message.parsed
    if result is None:
        raise RuntimeError("文章分析の構造化出力を取得できませんでした。")
    return result


def name_clusters(records: list[dict]) -> ClusterNameBatch:
    model = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o")
    response = _client().beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": NAMING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "次の場所クラスターを命名してください。\n"
                    + json.dumps(records, ensure_ascii=False)
                ),
            },
        ],
        response_format=ClusterNameBatch,
    )
    result = response.choices[0].message.parsed
    if result is None:
        raise RuntimeError("クラスター命名の構造化出力を取得できませんでした。")
    return result


def analyze_visitor_patterns(records: list[dict]) -> VisitorPatternBatch:
    model = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o")
    response = _client().beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": VISITOR_PATTERN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"prompt_version={VISITOR_PATTERN_PROMPT_VERSION}\n"
                    "次のreview_id別データを構造化してください。\n"
                    + json.dumps(records, ensure_ascii=False)
                ),
            },
        ],
        response_format=VisitorPatternBatch,
    )
    result = response.choices[0].message.parsed
    if result is None:
        raise RuntimeError("来場者体験パターンの構造化出力を取得できませんでした。")
    return result


def name_visitor_clusters(records: list[dict]) -> VisitorClusterNameBatch:
    model = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o")
    response = _client().beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": VISITOR_CLUSTER_NAMING_PROMPT},
            {
                "role": "user",
                "content": (
                    "次の確定済みクラスターを命名してください。\n"
                    + json.dumps(records, ensure_ascii=False)
                ),
            },
        ],
        response_format=VisitorClusterNameBatch,
    )
    result = response.choices[0].message.parsed
    if result is None:
        raise RuntimeError("来場者クラスター名を取得できませんでした。")
    return result


def embed_texts(texts: Iterable[str], batch_size: int = 128) -> np.ndarray:
    values = list(texts)
    if not values:
        return np.empty((0, 0), dtype=np.float32)
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    client = _client()
    rows: list[list[float]] = []
    for start in range(0, len(values), batch_size):
        batch = values[start: start + batch_size]
        response = client.embeddings.create(model=model, input=batch)
        rows.extend(item.embedding for item in response.data)
    matrix = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)
