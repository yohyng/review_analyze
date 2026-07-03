"""Tests for src/topic_score.py — 感情・トピック統合スコアモデル。

仕様書（sentiment_topic_score_model）に忠実であることを検証する。
"""
import numpy as np
import pytest

from src import topic_score as ts


# ─────────────────────────────────────────────────────────────────────────────
# 第1章 感情スコア
# ─────────────────────────────────────────────────────────────────────────────
def test_keyword_sentiment_probs_shape_and_sum():
    p = ts.keyword_sentiment_probs("素晴らしい体験でした", ts.POSITIVE_WORDS, ts.NEGATIVE_WORDS)
    assert p.shape == (3,)
    assert p[0] >= 0 and p[1] >= 0 and p[2] >= 0
    assert abs(float(p.sum()) - 1.0) < 1e-9


def test_keyword_sentiment_neutral_when_no_hits():
    p = ts.keyword_sentiment_probs("これはテストです", ["xyz"], ["zzz"])
    # s_raw = 0 → p_neu should dominate
    assert p[1] >= p[0] and p[1] >= p[2]


def test_temperature_scaling_sums_to_one_and_sharpens():
    probs = np.array([0.2, 0.5, 0.3])
    out = ts.temperature_scaling(probs, T=0.7)
    assert abs(float(out.sum()) - 1.0) < 1e-9
    # T<1 sharpens: max prob should increase
    assert out.max() >= probs.max()


def test_sentiment_value_range_and_direction():
    pos = ts.sentiment_value(
        ts.keyword_sentiment_probs("最高で快適、大満足でした", ts.POSITIVE_WORDS, ts.NEGATIVE_WORDS)
    )
    neg = ts.sentiment_value(
        ts.keyword_sentiment_probs("最悪で不快、ひどい対応でした", ts.POSITIVE_WORDS, ts.NEGATIVE_WORDS)
    )
    assert 0.0 <= pos <= 1.0
    assert 0.0 <= neg <= 1.0
    assert pos > 0.5 > neg


def test_sentiment_value_neutral_is_half():
    # No sentiment words → s_raw 0 → v_sentiment 0.5
    v = ts.sentiment_value(ts.keyword_sentiment_probs("普通の一日", ["xyz"], ["zzz"]))
    assert abs(v - 0.5) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 第2章 トピック確率
# ─────────────────────────────────────────────────────────────────────────────
def test_topic_probabilities_sum_to_one():
    rng = np.random.RandomState(0)
    embs = rng.rand(6, 32)
    p = ts.topic_probabilities(embs[0], embs[1:])
    assert len(p) == 5
    assert abs(float(p.sum()) - 1.0) < 1e-9
    assert np.all(p >= 0)


def test_topic_probabilities_zero_vector_is_uniform():
    # A sentence with no signal → similarities all 0 → near-uniform, no NaN
    topics = np.eye(4)
    p = ts.topic_probabilities(np.zeros(4), topics)
    assert not np.any(np.isnan(p))
    assert abs(float(p.sum()) - 1.0) < 1e-9


def test_cosine_similarity_bounds():
    a = np.array([1.0, 0.0])
    assert abs(ts.cosine_similarity(a, a) - 1.0) < 1e-6
    assert abs(ts.cosine_similarity(a, np.array([0.0, 1.0]))) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 第3〜6章 集計
# ─────────────────────────────────────────────────────────────────────────────
def test_sentence_topic_score_is_product():
    p = np.array([0.5, 0.3, 0.2])
    out = ts.sentence_topic_score(0.8, p)
    assert np.allclose(out, 0.8 * p)


def test_aggregate_all_reviews_overall_matches_formula():
    all_rts = np.array([[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]])
    weights = np.array([0.5, 0.3, 0.2])
    agg = ts.aggregate_all_reviews(all_rts, weights)
    avg = all_rts.mean(axis=0)
    assert np.allclose(agg["avg_score_t"], avg)
    assert np.allclose(agg["total_score_t"], avg * weights)
    assert abs(agg["overall_score"] - float(np.sum(avg * weights))) < 1e-12


# ─────────────────────────────────────────────────────────────────────────────
# 高レベル API
# ─────────────────────────────────────────────────────────────────────────────
_REVIEWS = [
    "接客がとても丁寧で親切でした。料理も美味しくて大満足です。",
    "値段が高いのに味は普通。スタッフの対応も雑で残念でした。",
    "立地が便利で駅から近い。店内は清潔感があって居心地が良かった。",
    "予約したのに待たされた。混雑していてうるさかった。",
]


def test_analyze_reviews_basic():
    res = ts.analyze_reviews(_REVIEWS)
    assert not res.empty
    assert res.n_reviews == 4
    assert res.n_sentences >= 4
    assert len(res.topics) == len(ts.DEFAULT_TOPICS)


def test_analyze_reviews_salience_sums_to_one():
    res = ts.analyze_reviews(_REVIEWS)
    total_sal = sum(t.salience for t in res.topics)
    assert abs(total_sal - 1.0) < 1e-6


def test_analyze_reviews_scores_in_range():
    res = ts.analyze_reviews(_REVIEWS)
    for t in res.topics:
        assert 0.0 <= t.sentiment <= 1.0
        assert 0.0 <= t.salience <= 1.0
        assert t.avg_score >= 0.0
    assert 0.0 <= res.weighted_sentiment_100 <= 100.0


def test_analyze_reviews_weights_normalized():
    res = ts.analyze_reviews(_REVIEWS)
    assert abs(sum(t.weight for t in res.topics) - 1.0) < 1e-6


def test_analyze_reviews_empty_input():
    assert ts.analyze_reviews([]).empty
    assert ts.analyze_reviews(["", "   "]).empty


def test_analyze_reviews_deterministic():
    a = ts.analyze_reviews(_REVIEWS)
    b = ts.analyze_reviews(_REVIEWS)
    assert [round(t.avg_score, 6) for t in a.topics] == [round(t.avg_score, 6) for t in b.topics]
    assert a.overall_score == b.overall_score


def test_uniform_sentiment_direction():
    # 一様にポジ/ネガなレビューでは、トピック平均感情が方向を反映する
    import statistics
    pos = ts.analyze_reviews(["最高でした。素晴らしい。", "とても良い。大満足。快適で楽しい。"])
    neg = ts.analyze_reviews(["最悪でした。ひどい。", "とても悪い。残念。不快で汚い。"])
    assert statistics.mean(t.sentiment for t in pos.topics) > 0.55
    assert statistics.mean(t.sentiment for t in neg.topics) < 0.45


def test_topics_are_22():
    assert len(ts.DEFAULT_TOPICS) == 22
    assert ts.TOPIC_ORDER[0] == "提供内容の品質"
    assert ts.TOPIC_ORDER[-1] == "再訪意向"


def test_batch_matches_looped_topic_probabilities():
    # ベクトル化バッチが逐次 topic_probabilities と一致すること
    import numpy as np
    rng = np.random.RandomState(3)
    se = rng.rand(7, 40)
    te = rng.rand(22, 40)
    batch = ts._topic_probabilities_batch(se, te)
    looped = np.array([ts.topic_probabilities(se[i], te) for i in range(se.shape[0])])
    assert np.allclose(batch, looped, atol=1e-9)


def test_split_sentences():
    s = ts._split_sentences("良かった。また来たい！でも高い？")
    assert len(s) == 3
