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
    assert am._go_label("target", done) == "KAIZODEのデータで分析する"
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



# ── 0件で完了した収集（2026-11-26 名古屋市美術館で実際に起きた） ──── #
def _done(did):
    return {"dataset_id": did, "dataset_name": "館", "status": kaizode.STATUS_DONE}


def test_empty_finished_collection_is_not_reused():
    """中身の無い収集を「既存あり」として使うと、取り込むものが無く止まる。"""
    pr = kaizode.Probe(datasets=[_done("e")], counts={"e": 0})
    assert pr.empty_ready and not pr.usable
    assert am._reusable(pr) is None             # → 新規取得に戻る


def test_empty_collection_is_skipped_for_one_with_reviews():
    pr = kaizode.Probe(datasets=[_done("e"), _done("f")], counts={"e": 0, "f": 300})
    assert am._reusable(pr)["dataset_id"] == "f"


def test_probe_does_not_call_zero_an_exact_count():
    """0件しか無いなら確定値は出さない（Google の概算に落とす）。"""
    class C:
        def list_datasets(self):
            return [_done("e")]

        def count_reviews(self, did, published_since=None):
            return 0
    pr = kaizode.probe_facility(C(), "館")
    assert pr.known_count is None and pr.counts == {"e": 0}
    assert pr.probe_cost == 1


def test_card_warns_about_an_empty_collection():
    pf = precheck.build(facility="館", remaining=5000, limit=5000)
    pr = kaizode.Probe(datasets=[_done("e")], counts={"e": 0})
    html = am._judgement_card(pf, pr, "")
    assert "既存の収集は0件" in html
    assert "既存の収集あり" not in html


# ── 取り直すと増えるか（2026-11-26「年月が経って件数が増えている」） ── #
def test_extra_estimate_is_the_gap_to_the_google_total():
    # Google 1,600 件 ×0.9 = 1,440 見込み、KAIZODE 1,240 件 → 差 200
    assert precheck.extra_estimate(1600, 1240) == 200


def test_extra_estimate_needs_both_numbers():
    assert precheck.extra_estimate(None, 1240) is None
    assert precheck.extra_estimate(1600, None) is None


def test_extra_estimate_never_goes_negative():
    assert precheck.extra_estimate(1000, 1240) == 0


def test_small_gaps_are_noise():
    """Google の総数には星だけの評価も入る。小さな差で取り直させない。"""
    assert not precheck.worth_refresh(10, 1240)        # 30件未満
    assert not precheck.worth_refresh(50, 2000)        # 5%未満（100件）
    assert precheck.worth_refresh(200, 1240)
    assert not precheck.worth_refresh(0, 1240)


def _exact_pf(n=1240):
    return precheck.build(facility="館", place_id="p", remaining=9999,
                          limit=9999, known_count=n)


def _probe_done(did="d", n=1240, status=kaizode.STATUS_DONE):
    return kaizode.Probe(datasets=[{"dataset_id": did, "dataset_name": "館",
                                    "status": status}],
                         counts={did: n} if status == kaizode.STATUS_DONE else {},
                         known_count=n if status == kaizode.STATUS_DONE else None)


def test_card_shows_the_estimate_before_refreshing(monkeypatch):
    monkeypatch.setattr(am.st, "session_state", {})
    html = am._judgement_card(_exact_pf(), _probe_done(), "", google_count=1600)
    assert "追加の見込み" in html and "約 200 件" in html and "目安" in html


def test_card_hides_the_estimate_when_the_gap_is_noise(monkeypatch):
    monkeypatch.setattr(am.st, "session_state", {})
    html = am._judgement_card(_exact_pf(), _probe_done(), "", google_count=1390)
    assert "追加の見込み" not in html


def test_card_hides_the_estimate_without_a_google_count(monkeypatch):
    monkeypatch.setattr(am.st, "session_state", {})
    html = am._judgement_card(_exact_pf(), _probe_done(), "")
    assert "追加の見込み" not in html


def test_refresh_running_then_done_gives_an_exact_diff(monkeypatch):
    """取り直す前の件数と後の件数の差を「確定」として出す。"""
    ss = {am._refresh_key("d"): {"before": 1240, "seen_running": False}}
    monkeypatch.setattr(am.st, "session_state", ss)

    running = _probe_done(status=10)
    # 進行中を見たら覚える（_kz_probe と同じ処理）
    for d in running.datasets:
        rec = ss.get(am._refresh_key(d["dataset_id"]))
        if rec is not None and d["status"] != kaizode.STATUS_DONE:
            rec["seen_running"] = True
    assert am._refresh_state(running)[0] == "running"
    html = am._judgement_card(_exact_pf(), running, "")
    assert "再収集中" in html

    done = _probe_done(n=1530)
    st_ = am._refresh_state(done)
    assert st_ == ("done", 1240, 1530)
    html = am._judgement_card(_exact_pf(1530), done, "", google_count=1600)
    assert "増えた件数" in html and "+290 件" in html and "確定" in html
    assert "追加の見込み" not in html          # 確定が出たら目安は出さない


def test_done_without_seeing_it_run_is_not_called_exact(monkeypatch):
    """頼んだ直後で、まだ動いていないだけかもしれない。+0件と言わない。"""
    ss = {am._refresh_key("d"): {"before": 1240, "seen_running": False}}
    monkeypatch.setattr(am.st, "session_state", ss)
    pr = _probe_done()
    assert am._refresh_state(pr)[0] == "pending"
    html = am._judgement_card(_exact_pf(), pr, "")
    assert "依頼済み" in html and "増えた件数" not in html


def test_probe_marks_a_refresh_as_seen_running():
    block = SRC[SRC.index("def _kz_probe"):SRC.index("def _refresh_key")]
    assert 'rec["seen_running"] = True' in block


def test_refresh_reruns_the_same_collection_not_a_new_one():
    """取り直しは rerun。新しい収集を作ると二重発注になる。"""
    block = SRC[SRC.index("def _kz_refresh"):SRC.index("def _refresh_controls")]
    assert ".rerun_dataset(did)" in block
    assert "_kz_order(" not in block and "create_dataset" not in block
    # 取り直す前の件数を覚え、状態を読み直す
    assert '{"before": before, "seen_running": False}' in block
    assert 'st.session_state.pop(f"an_kz_probe::{query}", None)' in block


def test_refresh_button_is_offered_in_both_flows():
    for fn, nxt in (("def _collect_flow", "# ── Background thread"),
                    ("def _kz_collect_section", "def _peer_add_panel")):
        block = SRC[SRC.index(fn):SRC.index(nxt)]
        assert "_refresh_controls(" in block, fn


def test_card_shows_last_update_and_schedule(monkeypatch):
    monkeypatch.setattr(am.st, "session_state", {})
    pr = kaizode.Probe(datasets=[{"dataset_id": "d", "dataset_name": "館",
                                  "status": kaizode.STATUS_DONE,
                                  "updated_at": "2026-03-12T04:00:00Z",
                                  "is_scheduled": False}],
                       counts={"d": 1240}, known_count=1240)
    html = am._judgement_card(_exact_pf(), pr, "")
    assert "最終更新 2026-03-12" in html and "定期取得オフ" in html
    assert "最終収集" not in html          # updated_at は名前変更でも動く
