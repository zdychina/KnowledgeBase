"""Reranker — post-retrieval reranking stage (v1.2).

Three-stage pipeline:
1. Deduplicate raw_text/contextual_text sharing same source_segment_id
2. Downweight low-value block types (heading/TOC/link)
3. Rule-based scoring boost (intent-role, scope, entity match)
4. Budget truncation
"""
from __future__ import annotations

import logging
from typing import Any

from agent_serving.serving.schemas.models import (
    QueryPlan,
    RetrievalCandidate,
    RetrievalRoutePlan,
)

logger = logging.getLogger(__name__)

# v1.2 constants
_LOW_VALUE_BLOCK_TYPES = frozenset({"heading", "toc", "link"})
_DOWNWEIGHT_FACTOR = 0.3

_INTENT_ROLE_BOOST = 0.3
_SCOPE_BOOST = 0.2
_ENTITY_BOOST = 0.25


class Reranker:
    """Abstract reranker interface."""

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan | None = None,
        route_plan: RetrievalRoutePlan | None = None,
    ) -> list[RetrievalCandidate]:
        """Rerank and truncate candidates."""
        ...


class ScoreReranker(Reranker):
    """Default reranker: dedup → downweight → rule scoring → truncation.

    v1.2 replaces the old "preferred + other" two-segment sort with
    proper score-based reranking.
    """

    def __init__(
        self,
        *,
        low_value_block_types: frozenset[str] | None = None,
        downweight_factor: float = _DOWNWEIGHT_FACTOR,
        intent_role_boost: float = _INTENT_ROLE_BOOST,
        scope_boost: float = _SCOPE_BOOST,
        entity_boost: float = _ENTITY_BOOST,
    ) -> None:
        self._low_value_block_types = low_value_block_types or _LOW_VALUE_BLOCK_TYPES
        self._downweight_factor = downweight_factor
        self._intent_role_boost = intent_role_boost
        self._scope_boost = scope_boost
        self._entity_boost = entity_boost

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan | None = None,
        route_plan: RetrievalRoutePlan | None = None,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        filtered = list(candidates)

        # Stage 1: Deduplicate raw_text/contextual_text by source_segment_id
        filtered = self._deduplicate_by_source(filtered)

        # Stage 2: Downweight low-value block types
        filtered = self._apply_downweight(filtered)

        # Stage 3: Rule-based scoring boost
        effective_plan = plan or QueryPlan()
        filtered = self._apply_rule_scoring(filtered, effective_plan)

        # Stage 4: Sort by adjusted score (descending)
        filtered.sort(key=lambda c: c.score, reverse=True)

        # Stage 5: Truncate to budget
        if route_plan is not None:
            recall_limit = route_plan.assembly.max_items
        elif plan is not None:
            recall_limit = plan.budget.max_items
        else:
            recall_limit = 10
        return filtered[:recall_limit]

    def _deduplicate_by_source(
        self,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        """Deduplicate raw_text/contextual_text sharing source_segment_id.

        For each source_segment_id, keep only the highest-scoring candidate
        among raw_text + contextual_text types. Other unit_types are unaffected.
        """
        source_groups: dict[str, list[RetrievalCandidate]] = {}
        result: list[RetrievalCandidate] = []

        for c in candidates:
            unit_type = c.metadata.get("unit_type", "")
            seg_id = c.metadata.get("source_segment_id")

            # Only deduplicate raw_text + contextual_text with source_segment_id
            if unit_type in ("raw_text", "contextual_text") and seg_id:
                if seg_id not in source_groups:
                    source_groups[seg_id] = []
                source_groups[seg_id].append(c)
            else:
                # Pass through without dedup
                result.append(c)

        # For each group, keep only the highest-scoring candidate
        for seg_id, group in source_groups.items():
            best = max(group, key=lambda c: c.score)
            result.append(best)

        return result

    def _apply_downweight(
        self,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        """Apply score penalty to low-value block types."""
        result = []
        for c in candidates:
            if c.metadata.get("block_type") in self._low_value_block_types:
                result.append(c.model_copy(update={"score": c.score * self._downweight_factor}))
            else:
                result.append(c)
        return result

    def _apply_rule_scoring(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        """Apply rule-based score boosts for role, scope, entity matching."""
        desired_roles = set(plan.desired_roles or [])
        desired_block_types = set(plan.desired_block_types or [])
        query_entities = set()
        for kw in plan.keywords:
            query_entities.add(kw.lower())

        import json as _json

        result = []
        for c in candidates:
            boost = 0.0

            # Intent-role match boost
            if desired_roles and c.metadata.get("semantic_role") in desired_roles:
                boost += self._intent_role_boost

            # Block type match boost
            if desired_block_types and c.metadata.get("block_type") in desired_block_types:
                boost += 0.15

            # Scope match boost (products/domains in facets)
            if plan.scope_constraints:
                facets_str = c.metadata.get("facets_json", "{}")
                if facets_str and facets_str != "{}":
                    try:
                        facets = _json.loads(facets_str)
                        for scope_key, scope_vals in plan.scope_constraints.items():
                            if scope_key in facets:
                                facet_vals = {v.lower() for v in facets[scope_key]}
                                query_vals = {v.lower() for v in scope_vals}
                                if facet_vals & query_vals:
                                    boost += self._scope_boost
                                    break
                    except (_json.JSONDecodeError, TypeError):
                        pass

            # Entity match boost
            entity_refs_str = c.metadata.get("entity_refs_json", "[]")
            if entity_refs_str and entity_refs_str != "[]" and query_entities:
                try:
                    entity_refs = _json.loads(entity_refs_str)
                    for ref in entity_refs:
                        norm = ref.get("normalized_name", "").lower()
                        if norm and norm in query_entities:
                            boost += self._entity_boost
                            break
                except (_json.JSONDecodeError, TypeError):
                    pass

            if boost:
                result.append(c.model_copy(update={"score": c.score + boost}))
            else:
                result.append(c)

        return result
