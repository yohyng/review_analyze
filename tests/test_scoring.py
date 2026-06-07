"""Tests for src/scoring.py — all deterministic, no I/O."""
import pytest
from src.scoring import (
    _clamp,
    _sentiment,
    compute_axis_scores,
    compute_tfidf_emphasis,
)


def test_clamp_within():
    assert _clamp(50) == 50.0


def test_clamp_below():
    assert _clamp(-5) == 0.0


def test_clamp_above():
    assert _clamp(105) == 100.0


def test_clamp_boundaries():
    assert _clamp(0) == 0.0
    assert _clamp(100) == 100.0


def test_sentiment_positive():
    s = _sentiment(["素晴らしいサービスで満足しました", "また来たいと思います"])
    assert s > 0


def test_sentiment_negative():
    s = _sentiment(["最悪の対応でした", "二度と来ません"])
    assert s < 0


def test_sentiment_empty():
    assert _sentiment([]) == 0.0


def test_sentiment_range():
    s = _sentiment(["とても良い施設でした"])
    assert -1.0 <= s <= 1.0


def test_axis_scores_basic():
    reviews = [
        (5.0, "スタッフが親切で最高でした"),
        (4.0, "清潔で快適な部屋でした"),
        (3.0, "料理が美味しかった"),
    ]
    scores = compute_axis_scores(reviews)
    assert "総合満足度" in scores
    for v in scores.values():
        assert 0 <= v <= 100


def test_axis_scores_total_only_no_text():
    reviews = [(5.0, ""), (3.0, ""), (4.0, "")]
    scores = compute_axis_scores(reviews)
    assert "総合満足度" in scores
    assert abs(scores["総合満足度"] - 80.0) < 1.0


def test_axis_scores_deterministic():
    reviews = [
        (5.0, "スタッフが親切で大満足でした"),
        (4.0, "清潔な部屋で快適でした"),
        (2.0, "料理が微妙でまずい"),
    ]
    assert compute_axis_scores(reviews) == compute_axis_scores(reviews)


def test_axis_scores_empty():
    assert compute_axis_scores([]) == {}


def test_axis_scores_none_ratings():
    reviews = [(None, "スタッフが親切"), (None, "清潔な部屋")]
    scores = compute_axis_scores(reviews)
    assert "総合満足度" not in scores


def test_tfidf_emphasis_basic():
    reviews = [
        (5.0, "スタッフが親切で接客が素晴らしい"),
        (4.0, "部屋が清潔でとてもきれい"),
        (3.0, "立地が便利で駅から近い"),
    ]
    emph = compute_tfidf_emphasis(reviews)
    assert len(emph) > 0
    assert max(emph.values()) == 100.0
    for v in emph.values():
        assert 0 <= v <= 100


def test_tfidf_emphasis_deterministic():
    reviews = [
        (5.0, "スタッフが親切で接客が素晴らしい"),
        (4.0, "部屋が清潔できれい"),
    ]
    assert compute_tfidf_emphasis(reviews) == compute_tfidf_emphasis(reviews)


def test_tfidf_emphasis_empty():
    assert compute_tfidf_emphasis([]) == {}


def test_tfidf_emphasis_whitespace_only():
    assert compute_tfidf_emphasis([(None, "   "), (None, "\t")]) == {}
