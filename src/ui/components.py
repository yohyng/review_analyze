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
    "口コミデータを収集中",
    "評価スコアを集計中",
    "ポジ／ネガの感情を分析中",
    "トピックを分類中（TF-IDF）",
    "競合と比較中",
    "レポートを生成中",
]


def loading_card_html(current: int, detail: str = "") -> str:
    """Full-screen loading overlay with the 6-step list + numeric progress.

    Rendered as a fixed, opaque overlay so nothing behind shows through.
    """
    total = len(LOADING_STEPS)
    done = min(current, total)
    pct = round(100 * done / total)

    rows = []
    for i, label in enumerate(LOADING_STEPS):
        if i < current:
            icon = '<div class="vb-step-done">✓</div>'
            lab = f'<div class="vb-step-label">{label}</div>'
        elif i == current:
            icon = '<div class="vb-step-active"></div>'
            lab = f'<div class="vb-step-label">{label}</div>'
        else:
            icon = '<div class="vb-step-todo"></div>'
            lab = f'<div class="vb-step-label-todo">{label}</div>'
        rows.append(f'<div class="vb-step-row">{icon}{lab}</div>')

    detail_html = (
        f'<div style="font-size:12px;color:#8A9098;margin-top:14px;text-align:center;">{detail}</div>'
        if detail else ""
    )
    progress = (
        '<div style="margin:4px 0 18px;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;'
        'font-size:12.5px;font-weight:700;color:#5B6672;margin-bottom:8px;">'
        f'<span>{done} / {total} ステップ完了</span>'
        f'<span style="font-size:18px;font-weight:800;color:{ACCENT};">{pct}%</span></div>'
        '<div style="height:9px;background:#F1F0EA;border-radius:99px;overflow:hidden;">'
        f'<div style="height:100%;width:{pct}%;background:{ACCENT};border-radius:99px;transition:width .3s ease;"></div>'
        '</div></div>'
    )
    return (
        '<div style="position:fixed;inset:0;z-index:2147483000;background:#F7F7F4;'
        'display:flex;align-items:center;justify-content:center;padding:20px;">'
        '<div class="vb-load-card" style="margin:0;">'
        '<div class="vb-load-title">口コミを解析しています…</div>'
        '<div class="vb-load-sub">評価・感情・キーワードを集計中</div>'
        + progress
        + "".join(rows)
        + detail_html
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
