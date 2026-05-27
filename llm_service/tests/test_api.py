import pytest

pytestmark = pytest.mark.asyncio


async def test_health(api_client):
    resp = await api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_submit_task(api_client):
    resp = await api_client.post(
        "/api/v1/tasks",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "task_id" in body
    assert body["status"] == "queued"


async def test_execute_task(api_client):
    resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": '{"answer": 42}'}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["result"]["parsed_output"] == {"answer": 42}


async def test_get_task(api_client):
    submit = await api_client.post(
        "/api/v1/tasks",
        json={"caller_service": "mining", "knowledge_domain": "cloud_core_network", "pipeline_stage": "test"},
    )
    task_id = submit.json()["task_id"]
    resp = await api_client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == task_id


async def test_cancel_task(api_client):
    submit = await api_client.post(
        "/api/v1/tasks",
        json={"caller_service": "mining", "knowledge_domain": "cloud_core_network", "pipeline_stage": "test"},
    )
    task_id = submit.json()["task_id"]
    resp = await api_client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_get_result_after_execute(api_client):
    exec_resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "serving",
            "knowledge_domain": "generic",
            "pipeline_stage": "search",
            "messages": [{"role": "user", "content": '{"name": "test"}'}],
        },
    )
    task_id = exec_resp.json()["task_id"]
    result_resp = await api_client.get(f"/api/v1/tasks/{task_id}/result")
    assert result_resp.status_code == 200
    result = result_resp.json()
    assert result["parse_status"] == "succeeded"


async def test_get_attempts_after_execute(api_client):
    exec_resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": '{"ok": true}'}],
        },
    )
    task_id = exec_resp.json()["task_id"]
    attempts_resp = await api_client.get(f"/api/v1/tasks/{task_id}/attempts")
    assert attempts_resp.status_code == 200
    attempts = attempts_resp.json()
    assert len(attempts) >= 1
    assert attempts[0]["status"] == "succeeded"


async def test_get_events_after_execute(api_client):
    exec_resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": '{"x": 1}'}],
        },
    )
    task_id = exec_resp.json()["task_id"]
    events_resp = await api_client.get(f"/api/v1/tasks/{task_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) >= 1


async def test_idempotent_submit(api_client):
    payload = {
        "caller_service": "mining",
        "knowledge_domain": "cloud_core_network",
        "pipeline_stage": "test",
        "messages": [{"role": "user", "content": "hi"}],
        "idempotency_key": "unique-123",
    }
    r1 = await api_client.post("/api/v1/tasks", json=payload)
    r2 = await api_client.post("/api/v1/tasks", json=payload)
    assert r1.json()["task_id"] == r2.json()["task_id"]


async def test_embeddings_endpoint(api_client):
    resp = await api_client.post(
        "/api/v1/models/embeddings",
        json={
            "input": ["alpha", "beta"],
            "caller_service": "serving",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "embedding",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "embedding-3"
    assert [item["index"] for item in body["data"]] == [0, 1]
    assert len(body["data"][0]["embedding"]) == 2


async def test_rerank_endpoint(api_client):
    resp = await api_client.post(
        "/api/v1/models/rerank",
        json={
            "query": "how to configure amf",
            "documents": ["doc-a", "doc-b", "doc-c"],
            "top_n": 2,
            "caller_service": "serving",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "rerank",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "rerank-pro"
    assert len(body["results"]) == 2
    assert body["results"][0]["index"] == 0
    assert body["results"][0]["document"] == "doc-a"
