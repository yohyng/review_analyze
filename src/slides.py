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
