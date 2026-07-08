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

from . import analysis, text_analysis, topic_score

# palette (VoiceBAUM)
ACCENT = "#B0338A"
ACCENT_SOFT = "rgba(176,51,138,0.09)"
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
    topic_results: dict,      # {facility_name: topic_score.TopicScoreResult}
    profile,                  # text_analysis.TextProfile
    insights,                 # llm.InsightResult | None
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

    # ── 感情・トピックモデルによる比較（SLIDE 01-03 の素） ──────────── #
    ts = topic_results.get(target)
    valid = {n: r for n, r in topic_results.items() if r is not None and not r.empty}
    multi = len(valid) >= 2 and target in valid

    order = topic_score.TOPIC_ORDER
    target_scores = ts.sentiment_by_topic() if (ts and not ts.empty) else {}

    # per-topic baseline: 全体平均（多施設）or 中立50（単体）
    overall_topic = {}
    for t in order:
        vals = [r.sentiment_by_topic().get(t) for r in valid.values()]
        vals = [v for v in vals if v is not None]
        overall_topic[t] = (sum(vals) / len(vals)) if vals else 50.0
    baseline_label = "全体平均" if multi else "中立(50)"

    diffs = []
    for t in order:
        tv = target_scores.get(t)
        if tv is None:
            continue
        base = overall_topic[t] if multi else 50.0
        diffs.append((t, round(tv, 2), round(base, 2), round(tv - base, 2)))
    diffs_sorted = sorted(diffs, key=lambda x: x[3], reverse=True)
    strengths = diffs_sorted[:5]
    weaknesses = list(reversed(diffs_sorted[-5:])) if len(diffs_sorted) >= 1 else []

    overall_score = ts.weighted_sentiment_100 if (ts and not ts.empty) else None

    # 全体順位・全体平均との差（トピック総合スコアで）
    fac_overall = {n: r.weighted_sentiment_100 for n, r in valid.items()}
    ranked = sorted(fac_overall.items(), key=lambda z: -z[1])
    total_fac = len(ranked)
    rank = next((i + 1 for i, (nm, _) in enumerate(ranked) if nm == target), None)
    overall_mean = (sum(fac_overall.values()) / len(fac_overall)) if fac_overall else None
    d_overall = (overall_score - overall_mean) if (multi and overall_score is not None) else None

    peers = analysis.facilities_by_type(conn, "comparison")
    peer_valid = [p for p in peers if p in valid and p != target]
    peer_mean = (sum(fac_overall[p] for p in peer_valid) / len(peer_valid)) if peer_valid else None
    d_peer = (overall_score - peer_mean) if (peer_mean is not None and overall_score is not None) else None

    def _topic_diff_label(entry):
        return f"{entry[0]}（{entry[3]:+.1f}pt）" if entry else "—"

    analysis_rows = [
        ("分析対象", target),
        ("比較母数", f"{total_fac} 施設"),
        ("ピア施設数", f"{len(peer_valid)} 施設"),
        ("全体スコア", f"{overall_score}" if overall_score is not None else "—"),
        ("全体順位", f"{rank} / {total_fac}" if rank else "—"),
        ("全体平均との差", f"{d_overall:+.2f}" if d_overall is not None else "—"),
        ("ピア平均との差", f"{d_peer:+.2f}" if d_peer is not None else "—"),
        ("最も強い差分", _topic_diff_label(strengths[0] if strengths else None)),
        ("最も弱い差分", _topic_diff_label(weaknesses[0] if weaknesses else None)),
    ]

    # インサイト（LLM があれば採用、なければ実データからテンプレ生成）
    if insights is not None and getattr(insights, "summary", None):
        insight = {
            "結論": insights.summary,
            "強み": "、".join(insights.strengths[:3]) if insights.strengths else (strengths[0][0] if strengths else "—"),
            "弱み": "、".join(insights.weaknesses[:3]) if insights.weaknesses else (weaknesses[0][0] if weaknesses else "—"),
            "示唆": "、".join(insights.implications[:2]) if insights.implications else "—",
        }
    elif strengths and weaknesses:
        s0, s1 = strengths[0], (strengths[1] if len(strengths) > 1 else strengths[0])
        w0, w1 = weaknesses[0], (weaknesses[1] if len(weaknesses) > 1 else weaknesses[0])
        insight = {
            "結論": (f"「{target}」は「{s0[0]}」「{s1[0]}」が{baseline_label}比で相対的に強い一方、"
                    f"「{w0[0]}」「{w1[0]}」が弱い。総合スコア {overall_score}"
                    f"（{total_fac}施設中 {rank}位）。"),
            "強み": f"「{s0[0]}」が {baseline_label}比 {s0[3]:+.1f}pt で最も高評価。「{s1[0]}」（{s1[3]:+.1f}pt）も強み。",
            "弱み": f"「{w0[0]}」が {w0[3]:+.1f}pt と最も低く改善余地。「{w1[0]}」（{w1[3]:+.1f}pt）も下位。",
            "示唆": f"「{w0[0]}」「{w1[0]}」の口コミ体験を底上げすることで、総合評価の向上が期待できます。",
        }
    else:
        insight = {"結論": f"「{target}」の口コミを分析しました。", "強み": "—", "弱み": "—", "示唆": "—"}

    # SLIDE 04（TF-IDF）: 特徴語 ＋ 象徴的な N=1 コメント
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

    tfidf_words = []
    ranked_reviews = []
    if profile is not None and not profile.empty and not profile.tfidf_keywords.empty:
        tfidf_words = [str(w) for w in profile.tfidf_keywords["単語"].head(12).tolist()]
        if fid:
            _rows = conn.execute(
                "SELECT rating, text FROM review WHERE facility_id = ? "
                "AND text IS NOT NULL AND text != ''", (fid,)
            ).fetchall()
            ranked_reviews = text_analysis.symbolic_ranking(
                [(r[0], r[1]) for r in _rows], profile.tfidf_keywords, top_k=5
            )

    # SLIDE 02 — 22観点の並び順＋各スコア
    topic_names = [t for t in order if t in target_scores]
    topic_values = [round(target_scores[t], 1) for t in topic_names]

    return {
        "target": target,
        "category": category,
        "n_reviews": n_reviews,
        "avg_rating": round(float(avg_rating), 1) if avg_rating is not None else None,
        "pos_rate": pos_rate,
        "rank": rank,
        "total_fac": total_fac,
        "date": f"{date.today():%Y年%m月%d日}",
        "basis": baseline_label,
        "baseline_label": baseline_label,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "analysis_rows": analysis_rows,
        "insight": insight,
        "samples": samples,
        "tfidf_words": tfidf_words,
        "ranked_reviews": ranked_reviews,
        "n1_note": insight["示唆"],
        "topic_names": topic_names,
        "topic_values": topic_values,
        "overall_sentiment": overall_score,
        "n_sentences": ts.n_sentences if (ts and not ts.empty) else 0,
        # PROFILE（プレビューで写真アップ / 住所自動取得 / 手入力を上書き）
        "address": None,
        "access": None,
        "open_year": None,
        "photo_data_uri": None,
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
        ("業種", b.get("category") or "—"),
        ("住所", b.get("address") or "—"),
        ("アクセス", b.get("access") or "—"),
        ("開業", b.get("open_year") or "—"),
        ("口コミ", (f"平均 ★{b['avg_rating']} ／ {b['n_reviews']:,} 件"
                   if b["avg_rating"] is not None else f"{b['n_reviews']:,} 件")),
    ]
    _uri = b.get("photo_data_uri")
    if _uri:
        photo = (
            f'<div style="width:40cqw;flex:none;border-radius:1.4cqw;overflow:hidden;border:1px solid #E4E3DD;'
            f'background:#F1F0EA url(\'{_uri}\') center/cover no-repeat;"></div>'
        )
    else:
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
    """SLIDE 02: 23観点の縦棒（静的・16:10キャンバス。他スライドと同じ固定サイズ）。"""
    names = list(b.get("topic_names") or [])
    values = list(b.get("topic_values") or [])
    ov = b.get("overall_sentiment")
    if ov is not None:
        names, values = names + ["全体"], values + [ov]

    if not names:
        body = (f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
                f'color:{SUB};font-size:1.4cqw;">本文付きの口コミが不足しています。</div>')
    else:
        MAXY = 120.0
        bars = "".join(
            '<div style="flex:1;display:flex;align-items:flex-end;justify-content:center;height:100%;">'
            f'<div style="width:62%;height:{max(0.0, min(100.0, v / MAXY * 100)):.1f}%;'
            f'background:{ACCENT};border-radius:.3cqw .3cqw 0 0;"></div></div>'
            for v in values
        )
        grid = "".join(
            f'<div style="position:absolute;left:0;right:0;top:{f*100:.1f}%;height:1px;background:#EEEDE7;"></div>'
            for f in (0, 1 / 3, 2 / 3)
        )
        # 50=中立 の破線
        grid += ('<div style="position:absolute;left:0;right:0;top:%.1f%%;height:0;'
                 'border-top:1px dashed #C9C3B6;"></div>' % ((1 - 50 / MAXY) * 100))
        ylabs = "".join(
            f'<div style="position:absolute;top:{f*100:.1f}%;right:.4cqw;transform:translateY(-50%);'
            f'font-size:.9cqw;color:#A7ABB0;font-variant-numeric:tabular-nums;">{val}</div>'
            for val, f in ((120, 0), (80, 1 / 3), (40, 2 / 3), (0, 1))
        )
        xlabs = "".join(
            '<div style="flex:1;display:flex;justify-content:center;">'
            f'<span style="writing-mode:vertical-rl;font-size:.85cqw;color:#5B6672;'
            f'white-space:nowrap;letter-spacing:.02em;">{escape(nm)}</span></div>'
            for nm in names
        )
        plot = (
            '<div style="flex:1;display:flex;flex-direction:column;min-height:0;">'
            '<div style="flex:1;display:flex;min-height:0;">'
            f'<div style="width:4cqw;flex:none;position:relative;">{ylabs}</div>'
            '<div style="flex:1;position:relative;display:flex;align-items:flex-end;gap:.4cqw;'
            f'border-bottom:1px solid #E1E0D9;">{grid}{bars}</div></div>'
            '<div style="height:11cqw;display:flex;">'
            '<div style="width:4cqw;flex:none;"></div>'
            f'<div style="flex:1;display:flex;gap:.4cqw;padding-top:.8cqw;">{xlabs}</div></div>'
            '</div>'
        )
        foot = ""
        if ov is not None:
            foot = (f'<div style="font-size:1.15cqw;color:#A7ABB0;margin-top:.6cqw;">'
                    f'総合感情スコア {ov}/100 ・ 分析文数 {b.get("n_sentences", 0):,} ・ '
                    f'感情・トピック統合スコアモデルによる算出</div>')
        body = plot + foot

    inner = _head("SLIDE 02", "感情評価・トピック分類",
                  "23観点での言及・評価スコア（独自指標・50=中立）") + body
    return _canvas(inner)


def _sw_table(title: str, rows, header_bg: str, label_col: str, base_label: str = "基準") -> str:
    head = (
        f'<div style="display:flex;background:{header_bg};color:#fff;font-weight:700;font-size:1.05cqw;">'
        '<div style="flex:1.7;padding:.55cqw .8cqw;">トピック</div>'
        '<div style="flex:1;padding:.55cqw .8cqw;text-align:right;">対象</div>'
        f'<div style="flex:1;padding:.55cqw .8cqw;text-align:right;">{escape(base_label)}</div>'
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
    base = b.get("baseline_label", "基準")
    if not b["strengths"] and not b["weaknesses"]:
        body = f'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:{SUB};font-size:1.4cqw;">比較できるデータが不足しています。</div>'
    else:
        body = (
            '<div style="flex:1;display:flex;gap:2.6cqw;min-height:0;">'
            + _sw_table("強み TOP5", b["strengths"], POS, POS, base_label=base)
            + _sw_table("弱み TOP5", b["weaknesses"], NEG, NEG, base_label=base)
            + '</div>'
        )
    inner = _head("SLIDE 03", "数値による比較評価",
                  f"感情・トピック統合スコアの上位項目（対象 vs {base}）") + body
    return _canvas(inner)


def html_slide04(b: dict) -> str:
    # TF-IDF 特徴語（コンパクトな上部ストリップ）
    words = (b.get("tfidf_words") or [])[:10]
    chips = "".join(
        f'<span style="display:inline-block;background:{ACCENT_SOFT};color:{ACCENT};font-weight:700;'
        f'font-size:1.02cqw;padding:.3cqw .8cqw;border-radius:99px;margin:0 .5cqw .4cqw 0;">{escape(w)}</span>'
        for w in words
    ) or f'<span style="color:{SUB};font-size:1.1cqw;">特徴語なし</span>'
    chips_row = (
        '<div style="margin-bottom:1cqw;line-height:1.9;">'
        f'<span style="font-size:1.2cqw;font-weight:800;color:{INK};">■ TF-IDF 特徴語　</span>{chips}</div>'
    )

    # 象徴度ランキング（特徴語をどれだけ体現しているか）
    ranked = b.get("ranked_reviews") or []
    if not ranked:
        rows_html = (f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
                     f'color:{SUB};font-size:1.3cqw;">本文付きの口コミが不足しています。</div>')
    else:
        rows = ""
        for r in ranked:
            kw = "・".join(r.get("keywords", [])[:5])
            star = f'★{r["rating"]}' if r.get("rating") is not None else ""
            rows += (
                '<div style="display:flex;align-items:center;gap:1.4cqw;flex:1;border-top:1px solid #EEEDE7;'
                'padding:.5cqw 0;min-height:0;">'
                f'<div style="width:3.4cqw;height:3.4cqw;flex:none;border-radius:50%;background:{ACCENT};'
                'color:#fff;font-weight:800;font-size:1.5cqw;display:flex;align-items:center;'
                f'justify-content:center;">{r["rank"]}</div>'
                '<div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;">'
                f'<div style="font-size:1.1cqw;line-height:1.4;color:#3A434E;overflow:hidden;">{escape(_clip(r["text"], 95))}</div>'
                f'<div style="font-size:.92cqw;color:{ACCENT};margin-top:.3cqw;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">{escape(kw)}</div></div>'
                '<div style="flex:none;width:8.5cqw;text-align:right;">'
                f'<div style="font-size:1.35cqw;font-weight:800;color:{INK};font-variant-numeric:tabular-nums;">象徴度 {r["share"]:.0f}</div>'
                f'<div style="font-size:1cqw;color:{SUB};">{star}</div></div></div>'
            )
        rows_html = f'<div style="flex:1;display:flex;flex-direction:column;min-height:0;">{rows}</div>'

    note = (
        '<div style="display:flex;gap:1.4cqw;margin-top:.8cqw;padding:1cqw 1.4cqw;background:#FBF4F9;border-radius:1cqw;align-items:center;">'
        f'<div style="flex:none;width:5.5cqw;font-size:1.1cqw;font-weight:800;color:{ACCENT};">示唆</div>'
        f'<div style="flex:1;font-size:1.1cqw;line-height:1.5;font-weight:600;color:{INK};">{escape(_clip(b["n1_note"], 110))}</div></div>'
    )
    body = chips_row + rows_html + note
    inner = _head("SLIDE 04", "象徴的な口コミ ランキング（TF-IDF 総合分析）",
                  "施設の特徴語をどれだけ体現しているかで口コミを総合スコア化し上位を抽出") + body
    return _canvas(inner)
