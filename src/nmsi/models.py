from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Phase = Literal[
    "pre_visit",
    "arrival",
    "exhibition",
    "experience",
    "show_interaction",
    "food_retail",
    "exit_reflection",
]


PHASE_LABELS: dict[str, str] = {
    "pre_visit": "来館前期待",
    "arrival": "駐車・入口",
    "exhibition": "展示・空間",
    "experience": "遊び・体験",
    "show_interaction": "ショー・交流",
    "food_retail": "飲食・物販",
    "exit_reflection": "出口・振り返り",
}


# ─── NMSI models ──────────────────────────────────────────────────────────────

class PlaceMention(BaseModel):
    surface_form: str = Field(
        description="原文に現れる場所名または場所を指す短い名詞句。推測で固有名を追加しない。"
    )
    place_function: str = Field(
        description="その場所が果たす機能を、感情評価を入れず20字程度で説明する。"
    )
    mention_confidence: float = Field(ge=0.0, le=1.0)


class SentenceAnalysis(BaseModel):
    source_index: int = Field(ge=0)
    phase: Phase
    sentiment: float = Field(ge=-1.0, le=1.0,
        description="-1は強い不満、0は中立、+1は強い満足。")
    intensity: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    positive_summary: str = Field(description="ポジティブ価値の短い要約。該当しない場合は空文字。")
    negative_summary: str = Field(description="不満・摩擦の短い要約。該当しない場合は空文字。")
    memory: float = Field(ge=0.0, le=1.0)
    self_relation: float = Field(ge=0.0, le=1.0)
    revisit: float = Field(ge=0.0, le=1.0)
    recommend: float = Field(ge=0.0, le=1.0)
    wait: float = Field(ge=0.0, le=1.0)
    congestion: float = Field(ge=0.0, le=1.0)
    restriction: float = Field(ge=0.0, le=1.0)
    expectation_gap: float = Field(ge=0.0, le=1.0)
    cost_burden: float = Field(ge=0.0, le=1.0)
    information_gap: float = Field(ge=0.0, le=1.0)
    place_mentions: list[PlaceMention]


class SentenceBatch(BaseModel):
    items: list[SentenceAnalysis]


class ClusterNamingInput(BaseModel):
    provisional_cluster_id: int
    representative_phrase: str
    member_phrases: list[str]
    place_functions: list[str]
    evidence_sentences: list[str]
    positive_evidence: list[str]
    negative_evidence: list[str]


class ClusterName(BaseModel):
    provisional_cluster_id: int
    place_name: str = Field(description="表の見出しに使える簡潔な代表場所名。")
    upper_place: str = Field(description="場所の上位分類。施設固有名ではなく機能分類。")
    phase: Phase
    positive_summary: str
    negative_summary: str
    naming_rationale: str


class ClusterNameBatch(BaseModel):
    items: list[ClusterName]


# ─── Visitor pattern models ────────────────────────────────────────────────────

class VisitorAttributes(BaseModel):
    family_with_children: float | None = Field(default=None, ge=0.0, le=1.0)
    solo: float | None = Field(default=None, ge=0.0, le=1.0)
    couple: float | None = Field(default=None, ge=0.0, le=1.0)
    friends_group: float | None = Field(default=None, ge=0.0, le=1.0)
    elderly_companion: float | None = Field(default=None, ge=0.0, le=1.0)
    tourist: float | None = Field(default=None, ge=0.0, le=1.0)
    local_resident: float | None = Field(default=None, ge=0.0, le=1.0)
    enthusiast_professional: float | None = Field(default=None, ge=0.0, le=1.0)


class VisitPurposes(BaseModel):
    learning: float | None = Field(default=None, ge=0.0, le=1.0)
    tourism: float | None = Field(default=None, ge=0.0, le=1.0)
    child_experience: float | None = Field(default=None, ge=0.0, le=1.0)
    nostalgia: float | None = Field(default=None, ge=0.0, le=1.0)
    brand_understanding: float | None = Field(default=None, ge=0.0, le=1.0)
    architecture_appreciation: float | None = Field(default=None, ge=0.0, le=1.0)
    photography_sns: float | None = Field(default=None, ge=0.0, le=1.0)
    event_participation: float | None = Field(default=None, ge=0.0, le=1.0)
    shopping_food: float | None = Field(default=None, ge=0.0, le=1.0)


class VisitorExpectations(BaseModel):
    detailed_explanation: float | None = Field(default=None, ge=0.0, le=1.0)
    entertainment: float | None = Field(default=None, ge=0.0, le=1.0)
    child_enjoyment: float | None = Field(default=None, ge=0.0, le=1.0)
    nostalgia_expectation: float | None = Field(default=None, ge=0.0, le=1.0)
    low_congestion: float | None = Field(default=None, ge=0.0, le=1.0)
    character_interaction: float | None = Field(default=None, ge=0.0, le=1.0)
    comfort: float | None = Field(default=None, ge=0.0, le=1.0)
    price_value: float | None = Field(default=None, ge=0.0, le=1.0)


class ExperiencedValues(BaseModel):
    learning: float | None = Field(default=None, ge=0.0, le=1.0)
    discovery: float | None = Field(default=None, ge=0.0, le=1.0)
    immersion: float | None = Field(default=None, ge=0.0, le=1.0)
    physical_participation: float | None = Field(default=None, ge=0.0, le=1.0)
    family_sharing: float | None = Field(default=None, ge=0.0, le=1.0)
    character_interaction: float | None = Field(default=None, ge=0.0, le=1.0)
    show_experience: float | None = Field(default=None, ge=0.0, le=1.0)
    circulation_comfort: float | None = Field(default=None, ge=0.0, le=1.0)
    infant_safety: float | None = Field(default=None, ge=0.0, le=1.0)
    price_acceptance: float | None = Field(default=None, ge=0.0, le=1.0)
    sns_photo: float | None = Field(default=None, ge=0.0, le=1.0)
    brand_immersion: float | None = Field(default=None, ge=0.0, le=1.0)


class VisitorFrictions(BaseModel):
    wait: float | None = Field(default=None, ge=0.0, le=1.0)
    congestion: float | None = Field(default=None, ge=0.0, le=1.0)
    restriction: float | None = Field(default=None, ge=0.0, le=1.0)
    cost: float | None = Field(default=None, ge=0.0, le=1.0)
    information_gap: float | None = Field(default=None, ge=0.0, le=1.0)
    expectation_gap: float | None = Field(default=None, ge=0.0, le=1.0)
    fatigue: float | None = Field(default=None, ge=0.0, le=1.0)
    age_mismatch: float | None = Field(default=None, ge=0.0, le=1.0)


class BehaviorIntentions(BaseModel):
    revisit: float | None = Field(default=None, ge=0.0, le=1.0)
    recommend: float | None = Field(default=None, ge=0.0, le=1.0)
    share: float | None = Field(default=None, ge=0.0, le=1.0)
    complaint: float | None = Field(default=None, ge=0.0, le=1.0)
    one_time_only: float | None = Field(default=None, ge=0.0, le=1.0)


class VisitorPattern(BaseModel):
    review_id: str
    attributes: VisitorAttributes
    purposes: VisitPurposes
    expectations: VisitorExpectations
    experienced_values: ExperiencedValues
    frictions: VisitorFrictions
    behavior_intentions: BehaviorIntentions
    overall_satisfaction: float | None = Field(default=None, ge=0.0, le=1.0)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]


class VisitorPatternBatch(BaseModel):
    items: list[VisitorPattern]


class VisitorClusterName(BaseModel):
    provisional_cluster_id: int
    cluster_name: str
    main_traits: str
    likely_visit_context: str
    satisfaction_structure: str
    improvement_direction: str


class VisitorClusterNameBatch(BaseModel):
    items: list[VisitorClusterName]
