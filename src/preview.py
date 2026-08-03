"""In-app analysis result screen — render the report as 16:10 slide canvases.

Produces a serialisable "bundle" of real data (KPIs, comparison, insights,
topic bars, N=1 comments) and HTML builders for each slide. Every slide is a
fixed 16:10 (PowerPoint-shaped) canvas using `container-type:inline-size` +
`cqw` units, so it scales proportionally like a slide thumbnail at any width.
"""
from __future__ import annotations

import base64
import sqlite3
from datetime import date
from html import escape
from typing import Optional

from . import (analysis, config, db, discussion, text_analysis, timeline,
               topic_score, voices)

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
# SLIDE 3（指定競合との比較）— 紺のパネル見出しと競合A〜Dの系列色
PANEL_HEAD = "#1B2A5B"
PEER_COLORS = ["#1B2A5B", "#5B9BD5", "#1FA98C", "#7B4FD8"]
NEU_LINE = "#A7ABB0"


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
    peers_override: list | None = None,  # 指定競合モード: 明示的な比較施設リスト
    change_points: list | None = None,   # LLMで説明文を入れた変化点（SLIDE 4）
    voices_result: list | None = None,   # LLMが選んだ代表口コミ（SLIDE 6）
    discussion_result=None,              # SLIDE 7: LLMの出力 dict、または
                                         # 課題リストを受け取って dict を返す callable
) -> dict:
    frow = conn.execute(
        "SELECT id, category, general_rating, floor_area FROM facility WHERE name = ?", (target,)
    ).fetchone()
    fid = frow["id"] if frow else None
    category = (frow["category"] if frow and frow["category"] else "—")
    general_rating = frow["general_rating"] if frow else None
    floor_area = frow["floor_area"] if frow else None

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
    valid_all = {n: r for n, r in topic_results.items() if r is not None and not r.empty}

    # ── 比較母数 ─────────────────────────────────────────────────── #
    # 指定競合モード（peers_override あり）では母数を「自施設＋選択した競合」に
    # 絞る。以降の順位・スコア分布・各観点の基準値がすべてこの範囲で計算される。
    # マーケットモードでは従来どおり DB 全施設が母数。
    is_competitor_mode = peers_override is not None
    if is_competitor_mode:
        peers = [p for p in peers_override if p != target]
        valid = {n: r for n, r in valid_all.items() if n == target or n in peers}
    else:
        peers = analysis.facilities_by_type(conn, "comparison")
        valid = valid_all
    peer_valid = [p for p in peers if p in valid_all and p != target]
    scope_label = "選択競合内" if is_competitor_mode else "市場内"
    scope_noun = "選択競合" if is_competitor_mode else "市場"

    multi = len(valid) >= 2 and target in valid

    order = topic_score.TOPIC_ORDER
    target_scores = ts.sentiment_by_topic() if (ts and not ts.empty) else {}

    # 各観点の基準値。指定競合モードは「選択競合の平均」（自施設は母数が小さく
    # 自分自身に引きずられるため除外）。マーケットモードは母数全体の平均。
    baseline_src = {n: valid_all[n] for n in peer_valid} if is_competitor_mode else valid
    overall_topic = {}
    for t in order:
        vals = [r.sentiment_by_topic().get(t) for r in baseline_src.values()]
        vals = [v for v in vals if v is not None]
        overall_topic[t] = (sum(vals) / len(vals)) if vals else 50.0
    has_baseline = bool(baseline_src) and multi
    baseline_label = (
        ("選択競合の平均" if is_competitor_mode else "全体平均")
        if has_baseline else "中立(50)"
    )

    diffs = []
    for t in order:
        tv = target_scores.get(t)
        if tv is None:
            continue
        base = overall_topic[t] if has_baseline else 50.0
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

    peer_mean = (sum(fac_overall[p] for p in peer_valid) / len(peer_valid)) if peer_valid else None
    d_peer = (overall_score - peer_mean) if (peer_mean is not None and overall_score is not None) else None

    # ── 比較対象施設カード（同カテゴリ優先で最大5件・写真つき）────────── #
    PEER_DISPLAY_CAP = 5
    peer_info: dict[str, dict] = {}
    if peer_valid:
        ph = ",".join("?" * len(peer_valid))
        for r in conn.execute(
            f"SELECT id, name, category FROM facility WHERE name IN ({ph})", peer_valid
        ).fetchall():
            peer_info[r["name"]] = {"id": r["id"], "category": r["category"]}
    same_cat = [p for p in sorted(peer_valid) if category != "—" and peer_info.get(p, {}).get("category") == category]
    other_cat = [p for p in sorted(peer_valid) if p not in same_cat]
    peer_display_names = (same_cat + other_cat)[:PEER_DISPLAY_CAP]

    peer_display = []
    for name in peer_display_names:
        pid = peer_info.get(name, {}).get("id")
        photo_uri = None
        if pid:
            p = db.get_photo(conn, pid)
            if p:
                photo_uri = f"data:{p['mime']};base64," + base64.b64encode(p["image"]).decode()
        peer_display.append({"name": name, "photo_data_uri": photo_uri})

    # ── 口コミ数の推移（月次・累積）─────────────────────────────────── #
    review_trend = []
    if fid:
        cum = 0
        for ym, cnt in db.monthly_review_counts(conn, fid):
            cum += cnt
            review_trend.append((ym, cum))

    # SLIDE 7「ディスカッションポイント」— 課題の抽出と優先度づけ。
    # 文章は LLM が書くが、課題そのもの・スコア・差・優先度はここで決める。
    _issues: list = []
    _actions: list = []

    def _topic_diff_label(entry):
        return f"{entry[0]}（{entry[3]:+.1f}pt）" if entry else "—"

    analysis_rows = [
        ("分析対象", target),
        ("比較母数", f"{scope_noun} {total_fac} 施設"),
        ("ピア施設数", f"{len(peer_valid)} 施設"),
        ("全体スコア", f"{overall_score}" if overall_score is not None else "—"),
        (f"{scope_label}順位", f"{rank} / {total_fac}" if rank else "—"),
        (f"{scope_noun}平均との差", f"{d_overall:+.2f}" if d_overall is not None else "—"),
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
                    f"（{scope_label} {total_fac}施設中 {rank}位）。"),
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

    # 比較施設ごとのトピックスコア（{施設名: {トピック: score}}）
    peer_topic_scores: dict[str, dict[str, float]] = {}
    for p in peer_valid:
        if p in valid:
            peer_topic_scores[p] = {t: round(v, 1) for t, v in valid[p].sentiment_by_topic().items()}

    # 全施設の総合スコア分布（ヒストグラム用）
    ranking_dist = sorted(fac_overall.values())

    # 上位何%か（SLIDE 2 の「上位19%」）
    percentile = round(100 * rank / total_fac) if (rank and total_fac) else None

    # 総合体験評価マッピング用（横軸=体験満足度／縦軸=推奨意向／バブル=再訪意向）。
    # 比較母数の全施設ぶんを返す（SLIDE 2 は市場全体、SLIDE 3 は競合のみを描く）。
    outcome_map: dict[str, dict[str, float]] = {}
    for _nm, _r in valid.items():
        _sb = _r.sentiment_by_topic()
        outcome_map[_nm] = {
            t: round(_sb.get(t, 50.0), 1) for t in topic_score.OUTCOME_TOPICS
        }

    # マーケット傾向（この市場で評価されやすい／課題になりやすい指標）。
    # driver 19指標の母数平均を高い順・低い順に並べる。
    _mkt = [(t, overall_topic[t]) for t in topic_score.DRIVER_TOPICS if t in overall_topic]
    _mkt.sort(key=lambda x: -x[1])
    market_trend_good = [t for t, _ in _mkt[:5]]
    market_trend_bad = [t for t, _ in _mkt[-5:]][::-1]

    # 月別ポジ/ネガ件数
    monthly_pos_neg = db.monthly_rating_counts(conn, fid) if fid else []

    # SLIDE 4「時間軸分析」— 月次のポジ/ネガ要因スコアと、評価が動いた月。
    # 変化点の説明文は LLM が後から埋める（analysis_mode 側）。ここでは
    # 検出と影響ptの算出だけを決定論的に行う。
    monthly_series = db.monthly_sentiment_series(conn, fid) if fid else []
    if change_points is None:
        change_points = timeline.detect_change_points(monthly_series)

    # SLIDE 6「特徴的な口コミ」— LLM が選んでいなければキーワードで決定論的に選ぶ
    if voices_result is None:
        _vrows = conn.execute(
            "SELECT rating, text FROM review WHERE facility_id = ? "
            "AND text IS NOT NULL AND text != ''", (fid,)
        ).fetchall() if fid else []
        voices_result = voices.pick_fallback([(r[0], r[1]) for r in _vrows])

    # ── 分析期間 ────────────────────────────────────────────────────── #
    # 固定値ではなく、その施設の口コミが実際にカバーしている範囲から出す。
    # スライドによって対象が違うので2種類返す:
    #   period_label       … 対象施設だけ（SLIDE 1「施設・基本情報」など）
    #   period_label_scope … 対象施設＋比較施設（比較系スライドのヘッダ）
    def _ym(s: str) -> str:
        return f"{s[:4]}/{s[5:7].lstrip('0')}" if len(s) >= 7 else str(s)

    def _period_of(names: list[str]) -> str:
        if not names:
            return ""
        ph = ",".join("?" * len(names))
        row = conn.execute(
            f"SELECT MIN(r.review_date), MAX(r.review_date) FROM review r "
            f"JOIN facility f ON f.id = r.facility_id "
            f"WHERE f.name IN ({ph}) AND r.review_date IS NOT NULL AND r.review_date != ''",
            names,
        ).fetchone()
        if not row or not row[0] or not row[1]:
            return ""
        return f"{_ym(row[0])}〜{_ym(row[1])}"

    period_label = _period_of([target])
    period_label_scope = _period_of([target] + peer_valid) or period_label

    _bundle_for_issues = {
        "topic_names": topic_names, "topic_values": topic_values,
        "overall_topic": overall_topic, "baseline_label": baseline_label,
    }
    _issues = discussion.pick_issues(_bundle_for_issues)
    # callable を渡せる。課題はここで確定するので、LLM 呼び出しのためだけに
    # build_bundle を2回走らせずに済む。
    if callable(discussion_result) and _issues:
        discussion_result = discussion_result(_issues)
    if discussion_result is not None and _issues:
        _actions = discussion.apply_llm_result(_issues, discussion_result) or []
    if not _actions and _issues:
        _actions = discussion.fallback_actions(_issues)

    return {
        "target": target,
        "category": category,
        "n_reviews": n_reviews,
        "avg_rating": round(float(avg_rating), 1) if avg_rating is not None else None,
        "pos_rate": pos_rate,
        "rank": rank,
        "total_fac": total_fac,
        # 比較母数のスコープ（指定競合モードか市場全体か）— スライドの見出しに使う
        "comparison_scope": "competitor" if is_competitor_mode else "market",
        "scope_label": scope_label,   # 「選択競合内」/「市場内」
        "scope_noun": scope_noun,     # 「選択競合」/「市場」
        "period_label": period_label,              # 対象施設の口コミ期間
        "period_label_scope": period_label_scope,  # 対象施設＋比較施設の口コミ期間
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
        # APPENDIX — 比較対象（ピア）施設の一覧
        "peer_names": sorted(peer_valid),
        "peer_count": len(peer_valid),
        # SLIDE 2-5 追加データ
        "ranking_dist": ranking_dist,
        "percentile": percentile,
        "outcome_map": outcome_map,
        "market_trend_good": market_trend_good,
        "market_trend_bad": market_trend_bad,
        "overall_topic": overall_topic,
        "peer_topic_scores": peer_topic_scores,
        "monthly_pos_neg": monthly_pos_neg,
        "monthly_series": monthly_series,
        "change_points": change_points,
        "voices": voices_result,
        "issues": _issues,
        "actions": _actions,
        # SLIDE 1（施設・基本情報）— 比較対象カード（同カテゴリ優先・写真つき最大5件）
        "peer_display": peer_display,
        "peer_display_same_category": bool(same_cat),
        # SLIDE 1 — 口コミ数の推移（月次・累積）: [(YYYY-MM, 累積件数), ...]
        "review_trend": review_trend,
        # PROFILE（プレビューで写真アップ / 住所自動取得 / 手入力を上書き）
        "address": None,
        "access": None,
        "open_year": None,
        "floor_area": floor_area,
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
def html_disclaimer(b: dict) -> str:
    """免責事項 — 分析アウトプットの冒頭1枚目に表示する。"""
    rows = ""
    for i, p in enumerate(config.DISCLAIMER_POINTS, 1):
        rows += (
            '<div style="display:flex;gap:1.2cqw;align-items:flex-start;padding:.55cqw 0;">'
            f'<span style="flex:none;width:2.1cqw;height:2.1cqw;border-radius:50%;background:{ACCENT_SOFT};'
            f'color:{ACCENT};font-weight:800;font-size:1.05cqw;display:flex;align-items:center;'
            f'justify-content:center;margin-top:.15cqw;">{i}</span>'
            f'<span style="flex:1;font-size:1.18cqw;line-height:1.55;color:{INK};">{escape(p)}</span></div>'
        )
    card = (
        f'<div style="flex:1;background:#FBFBF9;border:1px solid {CARD_LINE};border-radius:1.4cqw;'
        'padding:1.8cqw 2.4cqw;min-height:0;overflow:hidden;display:flex;flex-direction:column;'
        f'justify-content:center;">{rows}</div>'
    )
    foot = (
        f'<div style="margin-top:1cqw;font-size:1.05cqw;color:{SUB};">'
        f'データ基準日: {escape(b.get("date", ""))}　／　本レポートは参考情報です（VoiceBAUM）</div>'
    )
    inner = _head("免責事項", config.DISCLAIMER_TITLE,
                  "本レポートをご覧いただく前に、以下をご確認ください") + card + foot
    return _canvas(inner)


# ─────────────────────────────────────────────────────────────────────────── #
# SLIDE 1「施設・基本情報」— 新配色（濃紺＋ピンク）。このスライド限定のテーマで、
# 他スライドの VoiceBAUM 基調（ACCENT=マゼンタ）には影響しない。
# OVERVIEW / PROFILE / APPENDIX を1枚に統合したレイアウト。
# ─────────────────────────────────────────────────────────────────────────── #
S1_NAVY = "#101A38"
S1_PINK = "#EB1E4E"
S1_PINK_SOFT = "rgba(235,30,78,0.09)"
S1_LINE = "#E7E7EA"


def _canvas_s1(header_html: str, body_html: str) -> str:
    """全幅ヘッダー帯 + パディング付きボディ、の16:10キャンバス（通常の _canvas とは別枠）。"""
    return (
        f'<div style="width:100%;aspect-ratio:16/10;background:#fff;border:1px solid {CARD_LINE};'
        'border-radius:14px;box-shadow:0 1px 2px rgba(20,30,40,.04),0 14px 36px rgba(20,30,40,.05);'
        'overflow:hidden;container-type:inline-size;position:relative;margin-bottom:16px;">'
        '<div style="position:absolute;inset:0;display:flex;flex-direction:column;">'
        f'{header_html}'
        '<div style="flex:1;padding:1.5cqw 2.2cqw 1.2cqw;display:flex;flex-direction:column;min-height:0;">'
        f'{body_html}</div></div></div>'
    )


def _s1_header(title: str, period: str) -> str:
    period_html = (
        f'<div style="margin-left:auto;font-size:1.02cqw;color:#C7CCDA;background:rgba(255,255,255,.09);'
        f'padding:.5cqw 1.1cqw;border-radius:.5cqw;white-space:nowrap;">{escape(period)}</div>'
        if period else ""
    )
    return (
        f'<div style="flex:none;background:{S1_NAVY};padding:1.1cqw 2.2cqw;'
        'display:flex;align-items:center;gap:1.1cqw;">'
        f'<div style="flex:none;width:2.5cqw;height:2.5cqw;background:{S1_PINK};border-radius:.5cqw;'
        'display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.6cqw;font-weight:800;">1</div>'
        f'<div style="font-size:1.8cqw;font-weight:800;color:#fff;letter-spacing:.02em;">{escape(title)}</div>'
        f'{period_html}</div>'
    )


def _s1_card_open(icon: str, title: str, flex) -> str:
    return (
        f'<div style="flex:{flex};min-width:0;min-height:0;display:flex;flex-direction:column;'
        f'border:1px solid {S1_LINE};border-radius:.8cqw;overflow:hidden;background:#fff;">'
        f'<div style="flex:none;background:{S1_NAVY};color:#fff;padding:.6cqw 1cqw;'
        'display:flex;align-items:center;gap:.55cqw;font-size:1.05cqw;font-weight:700;">'
        f'<span>{icon}</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{escape(title)}</span></div>'
        '<div style="flex:1;min-height:0;padding:1cqw 1.1cqw;display:flex;flex-direction:column;">'
    )


_S1_CARD_CLOSE = '</div></div>'


def _s1_profile_body(b: dict) -> str:
    uri = b.get("photo_data_uri")
    if uri:
        photo = (
            '<div style="width:100%;flex:1;min-height:0;border-radius:.6cqw;overflow:hidden;'
            f'background:#F1F0EA url(\'{uri}\') center/cover no-repeat;margin-bottom:.6cqw;"></div>'
        )
    else:
        photo = (
            '<div style="width:100%;flex:1;min-height:0;border-radius:.6cqw;'
            'background:linear-gradient(160deg,#EEF0F5,#E4E7EC);display:flex;align-items:center;'
            f'justify-content:center;color:#A7ABB0;font-size:1cqw;margin-bottom:.6cqw;">施設写真</div>'
        )
    rows = [
        ("📍", "住所", b.get("address") or "—"),
        ("📅", "開業", b.get("open_year") or "—"),
        ("🏢", "延床", b.get("floor_area") or "—"),
        ("🏷️", "カテゴリ", b.get("category") or "—"),
    ]
    items = ""
    for icon, label, val in rows:
        items += (
            '<div style="display:flex;align-items:center;gap:.55cqw;padding:.3cqw 0;border-top:1px solid #F0F0F2;flex:none;">'
            f'<span style="flex:none;font-size:.9cqw;">{icon}</span>'
            f'<span style="flex:none;width:5.2cqw;font-size:.85cqw;color:{SUB};">{escape(label)}</span>'
            f'<span style="flex:1;min-width:0;font-size:.95cqw;font-weight:700;color:{INK};'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{escape(str(val))}</span></div>'
        )
    return photo + f'<div style="flex:none;">{items}</div>'


def _s1_summary_body(b: dict) -> str:
    n_reviews = b.get("n_reviews", 0)
    avg = b.get("avg_rating")
    stars = ""
    if avg is not None:
        filled = round(avg)
        for i in range(5):
            col = "#F0A93E" if i < filled else "#DDDDE2"
            stars += f'<span style="color:{col};font-size:1.5cqw;line-height:1;">★</span>'
    return (
        '<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:space-evenly;">'
        '<div style="text-align:center;">'
        f'<div style="font-size:.95cqw;color:{SUB};font-weight:600;margin-bottom:.4cqw;">総口コミ数</div>'
        f'<div style="font-size:2.5cqw;font-weight:800;color:{S1_PINK};line-height:1;">{n_reviews:,}'
        f'<span style="font-size:1.05cqw;color:{SUB};font-weight:600;"> 件</span></div></div>'
        '<div style="text-align:center;">'
        f'<div style="font-size:.95cqw;color:{SUB};font-weight:600;margin-bottom:.4cqw;">総合評価</div>'
        f'<div style="font-size:2.5cqw;font-weight:800;color:{INK};line-height:1;">'
        f'{avg if avg is not None else "—"}<span style="font-size:1.05cqw;color:{SUB};font-weight:600;"> / 5</span></div>'
        f'<div style="margin-top:.35cqw;">{stars}</div></div></div>'
    )


def _trend_trend_note(trend: list) -> str:
    """直近3ヶ月 vs その前3ヶ月の新規件数（累積の差分）で増減傾向を簡易判定。"""
    if len(trend) < 4:
        return ""
    diffs = [trend[i][1] - trend[i - 1][1] for i in range(1, len(trend))]
    if len(diffs) >= 6:
        recent, prev = diffs[-3:], diffs[-6:-3]
    else:
        half = len(diffs) // 2
        recent, prev = diffs[half:], diffs[:half]
    if not prev or not recent:
        return ""
    r_avg, p_avg = sum(recent) / len(recent), sum(prev) / len(prev)
    if p_avg <= 0:
        return "継続的に増加傾向" if r_avg > 0 else ""
    if r_avg > p_avg * 1.1:
        return "継続的に増加傾向"
    if r_avg < p_avg * 0.9:
        return "減少傾向"
    return "横ばい傾向"


def _s1_trend_body(trend: list) -> str:
    if len(trend) < 2:
        return (f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
                f'color:{SUB};font-size:1cqw;">推移を描画するにはデータが不足しています</div>')

    values = [v for _, v in trend]
    max_v = max(values) or 1
    n = len(trend)
    pts = [((i / (n - 1)) * 100 if n > 1 else 0, 100 - (v / max_v) * 90) for i, (_, v) in enumerate(trend)]
    poly = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    area = f"0,100 {poly} 100,100"
    dots = "".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.6" fill="{S1_PINK}" vector-effect="non-scaling-stroke" />'
        for x, y in pts
    )

    step = max(1, (n - 1) // 6) if n > 1 else 1
    xlabs = "".join(
        f'<span style="position:absolute;left:{pts[i][0]:.1f}%;top:0;transform:translateX(-50%);'
        f'font-size:.68cqw;color:#A7ABB0;white-space:nowrap;">{escape(trend[i][0])}</span>'
        for i in range(0, n, step)
    )
    if (n - 1) % step != 0:
        xlabs += (
            f'<span style="position:absolute;left:{pts[-1][0]:.1f}%;top:0;transform:translateX(-50%);'
            f'font-size:.68cqw;color:#A7ABB0;white-space:nowrap;">{escape(trend[-1][0])}</span>'
        )

    ylabs = "".join(
        f'<div style="position:absolute;top:{100 - frac * 90:.1f}%;right:0;transform:translateY(-50%);'
        f'font-size:.72cqw;color:#A7ABB0;">{int(max_v * frac):,}</div>'
        for frac in (0, 0.5, 1.0)
    )

    note = _trend_trend_note(trend)
    note_html = ""
    if note:
        note_html = (
            f'<div style="position:absolute;top:.3cqw;right:2.8cqw;background:{S1_PINK_SOFT};color:{S1_PINK};'
            f'font-size:.8cqw;font-weight:700;padding:.35cqw .75cqw;border-radius:99px;white-space:nowrap;">'
            f'{escape(note)}</div>'
        )

    return (
        '<div style="flex:1;display:flex;flex-direction:column;min-height:0;">'
        '<div style="flex:1;position:relative;min-height:0;">'
        f'{note_html}'
        f'<div style="position:absolute;top:0;bottom:1.3cqw;left:0;right:2.6cqw;'
        f'border-bottom:1px solid {S1_LINE};">'
        f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width:100%;height:100%;overflow:visible;">'
        f'<polygon points="{area}" fill="{S1_PINK_SOFT}" stroke="none" />'
        f'<polyline points="{poly}" fill="none" stroke="{S1_PINK}" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />'
        f'{dots}</svg></div>'
        f'<div style="position:absolute;top:0;bottom:1.3cqw;right:0;width:2.6cqw;">{ylabs}</div>'
        f'<div style="position:absolute;bottom:0;left:0;right:2.6cqw;height:1.3cqw;">{xlabs}</div>'
        '</div></div>'
    )


def _s1_peers_body(b: dict) -> str:
    peers = b.get("peer_display") or []
    if not peers:
        return (f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
                f'color:{SUB};font-size:1.1cqw;">比較対象施設がありません</div>')
    items = ""
    for p in peers:
        uri = p.get("photo_data_uri")
        if uri:
            img = (
                '<div style="width:100%;aspect-ratio:4/3;border-radius:.6cqw;overflow:hidden;'
                f'background:#F1F0EA url(\'{uri}\') center/cover no-repeat;"></div>'
            )
        else:
            img = (
                '<div style="width:100%;aspect-ratio:4/3;border-radius:.6cqw;'
                'background:linear-gradient(160deg,#EEF0F5,#E4E7EC);display:flex;align-items:center;'
                f'justify-content:center;color:#A7ABB0;font-size:1.5cqw;">🏢</div>'
            )
        items += (
            '<div style="flex:1;min-width:0;">' + img +
            f'<div style="margin-top:.5cqw;text-align:center;background:{S1_PINK_SOFT};color:{INK};'
            'font-size:.92cqw;font-weight:700;padding:.4cqw .3cqw;border-radius:.4cqw;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{escape(p["name"])}</div></div>'
        )
    return f'<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;">{items}</div>'


def html_facility_info(b: dict) -> str:
    """SLIDE 1「施設・基本情報」— OVERVIEW / PROFILE / APPENDIX を1枚に統合。

    施設プロフィール（写真・住所・開業・延床・カテゴリ）／口コミサマリー（件数・評価）／
    口コミ数の推移（月次累積の折れ線）／比較対象施設（同カテゴリ優先・写真つき最大5件）。
    """
    trend = b.get("review_trend") or []
    period = f"分析期間：{trend[0][0]}〜{trend[-1][0]}（累積推移）" if len(trend) >= 2 else ""
    header = _s1_header("施設・基本情報", period)

    peer_count = len(b.get("peer_display") or [])
    peer_note = (
        f"※{'同カテゴリの' if b.get('peer_display_same_category') else ''}{peer_count}施設を比較対象として設定"
        if peer_count else ""
    )

    top_row = (
        '<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;margin-bottom:1.1cqw;">'
        + _s1_card_open("🏢", "施設プロフィール", 3) + _s1_profile_body(b) + _S1_CARD_CLOSE
        + _s1_card_open("💬", "口コミサマリー", 2) + _s1_summary_body(b) + _S1_CARD_CLOSE
        + _s1_card_open("📈", "口コミ数の推移", 4) + _s1_trend_body(trend) + _S1_CARD_CLOSE
        + '</div>'
    )

    peers_head = (
        f'<div style="flex:1;display:flex;flex-direction:column;border:1px solid {S1_LINE};'
        f'border-radius:.8cqw;overflow:hidden;background:#fff;min-height:0;">'
        f'<div style="flex:none;background:{S1_NAVY};color:#fff;padding:.6cqw 1cqw;'
        'display:flex;align-items:center;gap:.55cqw;font-size:1.05cqw;font-weight:700;">'
        '<span>👥</span><span>比較対象施設（同カテゴリの類似施設）</span>'
        f'<span style="margin-left:auto;font-size:.85cqw;font-weight:600;color:#C7CCDA;">{escape(peer_note)}</span></div>'
        f'<div style="flex:1;min-height:0;padding:.9cqw 1.1cqw;display:flex;">{_s1_peers_body(b)}</div></div>'
    )

    inner = top_row + peers_head
    return _canvas_s1(header, inner)


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


def html_appendix(b: dict) -> str:
    """APPENDIX: 比較対象（ピア）施設の一覧。ピアが無ければ空文字を返す。"""
    names = list(b.get("peer_names") or [])
    if not names:
        return ""
    count = b.get("peer_count", len(names))

    CAP = 45                       # 1スライドに収まる上限（超過分は「ほかN施設」）
    overflow = max(0, len(names) - CAP)
    shown = names[:CAP]

    header = (
        '<div style="display:flex;align-items:center;gap:1.2cqw;margin-bottom:.2cqw;">'
        + _badge("APPENDIX")
        + f'<span style="font-size:2.4cqw;font-weight:800;color:{INK};line-height:1.1;">比較対象施設一覧</span>'
        + f'<span style="margin-left:auto;font-size:1.6cqw;font-weight:800;color:{ACCENT};'
          f'white-space:nowrap;">{count} 施設</span>'
        + '</div>'
        + f'<div style="font-size:1.25cqw;color:{SUB};margin:.3cqw 0 1.8cqw;">'
          '同市場の施設からも口コミを抽出し、比較して特徴点を可視化</div>'
    )

    items = "".join(
        '<div style="break-inside:avoid;display:flex;align-items:center;gap:.9cqw;padding:.5cqw 0;">'
        f'<span style="flex:none;width:1.05cqw;height:1.05cqw;border-radius:50%;background:{ACCENT};"></span>'
        f'<span style="flex:1;min-width:0;font-size:1.2cqw;color:{INK};overflow:hidden;'
        f'white-space:nowrap;text-overflow:ellipsis;">{escape(n)}</span></div>'
        for n in shown
    )
    over_html = (
        f'<div style="margin-top:.8cqw;font-size:1.1cqw;color:{ACCENT};font-weight:700;">'
        f'ほか {overflow} 施設</div>' if overflow else ""
    )
    card = (
        f'<div style="flex:1;background:{ACCENT_SOFT};border-radius:1.4cqw;padding:2.2cqw 2.6cqw;'
        'min-height:0;overflow:hidden;">'
        '<div style="column-count:3;column-gap:2.4cqw;">'
        f'{items}</div>{over_html}</div>'
    )
    return _canvas(header + card)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 2「市場内ポジション」— ランキング × 分布 × 強み弱みTOP3
# ═══════════════════════════════════════════════════════════════════════════
def _score_5pt(v100: float) -> float:
    """0-100スケールのスコアを5点満点に変換（小数1桁）。"""
    return round(v100 / 100 * 5, 1)


def _slide_header(num: str, title: str, sub: str = "") -> str:
    sub_html = (
        f'<div style="font-size:1.1cqw;color:{SUB};margin:.2cqw 0 1.6cqw;">{escape(sub)}</div>'
        if sub else '<div style="height:1.4cqw"></div>'
    )
    return (
        '<div style="display:flex;align-items:center;gap:1.1cqw;margin-bottom:.1cqw;">'
        f'<div style="flex:none;width:2.8cqw;height:2.8cqw;background:{ACCENT};border-radius:.55cqw;'
        'color:#fff;font-weight:800;font-size:1.3cqw;display:flex;align-items:center;'
        f'justify-content:center;">{escape(num)}</div>'
        f'<div style="font-size:2.2cqw;font-weight:800;color:{INK};line-height:1.1;">{escape(title)}</div></div>'
        + sub_html
    )


def html_market_position(b: dict) -> str:
    """SLIDE 2「市場内ポジション」— 王冠ランキング＋スコア分布＋強み弱みTOP3。"""
    rank = b.get("rank")
    total = b.get("total_fac", 0)
    avg_rating = b.get("avg_rating")
    overall_score = b.get("overall_sentiment")
    strengths = (b.get("strengths") or [])[:3]
    weaknesses = (b.get("weaknesses") or [])[:3]
    ranking_dist = list(b.get("ranking_dist") or [])
    target_score = overall_score or 0.0

    # ── ランキングカード (左) ──────────────────────────────────── #
    pct = round((1 - rank / total) * 100) if (rank and total > 1) else None
    pct_html = (
        f'<div style="font-size:1.15cqw;font-weight:700;color:{ACCENT};'
        f'background:{ACCENT_SOFT};padding:.4cqw .9cqw;border-radius:99px;'
        f'white-space:nowrap;margin-top:.5cqw;">上位 {pct}%</div>' if pct is not None else ""
    )
    star_row = ""
    if avg_rating is not None:
        filled = round(avg_rating)
        star_row = "".join(
            f'<span style="color:{"#F0A93E" if i < filled else "#DDDDE2"};font-size:2.2cqw;">★</span>'
            for i in range(5)
        )

    rank_html = (
        f'<div style="font-size:7cqw;line-height:1;text-align:center;">🏆</div>'
        f'<div style="text-align:center;margin-top:.5cqw;">'
        f'<span style="font-size:5cqw;font-weight:800;color:{INK};line-height:1;">'
        f'{rank}</span><span style="font-size:1.4cqw;color:{SUB};"> / {total} 施設</span></div>'
        f'<div style="display:flex;justify-content:center;margin-top:.4cqw;">{star_row}</div>'
        f'<div style="display:flex;justify-content:center;margin-top:.6cqw;">{pct_html}</div>'
        f'<div style="text-align:center;margin-top:.8cqw;font-size:1.1cqw;color:{SUB};">総合スコア</div>'
        f'<div style="text-align:center;font-size:2.4cqw;font-weight:800;color:{ACCENT};">'
        f'{overall_score if overall_score is not None else "—"}<span style="font-size:1cqw;color:{SUB};">/100</span></div>'
    ) if rank else (
        f'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:{SUB};font-size:1.2cqw;">データ不足</div>'
    )

    left = (
        f'<div style="width:22cqw;flex:none;display:flex;flex-direction:column;align-items:center;'
        f'justify-content:center;border:1px solid {CARD_LINE};border-radius:1.2cqw;'
        f'background:#FAFAF8;padding:1.5cqw 1cqw;">{rank_html}</div>'
    )

    # ── スコア分布ヒストグラム ──────────────────────────────────── #
    if ranking_dist:
        BINS = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 101)]
        bin_labels = ["〜30", "30-40", "40-50", "50-60", "60-70", "70-80", "80+"]
        counts = [sum(1 for v in ranking_dist if lo <= v < hi) for lo, hi in BINS]
        max_c = max(counts) or 1
        target_bin = next(
            (i for i, (lo, hi) in enumerate(BINS) if lo <= target_score < hi),
            len(BINS) - 1,
        )
        hist_bars = "".join(
            f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:.2cqw;">'
            f'<div style="font-size:.72cqw;color:{ACCENT if i == target_bin else SUB};">{c}</div>'
            f'<div style="width:80%;height:{c/max_c*100:.0f}%;min-height:.3cqw;border-radius:.3cqw .3cqw 0 0;'
            f'background:{ACCENT if i == target_bin else "#D8D4CE"};"></div>'
            f'<div style="font-size:.68cqw;color:{ACCENT if i == target_bin else "#A7ABB0"};white-space:nowrap;">'
            f'{escape(bin_labels[i])}</div></div>'
            for i, c in enumerate(counts)
        )
        hist_html = (
            f'<div style="flex:none;margin-bottom:.6cqw;font-size:1cqw;font-weight:700;color:{INK};">スコア分布</div>'
            f'<div style="flex:1;display:flex;align-items:flex-end;gap:.2cqw;min-height:0;'
            f'border-bottom:1px solid {LINE};">{hist_bars}</div>'
        )
    else:
        hist_html = f'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:{SUB};font-size:1cqw;">分布データなし</div>'

    hist_card = (
        f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;border:1px solid {CARD_LINE};'
        f'border-radius:1.2cqw;padding:1.2cqw 1.4cqw;background:#FAFAF8;min-height:0;">{hist_html}</div>'
    )

    # ── 強み弱みTOP3 ──────────────────────────────────────────── #
    def _sw3(title: str, rows, col: str) -> str:
        items = ""
        for nm, tv, bv, diff in rows:
            bar_w = min(100, max(5, int(tv)))
            items += (
                f'<div style="padding:.4cqw 0;border-top:1px solid {LINE};">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.2cqw;">'
                f'<span style="font-size:.95cqw;font-weight:600;color:{INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:12cqw;">{escape(str(nm))}</span>'
                f'<span style="font-size:.95cqw;font-weight:800;color:{col};white-space:nowrap;">{_score_5pt(tv):.1f}pt</span></div>'
                f'<div style="height:.45cqw;background:#E4E2DC;border-radius:99px;">'
                f'<div style="width:{bar_w}%;height:100%;background:{col};border-radius:99px;"></div></div></div>'
            )
        return (
            f'<div style="flex:1;min-width:0;border:1px solid {CARD_LINE};border-radius:1.2cqw;'
            f'padding:1cqw 1.2cqw;background:#FAFAF8;">'
            f'<div style="font-size:1cqw;font-weight:800;color:{col};margin-bottom:.4cqw;">{escape(title)}</div>'
            f'{items}</div>'
        )

    sw_row = (
        f'<div style="flex:none;display:flex;gap:1.1cqw;margin-top:1.1cqw;">'
        + _sw3("強み TOP3", strengths, POS)
        + _sw3("弱み TOP3", weaknesses, NEG)
        + '</div>'
    ) if (strengths or weaknesses) else ""

    right = (
        f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:1.1cqw;">'
        f'<div style="flex:1;display:flex;gap:1.1cqw;min-height:0;">{hist_card}</div>'
        f'{sw_row}</div>'
    )

    inner = (
        _slide_header("2", f'{b.get("scope_label", "市場内")}ポジション',
                      f"比較対象 {total} 施設中の相対評価（感情・トピック統合スコア）")
        + f'<div style="flex:1;display:flex;gap:1.4cqw;min-height:0;">{left}{right}</div>'
    )
    return _canvas(inner)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 2-detail「市場内ポジション（詳細）」
# ═══════════════════════════════════════════════════════════════════════════
def html_market_detail(b: dict) -> str:
    """SLIDE 2-detail: 22観点 折れ線（当施設 vs 同業平均）＋バブルスキャッタ＋市場傾向。"""
    order = topic_score.TOPIC_ORDER
    target_scores = {t: v for t, v in zip(b.get("topic_names") or [], b.get("topic_values") or [])}
    overall_topic = b.get("overall_topic") or {}
    basis = b.get("baseline_label", "全体平均")

    # ── 折れ線チャート（当施設 vs 同業平均）────────────────────── #
    topics_avail = [t for t in order if t in target_scores and t in overall_topic]
    if topics_avail:
        n = len(topics_avail)
        t_vals = [target_scores[t] for t in topics_avail]
        b_vals = [overall_topic[t] for t in topics_avail]
        all_vals = t_vals + b_vals
        mn, mx = min(all_vals) - 5, max(all_vals) + 5
        rng = mx - mn or 1

        def _pts(vals):
            return " ".join(
                f"{(i / (n - 1) * 100 if n > 1 else 50):.2f},{(1 - (v - mn) / rng) * 100:.2f}"
                for i, v in enumerate(vals)
            )

        xlabs = "".join(
            f'<div style="position:absolute;left:{(i/(n-1)*100 if n>1 else 50):.1f}%;bottom:0;'
            'transform:translateX(-50%) rotate(-45deg);transform-origin:top center;'
            f'font-size:.62cqw;color:#A7ABB0;white-space:nowrap;">{escape(t)}</div>'
            for i, t in enumerate(topics_avail)
        )
        chart_svg = (
            f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width:100%;height:100%;overflow:visible;">'
            f'<polyline points="{_pts(b_vals)}" fill="none" stroke="{NEU}" stroke-width="1.4" '
            'stroke-dasharray="3 2" vector-effect="non-scaling-stroke" stroke-linejoin="round" />'
            f'<polyline points="{_pts(t_vals)}" fill="none" stroke="{ACCENT}" stroke-width="1.8" '
            'vector-effect="non-scaling-stroke" stroke-linejoin="round" />'
            + "".join(
                f'<circle cx="{(i/(n-1)*100 if n>1 else 50):.2f}" cy="{(1-(v-mn)/rng)*100:.2f}" '
                f'r="1.5" fill="{ACCENT}" vector-effect="non-scaling-stroke" />'
                for i, v in enumerate(t_vals)
            )
            + '</svg>'
        )
        chart = (
            '<div style="flex:1;display:flex;flex-direction:column;min-height:0;">'
            f'<div style="flex:1;position:relative;min-height:0;border-bottom:1px solid {LINE};">'
            f'<div style="position:absolute;inset:0;">{chart_svg}</div></div>'
            f'<div style="position:relative;height:5.5cqw;">{xlabs}</div>'
            f'<div style="font-size:.85cqw;color:{SUB};margin-top:.3cqw;">'
            f'<span style="color:{ACCENT};font-weight:700;">━</span> 当施設　'
            f'<span style="color:{NEU};font-weight:700;">╌</span> {escape(basis)}</div>'
            '</div>'
        )
    else:
        chart = f'<div style="flex:1;display:flex;align-items:center;justify-content:center;color:{SUB};font-size:1.1cqw;">データ不足</div>'

    left = (
        f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;border:1px solid {CARD_LINE};'
        f'border-radius:1.1cqw;padding:1.1cqw 1.3cqw;min-height:0;">'
        f'<div style="flex:none;font-size:1.05cqw;font-weight:700;color:{INK};margin-bottom:.6cqw;">22観点スコア推移（vs {escape(basis)}）</div>'
        f'{chart}</div>'
    )

    # ── バブルスキャッタ（体験満足度 × 推奨意向 × 再訪意向）──── #
    AXES = ["体験満足度", "推奨意向", "再訪意向"]
    peer_ts = b.get("peer_topic_scores") or {}
    target_name = b.get("target", "対象施設")

    def _get_xyz(scores: dict) -> tuple:
        x = scores.get(AXES[0], 50.0)
        y = scores.get(AXES[1], 50.0)
        z = scores.get(AXES[2], 50.0)
        return x, y, z

    tx, ty, tz = _get_xyz(target_scores)
    bubble_items = [(target_name, tx, ty, tz, ACCENT, True)]
    for pnm, psc in peer_ts.items():
        px, py, pz = _get_xyz(psc)
        bubble_items.append((pnm, px, py, pz, "#A7ABB0", False))

    all_x = [v[1] for v in bubble_items]
    all_y = [v[2] for v in bubble_items]
    xmn, xmx = min(all_x) - 5, max(all_x) + 5
    ymn, ymx = min(all_y) - 5, max(all_y) + 5
    xrng, yrng = (xmx - xmn) or 1, (ymx - ymn) or 1

    bubbles = ""
    for nm, bx, by, bz, col, is_target in bubble_items:
        cx = (bx - xmn) / xrng * 80 + 10
        cy = (1 - (by - ymn) / yrng) * 80 + 10
        r = max(2, min(8, bz / 100 * 8 + 2))
        bubbles += (
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{col}" fill-opacity="{"0.85" if is_target else "0.4"}" '
            'vector-effect="non-scaling-stroke" />'
        )
        if is_target:
            bubbles += (
                f'<text x="{cx:.1f}" y="{max(5, cy-r-1):.1f}" text-anchor="middle" '
                f'font-size="4" fill="{ACCENT}" font-weight="bold">{escape(_clip(nm, 8))}</text>'
            )

    scatter = (
        f'<div style="flex:none;border:1px solid {CARD_LINE};border-radius:1.1cqw;'
        f'padding:1cqw 1.3cqw;background:#FAFAF8;">'
        f'<div style="font-size:1cqw;font-weight:700;color:{INK};margin-bottom:.5cqw;">'
        f'{escape(AXES[0])} × {escape(AXES[1])}（バブル={escape(AXES[2])}）</div>'
        f'<svg viewBox="0 0 100 100" style="width:100%;aspect-ratio:2/1;">'
        f'{bubbles}'
        f'<text x="50" y="99" text-anchor="middle" font-size="4" fill="{SUB}">{escape(AXES[0])}</text>'
        f'<text x="2" y="50" text-anchor="middle" font-size="4" fill="{SUB}" '
        f'transform="rotate(-90 2 50)">{escape(AXES[1])}</text>'
        '</svg></div>'
    )

    # ── 市場傾向（評価されやすい / 課題 上位5）──────────────────── #
    all_peer_topics: dict[str, list[float]] = {}
    for psc in peer_ts.values():
        for t, v in psc.items():
            all_peer_topics.setdefault(t, []).append(v)
    mkt_scores = {t: sum(vs) / len(vs) for t, vs in all_peer_topics.items() if vs}
    if not mkt_scores and overall_topic:
        mkt_scores = overall_topic
    top_mkt = sorted(mkt_scores.items(), key=lambda x: -x[1])[:4]
    bot_mkt = sorted(mkt_scores.items(), key=lambda x: x[1])[:4]

    def _mkt_rows(items, col: str) -> str:
        return "".join(
            f'<div style="display:flex;justify-content:space-between;padding:.3cqw 0;'
            f'border-bottom:1px solid {LINE};font-size:.9cqw;">'
            f'<span style="color:{INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:10cqw;">'
            f'{escape(t)}</span>'
            f'<span style="color:{col};font-weight:700;white-space:nowrap;">{_score_5pt(v):.1f}pt</span></div>'
            for t, v in items
        )

    mkt_card = (
        f'<div style="flex:none;border:1px solid {CARD_LINE};border-radius:1.1cqw;'
        f'padding:.9cqw 1.1cqw;background:#FAFAF8;">'
        f'<div style="font-size:.95cqw;font-weight:700;color:{INK};margin-bottom:.4cqw;">'
        f'{escape(b.get("scope_noun", "市場"))}の強み傾向（競合平均）</div>'
        + _mkt_rows(top_mkt, POS)
        + f'<div style="font-size:.95cqw;font-weight:700;color:{INK};margin:.6cqw 0 .4cqw;">'
        f'{escape(b.get("scope_noun", "市場"))}の課題傾向</div>'
        + _mkt_rows(bot_mkt, NEG)
        + '</div>'
    )

    right = (
        f'<div style="width:32cqw;flex:none;display:flex;flex-direction:column;gap:1cqw;">'
        f'{scatter}{mkt_card}</div>'
    )

    inner = (
        _slide_header("2", f'{b.get("scope_label", "市場内")}ポジション（詳細）',
                      "22観点スコア推移と体験系3軸の布置")
        + f'<div style="flex:1;display:flex;gap:1.4cqw;min-height:0;">{left}{right}</div>'
    )
    return _canvas(inner)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 3「指定競合との比較」
# ═══════════════════════════════════════════════════════════════════════════
def _panel(title: str, body: str, flex: str = "flex:1") -> str:
    """紺ヘッダ＋白本文のパネル（SLIDE 3 の共通ブロック）。"""
    return (
        f'<div style="{flex};min-width:0;display:flex;flex-direction:column;'
        f'border:1px solid {CARD_LINE};border-radius:.7cqw;overflow:hidden;">'
        f'<div style="flex:none;background:{PANEL_HEAD};color:#fff;text-align:center;'
        f'font-size:1.05cqw;font-weight:800;padding:.5cqw;">{escape(title)}</div>'
        f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;'
        f'padding:.7cqw .8cqw;background:#fff;">{body}</div></div>'
    )


def html_competitor_compare(b: dict) -> str:
    """SLIDE 3「指定競合との比較」— 主要19指標の折れ線＋施設別ヒートマップ＋強み弱み。

    体験満足度・推奨意向・再訪意向は体験の結果側（outcome）なので、施設を横並びで
    比較するこのスライドでは driver 側の19指標だけを扱う（topic_score.DRIVER_TOPICS）。
    スコアはすべて 5点満点換算で表示する。
    """
    target_name = b.get("target", "対象施設")
    target_scores = {t: v for t, v in zip(b.get("topic_names") or [], b.get("topic_values") or [])}
    peer_ts = b.get("peer_topic_scores") or {}
    overall_topic = b.get("overall_topic") or {}

    topics = [t for t in topic_score.DRIVER_TOPICS if t in target_scores]
    n = len(topics)
    if not topics:
        return _canvas(
            _slide_header("3", "指定競合との比較", "2〜5施設を横並びで比較し、自施設の立ち位置を把握します。")
            + f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{SUB};font-size:1.1cqw;">比較できるデータがありません。</div>'
        )

    # ── 列の構成: 自施設 → 競合A..D → 同業平均 ──────────────────── #
    peer_names = list(peer_ts.keys())[:4]
    cols: list[tuple[str, str, dict, str]] = [("自施設", target_name, target_scores, ACCENT)]
    for i, nm in enumerate(peer_names):
        cols.append((f"競合{'ABCD'[i]}", nm, peer_ts[nm], PEER_COLORS[i]))
    has_avg = bool(overall_topic)
    if has_avg:
        cols.append(("同業平均", b.get("baseline_label", "同業平均"), overall_topic, NEU_LINE))

    # ── 主要19指標の折れ線（5点満点・1.0〜5.0固定軸）──────────────── #
    LO, HI = 1.0, 5.0

    def _y(v100: float) -> float:
        return (1 - (min(max(_score_5pt(v100), LO), HI) - LO) / (HI - LO)) * 100

    def _x(i: int) -> float:
        return i / (n - 1) * 100 if n > 1 else 50.0

    _dash_grid = 'stroke-dasharray="2 2"'
    _dash_avg = 'stroke-dasharray="3 2"'
    grid = "".join(
        f'<line x1="0" y1="{_y(g / 5 * 100):.2f}" x2="100" y2="{_y(g / 5 * 100):.2f}" '
        f'stroke="{LINE}" stroke-width=".4" vector-effect="non-scaling-stroke" '
        f'{"" if g in (1, 5) else _dash_grid} />'
        for g in (1, 2, 3, 4, 5)
    )
    series = ""
    for label, _nm, sc, col in cols:
        is_avg = label == "同業平均"
        pts = " ".join(f"{_x(i):.2f},{_y(sc.get(t, 50.0)):.2f}" for i, t in enumerate(topics))
        series += (
            f'<polyline points="{pts}" fill="none" stroke="{col}" '
            f'stroke-width="{1.1 if is_avg else 1.6}" '
            f'{_dash_avg if is_avg else ""} '
            f'stroke-linejoin="round" vector-effect="non-scaling-stroke" />'
        )
        if not is_avg:   # マーカー（同業平均は線のみ）
            series += "".join(
                f'<circle cx="{_x(i):.2f}" cy="{_y(sc.get(t, 50.0)):.2f}" r="1.1" '
                f'fill="#fff" stroke="{col}" stroke-width=".9" vector-effect="non-scaling-stroke" />'
                for i, t in enumerate(topics)
            )

    ylabs = "".join(
        f'<div style="position:absolute;top:{_y(g / 5 * 100):.2f}%;left:-1.8cqw;width:1.5cqw;'
        f'text-align:right;transform:translateY(-50%);font-size:.65cqw;color:{SUB};">{g}.0</div>'
        for g in (1, 2, 3, 4, 5)
    )
    # 19本のラベルを狭いパネルに収めるため、傾きを強めにして長い名称は詰める
    xlabs = "".join(
        f'<div style="position:absolute;left:{_x(i):.2f}%;top:0;'
        'transform:translateX(-50%) rotate(-55deg);transform-origin:top right;'
        f'font-size:.52cqw;color:{SUB};white-space:nowrap;">{escape(_clip(t, 10))}</div>'
        for i, t in enumerate(topics)
    )
    legend = "".join(
        f'<span style="margin-right:1cqw;font-size:.72cqw;white-space:nowrap;color:{INK};">'
        f'<span style="color:{col};font-weight:800;">{"╌" if lb == "同業平均" else "─○─"}</span> '
        f'{escape(lb)}</span>'
        for lb, _nm, _sc, col in cols
    )
    chart_body = (
        f'<div style="flex:none;margin-bottom:.4cqw;">{legend}</div>'
        f'<div style="flex:1;position:relative;min-height:0;margin-left:1.8cqw;">'
        f'{ylabs}'
        f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" '
        f'style="position:absolute;inset:0;width:100%;height:100%;overflow:visible;">'
        f'{grid}{series}</svg></div>'
        f'<div style="flex:none;position:relative;height:5.2cqw;margin-left:1.8cqw;">{xlabs}</div>'
    )
    chart = _panel("主要19指標の比較（5点満点）", chart_body)

    # ── 施設別スコアヒートマップ: 行=19指標 × 列=施設 ────────────── #
    #    高い=ピンク / 低い=青 の2色発散。中心は各指標の平均ではなく全体の中央値。
    heat_vals = [sc.get(t, 50.0) for _l, _n, sc, _c in cols for t in topics]
    h_min, h_max = min(heat_vals), max(heat_vals)
    h_mid = (h_min + h_max) / 2
    h_half = max(h_max - h_mid, h_mid - h_min) or 1

    def _heat_bg(v: float) -> str:
        r = (v - h_mid) / h_half          # -1(低) 〜 +1(高)
        if r >= 0:                        # 高い → ピンク
            return f"rgba(176,51,138,{0.06 + 0.24 * min(r, 1):.3f})"
        return f"rgba(45,125,210,{0.06 + 0.24 * min(-r, 1):.3f})"

    _hcell = "padding:.28cqw .1cqw;text-align:center;font-size:.72cqw;"
    head = (
        f'<div style="display:flex;background:#F4F3EE;font-weight:800;color:{SUB};">'
        f'<div style="width:7.6cqw;flex:none;{_hcell}text-align:left;padding-left:.45cqw;">指標</div>'
        + "".join(
            f'<div style="flex:1;{_hcell}color:{col};">{escape(lb)}</div>'
            for lb, _nm, _sc, col in cols
        )
        + '</div>'
    )
    rows_html = "".join(
        f'<div style="display:flex;border-top:1px solid {LINE};">'
        f'<div style="width:7.6cqw;flex:none;{_hcell}text-align:left;padding-left:.45cqw;'
        f'color:{INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{escape(t)}</div>'
        + "".join(
            f'<div style="flex:1;{_hcell}background:{_heat_bg(sc.get(t, 50.0))};'
            f'color:{INK};font-weight:700;">{_score_5pt(sc.get(t, 50.0)):.2f}</div>'
            for _l, _n, sc, _c in cols
        )
        + '</div>'
        for t in topics
    )
    heatmap = _panel(
        "施設別スコアヒートマップ（5点満点）",
        f'<div style="flex:1;min-height:0;overflow:hidden;">{head}{rows_html}</div>',
    )

    # ── 自施設だけの強み / 競合に負けている項目（競合平均との差・5点満点）── #
    sv, wv = [], []
    if peer_ts:
        for t in topics:
            tv = target_scores.get(t, 50.0)
            pvals = [psc.get(t, 50.0) for psc in peer_ts.values()]
            if not pvals:
                continue
            d5 = _score_5pt(tv) - round(sum(pvals) / len(pvals) / 100 * 5, 2)
            (sv if d5 > 0 else wv).append((t, round(d5, 2)))
        sv.sort(key=lambda x: -x[1])
        wv.sort(key=lambda x: x[1])

    def _diff_panel(title: str, rows: list, col: str, cap: int) -> str:
        if not rows:
            body = f'<div style="color:{SUB};font-size:.8cqw;">該当なし</div>'
        else:
            body = (
                '<div style="display:grid;grid-template-columns:1fr 1fr;'
                'column-gap:1.2cqw;row-gap:.3cqw;">'
                + "".join(
                    f'<div style="display:flex;align-items:center;gap:.4cqw;font-size:.8cqw;">'
                    f'<span style="flex:none;width:.42cqw;height:.42cqw;border-radius:50%;'
                    f'background:{col};"></span>'
                    f'<span style="flex:1;min-width:0;color:{INK};overflow:hidden;'
                    f'text-overflow:ellipsis;white-space:nowrap;">{escape(t)}</span>'
                    f'<span style="flex:none;color:{col};font-weight:700;">'
                    f'（{d:+.2f}）</span></div>'
                    for t, d in rows[:cap]
                )
                + '</div>'
            )
        return _panel(title, body, flex="flex:1")

    bottom = (
        '<div style="flex:none;display:flex;gap:1.2cqw;margin-top:.9cqw;height:7.2cqw;">'
        + _diff_panel("自施設だけの強み", sv, ACCENT, 6)
        + _diff_panel("競合に負けている項目", wv, PANEL_HEAD, 4)
        + '</div>'
    )

    n_fac = len(cols) - 1 if has_avg else len(cols)
    # 比較スライドなので、対象施設だけでなく比較施設も含めた期間を出す
    period = b.get("period_label_scope") or b.get("period_label") or ""
    meta = (
        f'<div style="margin-left:auto;text-align:right;font-size:.85cqw;color:{SUB};">'
        f'分析対象：{n_fac}施設'
        + (f'　分析期間：{escape(period)}' if period else "")
        + '</div>'
    )
    header = (
        '<div style="display:flex;align-items:center;gap:1.1cqw;margin-bottom:.1cqw;">'
        f'<div style="flex:none;width:2.8cqw;height:2.8cqw;background:{ACCENT};border-radius:.55cqw;'
        'color:#fff;font-weight:800;font-size:1.3cqw;display:flex;align-items:center;'
        'justify-content:center;">3</div>'
        f'<div style="font-size:2.2cqw;font-weight:800;color:{INK};line-height:1.1;">指定競合との比較</div>'
        f'{meta}</div>'
        f'<div style="font-size:1.05cqw;color:{INK};font-weight:700;margin:.5cqw 0 .9cqw;">'
        '2〜5施設を横並びで比較し、自施設の立ち位置を把握します。</div>'
    )

    inner = (
        header
        + '<div style="flex:1;display:flex;gap:1.2cqw;min-height:0;">'
        f'{chart}{heatmap}</div>'
        + bottom
    )
    return _canvas(inner)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 3-detail「指定競合との比較（詳細）」
# ═══════════════════════════════════════════════════════════════════════════
def html_competitor_detail(b: dict) -> str:
    """SLIDE 3-detail: バブルスキャッタ（全施設）＋指定競合の傾向リスト。"""
    order = topic_score.TOPIC_ORDER
    target_name = b.get("target", "対象施設")
    target_scores = {t: v for t, v in zip(b.get("topic_names") or [], b.get("topic_values") or [])}
    peer_ts = b.get("peer_topic_scores") or {}
    FAC_COLORS = [ACCENT, "#2D7DD2", "#3BB273", "#E66000", "#8338EC", "#FF6B6B"]
    AXES = ["体験満足度", "推奨意向", "再訪意向"]

    def _get3(scores: dict) -> tuple:
        return scores.get(AXES[0], 50.0), scores.get(AXES[1], 50.0), scores.get(AXES[2], 50.0)

    all_fac = [(target_name, target_scores, ACCENT, True)] + [
        (nm, sc, FAC_COLORS[min(i + 1, len(FAC_COLORS) - 1)], False)
        for i, (nm, sc) in enumerate(peer_ts.items())
    ]
    all_x = [_get3(sc)[0] for _, sc, _, _ in all_fac]
    all_y = [_get3(sc)[1] for _, sc, _, _ in all_fac]
    xmn, xmx = min(all_x) - 8, max(all_x) + 8
    ymn, ymx = min(all_y) - 8, max(all_y) + 8
    xrng, yrng = (xmx - xmn) or 1, (ymx - ymn) or 1

    bubbles = ""
    for nm, sc, col, is_target in all_fac:
        bx, by, bz = _get3(sc)
        cx = (bx - xmn) / xrng * 80 + 10
        cy = (1 - (by - ymn) / yrng) * 80 + 10
        r = max(3, min(10, bz / 100 * 10 + 2))
        op = "0.85" if is_target else "0.45"
        bubbles += (
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{col}" fill-opacity="{op}" vector-effect="non-scaling-stroke" />'
            f'<text x="{cx:.1f}" y="{max(4, cy-r-1):.1f}" text-anchor="middle" '
            f'font-size="{"4.5" if is_target else "3.5"}" fill="{col}" font-weight="bold">{escape(_clip(nm, 8))}</text>'
        )

    gridlines = (
        f'<line x1="10" y1="50" x2="90" y2="50" stroke="{NEU}" stroke-width="0.5" stroke-dasharray="2 2" />'
        f'<line x1="50" y1="10" x2="50" y2="90" stroke="{NEU}" stroke-width="0.5" stroke-dasharray="2 2" />'
    )

    scatter = (
        f'<div style="flex:1;border:1px solid {CARD_LINE};border-radius:1.1cqw;padding:1.1cqw;min-height:0;">'
        f'<div style="font-size:1.05cqw;font-weight:700;color:{INK};margin-bottom:.6cqw;">'
        f'{escape(AXES[0])} × {escape(AXES[1])}　バブルサイズ={escape(AXES[2])}</div>'
        f'<svg viewBox="0 0 100 100" style="width:100%;height:calc(100% - 3cqw);">'
        f'{gridlines}{bubbles}'
        f'<text x="50" y="99" text-anchor="middle" font-size="3.5" fill="{SUB}">{escape(AXES[0])}</text>'
        f'<text x="2.5" y="50" text-anchor="middle" font-size="3.5" fill="{SUB}" transform="rotate(-90 2.5 50)">{escape(AXES[1])}</text>'
        '</svg></div>'
    )

    # ── 指定競合の傾向（各競合の強み/弱み上位3）────────────────── #
    trend_panels = ""
    for i, (pnm, psc) in enumerate(list(peer_ts.items())[:3]):
        col = FAC_COLORS[min(i + 1, len(FAC_COLORS) - 1)]
        diffs = sorted(
            [(t, psc.get(t, 50.0) - target_scores.get(t, 50.0)) for t in order if t in psc and t in target_scores],
            key=lambda x: -x[1],
        )
        top = diffs[:2]
        bot = diffs[-2:] if len(diffs) >= 2 else []
        rows = "".join(
            f'<div style="font-size:.8cqw;padding:.25cqw 0;border-bottom:1px solid {LINE};'
            'display:flex;justify-content:space-between;">'
            f'<span style="color:{INK};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:10cqw;">{escape(t)}</span>'
            f'<span style="color:{POS if d>0 else NEG};font-weight:700;white-space:nowrap;">{d:+.1f}</span></div>'
            for t, d in (top + [(t, d) for t, d in bot if (t, d) not in top])[:4]
        )
        trend_panels += (
            f'<div style="flex:1;min-width:0;border:1px solid {CARD_LINE};border-radius:.9cqw;'
            f'padding:.8cqw 1cqw;background:#FAFAF8;">'
            f'<div style="font-size:.9cqw;font-weight:800;color:{col};margin-bottom:.4cqw;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{escape(_clip(pnm, 10))}</div>'
            f'<div style="font-size:.75cqw;color:{SUB};margin-bottom:.3cqw;">vs 当施設</div>'
            f'{rows}</div>'
        )

    right = (
        f'<div style="width:36cqw;flex:none;display:flex;flex-direction:column;gap:1cqw;">'
        f'<div style="flex:none;font-size:1.05cqw;font-weight:700;color:{INK};">指定競合の傾向（vs 当施設）</div>'
        f'<div style="flex:none;display:flex;gap:.9cqw;">{trend_panels}</div>'
        '</div>'
    ) if peer_ts else ""

    inner = (
        _slide_header("3", "指定競合との比較（詳細）", "体験3軸の市場布置と競合別傾向分析")
        + f'<div style="flex:1;display:flex;gap:1.4cqw;min-height:0;">{scatter}{right}</div>'
    )
    return _canvas(inner)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 4「時間軸分析」
# ═══════════════════════════════════════════════════════════════════════════
def html_timeline(b: dict) -> str:
    """SLIDE 4: 月別ポジ/ネガ棒グラフ＋差分折れ線＋変化点カード。"""
    monthly = list(b.get("monthly_pos_neg") or [])
    target_name = b.get("target", "対象施設")

    if len(monthly) < 2:
        body = (
            f'<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            f'color:{SUB};font-size:1.3cqw;">月別評価データが不足しています（最低2ヶ月必要）</div>'
        )
    else:
        n = len(monthly)
        months = [r[0] for r in monthly]
        pos_counts = [r[1] for r in monthly]
        neg_counts = [r[2] for r in monthly]
        totals = [r[3] for r in monthly]
        pos_rates = [p / t * 100 if t else 0 for p, t in zip(pos_counts, totals)]
        neg_rates = [n / t * 100 if t else 0 for n, t in zip(neg_counts, totals)]
        max_rate = max(max(pos_rates), max(neg_rates), 1)

        BAR_W = 60  # SVGパーセント単位での棒幅
        bars = ""
        for i, (pr, nr) in enumerate(zip(pos_rates, neg_rates)):
            x_center = i / (n - 1) * 90 + 5 if n > 1 else 50
            bw = 90 / n * 0.6
            ph = pr / max_rate * 45
            nh = nr / max_rate * 45
            bars += (
                f'<rect x="{x_center - bw:.1f}" y="{50 - ph:.1f}" width="{bw:.1f}" height="{ph:.1f}" '
                f'fill="{POS}" fill-opacity="0.75" rx="0.5" />'
                f'<rect x="{x_center}" y="50" width="{bw:.1f}" height="{nh:.1f}" '
                f'fill="{NEG}" fill-opacity="0.75" rx="0.5" />'
            )

        # 差分折れ線（pos_rate - neg_rate）
        diffs = [p - n for p, n in zip(pos_rates, neg_rates)]
        max_abs = max(abs(d) for d in diffs) or 1
        diff_pts = " ".join(
            f"{(i/(n-1)*90+5 if n>1 else 50):.1f},{(50 - d/max_abs*40):.1f}"
            for i, d in enumerate(diffs)
        )

        step = max(1, (n - 1) // 5) if n > 1 else 1
        xlabs = "".join(
            f'<text x="{(i/(n-1)*90+5 if n>1 else 50):.1f}" y="98" text-anchor="middle" '
            f'font-size="3" fill="{SUB}">{escape(months[i])}</text>'
            for i in range(0, n, step)
        )

        chart = (
            f'<div style="flex:1;position:relative;min-height:0;border-bottom:1px solid {LINE};">'
            f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" style="width:100%;height:100%;overflow:visible;">'
            f'<line x1="0" y1="50" x2="100" y2="50" stroke="{LINE}" stroke-width="0.5" />'
            f'{bars}'
            f'<polyline points="{diff_pts}" fill="none" stroke="{ACCENT}" stroke-width="1.5" '
            'stroke-linejoin="round" vector-effect="non-scaling-stroke" />'
            + "".join(
                f'<circle cx="{(i/(n-1)*90+5 if n>1 else 50):.1f}" cy="{(50-d/max_abs*40):.1f}" '
                f'r="1.2" fill="{ACCENT}" vector-effect="non-scaling-stroke" />'
                for i, d in enumerate(diffs)
            )
            + f'{xlabs}'
            '</svg></div>'
        )

        legend = (
            f'<div style="flex:none;margin-top:.5cqw;font-size:.9cqw;color:{SUB};">'
            f'<span style="color:{POS};font-weight:700;">■</span> ポジティブ率　'
            f'<span style="color:{NEG};font-weight:700;">■</span> ネガティブ率　'
            f'<span style="color:{ACCENT};font-weight:700;">─</span> 差分（ポジ－ネガ）</div>'
        )

        # 変化点カード（差分の変動が大きかった月 TOP3）
        if len(diffs) >= 2:
            diff_changes = [(months[i], diffs[i] - diffs[i-1], pos_rates[i], neg_rates[i])
                            for i in range(1, n)]
            diff_changes.sort(key=lambda x: -abs(x[1]))
            top_changes = diff_changes[:3]
        else:
            top_changes = []

        change_cards = ""
        for ym, delta, pr, nr in top_changes:
            col = POS if delta > 0 else NEG
            sign = "▲" if delta > 0 else "▼"
            change_cards += (
                f'<div style="flex:1;border:1px solid {CARD_LINE};border-radius:1cqw;padding:.8cqw 1cqw;background:#FAFAF8;">'
                f'<div style="font-size:.85cqw;color:{SUB};margin-bottom:.3cqw;">{escape(ym)}</div>'
                f'<div style="font-size:1.5cqw;font-weight:800;color:{col};">{sign}{abs(delta):.0f}pt</div>'
                f'<div style="font-size:.75cqw;color:{SUB};margin-top:.2cqw;">ポジ {pr:.0f}% / ネガ {nr:.0f}%</div>'
                '</div>'
            )
        cards_row = (
            f'<div style="flex:none;display:flex;gap:.9cqw;margin-top:.9cqw;">{change_cards}</div>'
        ) if change_cards else ""

        body = (
            f'<div style="flex:1;display:flex;flex-direction:column;min-height:0;">'
            f'{chart}{legend}{cards_row}</div>'
        )

    inner = (
        _slide_header("4", "時間軸分析", "月別ポジティブ・ネガティブ評価の推移と変化点")
        + body
    )
    return _canvas(inner)


# ═══════════════════════════════════════════════════════════════════════════
# SLIDE 5「空間・体験分析」
# ═══════════════════════════════════════════════════════════════════════════
_RADAR_TOPICS = [
    "空間の機能性", "空間の質感", "空間の快適性", "空間の感情的インパクト",
    "美的完成度", "提供内容の品質", "スタッフ対応", "体験満足度",
    "推奨意向", "再訪意向",
]


def _radar_svg(datasets: list[tuple[str, dict, str]], topics: list[str]) -> str:
    """SVGレーダーチャート。datasets = [(label, {topic: score_0_100}, color)]"""
    import math
    n = len(topics)
    cx, cy, r = 50, 50, 38
    angle = [math.pi / 2 + 2 * math.pi * i / n for i in range(n)]

    # グリッド (3段)
    grid = ""
    for frac in (0.33, 0.67, 1.0):
        pts = " ".join(
            f"{cx + math.cos(a) * r * frac:.1f},{cy - math.sin(a) * r * frac:.1f}"
            for a in angle
        )
        grid += f'<polygon points="{pts}" fill="none" stroke="{LINE}" stroke-width="0.5" />'

    # 軸線
    axes = "".join(
        f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx + math.cos(a)*r:.1f}" y2="{cy - math.sin(a)*r:.1f}" '
        f'stroke="{LINE}" stroke-width="0.4" />'
        for a in angle
    )

    # ラベル
    labels = "".join(
        (lambda lx, ly, t:
         f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{"start" if lx > cx+2 else ("end" if lx < cx-2 else "middle")}" '
         f'dominant-baseline="{"hanging" if ly > cy+2 else ("auto" if ly < cy-2 else "middle")}" '
         f'font-size="3.5" fill="{SUB}">{escape(t[:6])}</text>'
         )(cx + math.cos(a) * (r + 8), cy - math.sin(a) * (r + 8), t)
        for a, t in zip(angle, topics)
    )

    # データ系列
    series_colors = [ACCENT, "#A7ABB0", NEU]
    series = ""
    legend = ""
    for (label, scores, col), sc_col in zip(datasets, series_colors):
        vals = [min(100, max(0, scores.get(t, 50.0))) for t in topics]
        pts = " ".join(
            f"{cx + math.cos(a) * r * v/100:.1f},{cy - math.sin(a) * r * v/100:.1f}"
            for a, v in zip(angle, vals)
        )
        series += (
            f'<polygon points="{pts}" fill="{sc_col}" fill-opacity="0.12" '
            f'stroke="{sc_col}" stroke-width="1.5" vector-effect="non-scaling-stroke" />'
        )
        legend += (
            f'<text x="2" y="{88 + datasets.index((label, scores, col)) * 5:.0f}" '
            f'font-size="3.5" fill="{sc_col}" font-weight="bold">— {escape(_clip(label, 8))}</text>'
        )

    return (
        '<svg viewBox="0 0 100 100" style="width:100%;height:100%;">'
        f'{grid}{axes}{labels}{series}{legend}'
        '</svg>'
    )


def html_space_experience(b: dict) -> str:
    """SLIDE 5「空間・体験分析」— レーダーチャート＋データ表＋4インサイトカード。"""
    target_name = b.get("target", "対象施設")
    target_scores = {t: v for t, v in zip(b.get("topic_names") or [], b.get("topic_values") or [])}
    peer_ts = b.get("peer_topic_scores") or {}
    overall_topic = b.get("overall_topic") or {}

    # 競合平均
    peer_avg: dict[str, float] = {}
    if peer_ts:
        for t in _RADAR_TOPICS:
            vals = [sc.get(t, 50.0) for sc in peer_ts.values() if t in sc]
            if vals:
                peer_avg[t] = sum(vals) / len(vals)

    datasets: list = [(target_name, target_scores, ACCENT)]
    if peer_avg:
        datasets.append(("競合平均", peer_avg, "#A7ABB0"))
    # 指定競合モードでは overall_topic ＝ 選択競合の平均なので「競合平均」と
    # 重なる。同じ線を2本描かない。
    if overall_topic and b.get("comparison_scope") != "competitor":
        datasets.append(("同業平均", overall_topic, NEU))

    radar = (
        f'<div style="flex:none;width:36cqw;aspect-ratio:1/1;">'
        + _radar_svg(datasets, _RADAR_TOPICS)
        + '</div>'
    )

    # データ表（全22観点）
    order = topic_score.TOPIC_ORDER
    table_rows = ""
    for t in order:
        tv = target_scores.get(t)
        ov = overall_topic.get(t)
        if tv is None:
            continue
        diff = (tv - ov) if ov is not None else None
        dcol = (POS if diff and diff >= 0 else NEG) if diff is not None else SUB
        diff_str = f"{diff:+.1f}" if diff is not None else "—"
        table_rows += (
            f'<div style="display:flex;align-items:center;border-bottom:1px solid {LINE};'
            f'padding:.3cqw 0;font-size:.85cqw;">'
            f'<div style="flex:2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:{INK};">'
            f'{escape(t)}</div>'
            f'<div style="flex:1;text-align:right;font-weight:700;color:{INK};">{_score_5pt(tv):.1f}</div>'
            f'<div style="flex:1;text-align:right;color:{SUB};">'
            f'{f"{_score_5pt(ov):.1f}" if ov is not None else "—"}</div>'
            f'<div style="flex:1;text-align:right;font-weight:700;color:{dcol};">{diff_str}</div></div>'
        )
    table_header = (
        f'<div style="display:flex;background:#F0EFE9;font-size:.78cqw;font-weight:700;color:{SUB};'
        f'padding:.35cqw 0;border-bottom:2px solid {LINE};">'
        '<div style="flex:2;overflow:hidden;">観点</div>'
        '<div style="flex:1;text-align:right;">当施設</div>'
        '<div style="flex:1;text-align:right;">平均</div>'
        '<div style="flex:1;text-align:right;">差分</div></div>'
    )
    table = (
        f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;border:1px solid {CARD_LINE};'
        f'border-radius:.9cqw;overflow:hidden;padding:.6cqw .9cqw;">'
        f'{table_header}'
        f'<div style="flex:1;overflow-y:auto;min-height:0;">{table_rows}</div>'
        '</div>'
    )

    # 4インサイトカード
    strengths = (b.get("strengths") or [])
    weaknesses = (b.get("weaknesses") or [])
    overall_score = b.get("overall_sentiment")
    rank = b.get("rank")
    total = b.get("total_fac", 0)

    radar_top = max(
        ((t, v) for t, v in target_scores.items() if t in _RADAR_TOPICS),
        key=lambda x: x[1], default=(None, None)
    )
    radar_bot = min(
        ((t, v) for t, v in target_scores.items() if t in _RADAR_TOPICS),
        key=lambda x: x[1], default=(None, None)
    )

    cards_data = [
        ("空間の強み", f"{radar_top[0] or '—'}\n{_score_5pt(radar_top[1]):.1f}pt" if radar_top[0] else "—", POS),
        ("空間の課題", f"{radar_bot[0] or '—'}\n{_score_5pt(radar_bot[1]):.1f}pt" if radar_bot[0] else "—", NEG),
        ("総合スコア", f"{overall_score}/100\n{rank}位/{total}施設" if (overall_score and rank) else "—", ACCENT),
        ("改善優先度", f"{weaknesses[0][0]}\n{weaknesses[0][3]:+.1f}pt" if weaknesses else "—", "#C79A2E"),
    ]

    insight_cards = "".join(
        f'<div style="flex:1;border:1px solid {CARD_LINE};border-radius:.9cqw;padding:.8cqw 1cqw;background:#FAFAF8;">'
        f'<div style="font-size:.85cqw;color:{SUB};font-weight:600;margin-bottom:.3cqw;">{escape(title)}</div>'
        + "".join(
            f'<div style="font-size:{"1.1" if i==0 else ".95"}cqw;font-weight:700;color:{col};'
            f'white-space:pre-line;line-height:1.35;">{escape(line)}</div>'
            for i, line in enumerate(val.split("\n"))
        )
        + '</div>'
        for title, val, col in cards_data
    )

    bottom = (
        f'<div style="flex:none;display:flex;gap:.9cqw;margin-top:1cqw;height:8cqw;">'
        f'{insight_cards}</div>'
    )

    right = (
        f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;min-height:0;">'
        f'{table}{bottom}</div>'
    )

    inner = (
        _slide_header("5", "空間・体験分析", "10観点レーダー＋22観点スコア一覧（5点満点換算）")
        + f'<div style="flex:1;display:flex;gap:1.4cqw;min-height:0;">{radar}{right}</div>'
    )
    return _canvas(inner)
