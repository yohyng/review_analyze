"""評価軸のカテゴリ分類と集計。

2026-11-15 のデッキの指示:
  「評価軸のカテゴリごとの評価順位と要約が欲しい。
    コンテンツ 空間設計 サービス 価格・決済 アクセス ブランド 総合評価」

同デッキの評価軸一覧（25項目）がこの7カテゴリで分類されていた。
現行の22観点は軸の名前と数が違うが、**分類そのものは過不足なく載る**。
その前提が崩れたら落ちるようにしておく（軸を25に差し替えるときの番人）。
"""
from __future__ import annotations

import pytest

from src import categories as cat
from src import topic_score as ts


# --------------------------------------------------------------------------- #
# 分類そのもの
# --------------------------------------------------------------------------- #
def test_every_current_axis_belongs_to_exactly_one_category():
    """漏れも重複も作らない。軸を増やしたらここで気づく。"""
    current = [t.name for t in ts.DEFAULT_TOPICS]
    mapped = [n for members in cat.CATEGORIES.values() for n in members]

    assert len(mapped) == len(set(mapped)), "同じ軸が複数カテゴリにある"
    assert set(mapped) == set(current), (
        f"未分類: {sorted(set(current) - set(mapped))} / "
        f"存在しない軸: {sorted(set(mapped) - set(current))}"
    )


def test_categories_match_the_source_document():
    assert cat.ORDER == ("コンテンツ", "空間設計", "サービス",
                         "価格・決済", "アクセス", "ブランド", "総合評価")


def test_category_of_maps_back():
    assert cat.category_of("スタッフ対応") == "サービス"
    assert cat.category_of("再訪意向") == "総合評価"
    assert cat.category_of("知らない軸") is None


# --------------------------------------------------------------------------- #
# 集計
# --------------------------------------------------------------------------- #
def _matrix(**overrides):
    base = {t.name: 50.0 for t in ts.DEFAULT_TOPICS}
    m = {"自施設": {**base, **overrides}}
    for i, d in enumerate([-10, -5, +5, +10], 1):
        m[f"競合{i}"] = {k: v + d for k, v in base.items()}
    return m


def test_category_score_is_the_mean_of_its_axes():
    m = _matrix(**{"スタッフ対応": 90.0, "スタッフ専門性": 60.0, "サービスの種類": 30.0})
    rows = {r.name: r for r in cat.assess("自施設", m)}
    assert rows["サービス"].score == pytest.approx(60.0)
    assert rows["サービス"].n_axes == 3


def test_rank_counts_only_facilities_with_a_value():
    """値の無い施設を母数に入れない。順位が実際より良く見える。"""
    m = _matrix()
    m["競合1"] = {k: v for k, v in m["競合1"].items()
                  if cat.category_of(k) != "アクセス"}
    rows = {r.name: r for r in cat.assess("自施設", m)}
    assert rows["アクセス"].total == 4          # 5施設中、値があるのは4
    assert rows["サービス"].total == 5


def test_ties_take_the_better_rank():
    m = _matrix()
    m["競合1"] = dict(m["自施設"])              # 完全に同点
    rows = {r.name: r for r in cat.assess("自施設", m)}
    # 同点が1位タイのとき、2位に落とさない
    assert rows["サービス"].rank <= 3


def test_missing_axes_do_not_break_the_category():
    m = _matrix()
    del m["自施設"]["スタッフ専門性"]
    rows = {r.name: r for r in cat.assess("自施設", m)}
    assert rows["サービス"].computable
    assert rows["サービス"].n_axes == 2


def test_unknown_target_returns_empty():
    assert cat.assess("居ない施設", _matrix()) == []


def test_standing_words():
    def mk(rank, total):
        return cat.CategoryScore(name="x", score=1.0, rank=rank, total=total)
    assert mk(1, 12).standing == "最上位"
    assert mk(12, 12).standing == "最下位"
    assert mk(2, 12).standing == "上位"
    assert mk(11, 12).standing == "下位"
    assert mk(6, 12).standing == "中位"
    assert cat.CategoryScore(name="x").standing == ""


def test_prompt_facts_carry_no_html():
    rows = cat.assess("自施設", _matrix())
    facts = cat.facts_for_prompt(rows)
    blob = str(facts)
    assert "<" not in blob and "cqw" not in blob
    assert len(facts) == len(cat.ORDER)
    assert all("カテゴリ" in f and "順位" in f for f in facts)
