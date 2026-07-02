"""In-app analysis result screen — render the report as stacked HTML slides.

Produces a serialisable "bundle" of real data (KPIs, comparison, insights,
N=1 comments) and HTML builders for each slide, matching the VoiceBAUM
design. Charts (SLIDE 02) are rendered separately with plotly in app.py.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from html import escape
from typing import Optional

from . import analysis, text_analysis

# palette (VoiceBAUM)
ACCENT = "#B0338A"
INK = "#16202B"
SUB = "#8A9098"
POS = "#4F8A6B"
NEG = "#C66B61"
LINE = "#E9E8E2"


# ═══════════════════════════════════════════════════════════════════════════
# Data bundle
# ═══════════════════════════════════════════════════════════════════════════
def build_bundle(
    conn: sqlite3.Connection,
    target: str,
    ts,                       # topic_score.TopicScoreResult
    profile,                  # text_analysis.TextProfile
    insights,                 # llm.InsightResult | None
    an_mode: str = "single",
    axis: str = "comparison_avg",
    specific_name: Optional[str] = None,
) -> dict:
    frow = conn.execute(
        "SELECT id, category, general_rating FROM facility WHERE name = ?", (target,)
    ).fetchone()
    fid = frow["id"] if frow else None
    category = (frow["category"] if frow and frow["category"] else "—")
    general_rating = frow["general_rating"] if frow else None

    n_reviews = conn.execute(
        "SELECT COUNT(*) FROM review WHERE facility_id = ?", (fid,)
    ).fetchone()[0] if fid else 0

    avg_row = conn.execute(
        "SELECT AVG(rating) FROM review WHERE facility_id = ? AND rating IS NOT NULL", (fid,)
    ).fetchone() if fid else None
    avg_rating = avg_row[0] if avg_row and avg_row[0] is not None else general_rating

    pr = conn.execute(
        "SELECT SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END), COUNT(rating) "
        "FROM review WHERE facility_id = ? AND rating IS NOT NULL", (fid,)
    ).fetchone() if fid else None
    pos_rate = round(100 * pr[0] / pr[1]) if pr and pr[1] else None

    # rank across facilities by average rating
    ranked = sorted(
        [
            (r[0], r[1]) for r in conn.execute(
                "SELECT f.name, AVG(r.rating) FROM facility f "
                "JOIN review r ON r.facility_id = f.id "
                "WHERE r.rating IS NOT NULL GROUP BY f.id"
            ).fetchall() if r[1] is not None
        ],
        key=lambda z: -z[1],
    )
    total_fac = len(ranked)
    rank = next((i + 1 for i, (nm, _) in enumerate(ranked) if nm == target), None)

    # comparisons (score-table based)
    comp_all = analysis.build_comparison(conn, target, "all_avg")
    comp_peer = analysis.build_comparison(conn, target, "comparison_avg")
    comp = None
    if an_mode == "compare":
        comp = analysis.build_comparison(conn, target, axis, specific_name=specific_name)
    comp = comp or comp_peer or comp_all

    # strengths / weaknesses — score comparison if available, else topic sentiment
    strengths, weaknesses = [], []
    basis = "感情スコア"
    baseline_label = "中立(50)"
    if comp is not None and not comp.diff.empty:
        basis = "スコア比較"
        baseline_label = comp.baseline_label
        diff_sorted = comp.diff.sort_values(ascending=False)
        for m in diff_sorted.head(5).index:
            strengths.append((m, round(float(comp.target[m]), 2),
                              round(float(comp.baseline[m]), 2), round(float(comp.diff[m]), 2)))
        for m in diff_sorted.tail(5).index[::-1]:
            weaknesses.append((m, round(float(comp.target[m]), 2),
                               round(float(comp.baseline[m]), 2), round(float(comp.diff[m]), 2)))
    elif ts is not None and not ts.empty:
        by_sent = ts.sorted_by_sentiment(reverse=True)
        for t in by_sent[:5]:
            strengths.append((t.name, t.sentiment_100, 50.0, round(t.sentiment_100 - 50, 1)))
        for t in list(reversed(by_sent))[:5]:
            weaknesses.append((t.name, t.sentiment_100, 50.0, round(t.sentiment_100 - 50, 1)))

    overall_score = None
    if comp is not None and not comp.target.empty:
        overall_score = round(float(comp.target.mean()), 2)
    elif ts is not None and not ts.empty:
        overall_score = ts.weighted_sentiment_100

    # SLIDE 01 analysis rows
    analysis_rows = [
        ("分析対象", target),
        ("登録施設数", f"{total_fac} 施設"),
        ("全体スコア", f"{overall_score}" if overall_score is not None else "—"),
        ("全体順位", f"{rank} / {total_fac}" if rank else "—"),
        ("全体平均との差", f"{comp_all.diff.mean():+.2f}" if comp_all is not None and not comp_all.diff.empty else "—"),
        ("ピア平均との差", f"{comp_peer.diff.mean():+.2f}" if comp_peer is not None and not comp_peer.diff.empty else "—"),
        ("最も強い項目", strengths[0][0] if strengths else "—"),
        ("最も弱い項目", weaknesses[0][0] if weaknesses else "—"),
    ]

    # insight text (LLM if available, else generated from data)
    if insights is not None and getattr(insights, "summary", None):
        insight = {
            "結論": insights.summary,
            "強み": "、".join(insights.strengths[:3]) if insights.strengths else (strengths[0][0] if strengths else "—"),
            "弱み": "、".join(insights.weaknesses[:3]) if insights.weaknesses else (weaknesses[0][0] if weaknesses else "—"),
            "示唆": "、".join(insights.implications[:2]) if insights.implications else "—",
        }
    else:
        s0 = strengths[0][0] if strengths else "—"
        w0 = weaknesses[0][0] if weaknesses else "—"
        insight = {
            "結論": f"「{target}」は{basis}において総合スコア {overall_score} "
                    f"（{total_fac}施設中 {rank}位）。強みは「{s0}」、課題は「{w0}」。"
                    if overall_score is not None else f"「{target}」の口コミを分析しました。",
            "強み": f"「{s0}」が高く評価されています。",
            "弱み": f"「{w0}」に改善余地があります。",
            "示唆": f"「{w0}」の改善が体験全体の評価向上に寄与する可能性があります。",
        }

    # SLIDE 04 — N=1 representative comments
    samples = []
    if profile is not None and not profile.empty:
        samples = list(profile.high_rated[:2]) + list(profile.low_rated[:1])
    samples = [s for s in samples if s][:3]
    if not samples and fid:
        rows = conn.execute(
            "SELECT text FROM review WHERE facility_id = ? AND text IS NOT NULL AND text != '' "
            "ORDER BY LENGTH(text) DESC LIMIT 3", (fid,)
        ).fetchall()
        samples = [r[0] for r in rows]

    n1_note = insight["示唆"]

    return {
        "target": target,
        "category": category,
        "n_reviews": n_reviews,
        "avg_rating": round(float(avg_rating), 1) if avg_rating is not None else None,
        "pos_rate": pos_rate,
        "rank": rank,
        "total_fac": total_fac,
        "date": f"{date.today():%Y年%m月%d日}",
        "basis": basis,
        "baseline_label": baseline_label,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "analysis_rows": analysis_rows,
        "insight": insight,
        "samples": samples,
        "n1_note": n1_note,
    }


# ═══════════════════════════════════════════════════════════════════════════
# HTML builders
# ═══════════════════════════════════════════════════════════════════════════
def _card(inner: str) -> str:
    return (
        f'<div style="background:#fff;border:1px solid {LINE};border-radius:16px;'
        f'box-shadow:0 1px 2px rgba(20,30,40,.04),0 14px 36px rgba(20,30,40,.05);'
        f'padding:26px 30px;margin-bottom:18px;">{inner}</div>'
    )


def _badge(text: str, bg: str = ACCENT) -> str:
    return (
        f'<span style="font-size:11px;font-weight:800;letter-spacing:.08em;color:#fff;'
        f'background:{bg};padding:4px 10px;border-radius:6px;white-space:nowrap;">{escape(text)}</span>'
    )


def _slide_head(badge: str, title: str, subtitle: str = "") -> str:
    sub = (f'<div style="font-size:12.5px;color:{SUB};margin:2px 0 16px;">{escape(subtitle)}</div>'
           if subtitle else '<div style="height:14px"></div>')
    return (
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:2px;">'
        + _badge(badge)
        + f'<span style="font-size:19px;font-weight:800;color:{INK};">{escape(title)}</span></div>'
        + sub
    )


def slide02_head() -> str:
    """SLIDE 02 head only (chart is rendered separately by st.plotly_chart)."""
    return _slide_head(
        "SLIDE 02", "感情評価・トピック分類",
        "トピック（指標軸）ごとの感情スコア（50=中立・言及度つき）",
    )


def html_overview(b: dict) -> str:
    tiles = [
        ("総合評価", f"{b['avg_rating']}" if b["avg_rating"] is not None else "—", "/ 5.0"),
        ("比較順位", f"{b['rank']} / {b['total_fac']}" if b["rank"] else "—", ""),
        ("レビュー件数", f"{b['n_reviews']:,}", "件"),
        ("ポジティブ率", f"{b['pos_rate']}%" if b["pos_rate"] is not None else "—", ""),
    ]
    cells = ""
    for label, value, sub in tiles:
        cells += (
            f'<div style="flex:1;min-width:120px;border:1px solid #EDECE6;border-radius:12px;'
            f'padding:16px 18px;background:#FBFBF9;">'
            f'<div style="font-size:12px;color:{SUB};font-weight:600;margin-bottom:8px;">{escape(label)}</div>'
            f'<div style="display:flex;align-items:baseline;gap:5px;">'
            f'<span style="font-size:30px;font-weight:800;color:{INK};letter-spacing:-.02em;">{value}</span>'
            f'<span style="font-size:12px;color:#A7ABB0;font-weight:600;">{escape(sub)}</span></div></div>'
        )
    inner = (
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:20px;">'
        '<div>'
        '<div style="display:flex;align-items:center;gap:9px;margin-bottom:10px;">'
        + _badge("概要")
        + f'<span style="font-size:12px;font-weight:700;letter-spacing:.1em;color:{ACCENT};">口コミ分析レポート</span></div>'
        + f'<div style="font-size:40px;font-weight:800;letter-spacing:-.02em;color:{INK};line-height:1.05;">{escape(b["target"])}</div>'
        + f'<div style="font-size:14px;color:{SUB};margin-top:6px;">{escape(b["category"])}</div>'
        '</div>'
        '<div style="text-align:right;flex:none;">'
        f'<div style="font-size:16px;font-weight:800;color:{INK};">VoiceBAUM</div>'
        f'<div style="font-size:12px;color:#A7ABB0;margin-top:4px;">作成日 {escape(b["date"])}</div>'
        '</div></div>'
        f'<div style="display:flex;gap:14px;flex-wrap:wrap;">{cells}</div>'
    )
    return _card(inner)


def html_profile(b: dict) -> str:
    rows = [
        ("施設名", b["target"]),
        ("業種", b["category"]),
        ("住所", "—"),
        ("アクセス", "—"),
        ("開業", "—"),
        ("口コミ", f"平均 ★{b['avg_rating']} ／ {b['n_reviews']:,} 件" if b["avg_rating"] is not None else f"{b['n_reviews']:,} 件"),
    ]
    trs = ""
    for i, (k, v) in enumerate(rows):
        border = f"border-bottom:1px solid {LINE};" if i < len(rows) - 1 else ""
        trs += (
            f'<div style="display:flex;{border}">'
            f'<div style="width:110px;flex:none;background:#F4F3EF;padding:12px 14px;'
            f'font-size:13px;font-weight:700;color:#3A434E;">{escape(k)}</div>'
            f'<div style="flex:1;padding:12px 16px;font-size:13.5px;color:{INK};">{escape(str(v))}</div></div>'
        )
    photo = (
        '<div style="flex:none;width:38%;min-width:220px;border-radius:12px;height:240px;'
        'background:linear-gradient(160deg,#EFE7EC,#E9ECEE);border:1px solid #E4E3DD;'
        'display:flex;align-items:center;justify-content:center;color:#A7ABB0;font-size:13px;">施設写真</div>'
    )
    table = (
        f'<div style="flex:1;min-width:260px;"><div style="font-size:14px;font-weight:800;color:{INK};margin-bottom:10px;">■ 基本情報</div>'
        f'<div style="border:1px solid {LINE};border-radius:10px;overflow:hidden;">{trs}</div></div>'
    )
    inner = _slide_head("PROFILE", "分析施設情報") + (
        f'<div style="display:flex;gap:22px;flex-wrap:wrap;align-items:stretch;">{photo}{table}</div>'
    )
    return _card(inner)


def _kv_table(rows) -> str:
    trs = ""
    for i, (k, v) in enumerate(rows):
        border = f"border-bottom:1px solid {LINE};" if i < len(rows) - 1 else ""
        trs += (
            f'<div style="display:flex;{border}">'
            f'<div style="width:130px;flex:none;background:#FBF4F9;padding:9px 12px;'
            f'font-size:12.5px;font-weight:700;color:#3A434E;">{escape(str(k))}</div>'
            f'<div style="flex:1;padding:9px 12px;font-size:13px;font-weight:700;color:{INK};">{escape(str(v))}</div></div>'
        )
    return f'<div style="border:1px solid {LINE};border-radius:10px;overflow:hidden;">{trs}</div>'


def html_slide01(b: dict) -> str:
    left = (
        f'<div style="flex:1;min-width:260px;"><div style="font-size:14px;font-weight:800;color:{INK};margin-bottom:10px;">■ 分析結果</div>'
        + _kv_table(b["analysis_rows"]) + '</div>'
    )
    ins = b["insight"]
    ins_rows = [("結論", ins["結論"], ACCENT), ("強み", ins["強み"], POS),
                ("弱み", ins["弱み"], NEG), ("示唆", ins["示唆"], "#3A434E")]
    ins_html = ""
    for i, (tag, txt, col) in enumerate(ins_rows):
        border = f"border-bottom:1px solid {LINE};" if i < len(ins_rows) - 1 else ""
        ins_html += (
            f'<div style="display:flex;{border}">'
            f'<div style="width:64px;flex:none;padding:11px;font-size:13px;font-weight:800;color:{col};'
            f'display:flex;align-items:center;justify-content:center;">{escape(tag)}</div>'
            f'<div style="flex:1;padding:11px 13px;font-size:13px;line-height:1.6;color:#3A434E;">{escape(txt)}</div></div>'
        )
    right = (
        f'<div style="flex:1;min-width:260px;"><div style="font-size:14px;font-weight:800;color:{INK};margin-bottom:10px;">■ インサイト</div>'
        f'<div style="border:1px solid {LINE};border-radius:10px;overflow:hidden;">{ins_html}</div>'
        f'<div style="font-size:11px;color:#A7ABB0;margin-top:8px;">※ {escape(b["basis"])}に基づく自動生成。</div></div>'
    )
    inner = _slide_head("SLIDE 01", "比較分析による特徴点抽出", "スコアから読み解く示唆") + (
        f'<div style="display:flex;gap:22px;flex-wrap:wrap;">{left}{right}</div>'
    )
    return _card(inner)


def _sw_table(title: str, rows, header_bg: str, diff_pos: bool) -> str:
    head = (
        f'<div style="display:flex;background:{header_bg};color:#fff;font-weight:700;font-size:12px;">'
        '<div style="flex:2;padding:8px 12px;">トピック</div>'
        '<div style="flex:1;padding:8px 12px;text-align:right;">対象</div>'
        '<div style="flex:1;padding:8px 12px;text-align:right;">基準</div>'
        '<div style="flex:1;padding:8px 12px;text-align:right;">差分</div></div>'
    )
    body = ""
    for i, (name, self_v, base_v, diff) in enumerate(rows):
        dcol = POS if diff >= 0 else NEG
        bg = "#fff" if i % 2 == 0 else "#FBFBF9"
        body += (
            f'<div style="display:flex;background:{bg};border-top:1px solid #EEEDE7;font-variant-numeric:tabular-nums;">'
            f'<div style="flex:2;padding:8px 12px;font-size:12.5px;font-weight:600;color:{INK};'
            'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escape(str(name)) + '</div>'
            f'<div style="flex:1;padding:8px 12px;text-align:right;font-size:12.5px;font-weight:700;color:{INK};">{self_v}</div>'
            f'<div style="flex:1;padding:8px 12px;text-align:right;font-size:12px;color:{SUB};">{base_v}</div>'
            f'<div style="flex:1;padding:8px 12px;text-align:right;font-size:12.5px;font-weight:800;color:{dcol};">{diff:+.2f}</div></div>'
        )
    label_col = POS if diff_pos else NEG
    return (
        f'<div style="flex:1;min-width:280px;">'
        f'<div style="font-size:14px;font-weight:800;color:{label_col};margin-bottom:8px;">{escape(title)}</div>'
        f'<div style="border:1px solid {LINE};border-radius:10px;overflow:hidden;">{head}{body}</div></div>'
    )


def html_slide03(b: dict) -> str:
    if not b["strengths"] and not b["weaknesses"]:
        body = f'<div style="color:{SUB};font-size:13px;padding:12px;">比較できるデータが不足しています。</div>'
    else:
        body = (
            '<div style="display:flex;gap:22px;flex-wrap:wrap;">'
            + _sw_table("強み TOP5", b["strengths"], POS, True)
            + _sw_table("弱み TOP5", b["weaknesses"], NEG, False)
            + '</div>'
        )
    sub = "強み・弱みの上位項目（対象 vs 基準）"
    inner = _slide_head("SLIDE 03", "数値による比較評価", sub) + body
    return _card(inner)


def html_slide04(b: dict) -> str:
    if not b["samples"]:
        rows_html = f'<div style="color:{SUB};font-size:13px;padding:12px;">本文付きの口コミがありません。</div>'
    else:
        rows_html = ""
        for i, s in enumerate(b["samples"], 1):
            disp = s if len(s) <= 220 else s[:220] + "…"
            rows_html += (
                '<div style="display:flex;gap:14px;padding:12px 0;border-top:1px solid #EEEDE7;">'
                f'<div style="flex:none;width:52px;font-size:12px;font-weight:800;color:{ACCENT};">口コミ<br>{i}</div>'
                f'<div style="flex:1;font-size:13px;line-height:1.65;color:#3A434E;">{escape(disp)}</div></div>'
            )
    note = (
        f'<div style="display:flex;gap:14px;margin-top:14px;padding:14px;background:#FBF4F9;border-radius:10px;">'
        f'<div style="flex:none;width:52px;font-size:12px;font-weight:800;color:{ACCENT};">示唆</div>'
        f'<div style="flex:1;font-size:13px;line-height:1.65;font-weight:600;color:{INK};">{escape(b["n1_note"])}</div></div>'
    )
    inner = _slide_head("SLIDE 04", "この施設に対する特徴的な口コミ（N=1／ミクロ分析）",
                        "平均には表れない、この施設を象徴する口コミと示唆") + rows_html + note
    return _card(inner)
