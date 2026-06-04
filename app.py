"""口コミ分析アプリ — 取り込み層 (steps 1-4).

    streamlit run app.py

Three screens:
  1. 口コミCSV取り込み   (step 1-3)
  2. スコアExcel取り込み (step 4)
  3. 取り込み状況         (DB の中身確認)
Steps 5-9 (グラフ / 強み弱み / TF-IDF / LLM / パワポ) come later.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import config, db, review_csv, score_excel

st.set_page_config(page_title="口コミ分析 — 取り込み", page_icon="📊", layout="wide")


@st.cache_resource
def _conn():
    conn = db.get_conn()
    db.init_db(conn)
    return conn


conn = _conn()

st.sidebar.title("📊 口コミ分析")
page = st.sidebar.radio(
    "メニュー",
    ["① 口コミCSV取り込み", "② スコアExcel取り込み", "③ 取り込み状況"],
)
st.sidebar.caption("取り込み層 (steps 1–4)。グラフ/分析は次フェーズ。")


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
        except Exception as e:  # noqa: BLE001 - surface parse errors to the user
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
                    "日付": r.review_date[:10],
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
            st.caption(
                "※ 施設名は①で手入力した名前と完全一致で紐付きます（無ければ新規作成）。"
            )
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
else:
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
