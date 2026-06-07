"""Topic modeling for reviews (PLACEHOLDER, deterministic).

本来は BERT 系（BERTopic / sentence-transformers の埋め込み）で行う想定。
ただし torch+transformers は数百MB〜GB級で Streamlit Cloud 無料枠（~1GB RAM）
では起動時に落ちるため、現状は TF-IDF + KMeans（random_state 固定）による
決定論的な仮実装にしている。

→ 後で BERTopic に差し替える際は extract_topics() のシグネチャ
   (reviews, n_topics) -> list[Topic] を保てば、呼び出し側は無改修で済む。

KMeans は random_state を固定しているため、同じ入力に対して常に同じ
クラスタリング結果（＝同じトピック）を返す。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import text_analysis

SEED = 42  # fixed → deterministic


@dataclass
class Topic:
    id: int
    label: str                       # 上位語を連結した見出し
    keywords: list[str] = field(default_factory=list)
    count: int = 0                   # このトピックに属する口コミ数
    share: float = 0.0               # 全体に占める割合 (%)
    samples: list[str] = field(default_factory=list)


def extract_topics(
    reviews: list[tuple[float | None, str]],
    n_topics: int = 5,
) -> list[Topic]:
    """reviews = [(rating, text), ...] -> deterministic list[Topic].

    Empty list if there are too few reviews to cluster.
    """
    raw_texts = [t for _, t in reviews if t and t.strip()]
    if len(raw_texts) < 2:
        return []

    # Tokenize and keep texts+docs in sync — filter both together so indices match
    pairs = [(t, " ".join(text_analysis.tokenize(t))) for t in raw_texts]
    pairs = [(t, d) for t, d in pairs if d.strip()]
    if len(pairs) < 2:
        return []
    texts = [t for t, _ in pairs]
    docs  = [d for _, d in pairs]

    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(token_pattern=r"[^\s]+", max_features=2000)
    try:
        X = vec.fit_transform(docs)
    except ValueError:
        return []

    k = max(1, min(n_topics, X.shape[0]))
    km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
    labels = km.fit_predict(X)
    feats = vec.get_feature_names_out()

    topics: list[Topic] = []
    total = len(texts)
    for c in range(k):
        center = km.cluster_centers_[c]
        top_idx = center.argsort()[::-1][:6]
        keywords = [feats[i] for i in top_idx if center[i] > 0]
        members = [texts[i] for i in range(len(texts)) if labels[i] == c]
        if not members:
            continue
        topics.append(
            Topic(
                id=c,
                label="・".join(keywords[:3]) if keywords else f"トピック{c + 1}",
                keywords=keywords,
                count=len(members),
                share=round(len(members) / total * 100, 1),
                samples=members[:2],
            )
        )

    topics.sort(key=lambda t: -t.count)
    return topics
