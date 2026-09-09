"""NMSI を画面につないだときの境界。

設計:
  課金する計算は**管理モード（ログイン必須）だけ**。
  分析画面は未ログインで開けるので、そこから LLM 呼び出しが飛ぶ導線は作らない。
  レポート側は保存済みの結果を読むだけ（閲覧では課金されない）。

この分離が崩れると、URL を知っている人がページを開くだけで所有者の
OpenAI に課金できてしまう。Google Maps のキーで一度踏んだのと同じ形。
"""
from __future__ import annotations

import ast
from pathlib import Path

from src.ui import admin_mode, analysis_mode

ADMIN = Path(admin_mode.__file__).read_text(encoding="utf-8")
ANALYSIS = Path(analysis_mode.__file__).read_text(encoding="utf-8")
SLIDES = Path("src/slides.py").read_text(encoding="utf-8")

# LLM を実際に叩く入口
PAID = {"analyze", "analyze_sentences", "analyze_sentence_batch",
        "run_pipeline", "run_visitor_vffi_pipeline", "embed_texts"}


def _calls(src: str) -> set[str]:
    out = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def test_the_public_analysis_screen_never_starts_a_paid_run():
    hits = _calls(ANALYSIS) & PAID
    # analysis_mode の "analyze" は別物（topic_score.analyze_facility 等）なので、
    # nmsi 経由で呼んでいないことを見る
    assert "nmsi" not in ANALYSIS or "nmsi_run.analyze" not in ANALYSIS, (
        "未ログインで開ける画面から NMSI の計算を呼んでいる")
    assert "analyze_sentences" not in hits
    assert "run_pipeline" not in hits


def test_slides_never_start_a_paid_run():
    """スライドは描画のたびに走る。ここから課金が飛ぶと歯止めが無い。"""
    assert "nmsi" not in SLIDES.lower() or "from src.nmsi import run" not in SLIDES
    assert not (_calls(SLIDES) & PAID)


def test_the_admin_page_shows_the_cost_before_the_button():
    """押す前に回数が見えること。黙って課金しない。"""
    i = ADMIN.index('elif _page == "nmsi":')
    page = ADMIN[i:i + 6000]
    assert "llm_calls" in page, "呼び出し回数を出していない"
    # 実行ボタンのラベルに回数が入っている
    assert "LLM {_plan.llm_calls:,} 回" in page
    # 回数の表示が、実行ボタンより前にあること
    assert page.index("_plan.llm_calls") < page.index('key="nmsi_run"')


def test_the_admin_page_is_disabled_without_a_key():
    i = ADMIN.index('elif _page == "nmsi":')
    page = ADMIN[i:i + 6000]
    assert "_disabled = not _key_set" in page
    assert 'disabled=_disabled' in page


def test_nmsi_page_is_reachable_only_from_the_admin_nav():
    app = Path("app.py").read_text(encoding="utf-8")
    assert '("🧭 NMSI（体験満足度）", "nmsi")' in app
    # 管理モードのナビは、app.py の認証ゲートより後ろで組まれる
    assert app.index('if not st.session_state.get("admin_authed")') < app.index('"nmsi")')
