"""Step 4: flexible importer for the existing score Excel.

We don't hard-code the columns. The app reads whatever sheet is dropped in,
guesses which column holds the facility name and which columns are numeric
score axes, and lets the user confirm in the UI before saving.

Supports both layouts:
  * wide : 1 row = 1 facility, numeric columns are axes   (default)
  * long : columns like (facility, axis/metric, value)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class ColumnGuess:
    name_col: Optional[str]               # column holding the facility name
    numeric_cols: list[str] = field(default_factory=list)
    text_cols: list[str] = field(default_factory=list)
    suggested_scale: Optional[float] = None
    layout: str = "wide"                  # 'wide' | 'long'
    long_axis_col: Optional[str] = None
    long_value_col: Optional[str] = None


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def read_table(source, filename: str = "") -> pd.DataFrame:
    """Read .xlsx/.xls/.csv (path or file-like) into a DataFrame."""
    name = (filename or getattr(source, "name", "") or str(source)).lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(source, dtype=object)
    else:
        df = pd.read_csv(source, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    # drop fully-empty rows/cols
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df


# --------------------------------------------------------------------------- #
# column detection
# --------------------------------------------------------------------------- #
def _numeric_ratio(series: pd.Series) -> float:
    vals = series.dropna()
    if len(vals) == 0:
        return 0.0
    parsed = pd.to_numeric(vals, errors="coerce")
    return float(parsed.notna().mean())


def _suggest_scale(df: pd.DataFrame, numeric_cols: list[str]) -> Optional[float]:
    if not numeric_cols:
        return None
    mx = pd.to_numeric(
        df[numeric_cols].stack(), errors="coerce"
    ).max()
    if pd.isna(mx):
        return None
    for cap in (5, 10, 100):
        if mx <= cap:
            return float(cap)
    return float(mx)


_LONG_AXIS_HINTS = {"axis", "metric", "指標", "軸", "項目", "category", "カテゴリ"}
_LONG_VALUE_HINTS = {"value", "score", "スコア", "点", "値", "評点"}


def guess_columns(df: pd.DataFrame, numeric_threshold: float = 0.6) -> ColumnGuess:
    """Heuristically classify columns and detect wide vs long layout."""
    numeric_cols, text_cols = [], []
    for col in df.columns:
        if _numeric_ratio(df[col]) >= numeric_threshold:
            numeric_cols.append(col)
        else:
            text_cols.append(col)

    lower = {c: str(c).lower() for c in df.columns}

    # long-format detection: a text axis column + a single numeric value column
    axis_col = next((c for c in text_cols if lower[c] in _LONG_AXIS_HINTS), None)
    value_col = next((c for c in numeric_cols if lower[c] in _LONG_VALUE_HINTS), None)
    if axis_col and value_col and len(numeric_cols) == 1:
        name_col = next((c for c in text_cols if c != axis_col), None)
        return ColumnGuess(
            name_col=name_col,
            numeric_cols=numeric_cols,
            text_cols=text_cols,
            suggested_scale=_suggest_scale(df, numeric_cols),
            layout="long",
            long_axis_col=axis_col,
            long_value_col=value_col,
        )

    # wide format: first text column is the facility name
    name_col = text_cols[0] if text_cols else (df.columns[0] if len(df.columns) else None)
    axis_cols = [c for c in numeric_cols if c != name_col]
    return ColumnGuess(
        name_col=name_col,
        numeric_cols=axis_cols,
        text_cols=text_cols,
        suggested_scale=_suggest_scale(df, axis_cols),
        layout="wide",
    )


# --------------------------------------------------------------------------- #
# extraction  ->  {facility_name: {axis: value}}
# --------------------------------------------------------------------------- #
def extract_scores_wide(
    df: pd.DataFrame, name_col: str, axis_cols: list[str]
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for _, row in df.iterrows():
        name = row.get(name_col)
        if name is None or str(name).strip() == "":
            continue
        name = str(name).strip()
        axes: dict[str, float] = {}
        for col in axis_cols:
            v = pd.to_numeric(row.get(col), errors="coerce")
            if pd.notna(v):
                axes[str(col).strip()] = float(v)
        if axes:
            out[name] = axes
    return out


def extract_scores_long(
    df: pd.DataFrame, name_col: str, axis_col: str, value_col: str
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for _, row in df.iterrows():
        name = row.get(name_col)
        axis = row.get(axis_col)
        if not name or not axis:
            continue
        v = pd.to_numeric(row.get(value_col), errors="coerce")
        if pd.isna(v):
            continue
        out.setdefault(str(name).strip(), {})[str(axis).strip()] = float(v)
    return out
