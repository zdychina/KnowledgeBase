"""Live demo: start LLM Service, submit tasks, inspect via API.

Usage:
    python llm_service/tests/test_live_demo.py

Then open in browser:
    - Swagger docs: http://localhost:8900/docs
    - Task list API: http://localhost:8900/api/v1/tasks (GET)
    - Health: http://localhost:8900/health

Press Ctrl+C to stop.
"""
from __future__ import annotations

import asyncio
import sys
import time

import httpx


BASE_URL = "http://localhost:8900"


async def wait_for_server(client: httpx.AsyncClient, timeout: int = 10) -> bool:
    """Wait for server to be ready."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            resp = await client.get("/health")
            if resp.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        await asyncio.sleep(0.3)
    return False


async def main():
    client = httpx.AsyncClient(base_url=BASE_URL, timeout=30)

    print("=" * 60)
    print("LLM Service Live Demo")
    print("=" * 60)

    # 0. Wait for server
    print("\n[1/6] Waiting for server at", BASE_URL)
    if not await wait_for_server(client):
        print("ERROR: Server not responding. Start it first:")
        print("  python -m llm_service")
        print("  OR set LLM_SERVICE_PROVIDER_API_KEY=your-key && python -m llm_service")
        await client.aclose()
        sys.exit(1)
    print("  Server is up!")

    # 1. Health check
    print("\n[2/6] Health check")
    resp = await client.get("/health")
    print(f"  GET /health -> {resp.json()}")

    # 2. Create a template
    print("\n[3/6] Creating templates")
    templates = [
        {
            "template_key": "demo-summary",
            "template_version": "1",
            "purpose": "Summarize text in Chinese",
            "system_prompt": "You are a helpful assistant. Reply in concise Chinese.",
            "user_prompt_template": "请用一句话总结以下内容：$text",
            "expected_output_type": "text",
        },
        {
            "template_key": "demo-qa-gen",
            "template_version": "1",
            "purpose": "Generate Q&A pairs from content",
            "system_prompt": "You are a knowledge mining assistant. Generate questions and answers in JSON format.",
            "user_prompt_template": "根据以下内容生成3个问答对，以JSON数组形式返回：$content",
            "expected_output_type": "json_array",
            "output_schema_json": '{"type":"array","items":{"type":"object","properties":{"question":{"type":"string"},"answer":{"type":"string"}}}}',
        },
    ]
    for tpl in templates:
        resp = await client.post("/api/v1/templates", json=tpl)
        if resp.status_code == 200:
            print(f"  Created template: {tpl['template_key']} (output: {tpl['expected_output_type']})")
        else:
            print(f"  Template {tpl['template_key']}: {resp.status_code} {resp.text[:80]}")

    # 3. Sync execute with text template (Serving pattern)
    print("\n[4/6] Sync execute (Serving pattern - text summary)")
    resp = await client.post("/api/v1/execute", json={
        "caller_service": "serving",
        "pipeline_stage": "normalizer",
        "template_key": "demo-summary",
        "input": {"text": "大语言模型（LLM）是一种基于深度学习的自然语言处理技术，通过海量文本数据训练，能够理解和生成人类语言。"},
        "max_attempts": 2,
    })
    result = resp.json()
    print(f"  Status: {result.get('status')}")
    print(f"  Task ID: {result.get('task_id')}")
    if result.get("result"):
        print(f"  Parse status: {result['result'].get('parse_status')}")
        print(f"  Text output: {result['result'].get('text_output', 'N/A')[:100]}")
    else:
        print(f"  Error: {result.get('error')}")

    # 4. Async submit (Mining pattern)
    print("\n[5/6] Async submit (Mining pattern - batch Q&A generation)")
    sections = [
        {"content": "Python是一种通用编程语言，支持多种编程范式，包括面向对象和函数式编程。"},
        {"content": "FastAPI是一个现代、快速的Web框架，用于构建API，基于Python类型提示。"},
        {"content": "SQLite是一个轻量级的嵌入式数据库引擎，不需要独立的服务器进程。"},
    ]
    task_ids = []
    for i, section in enumerate(sections):
        resp = await client.post("/api/v1/tasks", json={
            "caller_service": "mining",
            "pipeline_stage": "retrieval_units",
            "template_key": "demo-qa-gen",
            "input": section,
            "metadata": {"ref_type": "section", "ref_id": f"section-{i+1}"},
            "max_attempts": 3,
        })
        if resp.status_code == 200:
            tid = resp.json()["task_id"]
            task_ids.append(tid)
            print(f"  Submitted task for section-{i+1}: {tid[:8]}...")
        else:
            print(f"  Submit failed: {resp.status_code} {resp.text[:80]}")

    # 5. Check task status
    print("\n[6/6] Checking task statuses")
    for tid in task_ids:
        resp = await client.get(f"/api/v1/tasks/{tid}")
        if resp.status_code == 200:
            task = resp.json()
            print(f"  Task {tid[:8]}... status={task['status']} attempts={task['attempt_count']}")
        else:
            print(f"  Task {tid[:8]}... not found")

    # Summary
    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)
    print(f"\nAPI docs:  {BASE_URL}/docs")
    print(f"Stats:     {BASE_URL}/api/v1/stats")
    print(f"\nThis service uses PostgreSQL (database: agent_llm_runtime).")
    print(f"Connection details come from the control plane database/raw endpoint.")
    print(f"\nSubmitted {len(task_ids)} async tasks (mining) + 1 sync task (serving)")
    print("If using a real provider (DeepSeek), async tasks should complete in seconds.")
    print("If using mock, tasks stay 'queued' (no worker in mock mode).")

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
