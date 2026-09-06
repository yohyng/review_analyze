"""「指定競合との比較」で競合を選ばずに実行できてしまう問題の回帰テスト。

v0.53.0 以前:
  1. 施設を選ぶと「🎯 指定競合との比較」が既定で選択済みに見える
  2. 比較施設欄は空のまま実行でき、警告も出ない
  3. 出てくるのは**市場全体比較**のスライド（順位も基準値もDB全施設）
  「競合と比べた資料」のつもりのものが、そうでないまま外に出ていた。

既定の比較施設を入れる行もあったが、app.py が an_peers に [] を必ず
入れるため一度も効いていなかった。復活させるのは誤り —— facility.type は
target/comparison の2値しかなく「どの施設の競合か」を持たないので、
既定は「名前順で先頭5件」にしかならない。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from src import analysis, db
from src.ui import analysis_mode

SRC = Path(analysis_mode.__file__).read_text()


def test_run_button_is_disabled_when_no_peer_is_selected():
    m = re.search(r'key="an_run",?\s*\n?\s*disabled=([^)\n]+)', SRC)
    assert m, "実行ボタンに disabled が付いていない"
    assert "_run_block" in m.group(1), (
        "実行ボタンが競合未選択を見ていない: " + m.group(1)
    )


def test_the_block_reason_is_set_when_competitor_mode_has_no_peers():
    # _run_block が「competitor かつ選択0件」で立つこと
    assert 'if not _selected_peers:' in SRC
    i = SRC.index("if not _selected_peers:")
    tail = SRC[i:i + 420]
    assert "_run_block" in tail, "未選択時に理由が立たない"
    assert "マーケット比較" in tail, "代わりに何を押せばよいか書かれていない"


def test_no_silent_default_peers():
    """既定の比較施設を黙って入れないこと。

    facilities_by_type(conn, "comparison") は ORDER BY name の全件で、
    対象施設との関係を一切持たない。ここから5件を既定にすると、
    無関係な施設を競合として選んだ扱いの資料が黙って出る。
    """
    tree = ast.parse(SRC)
    render = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "render")
    calls = [n for n in ast.walk(render)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "facilities_by_type"]
    assert not calls, (
        "render() が facilities_by_type を既定値に使っている "
        f"(行 {[c.lineno for c in calls]})"
    )


def test_facilities_by_type_really_is_unrelated_to_the_target(tmp_path):
    """上のテストの前提（既定にすると無関係な施設が並ぶ）を実データで示す。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_facility(conn, "対象館", ftype="target")
    for n in ["あ美術館", "い水族館", "う科学館", "え記念館", "お資料館", "近所のライバル館"]:
        db.upsert_facility(conn, n, ftype="comparison")

    got = analysis.facilities_by_type(conn, "comparison")[:5]
    assert "近所のライバル館" not in got, (
        "名前順の先頭5件なので、本当の競合が落ちて無関係な施設が入る: " + str(got)
    )
