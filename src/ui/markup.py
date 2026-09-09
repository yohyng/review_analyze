"""生HTMLの入口。Markdown を通さない。

他の ui モジュールから広く呼ぶので、依存を持たせないこと
（components が theme を、theme が components を要るようになると循環する）。
"""
from __future__ import annotations


def html(markup: str, *, into=None) -> None:
    """生HTMLを描く。**Markdown を通さない**。

    st.markdown(..., unsafe_allow_html=True) は、渡した文字列をまず Markdown
    として解釈してから HTML にする。そのため書き方しだいで壊れる:

      - 空行があると、CommonMark ではそこで HTML ブロックが終わる。以降は
        「HTMLではない段落」と見なされて捨てられるか、文字として出る。
        実際 v0.55.0 で <style> が 6,049文字中 2,113文字で切れていた。
      - 4スペース字下げはコードブロックの記法と衝突する。

    st.html() は Markdown 解釈を挟まずそのまま流すので、この手の事故が
    構造的に起きない。CSS もレイアウトも Markdown 記法を意図していないので、
    こちらが正しい入口。

    into に st.empty() などのプレースホルダを渡すと、そこへ描く。

    st.html は Streamlit 1.33 で入った。それ以前でも動くよう従来の経路へ
    落とす（requirements は 1.58.0 固定だが、デプロイ先が違うことがある）。
    """
    import streamlit as st  # noqa: PLC0415

    target = st if into is None else into
    fn = getattr(target, "html", None)
    if fn is not None:
        fn(markup)
    else:
        target.markdown(markup, unsafe_allow_html=True)
