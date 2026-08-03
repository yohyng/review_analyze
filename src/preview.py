"""分析レポートに渡すデータの組み立て（bundle）。

build_bundle() が DB とスコア行列から、スライド描画に必要な値を一括で作る:
KPI・比較母数と順位・各観点のスコアと基準値・体験評価マッピング・月次推移と
変化点・代表口コミ・課題と打ち手。

描画そのものは src/slides.py が担当する（デザインの正は
docs/design/slide_p03..p12.png ＝ 20260726_VoiceBAUM_v1.pdf の p3〜p12）。
LLM を使う部分（変化点の要因・代表口コミ・企画仮説）は引数で受け取り、
渡されなければ決定論的なフォールバックを使う。
"""
from __future__ import annotations

import base64
import sqlite3
from datetime import date
from typing import Optional

from . import (analysis, config, db, discussion, text_analysis, timeline,
               topic_score, voices)

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
# 旧スライド描画（html_overview / html_slide01 / html_market_position ほか）は
# 2026-08 の刷新で src/slides.py に置き換えたため削除した。デザインの正は
# docs/design/slide_p03..p12.png（20260726_VoiceBAUM_v1.pdf）で、描画は
# slides.slide0_disclaimer / slide1_facility_info / … / slide7_discussion。
# このモジュールは build_bundle（スライドに渡すデータの組み立て）に専念する。
# ═══════════════════════════════════════════════════════════════════════════
