"""画面スライドと PPTX が同じ数字を出すことの回帰テスト。

v0.51.0 以前、較正（calibrate_matrix）は preview.build_bundle の中でしか
走らず、その手前で呼ばれる report.build_report には素点が渡っていた。
同じ分析なのに画面が「3.85 / 5」、客先に出る PPTX が「66 / 100」(=3.30/5)
と食い違う。較正は分布を広げる処理なので、上位施設ほどズレが大きい。
"""
from __future__ import annotations

import ast
from pathlib import Path

from src import preview, topic_score
from src.ui import analysis_mode

WORKER_SRC = Path(analysis_mode.__file__).read_text()


TOPICS = [t.name for t in topic_score.DEFAULT_TOPICS]


def _result(sentiment: float) -> topic_score.TopicScoreResult:
    """全観点が同じ感情値の結果。較正で動くことが分かればよい。"""
    w = 1.0 / len(TOPICS)
    return topic_score.TopicScoreResult(
        topics=[
            topic_score.TopicScore(name=t, weight=w, avg_score=sentiment * w,
                                   total_score=sentiment * w, salience=w,
                                   sentiment=sentiment)
            for t in TOPICS
        ],
        overall_score=sentiment, n_reviews=50, n_sentences=200, empty=False,
    )


def _matrix(n: int = 10) -> dict:
    # 施設ごとに違う平均 → 較正が効く（CALIBRATION_MIN_FACILITIES 以上必要）
    return {f"f{i}": _result(0.30 + i * 0.04) for i in range(n)}


def test_calibrate_matrix_is_idempotent():
    mat = _matrix()
    once, ok1 = topic_score.calibrate_matrix(mat)
    assert ok1
    twice, ok2 = topic_score.calibrate_matrix(once)
    assert ok2, "較正済みでも『表示値は較正済み』として True を返すこと"

    for name in mat:
        a = once[name].weighted_sentiment_100
        b = twice[name].weighted_sentiment_100
        assert abs(a - b) < 1e-9, (
            f"{name}: 2回目の較正で数字が動いた {a} → {b}（二重較正）"
        )


def test_already_calibrated_results_are_recognised():
    mat = _matrix()
    assert not topic_score.is_calibrated(mat["f0"])
    cal, _ = topic_score.calibrate_matrix(mat)
    assert topic_score.is_calibrated(cal["f0"])
    assert topic_score.is_calibrated(None) is False


def test_worker_calibrates_before_building_the_pptx():
    """ワーカー内で calibrate_matrix が build_report より前にあること。

    順番が逆だと PPTX にだけ素点が渡る（この不具合そのもの）。
    """
    tree = ast.parse(WORKER_SRC)
    worker = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_analysis_worker")

    def _line_of(attr: str) -> int:
        for n in ast.walk(worker):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == attr):
                return n.lineno
        raise AssertionError(f"{attr}() の呼び出しがワーカーに無い")

    cal = _line_of("calibrate_matrix")
    rep = _line_of("build_report")
    bun = _line_of("build_bundle")
    assert cal < rep, (
        f"calibrate_matrix({cal}行) が build_report({rep}行) より後ろにある。"
        "PPTX に素点が渡る。"
    )
    assert cal < bun


def test_bundle_and_pptx_see_the_same_target_score(tmp_path):
    """ワーカーと同じ順番で回して、両方に渡る値が一致すること。"""
    from src import db

    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for i in range(10):
        db.upsert_facility(conn, f"f{i}", ftype="target" if i == 5 else "comparison")

    matrix = _matrix()

    # --- ワーカーと同じ手順 ---
    calibrated, _ = topic_score.calibrate_matrix(matrix)
    to_pptx = calibrated["f5"]                       # build_report に渡る値
    bundle = preview.build_bundle(conn, "f5", calibrated, None, None)

    assert bundle["score_calibrated"], "較正済みの注記が出ない"

    # スライドは 0-100 を /20 して5点で見せる。単位を揃えて突き合わせる。
    html_5pt = bundle["overall_sentiment"] / 20
    pptx_5pt = to_pptx.weighted_sentiment_100 / 20
    assert abs(html_5pt - pptx_5pt) < 0.01, (
        f"画面 {html_5pt:.2f}/5 と PPTX {pptx_5pt:.2f}/5 が食い違う"
    )

    # --- 修正前の順番（素点を PPTX に渡す）だと実際にズレることを示す ---
    raw_5pt = matrix["f5"].weighted_sentiment_100 / 20
    assert abs(raw_5pt - html_5pt) > 0.05, (
        "このフィクスチャでは較正が効いていないので、テストが不具合を"
        "検出できない（fixture を見直すこと）"
    )
