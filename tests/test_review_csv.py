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


# --------------------------------------------------------------------------- #
# 取り込み画面のキャッシュが依存する契約:
#   infer_facilities / parse_reviews は BytesIO を受け取り、同じ内容なら
#   何度呼んでも同じ結果を返す（＝ファイル内容キーでのキャッシュが安全）。
# --------------------------------------------------------------------------- #
MULTI_CSV_BYTES = (
    "施設名,review,review_rating,review_date,publisher_name\n"
    "施設A,とても良い,5,2025-01-01,山田\n"
    "施設A,普通,3,2025-01-02,佐藤\n"
    "施設B,最高,5,2025-02-01,田中\n"
    "施設B,いまいち,2,2025-02-02,鈴木\n"
    "施設B,良い,4,2025-02-03,高橋\n"
).encode("utf-8")


def test_infer_facilities_from_bytesio_multi():
    inf = review_csv.infer_facilities(io.BytesIO(MULTI_CSV_BYTES))
    assert [f["name"] for f in inf] == ["施設B", "施設A"]   # 件数の多い順
    assert [f["count"] for f in inf] == [3, 2]


def test_infer_facilities_is_idempotent_on_same_bytes():
    """同じ内容の別 BytesIO で2回呼んでも同一結果（キャッシュ前提の契約）。"""
    a = review_csv.infer_facilities(io.BytesIO(MULTI_CSV_BYTES))
    b = review_csv.infer_facilities(io.BytesIO(MULTI_CSV_BYTES))
    assert a == b


def test_parse_reviews_from_bytesio_with_and_without_key():
    inf = review_csv.infer_facilities(io.BytesIO(MULTI_CSV_BYTES))
    key_b = next(f["key"] for f in inf if f["name"] == "施設B")
    only_b = review_csv.parse_reviews(io.BytesIO(MULTI_CSV_BYTES), facility_key=key_b)
    assert len(only_b.reviews) == 3
    all_rows = review_csv.parse_reviews(io.BytesIO(MULTI_CSV_BYTES), facility_key=None)
    assert len(all_rows.reviews) == 5


def test_parse_reviews_grouped_matches_per_facility():
    """grouped の各施設レビューが per-facility parse と一致する（バルク取込の要）。"""
    inf = review_csv.infer_facilities(io.BytesIO(MULTI_CSV_BYTES))
    grouped = review_csv.parse_reviews_grouped(io.BytesIO(MULTI_CSV_BYTES))
    assert set(grouped.keys()) == {f["key"] for f in inf}
    for f in inf:
        k = f["key"]
        single = review_csv.parse_reviews(io.BytesIO(MULTI_CSV_BYTES), facility_key=k)
        name, res = grouped[k]
        assert [r.review_id for r in res.reviews] == [r.review_id for r in single.reviews]
        assert len(res.reviews) == f["count"]
        assert res.category == single.category


def test_parsers_accept_raw_bytes():
    """アプリは uploaded.getvalue()（生bytes）を渡す — bytes 経路が壊れていないこと。"""
    inf = review_csv.infer_facilities(MULTI_CSV_BYTES)
    assert [f["name"] for f in inf] == ["施設B", "施設A"]
    grp = review_csv.parse_reviews_grouped(MULTI_CSV_BYTES)
    assert set(grp.keys()) == {f["key"] for f in inf}
    res = review_csv.parse_reviews(MULTI_CSV_BYTES)
    assert len(res.reviews) == 5


# --------------------------------------------------------------------------- #
# 代用IDのぶつかり
#   review_id 列が無いCSVでは、本文・日付・投稿者のハッシュを ID に使う。
#   「Good」「Nice」のような短い定型文は**別人でも三つ組が一致する**ので、
#   UNIQUE(facility_id, review_id) に当たって取り込みが丸ごと落ちていた。
# --------------------------------------------------------------------------- #
def _csv(tmp_path, body: str):
    f = tmp_path / "r.csv"
    f.write_bytes(body.encode("utf-8"))
    return str(f)


SHORT_REVIEWS = """place_name,review,review_rating,review_datetime_utc,author_title
Guoco Tower,Good,5,2026-05-01,
Guoco Tower,Good,5,2026-05-01,
Guoco Tower,Good,5,2026-05-01,
Guoco Tower,Good taste,5,2026-07-29,
Guoco Tower,Nice,4,2026-05-01,
"""


def test_identical_short_reviews_get_distinct_ids(tmp_path):
    res = review_csv.parse_reviews(_csv(tmp_path, SHORT_REVIEWS))
    ids = [r.review_id for r in res.reviews]
    assert len(ids) == 5
    assert len(set(ids)) == 5, ids          # 1つも潰さない


def test_duplicates_are_numbered_from_the_first_ones_id(tmp_path):
    """2件目以降に連番を足す。1件目の ID は変えない（既存DBと繋がるので）。"""
    res = review_csv.parse_reviews(_csv(tmp_path, SHORT_REVIEWS))
    goods = [r.review_id for r in res.reviews if r.text == "Good"]
    base = goods[0]
    assert base.startswith(review_csv.FALLBACK_PREFIX) and "#" not in base
    assert goods == [base, f"{base}#2", f"{base}#3"]


def test_disambiguate_reports_how_many_it_split():
    from src.review_csv import ParsedReview, disambiguate_ids

    rs = [ParsedReview(review_id="h:aaa", rating=5, text="Good", review_date="",
                       reviewer_name="", local_guide=False, likes=None,
                       owner_response="", owner_response_date="", subscores=[])
          for _ in range(3)]
    assert disambiguate_ids(rs) == 2
    assert [r.review_id for r in rs] == ["h:aaa", "h:aaa#2", "h:aaa#3"]


def test_same_file_twice_does_not_double_import(tmp_path):
    """採番はファイルの中身で決まるので、入れ直しても重複にならない。"""
    from src import db as _db

    path = _csv(tmp_path, SHORT_REVIEWS)
    conn = _db.get_conn(tmp_path / "t.db")
    _db.init_db(conn)
    fid = _db.upsert_facility(conn, "Guoco Tower")

    first = _db.insert_reviews(conn, fid, review_csv.parse_reviews(path).reviews)
    second = _db.insert_reviews(conn, fid, review_csv.parse_reviews(path).reviews)
    assert first == (5, 0)
    assert second == (0, 5)
    assert conn.execute("SELECT COUNT(*) FROM review").fetchone()[0] == 5


def test_explicit_duplicate_ids_are_skipped_not_fatal(tmp_path):
    """CSV が同じ口コミを2回載せていても、取り込みごと落とさない。"""
    from src import db as _db

    path = _csv(tmp_path, """place_name,review_id,review,review_rating,review_datetime_utc
Guoco Tower,ChZabc,Good,5,2026-05-01
Guoco Tower,ChZabc,Good,5,2026-05-01
Guoco Tower,ChZdef,Nice,4,2026-05-02
""")
    conn = _db.get_conn(tmp_path / "t.db")
    _db.init_db(conn)
    fid = _db.upsert_facility(conn, "Guoco Tower")
    assert _db.insert_reviews(conn, fid, review_csv.parse_reviews(path).reviews) == (2, 1)


def test_explicit_ids_are_not_renumbered(tmp_path):
    """CSV が持っている review_id には触らない（外のIDなので）。"""
    path = _csv(tmp_path, """place_name,review_id,review,review_rating,review_datetime_utc
Guoco Tower,ChZabc,Good,5,2026-05-01
Guoco Tower,ChZabc,Good,5,2026-05-01
""")
    ids = [r.review_id for r in review_csv.parse_reviews(path).reviews]
    assert ids == ["ChZabc", "ChZabc"]


def test_grouped_parse_disambiguates_per_facility(tmp_path):
    """複数施設のCSVでも、施設ごとに採番されること。"""
    path = _csv(tmp_path, """place_name,review,review_rating,review_datetime_utc,author_title
A館,Good,5,2026-05-01,
A館,Good,5,2026-05-01,
B館,Good,5,2026-05-01,
B館,Good,5,2026-05-01,
""")
    groups = review_csv.parse_reviews_grouped(path)
    assert len(groups) == 2
    for _key, (_name, res) in groups.items():
        ids = [r.review_id for r in res.reviews]
        assert len(set(ids)) == len(ids) == 2


def test_import_failure_is_explained_not_redacted():
    """Streamlit Cloud は未捕捉の例外の本文を伏せる。

    画面から原因が分からなくなるので、保存は try で包んで理由を出すこと。
    """
    import sqlite3
    from src.ui.admin_mode import _save_reason

    r = _save_reason(sqlite3.IntegrityError(
        "UNIQUE constraint failed: review.facility_id, review.review_id"))
    assert "同じ口コミID" in r
    assert "review.review_id" in r          # 元の文も残す（切り分け用）

    assert "DBの構造が古い" in _save_reason(
        sqlite3.OperationalError("no such column: review.source"))
    # 知らないエラーは加工せずそのまま
    assert _save_reason(RuntimeError("Turso: なにか")) == "Turso: なにか"


def test_save_is_wrapped_so_the_message_reaches_the_screen():
    src = Path("src/ui/admin_mode.py").read_text(encoding="utf-8")
    block = src[src.index('key="csv_save"'):src.index('elif uploaded and not facility_name')]
    assert "try:" in block
    assert "_save_reason(" in block
    assert block.index("try:") < block.index("db.insert_reviews(")
