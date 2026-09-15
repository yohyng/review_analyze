"""発注前の確認項目のテスト。

守りたいのは1つ: **何件取るのか誰も見ないまま発注が走らない**こと。
発注は取り消せず、取り込みは月の枠を減らす。
"""
from __future__ import annotations

import pytest

from src import places, precheck


def _pf(**kw):
    base = dict(facility="デモ美術館", place_id="ChIJ_x", review_count=500,
                remaining=9_000, limit=10_000)
    base.update(kw)
    return precheck.build(**base)


def _check(pf, key):
    return next(c for c in pf.checks if c.key == key)


# --------------------------------------------------------------------------- #
# 枠
# --------------------------------------------------------------------------- #
def test_over_quota_blocks_ordering():
    """残枠より多く取りそうなら、押させない。"""
    pf = _pf(review_count=20_000, remaining=1_000)
    assert pf.blocked
    assert _check(pf, "quota").blocking


def test_within_quota_does_not_block():
    pf = _pf(review_count=500, remaining=9_000)
    assert not pf.blocked
    assert _check(pf, "quota").ok
    assert pf.after == 9_000 - pf.expected


def test_big_bite_warns_without_blocking():
    """枠には収まるが半分以上を食うなら、警告はするが止めない。"""
    pf = _pf(review_count=6_000, remaining=9_000)
    assert not pf.blocked
    q = _check(pf, "quota")
    assert not q.ok and not q.blocking


def test_unknown_count_never_blocks_but_always_warns():
    """件数不明を 0 と決めつけない。0 扱いにすると枠の判定が嘘になる。"""
    pf = _pf(review_count=None, remaining=10)
    assert pf.expected is None
    assert pf.after is None
    assert not pf.blocked                      # 不明を理由に止めはしない
    assert not _check(pf, "quota").ok          # が、必ず警告する
    assert not _check(pf, "volume").ok


def test_expected_is_discounted_from_the_google_count():
    """Google の件数をそのまま使わない（KAIZODE が全部は拾えない）。"""
    assert precheck.expected_reviews(1_000) == int(1_000 * precheck.EXPECT_RATIO)
    assert precheck.expected_reviews(1_000) < 1_000
    assert precheck.expected_reviews(None) is None
    assert precheck.expected_reviews(0) == 0


# --------------------------------------------------------------------------- #
# 取り違え・二重取得
# --------------------------------------------------------------------------- #
def test_missing_place_id_warns():
    pf = _pf(place_id="")
    assert not _check(pf, "identity").ok
    assert not pf.blocked          # 名前でも発注自体はできる


def test_thin_facility_warns():
    """30件未満は傾向として読めない。集める前に言う。"""
    pf = _pf(review_count=12)
    assert not _check(pf, "volume").ok
    assert "12" in _check(pf, "volume").detail


def test_already_collected_warns():
    pf = _pf(already=400)
    assert not _check(pf, "duplicate").ok
    assert "400" in _check(pf, "duplicate").detail


def test_no_duplicate_check_when_nothing_collected():
    pf = _pf(already=0)
    assert not any(c.key == "duplicate" for c in pf.checks)


def test_existing_kaizode_dataset_warns():
    pf = _pf(existing_datasets=["デモ美術館"])
    assert not _check(pf, "dataset").ok


# --------------------------------------------------------------------------- #
# 候補の検索
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_candidates_are_sorted_by_review_count(monkeypatch):
    """選ぶ材料は件数。多い順に出す。不明は末尾。"""
    import requests

    payload = {"places": [
        {"id": "a", "displayName": {"text": "分館"},
         "formattedAddress": "A", "userRatingCount": 40, "rating": 4.1},
        {"id": "b", "displayName": {"text": "名前だけ"}, "formattedAddress": "B"},
        {"id": "c", "displayName": {"text": "本館"},
         "formattedAddress": "C", "userRatingCount": 900, "rating": 4.4},
    ]}
    seen = {}

    def _post(url, json=None, timeout=None, headers=None):
        seen["mask"] = headers["X-Goog-FieldMask"]
        return _Resp(payload)

    monkeypatch.setattr(requests, "post", _post)
    cands = places.search_candidates("美術館", "AIzaTest")

    assert [c.name for c in cands] == ["本館", "分館", "名前だけ"]
    assert cands[0].review_count == 900
    assert cands[-1].review_count is None          # 不明を 0 にしない
    assert "userRatingCount" in seen["mask"]
    assert cands[0].maps_url.endswith("place_id:c")


def test_candidates_need_a_key(monkeypatch):
    import requests

    def _boom(*_a, **_k):
        raise AssertionError("キーが無いのに呼んではいけない")

    monkeypatch.setattr(requests, "post", _boom)
    assert places.search_candidates("美術館", "") == []
    assert places.search_candidates("", "AIzaTest") == []


def test_candidate_search_failure_is_not_fatal(monkeypatch):
    """検索が落ちても画面は出す（名前での発注に落とす）。"""
    import requests

    def _boom(*_a, **_k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "post", _boom)
    assert places.search_candidates("美術館", "AIzaTest") == []


# --------------------------------------------------------------------------- #
# 貼られた Google マップURL
# --------------------------------------------------------------------------- #
REAL_URL = (
    "https://www.google.com/maps/place/%E3%82%B0%E3%82%AA%E3%82%B3%E3%82%BF"
    "%E3%83%AF%E3%83%BC/@1.2769781,103.8435312,988m/data=!3m2!1e3!5s0x31da19"
    "1323663569:0x2373592cf65b62e0!4m6!3m5!1s0x31da191325bc591d:0x4ea7065f16"
    "02c02b!8m2!3d1.2769781!4d103.8461061!16s%2Fg%2F11ddwhpnnd?entry=ttu"
    "&g_ep=EgoyMDI2MDkwOC4wIKXMDSoASAFQAw%3D%3D"
)


def test_parses_a_real_place_url():
    from src import maps_link

    link = maps_link.parse(REAL_URL)
    assert link.name == "グオコタワー"
    assert link.fid == "0x31da191325bc591d:0x4ea7065f1602c02b"
    assert link.mid == "/g/11ddwhpnnd"
    assert link.precise


def test_place_coords_beat_the_map_centre():
    """`@…` は地図の中心。施設の座標は `!8m2!3d…!4d…` のほう。

    実例では経度が 103.8435312（中心）と 103.8461061（施設）で食い違う。
    """
    from src import maps_link

    link = maps_link.parse(REAL_URL)
    assert link.lng == 103.8461061       # !4d
    assert link.lng != 103.8435312       # @ の経度ではない


def test_url_is_handed_to_kaizode_untouched():
    """貼られたURLを組み直さないこと（KAIZODE はこの形を正とする）。"""
    from src import maps_link

    assert maps_link.parse(REAL_URL).url == REAL_URL

    src = (__import__("pathlib").Path("src/ui/analysis_mode.py")
           .read_text(encoding="utf-8"))
    flow = src[src.index("def _url_flow"):src.index("def _nearest")]
    assert "_kz_order(conn, kzkey, link.url, _reg)" in flow
    assert "maps_search_url" not in flow
    assert "places.maps_url" not in flow


def test_plain_names_and_other_urls_are_not_maps_links():
    from src import maps_link

    assert maps_link.parse("国立西洋美術館") is None
    assert maps_link.parse("https://example.com/maps/place/x") is None
    assert maps_link.parse("") is None


def test_short_links_are_not_guessed():
    """短縮URLは展開しないと中身が分からない。推測で埋めない。"""
    from src import maps_link

    link = maps_link.parse("https://maps.app.goo.gl/abcDEF123")
    assert link is not None and link.short
    assert link.name == "" and not link.precise


def test_search_style_urls_are_not_precise():
    """名前の検索URLは1件に定まらない。precise と言わないこと。"""
    from src import maps_link

    link = maps_link.parse(
        "https://www.google.com/maps/search/?api=1&query=%E7%BE%8E%E8%A1%93%E9%A4%A8")
    assert link is not None and not link.precise


def test_place_id_urls_are_precise():
    from src import maps_link

    link = maps_link.parse("https://www.google.com/maps/place/?q=place_id:ChIJ_abc-123")
    assert link.place_id == "ChIJ_abc-123"
    assert link.precise
    assert link.name == ""          # `?q=…` を名前として拾わない


def test_plan_does_not_bill_places_for_a_pasted_url(monkeypatch):
    """URL を Places の textQuery に投げないこと（毎回課金される）。"""
    from src import onboard, places

    def _boom(*_a, **_k):
        raise AssertionError("URL のときに Places を呼んではいけない")

    monkeypatch.setattr(places, "resolve", _boom)
    p = onboard.plan(_FakeConn(), REAL_URL, names=[], gmaps_key="AIzaTest")
    assert p.action == onboard.NEW
    assert p.facility == "グオコタワー"
    assert p.maps_url == REAL_URL


class _FakeConn:
    def execute(self, *_a, **_k):
        raise RuntimeError("使わないはず")


def test_mismatched_candidate_is_not_substituted():
    """貼ったURLと名前が合わない候補で件数を埋めないこと。

    埋めると「グオコタワー」に「国立西洋美術館 8,200件」が付き、
    別施設の件数を根拠に発注させることになる。
    """
    from src import maps_link, places
    from src.ui import analysis_mode

    link = maps_link.parse(REAL_URL)            # name = グオコタワー
    cands = [places.Candidate("ChIJ_a", "国立西洋美術館", "東京", 8200, 4.4)]
    assert analysis_mode._nearest(cands, link) is None

    # 名前が合えば拾う
    ok = [places.Candidate("ChIJ_b", "グオコタワー", "Singapore", 900, 4.1)]
    assert analysis_mode._nearest(ok, link).place_id == "ChIJ_b"


def test_unknown_count_is_left_unknown_not_zero():
    """候補が見つからないときは件数不明のまま警告に回す。"""
    pf = precheck.build(facility="グオコタワー", place_id="", review_count=None,
                        remaining=9_000, limit=10_000)
    assert pf.expected is None
    assert not _check(pf, "volume").ok
    assert not pf.blocked
