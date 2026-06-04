"""Tests for the messy review CSV parser (step 3)."""
from pathlib import Path

from src import review_csv

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_reviews.csv"


def test_parses_both_reviews():
    res = review_csv.parse_reviews(SAMPLE)
    assert len(res.reviews) == 2
    assert res.n_skipped == 0


def test_facility_meta_from_misspelled_header():
    res = review_csv.parse_reviews(SAMPLE)
    assert res.general_rating == 4.5
    assert res.total_reviews == 240  # read from `overall_place_riviews`


def test_multiline_quoted_review_kept_intact():
    res = review_csv.parse_reviews(SAMPLE)
    first = res.reviews[0]
    assert first.rating == 5
    assert "\n" in first.text                 # newlines survived CSV parsing
    assert first.text.startswith("線状降水帯")
    assert first.text.rstrip().endswith("お世話になりました。")


def test_subscores_from_python_literal():
    res = review_csv.parse_reviews(SAMPLE)
    axes = dict(res.reviews[0].subscores)
    assert axes == {"Rooms": 5.0, "Service": 5.0, "Location": 5.0}
    # second review only rated Service -> sparse, that's expected
    assert dict(res.reviews[1].subscores) == {"Service": 4.0}


def test_local_guide_flag():
    res = review_csv.parse_reviews(SAMPLE)
    assert res.reviews[0].local_guide is True
    assert res.reviews[1].local_guide is False


def test_review_id_used_for_dedup_key():
    res = review_csv.parse_reviews(SAMPLE)
    assert res.reviews[0].review_id.startswith("Ci9DQUlR")
