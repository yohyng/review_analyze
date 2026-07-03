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

# VoiceBAUM accent (magenta) + sentiment palette
_ACCENT = "#B0338A"
_POS = "#4F8A6B"
_NEU = "#C9C3B6"
_NEG = "#C66B61"


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


def _sentiment_color(v100: float) -> str:
    """0-100 の感情スコア → ポジ/中立/ネガの色。"""
    if v100 >= 60:
        return _POS
    if v100 <= 40:
        return _NEG
    return _NEU


def topic_score_bar(result) -> go.Figure:
    """独自指標（感情・トピック統合スコア）のトピック別グラフ。

    横棒 = トピック別の感情スコア(0-100, 50=中立)。棒色はポジ/中立/ネガ。
    ラベルに言及度(%)を併記し、「何がどれだけ語られ、どう評価されているか」を可視化。
    result: topic_score.TopicScoreResult
    """
    topics = result.sorted_by_sentiment(reverse=False)  # 下から上に良い順
    names = [t.name for t in topics]
    sent = [t.sentiment_100 for t in topics]
    sal = [t.salience_pct for t in topics]
    colors = [_sentiment_color(v) for v in sent]
    texts = [f"{v:.0f}（言及 {s:.0f}%）" for v, s in zip(sent, sal)]

    fig = go.Figure(
        go.Bar(
            x=sent,
            y=names,
            orientation="h",
            marker_color=colors,
            text=texts,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "%{y}<br>感情スコア: %{x:.1f}/100"
                "<br>言及度: %{customdata:.1f}%<extra></extra>"
            ),
            customdata=sal,
        )
    )
    # 中立ライン
    fig.add_vline(x=50, line_width=1.5, line_dash="dash", line_color="#8A9098")
    fig.update_layout(
        xaxis=dict(title="トピック別 感情スコア（0-100 / 50=中立）", range=[0, 108]),
        yaxis=dict(title=""),
        height=max(320, 70 + 46 * len(names)),
        margin=dict(t=20, b=40, l=10, r=10),
        plot_bgcolor="#F7F7F4",
        paper_bgcolor="#F7F7F4",
        showlegend=False,
        font=dict(family="Manrope, 'Noto Sans JP', sans-serif"),
    )
    return fig


def topic_matrix_bar(
    names: list[str],
    values: list[float],
    target_label: str = "対象施設",
    overall_value: float | None = None,
) -> go.Figure:
    """SLIDE 02: 23観点（22トピック＋全体）の縦棒。感情スコア 0-100。"""
    xs = list(names)
    ys = list(values)
    if overall_value is not None:
        xs = xs + ["全体"]
        ys = ys + [overall_value]
    fig = go.Figure(
        go.Bar(
            x=xs, y=ys, marker_color=_ACCENT,
            hovertemplate="%{x}<br>感情スコア %{y:.1f}<extra></extra>",
        )
    )
    # Y軸は正の画像に合わせて 0-120（目盛20刻み）
    fig.update_layout(
        yaxis=dict(title="", range=[0, 120], dtick=20, tickformat=".2f",
                   gridcolor="#ECEBE5", zeroline=False),
        xaxis=dict(tickangle=-90, tickfont=dict(size=11)),
        height=460,
        margin=dict(t=10, b=150, l=10, r=10),
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        showlegend=False,
        bargap=0.45,
        font=dict(family="Manrope, 'Noto Sans JP', sans-serif", size=11),
    )
    return fig


def topic_salience_bar(result) -> go.Figure:
    """トピック別の言及度（どれだけ語られているか）を降順で。"""
    topics = sorted(result.topics, key=lambda t: t.salience, reverse=True)
    names = [t.name for t in topics]
    sal = [t.salience_pct for t in topics]
    fig = go.Figure(
        go.Bar(
            x=names, y=sal,
            marker_color=_ACCENT,
            text=[f"{s:.0f}%" for s in sal],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_layout(
        yaxis=dict(title="言及度 (%)"),
        height=320,
        margin=dict(t=20, b=60, l=10, r=10),
        plot_bgcolor="#F7F7F4",
        paper_bgcolor="#F7F7F4",
        showlegend=False,
        xaxis=dict(tickangle=-20),
        font=dict(family="Manrope, 'Noto Sans JP', sans-serif"),
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
