"""生HTMLの入口（src/ui/markup.py）。

ここは2つの事故の交差点なので、両方を同時に踏まないことを見張る。

  1. Markdown が HTML を壊す
     空行で HTML ブロックが終わる／4スペース字下げがコードブロック扱い。
     v0.55.0 で <style> が 6,049文字中 2,113文字で切れた。

  2. st.html が SVG を丸ごと落とす
     v0.56.0 で 1 を避けようと 68箇所を st.html に寄せた結果、
     レーダーチャートと時間軸の棒グラフが**全部消えた**。
     隣の <span>（マーカー）は残るので「HTMLは出るのにグラフだけ無い」
     という形で出て、気づきにくい。

  → 1行に潰してから st.markdown に渡す、で両方を外す。
"""
from __future__ import annotations

from src.ui import markup


# --------------------------------------------------------------------------- #
# flatten
# --------------------------------------------------------------------------- #
def test_blank_lines_are_removed():
    """空行が残ると、そこで HTML ブロックが終わる。"""
    out = markup.flatten("<style>\n\n.a{color:red}\n\n</style>\n<div>x</div>")
    assert "\n" not in out
    assert out == "<style> .a{color:red} </style> <div>x</div>"


def test_leading_indent_is_removed():
    """4スペース字下げはコードブロックの記法と衝突する。"""
    out = markup.flatten("    <div>\n        <span>x</span>\n    </div>")
    assert not out.startswith(" ")
    assert "\n" not in out
    assert out == "<div> <span>x</span> </div>"


def test_flatten_keeps_the_content():
    """潰すのは改行まわりの空白だけ。中身は落とさない。"""
    src = "<svg><rect x='1' y='2'/></svg>"
    assert markup.flatten(src) == src

    big = "<style>\n" + "\n\n".join(f".r{i}{{color:#{i:06d}}}" for i in range(300)) + "\n</style>"
    out = markup.flatten(big)
    assert ".r0{" in out and ".r299{" in out      # 先頭も末尾も残る
    assert "\n" not in out


def test_flatten_tolerates_empty():
    assert markup.flatten("") == ""
    assert markup.flatten(None) == ""


# --------------------------------------------------------------------------- #
# html()
# --------------------------------------------------------------------------- #
class _Target:
    def __init__(self, has_html: bool = True):
        self.markdown_calls: list = []
        self.html_calls: list = []
        if has_html:
            self.html = self.html_calls.append

    def markdown(self, s, **kw):
        self.markdown_calls.append((s, kw))


def test_html_never_uses_st_html():
    """st.html は SVG を落とす。使わないこと。"""
    t = _Target(has_html=True)
    markup.html("<svg><circle r='1'/></svg>", into=t)
    assert t.html_calls == []
    assert len(t.markdown_calls) == 1


def test_html_asks_markdown_for_raw_html():
    t = _Target()
    markup.html("<div>\n  <b>x</b>\n</div>", into=t)
    (sent, kw), = t.markdown_calls
    assert kw == {"unsafe_allow_html": True}
    assert sent == "<div> <b>x</b> </div>"


def test_svg_reaches_the_page_intact():
    """グラフの素（rect/polyline/polygon/line）が1つも落ちないこと。"""
    t = _Target()
    markup.html(
        "<svg viewBox='0 0 100 100'>\n"
        "  <line x1='0' y1='50' x2='100' y2='50'/>\n"
        "\n"
        "  <rect x='10' y='20' width='20' height='30'/>\n"
        "  <polyline points='0,80 30,20'/>\n"
        "  <polygon points='70,70 90,70 80,90'/>\n"
        "</svg>", into=t)
    sent = t.markdown_calls[0][0]
    for tag in ("<svg", "<line", "<rect", "<polyline", "<polygon"):
        assert tag in sent, tag


def test_every_call_site_goes_through_markup():
    """スライドを直接 st.html に渡す経路を作らないこと（SVGが消える）。"""
    import pathlib

    for p in pathlib.Path("src").rglob("*.py"):
        if p.name == "markup.py":
            continue
        src = p.read_text(encoding="utf-8")
        assert "st.html(" not in src, f"{p}: st.html は SVG を落とす"
