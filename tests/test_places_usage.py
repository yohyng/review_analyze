"""Google Places の呼び出し回数の帳簿。

Google 側に「今月いくら使ったか」を安く聞く口が無いので、
呼んだ本人（＝このアプリ）が数えるしかない。

守りたいのは2つ:
  - 帳簿のために本来の機能（写真・検索）を止めない
  - 呼び出しの**形**ごとに分けて数える（SKU階層が形で決まるので）
"""
from __future__ import annotations

import pytest
import requests

from src import db, places, places_usage


class _Resp:
    def __init__(self, payload=None, content=b"\x89PNG"):
        self._p = payload or {"places": [{"id": "x"}]}
        self.content = content
        self.headers = {"Content-Type": "image/png"}

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(tmp_path / "u.db")
    db.init_db(c)
    places_usage.install(c)
    yield c
    places.set_recorder(None)


def test_each_call_shape_is_counted_separately(conn, monkeypatch):
    """FieldMask が SKU 階層を決めるので、形ごとに分ける。"""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())

    places.find_place_id("美術館", "AIza")
    places.find_place_id("公園", "AIza")
    places.resolve("美術館", "AIza")
    places.search_candidates("美術館", "AIza")
    places.fetch_details("ChIJ_x", "AIza")
    places.fetch_photo_data_uri("places/x/photos/y", "AIza")

    u = places_usage.usage(conn)
    assert u[places.KIND_SEARCH_ID] == 2
    assert u[places.KIND_SEARCH_BASIC] == 1
    assert u[places.KIND_SEARCH_FULL] == 1
    assert u[places.KIND_DETAILS] == 1
    assert u[places.KIND_PHOTO] == 1
    assert places_usage.total(conn) == 6


def test_calls_without_a_key_are_not_counted(conn, monkeypatch):
    """呼んでいないものを数えない（キーが無ければ通信しない）。"""
    def _boom(*_a, **_k):
        raise AssertionError("呼んではいけない")

    monkeypatch.setattr(requests, "post", _boom)
    monkeypatch.setattr(requests, "get", _boom)

    places.find_place_id("美術館", "")
    places.search_candidates("美術館", "")
    places.fetch_details("ChIJ_x", "")
    places.fetch_photo_data_uri("places/x/photos/y", "")
    assert places_usage.total(conn) == 0


def test_a_failed_call_is_still_counted(conn, monkeypatch):
    """Google に届いていれば課金されうる。失敗しても数える。"""
    def _fail(*_a, **_k):
        raise requests.exceptions.HTTPError("429")

    monkeypatch.setattr(requests, "post", _fail)
    assert places.find_place_id("美術館", "AIza") is None
    assert places_usage.usage(conn)[places.KIND_SEARCH_ID] == 1


def test_a_broken_ledger_never_breaks_the_feature(monkeypatch):
    """帳簿が書けなくても、写真や検索は動くこと。"""
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())

    def _explode(_kind):
        raise RuntimeError("DBが落ちている")

    places.set_recorder(_explode)
    try:
        assert places.find_place_id("美術館", "AIza") == "x"
    finally:
        places.set_recorder(None)


def test_months_are_kept_apart(conn):
    places_usage.add(conn, places.KIND_PHOTO, 3, month="2026-08")
    places_usage.add(conn, places.KIND_PHOTO, 5, month="2026-09")
    assert places_usage.total(conn, "2026-08") == 3
    assert places_usage.total(conn, "2026-09") == 5
    assert places_usage.months(conn) == ["2026-09", "2026-08"]


def test_every_kind_has_a_japanese_label():
    """画面に生のキーを出さない。"""
    kinds = [v for k, v in vars(places).items() if k.startswith("KIND_")
             and isinstance(v, str)]
    for k in kinds:
        assert places.KIND_LABELS.get(k), k


def test_no_price_is_asserted_on_screen():
    """SKU 階層は料金表が正。ここで金額を断定しないこと。"""
    import pathlib

    src = pathlib.Path("src/ui/admin_mode.py").read_text(encoding="utf-8")
    panel = src[src.index("今月の呼び出し"):src.index("分析プレビューで施設写真")]
    assert "円" not in panel and "$" not in panel
    assert "請求画面が正" in panel
