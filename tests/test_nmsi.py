"""NMSI の移植（src/nmsi）が VoiceBAUM の中で動くこと。

外部プロジェクト facility-review-pipeline から、DBに触らない計算本体だけを
移した。元は PostgreSQL 直結の CLI だったので、入力の作り方（source.py）は
書き直している。ここではその接ぎ目を固定する。

**LLM は呼ばない**。analyze_sentence_batch を差し替えて、式のほうを検証する。
実際の呼び出しは課金が乗るので、テストから叩かないこと。
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import db
from src.nmsi import pipeline, source
from src.nmsi.models import SentenceAnalysis, SentenceBatch


# ── 入力アダプタ（VoiceBAUM DB → 1文1行）──────────────────────────────── #
def _seed(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "デモ美術館", ftype="target")
    rows = [
        ("r1", 5, "展示がとても良かった。また来たいです。"),
        ("r2", 2, "入口が分かりにくい。案内が少ない！"),
        ("r3", 4, "空いていて快適"),
        ("r4", 3, ""),          # 本文なし → 落ちる
    ]
    for rid, rating, text in rows:
        conn.execute(
            "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
            "VALUES (?,?,?,?,?)", (fid, rid, rating, text, "2025-04-01"))
    conn.commit()
    return conn


def test_sentence_frame_shape(tmp_path):
    conn = _seed(tmp_path)
    df = source.sentence_frame(conn, "デモ美術館")

    assert list(df.columns) == ["review_id", "sentence", "rating"]
    # 本文が空の r4 は含めない（文が作れないため）
    assert set(df["review_id"]) == {"r1", "r2", "r3"}
    # 「。」「！」で割れ、3文字未満は落ちる
    assert "展示がとても良かった" in set(df["sentence"])
    assert "また来たいです" in set(df["sentence"])
    assert df["rating"].tolist()[:2] == [5.0, 5.0]


def test_sentence_frame_is_empty_for_unknown_facility(tmp_path):
    conn = _seed(tmp_path)
    assert source.sentence_frame(conn, "存在しない館").empty


def test_split_drops_fragments_but_keeps_a_short_whole_review():
    assert source.split_sentences("とても良かった。また来たい！ん") == [
        "とても良かった", "また来たい"]
    # 全部が短いときは原文をそのまま1文として残す（無言にしない）
    assert source.split_sentences("最高") == ["最高"]
    assert source.split_sentences("   ") == []


def test_llm_call_estimate_is_shown_before_running():
    # 課金が乗るので、走らせる前に回数を出せること
    assert source.estimate_llm_calls(0) == 0
    assert source.estimate_llm_calls(1) == 1
    assert source.estimate_llm_calls(20) == 1
    assert source.estimate_llm_calls(21) == 2
    assert source.estimate_llm_calls(754) == 38


# ── NMSI の式（LLM は差し替える）────────────────────────────────────── #
def _analysis(idx: int, *, phase: str, sentiment: float, friction: float = 0.0,
              memory: float = 0.0, revisit: float = 0.0) -> SentenceAnalysis:
    return SentenceAnalysis(
        source_index=idx, phase=phase, sentiment=sentiment,
        intensity=1.0, confidence=1.0,
        positive_summary="", negative_summary="",
        memory=memory, self_relation=1.0, revisit=revisit, recommend=revisit,
        wait=friction, congestion=friction, restriction=0.0,
        expectation_gap=0.0, cost_burden=0.0, information_gap=0.0,
        place_mentions=[],
    )


def _fake_llm(monkeypatch, make):
    """analyze_sentence_batch を差し替える。本物は課金される。"""
    from src.nmsi import openai_service

    def _batch(records):
        return SentenceBatch(items=[make(r["index"], r["sentence"])
                                    for r in records])

    monkeypatch.setattr(openai_service, "analyze_sentence_batch", _batch)


def test_nmsi_rises_with_sentiment(monkeypatch):
    src_df = pd.DataFrame([{"review_id": "r1", "sentence": f"文{i}", "rating": None}
                           for i in range(6)])

    def run(sent):
        _fake_llm(monkeypatch, lambda i, _s: _analysis(i, phase="exhibition",
                                                       sentiment=sent))
        analysis, _m = pipeline.analyze_sentences(src_df)
        _table, summary = pipeline.calculate_nmsi(analysis)
        return summary["NMSI"]

    low, mid, high = run(-0.8), run(0.0), run(0.8)
    assert low < mid < high
    assert 0 <= low and high <= 100
    assert mid == pytest.approx(50.0, abs=0.5)   # 中立なら sigmoid(0) = 50


def test_friction_pulls_the_score_down(monkeypatch):
    src_df = pd.DataFrame([{"review_id": "r1", "sentence": f"文{i}", "rating": None}
                           for i in range(4)])

    def run(friction):
        _fake_llm(monkeypatch, lambda i, _s: _analysis(
            i, phase="arrival", sentiment=0.5, friction=friction))
        analysis, _ = pipeline.analyze_sentences(src_df)
        return pipeline.calculate_nmsi(analysis)[1]

    clean, rough = run(0.0), run(1.0)
    assert rough["NMSI"] < clean["NMSI"]
    assert rough["摩擦補正_F"] == pytest.approx(1.0)


def test_phase_weights_are_renormalised_over_observed_phases(monkeypatch):
    # 観測されたフェーズだけで重みを割り直すこと（1フェーズしか無くても
    # そのフェーズの重み 0.18 に縮まず、100%として扱う）
    src_df = pd.DataFrame([{"review_id": "r", "sentence": "文", "rating": None}])
    _fake_llm(monkeypatch, lambda i, _s: _analysis(i, phase="exhibition",
                                                   sentiment=1.0))
    analysis, _ = pipeline.analyze_sentences(src_df)
    table, summary = pipeline.calculate_nmsi(analysis)

    assert list(table["phase"]) == ["exhibition"]
    assert table["重み"].sum() == pytest.approx(1.0)
    assert summary["フェーズ加重効果"] == pytest.approx(1.0)


def test_star_rating_is_blended_in(monkeypatch):
    """星評価は 15% だけ混ぜる（star_blend）。本文の感情を上書きしない。"""
    _fake_llm(monkeypatch, lambda i, _s: _analysis(i, phase="exhibition",
                                                   sentiment=0.0))
    def run(rating):
        src_df = pd.DataFrame([{"review_id": "r", "sentence": "文",
                                "rating": rating}])
        analysis, _ = pipeline.analyze_sentences(src_df)
        return pipeline.calculate_nmsi(analysis)[1]["NMSI"]

    assert run(5.0) > run(3.0) > run(1.0)
    # 星だけで振り切らないこと（本文が中立なら中央から大きく離れない）
    assert abs(run(5.0) - 50.0) < 12


def test_mismatched_llm_output_is_rejected(monkeypatch):
    """LLM が入力と対応しない結果を返したら黙って進まないこと。"""
    src_df = pd.DataFrame([{"review_id": "r", "sentence": f"文{i}", "rating": None}
                           for i in range(3)])
    _fake_llm(monkeypatch, lambda i, _s: _analysis(i + 99, phase="exhibition",
                                                   sentiment=0.5))
    with pytest.raises(ValueError, match="source_index"):
        pipeline.analyze_sentences(src_df)


@pytest.mark.parametrize("sentiment,expect", [
    (1.0, "強い感動・推奨レベル"),
    (-1.0, "不満・失望"),
])
def test_interpretation_follows_the_score(monkeypatch, sentiment, expect):
    src_df = pd.DataFrame([{"review_id": "r", "sentence": "文", "rating": None}])
    _fake_llm(monkeypatch, lambda i, _s: _analysis(i, phase="experience",
                                                   sentiment=sentiment))
    analysis, _ = pipeline.analyze_sentences(src_df)
    assert pipeline.calculate_nmsi(analysis)[1]["解釈"] == expect


def test_core_imports_without_the_openai_package():
    """openai が入っていなくても計算本体は import できること。

    LLM を呼ぶのは実行時だけ。import した瞬間に openai を要求すると、
    鍵を持たない環境（テスト・CI・スライドの描画確認）で落ちる。
    """
    import ast
    from pathlib import Path

    for name in ("pipeline.py", "visitor_pipeline.py"):
        tree = ast.parse((Path("src/nmsi") / name).read_text())
        top = [n for n in tree.body
               if isinstance(n, (ast.Import, ast.ImportFrom))]
        names = []
        for n in top:
            if isinstance(n, ast.Import):
                names += [a.name for a in n.names]
            elif n.module:
                names.append(n.module)
        assert not any(m.split(".")[0] == "openai" for m in names), (
            f"{name} が openai をトップレベルで import している")


# ── 実行の入口（見積り・キャッシュ）──────────────────────────────────── #
def test_plan_shows_the_cost_before_running(tmp_path, monkeypatch):
    """走らせる前に「何回LLMを叩くか」を出せること。黙って課金しない。"""
    from src.nmsi import run

    conn = _seed(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    p = run.plan(conn, "デモ美術館")

    assert p.n_reviews == 3          # 本文のある3件
    assert p.n_sentences == 5
    assert p.llm_calls == 1          # 20文/バッチなので1回
    assert p.ready is True and p.cached is False
    assert p.model


def test_plan_refuses_without_a_key(tmp_path, monkeypatch):
    from src.nmsi import run

    conn = _seed(tmp_path)
    for k in ("OPENAI_API_KEY", "AI_INTEGRATIONS_OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    p = run.plan(conn, "デモ美術館")
    assert p.ready is False
    assert "OPENAI_API_KEY" in p.reason


def test_plan_reports_no_reviews(tmp_path, monkeypatch):
    from src.nmsi import run

    conn = _seed(tmp_path)
    db.upsert_facility(conn, "空の館", ftype="comparison")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    p = run.plan(conn, "空の館")
    assert p.ready is False and p.n_sentences == 0
    assert "口コミ" in p.reason


def test_result_is_cached_so_reopening_costs_nothing(tmp_path, monkeypatch):
    """移植元にはキャッシュが無く、開き直すたびに課金されていた。"""
    from src.nmsi import run

    conn = _seed(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "test-model")

    calls = {"n": 0}

    def _counting(records):
        calls["n"] += 1
        return SentenceBatch(items=[
            _analysis(r["index"], phase="exhibition", sentiment=0.4)
            for r in records])

    from src.nmsi import openai_service
    monkeypatch.setattr(openai_service, "analyze_sentence_batch", _counting)

    first = run.analyze(conn, "デモ美術館")
    assert first["from_cache"] is False and calls["n"] == 1
    assert 0 <= first["nmsi"] <= 100

    second = run.analyze(conn, "デモ美術館")
    assert second["from_cache"] is True
    assert calls["n"] == 1, "キャッシュがあるのに再度LLMを呼んでいる"
    assert second["nmsi"] == first["nmsi"]

    # force なら作り直す
    run.analyze(conn, "デモ美術館", force=True)
    assert calls["n"] == 2


def test_changing_the_model_invalidates_the_cache(tmp_path, monkeypatch):
    """モデルを変えれば数値も変わる。古い結果を返さないこと。"""
    from src.nmsi import openai_service, run

    conn = _seed(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr(openai_service, "analyze_sentence_batch",
                        lambda rs: SentenceBatch(items=[
                            _analysis(r["index"], phase="exhibition",
                                      sentiment=0.4) for r in rs]))

    monkeypatch.setenv("OPENAI_TEXT_MODEL", "model-a")
    run.analyze(conn, "デモ美術館")
    assert run.get_result(conn, "デモ美術館") is not None

    monkeypatch.setenv("OPENAI_TEXT_MODEL", "model-b")
    assert run.get_result(conn, "デモ美術館") is None, "別モデルの結果を使い回している"


def test_new_reviews_invalidate_the_cache(tmp_path, monkeypatch):
    from src.nmsi import openai_service, run

    conn = _seed(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "m")
    monkeypatch.setattr(openai_service, "analyze_sentence_batch",
                        lambda rs: SentenceBatch(items=[
                            _analysis(r["index"], phase="exhibition",
                                      sentiment=0.4) for r in rs]))
    run.analyze(conn, "デモ美術館")
    assert run.get_result(conn, "デモ美術館") is not None

    fid = conn.execute("SELECT id FROM facility WHERE name='デモ美術館'").fetchone()[0]
    conn.execute("INSERT INTO review(facility_id, review_id, rating, text, review_date)"
                 " VALUES (?,?,?,?,?)", (fid, "r9", 5, "新しい口コミ。", "2025-05-01"))
    conn.commit()
    assert run.get_result(conn, "デモ美術館") is None, "口コミが増えたのに古い結果を返している"
