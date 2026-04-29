"""RetrieverManager — orchestrates multi-path retrieval.

v2: Accepts RetrievalRoutePlan for dynamic route selection.
Each candidate records score_chain.raw_score and score_chain.route_sources.
Deduplication is deferred to the fusion stage.
Supports query_embedding for dense_vector retrieval.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_serving.serving.schemas.models import (
    QueryPlan,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalRoutePlan,
    ScoreChain,
)
from agent_serving.serving.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)


class RetrieverManager:
    """Manages multiple retriever paths and collects candidates.

    Retriever selection is driven by either QueryPlan (legacy) or
    RetrievalRoutePlan (v2). Each retriever is registered with a name.
    """

    def __init__(self, retrievers: dict[str, Retriever] | None = None) -> None:
        self._retrievers: dict[str, Retriever] = retrievers or {}

    def register(self, name: str, retriever: Retriever) -> None:
        self._retrievers[name] = retriever

    async def retrieve(
        self,
        plan: QueryPlan,
        snapshot_ids: list[str],
    ) -> list[RetrievalCandidate]:
        """Legacy retrieve: run all enabled retrievers from QueryPlan."""
        if not self._retrievers:
            return []

        enabled = plan.retriever_config.enabled_retrievers
        if not enabled:
            enabled = list(self._retrievers.keys())

        return await self._run_retrievers(enabled, plan, snapshot_ids)

    async def retrieve_from_route_plan(
        self,
        route_plan: RetrievalRoutePlan,
        snapshot_ids: list[str],
        query_embedding: list[float] | None = None,
    ) -> list[RetrievalCandidate]:
        """v2 retrieve: run enabled routes from RetrievalRoutePlan."""
        if not self._retrievers:
            return []

        enabled_routes = [r for r in route_plan.routes if r.enabled]
        route_config = {r.name: r for r in enabled_routes}
        enabled_names = [r.name for r in enabled_routes]
        plan = QueryPlan()
        return await self._run_retrievers(
            enabled_names, plan, snapshot_ids,
            route_config=route_config,
            query_embedding=query_embedding,
        )

    async def _run_retrievers(
        self,
        enabled_names: list[str],
        plan: QueryPlan,
        snapshot_ids: list[str],
        route_config: dict[str, Any] | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[RetrievalCandidate]:
        """Run specified retrievers concurrently."""
        if not snapshot_ids:
            return []

        async def _safe_retrieve(name: str, retriever: Retriever) -> list[RetrievalCandidate]:
            try:
                top_k = 50
                if route_config and name in route_config:
                    top_k = route_config[name].top_k

                # Build RetrievalQuery from QueryPlan fields
                rq = RetrievalQuery(
                    original_query="",
                    keywords=plan.keywords,
                    entities=plan.entity_constraints,
                    query_embedding=query_embedding,
                    intent=plan.intent,
                    scope=plan.scope_constraints,
                )
                return await retriever.retrieve(rq, snapshot_ids, top_k=top_k)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Retriever '%s' failed", name, exc_info=True)
                return []

        tasks = []
        for name in enabled_names:
            retriever = self._retrievers.get(name)
            if not retriever:
                logger.warning("Retriever '%s' not registered, skipping", name)
                continue
            tasks.append(_safe_retrieve(name, retriever))

        results = await asyncio.gather(*tasks)

        # Collect all candidates, annotate with route_source
        all_candidates: list[RetrievalCandidate] = []
        for name, batch in zip(enabled_names, results):
            for c in batch:
                chain = c.score_chain or ScoreChain(
                    raw_score=c.score,
                    route_sources=[c.source or name],
                )
                sources = list(chain.route_sources)
                if name not in sources:
                    sources.append(name)
                chain = chain.model_copy(update={
                    "raw_score": c.score,
                    "route_sources": sources,
                })
                all_candidates.append(c.model_copy(update={
                    "score_chain": chain,
                }))

        return all_candidates
