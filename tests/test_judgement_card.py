"""発注前の「取れそうか」判定（最初の画面のなめらかさ）。

2026-11-26 の要望:
  施設名を入れる → データがあればそれを使う → 無ければ KAIZODE を読みに
  行き、データがあるか・どれくらい取れそうかの判定を返す → それを見て
  取得して分析する。
"""
from __future__ import annotations

from pathlib import Path

from src import kaizode, precheck
from src.ui import analysis_mode as am

SRC = Path("src/ui/analysis_mode.py").read_text(encoding="utf-8")


# ── ③ 確定と概算を書き分ける ──────────────────────────────────── #
def test_known_count_beats_the_google_estimate():
    pf = precheck.build(facility="館", place_id="p", review_count=2000,
                        remaining=5000, limit=5000, known_count=1240)
    assert pf.expected == 1240 and pf.exact
    assert pf.volume_note == "確定"


def test_without_known_count_it_is_an_estimate():
    pf = precheck.build(facility="館", place_id="p", review_count=1000,
                        remaining=5000, limit=5000)
    assert pf.expected == int(1000 * precheck.EXPECT_RATIO)
    assert not pf.exact and pf.volume_note == "概算"


def test_unknown_stays_unknown():
    """件数が読めないときに 0 と書かない。枠の判定が嘘になる。"""
    pf = precheck.build(facility="館", remaining=5000, limit=5000)
    assert pf.expected is None and pf.volume_note == "件数不明"


def test_exact_count_still_hits_the_quota_gate():
    pf = precheck.build(facility="館", place_id="p", remaining=100, limit=5000,
                        known_count=1240)
    assert pf.blocked


def test_exact_but_thin_is_flagged():
    pf = precheck.build(facility="館", place_id="p", remaining=5000,
                        limit=5000, known_count=12)
    vol = next(c for c in pf.checks if c.key == "volume")
    assert not vol.ok and "確定" in vol.detail


# ── ② 判定を1枚にまとめる ─────────────────────────────────────── #
def _probe(**kw):
    return kaizode.Probe(**kw)


def test_card_says_exact_when_kaizode_answered():
    pf = precheck.build(facility="館", place_id="p", remaining=5000,
                        limit=5000, known_count=1240)
    pr = _probe(datasets=[{"dataset_name": "館", "status": kaizode.STATUS_DONE}],
                known_count=1240, probe_cost=1)
    html = am._judgement_card(pf, pr, "館", "愛知県")
    assert "既存の収集あり" in html
    assert "1,240 件" in html and "確定" in html
    assert "約 1,240" not in html


def test_card_says_estimate_when_it_is_one():
    pf = precheck.build(facility="館", place_id="p", review_count=1000,
                        remaining=5000, limit=5000)
    html = am._judgement_card(pf, _probe(), "館")
    assert "新規" in html
    assert "約 900 件" in html and "概算" in html


def test_card_does_not_call_a_running_collection_exact():
    pf = precheck.build(facility="館", place_id="p", review_count=1000,
                        remaining=5000, limit=5000)
    pr = _probe(datasets=[{"dataset_name": "館", "status": 10}])
    html = am._judgement_card(pf, pr, "館")
    assert "収集が進行中" in html and "確定" not in html.split("取得見込み")[1][:200]


def test_card_without_a_key_says_unchecked():
    pf = precheck.build(facility="館", place_id="p", review_count=1000,
                        remaining=5000, limit=5000)
    html = am._judgement_card(pf, None, "館")
    assert "未確認" in html


def test_card_escapes_names():
    pf = precheck.build(facility="x", remaining=1, limit=1)
    html = am._judgement_card(pf, _probe(), "<script>x</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_card_replaces_the_scattered_captions():
    """判定は1枚に集める。チェックを箇条書きで並べ直さない。"""
    block = SRC[SRC.index("def _collect_flow"):SRC.index("# ── Background thread")]
    assert "_judgement_card(" in block
    assert 'st.caption(f"{_icon} **{_c.label}**' not in block


# ── 件数を聞くコスト ─────────────────────────────────────────────── #
def test_probe_is_cached_and_charged_to_the_ledger():
    """1施設1回。引かれたぶんは帳簿に付ける。"""
    block = SRC[SRC.index("def _kz_probe"):SRC.index("def _judgement_card")]
    assert "an_kz_probe::" in block and "in st.session_state" in block
    assert "kaizode.add_monthly_usage(conn, pr.probe_cost)" in block


# ── ① 二度打ちをやめる ─────────────────────────────────────────── #
def test_collect_section_does_not_ask_for_the_name_again():
    block = SRC[SRC.index("def _kz_collect_section"):SRC.index("def _peer_add_panel")]
    assert '"Google MapsのURL または 施設名を入力"' not in block
    assert "_inp = (_ovr or \"\").strip() or query" in block
    # URL で指し直す欄は畳んで残す
    assert "URL で指定し直す" in block


def test_override_box_key_is_per_facility():
    """key を使い回すと、前の施設の URL が復元されて別の施設に発注する。"""
    block = SRC[SRC.index("def _kz_collect_section"):SRC.index("def _peer_add_panel")]
    assert '_ikey = f"an_kz_url_input::{query}"' in block
    assert 'key="an_kz_url_input"' not in block


def test_collect_section_respects_the_quota_gate():
    block = SRC[SRC.index("def _kz_collect_section"):SRC.index("def _peer_add_panel")]
    assert "if _pf.blocked:" in block


# ── 入口 ───────────────────────────────────────────────────────── #
def test_empty_database_still_shows_the_search_box():
    """空のDBで st.stop() しない。施設名を入れれば取りに行ける。"""
    assert "データを登録しましょう" not in SRC
    head = SRC[SRC.index("def render():"):SRC.index("SETUP SCREEN")]
    code = [ln for ln in head.splitlines() if not ln.strip().startswith("#")]
    assert not any("st.stop()" in ln for ln in code)


# ── 既存の収集は発注せずに使う ─────────────────────────────────── #
def test_reusable_prefers_a_finished_collection():
    pr = kaizode.Probe(datasets=[
        {"dataset_id": "run", "dataset_name": "館", "status": 10},
        {"dataset_id": "done", "dataset_name": "館", "status": kaizode.STATUS_DONE},
    ])
    assert am._reusable(pr)["dataset_id"] == "done"


def test_reusable_falls_back_to_a_running_collection():
    """進行中を見つけたら、新しく発注せずに完了を待つ（二重発注しない）。"""
    pr = kaizode.Probe(datasets=[{"dataset_id": "run", "dataset_name": "館",
                                  "status": 10}])
    assert am._reusable(pr)["dataset_id"] == "run"


def test_nothing_to_reuse_without_a_probe_or_on_error():
    assert am._reusable(None) is None
    assert am._reusable(kaizode.Probe()) is None
    assert am._reusable(kaizode.Probe(
        datasets=[{"dataset_id": "x", "status": kaizode.STATUS_DONE}],
        error="500")) is None


def test_button_says_whether_it_orders_or_imports():
    """押す前に、発注なのか取り込みなのかが分かること。"""
    done = {"dataset_id": "d", "status": kaizode.STATUS_DONE}
    run = {"dataset_id": "r", "status": 10}
    assert "取り込んで分析" in am._go_label("target", done)
    assert "完了を待って分析" in am._go_label("target", run)
    assert "比較に追加" in am._go_label("peer", done)
    assert am._go_label("target", None) == am._collect_label("target")


def test_reuse_skips_the_order():
    """既存の収集があるときは _kz_order を呼ばずに、その ID を追う。"""
    for fn, nxt in (("def _collect_flow", "# ── Background thread"),
                    ("def _kz_collect_section", "def _peer_add_panel")):
        block = SRC[SRC.index(fn):SRC.index(nxt)]
        assert '_reuse.get("dataset_id") if _reuse' in block, fn
        i = block.index('_reuse.get("dataset_id") if _reuse')
        assert "_kz_order(" in block[i:i + 200], fn   # 無いときだけ発注


def test_wrong_match_has_a_way_out():
    """照合は名前の部分一致。別の施設を拾っていたら新しく取り直せること。"""
    block = SRC[SRC.index("def _collect_flow"):SRC.index("# ── Background thread")]
    assert "別の施設なので新しく取得する" in block
