"""分析レポートのスライド描画（HTML）。

**デザインの正典は design_handoff_voicebaum**
  - `README.md` §2〜§4（トークン・レイアウト・チャート仕様）
  - `ReviewLens.dc.html`（動くリファレンス実装）

色・書体・寸法は src/report_theme.py のトークンを使い、値を直接書かない。
サイズは cqw（コンテナ幅に対する%）で持つので、どの幅で描いても同じ比率になる。
1枚は `canvas(header, body, foot)`：ヘッダーだけがフローに乗り、本文（body_area）と
フッターは絶対配置。中身が増えてもフッター位置がずれない。

番号タイルの数字は「章番号」であって通し番号ではない
（1 / 2 / 2 / 3 / 3 / 4 / 5 / 5 / 6 / 7。正典も詳細ページは親と同じ番号を出す）。

見た目の確認は `python3 scripts/render_slides.py` で PNG に書き出す。
"""
from __future__ import annotations

from html import escape

from . import report_theme as T


# ═══════════════════════════════════════════════════════════════════════════
# プリミティブ
# ═══════════════════════════════════════════════════════════════════════════
def canvas(header: str, body: str, foot: str) -> str:
    """1枚のスライド。container-type:inline-size で cqw を効かせる。

    ヘッダーだけがフローに乗り、本文とフッターは絶対配置（正典の組み方）。
    こうしておくと本文の中身が増えてもフッターの位置がずれない。
    """
    return (
        f'<div class="vb-cv" style="position:relative;width:100%;aspect-ratio:{T.ASPECT_RATIO};'
        f'background:{T.PAGE_BG};border:1px solid {T.CARD_LINE};'
        f'border-radius:{T.SLIDE_RADIUS};overflow:hidden;container-type:inline-size;'
        f'box-shadow:{T.SLIDE_SHADOW};font-family:{T.FONT_STACK};color:{T.INK};'
        'font-variant-numeric:tabular-nums;text-wrap:pretty;margin:0 0 22px;">'
        f'{TOOLTIP_CSS}{header}{body}{foot}</div>'
    )


def body_area(inner: str, *, top: float = T.BODY_TOP, column: bool = False,
              gap: float = 1.4) -> str:
    """本文エリア。left/right:2cqw・top:6.9〜7.4cqw・bottom:4.6cqw（README §2）。"""
    return (
        f'<div style="position:absolute;left:{T.BODY_X}cqw;right:{T.BODY_X}cqw;'
        f'top:{top}cqw;bottom:{T.BODY_BOTTOM}cqw;display:flex;'
        f'flex-direction:{"column" if column else "row"};gap:{gap}cqw;">'
        f'{inner}</div>'
    )


def _pill(text: str) -> str:
    """ヘッダー右のピンクの丸ピル（「プランナー起点」）。"""
    return (
        f'<span style="background:{T.ACCENT};color:#fff;font-size:1.32cqw;'
        'font-weight:700;padding:.5cqw 1.4cqw;border-radius:999px;'
        f'white-space:nowrap;">{escape(text)}</span>'
    )


def _outline_tag(text: str) -> str:
    """ヘッダー右の白抜きタグ（「confidential」）。"""
    return (
        f'<span style="border:1.5px solid {T.ACCENT};color:{T.ACCENT};background:#fff;'
        'font-size:1.32cqw;font-weight:700;padding:.4cqw 1.2cqw;border-radius:.3cqw;'
        f'white-space:nowrap;">{escape(text)}</span>'
    )


def slide_header(num: str, title: str, meta: str = "", sub_title: str = "",
                 right: str = "") -> str:
    """紺帯のヘッダー。左端にピンクの正方形タイル、右端に補足。

    寸法は README §2：帯 6.3cqw ／ タイル 6.3cqw 正方・数字 2.7cqw/800 ／
    タイトル 2.3cqw/800 ／ 右の補足 1.05cqw/600。
    """
    right_html = right or (
        f'<span style="color:#fff;font-size:{T.FS["slide_meta"]}cqw;font-weight:600;'
        f'white-space:nowrap;">{escape(meta)}</span>'
        if meta else "<span></span>"
    )
    sub_html = (
        f'<span style="font-size:{T.FS["slide_title"] * 0.62:.2f}cqw;font-weight:700;">'
        f'（{escape(sub_title)}）</span>'
        if sub_title else ""
    )
    return (
        f'<div style="display:flex;align-items:stretch;height:{T.HEADER_H}cqw;'
        f'background:{T.NAVY};">'
        f'<div style="width:{T.TILE_W}cqw;flex:none;background:{T.ACCENT};'
        'display:flex;align-items:center;justify-content:center;color:#fff;'
        f'font-size:{T.FS["slide_num"]}cqw;font-weight:800;">{escape(num)}</div>'
        '<div style="flex:1;display:flex;align-items:center;'
        'justify-content:space-between;gap:1.4cqw;padding:0 2cqw;min-width:0;">'
        f'<span style="color:#fff;font-size:{T.FS["slide_title"]}cqw;font-weight:800;'
        'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
        f'{escape(title)}{sub_html}</span>'
        f'{right_html}</div></div>'
    )


def panel(title: str, body: str, *, icon: str = "", note: str = "",
          style: str = "flex:1", pad: str = "1cqw", gap: str = "0",
          head_size: float | None = None) -> str:
    """紺の見出し帯＋白い本文のカード。

    見出しは README §2 の「高さ約3cqw・1.35cqw/700・背景 #17224B・白・中央寄せ」。
    アイコンや注記を添えるときだけ左寄せにする（正典もその使い分け）。
    """
    fs = T.FS["panel_head"] if head_size is None else head_size
    icon_html = f'<span style="font-size:1.2cqw;">{icon}</span>' if icon else ""
    note_html = (
        f'<span style="margin-left:auto;font-size:{T.FS["note"]}cqw;font-weight:400;'
        f'opacity:.85;white-space:nowrap;">{escape(note)}</span>'
        if note else ""
    )
    head_layout = (
        "display:flex;align-items:center;gap:.7cqw;"
        if (icon_html or note_html) else "text-align:center;"
    )
    return (
        f'<div style="{style};min-width:0;display:flex;flex-direction:column;'
        f'border:1px solid {T.CARD_LINE};border-radius:{T.CARD_RADIUS};'
        'overflow:hidden;background:#fff;">'
        f'<div style="flex:none;background:{T.NAVY};color:#fff;font-size:{fs}cqw;'
        f'font-weight:700;padding:.85cqw 1.2cqw;{head_layout}">'
        f'{icon_html}{escape(title)}{note_html}</div>'
        f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;'
        f'padding:{pad};gap:{gap};">'
        f'{body}</div></div>'
    )


def footer(note: str = "", tagline: str = "") -> str:
    """Voice(#E8386A) BAUM(#17224B) のワードマーク＋右に注記。

    README §2：`1.5cqw/800`、上罫 `1px #EDEFF3`。スライド下端 1.1cqw に絶対配置。
    """
    tag = (
        f'<span style="font-size:{T.FS["note"]}cqw;color:{T.INK_FAINT};'
        f'white-space:nowrap;">{escape(tagline)}</span>'
        if tagline else ""
    )
    return (
        f'<div style="position:absolute;left:{T.BODY_X}cqw;right:{T.BODY_X}cqw;'
        f'bottom:{T.FOOTER_BOTTOM}cqw;display:flex;align-items:center;'
        f'justify-content:space-between;gap:1cqw;border-top:1px solid {T.LINE};'
        'padding-top:.9cqw;">'
        '<span style="display:flex;align-items:baseline;gap:1cqw;min-width:0;">'
        f'<span style="font-size:{T.FS["footer_mark"]}cqw;font-weight:800;'
        f'white-space:nowrap;"><span style="color:{T.ACCENT};">Voice</span> '
        f'<span style="color:{T.NAVY};">BAUM</span></span>{tag}</span>'
        f'<span style="font-size:{T.FS["note"]}cqw;color:{T.INK_FAINT};'
        f'text-align:right;">{escape(note)}</span></div>'
    )


def vertical_text(s: str, *, size: float, color: str | None = None,
                  weight: int = 400) -> str:
    """縦書きテキスト。1文字ずつ積んで描く。

    CSS の writing-mode:vertical-rl は、環境によっては和文フォントに縦書き
    メトリクスが無く漢字が同じ位置に重なってしまう（headless Chromium で再現）。
    レポートはどの環境でも同じ見えでなければならないので、フォント任せにせず
    自前で積む。長音符など横倒しが必要な字だけ回転させる。

    ※ X軸ラベルには使わない（README §3 が -90°/-62° の回転を指定しているので
       tilted_axis_labels を使う）。散布図の軸見出しなど、真の縦組みだけに使う。
    """
    rotate = {"ー", "－", "-", "〜", "～", "―", "‐"}
    col = color or T.INK
    cells = "".join(
        f'<div style="height:{size * 1.06:.2f}cqw;line-height:{size * 1.06:.2f}cqw;'
        + ("transform:rotate(90deg);" if ch in rotate else "")
        + f'">{escape(ch)}</div>'
        for ch in s
    )
    return (
        f'<div style="font-size:{size}cqw;color:{col};font-weight:{weight};'
        f'text-align:center;">{cells}</div>'
    )


# --------------------------------------------------------------------------- #
# グラフの座標系
#
#   以前、y軸の上限を「mx/4 を切り下げて桁で丸める」で決めていたため、
#   上限がデータの最大値より小さくなることがあった（例: 累計457件 → 上限400）。
#   すると y 座標が負になり、折れ線がプロット領域の上へ突き抜けてカードから
#   はみ出す。13通り試して8通りで再現した。
#
#   同じ壊れ方を二度としないよう、ここに2重の歯止めを置く:
#     nice_axis() … top >= mx を必ず満たす目盛りを返す
#     plot_y()    … それでも範囲外の値が来たら 0..100 内へ丸める
#   さらに描画側の SVG は overflow:hidden にして、構造的に外へ出られなくする。
# --------------------------------------------------------------------------- #
PLOT_PAD_TOP = 4.0        # 線幅とマーカー半径ぶんの余白（viewBox 単位）
PLOT_PAD_BOTTOM = 2.0

_NICE_STEPS = (1.0, 2.0, 2.5, 5.0)


def nice_axis(mx: float, max_ticks: int = 5) -> tuple[list[float], float]:
    """0 から始まる「切りのいい」目盛りと上限を返す。

    **上限は必ず mx 以上**。そのうえで、いちばん詰まって収まる刻みを選ぶ
    （上限が同じなら目盛りが多いほうを採る）。

    >>> nice_axis(457)[1]
    500.0
    >>> nice_axis(55)[1]
    60.0
    """
    import math

    if not mx or mx <= 0:
        return [0.0, 1.0], 1.0

    exp = math.floor(math.log10(mx))
    best: tuple[float, float, int] | None = None      # (top, step, k)
    for e in range(exp - 2, exp + 2):
        for m in _NICE_STEPS:
            step = m * (10.0 ** e)
            if step <= 0:
                continue
            k = math.ceil(mx / step - 1e-9)           # 必要な区間数
            if not (2 <= k <= max_ticks):
                continue
            top = step * k
            if best is None or (top, -k) < (best[0], -best[2]):
                best = (top, step, k)

    if best is None:                                   # 理論上来ないが保険
        return [0.0, float(mx)], float(mx)
    top, step, k = best
    return [step * i for i in range(k + 1)], top


def plot_y(v: float, top: float, *, bottom: float = 0.0) -> float:
    """値を viewBox の y 座標（0..100）へ。範囲外は端で止める。

    軸の計算を間違えても、描画がカードの外へ出ないための最後の歯止め。
    """
    span = (top - bottom) or 1.0
    r = (v - bottom) / span
    r = 0.0 if r < 0 else (1.0 if r > 1 else r)
    usable = 100.0 - PLOT_PAD_TOP - PLOT_PAD_BOTTOM
    return PLOT_PAD_TOP + (1.0 - r) * usable


def _fmt_tick(v: float) -> str:
    """目盛りの数字。件数のような整数は小数点を出さない（60.0 ではなく 60）。"""
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.1f}"


def plot_dots(pts: list[tuple[float, float]], *, size: float, color: str,
              hollow: bool = False, ring: float = 0.16) -> str:
    """折れ線のマーカー。**必ず真円**になる描き方で置く。

    グラフの SVG は preserveAspectRatio="none" で縦横に別々の倍率で伸ばして
    いるので、中に <circle> を描くと縦横比のぶんだけ潰れて楕円になる。
    マーカーだけは HTML の絶対配置（幅も高さも cqw）で置き、
    SVG のスケーリングから切り離す。

    pts は (x%, y%) のリスト。size は直径（cqw）。
    """
    fill = "#fff" if hollow else color
    return "".join(
        f'<span style="position:absolute;left:{x:.2f}%;top:{y:.2f}%;'
        f'transform:translate(-50%,-50%);width:{size}cqw;height:{size}cqw;'
        f'border-radius:50%;background:{fill};'
        f'border:{ring}cqw solid {color};box-sizing:border-box;"></span>'
        for x, y in pts
    )


# --------------------------------------------------------------------------- #
# ツールチップ（軸の説明をホバーで出す）
#
#   Streamlit の st.markdown(unsafe_allow_html=True) は <script> を落とすので、
#   **CSS だけ**で作る（:hover で子要素を出す）。JS は使えないし要らない。
#
#   スライドの枠は overflow:hidden なので、外側へ出す向きを間違えると
#   吹き出しが切れる。place で内側へ逃がす。
#     "up"    … ラベルの上に出す（X軸ラベル＝下端にあるもの向け）
#     "down"  … 下に出す（上端にあるもの向け）
#     "right" / "left" … 横に出す（左右の軸ラベル向け）
# --------------------------------------------------------------------------- #
def _topic_index(name: str) -> int | None:
    """観点名 → 通し番号。:has() の相互ハイライト用の CSS 安全な識別子。

    日本語の観点名は属性セレクタに直接書けなくはないが、生成した CSS に
    ユーザー由来ではない固定文字列とはいえ日本語を大量に埋めると読みづらい。
    DEFAULT_TOPICS の並び順は安定しているので番号で引く。
    """
    from . import topic_score  # noqa: PLC0415

    for i, t in enumerate(topic_score.DEFAULT_TOPICS):
        if t.name == name:
            return i
    return None


def _highlight_rules() -> str:
    """同じ観点を指す要素どうしを、ホバー/フォーカスで結ぶ CSS。

    1枚のスライドの中に、同じ観点が「レーダーの軸」「ヒートマップの行」
    「強みTOP3」と何度も出てくる。片方を指したときにもう片方が光れば、
    3枚の別々の図ではなく1つの図として読める。

    :has() は実測で Streamlit 経由でも効く（probe 済み）。
    起点を .vb-cv（スライド1枚）に取るので、隣のスライドには波及しない。
    """
    from . import topic_score  # noqa: PLC0415

    out = []
    for i in range(len(topic_score.DEFAULT_TOPICS)):
        out.append(
            f'.vb-cv:has([data-t="{i}"]:hover) [data-t="{i}"],'
            f'.vb-cv:has([data-t="{i}"]:focus-visible) [data-t="{i}"]'
            f'{{background:{T.ACCENT_SOFT};border-radius:.3cqw;'
            f'box-shadow:0 0 0 .18cqw {T.ACCENT};}}'
        )
    return "".join(out)


def _css_min(css: str) -> str:
    """CSS を1行に潰す。**空行とコメントを残すと途中で切れる**。

    st.markdown は文字列を先に Markdown として解釈する。CommonMark では
    空行が HTML ブロックの終わりなので、空行を挟むと以降は「HTML では
    ない段落」と見なされて捨てられる。実測では 6,049 文字の <style> が
    2,113 文字で切れ、:has() の相互ハイライトと .vb-unmeasured が丸ごと
    消えていた（前半だけ効くので気づきにくい）。

    ついでに 1枚あたり数KBの重複も減る（CSS は 11枚それぞれに入るため）。
    """
    out = []
    for line in css.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(line)
    txt = " ".join(out)
    # /* ... */ を落とす（複数行にまたがるものも1行化済みなので単純に取れる）
    while "/*" in txt and "*/" in txt:
        a = txt.index("/*")
        b = txt.index("*/", a) + 2
        txt = txt[:a] + txt[b:]
    return " ".join(txt.split())


_TOOLTIP_CSS_SRC = f"""
<style>
/* ── ホバー/タップで出る根拠カード ──────────────────────────────── */
.vb-tip{{position:relative;cursor:help;border-bottom:1px dotted {T.INK_FAINT};}}
/* tabindex を付けた要素のブラウザ既定の枠は自前の指示子に置き換える */
.vb-tip:focus{{outline:none;}}
.vb-tip:focus-visible{{outline:.18cqw solid {T.ACCENT};outline-offset:.15cqw;}}
.vb-tip>.vb-tipbody{{
  visibility:hidden;opacity:0;transition:opacity .12s;
  position:absolute;z-index:60;width:16cqw;
  background:{T.NAVY};color:#fff;border-radius:.5cqw;
  padding:.7cqw .9cqw;font-size:.95cqw;font-weight:500;line-height:1.5;
  text-align:left;white-space:normal;
  box-shadow:0 .3cqw 1.2cqw rgba(20,30,40,.28);
}}
/* hover はマウスだけのもの。タブレットとキーボードには focus で届かせる。 */
.vb-tip:hover>.vb-tipbody,
.vb-tip:focus>.vb-tipbody,
.vb-tip:focus-within>.vb-tipbody{{visibility:visible;opacity:1;}}
.vb-tip>.vb-tipbody.up{{bottom:calc(100% + .5cqw);left:50%;transform:translateX(-50%);}}
.vb-tip>.vb-tipbody.down{{top:calc(100% + .5cqw);left:50%;transform:translateX(-50%);}}
.vb-tip>.vb-tipbody.right{{left:calc(100% + .5cqw);top:50%;transform:translateY(-50%);}}
.vb-tip>.vb-tipbody.left{{right:calc(100% + .5cqw);top:50%;transform:translateY(-50%);}}
/* 端のラベルは中央寄せだと枠を抜けるので、ラベル側の辺に合わせる */
.vb-tip>.vb-tipbody.up-l{{bottom:calc(100% + .5cqw);left:0;transform:none;}}
.vb-tip>.vb-tipbody.up-r{{bottom:calc(100% + .5cqw);right:0;left:auto;transform:none;}}
.vb-tip>.vb-tipbody.down-l{{top:calc(100% + .5cqw);left:0;transform:none;}}
.vb-tip>.vb-tipbody.down-r{{top:calc(100% + .5cqw);right:0;left:auto;transform:none;}}
.vb-tipkw{{display:block;margin-top:.4cqw;color:{T.LAUREL};font-size:.85cqw;}}

/* ── 根拠の明細（スコア / 基準 / 言及量）────────────────────────── */
.vb-tipname{{display:block;font-weight:800;font-size:1.02cqw;margin-bottom:.15cqw;}}
.vb-tiprule{{display:block;height:1px;background:rgba(255,255,255,.22);
  margin:.5cqw 0 .45cqw;}}
.vb-tipfact{{display:flex;justify-content:space-between;gap:.6cqw;
  font-size:.9cqw;line-height:1.55;}}
.vb-tipfact>i{{font-style:normal;color:rgba(255,255,255,.66);flex:0 0 auto;}}
.vb-tipfact>b{{font-weight:700;text-align:right;}}
.vb-tipwarn{{display:block;margin-top:.45cqw;font-size:.85cqw;
  color:{T.STAR};font-weight:700;}}

/* ── 言及が下限を割る（＝実質測れていない）観点の静的な指示子 ──────
   ホバーしないと分からない情報にはしない。スクショにも印刷にも残る。 */
.vb-unmeasured{{opacity:.55;}}

/* ── 同じ観点どうしの相互ハイライト（:has()）──────────────────── */
{_highlight_rules()}
</style>
"""

TOOLTIP_CSS = _css_min(_TOOLTIP_CSS_SRC)


def _fact(label: str, value: str) -> str:
    return f'<span class="vb-tipfact"><i>{escape(label)}</i><b>{escape(value)}</b></span>'


def tooltip(label: str, desc: str, *, place: str = "up",
            keywords: list[str] | None = None) -> str:
    """ホバーで説明が出るラベル。desc が空ならただのテキストを返す。

    keywords を渡すと「この語を数えている」を併記する。スコアが何で
    できているのかは、この資料でいちばん聞かれるところなので。
    """
    if not desc:
        return escape(label)
    kw = (f'<span class="vb-tipkw">拾う語: '
          f'{escape("・".join(keywords[:8]))}</span>' if keywords else "")
    return (
        f'<span class="vb-tip" tabindex="0">{escape(label)}'
        f'<span class="vb-tipbody {place}">{escape(desc)}{kw}</span></span>'
    )


def topic_attrs(name: str, b: dict | None = None, *, extra: str = "") -> str:
    """観点を指す要素に付ける共通属性。

    - class="vb-tip"      … 吹き出しの器
    - tabindex="0"        … タップ・キーボードでも吹き出しに届かせる
    - data-t="{番号}"     … 同じ観点どうしの相互ハイライト（:has()）の目印
    - class="vb-unmeasured" … 言及が下限を割る観点（静的に薄く出す）
    """
    cls = "vb-tip" + (f" {extra}" if extra else "")
    if b is not None and _is_unmeasured(name, b):
        cls += " vb-unmeasured"
    idx = _topic_index(name)
    attr = f' data-t="{idx}"' if idx is not None else ""
    return f'class="{cls}" tabindex="0"{attr}'


def topic_tooltip(name: str, *, place: str = "up", b: dict | None = None) -> str:
    """観点名を、その定義と根拠付きで返す。

    b（bundle）を渡すと、定義だけでなく「スコア / 基準との差 / 言及量」
    まで出す。客先で必ず聞かれる「その数字どこから出てるの」に一手で
    答えるため。渡さなければ従来どおり定義だけ。
    """
    body = _topic_tip_body(name, place, b)
    if not body:
        return escape(name)
    return f'<span {topic_attrs(name, b)}>{escape(name)}{body}</span>'


def _mentions(name: str, b: dict) -> int | None:
    """その観点に触れたとみなせる文の数。分からなければ None。"""
    sal = (b.get("topic_salience") or {}).get(name)
    if sal is None:
        return None
    n_sent = b.get("n_sentences") or 0
    return round(n_sent * sal / 100) if n_sent else 0


def _is_unmeasured(name: str, b: dict) -> bool:
    """静的に薄く出す観点＝**言及が1文も無い**もの。

    ここは誤検知を出せない。スクショにも PPTX にも残る表示で、しかも
    「この数字は読むな」と言うに等しいため。だから閾値を置かず、
    推定言及数が 0 のときだけにする。

    「平均より下」を基準にしてはいけない。salience は平均トピック確率で
    Σ=1 なので、平均はちょうど 1/観点数。それを下回る観点は定義上ほぼ
    半分あり、スライドの半分が灰色になる（一度そう書いて気づいた）。
    平均前後の観点への注意喚起は吹き出しの中だけで行う（_is_thin）。
    """
    n = _mentions(name, b)
    return n == 0


def _is_thin(name: str, b: dict) -> bool:
    """言及が「情報が無いときの水準」以下か＝吹き出しでだけ注意を出す。

    トピック確率は、どの観点にも当たらない文では一様（1/観点数）に配られる。
    そこを超えていない観点は「その観点に触れた証拠が無い」に等しい。
    較正はそういう観点にも施設全体の平均感情を配ってしまうので、強み/弱み
    として読むと事故になる。ただし定義上おおよそ半数が該当するので、
    静的な見た目は変えず、根拠カードの中でだけ伝える。
    """
    sal = (b.get("topic_salience") or {}).get(name)
    floor = b.get("salience_floor") or 0.0
    return sal is not None and floor > 0 and sal <= floor


def _topic_tip_body(name: str, place: str, b: dict | None = None) -> str:
    """観点の吹き出しの中身（ラベル本体は呼び出し側が描く）。"""
    from . import topic_score  # noqa: PLC0415

    d = next((t for t in topic_score.DEFAULT_TOPICS if t.name == name), None)
    if not d or not getattr(d, "desc", ""):
        return ""

    head = f'<span class="vb-tipname">{escape(name)}</span>'
    desc = escape(d.desc)
    kw = (f'<span class="vb-tipkw">拾う語: '
          f'{escape("・".join(d.keywords[:8]))}</span>')

    facts = ""
    if b is not None:
        facts = _topic_facts(name, b)

    return f'<span class="vb-tipbody {place}">{head}{desc}{kw}{facts}</span>'


def _topic_facts(name: str, b: dict) -> str:
    """スコア・基準・言及量の明細。bundle に無いものは黙って省く。"""
    rows = ""

    scores = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))
    tv = scores.get(name)
    if tv is not None:
        rows += _fact("スコア", f"{tv / 20:.2f} / 5")

    base = (b.get("overall_topic") or {}).get(name)
    if tv is not None and base is not None:
        lbl = b.get("baseline_label") or "基準"
        rows += _fact(lbl, f"{base / 20:.2f}（{(tv - base) / 20:+.2f}）")

    sal = (b.get("topic_salience") or {}).get(name)
    if sal is not None:
        n_sent = b.get("n_sentences") or 0
        hit = _mentions(name, b) or 0
        rows += _fact("言及", f"{hit:,}文 / {n_sent:,}文（{sal:.1f}%）")

    if not rows:
        return ""

    warn = ""
    if _is_unmeasured(name, b):
        warn = ('<span class="vb-tipwarn">'
                'この観点に触れた口コミがありません。'
                'スコアは全体の平均から埋めた値なので、'
                '強み・弱みとして読まないでください。</span>')
    elif _is_thin(name, b):
        warn = ('<span class="vb-tipwarn">'
                '言及が少なく、他の観点と比べられる水準にありません。'
                '参考値として扱ってください。</span>')
    return f'<span class="vb-tiprule"></span>{rows}{warn}'


def _tip_dir(lx: float, ly: float, cx: float, cy: float) -> str:
    """円周上のラベルから、吹き出しを**中心側**へ出す向きを選ぶ。

    上下の端で左右に出すと作図枠を横に抜け、カード（overflow:hidden）に
    切られる。縦に逃がし、さらに左右の端では寄せ方も内側へ倒す。
    """
    # 横に逃がすのが基本（円の外側ではなく、中心側に空きがある）。
    # 真上・真下のラベルだけは横に空きが無いので縦に逃がす。
    if abs(lx - cx) < 12:
        return "down" if ly < cy else "up"
    return "right" if lx < cx else "left"


def tilted_axis_labels(labels: list[str], xs: list[float], *, deg: float,
                       size: float, color: str | None = None,
                       prefix: list[str] | None = None,
                       tips: bool = False, b: dict | None = None) -> str:
    """X軸の傾いたラベル（README §3：独自指標 -90°／19指標比較 -62°）。

    右端を軸の目盛りに合わせて、そこを支点に反時計回りへ倒す。
    """
    col = color or T.INK
    out = ""
    for i, (t, px) in enumerate(zip(labels, xs)):
        head = (f'{prefix[i]} ' if prefix and i < len(prefix) else "")
        place = "up-l" if px < 25 else ("up-r" if px > 75 else "up")
        body = _topic_tip_body(t, place, b) if tips else ""
        # 吹き出しは付けられない（-62°回転を子が継承して枠を抜ける）が、
        # data-t だけは付けられる。同じスライドのヒートマップの指標名と
        # 結びついて、どちらかを指すともう片方が光る。
        # 「この指標、グラフのどれ？」を目で追わずに済む。
        cls = ' class="vb-tip"' if body else ""
        if b is not None and not body:
            idx = _topic_index(t)
            if idx is not None:
                mark = " vb-unmeasured" if _is_unmeasured(t, b) else ""
                cls = f' class="vb-xlab{mark}" data-t="{idx}"'
        out += (
            f'<div{cls} style="position:absolute;left:{px:.2f}%;top:0;'
            f'transform:translateX(-100%) rotate({-abs(deg):.0f}deg);'
            f'transform-origin:100% 0;font-size:{size}cqw;color:{col};'
            f'white-space:nowrap;">{escape(head + t)}{body}</div>'
        )
    return out


def score_note(b: dict) -> str:
    """スコアが何を意味するかの注記。較正の有無で言い方を変える。

    較正時は 3.00 が市場平均を指す相対値なので、絶対的な品質評価と
    誤読されないよう必ずその旨を書く。
    """
    if b.get("score_calibrated"):
        return ("※スコアは5点満点（3.00＝市場平均）。"
                "同カテゴリ施設の分布内での相対位置を示します")
    return "※スコアは5点満点。口コミ本文から算出した感情スコアです"


def _photo(uri: str | None, ratio: str = "16/10", radius: str = ".7cqw",
           height: str = "") -> str:
    """写真スロット。height を渡すとその高さで固定する（正典は 15cqw 固定）。"""
    box = (f"height:{height};flex:none;" if height else f"aspect-ratio:{ratio};")
    if uri:
        return (
            f'<div style="width:100%;{box}border-radius:{radius};'
            f'overflow:hidden;background:{T.TABLE_HEAD};">'
            f'<img src="{uri}" style="width:100%;height:100%;object-fit:cover;'
            'display:block;" /></div>'
        )
    return (
        f'<div style="width:100%;{box}border-radius:{radius};'
        f'background:{T.TABLE_HEAD};display:flex;align-items:center;'
        f'justify-content:center;color:{T.INK_FAINT};font-size:1.22cqw;">写真なし</div>'
    )


def _stars(rating: float | None, size: float = 1.7) -> str:
    """★を5つ。評価値を四捨五入した数だけ金色にする。"""
    v = 0.0 if rating is None else max(0.0, min(5.0, float(rating)))
    out = ""
    for i in range(5):
        frac = max(0.0, min(1.0, v - i))      # この星をどこまで塗るか（0〜1）
        base = (f'<span style="font-size:{size}cqw;color:{T.STAR_EMPTY};'
                'letter-spacing:.1em;">★</span>')
        if frac <= 0:
            out += base
            continue
        if frac >= 1:
            out += (f'<span style="font-size:{size}cqw;color:{T.STAR};'
                    'letter-spacing:.1em;">★</span>')
            continue
        # 端数は、金色の星を左から frac ぶんだけ見せて重ねる（3.5 → 半分）
        out += (
            '<span style="position:relative;display:inline-block;">'
            f'{base}'
            f'<span style="position:absolute;left:0;top:0;width:{frac * 100:.0f}%;'
            'overflow:hidden;white-space:nowrap;">'
            f'<span style="font-size:{size}cqw;color:{T.STAR};'
            'letter-spacing:.1em;">★</span></span></span>'
        )
    return out


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 1「施設・基本情報」— docs/design/slide_p03.png
# ═══════════════════════════════════════════════════════════════════════════
def _profile_rows(b: dict) -> str:
    """施設プロフィールの4行。正典は罫線で囲った箱＋アクセント色の記号。"""
    rows = [
        ("◉", "住所", b.get("address")),
        ("▤", "開業日", b.get("open_year")),
        ("▥", "延床", b.get("floor_area")),
        ("◍", "マーケットカテゴリ", b.get("category")),
    ]
    out = ""
    for i, (icon, label, val) in enumerate(rows):
        v = val if val and val != "—" else "—"
        border = (f"border-bottom:1px solid {T.LINE};" if i < len(rows) - 1 else "")
        out += (
            f'<div style="flex:1;display:flex;align-items:center;gap:.8cqw;'
            f'padding:0 1cqw;{border}">'
            f'<span style="color:{T.ACCENT};font-size:1.32cqw;flex:none;">{icon}</span>'
            f'<span style="font-size:1.32cqw;color:{T.INK_SUB};width:10cqw;flex:none;'
            f'white-space:nowrap;">{escape(label)}</span>'
            f'<span style="font-size:1.37cqw;color:{T.INK};font-weight:600;'
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{escape(str(v))}</span></div>'
        )
    return (
        f'<div style="border:1px solid {T.LINE};border-radius:.5cqw;flex:1;'
        f'display:flex;flex-direction:column;min-height:0;">{out}</div>'
    )


def _review_summary_body(b: dict) -> str:
    n_rev = b.get("n_reviews") or 0
    avg = b.get("avg_rating")
    avg_txt = f"{avg:.1f}" if avg is not None else "—"
    half = (
        'display:flex;flex-direction:column;align-items:center;gap:.6cqw;'
    )
    return (
        '<div style="flex:1;display:flex;align-items:center;'
        'justify-content:space-around;padding:1cqw;">'
        # 総口コミ数
        f'<div style="{half}">'
        f'<span style="font-size:1.37cqw;color:{T.INK_SUB};font-weight:600;">'
        '総口コミ数</span>'
        '<span style="display:flex;align-items:baseline;gap:.2cqw;">'
        f'<span style="font-size:{T.FS["big_number"]}cqw;font-weight:800;'
        f'color:{T.ACCENT};line-height:1;">{n_rev:,}</span>'
        f'<span style="font-size:1.3cqw;color:{T.INK_MUTE};font-weight:600;">件</span>'
        '</span>'
        # 口コミ＝声、なので丸ではなく吹き出しの形にする
        '<span style="position:relative;display:inline-flex;width:4.4cqw;'
        f'height:3.2cqw;border-radius:1.1cqw;background:{T.ACCENT_SOFT};'
        f'align-items:center;justify-content:center;color:{T.ACCENT};'
        'font-size:1.4cqw;line-height:1;margin-top:.2cqw;">•••'
        '<span style="position:absolute;left:1.1cqw;bottom:-.52cqw;width:0;height:0;'
        'border-left:.5cqw solid transparent;border-right:.5cqw solid transparent;'
        f'border-top:.55cqw solid {T.ACCENT_SOFT};"></span></span></div>'
        # 総合評価
        f'<div style="{half}">'
        f'<span style="font-size:1.37cqw;color:{T.INK_SUB};font-weight:600;">'
        '総合評価</span>'
        '<span style="display:flex;align-items:baseline;gap:.3cqw;">'
        f'<span style="font-size:{T.FS["big_number"]}cqw;font-weight:800;'
        f'color:{T.ACCENT};line-height:1;">{avg_txt}</span>'
        f'<span style="font-size:1.3cqw;color:{T.INK_MUTE};font-weight:600;">/ 5</span>'
        '</span>'
        f'<span>{_stars(avg, size=1.5)}</span>'
        '</div></div>'
    )


def _trend_body(trend: list) -> str:
    """口コミ数の推移（累積）。PDF は右上がりの折れ線＋丸マーカー＋注記バッジ。"""
    if not trend:
        return (
            f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{T.SUB};font-size:1.1cqw;">推移データがありません</div>'
        )
    pts = trend[-24:]                       # 直近24か月まで
    vals = [v for _, v in pts]
    mx = max(vals) or 1
    ticks, top = nice_axis(mx)              # top >= mx が保証される
    n = len(pts)

    def x(i): return i / (n - 1) * 100 if n > 1 else 50.0
    def y(v): return plot_y(v, top)

    grid = "".join(
        f'<line x1="0" y1="{y(t):.2f}" x2="100" y2="{y(t):.2f}" stroke="{T.LINE}" '
        'stroke-width=".5" vector-effect="non-scaling-stroke" />'
        for t in ticks
    )
    line = (
        f'<polyline points="{" ".join(f"{x(i):.2f},{y(v):.2f}" for i, v in enumerate(vals))}" '
        f'fill="none" stroke="{T.ACCENT}" stroke-width="1.6" stroke-linejoin="round" '
        'vector-effect="non-scaling-stroke" />'
    )
    dots = plot_dots([(x(i), y(v)) for i, v in enumerate(vals)],
                     size=.5, color=T.ACCENT)
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(t):.2f}%;left:-3.4cqw;width:3cqw;'
        f'text-align:right;transform:translateY(-50%);font-size:1.04cqw;'
        f'color:{T.INK_SUB};">{_fmt_tick(t)}</div>'
        for t in ticks
    )
    # x軸ラベルは端と等間隔の4点だけ（PDFも間引いている）
    # 端のラベルはキャンバスからはみ出すので、寄せ方を位置に応じて変える
    idxs = sorted({0, n // 3, n * 2 // 3, n - 1})
    xlabs = ""
    for i in idxs:
        px = x(i)
        shift = "0" if px < 5 else ("-100%" if px > 95 else "-50%")
        xlabs += (
            f'<div style="position:absolute;left:{px:.2f}%;top:.2cqw;'
            f'transform:translateX({shift});'
            f'font-size:1.04cqw;color:{T.INK_SUB};white-space:nowrap;">'
            f'{escape(pts[i][0].replace("-", "/"))}</div>'
        )
    growth = vals[-1] > vals[0]
    # 累計なので折れ線は必ず右上がり。左上は必ず空くので、そこへ置けば
    # データに関係なく線とかぶらない（右上に置くと終端の点に必ず重なる）。
    badge = (
        f'<div style="position:absolute;left:.4cqw;top:2%;'
        f'background:{T.ACCENT_SOFT};color:{T.ACCENT};'
        'border-radius:1.4cqw;padding:.45cqw 1cqw;text-align:center;'
        'font-size:1.04cqw;font-weight:800;line-height:1.3;white-space:nowrap;">'
        f'{"継続的に増加傾向" if growth else "横ばい〜減少傾向"}</div>'
    )
    return (
        f'<div style="flex:none;font-size:0.95cqw;color:{T.INK_SUB};">（件）</div>'
        '<div style="flex:1;position:relative;min-height:0;margin-left:3.6cqw;'
        'margin-top:.2cqw;">'
        f'{ylabs}'
        # overflow:hidden — 万一 y 座標が範囲外でも、線がカードの外へ出ない
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:hidden;">'
        f'{grid}{line}</svg>{dots}{badge}</div>'
        f'<div style="flex:none;position:relative;height:1.6cqw;margin-left:3.6cqw;">'
        f'{xlabs}</div>'
    )


def _peer_cards_body(b: dict) -> str:
    peers = (b.get("peer_display") or [])[:5]
    if not peers:
        return (
            f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{T.SUB};font-size:1.1cqw;">比較対象施設が選択されていません</div>'
        )
    cards = "".join(
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:.5cqw;">'
        '<div style="flex:1;min-height:0;display:flex;">'
        + _photo(p.get("photo_data_uri"), height="100%", radius=".4cqw")
        + '</div>'
        + f'<div style="background:{T.ACCENT_SOFT};border-radius:.4cqw;'
        'padding:.45cqw;text-align:center;font-size:1.22cqw;font-weight:600;'
        f'color:{T.INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        f'{escape(p.get("name", ""))}</div></div>'
        for p in peers
    )
    return f'<div style="flex:1;display:flex;gap:1cqw;min-height:0;">{cards}</div>'


def slide1_facility_info(b: dict) -> str:
    """SLIDE 1「施設・基本情報」。docs/design/slide_p03.png と同じ構成。"""
    period = b.get("period_label") or ""
    meta = f"分析期間：{period}" if period else ""

    left = panel(
        "施設プロフィール",
        _photo(b.get("photo_data_uri"), height="15cqw", radius=".5cqw")
        + _profile_rows(b),
        icon="▦", style="width:31cqw;flex:none",
        pad="1.2cqw", gap="1cqw",
    )
    summary = panel("口コミサマリー", _review_summary_body(b),
                    icon="◗", style="width:24cqw;flex:none", pad="0")
    trend = panel("口コミ数の推移", _trend_body(b.get("review_trend") or []),
                  icon="◪", style="flex:1", pad=".9cqw 1.2cqw")
    n_peers = len(b.get("peer_display") or [])
    peers = panel(
        "比較対象施設（同カテゴリの類似施設）",
        _peer_cards_body(b),
        icon="◫",
        note=f"※同カテゴリの{n_peers}施設を比較対象として設定" if n_peers else "",
        style="flex:none;height:16.5cqw", pad="1cqw 1.2cqw",
    )

    body = body_area(
        f'{left}'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:1.4cqw;">'
        f'<div style="flex:1;display:flex;gap:1.4cqw;min-height:0;">{summary}{trend}</div>'
        f'{peers}</div>'
    )
    # Google Places のコンテンツ（写真・住所）を出したときは帰属表示が必須。
    note = "※口コミ数・総合評価は収集した口コミの実測値です"
    if b.get("photo_attribution"):
        note += f"／{b['photo_attribution']}"
    if b.get("address_from_google"):
        note += "／住所: Google"
    return canvas(slide_header("1", "施設・基本情報", meta), body, footer(note))


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 2「市場内ポジション」— docs/design/slide_p04.png
# ═══════════════════════════════════════════════════════════════════════════
def _score5(v100: float | None) -> float | None:
    """0-100スケールを5点満点の数値に（グラフの座標計算用）。"""
    return None if v100 is None else v100 / 100 * 5


def _pt5(v100: float | None) -> str:
    """0-100スケールを5点満点の表示文字列に（常に小数2桁で桁を揃える）。"""
    return "—" if v100 is None else f"{v100 / 100 * 5:.2f}"


def _wreath_svg() -> str:
    """月桂冠＋小さな王冠（SLIDE 2 の順位まわりの意匠）。

    葉は中心 (50,46) 半径 30 の円弧上に、接線方向へ傾けて並べる。
    角度は 0=真上・時計回り。左右対称になるよう符号だけ反転させる。
    """
    import math

    cx, cy, r = 50.0, 48.0, 39.0
    leaves = ""
    for side in (-1, 1):
        for k in range(7):
            a = 186 + k * 20                     # 底 → 斜め上へ開く C 字（葉は少し重ねる）
            rad = math.radians(a * side)
            x = cx + r * math.sin(rad)
            y = cy - r * math.cos(rad)
            # README §3「王冠アウトライン＋月桂樹 #F8C4D5」。葉は淡いピンクで、
            # 中央の順位を食わないようにする。
            leaves += (
                f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="7.6" ry="3.1" '
                f'fill="{T.LAUREL}" '
                f'transform="rotate({a * side - 90:.0f} {x:.1f} {y:.1f})"/>'
            )
    crown = (
        f'<path d="M42 15 L45.5 9.5 L50 14 L54.5 9.5 L58 15 L56.5 19 L43.5 19 Z" '
        f'fill="none" stroke="{T.ACCENT}" stroke-width="1.6" stroke-linejoin="round" '
        'vector-effect="non-scaling-stroke"/>'
        f'<circle cx="45.5" cy="8" r="1.5" fill="{T.ACCENT}"/>'
        f'<circle cx="54.5" cy="8" r="1.5" fill="{T.ACCENT}"/>'
        f'<circle cx="50" cy="12.5" r="1.5" fill="{T.ACCENT}"/>'
    )
    return (
        '<svg viewBox="0 0 100 82" style="width:100%;height:100%;">'
        f'{leaves}{crown}</svg>'
    )


def _ranking_body(b: dict) -> str:
    rank, total = b.get("rank"), b.get("total_fac") or 0
    pct = b.get("percentile")
    score5 = _pt5(b.get("overall_sentiment"))
    scope = b.get("scope_noun", "市場")

    wreath = _wreath_svg()
    return (
        '<div style="flex:1;display:flex;flex-direction:column;align-items:center;'
        'justify-content:center;gap:.5cqw;min-height:0;">'
        # 王冠＋月桂冠＋順位
        '<div style="position:relative;width:21cqw;height:15.5cqw;flex:none;">'
        f'<div style="position:absolute;inset:0;">{wreath}</div>'
        '<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
        'align-items:center;justify-content:center;padding-top:2.6cqw;">'
        '<div style="display:flex;align-items:baseline;">'
        f'<span style="font-size:4.6cqw;font-weight:800;color:{T.ACCENT_DEEP};'
        f'line-height:1;">{rank if rank else "—"}</span>'
        f'<span style="font-size:1.6cqw;font-weight:800;color:{T.ACCENT_DEEP};">位</span>'
        '</div>'
        f'<div style="font-size:1.16cqw;font-weight:700;color:{T.INK};margin-top:.2cqw;">'
        f'/ {total}施設中</div></div></div>'
        # ★
        f'<div>{_stars(b.get("avg_rating"), size=1.9)}</div>'
        # 5点スコア
        '<div style="display:flex;align-items:baseline;gap:.35cqw;">'
        f'<span style="font-size:3cqw;font-weight:800;color:{T.NAVY};line-height:1;">'
        f'{score5}</span>'
        f'<span style="font-size:1.27cqw;font-weight:700;color:{T.SUB};">/ 5点</span></div>'
        # 上位X%
        + (
            f'<div style="margin-top:.3cqw;background:{T.TABLE_HEAD};border-radius:.5cqw;'
            f'padding:.5cqw 1.8cqw;font-size:1.27cqw;font-weight:800;color:{T.INK};">'
            f'{scope}上位{pct}%</div>'
            if pct is not None else ""
        )
        + '</div>'
    )


def _dist_axis_ticks(lo5: float, hi5: float, n: int = 5) -> str:
    """評価分布の横軸に5点満点の数値を並べる。端は枠から出ないよう寄せ方を変える。"""
    if hi5 - lo5 < 0.005:                     # 全施設が同スコア → 1本だけ
        return (
            '<div style="flex:none;position:relative;height:1.6cqw;">'
            f'<div style="position:absolute;left:50%;transform:translateX(-50%);'
            f'font-size:.95cqw;color:{T.INK_MUTE};">{lo5:.2f}</div></div>'
        )
    out = ""
    for i in range(n):
        r = i / (n - 1)
        shift = "0" if i == 0 else ("-100%" if i == n - 1 else "-50%")
        out += (
            f'<div style="position:absolute;left:{r * 100:.1f}%;'
            f'transform:translateX({shift});font-size:.95cqw;color:{T.INK_MUTE};'
            f'white-space:nowrap;">{lo5 + (hi5 - lo5) * r:.2f}</div>'
        )
    return (
        '<div style="flex:none;position:relative;height:1.6cqw;margin-top:.3cqw;">'
        f'{out}</div>'
    )


def _distribution_body(b: dict) -> str:
    """同業施設内の総合評価分布。

    以前は13本のヒストグラムだったが、施設数が少ないと（実データで5〜6施設）
    ほとんどの階級が空になり、孤立した棒が数本立つだけで「分布」に見えない。
    棒の高さ（＝1施設）も情報を持っていなかった。

    そこで **数直線に1施設1点を置くドットプロット** にした。
      ・施設が何点のあたりに集まっているかがそのまま見える
      ・自施設がどこにいるかが一目で分かる（大きい点＋順位）
      ・施設数が2でも46でも破綻しない（近い点は上へ積む）
    平均の位置も破線で入れて、自施設との距離が読めるようにする。
    """
    dist = b.get("ranking_dist") or []
    me = b.get("overall_sentiment")
    rank, total = b.get("rank"), b.get("total_fac") or len(dist)
    if not dist or me is None:
        return (
            f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{T.SUB};font-size:1.1cqw;">分布を出せるデータがありません</div>'
        )

    lo5, hi5 = min(dist) / 20, max(dist) / 20        # 0-100 → 5点満点
    me5, avg5 = me / 20, sum(dist) / len(dist) / 20
    span = (hi5 - lo5) or 1.0
    pad = span * 0.06                                 # 端の点が枠に接しないように
    axis_lo, axis_hi = lo5 - pad, hi5 + pad
    axis_span = axis_hi - axis_lo

    def px(v5: float) -> float:
        return (v5 - axis_lo) / axis_span * 100

    # 近い点どうしは上へ積む（Wilkinson 型のドットプロット）
    DOT = 2.6                                         # 点の直径（%）
    columns: list[list[float]] = []                   # 各列に入っている値
    placed: list[tuple[float, int, bool]] = []        # (x%, 段, 自施設か)
    for v in sorted(dist):
        x = px(v / 20)
        for col in columns:
            if abs(col[0] - x) < DOT:
                col.append(x)
                placed.append((col[0], len(col) - 1, False))
                break
        else:
            columns.append([x])
            placed.append((x, 0, False))
    # 自施設は別に置く（最前面・大きい点）
    me_x = px(me5)

    max_stack = max((len(c) for c in columns), default=1)
    step = min(11.0, 78.0 / max(max_stack, 1))        # 1段の高さ（%）

    dots = "".join(
        f'<span style="position:absolute;left:{x:.2f}%;'
        f'bottom:{6 + lvl * step:.2f}%;transform:translateX(-50%);'
        f'width:1.5cqw;height:1.5cqw;border-radius:50%;'
        f'background:{T.BAR_PEER};"></span>'
        for x, lvl, _me in placed
    )
    me_dot = (
        f'<span style="position:absolute;left:{me_x:.2f}%;bottom:6%;'
        'transform:translate(-50%,0);width:2.3cqw;height:2.3cqw;border-radius:50%;'
        f'background:{T.ACCENT};border:.3cqw solid #fff;'
        f'box-shadow:0 0 0 .18cqw {T.ACCENT};"></span>'
        f'<span style="position:absolute;left:{me_x:.2f}%;bottom:calc(6% + 3cqw);'
        f'transform:translateX(-50%);background:{T.ACCENT};color:#fff;'
        'border-radius:1cqw;padding:.28cqw .9cqw;font-size:1.02cqw;font-weight:800;'
        f'white-space:nowrap;">{rank}位 / {total}施設</span>'
        if rank else ""
    )
    avg_line = (
        f'<span style="position:absolute;left:{px(avg5):.2f}%;top:8%;bottom:6%;'
        f'width:0;border-left:1px dashed {T.INK_FAINT};"></span>'
        f'<span style="position:absolute;left:{px(avg5):.2f}%;top:0;'
        f'transform:translateX(-50%);font-size:.95cqw;color:{T.INK_FAINT};'
        f'white-space:nowrap;">平均 {avg5:.2f}</span>'
    )
    return (
        '<div style="flex:1;display:flex;flex-direction:column;min-height:0;'
        'padding-top:1cqw;">'
        '<div style="flex:1;position:relative;min-height:0;">'
        f'{avg_line}{dots}{me_dot}'
        # 数直線
        f'<span style="position:absolute;left:0;right:0;bottom:6%;height:1px;'
        f'background:{T.INK_SUB};"></span></div>'
        f'{_dist_axis_ticks(axis_lo, axis_hi)}'
        '<div style="flex:none;display:flex;justify-content:space-between;'
        f'font-size:.98cqw;font-weight:700;color:{T.INK_SUB};margin-top:.15cqw;">'
        '<span>低評価</span><span>高評価</span></div>'
        f'<div style="flex:none;margin-top:.8cqw;border:1px solid {T.CARD_LINE};'
        'border-radius:.5cqw;padding:.7cqw;text-align:center;font-size:1.25cqw;'
        f'font-weight:700;color:{T.NAVY};">'
        f'総合評価 <span style="color:{T.ACCENT};">{_pt5(me)}</span></div>'
        '</div>'
    )


def _top3_card(title: str, rows: list, accent: str, icon: str,
               b: dict | None = None) -> str:
    """強みTOP3 / 弱みTOP3 のカード。rows = [(指標名, 自施設100, 基準100), ...]

    基準の呼び名は bundle の baseline_label（'全体平均' / '選択競合の平均' /
    '中立(50)'）を使う。以前は「市場平均」と決め打ちで書いていたので、
    競合2社を選んで作った資料にも「市場平均」と出ていた。読み手は市場全体と
    比べた結果だと受け取るが、実際は選んだ2社との比較。SLIDE 2 は最も
    引用されるスライドなので誤読の影響が大きい。
    """
    rule = T.ACCENT_BORDER if accent == T.ACCENT else T.BLUE_BORDER
    base_lbl = (b or {}).get("baseline_label") or "市場平均"
    items = ""
    for i, (name, mine, base) in enumerate(rows[:3], 1):
        items += (
            f'<div style="flex:1;display:flex;align-items:center;gap:.8cqw;'
            f'border-top:1px solid {rule};min-height:0;">'
            f'<span style="width:2.1cqw;height:2.1cqw;flex:none;border-radius:50%;'
            f'background:{accent};color:#fff;display:flex;align-items:center;'
            f'justify-content:center;font-size:1.25cqw;font-weight:700;">{i}</span>'
            f'<span style="flex:1;min-width:0;font-size:1.45cqw;font-weight:700;'
            f'color:{T.INK};white-space:nowrap;">'
            f'{topic_tooltip(name, place="right", b=b)}</span>'
            '<span style="text-align:right;flex:none;">'
            f'<span style="display:block;font-size:1.95cqw;font-weight:800;'
            f'color:{accent};line-height:1.1;">{_pt5(mine)}</span>'
            f'<span style="display:block;font-size:1.05cqw;color:{T.MUTED};'
            f'white-space:nowrap;">{escape(base_lbl)} {_pt5(base)}</span>'
            '</span></div>'
        )
    if not rows:
        items = f'<div style="color:{T.SUB};font-size:1.16cqw;">該当なし</div>'
    return (
        f'<div style="flex:1;border:1.5px solid {accent};border-radius:{T.CARD_RADIUS};'
        'padding:1cqw 1.2cqw;display:flex;flex-direction:column;min-height:0;'
        'background:#fff;">'
        '<div style="display:flex;align-items:center;gap:.7cqw;margin-bottom:.6cqw;'
        'flex:none;">'
        f'<span style="width:2.2cqw;height:2.2cqw;border-radius:50%;background:{accent};'
        'color:#fff;display:flex;align-items:center;justify-content:center;'
        f'font-size:1.32cqw;">{icon}</span>'
        f'<span style="font-size:1.8cqw;font-weight:800;color:{accent};">'
        f'{escape(title)}</span></div>'
        f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;">'
        f'{items}</div></div>'
    )


def slide2_market_position(b: dict) -> str:
    """SLIDE 2「市場内ポジション」。docs/design/slide_p04.png と同じ構成。"""
    scope = b.get("scope_label", "市場内")
    period = b.get("period_label_scope") or b.get("period_label") or ""
    meta = f"分析期間：{period}" if period else ""

    st = [(t, mine, base) for t, mine, base, _d in (b.get("strengths") or [])]
    wk = [(t, mine, base) for t, mine, base, _d in (b.get("weaknesses") or [])]

    left = panel("総合評価ランキング", _ranking_body(b), style="width:29cqw;flex:none")
    mid = panel("同業施設内の総合評価分布", _distribution_body(b), style="width:27cqw;flex:none")
    right = (
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
        'gap:1.2cqw;min-height:0;">'
        + _top3_card("強み TOP3", st, T.ACCENT, "▲", b)
        + _top3_card("弱み TOP3", wk, T.BLUE, "▼", b)
        + '</div>'
    )
    return canvas(
        slide_header("2", f"{scope}ポジション", meta),
        body_area(f'{left}{mid}{right}'),
        footer(score_note(b)),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 2 詳細「市場内ポジション（詳細）」— docs/design/slide_p05.png
#   マッピング／主要スコア／マーケット傾向は SLIDE 3 詳細（p7）でも使い回す。
# ═══════════════════════════════════════════════════════════════════════════
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _driver_topics(b: dict) -> list[str]:
    """このバンドルに値がある主要19指標。"""
    from . import topic_score
    have = set(b.get("topic_names") or [])
    return [t for t in topic_score.DRIVER_TOPICS if t in have]


def _indicator_chart(b: dict) -> str:
    """19指標の折れ線（当施設 実線 vs 同業平均 破線）。1〜5点の固定軸。"""
    topics = _driver_topics(b)
    mine = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))
    avg = b.get("overall_topic") or {}
    n = len(topics)
    if not n:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">データ不足</div>')

    LO, HI = 1.0, 5.0

    def y(v100): return (1 - (min(max(_score5(v100), LO), HI) - LO) / (HI - LO)) * 100
    def x(i): return i / (n - 1) * 100 if n > 1 else 50.0

    dash = 'stroke-dasharray="3.5 2.5"'
    grid = "".join(
        f'<line x1="0" y1="{y(g * 20):.2f}" x2="100" y2="{y(g * 20):.2f}" '
        f'stroke="{T.LINE}" stroke-width=".45" vector-effect="non-scaling-stroke"/>'
        for g in (1, 2, 3, 4, 5)
    )
    series, markers = "", ""
    for label, src, col, is_avg in (
        ("当施設", mine, T.ACCENT, False),
        ("同業平均", avg, T.BLUE, True),
    ):
        pts = " ".join(f"{x(i):.2f},{y(src.get(t, 50.0)):.2f}" for i, t in enumerate(topics))
        series += (
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.5" '
            f'{dash if is_avg else ""} stroke-linejoin="round" '
            'vector-effect="non-scaling-stroke"/>'
        )
        markers += plot_dots(
            [(x(i), y(src.get(t, 50.0))) for i, t in enumerate(topics)],
            size=.62, color=col,
        )
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(g * 20):.2f}%;left:-2.2cqw;width:1.8cqw;'
        f'text-align:right;transform:translateY(-50%);font-size:0.76cqw;color:{T.SUB};">'
        f'{g}</div>'
        for g in (1, 2, 3, 4, 5)
    )
    # X軸ラベルは縦書き（丸番号＋指標名を1文字ずつ積む）。
    # 回転で寝かせると「横書きを横倒しにしただけ」に見えるため。
    xlabs = "".join(
        f'<div style="position:absolute;left:{x(i):.2f}%;top:0;'
        'transform:translateX(-50%);text-align:center;">'
        f'<div style="font-size:0.88cqw;color:{T.INK};line-height:1.2;'
        'margin-bottom:.15cqw;">'
        f'{_CIRCLED[i] if i < len(_CIRCLED) else i + 1}</div>'
        + f'<span {topic_attrs(t, b)}>{vertical_text(t, size=.66)}'
        + _topic_tip_body(
            t, "up-l" if x(i) < 25 else ("up-r" if x(i) > 75 else "up"), b)
        + '</span></div>'
        for i, t in enumerate(topics)
    )
    # 凡例は正典どおり「色の短い横棒＋名前」（線種の記号は使わない）
    legend = (
        '<div style="flex:none;display:flex;align-items:center;gap:1.4cqw;'
        f'font-size:1.22cqw;color:{T.INK_SUB};margin-bottom:.4cqw;">'
        '<span>評価スコア（点）</span>'
        '<span style="display:flex;align-items:center;gap:.4cqw;">'
        f'<span style="width:1.6cqw;height:.28cqw;background:{T.ACCENT};'
        'display:inline-block;"></span>当施設</span>'
        '<span style="display:flex;align-items:center;gap:.4cqw;">'
        f'<span style="width:1.6cqw;height:.28cqw;background:{T.BLUE};'
        'display:inline-block;"></span>同業平均</span></div>'
    )
    return (
        legend
        + '<div style="flex:1;position:relative;min-height:0;margin-left:2.4cqw;">'
        f'{ylabs}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'{grid}{series}</svg>{markers}</div>'
        f'<div style="flex:none;position:relative;height:10.5cqw;margin-left:2.4cqw;'
        f'margin-top:.35cqw;">{xlabs}</div>'
    )


def _indicator_table(b: dict) -> str:
    """指標（代表例）の表。強みTOP3＋弱みTOP3＋総合評価（PDFと同じ選び方）。"""
    rows = [(t, mine, base) for t, mine, base, _ in (b.get("strengths") or [])[:3]]
    rows += [(t, mine, base) for t, mine, base, _ in (b.get("weaknesses") or [])[:3]]
    num = "width:4.4cqw;flex:none;padding:.55cqw;text-align:center;"
    head = (
        f'<div style="display:flex;background:{T.TABLE_HEAD};font-size:1.16cqw;'
        f'font-weight:700;color:{T.INK_SUB};flex:none;">'
        '<div style="flex:1.5;padding:.55cqw .6cqw;">指標（代表例）</div>'
        f'<div style="{num}background:{T.ACCENT};color:#fff;">当施設</div>'
        f'<div style="{num}background:{T.TABLE_AVG};color:#fff;">同業平均</div></div>'
    )
    body = "".join(
        f'<div style="flex:1;display:flex;align-items:center;'
        f'border-top:1px solid {T.LINE};min-height:0;">'
        f'<div style="flex:1.5;padding:.2cqw .6cqw;font-size:1.1cqw;color:{T.INK};'
        'line-height:1.3;word-break:break-all;">'
        f'{escape(t)}</div>'
        f'<div style="width:4.4cqw;flex:none;text-align:center;font-size:1.27cqw;'
        f'font-weight:700;color:{T.ACCENT};">{_pt5(m)}</div>'
        f'<div style="width:4.4cqw;flex:none;text-align:center;font-size:1.27cqw;'
        f'color:{T.INK_MUTE};">{_pt5(a)}</div></div>'
        for t, m, a in rows
    )
    tot_mine = b.get("overall_sentiment")
    _dist = b.get("ranking_dist") or []
    tot_avg = sum(_dist) / len(_dist) if _dist else None
    total = (
        f'<div style="flex:1;display:flex;align-items:center;min-height:0;'
        f'border-top:1.5px solid {T.NAVY};">'
        f'<div style="flex:1.5;padding:0 .6cqw;font-size:1.22cqw;font-weight:700;'
        f'color:{T.INK};">総合評価</div>'
        f'<div style="width:4.4cqw;flex:none;text-align:center;font-size:1.27cqw;'
        f'font-weight:700;color:{T.ACCENT};">{_pt5(tot_mine)}</div>'
        f'<div style="width:4.4cqw;flex:none;text-align:center;font-size:1.27cqw;'
        f'font-weight:700;color:{T.INK_MUTE};">{_pt5(tot_avg)}</div></div>'
    )
    return (
        f'<div style="width:19cqw;flex:none;display:flex;flex-direction:column;'
        f'border:1px solid {T.CARD_LINE};border-radius:.5cqw;overflow:hidden;">'
        f'{head}{body}{total}</div>'
    )


def experience_map(b: dict, *, names: list[str] | None = None,
                   label_points: bool = False) -> str:
    """総合体験評価マッピング（横=体験満足度／縦=推奨意向／バブル=再訪意向）。

    names を渡すとその施設だけを描く（SLIDE 3 詳細で競合5施設に絞るため）。
    """
    omap = b.get("outcome_map") or {}
    target = b.get("target", "")
    if names is not None:
        omap = {k: v for k, v in omap.items() if k in set(names) | {target}}
    if not omap:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">データ不足</div>')

    XS, YS, RS = "体験満足度", "推奨意向", "再訪意向"
    xs = [v.get(XS, 50.0) for v in omap.values()]
    ys = [v.get(YS, 50.0) for v in omap.values()]
    rs = [v.get(RS, 50.0) for v in omap.values()]

    def _norm(v, lo, hi): return (v - lo) / ((hi - lo) or 1)
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    rlo, rhi = min(rs), max(rs)

    dots, labels = "", ""
    peer_order = [k for k in omap if k != target]
    for i, nm in enumerate(peer_order + ([target] if target in omap else [])):
        v = omap[nm]
        is_me = nm == target
        px = 8 + _norm(v.get(XS, 50.0), xlo, xhi) * 84
        py = 92 - _norm(v.get(YS, 50.0), ylo, yhi) * 84
        rr = 1.6 + _norm(v.get(RS, 50.0), rlo, rhi) * 2.6
        # バブルも真円で置く（SVG は縦横で倍率が違うので <circle> は潰れる）
        if is_me:
            dots += (
                f'<span style="position:absolute;left:{px:.2f}%;top:{py:.2f}%;'
                f'transform:translate(-50%,-50%);width:{rr * 1.7:.2f}cqw;'
                f'height:{rr * 1.7:.2f}cqw;border-radius:50%;'
                f'background:{T.ACCENT};"></span>'
            )
        else:
            col = T.SERIES_PEERS[i % len(T.SERIES_PEERS)] if label_points else T.BLUE
            dots += (
                f'<span style="position:absolute;left:{px:.2f}%;top:{py:.2f}%;'
                f'transform:translate(-50%,-50%);width:{rr:.2f}cqw;'
                f'height:{rr:.2f}cqw;border-radius:50%;background:{col};'
                f'opacity:{0.85 if label_points else 0.55};"></span>'
            )
        if is_me or label_points:
            nm_disp = "当施設" if is_me else _clip_name(nm, 7)
            # 上端付近のバブルはラベルを上に置くとカードの外（ヘッダー帯）まで
            # 抜けてしまうので、下に回す。閾値はラベル1行ぶんの余裕をみる。
            off = f"{rr * 1.9 + 3:.1f}" if py > 22 else f"-{rr * 1.9 + 1.6:.1f}"
            shift = "0" if px < 14 else ("-100%" if px > 86 else "-50%")
            labels += (
                f'<div style="position:absolute;left:{px:.2f}%;top:{py:.2f}%;'
                f'transform:translate({shift},-{off}cqw);'
                f'font-size:1.04cqw;font-weight:800;white-space:nowrap;'
                f'color:{T.ACCENT if is_me else T.INK};">{escape(nm_disp)}</div>'
            )
    dash = 'stroke-dasharray="2.5 2.5"'
    return (
        '<div style="flex:1;display:flex;gap:.8cqw;min-height:0;padding-left:2.2cqw;">'
        # 散布図
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        '<div style="flex:1;position:relative;min-height:0;">'
        f'<div style="position:absolute;left:-.1cqw;top:0;font-size:0.76cqw;'
        f'color:{T.INK};">高</div>'
        f'<div style="position:absolute;left:-.1cqw;bottom:1.3cqw;font-size:0.76cqw;'
        f'color:{T.INK};">低</div>'
        '<div style="position:absolute;left:-2cqw;top:50%;'
        'transform:translateY(-50%);">'
        + vertical_text("推奨意向", size=.7, weight=700) + '</div>'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'<line x1="50" y1="2" x2="50" y2="94" stroke="{T.LINE}" {dash} '
        'stroke-width=".5" vector-effect="non-scaling-stroke"/>'
        f'<line x1="6" y1="50" x2="98" y2="50" stroke="{T.LINE}" {dash} '
        'stroke-width=".5" vector-effect="non-scaling-stroke"/>'
        f'<line x1="6" y1="94" x2="98" y2="94" stroke="{T.INK}" stroke-width=".6" '
        'vector-effect="non-scaling-stroke"/>'
        f'<line x1="6" y1="94" x2="6" y2="2" stroke="{T.INK}" stroke-width=".6" '
        'vector-effect="non-scaling-stroke"/>'
        '</svg>'
        f'{dots}{labels}</div>'
        '<div style="flex:none;display:flex;justify-content:space-between;'
        f'font-size:1.04cqw;font-weight:600;color:{T.INK_SUB};margin-top:.15cqw;'
        'padding:0 .4cqw;">'
        '<span>低</span>'
        f'<span style="font-weight:800;color:{T.INK};">体験満足度</span>'
        '<span>高</span></div>'
        f'<div style="flex:none;font-size:{T.FS["note"]}cqw;font-weight:600;'
        f'color:{T.INK_SUB};margin-top:.25cqw;">○ バブルサイズ＝再訪意向</div>'
        '</div>'
        + _outcome_boxes(b)
        + '</div>'
    )


def _clip_name(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _outcome_boxes(b: dict) -> str:
    """口コミから算出した主要スコア（体験満足度／推奨意向／再訪意向）。"""
    mine = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))
    items = [("😊", "体験満足度"), ("👍", "推奨意向"), ("🔁", "再訪意向")]
    boxes = "".join(
        f'<div style="flex:1 1 0;min-height:0;max-height:5.6cqw;'
        f'border:1.4px solid {T.ACCENT};'
        'border-radius:.7cqw;display:flex;align-items:center;justify-content:center;'
        'gap:.6cqw;padding:.3cqw;">'
        f'<span style="font-size:1.3cqw;">{icon}</span>'
        '<span style="text-align:center;">'
        f'<div style="font-size:1.1cqw;font-weight:700;color:{T.INK_SUB};">'
        f'{topic_tooltip(name, place="down", b=b)}</div>'
        f'<div style="font-size:1.7cqw;font-weight:800;color:{T.ACCENT};'
        f'line-height:1.1;">{_pt5(mine.get(name))}</div>'
        '</span></div>'
        for icon, name in items
    )
    return (
        '<div style="width:12.6cqw;flex:none;display:flex;flex-direction:column;'
        'gap:.6cqw;min-height:0;overflow:hidden;justify-content:center;">'
        f'<div style="flex:none;font-size:1cqw;font-weight:800;'
        f'color:{T.ACCENT};white-space:nowrap;">口コミから算出した主要スコア</div>'
        f'{boxes}</div>'
    )


def market_trend(b: dict, note: str, *, large: bool = False) -> str:
    """マーケット傾向 A（評価されやすい）／B（課題になりやすい）。

    large=True は SLIDE 3 詳細の広いパネル用。項目を角丸タイル＋大きめの字にする。
    """
    good = b.get("market_trend_good") or []
    bad = b.get("market_trend_bad") or []
    fs_item = 1.15 if large else 1.0
    fs_head = 1.05 if large else .95

    def col(letter: str, title: str, items: list, accent: str, bg: str,
            border: str, arrow: str) -> str:
        if large:
            mark = (f'<span style="width:2.4cqw;height:2.4cqw;flex:none;'
                    f'border:1px solid {border};border-radius:.4cqw;color:{accent};'
                    'display:flex;align-items:center;justify-content:center;'
                    'font-size:1.32cqw;">◈</span>')
        else:
            mark = f'<span style="color:{accent};font-size:1.22cqw;flex:none;">◈</span>'
        rows = "".join(
            f'<div style="flex:1;display:flex;align-items:center;'
            f'gap:{".8" if large else ".6"}cqw;min-height:0;min-width:0;">'
            f'{mark}'
            f'<span style="flex:1;min-width:0;font-size:{fs_item}cqw;color:{T.INK};'
            f'font-weight:{700 if large else 600};'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{escape(t)}</span></div>'
            for t in items[:5]
        )
        if large:
            head = (
                f'<div style="background:{bg};border-radius:.5cqw;padding:.6cqw .8cqw;'
                'display:flex;align-items:center;gap:.6cqw;flex:none;">'
                f'<span style="width:1.9cqw;height:1.9cqw;border-radius:50%;'
                f'background:{accent};color:#fff;display:flex;align-items:center;'
                f'justify-content:center;font-size:1.22cqw;flex:none;">{arrow}</span>'
                f'<span style="font-size:{fs_head}cqw;font-weight:700;color:{accent};'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                f'{escape(title)}</span></div>'
            )
        else:
            head = (
                f'<div style="background:{bg};border-radius:.4cqw;'
                f'padding:.45cqw .7cqw;font-size:{fs_head}cqw;font-weight:700;'
                f'color:{accent};flex:none;overflow:hidden;text-overflow:ellipsis;'
                f'white-space:nowrap;">{letter}. {escape(title)}</div>'
            )
        return (
            '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
            f'gap:{".6" if large else ".4"}cqw;">{head}{rows}</div>'
        )

    return (
        f'<div style="flex:1;display:flex;gap:{"1.2" if large else ".9"}cqw;'
        'min-height:0;">'
        + col("A", "この市場で評価されやすい指標", good, T.ACCENT,
              T.ACCENT_SOFT, T.ACCENT_BORDER, "▲")
        + col("B", "この市場で課題になりやすい指標", bad, T.BLUE,
              T.BLUE_SOFT, T.BLUE_BORDER, "▼")
        + '</div>'
        f'<div style="flex:none;font-size:{T.FS["note"]}cqw;color:{T.INK_FAINT};'
        f'text-align:right;padding-top:.5cqw;">{escape(note)}</div>'
    )


def slide2_market_detail(b: dict) -> str:
    """SLIDE 2 詳細「市場内ポジション（詳細）」。"""
    scope = b.get("scope_label", "市場内")
    n_fac = b.get("total_fac") or 0

    left = panel(
        "乃村独自の口コミ分析指標",
        '<div style="flex:1;display:flex;gap:1cqw;min-height:0;">'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        f'{_indicator_chart(b)}</div>'
        f'{_indicator_table(b)}</div>'
        f'<div style="font-size:{T.FS["note"]}cqw;color:{T.INK_FAINT};'
        'padding:0 1cqw 1cqw;flex:none;">※ 各指標は1〜5点で評価</div>',
        style="flex:1", pad="1cqw 1cqw 0",
    )
    right = (
        '<div style="width:37cqw;flex:none;display:flex;flex-direction:column;'
        'gap:1.2cqw;min-width:0;">'
        + panel("総合体験評価マッピング", experience_map(b),
                note=f"※ マッピングは全{n_fac}施設を表示", style="flex:1",
                pad=".9cqw")
        + panel("マーケット傾向",
                market_trend(b, "※ 市場傾向は同カテゴリ施設の口コミ分析から算出"),
                style="height:19cqw;flex:none", pad=".9cqw")
        + '</div>'
    )
    return canvas(
        slide_header("2", f"{scope}ポジション", sub_title="詳細"),
        body_area(f'{left}{right}'),
        footer(score_note(b)),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 3「指定競合との比較」— docs/design/slide_p06.png / slide_p07.png
# ═══════════════════════════════════════════════════════════════════════════
def compare_columns(b: dict) -> list[tuple[str, str, dict, str]]:
    """(表示名, 施設名, スコア, 色) の列。自施設 → 競合A〜E → 同業平均。"""
    mine = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))
    peers = b.get("peer_topic_scores") or {}
    cols: list[tuple[str, str, dict, str]] = [
        ("自施設", b.get("target", ""), mine, T.SERIES_SELF)
    ]
    for i, nm in enumerate(list(peers)[: len(T.SERIES_PEERS)]):
        cols.append((f"競合{'ABCDE'[i]}", nm, peers[nm], T.SERIES_PEERS[i]))
    if b.get("overall_topic"):
        # 指定競合モードでは母数が選択競合なので overall_topic ＝ 競合の平均。
        # 「同業平均」と名乗ると市場全体の平均だと誤解されるため名前を変える。
        avg_label = ("競合平均" if b.get("comparison_scope") == "competitor"
                     else "同業平均")
        cols.append((avg_label, avg_label, b["overall_topic"], T.SERIES_AVG))
    return cols


def _compare_chart(b: dict, topics: list[str]) -> str:
    """主要19指標の折れ線（自施設・競合A〜D・同業平均）。1〜5点の固定軸。"""
    cols = compare_columns(b)
    n = len(topics)
    LO, HI = 1.0, 5.0

    def y(v): return (1 - (min(max(_score5(v), LO), HI) - LO) / (HI - LO)) * 100
    def x(i): return i / (n - 1) * 100 if n > 1 else 50.0

    dash = 'stroke-dasharray="3.5 2.5"'
    grid = "".join(
        f'<line x1="0" y1="{y(g * 20):.2f}" x2="100" y2="{y(g * 20):.2f}" '
        f'stroke="{T.LINE}" stroke-width=".45" vector-effect="non-scaling-stroke"/>'
        for g in (1, 2, 3, 4, 5)
    )
    series, markers = "", ""
    for label, _nm, sc, col in cols:
        is_avg = label.endswith("平均")
        pts = " ".join(f"{x(i):.2f},{y(sc.get(t, 50.0)):.2f}" for i, t in enumerate(topics))
        series += (
            f'<polyline points="{pts}" fill="none" stroke="{col}" '
            f'stroke-width="{1.1 if is_avg else 1.5}" {dash if is_avg else ""} '
            'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        )
        if not is_avg:
            markers += plot_dots(
                [(x(i), y(sc.get(t, 50.0))) for i, t in enumerate(topics)],
                size=.52, color=col,
            )
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(g * 20):.2f}%;left:-2.4cqw;width:2cqw;'
        f'text-align:right;transform:translateY(-50%);font-size:0.73cqw;color:{T.SUB};">'
        f'{g}.0</div>'
        for g in (1, 2, 3, 4, 5)
    )
    # README §3「19指標比較 … X軸 -62°」
    #   ラベルは -62° 回転しているので、子として吹き出しを置くと一緒に傾いて
    #   カードを抜ける。説明は同じスライドのヒートマップ（横書きの指標名）に
    #   任せ、ここには付けない。
    xlabs = tilted_axis_labels(topics, [x(i) for i in range(n)], deg=62,
                               size=.75, b=b)
    legend = "".join(
        '<span style="display:flex;align-items:center;gap:.35cqw;">'
        f'<span style="width:1.3cqw;height:.25cqw;background:{col};'
        f'display:inline-block;"></span>{escape(lb)}</span>'
        for lb, _nm, _sc, col in cols
    )
    return (
        '<div style="display:flex;gap:1cqw;flex-wrap:wrap;font-size:1.1cqw;'
        f'color:{T.INK_SUB};margin-bottom:.3cqw;flex:none;">{legend}</div>'
        '<div style="flex:1;position:relative;min-height:0;margin-left:2.6cqw;">'
        f'{ylabs}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'{grid}{series}</svg>{markers}</div>'
        '<div style="flex:none;position:relative;height:7.6cqw;margin-left:2.6cqw;'
        f'margin-top:.35cqw;">{xlabs}</div>'
    )


def _compare_heatmap(b: dict, topics: list[str]) -> str:
    """施設別スコアヒートマップ。行=19指標 × 列=自施設/競合A〜E/平均。

    セルの地色は README §2 の5段階（4.2+ / 3.8+ / 3.4+ / 3.0+ / 〜2.9）。
    """
    cols = compare_columns(b)
    head = (
        f'<div style="display:flex;background:{T.TABLE_HEAD};font-size:1.1cqw;'
        f'font-weight:700;color:{T.INK_SUB};flex:none;'
        f'border-bottom:1px solid {T.CARD_LINE};">'
        '<div style="flex:2;padding:.5cqw .6cqw;">指標</div>'
        + "".join(
            '<div style="flex:1;padding:.5cqw .2cqw;text-align:center;'
            f'color:{T.ACCENT if i == 0 else T.INK_SUB};white-space:nowrap;">'
            f'{escape(lb)}</div>'
            for i, (lb, _n, _s, _col) in enumerate(cols)
        )
        + '</div>'
    )
    rows = "".join(
        f'<div style="flex:1;display:flex;align-items:center;min-height:0;'
        f'border-bottom:1px solid {T.TABLE_HEAD};">'
        f'<div style="flex:2;padding:0 .6cqw;font-size:1.07cqw;color:{T.INK};'
        'white-space:nowrap;">'
        f'{topic_tooltip(t, place="right", b=b)}</div>'
        + "".join(
            '<div style="flex:1;align-self:stretch;display:flex;align-items:center;'
            'justify-content:center;font-size:1.1cqw;'
            f'background:{T.heat_bg(_score5(sc.get(t, 50.0)), is_self=i == 0)};'
            f'color:{T.ACCENT if i == 0 else T.INK_SUB};'
            f'font-weight:{800 if i == 0 else 500};">{_pt5(sc.get(t, 50.0))}</div>'
            for i, (_l, _n, sc, _c) in enumerate(cols)
        )
        + '</div>'
        for t in topics
    )
    return ('<div style="flex:1;min-height:0;display:flex;flex-direction:column;">'
            f'{head}{rows}</div>')


def _vs_peer_lists(b: dict, topics: list[str]) -> tuple[list, list]:
    """競合平均との差（5点満点）。(勝っている項目, 負けている項目)。"""
    mine = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))
    peers = b.get("peer_topic_scores") or {}
    if not peers:
        return [], []
    win, lose = [], []
    for t in topics:
        pv = [p.get(t, 50.0) for p in peers.values()]
        if not pv:
            continue
        d = (mine.get(t, 50.0) - sum(pv) / len(pv)) / 100 * 5
        (win if d > 0 else lose).append((t, round(d, 2)))
    win.sort(key=lambda z: -z[1])
    lose.sort(key=lambda z: z[1])
    return win, lose


def _diff_grid(rows: list, color: str, cap: int) -> str:
    if not rows:
        return f'<div style="color:{T.SUB};font-size:1.22cqw;">該当なし</div>'
    mark = "●" if color == T.ACCENT else "◆"
    return (
        '<div style="flex:1;display:grid;grid-template-columns:1fr 1fr;'
        'gap:.2cqw 1.4cqw;align-content:center;">'
        + "".join(
            '<div style="display:flex;align-items:center;gap:.5cqw;min-width:0;">'
            f'<span style="color:{color};font-size:1.1cqw;flex:none;">{mark}</span>'
            f'<span style="flex:1;font-size:1.22cqw;color:{T.INK};overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap;">{escape(t)}</span>'
            f'<span style="font-size:1.22cqw;font-weight:700;color:{color};flex:none;">'
            f'（{d:+.2f}）</span></div>'
            for t, d in rows[:cap]
        )
        + '</div>'
    )


def _compare_header(b: dict, detail: bool) -> str:
    cols = compare_columns(b)
    n_fac = sum(1 for lb, _n, _s, _c in cols if not lb.endswith("平均"))
    period = b.get("period_label_scope") or b.get("period_label") or ""
    meta = f"分析対象：{n_fac}施設"
    if period:
        meta += f"　分析期間：{period}"
    return slide_header("3", "指定競合との比較", meta,
                        sub_title="詳細" if detail else "")


def slide3_competitor_compare(b: dict) -> str:
    """SLIDE 3「指定競合との比較」。docs/design/slide_p06.png。"""
    topics = _driver_topics(b)
    if not topics:
        return canvas(
            _compare_header(b, False),
            body_area(
                '<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.32cqw;">'
                '比較できるデータがありません。</div>'
            ),
            footer(),
        )
    win, lose = _vs_peer_lists(b, topics)
    body = body_area(
        f'<div style="font-size:{T.FS["slide_lead"]}cqw;font-weight:700;'
        f'color:{T.INK};flex:none;">'
        '2〜5施設を横並びで比較し、自施設の立ち位置を把握します。</div>'
        '<div style="flex:1;display:flex;gap:1.2cqw;min-height:0;">'
        + panel("主要19指標の比較（5点満点）", _compare_chart(b, topics),
                head_size=1.3, pad=".9cqw")
        + panel("施設別スコアヒートマップ（5点満点）", _compare_heatmap(b, topics),
                style="width:50cqw;flex:none", head_size=1.3, pad="0")
        + '</div>'
        '<div style="height:9.4cqw;flex:none;display:flex;gap:1.2cqw;">'
        + panel("自施設だけの強み", _diff_grid(win, T.ACCENT, 6),
                head_size=1.25, pad=".6cqw 1.2cqw")
        + panel("競合に負けている項目", _diff_grid(lose, T.BLUE, 4),
                head_size=1.25, pad=".6cqw 1.2cqw")
        + '</div>',
        top=T.BODY_TOP_TIGHT, column=True, gap=.9,
    )
    return canvas(_compare_header(b, False), body, footer(score_note(b)))


def slide3_competitor_detail(b: dict) -> str:
    """SLIDE 3「指定競合との比較（詳細）」。"""
    peers = list((b.get("peer_topic_scores") or {}))[: len(T.SERIES_PEERS)]
    body = body_area(
        panel("総合体験評価マッピング",
              experience_map(b, names=peers, label_points=True),
              style="flex:1", head_size=1.45, pad="1.2cqw")
        + panel("指定競合の傾向",
                market_trend(b, "※ 市場傾向は同カテゴリ施設の口コミ分析から算出",
                             large=True),
                style="flex:1", head_size=1.45, pad="1.2cqw")
    )
    return canvas(_compare_header(b, True), body, footer(score_note(b)))


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 4「時間軸分析」— docs/design/slide_p08.png
# ═══════════════════════════════════════════════════════════════════════════
def _tag_head(title: str, *, inset: bool = False) -> str:
    """紺のタグ見出し（SLIDE 4 のブロック見出し）。

    inset=True はカードの左上角に食い込ませる形（右下だけ角丸）。
    """
    radius = ("border-bottom-right-radius:.6cqw;" if inset
              else "border-radius:.5cqw;")
    return (
        f'<div style="flex:none;align-self:flex-start;background:{T.NAVY};color:#fff;'
        f'font-size:1.3cqw;font-weight:700;padding:.6cqw 1.4cqw;{radius}">'
        f'{escape(title)}</div>'
    )


def _posneg_chart(series: list, points: list) -> str:
    """月次のポジ／ネガ積み上げ棒＋差分の折れ線。軸は −1.0〜+1.0 固定。"""
    if not series:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">'
                '推移を出せるデータがありません</div>')
    # 変化点は系列全体から検出するので、グラフも全期間を描く。
    # ここで直近Nか月に切ると、範囲外の変化点だけ番号バッジが消えてしまう。
    pts = series
    n = len(pts)
    marked = {cp.ym: i + 1 for i, cp in enumerate(points)}

    def y(v):                      # -1..+1 → 100..0
        return (1 - (max(-1.0, min(1.0, v)) + 1) / 2) * 100

    def x(i):
        return (i + 0.5) / n * 100

    grid = "".join(
        f'<line x1="0" y1="{y(g):.2f}" x2="100" y2="{y(g):.2f}" '
        f'stroke="{T.LINE if g else T.SUB}" stroke-width="{.8 if g == 0 else .45}" '
        'vector-effect="non-scaling-stroke"/>'
        for g in (1.0, 0.5, 0.0, -0.5, -1.0)
    )
    bw = 100 / n * 0.52
    bars = ""
    for i, (_ym, _n, pos, neg, _d, _a) in enumerate(pts):
        cx = x(i)
        bars += (
            f'<rect x="{cx - bw / 2:.2f}" y="{y(pos):.2f}" width="{bw:.2f}" '
            f'height="{y(0) - y(pos):.2f}" fill="{T.POS_BAR}"/>'
            f'<rect x="{cx - bw / 2:.2f}" y="{y(0):.2f}" width="{bw:.2f}" '
            f'height="{y(neg) - y(0):.2f}" fill="{T.NEG_BAR}"/>'
        )
    line = " ".join(f"{x(i):.2f},{y(r[4]):.2f}" for i, r in enumerate(pts))
    dots = plot_dots([(x(i), y(r[4])) for i, r in enumerate(pts)],
                     size=.55, color=T.DIFF_LINE, hollow=True, ring=.13)
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(g):.2f}%;left:-3cqw;width:2.6cqw;'
        'text-align:right;transform:translateY(-50%);font-size:0.76cqw;'
        f'color:{T.ACCENT_DEEP if g > 0 else (T.BLUE if g < 0 else T.INK)};">'
        f'{g:+.1f}</div>'.replace("+0.0", "0")
        for g in (1.0, 0.5, 0.0, -0.5, -1.0)
    )
    badges = "".join(
        f'<div style="position:absolute;left:{x(i):.2f}%;top:-2.2cqw;'
        'transform:translateX(-50%);width:1.9cqw;height:1.9cqw;border-radius:50%;'
        f'background:{T.ACCENT};color:#fff;font-size:1.04cqw;font-weight:800;'
        'display:flex;align-items:center;justify-content:center;">'
        f'{marked[r[0]]}</div>'
        for i, r in enumerate(pts) if r[0] in marked
    )
    xlabs = ""
    for i, r in enumerate(pts):
        y4, m2 = r[0].split("-")
        show = (i == 0) or m2 == "01" or n <= 14
        if not show:
            continue
        lab = f"'{y4[2:]}/{m2}" if (i == 0 or m2 == "01") else m2
        xlabs += (
            f'<div style="position:absolute;left:{x(i):.2f}%;top:.1cqw;'
            'transform:translateX(-50%);'
            f'font-size:0.73cqw;color:{T.INK};white-space:nowrap;">'
            f'{escape(lab)}</div>'
        )
    legend = (
        '<div style="flex:none;display:flex;flex-direction:column;gap:.45cqw;'
        'width:12.5cqw;padding-top:1.5cqw;">'
        + "".join(
            '<div style="display:flex;align-items:center;gap:.5cqw;'
            f'font-size:0.88cqw;color:{T.INK};">'
            f'<span style="flex:none;width:1.5cqw;height:.75cqw;background:{c};'
            'border-radius:.1cqw;"></span>' + escape(t) + '</div>'
            for c, t in ((T.POS_BAR, "ポジティブ要因スコア（+）"),
                         (T.NEG_BAR, "ネガティブ要因スコア（−）"))
        )
        + '<div style="display:flex;align-items:center;gap:.5cqw;'
        f'font-size:0.88cqw;color:{T.INK};">'
        f'<span style="flex:none;color:{T.DIFF_LINE};font-weight:800;">─○─</span>'
        '差分（ポジ − ネガ）</div>'
        f'<div style="font-size:0.81cqw;color:{T.SUB};margin-top:.2cqw;">（スコア）</div>'
        '</div>'
    )
    return (
        '<div style="flex:1;display:flex;gap:.8cqw;min-height:0;">'
        f'{legend}'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
        'padding-top:2.4cqw;">'
        '<div style="flex:1;position:relative;min-height:0;margin-left:3.2cqw;">'
        f'{ylabs}{badges}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'{grid}{bars}'
        f'<polyline points="{line}" fill="none" stroke="{T.DIFF_LINE}" '
        'stroke-width="1.4" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        f'</svg>{dots}</div>'
        f'<div style="flex:none;position:relative;height:1.7cqw;margin-left:3.2cqw;">'
        f'{xlabs}'
        f'<div style="position:absolute;right:-1.6cqw;top:.1cqw;font-size:0.73cqw;'
        f'color:{T.SUB};">（月）</div></div>'
        '</div></div>'
    )


def _change_point_cards(points: list) -> str:
    from . import timeline as _tl
    if not points:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">'
                '評価が大きく動いた月は検出されませんでした</div>')
    cards = []
    for i, cp in enumerate(points, 1):
        title, body = (cp.title, cp.body) if cp.title else _tl.fallback_description(cp)
        up = cp.direction == "up"
        col = T.BLUE if up else T.ACCENT_DEEP
        cards.append(
            f'<div style="flex:1;min-width:0;border:1px solid {T.CARD_LINE};'
            'border-radius:.8cqw;background:#fff;padding:.75cqw .9cqw;'
            'display:flex;flex-direction:column;gap:.4cqw;">'
            '<div style="flex:none;display:flex;align-items:center;gap:.55cqw;">'
            f'<span style="flex:none;width:1.7cqw;height:1.7cqw;border-radius:50%;'
            f'background:{T.ACCENT};color:#fff;font-size:1.04cqw;font-weight:800;'
            f'display:flex;align-items:center;justify-content:center;">{i}</span>'
            f'<span style="font-size:1.1cqw;font-weight:800;color:{T.ACCENT_DEEP};">'
            f'{escape(cp.label)}</span>'
            f'<span style="font-size:1.22cqw;font-weight:800;color:{T.INK};'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{escape(title)}</span></div>'
            f'<div style="flex:1;min-height:0;font-size:0.93cqw;line-height:1.5;'
            f'color:{T.INK};overflow:hidden;">{escape(body)}</div>'
            f'<div style="flex:none;border-top:1px dashed {T.LINE};padding-top:.35cqw;'
            'display:flex;align-items:center;gap:.45cqw;">'
            f'<span style="color:{col};font-size:1.16cqw;">{"↑" if up else "↓"}</span>'
            f'<span style="font-size:1.04cqw;font-weight:800;color:{col};">'
            f'影響：{cp.delta_pt:+.2f}pt</span></div></div>'
        )
    arrow = (f'<div style="flex:none;align-self:center;color:{T.HEAT_HIGH};'
             'font-size:1.3cqw;">▶</div>')
    return ('<div style="flex:1;display:flex;gap:.7cqw;min-height:0;">'
            + arrow.join(cards) + '</div>')


def slide4_timeline(b: dict) -> str:
    """SLIDE 4「時間軸分析」。docs/design/slide_p08.png。"""
    series = b.get("monthly_series") or []
    points = b.get("change_points") or []
    period = b.get("period_label") or ""
    n_months = len(series)
    sub = (
        '<div style="display:flex;align-items:center;justify-content:flex-end;'
        f'gap:1.6cqw;font-size:1.22cqw;color:{T.INK_SUB};flex:none;">'
        + (f'<span>分析期間：{escape(period)}（{n_months}か月）</span>' if period else "")
        + f'<span>対象：口コミ {b.get("n_reviews", 0):,} 件</span></div>'
    )
    chart_card = (
        '<div style="flex:1;border:1px solid ' + T.CARD_LINE
        + f';border-radius:{T.CARD_RADIUS};overflow:hidden;display:flex;'
        'flex-direction:column;min-height:0;">'
        + _tag_head("ポジティブ要因とネガティブ要因の推移", inset=True)
        + '<div style="flex:1;display:flex;padding:1cqw;min-height:0;">'
        + _posneg_chart(series, points) + '</div></div>'
    )
    cp_block = (
        '<div style="height:17cqw;flex:none;display:flex;flex-direction:column;'
        'gap:.7cqw;">'
        + _tag_head("主な変化点と評価変動要因")
        + '<div style="flex:1;display:flex;min-height:0;">'
        + _change_point_cards(points) + '</div></div>'
    )
    meta = f"分析期間：{period}" if period else ""
    return canvas(
        slide_header("4", "時間軸分析", meta),
        body_area(sub + chart_card + cp_block,
                  top=T.BODY_TOP_TIGHT, column=True, gap=.9),
        footer("※スコアは5点満点を−1〜+1のスケールに変換して集計",
               tagline="顧客の声を、戦略と成長へ。"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 5「空間・体験分析」— docs/design/slide_p09.png / slide_p10.png
# ═══════════════════════════════════════════════════════════════════════════
def _space_series(b: dict) -> list[tuple[str, dict, str, bool]]:
    """(凡例名, スコア, 色, 破線か) の3系列。当施設／競合平均／同業平均。"""
    from . import topic_score
    mine = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))
    peers = b.get("peer_topic_scores") or {}
    peer_avg = {}
    for t in topic_score.SPACE_TOPICS:
        vals = [p[t] for p in peers.values() if t in p]
        if vals:
            peer_avg[t] = sum(vals) / len(vals)
    out = [("当施設", mine, T.ACCENT, False)]
    if peer_avg:
        out.append(("競合平均", peer_avg, T.BLUE, True))
    # 指定競合モードでは母数＝選択競合なので overall_topic は競合平均と一致する。
    # 同じ系列を2本描いても情報が増えないので、市場比較のときだけ足す。
    if b.get("overall_topic") and b.get("comparison_scope") != "competitor":
        out.append(("同業平均", b["overall_topic"], T.SERIES_AVG, True))
    return out


def _radar(b: dict) -> str:
    """10軸のレーダーチャート（0〜5の同心リング）。"""
    import math
    from . import topic_score
    axes = [t for t in topic_score.SPACE_TOPICS
            if t in (b.get("topic_names") or [])]
    n = len(axes)
    if n < 3:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">データ不足</div>')

    # 作図は「正方形の枠」の中だけで行う。
    #   SVG を横長のカードいっぱいに置くと letterbox されて中央に寄るため、
    #   viewBox の座標と、HTML で置く軸ラベルの % がずれる（ラベルだけ
    #   外側に流れて見づらくなっていた）。正方形に固定すれば両者が一致する。
    CX, CY, R = 50.0, 50.0, 33.0
    LABEL_R = R * 1.22                 # 軸ラベルを置く半径

    def pos(i: int, v5: float, r: float = R) -> tuple[float, float]:
        a = math.radians(-90 + 360 * i / n)
        rr = r * max(0.0, min(5.0, v5)) / 5.0
        return CX + rr * math.cos(a), CY + rr * math.sin(a)

    rings = "".join(
        '<polygon points="' + " ".join(
            f"{x:.2f},{y:.2f}" for x, y in (pos(i, g) for i in range(n))
        ) + f'" fill="none" stroke="{T.LINE}" stroke-width="{.9 if g == 5 else .55}" '
        'vector-effect="non-scaling-stroke"/>'
        for g in (1, 2, 3, 4, 5)
    )
    spokes = "".join(
        f'<line x1="{CX}" y1="{CY}" x2="{pos(i, 5)[0]:.2f}" y2="{pos(i, 5)[1]:.2f}" '
        f'stroke="{T.LINE}" stroke-width=".45" vector-effect="non-scaling-stroke"/>'
        for i in range(n)
    )
    polys, marks = "", ""
    for name, sc, col, dashed in _space_series(b):
        xy = [pos(i, _score5(sc.get(t, 50.0)) or 0) for i, t in enumerate(axes)]
        # README §3：自施設だけ塗り10%、他系列は破線の線のみ
        dash = f'stroke-dasharray="{T.DASH_IND}"' if dashed else ""
        polys += (
            f'<polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in xy)}" '
            f'fill="{"none" if dashed else col}" fill-opacity="{0 if dashed else .1}" '
            f'stroke="{col}" stroke-width="{1.5 if dashed else 2.0}" '
            f'{dash} stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        )
        # 頂点は塗りつぶしの丸。この SVG は等倍スケールなので真円のまま。
        marks += "".join(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{1.1 if dashed else 1.4}" '
            f'fill="{col}"/>'
            for x, y in xy
        )
    # 目盛りは中心から上へ 0〜5。作図の邪魔にならないよう軸のすぐ左に小さく置く。
    ring_labels = "".join(
        f'<text x="{CX - 1.6:.1f}" y="{CY - R * g / 5 + .9:.1f}" font-size="2.8" '
        f'fill="{T.INK_FAINT}" text-anchor="end">{g}</text>'
        for g in (0, 1, 2, 3, 4, 5)
    )
    labels = ""
    for i, t in enumerate(axes):
        lx, ly = pos(i, 5.0, LABEL_R)
        if lx < CX - 4:                       # 左側 → 右寄せで内側に向ける
            shift, align = "-100%", "right"
        elif lx > CX + 4:                     # 右側 → 左寄せ
            shift, align = "0", "left"
        else:                                 # 真上・真下 → 中央
            shift, align = "-50%", "center"
        labels += (
            f'<div style="position:absolute;left:{lx:.1f}%;top:{ly:.1f}%;'
            f'transform:translate({shift},-50%);font-size:0.98cqw;font-weight:700;'
            f'color:{T.INK};text-align:{align};line-height:1.25;'
            f'width:8.6cqw;">{i + 1}. '
            f'{topic_tooltip(t, place=_tip_dir(lx, ly, CX, CY), b=b)}</div>'
        )
    legend = "".join(
        '<div style="display:flex;align-items:center;gap:.45cqw;font-size:1.04cqw;'
        f'font-weight:600;color:{T.INK};white-space:nowrap;">'
        f'<span style="width:1.6cqw;height:0;border-top:.22cqw '
        f'{"dashed" if dashed else "solid"} {col};display:inline-block;"></span>'
        f'<span style="width:.55cqw;height:.55cqw;border-radius:50%;'
        f'background:{col};flex:none;margin-left:-1.1cqw;"></span>'
        f'<span style="margin-left:.35cqw;">{escape(name)}</span></div>'
        for name, _sc, col, dashed in _space_series(b)
    )
    return (
        '<div style="flex:1;min-height:0;position:relative;display:flex;'
        'align-items:center;justify-content:center;">'
        # 正方形の作図領域。SVG と軸ラベルが同じ座標系になる。
        '<div style="position:relative;height:100%;aspect-ratio:1;flex:none;">'
        '<svg viewBox="0 0 100 100" style="position:absolute;inset:0;'
        'width:100%;height:100%;overflow:visible;">'
        f'{rings}{spokes}{ring_labels}{polys}{marks}</svg>'
        f'{labels}</div>'
        # 凡例は列を取らず重ねる（横幅は軸ラベルに使いたい）
        '<div style="position:absolute;right:0;bottom:0;display:flex;'
        f'flex-direction:column;gap:.4cqw;">{legend}</div></div>'
    )


def _space_table(b: dict, lo: int, hi: int) -> str:
    """評価軸テーブル（No./評価軸/当施設/競合平均/同業平均）。"""
    from . import topic_score
    series = _space_series(b)
    axes = [t for t in topic_score.SPACE_TOPICS if t in (b.get("topic_names") or [])]
    cell = "padding:.22cqw .15cqw;font-size:0.76cqw;text-align:center;"
    head = (
        f'<div style="display:flex;background:{T.TABLE_HEAD};font-weight:800;color:{T.SUB};">'
        f'<div style="width:1.7cqw;flex:none;{cell}">No.</div>'
        f'<div style="flex:2.3;{cell}">評価軸</div>'
        + "".join(
            f'<div style="flex:1;{cell}color:{col};">{escape(nm)}</div>'
            for nm, _s, col, _d in series
        )
        + '</div>'
    )
    rows = "".join(
        f'<div style="flex:1;display:flex;border-top:1px solid {T.LINE};">'
        f'<div style="width:1.7cqw;flex:none;{cell}color:{T.SUB};">{i + 1}</div>'
        # 上のレーダーの軸ラベルと同じ観点。data-t で結んでおくと、
        # どちらかを指すともう片方が光る（表の行 ↔ レーダーの角）。
        f'<div style="flex:2.3;{cell}text-align:left;color:{T.INK};overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;">'
        f'{topic_tooltip(t, place="right", b=b)}</div>'
        + "".join(
            f'<div style="flex:1;{cell}font-weight:{"800" if k == 0 else "400"};'
            f'color:{col if k == 0 else T.INK};">{_pt5(sc.get(t, 50.0))}</div>'
            for k, (_nm, sc, col, _d) in enumerate(series)
        )
        + '</div>'
        for i, t in enumerate(axes) if lo <= i + 1 <= hi
    )
    return (
        f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
        f'border:1px solid {T.CARD_LINE};border-radius:.4cqw;overflow:hidden;">'
        f'{head}{rows}</div>'
    )


def space_findings(b: dict) -> dict:
    """SLIDE 5 の要約に使う所見。すべてスコアから決定論的に出す。"""
    from . import topic_score
    mine = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))
    series = dict((nm, sc) for nm, sc, _c, _d in _space_series(b))
    base = series.get("競合平均") or series.get("同業平均") or {}
    axes = [t for t in topic_score.SPACE_TOPICS if t in mine]

    diffs = [(t, (mine[t] - base.get(t, 50.0)) / 100 * 5) for t in axes] if base else []
    diffs.sort(key=lambda z: -z[1])
    above = [t for t, d in diffs if d > 0]
    return {
        "axes": axes,
        "n_above": len(above),
        "n_axes": len(axes),
        "strong": [t for t, _ in diffs[:3]],
        "weak": [t for t, _ in diffs[-3:]][::-1],
        "diffs": dict(diffs),
        "base_label": "競合平均" if "競合平均" in series else "同業平均",
    }


def _summary_cards(b: dict) -> str:
    f = space_findings(b)
    if not f["axes"]:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">データ不足</div>')
    texts = [
        f'{f["n_axes"]}軸中{f["n_above"]}軸で<br>{f["base_label"]}を<br>上回る',
        "特に高評価：<br>" + "・<br>".join(f["strong"][:3]),
        "改善余地：<br>" + "・<br>".join(f["weak"][:3]),
        (f'{f["base_label"]}を上回る軸が<br>半数以上を占め<br>全体として優位'
         if f["n_above"] * 2 >= f["n_axes"]
         else f'{f["base_label"]}を下回る軸が<br>半数を超え<br>底上げが課題'),
    ]
    # 中身は上に詰めず、カードの中央に置く（正典もそうなっている）。
    # 番号の下には色の短い罫線を1本入れて、番号と本文を切り分ける。
    cards = "".join(
        f'<div style="flex:1;border:1px solid {c["border"]};background:{c["bg"]};'
        'border-radius:.7cqw;padding:1cqw .8cqw;display:flex;flex-direction:column;'
        'align-items:center;justify-content:center;gap:.7cqw;min-width:0;">'
        f'<span style="font-size:2.6cqw;color:{c["fg"]};line-height:1;">'
        f'{c["icon"]}</span>'
        f'<span style="font-size:2.4cqw;font-weight:800;color:{c["fg"]};'
        f'line-height:1;">{c["no"]}</span>'
        f'<span style="width:2.6cqw;height:.16cqw;background:{c["fg"]};'
        'flex:none;"></span>'
        f'<p style="margin:0;font-size:1.27cqw;line-height:1.55;color:{T.INK};'
        f'text-align:center;font-weight:700;">{txt}</p></div>'
        for c, txt in zip(T.SUMMARY_CARDS, texts)
    )
    return f'<div style="flex:1;display:flex;gap:1cqw;min-height:0;">{cards}</div>'


def slide5_space_experience(b: dict) -> str:
    """SLIDE 5「空間・体験分析」。"""
    left = panel(
        "乃村独自の空間分析指標",
        _radar(b)
        + '<div style="flex:none;display:flex;gap:.6cqw;">'
        + _space_table(b, 1, 5) + _space_table(b, 6, 10) + '</div>'
        + f'<div style="flex:none;font-size:1.07cqw;color:{T.INK_FAINT};'
        'text-align:right;padding-top:.4cqw;">'
        '※ スコアは5点満点（高いほど評価が高いことを示します）</div>',
        style="flex:1", pad=".8cqw",
    )
    body = body_area(
        f'<div style="font-size:{T.FS["slide_lead"]}cqw;font-weight:700;'
        f'color:{T.INK};flex:none;">'
        '空間と体験の質を10の観点で評価し、改善の優先ポイントを可視化します。</div>'
        '<div style="flex:1;display:flex;gap:1.4cqw;min-height:0;">'
        f'{left}'
        + panel("本ページの要約", _summary_cards(b),
                style="width:44cqw;flex:none", pad="1.2cqw")
        + '</div>',
        top=T.BODY_TOP_TIGHT, column=True, gap=.9,
    )
    return canvas(
        slide_header("5", "空間・体験分析", right=_outline_tag("confidential")),
        body, footer(score_note(b)),
    )


def _trend_badge(diff5: float) -> tuple[str, str]:
    """競合平均との差から 強み／課題／良好 を決める。"""
    if diff5 >= 0.15:
        return "強み", "強み"
    if diff5 <= -0.15:
        return "課題", "課題"
    return "良好", "良好"


def slide5_space_detail(b: dict) -> str:
    """SLIDE 5「空間体験分析（詳細）」。docs/design/slide_p10.png。"""
    from . import topic_score
    f = space_findings(b)
    axes = f["axes"]
    cols = compare_columns(b)
    mine = dict(zip(b.get("topic_names") or [], b.get("topic_values") or []))

    cell = "padding:.5cqw .15cqw;font-size:1.16cqw;text-align:center;"
    head = (
        f'<div style="display:flex;background:{T.TABLE_HEAD};flex:none;'
        f'border-bottom:1px solid {T.CARD_LINE};font-size:1.16cqw;font-weight:700;'
        f'color:{T.INK_SUB};">'
        f'<div style="width:3cqw;flex:none;{cell}">No.</div>'
        f'<div style="flex:1.8;{cell}text-align:left;padding-left:.7cqw;">評価項目</div>'
        + "".join(
            f'<div style="flex:1;{cell}'
            f'color:{T.ACCENT if i == 0 else T.INK_SUB};white-space:nowrap;">'
            f'{escape(lb)}</div>'
            for i, (lb, _n, _s, _col) in enumerate(cols)
        )
        + f'<div style="width:5.4cqw;flex:none;{cell}">傾向</div>'
        f'<div style="flex:2.4;{cell}text-align:left;padding-left:.7cqw;">'
        'ポイント</div></div>'
    )
    rows = ""
    for i, t in enumerate(axes, 1):
        d5 = f["diffs"].get(t, 0.0)
        badge, key = _trend_badge(d5)
        style = T.TREND_BADGES[key]
        point = (
            f'{f["base_label"]}を {abs(d5):.2f}pt 上回り、強みとして機能'
            if d5 >= 0.15 else
            f'{f["base_label"]}を {abs(d5):.2f}pt 下回り、改善余地あり'
            if d5 <= -0.15 else
            f'{f["base_label"]}と同水準（差 {d5:+.2f}pt）'
        )
        rows += (
            f'<div style="flex:1;display:flex;align-items:stretch;min-height:0;'
            f'border-bottom:1px solid {T.TABLE_HEAD};">'
            '<div style="width:3cqw;flex:none;display:flex;align-items:center;'
            'justify-content:center;">'
            f'<span style="width:1.7cqw;height:1.7cqw;'
            f'border-radius:50%;background:{T.ACCENT};color:#fff;font-size:1.1cqw;'
            'font-weight:700;display:flex;align-items:center;justify-content:center;">'
            f'{i}</span></div>'
            f'<div style="flex:1.8;padding:0 .7cqw;display:flex;align-items:center;'
            f'font-size:1.22cqw;font-weight:600;color:{T.INK};overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap;">{escape(t)}</div>'
            + "".join(
                '<div style="flex:1;display:flex;align-items:center;'
                'justify-content:center;'
                f'background:{T.heat_bg(_score5(sc.get(t, 50.0)), is_self=k == 0)};'
                f'color:{T.ACCENT if k == 0 else T.INK_SUB};'
                f'font-size:{"1.05" if k == 0 else ".98"}cqw;'
                f'font-weight:{800 if k == 0 else 400};">'
                f'{_pt5(sc.get(t, 50.0))}</div>'
                for k, (lb, _n, sc, _c) in enumerate(cols)
            )
            + '<div style="width:5.4cqw;flex:none;display:flex;align-items:center;'
            'justify-content:center;">'
            f'<span style="background:{style["bg"]};'
            f'color:{style["fg"]};border:1px solid {style["border"]};'
            'border-radius:.3cqw;padding:.2cqw .6cqw;font-size:1.1cqw;'
            f'font-weight:700;">{badge}</span></div>'
            f'<div style="flex:2.4;padding:0 .7cqw;display:flex;align-items:center;'
            f'font-size:1.16cqw;color:{T.INK_SUB};'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{escape(point)}</div></div>'
        )

    legend = "".join(
        '<span style="display:flex;align-items:center;gap:.35cqw;'
        f'font-size:1.12cqw;color:{T.INK_SUB};">'
        f'<span style="width:.8cqw;height:.8cqw;border-radius:50%;background:{col};">'
        f'</span>{lo:.1f}〜{hi:.1f}</span>'
        for lo, hi, col in T.SCORE_BANDS
    )
    strong = "」「".join(f["strong"][:3]) or "—"
    weak = "」「".join(f["weak"][:3]) or "—"
    summary = (
        f'<div style="flex:1;min-width:0;border:1px solid {T.BLUE_BORDER};'
        f'background:{T.BLUE_SOFT_3};border-radius:.7cqw;padding:.8cqw 1.1cqw;'
        'display:flex;gap:.9cqw;align-items:flex-start;">'
        f'<span style="width:2.2cqw;height:2.2cqw;flex:none;border-radius:50%;'
        f'background:{T.BLUE};color:#fff;display:flex;align-items:center;'
        'justify-content:center;font-size:1.32cqw;">◉</span>'
        '<div style="flex:1;min-width:0;">'
        f'<div style="font-size:1.37cqw;font-weight:800;color:{T.NAVY};'
        'margin-bottom:.35cqw;">総合サマリー</div>'
        f'<p style="margin:0;font-size:1.22cqw;line-height:1.6;color:{T.INK};">自施設は'
        f'<b style="color:{T.ACCENT};">「{escape(strong)}」</b>で優位性があります。'
        f'一方で<b style="color:{T.BLUE};">「{escape(weak)}」</b>に'
        '改善の余地が見られます。</p></div></div>'
    )

    n_fac = sum(1 for lb, _n, _s, _c in cols if not lb.endswith("平均"))
    period = b.get("period_label_scope") or b.get("period_label") or ""
    lead = (
        '<div style="display:flex;align-items:center;justify-content:space-between;'
        'gap:1.4cqw;flex:none;">'
        f'<span style="font-size:{T.FS["slide_lead"]}cqw;font-weight:700;'
        f'color:{T.INK};">空間と体験の質を10の視点で評価し、'
        '改善の優先ポイントを可視化します。</span>'
        f'<span style="font-size:1.22cqw;color:{T.INK_SUB};white-space:nowrap;">'
        f'分析対象：{n_fac}施設'
        + (f'　｜　分析期間：{escape(period)}' if period else "")
        + '</span></div>'
    )
    legend_card = (
        f'<div style="width:26cqw;flex:none;border:1px solid {T.CARD_LINE};'
        'border-radius:.7cqw;padding:.8cqw 1.1cqw;display:flex;flex-direction:column;'
        'justify-content:center;gap:.5cqw;">'
        f'<span style="font-size:1.27cqw;font-weight:700;color:{T.NAVY};">'
        'スコアの見方（5点満点）</span>'
        f'<div style="display:flex;flex-wrap:wrap;gap:.5cqw 1cqw;">{legend}</div></div>'
    )
    body = body_area(
        lead
        + panel("施設別スコアヒートマップ（10項目）",
                f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;">'
                f'{head}{rows}</div>', pad="0")
        + '<div style="height:8cqw;flex:none;display:flex;gap:1.2cqw;">'
        + summary + legend_card + '</div>',
        top=T.BODY_TOP_TIGHT, column=True, gap=.8,
    )
    return canvas(
        slide_header("5", "空間体験分析", sub_title="詳細",
                     right=_pill("プランナー起点")),
        body,
        footer(score_note(b), tagline="顧客の声を、戦略と成長へ。"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 6「特徴的な口コミ」— docs/design/slide_p11.png
# ═══════════════════════════════════════════════════════════════════════════
def _voice_card(v, style: dict) -> str:
    """4象限カード1枚。

    上段に **要約（1行）**、下段に **口コミの生データをそのまま小さく** 載せる。
    要約だけだと「本当にそう書いてあるのか」を確かめられないので、必ず原文を
    併記する。原文は一字も変えない（長くて入り切らないぶんは枠で切れる）。
    """
    if not v.quote and not v.raw:
        return (
            f'<div style="border:1px solid {style["border"]};background:{style["bg"]};'
            'border-radius:.9cqw;padding:1.2cqw 1.4cqw;display:flex;gap:1.2cqw;'
            'min-width:0;min-height:0;">'
            f'<span style="width:5.4cqw;height:5.4cqw;flex:none;border-radius:50%;'
            f'background:{style["icon_bg"]};color:{style["fg"]};display:flex;'
            f'align-items:center;justify-content:center;font-size:2.4cqw;">'
            f'{style["icon"]}</span>'
            '<div style="flex:1;display:flex;flex-direction:column;min-width:0;">'
            f'<div style="font-size:1.5cqw;font-weight:800;color:{style["fg"]};'
            f'margin-bottom:.5cqw;">{escape(v.quadrant)}</div>'
            f'<p style="margin:0;flex:1;color:{T.SUB};font-size:1.1cqw;">'
            'この観点に該当する口コミは見つかりませんでした</p></div></div>'
        )

    chips = "".join(
        f'<span style="background:#fff;border:1px solid {style["border"]};'
        'border-radius:.4cqw;padding:.22cqw .7cqw;font-size:.92cqw;'
        f'color:{T.INK_SUB};white-space:nowrap;">{escape(c)}</span>'
        for c in v.chips
    )
    stars = (f'<span style="font-size:.95cqw;">{_stars(v.rating, size=.95)}</span>'
             if v.rating else "")

    # 生データ。要約と見分けがつくよう、白地の枠に入れて一段小さく組む。
    raw_block = (
        f'<div style="flex:1;min-height:0;overflow:hidden;background:#fff;'
        f'border:1px solid {style["border"]};border-radius:.5cqw;'
        'padding:.6cqw .8cqw;margin-top:.5cqw;">'
        '<div style="display:flex;align-items:center;gap:.5cqw;'
        'margin-bottom:.3cqw;">'
        f'<span style="font-size:.85cqw;font-weight:700;color:{T.INK_FAINT};">'
        '口コミ原文</span>'
        f'{stars}</div>'
        f'<p style="margin:0;font-size:.92cqw;line-height:1.55;color:{T.INK_SUB};'
        f'word-break:break-all;">{escape(v.raw)}</p></div>'
        if v.raw else ""
    )
    return (
        f'<div style="border:1px solid {style["border"]};background:{style["bg"]};'
        'border-radius:.9cqw;padding:1cqw 1.2cqw;display:flex;gap:1cqw;'
        'min-width:0;min-height:0;">'
        f'<span style="width:4.6cqw;height:4.6cqw;flex:none;border-radius:50%;'
        f'background:{style["icon_bg"]};color:{style["fg"]};display:flex;'
        f'align-items:center;justify-content:center;font-size:2.1cqw;">'
        f'{style["icon"]}</span>'
        '<div style="flex:1;display:flex;flex-direction:column;min-width:0;">'
        f'<div style="font-size:1.4cqw;font-weight:800;color:{style["fg"]};'
        f'flex:none;">{escape(v.quadrant)}</div>'
        # 要約（見出し）
        f'<p style="margin:.3cqw 0 0;flex:none;font-size:1.25cqw;font-weight:700;'
        f'line-height:1.45;color:{T.INK};">{escape(v.quote)}</p>'
        # 生データ
        f'{raw_block}'
        + (f'<div style="display:flex;gap:.6cqw;min-width:0;flex:none;'
           f'margin-top:.5cqw;">{chips}</div>' if chips else "")
        + '</div></div>'
    )


def slide6_voices(b: dict) -> str:
    """SLIDE 6「特徴的な口コミ」。"""
    from . import voices as _v
    vs = b.get("voices") or _v.pick_fallback([])
    period = b.get("period_label") or ""
    meta = f"分析期間：{period}" if period else ""

    cards = "".join(
        _voice_card(v, T.QUADRANT_CARDS.get(v.quadrant, T.QUADRANT_CARDS["維持すべき価値"]))
        for v in vs
    )
    # 生成した箇所は必ず明示する（口コミに書かれた事実と区別できるように）
    estimated = any(getattr(v, "estimated", False) and v.chips for v in vs)
    summarized = any(getattr(v, "summarized", False) for v in vs)
    note = "※上記は代表的なご意見（N=1）です。原文はそのまま掲載しています"
    if summarized:
        note += "／見出しは生成AIによる要約です"
    if estimated:
        note += "／属性は口コミ本文からの推定です"
    body = body_area(
        f'<div style="font-size:{T.FS["slide_lead"]}cqw;font-weight:700;'
        f'color:{T.INK};flex:none;">'
        '実際の来場者のリアルな声から、維持すべき価値や改善のヒント、'
        '未来の企画につながる声を整理しました。</div>'
        '<div style="flex:1;display:grid;grid-template-columns:1fr 1fr;'
        f'grid-template-rows:1fr 1fr;gap:1.2cqw;min-height:0;">{cards}</div>',
        top=T.BODY_TOP_TIGHT, column=True, gap=1.0,
    )
    return canvas(
        slide_header("6", "特徴的な口コミ", meta), body,
        footer(note, tagline="利用しやすいアウトプット構成（プランナー起点）"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 7「ディスカッションポイント」— docs/design/slide_p12.png
#   （PDF のページ番号は 8 だが、構成上は 7 が正）
# ═══════════════════════════════════════════════════════════════════════════
def _prio_badge(p: str) -> str:
    col = T.ACCENT if p == "高" else T.TREND_BADGES["良好"]["fg"]
    return (
        f'<span style="display:inline-block;background:{col};color:#fff;'
        'border-radius:.7cqw;padding:.12cqw .7cqw;font-size:0.76cqw;'
        f'font-weight:800;white-space:nowrap;">優先度：{escape(p)}</span>'
    )


def _issue_table(issues: list) -> str:
    from . import discussion as _d
    if not issues:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">'
                '課題を抽出できるデータがありません</div>')
    cell = "padding:.55cqw .7cqw;font-size:0.9cqw;"
    head = (
        f'<div style="display:flex;background:{T.NAVY};color:#fff;'
        'font-size:1.3cqw;font-weight:700;flex:none;">'
        + "".join(
            f'<div style="flex:{w};padding:.7cqw 1cqw;text-align:center;'
            + (f'border-right:1px solid {T.NAVY_LINE};' if i < 3 else "")
            + f'">{escape(h)}</div>'
            for i, (h, w) in enumerate((("課題", "1.5"), ("根拠", "2"),
                                        ("企画仮説", "2"), ("対応領域", "1.6")))
        )
        + '</div>'
    )
    rows = ""
    for i, iss in enumerate(issues, 1):
        ev, hyp, doms = (iss.evidence, iss.hypothesis, iss.domains)
        if not hyp:
            ev, hyp, doms = _d.fallback_texts(iss)
        tags = "".join(
            f'<div style="display:flex;align-items:center;gap:.35cqw;'
            f'color:{T.ACCENT_DEEP};font-size:0.9cqw;font-weight:700;'
            'margin-bottom:.3cqw;">'
            f'<span style="font-size:0.98cqw;">◆</span>{escape(d)}</div>'
            for d in (doms or ["—"])
        )
        rows += (
            f'<div style="flex:1;display:flex;border-top:1px solid {T.LINE};">'
            # 課題
            f'<div style="flex:1.5;{cell}display:flex;flex-direction:column;'
            'gap:.35cqw;justify-content:center;">'
            '<div style="display:flex;align-items:center;gap:.5cqw;">'
            f'<span style="flex:none;width:1.5cqw;height:1.5cqw;border-radius:50%;'
            f'background:{T.ACCENT};color:#fff;font-size:0.88cqw;font-weight:800;'
            f'display:flex;align-items:center;justify-content:center;">{i}</span>'
            f'<span style="font-size:1.12cqw;font-weight:800;color:{T.INK};">'
            f'{escape(iss.title)}</span></div>'
            f'<div>{_prio_badge(iss.priority)}</div></div>'
            # 根拠（1行目は必ず実測スコア）
            f'<div style="flex:2;{cell}display:flex;flex-direction:column;'
            f'gap:.25cqw;justify-content:center;color:{T.INK};line-height:1.5;">'
            f'<div>・{escape(iss.score_line)}</div>'
            + (f'<div>・{escape(ev)}</div>' if ev else "")
            + '</div>'
            # 企画仮説
            f'<div style="flex:2;{cell}display:flex;align-items:center;'
            f'color:{T.INK};line-height:1.55;">{escape(hyp)}</div>'
            # 対応領域
            f'<div style="flex:1.5;{cell}display:flex;flex-direction:column;'
            f'justify-content:center;">{tags}</div></div>'
        )
    return (
        f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;'
        f'border:1px solid {T.CARD_LINE};border-radius:.7cqw;overflow:hidden;">'
        f'{head}{rows}</div>'
    )


def _priority_matrix(actions: list) -> str:
    """インパクト × 実現しやすさ の4象限。"""
    if not actions:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.04cqw;">'
                '打ち手がありません</div>')
    # (ラベル, 左半分か, 上半分か, 背景)
    # README §3「2×2。右上のみ #FDF2F6 で強調」
    quads = (
        ("中期で検討", True, True, "#fff"),
        ("優先的に着手", False, True, T.ACCENT_SOFT_2),
        ("検討優先度 低", True, False, "#fff"),
        ("短期で着手", False, False, "#fff"),
    )
    zones = "".join(
        f'<div style="position:absolute;left:{2 if left else 50}%;'
        f'top:{2 if top else 50}%;width:48%;height:48%;background:{bg};"></div>'
        for _lab, left, top, bg in quads
    )
    # ラベルは各象限の外側の角へ。中央付近はプロット点が来るので空けておく。
    labels = "".join(
        '<div style="position:absolute;'
        + (f'left:3%;' if left else 'right:3%;')
        + (f'top:3%;' if top else 'bottom:3%;')
        + f'font-size:0.81cqw;font-weight:800;white-space:nowrap;'
        f'color:{T.ACCENT if lab == "優先的に着手" else T.INK_FAINT};">'
        f'{escape(lab)}</div>'
        for lab, left, top, _bg in quads
    )
    # 象限を分ける破線（正典は 2×2 の十字）
    split = (
        f'<div style="position:absolute;left:50%;top:0;bottom:0;width:0;'
        f'border-left:1px dashed {T.CARD_LINE};"></div>'
        f'<div style="position:absolute;top:50%;left:0;right:0;height:0;'
        f'border-top:1px dashed {T.CARD_LINE};"></div>'
    )
    # 近い位置に重なるとラベルが読めなくなるので、既に置いた点から離す
    placed: list[tuple[float, float]] = []
    dots = ""
    for i, a in enumerate(actions, 1):
        px = 6 + a.feasibility * 86
        py = 92 - a.impact * 80
        # 上限に達したら諦める（回数を切らないと py が下限で止まって無限ループする）
        for _ in range(len(actions)):
            if not any(abs(px - qx) < 12 and abs(py - qy) < 7 for qx, qy in placed):
                break
            py -= 7.5
            if py < 6.0:
                py = 6.0
                break
        placed.append((px, py))
        dots += (
            f'<div style="position:absolute;left:{px:.1f}%;top:{py:.1f}%;'
            'transform:translate(-50%,-50%);display:flex;align-items:center;'
            'gap:.35cqw;white-space:nowrap;">'
            f'<span style="flex:none;width:1.2cqw;height:1.2cqw;border-radius:50%;'
            f'border:1.6px solid {T.ACCENT};background:#fff;color:{T.ACCENT_DEEP};'
            'font-size:0.73cqw;font-weight:800;display:flex;align-items:center;'
            f'justify-content:center;">{i}</span>'
            f'<span style="font-size:0.81cqw;font-weight:700;color:{T.INK};">'
            f'{escape(_clip_name(a.title, 10))}</span></div>'
        )
    return (
        '<div style="flex:1;display:flex;min-height:0;">'
        f'<div style="flex:none;width:1.6cqw;display:flex;align-items:center;">'
        + vertical_text("インパクト", size=.62, weight=700) + '</div>'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        f'<div style="flex:1;position:relative;min-height:0;border-left:1px solid '
        f'{T.INK_SUB};border-bottom:1px solid {T.INK_SUB};">'
        f'{zones}{split}{labels}{dots}</div>'
        '<div style="flex:none;display:flex;justify-content:space-between;'
        f'font-size:1.07cqw;color:{T.INK_SUB};margin-top:.2cqw;">'
        '<span>低</span><span style="font-weight:700;">実現しやすさ</span>'
        '<span>高</span></div>'
        + _matrix_legend() + '</div></div>'
    )


def _matrix_legend() -> str:
    """優先度マトリクスの凡例（正典 ReviewLens.dc.html:745）。"""
    return (
        '<div style="flex:none;display:flex;justify-content:center;gap:1.4cqw;'
        'flex-wrap:wrap;padding-top:.5cqw;">'
        + "".join(
            '<span style="display:flex;align-items:center;gap:.4cqw;'
            f'font-size:1.07cqw;color:{T.INK_SUB};">'
            f'<span style="width:.9cqw;height:.9cqw;border-radius:50%;'
            f'border:1.5px solid {col};"></span>{escape(lab)}</span>'
            for lab, col in T.MATRIX_LEGEND
        )
        + '</div>'
    )


def _action_cards(actions: list) -> str:
    if not actions:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:1.04cqw;">'
                '打ち手がありません</div>')
    items = "".join(
        f'<div style="flex:1;min-height:0;display:flex;gap:.7cqw;'
        f'border-bottom:1px solid {T.LINE};padding:.4cqw 0;">'
        '<div style="flex:none;display:flex;flex-direction:column;'
        'align-items:flex-start;gap:.3cqw;width:8.4cqw;">'
        '<div style="display:flex;align-items:center;gap:.35cqw;">'
        f'<span style="width:1.4cqw;height:1.4cqw;border-radius:50%;'
        f'background:{T.ACCENT};color:#fff;font-size:0.83cqw;font-weight:800;'
        f'display:flex;align-items:center;justify-content:center;">{i}</span>'
        f'<span style="font-size:0.93cqw;font-weight:800;color:{T.INK};'
        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
        f'max-width:6.2cqw;">{escape(_clip_name(a.title, 9))}</span></div>'
        f'{_prio_badge(a.priority)}</div>'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
        'justify-content:center;gap:.15cqw;">'
        + "".join(
            f'<div style="font-size:0.83cqw;color:{T.INK};overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap;">・{escape(bl)}</div>'
            for bl in (a.bullets or ["—"])
        )
        + '</div></div>'
        for i, a in enumerate(actions, 1)
    )
    return f'<div style="flex:1;display:flex;flex-direction:column;">{items}</div>'


def slide7_discussion(b: dict) -> str:
    """SLIDE 7「ディスカッションポイント」。docs/design/slide_p12.png。"""
    from . import discussion as _d
    issues = b.get("issues") or []
    actions = b.get("actions") or (_d.fallback_actions(issues) if issues else [])
    period = b.get("period_label") or ""
    meta = f"分析期間：{period}" if period else ""
    generated = any(getattr(i, "hypothesis", "") for i in issues)

    body = body_area(
        f'<div style="flex:1.15;min-height:0;display:flex;">{_issue_table(issues)}</div>'
        '<div style="flex:1;display:flex;gap:1.2cqw;min-height:0;">'
        + panel("優先度マトリクス（インパクト × 実現しやすさ）",
                _priority_matrix(actions), head_size=1.25, pad=".8cqw")
        + panel("打ち手アクション（優先施策）", _action_cards(actions),
                head_size=1.25, pad="0")
        + '</div>',
        top=7.2, column=True, gap=1.0,
    )
    note = "※スコアは5点満点。優先度とインパクトは実測の差から算出しています"
    if generated:
        note += "／企画仮説・打ち手は生成AIによる提案です"
    return canvas(slide_header("7", "ディスカッションポイント", meta), body,
                  footer(note))


# ═══════════════════════════════════════════════════════════════════════════
# 冒頭「本レポートのご利用にあたって」— PDF には無いが、公開口コミを扱う以上
# 免責は必ず先頭に置く。文面は config.DISCLAIMER_* を唯一の出典とする。
# ═══════════════════════════════════════════════════════════════════════════
def slide0_disclaimer(b: dict) -> str:
    from . import config
    rows = "".join(
        '<div style="flex:1;display:flex;gap:1cqw;align-items:center;">'
        f'<span style="flex:none;width:2.4cqw;height:2.4cqw;border-radius:50%;'
        f'background:{T.ACCENT_SOFT};color:{T.ACCENT};font-weight:800;'
        'font-size:1.35cqw;display:flex;align-items:center;justify-content:center;">'
        f'{i}</span>'
        f'<span style="flex:1;font-size:1.45cqw;line-height:1.6;color:{T.INK};">'
        f'{escape(p)}</span></div>'
        for i, p in enumerate(config.DISCLAIMER_POINTS, 1)
    )
    body = body_area(
        f'<div style="flex:none;font-size:{T.FS["slide_lead"]}cqw;font-weight:700;'
        f'color:{T.INK};">本レポートをご覧いただく前に、以下をご確認ください。</div>'
        f'<div style="flex:1;min-height:0;background:{T.TABLE_HEAD};'
        f'border:1px solid {T.CARD_LINE};border-radius:{T.CARD_RADIUS};'
        f'padding:1.2cqw 1.8cqw;display:flex;flex-direction:column;">{rows}</div>'
        f'<div style="flex:none;font-size:{T.FS["note"]}cqw;color:{T.INK_FAINT};">'
        f'データ基準日: {escape(b.get("date", ""))}'
        '　／　本レポートは参考情報です（Voice BAUM）</div>',
        top=T.BODY_TOP_TIGHT, column=True, gap=.9,
    )
    return canvas(
        slide_header("!", config.DISCLAIMER_TITLE, "免責事項"), body, footer(""),
    )


# ═══════════════════════════════════════════════════════════════════════════
# レポートの構成
# ═══════════════════════════════════════════════════════════════════════════
#   「（詳細）」の3枚は、プランナー向けの掘り下げページ。
#   相手や場面によっては要らないので、出す／出さないを選べるようにしてある。
DETAIL_SLIDES = (
    "slide2_market_detail",       # 市場内ポジション（詳細）
    "slide3_competitor_detail",   # 指定競合との比較（詳細）
    "slide5_space_detail",        # 空間体験分析（詳細）
)

# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 8「体験満足度（NMSI）」— 計算済みのときだけ出る
#   22観点スコア（キーワード＋TF-IDF）とは別の指標。同じ5点満点ではないので、
#   並べて「どっちが正しい」と読まれないよう、注記で棲み分けを明示する。
# ═══════════════════════════════════════════════════════════════════════════
_PHASE_JA = {
    "pre_visit": "来訪前", "arrival": "到着", "exhibition": "展示",
    "experience": "体験", "show_interaction": "ショー・交流",
    "food_retail": "飲食・物販", "exit_reflection": "退出・振り返り",
}


def slide8_nmsi(b: dict) -> str:
    """来場体験の満足度（NMSI）。b["nmsi"] が無ければ空文字を返す。"""
    n = b.get("nmsi")
    if not n:
        return ""

    score = float(n.get("nmsi") or 0.0)
    interp = str(n.get("interpretation") or "")
    summary = n.get("summary") or {}
    phases = [p for p in (n.get("phases") or []) if p.get("文数")]

    # 大きな数字（左）
    gauge_w = 12.0
    big = (
        f'<div style="width:{gauge_w}cqw;flex:none;display:flex;'
        'flex-direction:column;justify-content:center;align-items:center;'
        f'border-right:1px solid {T.LINE};padding-right:1.2cqw;">'
        f'<div style="font-size:1.05cqw;font-weight:800;color:{T.INK_MUTE};'
        'letter-spacing:.06em;">NMSI</div>'
        f'<div style="font-size:5.2cqw;font-weight:800;color:{T.ACCENT};'
        'line-height:1.05;font-variant-numeric:tabular-nums;">'
        f'{score:.1f}</div>'
        f'<div style="font-size:1cqw;color:{T.INK_FAINT};">/ 100</div>'
        f'<div style="font-size:1.25cqw;font-weight:700;color:{T.INK};'
        f'text-align:center;margin-top:.5cqw;">{escape(interp)}</div></div>'
    )

    # フェーズ別の帯
    rows = ""
    for p in phases:
        key = str(p.get("phase", ""))
        name = _PHASE_JA.get(key, str(p.get("フェーズ", key)))
        eff = float(p.get("E_i") or 0.0)          # -1〜+1
        w = float(p.get("重み") or 0.0)
        cnt = int(p.get("文数") or 0)
        # 中央を 50% に置いて、正負で左右に伸ばす
        half = abs(eff) * 50.0
        left = 50.0 - half if eff < 0 else 50.0
        col = T.ACCENT if eff >= 0 else T.BLUE
        rows += (
            '<div style="display:flex;align-items:center;gap:.6cqw;'
            'padding:.32cqw 0;">'
            f'<div style="width:7.6cqw;flex:none;font-size:1.02cqw;'
            f'font-weight:700;color:{T.INK};">{escape(name)}</div>'
            f'<div style="width:3.2cqw;flex:none;font-size:.92cqw;'
            f'color:{T.INK_FAINT};text-align:right;">重み{w * 100:.0f}%</div>'
            f'<div style="flex:1;position:relative;height:1.75cqw;'
            f'background:{T.LINE};'
            'border-radius:.25cqw;">'
            f'<div style="position:absolute;left:50%;top:0;bottom:0;'
            f'width:1px;background:{T.INK_FAINT};"></div>'
            f'<div style="position:absolute;left:{left:.2f}%;top:.18cqw;'
            f'bottom:.18cqw;width:{half:.2f}%;background:{col};'
            'border-radius:.2cqw;"></div></div>'
            f'<div style="width:3.4cqw;flex:none;font-size:.95cqw;'
            f'color:{T.INK_SUB};text-align:right;'
            f'font-variant-numeric:tabular-nums;">{eff:+.2f}</div>'
            f'<div style="width:3.6cqw;flex:none;font-size:.88cqw;'
            f'color:{T.INK_FAINT};text-align:right;">{cnt:,}文</div></div>'
        )

    chart = (
        '<div style="flex:1;display:flex;flex-direction:column;'
        'padding-left:1.2cqw;min-width:0;">'
        f'<div style="flex:none;font-size:1.05cqw;font-weight:800;color:{T.ACCENT};'
        'margin-bottom:.5cqw;">フェーズ別の効果（左=ネガティブ／右=ポジティブ）</div>'
        # 行は残りの高さに均等に配る。中央寄せにすると上下に死んだ余白が残る。
        '<div style="flex:1;display:flex;flex-direction:column;'
        f'justify-content:space-evenly;min-height:0;">{rows}</div></div>'
    )

    # 補正の内訳
    def _corr(label: str, key: str, sign: str) -> str:
        v = summary.get(key)
        v = float(v) if isinstance(v, (int, float)) else 0.0
        return (
            '<div style="flex:1;border:1px solid ' + T.CARD_LINE
            + f';border-radius:{T.CARD_RADIUS};padding:.6cqw .8cqw;'
            'background:#fff;text-align:center;">'
            f'<div style="font-size:.92cqw;color:{T.INK_MUTE};'
            f'font-weight:700;">{escape(label)}</div>'
            f'<div style="font-size:1.7cqw;font-weight:800;color:{T.INK};'
            f'line-height:1.2;font-variant-numeric:tabular-nums;">'
            f'{sign}{v:.2f}</div></div>'
        )

    corr = (
        '<div style="flex:none;display:flex;gap:.8cqw;margin-top:.8cqw;">'
        + _corr("記憶に残ったか", "記憶補正_M", "+")
        + _corr("再訪・推奨", "再訪推奨補正_R", "+")
        + _corr("摩擦（待ち・混雑ほか）", "摩擦補正_F", "−")
        + '</div>'
    )

    n_sent = int(n.get("n_sentences") or 0)
    return canvas(
        slide_header("8", "体験満足度", f"対象：口コミ本文 {n_sent:,} 文",
                     sub_title="来場体験を7フェーズに分けた満足度指標"),
        body_area(
            f'<div style="flex:1;display:flex;flex-direction:column;min-height:0;">'
            f'<div style="flex:1;display:flex;min-height:0;">{big}{chart}</div>'
            f'{corr}</div>',
            column=True),
        footer(
            "※NMSI は 0〜100。22観点スコア（5点満点）とは別の指標で、"
            "算出方法が違うため直接は比較できません",
            tagline="顧客の声を、戦略と成長へ。"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 9「このデータについて」— 分母と誤差を最後に置く
#   本編は「4.50」のような数字を並べて順位をつける。それが4件から出たのか
#   5,877件から出たのかを示さないと、順位だけが独り歩きする。
# ═══════════════════════════════════════════════════════════════════════════
# 言語内訳の色。日本語＝アクセント、外側へ行くほど淡く。
_LANG_COLORS = {
    "日本語": T.ACCENT,
    "和欧混在": T.BAR_PINK,
    "日本語以外": T.BLUE,
    "記号・数字のみ": T.BAR_BLUE,
    "本文なし": T.LINE,
}


def _funnel_rows(r: dict) -> str:
    """全件からどう減るか。棒の長さは全件に対する比。"""
    total = max(int(r.get("total") or 0), 1)
    steps = [
        ("口コミ 全件", r.get("total"), T.INK_FAINT),
        ("本文あり", r.get("with_text"), T.SERIES_AVG),
        ("日本語（混在含む）", r.get("japanese"), T.BAR_PINK),
        ("観点判定に使えた", r.get("usable"), T.ACCENT),
    ]
    out = ""
    for label, v, col in steps:
        n = int(v or 0)
        pct = n / total
        out += (
            '<div style="display:flex;align-items:center;gap:.7cqw;'
            'padding:.42cqw 0;">'
            f'<div style="width:9.4cqw;flex:none;font-size:1.02cqw;'
            f'font-weight:700;color:{T.INK};">{escape(label)}</div>'
            f'<div style="flex:1;height:1.6cqw;background:{T.LINE};'
            'border-radius:.25cqw;overflow:hidden;">'
            f'<div style="height:100%;width:{pct * 100:.1f}%;background:{col};'
            'border-radius:.25cqw;"></div></div>'
            f'<div style="width:4.6cqw;flex:none;text-align:right;'
            f'font-size:1.12cqw;font-weight:800;color:{T.INK};'
            f'font-variant-numeric:tabular-nums;">{n:,}</div>'
            f'<div style="width:3.2cqw;flex:none;text-align:right;'
            f'font-size:.92cqw;color:{T.INK_FAINT};">{pct:.0%}</div></div>'
        )
    return out


def _lang_bar(r: dict) -> str:
    """本文の言語内訳。合計は必ず全件に一致する。"""
    mix = [(k, int(v or 0)) for k, v in (r.get("language_mix") or []) if v]
    total = sum(v for _k, v in mix)
    if not total:
        return ""
    seg = "".join(
        f'<div style="width:{v / total * 100:.2f}%;background:'
        f'{_LANG_COLORS.get(k, T.LINE)};" title="{escape(k)} {v:,}"></div>'
        for k, v in mix
    )
    legend = "".join(
        '<span style="display:inline-flex;align-items:center;gap:.35cqw;'
        'margin-right:1cqw;white-space:nowrap;font-size:.92cqw;">'
        f'<span style="width:.9cqw;height:.9cqw;border-radius:.15cqw;'
        f'background:{_LANG_COLORS.get(k, T.LINE)};flex:none;"></span>'
        f'<span style="color:{T.INK_SUB};">{escape(k)}</span>'
        f'<b style="color:{T.INK};font-variant-numeric:tabular-nums;">'
        f'{"<1%" if 0 < v / total < 0.005 else f"{v / total:.0%}"}</b></span>'
        for k, v in mix
    )
    return (
        f'<div style="display:flex;height:1.9cqw;border-radius:.3cqw;'
        f'overflow:hidden;border:1px solid {T.CARD_LINE};">{seg}</div>'
        f'<div style="margin-top:.6cqw;line-height:1.9;">{legend}</div>'
    )


def _ci_row(label: str, value: float | None, lo: float | None,
            hi: float | None, *, lo_end: float, hi_end: float,
            fmt: str = "{:.2f}") -> str:
    """点推定と95%信頼区間を1本の目盛りの上に置く。"""
    if value is None or lo is None or hi is None:
        return ""
    span = max(hi_end - lo_end, 1e-9)
    x = lambda v: max(0.0, min(100.0, (v - lo_end) / span * 100))  # noqa: E731
    return (
        '<div style="padding:.5cqw 0;">'
        '<div style="display:flex;justify-content:space-between;'
        'align-items:baseline;margin-bottom:.3cqw;">'
        f'<span style="font-size:1.02cqw;font-weight:700;color:{T.INK};">'
        f'{escape(label)}</span>'
        f'<span style="font-size:1.02cqw;color:{T.INK_SUB};'
        'font-variant-numeric:tabular-nums;">'
        f'<b style="color:{T.ACCENT};font-size:1.25cqw;">{fmt.format(value)}</b>'
        f'　95%CI {fmt.format(lo)} – {fmt.format(hi)}</span></div>'
        f'<div style="position:relative;height:1.1cqw;background:{T.LINE};'
        'border-radius:.2cqw;">'
        # 区間の帯。件数が多いと区間は正しく細くなるが、目盛り上で消えると
        # 「描けていない」ように見えるので下限を置く。
        f'<div style="position:absolute;left:{x(lo):.2f}%;'
        f'width:{max(x(hi) - x(lo), 1.6):.2f}%;top:.2cqw;bottom:.2cqw;'
        f'background:{T.BAR_PINK};border-radius:.15cqw;"></div>'
        # 両端のキャップ。幅が最小に張り付いたときでも「区間である」と分かる。
        f'<div style="position:absolute;left:{x(lo):.2f}%;top:0;bottom:0;'
        f'width:.14cqw;background:{T.BAR_PINK};transform:translateX(-50%);'
        '"></div>'
        f'<div style="position:absolute;left:{x(hi):.2f}%;top:0;bottom:0;'
        f'width:.14cqw;background:{T.BAR_PINK};transform:translateX(-50%);'
        '"></div>'
        f'<div style="position:absolute;left:{x(value):.2f}%;top:-.15cqw;'
        f'bottom:-.15cqw;width:.26cqw;background:{T.ACCENT};'
        'transform:translateX(-50%);border-radius:.1cqw;"></div>'
        '</div>'
        # 目盛りの両端を書く。何のスケール上に置かれているかが分からないと
        # 帯の細さが読めない。
        '<div style="display:flex;justify-content:space-between;'
        f'font-size:.82cqw;color:{T.INK_FAINT};margin-top:.1cqw;">'
        f'<span>{fmt.format(lo_end)}</span><span>{fmt.format(hi_end)}</span>'
        '</div></div>'
    )


def slide9_data_quality(b: dict) -> str:
    """このデータについて。r が無い、または口コミ0件なら出さない。"""
    r = b.get("reliability")
    if not r or not int(r.get("total") or 0):
        return ""

    total = int(r["total"])
    usable = int(r.get("usable") or 0)

    left = panel(
        "分析に使えた口コミ",
        f'<div style="flex:1;display:flex;flex-direction:column;'
        f'justify-content:space-evenly;min-height:0;">{_funnel_rows(r)}</div>'
        f'<div style="flex:none;font-size:.95cqw;color:{T.INK_FAINT};'
        'padding-top:.5cqw;">'
        f'全 {total:,} 件のうち、観点の判定に使えたのは '
        f'<b style="color:{T.ACCENT};">{usable:,} 件（{r.get("usable_rate", 0):.0%}）</b>。'
        f'本編のスコアはこの {usable:,} 件から出ています。</div>',
        style="flex:1.15", pad=".9cqw",
    )

    lang = _lang_bar(r)
    ci = (
        _ci_row("平均星評価", r.get("rating_mean"), r.get("rating_lo"),
                r.get("rating_hi"), lo_end=1.0, hi_end=5.0)
        + _ci_row("ポジティブ率", r.get("pos_rate"), r.get("pos_lo"),
                  r.get("pos_hi"), lo_end=0.0, hi_end=1.0, fmt="{:.0%}")
    )

    right = panel(
        "本文の言語と、数値の幅",
        f'<div style="flex:none;">'
        f'<div style="font-size:1cqw;font-weight:800;color:{T.ACCENT};'
        'margin-bottom:.45cqw;">本文の言語</div>'
        f'{lang}</div>'
        f'<div style="flex:1;display:flex;flex-direction:column;'
        'justify-content:center;min-height:0;">'
        f'<div style="font-size:1cqw;font-weight:800;color:{T.ACCENT};'
        'margin-bottom:.2cqw;">95%信頼区間</div>'
        f'{ci}</div>',
        style="flex:1", pad=".9cqw",
    )

    notes = [f["text"] for f in (r.get("flags") or [])]
    warn = ""
    if notes:
        warn = (
            f'<div style="flex:none;border:1.5px solid {T.ACCENT};'
            f'background:{T.ACCENT_SOFT};border-radius:{T.CARD_RADIUS};'
            'padding:.7cqw 1cqw;margin-top:.8cqw;">'
            + "".join(
                f'<div style="font-size:1.02cqw;color:{T.INK};'
                'line-height:1.5;">▲ ' + escape(t) + '</div>'
                for t in notes[:3])
            + '</div>'
        )

    return canvas(
        slide_header("9", "このデータについて",
                     f"全 {total:,} 件 ／ 分析に使えた {usable:,} 件",
                     sub_title="スコアの分母と、数値の幅"),
        body_area(
            '<div style="flex:1;display:flex;flex-direction:column;min-height:0;">'
            '<div style="flex:1;display:flex;gap:1.2cqw;min-height:0;">'
            f'{left}{right}</div>{warn}</div>', column=True),
        footer("※信頼区間は口コミ単位の95%区間。比率は Wilson score interval",
               tagline="顧客の声を、戦略と成長へ。"),
    )


_ALL_SLIDES = (
    "slide1_facility_info",
    "slide2_market_position",
    "slide2_market_detail",
    "slide3_competitor_compare",
    "slide3_competitor_detail",
    "slide4_timeline",
    "slide5_space_experience",
    "slide5_space_detail",
    "slide6_voices",
    "slide7_discussion",
)

# 条件つきで増える枚。データが無ければ出ないので _ALL_SLIDES には入れない
# （report_slides() の「10枚 / 7枚」という契約を動かさないため）。
OPTIONAL_SLIDES = ("slide8_nmsi", "slide9_data_quality")


def report_slides(*, detail: bool = True) -> list:
    """レポートに載せるスライド描画関数を順番に返す。

    detail=False なら「（詳細）」の3枚を外す（10枚 → 7枚）。
    免責（slide0_disclaimer）は別枠なのでここには含めない。
    """
    names = _ALL_SLIDES if detail else tuple(
        n for n in _ALL_SLIDES if n not in DETAIL_SLIDES
    )
    return [globals()[n] for n in names]


def deck(b: dict, *, detail: bool = True) -> list[str]:
    """バンドルから実際に出す HTML を順に返す。

    固定の10枚（detail=False なら7枚）に続けて、データが揃っている
    OPTIONAL_SLIDES だけを足す。NMSI が未計算なら空文字が返るので落とす。
    **今までの10枚は、NMSI があってもなくても1枚も変わらない。**
    """
    out = [fn(b) for fn in report_slides(detail=detail)]
    out += [globals()[n](b) for n in OPTIONAL_SLIDES]
    return [h for h in out if h and h.strip()]


def deck_size(b: dict, *, detail: bool = True) -> int:
    """描く前に枚数を知りたいとき（設定画面の「全N枚」表示）。"""
    n = len(report_slides(detail=detail))
    return n + sum(1 for k in OPTIONAL_SLIDES if globals()[k](b).strip())
