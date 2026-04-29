"""v1.1 Serving constants."""
from __future__ import annotations

# --- Intent types ---
INTENT_COMMAND_USAGE = "command_usage"
INTENT_TROUBLESHOOT = "troubleshooting"
INTENT_CONCEPT_LOOKUP = "concept_lookup"
INTENT_PROCEDURE = "procedure"
INTENT_GENERAL = "general"

# --- Item roles (how an item relates to the query) ---
ROLE_SEED = "seed"
ROLE_CONTEXT = "context"
ROLE_SUPPORT = "support"

# --- Item kinds (what table the item came from) ---
KIND_RETRIEVAL_UNIT = "retrieval_unit"
KIND_RAW_SEGMENT = "raw_segment"

# --- Issue types ---
ISSUE_NO_RESULT = "no_result"
ISSUE_LOW_CONFIDENCE = "low_confidence"
ISSUE_AMBIGUOUS_SCOPE = "ambiguous_scope"
ISSUE_PARTIAL_CONTEXT = "partial_context"

# --- Route names (global standard, only 3) ---
ROUTE_LEXICAL_BM25 = "lexical_bm25"
ROUTE_ENTITY_EXACT = "entity_exact"
ROUTE_DENSE_VECTOR = "dense_vector"
ALL_ROUTE_NAMES = [ROUTE_LEXICAL_BM25, ROUTE_ENTITY_EXACT, ROUTE_DENSE_VECTOR]

# --- LLM intent -> internal taxonomy mapping ---
LLM_INTENT_TO_INTERNAL: dict[str, str] = {
    "conceptual": INTENT_CONCEPT_LOOKUP,
    "factoid": INTENT_GENERAL,
    "procedural": INTENT_PROCEDURE,
    "comparative": "comparison",
    "troubleshooting": INTENT_TROUBLESHOOT,
    "navigational": INTENT_GENERAL,
    "general": INTENT_GENERAL,
    # Also map internal names to themselves (idempotent)
    INTENT_COMMAND_USAGE: INTENT_COMMAND_USAGE,
    INTENT_TROUBLESHOOT: INTENT_TROUBLESHOOT,
    INTENT_CONCEPT_LOOKUP: INTENT_CONCEPT_LOOKUP,
    INTENT_PROCEDURE: INTENT_PROCEDURE,
    INTENT_GENERAL: INTENT_GENERAL,
    "comparison": "comparison",
}
