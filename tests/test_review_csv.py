"""Tests for the messy review CSV parser (step 3)."""
import io
from pathlib import Path

from src import review_csv

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_reviews.csv"

# Simple Japanese-column-name format (e.g. 高浜市やきものの里 CSV)
JP_CSV = io.BytesIO(
    (
        "施設名,投稿者,クチコミ内容,review_date,review_rating,url\n"
        "かわら美術館,テスト太郎,とても良い施設でした,2024-01-10T00:00:00.000Z,5,https://example.com\n"
        "かわら美術館,テスト花子,展示が充実していて満足です,2024-02-01T00:00:00.000Z,4,https://example.com\n"
        "かわら美術館,匿名,少し暗い感じがする,2024-03-15T00:00:00.000Z,2,https://example.com\n"
    ).encode("utf-8")
)


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


# ── Japanese-column-name format tests ────────────────────────────────────── #

def _jp_res():
    JP_CSV.seek(0)
    return review_csv.parse_reviews(JP_CSV)


def test_jp_format_parses_all_rows():
    res = _jp_res()
    assert len(res.reviews) == 3
    assert res.n_skipped == 0


def test_jp_format_text_extracted():
    res = _jp_res()
    assert res.reviews[0].text == "とても良い施設でした"
    assert res.reviews[1].text == "展示が充実していて満足です"


def test_jp_format_reviewer_name():
    res = _jp_res()
    assert res.reviews[0].reviewer_name == "テスト太郎"


def test_jp_format_rating():
    res = _jp_res()
    assert res.reviews[0].rating == 5
    assert res.reviews[2].rating == 2


def test_jp_format_infer_facilities():
    JP_CSV.seek(0)
    facilities = review_csv.infer_facilities(JP_CSV)
    assert len(facilities) == 1
    assert facilities[0]["name"] == "かわら美術館"
    assert facilities[0]["count"] == 3
