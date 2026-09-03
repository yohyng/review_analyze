"""グラフの軸にホバーすると、その観点の説明が出ることのテスト。

Streamlit の st.markdown(unsafe_allow_html=True) は <script> を落とすので、
**CSS だけ**で作る（:hover で子要素を出す）。

吹き出しはスライドの枠（overflow:hidden）に切られるので、ラベルの位置に
応じて内側へ逃がす。実ブラウザで54個すべてホバーして枠内に収まることを
確認したうえで、その取り決めをここで固定する。
"""
from __future__ import annotations

import pytest

from src import db, preview, slides, topic_score


# --------------------------------------------------------------------------- #
# 22観点すべてに説明がある
# --------------------------------------------------------------------------- #
def test_every_topic_has_a_description():
    missing = [t.name for t in topic_score.DEFAULT_TOPICS if not t.desc]
    assert not missing, f"説明の無い観点: {missing}"
    assert len(topic_score.DEFAULT_TOPICS) == 22


def test_descriptions_say_what_is_measured_not_just_restate_the_name():
    """名前を言い換えただけの説明にしない。"""
    for t in topic_score.DEFAULT_TOPICS:
        assert len(t.desc) >= 12, f"{t.name} の説明が短すぎる: {t.desc}"
        assert t.desc != t.name


def test_outcome_topics_are_marked_as_such():
    """成果指標（体験満足度・推奨意向・再訪意向）はその旨が分かること。"""
    for name in topic_score.OUTCOME_TOPICS:
        d = next(t for t in topic_score.DEFAULT_TOPICS if t.name == name)
        assert "成果指標" in d.desc, name


# --------------------------------------------------------------------------- #
# ツールチップの組み立て
# --------------------------------------------------------------------------- #
def test_tooltip_is_css_only():
    """<script> は st.markdown に落とされる。JS に頼らないこと。"""
    assert "<script" not in slides.TOOLTIP_CSS
    assert ":hover" in slides.TOOLTIP_CSS
    assert "<script" not in slides.topic_tooltip("空間の快適性")


def test_topic_tooltip_carries_the_description_and_keywords():
    html = slides.topic_tooltip("空間の快適性")
    assert "空間の快適性" in html
    assert "居心地" in html                      # 説明
    assert "拾う語:" in html and "静か" in html   # 何を数えているか


def test_tooltip_without_a_description_is_plain_text():
    assert slides.tooltip("ラベル", "") == "ラベル"
    assert slides.topic_tooltip("存在しない観点") == "存在しない観点"


def test_tooltip_escapes_user_text():
    html = slides.tooltip("<b>名前</b>", "<i>説明</i>")
    assert "<b>" not in html and "&lt;b&gt;" in html
    assert "<i>" not in html and "&lt;i&gt;" in html


@pytest.mark.parametrize("place", ["up", "down", "left", "right",
                                   "up-l", "up-r", "down-l", "down-r"])
def test_every_place_has_matching_css(place):
    assert f".vb-tipbody.{place}{{" in slides.TOOLTIP_CSS.replace(" ", "")
    assert f'vb-tipbody {place}"' in slides.tooltip("x", "せつめい", place=place)


# --------------------------------------------------------------------------- #
# 吹き出しを出す向き（枠から抜けないように内側へ）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lx,ly,want", [
    (10, 50, "right"),    # 左のラベル → 中心側（右）へ
    (90, 50, "left"),     # 右のラベル → 左へ
    (50, 10, "down"),     # 真上 → 下へ
    (50, 90, "up"),       # 真下 → 上へ
    (52, 88, "up"),       # 真下寄り（±12以内）は縦に逃がす
    (70, 88, "left"),     # 右下は横に空きがある
])
def test_radar_tooltip_points_toward_the_centre(lx, ly, want):
    assert slides._tip_dir(lx, ly, 50, 50) == want


def test_rotated_axis_labels_do_not_carry_tooltips():
    """-62°回転したラベルに吹き出しを入れると、一緒に傾いて枠を抜ける。

    19指標比較のX軸は回転しているので付けない。同じスライドのヒートマップに
    横書きの指標名があり、そちらで説明が読める。
    """
    import inspect

    src = inspect.getsource(slides._compare_chart)
    assert "tips=True" not in src
    assert "ヒートマップ" in src


# --------------------------------------------------------------------------- #
# 実際のスライドに乗っていること
# --------------------------------------------------------------------------- #
def _bundle(tmp_path):
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = ["target"] + [f"peer{i}" for i in range(3)]
    w = 1.0 / len(topic_score.TOPIC_ORDER)
    matrix = {}
    for i, nm in enumerate(names):
        db.upsert_facility(conn, nm, ftype="comparison", category="美術館")
        sv = 0.5 + 0.03 * i
        matrix[nm] = topic_score.TopicScoreResult(
            topics=[topic_score.TopicScore(name=t, weight=w, avg_score=sv * w,
                                           total_score=sv * w, salience=w,
                                           sentiment=sv)
                    for t in topic_score.TOPIC_ORDER],
            overall_score=sv, n_reviews=10, n_sentences=30, empty=False)
    conn.commit()
    return preview.build_bundle(conn, "target", matrix, None, None,
                                peers_override=names[1:])


@pytest.mark.parametrize("fn_name", [
    "slide2_market_position",     # 強み/弱み TOP3
    "slide2_market_detail",       # 独自分析指標のX軸（縦書き）
    "slide3_competitor_compare",  # ヒートマップの指標名
    "slide5_space_experience",    # レーダーの軸
])
def test_slides_carry_hover_explanations(tmp_path, fn_name):
    html = getattr(slides, fn_name)(_bundle(tmp_path))
    assert 'class="vb-tip"' in html, f"{fn_name} に説明が付いていない"
    assert "vb-tipbody" in html
    assert "拾う語:" in html


def test_tooltip_css_is_included_once_per_slide(tmp_path):
    html = slides.slide2_market_position(_bundle(tmp_path))
    assert html.count(".vb-tip{") == 1


def test_slides_without_axis_labels_still_render(tmp_path):
    """説明が付かない面も落ちないこと。"""
    b = _bundle(tmp_path)
    for fn in (slides.slide0_disclaimer, slides.slide1_facility_info,
               slides.slide6_voices, slides.slide7_discussion):
        assert fn(b)
