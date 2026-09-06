"""解析中画面で「■ 分析を中止する」がオーバーレイの下に隠れないこと。

v0.44.0 でこのボタンを足したが、v0.52.0 まで一度も押せていなかった。
components.loading_card_html() は position:fixed / inset:0 / 不透明背景 の
板を z-index:2147483000 で全面に敷く。ボタンは素直に描くとその**下**に入る。

実ブラウザでの確認（Chromium で elementFromPoint と実クリック）:
    修正前  ボタン y=128, 覆っているのは DIV, クリック失敗
    修正後  ボタン y=773, 覆いなし,          クリック成功

CI に Chromium は入れていないので、ここでは「ボタン側の重なり順が
オーバーレイより必ず上」という、壊れたら押せなくなる条件を固定する。
"""
from __future__ import annotations

import re

from src.ui import analysis_mode, components


def _overlay_z() -> int:
    html = components.loading_card_html(3, "解析中", 1.0)
    m = re.search(r"position:fixed;inset:0;z-index:(\d+)", html)
    assert m, "ローディングのオーバーレイの z-index が読めない"
    return int(m.group(1))


def test_cancel_zone_sits_above_the_loading_overlay():
    assert analysis_mode.CANCEL_ZONE_Z > _overlay_z(), (
        f"中止ボタンの z-index({analysis_mode.CANCEL_ZONE_Z}) が"
        f"オーバーレイ({_overlay_z()}) 以下。ボタンが板の下に入って押せない。"
    )


def test_running_css_actually_floats_the_cancel_zone():
    css = analysis_mode._RUNNING_CSS
    rule = re.search(r"\.st-key-an_cancel_zone\{([^}]*)\}", css)
    assert rule, "中止ボタンを浮かせるルールが CSS から消えている"
    body = rule.group(1)

    # position:fixed でないと、オーバーレイと同じ流れの中に置かれて
    # z-index が効かない（stacking context に入らない）。
    assert "position:fixed" in body
    assert f"z-index:{analysis_mode.CANCEL_ZONE_Z}" in body
    # 画面下部に出す。中央だとローディングカード本体と重なって読めない。
    assert "bottom:" in body


def test_cancel_button_and_caption_share_the_floated_container():
    # ボタンだけを浮かせると、注記（「進んだぶんはDBに残ります」）だけが
    # オーバーレイの下に残って読めなくなる。両方を同じ箱に入れること。
    src = analysis_mode.__file__
    with open(src, encoding="utf-8") as fh:
        body = fh.read()

    m = re.search(r'with st\.container\(key="an_cancel_zone"\):\n(.*?)\n            st\.stop\(\)',
                  body, re.S)
    assert m, "キー付きコンテナ an_cancel_zone が見つからない"
    block = m.group(1)
    assert 'st.button("■ 分析を中止する"' in block
    assert "st.caption(" in block, "注記がコンテナの外にある"
