"""分析画面（ログイン不要）から本番DBを書き換えられないことの回帰テスト。

v0.50.0 以前、プレビュー内の PROFILE 編集パネルには認証チェックが無く、
アプリのURLを知っている人なら誰でも

    db.save_photo / db.upsert_facility / db.delete_photo

を叩けた。手動アップロードした施設写真は「規約上PPTXに載せてよい唯一の
写真」なので、消されると配布物が壊れる。

パネルは render() の深いところにあってクロージャ変数（_bundle, _prof, _fid …）
に依存するため、単体で呼び出せない。ここはソースを構文木として読み、
「書き込みが認証の内側にあること」を構造として固定する。
"""
from __future__ import annotations

import ast
from pathlib import Path

from src.ui import analysis_mode

SRC = Path(analysis_mode.__file__)
TREE = ast.parse(SRC.read_text())

WRITES = {"save_photo", "upsert_facility", "delete_photo",
          "delete_facility", "insert_reviews"}


def _write_calls(node):
    """node 以下にある db.<書き込み系>(...) の呼び出し名を集める。"""
    out = []
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in WRITES
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "db"):
            out.append((n.func.attr, n.lineno))
    return out


def _guards_admin(test) -> bool:
    """if 文の条件が admin_authed を見ているか。"""
    for n in ast.walk(test):
        if isinstance(n, ast.Constant) and n.value == "admin_authed":
            return True
        if isinstance(n, ast.Name) and n.id == "_can_edit":
            return True
    return False


def _render():
    for n in ast.walk(TREE):
        if isinstance(n, ast.FunctionDef) and n.name == "render":
            return n
    raise AssertionError("render() が見つからない")


def test_profile_edit_writes_are_behind_the_admin_gate():
    render = _render()

    # render() 内の db 書き込みを全部拾い、それぞれについて
    # 「admin_authed を見る if の中にあるか」を確かめる。
    guarded_lines = set()
    for node in ast.walk(render):
        if isinstance(node, ast.If) and _guards_admin(node.test):
            for _, lineno in _write_calls(node):
                guarded_lines.add(lineno)

    all_writes = _write_calls(render)
    assert all_writes, "書き込みが1つも見つからない（テストの前提が壊れている）"

    unguarded = [(name, ln) for name, ln in all_writes if ln not in guarded_lines]
    assert not unguarded, (
        "分析画面から未認証で叩ける DB 書き込みがある: "
        + ", ".join(f"db.{n}() @ {SRC.name}:{ln}" for n, ln in unguarded)
    )


def test_edit_panel_itself_checks_auth_not_just_the_entry_button():
    # _ekey は session_state に残るので、入口だけを塞いでも
    # 「編集中にログアウト」でパネルが開いたままになる。
    src = SRC.read_text()
    assert "_can_edit = bool(st.session_state.get(\"admin_authed\"))" in src
    assert "if _can_edit and st.session_state.get(_ekey):" in src, (
        "パネル本体が _can_edit を見ていない"
    )
