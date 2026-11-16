"""PPT v5 — 18枚固定のレポート。

原典: facility-review-analysis スキルの references/ppt-spec-v5.md。

    1 表紙              2 分析サマリー        3 市場ポジション
    4 競合比較ヒートマップ  5 競合・他施設比較    6 スコアレーダーチャート
    7 平均スコア分析      8 口コミインサイト     9 来場者適合分析
   10 NMSI詳述          11 VFFI詳述          12 適合度×満足度マップ
   13 感情・生理指標推定  14 KPI別戦略         15 優先改善項目
   16 戦略提案          17 最重要インサイト    18 レアクチコミ分析

原典が明示している制約をそのまま実装する。

  - **18枚固定・順番固定・タイトル固定。省略・統合・順番変更は禁止。**
  - **データが不足する場合も該当スライドを作成し、その旨を明記する。**
    → 作らない、ではなく「空で作る」。_no_data() がその面を描く。
  - **表の最小フォントは12pt。収まらなくても縮小しない。**
    → 縮小する代わりに行数を削る。削ったことは画面に残す（黙って切らない）。

既存の report.py（可変長・データがある分だけ出す）は残してある。
こちらは「毎回同じ18枚が出る」ことを保証する別経路。

### スライド13について
原典は感情・生理指標（Valence / Arousal / β/α / PNN50）の面を置くが、
**β/α は脳波比、PNN50 は心拍変動指標で、クチコミからは測定できない**。
原典自身も「名称を借りた非生理学的な代理推計であり、実測と誤認させない」
と断っている。本実装は推計値を作らず、13枚目は「測定していない」面として
出す。枚数を詰めて17枚にはしない（順番固定の指示に従う）。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pptx import Presentation
from pptx.util import Inches, Pt

from . import kpi as kpi_mod
from . import rare as rare_mod
from . import vffi as vffi_mod
from .report import (
    BLUE, GREY, LIGHT, MAGENTA, NAVY, SLIDE_H, SLIDE_W, WHITE,
    _blank, _bullets, _table, _textbox, _title_bar,
)

ACCENT = MAGENTA      # VoiceBAUM のアクセント色に合わせる
GRAY = GREY           # report.py は GREY 表記

# 原典の18枚。index+1 が仕様のスライド番号。
SPEC_TITLES: tuple[str, ...] = (
    "表紙", "分析サマリー", "市場ポジション", "競合比較ヒートマップ",
    "競合・他施設比較", "スコアレーダーチャート", "平均スコア分析",
    "口コミインサイト", "来場者適合分析", "NMSI詳述", "VFFI詳述",
    "適合度×満足度マップ", "感情・生理指標推定", "KPI別戦略",
    "優先改善項目", "戦略提案", "最重要インサイト", "レアクチコミ分析",
)

# 表の最小フォント。原典が 12pt を下限と定め、下回る自動縮小を禁じている。
MIN_TABLE_PT = 12

# 1枚に載せる表の最大行数。これを超えたら**縮小ではなく行を削る**。
MAX_TABLE_ROWS = 12

BODY = Inches(1.25)          # タイトルバーの下端
MARGIN = Inches(0.6)
CONTENT_W = SLIDE_W - MARGIN * 2


@dataclass
class Ctx:
    """18枚が参照するデータ。無いものは None のままでよい。"""
    target: str = ""
    conn: Any = None
    comp: Any = None                     # analysis.build_comparison
    profile: Any = None                  # text_analysis.TextProfile
    topic_score: Any = None              # topic_score.TopicScoreResult
    insights: Any = None                 # llm.InsightResult
    nmsi: Any = None                     # src.nmsi の結果
    vffi: Any = None                     # src.vffi.VFFIResult
    rares: list = field(default_factory=list)
    reviews: list = field(default_factory=list)   # [(rating, text), ...]
    baseline_label: str = ""
    notes: list = field(default_factory=list)     # 落とした行などの記録


# --------------------------------------------------------------------------- #
# 共通パーツ
# --------------------------------------------------------------------------- #
def _no_data(slide, reason: str, *, hint: str = "") -> None:
    """データ不足の面。**白紙にしない。** 何が無いのかを書く。

    原典「データが不足する場合も該当スライドを作成し、明記する」に対応。
    """
    _textbox(slide, MARGIN, Inches(2.8), CONTENT_W, Inches(1.0),
             "データ不足のため、この面は作成していません",
             size=20, bold=True, color=GRAY)
    _textbox(slide, MARGIN, Inches(3.7), CONTENT_W, Inches(1.6),
             reason, size=14, color=GRAY)
    if hint:
        _textbox(slide, MARGIN, Inches(4.9), CONTENT_W, Inches(1.2),
                 hint, size=13, color=BLUE)


def _fit_rows(rows: list, ctx: Ctx, where: str) -> list:
    """行数を上限で切る。**フォントを縮めない代わりに行を削る。**

    黙って切ると「全部載っている」と読まれるので、切ったことを notes に残し、
    呼び出し側が画面にも出す。
    """
    if len(rows) <= MAX_TABLE_ROWS:
        return rows
    ctx.notes.append(f"{where}: {len(rows)} 行中 {MAX_TABLE_ROWS} 行を表示")
    return rows[:MAX_TABLE_ROWS]


def _trimmed_note(slide, rows_all: int, shown: int) -> None:
    if rows_all > shown:
        _textbox(slide, MARGIN, SLIDE_H - Inches(0.75), CONTENT_W, Inches(0.4),
                 f"※ 全 {rows_all} 行のうち上位 {shown} 行を表示（12pt を下回る縮小はしません）",
                 size=11, color=GRAY)


# --------------------------------------------------------------------------- #
# 1 表紙
# --------------------------------------------------------------------------- #
def _s01_cover(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    bg = slide.shapes.add_shape(1, 0, 0, SLIDE_W, SLIDE_H)
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    _textbox(slide, MARGIN, Inches(2.6), CONTENT_W, Inches(1.4),
             ctx.target or "（施設名未設定）", size=40, bold=True, color=WHITE)
    _textbox(slide, MARGIN, Inches(4.0), CONTENT_W, Inches(0.8),
             "口コミ統合分析レポート", size=20, color=WHITE)
    sub = ctx.baseline_label or "（比較データなし）"
    _textbox(slide, MARGIN, Inches(4.8), CONTENT_W, Inches(0.6),
             f"比較基準: {sub}", size=14, color=LIGHT)


# --------------------------------------------------------------------------- #
# 2 分析サマリー
# --------------------------------------------------------------------------- #
def _s02_summary(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "分析サマリー")
    n = len(ctx.reviews)
    cards = [
        ("対象口コミ", f"{n:,} 件"),
        ("平均評価", _avg_rating(ctx)),
        ("比較基準", ctx.baseline_label or "—"),
    ]
    w = CONTENT_W / 3 - Inches(0.2)
    for i, (label, val) in enumerate(cards):
        left = MARGIN + (w + Inches(0.3)) * i
        _textbox(slide, left, BODY + Inches(0.2), w, Inches(0.4),
                 label, size=13, color=GRAY)
        _textbox(slide, left, BODY + Inches(0.6), w, Inches(0.8),
                 val, size=26, bold=True, color=NAVY)
    body = getattr(ctx.insights, "summary", "") or "（インサイト未生成）"
    _textbox(slide, MARGIN, Inches(3.2), CONTENT_W, Inches(3.2),
             body, size=14, color=NAVY)


def _avg_rating(ctx: Ctx) -> str:
    vals = [r for r, _t in ctx.reviews if r is not None]
    return f"★{sum(vals) / len(vals):.2f}" if vals else "—"


# --------------------------------------------------------------------------- #
# 3 市場ポジション / 4 ヒートマップ / 5 競合比較 / 6 レーダー / 7 平均スコア
# --------------------------------------------------------------------------- #
def _s03_market(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "市場ポジション")
    ts = ctx.topic_score
    if ts is None or getattr(ts, "empty", True):
        _no_data(slide, "トピックスコアが未算出です。",
                 hint="管理モードの「⚡分析の事前計算」で算出できます。")
        return
    _textbox(slide, MARGIN, BODY + Inches(0.2), CONTENT_W, Inches(0.8),
             f"総合スコア {ts.overall_100} / 100", size=28, bold=True, color=NAVY)
    rows = [(t.name, f"{t.sentiment_100:.1f}", f"{t.salience_pct:.1f}%")
            for t in sorted(ts.topics, key=lambda x: -x.salience)]
    shown = _fit_rows(rows, ctx, "市場ポジション")
    _table(slide, MARGIN, Inches(2.6), CONTENT_W, Inches(0.4),
           ["観点", "感情スコア", "言及度"], shown)
    _trimmed_note(slide, len(rows), len(shown))


def _s04_heatmap(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "競合比較ヒートマップ")
    comp = ctx.comp
    if comp is None or getattr(comp, "diff", None) is None:
        _no_data(slide, "比較対象の施設にスコアがありません。",
                 hint="比較施設を選び直すか、スコアを取り込んでください。")
        return
    rows = [(str(k), f"{v:+.2f}") for k, v in comp.diff.items()]
    shown = _fit_rows(rows, ctx, "ヒートマップ")
    _table(slide, MARGIN, BODY + Inches(0.3), CONTENT_W, Inches(0.4),
           ["評価軸", "競合平均との差"], shown,
           accent={"col": 1, "color": ACCENT})
    _trimmed_note(slide, len(rows), len(shown))


def _s05_competitors(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "競合・他施設比較")
    comp = ctx.comp
    if comp is None:
        _no_data(slide, "比較データがありません。")
        return
    _textbox(slide, MARGIN, BODY + Inches(0.2), CONTENT_W, Inches(0.6),
             f"比較基準: {ctx.baseline_label}", size=14, color=GRAY)
    rows = [(str(k), f"{v:+.2f}",
             "優位" if v > 0 else ("同水準" if abs(v) < 0.05 else "劣位"))
            for k, v in (comp.diff or {}).items()]
    shown = _fit_rows(rows, ctx, "競合比較")
    if not shown:
        _no_data(slide, "比較できる評価軸がありません。")
        return
    _table(slide, MARGIN, Inches(2.3), CONTENT_W, Inches(0.4),
           ["評価軸", "差分", "判定"], shown)
    _trimmed_note(slide, len(rows), len(shown))


def _s06_radar(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "スコアレーダーチャート")
    ts = ctx.topic_score
    if ts is None or getattr(ts, "empty", True):
        _no_data(slide, "トピックスコアが未算出のため、レーダーを描けません。")
        return
    from . import topic_score as _tsmod
    axes = [t for t in ts.topics if t.name in _tsmod.SPACE_TOPICS]
    if len(axes) < 3:
        _no_data(slide, f"レーダーに必要な軸が {len(axes)} 本しかありません（3本以上必要）。")
        return
    rows = [(t.name, f"{t.sentiment_100:.1f}") for t in axes]
    _textbox(slide, MARGIN, BODY + Inches(0.2), CONTENT_W, Inches(0.5),
             "空間・体験の10軸", size=16, bold=True, color=NAVY)
    _table(slide, MARGIN, Inches(2.0), CONTENT_W, Inches(0.4),
           ["評価軸", "スコア"], _fit_rows(rows, ctx, "レーダー"))


def _s07_avg_score(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "平均スコア分析")
    ts = ctx.topic_score
    if ts is None or getattr(ts, "empty", True):
        _no_data(slide, "トピックスコアが未算出です。")
        return
    rows = []
    for t in sorted(ts.topics, key=lambda x: -x.sentiment):
        kpis = kpi_mod.kpis_for(t.name) if hasattr(kpi_mod, "kpis_for") else []
        rows.append((t.name, f"{t.sentiment_100:.1f}", f"{t.salience_pct:.1f}%",
                     ", ".join(kpis[:2]) if kpis else "—"))
    shown = _fit_rows(rows, ctx, "平均スコア")
    _table(slide, MARGIN, BODY + Inches(0.3), CONTENT_W, Inches(0.4),
           ["トピック", "平均スコア", "言及度", "KPI影響"], shown)
    _trimmed_note(slide, len(rows), len(shown))


# --------------------------------------------------------------------------- #
# 8 口コミインサイト
# --------------------------------------------------------------------------- #
def _s08_insights(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "口コミインサイト")
    ins = ctx.insights
    strengths = list(getattr(ins, "strengths", None) or [])
    weaknesses = list(getattr(ins, "weaknesses", None) or [])
    if not strengths and not weaknesses:
        _no_data(slide, "インサイトが未生成です。",
                 hint="分析画面で生成すると反映されます。")
        return
    half = CONTENT_W / 2 - Inches(0.2)
    _textbox(slide, MARGIN, BODY + Inches(0.2), half, Inches(0.5),
             "ポジティブな声", size=16, bold=True, color=BLUE)
    _bullets(slide, MARGIN, BODY + Inches(0.8), half, Inches(4.0),
             strengths[:6] or ["—"])
    right = MARGIN + half + Inches(0.4)
    _textbox(slide, right, BODY + Inches(0.2), half, Inches(0.5),
             "ネガティブな声", size=16, bold=True, color=ACCENT)
    _bullets(slide, right, BODY + Inches(0.8), half, Inches(4.0),
             weaknesses[:6] or ["—"])


# --------------------------------------------------------------------------- #
# 9〜12 来場者適合（NMSI / VFFI）
# --------------------------------------------------------------------------- #
def _s09_visitor_fit(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "来場者適合分析")
    v, n = ctx.vffi, ctx.nmsi
    if v is None and n is None:
        _no_data(slide, "NMSI・VFFI がいずれも未算出です。")
        return
    rows = []
    if n is not None:
        rows.append(("NMSI（感動指数）", f"{getattr(n, 'score', '—')}",
                     getattr(n, "band", "") or "—"))
    if v is not None:
        rows.append(("VFFI（適合指数）",
                     f"{v.score}" if v.computable else "算出不可",
                     v.band if v.computable else v.reason))
    _table(slide, MARGIN, BODY + Inches(0.4), CONTENT_W, Inches(0.4),
           ["指標", "値", "解釈"], rows)
    _textbox(slide, MARGIN, Inches(4.2), CONTENT_W, Inches(1.8),
             "いずれも推計値です。算出条件と仮定は各詳述ページに記載します。",
             size=12, color=GRAY)


def _s10_nmsi(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "NMSI詳述")
    n = ctx.nmsi
    if n is None:
        _no_data(slide, "NMSI が未算出です。",
                 hint="管理モードの「NMSI（体験満足度）」から算出できます。")
        return
    _textbox(slide, MARGIN, BODY + Inches(0.2), CONTENT_W, Inches(0.9),
             f"NMSI {getattr(n, 'score', '—')} / 100", size=30, bold=True, color=NAVY)
    phases = list(getattr(n, "phases", None) or [])
    if phases:
        rows = [(getattr(p, "name", "—"), f"{getattr(p, 'weight', 0):.2f}",
                 f"{getattr(p, 'score', 0):.2f}") for p in phases]
        _table(slide, MARGIN, Inches(2.6), CONTENT_W, Inches(0.4),
               ["フェーズ", "重み", "E_i"], _fit_rows(rows, ctx, "NMSI"))
    else:
        _textbox(slide, MARGIN, Inches(2.6), CONTENT_W, Inches(1.2),
                 "フェーズ別の内訳がありません（総合値のみ）。", size=13, color=GRAY)


def _s11_vffi(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "VFFI詳述")
    v = ctx.vffi
    if v is None:
        _no_data(slide, "VFFI が未算出です。")
        return
    if not v.computable:
        _no_data(slide, v.reason, hint=vffi_mod.vffi_note(v))
        return
    _textbox(slide, MARGIN, BODY + Inches(0.1), CONTENT_W, Inches(0.8),
             f"VFFI {v.score} / 100　{v.band}", size=26, bold=True, color=NAVY)
    rows = [(r.element, f"{r.target:.2f}", f"{r.experience:.2f}",
             f"{r.gap:+.2f}", r.reading) for r in v.rows]
    shown = _fit_rows(rows, ctx, "VFFI要素")
    _table(slide, MARGIN, Inches(2.1), CONTENT_W, Inches(0.4),
           ["要素", "狙い T", "体験 V", "ズレ D", "解釈"], shown)
    _textbox(slide, MARGIN, SLIDE_H - Inches(1.15), CONTENT_W, Inches(0.9),
             vffi_mod.vffi_note(v), size=10, color=GRAY)


def _s12_fit_map(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "適合度×満足度マップ")
    v = ctx.vffi
    if v is None or not v.computable or not v.quadrants:
        _no_data(slide, "VFFI を算出できていないため、4象限を描けません。")
        return
    order = ["理想顧客", "施設サービス改善が必要", "想定外ヒット", "マーケティング改善が必要"]
    w = CONTENT_W / 2 - Inches(0.2)
    h = Inches(1.9)
    for i, name in enumerate(order):
        q = v.quadrants.get(name, {"count": 0, "share": 0.0})
        left = MARGIN + (w + Inches(0.4)) * (i % 2)
        top = BODY + Inches(0.5) + (h + Inches(0.3)) * (i // 2)
        box = slide.shapes.add_shape(1, left, top, w, h)
        box.fill.solid()
        box.fill.fore_color.rgb = LIGHT
        box.line.color.rgb = NAVY
        _textbox(slide, left + Inches(0.2), top + Inches(0.2), w - Inches(0.4),
                 Inches(0.5), name, size=15, bold=True, color=NAVY)
        _textbox(slide, left + Inches(0.2), top + Inches(0.8), w - Inches(0.4),
                 Inches(0.8), f"{q['count']} 件　{q['share']}%",
                 size=22, bold=True, color=ACCENT)


# --------------------------------------------------------------------------- #
# 13 感情・生理指標推定（測っていないので空で出す）
# --------------------------------------------------------------------------- #
def _s13_physio(prs, ctx: Ctx) -> None:
    """原典の13枚目。**数値は作らない。**

    Valence / Arousal / β/α / PNN50 のうち、β/α は脳波比、PNN50 は
    心拍変動指標で、クチコミからは測定できない。原典自身が
    「名称を借りた非生理学的な代理推計であり、実測と誤認させない」と
    断っている。代理値を置くと、読み手は計測結果として受け取る。
    枚数を詰めないのは、原典の順番固定の指示に従うため。
    """
    slide = _blank(prs)
    _title_bar(slide, "感情・生理指標推定")
    _textbox(slide, MARGIN, BODY + Inches(0.4), CONTENT_W, Inches(0.8),
             "測定していません", size=24, bold=True, color=GRAY)
    _textbox(slide, MARGIN, BODY + Inches(1.3), CONTENT_W, Inches(2.6),
             "β/α（脳波比）と PNN50（心拍変動指標）は生体計測で得る指標であり、"
             "クチコミ本文からは測定も推定もできません。\n\n"
             "原典仕様も、これらを出す場合は「名称を借りた非生理学的な代理推計」で"
             "あって実測ではないと断ることを求めています。本レポートでは"
             "代理値を置かず、空のまま残します。\n\n"
             "感情の傾向は『平均スコア分析』『口コミインサイト』の各ページを"
             "参照してください。",
             size=14, color=NAVY)
    _textbox(slide, MARGIN, SLIDE_H - Inches(1.0), CONTENT_W, Inches(0.5),
             "※ 生体計測データを取得した場合は、この面に実測値を記載できます。",
             size=11, color=GRAY)


# --------------------------------------------------------------------------- #
# 14〜18
# --------------------------------------------------------------------------- #
def _s14_kpi(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "KPI別戦略")
    ts = ctx.topic_score
    rows = []
    for layer in kpi_mod.LAYERS:
        codes = [k.code for k in kpi_mod.KPIS if k.layer == layer]
        rows.append((layer, " / ".join(codes), _kpi_state(ts, layer)))
    _table(slide, MARGIN, BODY + Inches(0.3), CONTENT_W, Inches(0.4),
           ["層", "KPI", "現状"], rows)
    _textbox(slide, MARGIN, SLIDE_H - Inches(1.3), CONTENT_W, Inches(1.0),
             "ROI・財務・従業員満足など、クチコミから観測できない項目は"
             "「定量測定不可、代理兆候のみ」として扱います。",
             size=11, color=GRAY)


def _kpi_state(ts, layer: str) -> str:
    if ts is None or getattr(ts, "empty", True):
        return "スコア未算出"
    names = kpi_mod.topics_for(layer) if hasattr(kpi_mod, "topics_for") else []
    vals = [t.sentiment_100 for t in ts.topics if t.name in names]
    return f"平均 {sum(vals) / len(vals):.1f}" if vals else "対応トピックなし"


def _s15_priority(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "優先改善項目")
    ts = ctx.topic_score
    if ts is None or getattr(ts, "empty", True):
        _no_data(slide, "トピックスコアが未算出のため、優先順位を出せません。")
        return
    worst = sorted(ts.topics, key=lambda t: (t.sentiment, -t.salience))
    rows = [(str(i), t.name, f"{t.sentiment_100:.1f}", f"{t.salience_pct:.1f}%")
            for i, t in enumerate(worst[:MAX_TABLE_ROWS], 1)]
    _table(slide, MARGIN, BODY + Inches(0.3), CONTENT_W, Inches(0.4),
           ["優先", "改善テーマ", "スコア", "言及度"], rows)
    _textbox(slide, MARGIN, SLIDE_H - Inches(1.0), CONTENT_W, Inches(0.6),
             "言及度が高く感情スコアが低い順。ROI データが無いため、"
             "費用対効果は含めていません。", size=11, color=GRAY)


def _s16_strategy(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "戦略提案")
    items = list(getattr(ctx.insights, "actions", None) or [])
    if not items:
        _no_data(slide, "戦略提案が未生成です。",
                 hint="分析画面で LLM インサイトを生成すると反映されます。")
        return
    _bullets(slide, MARGIN, BODY + Inches(0.4), CONTENT_W, Inches(4.6),
             items[:5], size=16)


def _s17_key_insight(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "最重要インサイト")
    text = getattr(ctx.insights, "summary", "") or ""
    if not text:
        _no_data(slide, "インサイトが未生成です。")
        return
    _textbox(slide, MARGIN, BODY + Inches(0.6), CONTENT_W, Inches(4.0),
             text, size=18, color=NAVY)


def _s18_rare(prs, ctx: Ctx) -> None:
    slide = _blank(prs)
    _title_bar(slide, "レアクチコミ分析")
    if not ctx.rares:
        _no_data(slide, "n=1 のレアクチコミが抽出されませんでした。")
        return
    rows = [(str(i), r.text[:46], f"{r.score:.2f}", getattr(r, "category", "—"))
            for i, r in enumerate(ctx.rares[:rare_mod.MAX_PER_FACILITY], 1)]
    _table(slide, MARGIN, BODY + Inches(0.3), CONTENT_W, Inches(0.4),
           ["rank", "原文（抜粋）", "スコア", "カテゴリ"], rows)
    _textbox(slide, MARGIN, SLIDE_H - Inches(1.2), CONTENT_W, Inches(0.9),
             f"1施設あたり最大 {rare_mod.MAX_PER_FACILITY} 件。"
             "個人を特定しうる記述は含めていません。", size=11, color=GRAY)


BUILDERS = (
    _s01_cover, _s02_summary, _s03_market, _s04_heatmap, _s05_competitors,
    _s06_radar, _s07_avg_score, _s08_insights, _s09_visitor_fit, _s10_nmsi,
    _s11_vffi, _s12_fit_map, _s13_physio, _s14_kpi, _s15_priority,
    _s16_strategy, _s17_key_insight, _s18_rare,
)


def build_report_v5(ctx: Ctx, output_path: str | Path = "report_v5.pptx") -> Path:
    """18枚を**必ず**この順で出す。データの有無で枚数は変わらない。"""
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    for build in BUILDERS:
        build(prs, ctx)
    assert len(prs.slides) == len(SPEC_TITLES), (
        f"18枚固定のはずが {len(prs.slides)} 枚になっています"
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return out
