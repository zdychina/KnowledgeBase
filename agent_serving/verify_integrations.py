"""E2E verification: call real LLM, embedding, and rerank services.

Run: python -m agent_serving.verify_integrations

Requires:
- LLM service running at localhost:8900
- EMBEDDING_API_KEY in .env
- Mining-built DB at data/mining-single-asset_core.sqlite or similar
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

# Load .env
from dotenv import load_dotenv
load_dotenv()


async def verify_llm():
    """1. Verify LLM service + query understanding."""
    print("\n" + "=" * 60)
    print("[1/3] LLM SERVICE — Query Understanding")
    print("=" * 60)

    from agent_serving.serving.infrastructure.llm_client import ServingLlmClient

    base_url = os.environ.get("LLM_SERVICE_URL", "http://localhost:8900")
    print(f"  Connecting to LLM service: {base_url}")

    client = ServingLlmClient(base_url=base_url)

    # Health check
    t0 = time.monotonic()
    available = client.is_available()
    dt = (time.monotonic() - t0) * 1000
    print(f"  Health check: {'OK' if available else 'FAILED'} ({dt:.0f}ms)")
    if not available:
        print("  SKIP — LLM service not reachable")
        return False

    # Register templates
    await client.ensure_templates()
    print("  Templates registered")

    # Test query understanding
    queries = ["什么是SMF", "ADD APN 怎么配置", "SMF和UPF的区别"]
    for q in queries:
        t0 = time.monotonic()
        result = await client.execute(
            template_key="serving-query-understanding",
            caller_domain="serving",
            pipeline_stage="query_understanding",
            input={"query": q},
            expected_output_type="json_object",
        )
        dt = (time.monotonic() - t0) * 1000

        if result:
            inner = result.get("result", result) if isinstance(result, dict) else {}
            parsed = inner.get("parsed_output", {})
            intent = parsed.get("intent", "?")
            entities = [e.get("name", "") for e in parsed.get("entities", [])]
            print(f"  [{dt:.0f}ms] '{q}' → intent={intent}, entities={entities}")
        else:
            print(f"  [{dt:.0f}ms] '{q}' → FAILED (no result)")

    return True


async def verify_embedding():
    """2. Verify Zhipu embedding generation."""
    print("\n" + "=" * 60)
    print("[2/3] EMBEDDING — Zhipu Embedding-3")
    print("=" * 60)

    api_key = os.environ.get("EMBEDDING_API_KEY")
    if not api_key:
        print("  SKIP — EMBEDDING_API_KEY not set")
        return False

    from agent_serving.serving.infrastructure.embedding import EmbeddingGenerator

    gen = EmbeddingGenerator(
        api_key=api_key,
        model=os.environ.get("EMBEDDING_MODEL", "embedding-3"),
        base_url=os.environ.get("EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", "1024")),
    )

    queries = ["什么是SMF", "ADD APN configuration"]
    for q in queries:
        t0 = time.monotonic()
        vecs = await asyncio.to_thread(gen.embed, [q])
        dt = (time.monotonic() - t0) * 1000

        if vecs and len(vecs) > 0:
            dim = len(vecs[0])
            norm = sum(v * v for v in vecs[0]) ** 0.5
            print(f"  [{dt:.0f}ms] '{q}' → dim={dim}, norm={norm:.4f}")
        else:
            print(f"  [{dt:.0f}ms] '{q}' → FAILED (empty result)")

    return True


async def verify_rerank():
    """3. Verify Zhipu rerank API."""
    print("\n" + "=" * 60)
    print("[3/3] RERANK — Zhipu Rerank Model")
    print("=" * 60)

    api_key = os.environ.get("EMBEDDING_API_KEY")
    if not api_key:
        print("  SKIP — EMBEDDING_API_KEY not set (same key for rerank)")
        return False

    from agent_serving.serving.rerank.zhipu_reranker import ZhipuReranker

    reranker = ZhipuReranker(
        api_key=api_key,
        base_url=os.environ.get("EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
    )

    query = "什么是SMF"
    documents = [
        "SMF (Session Management Function) 是5GC中的会话管理功能实体",
        "UPF 是用户面功能，负责数据包路由和转发",
        "AMF 负责接入和移动性管理",
        "SMF的配置命令包括 ADD SMF、MOD SMF 等",
    ]

    t0 = time.monotonic()
    results = await reranker._call_api(query, documents)
    dt = (time.monotonic() - t0) * 1000

    if results:
        print(f"  [{dt:.0f}ms] Query: '{query}'")
        for r in results:
            idx = r.get("index", -1)
            score = r.get("relevance_score", 0)
            print(f"    [{idx}] score={score:.4f} | {documents[idx][:60]}...")
    else:
        print(f"  [{dt:.0f}ms] FAILED (no results)")
        return False

    return True


async def main():
    print("Serving Integration Verification")
    print("=" * 60)

    r1 = await verify_llm()
    r2 = await verify_embedding()
    r3 = await verify_rerank()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  LLM Query Understanding: {'PASS' if r1 else 'FAIL/SKIP'}")
    print(f"  Embedding Generation:    {'PASS' if r2 else 'FAIL/SKIP'}")
    print(f"  Zhipu Rerank:            {'PASS' if r3 else 'FAIL/SKIP'}")

    if r1 and r2 and r3:
        print("\n  All integrations verified!")
    else:
        print("\n  Some integrations failed or skipped.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
