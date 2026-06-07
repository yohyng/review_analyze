"""Tests for src/topics.py — deterministic, no I/O."""
import pytest
from src.topics import Topic, extract_topics

_REVIEWS = [
    (5.0, "スタッフが親切で笑顔が素晴らしかった"),
    (4.0, "部屋が清潔でとてもきれいでした"),
    (3.0, "料理が美味しかった"),
    (5.0, "接客が丁寧で大満足でした"),
    (4.0, "設備が新しく快適な客室でした"),
]


def test_returns_list_of_topics():
    result = extract_topics(_REVIEWS, n_topics=2)
    assert isinstance(result, list)
    assert len(result) >= 1
    for t in result:
        assert isinstance(t, Topic)


def test_topic_fields_populated():
    result = extract_topics(_REVIEWS, n_topics=2)
    for t in result:
        assert t.count > 0
        assert 0 < t.share <= 100
        assert isinstance(t.keywords, list)
        assert isinstance(t.samples, list)
        assert len(t.label) > 0


def test_empty_input():
    assert extract_topics([]) == []


def test_empty_texts():
    assert extract_topics([(5.0, ""), (4.0, "  ")]) == []


def test_too_few_reviews():
    assert extract_topics([(5.0, "良い施設でした")]) == []


def test_deterministic():
    r1 = extract_topics(_REVIEWS, n_topics=3)
    r2 = extract_topics(_REVIEWS, n_topics=3)
    assert [t.id for t in r1] == [t.id for t in r2]
    assert [t.label for t in r1] == [t.label for t in r2]
    assert [t.count for t in r1] == [t.count for t in r2]


def test_count_sum_equals_total():
    result = extract_topics(_REVIEWS, n_topics=3)
    assert sum(t.count for t in result) == len(_REVIEWS)


def test_sorted_by_count_descending():
    result = extract_topics(_REVIEWS, n_topics=3)
    counts = [t.count for t in result]
    assert counts == sorted(counts, reverse=True)


def test_n_topics_clamped():
    # requesting more topics than reviews should not crash
    result = extract_topics(_REVIEWS, n_topics=100)
    assert len(result) <= len(_REVIEWS)


def test_samples_are_subsets_of_input():
    texts = {r[1] for r in _REVIEWS}
    result = extract_topics(_REVIEWS, n_topics=2)
    for t in result:
        for s in t.samples:
            assert s in texts
