"""新レポート構成（PDF p3〜p12 準拠）のスライド描画テスト。

デザインの正は docs/design/slide_pNN.png。ここでは「PDFに書かれている要素が
実際に描画されているか」「データが欠けても落ちないか」を固定する。
"""
from __future__ import annotations

import re

import pytest

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
    """スライドは 16:9。枠は正典どおり 10px 角丸＋カード罫線。"""
    assert T.ASPECT_RATIO == "16/9"
    c = slides.canvas("<h/>", "<b/>", "<f/>")
    assert "aspect-ratio:16/9" in c
    assert "container-type:inline-size" in c
    # 本文とフッターを絶対配置するので、枠自体は position:relative でなければならない
    assert "position:relative" in c
    assert "<h/><b/><f/>" in c


def test_body_area_uses_canonical_insets():
    """本文エリア left/right:2cqw・top:6.9〜7.4cqw・bottom:4.6cqw（README §2）。"""
    a = slides.body_area("<x/>")
    assert "left:2.0cqw" in a and "right:2.0cqw" in a
    assert "top:7.4cqw" in a and "bottom:4.6cqw" in a
    assert "top:6.9cqw" in slides.body_area("<x/>", top=T.BODY_TOP_TIGHT)


def test_slide_header_follows_design_tokens():
    """帯 6.3cqw ／ タイル 6.3cqw 正方・2.7cqw/800 ／ タイトル 2.3cqw/800。"""
    h = slides.slide_header("1", "施設・基本情報", "分析期間：2023/4〜2024/3")
    assert T.NAVY in h and T.ACCENT in h
    assert "施設・基本情報" in h and "分析期間：2023/4〜2024/3" in h
    assert "height:6.3cqw" in h
    assert "width:6.3cqw" in h
    assert "font-size:2.7cqw" in h and "font-size:2.3cqw" in h
    # 補足は 600。級数は正典の 1.05 より一段上げてある（実データで読めないため）
    assert f'font-size:{T.FS["slide_meta"]}cqw;font-weight:600' in h
    assert T.FS["slide_meta"] >= 1.05
    assert "align-items:stretch" in h


def test_slide_header_accepts_pill_and_outline_tags():
    pill = slides.slide_header("2", "市場内ポジション", right=slides._pill("プランナー起点"))
    assert "プランナー起点" in pill and "border-radius:999px" in pill
    conf = slides.slide_header("5", "空間・体験分析", right=slides._outline_tag("confidential"))
    assert "confidential" in conf and f"border:1.5px solid {T.ACCENT}" in conf


def test_panel_renders_title_icon_and_note():
    p = slides.panel("施設別スコアヒートマップ", "<i>body</i>", icon="📊", note="※注記")
    assert "施設別スコアヒートマップ" in p and "📊" in p and "※注記" in p
    assert "<i>body</i>" in p
    assert T.NAVY in p
    # カード見出しは 1.35cqw/700（README §2）
    assert "font-size:1.35cqw;font-weight:700" in p


def test_panel_head_is_centered_without_icon_or_note():
    """アイコンも注記も無いカード見出しは中央寄せ（正典の既定）。"""
    assert "text-align:center" in slides.panel("総合評価ランキング", "")
    assert "text-align:center" not in slides.panel("口コミ数の推移", "", icon="◪")


def test_footer_is_pinned_and_two_toned():
    """Voice=アクセント／BAUM=ネイビーの2色・1.5cqw/800、上罫は内部罫線色。"""
    f = slides.footer("※注記")
    assert f'color:{T.ACCENT};">Voice' in f
    assert f'color:{T.NAVY};">BAUM' in f
    assert "font-size:1.5cqw;font-weight:800" in f
    assert f"border-top:1px solid {T.LINE}" in f
    assert "position:absolute" in f and "bottom:1.1cqw" in f
    assert "※注記" in f


def test_stars_are_filled_in_whole_steps():
    assert slides._stars(5.0).count(T.STAR) == 5
    assert slides._stars(5.0).count(T.STAR_EMPTY) == 0
    assert slides._stars(3.0).count(T.STAR) == 3
    assert slides._stars(3.0).count(T.STAR_EMPTY) == 2
    assert slides._stars(None).count(T.STAR_EMPTY) == 5
    assert slides._stars(0).count(T.STAR) == 0
    assert T.STAR == "#F2B01E" and T.STAR_EMPTY == "#D6D9E0"


def test_half_rating_fills_half_a_star():
    """3.5 なら4つ目の星が半分だけ金色になる。"""
    html = slides._stars(3.5)
    assert "width:50%" in html
    # 3つは満杯、1つは端数（クリップ用に金色をもう1つ描く）、1つは空
    assert html.count(T.STAR) == 4 and html.count(T.STAR_EMPTY) == 2


@pytest.mark.parametrize("rating,pct", [
    (4.2, "20%"), (3.8, "80%"), (2.25, "25%"), (0.5, "50%"),
])
def test_fractional_ratings_clip_proportionally(rating, pct):
    assert f"width:{pct}" in slides._stars(rating)


def test_stars_clamp_out_of_range_ratings():
    assert slides._stars(7.0).count(T.STAR) == 5
    assert slides._stars(-1).count(T.STAR_EMPTY) == 5


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
    assert "Voice" in html
    # PDF の「※数値はサンプルです」はモックの文言。実データなので出さない
    assert "※数値はサンプルです" not in html
    assert "実測値" in html


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
    html = slides.slide3_competitor_compare(b)
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
              "指標（代表例）", "当施設", "同業平均", "総合評価",
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
    """最後の列は平均。指定競合モードでは母数が選択競合なので「競合平均」。"""
    b = _bundle(tmp_path, n_peers=4)
    labels = [c[0] for c in slides.compare_columns(b)]
    assert labels == ["自施設", "競合A", "競合B", "競合C", "競合D", "競合平均"]


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


# --------------------------------------------------------------------------- #
# SLIDE 4「時間軸分析」（PDF p8）
# --------------------------------------------------------------------------- #
def _timeline_conn(tmp_path, monthly: dict):
    """{ 'YYYY-MM': [rating, ...] } から施設を1つ作る。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "target", ftype="target")
    i = 0
    for ym, ratings in monthly.items():
        for r in ratings:
            i += 1
            conn.execute(
                "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
                "VALUES (?, ?, ?, ?, ?)", (fid, f"r{i}", r, "本文", f"{ym}-15"))
    conn.commit()
    return conn, fid


def test_monthly_series_converts_stars_to_minus_one_to_plus_one(tmp_path):
    """★5→+1.0 / ★3→0 / ★1→−1.0 に線形変換して集計する。"""
    conn, fid = _timeline_conn(tmp_path, {"2024-01": [5, 5], "2024-02": [1, 1],
                                          "2024-03": [3, 3], "2024-04": [5, 1]})
    s = {row[0]: row for row in db.monthly_sentiment_series(conn, fid)}
    assert s["2024-01"][2:5] == (1.0, 0.0, 1.0)        # pos, neg, diff
    assert s["2024-02"][2:5] == (0.0, -1.0, -1.0)
    assert s["2024-03"][2:5] == (0.0, 0.0, 0.0)
    assert s["2024-04"][2:5] == (0.5, -0.5, 0.0)       # ★5と★1が相殺
    assert s["2024-01"][5] == 5.0                      # 平均★


def test_detect_change_points_finds_the_drop(tmp_path):
    from src import timeline
    monthly = {f"2024-{m:02d}": [5, 5, 5] for m in range(1, 6)}
    monthly["2024-06"] = [2, 2, 2]                     # ここで急落
    monthly.update({f"2024-{m:02d}": [5, 5, 5] for m in range(7, 10)})
    conn, fid = _timeline_conn(tmp_path, monthly)

    pts = timeline.detect_change_points(db.monthly_sentiment_series(conn, fid))
    assert pts, "変化点が検出されていない"
    assert pts[0].ym == "2024-06"
    assert pts[0].direction == "down"
    assert pts[0].delta_pt == -3.0                     # 5.0 → 2.0
    assert pts[0].label == "'24/06"


def test_detect_change_points_ignores_thin_months(tmp_path):
    """口コミ1件だけの月は外れ値になるので変化点にしない。"""
    from src import timeline
    monthly = {f"2024-{m:02d}": [5, 5, 5] for m in range(1, 6)}
    monthly["2024-06"] = [1]                           # 1件だけの激しい低評価
    conn, fid = _timeline_conn(tmp_path, monthly)
    pts = timeline.detect_change_points(db.monthly_sentiment_series(conn, fid))
    assert all(p.ym != "2024-06" for p in pts)


def test_detect_change_points_does_not_double_count_the_same_dip(tmp_path):
    """隣り合う月で同じ谷を2回拾わない。"""
    from src import timeline
    monthly = {f"2024-{m:02d}": [5, 5, 5] for m in range(1, 6)}
    monthly["2024-06"] = [2, 2, 2]
    monthly["2024-07"] = [2, 2, 2]
    monthly.update({f"2024-{m:02d}": [5, 5, 5] for m in range(8, 11)})
    conn, fid = _timeline_conn(tmp_path, monthly)
    pts = timeline.detect_change_points(db.monthly_sentiment_series(conn, fid))
    assert len({p.ym for p in pts} & {"2024-06", "2024-07"}) <= 1


def test_slide4_renders_chart_and_cards(tmp_path):
    from src import timeline
    monthly = {f"2024-{m:02d}": [5, 5, 5] for m in range(1, 6)}
    monthly["2024-06"] = [2, 2, 2]
    monthly.update({f"2024-{m:02d}": [5, 5, 5] for m in range(7, 11)})
    conn, fid = _timeline_conn(tmp_path, monthly)
    b = preview.build_bundle(conn, "target", {"target": _result(0.6)}, None, None,
                             peers_override=[])
    html = slides.slide4_timeline(b)

    assert "時間軸分析" in html
    assert "ポジティブ要因とネガティブ要因の推移" in html
    assert "主な変化点と評価変動要因" in html
    assert "ポジティブ要因スコア（+）" in html and "ネガティブ要因スコア（−）" in html
    assert "差分（ポジ − ネガ）" in html
    assert "※スコアは5点満点を−1〜+1のスケールに変換して集計" in html
    assert "影響：-3.00pt" in html
    assert "24/06" in html


def test_slide4_marks_every_change_point_on_the_chart(tmp_path):
    """検出した変化点は必ずグラフ上に番号バッジが出る（期間を切らない）。"""
    from src import timeline
    monthly = {f"2023-{m:02d}": [5, 5, 5] for m in range(1, 13)}
    monthly["2023-06"] = [2, 2, 2]                     # 古い側の変化点
    # （先頭3か月は「直前3か月」が取れないので変化点にはならない）
    monthly.update({f"2024-{m:02d}": [5, 5, 5] for m in range(1, 13)})
    monthly.update({f"2025-{m:02d}": [5, 5, 5] for m in range(1, 13)})
    conn, fid = _timeline_conn(tmp_path, monthly)
    b = preview.build_bundle(conn, "target", {"target": _result(0.6)}, None, None,
                             peers_override=[])
    assert len(b["monthly_series"]) == 36
    pts = b["change_points"]
    assert pts and pts[0].ym == "2023-06"
    html = slides.slide4_timeline(b)
    # 36か月ぶんの棒が描かれ、古い変化点のバッジも残っている
    assert html.count("<rect") == 36 * 2
    assert "23/06" in html


def test_slide4_falls_back_when_llm_is_unavailable(tmp_path):
    """LLM未使用でも、観測できた事実だけのカードを出す（憶測を書かない）。"""
    from src import timeline
    cp = timeline.ChangePoint(ym="2024-06", index=5, delta_pt=-0.42,
                              n_reviews=8, direction="down")
    title, body = timeline.fallback_description(cp)
    assert title == "評価の低下"
    assert "-0.42pt" in body and "8 件" in body
    assert "特定していません" in body


def test_slide4_survives_no_reviews_with_dates(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_facility(conn, "target", ftype="target")
    conn.commit()
    b = preview.build_bundle(conn, "target", {"target": _result(0.5)}, None, None,
                             peers_override=[])
    html = slides.slide4_timeline(b)
    assert "推移を出せるデータがありません" in html
    assert "評価が大きく動いた月は検出されませんでした" in html


# --------------------------------------------------------------------------- #
# SLIDE 5「空間・体験分析」＋詳細（PDF p9, p10）
# --------------------------------------------------------------------------- #
def test_space_topics_are_the_ten_axes():
    """PDF のレーダー10軸。19指標のうち空間・体験に関わるものだけ。"""
    assert len(topic_score.SPACE_TOPICS) == 10
    assert set(topic_score.SPACE_TOPICS) <= set(topic_score.DRIVER_TOPICS)
    # 運営側の変数（スタッフ・料金・立地・ブランド）は入れない
    for ng in ("スタッフ対応", "料金の適正さ", "立地・アクセス", "ブランド信頼感"):
        assert ng not in topic_score.SPACE_TOPICS


def test_slide5_renders_radar_tables_and_summary(tmp_path):
    b = _bundle(tmp_path, n_peers=4)
    html = slides.slide5_space_experience(b)
    assert "空間・体験分析" in html
    assert "乃村独自の空間分析指標" in html and "本ページの要約" in html
    assert "confidential" in html
    assert "空間と体験の質を10の観点で評価し、改善の優先ポイントを可視化します。" in html
    assert "※ スコアは5点満点（高いほど評価が高いことを示します）" in html
    for i, t in enumerate(topic_score.SPACE_TOPICS, 1):
        assert f"{i}. {t}" in html
    for no in ("01", "02", "03", "04"):
        assert f">{no}</span>" in html
    # 要約カードはアイコン・番号・枠線を正典（ReviewLens.dc.html:2063）から取る
    for c in T.SUMMARY_CARDS:
        assert c["icon"] in html and c["border"] in html


def test_slide5_detail_has_ten_rows_with_trend_badges(tmp_path):
    b = _bundle(tmp_path, n_peers=4)
    html = slides.slide5_space_detail(b)
    assert "空間体験分析" in html and "（詳細）" in html
    assert "施設別スコアヒートマップ（10項目）" in html
    assert "傾向" in html and "ポイント" in html
    assert "総合サマリー" in html and "スコアの見方（5点満点）" in html
    for t in topic_score.SPACE_TOPICS:
        assert t in html
    # 傾向バッジは3種のいずれか
    assert any(x in html for x in ("強み", "課題", "良好"))


def test_competitor_mode_does_not_duplicate_peer_and_industry_average(tmp_path):
    """指定競合モードでは母数＝選択競合なので、同じ平均を2本描かない。"""
    b = _bundle(tmp_path, n_peers=4)
    assert b["comparison_scope"] == "competitor"
    names = [nm for nm, _sc, _c, _d in slides._space_series(b)]
    assert names == ["当施設", "競合平均"]
    assert "同業平均" not in slides.slide5_space_experience(b)


def test_market_mode_keeps_both_averages(tmp_path):
    """マーケット比較では競合平均と同業平均は別物なので両方出す。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = ["target"] + [f"f{i}" for i in range(5)]
    for i, nm in enumerate(names):
        db.upsert_facility(conn, nm, ftype="comparison" if i < 3 else "target")
    conn.commit()
    matrix = {nm: _result(0.4 + 0.05 * i) for i, nm in enumerate(names)}
    b = preview.build_bundle(conn, "target", matrix, None, None)   # peers_override なし
    assert b["comparison_scope"] == "market"
    labels = [nm for nm, _sc, _c, _d in slides._space_series(b)]
    assert "同業平均" in labels


def test_average_column_is_named_for_the_mode(tmp_path):
    """指定競合モードの平均列は「競合平均」と名乗る（同業平均だと誤解を招く）。"""
    b = _bundle(tmp_path, n_peers=3)
    labels = [c[0] for c in slides.compare_columns(b)]
    assert labels[-1] == "競合平均"
    assert "同業平均" not in labels


def test_space_findings_counts_axes_above_the_baseline(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for nm in ("target", "peer1"):
        db.upsert_facility(conn, nm, ftype="comparison")
    conn.commit()
    b = preview.build_bundle(conn, "target", {"target": _result(0.7),
                                              "peer1": _result(0.5)},
                             None, None, peers_override=["peer1"])
    f = slides.space_findings(b)
    assert f["n_axes"] == 10
    assert f["n_above"] == 10                 # 全軸で上回る
    assert f["base_label"] == "競合平均"
    assert all(abs(v - 1.0) < 1e-6 for v in f["diffs"].values())   # (70-50)/100*5


def test_trend_badge_thresholds():
    assert slides._trend_badge(0.30)[0] == "強み"
    assert slides._trend_badge(0.15)[0] == "強み"
    assert slides._trend_badge(0.05)[0] == "良好"
    assert slides._trend_badge(-0.05)[0] == "良好"
    assert slides._trend_badge(-0.15)[0] == "課題"


def test_slide5_survives_no_peers(tmp_path):
    b = _bundle(tmp_path, n_peers=0)
    assert slides.slide5_space_experience(b)
    assert slides.slide5_space_detail(b)


# --------------------------------------------------------------------------- #
# SLIDE 6「特徴的な口コミ」（PDF p11）
# --------------------------------------------------------------------------- #
def _voice_conn(tmp_path):
    from src import voices
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    fid = db.upsert_facility(conn, "target", ftype="target")
    rows = [
        (5, "映像体験が圧倒的に素晴らしく、何度でも来たくなる展示でした。演出の作り込みが丁寧で、家族全員が最後まで飽きずに楽しめました。"),
        (2, "混雑時は待ち時間が長く、子どもがぐずってしまった。案内も不足。"),
        (4, "雨の日でも安心して楽しめる屋内のキッズスペースがほしいと感じました。"),
        (5, "季節ごとのイベントがもっと増えると、何度でも訪れたくなると思います。"),
        (3, "普通でした。"),
    ]
    for i, (r, txt) in enumerate(rows):
        conn.execute(
            "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
            "VALUES (?, ?, ?, ?, ?)", (fid, f"v{i}", r, txt, "2024-05-01"))
    conn.commit()
    return conn, rows


def test_voice_fallback_fills_four_quadrants_without_repeating(tmp_path):
    from src import voices
    _conn, rows = _voice_conn(tmp_path)
    vs = voices.pick_fallback(rows)
    assert [v.quadrant for v in vs] == [q for q, _d in voices.QUADRANTS]
    quotes = [v.quote for v in vs if v.quote]
    assert len(quotes) == len(set(quotes)), "同じ口コミを複数の象限に使っている"
    assert vs[0].rating >= 4          # 維持すべき価値は高評価から
    assert vs[1].rating <= 3          # 重大な不満は低評価から


def test_voice_fallback_adds_no_attributes(tmp_path):
    """口コミからは属性が分からないので、fallback では付けない。"""
    from src import voices
    _conn, rows = _voice_conn(tmp_path)
    for v in voices.pick_fallback(rows):
        assert v.chips == []
        assert v.estimated is False


def test_llm_quote_must_actually_exist_in_the_review(tmp_path):
    """生成された引用が本文に無ければ捏造なので、本文で置き換える。"""
    from src import voices
    _conn, rows = _voice_conn(tmp_path)
    data = [
        {"index": 0, "quote": "映像体験が圧倒的に素晴らしく", "age": "40代",
         "gender": "女性", "companion": "ファミリー"},
        {"index": 1, "quote": "スタッフが最高でした", "age": "", "gender": "",
         "companion": ""},                                   # 本文に無い＝捏造
        {"index": 2, "quote": "", "age": "", "gender": "", "companion": ""},
        {"index": 3, "quote": "季節ごとのイベントがもっと増える", "age": "",
         "gender": "", "companion": ""},
    ]
    vs = voices.apply_llm_result(rows, data)
    assert vs[0].quote.startswith("映像体験が圧倒的に素晴らしく")
    assert vs[0].chips == ["40代・女性", "ファミリー"]
    # 捏造された引用は採用せず、その口コミの本文に差し替わる
    assert "スタッフが最高" not in vs[1].quote
    assert vs[1].quote.startswith("混雑時は待ち時間")
    assert vs[2].quote.startswith("雨の日でも安心して")   # 空なら本文
    assert vs[3].quote.startswith("季節ごとのイベントが")


def test_llm_result_rejects_malformed_shapes(tmp_path):
    from src import voices
    _conn, rows = _voice_conn(tmp_path)
    assert voices.apply_llm_result(rows, "nope") is None
    assert voices.apply_llm_result(rows, [{"index": 0}]) is None       # 件数不足
    assert voices.apply_llm_result(rows, [1, 2, 3, 4]) is None         # dict でない


def test_llm_out_of_range_index_becomes_an_empty_card(tmp_path):
    from src import voices
    _conn, rows = _voice_conn(tmp_path)
    data = [{"index": -1, "quote": "", "age": "", "gender": "", "companion": ""}] * 4
    vs = voices.apply_llm_result(rows, data)
    assert all(v.quote == "" for v in vs)


def test_slide6_renders_four_cards(tmp_path):
    conn, _rows = _voice_conn(tmp_path)
    b = preview.build_bundle(conn, "target", {"target": _result(0.6)}, None, None,
                             peers_override=[])
    html = slides.slide6_voices(b)
    assert "特徴的な口コミ" in html
    assert ("実際の来場者のリアルな声から、維持すべき価値や改善のヒント、"
            "未来の企画につながる声を整理しました。") in html
    for q, _d in __import__("src.voices", fromlist=["voices"]).QUADRANTS:
        assert q in html
    assert "※上記は代表的なご意見（N=1）です。原文はそのまま掲載しています" in html
    assert "映像体験" in html and "混雑時は待ち時間" in html


def test_slide6_notes_that_attributes_are_estimated(tmp_path):
    """属性を出すときは推定である旨を必ず添える。"""
    from src import voices
    conn, rows = _voice_conn(tmp_path)
    data = [{"index": i, "quote": "", "age": "30代", "gender": "男性",
             "companion": "ファミリー"} for i in range(4)]
    b = preview.build_bundle(conn, "target", {"target": _result(0.6)}, None, None,
                             peers_override=[],
                             voices_result=voices.apply_llm_result(rows, data))
    html = slides.slide6_voices(b)
    assert "属性は口コミ本文からの推定です" in html

    # 属性が無いときは余計な注記を出さない
    b2 = preview.build_bundle(conn, "target", {"target": _result(0.6)}, None, None,
                              peers_override=[])
    assert "属性は口コミ本文からの推定です" not in slides.slide6_voices(b2)


def test_slide6_survives_no_reviews(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_facility(conn, "target", ftype="target")
    conn.commit()
    b = preview.build_bundle(conn, "target", {"target": _result(0.5)}, None, None,
                             peers_override=[])
    html = slides.slide6_voices(b)
    assert "この観点に該当する口コミは見つかりませんでした" in html


# --------------------------------------------------------------------------- #
# SLIDE 7「ディスカッションポイント」（PDF p12・構成上は 7）
# --------------------------------------------------------------------------- #
def _disc_bundle(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for nm in ("target", "peer1", "peer2"):
        fid = db.upsert_facility(conn, nm, ftype="comparison")
        conn.execute(
            "INSERT INTO review(facility_id, review_id, rating, text, review_date) "
            "VALUES (?, ?, ?, ?, ?)", (fid, f"{nm}-1", 4, "普通に良い", "2024-04-01"))
    conn.commit()
    matrix = {"target": _result(0.50), "peer1": _result(0.62), "peer2": _result(0.66)}
    return conn, matrix


def test_issues_are_the_weakest_topics_with_computed_scores(tmp_path):
    conn, matrix = _disc_bundle(tmp_path)
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"])
    issues = b["issues"]
    assert len(issues) == 3
    # 自施設 50 → 2.50、競合平均 64 → 3.20、差 -0.70
    for iss in issues:
        assert iss.score5 == 2.50
        assert iss.base5 == 3.20
        assert iss.gap5 == -0.70
        assert iss.impact == 1.0            # 差0.6以上は上限
    assert issues[0].priority == "高"
    assert [i.priority for i in issues[1:]] == ["中", "中"]


def test_issue_score_line_states_the_measured_values(tmp_path):
    conn, matrix = _disc_bundle(tmp_path)
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"])
    line = b["issues"][0].score_line
    assert "2.50" in line and "3.20" in line
    assert "競合平均" in line


def test_discussion_llm_cannot_override_the_numbers(tmp_path):
    """LLM がインパクトを返しても、実測から算出した値を使う。"""
    from src import discussion
    conn, matrix = _disc_bundle(tmp_path)
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"])
    issues = b["issues"]
    data = {
        "issues": [{"evidence": "混雑への言及が多い", "hypothesis": "動線設計の問題",
                    "domains": ["体験設計", "運営"]}] * 3,
        # impact を送りつけても無視されること
        "actions": [{"title": "動線改善", "bullets": ["A", "B", "C"],
                     "feasibility": 0.9, "impact": 0.01}] * 3,
    }
    actions = discussion.apply_llm_result(issues, data)
    assert actions and len(actions) == 3
    assert all(a.impact == 1.0 for a in actions)       # 実測由来（LLMの0.01ではない）
    assert actions[0].feasibility == 0.9               # 実現しやすさはLLMの値
    assert actions[0].priority == "高"                  # 優先度はコード側


def test_discussion_llm_result_rejects_malformed_shapes(tmp_path):
    from src import discussion
    conn, matrix = _disc_bundle(tmp_path)
    issues = preview.build_bundle(conn, "target", matrix, None, None,
                                  peers_override=["peer1", "peer2"])["issues"]
    assert discussion.apply_llm_result(issues, "nope") is None
    assert discussion.apply_llm_result(issues, {"issues": [], "actions": []}) is None
    assert discussion.apply_llm_result(
        issues, {"issues": [{}], "actions": [{}]}) is None      # 件数不足


def test_discussion_result_can_be_a_callback(tmp_path):
    """課題が確定した時点で呼ばれる callable を渡せる（build_bundle は1回だけ）。"""
    conn, matrix = _disc_bundle(tmp_path)
    seen = {}

    def cb(issues):
        seen["n"] = len(issues)
        return {"issues": [{"evidence": "e", "hypothesis": "h",
                            "domains": ["d1", "d2"]}] * 3,
                "actions": [{"title": "施策", "bullets": ["x"],
                             "feasibility": 0.4}] * 3}

    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"],
                             discussion_result=cb)
    assert seen["n"] == 3
    assert b["actions"][0].title == "施策"
    assert b["issues"][0].hypothesis == "h"


def test_slide7_renders_table_matrix_and_actions(tmp_path):
    conn, matrix = _disc_bundle(tmp_path)
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"])
    html = slides.slide7_discussion(b)
    assert "ディスカッションポイント" in html
    for h in ("課題", "根拠", "企画仮説", "対応領域"):
        assert h in html
    assert "優先度マトリクス（インパクト × 実現しやすさ）" in html
    assert "打ち手アクション（優先施策）" in html
    for q in ("中期で検討", "優先的に着手", "検討優先度 低", "短期で着手"):
        assert q in html
    assert "優先度：高" in html and "優先度：中" in html
    assert "実現しやすさ" in html


def test_slide7_marks_llm_generated_content(tmp_path):
    """企画仮説を生成AIが書いたときは、その旨をフッタに出す。"""
    conn, matrix = _disc_bundle(tmp_path)
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"])
    assert "企画仮説・打ち手は生成AIによる提案です" not in slides.slide7_discussion(b)

    b2 = preview.build_bundle(
        conn, "target", matrix, None, None, peers_override=["peer1", "peer2"],
        discussion_result={"issues": [{"evidence": "e", "hypothesis": "仮説",
                                       "domains": ["a", "b"]}] * 3,
                           "actions": [{"title": "t", "bullets": ["b"],
                                        "feasibility": .5}] * 3})
    assert "企画仮説・打ち手は生成AIによる提案です" in slides.slide7_discussion(b2)


def test_slide7_fallback_does_not_invent_measures(tmp_path):
    """LLM 無しでは施策を創作せず、要因特定が先だと述べる。"""
    from src import discussion
    conn, matrix = _disc_bundle(tmp_path)
    b = preview.build_bundle(conn, "target", matrix, None, None,
                             peers_override=["peer1", "peer2"])
    html = slides.slide7_discussion(b)
    assert "要因は未検証" in html
    assert "打ち手は要因を特定してから検討する" in html


def test_slide7_survives_without_topics(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_facility(conn, "target", ftype="target")
    conn.commit()
    b = preview.build_bundle(conn, "target", {}, None, None, peers_override=[])
    assert b["issues"] == []
    assert "課題を抽出できるデータがありません" in slides.slide7_discussion(b)


# --------------------------------------------------------------------------- #
# スコアの較正（市場内の相対位置へ）
# --------------------------------------------------------------------------- #
def _matrix(n: int, spread: float = 0.02) -> dict:
    """n施設ぶんの行列。i番目の感情スコアが 0.50 + i*spread。"""
    return {f"f{i}": _result(0.50 + i * spread) for i in range(n)}


def test_calibration_needs_enough_facilities():
    """施設数が少ないと分布が不安定なので較正しない。"""
    assert topic_score.calibration_stats(_matrix(3)) is None
    assert topic_score.calibration_stats(
        _matrix(topic_score.CALIBRATION_MIN_FACILITIES - 1)) is None
    assert topic_score.calibration_stats(
        _matrix(topic_score.CALIBRATION_MIN_FACILITIES)) is not None


def test_calibration_maps_market_average_to_three():
    """市場平均がちょうど 3.00 になる。"""
    mat = _matrix(11)                      # 0.50〜0.70、平均 0.60
    stats = topic_score.calibration_stats(mat)
    mean, _sd = stats["スタッフ対応"]
    assert abs(mean - 60.0) < 1e-6
    assert abs(topic_score.calibrated_sentiment(mean, stats["スタッフ対応"]) / 20 - 3.0) < 1e-9


def test_calibration_moves_half_a_point_per_standard_deviation():
    mat = _matrix(11)
    stats = topic_score.calibration_stats(mat)
    mean, sd = stats["スタッフ対応"]
    for z, expected in ((1, 3.5), (2, 4.0), (-1, 2.5), (-2, 2.0)):
        got = topic_score.calibrated_sentiment(mean + z * sd, stats["スタッフ対応"]) / 20
        assert abs(got - expected) < 1e-9, (z, got)


def test_calibration_clips_to_the_five_point_range():
    mat = _matrix(11)
    stats = topic_score.calibration_stats(mat)
    mean, sd = stats["スタッフ対応"]
    assert topic_score.calibrated_sentiment(mean + 99 * sd, stats["スタッフ対応"]) == 100.0
    assert topic_score.calibrated_sentiment(mean - 99 * sd, stats["スタッフ対応"]) == 20.0


def test_calibration_preserves_ranking():
    """順位は変えない（相対位置への写像なので単調）。"""
    mat = _matrix(12)
    cal, did = topic_score.calibrate_matrix(mat)
    assert did
    raw = sorted(mat, key=lambda n: -mat[n].sentiment_by_topic()["スタッフ対応"])
    new = sorted(cal, key=lambda n: -cal[n].sentiment_by_topic()["スタッフ対応"])
    assert raw == new


def test_calibration_spreads_compressed_scores():
    """潰れていたスコアが読める幅に広がる。"""
    mat = _matrix(12, spread=0.004)        # 素だと 2.50〜2.72 に潰れる
    raw = [v for r in mat.values() for v in r.sentiment_by_topic().values()]
    cal, _ = topic_score.calibrate_matrix(mat)
    new = [v for r in cal.values() for v in r.sentiment_by_topic().values()]

    raw_span = (max(raw) - min(raw)) / 20
    new_span = (max(new) - min(new)) / 20
    assert raw_span < 0.3                          # 素はほぼ差が無い
    assert new_span > 1.4                          # 較正後は読める幅になる
    assert new_span / raw_span > 5                 # 5倍以上に広がる


def test_calibration_does_not_mutate_the_original():
    mat = _matrix(12)
    before = mat["f0"].sentiment_by_topic()["スタッフ対応"]
    topic_score.calibrate_matrix(mat)
    assert mat["f0"].sentiment_by_topic()["スタッフ対応"] == before


def test_bundle_calibrates_against_the_whole_population_not_the_peers(tmp_path):
    """較正の基準は母集団全体。誰を競合に選んでもスコアは変わらない。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = [f"f{i}" for i in range(12)]
    for nm in names:
        db.upsert_facility(conn, nm, ftype="comparison")
    conn.commit()
    mat = {nm: _result(0.50 + i * 0.02) for i, nm in enumerate(names)}

    a = preview.build_bundle(conn, "f5", mat, None, None, peers_override=names[0:3])
    b = preview.build_bundle(conn, "f5", mat, None, None, peers_override=names[8:11])
    assert a["score_calibrated"] and b["score_calibrated"]
    # 競合の選び方が違っても、自施設のスコアそのものは同じ
    assert a["topic_values"] == b["topic_values"]


def test_bundle_reports_whether_scores_were_calibrated(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    for nm in ("target", "peer1"):
        db.upsert_facility(conn, nm, ftype="comparison")
    conn.commit()
    small = preview.build_bundle(conn, "target",
                                 {"target": _result(0.5), "peer1": _result(0.6)},
                                 None, None, peers_override=["peer1"])
    assert small["score_calibrated"] is False      # 2施設では較正しない


def test_slides_state_what_three_points_means(tmp_path):
    """較正時は「3.00＝市場平均」と必ず書く（絶対評価と誤読されないように）。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = [f"f{i}" for i in range(12)]
    for nm in names:
        db.upsert_facility(conn, nm, ftype="comparison")
    conn.commit()
    mat = {nm: _result(0.50 + i * 0.02) for i, nm in enumerate(names)}
    b = preview.build_bundle(conn, "f5", mat, None, None, peers_override=names[0:4])

    assert b["score_calibrated"]
    note = slides.score_note(b)
    assert "3.00＝市場平均" in note and "相対位置" in note
    for fn in (slides.slide2_market_position, slides.slide2_market_detail,
               slides.slide3_competitor_compare, slides.slide3_competitor_detail,
               slides.slide5_space_experience, slides.slide5_space_detail):
        assert "3.00＝市場平均" in fn(b), fn.__name__

    b2 = dict(b, score_calibrated=False)
    assert "3.00＝市場平均" not in slides.score_note(b2)


# --------------------------------------------------------------------------- #
# レポートの構成（「詳細」ページを出すかどうか）
# --------------------------------------------------------------------------- #
def test_report_has_ten_slides_by_default():
    fns = slides.report_slides()
    assert len(fns) == 10
    assert fns[0] is slides.slide1_facility_info
    assert fns[-1] is slides.slide7_discussion


def test_detail_slides_can_be_dropped():
    """「（詳細）」の3枚を外すと7枚構成になる。"""
    fns = slides.report_slides(detail=False)
    names = [f.__name__ for f in fns]
    assert len(fns) == 7
    for n in slides.DETAIL_SLIDES:
        assert n not in names, f"{n} が外れていない"
    # 外すのは詳細だけ。本編は順番も含めてそのまま
    assert names == ["slide1_facility_info", "slide2_market_position",
                     "slide3_competitor_compare", "slide4_timeline",
                     "slide5_space_experience", "slide6_voices",
                     "slide7_discussion"]


def test_detail_slide_names_all_exist():
    for n in slides.DETAIL_SLIDES:
        assert callable(getattr(slides, n)), n
    assert "（詳細）" not in slides.slide2_market_position({"target": "x"})


def test_both_report_shapes_render(tmp_path):
    b = _bundle(tmp_path)
    for detail in (True, False):
        for fn in slides.report_slides(detail=detail):
            assert fn(b), f"{fn.__name__} (detail={detail})"


def test_setup_screen_offers_the_detail_toggle():
    from pathlib import Path

    from src.ui import analysis_mode

    src = Path(analysis_mode.__file__).read_text(encoding="utf-8")
    assert 'key="an_with_detail"' in src
    assert 'slides.report_slides(' in src


def test_planner_pill_is_gone_from_market_detail(tmp_path):
    """右上の「プランナー起点」は不要との判断で外した。"""
    b = _bundle(tmp_path)
    assert "プランナー起点" not in slides.slide2_market_detail(b)


# --------------------------------------------------------------------------- #
# SLIDE 6（N=1）— 要約と生データの併記
#
#   要約だけだと「本当にそう書いてあるのか」を確かめられない。
#   必ず口コミの原文をそのまま併記する、という取り決めをここで固定する。
# --------------------------------------------------------------------------- #
_RAW = "スタッフの方の説明がとても丁寧で、展示の見方が変わりました。また来たいです。"


def _voice_bundle(tmp_path, voices_list):
    b = _bundle(tmp_path)
    b["voices"] = voices_list
    return b


def test_headline_is_taken_verbatim_from_the_review():
    """LLM が無いときの見出しは、要約せず先頭の文をそのまま切り出す。"""
    from src import voices as _v

    h = _v.headline(_RAW)
    assert h == "スタッフの方の説明がとても丁寧で、展示の見方が変わりました。"
    assert h in _RAW, "生成せず、本文の一部をそのまま使うこと"
    assert _v.headline("") == ""
    assert _v.headline("句点のない口コミ") == "句点のない口コミ"


def test_fallback_keeps_the_raw_text_untouched():
    from src import voices as _v

    vs = _v.pick_fallback([(5, _RAW), (2, "混雑がひどい。")])
    top = vs[0]
    assert top.raw == _RAW, "生データは一字も変えないこと"
    assert top.quote and top.quote in _RAW
    assert top.summarized is False


def test_slide6_shows_both_the_headline_and_the_raw_text(tmp_path):
    from src import voices as _v

    vs = _v.pick_fallback([(5, _RAW)])
    html = slides.slide6_voices(_voice_bundle(tmp_path, vs))
    assert "口コミ原文" in html
    assert escape_ok(html, _RAW), "原文がそのまま載っていない"
    assert escape_ok(html, vs[0].quote)


def escape_ok(html: str, text: str) -> bool:
    from html import escape as _e
    return _e(text) in html


def test_slide6_marks_generated_summaries(tmp_path):
    from src import voices as _v

    vs = _v.apply_llm_result(
        [(5, _RAW), (2, "混雑がひどい。"), (3, "案内がほしい。"), (4, "また来たい。")],
        [{"index": i, "summary": f"要約{i}", "quote": "", "age": "", "gender": "",
          "companion": ""} for i in range(4)],
    )
    assert all(v.summarized for v in vs)
    html = slides.slide6_voices(_voice_bundle(tmp_path, vs))
    assert "見出しは生成AIによる要約です" in html
    # 要約が生成でも、原文は必ずそのまま出る
    assert escape_ok(html, _RAW)


def test_llm_summary_falls_back_to_the_first_sentence(tmp_path):
    """LLM が summary を返さなかったら、生成せず本文の先頭文に落とす。"""
    from src import voices as _v

    vs = _v.apply_llm_result(
        [(5, _RAW)] * 4,
        [{"index": 0, "quote": "", "age": "", "gender": "", "companion": ""}] * 4,
    )
    assert vs[0].quote in _RAW
    assert vs[0].summarized is False


def test_llm_summary_is_used_when_present():
    from src import voices as _v

    vs = _v.apply_llm_result(
        [(5, _RAW)] * 4,
        [{"index": 0, "summary": "説明の丁寧さが体験を変えた", "quote": "",
          "age": "", "gender": "", "companion": ""}] * 4,
    )
    assert vs[0].quote == "説明の丁寧さが体験を変えた"
    assert vs[0].raw == _RAW
    assert vs[0].summarized is True


def test_slide6_survives_an_empty_quadrant(tmp_path):
    from src import voices as _v

    vs = _v.pick_fallback([])
    html = slides.slide6_voices(_voice_bundle(tmp_path, vs))
    assert html and "この観点に該当する口コミは見つかりませんでした" in html


def test_llm_prompt_asks_for_a_summary():
    """要約は生成させる。ただし本文の創作は禁じたまま。"""
    import inspect

    from src import llm

    src = inspect.getsource(llm.pick_voice_quadrants)
    assert '"summary"' in src
    assert "書かれていない事実を足さない" in src
    assert "創作してはいけません" in src
