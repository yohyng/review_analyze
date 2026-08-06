"""レポート（分析スライド）のデザイントークン。

**出典: design_handoff_voicebaum（デザインの正典）**
  - `README.md` §2「デザイントークン（厳守）」… ここに書かれた値がすべてに優先する
  - `ReviewLens.dc.html`（動くリファレンス実装）… README に載っていない
    系列色・カード配色・SVG の細部はここから採った（行番号をコメントに残す）

以前は PDF を 200dpi でラスタライズして画素から色を実測していたが、
ハンドオフの README がトークンを明示したのでそちらに合わせた（実測値は
JPEG 圧縮のにじみを拾っていて 1〜2 段ずれていた）。

⚠️ アプリのUI全体のテーマ（src/ui/theme.py の ACCENT = #B0338A マゼンタ）とは
   別系統。レポート内の描画は必ずこちらを使うこと。
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# ベース（README §2「色」）
# --------------------------------------------------------------------------- #
NAVY        = "#17224B"   # ヘッダー帯・カード見出し
NAVY_DEEP   = "#17224B"   # 帯の濃淡差は正典に無い。同値に揃える
NAVY_LINE   = "#2C3A66"   # 紺地の上に引く仕切り線（SLIDE 7 の表ヘッダ）

ACCENT      = "#E8386A"   # アクセント（マゼンタ）
ACCENT_DEEP = "#E8386A"   # 正典はアクセント1色。濃淡を作らない
ACCENT_VIVID = "#E8386A"

# アクセント淡（面）
ACCENT_SOFT   = "#FDEBF1"  # 帯・アイコン地
ACCENT_SOFT_2 = "#FDF2F6"  # ヒートマップ 3.8+ / 優先マトリクスの強調象限
ACCENT_SOFT_3 = "#FBDDE7"  # ヒートマップ 4.2+
ACCENT_BORDER = "#F0C9D8"  # 淡い面の枠

BLUE        = "#2E5BD8"   # 弱み・競合・課題
BLUE_SOFT   = "#EAF0FB"
BLUE_SOFT_2 = "#F2F6FD"
BLUE_SOFT_3 = "#F5F8FE"
BLUE_BORDER = "#C9D8F3"

BAR_PINK    = "#F8B8CC"   # 積み上げバー（正）
BAR_BLUE    = "#9EBBEC"   # 積み上げバー（負）

INK         = "#1B2333"   # 本文インク
INK_SUB     = "#4A5262"   # サブ
INK_MUTE    = "#6B7280"   # 淡
INK_FAINT   = "#9AA0AE"   # 極淡
SUB         = INK_SUB     # 旧名の別名（軸ラベル等）
MUTED       = "#8A90A0"   # 「市場平均 3.4」のような添え字

CARD_LINE   = "#E3E5EA"   # カード枠
LINE        = "#EDEFF3"   # 内部罫線
TABLE_HEAD  = "#F3F5F8"   # 表ヘッダ地
PAGE_BG     = "#FFFFFF"

STAR        = "#F2B01E"   # 星（ゴールド）
STAR_EMPTY  = "#D6D9E0"   # 空星
LAUREL      = "#F8C4D5"   # 総合評価ランキングの月桂樹（README §3）
TABLE_AVG   = "#C9CEDA"   # 「同業平均」列のヘッダ地（ReviewLens.dc.html:306）

# --------------------------------------------------------------------------- #
# ヒートマップ（README §2 最終行・ReviewLens.dc.html:2028 heatBg）
#   高＝ピンク / 低＝ブルーの5段階
# --------------------------------------------------------------------------- #
HEAT_STEPS = [            # (この値以上, 背景色)
    (4.2, "#FBDDE7"),
    (3.8, "#FDF2F6"),
    (3.4, "#F7FAFE"),
    (3.0, "#EDF3FC"),
]
HEAT_FLOOR  = "#E2EBF9"   # 2.9 以下
HEAT_SELF   = "#FDEFF4"   # 自施設列は 4.2 未満でも薄ピンクを敷く

HEAT_HIGH   = ACCENT_SOFT_3
HEAT_HIGH_W = ACCENT_SOFT_2
HEAT_LOW    = "#E2EBF9"
HEAT_LOW_W  = "#EDF3FC"


def heat_bg(v5: float | None, *, is_self: bool = False) -> str:
    """5点満点のスコアをヒートマップの背景色に。ReviewLens.dc.html:2028 と同じ段階。"""
    if v5 is None:
        return "#FFFFFF"
    if is_self:
        return "#FBDDE7" if v5 >= 4.2 else HEAT_SELF
    for lo, col in HEAT_STEPS:
        if v5 >= lo:
            return col
    return HEAT_FLOOR


# --------------------------------------------------------------------------- #
# 系列色（ReviewLens.dc.html:1907 / :2049）
# --------------------------------------------------------------------------- #
SERIES_SELF = ACCENT      # 自施設（実線 2px）
SERIES_PEERS = [          # 競合A〜E
    "#17224B",            # 競合A（ネイビー）
    "#6E9BE8",            # 競合B（ブルー）
    "#12A594",            # 競合C（ティール）
    "#8B5CF6",            # 競合D（パープル）
    "#B6BCC8",            # 競合E（グレー）
]
SERIES_AVG  = "#B6BCC8"   # 同業平均（破線 4 3・マーカーなし）
DASH_AVG    = "4 3"       # README §3「破線 4 3」
DASH_IND    = "3 3"       # レーダーの同業平均
BAR_PEER    = "#B9C9E8"   # 評価分布ヒストグラムの通常バー（:1842）

# --------------------------------------------------------------------------- #
# ポジ／ネガ（SLIDE 4 時間軸分析の積み上げ棒）
# --------------------------------------------------------------------------- #
POS_BAR     = BAR_PINK
NEG_BAR     = BAR_BLUE
DIFF_LINE   = NAVY        # 差分（ポジ−ネガ）の折れ線（白抜き点）

# --------------------------------------------------------------------------- #
# 要約4カード（SLIDE 5「本ページの要約」・ReviewLens.dc.html:2063）
# --------------------------------------------------------------------------- #
SUMMARY_CARDS = [
    {"no": "01", "icon": "▲", "fg": ACCENT,   "bg": "#FDF2F6", "border": "#F5D2DF"},
    {"no": "02", "icon": "✿", "fg": BLUE,     "bg": "#F4F8FE", "border": "#CFDEF6"},
    {"no": "03", "icon": "◎", "fg": "#E08A2E", "bg": "#FEF8F0", "border": "#F5E0BE"},
    {"no": "04", "icon": "✦", "fg": "#12A594", "bg": "#F1FAF8", "border": "#C4E9E3"},
]

# 4象限カード（SLIDE 6「特徴的な口コミ」・ReviewLens.dc.html:2076）
QUADRANT_CARDS = {
    "維持すべき価値": {
        "icon": "♥", "fg": ACCENT, "bg": "#FDF6F9",
        "border": "#F3D4E0", "icon_bg": "#FBE3EC",
    },
    "重大な不満": {
        "icon": "!", "fg": "#D94A4A", "bg": "#FDF5F5",
        "border": "#F0D2D2", "icon_bg": "#FBE1E1",
    },
    "潜在的なニーズ": {
        "icon": "✦", "fg": "#E0A02E", "bg": "#FEFAF2",
        "border": "#F2E3C4", "icon_bg": "#FBEFD5",
    },
    "未来の企画につながる声": {
        "icon": "★", "fg": BLUE, "bg": "#F5F8FE",
        "border": "#CFDEF6", "icon_bg": "#E3ECFB",
    },
}

# 傾向タグ（SLIDE 5 詳細「傾向」列・ReviewLens.dc.html:2035 tagStyle）
TREND_BADGES = {
    "強み": {"fg": ACCENT,   "border": "#F0C9D8", "bg": "#FDF2F6"},
    "課題": {"fg": BLUE,     "border": "#C9D8F3", "bg": "#F2F6FD"},
    "良好": {"fg": "#E08A2E", "border": "#F3DDB9", "bg": "#FEF8F0"},
}

# スコアの見方（SLIDE 5 詳細 右下の凡例・5点満点の4段階）
SCORE_BANDS = [
    (4.0, 5.0, "#E8386A"),
    (3.0, 3.9, "#F5A0BE"),
    (2.0, 2.9, "#9EBBEC"),
    (1.0, 1.9, "#CBDAF5"),
]

# 優先度マトリクスの凡例（SLIDE 7）
MATRIX_LEGEND = [
    ("優先施策（短期〜中期）", ACCENT),
    ("改善施策（短期）", BLUE),
    ("中長期・検討施策", INK_FAINT),
]

# --------------------------------------------------------------------------- #
# タイポグラフィ（README §2「タイポグラフィ」）
#   Noto Sans JP ＋ Manrope（数字・英字）。Streamlit 側で Google Fonts を読み込む。
# --------------------------------------------------------------------------- #
FONT_STACK = (
    "Manrope, 'Noto Sans JP', 'Yu Gothic', YuGothic, "
    "'Hiragino Sans', Meiryo, system-ui, sans-serif"
)
FONT_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Manrope:wght@400;500;600;700;800"
    "&family=Noto+Sans+JP:wght@400;500;700;800&display=swap"
)

# スライドは 16:9。内部の寸法はすべて cqw（コンテナ幅%）で持つ。
ASPECT_RATIO = "16/9"

# レイアウト（README §2「スライドの寸法系」）
HEADER_H     = 6.3        # ヘッダー帯の高さ
TILE_W       = 6.3        # 番号タイル（正方）
BODY_X       = 2.0        # 本文エリアの左右
BODY_TOP     = 7.4        # 本文エリアの上（詰めたい面は 6.9）
BODY_TOP_TIGHT = 6.9
BODY_BOTTOM  = 4.6        # 本文エリアの下
FOOTER_BOTTOM = 1.1       # フッターの下端
CARD_RADIUS  = ".8cqw"    # カードの角丸
SLIDE_RADIUS = "10px"     # スライド枠の角丸
SLIDE_SHADOW = ("0 1px 2px rgba(20,30,40,.05),"
                "0 10px 28px rgba(20,30,40,.05)")

FS = {
    "slide_title":  2.30,   # スライドタイトル（白・800）
    "slide_num":    2.70,   # 番号タイルの数字（白・800）
    "slide_meta":   1.05,   # ヘッダー右の補足（白・600）
    "slide_lead":   1.20,   # 本文先頭のリード文（700）
    "panel_head":   1.35,   # カード見出し（白・700）
    "panel_head_s": 1.25,   # 幅の狭いカードの見出し
    "body":         1.05,   # 本文テキスト（1.0〜1.2）
    "table_head":   0.95,
    "table_cell":   0.95,   # 表セル（0.88〜1.05）
    "table_cell_s": 0.88,
    "axis_label":   0.80,
    "legend":       0.95,
    "big_number":   3.40,   # 「4.12」など
    "footer_mark":  1.50,   # Voice BAUM のワードマーク（800）
    "note":         0.95,   # フッタ・欄外の注記
}
