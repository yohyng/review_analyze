"""スライドごとの「このページが示していること」（LLM生成）。

設計の要:
  - スライドは描画のたびに走る。**描画から課金が飛ばないこと**。
  - 生成は事前に1回。鍵は (施設, スライド, 事実のハッシュ, モデル)。
    元の数字が変われば作り直され、文言だけ変えても作り直されない。
  - テストから本物のAPIを叩かないこと（課金される）。
"""
from __future__ import annotations

import json

import pytest

from src import db, slide_summary as ss


def _bundle(**over):
    b = {
        "target": "デモ美術館", "n_reviews": 500,
        "baseline_label": "全体平均", "scope_label": "市場内",
        "rank": 3, "total_fac": 46, "overall_sentiment": 74.0,
        "topic_names": ["展示", "価格", "接客"],
        "topic_values": [80.0, 40.0, 65.0],
        "overall_topic": {"展示": 60.0, "価格": 55.0, "接客": 60.0},
        "peer_names": ["競合A", "競合B"],
    }
    b.update(over)
    return b


def _conn(tmp_path, facility="デモ美術館"):
    conn = db.get_conn(tmp_path / "s.db")
    db.init_db(conn)
    db.upsert_facility(conn, facility, ftype="target")
    return conn


def _fake_llm(monkeypatch, headline="順位は上位", body="46施設中3位。",
              err="", counter=None):
    from src import llm

    def _call(prompt, api_key, **kw):
        if counter is not None:
            counter.append(prompt)
        if err:
            return None, err
        return {"headline": headline, "body": body}, ""

    monkeypatch.setattr(llm, "call_json", _call)


# ── 何を渡すか ───────────────────────────────────────────────────── #
def test_facts_carry_numbers_not_html():
    """HTMLを投げない。体裁の話をされるし、トークンも無駄になる。"""
    f = ss.facts_for("slide2_market_position", _bundle())
    blob = json.dumps(f, ensure_ascii=False)
    assert "<div" not in blob and "cqw" not in blob
    assert f["順位"] == 3 and f["母数"] == 46
    assert f["総合スコア5点"] == pytest.approx(3.7)


def test_facts_differ_per_slide():
    b = _bundle(nmsi={"nmsi": 72.4, "interpretation": "高満足", "phases": []},
                reliability={"total": 500, "usable": 400, "foreign": 60,
                             "rating_mean": 4.3, "rating_lo": 4.2,
                             "rating_hi": 4.4})
    a = ss.facts_for("slide8_nmsi", b)
    c = ss.facts_for("slide9_data_quality", b)
    assert a["NMSI"] == 72.4
    assert c["使えた"] == 400 and c["日本語以外"] == 60
    assert a != c


def test_every_listed_slide_produces_facts():
    b = _bundle()
    for slide in ss.SLIDE_TITLES:
        f = ss.facts_for(slide, b)
        assert f.get("施設") == "デモ美術館", slide


# ── 鍵の持ち方 ───────────────────────────────────────────────────── #
def test_hash_follows_the_numbers():
    b1 = _bundle()
    b2 = _bundle(rank=5)                     # 数字が変わった
    s = "slide2_market_position"
    assert ss.fact_hash(ss.facts_for(s, b1)) != ss.fact_hash(ss.facts_for(s, b2))


def test_hash_is_stable_for_the_same_numbers():
    s = "slide2_market_position"
    h1 = ss.fact_hash(ss.facts_for(s, _bundle()))
    h2 = ss.fact_hash(ss.facts_for(s, _bundle()))
    assert h1 == h2


# ── 保存と読み出し ───────────────────────────────────────────────── #
def test_get_does_not_talk_to_the_network(tmp_path, monkeypatch):
    """描画側が呼ぶ経路。ここから課金が飛んではいけない。"""
    from src import llm

    def _boom(*a, **k):
        raise AssertionError("描画から LLM を呼んでいる")

    monkeypatch.setattr(llm, "call_json", _boom)
    conn = _conn(tmp_path)
    assert ss.get(conn, "デモ美術館", "slide2_market_position", _bundle()) is None


def test_round_trip(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    b = _bundle()
    _fake_llm(monkeypatch)

    s, err = ss.generate("slide2_market_position", b, "KEY")
    assert not err and s.headline == "順位は上位"
    ss.save(conn, "デモ美術館", "slide2_market_position", b, s)

    got = ss.get(conn, "デモ美術館", "slide2_market_position", b)
    assert got and got.body == "46施設中3位。" and got.from_cache


def test_changing_the_numbers_invalidates_the_summary(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    _fake_llm(monkeypatch)
    b = _bundle()
    s, _ = ss.generate("slide2_market_position", b, "KEY")
    ss.save(conn, "デモ美術館", "slide2_market_position", b, s)

    moved = _bundle(rank=11)
    assert ss.get(conn, "デモ美術館", "slide2_market_position", moved) is None, \
        "数字が変わったのに古い要約を返している"


def test_changing_the_model_invalidates_the_summary(tmp_path, monkeypatch):
    from src import llm

    conn = _conn(tmp_path)
    _fake_llm(monkeypatch)
    b = _bundle()
    ss.save(conn, "デモ美術館", "slide8_nmsi", b,
            ss.Summary("slide8_nmsi", "x", "y"))
    assert ss.get(conn, "デモ美術館", "slide8_nmsi", b)

    monkeypatch.setattr(llm, "GEMINI_MODEL", "別モデル")
    assert ss.get(conn, "デモ美術館", "slide8_nmsi", b) is None


# ── 一括生成 ─────────────────────────────────────────────────────── #
def test_build_all_skips_what_is_already_there(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    calls: list = []
    _fake_llm(monkeypatch, counter=calls)
    b = _bundle()

    first = ss.build_all(conn, "デモ美術館", b, "KEY")
    assert first["created"] == len(ss.SLIDE_TITLES)
    assert len(calls) == len(ss.SLIDE_TITLES)

    calls.clear()
    second = ss.build_all(conn, "デモ美術館", b, "KEY")
    assert second["cached"] == len(ss.SLIDE_TITLES)
    assert second["created"] == 0
    assert calls == [], "保存済みなのに再度呼んでいる"

    calls.clear()
    ss.build_all(conn, "デモ美術館", b, "KEY", force=True)
    assert len(calls) == len(ss.SLIDE_TITLES)


def test_build_all_reports_failures_without_stopping(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    _fake_llm(monkeypatch, err="API エラー (429)")
    r = ss.build_all(conn, "デモ美術館", _bundle(), "KEY",
                     slides=["slide8_nmsi", "slide9_data_quality"])
    assert r["created"] == 0 and len(r["failed"]) == 2
    assert "429" in r["failed"][0][1]


def test_generate_survives_a_junk_response(tmp_path, monkeypatch):
    from src import llm
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: (["これは配列"], ""))
    s, err = ss.generate("slide8_nmsi", _bundle(), "KEY")
    assert not s and err


def test_prompt_forbids_making_things_up():
    """数字にない話をさせない。レポートに載る文なので。"""
    assert "数字にない話をしないこと" in ss.PROMPT
    assert "推測を書かないこと" in ss.PROMPT
    assert "JSON" in ss.PROMPT
