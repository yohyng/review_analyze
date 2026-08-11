"""Google Places からの施設写真取得のテスト。

規約（Google Maps Platform）が設計をほぼ決めている:

  保存してよい        place_id …… 無期限
  保存してはいけない  写真・名称・評価 …… 都度取得

  → 写真は DB に焼かず、Google の URL を <img src> で参照する。
    PPTX には入らない（焼き込み＝保存・再配布のため）。
  → 帰属表示（authorAttributions）が必須。

写真は資料の飾りなので、失敗しても分析を止めない（None を返す）。
"""
from __future__ import annotations

import pytest
import requests

from src import db, places, preview, slides


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(tmp_path / "t.db")
    db.init_db(c)
    for n in ("対象館", "競合A"):
        db.upsert_facility(c, n)
    return c


# --------------------------------------------------------------------------- #
# place_id は保存してよい唯一のもの
# --------------------------------------------------------------------------- #
def test_place_id_round_trips(conn):
    assert db.get_place_id(conn, "対象館") is None
    assert db.set_place_id(conn, "対象館", "ChIJabc")
    assert db.get_place_id(conn, "対象館") == "ChIJabc"


def test_place_ids_are_read_in_one_query(conn):
    db.set_place_id(conn, "対象館", "ChIJa")
    db.set_place_id(conn, "競合A", "ChIJb")
    calls = []
    real = conn.execute
    proxy = type("P", (), {
        "execute": lambda _s, sql, *a: (calls.append(sql) or real(sql, *a)),
    })()
    got = db.place_ids_bulk(proxy, ["対象館", "競合A", "無い館"])
    assert len(calls) == 1
    assert got == {"対象館": "ChIJa", "競合A": "ChIJb"}


def test_place_id_helpers_never_raise():
    class _Broken:
        def execute(self, *_a, **_k):
            raise requests.exceptions.HTTPError("502")

        def commit(self):
            pass

    assert db.get_place_id(_Broken(), "x") is None
    assert db.set_place_id(_Broken(), "x", "y") is False
    assert db.place_ids_bulk(_Broken(), ["x"]) == {}


# --------------------------------------------------------------------------- #
# 検索は「IDのみ」で引く（一番安いSKU）
# --------------------------------------------------------------------------- #
def test_find_place_id_requests_only_the_id(monkeypatch):
    seen = {}

    def _post(url, json=None, timeout=None, headers=None):
        seen.update(url=url, body=json, headers=headers)
        return _FakeResp({"places": [{"id": "ChIJxyz"}]})

    monkeypatch.setattr(requests, "post", _post)
    assert places.find_place_id("国立西洋美術館", "KEY") == "ChIJxyz"
    assert seen["headers"]["X-Goog-FieldMask"] == "places.id", (
        "フィールドを増やすと課金階層が上がる。ID だけを要求すること。"
    )
    assert seen["headers"]["X-Goog-Api-Key"] == "KEY"
    assert seen["body"]["textQuery"] == "国立西洋美術館"


def test_find_place_id_handles_no_match(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: _FakeResp({"places": []}))
    assert places.find_place_id("存在しない館", "KEY") is None


def test_find_place_id_needs_a_name_and_a_key(monkeypatch):
    called = []
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: called.append(1) or _FakeResp({}))
    assert places.find_place_id("", "KEY") is None
    assert places.find_place_id("館", "") is None
    assert called == [], "呼ぶ必要のない場面で API を叩いている"


# --------------------------------------------------------------------------- #
# 写真の取得と帰属表示
# --------------------------------------------------------------------------- #
_PHOTO_PAYLOAD = {
    "photos": [{
        "name": "places/ChIJxyz/photos/AeJbb3",
        "authorAttributions": [{"displayName": "山田太郎"},
                               {"displayName": "Jane Doe"}],
    }]
}


def test_fetch_photo_builds_a_media_url_and_attribution(monkeypatch):
    seen = {}

    def _get(url, timeout=None, headers=None):
        seen.update(url=url, headers=headers)
        return _FakeResp(_PHOTO_PAYLOAD)

    monkeypatch.setattr(requests, "get", _get)
    p = places.fetch_photo("ChIJxyz", "KEY", max_px=600)

    # 住所は同じ呼び出しに相乗りさせる（photos を要求した時点で Pro 階層に
    # なるので、formattedAddress を足しても課金は変わらない）
    assert seen["headers"]["X-Goog-FieldMask"] == "photos,formattedAddress"
    assert p and p.url.startswith(
        "https://places.googleapis.com/v1/places/ChIJxyz/photos/AeJbb3/media")
    assert "maxWidthPx=600" in p.url and "key=KEY" in p.url
    # 帰属表示は必須（規約）
    assert "山田太郎" in p.attribution and "Jane Doe" in p.attribution


def test_fetch_photo_without_attribution_still_credits_google(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp(
        {"photos": [{"name": "places/x/photos/y"}]}))
    p = places.fetch_photo("ChIJxyz", "KEY")
    assert p and p.attribution == "Google"


def test_fetch_photo_returns_none_when_there_are_no_photos(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp({"photos": []}))
    assert places.fetch_photo("ChIJxyz", "KEY") is None


def test_api_failures_never_raise(monkeypatch):
    """写真は資料の飾り。取れなくても分析を止めない。"""
    def _boom(*_a, **_k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "post", _boom)
    assert places.fetch_photo("ChIJxyz", "KEY") is None
    assert places.find_place_id("館", "KEY") is None


# --------------------------------------------------------------------------- #
# 呼び出し回数を減らす（place_id を覚える）
# --------------------------------------------------------------------------- #
def test_place_id_is_looked_up_only_once_per_facility(conn, monkeypatch):
    searches, details = [], []
    monkeypatch.setattr(requests, "post", lambda *a, **k: (
        searches.append(1) or _FakeResp({"places": [{"id": "ChIJxyz"}]})))
    monkeypatch.setattr(requests, "get", lambda *a, **k: (
        details.append(1) or _FakeResp(_PHOTO_PAYLOAD)))

    for _ in range(3):
        assert places.photo_for_facility(conn, "対象館", "KEY")

    assert searches == [1], "place_id を保存していれば検索は1回で済む"
    assert len(details) == 3, "写真は保存できないので毎回取り直す"
    assert db.get_place_id(conn, "対象館") == "ChIJxyz"


def test_photo_is_skipped_without_a_key(conn, monkeypatch):
    called = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: called.append(1))
    monkeypatch.setattr(requests, "get", lambda *a, **k: called.append(1))
    assert places.photo_for_facility(conn, "対象館", "") is None
    assert called == []


# --------------------------------------------------------------------------- #
# スライド側
# --------------------------------------------------------------------------- #
def test_slide_renders_a_remote_photo_url(conn):
    """data: URI ではなく https の URL でも <img src> に入ること。"""
    b = preview.build_bundle(conn, "対象館", {}, None, None)
    b["photo_data_uri"] = "https://places.googleapis.com/v1/x/media?key=K"
    html = slides.slide1_facility_info(b)
    assert 'src="https://places.googleapis.com/v1/x/media?key=K"' in html
    assert "写真なし" not in html.split("施設プロフィール")[1][:600]


def test_slide_shows_the_photo_attribution(conn):
    b = preview.build_bundle(conn, "対象館", {}, None, None)
    b["photo_attribution"] = "写真: Google / 山田太郎"
    html = slides.slide1_facility_info(b)
    assert "Google / 山田太郎" in html, "帰属表示は規約上必須"


def test_slide_without_places_photos_is_unchanged(conn):
    b = preview.build_bundle(conn, "対象館", {}, None, None)
    html = slides.slide1_facility_info(b)
    assert "写真: " not in html
    assert "実測値" in html


# --------------------------------------------------------------------------- #
# 住所も同じ呼び出しで取る（追加課金なし）
# --------------------------------------------------------------------------- #
_DETAILS_PAYLOAD = dict(_PHOTO_PAYLOAD, formattedAddress="東京都台東区上野公園7-7")


def test_details_returns_photo_and_address_in_one_call(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: (
        calls.append(1) or _FakeResp(_DETAILS_PAYLOAD)))

    d = places.fetch_details("ChIJxyz", "KEY")
    assert len(calls) == 1, "写真と住所で2回叩いている"
    assert d.address == "東京都台東区上野公園7-7"
    assert d.photo and d.photo.url


def test_details_survives_a_place_without_photos(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp(
        {"formattedAddress": "北海道帯広市"}))
    d = places.fetch_details("ChIJxyz", "KEY")
    assert d.address == "北海道帯広市" and d.photo is None


def test_details_is_empty_on_failure(monkeypatch):
    def _boom(*_a, **_k):
        raise requests.exceptions.HTTPError("500")
    monkeypatch.setattr(requests, "get", _boom)
    d = places.fetch_details("ChIJxyz", "KEY")
    assert d.address == "" and d.photo is None


def test_address_only_fills_an_empty_field():
    """OSM や手入力で住所が入っていれば、Google の値で上書きしない。"""
    from pathlib import Path

    from src.ui import analysis_mode

    src = Path(analysis_mode.__file__).read_text(encoding="utf-8")
    assert 'not (bundle.get("address") or "").strip()' in src


# --------------------------------------------------------------------------- #
# KAIZODE へ渡す Google マップ URL
# --------------------------------------------------------------------------- #
def test_maps_url_points_at_one_place():
    """検索URLではなく place_id を指す URL。同名の別施設を拾わせない。"""
    assert places.maps_url("ChIJxyz") == (
        "https://www.google.com/maps/place/?q=place_id:ChIJxyz")
    assert places.maps_url("") == ""


def test_resolve_returns_the_place_with_name_and_address(monkeypatch):
    seen = {}

    def _post(url, json=None, timeout=None, headers=None):
        seen.update(headers=headers, body=json)
        return _FakeResp({"places": [{
            "id": "ChIJabc",
            "displayName": {"text": "国立西洋美術館"},
            "formattedAddress": "東京都台東区上野公園7-7",
        }]})

    monkeypatch.setattr(requests, "post", _post)
    r = places.resolve("西洋美術館", "KEY")

    assert r and r.place_id == "ChIJabc"
    assert r.name == "国立西洋美術館"
    assert r.address == "東京都台東区上野公園7-7"
    assert r.maps_url.endswith("place_id:ChIJabc")
    # 人が「この施設で合っているか」を確かめられるよう名前と住所も取る
    assert seen["headers"]["X-Goog-FieldMask"] == (
        "places.id,places.displayName,places.formattedAddress")


def test_resolve_handles_no_match_and_failures(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResp({"places": []}))
    assert places.resolve("存在しない館", "KEY") is None

    def _boom(*_a, **_k):
        raise requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(requests, "post", _boom)
    assert places.resolve("館", "KEY") is None
    assert places.resolve("館", "") is None


def test_kaizode_flow_prefers_the_place_id_url():
    """名前を打たれたら place_id の URL を作り、それを発注に使うこと。"""
    from pathlib import Path

    from src.ui import analysis_mode

    src = Path(analysis_mode.__file__).read_text(encoding="utf-8")
    sec = src[src.index("def _kz_collect_section"):src.index("# ── Background thread")]
    assert "places.resolve(" in sec
    assert '_maps_url = _resolved["url"]' in sec
    # 特定できなかったときは名前での検索URLに落ち、その旨を伝えること
    assert "kaizode.maps_search_url(" in sec
    assert "同名の別施設" in sec
    # 確定した place_id は覚える
    assert "db.set_place_id(" in sec


def test_slide_credits_google_for_the_address(conn):
    """住所も Places のコンテンツ。出所を明記する（規約）。"""
    b = preview.build_bundle(conn, "対象館", {}, None, None)
    b.update(address="東京都台東区上野公園7-7", address_from_google=True)
    html = slides.slide1_facility_info(b)
    assert "東京都台東区上野公園7-7" in html
    assert "住所: Google" in html
    # OSM 由来のときは付けない
    b2 = preview.build_bundle(conn, "対象館", {}, None, None)
    b2["address"] = "東京都台東区上野公園7-7"
    assert "住所: Google" not in slides.slide1_facility_info(b2)
