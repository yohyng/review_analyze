"""Step 7: Japanese text analysis — TF-IDF keywords + N-gram phrases.

For each facility:
  1. Tokenize reviews with Janome (pure-Python morphological analyser)
  2. TF-IDF: words that characterise THIS facility vs all others in the DB
     (falls back to plain TF when only 1 facility exists)
  3. Bigrams / trigrams: frequently co-occurring word pairs / triples
  4. Collect high/low rated sample reviews for the LLM prompt
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

_tokenizer_cache = None


def _tok():
    global _tokenizer_cache
    if _tokenizer_cache is None:
        from janome.tokenizer import Tokenizer
        _tokenizer_cache = Tokenizer()
    return _tokenizer_cache


# words to strip even if they pass the POS filter
_STOPWORDS = frozenset({
    "こと", "もの", "ため", "よう", "感じ", "思い", "思う", "自分",
    "ある", "いる", "なる", "する", "できる", "来る", "行く", "見る",
    "ます", "です", "でし", "ない", "たい", "てい", "ので", "けど",
    "ここ", "そこ", "これ", "それ", "あれ", "あと", "また", "とても",
    "すごく", "ちょっと", "やっぱり", "やはり", "さらに", "一度",
    "よかっ", "良かっ", "よく", "いい", "良い",
    "今回", "以前", "今度", "次回", "今後", "先日",
})

_KEEP_POS = frozenset({"名詞", "動詞", "形容詞", "形容動詞"})


def tokenize(text: str) -> list[str]:
    """Return base-form content words from Japanese text."""
    out = []
    for token in _tok().tokenize(text):
        pos = token.part_of_speech.split(",")[0]
        if pos not in _KEEP_POS:
            continue
        base = token.base_form if token.base_form and token.base_form != "*" else token.surface
        if len(base) < 2 or base in _STOPWORDS:
            continue
        out.append(base)
    return out


def symbolic_ranking(reviews, tfidf_keywords, top_k: int = 5) -> list[dict]:
    """口コミを『施設の特徴語（TF-IDF）をどれだけ体現しているか』で総合ランキング。

    reviews: list[(rating, text)]、tfidf_keywords: build_profile の DataFrame(単語/スコア)。
    象徴度 = レビュー内に含まれる特徴語の TF-IDF スコア合計（多様な特徴語を語るレビューほど上位）。
    Returns 上位 top_k: [{rank, rating, text, score, share, keywords}]。
    """
    if tfidf_keywords is None or getattr(tfidf_keywords, "empty", True):
        return []
    scores = dict(zip(tfidf_keywords["単語"], tfidf_keywords["スコア"]))
    total = sum(scores.values()) or 1.0
    ranked = []
    for rating, text in reviews:
        if not text or not text.strip():
            continue
        toks = set(tokenize(text))
        matched = [w for w in scores if w in toks]
        if not matched:
            continue
        s = sum(scores[w] for w in matched)
        ranked.append({
            "rating": rating,
            "text": text.strip(),
            "score": round(float(s), 3),
            "share": round(100 * s / total, 1),
            "keywords": sorted(matched, key=lambda w: -scores[w])[:6],
        })
    ranked.sort(key=lambda r: -r["score"])
    for i, r in enumerate(ranked[:top_k], 1):
        r["rank"] = i
    return ranked[:top_k]


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #
def _fetch_reviews(conn: sqlite3.Connection, facility_name: str) -> list[str]:
    rows = conn.execute(
        """SELECT r.text FROM review r
           JOIN facility f ON f.id = r.facility_id
           WHERE f.name = ? AND r.text IS NOT NULL AND r.text != ''""",
        (facility_name,),
    ).fetchall()
    return [r[0] for r in rows]


def _fetch_all_reviews(conn: sqlite3.Connection) -> dict[str, list[str]]:
    rows = conn.execute(
        """SELECT f.name, r.text FROM review r
           JOIN facility f ON f.id = r.facility_id
           WHERE r.text IS NOT NULL AND r.text != ''""",
    ).fetchall()
    out: dict[str, list[str]] = {}
    for name, text in rows:
        out.setdefault(name, []).append(text)
    return out


def _rated_samples(
    conn: sqlite3.Connection, facility_name: str
) -> tuple[list[str], list[str]]:
    rows = conn.execute(
        """SELECT r.text, r.rating FROM review r
           JOIN facility f ON f.id = r.facility_id
           WHERE f.name = ? AND r.text IS NOT NULL AND r.text != ''
           ORDER BY r.rating DESC NULLS LAST""",
        (facility_name,),
    ).fetchall()
    if not rows:
        return [], []
    high = [r[0] for r in rows[:3]]
    low = [r[0] for r in rows if r[1] is not None and int(r[1]) <= 3][-3:]
    return high, low


# --------------------------------------------------------------------------- #
# TF-IDF
# --------------------------------------------------------------------------- #
def _tfidf_df(
    all_reviews: dict[str, list[str]],
    target_name: str,
    top_n: int,
) -> pd.DataFrame:
    # Build one tokenized document per facility
    docs: dict[str, str] = {}
    for name, texts in all_reviews.items():
        tokens: list[str] = []
        for t in texts:
            tokens.extend(tokenize(t))
        docs[name] = " ".join(tokens)

    if not docs or target_name not in docs:
        return pd.DataFrame(columns=["単語", "スコア"])

    names = list(docs.keys())
    corpus = [docs[n] for n in names]
    target_idx = names.index(target_name)

    if len(names) == 1:
        # single facility → plain term frequency
        counts = Counter(corpus[0].split())
        total = sum(counts.values()) or 1
        rows = [(w, round(c / total, 4)) for w, c in counts.most_common(top_n)]
    else:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(analyzer="word", token_pattern=r"[^\s]+", max_features=5000)
        mat = vec.fit_transform(corpus)
        feat = vec.get_feature_names_out()
        scores = mat[target_idx].toarray().flatten()
        top_idx = scores.argsort()[::-1][:top_n]
        rows = [(feat[i], round(float(scores[i]), 4)) for i in top_idx if scores[i] > 0]

    return pd.DataFrame(rows, columns=["単語", "スコア"])


# --------------------------------------------------------------------------- #
# N-gram
# --------------------------------------------------------------------------- #
def _ngram_df(reviews: list[str], n: int, top_k: int) -> pd.DataFrame:
    counter: Counter = Counter()
    for text in reviews:
        tokens = tokenize(text)
        for i in range(len(tokens) - n + 1):
            counter[tuple(tokens[i : i + n])] += 1
    rows = [
        (" ".join(gram), cnt)
        for gram, cnt in counter.most_common(top_k)
        if cnt >= 2
    ]
    return (
        pd.DataFrame(rows, columns=["フレーズ", "件数"])
        if rows
        else pd.DataFrame(columns=["フレーズ", "件数"])
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
@dataclass
class TextProfile:
    facility_name: str
    n_reviews: int
    tfidf_keywords: pd.DataFrame   # 単語 / スコア
    bigrams: pd.DataFrame          # フレーズ / 件数
    trigrams: pd.DataFrame         # フレーズ / 件数
    high_rated: list[str]
    low_rated: list[str]
    empty: bool = False


def build_profile(
    conn: sqlite3.Connection,
    facility_name: str,
    top_n: int = 20,
) -> TextProfile:
    reviews = _fetch_reviews(conn, facility_name)
    if not reviews:
        return TextProfile(
            facility_name=facility_name,
            n_reviews=0,
            tfidf_keywords=pd.DataFrame(columns=["単語", "スコア"]),
            bigrams=pd.DataFrame(columns=["フレーズ", "件数"]),
            trigrams=pd.DataFrame(columns=["フレーズ", "件数"]),
            high_rated=[],
            low_rated=[],
            empty=True,
        )

    all_reviews = _fetch_all_reviews(conn)
    high, low = _rated_samples(conn, facility_name)

    return TextProfile(
        facility_name=facility_name,
        n_reviews=len(reviews),
        tfidf_keywords=_tfidf_df(all_reviews, facility_name, top_n),
        bigrams=_ngram_df(reviews, n=2, top_k=top_n),
        trigrams=_ngram_df(reviews, n=3, top_k=top_n),
        high_rated=high,
        low_rated=low,
    )
