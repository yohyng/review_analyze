"""デザイントークンが引き継ぎ資料の正典どおりであることを固定する。

出典は design_handoff_voicebaum の README §2「デザイントークン（厳守）」と、
動くリファレンス実装 ReviewLens.dc.html。ここに書いてある値は「実装の都合で
近い色に寄せる」ことが許されない類のものなので、テストで直に固定する。

以前は PDF を 200dpi でラスタライズして画素から実測していたが、JPEG 圧縮の
にじみを拾って 1〜2 段ずれていた。README の値が正。
"""
from __future__ import annotations

from src import report_theme as T


# --------------------------------------------------------------------------- #
# README §2「色」
# --------------------------------------------------------------------------- #
def test_base_colors_match_readme():
    assert T.NAVY == "#17224B"          # ヘッダー帯・カード見出し
    assert T.ACCENT == "#E8386A"        # アクセント（マゼンタ）
    assert T.BLUE == "#2E5BD8"          # 弱み・競合・課題


def test_accent_has_no_second_shade():
    """正典のアクセントは1色。濃淡を勝手に作らない。"""
    assert T.ACCENT_DEEP == T.ACCENT
    assert T.ACCENT_VIVID == T.ACCENT


def test_soft_fills_match_readme():
    assert (T.ACCENT_SOFT, T.ACCENT_SOFT_2, T.ACCENT_SOFT_3) == (
        "#FDEBF1", "#FDF2F6", "#FBDDE7")
    assert (T.BLUE_SOFT, T.BLUE_SOFT_2, T.BLUE_SOFT_3) == (
        "#EAF0FB", "#F2F6FD", "#F5F8FE")
    assert (T.BAR_PINK, T.BAR_BLUE) == ("#F8B8CC", "#9EBBEC")


def test_ink_and_rules_match_readme():
    assert (T.INK, T.INK_SUB, T.INK_MUTE, T.INK_FAINT) == (
        "#1B2333", "#4A5262", "#6B7280", "#9AA0AE")
    assert (T.CARD_LINE, T.LINE, T.TABLE_HEAD) == ("#E3E5EA", "#EDEFF3", "#F3F5F8")
    assert (T.STAR, T.STAR_EMPTY) == ("#F2B01E", "#D6D9E0")


def test_trend_badge_colors_match_readme():
    assert T.TREND_BADGES["強み"]["fg"] == "#E8386A"
    assert T.TREND_BADGES["課題"]["fg"] == "#2E5BD8"
    assert T.TREND_BADGES["良好"]["fg"] == "#E08A2E"


# --------------------------------------------------------------------------- #
# README §2 最終行・ReviewLens.dc.html:2028 のヒートマップ5段階
# --------------------------------------------------------------------------- #
def test_heatmap_steps_match_readme():
    assert T.HEAT_STEPS == [
        (4.2, "#FBDDE7"), (3.8, "#FDF2F6"), (3.4, "#F7FAFE"), (3.0, "#EDF3FC"),
    ]
    assert T.HEAT_FLOOR == "#E2EBF9"


def test_heat_bg_picks_the_right_step():
    assert T.heat_bg(4.5) == "#FBDDE7"
    assert T.heat_bg(4.2) == "#FBDDE7"      # 境界は「以上」
    assert T.heat_bg(3.9) == "#FDF2F6"
    assert T.heat_bg(3.5) == "#F7FAFE"
    assert T.heat_bg(3.0) == "#EDF3FC"
    assert T.heat_bg(2.9) == "#E2EBF9"
    assert T.heat_bg(None) == "#FFFFFF"


def test_heat_bg_self_column_stays_pink():
    """自施設の列は低スコアでも薄ピンク（青くしない）。"""
    assert T.heat_bg(4.3, is_self=True) == "#FBDDE7"
    assert T.heat_bg(2.0, is_self=True) == T.HEAT_SELF
    assert T.HEAT_SELF == "#FDEFF4"


# --------------------------------------------------------------------------- #
# 系列色（ReviewLens.dc.html:1907 / :2049）
# --------------------------------------------------------------------------- #
def test_series_colors_match_reference_implementation():
    assert T.SERIES_SELF == T.ACCENT
    assert T.SERIES_PEERS == ["#17224B", "#6E9BE8", "#12A594", "#8B5CF6", "#B6BCC8"]
    assert T.SERIES_AVG == "#B6BCC8"
    assert T.DASH_AVG == "4 3"              # README §3
    assert T.BAR_PEER == "#B9C9E8"          # 評価分布ヒストグラム


def test_score_bands_match_reference_legend():
    assert T.SCORE_BANDS == [
        (4.0, 5.0, "#E8386A"), (3.0, 3.9, "#F5A0BE"),
        (2.0, 2.9, "#9EBBEC"), (1.0, 1.9, "#CBDAF5"),
    ]


def test_quadrant_and_summary_cards_carry_icon_and_border():
    """カードの意匠は icon / bg / border / fg の4点セットで持つ。"""
    for c in T.SUMMARY_CARDS:
        assert {"no", "icon", "fg", "bg", "border"} <= set(c)
    for style in T.QUADRANT_CARDS.values():
        assert {"icon", "fg", "bg", "border", "icon_bg"} <= set(style)
    assert len(T.SUMMARY_CARDS) == 4 and len(T.QUADRANT_CARDS) == 4


# --------------------------------------------------------------------------- #
# README §2「スライドの寸法系（重要）」
# --------------------------------------------------------------------------- #
def test_layout_metrics_match_readme():
    assert T.ASPECT_RATIO == "16/9"
    assert T.HEADER_H == 6.3            # ヘッダー帯の高さ
    assert T.TILE_W == 6.3              # 番号タイルは正方
    assert T.BODY_X == 2.0              # 本文エリアの左右
    assert (T.BODY_TOP, T.BODY_TOP_TIGHT) == (7.4, 6.9)
    assert T.BODY_BOTTOM == 4.6
    assert T.SLIDE_RADIUS == "10px"


def test_structural_font_sizes_match_readme():
    """骨格の級数は正典のまま動かさない。"""
    assert T.FS["slide_title"] == 2.30   # スライドタイトル 2.3cqw/800
    assert T.FS["slide_num"] == 2.70     # 番号タイルの数字 2.7cqw/800
    assert T.FS["panel_head"] == 1.35    # カード見出し 1.35cqw/700
    assert T.FS["footer_mark"] == 1.50   # Voice BAUM 1.5cqw/800
    assert T.FS["big_number"] == 3.40


def test_body_font_sizes_are_raised_above_the_readme_minimums():
    """本文まわりは正典より一段上げてある（実データで読めなかったため）。

    上げたことを忘れて正典の値へ戻さないよう、下限をここで固定する。
    """
    assert T.FS["slide_meta"] >= 1.05    # 正典 1.05
    assert T.FS["note"] >= 0.95          # 正典 0.95
    assert T.FS["table_cell"] >= 0.88    # 正典 0.88〜1.05
    assert T.FS["body"] >= 1.0           # 正典 1.0〜1.2
    # 上げすぎて骨格を食わないこと
    assert T.FS["body"] < T.FS["panel_head"]


def test_font_stack_loads_both_families_including_weight_800():
    """見出しは800。Noto Sans JP の 800 を読まないと和文が合成太字になる。"""
    assert "Noto Sans JP" in T.FONT_STACK and "Manrope" in T.FONT_STACK
    assert "Noto+Sans+JP:wght@400;500;700;800" in T.FONT_URL
    assert "Manrope:wght@400;500;600;700;800" in T.FONT_URL


def test_report_theme_is_not_the_app_ui_theme():
    """アプリUIのマゼンタ（#B0338A）がレポート側に混ざっていないこと。

    （モジュールの docstring では注意書きとして触れているので、そこは除く。）
    """
    values = [v for k, v in vars(T).items()
              if isinstance(v, str) and not k.startswith("__")]
    assert not any("B0338A" in v for v in values)
