"""Tests for SQLite storage + dedup + score upsert (steps 3-4)."""
from pathlib import Path

from src import db, review_csv, score_excel

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _fresh(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    return conn


def test_review_roundtrip_and_dedup(tmp_path):
    conn = _fresh(tmp_path)
    res = review_csv.parse_reviews(SAMPLES / "sample_reviews.csv")
    fid = db.upsert_facility(
        conn, "風の海", ftype="target",
        general_rating=res.general_rating, total_reviews=res.total_reviews,
    )

    inserted, skipped = db.insert_reviews(conn, fid, res.reviews)
    assert (inserted, skipped) == (2, 0)

    # re-uploading the same file must not duplicate
    inserted2, skipped2 = db.insert_reviews(conn, fid, res.reviews)
    assert (inserted2, skipped2) == (0, 2)

    # subscores were expanded
    n_sub = conn.execute("SELECT COUNT(*) FROM review_subscore").fetchone()[0]
    assert n_sub == 4  # 3 (Rooms/Service/Location) + 1 (Service)


def test_score_upsert_overwrites(tmp_path):
    conn = _fresh(tmp_path)
    fid = db.upsert_facility(conn, "風の海")
    db.upsert_scores(conn, fid, {"清潔感": 4.2, "食事": 3.9}, scale=5)
    db.upsert_scores(conn, fid, {"清潔感": 4.5}, scale=5)  # update one axis

    val = conn.execute(
        "SELECT value FROM score WHERE facility_id=? AND metric_name=?",
        (fid, "清潔感"),
    ).fetchone()[0]
    assert val == 4.5
    n = conn.execute("SELECT COUNT(*) FROM score WHERE facility_id=?", (fid,)).fetchone()[0]
    assert n == 2  # still 2 axes, not 3


def test_excel_import_wide(tmp_path):
    conn = _fresh(tmp_path)
    df = score_excel.read_table(SAMPLES / "sample_scores.xlsx")
    guess = score_excel.guess_columns(df)
    assert guess.layout == "wide"
    assert guess.name_col == "施設名"

    scores = score_excel.extract_scores_wide(df, guess.name_col, guess.numeric_cols)
    assert scores["風の海"]["清潔感"] == 4.2
    assert set(scores["風の海"]) == {"清潔感", "スタッフ対応", "食事", "設備", "立地"}
