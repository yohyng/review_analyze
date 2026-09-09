"""分析がどれだけのデータに支えられているか（src/reliability.py）。

レポートは「4.50」と「4.70」を同じ見た目で並べて順位をつけるが、
前者が4件・後者が5,877件なら意味が違う。実データ（デモ46施設）では
口コミ件数が 4〜5,877（中央値166）まで開く。
"""
from __future__ import annotations

import math

import pytest

from src import db, reliability as R


# ── Wilson score interval ────────────────────────────────────────────── #
def test_wilson_never_leaves_zero_to_one():
    for k, n in [(0, 1), (1, 1), (0, 10), (10, 10), (3, 7), (1, 4)]:
        lo, hi = R.wilson(k, n)
        assert 0.0 <= lo <= hi <= 1.0, (k, n, lo, hi)


def test_wilson_has_width_at_the_extremes():
    """正規近似だと p=0 / p=1 で幅0になる。Wilson はならない。

    「10件中10件がポジ」を「ポジ率100%、誤差なし」と出すのは嘘。
    """
    lo, hi = R.wilson(10, 10)
    assert hi == 1.0 and lo < 1.0
    assert hi - lo > 0.2, "10件全部ポジでも幅が必要"

    lo0, hi0 = R.wilson(0, 10)
    assert lo0 == 0.0 and hi0 > 0.2


def test_wilson_narrows_as_n_grows():
    widths = [R.wilson(int(n * 0.8), n)[1] - R.wilson(int(n * 0.8), n)[0]
              for n in (10, 100, 1000)]
    assert widths[0] > widths[1] > widths[2]


def test_wilson_matches_a_known_value():
    # 教科書値: k=5, n=10, z=1.96 → およそ (0.237, 0.763)
    lo, hi = R.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=0.002)
    assert hi == pytest.approx(0.7634, abs=0.002)


def test_wilson_handles_no_data():
    assert R.wilson(0, 0) == (0.0, 1.0)      # 何も言えない＝全区間


# ── 平均の信頼区間 ───────────────────────────────────────────────── #
def test_mean_ci_needs_at_least_two_points():
    assert R.mean_ci([]) is None
    assert R.mean_ci([4.0]) is None, "1件では区間が定義できない"
    assert R.mean_ci([4.0, 5.0]) is not None


def test_mean_ci_uses_t_for_small_samples():
    """n が小さいほど区間は広い。正規近似で押し通すと狭すぎる。"""
    small = R.mean_ci([4, 5, 4, 5])
    large = R.mean_ci([4, 5] * 200)
    assert small and large
    assert (small[2] - small[1]) > (large[2] - large[1]) * 5


def test_mean_ci_brackets_the_mean():
    m, lo, hi = R.mean_ci([1, 2, 3, 4, 5])
    assert lo < m < hi
    assert m == pytest.approx(3.0)


# ── 本文の素性 ───────────────────────────────────────────────────── #
@pytest.mark.parametrize("text,kind", [
    ("とても良かったです", "ja"),
    ("Great museum, worth visiting", "foreign"),
    ("、。！", "symbols"),
    ("", "empty"),
    ("   ", "empty"),
    ("6 ^^", "symbols"),
    ("VR体験 was great", "mixed"),
])
def test_language_classification(text, kind):
    assert R.language_of(text) == kind


# ── 有効性の階層 ─────────────────────────────────────────────────── #
def _seed(tmp_path, rows):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "館", ftype="target")
    for i, (rating, text) in enumerate(rows):
        conn.execute(
            "INSERT INTO review(facility_id, review_id, rating, text, review_date)"
            " VALUES (?,?,?,?,?)", (fid, f"r{i}", rating, text, "2025-04-01"))
    conn.commit()
    return conn


def test_funnel_accounts_for_every_review(tmp_path):
    """全件が必ずどこかに振り分けられること。分母を隠さない。"""
    conn = _seed(tmp_path, [
        (5, "展示がとても良かったです。また来たい。"),   # 使える
        (4, "静かで落ち着ける良い場所でした。"),        # 使える
        (5, "Excellent exhibition and staff"),        # 非日本語
        (3, "、。！"),                                 # 記号のみ
        (4, ""),                                      # 本文なし
        (5, "良い"),                                   # 短文
    ])
    f = R.funnel(conn, "館")
    assert f.total == 6
    assert f.empty + f.symbols + f.foreign + f.short + f.usable == f.total
    assert f.usable == 2 and f.foreign == 1 and f.symbols == 1
    assert f.empty == 1 and f.short == 1
    assert f.with_text == 5
    assert f.sentences >= 3


def test_funnel_rates(tmp_path):
    conn = _seed(tmp_path, [(5, "とても良い展示でした。")] * 8
                 + [(4, "Nice place to visit here")] * 2)
    f = R.funnel(conn, "館")
    assert f.usable_rate == pytest.approx(0.8)
    assert f.foreign_rate == pytest.approx(0.2)


# ── 警告 ─────────────────────────────────────────────────────────── #
def test_small_sample_is_flagged(tmp_path):
    conn = _seed(tmp_path, [(5, "とても良い展示でした。")] * 4)
    a = R.assess(conn, "館")
    assert a.small_sample
    keys = {f.key for f in a.flags}
    assert "small_n" in keys
    assert any("参考値" in f.text for f in a.flags)


def test_a_large_japanese_sample_raises_no_warning(tmp_path):
    conn = _seed(tmp_path, [(4 + (i % 2), f"展示がとても良かったです{i}。また来ます。")
                            for i in range(200)])
    a = R.assess(conn, "館")
    assert not a.small_sample
    assert not [f for f in a.flags if f.level == "warn"], \
        [f.text for f in a.flags]


def test_foreign_heavy_data_is_flagged(tmp_path):
    """トピック辞書も形態素解析も日本語前提。欧文は観点に当たらない。"""
    conn = _seed(tmp_path, [(5, "とても良い展示でした。")] * 60
                 + [(5, "Great museum with nice staff")] * 40)
    a = R.assess(conn, "館")
    warn = {f.key for f in a.flags if f.level == "warn"}
    assert "foreign" in warn
    assert any("日本語以外" in f.text for f in a.flags)


def test_intervals_are_computed_per_review_not_per_sentence(tmp_path):
    """1件の長い口コミが何票も持たないこと。区間が狭く出てしまう。"""
    long_one = "。".join([f"とても良い展示でした{i}" for i in range(30)]) + "。"
    conn = _seed(tmp_path, [(5, long_one), (1, "残念でした。")])
    iv = R.intervals(conn, "館")
    assert iv.n_rated == 2, "文ではなく口コミの数で数えること"
    assert iv.rating_mean == pytest.approx(3.0)


def test_intervals_reflect_sample_size(tmp_path):
    few = _seed(tmp_path / "a", [(5, "良い展示。"), (4, "良い展示。")])
    many = _seed(tmp_path / "b", [(5, "良い展示。"), (4, "良い展示。")] * 100)
    a, b = R.intervals(few, "館"), R.intervals(many, "館")
    assert (a.rating_hi - a.rating_lo) > (b.rating_hi - b.rating_lo)
    assert (a.pos_hi - a.pos_lo) > (b.pos_hi - b.pos_lo)


def test_no_reviews_is_handled(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_facility(conn, "空館", ftype="target")
    a = R.assess(conn, "空館")
    assert a.funnel.total == 0
    assert a.intervals.rating_mean is None
    assert a.funnel.usable_rate == 0.0
