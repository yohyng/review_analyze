"""Plotly figure builders for steps 5-6.

All inputs are pd.Series of normalised 0-100 values.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

_GREEN = "#2ecc71"
_RED = "#e74c3c"
_BLUE = "#2980b9"
_ORANGE = "#e67e22"


def radar(
    target: pd.Series,
    baseline: pd.Series,
    target_label: str,
    baseline_label: str,
) -> go.Figure:
    cats = list(target.index.union(baseline.index))
    # plotly radar requires the first/last point to be the same to close the shape
    cats_closed = cats + [cats[0]]

    def _vals(s: pd.Series) -> list:
        return [s.get(c) for c in cats_closed]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=_vals(target),
            theta=cats_closed,
            fill="toself",
            name=target_label,
            line=dict(color=_BLUE, width=2),
            fillcolor=f"rgba(41,128,185,0.15)",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=_vals(baseline),
            theta=cats_closed,
            fill="toself",
            name=baseline_label,
            line=dict(color=_ORANGE, width=2, dash="dash"),
            fillcolor=f"rgba(230,126,34,0.10)",
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], ticksuffix="pt"),
        ),
        legend=dict(orientation="h", y=-0.1),
        height=460,
        margin=dict(t=30, b=60),
    )
    return fig


def diff_bar(diff: pd.Series, target_label: str, baseline_label: str) -> go.Figure:
    colors = [_GREEN if v >= 0 else _RED for v in diff.values]
    texts = [f"{v:+.1f}pt" for v in diff.values]
    fig = go.Figure(
        go.Bar(
            x=diff.index,
            y=diff.values,
            marker_color=colors,
            text=texts,
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.add_hline(y=0, line_width=1.5, line_color="black")
    # colour-coded legend patches via shapes
    max_abs = max(abs(diff.values.max()), abs(diff.values.min()), 1)
    fig.update_layout(
        title=dict(text=f"{target_label} vs {baseline_label}", font_size=13),
        yaxis=dict(
            title="差（対象−比較 / pt）",
            range=[-(max_abs * 1.4), max_abs * 1.4],
            zeroline=False,
        ),
        xaxis_title="指標",
        height=360,
        margin=dict(t=50, b=10),
        showlegend=False,
    )
    return fig


def score_heatmap(matrix: pd.DataFrame) -> go.Figure:
    """Show all facilities × metrics as a colour-coded heatmap (0-100 scale)."""
    if matrix.empty:
        return go.Figure()
    fig = go.Figure(
        go.Heatmap(
            z=matrix.values,
            x=list(matrix.columns),
            y=list(matrix.index),
            colorscale="RdYlGn",
            zmin=0,
            zmax=100,
            text=[[f"{v:.0f}" for v in row] for row in matrix.values],
            texttemplate="%{text}",
            hovertemplate="施設: %{y}<br>指標: %{x}<br>スコア: %{z:.1f}pt<extra></extra>",
        )
    )
    fig.update_layout(
        height=max(200, 80 + 50 * len(matrix)),
        margin=dict(t=20, b=10),
        xaxis=dict(side="top"),
    )
    return fig
