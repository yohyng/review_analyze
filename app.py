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
    csv_profiler,
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
page = st.sidebar.radio(
    "メニュー",
    [
        "⚡ クイックレポート",
        "─── 詳細分析 ───",
        "🔍 施設を選ぶ",
        "📈 強み・弱み",
        "💬 テキスト & インサイト",
        "📑 レポート出力",
        "─── データ管理 ───",
        "📥 データ登録",
        "📋 取り込み状況",
        "🔬 CSVプロファイラ",
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


# separators act as disabled dividers — skip them
if page in ("─── 詳細分析 ───", "─── データ管理 ───"):
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
        inferred = []
        if uploaded:
            with st.spinner("CSVを解析中..."):
                try:
                    inferred = review_csv.infer_facilities(uploaded)
                    uploaded.seek(0)
                except Exception:
                    inferred = []

        if len(inferred) > 1:
            sel_key = "csv_facilities_checked"
            # Reset checkboxes when file changes
            inferred_keys = {f["key"] for f in inferred}
            if sel_key not in st.session_state or set(st.session_state[sel_key]) != inferred_keys:
                st.session_state[sel_key] = {f["key"]: True for f in inferred}  # default: all checked

            # ── ① 施設リスト ──────────────────────────────── #
            st.markdown(f"**{len(inferred)} 施設が見つかりました。取り込む施設を選んでください。**")
            c1, c2, _ = st.columns([1, 1, 3])
            with c1:
                if st.button("✅ すべて選択", use_container_width=True):
                    for k in st.session_state[sel_key]:
                        st.session_state[sel_key][k] = True
                    st.rerun()
            with c2:
                if st.button("☐ すべて解除", use_container_width=True):
                    for k in st.session_state[sel_key]:
                        st.session_state[sel_key][k] = False
                    st.rerun()

            st.markdown("")
            for _f in inferred:
                _r = f"★{_f['avg_rating']}" if _f["avg_rating"] else ""
                label = f"**{_f['name']}** — {_f['count']}件　{_r}"
                st.session_state[sel_key][_f["key"]] = st.checkbox(
                    label,
                    value=st.session_state[sel_key].get(_f["key"], True),
                    key=f"fac_check_{_f['key']}",
                )

            # ── ② 保存実行 ────────────────────────────────── #
            selected_fac = [f for f in inferred if st.session_state[sel_key].get(f["key"], False)]
            st.divider()

            if selected_fac:
                col1, col2 = st.columns([1, 2])
                with col1:
                    ftype_label = st.radio(
                        "種別", list(config.FACILITY_TYPES.values()), horizontal=True, key="csv_ftype_multi"
                    )
                ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)

                if st.button(
                    f"💾 {len(selected_fac)} 施設を保存する",
                    type="primary", use_container_width=True, key="csv_save_multi"
                ):
                    with st.status(f"保存中... 0 / {len(selected_fac)} 完了", expanded=True) as status:
                        for i, chosen_fac in enumerate(selected_fac, 1):
                            with st.status(f"🔄 {chosen_fac['name']} 処理中...", expanded=False) as fac_status:
                                try:
                                    st.write(f"📖 {len(chosen_fac['reviews']) if 'reviews' in chosen_fac else '?'} 件のデータを解析中...")
                                    result = review_csv.parse_reviews(uploaded, facility_key=chosen_fac["key"])
                                    uploaded.seek(0)
                                    st.write(f"✅ {len(result.reviews)} 件のパース完了")
                                except Exception as e:
                                    st.error(f"パース失敗: {e}")
                                    fac_status.update(label=f"❌ {chosen_fac['name']} パース失敗", state="error")
                                    continue

                                try:
                                    st.write("💾 DB に施設情報・口コミを保存中...")
                                    fid = db.upsert_facility(
                                        conn, chosen_fac["name"], ftype=ftype,
                                        category=result.category,
                                        general_rating=result.general_rating,
                                        total_reviews=result.total_reviews,
                                    )
                                    n_total = len(result.reviews)
                                    _pb = st.progress(0, text=f"0 / {n_total} 件")
                                    inserted, skipped = db.insert_reviews(
                                        conn, fid, result.reviews,
                                        progress_callback=lambda cur, tot, pb=_pb: pb.progress(
                                            cur / tot, text=f"{cur} / {tot} 件保存中..."
                                        ),
                                    )
                                    _pb.empty()
                                    st.write(f"✅ {inserted} 件の口コミを保存（重複 {skipped} 件スキップ）")
                                except Exception as e:
                                    st.error(f"DB保存失敗: {e}")
                                    fac_status.update(label=f"❌ {chosen_fac['name']} 保存失敗", state="error")
                                    continue

                                try:
                                    st.write("🔢 定量スコアを算出中...")
                                    n_axes = scoring.compute_and_store(conn, fid)
                                    if n_axes:
                                        st.write(f"✅ {n_axes} 軸のスコアを自動算出")
                                    else:
                                        st.write("ℹ️ スコアデータなし")
                                except Exception as e:
                                    st.warning(f"スコア算出スキップ: {e}")

                                fac_status.update(
                                    label=f"✅ {chosen_fac['name']} 完了（{inserted}件保存）",
                                    state="complete"
                                )

                            status.update(label=f"保存中... {i} / {len(selected_fac)} 完了")

                        status.update(label=f"✅ {len(selected_fac)} 施設の保存が完了しました", state="complete")
                    st.balloons()
            else:
                st.warning("施設を1つ以上選択してください。")

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
                    result = review_csv.parse_reviews(uploaded, facility_key=_f["key"])
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

        elif uploaded:
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

            facility_name = st.text_input("施設名", value=facility_name_input, key="csv_fac_manual").strip()

            if facility_name:
                try:
                    result = review_csv.parse_reviews(uploaded)
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

                if st.button("💾 DBに保存", type="primary", key="csv_save_manual"):
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
        st.info("まだデータがありません。")
        st.markdown("👉 **データ管理 → 📥 データ登録** から口コミCSVを投入してください。")
    else:
        st.dataframe(
            pd.DataFrame(overview).drop(columns=["id"]),
            use_container_width=True, hide_index=True,
        )
        st.caption(f"DB: {config.DB_PATH}")

        st.divider()
        st.subheader("施設の操作")
        _del_names = [f["施設名"] for f in overview]
        _del_col1, _del_col2 = st.columns([3, 1])
        with _del_col1:
            _del_target = st.selectbox("操作対象の施設", _del_names, key="del_target")
        with _del_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ 削除", key="del_btn", type="secondary"):
                st.session_state["del_confirm"] = _del_target

        if st.session_state.get("del_confirm") == _del_target:
            st.warning(
                f"「{_del_target}」とその口コミデータをすべて削除します。元に戻せません。"
            )
            _dc1, _dc2 = st.columns(2)
            with _dc1:
                if st.button("⚠️ はい、削除する", type="primary", key="del_yes"):
                    _del_fid = conn.execute(
                        "SELECT id FROM facility WHERE name = ?", (_del_target,)
                    ).fetchone()
                    if _del_fid:
                        db.delete_facility(conn, _del_fid["id"])
                    st.session_state.pop("del_confirm", None)
                    st.success(f"「{_del_target}」を削除しました。")
                    st.rerun()
            with _dc2:
                if st.button("キャンセル", key="del_no"):
                    st.session_state.pop("del_confirm", None)
                    st.rerun()


# ============================================================================
# 🔬 CSVプロファイラ
# ============================================================================
elif page == "🔬 CSVプロファイラ":
    st.header("🔬 CSVプロファイラ")
    st.caption(
        "CSVをアップロードするとデータ構造（列・型・統計・サンプル）を解析し、"
        "Claude に貼り付けられるプロンプトを生成します。"
    )

    _pf_upload = st.file_uploader(
        "CSV / TSV ファイル", type=["csv", "tsv", "txt"], key="pf_upload"
    )

    if _pf_upload:
        try:
            _pf_df = csv_profiler.load_df(_pf_upload)
            _pf_upload.seek(0)
        except Exception as _e:
            st.error(f"読み込みに失敗しました: {_e}")
            st.stop()

        st.success(f"読み込み完了: **{len(_pf_df)} 行 × {len(_pf_df.columns)} 列**")

        with st.expander("データプレビュー（先頭20行）", expanded=False):
            st.dataframe(_pf_df.head(20), use_container_width=True)

        _pf_question = st.text_area(
            "Claudeへの質問（省略可）",
            placeholder=(
                "例: この口コミCSVの列構造を把握してください。\n"
                "評価が空欄の行が多い理由と、テキスト分析に使える列を教えてください。"
            ),
            height=90,
            key="pf_question",
        )

        _pf_prompt = csv_profiler.build_claude_prompt(
            _pf_df,
            filename=getattr(_pf_upload, "name", ""),
            question=_pf_question,
        )

        st.subheader("📤 Claude用プロンプト")
        st.caption(
            "以下のテキストをコピーして Claude（claude.ai など）に貼り付けてください。"
            "CSVを直接アップロードしなくてもデータ構造を共有できます。"
        )
        st.code(_pf_prompt, language="markdown")


# ============================================================================
# ⚡ クイックレポート
# ============================================================================
elif page == "⚡ クイックレポート":
    st.header("⚡ クイックレポート")

    _q_names = analysis.facility_names(conn)
    if not _q_names:
        st.info("まだ施設データがありません。")
        st.markdown(
            "👉 まず **データ管理 → 📥 データ登録** から口コミCSVを投入してください。"
        )
        st.stop()

    # ── ① 対象施設を選ぶ ─────────────────────────────────────────────── #
    st.subheader("① 対象施設を選ぶ")
    _qc1, _qc2 = st.columns([3, 1])
    with _qc1:
        _q_target = st.selectbox(
            "対象施設",
            _q_names,
            index=_q_names.index(st.session_state["analysis_target"])
            if st.session_state.get("analysis_target") in _q_names else 0,
            key="q_target",
            label_visibility="collapsed",
        )
    with _qc2:
        _q_n_topics = st.slider("トピック数", 2, 10, 5, key="q_n_topics")

    # 施設ステータスカード
    _q_stats = db.facility_stats(conn, _q_target)
    if _q_stats:
        _cs = st.columns(4)
        _cs[0].metric("口コミ数", f"{_q_stats['n_reviews']} 件")
        _cs[1].metric("本文あり", f"{_q_stats['n_text_reviews']} 件")
        _cs[2].metric("平均評点", f"★{_q_stats['avg_rating']}" if _q_stats['avg_rating'] else "-")
        _cs[3].metric("スコア軸", f"{len(_q_stats['score_axes'])} 軸" if _q_stats['score_axes'] else "なし")
        if _q_stats['date_oldest'] != "-":
            st.caption(f"口コミ期間: {_q_stats['date_oldest']} 〜 {_q_stats['date_newest']}")

    st.divider()

    # ── ② 分析モード ──────────────────────────────────────────────────── #
    st.subheader("② 分析モードを選ぶ")
    _q_mode = st.radio(
        "分析モード",
        ["🏠 単体分析", "🆚 比較分析"],
        horizontal=True,
        key="q_mode",
        help="単体：その施設だけを深掘り。比較：他施設との強み・弱みを対比。",
    )

    _q_axis = "comparison_avg"
    _q_specific = None

    if _q_mode == "🆚 比較分析":
        _others = [n for n in _q_names if n != _q_target]
        if not _others:
            st.warning("比較できる他の施設がDBにありません。単体分析でレポートを生成します。")
            _q_mode = "🏠 単体分析"
        else:
            _q_axis_label = st.radio(
                "比較基準",
                ["比較施設の平均", "DB全体の平均", "特定施設1つを指定"],
                horizontal=True,
                key="q_axis_label",
            )
            if _q_axis_label == "比較施設の平均":
                _q_axis = "comparison_avg"
                _comp_peers = analysis.facilities_by_type(conn, "comparison")
                if _comp_peers:
                    st.caption(f"比較対象: {', '.join(_comp_peers)}")
                else:
                    st.warning("種別「比較施設」として登録された施設がありません。DB全体平均で代替します。")
                    _q_axis = "all_avg"
            elif _q_axis_label == "DB全体の平均":
                _q_axis = "all_avg"
                st.caption(f"比較対象: DB内の全施設（対象施設を除く {len(_others)} 施設の平均）")
            else:
                _q_axis = "specific"
                _q_specific = st.selectbox("比較先施設", _others, key="q_specific")

    st.divider()

    # ── ③ APIキー（任意）────────────────────────────────────────────── #
    _q_api_key = llm.get_api_key()
    if not _q_api_key:
        with st.expander("✨ LLMインサイトを追加する（任意）"):
            _q_api_key = st.text_input(
                "Gemini API キー",
                type="password", key="q_api",
                help="aistudio.google.com で無料取得できます。省略してもレポートを生成できます。",
            )

    # ── 実行ボタン ────────────────────────────────────────────────────── #
    _q_btn_label = (
        f"🚀 「{_q_target}」のレポートを生成"
        if _q_mode == "🏠 単体分析"
        else f"🚀 「{_q_target}」の比較レポートを生成"
    )
    if not (_q_stats and _q_stats["n_reviews"] > 0):
        st.warning("この施設には口コミデータがありません。データ登録を確認してください。")
        st.stop()

    if st.button(_q_btn_label, type="primary", use_container_width=True, key="q_run"):
        _q_fid = conn.execute(
            "SELECT id FROM facility WHERE name = ?", (_q_target,)
        ).fetchone()
        if not _q_fid:
            st.error("施設データが見つかりません。")
            st.stop()
        _q_fid = _q_fid["id"]

        _q_insights = None
        _q_topic_list = []

        with st.status("分析・生成中…", expanded=True) as _status:

            # ① スコア算出
            st.write("📊 スコア算出中…")
            _q_n_axes = scoring.compute_and_store(conn, _q_fid)
            st.write(f"✅ スコア {_q_n_axes} 軸算出完了")

            # ② テキスト分析
            st.write("💬 テキスト分析中…")
            _q_profile = text_analysis.build_profile(conn, _q_target, top_n=20)
            if _q_profile.empty:
                st.write("⚠️ テキスト付き口コミが不足のためスキップ")
            else:
                st.write(f"✅ テキスト分析完了（キーワード {len(_q_profile.tfidf_keywords)} 件）")

            # ③ トピック分析
            st.write("🗂️ トピック分析中…")
            _q_rev_rows = conn.execute(
                "SELECT rating, text FROM review WHERE facility_id = ?",
                (_q_fid,),
            ).fetchall()
            _q_revs = [(_r["rating"], _r["text"] or "") for _r in _q_rev_rows]
            _q_topic_list = topics.extract_topics(_q_revs, n_topics=_q_n_topics)
            if _q_topic_list:
                st.write(f"✅ トピック {len(_q_topic_list)} 件抽出完了")
            else:
                st.write("⚠️ トピック抽出には本文付き口コミが不足")

            # ④ LLMインサイト（任意）
            if _q_api_key and not _q_profile.empty:
                st.write("✨ LLMインサイト生成中…")
                _q_comp = (
                    analysis.build_comparison(conn, _q_target, _q_axis, specific_name=_q_specific)
                    or analysis.build_comparison(conn, _q_target, "all_avg")
                )
                _q_diff = _q_comp.diff if _q_comp else None
                _q_kw = _q_profile.tfidf_keywords["単語"].tolist()
                _q_bi = (
                    _q_profile.bigrams["フレーズ"].tolist()
                    if not _q_profile.bigrams.empty else []
                )
                _q_prompt = llm.build_prompt(
                    _q_target, _q_diff, _q_kw, _q_bi,
                    _q_profile.high_rated, _q_profile.low_rated,
                )
                _q_result = llm.generate_insights(_q_prompt, _q_api_key)
                if _q_result.error:
                    st.write(f"⚠️ インサイト生成失敗: {_q_result.error}")
                else:
                    _q_insights = _q_result
                    st.write("✅ インサイト生成完了")
            elif not _q_api_key:
                st.write("⏭️ API キー未設定のためインサイト生成をスキップ")

            # ⑤ PPTX生成
            st.write("📑 PPTX生成中…")
            _q_use_axis = _q_axis if _q_mode == "🆚 比較分析" else "comparison_avg"
            _q_tmp = Path(tempfile.mkdtemp()) / f"{_q_target}_分析レポート.pptx"
            _q_built_comp = report.build_report(
                conn, _q_target,
                axis=_q_use_axis,
                specific_name=_q_specific,
                insights=_q_insights,
                topic_list=_q_topic_list if _q_topic_list else None,
                output_path=_q_tmp,
            )
            st.write("✅ PPTX生成完了")
            _status.update(label="✅ 完了！レポートをダウンロードしてください", state="complete")

        # スライド内容サマリ
        _q_slides = []
        _q_slides.append("表紙 / サマリ / テキスト分析 / インサイト（常時）")
        if _q_mode == "🆚 比較分析":
            _q_comp_check = analysis.build_comparison(conn, _q_target, _q_use_axis, specific_name=_q_specific)
            if _q_comp_check:
                _q_slides.insert(1, f"スコア比較（vs {_q_comp_check.baseline_label}）")
            else:
                st.info("比較データが不足のため、スコア比較スライドは省略されました。")
        if _q_topic_list:
            _q_slides.append(f"トピック分析（{len(_q_topic_list)} 件）")

        with open(_q_tmp, "rb") as _f:
            st.download_button(
                f"⬇️ {_q_target}_分析レポート.pptx",
                data=_f.read(),
                file_name=_q_tmp.name,
                mime=(
                    "application/vnd.openxmlformats-officedocument"
                    ".presentationml.presentation"
                ),
                type="primary",
                use_container_width=True,
                key="q_dl",
            )
        st.caption("含まれるスライド: " + " / ".join(_q_slides))


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
