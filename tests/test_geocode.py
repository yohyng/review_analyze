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


def test_simplify_long_name():
    assert geocode._simplify("高浜市やきものの里かわら美術館・図書館") == "高浜市やきものの里かわら美術館"
    assert geocode._simplify("トヨタ博物館（愛知県長久手市）") == "トヨタ博物館"
    assert geocode._simplify("トヨタ博物館") == "トヨタ博物館"


def test_geocode_falls_back_to_simplified(monkeypatch):
    tried = []

    def fake_one(q):
        tried.append(q)
        if q == "高浜市やきものの里かわら美術館":   # 簡略名だけヒット
            return {"address": "愛知県高浜市青木町9-6-18", "lat": "34.9", "lon": "137.0",
                    "open_year": None, "category": "美術館・博物館"}
        return None

    monkeypatch.setattr(geocode, "_nominatim_one", fake_one)
    geocode._geocode.cache_clear()
    r = geocode._geocode("高浜市やきものの里かわら美術館・図書館")
    assert r and r["address"].startswith("愛知県高浜市")
    assert tried == ["高浜市やきものの里かわら美術館・図書館", "高浜市やきものの里かわら美術館"]


def test_search_candidates_parses(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self):
            return [
                {"name": "容器文化ミュージアム",
                 "display_name": "容器文化ミュージアム, 大山崎町, 乙訓郡, 京都府, 日本",
                 "lat": "34.9", "lon": "135.6", "type": "museum"},
                {"name": "別の施設", "display_name": "別の施設, 東京都, 日本",
                 "lat": "35.6", "lon": "139.7", "type": "attraction"},
            ]
    monkeypatch.setattr("requests.get", lambda *a, **k: R())
    from src import geocode
    cands = geocode.search_candidates("容器文化ミュージアム")
    assert len(cands) == 2
    assert cands[0]["name"] == "容器文化ミュージアム"
    assert "大山崎町" in cands[0]["address"]
    assert cands[0]["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")
    assert cands[0]["category"] == "美術館・博物館"


def test_search_candidates_network_fail(monkeypatch):
    def boom(*a, **k):
        raise Exception("no net")
    monkeypatch.setattr("requests.get", boom)
    from src import geocode
    assert geocode.search_candidates("x") == []
    assert geocode.search_candidates("") == []


def test_ql_escape():
    from src.geocode import _ql_escape
    assert _ql_escape('a"b\\c') == 'a\\"b\\\\c'
    assert _ql_escape("") == ""


def test_discover_by_keyword_parses(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"elements": [
                {"type": "node", "lat": 36.1, "lon": 139.2,
                 "tags": {"name": "小川和紙のふるさと資料館", "tourism": "museum",
                          "addr:prefecture": "埼玉県", "addr:city": "小川町"}},
                {"type": "way", "center": {"lat": 35.5, "lon": 136.9},
                 "tags": {"name": "美濃和紙の里会館", "craft": "paper"}},
                {"type": "node", "tags": {}},          # 名前なし → 除外
                {"type": "node", "lat": 1, "lon": 1,
                 "tags": {"name": "小川和紙のふるさと資料館"}},  # 同名重複 → 除外
            ]}
    monkeypatch.setattr("requests.post", lambda *a, **k: R())
    from src import geocode
    cands = geocode.discover_by_keyword("和紙")
    assert len(cands) == 2
    assert cands[0]["name"] == "小川和紙のふるさと資料館"
    assert "埼玉県" in cands[0]["address"]
    assert cands[0]["category"] == "美術館・博物館"
    assert cands[1]["name"] == "美濃和紙の里会館"
    assert cands[1]["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")


def test_discover_by_keyword_sends_area_and_query(monkeypatch):
    captured = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return {"elements": []}
    def fake_post(url, data=None, headers=None, timeout=None):
        captured["ql"] = data["data"]
        return R()
    monkeypatch.setattr("requests.post", fake_post)
    from src import geocode
    geocode.discover_by_keyword("和紙", area="岐阜県")
    assert "和紙" in captured["ql"]
    assert "岐阜県" in captured["ql"]
    assert "ISO3166-1" not in captured["ql"]     # area指定時は全国検索を使わない

    geocode.discover_by_keyword("和紙")           # area未指定 → 全国
    assert "ISO3166-1" in captured["ql"]


def test_discover_by_keyword_network_fail_and_empty(monkeypatch):
    def boom(*a, **k):
        raise Exception("no net")
    monkeypatch.setattr("requests.post", boom)
    from src import geocode
    assert geocode.discover_by_keyword("和紙") == []
    assert geocode.discover_by_keyword("") == []


def test_parse_maps_url_search_query():
    """Google Maps search URL からクエリを抽出"""
    url = "https://www.google.com/maps/search/?api=1&query=%E7%9F%A5%E6%81%A9%E5%B0%8F%E5%B7%9D"
    result = geocode.parse_maps_url(url)
    assert result == "知恩小川"

    # 複数の query パラム (最初のものを取得)
    url2 = "https://www.google.com/maps/search/?query=cafe&query=museum"
    assert geocode.parse_maps_url(url2) == "cafe"


def test_parse_maps_url_fails_gracefully():
    """URLでなければ None を返す"""
    assert geocode.parse_maps_url("単なる施設名") is None
    assert geocode.parse_maps_url("") is None
    assert geocode.parse_maps_url("https://example.com") is None
    assert geocode.parse_maps_url(None) is None

    # 不正なURL形式
    assert geocode.parse_maps_url("https://maps.google.com/invalid") is None
