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


def test_migration_sets_user_version():
    """init_db が PRAGMA user_version を設定し、再実行しても壊れない。"""
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    assert v == db._SCHEMA_VERSION
    db.init_db(conn)                       # idempotent
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db._SCHEMA_VERSION


def test_migration_adds_floor_area_to_old_db(tmp_path):
    """floor_area カラムが無い旧スキーマのDBでも init_db 実行で ALTER 追加される。"""
    import sqlite3
    p = tmp_path / "old.db"
    raw = sqlite3.connect(str(p))
    raw.execute("""CREATE TABLE facility (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
        type TEXT, category TEXT, general_rating REAL, total_reviews INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    raw.execute("INSERT INTO facility(name) VALUES ('旧施設')")
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()

    conn = db.get_conn(p)
    db.init_db(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(facility)").fetchall()]
    assert "floor_area" in cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db._SCHEMA_VERSION

    fid = db.upsert_facility(conn, "旧施設", floor_area="28,500㎡")
    row = conn.execute("SELECT floor_area FROM facility WHERE id=?", (fid,)).fetchone()
    assert row["floor_area"] == "28,500㎡"


def test_upsert_facility_floor_area_coalesce(tmp_path):
    """floor_area も他メタデータ同様 COALESCE 更新（None を渡しても既存値を保持）。"""
    conn = _fresh(tmp_path)
    fid = db.upsert_facility(conn, "施設X", floor_area="10,000㎡")
    row = conn.execute("SELECT floor_area FROM facility WHERE id=?", (fid,)).fetchone()
    assert row["floor_area"] == "10,000㎡"

    db.upsert_facility(conn, "施設X", category="美術館")   # floor_area 未指定
    row = conn.execute("SELECT floor_area, category FROM facility WHERE id=?", (fid,)).fetchone()
    assert row["floor_area"] == "10,000㎡"          # 保持される
    assert row["category"] == "美術館"


def test_monthly_review_counts_groups_and_excludes_invalid(tmp_path):
    conn = _fresh(tmp_path)
    fid = db.upsert_facility(conn, "施設Y")
    revs = [
        review_csv.ParsedReview(review_id=f"r{i}", rating=5, text="x", review_date=d,
                                reviewer_name="A", local_guide=False, likes=None,
                                owner_response="", owner_response_date="", subscores=[])
        for i, d in enumerate([
            "2025-01-05T00:00:00Z", "2025-01-20T00:00:00Z",
            "2025-02-01T00:00:00Z",
            "2025-03-15T00:00:00Z", "2025-03-16T00:00:00Z", "2025-03-17T00:00:00Z",
            "", None,
        ])
    ]
    db.insert_reviews(conn, fid, revs)
    assert db.monthly_review_counts(conn, fid) == [
        ("2025-01", 2), ("2025-02", 1), ("2025-03", 3),
    ]


def test_monthly_review_counts_empty_facility(tmp_path):
    conn = _fresh(tmp_path)
    fid = db.upsert_facility(conn, "口コミ無し施設")
    assert db.monthly_review_counts(conn, fid) == []


# --------------------------------------------------------------------------- #
# 分析キャッシュ（口コミ件数をキーにして自動失効する）
# --------------------------------------------------------------------------- #
def test_topic_score_cache_roundtrip_and_invalidation(tmp_path):
    conn = _fresh(tmp_path)
    fid = db.upsert_facility(conn, "風の海")

    assert db.get_topic_score_cache(conn, fid, 10) is None

    db.set_topic_score_cache(conn, fid, 10, '[{"name": "接客"}]', 62.5, 300)
    got = db.get_topic_score_cache(conn, fid, 10)
    assert got["topics_json"] == '[{"name": "接客"}]'
    assert got["overall_score"] == 62.5
    assert got["n_sentences"] == 300

    # 口コミ件数が変われば別キー → 自動的に再計算される
    assert db.get_topic_score_cache(conn, fid, 11) is None

    # 同一キーの再保存は上書き（重複行を作らない）
    db.set_topic_score_cache(conn, fid, 10, "[]", 70.0, 310)
    assert db.get_topic_score_cache(conn, fid, 10)["overall_score"] == 70.0
    assert conn.execute("SELECT COUNT(*) FROM topic_score_cache").fetchone()[0] == 1


def test_text_profile_cache_roundtrip_and_invalidation(tmp_path):
    conn = _fresh(tmp_path)
    fid = db.upsert_facility(conn, "風の海")

    assert db.get_text_profile_cache(conn, fid, 5) is None

    db.set_text_profile_cache(
        conn, fid, 5,
        '[{"単語": "景色", "スコア": 0.4}]', '[{"フレーズ": "景色 良い", "件数": 3}]',
        "[]", '["最高でした"]', '["残念"]',
    )
    got = db.get_text_profile_cache(conn, fid, 5)
    assert got["tfidf_json"] == '[{"単語": "景色", "スコア": 0.4}]'
    assert got["bigrams_json"] == '[{"フレーズ": "景色 良い", "件数": 3}]'
    assert got["trigrams_json"] == "[]"
    assert got["high_rated_json"] == '["最高でした"]'
    assert got["low_rated_json"] == '["残念"]'

    # 本文ありの件数が増えたら別キー → 再抽出される
    assert db.get_text_profile_cache(conn, fid, 6) is None

    db.set_text_profile_cache(conn, fid, 5, "[]", "[]", "[]", "[]", "[]")
    assert db.get_text_profile_cache(conn, fid, 5)["tfidf_json"] == "[]"
    assert conn.execute("SELECT COUNT(*) FROM text_profile_cache").fetchone()[0] == 1


def test_analysis_caches_cascade_on_facility_delete(tmp_path):
    conn = _fresh(tmp_path)
    fid = db.upsert_facility(conn, "風の海")
    db.set_topic_score_cache(conn, fid, 3, "[]", 50.0, 9)
    db.set_text_profile_cache(conn, fid, 3, "[]", "[]", "[]", "[]", "[]")

    db.delete_facility(conn, fid)

    assert conn.execute("SELECT COUNT(*) FROM topic_score_cache").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM text_profile_cache").fetchone()[0] == 0
