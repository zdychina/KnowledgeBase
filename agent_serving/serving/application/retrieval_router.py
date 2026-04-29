"""RetrievalRouter — intent-aware dynamic route plan generation.

Reads route policy from Domain Pack (serving.route_policy) and builds
a RetrievalRoutePlan with per-route weights and top_k values.
Falls back to built-in defaults when no domain pack is available.
"""
from __future__ import annotations

import logging

from agent_serving.serving.schemas.models import (
    AssemblyConfig,
    ExpansionConfig,
    FusionConfig,
    QueryUnderstanding,
    RerankConfig,
    RetrievalRoutePlan,
    RouteConfig,
)
from agent_serving.serving.domain_pack_reader import (
    ServingDomainProfile,
    get_route_policy,
)

logger = logging.getLogger(__name__)

# Built-in intent -> route defaults (used when no domain pack)
_BUILTIN_ROUTES: dict[str, dict[str, dict[str, float]]] = {
    "default": {
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 1.0, "top_k": 30},
        "dense_vector": {"weight": 0.8, "top_k": 50},
    },
    "command_usage": {
        "entity_exact": {"weight": 1.4, "top_k": 20},
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "dense_vector": {"weight": 0.5, "top_k": 30},
    },
    "concept_lookup": {
        "dense_vector": {"weight": 1.2, "top_k": 50},
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 0.6, "top_k": 20},
    },
    "troubleshooting": {
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 1.2, "top_k": 30},
        "dense_vector": {"weight": 0.6, "top_k": 30},
    },
    "comparison": {
        "lexical_bm25": {"weight": 1.0, "top_k": 50},
        "dense_vector": {"weight": 1.0, "top_k": 50},
        "entity_exact": {"weight": 1.0, "top_k": 30},
    },
}


class RetrievalRouter:
    """Generates RetrievalRoutePlan based on intent and domain profile."""

    def route(
        self,
        understanding: QueryUnderstanding,
        domain_profile: ServingDomainProfile | None = None,
    ) -> RetrievalRoutePlan:
        """Build a route plan from query understanding."""
        intent = understanding.intent

        # Get route weights from domain profile or built-in defaults
        if domain_profile:
            route_weights = get_route_policy(domain_profile, intent)
        else:
            route_weights = _BUILTIN_ROUTES.get(
                intent, _BUILTIN_ROUTES["default"],
            )

        # Build route configs
        routes: list[RouteConfig] = []
        for route_name, config in route_weights.items():
            routes.append(RouteConfig(
                name=route_name,
                enabled=True,
                weight=float(config.get("weight", 1.0)),
                top_k=int(config.get("top_k", 50)),
            ))

        # Determine rerank strategy
        rerank_method = "score"
        if understanding.evidence_need.needs_comparison:
            rerank_method = "cascade"

        # Determine fusion method based on number of enabled routes
        enabled_count = sum(1 for r in routes if r.enabled)
        fusion_method = "weighted_rrf" if enabled_count > 1 else "identity"

        return RetrievalRoutePlan(
            routes=routes,
            filters=understanding.scope,
            fusion=FusionConfig(method=fusion_method),
            rerank=RerankConfig(method=rerank_method),
            assembly=AssemblyConfig(
                max_items=10,
                max_expanded=20,
            ),
            expansion=ExpansionConfig(),
        )
