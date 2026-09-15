"""比較施設を、対象施設と同じ道筋で足せること。

これまでは **DBに入っている施設からしか選べなかった**。対象施設のほうは
「名前かURLを入れる → 口コミの有無を見る → 候補を選ぶ → 確認して集める」
まで通っているのに、比較施設だけ手前で止まっていた。

守りたいのは2つ:
  - 判定から取得まで、同じ関数を通ること（片方だけ直る、を防ぐ）
  - 比較施設として集めたものが、**分析対象を乗っ取らない**こと
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.ui import analysis_mode as am

SRC = Path("src/ui/analysis_mode.py").read_text(encoding="utf-8")


def _src(start: str, end: str) -> str:
    return SRC[SRC.index(start):SRC.index(end)]


def _flows() -> str:
    """URL経路と候補経路の両方（ファイル上は _url_flow のほうが先）。"""
    return _src("def _url_flow", "# ── Background thread")


# --------------------------------------------------------------------------- #
# 同じ道を通ること
# --------------------------------------------------------------------------- #
def test_peer_panel_uses_the_same_plan_and_collect_flow():
    panel = _src("def _peer_add_panel", "def _onboard_panel")
    assert "onboard.plan(" in panel
    assert '_collect_flow(conn, _plan, _kzkey, role="peer")' in panel


def test_peer_panel_handles_every_plan_action():
    """READY / AMBIGUOUS / NOT_FOUND / 収集 の全部に出口があること。"""
    panel = _src("def _peer_add_panel", "def _onboard_panel")
    for action in ("onboard.READY", "onboard.AMBIGUOUS", "onboard.NOT_FOUND"):
        assert action in panel, action


def test_ready_peers_are_added_without_collecting():
    """すでに口コミがあるなら、KAIZODE を呼ばずに足すだけ。"""
    panel = _src("def _peer_add_panel", "def _onboard_panel")
    ready = panel[panel.index("onboard.READY"):panel.index("onboard.AMBIGUOUS")]
    assert "add_peer(" in ready
    assert "_kz_order(" not in ready


def test_collecting_a_peer_needs_login_and_a_key():
    """発注は枠を使うので、対象施設と同じ条件を課す。"""
    panel = _src("def _peer_add_panel", "def _onboard_panel")
    assert "admin_authed" in panel
    assert "_resolve_kaizode_key()" in panel
    assert panel.index("admin_authed") < panel.index('role="peer"')


# --------------------------------------------------------------------------- #
# 着地点が違うこと
# --------------------------------------------------------------------------- #
def test_peer_collection_does_not_hijack_the_target():
    """比較施設として集めたのに分析対象が差し替わる、を防ぐ。"""
    flow = _flows()
    # 対象施設のときだけ an_target を差し替える（URL経路・候補経路の両方）
    assert flow.count('if role == "target":') == 2
    for m in re.finditer(r'if role == "target":\n(\s*)st\.session_state\["an_target"\]',
                         flow):
        assert m                     # 直後の行が an_target の代入であること

    pull = _src("def _kz_pull", "@st.fragment")
    assert 'if _ong.get("role") == "peer":' in pull
    peer = pull[pull.index('_ong.get("role") == "peer"'):]
    head = peer[:peer.index("return True")]
    assert "add_peer(" in head
    assert '"an_target"' not in head
    assert '"an_screen"' not in head


def test_peer_is_registered_as_comparison():
    assert am._ftype("peer") == "comparison"
    assert am._ftype("target") == "target"


def test_labels_say_what_will_happen():
    assert "比較施設" in am._collect_label("peer")
    assert "分析" in am._collect_label("target")
    assert "比較施設に" in am._collect_note("peer", 100)
    assert "残枠 100 件" in am._collect_note("peer", 100)


# --------------------------------------------------------------------------- #
# add_peer
# --------------------------------------------------------------------------- #
@pytest.fixture
def ss(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(am.st, "session_state", state, raising=False)
    return state


def test_add_peer_rotates_the_widget_key(ss):
    """同じ key のままだと multiselect が古い値に戻り、追加が消える。

    st.rerun() はフロント側のウィジェット値を送り直すので、
    session_state からキーを消しても戻ってしまう。key を変えるしかない。
    """
    ss[am.PEERS_KEY] = ["A館"]
    before = am.peer_widget_key()
    assert am.add_peer("B館") is True
    assert ss[am.PEERS_KEY] == ["A館", "B館"]
    assert am.peer_widget_key() != before
    assert ss["an_mode"] == "compare"


def test_failed_add_does_not_rotate_the_key(ss):
    """足せなかったときに key を変えない（入力を無駄に消さない）。"""
    ss[am.PEERS_KEY] = ["A館"]
    before = am.peer_widget_key()
    assert am.add_peer("A館") is False
    assert am.peer_widget_key() == before


def test_search_box_and_multiselect_share_the_nonce(ss):
    """どちらも同じ合図で組み直す（片方だけ残ると噛み合わない）。"""
    src = SRC[SRC.index("def _peer_add_panel"):SRC.index("def _onboard_panel")]
    assert "_box = f\"{PEER_SEARCH}_{_nonce}\"" in src
    assert "key=peer_widget_key()" in SRC


def test_add_peer_refuses_duplicates_and_overflow(ss):
    ss[am.PEERS_KEY] = ["A館"]
    assert am.add_peer("A館") is False
    assert am.add_peer("") is False
    assert am.add_peer("   ") is False

    ss[am.PEERS_KEY] = [f"{i}館" for i in range(am.MAX_PEERS)]
    assert am.add_peer("あふれる館") is False
    assert len(ss[am.PEERS_KEY]) == am.MAX_PEERS


def test_add_peer_starts_from_empty(ss):
    assert am.add_peer("A館") is True
    assert ss[am.PEERS_KEY] == ["A館"]


def test_peer_keys_do_not_collide_with_the_target_flow():
    """同じ画面に両方出るので、ウィジェットのキーが被らないこと。"""
    flow = _flows()
    for k in ("an_go_collect", "an_go_blocked", "an_pick_back",
              "an_url_collect", "an_url_blocked"):
        assert f'key=f"{k}_{{role}}"' in flow, k
    assert 'f"an_pick::{role}::{p.query}"' in flow
