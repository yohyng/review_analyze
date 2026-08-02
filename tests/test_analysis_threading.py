"""分析のバックグラウンドスレッド周りの回帰テスト。

背景（これが無いと分析が終わらず無限にやり直される）:
  分析の重い処理（③〜⑥）は素の threading.Thread で走らせている。Streamlit の
  ScriptRunContext は「スレッドオブジェクトの属性」として持ち回られるため、
  自前で起こしたスレッドでは ctx が None になる。そして Streamlit 1.58 の
  session_state_proxy.get_session_state() は ctx が None のとき例外を投げず、
  **使い捨てのグローバル・モック SessionState を返す**。
  つまりワーカースレッドからの st.session_state への書き込みは、エラーも警告も
  無いまま丸ごと捨てられる。

  実際にこれで、ワーカーが書いた an_screen="preview" が本物のセッションに
  届かず、fragment の rerun 後もずっと an_screen=="running" のままとなり、
  分析が延々と再起動し続ける不具合が起きた。

  → ワーカーは成果物を素の dict（prog["result"]）に貯め、session_state への
    反映はメインスレッドだけが行う、という取り決めをここで固定する。
"""
from __future__ import annotations

import threading
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "ui" / "analysis_mode.py"


def _worker_source() -> str:
    """analysis_mode._analysis_worker の本体ソースだけを切り出す。"""
    text = SRC.read_text(encoding="utf-8")
    start = text.index("def _analysis_worker(")
    end = text.index("_thread = threading.Thread(", start)
    return text[start:end]


def test_spawned_thread_has_no_script_run_ctx():
    """自前スレッドには ScriptRunContext が無い（＝session_state が偽物になる）。"""
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    seen: dict = {}

    def _worker():
        seen["ctx"] = get_script_run_ctx(suppress_warning=True)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=5)

    assert not t.is_alive()
    assert seen["ctx"] is None


def test_worker_never_touches_session_state():
    """ワーカー本体に st.session_state が出てきたら回帰（黙って消える書き込み）。"""
    body = _worker_source()
    assert "st.session_state" not in body, (
        "ワーカースレッドから st.session_state に書くと、ctx が無いため "
        "Streamlit のモックに落ちて無言で捨てられる。結果は result dict に入れ、"
        "反映はメインスレッド側で行うこと。"
    )


def test_worker_publishes_result_before_setting_done():
    """メインスレッドは done を見て result を読む → result を先に入れる必要がある。"""
    body = _worker_source()
    assert body.index('prog["result"]') < body.index('prog["done"]   = True'), (
        'done を先に立てると、メインスレッドが result 未設定の状態で読み取り、'
        "結果が空のままプレビューに遷移しうる。"
    )


def test_running_screen_commits_result_on_main_thread():
    """完了時にメインスレッドが result を session_state へ反映し、preview へ遷移する。"""
    text = SRC.read_text(encoding="utf-8")
    assert 'for _k, _v in (_prog.get("result") or {}).items():' in text
    assert 'st.session_state["an_screen"] = "preview"' in text


def test_running_screen_does_not_block_on_cached_matrix():
    """@st.cache_data の topic_matrix_cached をランニング画面から呼ばないこと。

    ミス時に全施設ぶんを同期計算してメインスレッドを数分ブロックし、
    進捗カードが固まったまま動かなくなる（体感は「フリーズ」）。
    """
    text = SRC.read_text(encoding="utf-8")
    assert "_topic_matrix_cached(" not in text
