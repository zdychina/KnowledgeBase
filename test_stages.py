# -*- coding: utf-8 -*-
"""逐阶段追踪 Serving Pipeline — 展示每个阶段的输入输出。

Usage:
    python test_stages.py
"""
import asyncio
import json
import os
import sys
import time

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load .env
from dotenv import load_dotenv
load_dotenv()

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

# ─── Helpers ──────────────────────────────────────────────

def sep(stage: str):
    print(f"\n{'='*70}")
    print(f"  STAGE: {stage}")
    print(f"{'='*70}")

def show(label: str, obj):
    print(f"\n  [{label}]")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > 200:
                print(f"    {k}: {v[:200]}...")
            elif isinstance(v, list) and len(v) > 5:
                print(f"    {k}: [{len(v)} items] first={v[:3]}")
            else:
                print(f"    {k}: {v}")
    elif isinstance(obj, list):
        print(f"    count: {len(obj)}")
        for i, item in enumerate(obj[:5]):
            if isinstance(item, dict):
                print(f"    [{i}] {json.dumps(item, ensure_ascii=False)[:200]}")
            else:
                print(f"    [{i}] {str(item)[:200]}")
        if len(obj) > 5:
            print(f"    ... ({len(obj)-5} more)")
    else:
        print(f"    {obj}")


QUERY = "什么是SBA？"


async def run():
    from agent_serving.serving.infrastructure.pg_config import ServingDbConfig

    cfg = ServingDbConfig()
    pool = cfg.create_pool()
    await pool.open()

    # ═══════════════════════════════════════════════════════
    # STAGE 1: Query Understanding
    # ═══════════════════════════════════════════════════════
    sep("1. Query Understanding")
    print(f"  INPUT: query = '{QUERY}'")

    from agent_serving.serving.application.query_understanding import QueryUnderstandingEngine
    from agent_serving.serving.infrastructure.llm_client import ServingLlmClient

    llm_client = ServingLlmClient(base_url=os.environ.get("LLM_SERVICE_URL", "http://localhost:8900"))
    qu_engine = QueryUnderstandingEngine(llm_client=llm_client)

    t0 = time.perf_counter()
    understanding = await qu_engine.understand(QUERY, domain_profile=None)
    ms = (time.perf_counter() - t0) * 1000

    print(f"\n  OUTPUT ({ms:.0f}ms):")
    print(f"    intent:      {understanding.intent}")
    print(f"    source:      {understanding.source}")
    print(f"    keywords:    {understanding.keywords}")
    print(f"    entities:    {[{'type':e.type,'name':e.name} for e in understanding.entities]}")
    print(f"    scope:       {understanding.scope}")
    print(f"    sub_queries: {[sq.text for sq in understanding.sub_queries]}")
    print(f"    evidence_need.preferred_roles: {understanding.evidence_need.preferred_roles}")

    # ═══════════════════════════════════════════════════════
    # STAGE 2: Retrieval Router
    # ═══════════════════════════════════════════════════════
    sep("2. Retrieval Router")
    print(f"  INPUT: understanding (intent={understanding.intent}, keywords={understanding.keywords})")

    from agent_serving.serving.application.retrieval_router import RetrievalRouter
    router = RetrievalRouter()
    route_plan = router.route(understanding, domain_profile=None)

    print(f"\n  OUTPUT:")
    print(f"    fusion method: {route_plan.fusion.method} (k={route_plan.fusion.k})")
    for r in route_plan.routes:
        print(f"    route: name={r.name} enabled={r.enabled} weight={r.weight} top_k={r.top_k}")
    print(f"    expansion: enable={route_plan.expansion.enable_relation_expansion} types={route_plan.expansion.relation_types}")
    print(f"    assembly: max_items={route_plan.assembly.max_items} max_expanded={route_plan.assembly.max_expanded}")
    print(f"              max_relation_depth={route_plan.assembly.max_relation_depth}")
    print(f"              relation_types={route_plan.assembly.relation_types}")

    # ═══════════════════════════════════════════════════════
    # STAGE 3: Scope Resolution
    # ═══════════════════════════════════════════════════════
    sep("3. Scope Resolution (active release → build → snapshots)")
    print(f"  INPUT: channel='default'")

    from agent_serving.serving.repositories.asset_repo import AssetRepository
    repo = AssetRepository(pool)
    scope = await repo.resolve_active_scope()

    print(f"\n  OUTPUT:")
    print(f"    release_id:  {scope.release_id[:24]}...")
    print(f"    build_id:    {scope.build_id[:24]}...")
    print(f"    snapshot_ids: {scope.snapshot_ids}")
    print(f"    doc→snap map: {scope.document_snapshot_map}")

    # ═══════════════════════════════════════════════════════
    # STAGE 4: Query Embedding
    # ═══════════════════════════════════════════════════════
    sep("4. Query Embedding")
    print(f"  INPUT: query='{QUERY}', model=embedding-3, dimensions=1024")

    t0 = time.perf_counter()
    emb_resp = await llm_client.embed(
        [QUERY], model="embedding-3", dimensions=1024,
    )
    ms = (time.perf_counter() - t0) * 1000
    query_embedding = emb_resp["data"][0]["embedding"] if emb_resp and emb_resp.get("data") else None

    print(f"\n  OUTPUT ({ms:.0f}ms):")
    print(f"    dim:    {len(query_embedding) if query_embedding else 0}")
    print(f"    first5: {query_embedding[:5] if query_embedding else None}")

    # ═══════════════════════════════════════════════════════
    # STAGE 5: Retrieval (BM25 + Dense)
    # ═══════════════════════════════════════════════════════
    sep("5. Retrieval")

    from agent_serving.serving.schemas.models import RetrievalQuery
    from agent_serving.serving.retrieval.bm25_retriever import FTS5BM25Retriever
    from agent_serving.serving.retrieval.dense_vector_retriever import DenseVectorRetriever

    bm25 = FTS5BM25Retriever(pool)
    dense = DenseVectorRetriever(pool, embedding_dimensions=1024)

    retrieval_q = RetrievalQuery(
        original_query=QUERY,
        keywords=understanding.keywords,
        sub_queries=[sq.text for sq in understanding.sub_queries],
        query_embedding=query_embedding,
        scope=understanding.scope,
    )

    print(f"  INPUT: RetrievalQuery")
    print(f"    keywords:       {retrieval_q.keywords}")
    print(f"    sub_queries:    {retrieval_q.sub_queries}")
    print(f"    embedding_dim:  {len(retrieval_q.query_embedding) if retrieval_q.query_embedding else 0}")
    print(f"    snapshot_ids:   {scope.snapshot_ids}")

    # BM25
    print(f"\n  --- BM25 Retrieval ---")
    # Show jieba tokenization effect
    from agent_serving.serving.retrieval.bm25_retriever import _jieba_tokenize
    raw_search = " ".join(retrieval_q.keywords) or retrieval_q.original_query
    jieba_tokens = _jieba_tokenize(raw_search)
    print(f"  jieba: '{raw_search}' → {jieba_tokens}")
    t0 = time.perf_counter()
    bm25_results = await bm25.retrieve(retrieval_q, snapshot_ids=scope.snapshot_ids, top_k=50)
    ms_bm25 = (time.perf_counter() - t0) * 1000
    print(f"  OUTPUT ({ms_bm25:.0f}ms): {len(bm25_results)} candidates")
    for i, c in enumerate(bm25_results[:5]):
        print(f"    [{i}] score={c.score:.4f} id={c.retrieval_unit_id[:16]}...")
        print(f"        title={c.metadata.get('title','')[:60]}")
        print(f"        text={c.metadata.get('text','')[:100]}")

    # Dense
    print(f"\n  --- Dense Vector Retrieval ---")
    t0 = time.perf_counter()
    dense_results = await dense.retrieve(retrieval_q, snapshot_ids=scope.snapshot_ids, top_k=50)
    ms_dense = (time.perf_counter() - t0) * 1000
    print(f"  OUTPUT ({ms_dense:.0f}ms): {len(dense_results)} candidates")
    for i, c in enumerate(dense_results[:5]):
        print(f"    [{i}] score={c.score:.6f} id={c.retrieval_unit_id[:16]}...")
        print(f"        title={c.metadata.get('title','')[:60]}")
        print(f"        text={c.metadata.get('text','')[:100]}")

    # ═══════════════════════════════════════════════════════
    # STAGE 6: Fusion (Weighted RRF)
    # ═══════════════════════════════════════════════════════
    sep("6. Fusion (Weighted RRF)")
    from agent_serving.serving.pipeline.fusion import WeightedRRFFusion
    from agent_serving.serving.schemas.models import QueryPlan

    all_candidates = bm25_results + dense_results
    print(f"  INPUT: {len(all_candidates)} candidates ({len(bm25_results)} BM25 + {len(dense_results)} Dense)")

    fusion = WeightedRRFFusion(k=route_plan.fusion.k)
    t0 = time.perf_counter()
    fused = await fusion.fuse(all_candidates, QueryPlan(), route_plan)
    ms_fusion = (time.perf_counter() - t0) * 1000

    print(f"\n  OUTPUT ({ms_fusion:.0f}ms): {len(fused)} fused candidates")
    for i, c in enumerate(fused[:5]):
        routes = c.score_chain.route_sources if c.score_chain else []
        print(f"    [{i}] score={c.score:.6f} routes={routes}")
        print(f"        title={c.metadata.get('title','')[:60]}")
        print(f"        text={c.metadata.get('text','')[:100]}")

    # ═══════════════════════════════════════════════════════
    # STAGE 7: Rerank
    # ═══════════════════════════════════════════════════════
    sep("7. Rerank (rerank-pro via LLM service)")
    print(f"  INPUT: {len(fused)} fused candidates")

    from agent_serving.serving.rerank.pipeline import RerankPipeline
    from agent_serving.serving.pipeline.reranker import ScoreReranker
    from agent_serving.serving.rerank.service_reranker import LLMServiceReranker

    model_reranker = LLMServiceReranker(llm_client=llm_client, model="rerank-pro")
    rerank_pipeline = RerankPipeline(model_reranker=model_reranker, score_reranker=ScoreReranker())

    t0 = time.perf_counter()
    ranked, rerank_traces = await rerank_pipeline.rerank(fused, route_plan, understanding)
    ms_rerank = (time.perf_counter() - t0) * 1000

    for rt in rerank_traces:
        print(f"    trace: provider={rt.provider} ok={rt.succeeded} latency={rt.latency_ms:.0f}ms "
              f"before={rt.count_before} after={rt.count_after} fallback={rt.fallback_reason}")

    print(f"\n  OUTPUT ({ms_rerank:.0f}ms): {len(ranked)} ranked candidates")
    for i, c in enumerate(ranked[:10]):
        routes = c.score_chain.route_sources if c.score_chain else []
        print(f"    [{i}] score={c.score:.6f} routes={routes}")
        print(f"        title={c.metadata.get('title','')[:60]}")
        print(f"        text={c.metadata.get('text','')[:120]}")

    # ═══════════════════════════════════════════════════════
    # STAGE 8: Assembly (source segments → RST expansion)
    # ═══════════════════════════════════════════════════════
    sep("8. Assembly (source drill-down + RST expansion)")

    # 8a. Resolve source segment IDs from candidates
    from agent_serving.serving.schemas.json_utils import parse_source_refs, parse_target_ref
    from agent_serving.serving.application.assembler import ContextAssembler
    from agent_serving.serving.retrieval.graph_expander import GraphExpander

    all_seg_ids = []
    for c in ranked[:10]:
        seg_id = c.metadata.get("source_segment_id")
        if seg_id:
            all_seg_ids.append(seg_id)
        else:
            refs = c.metadata.get("source_refs_json", "{}")
            if isinstance(refs, str):
                parsed = parse_source_refs(refs)
            elif isinstance(refs, dict):
                parsed = refs.get("raw_segment_ids", [])
            else:
                parsed = []
            all_seg_ids.extend(parsed)

    unique_seg_ids = list(dict.fromkeys(all_seg_ids))
    print(f"  8a. Source segment IDs from top-10 candidates:")
    print(f"      total resolved: {len(all_seg_ids)}, unique: {len(unique_seg_ids)}")
    for sid in unique_seg_ids[:5]:
        print(f"        {sid[:24]}...")

    # 8b. Fetch source segments (with scope filter)
    print(f"\n  8b. Fetch source segments (snapshot_ids={scope.snapshot_ids}):")
    source_segments = await repo.resolve_segments_by_ids(unique_seg_ids, snapshot_ids=scope.snapshot_ids)
    print(f"      result: {len(source_segments)} segments")

    # Also try WITHOUT scope filter
    source_segments_noscope = await repo.resolve_segments_by_ids(unique_seg_ids, snapshot_ids=None)
    print(f"      without scope filter: {len(source_segments_noscope)} segments")
    if source_segments_noscope and len(source_segments_noscope) > 0:
        for s in source_segments_noscope[:3]:
            print(f"        snap_id={s.get('document_snapshot_id','')[:16]}... text={s.get('raw_text','')[:80]}")

    # 8c. Graph expansion
    print(f"\n  8c. RST Graph Expansion:")
    print(f"      seed_segment_ids: {unique_seg_ids}")
    print(f"      snapshot_ids: {scope.snapshot_ids}")
    print(f"      max_depth: {route_plan.assembly.max_relation_depth}")

    expander = GraphExpander(pool)
    expansions = await expander.expand(
        seed_segment_ids=unique_seg_ids,
        max_depth=route_plan.assembly.max_relation_depth,
        relation_types=route_plan.assembly.relation_types or None,
        max_results=route_plan.assembly.max_expanded,
        snapshot_ids=scope.snapshot_ids,
    )
    print(f"      expansions WITH scope: {len(expansions)}")

    expansions_noscope = await expander.expand(
        seed_segment_ids=unique_seg_ids,
        max_depth=route_plan.assembly.max_relation_depth,
        relation_types=route_plan.assembly.relation_types or None,
        max_results=route_plan.assembly.max_expanded,
        snapshot_ids=None,
    )
    print(f"      expansions WITHOUT scope: {len(expansions_noscope)}")
    for e in expansions_noscope[:5]:
        print(f"        seg={e['segment_id'][:16]}... rel={e['relation_type']} depth={e['depth']}")

    await pool.close()
    await llm_client.close()
    print("\n" + "="*70 + "\n  DONE")


if __name__ == "__main__":
    asyncio.run(run())
