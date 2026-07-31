"""Presentational helpers (HTML builders + small widgets) for the VoiceBAUM UI."""
from __future__ import annotations

from html import escape

import streamlit as st

from src import db
from src.ui import data
from src.ui.theme import ACCENT, ACCENT_SOFT


def facility_card(name: str) -> None:
    """Render a facility info card with key stats."""
    stats = db.facility_stats(data.get_conn(), name)
    if not stats:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("口コミ数", f"{stats['n_reviews']} 件")
    c2.metric("本文あり", f"{stats['n_text_reviews']} 件")
    c3.metric(
        "平均評点",
        f"★{stats['avg_rating']}" if stats["avg_rating"] else "-",
    )
    c4.metric(
        "スコア軸",
        f"{len(stats['score_axes'])} 軸" if stats["score_axes"] else "なし",
    )
    if stats["date_oldest"] != "-":
        st.caption(f"口コミ期間: {stats['date_oldest']} 〜 {stats['date_newest']}")


LOADING_STEPS = [
    ("口コミデータを収集中",      "DBから全口コミを読み込んでいます"),
    ("評価スコアを集計中",        "評点・ポジ率などの基本指標を計算しています"),
    ("ポジ／ネガの感情を分析中",   "22観点の感情・トピック統合スコアを解析中です"),
    ("トピックを分類中（TF-IDF）", "施設を特徴づけるキーワードを抽出しています"),
    ("競合と比較中",              "比較施設とのスコア差分を計算しています"),
    ("レポートを生成中",          "PowerPoint ファイルをビルドしています"),
]

_STEP_SUBTITLES = [s[0] for s in LOADING_STEPS]
_STEP_HINTS     = [s[1] for s in LOADING_STEPS]


def loading_card_html(current: int, detail: str = "") -> str:
    """Full-screen loading overlay — step list with per-step detail text.

    `current` = index of the step currently running (0-based).
    `detail`  = fine-grained message shown directly under the active step.
    """
    total = len(LOADING_STEPS)
    done = min(current, total)
    pct = round(100 * done / total)
    all_done = current >= total

    subtitle = "完了しました ✓" if all_done else _STEP_SUBTITLES[min(current, total - 1)]

    rows = []
    for i, (label, hint) in enumerate(LOADING_STEPS):
        if i < current:
            icon = (
                f'<div style="flex:none;width:22px;height:22px;border-radius:50%;'
                f'background:{ACCENT};display:flex;align-items:center;justify-content:center;'
                'color:#fff;font-size:12px;font-weight:800;">✓</div>'
            )
            row_body = f'<div style="font-size:13.5px;font-weight:700;color:#3A434E;">{escape(label)}</div>'
        elif i == current:
            icon = (
                f'<div style="flex:none;width:22px;height:22px;border-radius:50%;'
                f'border:2.5px solid {ACCENT};background:{ACCENT_SOFT};'
                'display:flex;align-items:center;justify-content:center;">'
                f'<div style="width:8px;height:8px;border-radius:50%;background:{ACCENT};'
                'animation:vb-pulse 1.1s ease-in-out infinite;"></div></div>'
            )
            # active detail: fallback to built-in hint when no detail passed
            active_detail = detail or hint
            row_body = (
                f'<div style="font-size:13.5px;font-weight:800;color:#16202B;">{escape(label)}</div>'
                f'<div style="font-size:11.5px;color:{ACCENT};margin-top:3px;line-height:1.45;">'
                f'▷ {escape(active_detail)}</div>'
            )
        else:
            icon = (
                '<div style="flex:none;width:22px;height:22px;border-radius:50%;'
                'border:2px solid #D8D4CE;background:#F4F3EF;"></div>'
            )
            row_body = f'<div style="font-size:13.5px;color:#B0B4BC;">{escape(label)}</div>'

        rows.append(
            '<div style="display:flex;align-items:flex-start;gap:12px;padding:7px 0;">'
            f'{icon}'
            f'<div style="flex:1;min-width:0;">{row_body}</div>'
            '</div>'
        )

    progress = (
        '<div style="margin:4px 0 16px;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;'
        'font-size:12.5px;font-weight:700;color:#5B6672;margin-bottom:8px;">'
        f'<span>{done} / {total} ステップ完了</span>'
        f'<span style="font-size:18px;font-weight:800;color:{ACCENT};">{pct}%</span></div>'
        '<div style="height:9px;background:#F1F0EA;border-radius:99px;overflow:hidden;">'
        f'<div style="height:100%;width:{pct}%;background:{ACCENT};border-radius:99px;'
        'transition:width .4s ease;"></div></div></div>'
    )
    pulse_css = (
        '<style>@keyframes vb-pulse{'
        '0%,100%{opacity:.35;transform:scale(.7)}'
        '50%{opacity:1;transform:scale(1)}}</style>'
    )
    return (
        '<div style="position:fixed;inset:0;z-index:2147483000;background:#F7F7F4;'
        'display:flex;align-items:center;justify-content:center;padding:20px;">'
        f'{pulse_css}'
        '<div class="vb-load-card" style="margin:0;">'
        '<div class="vb-load-title">口コミを解析しています…</div>'
        f'<div class="vb-load-sub">{escape(subtitle)}</div>'
        + progress
        + "".join(rows)
        + "</div></div>"
    )


def selected_card_html(name: str, meta: dict[str, str]) -> str:
    """Selected-facility card (magenta ring + tinted icon + name + area)."""
    sub = meta.get(name, "")
    return (
        f'<div style="display:flex;align-items:center;gap:14px;padding:16px 18px;'
        f'border:2px solid {ACCENT};border-radius:16px;background:#fff;'
        'box-shadow:0 1px 2px rgba(20,30,40,.04),0 12px 30px rgba(20,30,40,.05);">'
        f'<span style="width:46px;height:46px;flex:none;border-radius:12px;background:{ACCENT_SOFT};'
        f'color:{ACCENT};display:flex;align-items:center;justify-content:center;'
        f'font-weight:800;font-size:18px;">{escape(name[:1])}</span>'
        '<span style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        f'<span style="font-weight:800;font-size:17px;color:#16202B;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;">{escape(name)}</span>'
        f'<span style="font-size:13px;color:#8A9098;margin-top:2px;">{escape(sub)}</span></span></div>'
    )
