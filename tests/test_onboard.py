"""新規施設の追加を「名前 → 1クリック → あとは自動」にするためのテスト。

これまでの導線は9ステップ・テキスト入力2回・画面遷移ありだった。
入力された名前から「次に何をすべきか」を1つに決められることを固定する。
"""
from __future__ import annotations

import pytest
import requests

from src import db, onboard, review_csv


def _mk(i: int, text: str) -> review_csv.ParsedReview:
    return review_csv.ParsedReview(
        review_id=f"r{i}", rating=4, text=text,
        review_date="2025-01-01T00:00:00Z", reviewer_name="u",
        local_guide=False, likes=None, owner_response="",
        owner_response_date="", subscores=[],
    )


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(tmp_path / "t.db")
    db.init_db(c)
    fid = db.upsert_facility(c, "国立西洋美術館")
    db.insert_reviews(c, fid, [_mk(i, "とても良い展示でした。") for i in range(3)])
    db.upsert_facility(c, "空っぽ美術館")            # 施設だけあって口コミ無し
    db.upsert_facility(c, "県立近代美術館")
    db.upsert_facility(c, "市立近代美術館")
    c.commit()
    return c


# --------------------------------------------------------------------------- #
# 次に何をすべきか
# --------------------------------------------------------------------------- #
def test_existing_facility_with_reviews_is_ready(conn):
    p = onboard.plan(conn, "国立西洋美術館")
    assert p.action == onboard.READY
    assert p.facility == "国立西洋美術館" and p.n_reviews == 3
    assert not p.needs_collection
    assert "3" in p.label and "分析する" in p.label


def test_existing_facility_without_reviews_needs_collection(conn):
    p = onboard.plan(conn, "空っぽ美術館")
    assert p.action == onboard.EMPTY
    assert p.needs_collection
    assert "集めて分析する" in p.label


def test_a_single_fuzzy_hit_is_treated_as_that_facility(conn):
    """1件に絞れるなら、選ばせずにそのまま進める。"""
    p = onboard.plan(conn, "国立西洋")
    assert p.action == onboard.READY and p.facility == "国立西洋美術館"


def test_multiple_hits_ask_the_user_to_choose(conn):
    p = onboard.plan(conn, "近代美術館")
    assert p.action == onboard.AMBIGUOUS
    assert set(p.candidates) >= {"県立近代美術館", "市立近代美術館"}
    assert p.label == ""            # ボタンは出さない


def test_unknown_name_resolves_through_google(conn, monkeypatch):
    from src import places

    monkeypatch.setattr(requests, "post", lambda *a, **k: type(
        "R", (), {"raise_for_status": lambda s: None,
                  "json": lambda s: {"places": [{
                      "id": "ChIJ_new",
                      "displayName": {"text": "魔法の文学館"},
                      "formattedAddress": "千葉県市川市"}]}})())

    p = onboard.plan(conn, "魔法の文学館", gmaps_key="KEY")
    assert p.action == onboard.NEW
    assert p.place_id == "ChIJ_new"
    assert p.display_name == "魔法の文学館" and p.address == "千葉県市川市"
    assert p.maps_url.endswith("place_id:ChIJ_new")
    assert "集めて分析する" in p.label


def test_unknown_name_without_a_key_still_offers_collection(conn):
    """Google キーが無くても、名前だけで発注はできる。"""
    p = onboard.plan(conn, "まったく新しい館")
    assert p.action == onboard.NEW and p.needs_collection
    assert p.place_id == ""


def test_empty_query_is_not_found(conn):
    for q in ("", "   ", None):
        assert onboard.plan(conn, q).action == onboard.NOT_FOUND


def test_plan_does_not_call_google_when_the_db_already_answers(conn, monkeypatch):
    called = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: called.append(1))
    onboard.plan(conn, "国立西洋美術館", gmaps_key="KEY")
    onboard.plan(conn, "空っぽ美術館", gmaps_key="KEY")
    onboard.plan(conn, "近代美術館", gmaps_key="KEY")
    assert called == [], "DBで答えが出る場面で Google を叩いている"


# --------------------------------------------------------------------------- #
# 登録と発注
# --------------------------------------------------------------------------- #
def test_register_creates_the_facility_and_remembers_place_id(conn):
    p = onboard.Plan(action=onboard.NEW, query="新館", facility="新館",
                     place_id="ChIJ_x")
    assert onboard.register(conn, p) == "新館"
    assert db.get_place_id(conn, "新館") == "ChIJ_x"
    # 二度呼んでも増えない
    onboard.register(conn, p)
    n = conn.execute("SELECT COUNT(*) FROM facility WHERE name='新館'").fetchone()[0]
    assert n == 1


def test_register_is_a_no_op_for_an_empty_name(conn):
    assert onboard.register(conn, onboard.Plan(action=onboard.NEW)) == ""


def test_collect_url_prefers_the_place_id(conn):
    p = onboard.Plan(action=onboard.NEW, query="新館", facility="新館",
                     maps_url="https://www.google.com/maps/place/?q=place_id:ChIJ_x")
    assert onboard.collect_url(p).endswith("place_id:ChIJ_x")


def test_collect_url_falls_back_to_a_name_search(conn):
    p = onboard.Plan(action=onboard.NEW, query="新館", facility="新館")
    url = onboard.collect_url(p)
    assert url and "place_id" not in url


def test_register_survives_a_broken_connection():
    class _Broken:
        def execute(self, *_a, **_k):
            raise requests.exceptions.HTTPError("502")

        def commit(self):
            pass

    p = onboard.Plan(action=onboard.NEW, query="新館", facility="新館")
    with pytest.raises(Exception):
        onboard.register(_Broken(), p)      # 登録の失敗は握らない（発注前に気づきたい）


# --------------------------------------------------------------------------- #
# 画面側の配線
#
#   「押すべきボタンは常に1つ」「押した先は最後まで自動」を固定する。
# --------------------------------------------------------------------------- #
def _ui_src() -> str:
    from pathlib import Path

    from src.ui import analysis_mode

    return Path(analysis_mode.__file__).read_text(encoding="utf-8")


def _panel_src() -> str:
    src = _ui_src()
    return src[src.index("def _onboard_panel"):src.index("# ── Background thread")]


def test_hero_uses_the_plan_instead_of_hand_rolled_branches():
    src = _ui_src()
    assert "onboard.plan(" in src
    assert "_onboard_panel(" in src
    assert "候補に無い？ KAIZODEで新しく収集する" not in src


def test_collect_button_registers_orders_and_starts_the_analysis():
    """1クリックで「登録 → 発注 → 自動で待つ → 分析」まで繋がっていること。"""
    panel = _panel_src()
    assert "onboard.register(conn, p)" in panel
    assert "_kz_order(" in panel
    assert '"auto_analyze": True' in panel
    assert 'st.session_state["an_target"] = _name' in panel


def test_import_chains_into_the_analysis_when_started_in_one_click():
    """待った末にもう一度ボタンを押させない。"""
    src = _ui_src()
    pull = src[src.index("def _kz_pull"):src.index("@st.fragment")]
    assert 'if _ong.get("auto_analyze"):' in pull
    assert 'st.session_state["an_screen"] = "running"' in pull


def test_unresolved_places_are_flagged_before_ordering():
    """収集枠を使う操作なので、施設を特定できていないことは隠さない。"""
    panel = _panel_src()
    assert "同名の別施設を拾う可能性" in panel
    assert "残枠" in panel


def test_ready_path_does_not_touch_kaizode():
    """既に口コミがある施設は、収集の導線を出さない。"""
    panel = _panel_src()
    ready = panel[panel.index("if p.action == onboard.READY:"):
                  panel.index("# ここから先は収集が要る")]
    assert "_kz_order" not in ready and "kaizode" not in ready
