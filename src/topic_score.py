"""感情・トピック統合スコア算出モデル（このモデルを「正」とする実装）。

アップロードされた仕様書 `sentiment_topic_score_model` を Python に忠実移植したもの。
クチコミを文単位に分解し、各文について「感情値」と「トピック確率」を算出、
レビュー単位・トピック単位・施設全体単位へ集計して独自の統合スコアを出す。

  文 → 感情分析 → 温度スケーリング → 非線形補正 → v_sentiment ∈ [0,1]
  文 → 埋め込み → コサイン類似 → z-score → 適応温度 → softmax → Top-kブースト → p_topic
  文×トピックスコア = v_sentiment × p_topic
  → レビュー内平均 → 重み合算 → 全レビュー平均 → トピック平均 → 重み → 全体スコア

バックエンド:
  * 感情    : キーワード辞書ベース（軽量・torch不要）。BERT へ差し替え可能な設計。
  * 埋め込み: 共有 TF-IDF 空間でのコサイン類似（軽量・torch不要）。
              sentence-transformers があれば SBERT に差し替え可能。

Streamlit Cloud 無料枠でも動くよう、既定は軽量バックエンド。数式（モデル本体）は
バックエンドに依存せず一意。
"""
from __future__ import annotations

import re
import hashlib as _hashlib
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from . import text_analysis


# ═══════════════════════════════════════════════════════════════════════════
# 第1章 — 感情スコア（文単位）  ※仕様書に忠実
# ═══════════════════════════════════════════════════════════════════════════
def keyword_sentiment_probs(
    text: str,
    positive_words: List[str],
    negative_words: List[str],
) -> np.ndarray:
    """キーワード出現数から3クラス確率 [p_neg, p_neu, p_pos] を生成。"""
    pos_count = sum(text.count(w) for w in positive_words)
    neg_count = sum(text.count(w) for w in negative_words)

    s_raw = (pos_count - neg_count) / (pos_count + neg_count + 1)

    p_neu = max(0.1, 1 - abs(s_raw))
    p_pos = (1 - p_neu) * (s_raw + 1) / 2
    p_neg = (1 - p_neu) * (1 - s_raw) / 2

    probs = np.array([p_neg, p_neu, p_pos])
    probs = probs / probs.sum()
    return probs


def temperature_scaling(probs: np.ndarray, T: float = 0.7) -> np.ndarray:
    """Softmax 温度スケーリングで確率分布をシャープ化（T=0.7）。"""
    probs = np.clip(probs, 1e-12, 1.0)

    logits = np.log(probs)
    scaled_logits = logits / T

    scaled_logits = scaled_logits - np.max(scaled_logits)
    exp_values = np.exp(scaled_logits)
    return exp_values / exp_values.sum()


def sentiment_value(probs: np.ndarray, alpha: float = 0.7) -> float:
    """probs=[p_neg,p_neu,p_pos] → 感情値 v_sentiment ∈ [0,1]（0.5=中立）。"""
    scaled_probs = temperature_scaling(probs)

    p_neg = scaled_probs[0]
    p_pos = scaled_probs[2]

    s_raw = p_pos - p_neg
    s = np.sign(s_raw) * (abs(s_raw) ** alpha)   # 非線形補正（中庸値を分散）

    v_sentiment = (s + 1) / 2
    return float(v_sentiment)


# ═══════════════════════════════════════════════════════════════════════════
# 第2章 — トピック確率（Sentence-BERT 方式の数式）  ※仕様書に忠実
# ═══════════════════════════════════════════════════════════════════════════
def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def topic_probabilities(
    sentence_embedding: np.ndarray,
    topic_embeddings: np.ndarray,
    boost_factor: float = 0.5,
) -> np.ndarray:
    """文埋め込み × トピック埋め込み群 → トピック確率ベクトル（合計1）。"""
    similarities = np.array([
        cosine_similarity(sentence_embedding, topic_embedding)
        for topic_embedding in topic_embeddings
    ])

    c_mean = similarities.mean()
    c_std = similarities.std()

    z_scores = (similarities - c_mean) / (c_std + 1e-6)

    # 適応的温度：話題が明確（分散大）なほど尖らせる
    T = np.clip(0.3 / (c_std + 1e-6), 0.05, 0.7)

    logits = z_scores / T
    logits = logits - np.max(logits)
    exp_values = np.exp(logits)
    p = exp_values / exp_values.sum()

    # Top-k ブースト（baseline = 1/N を超えたトピックを強調）
    N = len(topic_embeddings)
    baseline = 1 / N
    boost = np.maximum(p - baseline, 0) * boost_factor
    p_boost = p + boost
    p_final = p_boost / p_boost.sum()
    return p_final


# ═══════════════════════════════════════════════════════════════════════════
# 第3〜6章 — 集計  ※仕様書に忠実
# ═══════════════════════════════════════════════════════════════════════════
def sentence_topic_score(v_sentiment: float, p_topics: np.ndarray) -> np.ndarray:
    """文×トピックスコア = 感情値 × トピック確率。"""
    return v_sentiment * p_topics


def review_topic_average(sentence_scores: np.ndarray) -> np.ndarray:
    """sentence_scores: [文数, トピック数] → トピック別平均 [トピック数]。"""
    return np.mean(sentence_scores, axis=0)


def review_total_score(review_topic_scores: np.ndarray, topic_weights: np.ndarray) -> float:
    return float(np.sum(review_topic_scores * topic_weights))


def aggregate_all_reviews(
    all_review_topic_scores: np.ndarray,
    topic_weights: np.ndarray,
) -> dict:
    """all_review_topic_scores: [レビュー数, トピック数]。"""
    avg_score_t = np.mean(all_review_topic_scores, axis=0)
    total_score_t = avg_score_t * topic_weights
    overall_score = np.sum(total_score_t)
    return {
        "avg_score_t": avg_score_t,
        "total_score_t": total_score_t,
        "overall_score": float(overall_score),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 指標軸（トピック定義）と感情辞書  — 施設クチコミ向けの既定セット
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class TopicDef:
    name: str
    keywords: List[str]
    weight: float
    desc: str = ""          # この観点が何を測っているか（画面のツールチップ用）


# 評価軸 25 項目。**原典は利用部門の「20261116 評価軸一覧」**（2026-11-26 受領）
# で、軸名・定義・重みはそのファイルの値をそのまま使っている。重みの合計は 1.0。
#
# 判定キーワードは原典に無い（原典は軸の定義だけ）。ここが**この実装の推定部分**。
# 日本語の口コミ本文に対する部分一致で数えるので、誤爆しやすい語は入れない。
#
# 旧 22 軸からの変更（2026-11-26）:
#   追加 5 … 最新性 / 情報性 / レイアウト / 雰囲気 / ロイヤリティ
#   削除 2 … 空間の質感（語は「デザインクオリティ」へ）
#            ブランドの歴史性（語は「信頼度」へ。長年の実績＝信頼と扱う）
#   改名   … 提供内容の品質→品質、情報提供→分かりやすさ、美的完成度→
#            デザインクオリティ、空間の感情的インパクト→インパクト、
#            立地・アクセス→アクセスの利便性、ブランド信頼感→信頼度 ほか
# 軸を変えたらキャッシュを作り直させること（TOPICS_VERSION）。
DEFAULT_TOPICS: List[TopicDef] = [
    # ── コンテンツ ──────────────────────────────────────────────── #
    TopicDef("品質", [
        "品質", "クオリティ", "完成度", "仕上がり", "出来", "美味しい",
        "おいしい", "上質", "良質", "料理", "商品", "味",
    ], 0.025,
        "コンテンツが魅力的に見えるか"),
    TopicDef("多様性", [
        "種類", "豊富", "バリエーション", "品揃え", "多彩", "選択肢",
        "ラインナップ", "多様", "いろいろ", "幅広い",
    ], 0.025,
        "コンテンツの種類が豊富か。また内容の幅が広いか"),
    TopicDef("独自性", [
        "独自", "オリジナル", "個性", "ユニーク", "唯一", "特別",
        "こだわり", "他にない", "ここだけ", "斬新",
    ], 0.025,
        "その施設ならではで他施設にはないコンテンツになっているか"),
    TopicDef("最新性", [
        "最新", "流行", "トレンド", "今風", "現代的", "話題",
        "新しい技術", "先端", "イマドキ",
    ], 0.025,
        "コンテンツの内容が時代の流行を反映しているか"),
    TopicDef("更新性", [
        "新作", "季節", "限定", "リニューアル", "更新", "新メニュー",
        "旬", "入れ替え", "展示替え", "企画展",
    ], 0.025,
        "コンテンツが定期的に変化しているか"),
    TopicDef("情報性", [
        "詳しい", "詳細", "深い", "マニア", "初心者", "子どもでも",
        "勉強になる", "学べ", "知識", "読み応え", "解説",
    ], 0.025,
        "素人から玄人までどんな層にも満足できる情報があるか"),
    TopicDef("分かりやすさ", [
        "分かりやすい", "わかりやすい", "案内", "説明", "表示", "掲示",
        "看板", "告知", "アナウンス", "理解",
    ], 0.025,
        "コンテンツ内容をすぐに理解できるか"),
    # ── 空間設計 ────────────────────────────────────────────────── #
    TopicDef("レイアウト", [
        "レイアウト", "配置", "動線", "順路", "導線", "並び",
        "見やすい配置", "回りやすい",
    ], 0.05,
        "分かりやすい配置になっているか"),
    TopicDef("機能性", [
        "機能", "使いやすい", "広さ", "設備", "使い勝手", "コンセント",
        "収納", "トイレ", "ベビーカー", "バリアフリー",
    ], 0.05,
        "空間の設備がその目的を十分に果たせるかどうか。"
        "より質の高い機能を提供できているか"),
    TopicDef("快適さ", [
        "快適", "居心地", "静か", "落ち着く", "リラックス", "ゆったり",
        "過ごしやすい", "静粛", "寛げ", "癒",
    ], 0.05,
        "目的をストレスなく達成できるか"),
    TopicDef("デザインクオリティ", [
        "美しい", "おしゃれ", "デザイン", "洗練", "綺麗", "きれい",
        "映え", "スタイリッシュ", "美的", "上品",
        "質感", "素材", "内装", "高級感", "重厚",
    ], 0.05,
        "無駄なく磨かれ、上品で完成された状態にあるか"),
    TopicDef("雰囲気", [
        "雰囲気", "空気感", "ムード", "趣", "風情", "情緒",
        "荘厳", "厳か", "世界観", "たたずまい",
    ], 0.05,
        "足を踏み入れたときに感じる空気感や印象が良いか"),
    TopicDef("インパクト", [
        "感動", "印象的", "圧巻", "驚き", "没入", "記憶",
        "特別感", "感激", "非日常", "迫力",
    ], 0.05,
        "印象に残る空間になっているか"),
    # ── サービス ────────────────────────────────────────────────── #
    TopicDef("スタッフ対応", [
        "接客", "スタッフ", "店員", "従業員", "対応", "丁寧", "親切",
        "笑顔", "気配り", "態度", "愛想", "ホスピタリティ",
    ], 0.05,
        "適切なコミュニケーションが取れているか。"
        "発生した問題に対して臨機応変に対応ができているか"),
    TopicDef("スタッフ専門性", [
        "専門", "詳しい説明", "プロ", "的確", "技術",
        "経験", "熟練", "ソムリエ", "コンシェルジュ", "学芸員",
    ], 0.05,
        "専門性の高い対応ができているか"),
    TopicDef("サービス種類", [
        "サービス", "特典", "オプション", "送迎", "貸出", "アメニティ",
        "サービス内容", "無料", "プラン",
    ], 0.025,
        "来場者の様々な課題に対する解決策を用意できているか"),
    # ── 価格・決済 ──────────────────────────────────────────────── #
    TopicDef("料金の適正さ", [
        "価格", "値段", "料金", "適正", "高い", "安い", "妥当",
        "コスパ", "割高", "見合う", "リーズナブル",
    ], 0.025,
        "サービスや体験に対する価格設定の妥当性"),
    TopicDef("料金・決済のサービス多様性", [
        "割引", "クーポン", "支払い", "決済", "カード", "キャッシュレス",
        "ポイント", "会計", "精算", "電子マネー",
    ], 0.025,
        "割引や特典サービスがある。多様な料金支払い方法が用意されている"),
    # ── アクセス ────────────────────────────────────────────────── #
    TopicDef("アクセスの利便性", [
        "立地", "アクセス", "駅", "場所", "近い", "便利", "遠い",
        "駐車場", "徒歩", "ロケーション", "最寄り",
    ], 0.05,
        "アクセスしやすい場所があるか"),
    # ── ブランド ────────────────────────────────────────────────── #
    TopicDef("信頼度", [
        "信頼", "安心", "安定", "ブランド", "実績", "定評", "さすが",
        "期待通り", "間違いない", "信用",
        "歴史", "伝統", "老舗", "長年", "地域",
    ], 0.05,
        "社会的責任、地域貢献に役立っているか"),
    TopicDef("ロイヤリティ", [
        "常連", "通って", "通い", "お気に入り", "ファン", "毎年",
        "何度も", "愛着", "ひいき", "定期的に",
    ], 0.05,
        "施設やサービスに対する再訪意向・継続利用・愛着・信頼など、"
        "長期的な関係性の強さ"),
    # ── 総合評価 ────────────────────────────────────────────────── #
    TopicDef("体験満足度", [
        "満足", "大満足", "良かった", "最高", "楽しい", "素晴らしい",
        "感謝", "幸せ", "充実",
    ], 0.05,
        "体験にどれくらい満足したか"),
    TopicDef("比較優位性", [
        "一番", "比べ", "より良い", "優れ", "ダントツ",
        "群を抜", "ナンバーワン", "随一",
    ], 0.05,
        "他施設・類似体験より優れていると感じたか"),
    TopicDef("推奨意向", [
        "おすすめ", "勧め", "紹介", "教えたい", "ぜひ", "推薦", "人に",
    ], 0.05,
        "他者に勧めたいか"),
    TopicDef("再訪意向", [
        "また", "リピート", "再訪", "また来", "また行", "次回",
    ], 0.05,
        "もう一度訪れたいか"),
]

# 軸の構成が変わったことをキャッシュに知らせる鍵。
#   topic_score_cache は (施設, 口コミ件数) だけを鍵にしていたので、軸を
#   入れ替えても**古い結果が返り続けていた**（2026-11-26 に気づいた）。
#   名前と重みから作るので、軸を足す・重みを変えるだけで自動的に変わる。
TOPICS_VERSION: str = _hashlib.sha1(
    "|".join(f"{t.name}:{t.weight}" for t in DEFAULT_TOPICS).encode("utf-8")
).hexdigest()[:8]

# SLIDE 02 のラベル順（全体を末尾に）
TOPIC_ORDER: List[str] = [t.name for t in DEFAULT_TOPICS]

# 「体験満足度 / 推奨意向 / 再訪意向」は施設の打ち手ではなく、体験の結果として
# 現れる outcome 指標。施設を横並びで比較する SLIDE 3 では、差の原因になりうる
# driver 側だけを見たいので、この3つを除いたものを「主要指標」とする。
# **数は直書きしないこと。** 原典の軸が増減したら画面のラベルも len() で出す。
OUTCOME_TOPICS: List[str] = ["体験満足度", "推奨意向", "再訪意向"]
DRIVER_TOPICS: List[str] = [t for t in TOPIC_ORDER if t not in OUTCOME_TOPICS]

# SLIDE 5「空間・体験分析」で扱う軸。原典の7カテゴリのうち
# 「コンテンツ」「空間設計」に属するもの（2026-11-15 デッキ 10P の指示
# 「この評価軸で入れる」に合わせた）。**数を直書きしないこと**。
# 軸が増減したら画面のラベルも len() から出す。
def _space_topics() -> List[str]:
    from . import categories as _cat  # noqa: PLC0415

    want = set(_cat.CATEGORIES["コンテンツ"]) | set(_cat.CATEGORIES["空間設計"])
    return [t for t in TOPIC_ORDER if t in want]


SPACE_TOPICS: List[str] = _space_topics()
OVERALL_LABEL = "全体"

POSITIVE_WORDS: List[str] = [
    "良い", "よい", "いい", "素晴らしい", "最高", "美味しい", "おいしい",
    "快適", "楽しい", "満足", "親切", "丁寧", "綺麗", "きれい", "清潔",
    "おすすめ", "好き", "便利", "広い", "新しい", "優しい", "感動",
    "また来", "リピート", "大満足", "癒", "落ち着", "居心地", "笑顔",
    "コスパ", "安い", "お得", "早い", "スムーズ", "豊富", "充実",
    "こだわり", "本格", "絶品", "ボリューム", "リーズナブル", "おしゃれ",
]

NEGATIVE_WORDS: List[str] = [
    "悪い", "残念", "不満", "狭い", "汚い", "遅い", "最悪", "ひどい",
    "がっかり", "いまいち", "イマイチ", "微妙", "不便", "古い", "うるさい",
    "混雑", "待たさ", "雑", "冷たい", "無愛想", "二度と", "期待外れ",
    "割高", "物足り", "クレーム", "不快", "まずい", "不親切", "乱雑",
    "高すぎ", "並ぶ", "行列", "残念だっ", "対応が悪",
]


# ═══════════════════════════════════════════════════════════════════════════
# 埋め込みバックエンド
# ═══════════════════════════════════════════════════════════════════════════
def _split_sentences(text: str) -> List[str]:
    """日本語テキストを文単位に分割。"""
    parts = re.split(r"[。！？\!\?\n]+", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def _topic_doc(keywords: List[str]) -> str:
    """トピックのキーワード群を、文と同じトークン空間の疑似文書に変換。"""
    toks: List[str] = []
    for kw in keywords:
        t = text_analysis.tokenize(kw)
        toks.extend(t if t else [kw])
    return " ".join(toks)


def _lightweight_embeddings(
    sentences: List[str],
    topics: List[TopicDef],
):
    """共有 TF-IDF 空間で文・トピックをベクトル化（torch 不要）。

    Returns (sentence_embeddings[n_sent, V], topic_embeddings[n_topic, V]) or (None, None).
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    sent_docs = [" ".join(text_analysis.tokenize(s)) for s in sentences]
    if not any(d.strip() for d in sent_docs):
        return None, None

    vec = TfidfVectorizer(token_pattern=r"[^\s]+", max_features=1500)
    try:
        S = vec.fit_transform([d if d.strip() else " " for d in sent_docs])
    except ValueError:
        return None, None

    topic_docs = [_topic_doc(t.keywords) for t in topics]
    T = vec.transform(topic_docs)
    return S.toarray(), T.toarray()


def sbert_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def _sbert_embeddings(sentences: List[str], topics: List[TopicDef]):
    """任意: sentence-transformers があれば SBERT で埋め込み。"""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("sonoisa/sentence-bert-base-ja-mean-tokens")
    sent_emb = np.asarray(model.encode(sentences))
    topic_texts = ["、".join(t.keywords) for t in topics]
    topic_emb = np.asarray(model.encode(topic_texts))
    return sent_emb, topic_emb


# ═══════════════════════════════════════════════════════════════════════════
# 高レベル API
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class TopicScore:
    name: str
    weight: float           # 正規化後の重み w_t
    avg_score: float        # avg_score_t（モデルの独自指標・感情×トピック確率の平均）
    total_score: float      # avg_score_t × w_t
    salience: float         # 言及度（平均トピック確率, Σ=1）
    sentiment: float        # そのトピックを語るときの感情 ∈ [0,1]（0.5=中立）

    @property
    def sentiment_100(self) -> float:
        return round(self.sentiment * 100, 1)

    @property
    def salience_pct(self) -> float:
        return round(self.salience * 100, 1)


@dataclass
class TopicScoreResult:
    topics: List[TopicScore] = field(default_factory=list)
    overall_score: float = 0.0     # 全体スコア Σ avg_score_t·w_t
    n_reviews: int = 0
    n_sentences: int = 0
    backend: str = "lightweight"
    empty: bool = True

    @property
    def overall_100(self) -> float:
        """モデル定義の全体スコア Σ avg_score_t·w_t を 0-100 換算。"""
        return round(self.overall_score * 100, 1)

    @property
    def weighted_sentiment_100(self) -> float:
        """重み付き総合感情スコア Σ sentiment_t·w_t（0-100・50=中立）。表示用の総合指標。"""
        if not self.topics:
            return 0.0
        return round(sum(t.sentiment * t.weight for t in self.topics) * 100, 1)

    def sorted_by_sentiment(self, reverse: bool = True) -> List[TopicScore]:
        return sorted(self.topics, key=lambda t: t.sentiment, reverse=reverse)

    def sentiment_by_topic(self) -> dict:
        """{トピック名: 感情スコア(0-100)}。"""
        return {t.name: t.sentiment_100 for t in self.topics}

    def salience_by_topic(self) -> dict:
        return {t.name: t.salience_pct for t in self.topics}


def _topic_probabilities_batch(sent_emb: np.ndarray, topic_emb: np.ndarray,
                               boost_factor: float = 0.5) -> np.ndarray:
    """topic_probabilities を全文まとめてベクトル化（数値は同一）。[n_sent, k] を返す。"""
    na = np.linalg.norm(sent_emb, axis=1)          # [n]
    nb = np.linalg.norm(topic_emb, axis=1)         # [k]
    C = (sent_emb @ topic_emb.T) / (np.outer(na, nb) + 1e-12)   # コサイン [n,k]

    c_mean = C.mean(axis=1, keepdims=True)
    c_std = C.std(axis=1, keepdims=True)
    z = (C - c_mean) / (c_std + 1e-6)
    T = np.clip(0.3 / (c_std + 1e-6), 0.05, 0.7)   # [n,1]
    logits = z / T
    logits = logits - logits.max(axis=1, keepdims=True)
    ex = np.exp(logits)
    p = ex / ex.sum(axis=1, keepdims=True)

    N = topic_emb.shape[0]
    boost = np.maximum(p - 1.0 / N, 0) * boost_factor
    p_boost = p + boost
    return p_boost / p_boost.sum(axis=1, keepdims=True)


def analyze_reviews(
    reviews: List[str],
    topics: Optional[List[TopicDef]] = None,
    backend: str = "lightweight",
) -> TopicScoreResult:
    """クチコミ本文リスト → 感情・トピック統合スコア。"""
    topics = topics or DEFAULT_TOPICS
    topic_weights = np.array([t.weight for t in topics], dtype=float)
    topic_weights = topic_weights / topic_weights.sum()

    # 文分割（レビュー単位を保持）
    review_sentences = [_split_sentences(r) for r in reviews if r and r.strip()]
    review_sentences = [s for s in review_sentences if s]
    if not review_sentences:
        return TopicScoreResult(empty=True)

    all_sentences = [s for rs in review_sentences for s in rs]

    # 埋め込み
    if backend == "sbert" and sbert_available():
        sent_emb, topic_emb = _sbert_embeddings(all_sentences, topics)
        used_backend = "sbert"
    else:
        sent_emb, topic_emb = _lightweight_embeddings(all_sentences, topics)
        used_backend = "lightweight"

    if sent_emb is None:
        return TopicScoreResult(empty=True)

    # 感情値（文単位・軽量）とトピック確率（ベクトル化）
    v_all = np.array([
        sentiment_value(keyword_sentiment_probs(_s, POSITIVE_WORDS, NEGATIVE_WORDS))
        for _s in all_sentences
    ])
    P = _topic_probabilities_batch(sent_emb, topic_emb)   # [n_sent, k]
    S_scores = v_all[:, None] * P                          # 文×トピックスコア

    # レビュー単位に集計（仕様どおり：文平均 → レビュー、次に全レビュー平均）
    per_review_topic_scores = []
    per_review_salience = []
    idx = 0
    for rs in review_sentences:
        m = len(rs)
        per_review_topic_scores.append(S_scores[idx:idx + m].mean(axis=0))
        per_review_salience.append(P[idx:idx + m].mean(axis=0))
        idx += m

    all_rts = np.array(per_review_topic_scores)   # [R, N]
    all_sal = np.array(per_review_salience)        # [R, N]

    agg = aggregate_all_reviews(all_rts, topic_weights)
    avg_score_t = agg["avg_score_t"]
    total_score_t = agg["total_score_t"]
    salience_t = all_sal.mean(axis=0)
    # そのトピックを語るときの平均感情（言及度で正規化）
    sentiment_t = np.where(salience_t > 1e-9, avg_score_t / salience_t, 0.5)
    sentiment_t = np.clip(sentiment_t, 0.0, 1.0)

    topic_scores = [
        TopicScore(
            name=t.name,
            weight=float(topic_weights[i]),
            avg_score=float(avg_score_t[i]),
            total_score=float(total_score_t[i]),
            salience=float(salience_t[i]),
            sentiment=float(sentiment_t[i]),
        )
        for i, t in enumerate(topics)
    ]

    return TopicScoreResult(
        topics=topic_scores,
        overall_score=agg["overall_score"],
        n_reviews=len(review_sentences),
        n_sentences=len(all_sentences),
        backend=used_backend,
        empty=False,
    )


def analyze_facility(
    conn,
    facility_name: str,
    topics: Optional[List[TopicDef]] = None,
    backend: str = "lightweight",
) -> TopicScoreResult:
    """DB の施設クチコミ本文を取得して analyze_reviews を実行。"""
    rows = conn.execute(
        """SELECT r.text FROM review r
           JOIN facility f ON f.id = r.facility_id
           WHERE f.name = ? AND r.text IS NOT NULL AND r.text != ''""",
        (facility_name,),
    ).fetchall()
    reviews = [r[0] for r in rows]
    return analyze_reviews(reviews, topics=topics, backend=backend)


# ═══════════════════════════════════════════════════════════════════════════
# スコアの較正（市場内の相対位置へ）
# ═══════════════════════════════════════════════════════════════════════════
# 感情スコアは 0-100 の絶対値だが、実データでは中立(50)付近に強く集まる。
# 実測（40施設）では観点別スコアが 47.2〜71.5（平均53.1・sd 3.0）で、5点満点に
# 素で直すと全施設が 2.4〜3.3 に潰れて差が読めない。さらに観点ごとの sd が
# 1.12〜5.06 と4.5倍ばらつくため、「サービスの種類」のように何をやっても
# 全施設 2.7 前後にしかならない軸が生まれる。
#
# そこで観点ごとに市場の分布で標準化し、5点満点へ写す:
#     z = (score - 市場平均) / 市場sd
#     5点 = 3.0 + z × 0.5   （1sd = 0.5点、1.0〜5.0でクリップ）
#
# 3.00 が「市場平均」を意味するようになる。絶対的な品質評価ではなく市場内の
# 相対位置である点に注意（スライドにもその旨を明記すること）。
CALIBRATION_CENTER = 3.0      # 市場平均に対応する5点満点上の値
CALIBRATION_PER_SD = 0.5      # 1標準偏差あたり何点動かすか
CALIBRATION_MIN_SD = 1.0      # sd の下限（小さすぎると z が暴れる）
CALIBRATION_MIN_FACILITIES = 8  # これ未満では分布が不安定なので較正しない


def calibration_stats(matrix: dict) -> Optional[dict]:
    """{施設名: TopicScoreResult} から観点ごとの (平均, sd) を出す。

    較正の基準は必ず**母集団全体**にすること。指定競合モードで選んだ5施設だけを
    基準にすると、同じ施設のスコアが「誰と比べたか」で変わってしまう。
    施設数が足りないときは None（＝較正しない）。
    """
    usable = [r for r in matrix.values() if r is not None and not r.empty]
    if len(usable) < CALIBRATION_MIN_FACILITIES:
        return None

    per: dict[str, List[float]] = {}
    for r in usable:
        for t, v in r.sentiment_by_topic().items():
            per.setdefault(t, []).append(v)

    out = {}
    for t, vals in per.items():
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        out[t] = (mean, max(var ** 0.5, CALIBRATION_MIN_SD))
    return out


# 較正済みかどうかは backend の接尾辞で判別する（結果に専用のフラグを
# 持たせると、キャッシュを経由したときに落ちるため）。
CALIBRATED_SUFFIX = "+calibrated"


def calibrated_sentiment(v100: float, stat: Optional[tuple]) -> float:
    """観点スコア(0-100)を、市場内の相対位置にもとづく 0-100 に写す。

    戻り値も 0-100 スケール（表示側が /20 して5点にする）なので、
    呼び出し側の計算はそのまま使える。
    """
    if not stat:
        return v100
    mean, sd = stat
    z = (v100 - mean) / sd
    pt5 = CALIBRATION_CENTER + z * CALIBRATION_PER_SD
    return min(5.0, max(1.0, pt5)) * 20.0


def calibrate_result(result: "TopicScoreResult",
                     stats: Optional[dict]) -> "TopicScoreResult":
    """TopicScoreResult の各観点スコアを較正した新しい結果を返す（元は変更しない）。"""
    if not stats or result is None or result.empty:
        return result
    topics = [
        TopicScore(
            name=t.name, weight=t.weight, avg_score=t.avg_score,
            total_score=t.total_score, salience=t.salience,
            sentiment=calibrated_sentiment(t.sentiment_100, stats.get(t.name)) / 100,
        )
        for t in result.topics
    ]
    return TopicScoreResult(
        topics=topics, overall_score=result.overall_score,
        n_reviews=result.n_reviews, n_sentences=result.n_sentences,
        backend=result.backend + CALIBRATED_SUFFIX, empty=result.empty,
    )


def is_calibrated(result) -> bool:
    """この結果がすでに較正済みか（backend の接尾辞で判別する）。"""
    return bool(result is not None and str(result.backend).endswith(CALIBRATED_SUFFIX))


def calibrate_matrix(matrix: dict) -> tuple[dict, bool]:
    """行列全体を較正する。戻り値は (較正後の行列, 表示値が較正済みか)。

    **冪等**。すでに較正済みの行列を渡しても二重に較正しない。
    分析ワーカーは PPTX と画面スライドの数字を揃えるために、両方を作る前に
    1回だけ較正して同じ行列を渡す。build_bundle は素の行列を受け取る
    呼び出し（テストやダミーデータ生成）も残っているので、ここで吸収する。

    第2要素は「較正を実行したか」ではなく「返す値が較正済みか」。
    スライドの注記（3.00＝市場平均）の出し分けに使うので、素通しした
    ときも較正済みなら True を返す。
    """
    usable = [r for r in matrix.values() if r is not None]
    if usable and all(is_calibrated(r) for r in usable):
        return matrix, True
    stats = calibration_stats(matrix)
    if not stats:
        return matrix, False
    return ({n: (calibrate_result(r, stats) if r is not None else None)
             for n, r in matrix.items()}, True)


def facility_topic_matrix(
    conn,
    names: Optional[List[str]] = None,
    topics: Optional[List[TopicDef]] = None,
    backend: str = "lightweight",
) -> dict:
    """全施設のトピックスコアを算出（比較用）。

    Returns {facility_name: TopicScoreResult}。空本文の施設は結果 empty。
    重い処理なので呼び出し側でキャッシュすること。
    """
    if names is None:
        from . import analysis
        names = analysis.facility_names(conn)
    return {n: analyze_facility(conn, n, topics=topics, backend=backend) for n in names}
