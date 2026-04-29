"""RetrievalOrchestrator — industrial-grade multi-route retrieval.

Replaces RetrieverManager. Passes full RetrievalQuery to each retriever.
Routes that lack required input (e.g. no embedding for dense) are auto-skipped.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from agent_serving.serving.schemas.models import (
    QueryUnderstanding,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalRoutePlan,
)
from agent_serving.serving.retrieval.retriever import Retriever
from agent_serving.serving.schemas.constants import (
    ROUTE_LEXICAL_BM25,
    ROUTE_ENTITY_EXACT,
    ROUTE_DENSE_VECTOR,
)

logger = logging.getLogger(__name__)


@dataclass
class RouteTrace:
    name: str
    attempted: bool
    candidate_count: int = 0
    skipped_reason: str = ""
    latency_ms: float = 0.0


@dataclass
class OrchestratorResult:
    candidates: list[RetrievalCandidate] = field(default_factory=list)
    route_traces: list[RouteTrace] = field(default_factory=list)


class RetrievalOrchestrator:
    """Orchestrates multi-route retrieval with full query semantics."""

    def __init__(self, retrievers: dict[str, Retriever]) -> None:
        self._retrievers = retrievers

    async def execute(
        self,
        understanding: QueryUnderstanding,
        route_plan: RetrievalRoutePlan,
        query_embedding: list[float] | None,
        snapshot_ids: list[str],
    ) -> OrchestratorResult:
        if not snapshot_ids:
            return OrchestratorResult()

        # Build RetrievalQuery from understanding + embedding
        retrieval_query = RetrievalQuery(
            original_query=understanding.original_query,
            keywords=understanding.keywords,
            entities=understanding.entities,
            query_embedding=query_embedding,
            sub_queries=[sq.text for sq in understanding.sub_queries],
            intent=understanding.intent,
            scope=understanding.scope,
        )

        # Build route config map
        route_config = {r.name: r for r in route_plan.routes if r.enabled}

        traces: list[RouteTrace] = []
        tasks: list[tuple[str, asyncio.Task]] = []

        for route_name, route_cfg in route_config.items():
            retriever = self._retrievers.get(route_name)
            if not retriever:
                traces.append(RouteTrace(name=route_name, attempted=False, skipped_reason="not_registered"))
                continue

            # Auto-skip dense when no embedding
            if route_name == ROUTE_DENSE_VECTOR and not query_embedding:
                traces.append(RouteTrace(name=route_name, attempted=False, skipped_reason="no_embedding"))
                continue

            top_k = route_cfg.top_k
            task = asyncio.ensure_future(
                self._safe_retrieve(retriever, retrieval_query, snapshot_ids, top_k)
            )
            tasks.append((route_name, task))

        # Execute concurrently
        results = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)

        # Collect candidates
        all_candidates: list[RetrievalCandidate] = []
        for (route_name, task), result in zip(tasks, results):
            if isinstance(result, Exception):
                traces.append(RouteTrace(name=route_name, attempted=True, candidate_count=0, skipped_reason=str(result)))
                logger.warning("Route %s failed: %s", route_name, result)
            else:
                candidates = result
                # Normalize source to canonical route name
                annotated = []
                for c in candidates:
                    if c.source != route_name:
                        c = c.model_copy(update={"source": route_name})
                    annotated.append(c)
                all_candidates.extend(annotated)
                traces.append(RouteTrace(name=route_name, attempted=True, candidate_count=len(candidates)))

        return OrchestratorResult(candidates=all_candidates, route_traces=traces)

    async def _safe_retrieve(
        self,
        retriever: Retriever,
        query: RetrievalQuery,
        snapshot_ids: list[str],
        top_k: int,
    ) -> list[RetrievalCandidate]:
        try:
            return await retriever.retrieve(query, snapshot_ids, top_k=top_k)
        except asyncio.CancelledError:
            raise
