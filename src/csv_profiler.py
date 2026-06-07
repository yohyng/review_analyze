"""CSV structure profiler — generates a Claude-ready context prompt.

Upload any CSV/TSV → get a Markdown summary of columns, types, stats,
and sample rows that you can paste directly into Claude (or any LLM).
"""
from __future__ import annotations

import io

import pandas as pd


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def _load_text(source) -> str:
    if hasattr(source, "read"):
        data = source.read()
    else:
        with open(source, "rb") as f:
            data = f.read()
    if isinstance(data, bytes):
        for enc in ("utf-8-sig", "utf-8", "cp932"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
    return data


def load_df(source) -> pd.DataFrame:
    """Read a CSV/TSV (path or file-like) into a raw DataFrame."""
    text = _load_text(source)
    header = text.split("\n", 1)[0]
    delim = "\t" if header.count("\t") >= header.count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=delim, dtype=str, keep_default_na=False)
    if df.shape[1] == 1 and delim != ",":
        df = pd.read_csv(io.StringIO(text), sep=",", dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    return df


# --------------------------------------------------------------------------- #
# Profiling
# --------------------------------------------------------------------------- #
def _col_stats(series: pd.Series, n_rows: int) -> dict:
    s = series.astype(str).str.strip()
    non_empty_mask = s != ""
    non_empty_n = int(non_empty_mask.sum())
    non_empty_pct = round(non_empty_n / n_rows * 100) if n_rows else 0
    unique = int(s.nunique())

    num = pd.to_numeric(s.replace("", pd.NA), errors="coerce")
    is_num = num.notna().sum() > max(n_rows * 0.3, 1)

    samples = s[non_empty_mask].head(3).tolist()

    info: dict = {
        "non_empty_n": non_empty_n,
        "non_empty_pct": non_empty_pct,
        "unique": unique,
        "is_num": is_num,
        "samples": samples,
    }
    if is_num and non_empty_n > 0:
        info["mean"] = round(float(num.mean()), 2)
        info["min"] = round(float(num.min()), 2)
        info["max"] = round(float(num.max()), 2)
    return info


# --------------------------------------------------------------------------- #
# Prompt generation
# --------------------------------------------------------------------------- #
def build_claude_prompt(
    df: pd.DataFrame,
    filename: str = "",
    question: str = "",
) -> str:
    """Return a Markdown string describing the CSV structure.

    Paste the output into Claude (or any LLM) to share data context
    without uploading the actual file.
    """
    n_rows, n_cols = len(df), len(df.columns)
    lines: list[str] = []

    # ── Intro ──
    lines.append("以下のCSVデータの構造を共有します。")
    if filename:
        lines.append(f"ファイル名: `{filename}`")
    lines.append("")

    # ── Overview ──
    lines.append("## 概要")
    lines.append(f"- 行数: {n_rows} 件")
    lines.append(f"- 列数: {n_cols} 列")
    lines.append("")

    # ── Column table ──
    lines.append("## 列一覧")
    lines.append("| # | 列名 | 型 | 非空率 | ユニーク数 | サンプル値（最大3件） |")
    lines.append("|---|------|----|--------|-----------|---------------------|")

    col_stats_list = []
    for i, col in enumerate(df.columns, 1):
        cs = _col_stats(df[col], n_rows)
        col_stats_list.append((col, cs))
        typ = "数値" if cs["is_num"] else "文字列"
        sample_parts = []
        for s in cs["samples"]:
            display = (s[:40] + "…") if len(s) > 40 else s
            sample_parts.append(f'"{display}"' if ("," in display or len(display) > 12) else display)
        sample_str = " / ".join(sample_parts) if sample_parts else "（空欄のみ）"
        lines.append(
            f"| {i} | `{col}` | {typ} | {cs['non_empty_pct']}% | {cs['unique']} | {sample_str} |"
        )
    lines.append("")

    # ── Numeric stats ──
    numeric = [(col, cs) for col, cs in col_stats_list if cs["is_num"] and "mean" in cs]
    if numeric:
        lines.append("## 数値列の統計")
        for col, cs in numeric:
            lines.append(
                f"- `{col}`: 平均 {cs['mean']} / 最小 {cs['min']} / 最大 {cs['max']}"
            )
        lines.append("")

    # ── Sample rows ──
    lines.append("## サンプルデータ（先頭3行）")
    for idx, (_, row) in enumerate(df.head(3).iterrows(), 1):
        lines.append(f"### 行{idx}")
        for col in df.columns:
            val = str(row[col]).strip()
            if val and val not in ("", "nan"):
                display = (val[:150] + "…") if len(val) > 150 else val
                lines.append(f"- **{col}**: {display}")
        lines.append("")

    # ── Closing ──
    lines.append("---")
    if question:
        lines.append(question)
    else:
        lines.append("このデータについて、以下の点を教えてください：\n（ここに質問を記入）")

    return "\n".join(lines)
