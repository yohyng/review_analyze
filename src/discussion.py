"""SLIDE 7「ディスカッションポイント」— 課題の抽出と優先度づけ。

課題そのもの・スコア・平均との差・優先度・インパクトは**すべてここで算出する**。
LLM に任せるのは「企画仮説」「対応領域」「打ち手の中身」といった文章と、
実現しやすさの見立てだけ。数値をモデルに作らせない。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Issue:
    topic: str                    # 「再訪意向の低さ」の元になる観点名
    score5: float                 # 自施設のスコア（5点満点）
    base5: float                  # 比較基準のスコア（5点満点）
    gap5: float                   # score5 - base5（負なら劣位）
    priority: str                 # 「高」/「中」
    base_label: str = "同業平均"
    evidence: str = ""            # LLM: 口コミから読み取れる定性的な根拠
    hypothesis: str = ""          # LLM: 企画仮説
    domains: list[str] = field(default_factory=list)   # LLM: 対応領域タグ

    @property
    def title(self) -> str:
        return f"{self.topic}の低さ" if self.gap5 < 0 else f"{self.topic}の伸びしろ"

    @property
    def score_line(self) -> str:
        return f"{self.topic} {self.score5:.2f}（{self.base_label} {self.base5:.2f}）"

    @property
    def impact(self) -> float:
        """改善インパクト 0〜1。基準との差が大きいほど伸びしろが大きい。"""
        return min(1.0, abs(self.gap5) / 0.6)


@dataclass
class Action:
    title: str
    priority: str
    bullets: list[str] = field(default_factory=list)
    impact: float = 0.5           # 縦軸（コード側で算出）
    feasibility: float = 0.5      # 横軸（LLM の見立て。無ければ0.5）


def pick_issues(bundle: dict, k: int = 3) -> list[Issue]:
    """比較基準に対して最も劣位な観点を課題として拾う。

    outcome（体験満足度・推奨意向・再訪意向）も含めた22観点から選ぶ。
    ディスカッションの起点なので、結果指標の落ち込みも課題になりうるため。
    """
    from . import topic_score
    mine = dict(zip(bundle.get("topic_names") or [], bundle.get("topic_values") or []))
    base = bundle.get("overall_topic") or {}
    if not mine or not base:
        return []

    rows = []
    for t in topic_score.TOPIC_ORDER:
        if t not in mine or t not in base:
            continue
        s5, b5 = mine[t] / 100 * 5, base[t] / 100 * 5
        rows.append((t, round(s5, 2), round(b5, 2), round(s5 - b5, 2)))
    rows.sort(key=lambda r: r[3])          # 劣位が大きい順

    label = bundle.get("baseline_label") or "同業平均"
    if label.endswith("の平均"):
        label = label[:-3] + "平均"
    out = []
    for i, (t, s5, b5, gap) in enumerate(rows[:k]):
        out.append(Issue(topic=t, score5=s5, base5=b5, gap5=gap,
                         priority="高" if i == 0 else "中", base_label=label))
    return out


def fallback_texts(issue: Issue) -> tuple[str, str, list[str]]:
    """LLM を使わないときの根拠・仮説・対応領域。

    観測できた差だけを述べ、原因や打ち手を断定しない。
    """
    direction = "下回っている" if issue.gap5 < 0 else "上回っている"
    evidence = f"{issue.base_label}を {abs(issue.gap5):.2f}pt {direction}"
    hypothesis = (f"「{issue.topic}」に関する口コミの評価が"
                  f"{issue.base_label}に届いていない。要因は未検証。")
    return evidence, hypothesis, []


def fallback_actions(issues: list[Issue]) -> list[Action]:
    """LLM を使わないときの打ち手。施策を創作せず、検討の起点だけを示す。"""
    return [
        Action(title=f"「{iss.topic}」の実態把握",
               priority=iss.priority,
               bullets=[f"該当する口コミを抽出して具体的な不満点を特定する",
                        f"{iss.base_label}との差 {iss.gap5:+.2f}pt の内訳を分解する",
                        "打ち手は要因を特定してから検討する"],
               impact=iss.impact, feasibility=0.5)
        for iss in issues
    ]


def apply_llm_result(issues: list[Issue], data) -> list[Action] | None:
    """LLM の返り値を Issue に流し込み、Action を組み立てる。

    data は {"issues": [{evidence, hypothesis, domains}], "actions":
    [{title, bullets, feasibility}]} を想定。形式が壊れていれば None。
    インパクトは LLM の値を使わず、必ず Issue.impact（実測の差）から入れる。
    """
    if not isinstance(data, dict):
        return None
    di, da = data.get("issues"), data.get("actions")
    if not isinstance(di, list) or not isinstance(da, list):
        return None
    if len(di) != len(issues):
        return None

    for iss, item in zip(issues, di):
        if not isinstance(item, dict):
            return None
        iss.evidence = str(item.get("evidence", "")).strip()
        iss.hypothesis = str(item.get("hypothesis", "")).strip()
        doms = item.get("domains") or []
        iss.domains = [str(d) for d in doms][:2] if isinstance(doms, list) else []

    actions = []
    for i, item in enumerate(da[:len(issues)]):
        if not isinstance(item, dict):
            return None
        try:
            feas = float(item.get("feasibility", 0.5))
        except (TypeError, ValueError):
            feas = 0.5
        bl = item.get("bullets") or []
        actions.append(Action(
            title=str(item.get("title", "")).strip() or issues[i].topic,
            priority=issues[i].priority,
            bullets=[str(b) for b in bl][:3] if isinstance(bl, list) else [],
            impact=issues[i].impact,                 # 実測から。LLMの値は使わない
            feasibility=min(1.0, max(0.0, feas)),
        ))
    return actions or None
