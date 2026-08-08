"""グラフがカードからはみ出さないことのテスト。

背景:
  「口コミ数の推移」の y 軸上限を「mx/4 を切り下げて桁で丸める」で決めていた
  ため、上限がデータの最大値より小さくなることがあった。
      累計 457 件 → 上限 400 → y = -14%（プロット領域の上へ突き抜ける）
      累計 780 件 → 上限 400 → y = -95%（ほぼ1枚ぶん上へ飛び出す）
  13通り試して8通りで再現した。実際にカードの外へ線が出た。

  → 二重の歯止めを置く:
      nice_axis() が top >= mx を必ず満たす
      plot_y()   が範囲外を 0..100 に丸める
    さらに描画側の SVG を overflow:hidden にして構造的に外へ出られなくする。

  ここでは「特定の1件を直した」ではなく、**広い入力範囲で座標が枠内に収まる**
  ことを固定する。
"""
from __future__ import annotations

import re

import pytest

from src import db, preview, slides

_MAXES = [1, 2, 3, 5, 7, 9, 12, 17, 30, 40, 55, 77, 99, 100, 101, 120, 150,
          199, 200, 249, 250, 333, 400, 457, 499, 500, 501, 780, 999, 1000,
          1001, 1200, 3700, 6083, 9999, 12345, 87654]


# --------------------------------------------------------------------------- #
# 軸の上限はデータの最大値を必ず含む
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mx", _MAXES)
def test_axis_top_is_never_below_the_data(mx):
    ticks, top = slides.nice_axis(mx)
    assert top >= mx, f"最大値 {mx} が上限 {top} を超えている＝線が枠外に出る"
    assert ticks[0] == 0 and ticks[-1] == pytest.approx(top)
    assert len(ticks) >= 3


@pytest.mark.parametrize("mx", _MAXES)
def test_axis_is_not_wastefully_loose(mx):
    """安全側に倒しすぎて、グラフが下半分に潰れないこと。"""
    _ticks, top = slides.nice_axis(mx)
    assert mx / top >= 0.5, f"最大値 {mx} に対して上限 {top} は緩すぎる"


@pytest.mark.parametrize("mx", _MAXES)
def test_ticks_are_evenly_spaced(mx):
    ticks, _top = slides.nice_axis(mx)
    gaps = [round(b - a, 9) for a, b in zip(ticks, ticks[1:])]
    assert len(set(gaps)) == 1, f"目盛り間隔が不揃い: {ticks}"


def test_axis_handles_degenerate_input():
    for mx in (0, -5, None):
        ticks, top = slides.nice_axis(mx or 0)
        assert top > 0 and ticks[0] == 0


# --------------------------------------------------------------------------- #
# 座標は必ず 0..100 に収まる
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mx", _MAXES)
def test_plotted_points_stay_inside_the_viewbox(mx):
    _ticks, top = slides.nice_axis(mx)
    for v in (0, 1, mx / 3, mx / 2, mx - 1, mx):
        y = slides.plot_y(v, top)
        assert 0 <= y <= 100, f"v={v} top={top} → y={y}"


def test_plot_y_clamps_values_outside_the_axis():
    """軸の計算を間違えても、描画は枠内で止まる（最後の歯止め）。"""
    assert slides.plot_y(999, 100) == slides.plot_y(100, 100)
    assert slides.plot_y(-50, 100) == slides.plot_y(0, 100)
    assert 0 <= slides.plot_y(float("inf") if False else 1e9, 10) <= 100


def test_plot_y_leaves_room_for_the_stroke():
    """線の太さとマーカーの半径ぶん、上下に余白を残す。"""
    assert slides.plot_y(100, 100) == pytest.approx(slides.PLOT_PAD_TOP)
    assert slides.plot_y(0, 100) == pytest.approx(100 - slides.PLOT_PAD_BOTTOM)


# --------------------------------------------------------------------------- #
# 実際に描いた HTML の座標を検査する
# --------------------------------------------------------------------------- #
def _coords(html: str, attr: str) -> list[float]:
    return [float(m) for m in re.findall(rf'{attr}="(-?[\d.]+)"', html)]


@pytest.mark.parametrize("mx", [40, 55, 100, 199, 457, 780, 999, 3700, 6083])
def test_trend_chart_never_draws_outside_the_plot_area(mx):
    """累積の折れ線と点が、どの件数でも 0..100 の内側に収まること。"""
    n = 24
    trend = [(f"2024-{i % 12 + 1:02d}", round(mx * (i + 1) / n)) for i in range(n)]
    html = slides._trend_body(trend)

    ys = _coords(html, "y1") + _coords(html, "y2")
    for pl in re.findall(r'points="([^"]+)"', html):
        ys += [float(p.split(",")[1]) for p in pl.split()]
    assert ys, "座標が1つも取れていない"
    assert min(ys) >= 0 and max(ys) <= 100, (
        f"最大 {mx} 件で y が {min(ys):.1f}〜{max(ys):.1f} になった（枠外）"
    )
    # マーカーは HTML 側の絶対配置。こちらも 0..100% に収まること
    tops = [float(m) for m in re.findall(r"top:(-?[\d.]+)%", html)]
    assert all(0 <= t <= 100 for t in tops), f"マーカーが枠外: {tops}"


def test_trend_chart_clips_at_the_svg():
    """計算をすり抜けても外へ出ないよう、SVG 自体でクリップする。"""
    html = slides._trend_body([("2024-01", 10), ("2024-02", 457)])
    assert "overflow:hidden" in html
    assert "overflow:visible" not in html


def test_trend_axis_labels_are_integers_for_counts():
    html = slides._trend_body([("2024-01", 10), ("2024-02", 55)])
    assert ">60<" in html and ">60.0<" not in html


# --------------------------------------------------------------------------- #
# マーカーは真円（SVG の <circle> は縦横比で潰れる）
# --------------------------------------------------------------------------- #
def test_markers_are_perfect_circles():
    """preserveAspectRatio="none" の SVG に <circle> を置くと楕円になる。"""
    dots = slides.plot_dots([(10.0, 20.0), (50.0, 80.0)], size=.5, color="#E8386A")
    assert dots.count("border-radius:50%") == 2
    assert "width:0.5cqw" in dots and "height:0.5cqw" in dots, (
        "幅と高さを同じ cqw で指定しないと、縦横比のぶん潰れる"
    )


@pytest.mark.parametrize("fn_name,arg_topics", [
    ("_trend_body", None),
])
def test_trend_markers_are_not_svg_circles(fn_name, arg_topics):
    html = slides._trend_body([("2024-01", 10), ("2024-02", 55)])
    svg = html[html.index("<svg"):html.index("</svg>")]
    assert "<circle" not in svg, "マーカーを SVG 内に置くと楕円に潰れる"


def test_indicator_and_compare_charts_use_round_markers(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for nm in ("target", "peer1", "peer2"):
        db.upsert_facility(conn, nm, ftype="comparison")
    from src import topic_score
    w = 1.0 / len(topic_score.TOPIC_ORDER)
    mk = lambda sv: topic_score.TopicScoreResult(  # noqa: E731
        topics=[topic_score.TopicScore(name=t, weight=w, avg_score=sv * w,
                                       total_score=sv * w, salience=w, sentiment=sv)
                for t in topic_score.TOPIC_ORDER],
        overall_score=sv, n_reviews=10, n_sentences=30, empty=False)
    matrix = {"target": mk(.6), "peer1": mk(.5), "peer2": mk(.7)}
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"])

    for html in (slides.slide2_market_detail(b),
                 slides.slide3_competitor_compare(b),
                 slides.slide4_timeline(b)):
        for svg in re.findall(r"<svg.*?</svg>", html, re.S):
            assert "<circle" not in svg, "折れ線のマーカーが SVG 内にある（楕円になる）"


# --------------------------------------------------------------------------- #
# 評価分布の横軸に数値が出る
# --------------------------------------------------------------------------- #
def _dist_bundle(tmp_path, scores):
    conn = db.get_conn(tmp_path / "d.db")
    db.init_db(conn)
    from src import topic_score
    w = 1.0 / len(topic_score.TOPIC_ORDER)
    matrix = {}
    for i, sv in enumerate(scores):
        nm = f"f{i}"
        db.upsert_facility(conn, nm, ftype="comparison")
        matrix[nm] = topic_score.TopicScoreResult(
            topics=[topic_score.TopicScore(name=t, weight=w, avg_score=sv * w,
                                           total_score=sv * w, salience=w,
                                           sentiment=sv)
                    for t in topic_score.TOPIC_ORDER],
            overall_score=sv, n_reviews=10, n_sentences=30, empty=False)
    return preview.build_bundle(conn, "f0", matrix, None, None)


def test_distribution_shows_numeric_x_axis(tmp_path):
    """低評価／高評価だけだと何の分布か読めないので、5点満点の数値を置く。"""
    b = _dist_bundle(tmp_path, [0.50, 0.55, 0.60, 0.65, 0.70])
    html = slides._distribution_body(b)
    assert "低評価" in html and "高評価" in html
    # 下端 2.50 と上端 3.50 が数値で出ること
    assert "2.50" in html and "3.50" in html


def test_distribution_axis_handles_identical_scores(tmp_path):
    """全施設が同じスコアでも軸が壊れないこと。"""
    b = _dist_bundle(tmp_path, [0.6, 0.6, 0.6])
    html = slides._distribution_body(b)
    assert "3.00" in html


def test_distribution_has_thirteen_bars(tmp_path):
    b = _dist_bundle(tmp_path, [0.4, 0.5, 0.6, 0.7, 0.8])
    html = slides._distribution_body(b)
    assert html.count("border-radius:.18cqw .18cqw 0 0") == 13
