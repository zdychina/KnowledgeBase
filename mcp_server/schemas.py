"""Pydantic models for MCP tool inputs and outputs."""

from __future__ import annotations

from pydantic import BaseModel, Field


# --- health_check output ---

class HealthResult(BaseModel):
    available: bool
    status: str = ""
    version: str = ""
    latency_ms: float = 0.0
    error: str = ""


# --- search_knowledge input ---

class EntityRef(BaseModel):
    type: str = ""
    name: str
    normalized_name: str = ""


class SearchInput(BaseModel):
    query: str
    domain: str = "cloud_core_network"
    scope: dict | None = None
    entities: list[EntityRef] | None = None
    debug: bool = False
    max_text_length: int = 1000


# --- search_knowledge output ---

class QueryUnderstanding(BaseModel):
    original: str = ""
    intent: str = ""
    keywords: list[str] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    index: int
    role: str = ""
    evidence_role: str = ""
    score: float = 0.0
    title: str = ""
    semantic_role: str = ""
    block_type: str = ""
    text: str = ""
    citation: dict = Field(default_factory=dict)


class SourceRef(BaseModel):
    document_key: str = ""
    title: str = ""


class IssueNote(BaseModel):
    type: str = ""
    message: str = ""


class SearchResult(BaseModel):
    query_understanding: QueryUnderstanding = Field(default_factory=QueryUnderstanding)
    items: list[EvidenceItem] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    issues: list[IssueNote] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    item_count: int = 0


# --- evaluate_evidence input ---

class ItemSummary(BaseModel):
    evidence_role: str = ""
    score: float = 0.0
    semantic_role: str = ""


class EvaluateInput(BaseModel):
    items_summary: list[ItemSummary]
    intent: str = ""
    query: str = ""


# --- evaluate_evidence output ---

class EvidenceAssessment(BaseModel):
    evidence_sufficiency: str  # sufficient | partial | insufficient
    recommended_action: str    # answer_now | ask_followup | answer_with_caution | delegate
    reasoning: str
    coverage_gaps: list[str] = Field(default_factory=list)
    followup_questions: list[str] = Field(default_factory=list)
    direct_answer_count: int = 0
    support_count: int = 0
    has_background_only: bool = False
