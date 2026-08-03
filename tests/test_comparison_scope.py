"""指定競合モードで比較母数が「自施設＋選択した競合」に絞られることのテスト。

マーケット比較（DB全施設が母数）と、指定競合比較（選んだ最大5施設だけが母数）で
順位・スコア分布・各観点の基準値・見出しがすべて切り替わることを固定する。
"""
from __future__ import annotations

from src import analysis, db, preview, slides, topic_score

TOPICS = topic_score.TOPIC_ORDER


def _result(sentiment: float) -> topic_score.TopicScoreResult:
    """全観点が同じ感情スコア(0-1)の TopicScoreResult を作る。"""
    w = 1.0 / len(TOPICS)
    return topic_score.TopicScoreResult(
        topics=[
            topic_score.TopicScore(
                name=t, weight=w, avg_score=sentiment * w,
                total_score=sentiment * w, salience=w, sentiment=sentiment,
            )
            for t in TOPICS
        ],
        overall_score=sentiment, n_reviews=10, n_sentences=30, empty=False,
    )


def _setup(tmp_path):
    """target + peer1..peer3 + far1..far2 の6施設を作る。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for name in ("target", "peer1", "peer2", "peer3", "far1", "far2"):
        db.upsert_facility(conn, name, ftype="comparison")

    # target=60点。競合は50点台、遠い2施設は90点台（母数に入ると平均を押し上げる）
    matrix = {
        "target": _result(0.60),
        "peer1": _result(0.50), "peer2": _result(0.52), "peer3": _result(0.54),
        "far1": _result(0.90), "far2": _result(0.92),
    }
    return conn, matrix


def test_competitor_mode_restricts_universe(tmp_path):
    conn, matrix = _setup(tmp_path)
    sel = ["peer1", "peer2", "peer3"]

    market = preview.build_bundle(conn, "target", matrix, None, None)
    comp = preview.build_bundle(conn, "target", matrix, None, None, peers_override=sel)

    # 母数: マーケットは6施設、指定競合は自施設＋3施設
    assert market["total_fac"] == 6
    assert comp["total_fac"] == 4

    # スコア分布も母数ぶんだけ
    assert len(market["ranking_dist"]) == 6
    assert len(comp["ranking_dist"]) == 4

    # 順位: 90点台の2施設が母数から外れるので target は3位→1位に上がる
    assert market["rank"] == 3
    assert comp["rank"] == 1

    assert market["comparison_scope"] == "market"
    assert comp["comparison_scope"] == "competitor"


def test_competitor_mode_baseline_is_selected_peers_only(tmp_path):
    """各観点の基準値が「選択競合の平均」になり、自施設も他施設も混ざらない。"""
    conn, matrix = _setup(tmp_path)
    comp = preview.build_bundle(
        conn, "target", matrix, None, None, peers_override=["peer1", "peer2", "peer3"]
    )

    # peer1..3 の平均 = (50 + 52 + 54) / 3 = 52.0（target の60も far の90も含まない）
    assert comp["overall_topic"]["スタッフ対応"] == 52.0
    assert comp["baseline_label"] == "選択競合の平均"

    # 強み差分もその基準に対して計算される（60 - 52 = +8.0pt）
    assert comp["strengths"][0][2] == 52.0
    assert comp["strengths"][0][3] == 8.0

    # マーケット側は母数全体（自施設含む）の平均なのでもっと高い
    market = preview.build_bundle(conn, "target", matrix, None, None)
    assert market["overall_topic"]["スタッフ対応"] > 60.0
    assert market["baseline_label"] == "全体平均"


def test_scope_labels_switch_in_slides(tmp_path):
    conn, matrix = _setup(tmp_path)
    market = preview.build_bundle(conn, "target", matrix, None, None)
    comp = preview.build_bundle(
        conn, "target", matrix, None, None, peers_override=["peer1", "peer2"]
    )

    assert "市場内ポジション" in slides.slide2_market_position(market)
    assert "選択競合内ポジション" in slides.slide2_market_position(comp)
    # マーケット傾向の見出しは PDF 準拠の文言。母数のスコープはヘッダ側で示す。
    assert "この市場で評価されやすい指標" in slides.slide2_market_detail(market)
    assert "この市場で課題になりやすい指標" in slides.slide2_market_detail(comp)

    # analysis_rows の見出しもモードに合わせて変わる
    assert any("市場内順位" == k for k, _ in market["analysis_rows"])
    assert any("選択競合内順位" == k for k, _ in comp["analysis_rows"])


def test_competitor_mode_radar_does_not_duplicate_peer_average(tmp_path):
    """指定競合モードでは overall_topic == 競合平均。レーダーに同じ線を2本描かない。"""
    conn, matrix = _setup(tmp_path)
    comp = preview.build_bundle(
        conn, "target", matrix, None, None, peers_override=["peer1", "peer2"]
    )
    html = slides.slide5_space_experience(comp)
    assert "競合平均" in html
    assert "同業平均" not in html

    market = preview.build_bundle(conn, "target", matrix, None, None)
    assert "同業平均" in slides.slide5_space_experience(market)


def test_all_slides_render_in_both_modes(tmp_path):
    conn, matrix = _setup(tmp_path)
    for peers in (None, ["peer1", "peer2"]):
        b = preview.build_bundle(conn, "target", matrix, None, None, peers_override=peers)
        for fn in (
            slides.slide0_disclaimer, slides.slide1_facility_info,
            slides.slide2_market_position, slides.slide2_market_detail,
            slides.slide3_competitor_compare, slides.slide3_competitor_detail,
            slides.slide4_timeline, slides.slide5_space_experience,
            slides.slide5_space_detail, slides.slide6_voices,
            slides.slide7_discussion,
        ):
            assert fn(b), f"{fn.__name__} failed (peers={peers})"


def test_build_comparison_accepts_explicit_peers(tmp_path):
    """指定競合モードの比較軸が DB の type='comparison' タグではなく選択施設になる。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for name, ftype in (("target", "target"), ("chosen", "comparison"),
                        ("tagged1", "comparison"), ("tagged2", "comparison")):
        fid = db.upsert_facility(conn, name, ftype=ftype)
        # chosen だけ target と大きく違うスコアにする
        val = {"target": 5.0, "chosen": 1.0, "tagged1": 5.0, "tagged2": 5.0}[name]
        db.upsert_scores(conn, fid, {"清潔感": val}, scale=5)

    tagged = analysis.build_comparison(conn, "target", "comparison_avg")
    chosen = analysis.build_comparison(conn, "target", "comparison_avg", peers=["chosen"])

    assert tagged is not None and chosen is not None
    # DBタグ側は3施設平均（chosen も含む）、明示指定側は chosen 1施設のみ
    assert "3施設" in tagged.baseline_label
    assert "1施設" in chosen.baseline_label
    # スコアは 0-100 に正規化される（5点満点の 5.0→100 / 1.0→20）
    assert chosen.diff["清潔感"] == 80.0                    # 100 - 20
    assert tagged.diff["清潔感"] < 80.0                     # 100 - (20+100+100)/3

    # 自施設が peers に混じっても除外される
    with_self = analysis.build_comparison(
        conn, "target", "comparison_avg", peers=["chosen", "target"]
    )
    assert "1施設" in with_self.baseline_label


# --------------------------------------------------------------------------- #
# SLIDE 3「指定競合との比較」— 資料（主要19指標・5点満点・施設別ヒートマップ）準拠
# --------------------------------------------------------------------------- #
def test_driver_topics_are_the_19_indicators():
    """主要19指標＝22観点から outcome 3指標を除いたもの。"""
    assert topic_score.OUTCOME_TOPICS == ["体験満足度", "推奨意向", "再訪意向"]
    assert len(topic_score.DRIVER_TOPICS) == 19
    assert topic_score.DRIVER_TOPICS == topic_score.TOPIC_ORDER[:19]
    assert not set(topic_score.DRIVER_TOPICS) & set(topic_score.OUTCOME_TOPICS)


def test_slide3_shows_only_driver_topics(tmp_path):
    conn, matrix = _setup(tmp_path)
    b = preview.build_bundle(
        conn, "target", matrix, None, None, peers_override=["peer1", "peer2"]
    )
    html = slides.slide3_competitor_compare(b)

    for t in topic_score.DRIVER_TOPICS:
        assert t[:6] in html, f"19指標の {t} が出ていない"
    for t in topic_score.OUTCOME_TOPICS:
        assert t not in html, f"outcome指標 {t} を出してはいけない"


def test_slide3_columns_are_self_peers_and_average(tmp_path):
    conn, matrix = _setup(tmp_path)
    b = preview.build_bundle(
        conn, "target", matrix, None, None,
        peers_override=["peer1", "peer2", "peer3"],
    )
    html = slides.slide3_competitor_compare(b)

    assert "主要19指標の比較（5点満点）" in html
    assert "施設別スコアヒートマップ（5点満点）" in html
    assert "自施設だけの強み" in html and "競合に負けている項目" in html
    assert "2〜5施設を横並びで比較し、自施設の立ち位置を把握します。" in html
    for lbl in ("自施設", "競合A", "競合B", "競合C", "競合平均"):
        assert lbl in html, lbl
    assert "競合D" not in html          # ピアは3施設なのでDは出ない
    assert "分析対象：4施設" in html      # 自施設＋競合3（同業平均は施設数に数えない）


def test_slide3_caps_peer_columns_at_five(tmp_path):
    """競合は最大5列（競合A〜E）まで。PDF p10 のヒートマップが競合Eまで。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = ["target"] + [f"p{i}" for i in range(6)]
    for nm in names:
        db.upsert_facility(conn, nm, ftype="comparison")
    matrix = {nm: _result(0.5 + 0.02 * i) for i, nm in enumerate(names)}

    b = preview.build_bundle(
        conn, "target", matrix, None, None, peers_override=names[1:]
    )
    html = slides.slide3_competitor_compare(b)
    assert "競合E" in html
    assert "競合F" not in html


def test_slide3_scores_are_on_a_five_point_scale(tmp_path):
    """ヒートマップの数値が 0-100 ではなく 5点満点で出ること。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for nm in ("target", "peer1"):
        db.upsert_facility(conn, nm, ftype="comparison")
    # 感情 0.8 → 80/100 → 4.00点
    matrix = {"target": _result(0.80), "peer1": _result(0.40)}

    b = preview.build_bundle(conn, "target", matrix, None, None, peers_override=["peer1"])
    html = slides.slide3_competitor_compare(b)
    assert "4.00" in html and "2.00" in html
    assert ">80.0<" not in html and ">80<" not in html
    # 差分も5点満点（80-40=40pt ではなく 4.00-2.00=+2.00）
    assert "+2.00" in html


def test_slide3_handles_no_peers(tmp_path):
    """競合未選択でも落ちない。"""
    conn, matrix = _setup(tmp_path)
    b = preview.build_bundle(conn, "target", matrix, None, None, peers_override=[])
    assert slides.slide3_competitor_compare(b)
