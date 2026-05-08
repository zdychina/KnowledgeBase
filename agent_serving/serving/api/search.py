"""Search API — v2 Retrieval Orchestrator endpoint.

Pipeline: understand → route → resolve scope → retrieve → fuse → rerank → assemble
Each stage is traced via TraceCollector.

Integrations:
- LLM: QueryUnderstandingEngine (LLM-first, rule fallback)
- Embedding: llm_service model endpoint preferred, direct embedding fallback retained
- Rerank: llm_service model rerank → LLMReranker → ScoreReranker (fallback chain)
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from agent_serving.serving.schemas.models import (
    ContextPack,
    QueryPlan,
    QueryUnderstanding,
    RetrievalBudget,
    RetrievalRoutePlan,
    SearchRequest,
)
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.retrieval.bm25_retriever import FTS5BM25Retriever
from agent_serving.serving.retrieval.dense_vector_retriever import DenseVectorRetriever
from agent_serving.serving.retrieval.graph_expander import GraphExpander
from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.application.query_understanding import QueryUnderstandingEngine
from agent_serving.serving.application.retrieval_router import RetrievalRouter
from agent_serving.serving.pipeline.retrieval_orchestrator import RetrievalOrchestrator
from agent_serving.serving.pipeline.fusion import (
    IdentityFusion,
    RRFFusion,
    WeightedRRFFusion,
)
from agent_serving.serving.pipeline.reranker import ScoreReranker
from agent_serving.serving.rerank.pipeline import RerankPipeline
from agent_serving.serving.observability.trace import TraceCollector
from agent_serving.serving.domain_pack_reader import load_serving_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["search"])


def _get_repo(request: Request) -> AssetRepository:
    return AssetRepository(request.app.state.pool)


def _get_orchestrator(request: Request) -> RetrievalOrchestrator:
    pool = request.app.state.pool
    embedding_dimensions = getattr(request.app.state, "embedding_dimensions", 1024)
    bm25 = FTS5BM25Retriever(pool)
    dense = DenseVectorRetriever(pool, embedding_dimensions=embedding_dimensions)
    return RetrievalOrchestrator({
        "lexical_bm25": bm25,
        "dense_vector": dense,
    })


def _get_expander(request: Request) -> GraphExpander:
    return GraphExpander(request.app.state.pool)


def _get_qu_engine(request: Request) -> QueryUnderstandingEngine:
    return QueryUnderstandingEngine(
        llm_client=getattr(request.app.state, "llm_client", None),
    )


def _get_router() -> RetrievalRouter:
    return RetrievalRouter()


def _get_rerank_pipeline(request: Request) -> RerankPipeline:
    """Build cascading rerank pipeline: shared model endpoint → LLM → Score."""
    model_reranker = None
    llm_client = getattr(request.app.state, "llm_client", None)
    if llm_client:
        try:
            from agent_serving.serving.rerank.service_reranker import LLMServiceReranker
            model_reranker = LLMServiceReranker(
                llm_client=llm_client,
                model=os.environ.get("RERANK_MODEL", "rerank-pro"),
            )
        except Exception:
            logger.warning("Failed to create LLMServiceReranker", exc_info=True)

    if model_reranker is None:
        api_key = os.environ.get("RERANK_API_KEY")
        if api_key:
            try:
                from agent_serving.serving.rerank.zhipu_reranker import ZhipuReranker
                model_reranker = ZhipuReranker(
                    api_key=api_key,
                    base_url=os.environ.get(
                        "RERANK_BASE_URL", "https://open.bigmodel.cn/api/paas/v4",
                    ),
                    model=os.environ.get("RERANK_MODEL", "rerank-pro"),
                )
            except Exception:
                logger.warning("Failed to create ZhipuReranker", exc_info=True)

    # LLM-based reranker (via LLM service)
    llm_reranker = None
    if llm_client:
        try:
            from agent_serving.serving.rerank.llm_reranker import LLMReranker
            llm_reranker = LLMReranker(llm_client=llm_client)
        except Exception:
            logger.warning("Failed to create LLMReranker", exc_info=True)

    return RerankPipeline(
        model_reranker=model_reranker,
        llm_reranker=llm_reranker,
        score_reranker=ScoreReranker(),
    )


async def _generate_query_embedding(
    request: Request, query: str,
) -> list[float] | None:
    """Generate query embedding via shared llm_service, fallback to direct client."""
    llm_client = getattr(request.app.state, "llm_client", None)
    if llm_client:
        try:
            response = await llm_client.embed(
                [query],
                model=os.environ.get("EMBEDDING_MODEL", "embedding-3"),
                dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", "1024")),
            )
            if response and response.get("data"):
                return response["data"][0]["embedding"]
        except Exception:
            logger.warning("LLM service query embedding failed", exc_info=True)

    embedding_gen = getattr(request.app.state, "embedding_generator", None)
    if embedding_gen:
        try:
            embeddings = await asyncio.to_thread(embedding_gen.embed, [query])
            if embeddings and len(embeddings) > 0:
                return embeddings[0]
        except Exception:
            logger.warning("Direct query embedding generation failed", exc_info=True)
    return None


@router.post("/search", response_model=ContextPack)
async def search(
    body: SearchRequest,
    request: Request,
    repo: AssetRepository = Depends(_get_repo),
    orchestrator: RetrievalOrchestrator = Depends(_get_orchestrator),
    expander: GraphExpander = Depends(_get_expander),
    qu_engine: QueryUnderstandingEngine = Depends(_get_qu_engine),
    route_router: RetrievalRouter = Depends(_get_router),
) -> ContextPack:
    trace = TraceCollector()

    # 1. Load Domain Profile
    domain_profile = None
    if body.domain:
        domain_profile = load_serving_profile(body.domain)
    elif hasattr(request.app.state, "domain_profile"):
        domain_profile = request.app.state.domain_profile

    # 2. Query Understanding (LLM-first, rule fallback)
    trace.start_stage("query_understanding")
    understanding = await qu_engine.understand(body.query, domain_profile)
    trace.end_stage(
        "query_understanding",
        output_summary=f"intent={understanding.intent}, entities={len(understanding.entities)}, source={understanding.source}",
    )

    # 3. Retrieval Router
    trace.start_stage("retrieval_router")
    route_plan = route_router.route(understanding, domain_profile)
    trace.end_stage(
        "retrieval_router",
        output_summary=f"routes={len(route_plan.routes)}, fusion={route_plan.fusion.method}",
    )

    # 4. Resolve active scope
    trace.start_stage("resolve_scope")
    try:
        scope = await repo.resolve_active_scope()
    except ValueError as e:
        if str(e) == "no_active_release":
            raise HTTPException(
                status_code=503,
                detail="No active release — knowledge base is empty",
            )
        if str(e) == "multiple_active_releases":
            raise HTTPException(
                status_code=500,
                detail="Data integrity error: multiple active releases",
            )
        raise
    trace.end_stage("resolve_scope", output_summary=f"snapshots={len(scope.snapshot_ids)}")

    # 5. Generate query embedding for dense vector route
    query_embedding = None
    dense_enabled = any(r.name == "dense_vector" and r.enabled for r in route_plan.routes)
    if dense_enabled:
        trace.start_stage("embedding")
        query_embedding = await _generate_query_embedding(request, body.query)
        trace.end_stage(
            "embedding",
            output_summary=f"dim={len(query_embedding) if query_embedding else 0}",
        )

    # 6. Retrieve from all configured routes
    trace.start_stage("retrieve")
    orch_result = await orchestrator.execute(
        understanding, route_plan,
        query_embedding=query_embedding,
        snapshot_ids=scope.snapshot_ids,
    )
    raw_candidates = orch_result.candidates
    trace.end_stage("retrieve", output_summary=f"candidates={len(raw_candidates)}")

    # 7. Fuse
    trace.start_stage("fusion")
    fusion_method = route_plan.fusion.method
    if fusion_method == "weighted_rrf":
        fusion = WeightedRRFFusion(k=route_plan.fusion.k)
        fused = await fusion.fuse(raw_candidates, QueryPlan(), route_plan)
    elif fusion_method == "rrf":
        fusion = RRFFusion(k=route_plan.fusion.k)
        fused = await fusion.fuse(raw_candidates, QueryPlan())
    else:
        fusion = IdentityFusion()
        fused = await fusion.fuse(raw_candidates, QueryPlan())
    trace.end_stage("fusion", output_summary=f"fused={len(fused)}, method={fusion_method}")

    # 8. Rerank (cascading: Zhipu → LLM → Score)
    trace.start_stage("rerank")
    rerank_pipeline = _get_rerank_pipeline(request)
    ranked, rerank_traces = await rerank_pipeline.rerank(
        fused, route_plan, understanding,
    )
    rerank_method = "model" if rerank_pipeline._model_reranker else "score"
    trace.end_stage("rerank", output_summary=f"ranked={len(ranked)}, method={rerank_method}")

    # 9. Assemble ContextPack
    trace.start_stage("assembly")
    legacy_plan = QueryPlan(
        intent=understanding.intent,
        keywords=understanding.keywords,
        desired_roles=understanding.evidence_need.preferred_roles,
        budget=RetrievalBudget(
            max_items=route_plan.assembly.max_items,
            max_expanded=route_plan.assembly.max_expanded,
        ),
        expansion=route_plan.expansion,
    )
    assembler = ContextAssembler(repo, expander)
    pack = await assembler.assemble(
        query=body.query,
        understanding=understanding,
        plan=legacy_plan,
        scope=scope,
        candidates=ranked,
        route_plan=route_plan,
    )
    trace.end_stage("assembly", output_summary=f"items={len(pack.items)}")

    # 10. Build trace for debug
    full_trace = trace.build_trace()

    if body.debug:
        pack = pack.model_copy(update={
            "debug": {
                "understanding": understanding.model_dump(),
                "route_plan": route_plan.model_dump(),
                "scope": scope.model_dump(),
                "trace": full_trace.model_dump(),
                "candidate_count": len(ranked),
                "fusion_method": fusion_method,
                "query_embedding_dim": len(query_embedding) if query_embedding else 0,
                "route_traces": [{"name": t.name, "attempted": t.attempted, "candidates": t.candidate_count, "skipped_reason": t.skipped_reason} for t in orch_result.route_traces],
                "rerank_traces": [t.model_dump() for t in rerank_traces],
            },
        })

    return pack
