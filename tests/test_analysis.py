"""Tests for steps 5-6: score matrices, diff, TOP5."""
from pathlib import Path

import pytest

from src import analysis, db, review_csv, score_excel

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _seed(tmp_path):
    """Seed a fresh DB with both facilities from sample files."""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)

    # Excel scores: 風の海 (target) + 海の宿 潮 (comparison)
    df = score_excel.read_table(SAMPLES / "sample_scores.xlsx")
    g = score_excel.guess_columns(df)
    scores = score_excel.extract_scores_wide(df, g.name_col, g.numeric_cols)

    fid_target = db.upsert_facility(conn, "風の海", ftype="target")
    db.upsert_scores(conn, fid_target, scores["風の海"], scale=5)

    fid_comp = db.upsert_facility(conn, "海の宿 潮", ftype="comparison")
    db.upsert_scores(conn, fid_comp, scores["海の宿 潮"], scale=5)

    return conn


def test_score_matrix_normalized(tmp_path):
    conn = _seed(tmp_path)
    mat = analysis.score_matrix(conn)
    assert set(mat.index) == {"風の海", "海の宿 潮"}
    # 4.2 / 5 * 100 = 84.0
    assert abs(mat.loc["風の海", "清潔感"] - 84.0) < 0.1
    # all values should be 0-100
    assert mat.values.min() >= 0
    assert mat.values.max() <= 100


def test_build_comparison_comparison_avg(tmp_path):
    conn = _seed(tmp_path)
    result = analysis.build_comparison(conn, "風の海", "comparison_avg")
    assert result is not None
    assert result.target_label == "風の海"
    assert "比較施設の平均" in result.baseline_label
    # 風の海 スタッフ対応 = 4.6/5*100 = 92, 海の宿潮 = 3.5/5*100 = 70 → diff +22
    assert abs(result.diff["スタッフ対応"] - 22.0) < 0.5


def test_build_comparison_all_avg(tmp_path):
    conn = _seed(tmp_path)
    result = analysis.build_comparison(conn, "風の海", "all_avg")
    assert result is not None
    # baseline is the other facility only (風の海 excluded)
    assert "全体平均" in result.baseline_label


def test_build_comparison_specific(tmp_path):
    conn = _seed(tmp_path)
    result = analysis.build_comparison(conn, "風の海", "specific", specific_name="海の宿 潮")
    assert result is not None
    assert result.baseline_label == "海の宿 潮"


def test_build_comparison_returns_none_when_no_peers(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "孤独な施設", ftype="target")
    db.upsert_scores(conn, fid, {"清潔感": 4.0}, scale=5)
    # no comparison-type facilities
    assert analysis.build_comparison(conn, "孤独な施設", "comparison_avg") is None
    # all_avg: no other facilities
    assert analysis.build_comparison(conn, "孤独な施設", "all_avg") is None


def test_top_n(tmp_path):
    conn = _seed(tmp_path)
    result = analysis.build_comparison(conn, "風の海", "comparison_avg")
    strengths, weaknesses = analysis.top_n(result.diff, n=5)
    # strengths: diff >= 0, sorted descending
    if not strengths.empty:
        assert strengths["差（対象−比較）"].iloc[0] >= 0
    # weaknesses: diff < 0, sorted ascending
    if not weaknesses.empty:
        assert weaknesses["差（対象−比較）"].iloc[0] < 0


def test_google_matrix_from_review_subscores(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    res = review_csv.parse_reviews(SAMPLES / "sample_reviews.csv")
    fid = db.upsert_facility(conn, "風の海", ftype="target")
    db.insert_reviews(conn, fid, res.reviews)

    mat = analysis.google_matrix(conn)
    assert not mat.empty
    # Rooms:5 → 5/5*100 = 100
    assert abs(mat.loc["風の海", "Rooms"] - 100.0) < 0.1
