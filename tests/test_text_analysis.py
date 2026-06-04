"""Tests for step 7: tokenizer, TF-IDF, N-gram, profile builder."""
from pathlib import Path

from src import db, review_csv, text_analysis

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _seed(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    res = review_csv.parse_reviews(SAMPLES / "sample_reviews.csv")
    fid = db.upsert_facility(conn, "風の海", ftype="target")
    db.insert_reviews(conn, fid, res.reviews)
    return conn


def test_tokenize_returns_content_words():
    tokens = text_analysis.tokenize("スタッフの対応が丁寧で安心できました。食事も美味しかった。")
    assert "スタッフ" in tokens
    assert "対応" in tokens
    assert "食事" in tokens
    # stopwords removed
    assert "こと" not in tokens
    assert "です" not in tokens


def test_tokenize_filters_short_words():
    tokens = text_analysis.tokenize("良い宿でした。")
    # single-char tokens stripped (length < 2)
    for t in tokens:
        assert len(t) >= 2


def test_build_profile_empty_when_no_reviews(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_facility(conn, "幽霊施設")
    profile = text_analysis.build_profile(conn, "幽霊施設")
    assert profile.empty is True
    assert profile.n_reviews == 0


def test_build_profile_keywords(tmp_path):
    conn = _seed(tmp_path)
    profile = text_analysis.build_profile(conn, "風の海")
    assert not profile.empty
    assert profile.n_reviews == 2
    # TF-IDF keywords DataFrame has expected columns
    assert list(profile.tfidf_keywords.columns) == ["単語", "スコア"]
    assert len(profile.tfidf_keywords) > 0


def test_build_profile_bigrams(tmp_path):
    conn = _seed(tmp_path)
    # Add more reviews so bigrams can exceed min-count of 2
    fid = conn.execute("SELECT id FROM facility WHERE name='風の海'").fetchone()[0]
    from src.db import insert_reviews
    from src.review_csv import ParsedReview
    extra = [
        ParsedReview(
            review_id=f"extra_{i}",
            rating=4,
            text="食事が美味しかった。スタッフの対応も良かった。",
            review_date="2025-01-01",
            reviewer_name="テスト",
            local_guide=False,
            likes=0,
            owner_response="",
            owner_response_date="",
            subscores=[],
        )
        for i in range(5)
    ]
    insert_reviews(conn, fid, extra)
    profile = text_analysis.build_profile(conn, "風の海")
    # bigrams DataFrame is not empty after enough repetitions
    assert list(profile.bigrams.columns) == ["フレーズ", "件数"]


def test_build_profile_high_low_reviews(tmp_path):
    conn = _seed(tmp_path)
    profile = text_analysis.build_profile(conn, "風の海")
    # 5-star review should be in high_rated
    assert len(profile.high_rated) >= 1
    # sample reviews contain the original text
    assert any("米寿" in r or "避難" in r for r in profile.high_rated)
