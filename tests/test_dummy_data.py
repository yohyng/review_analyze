"""ダミーデータ生成の回帰テスト。

分析パイプラインの動作確認そのものに使う仕組みなので、
「投入 → 検証 → 削除」が壊れていないことを固定する。
"""
from __future__ import annotations

from src import db, dummy_data


def _conn(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    return conn


def test_build_inserts_the_expected_facilities(tmp_path):
    conn = _conn(tmp_path)
    dummy_data.build(conn)

    names = {r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()}
    assert names == set(dummy_data.facility_names())
    assert len(names) == 12
    assert dummy_data.target_name() in names
    assert len(dummy_data.peer_names()) == 5


def test_build_is_deterministic(tmp_path):
    """固定シードなので、何度実行しても同じ口コミになる。"""
    a = db.get_conn(tmp_path / "a.db"); db.init_db(a)
    b = db.get_conn(tmp_path / "b.db"); db.init_db(b)
    dummy_data.build(a)
    dummy_data.build(b)

    q = ("SELECT r.rating, r.text FROM review r JOIN facility f "
         "ON f.id = r.facility_id WHERE f.name = ? ORDER BY r.review_id")
    ra = [(x[0], x[1]) for x in a.execute(q, (dummy_data.target_name(),)).fetchall()]
    rb = [(x[0], x[1]) for x in b.execute(q, (dummy_data.target_name(),)).fetchall()]
    assert ra and ra == rb


def test_build_replaces_previous_run(tmp_path):
    """二度投入しても重複しない。"""
    conn = _conn(tmp_path)
    dummy_data.build(conn)
    n1 = conn.execute("SELECT COUNT(*) FROM review").fetchone()[0]
    dummy_data.build(conn)
    n2 = conn.execute("SELECT COUNT(*) FROM review").fetchone()[0]
    assert n1 == n2


def test_build_does_not_touch_other_facilities(tmp_path):
    """既存のデータには触れない。"""
    conn = _conn(tmp_path)
    fid = db.upsert_facility(conn, "本物の施設", ftype="target")
    conn.execute(
        "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
        "VALUES (?, ?, ?, ?, ?)", (fid, "real-1", 5, "実データ", "2025-01-01"))
    conn.commit()

    dummy_data.build(conn)
    dummy_data.remove(conn)

    left = [r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()]
    assert left == ["本物の施設"]
    assert conn.execute("SELECT COUNT(*) FROM review").fetchone()[0] == 1


def test_remove_deletes_only_the_dummy_facilities(tmp_path):
    conn = _conn(tmp_path)
    dummy_data.build(conn)
    removed = dummy_data.remove(conn)
    assert removed == len(dummy_data.facility_names())
    assert conn.execute("SELECT COUNT(*) FROM facility").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM review").fetchone()[0] == 0


def test_reviews_have_ratings_dates_and_japanese_text(tmp_path):
    conn = _conn(tmp_path)
    dummy_data.build(conn)
    rows = conn.execute(
        "SELECT rating, text, review_date FROM review LIMIT 200").fetchall()
    assert rows
    for rating, text, d in rows:
        assert 1 <= rating <= 5
        assert text and text.endswith("。")
        assert len(d) >= 10                      # ISO 日付
    # 星評価がばらけている（全部同じではない）
    stars = {r[0] for r in rows}
    assert len(stars) >= 3


def test_event_month_is_within_the_generated_period(tmp_path):
    conn = _conn(tmp_path)
    dummy_data.build(conn)
    ev = dummy_data.event_month()
    rows = conn.execute(
        "SELECT MIN(strftime('%Y-%m', review_date)), "
        "MAX(strftime('%Y-%m', review_date)) FROM review").fetchone()
    assert rows[0] <= ev <= rows[1]


def test_verify_reproduces_the_planted_features(tmp_path):
    """仕込んだ強み・弱み・出来事を分析が再現できる（パイプラインの通し確認）。"""
    conn = _conn(tmp_path)
    dummy_data.build(conn)
    r = dummy_data.verify(conn)

    assert r["target"] == dummy_data.target_name()
    assert r["calibrated"] is True                # 12施設なので較正が効く
    assert 1 <= r["rank"] <= r["total"] == 6
    assert len(r["hit_strong"]) >= 2
    assert len(r["hit_weak"]) >= 2
    assert r["event_detected"] is True
    assert r["ok"] is True


def test_market_facilities_have_varied_profiles():
    """市場背景を全観点フラットにすると分布が歪むので、施設ごとに変えている。"""
    market = [f for f in dummy_data.FACILITIES if f["name"].startswith("市場施設")]
    assert len(market) == 6
    assert all(f["strong"] and f["weak"] for f in market)
    # 6施設が同じ強みの組み合わせになっていない
    combos = {tuple(f["strong"]) for f in market}
    assert len(combos) == 6
