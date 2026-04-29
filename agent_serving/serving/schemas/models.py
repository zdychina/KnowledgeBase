"""v1.1 Serving data models — ContextPack, QueryPlan, and supporting types.

Key changes from M1:
- ContextPack replaces EvidencePack as the output contract
- ContextRelation is a first-class structure, not a sub-field
- ActiveScope carries document_snapshot_map for document attribution
- QueryPlan uses generic scope dict, not fixed QueryScope fields
- source_refs_json is parsed, not passthrough
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# --- Request ---

class EntityRef(BaseModel):
    type: str = ""
    name: str
    normalized_name: str = ""


class SearchRequest(BaseModel):
    query: str
    scope: dict | None = None
    entities: list[EntityRef] | None = None
    debug: bool = False
    domain: str | None = None
    mode: str = "evidence"


# --- Normalized Query ---

class NormalizedQuery(BaseModel):
    original_query: str = ""
    intent: str = "general"
    entities: list[EntityRef] = Field(default_factory=list)
    scope: dict = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    desired_roles: list[str] = Field(default_factory=list)


# --- Query Plan ---

class RetrievalBudget(BaseModel):
    max_items: int = 10
    max_expanded: int = 20
    recall_multiplier: int = 5


class ExpansionConfig(BaseModel):
    enable_relation_expansion: bool = True
    max_relation_depth: int = 2
    relation_types: list[str] = Field(default_factory=lambda: [
        "previous", "next", "same_section",
        "same_parent_section", "section_header_of",
    ])


class RetrieverConfig(BaseModel):
    """Controls which retrievers to activate and how to fuse results."""
    enabled_retrievers: list[str] = Field(default_factory=lambda: ["fts_bm25"])
    fusion_method: str = "identity"  # "identity" | "rrf"
    rrf_k: int = 60


class RerankerConfig(BaseModel):
    """Controls reranker selection and parameters."""
    reranker_type: str = "score"  # "score" | "llm" | "cross_encoder"


class QueryPlan(BaseModel):
    intent: str = "general"
    keywords: list[str] = Field(default_factory=list)
    entity_constraints: list[EntityRef] = Field(default_factory=list)
    scope_constraints: dict = Field(default_factory=dict)
    desired_roles: list[str] = Field(default_factory=list)
    desired_block_types: list[str] = Field(default_factory=list)
    budget: RetrievalBudget = Field(default_factory=RetrievalBudget)
    expansion: ExpansionConfig = Field(default_factory=ExpansionConfig)
    retriever_config: RetrieverConfig = Field(default_factory=RetrieverConfig)
    reranker_config: RerankerConfig = Field(default_factory=RerankerConfig)


# --- Retrieval Query (v1.3 — replaces empty QueryPlan in retrieval) ---


class RetrievalQuery(BaseModel):
    """Rich query context — carries full semantics to each retriever.

    Modeled after LlamaIndex QueryBundle: carries query text, keywords,
    entities, embedding, and scope in a single structured object.
    Each retriever extracts only what it needs from this object.
    """
    original_query: str
    keywords: list[str] = Field(default_factory=list)
    entities: list[EntityRef] = Field(default_factory=list)
    query_embedding: list[float] | None = None
    sub_queries: list[str] = Field(default_factory=list)
    intent: str = "general"
    scope: dict = Field(default_factory=dict)


# --- Retrieval ---

class RetrievalCandidate(BaseModel):
    retrieval_unit_id: str
    score: float
    source: str
    metadata: dict = Field(default_factory=dict)
    score_chain: "ScoreChain | None" = None


# --- Active Scope ---

class ActiveScope(BaseModel):
    release_id: str
    build_id: str
    snapshot_ids: list[str] = Field(default_factory=list)
    document_snapshot_map: dict[str, str] = Field(default_factory=dict)


# --- Output ---

class ContextQuery(BaseModel):
    original: str
    normalized: str
    intent: str
    entities: list[EntityRef] = Field(default_factory=list)
    scope: dict = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)


class ContextItem(BaseModel):
    id: str
    kind: str
    role: str
    text: str
    score: float
    title: str | None = None
    block_type: str = "unknown"
    semantic_role: str = "unknown"
    source_id: str | None = None
    relation_to_seed: str | None = None
    source_refs: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    route_sources: list[str] = Field(default_factory=list)
    score_chain: "ScoreChain | None" = None
    evidence_role: str = ""
    citation: dict = Field(default_factory=dict)


class ContextRelation(BaseModel):
    id: str
    from_id: str
    to_id: str
    relation_type: str
    distance: int | None = None


class SourceRef(BaseModel):
    id: str
    document_key: str
    title: str | None = None
    relative_path: str | None = None
    scope_json: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class Issue(BaseModel):
    type: str
    message: str
    detail: dict = Field(default_factory=dict)


class ContextPack(BaseModel):
    query: ContextQuery
    items: list[ContextItem] = Field(default_factory=list)
    relations: list[ContextRelation] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    debug: dict | None = None


# --- v2 Retrieval Orchestrator models ---

class SubQuery(BaseModel):
    text: str
    intent: str = "general"
    entities: list[EntityRef] = Field(default_factory=list)


class EvidenceNeed(BaseModel):
    preferred_roles: list[str] = Field(default_factory=list)
    preferred_blocks: list[str] = Field(default_factory=list)
    needs_comparison: bool = False
    needs_citation: bool = False


class QueryUnderstanding(BaseModel):
    original_query: str = ""
    intent: str = "general"
    sub_queries: list[SubQuery] = Field(default_factory=list)
    entities: list[EntityRef] = Field(default_factory=list)
    scope: dict = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    evidence_need: EvidenceNeed = Field(default_factory=EvidenceNeed)
    ambiguities: list[str] = Field(default_factory=list)
    source: str = "rule"  # "rule" | "llm"


class RouteConfig(BaseModel):
    name: str
    enabled: bool = True
    weight: float = 1.0
    top_k: int = 50


class FusionConfig(BaseModel):
    method: str = "weighted_rrf"  # "identity" | "rrf" | "weighted_rrf"
    k: int = 60


class RerankConfig(BaseModel):
    method: str = "score"  # "score" | "llm" | "cascade"
    fallback: str = "score"


class AssemblyConfig(BaseModel):
    source_drilldown: bool = True
    relation_expansion: bool = True
    max_items: int = 10
    max_expanded: int = 20
    max_relation_depth: int = 2
    relation_types: list[str] = Field(default_factory=lambda: [
        "previous", "next", "same_section",
        "same_parent_section", "section_header_of",
    ])


class RetrievalRoutePlan(BaseModel):
    routes: list[RouteConfig] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    assembly: AssemblyConfig = Field(default_factory=AssemblyConfig)
    expansion: ExpansionConfig = Field(default_factory=ExpansionConfig)


class ScoreChain(BaseModel):
    raw_score: float = 0.0
    fusion_score: float = 0.0
    rerank_score: float = 0.0
    route_sources: list[str] = Field(default_factory=list)


class TraceStage(BaseModel):
    name: str
    input_summary: str = ""
    output_summary: str = ""
    duration_ms: float = 0.0
    error: str = ""


class Trace(BaseModel):
    request_id: str = ""
    stages: list[TraceStage] = Field(default_factory=list)
    total_duration_ms: float = 0.0
