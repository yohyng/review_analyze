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
