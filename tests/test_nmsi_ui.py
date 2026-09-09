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


# ── スライドへの反映 ──────────────────────────────────────────────── #
def _bundle_with_nmsi(tmp_path, nmsi=None):
    from src import db, preview, topic_score

    topics = [t.name for t in topic_score.DEFAULT_TOPICS]
    w = 1.0 / len(topics)

    def _res(v):
        return topic_score.TopicScoreResult(
            topics=[topic_score.TopicScore(name=t, weight=w, avg_score=v * w,
                                           total_score=v * w, salience=w,
                                           sentiment=v) for t in topics],
            overall_score=v, n_reviews=20, n_sentences=200, empty=False)

    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = ["target"] + [f"peer{i}" for i in range(5)]
    for nm in names:
        db.upsert_facility(conn, nm, ftype="comparison", category="美術館")
    if nmsi is not None:
        from src.nmsi import run as nmsi_run
        nmsi_run.save_result(conn, "target", nmsi["summary"], nmsi["phases"],
                             n_sentences=nmsi["n_sentences"], llm_calls=3)
    return preview.build_bundle(
        conn, "target", {n: _res(0.5 + 0.02 * i) for i, n in enumerate(names)},
        None, None)


_NMSI_FIXTURE = {
    "summary": {"NMSI": 72.4, "解釈": "高満足", "記憶補正_M": 0.31,
                "再訪推奨補正_R": 0.44, "摩擦補正_F": 0.18},
    "phases": [
        {"phase": "arrival", "フェーズ": "到着", "重み": 0.30, "E_i": -0.22,
         "ポジティブ": 0.39, "文数": 40},
        {"phase": "exhibition", "フェーズ": "展示", "重み": 0.45, "E_i": 0.61,
         "ポジティブ": 0.80, "文数": 120},
        {"phase": "experience", "フェーズ": "体験", "重み": 0.25, "E_i": 0.33,
         "ポジティブ": 0.66, "文数": 55},
    ],
    "n_sentences": 215,
}


def test_deck_is_unchanged_when_nmsi_was_never_computed(tmp_path):
    """未計算なら今までの10枚が1枚も変わらないこと。"""
    from src import slides

    b = _bundle_with_nmsi(tmp_path)
    assert b["nmsi"] is None

    fixed = [fn(b) for fn in slides.report_slides()]
    assert slides.deck(b) == fixed
    assert len(slides.deck(b)) == 10
    assert len(slides.deck(b, detail=False)) == 7
    assert slides.deck_size(b) == 10


def test_deck_gains_one_slide_when_nmsi_exists(tmp_path, monkeypatch):
    from src import slides

    monkeypatch.setenv("OPENAI_TEXT_MODEL", "m")
    b = _bundle_with_nmsi(tmp_path, _NMSI_FIXTURE)
    assert b["nmsi"] and b["nmsi"]["nmsi"] == 72.4

    d = slides.deck(b)
    assert len(d) == 11
    assert slides.deck_size(b) == 11
    # 先頭10枚は未計算のときと同じ
    assert d[:10] == [fn(b) for fn in slides.report_slides()]

    last = d[-1]
    assert "72.4" in last and "高満足" in last
    assert "展示" in last and "到着" in last
    # 22観点と混同させない注記
    assert "直接は比較できません" in last


def test_nmsi_slide_is_empty_without_data():
    from src import slides
    assert slides.slide8_nmsi({}) == ""
    assert slides.slide8_nmsi({"nmsi": None}) == ""


def test_phases_with_no_sentences_are_dropped(tmp_path, monkeypatch):
    """観測されなかったフェーズの帯を描かないこと（空の行が並ぶため）。"""
    from src import slides

    monkeypatch.setenv("OPENAI_TEXT_MODEL", "m")
    fx = dict(_NMSI_FIXTURE)
    fx["phases"] = _NMSI_FIXTURE["phases"] + [
        {"phase": "food_retail", "フェーズ": "飲食・物販", "重み": 0.0,
         "E_i": 0.0, "ポジティブ": 0.5, "文数": 0}]
    b = _bundle_with_nmsi(tmp_path, fx)
    assert "飲食・物販" not in slides.slide8_nmsi(b)
