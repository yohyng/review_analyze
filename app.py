"""口コミ分析アプリ

    streamlit run app.py

Menu:
  ── 管理 ──────────────────────────
  📥 データ登録       CSV / Excel を DB に投入
  📋 取り込み状況     DB の中身一覧
  ── 分析 ──────────────────────────
  🔍 施設を選ぶ       検索 → 概要 → 分析開始  ← home
  📈 強み・弱み       スコア比較（3 軸）
  💬 テキスト & インサイト  TF-IDF / N-gram / LLM
  📑 レポート出力     PPTX ダウンロード
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src import (
    analysis,
    charts,
    config,
    db,
    llm,
    report,
    review_csv,
    score_excel,
    scoring,
    search,
    text_analysis,
    topics,
)

st.set_page_config(page_title="口コミ分析", page_icon="📊", layout="wide")


@st.cache_resource
def _conn():
    conn = db.get_conn()
    db.init_db(conn)
    return conn


conn = _conn()

# ── sidebar ──────────────────────────────────────────────────────────────── #
st.sidebar.title("📊 口コミ分析")
st.sidebar.markdown("**── 管理 ──**")
page = st.sidebar.radio(
    "メニュー",
    [
        "📥 データ登録",
        "📋 取り込み状況",
        "─────────",
        "🔍 施設を選ぶ",
        "📈 強み・弱み",
        "💬 テキスト & インサイト",
        "📑 レポート出力",
    ],
    label_visibility="collapsed",
)
st.sidebar.divider()
st.sidebar.caption(f"v{config.APP_VERSION}")


# ── helpers ──────────────────────────────────────────────────────────────── #
def _facility_selector(key: str) -> str | None:
    """Selectbox pre-populated from session_state['selected_facility']."""
    names = analysis.facility_names(conn)
    if not names:
        return None
    default_name = st.session_state.get("selected_facility", names[0])
    default_idx = names.index(default_name) if default_name in names else 0
    return st.selectbox("対象施設", names, index=default_idx, key=key)


# separator acts as a disabled divider — skip it
if page == "─────────":
    st.stop()


# ============================================================================
# 📥 データ登録  (旧 ①②)
# ============================================================================
if page == "📥 データ登録":
    st.header("📥 データ登録")
    tab_csv, tab_excel = st.tabs(["口コミ CSV", "スコア Excel"])

    # ── CSV tab ─────────────────────────────────────────────────────────── #
    with tab_csv:
        st.caption("KAIZODE などからDLした口コミCSV/TSVを投げ込みます（施設名は手入力）。")

        uploaded = st.file_uploader(
            "口コミ CSV / TSV", type=["csv", "tsv", "txt"], key="csv_upload"
        )

        # ── Facility inference from CSV ──────────────────────────────────── #
        facility_key_for_parse = None
        if uploaded:
            try:
                inferred = review_csv.infer_facilities(uploaded)
                uploaded.seek(0)
            except Exception:
                inferred = []

            if len(inferred) > 1:
                st.info(f"このCSVには **{len(inferred)} 施設** のデータが含まれています。")
                fac_opts = []
                for _f in inferred:
                    _r = f" / ★{_f['avg_rating']}" if _f["avg_rating"] else ""
                    fac_opts.append(f"{_f['name']} ({_f['count']}件{_r})")
                picked = st.selectbox(
                    "取り込む施設を選択", range(len(inferred)),
                    format_func=lambda i: fac_opts[i], key="fac_pick",
                )
                chosen_fac = inferred[picked]
                facility_key_for_parse = chosen_fac["key"]
                if chosen_fac["name"] and st.button(
                    f"施設名に「{chosen_fac['name']}」を使う", key="autofill_multi"
                ):
                    st.session_state["csv_fac_confirm"] = chosen_fac["name"]
                    st.rerun()
            elif len(inferred) == 1:
                _f = inferred[0]
                _r = f" / 平均 ★{_f['avg_rating']}" if _f["avg_rating"] else ""
                st.info(f"📍 推定施設: **{_f['name']}** — {_f['count']}件{_r}")
                if _f["name"] and not st.session_state.get("csv_fac_confirm"):
                    if st.button(f"施設名に「{_f['name']}」を使う", key="autofill_single"):
                        st.session_state["csv_fac_confirm"] = _f["name"]
                        st.rerun()

        col1, col2 = st.columns(2)
        with col1:
            facility_name_input = st.text_input(
                "施設名（手入力・必須）", placeholder="例: 風の海",
                key="csv_fac_input",
            )
        with col2:
            ftype_label = st.radio(
                "種別", list(config.FACILITY_TYPES.values()), horizontal=True
            )
        ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)

        # fuzzy suggestion
        if facility_name_input.strip():
            existing = analysis.facility_names(conn)
            hints = search.suggest(facility_name_input.strip(), existing)
            if hints:
                st.info("DBにこんな施設が見つかりました")
                cols = st.columns(len(hints))
                for col, h in zip(cols, hints):
                    with col:
                        if st.button(f"✅ {h}", key=f"hint_{h}"):
                            st.session_state["csv_fac_confirm"] = h

        facility_name = st.session_state.get(
            "csv_fac_confirm", facility_name_input
        ).strip()

        if facility_name and facility_name != facility_name_input.strip():
            st.success(f"施設名: **{facility_name}** を使用します")

        if uploaded and facility_name:
            try:
                result = review_csv.parse_reviews(uploaded, facility_key=facility_key_for_parse)
            except Exception as e:
                st.error(f"パースに失敗しました: {e}")
                st.stop()

            st.success(
                f"解析: {len(result.reviews)} 件の口コミ "
                f"（生 {result.n_raw} 行 / スキップ {result.n_skipped} 行）"
            )
            m1, m2, m3 = st.columns(3)
            m1.metric("総合評点", result.general_rating or "-")
            m2.metric("口コミ総数(施設)", result.total_reviews or "-")
            m3.metric("カテゴリ", result.category or "-")

            preview = pd.DataFrame([
                {
                    "★": r.rating,
                    "日付": r.review_date[:10] if len(r.review_date) >= 10 else r.review_date,
                    "本文": (r.text[:60] + "…") if len(r.text) > 60 else r.text,
                    "サブスコア": ", ".join(f"{a}:{int(v)}" for a, v in r.subscores) or "-",
                }
                for r in result.reviews[:20]
            ])
            st.dataframe(preview, use_container_width=True, hide_index=True)

            if st.button("💾 DBに保存", type="primary", key="csv_save"):
                fid = db.upsert_facility(
                    conn, facility_name, ftype=ftype,
                    category=result.category,
                    general_rating=result.general_rating,
                    total_reviews=result.total_reviews,
                )
                inserted, skipped = db.insert_reviews(conn, fid, result.reviews)
                n_axes = scoring.compute_and_store(conn, fid)
                st.success(
                    f"✅ 「{facility_name}」に {inserted} 件保存"
                    f"（重複スキップ {skipped} 件）"
                    + (f" / 定量スコア {n_axes} 軸を自動算出しました" if n_axes else "")
                )
                st.session_state.pop("csv_fac_confirm", None)
        elif uploaded and not facility_name:
            st.warning("先に施設名を入力してください。")

    # ── Excel tab ───────────────────────────────────────────────────────── #
    with tab_excel:
        st.caption("既存の定量化指標 Excel を投げ込み → 列を確認して保存（どんな列でもOK）。")
        uploaded_xl = st.file_uploader(
            "スコア Excel / CSV", type=["xlsx", "xls", "csv"], key="xl_upload"
        )
        if uploaded_xl:
            try:
                df = score_excel.read_table(uploaded_xl, filename=uploaded_xl.name)
            except Exception as e:
                st.error(f"読み込みに失敗しました: {e}")
                st.stop()

            st.subheader("プレビュー")
            st.dataframe(df.head(20), use_container_width=True)

            guess = score_excel.guess_columns(df)
            if guess.layout == "long":
                st.info("縦持ち（施設・指標・値）の形式と判定しました。")

            cols = list(df.columns)
            name_col = st.selectbox(
                "施設名の列", cols,
                index=cols.index(guess.name_col) if guess.name_col in cols else 0,
            )
            if guess.layout == "long":
                axis_col = st.selectbox(
                    "指標名の列", cols,
                    index=cols.index(guess.long_axis_col) if guess.long_axis_col in cols else 0,
                )
                value_col = st.selectbox(
                    "値の列", cols,
                    index=cols.index(guess.long_value_col) if guess.long_value_col in cols else 0,
                )
                scores = score_excel.extract_scores_long(df, name_col, axis_col, value_col)
            else:
                axis_cols = st.multiselect(
                    "スコア指標の列",
                    [c for c in cols if c != name_col],
                    default=[c for c in guess.numeric_cols if c != name_col],
                )
                scores = score_excel.extract_scores_wide(df, name_col, axis_cols)

            scale = st.number_input(
                "スケール", min_value=1.0,
                value=float(guess.suggested_scale or 5.0), step=1.0,
            )

            if scores:
                st.subheader("保存される内容")
                st.dataframe(
                    pd.DataFrame(scores).T.rename_axis("施設名").reset_index(),
                    use_container_width=True, hide_index=True,
                )
                st.caption("※ 施設名は口コミCSVで手入力した名前と完全一致で紐付きます。")
                if st.button("💾 スコアをDBに保存", type="primary", key="xl_save"):
                    total = 0
                    for fname, axes in scores.items():
                        fid = db.upsert_facility(conn, fname)
                        total += db.upsert_scores(conn, fid, axes, scale=scale)
                    st.success(f"✅ {len(scores)} 施設 / {total} 指標を保存しました。")
            else:
                st.warning("数値の指標列が見つかりません。列マッピングを確認してください。")


# ============================================================================
# 📋 取り込み状況
# ============================================================================
elif page == "📋 取り込み状況":
    st.header("📋 取り込み状況")
    overview = db.facility_overview(conn)
    if not overview:
        st.info("まだデータがありません。📥 データ登録から始めてください。")
    else:
        st.dataframe(
            pd.DataFrame(overview).drop(columns=["id"]),
            use_container_width=True, hide_index=True,
        )
        st.caption(f"DB: {config.DB_PATH}")


# ============================================================================
# 🔍 施設を選ぶ  (home / launcher)
# ============================================================================
elif page == "🔍 施設を選ぶ":
    st.header("🔍 施設を選ぶ")

    all_names = analysis.facility_names(conn)
    if not all_names:
        st.info("まだ施設データがありません。📥 データ登録から口コミCSVを投入してください。")
        st.stop()

    # ── Search box with fuzzy suggestion ───────────────────────────────── #
    query = st.text_input(
        "施設名を検索", placeholder="例: 風の海",
        value=st.session_state.get("selected_facility", ""),
    )

    if query.strip():
        hints = search.suggest(query.strip(), all_names)
        exact = query.strip() in all_names

        if not exact and hints:
            st.caption("もしかして…")
            cols = st.columns(min(len(hints), 4))
            for col, h in zip(cols, hints):
                with col:
                    if st.button(f"✅ {h}", key=f"sel_{h}"):
                        st.session_state["selected_facility"] = h
                        st.rerun()

        if exact:
            st.session_state["selected_facility"] = query.strip()
        elif not hints:
            st.warning("一致する施設が見つかりません。📥 データ登録で登録してください。")

    selected = st.session_state.get("selected_facility")
    if selected and selected in all_names:
        # ── Data overview card ──────────────────────────────────────────── #
        stats = db.facility_stats(conn, selected)
        if stats:
            st.divider()
            st.subheader(f"📋 {selected}")

            c1, c2, c3, c4 = st.columns(4)
            _n_text = stats.get("n_text_reviews", stats["n_reviews"])
            _n_delta = stats["n_reviews"] - _n_text
            _count_label = (
                f"{stats['n_reviews']} 件（本文あり {_n_text} 件）"
                if _n_delta > 0 else f"{stats['n_reviews']} 件"
            )
            c1.metric("口コミ件数", _count_label)
            c2.metric(
                "期間",
                f"{stats['date_oldest']} 〜 {stats['date_newest']}"
                if stats["n_reviews"] else "-"
            )
            c3.metric(
                "平均評点",
                f"⭐ {stats['avg_rating']}" if stats["avg_rating"] else "-"
            )
            c4.metric(
                "スコア指標",
                f"{len(stats['score_axes'])} 軸" if stats["score_axes"] else "未登録"
            )

            if stats["score_axes"]:
                st.caption("スコア指標: " + " / ".join(stats["score_axes"]))

            # readiness badges
            badges = []
            if stats["can_analyze"]:
                badges.append("✅ 口コミデータあり")
            else:
                badges.append("⚠️ 口コミなし")
            if stats["can_tfidf"]:
                badges.append(f"✅ テキスト分析可（本文あり {_n_text} 件）")
            else:
                badges.append(f"⚠️ テキスト分析には本文付き口コミ3件以上必要（現在 {_n_text} 件）")
            if stats["can_score"]:
                badges.append("✅ スコア比較可")
            else:
                badges.append("⚠️ スコアなし（Excel登録で有効化）")
            st.markdown("  |  ".join(badges))

            st.divider()

            # ── Launch button ──────────────────────────────────────────── #
            if not stats["can_analyze"]:
                st.warning("口コミデータがありません。📥 データ登録から口コミCSVを投入してください。")
            else:
                if st.button(
                    f"🚀 「{selected}」を分析する",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state["analysis_target"] = selected
                    st.session_state["show_analysis"] = True
                    st.rerun()

    # ── Inline analysis results ─────────────────────────────────────────── #
    if st.session_state.get("show_analysis") and st.session_state.get("analysis_target"):
        target = st.session_state["analysis_target"]
        st.divider()
        st.subheader(f"📊 分析結果 — {target}")

        tab_score, tab_topic, tab_text, tab_report = st.tabs(
            ["📈 強み・弱み", "🗂️ トピック分析", "💬 テキスト & インサイト", "📑 レポート出力"]
        )

        # ── Score tab ─────────────────────────────────────────────────── #
        with tab_score:
            mat = analysis.score_matrix(conn)
            if mat.empty:
                mat = analysis.google_matrix(conn)

            if mat.empty or target not in mat.index:
                st.info("スコアデータがありません。📥 データ登録でExcelを登録してください。")
            else:
                comp = analysis.build_comparison(conn, target, "comparison_avg")
                if comp is None:
                    comp = analysis.build_comparison(conn, target, "all_avg")

                if comp is None:
                    st.info("比較できる施設が不足しています。")
                else:
                    col_l, col_r = st.columns(2)
                    with col_l:
                        st.plotly_chart(
                            charts.radar(comp.target, comp.baseline,
                                         comp.target_label, comp.baseline_label),
                            use_container_width=True, key="home_radar",
                        )
                    with col_r:
                        st.plotly_chart(
                            charts.diff_bar(comp.diff, comp.target_label, comp.baseline_label),
                            use_container_width=True, key="home_bar",
                        )
                    s, w = analysis.top_n(comp.diff)
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**💪 強み TOP5**")
                        st.dataframe(s, use_container_width=True, hide_index=True)
                    with c2:
                        st.markdown("**⚠️ 弱み TOP5**")
                        st.dataframe(w, use_container_width=True, hide_index=True)

        # ── Topic tab ─────────────────────────────────────────────────── #
        with tab_topic:
            _fid_row = conn.execute(
                "SELECT id FROM facility WHERE name = ?", (target,)
            ).fetchone()
            if not _fid_row:
                st.info("施設データが見つかりません。")
            else:
                _rev_rows = conn.execute(
                    "SELECT rating, text FROM review WHERE facility_id = ?",
                    (_fid_row["id"],),
                ).fetchall()
                _revs = [(_r["rating"], _r["text"] or "") for _r in _rev_rows]
                _n_text = sum(1 for _, t in _revs if t and t.strip())
                if _n_text < 2:
                    _n_total = len(_revs)
                    if _n_total > _n_text:
                        st.info(
                            f"テキスト付き口コミが {_n_text} 件です"
                            f"（全 {_n_total} 件のうち {_n_total - _n_text} 件は評価のみ）。"
                            f"トピック分析には本文が2件以上必要です。"
                        )
                    else:
                        st.info("トピック分析には口コミの本文が2件以上必要です。")
                else:
                    _n = st.slider("トピック数", 2, 10, 5, key=f"topic_n_{target}")
                    with st.spinner("トピック分析中…（TF-IDF + KMeans / 仮 BERTopic）"):
                        _topic_list = topics.extract_topics(_revs, n_topics=_n)
                    if not _topic_list:
                        st.info("トピックを抽出できませんでした。")
                    else:
                        st.caption("⚠️ 現在は TF-IDF + KMeans による仮実装です（BERTopic に差し替え予定）")
                        for _t in _topic_list:
                            with st.expander(
                                f"**{_t.label}** — {_t.count}件 ({_t.share}%)",
                                expanded=True,
                            ):
                                st.markdown("**キーワード**: " + "　/　".join(_t.keywords))
                                for _i, _s in enumerate(_t.samples, 1):
                                    st.text_area(
                                        f"代表口コミ {_i}", _s, height=80,
                                        key=f"topic_{target}_{_t.id}_{_i}",
                                        disabled=True,
                                    )

        # ── Text tab ──────────────────────────────────────────────────── #
        with tab_text:
            with st.spinner("テキスト分析中…"):
                profile = text_analysis.build_profile(conn, target)

            if profile.empty:
                st.info("テキストデータが不足しています（3件以上の口コミが必要）。")
            else:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**TF-IDF キーワード TOP20**")
                    if not profile.tfidf_keywords.empty:
                        fig = px.bar(
                            profile.tfidf_keywords.head(20),
                            x="スコア", y="単語", orientation="h",
                            color="スコア", color_continuous_scale="Blues", height=450,
                        )
                        fig.update_layout(yaxis=dict(autorange="reversed"),
                                          coloraxis_showscale=False,
                                          margin=dict(t=10, b=10))
                        st.plotly_chart(fig, use_container_width=True, key="home_kw")
                with col2:
                    st.markdown("**頻出フレーズ（バイグラム）**")
                    if not profile.bigrams.empty:
                        fig2 = px.bar(
                            profile.bigrams.head(20),
                            x="件数", y="フレーズ", orientation="h",
                            color="件数", color_continuous_scale="Greens", height=450,
                        )
                        fig2.update_layout(yaxis=dict(autorange="reversed"),
                                           coloraxis_showscale=False,
                                           margin=dict(t=10, b=10))
                        st.plotly_chart(fig2, use_container_width=True, key="home_bi")
                    else:
                        st.info("フレーズ抽出には口コミ件数がもう少し必要です。")

                st.divider()
                st.markdown("**⑧ LLMインサイト**")
                api_key = llm.get_api_key()
                if not api_key:
                    api_key = st.text_input(
                        "Gemini API キー（セッション限り）",
                        type="password", key="home_api",
                        help="aistudio.google.com で無料取得できます",
                    )
                if st.button("✨ インサイトを生成", type="primary",
                             disabled=not api_key, key="home_llm"):
                    kw = profile.tfidf_keywords["単語"].tolist()
                    bi = profile.bigrams["フレーズ"].tolist() if not profile.bigrams.empty else []
                    comp2 = analysis.build_comparison(conn, target, "comparison_avg") or \
                            analysis.build_comparison(conn, target, "all_avg")
                    diff = comp2.diff if comp2 else None
                    prompt = llm.build_prompt(target, diff, kw, bi,
                                              profile.high_rated, profile.low_rated)
                    with st.spinner("Gemini が分析中…"):
                        result = llm.generate_insights(prompt, api_key)
                    if result.error:
                        st.error(result.error)
                    else:
                        st.session_state["insights"] = result
                        st.session_state["insights_facility"] = target
                        st.markdown(f"### まとめ\n{result.summary}")
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**💪 強み**")
                            for item in result.strengths:
                                st.markdown(f"- {item}")
                        with c2:
                            st.markdown("**⚠️ 弱み**")
                            for item in result.weaknesses:
                                st.markdown(f"- {item}")
                        st.markdown("**💡 示唆**")
                        for item in result.implications:
                            st.markdown(f"- {item}")
                        st.markdown("**🔧 改善提案**")
                        for item in result.improvements:
                            st.markdown(f"- {item}")

        # ── Report tab ────────────────────────────────────────────────── #
        with tab_report:
            insights = None
            if st.session_state.get("insights_facility") == target:
                insights = st.session_state.get("insights")
                st.success("生成済みのインサイトをレポートに含めます。")
            else:
                st.info("インサイトを生成してからレポートを出力するとより充実した内容になります。")

            if st.button("📑 レポート(PPTX)を生成", type="primary", key="home_pptx"):
                with st.spinner("スライドを生成中…"):
                    tmp = Path(tempfile.mkdtemp()) / f"{target}_分析レポート.pptx"
                    report.build_report(conn, target, insights=insights, output_path=tmp)
                with open(tmp, "rb") as f:
                    st.download_button(
                        "⬇️ ダウンロード", data=f.read(),
                        file_name=tmp.name,
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        type="primary", key="home_dl",
                    )


# ============================================================================
# 📈 強み・弱み分析
# ============================================================================
elif page == "📈 強み・弱み":
    st.header("📈 強み・弱み分析")

    mat = analysis.score_matrix(conn)
    if mat.empty:
        mat = analysis.google_matrix(conn)

    if mat.empty:
        st.info("スコアデータがありません。📥 データ登録でExcelを登録してください。")
        st.stop()

    all_names = list(mat.index)
    target_name = st.selectbox(
        "対象施設", all_names,
        index=all_names.index(st.session_state["analysis_target"])
        if st.session_state.get("analysis_target") in all_names else 0,
    )

    with st.expander("全施設スコア一覧（ヒートマップ）", expanded=False):
        st.plotly_chart(charts.score_heatmap(mat), use_container_width=True)

    st.divider()
    tab_a, tab_b, tab_c = st.tabs(
        ["A　比較施設の平均", "B　全体（DB内）の平均", "C　特定施設1つ"]
    )

    def _render(result: analysis.ComparisonResult | None, key: str) -> None:
        if result is None:
            st.warning("比較できるデータが不足しています。")
            return
        strengths, weaknesses = analysis.top_n(result.diff, n=5)
        col_l, col_r = st.columns(2)
        with col_l:
            st.subheader("レーダーチャート")
            st.plotly_chart(
                charts.radar(result.target, result.baseline,
                             result.target_label, result.baseline_label),
                use_container_width=True, key=f"radar_{key}",
            )
        with col_r:
            st.subheader("差分バーチャート")
            st.plotly_chart(
                charts.diff_bar(result.diff, result.target_label, result.baseline_label),
                use_container_width=True, key=f"bar_{key}",
            )
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**💪 強み TOP5**")
            st.dataframe(strengths, use_container_width=True, hide_index=True) if not strengths.empty else st.caption("なし")
        with c2:
            st.markdown("**⚠️ 弱み TOP5**")
            st.dataframe(weaknesses, use_container_width=True, hide_index=True) if not weaknesses.empty else st.caption("なし")
        with st.expander("数値詳細", expanded=False):
            detail = pd.DataFrame({"対象": result.target.round(1),
                                   "比較基準": result.baseline.round(1),
                                   "差": result.diff.round(1)})
            detail.index.name = "指標"
            st.dataframe(detail, use_container_width=True)

    with tab_a:
        st.caption("対象施設 vs 比較施設（「比較施設」として登録した施設）の平均")
        _render(analysis.build_comparison(conn, target_name, "comparison_avg"), "a")
    with tab_b:
        st.caption("対象施設 vs DB内の全施設平均（対象除く）")
        _render(analysis.build_comparison(conn, target_name, "all_avg"), "b")
    with tab_c:
        st.caption("対象施設 vs 特定の1施設")
        others = [n for n in all_names if n != target_name]
        if not others:
            st.warning("比較できる他の施設がありません。")
        else:
            specific = st.selectbox("比較する施設", others, key="spec")
            _render(analysis.build_comparison(conn, target_name, "specific",
                                               specific_name=specific), "c")


# ============================================================================
# 💬 テキスト分析 & インサイト
# ============================================================================
elif page == "💬 テキスト & インサイト":
    st.header("💬 テキスト分析 & インサイト")

    all_names = analysis.facility_names(conn)
    if not all_names:
        st.info("施設データがありません。")
        st.stop()

    target_name = st.selectbox(
        "対象施設", all_names,
        index=all_names.index(st.session_state["analysis_target"])
        if st.session_state.get("analysis_target") in all_names else 0,
        key="text_fac",
    )

    st.subheader("⑦ テキスト分析")
    with st.spinner("形態素解析 + TF-IDF 実行中…"):
        profile = text_analysis.build_profile(conn, target_name, top_n=20)

    if profile.empty:
        st.warning("口コミテキストがありません。")
    else:
        st.caption(f"分析対象: {profile.n_reviews} 件")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**TF-IDF キーワード TOP20**")
            if not profile.tfidf_keywords.empty:
                fig = px.bar(profile.tfidf_keywords.head(20), x="スコア", y="単語",
                             orientation="h", color="スコア",
                             color_continuous_scale="Blues", height=500)
                fig.update_layout(yaxis=dict(autorange="reversed"),
                                  coloraxis_showscale=False, margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)
        with col2:
            st.markdown("**頻出フレーズ（バイグラム）**")
            if not profile.bigrams.empty:
                fig2 = px.bar(profile.bigrams.head(20), x="件数", y="フレーズ",
                              orientation="h", color="件数",
                              color_continuous_scale="Greens", height=500)
                fig2.update_layout(yaxis=dict(autorange="reversed"),
                                   coloraxis_showscale=False, margin=dict(t=10, b=10))
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("フレーズ抽出には口コミ件数がもう少し必要です。")

        with st.expander("トライグラム TOP20", expanded=False):
            st.dataframe(profile.trigrams, use_container_width=True, hide_index=True) if not profile.trigrams.empty else st.info("なし")

        with st.expander("代表口コミ", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**高評価 TOP3**")
                for i, r in enumerate(profile.high_rated, 1):
                    st.text_area(f"{i}", r, height=120, key=f"hi_{i}", disabled=True)
            with c2:
                st.markdown("**低評価 TOP3**")
                if not profile.low_rated:
                    st.caption("低評価（3★以下）なし")
                for i, r in enumerate(profile.low_rated, 1):
                    st.text_area(f"{i}", r, height=120, key=f"lo_{i}", disabled=True)

    st.divider()
    st.subheader("⑧ LLMインサイト")

    comp_res = analysis.build_comparison(conn, target_name, "comparison_avg") or \
               analysis.build_comparison(conn, target_name, "all_avg")
    if comp_res:
        st.caption(f"スコア比較軸: {comp_res.baseline_label}")

    api_key = llm.get_api_key()
    if not api_key:
        st.info(
            "Gemini API キー未設定。\n\n"
            "取得: https://aistudio.google.com/ → 「Get API key」（Googleアカウントで無料）\n\n"
            "設定: 環境変数 `GEMINI_API_KEY` / `.streamlit/secrets.toml` / 下の入力欄"
        )
        api_key = st.text_input("Gemini API キー（セッション限り）", type="password")

    if not profile.empty:
        if st.button("✨ インサイトを生成する", type="primary", disabled=not api_key):
            kw = profile.tfidf_keywords["単語"].tolist()
            bi = profile.bigrams["フレーズ"].tolist() if not profile.bigrams.empty else []
            prompt = llm.build_prompt(
                target_name, comp_res.diff if comp_res else None,
                kw, bi, profile.high_rated, profile.low_rated,
            )
            with st.spinner("Gemini が分析中…"):
                result = llm.generate_insights(prompt, api_key)

            if result.error:
                st.error(result.error)
            else:
                st.session_state["insights"] = result
                st.session_state["insights_facility"] = target_name
                st.success("インサイト生成完了")
                st.markdown(f"### まとめ\n{result.summary}")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**💪 強み**")
                    for item in result.strengths:
                        st.markdown(f"- {item}")
                with c2:
                    st.markdown("**⚠️ 弱み**")
                    for item in result.weaknesses:
                        st.markdown(f"- {item}")
                st.markdown("**💡 示唆**")
                for item in result.implications:
                    st.markdown(f"- {item}")
                st.markdown("**🔧 改善提案**")
                for item in result.improvements:
                    st.markdown(f"- {item}")
                with st.expander("プロンプト（確認用）", expanded=False):
                    st.text(prompt)


# ============================================================================
# 📑 レポート出力
# ============================================================================
else:
    st.header("📑 レポート出力 (PPTX)")
    st.caption("分析結果を1つのPowerPointにまとめます。")

    all_names = analysis.facility_names(conn)
    if not all_names:
        st.info("施設データがありません。")
        st.stop()

    col1, col2 = st.columns(2)
    with col1:
        target_name = st.selectbox(
            "対象施設", all_names,
            index=all_names.index(st.session_state["analysis_target"])
            if st.session_state.get("analysis_target") in all_names else 0,
            key="rep_fac",
        )
    with col2:
        axis_label = st.radio("比較基準", ["比較施設の平均", "全体（DB内）の平均"], horizontal=True)
    axis = "comparison_avg" if axis_label == "比較施設の平均" else "all_avg"

    insights = None
    if st.session_state.get("insights_facility") == target_name:
        insights = st.session_state.get("insights")
        st.success("生成済みインサイトをレポートに含めます。")
    else:
        st.info("💬 テキスト & インサイト でインサイトを生成するとレポートに反映されます。")

    if st.button("📑 レポート(PPTX)を生成", type="primary"):
        with st.spinner("スライドを生成中…"):
            tmp = Path(tempfile.mkdtemp()) / f"{target_name}_分析レポート.pptx"
            report.build_report(conn, target_name, axis=axis,
                                 insights=insights, output_path=tmp)
        with open(tmp, "rb") as f:
            st.download_button(
                "⬇️ ダウンロード", data=f.read(),
                file_name=tmp.name,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                type="primary",
            )
        st.success("生成完了。上のボタンからダウンロードしてください。")
