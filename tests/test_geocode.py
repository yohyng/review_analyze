"""Tests for src/geocode.py — offline logic + mocked structured-data parsing.

Network calls (Nominatim/Overpass/Wikidata) fail closed in CI; here we verify
the deterministic parts (year/haversine) and the response-parsing via mocks.
No LLM anywhere.
"""
import requests

from src import geocode


def test_year_parsing():
    assert geocode._year("2015-04-01") == "2015年"
    assert geocode._year("+1998-05-01T00:00:00Z") == "1998年"  # Wikidata time format
    assert geocode._year("明治10年頃 1877") == "1877年"
    assert geocode._year("n/a") is None
    assert geocode._year("") is None


def test_haversine_distance():
    # Tokyo Station -> ~6km away; sanity range
    d = geocode._haversine_m(35.681, 139.767, 35.690, 139.700)
    assert 5000 < d < 7000
    assert geocode._haversine_m(35.0, 135.0, 35.0, 135.0) == 0.0


def test_enrich_fails_closed_without_network():
    # In the sandbox all endpoints are blocked → must not raise, returns {}
    assert geocode.enrich("存在しない施設XYZ_ネットワーク遮断テスト") == {}
    assert geocode.lookup("存在しない施設XYZ_ネットワーク遮断テスト") is None


def _fake_resp(data):
    class R:
        def raise_for_status(self): pass
        def json(self): return data
    return R()


def test_wikidata_inception_parse(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        if params.get("action") == "wbsearchentities":
            return _fake_resp({"search": [{"id": "Q123", "label": "テスト館"}]})
        if params.get("action") == "wbgetentities":
            return _fake_resp({"entities": {"Q123": {"claims": {"P571": [
                {"mainsnak": {"datavalue": {"value": {"time": "+1998-05-01T00:00:00Z"}}}}
            ]}}}})
        return _fake_resp({})

    monkeypatch.setattr(requests, "get", fake_get)
    geocode._wikidata_facts.cache_clear()
    out = geocode._wikidata_facts("ユニーク施設名_テスト_ABC")
    assert out == {"open_year": "1998年"}


def test_wikidata_no_hit(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _fake_resp({"search": []}))
    geocode._wikidata_facts.cache_clear()
    assert geocode._wikidata_facts("該当なし施設_テスト_DEF") == {}
