"""直接调用 llm_service 三个端点，测量 wall-clock vs 自报 latency_ms
端点: /api/v1/execute (query_understanding)
      /api/v1/models/embeddings
      /api/v1/models/rerank
"""

import time
import json
import urllib.request

BASE = "http://localhost:8900"


def post(endpoint, payload, runs=5):
    """对一个端点跑 runs 次，返回 [(wall_ms, service_ms, detail), ...]"""
    url = BASE + endpoint
    results = []

    # Warm up
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        json.loads(resp.read().decode("utf-8"))

    for i in range(runs):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        wall_ms = (time.perf_counter() - t0) * 1000

        # 提取自报延迟
        svc_ms = body.get("data", {}).get("latency_ms") if endpoint == "/api/v1/execute" else None

        # 各端点的关键指标
        if endpoint == "/api/v1/execute":
            d = body.get("data", {})
            svc_ms = d.get("latency_ms")
            detail = f"tokens={d.get('total_tokens', '?')}"
        elif endpoint == "/api/v1/models/embeddings":
            emb_data = body.get("data", [])
            dim = len(emb_data[0].get("embedding", [])) if emb_data else 0
            svc_ms = body.get("latency_ms")
            detail = f"dim={dim}"
        elif endpoint == "/api/v1/models/rerank":
            results_list = body.get("results", [])
            top_score = results_list[0].get("relevance_score", 0) if results_list else 0
            svc_ms = body.get("latency_ms")
            detail = f"top_score={top_score:.4f}"
        else:
            detail = ""

        results.append((wall_ms, svc_ms, detail))

    return results


def print_report(title, results):
    walls = [r[0] for r in results]
    svcs = [r[1] or 0 for r in results]
    has_svc = any(r[1] is not None for r in results)

    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

    if has_svc:
        print(f"{'#':>3}  {'wall_ms':>8}  {'service_ms':>10}  {'overhead':>9}  detail")
        print("-" * 70)
        for i, (w, s, d) in enumerate(results):
            oh = w - (s or 0)
            print(f"{i+1:3d}  {w:8.0f}  {s or 'N/A':>10}  {oh:9.0f}  {d}")
        print("-" * 70)
        avg_w = sum(walls) / len(walls)
        avg_s = sum(svcs) / len(svcs)
        print(f"avg  {avg_w:8.0f}  {avg_s:10.0f}  {avg_w - avg_s:9.0f}")
    else:
        print(f"{'#':>3}  {'wall_ms':>8}  detail")
        print("-" * 50)
        for i, (w, s, d) in enumerate(results):
            print(f"{i+1:3d}  {w:8.0f}  {d}")
        print("-" * 50)
        avg_w = sum(walls) / len(walls)
        print(f"avg  {avg_w:8.0f}")

    print(f"min  {min(walls):8.0f}")
    print(f"max  {max(walls):8.0f}")


# =========================================================================
# 1. Query Understanding  (POST /api/v1/execute)
# =========================================================================
qu_payload = {
    "pipeline_stage": "query_understanding",
    "template_key": "serving-query-understanding",
    "input": {"query": "SMF是什么网元"},
    "caller_service": "serving",
    "knowledge_domain": "cloud_core_network",
}
qu_results = post("/api/v1/execute", qu_payload, runs=5)
print_report("1. Query Understanding  POST /api/v1/execute", qu_results)

# =========================================================================
# 2. Embedding  (POST /api/v1/models/embeddings)
# =========================================================================
emb_payload = {
    "input": ["SMF是什么网元"],
    "model": "embedding-3",
    "dimensions": 1024,
    "caller_service": "serving",
    "knowledge_domain": "cloud_core_network",
}
emb_results = post("/api/v1/models/embeddings", emb_payload, runs=5)
print_report("2. Embedding  POST /api/v1/models/embeddings", emb_results)

# =========================================================================
# 3. Rerank  (POST /api/v1/models/rerank)
# =========================================================================
rerank_payload = {
    "query": "SMF是什么",
    "documents": [
        "SMF是会话管理功能，负责PDU会话管理",
        "UPF是用户面功能，负责数据转发",
        "AMF是接入和移动性管理功能",
    ],
    "model": "rerank-pro",
    "top_n": 3,
    "caller_service": "serving",
    "knowledge_domain": "cloud_core_network",
}
rerank_results = post("/api/v1/models/rerank", rerank_payload, runs=5)
print_report("3. Rerank  POST /api/v1/models/rerank", rerank_results)

# =========================================================================
# Summary
# =========================================================================
print(f"\n{'='*70}")
print("  SUMMARY — 三个端点对比")
print(f"{'='*70}")
for name, results in [("Query Understanding", qu_results), ("Embedding", emb_results), ("Rerank", rerank_results)]:
    walls = [r[0] for r in results]
    svcs = [r[1] or 0 for r in results]
    avg_w = sum(walls) / len(walls)
    avg_s = sum(svcs) / len(svcs)
    overhead = avg_w - avg_s
    print(f"  {name:22s}  wall={avg_w:6.0f}ms  service={avg_s:6.0f}ms  overhead={overhead:6.0f}ms")
