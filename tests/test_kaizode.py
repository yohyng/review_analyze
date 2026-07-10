"""Tests for src/kaizode.py — KAIZODE APIクライアント（ネットワークはモック）。"""
import pytest

from src import db, kaizode
from src.kaizode import KaizodeClient, KaizodeError, facility_name_of, to_parsed_review


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    """記録付きのフェイク requests.Session。queue から順に返す。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "params": params, "json": json})
        return self.responses.pop(0)


def _client(responses):
    sess = FakeSession(responses)
    c = KaizodeClient(api_key="TESTKEY", session=sess, min_interval=0)
    return c, sess


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("KAIZODE_API_KEY", raising=False)
    with pytest.raises(KaizodeError):
        KaizodeClient(session=FakeSession([]))


def test_auth_header_and_list_datasets():
    c, sess = _client([FakeResp(200, {"data": [{"dataset_id": "d1", "status": 30}]})])
    out = c.list_datasets()
    assert out == [{"dataset_id": "d1", "status": 30}]
    call = sess.calls[0]
    assert call["headers"]["x-api-key"] == "TESTKEY"
    assert call["url"].endswith("/datasets")


def test_create_dataset_payload():
    c, sess = _client([FakeResp(201, {"data": {"dataset_id": "new1", "status": 10}})])
    urls = [{"url": "https://example.com/x", "review_target_name": "施設A", "since": "2024-01-01"}]
    ds = c.create_dataset("口コミ対象", urls)
    assert ds["dataset_id"] == "new1"
    assert sess.calls[0]["json"] == {"dataset_name": "口コミ対象", "urls": urls}


def test_iter_reviews_paginates_and_passes_since():
    page0 = {"data": [{"review_id": f"r{i}"} for i in range(3)],
             "pagination": {"total_items": 5, "limit": 3, "page": 0}}
    page1 = {"data": [{"review_id": "r3"}, {"review_id": "r4"}],
             "pagination": {"total_items": 5, "limit": 3, "page": 1}}
    c, sess = _client([FakeResp(200, page0), FakeResp(200, page1)])
    got = list(c.iter_reviews("d1", published_since="2025-01-01", limit=3))
    assert [r["review_id"] for r in got] == ["r0", "r1", "r2", "r3", "r4"]
    assert len(sess.calls) == 2
    assert sess.calls[0]["params"] == {"limit": 3, "page": 0, "published_since": "2025-01-01"}
    assert sess.calls[1]["params"]["page"] == 1


def test_retry_on_429(monkeypatch):
    monkeypatch.setattr(kaizode.time, "sleep", lambda *_: None)
    c, sess = _client([FakeResp(429, {"message": "too many"}),
                       FakeResp(200, {"data": []})])
    assert c.list_datasets() == []
    assert len(sess.calls) == 2


def test_error_raises_with_message():
    c, _ = _client([FakeResp(401, {"message": "認証に失敗しました。"})])
    with pytest.raises(KaizodeError, match="401"):
        c.list_datasets()


def test_to_parsed_review_mapping():
    r = {
        "review_id": "abc123",
        "review_title": "最高でした",
        "review": "展示が素晴らしい。",
        "published_at": "2025-05-27 18:10:57.123",
        "review_rating": 4.0,
        "publisher_name": "山田",
        "review_target_name": "容器文化ミュージアム",
        "sentiment": "ポジティブ",
    }
    p = to_parsed_review(r)
    assert p.review_id == "abc123"
    assert p.rating == 4 and isinstance(p.rating, int)
    assert p.text == "最高でした\n展示が素晴らしい。"
    assert p.review_date == "2025-05-27 18:10:57"
    assert p.reviewer_name == "山田"
    assert p.subscores == []


def test_to_parsed_review_fractional_rating_and_no_title():
    p = to_parsed_review({"review_id": "x", "review": "普通。", "review_rating": 4.5,
                          "published_at": "2025-01-01 00:00:00"})
    assert p.rating == 4.5
    assert p.text == "普通。"


def test_facility_name_fallback():
    assert facility_name_of({"review_target_name": "施設A"}) == "施設A"
    assert facility_name_of({"dataset_name": "DS1"}) == "DS1"
    assert facility_name_of({}, fallback="不明") == "不明"


def test_sync_state_roundtrip():
    conn = db.get_conn(":memory:")
    db.init_db(conn)
    assert kaizode.get_last_sync(conn, "d1") is None
    kaizode.set_last_sync(conn, "d1", "口コミ対象", "2025-05-27 18:10:57")
    assert kaizode.get_last_sync(conn, "d1") == "2025-05-27 18:10:57"
    # 上書き（1データセット1行）
    kaizode.set_last_sync(conn, "d1", "口コミ対象", "2025-06-01 00:00:00")
    assert kaizode.get_last_sync(conn, "d1") == "2025-06-01 00:00:00"
    n = conn.execute("SELECT COUNT(*) FROM kaizode_sync").fetchone()[0]
    assert n == 1


def test_end_to_end_sync_into_db():
    """モックAPI → to_parsed_review → insert_reviews の一気通貫。"""
    reviews = {"data": [
        {"review_id": "k1", "review": "接客が丁寧。", "review_rating": 5,
         "published_at": "2025-05-01 10:00:00", "review_target_name": "施設A"},
        {"review_id": "k2", "review": "混雑していた。", "review_rating": 2,
         "published_at": "2025-05-02 11:00:00", "review_target_name": "施設A"},
    ], "pagination": {"total_items": 2, "limit": 5000, "page": 0}}
    c, _ = _client([FakeResp(200, reviews)])

    conn = db.get_conn(":memory:")
    db.init_db(conn)
    got = list(c.iter_reviews("d1"))
    fid = db.upsert_facility(conn, facility_name_of(got[0]), ftype="comparison",
                             category="口コミ対象")
    ins, skip = db.insert_reviews(conn, fid, [to_parsed_review(r) for r in got])
    assert (ins, skip) == (2, 0)
    # 再取り込みは全て重複スキップ（review_id がそのまま使えている）
    ins2, skip2 = db.insert_reviews(conn, fid, [to_parsed_review(r) for r in got])
    assert (ins2, skip2) == (0, 2)
