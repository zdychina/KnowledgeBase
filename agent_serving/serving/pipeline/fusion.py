"""Fusion — combines and deduplicates candidates from multiple retrievers.

Reciprocal Rank Fusion (RRF) is the default strategy.
v2: WeightedRRFFusion for multi-route weighted fusion.
"""
from __future__ import annotations

import logging
from typing import Any

from agent_serving.serving.schemas.models import (
    QueryPlan,
    RetrievalCandidate,
    RetrievalRoutePlan,
    RouteConfig,
    ScoreChain,
)

logger = logging.getLogger(__name__)


class FusionStrategy:
    """Abstract fusion strategy."""

    async def fuse(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        """Combine and rerank candidates."""
        ...


class RRFFusion(FusionStrategy):
    """Reciprocal Rank Fusion.

    Default RRF k=60. Candidates are grouped by retriever source,
    ranked per-source, then merged via RRF formula:
    score = sum(1 / (k + rank_i)) for each source ranking.
    """

    def __init__(self, k: int = 60) -> None:
        self._k = k

    async def fuse(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        # Group by source and rank
        by_source: dict[str, list[RetrievalCandidate]] = {}
        for c in candidates:
            by_source.setdefault(c.source, []).append(c)

        # Sort each source by original score desc
        for source in by_source:
            by_source[source].sort(key=lambda c: c.score, reverse=True)

        # Compute RRF scores
        rrf_scores: dict[str, float] = {}
        candidate_map: dict[str, RetrievalCandidate] = {}

        for source, ranked in by_source.items():
            for rank, c in enumerate(ranked, start=1):
                uid = c.retrieval_unit_id
                rrf_scores[uid] = rrf_scores.get(uid, 0.0) + 1.0 / (self._k + rank)
                candidate_map[uid] = c

        # Sort by RRF score
        sorted_ids = sorted(rrf_scores, key=lambda uid: rrf_scores[uid], reverse=True)
        return [candidate_map[uid] for uid in sorted_ids]


class IdentityFusion(FusionStrategy):
    """Pass-through fusion: sort by original score, deduplicate."""

    async def fuse(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        # Deduplicate by id, keep higher score
        seen: dict[str, RetrievalCandidate] = {}
        for c in candidates:
            key = c.retrieval_unit_id
            if key not in seen or c.score > seen[key].score:
                seen[key] = c
        return sorted(seen.values(), key=lambda c: c.score, reverse=True)


class WeightedRRFFusion(FusionStrategy):
    """Weighted Reciprocal Rank Fusion.

    Same as RRF but each route has a configurable weight:
    score = sum(weight_route * 1 / (k + rank_route))

    Reads weights from RetrievalRoutePlan.routes.
    Each candidate records score_chain.fusion_score and route_sources.
    """

    def __init__(self, k: int = 60) -> None:
        self._k = k

    async def fuse(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
        route_plan: RetrievalRoutePlan | None = None,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        # Build weight map from route_plan
        weight_map: dict[str, float] = {}
        if route_plan:
            for route in route_plan.routes:
                weight_map[route.name] = route.weight

        # Group by source and rank
        by_source: dict[str, list[RetrievalCandidate]] = {}
        for c in candidates:
            by_source.setdefault(c.source, []).append(c)

        # Sort each source by original score desc
        for source in by_source:
            by_source[source].sort(key=lambda c: c.score, reverse=True)

        # Compute weighted RRF scores
        rrf_scores: dict[str, float] = {}
        candidate_map: dict[str, RetrievalCandidate] = {}
        candidate_sources: dict[str, list[str]] = {}

        for source, ranked in by_source.items():
            weight = weight_map.get(source, 1.0)
            for rank, c in enumerate(ranked, start=1):
                uid = c.retrieval_unit_id
                rrf_scores[uid] = rrf_scores.get(uid, 0.0) + weight / (self._k + rank)
                candidate_map[uid] = c
                candidate_sources.setdefault(uid, [])
                if source not in candidate_sources[uid]:
                    candidate_sources[uid].append(source)

        # Build results with score_chain
        sorted_ids = sorted(rrf_scores, key=lambda uid: rrf_scores[uid], reverse=True)
        results: list[RetrievalCandidate] = []
        for uid in sorted_ids:
            c = candidate_map[uid]
            fusion_score = rrf_scores[uid]
            chain = c.score_chain or ScoreChain(
                raw_score=c.score,
                route_sources=candidate_sources.get(uid, [c.source]),
            )
            chain = chain.model_copy(update={
                "fusion_score": fusion_score,
                "route_sources": candidate_sources.get(uid, chain.route_sources),
            })
            results.append(c.model_copy(update={
                "score": fusion_score,
                "score_chain": chain,
            }))
        return results
