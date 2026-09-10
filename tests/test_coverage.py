"""Google にある件数 / KAIZODE が返せる件数 / 分析に使えた件数 の突き合わせ。

①→② が KAIZODE の収集率、②→③ が本ツールの選別率。
どちらで落ちているかを分けて見るためのもの。
"""
from __future__ import annotations

import pytest

from src import coverage, db


def _seed(tmp_path, name="館", rows=None, total_reviews=None):
    conn = db.get_conn(tmp_path / "c.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, name, ftype="target",
                             total_reviews=total_reviews)
    for i, (rating, text) in enumerate(rows or []):
        conn.execute(
            "INSERT INTO review(facility_id, review_id, rating, text, review_date)"
            " VALUES (?,?,?,?,?)", (fid, f"r{i}", rating, text, "2025-04-01"))
    conn.commit()
    return conn


# ── 率の計算 ─────────────────────────────────────────────────────── #
def test_rates():
    c = coverage.Coverage("館", google_total=1000, kaizode_total=800,
                          db_total=780, usable=600)
    assert c.collect_rate == pytest.approx(0.8)
    assert c.import_rate == pytest.approx(780 / 800)
    assert c.usable_rate == pytest.approx(0.6)
    assert c.missing == 200


def test_rates_are_none_when_the_denominator_is_unknown():
    """分からないものを 0% と出さない。推測しない。"""
    c = coverage.Coverage("館", kaizode_total=50, usable=40)
    assert c.collect_rate is None
    assert c.usable_rate is None
    assert c.missing is None

    c2 = coverage.Coverage("館", google_total=0, kaizode_total=0)
    assert c2.collect_rate is None      # 0 で割らない


def test_missing_never_goes_negative():
    """KAIZODE のほうが多いことがある（Googleの表示と収集時点の差）。"""
    c = coverage.Coverage("館", google_total=100, kaizode_total=120)
    assert c.missing == 0


# ── 組み立て ─────────────────────────────────────────────────────── #
def test_uses_the_stored_total_without_any_network(tmp_path):
    """CSV取り込み時に入った総口コミ数を使う。追加の通信も課金も無い。"""
    conn = _seed(tmp_path, rows=[(5, "とても良い展示でした。")] * 30,
                 total_reviews=200)
    cov = coverage.assess(conn, "館")

    assert cov.google_total == 200
    assert cov.google_source == "kaizode"
    assert cov.db_total == 30
    assert cov.usable == 30
    assert cov.kaizode_total is None      # 問い合わせていない


def test_asks_kaizode_when_a_client_is_given(tmp_path):
    conn = _seed(tmp_path, rows=[(5, "とても良い展示でした。")] * 10,
                 total_reviews=100)

    class _K:
        def __init__(self): self.asked = []
        def count_reviews(self, dsid, published_since=None):
            self.asked.append(dsid); return 88

    k = _K()
    cov = coverage.assess(conn, "館", kaizode_client=k, dataset_id="d1")
    assert cov.kaizode_total == 88
    assert k.asked == ["d1"]
    assert cov.collect_rate == pytest.approx(0.88)
    assert cov.missing == 12


def test_survives_a_kaizode_failure(tmp_path):
    conn = _seed(tmp_path, rows=[(5, "良い展示でした。")] * 5, total_reviews=50)

    class _Broken:
        def count_reviews(self, *a, **k): raise RuntimeError("断")

    cov = coverage.assess(conn, "館", kaizode_client=_Broken(), dataset_id="d1")
    assert cov.kaizode_total is None
    assert "KAIZODE" in cov.note
    assert cov.google_total == 50 and cov.db_total == 5   # 他は返る


def test_google_is_only_asked_when_the_total_is_missing(tmp_path, monkeypatch):
    """保存済みがあれば Google に聞かない（課金と規約の両方の理由）。"""
    conn = _seed(tmp_path, rows=[(5, "良い展示でした。")], total_reviews=42)
    called = []

    from src import places
    monkeypatch.setattr(places, "details_for_facility",
                        lambda *a, **k: called.append(1))

    cov = coverage.assess(conn, "館", places_key="KEY")
    assert cov.google_total == 42 and cov.google_source == "kaizode"
    assert called == [], "保存済みがあるのに Google を叩いている"


def test_google_fills_in_when_nothing_is_stored(tmp_path, monkeypatch):
    conn = _seed(tmp_path, rows=[(5, "良い展示でした。")])   # total_reviews なし

    from src import places
    monkeypatch.setattr(
        places, "details_for_facility",
        lambda *a, **k: places.Details(review_count=777, rating=4.4))

    cov = coverage.assess(conn, "館", places_key="KEY")
    assert cov.google_total == 777
    assert cov.google_source == "places"


def test_no_key_means_no_guess(tmp_path):
    conn = _seed(tmp_path, rows=[(5, "良い展示でした。")])
    cov = coverage.assess(conn, "館")
    assert cov.google_total is None and cov.google_source == ""


# ── 集計 ─────────────────────────────────────────────────────────── #
def test_summary_excludes_facilities_with_no_denominator():
    rows = [
        coverage.Coverage("a", google_total=1000, kaizode_total=900, usable=700),
        coverage.Coverage("b", google_total=500, kaizode_total=400, usable=300),
        coverage.Coverage("c", kaizode_total=50, usable=40),   # 母数不明
    ]
    s = coverage.summarize(rows)
    assert s["facilities"] == 3 and s["with_total"] == 2
    assert s["google_total"] == 1500
    assert s["kaizode_total"] == 1300
    assert s["collect_rate"] == pytest.approx(1300 / 1500)
    assert s["usable_rate"] == pytest.approx(1000 / 1500)


def test_summary_handles_an_empty_list():
    s = coverage.summarize([])
    assert s["facilities"] == 0 and s["collect_rate"] is None


# ── Places 側 ────────────────────────────────────────────────────── #
def test_details_carries_the_google_review_count():
    """userRatingCount は photos と同じ階層なので相乗りできる（追加課金なし）。"""
    import inspect
    from src import places

    src = inspect.getsource(places.fetch_details)
    assert "userRatingCount" in src
    # 1回の呼び出しで済ませること（別呼び出しにすると課金が増える）
    assert src.count("_get(") == 1

    d = places.Details(review_count=1234, rating=4.3)
    assert d.review_count == 1234 and d.rating == 4.3
    assert places.Details().review_count is None
