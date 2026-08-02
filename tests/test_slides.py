"""新レポート構成（PDF p3〜p12 準拠）のスライド描画テスト。

デザインの正は docs/design/slide_pNN.png。ここでは「PDFに書かれている要素が
実際に描画されているか」「データが欠けても落ちないか」を固定する。
"""
from __future__ import annotations

import re

from src import db, preview, report_theme as T, slides, topic_score

TOPICS = topic_score.TOPIC_ORDER


def _result(sentiment: float) -> topic_score.TopicScoreResult:
    w = 1.0 / len(TOPICS)
    return topic_score.TopicScoreResult(
        topics=[
            topic_score.TopicScore(name=t, weight=w, avg_score=sentiment * w,
                                   total_score=sentiment * w, salience=w,
                                   sentiment=sentiment)
            for t in TOPICS
        ],
        overall_score=sentiment, n_reviews=10, n_sentences=30, empty=False,
    )


def _bundle(tmp_path, n_peers: int = 5):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = ["target"] + [f"peer{i}" for i in range(n_peers)]
    for nm in names:
        fid = db.upsert_facility(conn, nm, ftype="comparison", category="美術館")
        conn.execute(
            "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
            "VALUES (?, ?, ?, ?, ?)", (fid, f"{nm}-1", 5, "とても良い", "2024-03-01"))
        conn.execute(
            "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
            "VALUES (?, ?, ?, ?, ?)", (fid, f"{nm}-2", 4, "また来たい", "2024-06-01"))
    conn.commit()
    matrix = {nm: _result(0.5 + 0.03 * i) for i, nm in enumerate(names)}
    return preview.build_bundle(conn, "target", matrix, None, None,
                                peers_override=names[1:])


# --------------------------------------------------------------------------- #
# プリミティブ
# --------------------------------------------------------------------------- #
def test_canvas_is_16_by_9():
    """PDF が 960×540pt なのでスライドは 16:9（従来の 16:10 ではない）。"""
    assert T.ASPECT_RATIO == "16/9"
    assert "aspect-ratio:16/9" in slides.canvas("x")


def test_slide_header_uses_pdf_colors():
    h = slides.slide_header("1", "施設・基本情報", "分析期間：2023/4〜2024/3")
    assert T.NAVY in h and T.ACCENT in h
    assert "施設・基本情報" in h and "分析期間：2023/4〜2024/3" in h
    # 番号バッジは帯と同じ高さまで伸ばす（align-items:stretch）
    assert "align-items:stretch" in h


def test_panel_renders_title_icon_and_note():
    p = slides.panel("施設別スコアヒートマップ", "<i>body</i>", icon="📊", note="※注記")
    assert "施設別スコアヒートマップ" in p and "📊" in p and "※注記" in p
    assert "<i>body</i>" in p
    assert T.NAVY in p


def test_stars_gold_count_follows_rating():
    assert slides._stars(4.2).count("#F5B324") == 4
    assert slides._stars(4.2).count("#D9D9D9") == 1
    assert slides._stars(5.0).count("#F5B324") == 5
    assert slides._stars(None).count("#D9D9D9") == 5


# --------------------------------------------------------------------------- #
# SLIDE 1「施設・基本情報」（PDF p3）
# --------------------------------------------------------------------------- #
def test_slide1_has_all_four_panels(tmp_path):
    b = _bundle(tmp_path)
    b.update(address="東京都○○区", open_year="2015年4月",
             floor_area="28,500㎡", category="ファミリー向け商業施設")
    html = slides.slide1_facility_info(b)

    for t in ("施設プロフィール", "口コミサマリー", "口コミ数の推移",
              "比較対象施設（同カテゴリの類似施設）"):
        assert t in html, t
    for label in ("住所", "開業日", "延床", "マーケットカテゴリ"):
        assert label in html, label
    for val in ("東京都○○区", "2015年4月", "28,500㎡", "ファミリー向け商業施設"):
        assert val in html, val
    assert "総口コミ数" in html and "総合評価" in html
    assert "Voice" in html and "※数値はサンプルです" in html


def test_slide1_shows_review_count_and_rating(tmp_path):
    b = _bundle(tmp_path)
    html = slides.slide1_facility_info(b)
    assert f'{b["n_reviews"]:,}' in html
    assert "/ 5" in html


def test_slide1_lists_up_to_five_peers(tmp_path):
    b = _bundle(tmp_path, n_peers=5)
    html = slides.slide1_facility_info(b)
    for i in range(5):
        assert f"peer{i}" in html
    assert "※同カテゴリの5施設を比較対象として設定" in html


def test_slide1_caps_peer_cards_at_five(tmp_path):
    """peer_display は最大5件（PDF のカードが5枚）。"""
    b = _bundle(tmp_path, n_peers=8)
    assert len(b["peer_display"]) <= 5


def test_slide1_survives_missing_optional_data(tmp_path):
    """住所・写真・推移が無くても落ちない（—で埋める）。"""
    b = _bundle(tmp_path)
    b.update(address=None, open_year=None, floor_area=None,
             photo_data_uri=None, review_trend=[], peer_display=[])
    html = slides.slide1_facility_info(b)
    assert html and "施設プロフィール" in html
    assert "推移データがありません" in html
    assert "比較対象施設が選択されていません" in html


def test_slide1_trend_marks_growth_or_decline(tmp_path):
    b = _bundle(tmp_path)
    b["review_trend"] = [("2023-04", 10), ("2023-08", 60), ("2024-01", 180)]
    assert "継続的に" in slides.slide1_facility_info(b)

    b["review_trend"] = [("2023-04", 180), ("2023-08", 100), ("2024-01", 40)]
    assert "減少傾向" in slides.slide1_facility_info(b)


def test_slide1_edge_x_labels_stay_inside_canvas(tmp_path):
    """両端の月ラベルがキャンバスからはみ出さないよう寄せ方を変えている。"""
    b = _bundle(tmp_path)
    b["review_trend"] = [(f"2023-{m:02d}", m * 10) for m in range(1, 13)]
    html = slides.slide1_facility_info(b)
    assert "translateX(0)" in html          # 左端は左寄せ
    assert "translateX(-100%)" in html      # 右端は右寄せ


def test_slide1_colors_come_from_report_theme(tmp_path):
    """色は report_theme のトークン経由（アプリUIのマゼンタが混ざっていない）。"""
    b = _bundle(tmp_path)
    html = slides.slide1_facility_info(b)
    assert T.NAVY in html and T.ACCENT_DEEP in html
    assert "#B0338A" not in html            # アプリUI側の ACCENT
    # 生の16進を直書きしていないか（テーマに無い色が散らばっていないか）を軽く確認
    known = {v.upper() for v in vars(T).values() if isinstance(v, str) and v.startswith("#")}
    known |= {"#FFF", "#FF", "#F5B324", "#D9D9D9", "#F1F0EA"}
    for hexcol in set(re.findall(r"#[0-9A-Fa-f]{6}", html)):
        assert hexcol.upper() in known, f"テーマ外の色: {hexcol}"


# --------------------------------------------------------------------------- #
# 分析期間 — 固定値ではなく、その施設の口コミが実際にある範囲から出す
# --------------------------------------------------------------------------- #
def _conn_with_periods(tmp_path):
    """対象施設は2024年のみ、競合は2021〜2026 と期間が異なるDBを作る。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    spec = {
        "target": ["2024-03-01", "2024-09-01"],
        "peer0":  ["2021-01-01", "2026-05-01"],
        "peer1":  ["2023-07-01", "2025-02-01"],
    }
    for nm, dates in spec.items():
        fid = db.upsert_facility(conn, nm, ftype="comparison")
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
                "VALUES (?, ?, ?, ?, ?)", (fid, f"{nm}-{i}", 5, "良い", d))
    conn.commit()
    matrix = {nm: _result(0.5 + 0.02 * i) for i, nm in enumerate(spec)}
    return preview.build_bundle(conn, "target", matrix, None, None,
                                peers_override=["peer0", "peer1"])


def test_period_label_is_derived_from_the_target_facility(tmp_path):
    """対象施設のページは、その施設の口コミ期間だけを出す。"""
    b = _conn_with_periods(tmp_path)
    assert b["period_label"] == "2024/3〜2024/9"


def test_period_label_scope_covers_compared_facilities(tmp_path):
    """比較スライドは、比較した施設すべてを含む期間を出す。"""
    b = _conn_with_periods(tmp_path)
    assert b["period_label_scope"] == "2021/1〜2026/5"


def test_slide1_header_uses_the_target_period_not_the_peers(tmp_path):
    b = _conn_with_periods(tmp_path)
    html = slides.slide1_facility_info(b)
    assert "分析期間：2024/3〜2024/9" in html
    assert "2021/1" not in html          # 競合の期間を混ぜない


def test_competitor_slide_header_uses_the_scope_period(tmp_path):
    b = _conn_with_periods(tmp_path)
    html = preview.html_competitor_compare(b)
    assert "分析期間：2021/1〜2026/5" in html


def test_period_label_absent_when_no_review_dates(tmp_path):
    """日付が無い口コミしかない施設でも落ちない（期間表記を出さない）。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "target", ftype="target")
    conn.execute(
        "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
        "VALUES (?, ?, ?, ?, ?)", (fid, "r1", 5, "良い", None))
    conn.commit()
    b = preview.build_bundle(conn, "target", {"target": _result(0.5)}, None, None,
                             peers_override=[])
    assert b["period_label"] == ""
    assert "分析期間" not in slides.slide1_facility_info(b)


# --------------------------------------------------------------------------- #
# 縦書き — フォント任せにせず1文字ずつ積む
# --------------------------------------------------------------------------- #
def test_vertical_text_stacks_each_character():
    """writing-mode に頼ると環境によって漢字が重なるため、自前で積んでいる。

    headless Chromium では和文フォントに縦書きメトリクスが無く、
    「提供内容の品質」の漢字が全部同じ位置に重なる事故が実際に起きた。
    """
    html = slides.vertical_text("提供内容の品質", size=0.55)
    assert "writing-mode" not in html
    for ch in "提供内容の品質":
        assert f">{ch}</div>" in html
    assert html.count("</div>") == len("提供内容の品質") + 1


def test_vertical_text_rotates_long_vowel_marks():
    """「サービス」の長音符は縦組みで横倒しにする。"""
    html = slides.vertical_text("サービス", size=0.55)
    assert "rotate(90deg)" in html
    # 回転するのは長音符だけ
    assert html.count("rotate(90deg)") == 1


def test_indicator_axis_labels_are_vertical(tmp_path):
    b = _bundle(tmp_path)
    html = slides.slide2_market_detail(b)
    assert "writing-mode" not in html          # 全部が自前の縦組み
    assert "①" in html and "⑲" in html          # 丸番号は19まで


# --------------------------------------------------------------------------- #
# SLIDE 2「市場内ポジション」（PDF p4）
# --------------------------------------------------------------------------- #
def test_slide2_shows_rank_distribution_and_top3(tmp_path):
    b = _bundle(tmp_path)
    html = slides.slide2_market_position(b)
    for t in ("総合評価ランキング", "同業施設内の総合評価分布", "強み TOP3", "弱み TOP3"):
        assert t in html, t
    assert f'/ {b["total_fac"]}施設中' in html
    assert "低評価" in html and "高評価" in html
    assert "市場平均" in html


def test_slide2_percentile_matches_rank(tmp_path):
    b = _bundle(tmp_path)
    assert b["percentile"] == round(100 * b["rank"] / b["total_fac"])
    assert f'上位{b["percentile"]}%' in slides.slide2_market_position(b)


def test_slide2_scores_are_five_point_with_two_decimals(tmp_path):
    """5点満点は必ず小数2桁（2.6 ではなく 2.60）。"""
    assert slides._pt5(52.0) == "2.60"
    assert slides._pt5(100.0) == "5.00"
    assert slides._pt5(None) == "—"
    # グラフの座標計算用は数値
    assert slides._score5(52.0) == 2.6
    assert slides._score5(None) is None


def test_slide2_survives_single_facility(tmp_path):
    """比較相手がいなくても落ちない。"""
    b = _bundle(tmp_path, n_peers=0)
    assert slides.slide2_market_position(b)
    assert slides.slide2_market_detail(b)


# --------------------------------------------------------------------------- #
# SLIDE 2 詳細（PDF p5）
# --------------------------------------------------------------------------- #
def test_slide2_detail_has_all_three_panels(tmp_path):
    b = _bundle(tmp_path)
    html = slides.slide2_market_detail(b)
    for t in ("乃村独自の口コミ分析指標", "総合体験評価マッピング", "マーケット傾向",
              "プランナー起点", "指標（代表例）", "当施設", "同業平均", "総合評価",
              "この市場で評価されやすい指標", "この市場で課題になりやすい指標",
              "口コミから算出した主要スコア", "体験満足度", "推奨意向", "再訪意向"):
        assert t in html, t
    assert "※ 各指標は1〜5点で評価" in html
    assert "○ バブルサイズ＝再訪意向" in html
    assert f'※ マッピングは全{b["total_fac"]}施設を表示' in html


def test_market_trend_lists_five_each_and_does_not_overlap(tmp_path):
    b = _bundle(tmp_path)
    good, bad = b["market_trend_good"], b["market_trend_bad"]
    assert len(good) == 5 and len(bad) == 5
    assert not set(good) & set(bad)
    # 上位は下位より必ずスコアが高い
    ot = b["overall_topic"]
    assert min(ot[t] for t in good) >= max(ot[t] for t in bad)


def test_outcome_map_covers_the_comparison_universe(tmp_path):
    b = _bundle(tmp_path, n_peers=5)
    assert set(b["outcome_map"]) == {"target"} | {f"peer{i}" for i in range(5)}
    for v in b["outcome_map"].values():
        assert set(v) == {"体験満足度", "推奨意向", "再訪意向"}


def test_experience_map_can_be_limited_to_selected_peers(tmp_path):
    """SLIDE 3 詳細では競合だけを描くため names で絞れる。"""
    b = _bundle(tmp_path, n_peers=5)
    only2 = slides.experience_map(b, names=["peer0", "peer1"], label_points=True)
    assert "peer0" in only2 and "peer1" in only2
    assert "peer4" not in only2
    assert "当施設" in only2                    # 対象施設は常に描く


# --------------------------------------------------------------------------- #
# SLIDE 3「指定競合との比較」＋詳細（PDF p6, p7）
# --------------------------------------------------------------------------- #
def test_compare_columns_are_self_peers_then_average(tmp_path):
    b = _bundle(tmp_path, n_peers=4)
    labels = [c[0] for c in slides.compare_columns(b)]
    assert labels == ["自施設", "競合A", "競合B", "競合C", "競合D", "同業平均"]


def test_compare_columns_cap_peers_at_five(tmp_path):
    b = _bundle(tmp_path, n_peers=8)
    labels = [c[0] for c in slides.compare_columns(b)]
    assert "競合E" in labels and "競合F" not in labels


def test_slide3_has_chart_heatmap_and_diff_panels(tmp_path):
    b = _bundle(tmp_path, n_peers=4)
    html = slides.slide3_competitor_compare(b)
    for t in ("指定競合との比較", "2〜5施設を横並びで比較し、自施設の立ち位置を把握します。",
              "主要19指標の比較（5点満点）", "施設別スコアヒートマップ（5点満点）",
              "自施設だけの強み", "競合に負けている項目", "分析対象：5施設"):
        assert t in html, t
    for t in topic_score.DRIVER_TOPICS:
        assert t[:4] in html, t
    for t in topic_score.OUTCOME_TOPICS:
        assert t not in html, t


def test_slide3_diff_values_are_five_point_scale(tmp_path):
    """差分は5点満点（100点満点の pt ではない）。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for nm in ("target", "peer1"):
        db.upsert_facility(conn, nm, ftype="comparison")
    conn.commit()
    matrix = {"target": _result(0.80), "peer1": _result(0.40)}
    b = preview.build_bundle(conn, "target", matrix, None, None, peers_override=["peer1"])
    html = slides.slide3_competitor_compare(b)
    assert "+2.00" in html          # 4.00 - 2.00
    assert "+40.0" not in html


def test_slide3_detail_has_map_and_trend(tmp_path):
    b = _bundle(tmp_path, n_peers=4)
    html = slides.slide3_competitor_detail(b)
    assert "総合体験評価マッピング" in html and "指定競合の傾向" in html
    assert "（詳細）" in html
    assert "体験満足度" in html and "推奨意向" in html and "再訪意向" in html
    # 詳細は競合だけをプロットして名前を出す
    for i in range(4):
        assert f"peer{i}" in html
    assert "当施設" in html


def test_slide3_detail_excludes_non_selected_facilities(tmp_path):
    """母数に他施設がいても、詳細のマッピングには競合だけを描く。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = ["target", "peerA", "peerB", "outsider"]
    for nm in names:
        db.upsert_facility(conn, nm, ftype="comparison")
    conn.commit()
    matrix = {nm: _result(0.5 + 0.04 * i) for i, nm in enumerate(names)}
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peerA", "peerB"])
    html = slides.slide3_competitor_detail(b)
    assert "peerA" in html and "peerB" in html
    assert "outsider" not in html


def test_slide3_survives_no_peers(tmp_path):
    b = _bundle(tmp_path, n_peers=0)
    assert slides.slide3_competitor_compare(b)
    assert slides.slide3_competitor_detail(b)


def test_bubble_labels_stay_inside_the_plot(tmp_path):
    """端のバブルはラベルの寄せ方を変えてパネル外へ出さない。"""
    b = _bundle(tmp_path, n_peers=4)
    html = slides.experience_map(b, names=list(b["peer_topic_scores"]), label_points=True)
    assert "translate(0," in html or "translate(-100%," in html or "translate(-50%," in html
