"""Admin-mode pages (dashboard / facilities / import / analysis / settings /
KAIZODE / account) for VoiceBAUM.

Extracted from app.py. render() is called once per Streamlit rerun when
app_mode != "analysis" AND the user is authenticated (the login gate in
app.py st.stop()s earlier otherwise). The sidebar that sets admin_page still
lives in app.py and runs before this.
"""
from __future__ import annotations

import base64
import logging
import os
import tempfile
import time
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src import (
    analysis, auth, charts, config, csv_profiler, db, geocode, images, kaizode,
    llm, preview, report, review_csv, score_excel, scoring, search,
    text_analysis, topic_score, topics,
)
from src.ui import components, data
from src.ui.theme import ACCENT, ACCENT_RING, ACCENT_SOFT

logger = logging.getLogger("voicebaum")


def render():
    conn = data.get_conn()
    _all_facility_names = data.all_facility_names
    _facility_card = components.facility_card
    _loading_card_html = components.loading_card_html
    _review_counts = data.review_counts
    _facility_meta = data.facility_meta
    _selected_card_html = components.selected_card_html
    _topic_sig = data.topic_sig
    _topic_matrix_cached = data.topic_matrix_cached
    _photo_from_db = data.photo_from_db
    _infer_facilities_cached = data.infer_facilities_cached
    _parse_reviews_cached = data.parse_reviews_cached
    _page = st.session_state["admin_page"]

    # ══════════════════════════════════════════════════════════════════════ #
    # ダッシュボード
    # ══════════════════════════════════════════════════════════════════════ #
    if _page == "dashboard":
        st.markdown(
            '<div class="vb-step">管理モード</div>'
            '<h1 class="vb-h1">ダッシュボード</h1>',
            unsafe_allow_html=True,
        )

        overview = db.facility_overview(conn)
        n_fac = len(overview)
        n_reviews = sum(r["口コミ数"] for r in overview)
        n_no_data = sum(1 for r in overview if r["口コミ数"] == 0)

        _kc1, _kc2, _kc3, _kc4 = st.columns(4)
        _kc1.metric("登録施設", f"{n_fac} 件")
        _kc2.metric("総口コミ", f"{n_reviews} 件")
        _kc3.metric("未分析施設", f"{n_no_data} 件")
        _kc4.metric("アプリバージョン", config.APP_VERSION)

        if overview:
            st.divider()
            st.subheader("施設別の口コミ件数")
            _df = pd.DataFrame(overview)[["施設名", "口コミ数"]].sort_values(
                "口コミ数", ascending=False
            ).head(10)
            _fig = px.bar(
                _df, x="施設名", y="口コミ数",
                color_discrete_sequence=[ACCENT],
                height=320,
            )
            _fig.update_layout(
                plot_bgcolor="#F7F7F4",
                paper_bgcolor="#F7F7F4",
                margin=dict(t=10, b=10, l=0, r=0),
                xaxis=dict(tickangle=-30),
            )
            st.plotly_chart(_fig, width="stretch")

            st.divider()
            st.subheader("施設一覧")
            st.dataframe(
                pd.DataFrame(overview).drop(columns=["id"]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info(
                "まだデータがありません。「📥 データ取り込み」からCSVを投入してください。"
            )

    # ══════════════════════════════════════════════════════════════════════ #
    # 施設管理
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "facilities":
        st.markdown(
            '<div class="vb-step">管理モード</div>'
            '<h1 class="vb-h1">施設管理</h1>',
            unsafe_allow_html=True,
        )
        overview = db.facility_overview(conn)
        if not overview:
            st.info("まだデータがありません。")
            st.markdown("👉 **📥 データ取り込み** から口コミCSVを投入してください。")
        else:
            st.dataframe(
                pd.DataFrame(overview).drop(columns=["id"]),
                width="stretch",
                hide_index=True,
            )

            st.divider()
            st.subheader("施設の操作")
            _del_names = [f["施設名"] for f in overview]
            _dc1, _dc2 = st.columns([3, 1])
            with _dc1:
                _del_target = st.selectbox("操作対象の施設", _del_names, key="del_target")
            with _dc2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️ 削除", key="del_btn", type="secondary"):
                    st.session_state["del_confirm"] = _del_target

            if st.session_state.get("del_confirm") == _del_target:
                st.warning(
                    f"「{_del_target}」とその口コミデータをすべて削除します。元に戻せません。"
                )
                _yc1, _yc2 = st.columns(2)
                with _yc1:
                    if st.button("⚠️ はい、削除する", type="primary", key="del_yes"):
                        _del_fid = conn.execute(
                            "SELECT id FROM facility WHERE name = ?", (_del_target,)
                        ).fetchone()
                        if _del_fid:
                            db.delete_facility(conn, _del_fid["id"])
                        st.session_state.pop("del_confirm", None)
                        st.success(f"「{_del_target}」を削除しました。")
                        st.rerun()
                with _yc2:
                    if st.button("キャンセル", key="del_no"):
                        st.session_state.pop("del_confirm", None)
                        st.rerun()

    # ══════════════════════════════════════════════════════════════════════ #
    # データ取り込み
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "import":
        st.markdown(
            '<div class="vb-step">管理モード</div>'
            '<h1 class="vb-h1">データ取り込み</h1>',
            unsafe_allow_html=True,
        )
        tab_csv, tab_excel = st.tabs(["📄 口コミ CSV", "📊 スコア Excel"])

        # ── CSV tab ─────────────────────────────────────────────────────── #
        with tab_csv:
            st.caption(
                "KAIZODE などからDLした口コミCSV/TSVを投げ込みます（施設名は手入力）。"
            )

            uploaded = st.file_uploader(
                "口コミ CSV / TSV", type=["csv", "tsv", "txt"], key="csv_upload"
            )

            inferred = []
            if uploaded:
                # ファイル内容でキャッシュ（チェック操作の再実行ごとに再解析しない）
                try:
                    inferred = _infer_facilities_cached(uploaded.getvalue())
                except Exception as _e:
                    inferred = []
                    logger.exception("infer_facilities failed")
                    st.error(f"ファイルの解析に失敗しました: {_e}")

            if len(inferred) > 1:
                sel_key = "csv_facilities_checked"
                inferred_keys = {f["key"] for f in inferred}
                if sel_key not in st.session_state or set(st.session_state[sel_key]) != inferred_keys:
                    st.session_state[sel_key] = {f["key"]: True for f in inferred}

                st.markdown(f"**{len(inferred)} 施設が見つかりました。取り込む施設を選んでください。**")
                c1, c2, _ = st.columns([1, 1, 3])
                with c1:
                    if st.button("✅ すべて選択", width="stretch"):
                        for k in st.session_state[sel_key]:
                            st.session_state[sel_key][k] = True
                        st.rerun()
                with c2:
                    if st.button("☐ すべて解除", width="stretch"):
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

                selected_fac = [f for f in inferred if st.session_state[sel_key].get(f["key"], False)]
                st.divider()

                if selected_fac:
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        ftype_label = st.radio(
                            "種別",
                            list(config.FACILITY_TYPES.values()),
                            horizontal=True,
                            key="csv_ftype_multi",
                        )
                    ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)

                    if st.button(
                        f"💾 {len(selected_fac)} 施設を保存する",
                        type="primary", width="stretch", key="csv_save_multi",
                    ):
                        _total_fac = len(selected_fac)
                        with st.status(
                            f"保存中... 0 / {_total_fac} 完了", expanded=True
                        ) as status:
                            # ① ファイルは1回だけ解析して施設ごとに振り分ける
                            #    （施設数ぶん再解析するとO(n²)になり大きいファイルで力尽きる）
                            status.write("📖 ファイルを1回だけ解析中...")
                            _grouped = None
                            try:
                                _grouped = review_csv.parse_reviews_grouped(uploaded.getvalue())
                            except Exception as e:
                                status.update(label=f"❌ 解析に失敗しました: {e}", state="error")

                            if _grouped is not None:
                                _pb = st.progress(0.0, text=f"0 / {_total_fac} 施設")
                                _n_ok = _n_rev = _n_dup = 0
                                # ② 以降はDB書き込みのみ（再解析なし）
                                for i, chosen_fac in enumerate(selected_fac, 1):
                                    _entry = _grouped.get(chosen_fac["key"])
                                    if not _entry:
                                        status.write(f"⏭️ {chosen_fac['name']}: 該当データなし")
                                    else:
                                        _result = _entry[1]
                                        try:
                                            fid = db.upsert_facility(
                                                conn, chosen_fac["name"], ftype=ftype,
                                                category=_result.category,
                                                general_rating=_result.general_rating,
                                                total_reviews=_result.total_reviews,
                                            )
                                            inserted, skipped = db.insert_reviews(
                                                conn, fid, _result.reviews
                                            )
                                            try:
                                                scoring.compute_and_store(conn, fid)
                                            except Exception:
                                                # スコア算出は任意（失敗しても取り込みは成功）
                                                logger.warning(
                                                    "score compute failed for %s",
                                                    chosen_fac["name"],
                                                )
                                            _n_ok += 1
                                            _n_rev += inserted
                                            _n_dup += skipped
                                            status.write(
                                                f"✅ {chosen_fac['name']}: {inserted:,}件保存"
                                                f"（重複{skipped:,}件）"
                                            )
                                        except Exception as e:
                                            status.write(f"❌ {chosen_fac['name']}: {e}")
                                    _pb.progress(i / _total_fac, text=f"{i} / {_total_fac} 施設")
                                    status.update(label=f"保存中... {i} / {_total_fac} 完了")

                                _pb.empty()
                                status.update(
                                    label=f"✅ {_n_ok} / {_total_fac} 施設・計 {_n_rev:,} 件を保存"
                                          f"（重複 {_n_dup:,} 件スキップ）",
                                    state="complete",
                                )
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
                        "施設名（手入力・必須）",
                        placeholder="例: 風の海",
                        key="csv_fac_input",
                    )
                with col2:
                    ftype_label = st.radio(
                        "種別", list(config.FACILITY_TYPES.values()), horizontal=True
                    )
                ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)

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
                        result = _parse_reviews_cached(uploaded.getvalue(), _f["key"])
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
                    st.dataframe(preview, width="stretch", hide_index=True)

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
                        "施設名（手入力・必須）",
                        placeholder="例: 風の海",
                        key="csv_fac_input_manual",
                    )
                with col2:
                    ftype_label = st.radio(
                        "種別", list(config.FACILITY_TYPES.values()), horizontal=True
                    )
                ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)
                facility_name = facility_name_input.strip()

                if facility_name:
                    try:
                        result = _parse_reviews_cached(uploaded.getvalue(), None)
                    except Exception as e:
                        st.error(f"パースに失敗しました: {e}")
                        st.stop()

                    st.success(
                        f"解析: {len(result.reviews)} 件の口コミ "
                        f"（生 {result.n_raw} 行 / スキップ {result.n_skipped} 行）"
                    )
                    preview = pd.DataFrame([
                        {
                            "★": r.rating,
                            "日付": r.review_date[:10] if len(r.review_date) >= 10 else r.review_date,
                            "本文": (r.text[:60] + "…") if len(r.text) > 60 else r.text,
                        }
                        for r in result.reviews[:20]
                    ])
                    st.dataframe(preview, width="stretch", hide_index=True)

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

        # ── Excel tab ───────────────────────────────────────────────────── #
        with tab_excel:
            st.caption("既存の定量化指標 Excel を投げ込み → 列を確認して保存。")
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
                st.dataframe(df.head(20), width="stretch")

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
                        width="stretch", hide_index=True,
                    )
                    if st.button("💾 スコアをDBに保存", type="primary", key="xl_save"):
                        total = 0
                        for fname, axes in scores.items():
                            fid = db.upsert_facility(conn, fname)
                            total += db.upsert_scores(conn, fid, axes, scale=scale)
                        st.success(
                            f"✅ {len(scores)} 施設 / {total} 指標を保存しました。"
                        )
                else:
                    st.warning("数値の指標列が見つかりません。列マッピングを確認してください。")

    # ══════════════════════════════════════════════════════════════════════ #
    # トピックスコア（独自指標）
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "topic":
        st.markdown(
            '<div class="vb-step">独自指標</div>'
            '<h1 class="vb-h1">感情・トピック統合スコア</h1>',
            unsafe_allow_html=True,
        )
        st.caption(
            "口コミを文単位でポジ／ネガ評価し、トピック確率で重み付けした独自指標。"
            "各トピック（指標軸）ごとに「どれだけ語られ、どう評価されているか」を可視化します。"
        )

        _tnames = analysis.facility_names(conn)
        if not _tnames:
            st.info("施設データがありません。")
            st.stop()

        _tt = st.selectbox(
            "対象施設", _tnames,
            index=_tnames.index(st.session_state["analysis_target"])
            if st.session_state.get("analysis_target") in _tnames else 0,
            key="topic_fac",
        )
        st.session_state["analysis_target"] = _tt

        with st.spinner("感情・トピック統合スコアを算出中…"):
            _tres = topic_score.analyze_facility(conn, _tt)

        if _tres.empty:
            st.warning("トピックスコアの算出には本文付きの口コミが必要です。")
        else:
            _c1, _c2, _c3, _c4 = st.columns(4)
            _c1.metric("総合感情スコア", f"{_tres.weighted_sentiment_100:.0f} / 100")
            _c2.metric("分析文数", f"{_tres.n_sentences} 文")
            _c3.metric("レビュー数", f"{_tres.n_reviews} 件")
            _best = _tres.sorted_by_sentiment()[0] if _tres.topics else None
            _c4.metric("最高評価の観点", _best.name if _best else "-")

            _tsent = _tres.sentiment_by_topic()
            _tnames = [t for t in topic_score.TOPIC_ORDER if t in _tsent]
            st.plotly_chart(
                charts.topic_matrix_bar(
                    _tnames, [_tsent[t] for t in _tnames],
                    overall_value=_tres.weighted_sentiment_100,
                ),
                width="stretch", key="adm_ts_bar",
            )

            _cl, _cr = st.columns([3, 2])
            with _cl:
                st.markdown("**トピック別の詳細**")
                _df = pd.DataFrame([
                    {
                        "トピック（指標軸）": t.name,
                        "感情スコア": round(t.sentiment_100, 1),
                        "言及度(%)": round(t.salience_pct, 1),
                        "統合スコア": round(t.avg_score, 4),
                        "重み": round(t.weight, 3),
                    }
                    for t in _tres.sorted_by_sentiment()
                ])
                st.dataframe(_df, width="stretch", hide_index=True)
            with _cr:
                st.markdown("**言及度（話題の量）**")
                st.plotly_chart(
                    charts.topic_salience_bar(_tres), width="stretch", key="adm_ts_sal"
                )

            st.caption(
                f"モデル全体スコア Σ(avg×重み) = {_tres.overall_100} / 100 ・ "
                f"バックエンド: {_tres.backend}（軽量: TF-IDFコサイン / SBERT任意）"
            )
            with st.expander("この指標について（算出モデル）", expanded=False):
                st.markdown(
                    "- **感情値**: 各文をキーワード辞書でポジ／中立／ネガ評価 → "
                    "温度スケーリング（T=0.7）→ 非線形補正（α=0.7）→ 0〜1 に正規化\n"
                    "- **トピック確率**: 文とトピック説明の類似度を z-score → 適応温度 → "
                    "softmax → Top-kブースト\n"
                    "- **統合スコア**: 文×トピック = 感情値 × トピック確率 を、"
                    "レビュー→トピック→全体へ集計\n"
                    "- **感情スコア(表示)**: 各トピックを語るときの平均感情（50=中立）"
                )

    # ══════════════════════════════════════════════════════════════════════ #
    # 強み・弱み分析
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "score":
        st.markdown(
            '<div class="vb-step">詳細分析</div>'
            '<h1 class="vb-h1">強み・弱み分析</h1>',
            unsafe_allow_html=True,
        )

        mat = analysis.score_matrix(conn)
        if mat.empty:
            mat = analysis.google_matrix(conn)

        if mat.empty:
            st.info("スコアデータがありません。「📥 データ取り込み」でExcelを登録してください。")
            st.stop()

        all_names = list(mat.index)
        target_name = st.selectbox(
            "対象施設", all_names,
            index=all_names.index(st.session_state["analysis_target"])
            if st.session_state.get("analysis_target") in all_names else 0,
        )
        st.session_state["analysis_target"] = target_name

        with st.expander("全施設スコア一覧（ヒートマップ）", expanded=False):
            st.plotly_chart(charts.score_heatmap(mat), width="stretch")

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
                    width="stretch", key=f"radar_{key}",
                )
            with col_r:
                st.subheader("差分バーチャート")
                st.plotly_chart(
                    charts.diff_bar(result.diff, result.target_label, result.baseline_label),
                    width="stretch", key=f"bar_{key}",
                )
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**💪 強み TOP5**")
                if not strengths.empty:
                    st.dataframe(strengths, width="stretch", hide_index=True)
                else:
                    st.caption("なし")
            with c2:
                st.markdown("**⚠️ 弱み TOP5**")
                if not weaknesses.empty:
                    st.dataframe(weaknesses, width="stretch", hide_index=True)
                else:
                    st.caption("なし")
            with st.expander("数値詳細", expanded=False):
                detail = pd.DataFrame({
                    "対象": result.target.round(1),
                    "比較基準": result.baseline.round(1),
                    "差": result.diff.round(1),
                })
                detail.index.name = "指標"
                st.dataframe(detail, width="stretch")

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
                _render(
                    analysis.build_comparison(conn, target_name, "specific",
                                              specific_name=specific), "c"
                )

    # ══════════════════════════════════════════════════════════════════════ #
    # テキスト分析 & インサイト
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "text":
        st.markdown(
            '<div class="vb-step">詳細分析</div>'
            '<h1 class="vb-h1">テキスト分析 & インサイト</h1>',
            unsafe_allow_html=True,
        )

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
        st.session_state["analysis_target"] = target_name

        st.subheader("テキスト分析")
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
                    fig = px.bar(
                        profile.tfidf_keywords.head(20), x="スコア", y="単語",
                        orientation="h", color="スコア",
                        color_continuous_scale=[[0, "#D9E8F0"], [1, ACCENT]],
                        height=500,
                    )
                    fig.update_layout(
                        yaxis=dict(autorange="reversed"),
                        coloraxis_showscale=False,
                        margin=dict(t=10, b=10),
                        plot_bgcolor="#F7F7F4",
                        paper_bgcolor="#F7F7F4",
                    )
                    st.plotly_chart(fig, width="stretch")
            with col2:
                st.markdown("**頻出フレーズ（バイグラム）**")
                if not profile.bigrams.empty:
                    fig2 = px.bar(
                        profile.bigrams.head(20), x="件数", y="フレーズ",
                        orientation="h", color="件数",
                        color_continuous_scale=[[0, "#D5EBE2"], [1, "#4F8A6B"]],
                        height=500,
                    )
                    fig2.update_layout(
                        yaxis=dict(autorange="reversed"),
                        coloraxis_showscale=False,
                        margin=dict(t=10, b=10),
                        plot_bgcolor="#F7F7F4",
                        paper_bgcolor="#F7F7F4",
                    )
                    st.plotly_chart(fig2, width="stretch")
                else:
                    st.info("フレーズ抽出には口コミ件数がもう少し必要です。")

            with st.expander("トライグラム TOP20", expanded=False):
                if not profile.trigrams.empty:
                    st.dataframe(profile.trigrams, width="stretch", hide_index=True)
                else:
                    st.info("なし")

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
        st.subheader("LLMインサイト")

        comp_res = (
            analysis.build_comparison(conn, target_name, "comparison_avg")
            or analysis.build_comparison(conn, target_name, "all_avg")
        )
        if comp_res:
            st.caption(f"スコア比較軸: {comp_res.baseline_label}")

        api_key = llm.get_api_key()
        if not api_key:
            st.info("Gemini API キー未設定。aistudio.google.com で無料取得できます。")
            api_key = st.text_input("Gemini API キー（セッション限り）", type="password")

        if not profile.empty:
            if st.button("✨ インサイトを生成する", type="primary", disabled=not api_key):
                kw = profile.tfidf_keywords["単語"].tolist()
                bi = (
                    profile.bigrams["フレーズ"].tolist()
                    if not profile.bigrams.empty else []
                )
                prompt = llm.build_prompt(
                    target_name,
                    comp_res.diff if comp_res else None,
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

    # ══════════════════════════════════════════════════════════════════════ #
    # レポート出力
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "report":
        st.markdown(
            '<div class="vb-step">詳細分析</div>'
            '<h1 class="vb-h1">レポート出力 (PPTX)</h1>',
            unsafe_allow_html=True,
        )
        st.caption("分析結果を PowerPoint にまとめてダウンロードします。")

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
            axis_label = st.radio(
                "比較基準", ["比較施設の平均", "全体（DB内）の平均"], horizontal=True
            )
        axis = "comparison_avg" if axis_label == "比較施設の平均" else "all_avg"

        insights = None
        if st.session_state.get("insights_facility") == target_name:
            insights = st.session_state.get("insights")
            st.success("生成済みインサイトをレポートに含めます。")
        else:
            st.info("「💬 テキスト分析」でインサイトを生成するとレポートに反映されます。")

        if st.button("📑 レポート(PPTX)を生成", type="primary"):
            with st.spinner("スライドを生成中…"):
                tmp = Path(tempfile.mkdtemp()) / f"VoiceBaum_{target_name}.pptx"
                report.build_report(conn, target_name, axis=axis, insights=insights, output_path=tmp)
            with open(tmp, "rb") as f:
                st.download_button(
                    "⬇️ ダウンロード", data=f.read(),
                    file_name=tmp.name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    type="primary",
                )
            st.success("生成完了。上のボタンからダウンロードしてください。")

    # ══════════════════════════════════════════════════════════════════════ #
    # CSVプロファイラ
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "profiler":
        st.markdown(
            '<div class="vb-step">ツール</div>'
            '<h1 class="vb-h1">CSVプロファイラ</h1>',
            unsafe_allow_html=True,
        )
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
                st.dataframe(_pf_df.head(20), width="stretch")

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

            st.subheader("Claude用プロンプト")
            st.caption(
                "以下のテキストをコピーして Claude（claude.ai など）に貼り付けてください。"
            )
            st.code(_pf_prompt, language="markdown")

    # ══════════════════════════════════════════════════════════════════════ #
    # KAIZODE連携（発注・状況確認・DB取り込み）※ログイン後のみ到達
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "kaizode":
        st.markdown(
            '<div class="vb-step">連携</div>'
            '<h1 class="vb-h1">KAIZODE連携</h1>',
            unsafe_allow_html=True,
        )
        st.caption(
            "KAIZODEにレビュー収集を発注し、解析完了分をDBへ取り込みます。"
            "レート制限（20リクエスト/分）には自動で対応します。"
        )

        # ── APIキーの解決（secrets/環境変数を推奨。無ければセッション限りの入力）─ #
        _kz_key = os.environ.get("KAIZODE_API_KEY", "")
        _key_src = "secrets/環境変数"
        if not _kz_key:
            try:
                _kz_key = st.secrets.get("KAIZODE_API_KEY", "")
            except Exception:
                _kz_key = ""
        if not _kz_key:
            _kz_key = st.session_state.get("kz_session_key", "")
            _key_src = "セッション入力"

        if not _kz_key:
            st.info(
                "KAIZODE APIキーが未設定です。恒久利用は secrets の `KAIZODE_API_KEY` を推奨。"
                "下で入力した場合は**このセッション限り**で使用し、DBやファイルには保存しません。"
            )
            _kz_in = st.text_input(
                "KAIZODE APIキー（セッション限り）", type="password", key="kz_key_input",
            )
            if st.button("このセッションで使用する", type="primary", key="kz_key_use"):
                if _kz_in.strip():
                    st.session_state["kz_session_key"] = _kz_in.strip()
                    st.rerun()
                else:
                    st.warning("APIキーを入力してください。")
            st.stop()

        _kc1, _kc2 = st.columns([3, 1])
        with _kc1:
            st.caption(f"🔑 APIキー: 設定済み（{_key_src}・末尾 …{_kz_key[-4:]}）")
        with _kc2:
            if _key_src == "セッション入力":
                if st.button("🔒 キーを破棄", key="kz_key_clear", width="stretch"):
                    st.session_state.pop("kz_session_key", None)
                    st.rerun()

        _kz_client = kaizode.KaizodeClient(api_key=_kz_key)
        tab_kst, tab_knew, tab_ksync = st.tabs(
            ["📋 収集状況", "🛒 収集を発注", "⬇️ DBへ取り込み"]
        )

        # ── 収集状況 ────────────────────────────────────────────────── #
        with tab_kst:
            if st.button("🔄 最新の状況を取得", key="kz_refresh"):
                st.session_state.pop("kz_datasets", None)
            if "kz_datasets" not in st.session_state:
                with st.spinner("KAIZODEに問い合わせ中…"):
                    try:
                        st.session_state["kz_datasets"] = _kz_client.list_datasets()
                    except kaizode.KaizodeError as _e:
                        st.error(str(_e))
                        st.stop()
            _kz_dss = st.session_state.get("kz_datasets") or []
            if not _kz_dss:
                st.info("データセットがまだありません。「🛒 収集を発注」から作成してください。")
            else:
                st.dataframe(
                    pd.DataFrame([
                        {
                            "データセット": d.get("dataset_name", ""),
                            "状態": kaizode.STATUS_LABELS.get(d.get("status"), d.get("status")),
                            "定期": "✓" if d.get("is_scheduled") else "",
                            "更新": str(d.get("updated_at", ""))[:19],
                            "ID": d.get("dataset_id", ""),
                        }
                        for d in _kz_dss
                    ]),
                    width="stretch", hide_index=True,
                )
                st.caption("収集はKAIZODE側で非同期に進みます。「解析完了」になったら取り込めます。")

        # ── 収集を発注 ──────────────────────────────────────────────── #
        with tab_knew:
            st.caption("1行1施設で「施設名,レビューURL[,取得開始日]」を入力してください。")
            _kz_name = st.text_input("データセット名", value="口コミ対象", key="kz_ds_name")
            _kz_lines = st.text_area(
                "施設リスト", height=170, key="kz_lines",
                placeholder="容器文化ミュージアム,https://www.google.com/maps/...,2024-01-01\nトヨタ博物館,https://www.google.com/maps/...",
            )
            if st.button("🛒 収集を発注する", type="primary", key="kz_create"):
                _urls = []
                for _ln in _kz_lines.splitlines():
                    _parts = [p.strip() for p in _ln.split(",")]
                    if len(_parts) >= 2 and _parts[1]:
                        _item = {"url": _parts[1],
                                 "review_target_name": _parts[0] or None}
                        if len(_parts) >= 3 and _parts[2]:
                            _item["since"] = _parts[2]
                        _urls.append(_item)
                if not _urls:
                    st.warning("1件も読み取れませんでした。「施設名,URL」の形式で入力してください。")
                else:
                    try:
                        with st.spinner("データセットを作成中…"):
                            _ds = _kz_client.create_dataset(
                                _kz_name.strip() or "口コミ対象", _urls
                            )
                        st.success(
                            f"✅ {len(_urls)} 施設で発注しました"
                            f"（dataset_id: {_ds.get('dataset_id')}）。"
                            "収集完了後に「⬇️ DBへ取り込み」を実行してください。"
                        )
                        st.session_state.pop("kz_datasets", None)
                    except kaizode.KaizodeError as _e:
                        st.error(str(_e))

        # ── DBへ取り込み ────────────────────────────────────────────── #
        with tab_ksync:
            _sc1, _sc2 = st.columns(2)
            with _sc1:
                _kz_cat = st.text_input(
                    "category（任意）", key="kz_cat", placeholder="例: 企業ミュージアム",
                )
            with _sc2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                _kz_full = st.checkbox("全件取り直し（通常は差分）", key="kz_full")
            if st.button("⬇️ 解析完了分をDBへ取り込む", type="primary", key="kz_sync"):
                _logbox = st.container(height=260)
                try:
                    with st.spinner("同期中…（件数により数分かかります）"):
                        _res = kaizode.sync_datasets(
                            _kz_client, conn,
                            category=(_kz_cat.strip() or None),
                            full=_kz_full, log=_logbox.write,
                        )
                    st.success(
                        f"✅ 完了: 新規 {_res['inserted']:,} 件 / "
                        f"重複 {_res['skipped_dup']:,} 件 / "
                        f"{_res['datasets_synced']} データセット"
                    )
                    _topic_matrix_cached.clear()
                except kaizode.KaizodeError as _e:
                    st.error(str(_e))
            st.caption(
                "差分取得: 前回取り込み以降のレビューだけをDLします（重複は自動スキップ）。"
            )

    # ══════════════════════════════════════════════════════════════════════ #
    # 連携設定
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "integration":
        st.markdown(
            '<div class="vb-step">ツール</div>'
            '<h1 class="vb-h1">連携設定</h1>',
            unsafe_allow_html=True,
        )

        # DB connection status
        _turso_url = os.environ.get("TURSO_URL")
        if not _turso_url:
            try:
                _turso_url = st.secrets.get("TURSO_URL", None)
            except Exception:
                _turso_url = None

        if _turso_url:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;padding:16px 18px;
                        background:#fff;border:1px solid #E9E8E2;border-radius:12px;
                        margin-bottom:16px;">
              <div style="width:10px;height:10px;border-radius:50%;background:#4F8A6B;"></div>
              <div>
                <div style="font-weight:700;color:#16202B;">Turso (libSQL) — 接続済み</div>
                <div style="font-size:12px;color:#8A9098;margin-top:2px;">{_turso_url}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;padding:16px 18px;
                        background:#fff;border:1px solid #E9E8E2;border-radius:12px;
                        margin-bottom:16px;">
              <div style="width:10px;height:10px;border-radius:50%;background:#C9A24B;"></div>
              <div>
                <div style="font-weight:700;color:#16202B;">SQLite（ローカル）</div>
                <div style="font-size:12px;color:#8A9098;margin-top:2px;">
                  Turso 未設定 — ローカルの data/reviews.db を使用中
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        tab_schema, tab_guide = st.tabs(["📋 テーブルスキーマ", "📖 接続ガイド"])

        with tab_schema:
            st.code("""-- 施設マスタ
CREATE TABLE facility (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  name            TEXT NOT NULL UNIQUE,
  type            TEXT,                    -- 'target' | 'comparison'
  category        TEXT,
  general_rating  REAL,
  total_reviews   INTEGER
);

-- 口コミ本文
CREATE TABLE review (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  facility_id INTEGER REFERENCES facility(id),
  review_id   TEXT,
  review_date TEXT,
  rating      REAL,
  text        TEXT,
  source      TEXT,
  author      TEXT
);

-- Google観点別スコア（Rooms/Service/...）
CREATE TABLE review_subscore (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  review_db_id INTEGER REFERENCES review(id),
  axis        TEXT,
  value       REAL
);

-- 定量化指標（Excel取り込み / 自動算出）
CREATE TABLE score (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  facility_id  INTEGER REFERENCES facility(id),
  metric_name  TEXT,
  value        REAL,
  scale        REAL DEFAULT 5.0
);""", language="sql")

        with tab_guide:
            st.markdown("""
### Turso への接続設定

1. [turso.tech](https://turso.tech) でアカウントを作成
2. データベースを作成し、DB URL と Auth Token を取得
3. 以下のいずれかで設定:

**Streamlit Cloud の場合** (`.streamlit/secrets.toml`):
```toml
TURSO_URL = "libsql://your-db-xxx.turso.io"
TURSO_TOKEN = "eyJh..."
```

**ローカルの場合** (環境変数):
```bash
export TURSO_URL="libsql://your-db-xxx.turso.io"
export TURSO_TOKEN="eyJh..."
```

**Gemini API キー** (LLMインサイト機能):
```toml
GEMINI_API_KEY = "AIza..."
```
""")

            st.info(
                "Turso 未設定の場合はローカルの `data/reviews.db` を使用します。"
                "データはサーバー再起動で消えるためクラウドDBの設定を推奨します。"
            )

    elif _page == "account":
        st.markdown(
            '<div class="vb-step">ツール</div>'
            '<h1 class="vb-h1">アカウント</h1>',
            unsafe_allow_html=True,
        )

        _me = st.session_state.get("admin_email") or "—"
        _gate_signup = bool(auth.signup_code())
        _gate_master = bool(auth.admin_password())
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:16px 18px;
                    background:#fff;border:1px solid #E9E8E2;border-radius:12px;
                    margin-bottom:16px;">
          <div style="width:10px;height:10px;border-radius:50%;background:#4F8A6B;"></div>
          <div>
            <div style="font-weight:700;color:#16202B;">ログイン中: {escape(str(_me))}</div>
            <div style="font-size:12px;color:#8A9098;margin-top:2px;">
              招待コード(SIGNUP_CODE): {"設定済み ✅" if _gate_signup else "未設定 —（新規登録は無効）"}
              ／ 非常口(ADMIN_PASSWORD): {"設定済み ✅" if _gate_master else "未設定 —"}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        tab_users, tab_add, tab_pw = st.tabs(
            ["👥 ユーザー一覧", "➕ ユーザー追加", "🔑 自分のパスワード変更"]
        )

        # ── ユーザー一覧 ─────────────────────────────────────────────── #
        with tab_users:
            try:
                _users = auth.list_users(conn)
            except Exception as _e:
                _users = []
                st.error(f"ユーザー一覧を取得できませんでした: {_e}")
            if not _users:
                st.caption("登録済みアカウントはまだありません。"
                           "（非常口パスワードでログイン中の可能性があります）")
            else:
                st.caption(f"{len(_users)} 件のアカウント")
                for _u in _users:
                    _uc1, _uc2, _uc3 = st.columns([3, 2, 1])
                    with _uc1:
                        st.markdown(
                            f"<div style='padding:8px 0;font-weight:600;color:#16202B;'>"
                            f"{escape(_u['email'])}</div>",
                            unsafe_allow_html=True,
                        )
                    with _uc2:
                        st.markdown(
                            f"<div style='padding:8px 0;font-size:12px;color:#8A9098;'>"
                            f"{escape(str(_u.get('created_at') or ''))[:10]}</div>",
                            unsafe_allow_html=True,
                        )
                    with _uc3:
                        _is_self = (auth.normalize_email(str(_me)) == _u["email"])
                        if st.button("削除", key=f"deluser_{_u['email']}",
                                     width="stretch", disabled=_is_self,
                                     help="ログイン中の自分は削除できません" if _is_self else None):
                            auth.delete_user(conn, _u["email"])
                            st.toast(f"{_u['email']} を削除しました。", icon="🗑️")
                            st.rerun()

        # ── ユーザー追加（ログイン済み管理者が招待コード無しで追加）──── #
        with tab_add:
            st.caption("ログイン中の管理者は、招待コードなしで新しいアカウントを追加できます。")
            with st.form("account_add_user"):
                _nem = st.text_input("メールアドレス", key="acc_add_email")
                _npw = st.text_input("パスワード（8文字以上）", type="password",
                                     key="acc_add_pw")
                _add = st.form_submit_button("➕ 追加", type="primary")
            if _add:
                try:
                    auth.create_user(conn, _nem, _npw)
                    st.success(f"{auth.normalize_email(_nem)} を追加しました。")
                    st.rerun()
                except auth.AuthError as _e:
                    st.error(str(_e))
                except Exception as _e:
                    st.error(f"追加に失敗しました: {_e}")

        # ── 自分のパスワード変更 ─────────────────────────────────────── #
        with tab_pw:
            _me_norm = auth.normalize_email(str(_me))
            _is_account = bool(_me_norm) and auth.user_exists(conn, _me_norm)
            if not _is_account:
                st.info("非常口パスワードでログイン中のため、ここでは変更できません。"
                        "アカウントを作成するとパスワードを管理できます。")
            else:
                with st.form("account_change_pw"):
                    _cur = st.text_input("現在のパスワード", type="password", key="acc_cur_pw")
                    _new1 = st.text_input("新しいパスワード（8文字以上）", type="password",
                                          key="acc_new_pw1")
                    _new2 = st.text_input("新しいパスワード（確認）", type="password",
                                          key="acc_new_pw2")
                    _chg = st.form_submit_button("🔑 変更", type="primary")
                if _chg:
                    if not auth.authenticate(conn, _me_norm, _cur):
                        time.sleep(1)
                        st.error("現在のパスワードが違います。")
                    elif _new1 != _new2:
                        st.error("新しいパスワード（確認）が一致しません。")
                    else:
                        try:
                            auth.set_password(conn, _me_norm, _new1)
                            st.success("パスワードを変更しました。")
                        except auth.AuthError as _e:
                            st.error(str(_e))
