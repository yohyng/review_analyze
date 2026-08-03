"""分析レポートのスライド描画（HTML）。

デザインの正は docs/design/slide_p03..p12.png（20260726_VoiceBAUM_v1.pdf の
p3〜p12）。色・書体・寸法は src/report_theme.py のトークンを使い、値を直接
書かない。サイズは cqw（コンテナ幅に対する%）で持つので、どの幅で描いても
PDF と同じ比率になる。

キャンバスは 16:9（PDF が 960×540pt のため）。
"""
from __future__ import annotations

from html import escape

from . import report_theme as T


# ═══════════════════════════════════════════════════════════════════════════
# プリミティブ
# ═══════════════════════════════════════════════════════════════════════════
def canvas(inner: str) -> str:
    """1枚のスライド。container-type:inline-size で cqw を効かせる。"""
    return (
        f'<div style="width:100%;aspect-ratio:{T.ASPECT_RATIO};background:{T.PAGE_BG};'
        f'container-type:inline-size;font-family:{T.FONT_STACK};color:{T.INK};'
        f'border:1px solid {T.CARD_LINE};border-radius:10px;overflow:hidden;'
        'box-shadow:0 1px 2px rgba(20,30,40,.04),0 12px 30px rgba(20,30,40,.06);'
        'margin:0 0 22px;display:flex;flex-direction:column;">'
        f'{inner}</div>'
    )


def slide_header(num: str, title: str, meta: str = "", sub_title: str = "") -> str:
    """紺帯のヘッダ。左端にピンクの番号バッジ、右端に分析条件。

    バッジと帯は上下いっぱいに詰める（PDF はヘッダ帯が天地いっぱい）。
    """
    meta_html = (
        f'<div style="margin-left:auto;display:flex;align-items:center;'
        f'padding-right:1.8cqw;color:#fff;font-size:{T.FS["slide_meta"]}cqw;'
        f'font-weight:700;white-space:nowrap;">{escape(meta)}</div>'
        if meta else ""
    )
    sub_html = (
        f'<span style="font-size:{T.FS["slide_title"] * 0.62:.2f}cqw;font-weight:700;">'
        f'（{escape(sub_title)}）</span>'
        if sub_title else ""
    )
    return (
        f'<div style="flex:none;display:flex;align-items:stretch;background:{T.NAVY};'
        'height:7.4cqw;">'
        f'<div style="flex:none;width:6.6cqw;background:{T.ACCENT};color:#fff;'
        f'display:flex;align-items:center;justify-content:center;'
        f'font-size:3.1cqw;font-weight:800;">{escape(num)}</div>'
        f'<div style="display:flex;align-items:center;padding-left:2.2cqw;color:#fff;'
        f'font-size:{T.FS["slide_title"]}cqw;font-weight:800;letter-spacing:.02em;">'
        f'{escape(title)}{sub_html}</div>'
        f'{meta_html}</div>'
    )


def panel(title: str, body: str, *, icon: str = "", note: str = "",
          style: str = "flex:1") -> str:
    """紺の見出し帯＋白い本文のパネル。"""
    icon_html = (
        f'<span style="margin-right:.7cqw;font-size:1.2cqw;">{icon}</span>' if icon else ""
    )
    note_html = (
        f'<span style="margin-left:auto;font-size:{T.FS["note"]}cqw;font-weight:400;'
        f'opacity:.85;">{escape(note)}</span>'
        if note else ""
    )
    return (
        f'<div style="{style};min-width:0;display:flex;flex-direction:column;'
        f'border:1px solid {T.CARD_LINE};border-radius:1cqw;overflow:hidden;'
        'background:#fff;">'
        f'<div style="flex:none;display:flex;align-items:center;background:{T.NAVY};'
        f'color:#fff;font-size:{T.FS["panel_head"]}cqw;font-weight:800;'
        'padding:.62cqw 1.1cqw;">'
        f'{icon_html}{escape(title)}{note_html}</div>'
        f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;'
        'padding:1cqw 1.1cqw;">'
        f'{body}</div></div>'
    )


def footer(note: str = "※数値はサンプルです") -> str:
    """Voice BAUM のワードマーク＋ピンクの罫線。"""
    return (
        '<div style="flex:none;display:flex;align-items:center;gap:1cqw;'
        'padding:.5cqw 1.8cqw 1cqw;">'
        f'<span style="font-size:1.35cqw;font-weight:800;color:{T.INK};'
        'letter-spacing:.01em;white-space:nowrap;">'
        f'Voice <span style="color:{T.INK};">BAUM</span></span>'
        f'<span style="flex:1;height:1.5px;background:{T.ACCENT};"></span>'
        f'<span style="font-size:{T.FS["note"]}cqw;color:{T.SUB};white-space:nowrap;">'
        f'{escape(note)}</span></div>'
    )


def vertical_text(s: str, *, size: float, color: str | None = None,
                  weight: int = 400) -> str:
    """縦書きテキスト。1文字ずつ積んで描く。

    CSS の writing-mode:vertical-rl は、環境によっては和文フォントに縦書き
    メトリクスが無く漢字が同じ位置に重なってしまう（headless Chromium で再現）。
    レポートはどの環境でも同じ見えでなければならないので、フォント任せにせず
    自前で積む。長音符など横倒しが必要な字だけ回転させる。
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


def _photo(uri: str | None, ratio: str = "16/10", radius: str = ".7cqw") -> str:
    if uri:
        return (
            f'<div style="width:100%;aspect-ratio:{ratio};border-radius:{radius};'
            f'overflow:hidden;background:#F1F0EA;">'
            f'<img src="{uri}" style="width:100%;height:100%;object-fit:cover;'
            'display:block;" /></div>'
        )
    return (
        f'<div style="width:100%;aspect-ratio:{ratio};border-radius:{radius};'
        f'background:#F1F0EA;display:flex;align-items:center;justify-content:center;'
        f'color:{T.SUB};font-size:.8cqw;">写真なし</div>'
    )


def _stars(rating: float | None, size: float = 1.7) -> str:
    """★を5つ。評価値を四捨五入した数だけ金色にする。"""
    n = int(round(rating)) if rating is not None else 0
    return "".join(
        f'<span style="font-size:{size}cqw;color:{"#F5B324" if i < n else "#D9D9D9"};'
        'letter-spacing:.06em;">★</span>'
        for i in range(5)
    )


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 1「施設・基本情報」— docs/design/slide_p03.png
# ═══════════════════════════════════════════════════════════════════════════
def _profile_rows(b: dict) -> str:
    rows = [
        ("📍", "住所", b.get("address")),
        ("📅", "開業日", b.get("open_year")),
        ("🏢", "延床", b.get("floor_area")),
        ("👥", "マーケットカテゴリ", b.get("category")),
    ]
    out = ""
    for icon, label, val in rows:
        v = val if val and val != "—" else "—"
        out += (
            f'<div style="flex:1;display:flex;align-items:center;gap:.7cqw;'
            f'border-bottom:1px solid {T.LINE};">'
            f'<span style="flex:none;font-size:.95cqw;">{icon}</span>'
            f'<span style="flex:none;font-size:.92cqw;font-weight:700;color:{T.INK};">'
            f'{escape(label)}</span>'
            f'<span style="margin-left:auto;font-size:.92cqw;color:{T.INK};'
            'text-align:right;overflow:hidden;text-overflow:ellipsis;'
            f'white-space:nowrap;max-width:14cqw;">{escape(str(v))}</span></div>'
        )
    return out


def _review_summary_body(b: dict) -> str:
    n_rev = b.get("n_reviews") or 0
    avg = b.get("avg_rating")
    avg_txt = f"{avg:.1f}" if avg is not None else "—"
    half = (
        'flex:1;min-width:0;display:flex;flex-direction:column;'
        'align-items:center;justify-content:center;gap:.5cqw;'
    )
    return (
        '<div style="flex:1;display:flex;align-items:stretch;">'
        # 総口コミ数
        f'<div style="{half}">'
        f'<div style="font-size:1.05cqw;font-weight:700;color:{T.INK};">総口コミ数</div>'
        f'<div style="display:flex;align-items:baseline;gap:.2cqw;">'
        f'<span style="font-size:3.4cqw;font-weight:800;color:{T.ACCENT_DEEP};'
        f'line-height:1;">{n_rev:,}</span>'
        f'<span style="font-size:1.2cqw;font-weight:700;color:{T.ACCENT_DEEP};">件</span>'
        '</div>'
        f'<div style="margin-top:.4cqw;width:4.4cqw;height:2.6cqw;border-radius:1.3cqw;'
        f'background:{T.HEAT_HIGH_W};display:flex;align-items:center;'
        'justify-content:center;gap:.35cqw;">'
        + "".join(
            f'<span style="width:.42cqw;height:.42cqw;border-radius:50%;'
            f'background:{T.ACCENT};"></span>' for _ in range(3)
        )
        + '</div></div>'
        # 区切り
        f'<div style="flex:none;width:1px;background:{T.LINE};margin:.6cqw 0;"></div>'
        # 総合評価
        f'<div style="{half}">'
        f'<div style="font-size:1.05cqw;font-weight:700;color:{T.INK};">総合評価</div>'
        '<div style="display:flex;align-items:baseline;gap:.3cqw;">'
        f'<span style="font-size:3.4cqw;font-weight:800;color:{T.NAVY};line-height:1;">'
        f'{avg_txt}</span>'
        f'<span style="font-size:1.2cqw;font-weight:700;color:{T.SUB};">/ 5</span></div>'
        f'<div style="margin-top:.3cqw;">{_stars(avg)}</div>'
        '</div></div>'
    )


def _trend_body(trend: list) -> str:
    """口コミ数の推移（累積）。PDF は右上がりの折れ線＋丸マーカー＋注記バッジ。"""
    if not trend:
        return (
            f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{T.SUB};font-size:.9cqw;">推移データがありません</div>'
        )
    pts = trend[-24:]                       # 直近24か月まで
    vals = [v for _, v in pts]
    mx = max(vals) or 1
    # y軸の目盛りは切りのいい5分割
    step = max(1, int(mx / 4))
    digits = 10 ** max(0, len(str(step)) - 1)
    step = max(digits, (step // digits) * digits)
    ticks = [step * i for i in range(5)]
    top = ticks[-1] or 1
    n = len(pts)

    def x(i): return i / (n - 1) * 100 if n > 1 else 50.0
    def y(v): return (1 - v / top) * 100

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
    dots = "".join(
        f'<circle cx="{x(i):.2f}" cy="{y(v):.2f}" r="1.4" fill="{T.ACCENT}" '
        'vector-effect="non-scaling-stroke" />'
        for i, v in enumerate(vals)
    )
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(t):.2f}%;left:-3.4cqw;width:3cqw;'
        f'text-align:right;transform:translateY(-50%);font-size:.6cqw;color:{T.SUB};">'
        f'{t:,}</div>'
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
            f'font-size:.6cqw;color:{T.SUB};white-space:nowrap;">'
            f'{escape(pts[i][0].replace("-", "/"))}</div>'
        )
    growth = vals[-1] > vals[0]
    badge = (
        f'<div style="position:absolute;right:1cqw;top:14%;width:6.6cqw;height:6.6cqw;'
        f'border-radius:50%;background:{T.HEAT_HIGH_W};color:{T.ACCENT_DEEP};'
        'display:flex;align-items:center;justify-content:center;text-align:center;'
        'font-size:.72cqw;font-weight:800;line-height:1.35;">'
        f'{"継続的に<br>増加傾向" if growth else "横ばい〜<br>減少傾向"}</div>'
    )
    return (
        f'<div style="flex:none;font-size:.62cqw;color:{T.SUB};margin-left:-2.6cqw;">（件）</div>'
        '<div style="flex:1;position:relative;min-height:0;margin-left:3.6cqw;'
        'margin-top:.2cqw;">'
        f'{ylabs}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'{grid}{line}{dots}</svg>{badge}</div>'
        f'<div style="flex:none;position:relative;height:1.6cqw;margin-left:3.6cqw;">'
        f'{xlabs}</div>'
    )


def _peer_cards_body(b: dict) -> str:
    peers = (b.get("peer_display") or [])[:5]
    if not peers:
        return (
            f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{T.SUB};font-size:.9cqw;">比較対象施設が選択されていません</div>'
        )
    cards = "".join(
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:.4cqw;">'
        + _photo(p.get("photo_data_uri"), ratio="16/9", radius=".55cqw")
        + f'<div style="background:{T.HEAT_HIGH_W};border-radius:.45cqw;'
        'padding:.42cqw .3cqw;text-align:center;font-size:.78cqw;font-weight:700;'
        f'color:{T.INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        f'{escape(p.get("name", ""))}</div></div>'
        for p in peers
    )
    return f'<div style="flex:1;display:flex;gap:.85cqw;min-height:0;">{cards}</div>'


def slide1_facility_info(b: dict) -> str:
    """SLIDE 1「施設・基本情報」。docs/design/slide_p03.png と同じ構成。"""
    period = b.get("period_label") or ""
    meta = f"分析期間：{period}" if period else ""

    left = panel(
        "施設プロフィール",
        _photo(b.get("photo_data_uri"), ratio="16/11")
        + '<div style="flex:1;min-height:0;margin-top:.9cqw;display:flex;'
        f'flex-direction:column;">{_profile_rows(b)}</div>',
        icon="🏢", style="width:29cqw;flex:none",
    )
    summary = panel("口コミサマリー", _review_summary_body(b),
                    icon="💬", style="width:24cqw;flex:none")
    trend = panel("口コミ数の推移", _trend_body(b.get("review_trend") or []),
                  icon="📈", style="flex:1")
    n_peers = len(b.get("peer_display") or [])
    peers = panel(
        "比較対象施設（同カテゴリの類似施設）",
        _peer_cards_body(b),
        icon="👥",
        note=f"※同カテゴリの{n_peers}施設を比較対象として設定" if n_peers else "",
        style="flex:none;height:15.5cqw",
    )

    body = (
        '<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;'
        'padding:1.2cqw 1.8cqw .4cqw;">'
        f'{left}'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:1.1cqw;">'
        f'<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;">{summary}{trend}</div>'
        f'{peers}</div></div>'
    )
    return canvas(slide_header("1", "施設・基本情報", meta) + body + footer())


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
            leaves += (
                f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="7.6" ry="3.1" '
                f'fill="{T.ACCENT}" opacity=".9" '
                f'transform="rotate({a * side - 90:.0f} {x:.1f} {y:.1f})"/>'
            )
    crown = (
        f'<path d="M42 15 L45.5 9.5 L50 14 L54.5 9.5 L58 15 L56.5 19 L43.5 19 Z" '
        f'fill="{T.ACCENT}"/>'
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
        f'<div style="font-size:.95cqw;font-weight:700;color:{T.INK};margin-top:.2cqw;">'
        f'/ {total}施設中</div></div></div>'
        # ★
        f'<div>{_stars(b.get("avg_rating"), size=1.9)}</div>'
        # 5点スコア
        '<div style="display:flex;align-items:baseline;gap:.35cqw;">'
        f'<span style="font-size:3cqw;font-weight:800;color:{T.NAVY};line-height:1;">'
        f'{score5}</span>'
        f'<span style="font-size:1.05cqw;font-weight:700;color:{T.SUB};">/ 5点</span></div>'
        # 上位X%
        + (
            f'<div style="margin-top:.3cqw;background:#F4F4F1;border-radius:.5cqw;'
            f'padding:.5cqw 1.8cqw;font-size:1.05cqw;font-weight:800;color:{T.INK};">'
            f'{scope}上位{pct}%</div>'
            if pct is not None else ""
        )
        + '</div>'
    )


def _distribution_body(b: dict) -> str:
    dist = b.get("ranking_dist") or []
    me = b.get("overall_sentiment")
    rank = b.get("rank")
    if not dist or me is None:
        return (
            f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{T.SUB};font-size:.9cqw;">分布を出せるデータがありません</div>'
        )
    lo, hi = min(dist), max(dist)
    span = (hi - lo) or 1
    n_bin = 11
    bins = [0] * n_bin
    for v in dist:
        bins[min(n_bin - 1, int((v - lo) / span * n_bin))] += 1
    mine = min(n_bin - 1, int((me - lo) / span * n_bin))
    top = max(bins) or 1

    bars = ""
    for i, c in enumerate(bins):
        h = max(4, c / top * 100)
        is_me = i == mine
        col = T.ACCENT_VIVID if is_me else T.BAR_PEER
        bubble = (
            f'<div style="position:absolute;bottom:calc(100% + 1.5cqw);left:50%;'
            f'transform:translateX(-50%);background:{T.ACCENT_VIVID};color:#fff;'
            'border-radius:1cqw;padding:.22cqw .8cqw;font-size:.85cqw;font-weight:800;'
            f'white-space:nowrap;">{rank}位</div>'
            f'<div style="position:absolute;bottom:100%;left:50%;width:1.5px;'
            f'height:1.5cqw;background:{T.ACCENT_VIVID};"></div>'
            if is_me and rank else ""
        )
        bars += (
            '<div style="flex:1;display:flex;align-items:flex-end;justify-content:center;'
            'position:relative;height:100%;">'
            f'<div style="position:relative;width:74%;height:{h:.1f}%;background:{col};'
            f'border-radius:.18cqw .18cqw 0 0;">{bubble}</div></div>'
        )

    return (
        '<div style="flex:1;display:flex;flex-direction:column;min-height:0;'
        'padding-top:2.6cqw;">'
        f'<div style="flex:1;display:flex;align-items:flex-end;gap:.22cqw;'
        'min-height:0;">' + bars + '</div>'
        # 軸（矢印付き）
        f'<div style="flex:none;height:1px;background:{T.INK};margin-top:.35cqw;'
        'position:relative;">'
        f'<div style="position:absolute;right:-.1cqw;top:-.28cqw;width:0;height:0;'
        f'border-left:.55cqw solid {T.INK};border-top:.3cqw solid transparent;'
        'border-bottom:.3cqw solid transparent;"></div></div>'
        '<div style="flex:none;display:flex;justify-content:space-between;'
        f'font-size:.85cqw;font-weight:700;color:{T.INK};margin-top:.35cqw;">'
        '<span>低評価</span><span>高評価</span></div>'
        # 総合評価
        '<div style="flex:none;margin:.9cqw auto 0;background:#F4F4F1;'
        'border-radius:.5cqw;padding:.5cqw 2.2cqw;display:flex;align-items:baseline;'
        'gap:.6cqw;">'
        f'<span style="font-size:1.05cqw;font-weight:700;color:{T.INK};">総合評価</span>'
        f'<span style="font-size:1.5cqw;font-weight:800;color:{T.ACCENT_DEEP};">'
        f'{_pt5(me)}</span></div>'
        '</div>'
    )


def _top3_card(title: str, rows: list, accent: str, icon: str) -> str:
    """強みTOP3 / 弱みTOP3 のカード。rows = [(指標名, 自施設100, 市場平均100), ...]"""
    items = ""
    for i, (name, mine, base) in enumerate(rows[:3], 1):
        items += (
            f'<div style="flex:1;display:flex;align-items:center;gap:.7cqw;'
            + (f'border-bottom:1px dashed {T.LINE};' if i < min(3, len(rows)) else "")
            + '">'
            f'<span style="flex:none;width:1.5cqw;height:1.5cqw;border-radius:50%;'
            f'background:{accent};color:#fff;font-size:.8cqw;font-weight:800;'
            'display:flex;align-items:center;justify-content:center;">'
            f'{i}</span>'
            f'<span style="flex:1;min-width:0;font-size:1cqw;font-weight:700;'
            f'color:{T.INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{escape(name)}</span>'
            '<span style="flex:none;text-align:right;">'
            f'<div style="font-size:1.55cqw;font-weight:800;color:{accent};'
            f'line-height:1.05;">{_pt5(mine)}</div>'
            f'<div style="font-size:.68cqw;color:{T.SUB};white-space:nowrap;">'
            f'市場平均 {_pt5(base)}</div></span></div>'
        )
    if not rows:
        items = f'<div style="color:{T.SUB};font-size:.85cqw;">該当なし</div>'
    return (
        f'<div style="flex:1;min-height:0;border:1.5px solid {accent};'
        'border-radius:1cqw;background:#fff;padding:.75cqw 1cqw;display:flex;'
        'flex-direction:column;">'
        '<div style="flex:none;display:flex;align-items:center;gap:.55cqw;'
        'margin-bottom:.35cqw;">'
        f'<span style="width:1.9cqw;height:1.9cqw;border-radius:50%;background:{accent};'
        'color:#fff;display:flex;align-items:center;justify-content:center;'
        f'font-size:1cqw;">{icon}</span>'
        f'<span style="font-size:1.25cqw;font-weight:800;color:{accent};">'
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

    left = panel("総合評価ランキング", _ranking_body(b), style="width:26cqw;flex:none")
    mid = panel(f"同業施設内の総合評価分布", _distribution_body(b), style="flex:1")
    right = (
        '<div style="width:30cqw;flex:none;display:flex;flex-direction:column;'
        'gap:1cqw;min-height:0;">'
        + _top3_card("強み TOP3", st, T.ACCENT_DEEP, "👍")
        + _top3_card("弱み TOP3", wk, "#1B4DA8", "👎")
        + '</div>'
    )
    body = (
        '<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;'
        'padding:1.2cqw 1.8cqw .4cqw;">'
        f'{left}{mid}{right}</div>'
    )
    return canvas(slide_header("2", f"{scope}ポジション", meta) + body + footer())


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
                f'justify-content:center;color:{T.SUB};font-size:.9cqw;">データ不足</div>')

    LO, HI = 1.0, 5.0

    def y(v100): return (1 - (min(max(_score5(v100), LO), HI) - LO) / (HI - LO)) * 100
    def x(i): return i / (n - 1) * 100 if n > 1 else 50.0

    dash = 'stroke-dasharray="3.5 2.5"'
    grid = "".join(
        f'<line x1="0" y1="{y(g * 20):.2f}" x2="100" y2="{y(g * 20):.2f}" '
        f'stroke="{T.LINE}" stroke-width=".45" vector-effect="non-scaling-stroke"/>'
        for g in (1, 2, 3, 4, 5)
    )
    series = ""
    for label, src, col, is_avg in (
        ("当施設", mine, T.ACCENT, False),
        ("同業平均", avg, "#4A7DC4", True),
    ):
        pts = " ".join(f"{x(i):.2f},{y(src.get(t, 50.0)):.2f}" for i, t in enumerate(topics))
        series += (
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.5" '
            f'{dash if is_avg else ""} stroke-linejoin="round" '
            'vector-effect="non-scaling-stroke"/>'
        )
        series += "".join(
            f'<circle cx="{x(i):.2f}" cy="{y(src.get(t, 50.0)):.2f}" r="1.25" '
            f'fill="{"#fff" if not is_avg else col}" stroke="{col}" stroke-width="1" '
            'vector-effect="non-scaling-stroke"/>'
            for i, t in enumerate(topics)
        )
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(g * 20):.2f}%;left:-2.2cqw;width:1.8cqw;'
        f'text-align:right;transform:translateY(-50%);font-size:.62cqw;color:{T.SUB};">'
        f'{g}</div>'
        for g in (1, 2, 3, 4, 5)
    )
    # x軸ラベルは PDF と同じく縦書き（丸番号＋指標名）
    # 縦書きは flex アイテムにすると inline-size が潰れるので、素のブロックに
    # 明示的な height（＝縦書きでの行の長さ）を与える。
    xlabs = "".join(
        f'<div style="position:absolute;left:{x(i):.2f}%;top:0;'
        'transform:translateX(-50%);text-align:center;">'
        f'<div style="font-size:.62cqw;color:{T.INK};line-height:1.2;'
        f'margin-bottom:.15cqw;">{_CIRCLED[i]}</div>'
        + vertical_text(t, size=.55) + '</div>'
        for i, t in enumerate(topics)
    )
    legend = (
        '<div style="flex:none;display:flex;align-items:center;gap:1.2cqw;'
        'justify-content:flex-end;margin-bottom:.3cqw;">'
        f'<span style="font-size:.68cqw;color:{T.SUB};margin-right:auto;">評価スコア（点）</span>'
        f'<span style="font-size:.72cqw;color:{T.INK};">'
        f'<span style="color:{T.ACCENT};font-weight:800;">─●─</span> 当施設</span>'
        f'<span style="font-size:.72cqw;color:{T.INK};">'
        '<span style="color:#4A7DC4;font-weight:800;">╌●╌</span> 同業平均</span></div>'
    )
    return (
        legend
        + '<div style="flex:1;position:relative;min-height:0;margin-left:2.4cqw;">'
        f'{ylabs}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'{grid}{series}</svg></div>'
        f'<div style="flex:none;position:relative;height:11cqw;margin-left:2.4cqw;'
        f'margin-top:.35cqw;">{xlabs}</div>'
        f'<div style="flex:none;font-size:{T.FS["note"]}cqw;color:{T.SUB};'
        'margin-top:.2cqw;">※ 各指標は1〜5点で評価</div>'
    )


def _indicator_table(b: dict) -> str:
    """指標（代表例）の表。強みTOP3＋弱みTOP3＋総合評価（PDFと同じ選び方）。"""
    rows = [(t, mine, base) for t, mine, base, _ in (b.get("strengths") or [])[:3]]
    rows += [(t, mine, base) for t, mine, base, _ in (b.get("weaknesses") or [])[:3]]
    cell = "padding:.45cqw .5cqw;font-size:.78cqw;text-align:center;"
    head = (
        '<div style="display:flex;">'
        f'<div style="flex:1.7;{cell}text-align:left;background:#F4F3EE;'
        f'font-weight:700;color:{T.SUB};">指標（代表例）</div>'
        f'<div style="flex:1;{cell}background:{T.ACCENT};color:#fff;font-weight:800;">'
        '当施設</div>'
        f'<div style="flex:1;{cell}background:{T.NAVY};color:#fff;font-weight:800;">'
        '同業平均</div></div>'
    )
    body = "".join(
        f'<div style="flex:1;display:flex;align-items:center;'
        f'border-bottom:1px solid {T.LINE};">'
        f'<div style="flex:1.7;{cell}text-align:left;color:{T.INK};overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;">{escape(t)}</div>'
        f'<div style="flex:1;{cell}color:{T.ACCENT_DEEP};font-weight:800;">'
        f'{_pt5(m)}</div>'
        f'<div style="flex:1;{cell}color:{T.INK};">{_pt5(a)}</div></div>'
        for t, m, a in rows
    )
    tot_mine = b.get("overall_sentiment")
    _dist = b.get("ranking_dist") or []
    tot_avg = sum(_dist) / len(_dist) if _dist else None
    total = (
        '<div style="flex:1;display:flex;align-items:center;border-top:1.5px solid '
        f'{T.INK};">'
        f'<div style="flex:1.7;{cell}text-align:left;font-weight:800;color:{T.INK};">'
        '総合評価</div>'
        f'<div style="flex:1;{cell}color:{T.ACCENT_DEEP};font-weight:800;">'
        f'{_pt5(tot_mine)}</div>'
        f'<div style="flex:1;{cell}font-weight:700;color:{T.INK};">'
        f'{_pt5(tot_avg)}</div></div>'
    )
    return (
        f'<div style="width:19cqw;flex:none;display:flex;flex-direction:column;'
        f'border:1px solid {T.CARD_LINE};border-radius:.6cqw;overflow:hidden;">'
        f'{head}<div style="flex:1;display:flex;flex-direction:column;">'
        f'{body}{total}</div></div>'
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
                f'justify-content:center;color:{T.SUB};font-size:.9cqw;">データ不足</div>')

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
        if is_me:
            dots += (f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{rr * 1.7:.2f}" '
                     f'fill="{T.ACCENT}"/>')
        else:
            col = T.SERIES_PEERS[i % len(T.SERIES_PEERS)] if label_points else "#3E76C4"
            dots += (f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{rr:.2f}" fill="{col}" '
                     f'opacity="{0.85 if label_points else 0.55}"/>')
        if is_me or label_points:
            nm_disp = "当施設" if is_me else _clip_name(nm, 7)
            # 上端付近のバブルはラベルを上に置くとパネルからはみ出すので下に回す
            off = f"{rr * 1.9 + 3:.1f}" if py > 14 else f"-{rr * 1.9 + 1.6:.1f}"
            shift = "0" if px < 14 else ("-100%" if px > 86 else "-50%")
            labels += (
                f'<div style="position:absolute;left:{px:.2f}%;top:{py:.2f}%;'
                f'transform:translate({shift},-{off}cqw);'
                f'font-size:.68cqw;font-weight:800;white-space:nowrap;'
                f'color:{T.ACCENT_DEEP if is_me else T.INK};">{escape(nm_disp)}</div>'
            )
    dash = 'stroke-dasharray="2.5 2.5"'
    return (
        '<div style="flex:1;display:flex;gap:.8cqw;min-height:0;padding-left:2.2cqw;">'
        # 散布図
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        '<div style="flex:1;position:relative;min-height:0;">'
        f'<div style="position:absolute;left:-.1cqw;top:0;font-size:.62cqw;'
        f'color:{T.INK};">高</div>'
        f'<div style="position:absolute;left:-.1cqw;bottom:1.3cqw;font-size:.62cqw;'
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
        f'{dots}</svg>'
        f'{labels}</div>'
        '<div style="flex:none;display:flex;justify-content:space-between;'
        f'font-size:.66cqw;color:{T.INK};margin-top:.15cqw;padding:0 .4cqw;">'
        '<span>低</span>'
        '<span style="font-weight:700;">体験満足度</span><span>高</span></div>'
        f'<div style="flex:none;font-size:{T.FS["note"]}cqw;color:{T.SUB};'
        'margin-top:.25cqw;">○ バブルサイズ＝再訪意向</div>'
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
        f'<div style="flex:0 0 5.4cqw;border:1.4px solid {T.ACCENT};'
        'border-radius:.7cqw;display:flex;align-items:center;justify-content:center;'
        'gap:.6cqw;padding:.3cqw;">'
        f'<span style="font-size:1.3cqw;">{icon}</span>'
        '<span style="text-align:center;">'
        f'<div style="font-size:.68cqw;font-weight:700;color:{T.INK};">{name}</div>'
        f'<div style="font-size:1.5cqw;font-weight:800;color:{T.ACCENT_DEEP};'
        f'line-height:1.1;">{_pt5(mine.get(name))}</div>'
        '</span></div>'
        for icon, name in items
    )
    return (
        '<div style="width:11cqw;flex:none;display:flex;flex-direction:column;'
        'gap:.7cqw;min-height:0;justify-content:center;">'
        f'<div style="flex:none;font-size:.66cqw;font-weight:700;'
        f'color:{T.ACCENT_DEEP};">口コミから算出した主要スコア</div>'
        f'{boxes}</div>'
    )


def market_trend(b: dict, note: str) -> str:
    """マーケット傾向 A（評価されやすい）／B（課題になりやすい）。"""
    good = b.get("market_trend_good") or []
    bad = b.get("market_trend_bad") or []

    def col(letter: str, title: str, items: list, accent: str, bg: str) -> str:
        rows = "".join(
            '<div style="flex:none;height:2.1cqw;display:flex;align-items:center;'
            'gap:.5cqw;font-size:.78cqw;min-width:0;">'
            f'<span style="flex:none;width:1.2cqw;height:1.2cqw;border-radius:50%;'
            f'border:1.2px solid {accent};"></span>'
            f'<span style="flex:1;min-width:0;color:{T.INK};overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap;">{escape(t)}</span></div>'
            for t in items[:5]
        )
        return (
            '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
            f'<div style="flex:none;background:{bg};border-radius:.5cqw;'
            'padding:.32cqw .6cqw;margin-bottom:.35cqw;font-size:.74cqw;'
            f'font-weight:800;color:{accent};overflow:hidden;text-overflow:ellipsis;'
            f'white-space:nowrap;"><b>{letter}.</b> {escape(title)}</div>'
            f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;">'
            f'{rows}</div></div>'
        )

    return (
        '<div style="flex:1;display:flex;gap:.9cqw;min-height:0;">'
        + col("A", "この市場で評価されやすい指標", good, T.ACCENT_DEEP, T.HEAT_HIGH_W)
        + col("B", "この市場で課題になりやすい指標", bad, "#1B4DA8", "#EDF2FC")
        + '</div>'
        f'<div style="flex:none;font-size:{T.FS["note"]}cqw;color:{T.SUB};'
        f'text-align:right;margin-top:.3cqw;">{escape(note)}</div>'
    )


def _planner_badge() -> str:
    return (
        f'<div style="margin-left:auto;display:flex;align-items:center;'
        'padding-right:1.8cqw;"><span style="background:{};color:#fff;'
        'border-radius:1.2cqw;padding:.3cqw 1.2cqw;font-size:.85cqw;'
        'font-weight:800;white-space:nowrap;">プランナー起点</span></div>'.format(T.ACCENT)
    )


def slide2_market_detail(b: dict) -> str:
    """SLIDE 2 詳細「市場内ポジション（詳細）」。docs/design/slide_p05.png。"""
    scope = b.get("scope_label", "市場内")
    n_fac = b.get("total_fac") or 0

    header = (
        f'<div style="flex:none;display:flex;align-items:stretch;background:{T.NAVY};'
        'height:7.4cqw;">'
        f'<div style="flex:none;width:6.6cqw;background:{T.ACCENT};color:#fff;'
        'display:flex;align-items:center;justify-content:center;'
        'font-size:3.1cqw;font-weight:800;">2</div>'
        f'<div style="display:flex;align-items:center;padding-left:2.2cqw;color:#fff;'
        f'font-size:{T.FS["slide_title"]}cqw;font-weight:800;">'
        f'{escape(scope)}ポジション'
        f'<span style="font-size:{T.FS["slide_title"] * 0.62:.2f}cqw;font-weight:700;">'
        '（詳細）</span></div>'
        + _planner_badge() + '</div>'
    )
    left = panel(
        "乃村独自の口コミ分析指標",
        '<div style="flex:1;display:flex;gap:1cqw;min-height:0;">'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        f'{_indicator_chart(b)}</div>'
        f'{_indicator_table(b)}</div>',
        style="flex:1.35",
    )
    right = (
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:1cqw;">'
        + panel("総合体験評価マッピング", experience_map(b),
                note=f"※ マッピングは全{n_fac}施設を表示", style="flex:1.15")
        + panel("マーケット傾向",
                market_trend(b, "※ 市場傾向は同カテゴリ施設の口コミ分析から算出"),
                style="flex:1")
        + '</div>'
    )
    body = (
        '<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;'
        f'padding:1.2cqw 1.8cqw .4cqw;">{left}{right}</div>'
    )
    return canvas(header + body + footer())


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
        cols.append(("同業平均", "同業平均", b["overall_topic"], T.SERIES_AVG))
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
    series = ""
    for label, _nm, sc, col in cols:
        is_avg = label == "同業平均"
        pts = " ".join(f"{x(i):.2f},{y(sc.get(t, 50.0)):.2f}" for i, t in enumerate(topics))
        series += (
            f'<polyline points="{pts}" fill="none" stroke="{col}" '
            f'stroke-width="{1.1 if is_avg else 1.5}" {dash if is_avg else ""} '
            'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        )
        if not is_avg:
            series += "".join(
                f'<circle cx="{x(i):.2f}" cy="{y(sc.get(t, 50.0)):.2f}" r="1.15" '
                f'fill="#fff" stroke="{col}" stroke-width=".95" '
                'vector-effect="non-scaling-stroke"/>'
                for i, t in enumerate(topics)
            )
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(g * 20):.2f}%;left:-2.4cqw;width:2cqw;'
        f'text-align:right;transform:translateY(-50%);font-size:.6cqw;color:{T.SUB};">'
        f'{g}.0</div>'
        for g in (1, 2, 3, 4, 5)
    )
    xlabs = "".join(
        f'<div style="position:absolute;left:{x(i):.2f}%;top:0;'
        'transform:translateX(-50%);">' + vertical_text(t, size=.5) + '</div>'
        for i, t in enumerate(topics)
    )
    legend = "".join(
        f'<span style="font-size:.68cqw;color:{T.INK};white-space:nowrap;">'
        f'<span style="color:{col};font-weight:800;">'
        f'{"╌╌" if lb == "同業平均" else "─○─"}</span> {escape(lb)}</span>'
        for lb, _nm, _sc, col in cols
    )
    return (
        '<div style="flex:none;display:flex;gap:.9cqw;flex-wrap:wrap;'
        f'margin-bottom:.35cqw;">{legend}</div>'
        '<div style="flex:1;position:relative;min-height:0;margin-left:2.6cqw;">'
        f'{ylabs}'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'{grid}{series}</svg></div>'
        '<div style="flex:none;position:relative;height:8.6cqw;margin-left:2.6cqw;'
        f'margin-top:.35cqw;">{xlabs}</div>'
    )


def _compare_heatmap(b: dict, topics: list[str]) -> str:
    """施設別スコアヒートマップ。行=19指標 × 列=自施設/競合A〜D/同業平均。"""
    cols = compare_columns(b)
    vals = [sc.get(t, 50.0) for _l, _n, sc, _c in cols for t in topics]
    lo, hi = min(vals), max(vals)
    mid = (lo + hi) / 2
    half = max(hi - mid, mid - lo) or 1

    def bg(v: float) -> str:
        r = (v - mid) / half
        if r >= 0:
            return f"rgba(233,64,107,{0.05 + 0.30 * min(r, 1):.3f})"
        return f"rgba(91,155,213,{0.05 + 0.30 * min(-r, 1):.3f})"

    c = "padding:.24cqw .1cqw;text-align:center;font-size:.64cqw;"
    head = (
        f'<div style="display:flex;background:#F4F3EE;font-weight:800;color:{T.SUB};">'
        f'<div style="width:7.2cqw;flex:none;{c}text-align:left;padding-left:.4cqw;">'
        '指標</div>'
        + "".join(
            f'<div style="flex:1;{c}color:{col};">{escape(lb)}</div>'
            for lb, _n, _s, col in cols
        )
        + '</div>'
    )
    rows = "".join(
        f'<div style="flex:1;display:flex;border-top:1px solid {T.LINE};">'
        f'<div style="width:7.2cqw;flex:none;{c}text-align:left;padding-left:.4cqw;'
        f'color:{T.INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        f'{escape(t)}</div>'
        + "".join(
            f'<div style="flex:1;{c}background:{bg(sc.get(t, 50.0))};'
            f'color:{T.INK};font-weight:700;">{_pt5(sc.get(t, 50.0))}</div>'
            for _l, _n, sc, _c in cols
        )
        + '</div>'
        for t in topics
    )
    return f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;">{head}{rows}</div>'


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
        return f'<div style="color:{T.SUB};font-size:.8cqw;">該当なし</div>'
    return (
        '<div style="flex:1;display:grid;grid-template-columns:1fr 1fr;'
        'column-gap:1.4cqw;align-content:space-around;">'
        + "".join(
            '<div style="display:flex;align-items:center;gap:.5cqw;font-size:.82cqw;">'
            f'<span style="flex:none;width:.44cqw;height:.44cqw;border-radius:50%;'
            f'background:{color};"></span>'
            f'<span style="flex:1;min-width:0;color:{T.INK};overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap;">{escape(t)}</span>'
            f'<span style="flex:none;color:{color};font-weight:700;">'
            f'（{d:+.2f}）</span></div>'
            for t, d in rows[:cap]
        )
        + '</div>'
    )


def _compare_header(b: dict, detail: bool) -> str:
    cols = compare_columns(b)
    n_fac = sum(1 for lb, _n, _s, _c in cols if lb != "同業平均")
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
            _compare_header(b, False)
            + f'<div style="flex:1;display:flex;align-items:center;'
            f'justify-content:center;color:{T.SUB};font-size:1.1cqw;">'
            '比較できるデータがありません。</div>' + footer()
        )
    win, lose = _vs_peer_lists(b, topics)
    body = (
        f'<div style="flex:none;font-size:{T.FS["slide_lead"]}cqw;font-weight:700;'
        f'color:{T.INK};padding:.9cqw 1.8cqw .6cqw;">'
        '2〜5施設を横並びで比較し、自施設の立ち位置を把握します。</div>'
        '<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;padding:0 1.8cqw;">'
        + panel("主要19指標の比較（5点満点）", _compare_chart(b, topics))
        + panel("施設別スコアヒートマップ（5点満点）", _compare_heatmap(b, topics))
        + '</div>'
        '<div style="flex:none;display:flex;gap:1.1cqw;height:8.6cqw;'
        'padding:.9cqw 1.8cqw 0;">'
        + panel("自施設だけの強み", _diff_grid(win, T.ACCENT_DEEP, 6))
        + panel("競合に負けている項目", _diff_grid(lose, T.NAVY, 4))
        + '</div>'
    )
    return canvas(_compare_header(b, False) + body + footer())


def slide3_competitor_detail(b: dict) -> str:
    """SLIDE 3「指定競合との比較（詳細）」。docs/design/slide_p07.png。"""
    peers = list((b.get("peer_topic_scores") or {}))[: len(T.SERIES_PEERS)]
    body = (
        '<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;'
        'padding:1.2cqw 1.8cqw .4cqw;">'
        + panel("総合体験評価マッピング",
                experience_map(b, names=peers, label_points=True), style="flex:1")
        + panel("指定競合の傾向",
                market_trend(b, "※ 市場傾向は同カテゴリ施設の口コミ分析から算出"),
                style="flex:1")
        + '</div>'
    )
    return canvas(_compare_header(b, True) + body + footer())


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 4「時間軸分析」— docs/design/slide_p08.png
# ═══════════════════════════════════════════════════════════════════════════
def _pill(title: str) -> str:
    """紺の角丸タグ見出し（SLIDE 4 のブロック見出し）。"""
    return (
        f'<div style="flex:none;align-self:flex-start;background:{T.NAVY};color:#fff;'
        'border-radius:.5cqw .5cqw .5cqw 0;padding:.4cqw 1.1cqw;'
        f'font-size:1cqw;font-weight:800;">{escape(title)}</div>'
    )


def _posneg_chart(series: list, points: list) -> str:
    """月次のポジ／ネガ積み上げ棒＋差分の折れ線。軸は −1.0〜+1.0 固定。"""
    if not series:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:.9cqw;">'
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
    dots = "".join(
        f'<circle cx="{x(i):.2f}" cy="{y(r[4]):.2f}" r="1.3" fill="#fff" '
        f'stroke="{T.DIFF_LINE}" stroke-width="1" vector-effect="non-scaling-stroke"/>'
        for i, r in enumerate(pts)
    )
    ylabs = "".join(
        f'<div style="position:absolute;top:{y(g):.2f}%;left:-3cqw;width:2.6cqw;'
        'text-align:right;transform:translateY(-50%);font-size:.62cqw;'
        f'color:{T.ACCENT_DEEP if g > 0 else ("#1B4DA8" if g < 0 else T.INK)};">'
        f'{g:+.1f}</div>'.replace("+0.0", "0")
        for g in (1.0, 0.5, 0.0, -0.5, -1.0)
    )
    badges = "".join(
        f'<div style="position:absolute;left:{x(i):.2f}%;top:-2.2cqw;'
        'transform:translateX(-50%);width:1.9cqw;height:1.9cqw;border-radius:50%;'
        f'background:{T.ACCENT};color:#fff;font-size:.85cqw;font-weight:800;'
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
            f'font-size:.6cqw;color:{T.INK};white-space:nowrap;">'
            f'{escape(lab)}</div>'
        )
    legend = (
        '<div style="flex:none;display:flex;flex-direction:column;gap:.45cqw;'
        'width:12.5cqw;padding-top:1.5cqw;">'
        + "".join(
            '<div style="display:flex;align-items:center;gap:.5cqw;'
            f'font-size:.72cqw;color:{T.INK};">'
            f'<span style="flex:none;width:1.5cqw;height:.75cqw;background:{c};'
            'border-radius:.1cqw;"></span>' + escape(t) + '</div>'
            for c, t in ((T.POS_BAR, "ポジティブ要因スコア（+）"),
                         (T.NEG_BAR, "ネガティブ要因スコア（−）"))
        )
        + '<div style="display:flex;align-items:center;gap:.5cqw;'
        f'font-size:.72cqw;color:{T.INK};">'
        f'<span style="flex:none;color:{T.DIFF_LINE};font-weight:800;">─○─</span>'
        '差分（ポジ − ネガ）</div>'
        f'<div style="font-size:.66cqw;color:{T.SUB};margin-top:.2cqw;">（スコア）</div>'
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
        f'{dots}</svg></div>'
        f'<div style="flex:none;position:relative;height:1.7cqw;margin-left:3.2cqw;">'
        f'{xlabs}'
        f'<div style="position:absolute;right:-1.6cqw;top:.1cqw;font-size:.6cqw;'
        f'color:{T.SUB};">（月）</div></div>'
        '</div></div>'
    )


def _change_point_cards(points: list) -> str:
    from . import timeline as _tl
    if not points:
        return (f'<div style="flex:1;display:flex;align-items:center;'
                f'justify-content:center;color:{T.SUB};font-size:.9cqw;">'
                '評価が大きく動いた月は検出されませんでした</div>')
    cards = []
    for i, cp in enumerate(points, 1):
        title, body = (cp.title, cp.body) if cp.title else _tl.fallback_description(cp)
        up = cp.direction == "up"
        col = "#1B4DA8" if up else T.ACCENT_DEEP
        cards.append(
            f'<div style="flex:1;min-width:0;border:1px solid {T.CARD_LINE};'
            'border-radius:.8cqw;background:#fff;padding:.75cqw .9cqw;'
            'display:flex;flex-direction:column;gap:.4cqw;">'
            '<div style="flex:none;display:flex;align-items:center;gap:.55cqw;">'
            f'<span style="flex:none;width:1.7cqw;height:1.7cqw;border-radius:50%;'
            f'background:{T.ACCENT};color:#fff;font-size:.85cqw;font-weight:800;'
            f'display:flex;align-items:center;justify-content:center;">{i}</span>'
            f'<span style="font-size:.9cqw;font-weight:800;color:{T.ACCENT_DEEP};">'
            f'{escape(cp.label)}</span>'
            f'<span style="font-size:1cqw;font-weight:800;color:{T.INK};'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            f'{escape(title)}</span></div>'
            f'<div style="flex:1;min-height:0;font-size:.76cqw;line-height:1.5;'
            f'color:{T.INK};overflow:hidden;">{escape(body)}</div>'
            f'<div style="flex:none;border-top:1px dashed {T.LINE};padding-top:.35cqw;'
            'display:flex;align-items:center;gap:.45cqw;">'
            f'<span style="color:{col};font-size:.95cqw;">{"↑" if up else "↓"}</span>'
            f'<span style="font-size:.85cqw;font-weight:800;color:{col};">'
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
        '<div style="flex:none;display:flex;justify-content:flex-end;gap:1.6cqw;'
        f'font-size:.78cqw;color:{T.INK};padding:.6cqw 1.8cqw .2cqw;">'
        + (f'<span>📅 分析期間：{escape(period)}（{n_months}か月）</span>' if period else "")
        + f'<span>💬 対象：口コミ {b.get("n_reviews", 0):,} 件</span></div>'
    )
    box = (
        f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;gap:.5cqw;'
        f'border:1px solid {T.CARD_LINE};border-radius:.9cqw;padding:.7cqw 1cqw 1cqw;">'
    )
    body = (
        sub
        + '<div style="flex:1;display:flex;flex-direction:column;gap:.9cqw;'
        'min-height:0;padding:.2cqw 1.8cqw 0;">'
        + _pill("ポジティブ要因とネガティブ要因の推移")
        + box + _posneg_chart(series, points) + '</div>'
        + _pill("主な変化点と評価変動要因")
        + '<div style="flex:none;height:12cqw;display:flex;">'
        + _change_point_cards(points) + '</div></div>'
    )
    meta = f"分析期間：{period}" if period else ""
    return canvas(
        slide_header("4", "時間軸分析", meta) + body
        + footer("※スコアは5点満点を−1〜+1のスケールに変換して集計")
    )
