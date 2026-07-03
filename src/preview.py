"""In-app analysis result screen — render the report as 16:10 slide canvases.

Produces a serialisable "bundle" of real data (KPIs, comparison, insights,
topic bars, N=1 comments) and HTML builders for each slide. Every slide is a
fixed 16:10 (PowerPoint-shaped) canvas using `container-type:inline-size` +
`cqw` units, so it scales proportionally like a slide thumbnail at any width.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from html import escape
from typing import Optional

from . import analysis

# palette (VoiceBAUM)
ACCENT = "#B0338A"
INK = "#16202B"
SUB = "#8A9098"
POS = "#4F8A6B"
NEU = "#C9C3B6"
NEG = "#C66B61"
LINE = "#E1E0D9"
CARD_LINE = "#E9E8E2"


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


def _sent_color(v100: float) -> str:
    if v100 >= 60:
        return POS
    if v100 <= 40:
        return NEG
    return "#C79A2E"  # amber for the neutral band, readable on white


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

    comp_all = analysis.build_comparison(conn, target, "all_avg")
    comp_peer = analysis.build_comparison(conn, target, "comparison_avg")
    comp = None
    if an_mode == "compare":
        comp = analysis.build_comparison(conn, target, axis, specific_name=specific_name)
    comp = comp or comp_peer or comp_all

    strengths, weaknesses = [], []
    basis = "感情スコア"
    if comp is not None and not comp.diff.empty:
        basis = "スコア比較"
        diff_sorted = comp.diff.sort_values(ascending=False)
        for m in diff_sorted.head(5).index:
            strengths.append((m, round(float(comp.target[m]), 1),
                              round(float(comp.baseline[m]), 1), round(float(comp.diff[m]), 2)))
        for m in diff_sorted.tail(5).index[::-1]:
            weaknesses.append((m, round(float(comp.target[m]), 1),
                               round(float(comp.baseline[m]), 1), round(float(comp.diff[m]), 2)))
    elif ts is not None and not ts.empty:
        by_sent = ts.sorted_by_sentiment(reverse=True)
        for t in by_sent[:5]:
            strengths.append((t.name, t.sentiment_100, 50.0, round(t.sentiment_100 - 50, 1)))
        for t in list(reversed(by_sent))[:5]:
            weaknesses.append((t.name, t.sentiment_100, 50.0, round(t.sentiment_100 - 50, 1)))

    overall_score = None
    if comp is not None and not comp.target.empty:
        overall_score = round(float(comp.target.mean()), 1)
    elif ts is not None and not ts.empty:
        overall_score = ts.weighted_sentiment_100

    # SLIDE 02 — topic sentiment bars
    topics_bars = []
    if ts is not None and not ts.empty:
        for t in ts.sorted_by_sentiment(reverse=True):
            topics_bars.append((t.name, t.sentiment_100, t.salience_pct))

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
            "結論": (f"「{target}」は{basis}で総合スコア {overall_score}"
                    f"（{total_fac}施設中 {rank}位）。強みは「{s0}」、課題は「{w0}」。"
                    if overall_score is not None else f"「{target}」の口コミを分析しました。"),
            "強み": f"「{s0}」が高く評価されています。",
            "弱み": f"「{w0}」に改善余地があります。",
            "示唆": f"「{w0}」の改善が体験全体の評価向上に寄与する可能性があります。",
        }

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
        "strengths": strengths,
        "weaknesses": weaknesses,
        "analysis_rows": analysis_rows,
        "insight": insight,
        "samples": samples,
        "n1_note": insight["示唆"],
        "topics_bars": topics_bars,
        "overall_sentiment": ts.weighted_sentiment_100 if (ts is not None and not ts.empty) else None,
        "n_sentences": ts.n_sentences if (ts is not None and not ts.empty) else 0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 16:10 canvas primitives (all sizes in cqw)
# ═══════════════════════════════════════════════════════════════════════════
def _canvas(inner: str) -> str:
    return (
        f'<div style="width:100%;aspect-ratio:16/10;background:#fff;border:1px solid {CARD_LINE};'
        'border-radius:14px;box-shadow:0 1px 2px rgba(20,30,40,.04),0 14px 36px rgba(20,30,40,.05);'
        'overflow:hidden;container-type:inline-size;position:relative;margin-bottom:16px;">'
        '<div style="position:absolute;inset:0;padding:4.4cqw 5cqw;display:flex;flex-direction:column;">'
        f'{inner}</div></div>'
    )


def _badge(text: str, bg: str = ACCENT) -> str:
    return (
        f'<span style="font-size:1.15cqw;font-weight:800;letter-spacing:.06em;color:#fff;'
        f'background:{bg};padding:.45cqw .9cqw;border-radius:.6cqw;white-space:nowrap;">{escape(text)}</span>'
    )


def _head(badge: str, title: str, sub: str = "") -> str:
    sub_html = (f'<div style="font-size:1.25cqw;color:{SUB};margin:.3cqw 0 1.8cqw;">{escape(sub)}</div>'
                if sub else '<div style="height:1.6cqw"></div>')
    return (
        '<div style="display:flex;align-items:center;gap:1.2cqw;margin-bottom:.2cqw;">'
        + _badge(badge)
        + f'<span style="font-size:2.4cqw;font-weight:800;color:{INK};line-height:1.1;">{escape(title)}</span></div>'
        + sub_html
    )


# ═══════════════════════════════════════════════════════════════════════════
# Slides
# ═══════════════════════════════════════════════════════════════════════════
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
            f'<div style="flex:1;border:1px solid #EDECE6;border-radius:1.3cqw;padding:2cqw 2.2cqw;background:#FBFBF9;">'
            f'<div style="font-size:1.35cqw;color:{SUB};font-weight:600;margin-bottom:1cqw;">{escape(label)}</div>'
            f'<div style="display:flex;align-items:baseline;gap:.5cqw;">'
            f'<span style="font-size:3.6cqw;font-weight:800;color:{INK};letter-spacing:-.02em;line-height:1;font-variant-numeric:tabular-nums;">{value}</span>'
            f'<span style="font-size:1.3cqw;color:#A7ABB0;font-weight:600;">{escape(sub)}</span></div></div>'
        )
    top = (
        '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:2cqw;">'
        '<div style="min-width:0;">'
        '<div style="display:flex;align-items:center;gap:1cqw;margin-bottom:1.6cqw;">'
        + _badge("概要")
        + f'<span style="font-size:1.4cqw;font-weight:700;letter-spacing:.1em;color:{ACCENT};">口コミ分析レポート</span></div>'
        + f'<div style="font-size:4.8cqw;font-weight:800;letter-spacing:-.02em;color:{INK};line-height:1.05;">{escape(b["target"])}</div>'
        + f'<div style="font-size:1.7cqw;color:{SUB};margin-top:1cqw;">{escape(b["category"])}</div>'
        '</div>'
        '<div style="text-align:right;flex:none;">'
        f'<div style="font-size:1.9cqw;font-weight:800;color:{INK};">VoiceBAUM</div>'
        f'<div style="font-size:1.3cqw;color:#A7ABB0;margin-top:.5cqw;">作成日 {escape(b["date"])}</div>'
        '</div></div>'
    )
    inner = top + '<div style="flex:1;"></div>' + f'<div style="display:flex;gap:1.6cqw;">{cells}</div>'
    return _canvas(inner)


def _table(rows, key_w="14cqw", key_bg="#ECEBE5", key_fs="1.45cqw", val_fs="1.55cqw", val_bold=True):
    trs = ""
    for i, (k, v) in enumerate(rows):
        border = f"border-bottom:1px solid {LINE};" if i < len(rows) - 1 else ""
        trs += (
            f'<div style="display:flex;flex:1;{border}">'
            f'<div style="width:{key_w};flex:none;background:{key_bg};padding:0 1.4cqw;'
            f'font-size:{key_fs};font-weight:700;color:#3A434E;display:flex;align-items:center;">{escape(str(k))}</div>'
            f'<div style="flex:1;padding:0 1.5cqw;font-size:{val_fs};color:{INK};display:flex;align-items:center;'
            f'{"font-weight:700;" if val_bold else ""}white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{escape(str(v))}</div></div>'
        )
    return f'<div style="flex:1;display:flex;flex-direction:column;border:1px solid {LINE};border-radius:1cqw;overflow:hidden;">{trs}</div>'


def html_profile(b: dict) -> str:
    rows = [
        ("施設名", b["target"]),
        ("業種", b["category"]),
        ("住所", "—"),
        ("アクセス", "—"),
        ("開業", "—"),
        ("口コミ", (f"平均 ★{b['avg_rating']} ／ {b['n_reviews']:,} 件"
                   if b["avg_rating"] is not None else f"{b['n_reviews']:,} 件")),
    ]
    photo = (
        '<div style="width:40cqw;flex:none;border-radius:1.4cqw;background:linear-gradient(160deg,#EFE7EC,#E9ECEE);'
        'border:1px solid #E4E3DD;display:flex;align-items:center;justify-content:center;color:#A7ABB0;font-size:1.4cqw;">施設写真</div>'
    )
    right = (
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        f'<div style="font-size:1.7cqw;font-weight:800;color:{INK};margin-bottom:1.2cqw;">■ 基本情報</div>'
        + _table(rows) + '</div>'
    )
    inner = _head("PROFILE", "分析施設情報") + (
        f'<div style="flex:1;display:flex;gap:3cqw;min-height:0;">{photo}{right}</div>'
    )
    return _canvas(inner)


def html_slide01(b: dict) -> str:
    left = (
        '<div style="width:36cqw;flex:none;display:flex;flex-direction:column;">'
        f'<div style="font-size:1.6cqw;font-weight:800;color:{INK};margin-bottom:1cqw;">■ 分析結果</div>'
        + _table(b["analysis_rows"], key_w="13cqw", key_bg="#FBF4F9", key_fs="1.25cqw", val_fs="1.35cqw") + '</div>'
    )
    ins = b["insight"]
    ins_rows = [("結論", _clip(ins["結論"], 160), ACCENT), ("強み", _clip(ins["強み"], 90), POS),
                ("弱み", _clip(ins["弱み"], 90), NEG), ("示唆", _clip(ins["示唆"], 110), "#3A434E")]
    ins_html = ""
    for i, (tag, txt, col) in enumerate(ins_rows):
        border = f"border-bottom:1px solid {LINE};" if i < len(ins_rows) - 1 else ""
        ins_html += (
            f'<div style="display:flex;flex:1;{border}">'
            f'<div style="width:7cqw;flex:none;padding:.8cqw;font-size:1.3cqw;font-weight:800;color:{col};'
            'display:flex;align-items:center;justify-content:center;">' + escape(tag) + '</div>'
            f'<div style="flex:1;padding:.8cqw 1cqw;font-size:1.2cqw;line-height:1.5;color:#3A434E;'
            'display:flex;align-items:center;">' + escape(txt) + '</div></div>'
        )
    right = (
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        f'<div style="font-size:1.6cqw;font-weight:800;color:{INK};margin-bottom:1cqw;">■ インサイト</div>'
        f'<div style="flex:1;display:flex;flex-direction:column;border:1px solid {LINE};border-radius:1cqw;overflow:hidden;">{ins_html}</div></div>'
    )
    inner = _head("SLIDE 01", "比較分析による特徴点抽出", "スコアから読み解く示唆") + (
        f'<div style="flex:1;display:flex;gap:2.6cqw;min-height:0;">{left}{right}</div>'
    )
    return _canvas(inner)


def html_slide02(b: dict) -> str:
    bars = b.get("topics_bars") or []
    if not bars:
        body = f'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:{SUB};font-size:1.4cqw;">本文付きの口コミが不足しています。</div>'
    else:
        rows = ""
        for name, sent, sal in bars:
            col = _sent_color(sent)
            width = max(2, min(100, sent))
            rows += (
                '<div style="display:flex;align-items:center;gap:1.4cqw;flex:1;">'
                f'<div style="width:17cqw;flex:none;font-size:1.25cqw;color:{INK};font-weight:600;text-align:right;'
                'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escape(name) + '</div>'
                '<div style="flex:1;height:1.9cqw;background:#F1F0EA;border-radius:.5cqw;position:relative;overflow:hidden;">'
                f'<div style="position:absolute;left:0;top:0;bottom:0;width:{width}cqw;max-width:100%;background:{col};border-radius:.5cqw;"></div>'
                '<div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(20,30,40,.18);"></div></div>'
                f'<div style="width:5cqw;flex:none;font-size:1.3cqw;font-weight:800;color:{col};text-align:right;font-variant-numeric:tabular-nums;">{sent:.0f}</div>'
                f'<div style="width:6cqw;flex:none;font-size:1.05cqw;color:{SUB};text-align:right;">言及{sal:.0f}%</div>'
                '</div>'
            )
        legend = (
            '<div style="display:flex;gap:1.8cqw;align-items:center;margin-top:1cqw;">'
            f'<span style="font-size:1.1cqw;color:{SUB};">50=中立</span>'
            f'<span style="display:flex;align-items:center;gap:.5cqw;font-size:1.1cqw;color:{SUB};"><span style="width:1.1cqw;height:1.1cqw;border-radius:.25cqw;background:{POS};"></span>ポジ</span>'
            f'<span style="display:flex;align-items:center;gap:.5cqw;font-size:1.1cqw;color:{SUB};"><span style="width:1.1cqw;height:1.1cqw;border-radius:.25cqw;background:{NEG};"></span>ネガ</span>'
            + (f'<span style="font-size:1.1cqw;color:#A7ABB0;margin-left:auto;">総合感情スコア {b["overall_sentiment"]:.0f}/100 ・ 分析文数 {b["n_sentences"]}</span>' if b.get("overall_sentiment") is not None else '')
            + '</div>'
        )
        body = f'<div style="flex:1;display:flex;flex-direction:column;gap:.6cqw;min-height:0;">{rows}</div>{legend}'
    inner = _head("SLIDE 02", "感情評価・トピック分類",
                  "トピック（指標軸）ごとの感情スコア（独自指標・50=中立）") + body
    return _canvas(inner)


def _sw_table(title: str, rows, header_bg: str, label_col: str) -> str:
    head = (
        f'<div style="display:flex;background:{header_bg};color:#fff;font-weight:700;font-size:1.05cqw;">'
        '<div style="flex:1.7;padding:.55cqw .8cqw;">トピック</div>'
        '<div style="flex:1;padding:.55cqw .8cqw;text-align:right;">対象</div>'
        '<div style="flex:1;padding:.55cqw .8cqw;text-align:right;">基準</div>'
        '<div style="flex:1;padding:.55cqw .8cqw;text-align:right;">差分</div></div>'
    )
    body = ""
    for name, self_v, base_v, diff in rows:
        dcol = POS if diff >= 0 else NEG
        body += (
            '<div style="display:flex;align-items:center;flex:1;border-top:1px solid #EEEDE7;font-variant-numeric:tabular-nums;">'
            f'<div style="flex:1.7;padding:0 .8cqw;font-size:1.1cqw;font-weight:600;color:{INK};'
            'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escape(str(name)) + '</div>'
            f'<div style="flex:1;padding:0 .8cqw;text-align:right;font-size:1.1cqw;font-weight:700;color:{INK};">{self_v}</div>'
            f'<div style="flex:1;padding:0 .8cqw;text-align:right;font-size:1.02cqw;color:{SUB};">{base_v}</div>'
            f'<div style="flex:1;padding:0 .8cqw;text-align:right;font-size:1.1cqw;font-weight:800;color:{dcol};">{diff:+.2f}</div></div>'
        )
    return (
        '<div style="flex:1;display:flex;flex-direction:column;min-width:0;">'
        f'<div style="font-size:1.5cqw;font-weight:800;color:{label_col};margin-bottom:.7cqw;">{escape(title)}</div>'
        f'<div style="flex:1;display:flex;flex-direction:column;border:1px solid {LINE};border-radius:.7cqw;overflow:hidden;">{head}{body}</div></div>'
    )


def html_slide03(b: dict) -> str:
    if not b["strengths"] and not b["weaknesses"]:
        body = f'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:{SUB};font-size:1.4cqw;">比較できるデータが不足しています。</div>'
    else:
        body = (
            '<div style="flex:1;display:flex;gap:2.6cqw;min-height:0;">'
            + _sw_table("強み TOP5", b["strengths"], POS, POS)
            + _sw_table("弱み TOP5", b["weaknesses"], NEG, NEG)
            + '</div>'
        )
    inner = _head("SLIDE 03", "数値による比較評価", "強み・弱みの上位項目（対象 vs 基準）") + body
    return _canvas(inner)


def html_slide04(b: dict) -> str:
    if not b["samples"]:
        rows_html = f'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:{SUB};font-size:1.4cqw;">本文付きの口コミがありません。</div>'
    else:
        rows_html = '<div style="flex:1;display:flex;flex-direction:column;min-height:0;">'
        for i, s in enumerate(b["samples"], 1):
            rows_html += (
                '<div style="display:flex;gap:1.4cqw;flex:1;padding:.7cqw 0;border-top:1px solid #EEEDE7;align-items:center;">'
                f'<div style="flex:none;width:6cqw;font-size:1.1cqw;font-weight:800;color:{ACCENT};line-height:1.2;">口コミ<br>{i}</div>'
                f'<div style="flex:1;font-size:1.2cqw;line-height:1.5;color:#3A434E;overflow:hidden;">{escape(_clip(s, 150))}</div></div>'
            )
        rows_html += '</div>'
    note = (
        '<div style="display:flex;gap:1.4cqw;margin-top:1cqw;padding:1.2cqw 1.4cqw;background:#FBF4F9;border-radius:1cqw;align-items:center;">'
        f'<div style="flex:none;width:6cqw;font-size:1.2cqw;font-weight:800;color:{ACCENT};">示唆</div>'
        f'<div style="flex:1;font-size:1.2cqw;line-height:1.5;font-weight:600;color:{INK};">{escape(_clip(b["n1_note"], 130))}</div></div>'
    )
    inner = _head("SLIDE 04", "この施設に対する特徴的な口コミ（N=1／ミクロ分析）",
                  "平均には表れない、この施設を象徴する口コミと示唆") + rows_html + note
    return _canvas(inner)
