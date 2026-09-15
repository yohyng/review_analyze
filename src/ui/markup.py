"""生HTMLの入口。

他の ui モジュールから広く呼ぶので、依存を持たせないこと
（components が theme を、theme が components を要るようになると循環する）。
"""
from __future__ import annotations

import re

# 改行を含む空白の連なり。1個の空白に潰す。
_NEWLINE_RUN = re.compile(r"\s*\n\s*")


def flatten(markup: str) -> str:
    """HTML を1行にする。**Markdown に壊されないための前処理**。

    Markdown が HTML を壊すのは、行の形に意味があるからだけ:
      - 空行があると、CommonMark ではそこで HTML ブロックが終わる。
        以降は捨てられるか、文字として出る（v0.55.0 で <style> が
        6,049文字中 2,113文字で切れていたのがこれ）。
      - 4スペース字下げはコードブロックの記法と衝突する。

    どちらも「改行が無ければ起きない」。1行に潰してしまえば、
    先頭の `<` から末尾まで丸ごと HTML ブロックとして素通りする。

    HTML では改行はただの空白なので、潰しても見た目は変わらない
    （`<pre>` や white-space:pre を使っていないことが前提。現状は0箇所）。
    """
    return _NEWLINE_RUN.sub(" ", markup or "").strip()


def html(markup: str, *, into=None) -> None:
    """生HTMLを描く。

    **st.html() を使わないこと**。あれは SVG を丸ごと落とす。

      実測（Streamlit 1.58 / 同じ文字列を両経路に流して DOM を数えた）:
        st.html()                        → svg 0 / line 0 / rect 0 / polyline 0
        st.markdown(unsafe_allow_html=True) → svg 1 / line 1 / rect 1 / polyline 1
      隣に置いた <span> はどちらでも残るので、**HTMLは出るのにグラフだけ
      消える**という形で出る。v0.56.0 で 68箇所を st.html に寄せた際、
      レーダーチャートと時間軸の棒グラフが全部消えていた。

    st.html に寄せた理由（Markdown が HTML を壊す）は flatten() で潰す。
    行の形に意味を持たせない限り、Markdown 経路でも壊れない。

    into に st.empty() などのプレースホルダを渡すと、そこへ描く。
    """
    import streamlit as st  # noqa: PLC0415

    target = st if into is None else into
    target.markdown(flatten(markup), unsafe_allow_html=True)
