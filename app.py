"""口コミ分析アプリ

    streamlit run app.py

Screens:
  1. 口コミCSV取り込み      (step 1-3)
  2. スコアExcel取り込み    (step 4)
  3. 取り込み状況
  4. 強み・弱み分析         (step 5-6)
  5. テキスト分析 & インサイト (step 7-8)  ← NEW
Step 9 (パワポ) comes next.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
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
    text_analysis,
)

st.set_page_config(page_title="口コミ分析", page_icon="📊", layout="wide")


@st.cache_resource
def _conn():
    conn = db.get_conn()
    db.init_db(conn)
    return conn


conn = _conn()

st.sidebar.title("📊 口コミ分析")
page = st.sidebar.radio(
    "メニュー",
    [
        "① 口コミCSV取り込み",
        "② スコアExcel取り込み",
        "③ 取り込み状況",
        "④ 強み・弱み分析",
        "⑤ テキスト分析 & インサイト",
        "⑥ レポート出力 (PPTX)",
    ],
)


# --------------------------------------------------------------------------- #
# 1) review CSV
# --------------------------------------------------------------------------- #
if page.startswith("①"):
    st.header("① 口コミCSV取り込み")
    st.caption("KAIZODE などからDLした口コミCSV/TSVを投げ込みます（施設名は手入力）。")

    col1, col2 = st.columns(2)
    with col1:
        facility_name = st.text_input("施設名（手入力・必須）", placeholder="例: 風の海")
    with col2:
        ftype_label = st.radio("種別", list(config.FACILITY_TYPES.values()), horizontal=True)
    ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)

    uploaded = st.file_uploader("口コミCSV / TSV", type=["csv", "tsv", "txt"])

    if uploaded and facility_name.strip():
        try:
            result = review_csv.parse_reviews(uploaded)
        except Exception as e:  # noqa: BLE001
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

        preview = pd.DataFrame(
            [
                {
                    "★": r.rating,
                    "日付": r.review_date[:10] if len(r.review_date) >= 10 else r.review_date,
                    "本文": (r.text[:60] + "…") if len(r.text) > 60 else r.text,
                    "サブスコア": ", ".join(f"{a}:{int(v)}" for a, v in r.subscores) or "-",
                }
                for r in result.reviews[:20]
            ]
        )
        st.dataframe(preview, use_container_width=True, hide_index=True)

        if st.button("💾 この内容でDBに保存", type="primary"):
            fid = db.upsert_facility(
                conn,
                facility_name,
                ftype=ftype,
                category=result.category,
                general_rating=result.general_rating,
                total_reviews=result.total_reviews,
            )
            inserted, skipped = db.insert_reviews(conn, fid, result.reviews)
            st.success(
                f"✅ 「{facility_name}」に {inserted} 件保存"
                f"（重複スキップ {skipped} 件）"
            )
    elif uploaded and not facility_name.strip():
        st.warning("先に施設名を入力してください。")


# --------------------------------------------------------------------------- #
# 2) score Excel
# --------------------------------------------------------------------------- #
elif page.startswith("②"):
    st.header("② スコアExcel取り込み")
    st.caption("既存の定量化指標Excelを投げ込み → 列を確認して保存（どんな列でもOK）。")

    uploaded = st.file_uploader("スコア Excel / CSV", type=["xlsx", "xls", "csv"])

    if uploaded:
        try:
            df = score_excel.read_table(uploaded, filename=uploaded.name)
        except Exception as e:  # noqa: BLE001
            st.error(f"読み込みに失敗しました: {e}")
            st.stop()

        st.subheader("プレビュー")
        st.dataframe(df.head(20), use_container_width=True)

        guess = score_excel.guess_columns(df)
        st.subheader("列マッピング")
        if guess.layout == "long":
            st.info("縦持ち（施設・指標・値）の形式と判定しました。")

        cols = list(df.columns)
        name_col = st.selectbox(
            "施設名の列",
            cols,
            index=cols.index(guess.name_col) if guess.name_col in cols else 0,
        )

        if guess.layout == "long":
            axis_col = st.selectbox(
                "指標名の列",
                cols,
                index=cols.index(guess.long_axis_col) if guess.long_axis_col in cols else 0,
            )
            value_col = st.selectbox(
                "値の列",
                cols,
                index=cols.index(guess.long_value_col) if guess.long_value_col in cols else 0,
            )
            scores = score_excel.extract_scores_long(df, name_col, axis_col, value_col)
        else:
            axis_cols = st.multiselect(
                "スコア指標の列（数値列）",
                [c for c in cols if c != name_col],
                default=[c for c in guess.numeric_cols if c != name_col],
            )
            scores = score_excel.extract_scores_wide(df, name_col, axis_cols)

        scale = st.number_input(
            "スケール（最大値の目安。自動推定値を編集可）",
            min_value=1.0,
            value=float(guess.suggested_scale or 5.0),
            step=1.0,
        )

        if scores:
            st.subheader("保存される内容")
            st.dataframe(
                pd.DataFrame(scores).T.rename_axis("施設名").reset_index(),
                use_container_width=True,
                hide_index=True,
            )
            st.caption("※ 施設名は①で手入力した名前と完全一致で紐付きます（無ければ新規作成）。")
            if st.button("💾 スコアをDBに保存", type="primary"):
                total = 0
                for fname, axes in scores.items():
                    fid = db.upsert_facility(conn, fname)
                    total += db.upsert_scores(conn, fid, axes, scale=scale)
                st.success(f"✅ {len(scores)} 施設 / {total} 指標を保存しました。")
        else:
            st.warning("数値の指標列が見つかりません。列マッピングを確認してください。")


# --------------------------------------------------------------------------- #
# 3) status
# --------------------------------------------------------------------------- #
elif page.startswith("③"):
    st.header("③ 取り込み状況")
    overview = db.facility_overview(conn)
    if not overview:
        st.info("まだデータがありません。①②から取り込んでください。")
    else:
        st.dataframe(
            pd.DataFrame(overview).drop(columns=["id"]),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"DB: {config.DB_PATH}")


# --------------------------------------------------------------------------- #
# 4) 強み・弱み分析 (steps 5-6)
# --------------------------------------------------------------------------- #
elif page.startswith("④"):
    st.header("④ 強み・弱み分析")

    mat = analysis.score_matrix(conn)
    if mat.empty:
        mat = analysis.google_matrix(conn)

    if mat.empty:
        st.info(
            "スコアデータがありません。先に ② スコアExcel取り込み または "
            "① 口コミCSV取り込み（review_details付き）を行ってください。"
        )
        st.stop()

    all_names = list(mat.index)
    target_name = st.selectbox("対象施設", all_names)

    # ── overall heatmap (all facilities) ─────────────────────────────────── #
    with st.expander("全施設スコア一覧（ヒートマップ）", expanded=False):
        st.plotly_chart(
            charts.score_heatmap(mat),
            use_container_width=True,
        )

    st.divider()

    # ── 3 comparison axes as tabs ─────────────────────────────────────────── #
    tab_a, tab_b, tab_c = st.tabs(
        ["A　比較施設の平均", "B　全体（DB内）の平均", "C　特定施設1つ"]
    )

    def _render_comparison(result: analysis.ComparisonResult | None, key: str) -> None:
        if result is None:
            st.warning("比較できるデータが不足しています。")
            return

        strengths, weaknesses = analysis.top_n(result.diff, n=5)

        col_left, col_right = st.columns([1, 1])
        with col_left:
            st.subheader("レーダーチャート")
            st.plotly_chart(
                charts.radar(
                    result.target,
                    result.baseline,
                    result.target_label,
                    result.baseline_label,
                ),
                use_container_width=True,
                key=f"radar_{key}",
            )
        with col_right:
            st.subheader("差分バーチャート")
            st.plotly_chart(
                charts.diff_bar(result.diff, result.target_label, result.baseline_label),
                use_container_width=True,
                key=f"bar_{key}",
            )

        st.subheader("TOP5 強み・弱み")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**💪 強み TOP5**")
            if strengths.empty:
                st.caption("比較施設を上回る指標なし")
            else:
                st.dataframe(strengths, use_container_width=True, hide_index=True)
        with c2:
            st.markdown("**⚠️ 弱み TOP5**")
            if weaknesses.empty:
                st.caption("比較施設を下回る指標なし")
            else:
                st.dataframe(weaknesses, use_container_width=True, hide_index=True)

        # raw numbers
        with st.expander("数値詳細", expanded=False):
            detail = pd.DataFrame(
                {
                    "対象": result.target.round(1),
                    "比較基準": result.baseline.round(1),
                    "差": result.diff.round(1),
                }
            )
            detail.index.name = "指標"
            st.dataframe(detail, use_container_width=True)
            st.caption("単位: 正規化スコア（0-100pt）")

    with tab_a:
        st.caption("対象施設 vs 比較施設（②で「比較施設」として登録した施設）の平均")
        result_a = analysis.build_comparison(conn, target_name, "comparison_avg")
        if result_a is None:
            comp_names = analysis.facilities_by_type(conn, "comparison")
            if not comp_names:
                st.warning(
                    "比較施設が登録されていません。"
                    "① 口コミCSV取り込み で「比較施設」を選んで取り込んでください。"
                )
            else:
                st.warning(f"比較施設（{comp_names}）のスコアデータがありません。")
        else:
            _render_comparison(result_a, "a")

    with tab_b:
        st.caption("対象施設 vs DB内の全施設平均（対象施設自身は除く）")
        result_b = analysis.build_comparison(conn, target_name, "all_avg")
        _render_comparison(result_b, "b")

    with tab_c:
        st.caption("対象施設 vs 特定の1施設を直接比較")
        others = [n for n in all_names if n != target_name]
        if not others:
            st.warning("比較できる他の施設がありません。")
        else:
            specific = st.selectbox("比較する施設", others, key="specific_select")
            result_c = analysis.build_comparison(
                conn, target_name, "specific", specific_name=specific
            )
            _render_comparison(result_c, "c")


# --------------------------------------------------------------------------- #
# 5) テキスト分析 & インサイト (steps 7-8)
# --------------------------------------------------------------------------- #
elif page.startswith("⑤"):
    st.header("⑤ テキスト分析 & インサイト")

    all_names = analysis.facility_names(conn)
    if not all_names:
        st.info("施設データがありません。① 口コミCSV取り込みから始めてください。")
        st.stop()

    target_name = st.selectbox("対象施設", all_names)

    # ── ⑦ Text analysis ──────────────────────────────────────────────────── #
    st.subheader("⑦ テキスト分析")

    with st.spinner("形態素解析 + TF-IDF を実行中…（初回は少し時間がかかります）"):
        profile = text_analysis.build_profile(conn, target_name, top_n=20)

    if profile.empty:
        st.warning("口コミテキストがありません。① で口コミCSVを取り込んでください。")
    else:
        st.caption(f"分析対象: {profile.n_reviews} 件の口コミ")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**TF-IDF キーワード TOP20**")
            st.caption("この施設に特徴的な単語（他施設と比べて相対的に多い語）")
            if profile.tfidf_keywords.empty:
                st.info("キーワードなし")
            else:
                import plotly.express as px
                fig_kw = px.bar(
                    profile.tfidf_keywords.head(20),
                    x="スコア",
                    y="単語",
                    orientation="h",
                    color="スコア",
                    color_continuous_scale="Blues",
                    height=500,
                )
                fig_kw.update_layout(
                    yaxis=dict(autorange="reversed"),
                    coloraxis_showscale=False,
                    margin=dict(t=10, b=10),
                )
                st.plotly_chart(fig_kw, use_container_width=True)

        with col2:
            st.markdown("**頻出フレーズ（バイグラム TOP20）**")
            st.caption("2語の組み合わせで頻繁に登場するフレーズ")
            if profile.bigrams.empty:
                st.info("フレーズなし（口コミ件数が少ない可能性があります）")
            else:
                fig_bi = px.bar(
                    profile.bigrams.head(20),
                    x="件数",
                    y="フレーズ",
                    orientation="h",
                    color="件数",
                    color_continuous_scale="Greens",
                    height=500,
                )
                fig_bi.update_layout(
                    yaxis=dict(autorange="reversed"),
                    coloraxis_showscale=False,
                    margin=dict(t=10, b=10),
                )
                st.plotly_chart(fig_bi, use_container_width=True)

        with st.expander("トライグラム（3語フレーズ）TOP20", expanded=False):
            if profile.trigrams.empty:
                st.info("トライグラムなし")
            else:
                st.dataframe(profile.trigrams, use_container_width=True, hide_index=True)

        with st.expander("代表的な口コミ", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**高評価 TOP3**")
                for i, r in enumerate(profile.high_rated, 1):
                    st.text_area(f"高評価 {i}", r, height=120, key=f"hi_{i}", disabled=True)
            with c2:
                st.markdown("**低評価 TOP3**")
                if not profile.low_rated:
                    st.caption("低評価（3★以下）の口コミなし")
                for i, r in enumerate(profile.low_rated, 1):
                    st.text_area(f"低評価 {i}", r, height=120, key=f"lo_{i}", disabled=True)

    st.divider()

    # ── ⑧ LLM Insights ───────────────────────────────────────────────────── #
    st.subheader("⑧ LLMインサイト")

    # Score context: use comparison_avg if available, else all_avg
    score_diff = None
    comp_result = analysis.build_comparison(conn, target_name, "comparison_avg")
    if comp_result is None:
        comp_result = analysis.build_comparison(conn, target_name, "all_avg")
    if comp_result is not None:
        score_diff = comp_result.diff
        st.caption(f"スコア比較軸: {comp_result.baseline_label}")

    api_key = llm.get_api_key()
    if not api_key:
        st.info(
            "Gemini API キーが設定されていません。\n\n"
            "取得方法: https://aistudio.google.com/ → 「Get API key」（Googleアカウントで無料）\n\n"
            "設定方法（いずれか）:\n"
            "- 環境変数 `GEMINI_API_KEY=AIza...` を設定して再起動\n"
            "- `.streamlit/secrets.toml` に `GEMINI_API_KEY = \"AIza...\"` を追記\n"
            "- 下のフォームに直接入力（このセッション限り）"
        )
        api_key = st.text_input("Gemini API キーを入力（セッション限り）", type="password")

    if not profile.empty:
        if st.button("✨ インサイトを生成する", type="primary", disabled=not api_key):
            kw_list = profile.tfidf_keywords["単語"].tolist() if not profile.tfidf_keywords.empty else []
            bi_list = profile.bigrams["フレーズ"].tolist() if not profile.bigrams.empty else []

            prompt = llm.build_prompt(
                facility_name=target_name,
                score_diff=score_diff,
                tfidf_keywords=kw_list,
                bigrams=bi_list,
                high_reviews=profile.high_rated,
                low_reviews=profile.low_rated,
            )

            with st.spinner("LLMが分析中です…"):
                result = llm.generate_insights(prompt, api_key)

            if result.error:
                st.error(result.error)
                if result.raw:
                    with st.expander("raw レスポンス"):
                        st.text(result.raw)
            else:
                st.success("インサイト生成完了")
                # stash for the report page (⑥)
                st.session_state["insights"] = result
                st.session_state["insights_facility"] = target_name

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


# --------------------------------------------------------------------------- #
# 6) レポート出力 (step 9)
# --------------------------------------------------------------------------- #
else:
    import tempfile

    st.header("⑥ レポート出力 (PPTX)")
    st.caption("これまでの分析（スコア比較・強み弱み・テキスト分析・インサイト）を1つのPowerPointにまとめます。")

    all_names = analysis.facility_names(conn)
    if not all_names:
        st.info("施設データがありません。① 口コミCSV取り込みから始めてください。")
        st.stop()

    col1, col2 = st.columns(2)
    with col1:
        target_name = st.selectbox("対象施設", all_names)
    with col2:
        axis_label = st.radio(
            "比較基準",
            ["比較施設の平均", "全体（DB内）の平均"],
            horizontal=True,
        )
    axis = "comparison_avg" if axis_label == "比較施設の平均" else "all_avg"

    # reuse insights generated on page ⑤ if they match this facility
    insights = None
    if st.session_state.get("insights_facility") == target_name:
        insights = st.session_state.get("insights")
        st.success("⑤で生成したインサイトをレポートに含めます。")
    else:
        st.info(
            "この施設のLLMインサイトは未生成です。⑤で生成するとレポートに反映されます"
            "（未生成のままでも、グラフ・表・テキスト分析だけのレポートは作成できます）。"
        )

    if st.button("📑 レポート(PPTX)を生成", type="primary"):
        with st.spinner("スライドを生成中…"):
            tmp_path = Path(tempfile.mkdtemp()) / f"{target_name}_分析レポート.pptx"
            report.build_report(
                conn, target_name, axis=axis, insights=insights, output_path=tmp_path
            )
        with open(tmp_path, "rb") as f:
            st.download_button(
                "⬇️ ダウンロード",
                data=f.read(),
                file_name=tmp_path.name,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                type="primary",
            )
        st.success("生成完了。上のボタンからダウンロードしてください。")
