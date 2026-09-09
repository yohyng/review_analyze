"""Shared paths and constants."""
from pathlib import Path

import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# 既定は data/reviews.db。環境変数 VOICEBAUM_DB で差し替えられる。
# ダミーデータで動作確認するときに本番DBを汚さずに済む:
#     VOICEBAUM_DB=data/dummy.db streamlit run app.py
DB_PATH = Path(os.environ.get("VOICEBAUM_DB") or (DATA_DIR / "reviews.db"))

APP_VERSION = "0.58.0"

# スコアの較正（市場内の相対位置へ写す）。詳細は topic_score の
# calibration_stats を参照。False にすると素の感情スコアがそのまま出るが、
# 実データでは全施設が5点満点の 2.4〜3.3 に潰れて差が読めなくなる。
SCORE_CALIBRATION = True

# Facility roles (step 1 / step 2)
FACILITY_TYPES = {
    "target": "対象施設",
    "comparison": "比較施設",
}

# Disclaimer shown as the opening slide of every analysis output (preview + PPTX).
# Edit here to change the wording in one place.
DISCLAIMER_TITLE = "本レポートのご利用にあたって"
DISCLAIMER_POINTS = [
    "本レポートは、Googleマップ等に一般公開された口コミを自動で収集・集計・分析したものです。",
    "感情・トピックスコアは独自アルゴリズムによる自動推定値であり、人手による検証は行っていません。数値は相対的な傾向把握を目的とした参考指標です。",
    "口コミは投稿者個人の主観的な意見であり、内容の正確性・網羅性・最新性を保証するものではありません（投稿の偏り・重複・作為的投稿等を含む可能性があります）。",
    "本レポートの内容は分析時点のデータに基づきます。時間の経過により実態と乖離する場合があります。",
    "本レポートは確定的な評価・意思決定・第三者への公表を目的とするものではなく、利用に伴う一切の結果について作成者は責任を負いません。",
    "施設名・投稿者名等の情報を含む場合があります。取扱いには十分ご注意ください（社内限りでのご利用を想定）。",
]
