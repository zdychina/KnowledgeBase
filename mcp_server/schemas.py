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


# --- evidence assessment (computed by MCP Server) ---

class ItemSummary(BaseModel):
    evidence_role: str = ""
    score: float = 0.0
    semantic_role: str = ""

class EvidenceAssessment(BaseModel):
    evidence_sufficiency: str  # sufficient | partial | insufficient
    recommended_action: str    # answer_now | ask_followup | answer_with_caution | delegate
    reasoning: str
    coverage_gaps: list[str] = Field(default_factory=list)
    followup_questions: list[str] = Field(default_factory=list)
    direct_answer_count: int = 0
    support_count: int = 0
    has_background_only: bool = False
