"""Steps 5-6: score analysis — comparison matrices, diff, TOP5.

All scores are normalised to 0-100 internally so Excel scales (5-pt, 100-pt…)
and Google sub-scores (1-5) can be compared on the same axis.

Public API
----------
score_matrix(conn)          facility_name × metric → normalised value (0-100)
google_matrix(conn)         facility_name × Google axis → normalised value (0-100)
review_rating_series(conn)  facility_name → normalised avg star rating (0-100)

build_comparison(conn, target_name, axis, specific_name)
    → ComparisonResult (target/baseline Series + diff + labels)

top_n(diff, n)  → (strengths_df, weaknesses_df)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd


# --------------------------------------------------------------------------- #
# Raw matrices
# --------------------------------------------------------------------------- #
def score_matrix(conn: sqlite3.Connection) -> pd.DataFrame:
    """Excel scores → normalised 0-100 DataFrame (facility_name × metric)."""
    rows = conn.execute("""
        SELECT f.name, s.metric_name, s.value, COALESCE(s.scale, 5) AS scale
        FROM score s
        JOIN facility f ON f.id = s.facility_id
        WHERE s.source = 'excel'
    """).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["施設名", "指標", "値", "scale"])
    df["norm"] = df["値"] / df["scale"] * 100
    pivot = df.pivot_table(index="施設名", columns="指標", values="norm", aggfunc="first")
    pivot.columns.name = None
    return pivot.round(2)


def google_matrix(conn: sqlite3.Connection) -> pd.DataFrame:
    """Google sub-scores → normalised 0-100 DataFrame (facility_name × axis)."""
    rows = conn.execute("""
        SELECT f.name, rs.axis, AVG(rs.value) AS avg_val
        FROM review_subscore rs
        JOIN review r ON r.id = rs.review_db_id
        JOIN facility f ON f.id = r.facility_id
        GROUP BY f.name, rs.axis
    """).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["施設名", "軸", "avg"])
    pivot = df.pivot_table(index="施設名", columns="軸", values="avg", aggfunc="first")
    pivot.columns.name = None
    return (pivot / 5 * 100).round(2)


def review_rating_series(conn: sqlite3.Connection) -> pd.Series:
    """Average star rating per facility → normalised 0-100."""
    rows = conn.execute("""
        SELECT f.name, AVG(r.rating) AS avg_r
        FROM review r
        JOIN facility f ON f.id = r.facility_id
        WHERE r.rating IS NOT NULL
        GROUP BY f.name
    """).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series(
        {row[0]: round(row[1] / 5 * 100, 2) for row in rows},
        name="口コミ評点",
    )


def facility_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM facility ORDER BY name").fetchall()
    return [r[0] for r in rows]


def facilities_by_type(conn: sqlite3.Connection, ftype: str) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM facility WHERE type = ? ORDER BY name", (ftype,)
    ).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# Comparison helper
# --------------------------------------------------------------------------- #
@dataclass
class ComparisonResult:
    target: pd.Series
    baseline: pd.Series
    diff: pd.Series
    target_label: str
    baseline_label: str
    metrics: list[str]


def _pick_matrix(conn: sqlite3.Connection) -> pd.DataFrame:
    """Excel scores first; fall back to Google sub-scores if empty."""
    mat = score_matrix(conn)
    if mat.empty:
        mat = google_matrix(conn)
    return mat


def build_comparison(
    conn: sqlite3.Connection,
    target_name: str,
    axis: str,
    specific_name: str | None = None,
) -> ComparisonResult | None:
    """
    axis:
      'comparison_avg'  — vs average of facilities with type='comparison'
      'all_avg'         — vs average of ALL facilities in DB
      'specific'        — vs one named facility (specific_name required)
    Returns None when there is not enough data to compute.
    """
    mat = _pick_matrix(conn)
    if mat.empty or target_name not in mat.index:
        return None

    target = mat.loc[target_name].dropna()

    if axis == "comparison_avg":
        peers = [n for n in facilities_by_type(conn, "comparison") if n in mat.index]
        if not peers:
            return None
        baseline = mat.loc[peers].mean().dropna()
        label = f"比較施設の平均（{len(peers)}施設）"

    elif axis == "all_avg":
        others = [n for n in mat.index if n != target_name]
        if not others:
            return None
        baseline = mat.loc[others].mean().dropna()
        label = f"全体平均（{len(others)}施設）"

    elif axis == "specific":
        if specific_name is None or specific_name not in mat.index:
            return None
        baseline = mat.loc[specific_name].dropna()
        label = specific_name

    else:
        return None

    common = target.index.intersection(baseline.index)
    if common.empty:
        return None

    diff = (target[common] - baseline[common]).sort_values(ascending=False)
    return ComparisonResult(
        target=target[common],
        baseline=baseline[common],
        diff=diff,
        target_label=target_name,
        baseline_label=label,
        metrics=list(common),
    )


# --------------------------------------------------------------------------- #
# TOP-N
# --------------------------------------------------------------------------- #
def top_n(
    diff: pd.Series, n: int = 5
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (strengths_df, weaknesses_df), each with 指標/差/評価 columns."""

    def _fmt(series: pd.Series, kind: str) -> pd.DataFrame:
        df = series.reset_index()
        df.columns = ["指標", "差（対象−比較）"]
        df["差（対象−比較）"] = df["差（対象−比較）"].round(1)
        df["評価"] = "💪 強み" if kind == "strength" else "⚠️ 弱み"
        return df

    strengths = _fmt(diff[diff >= 0].nlargest(n), "strength")
    weaknesses = _fmt(diff[diff < 0].nsmallest(n), "weakness")
    return strengths, weaknesses
