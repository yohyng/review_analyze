"""企業ミュージアムの価値KPI体系と、22観点との対応。

資料「企業ミュージアム統合分析GPT」の KPI 一覧と「トピックとKPI対応」表を
そのまま持ち込んだもの。**計算は増えない**。既存の22観点スコアに
「この観点はどのKPIに効くか」を添えるだけ。

価値の見方は 体験価値 × ブランド価値 × 収益価値。
層ごとに見たいKPIが違うので、層でまとめてある。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kpi:
    code: str
    name: str
    layer: str


# 7層・21指標（資料 §8「KPI一覧」）
KPIS: tuple[Kpi, ...] = (
    Kpi("SAVI", "空間資産価値", "投資家"),
    Kpi("FDI", "施設差別化", "投資家"),
    Kpi("D-ROI", "デザイン投資回収", "投資家"),

    Kpi("SEI", "空間効率", "経営者"),
    Kpi("CES", "来館体験満足", "経営者"),
    Kpi("MSI", "維持管理効率", "経営者"),

    Kpi("SOI", "運営効率", "運営主体"),
    Kpi("EAS", "空間適応性", "運営主体"),
    Kpi("CPI", "清潔性", "運営主体"),

    Kpi("SBP", "ブランド力", "マーケティング"),
    Kpi("PAI", "SNS魅力度", "マーケティング"),
    Kpi("EII", "没入体験", "マーケティング"),

    Kpi("MHI", "空間調和", "デザイン"),
    Kpi("ACI", "世界観一貫性", "デザイン"),
    Kpi("SII", "空間革新性", "デザイン"),

    Kpi("SIE", "戦略投資効率", "経営企画"),
    Kpi("FMS", "更新性", "経営企画"),
    Kpi("EVE", "感情価値", "経営企画"),

    Kpi("WCI", "働きやすさ", "スタッフ"),
    Kpi("OSI", "安全性", "スタッフ"),
    Kpi("SSS", "スタッフ満足", "スタッフ"),
)

BY_CODE = {k.code: k for k in KPIS}
LAYERS = tuple(dict.fromkeys(k.layer for k in KPIS))

# 観点 → 効くKPI（資料 §8「トピックとKPI対応」）。
# 「再訪意向」「推奨意向」は資料では KPI コードでない語も混ざるので、
# ここではコードに落とせるものだけを載せる。
TOPIC_KPIS: dict[str, tuple[str, ...]] = {
    # ── コンテンツ ──
    "品質": ("CES", "FDI", "SBP"),
    "多様性": ("CES", "FMS", "EII"),
    "独自性": ("FDI", "SBP", "SII"),
    "最新性": ("FMS", "SIE", "SII"),
    "更新性": ("FMS", "SIE"),
    "情報性": ("EII", "CES", "SOI"),
    "分かりやすさ": ("CES", "SOI", "EII"),
    # ── 空間設計 ──
    "レイアウト": ("SEI", "SOI", "CES"),
    "機能性": ("SEI", "SOI", "CES"),
    "快適さ": ("CES", "WCI", "CPI"),
    "デザインクオリティ": ("MHI", "ACI", "SAVI", "PAI"),
    "雰囲気": ("SAVI", "MHI", "EVE"),
    "インパクト": ("EVE", "EII", "PAI"),
    # ── サービス ──
    "スタッフ対応": ("CES", "SSS", "SBP"),
    "スタッフ専門性": ("SSS", "SBP", "EVE"),
    "サービス種類": ("CES", "SOI", "D-ROI"),
    # ── 価格・決済 ──
    "料金の適正さ": ("D-ROI", "CES"),
    "料金・決済のサービス多様性": ("D-ROI", "CES"),
    # ── アクセス ──
    "アクセスの利便性": ("SEI", "CES", "SOI"),
    # ── ブランド ──
    "信頼度": ("SBP", "FDI", "SIE"),
    "ロイヤリティ": ("FMS", "SBP", "EVE"),
    # ── 総合評価 ──
    "体験満足度": ("CES", "EVE", "EII"),
    "比較優位性": ("FDI", "SBP", "SAVI"),
    "推奨意向": ("SBP", "PAI", "CES"),
    "再訪意向": ("FMS", "EVE", "SIE"),
}


def kpis_for(topic: str) -> tuple[Kpi, ...]:
    """観点に効くKPI。対応が無ければ空。"""
    return tuple(BY_CODE[c] for c in TOPIC_KPIS.get(topic, ()) if c in BY_CODE)


def label(topic: str, *, with_name: bool = False) -> str:
    """表に添える1行。例 'CES / EVE / EII'。"""
    ks = kpis_for(topic)
    if not ks:
        return ""
    if with_name:
        return " / ".join(f"{k.code}（{k.name}）" for k in ks)
    return " / ".join(k.code for k in ks)


def topics_for(code: str) -> tuple[str, ...]:
    """そのKPIに効く観点の一覧（逆引き）。"""
    return tuple(t for t, cs in TOPIC_KPIS.items() if code in cs)


def rollup(topic_scores: dict) -> dict:
    """観点スコア {観点: 0-100} を KPI 単位に畳む。

    そのKPIに効く観点の**単純平均**。重み付けの根拠が資料に無いので
    勝手な重みは置かない。観点が1つも無いKPIは含めない。
    """
    out: dict[str, float] = {}
    for k in KPIS:
        vals = [topic_scores[t] for t in topics_for(k.code)
                if t in topic_scores and topic_scores[t] is not None]
        if vals:
            out[k.code] = sum(vals) / len(vals)
    return out
