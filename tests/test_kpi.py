"""22観点 → KPI の対応（資料「企業ミュージアム統合分析GPT」§8）。

計算は増やさない。既存のスコアに「この観点はどのKPIに効くか」を添えるだけ。
"""
from __future__ import annotations

import pytest

from src import kpi, topic_score


def test_every_topic_has_a_kpi_mapping():
    """22観点すべてに対応があること。資料の表と過不足なく一致する。"""
    vb = [t.name for t in topic_score.DEFAULT_TOPICS]
    assert len(vb) == 22
    missing = [t for t in vb if not kpi.kpis_for(t)]
    assert missing == [], f"対応が無い観点: {missing}"

    extra = [t for t in kpi.TOPIC_KPIS if t not in vb]
    assert extra == [], f"22観点に無いものが混ざっている: {extra}"


def test_kpi_catalogue_shape():
    assert len(kpi.KPIS) == 21
    assert len(kpi.LAYERS) == 7
    codes = [k.code for k in kpi.KPIS]
    assert len(set(codes)) == len(codes), "コードが重複している"
    # 各層3指標
    for layer in kpi.LAYERS:
        n = sum(1 for k in kpi.KPIS if k.layer == layer)
        assert n == 3, f"{layer} が {n} 指標"


def test_mappings_only_use_known_codes():
    known = {k.code for k in kpi.KPIS}
    for topic, codes in kpi.TOPIC_KPIS.items():
        unknown = [c for c in codes if c not in known]
        assert unknown == [], f"{topic}: 未定義のKPI {unknown}"


def test_label():
    assert kpi.label("体験満足度") == "CES / EVE / EII"
    assert "来館体験満足" in kpi.label("体験満足度", with_name=True)
    assert kpi.label("存在しない観点") == ""


def test_reverse_lookup():
    topics = kpi.topics_for("CES")
    assert "体験満足度" in topics and "空間の快適性" in topics
    assert kpi.topics_for("XXX") == ()


def test_rollup_is_a_plain_mean():
    """重みの根拠が資料に無いので、勝手な重みを置かないこと。"""
    scores = {t: 50.0 for t in kpi.TOPIC_KPIS}
    scores["体験満足度"] = 100.0        # CES / EVE / EII に効く
    r = kpi.rollup(scores)

    ces_topics = kpi.topics_for("CES")
    expect = sum(scores[t] for t in ces_topics) / len(ces_topics)
    assert r["CES"] == pytest.approx(expect)
    # 効かないKPIは動かない
    assert r["CPI"] == pytest.approx(50.0)


def test_rollup_skips_missing_and_none():
    r = kpi.rollup({"体験満足度": 80.0, "空間の快適性": None})
    assert r["CES"] == pytest.approx(80.0)     # None は数えない
    assert "MSI" not in r                       # 効く観点が1つも無い
    assert kpi.rollup({}) == {}
