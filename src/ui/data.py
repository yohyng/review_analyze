"""Cached data-access layer for the VoiceBAUM UI.

Wraps the single DB connection (one cached resource) and the heavier
per-facility queries / computations behind @st.cache_data so Streamlit reruns
stay cheap. Every helper fetches the shared connection via get_conn().
"""
from __future__ import annotations

import io

import streamlit as st

from src import analysis, db, review_csv, topic_score


@st.cache_resource
def get_conn():
    """The single app-wide DB connection (Turso or local SQLite), initialised."""
    c = db.get_conn()
    db.init_db(c)
    return c


def all_facility_names() -> list[str]:
    return analysis.facility_names(get_conn())


def review_counts() -> dict[str, int]:
    """name -> review count (single query, for search suggestions)."""
    rows = get_conn().execute(
        """SELECT f.name, COUNT(r.id) FROM facility f
           LEFT JOIN review r ON r.facility_id = f.id
           GROUP BY f.id""",
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def facility_meta() -> dict[str, str]:
    """name -> sub-line (category, else review count) for the search dropdown."""
    rows = get_conn().execute(
        """SELECT f.name, f.category, COUNT(r.id) FROM facility f
           LEFT JOIN review r ON r.facility_id = f.id GROUP BY f.id""",
    ).fetchall()
    out = {}
    for name, cat, cnt in rows:
        out[name] = cat if cat else (f"口コミ {cnt}件" if cnt else "口コミ未登録")
    return out


def topic_sig() -> tuple:
    """Data signature so the topic-matrix cache invalidates when reviews change."""
    rows = get_conn().execute(
        """SELECT f.name, COUNT(r.id) FROM facility f
           LEFT JOIN review r ON r.facility_id = f.id GROUP BY f.id""",
    ).fetchall()
    return tuple(sorted((r[0], r[1]) for r in rows))


@st.cache_data(show_spinner=False)
def topic_matrix_cached(sig):
    """{facility: TopicScoreResult} for all facilities (heavy → cached by data sig)."""
    conn = get_conn()
    names = analysis.facility_names(conn)
    return topic_score.facility_topic_matrix(conn, names)


@st.cache_data(show_spinner=False)
def photo_from_db(fid: int, sig):
    """(bytes, mime) or None — cached BLOB fetch (sig=updated_at invalidates)."""
    d = db.get_photo(get_conn(), fid)
    return (d["image"], d["mime"]) if d else None


@st.cache_data(show_spinner=False)
def infer_facilities_cached(file_bytes: bytes):
    """施設推定はファイル全体を再解析するため重い。チェック操作のたびに走ると
    大きなCSVでプロセスが落ちる → ファイル内容でキャッシュ（返り値は小さいサマリ）。"""
    return review_csv.infer_facilities(io.BytesIO(file_bytes))


@st.cache_data(show_spinner=False, max_entries=8)
def parse_reviews_cached(file_bytes: bytes, facility_key):
    """単一施設プレビューの再解析（テキスト入力の再実行ごと）を防ぐためキャッシュ。
    max_entries でメモリを抑制。複数施設の保存ループでは使わない（1件ずつ処理）。"""
    return review_csv.parse_reviews(io.BytesIO(file_bytes), facility_key=facility_key)
