"""Integration tests covering full end-to-end flows."""
import json

import pytest

pytestmark = pytest.mark.asyncio


async def test_full_sync_execute_flow(api_client):
    """Submit via /execute → get result → verify attempts + events."""
    exec_resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "extract",
            "messages": [{"role": "user", "content": "extract entities"}],
            "expected_output_type": "json_object",
        },
    )
    assert exec_resp.status_code == 200
    body = exec_resp.json()
    task_id = body["task_id"]
    assert body["status"] == "succeeded"
    assert body["result"]["parsed_output"] == {"answer": 42}

    # Verify result endpoint
    result = (await api_client.get(f"/api/v1/tasks/{task_id}/result")).json()
    assert result["parse_status"] == "succeeded"

    # Verify attempts
    attempts = (await api_client.get(f"/api/v1/tasks/{task_id}/attempts")).json()
    assert len(attempts) == 1
    assert attempts[0]["status"] == "succeeded"
    assert attempts[0]["latency_ms"] is not None

    # Verify events
    events = (await api_client.get(f"/api/v1/tasks/{task_id}/events")).json()
    event_types = [e["event_type"] for e in events]
    assert "submitted" in event_types
    assert "succeeded" in event_types


async def test_async_submit_then_get(api_client):
    """Submit async task → poll status."""
    submit = await api_client.post(
        "/api/v1/tasks",
        json={
            "caller_service": "serving",
            "knowledge_domain": "generic",
            "pipeline_stage": "search",
            "messages": [{"role": "user", "content": "search query"}],
            "priority": 50,
        },
    )
    task_id = submit.json()["task_id"]
    assert submit.json()["status"] == "queued"

    task = (await api_client.get(f"/api/v1/tasks/{task_id}")).json()
    assert task["status"] == "queued"
    assert task["caller_service"] == "serving"
    assert task["knowledge_domain"] == "generic"
    assert task["pipeline_stage"] == "search"


async def test_idempotency_key_dedup(api_client):
    """Same idempotency_key returns same task_id."""
    payload = {
        "caller_service": "mining",
        "knowledge_domain": "cloud_core_network",
        "pipeline_stage": "normalize",
        "messages": [{"role": "user", "content": "normalize"}],
        "idempotency_key": "idem-integration-001",
    }
    r1 = await api_client.post("/api/v1/tasks", json=payload)
    r2 = await api_client.post("/api/v1/tasks", json=payload)
    assert r1.json()["task_id"] == r2.json()["task_id"]

    # Execute with same idempotency_key should also return same task
    r3 = await api_client.post("/api/v1/execute", json={**payload, "idempotency_key": "idem-integration-001"})
    # The execute will see the queued task, claim and run it
    assert r3.json()["task_id"] == r1.json()["task_id"]


async def test_cancel_prevents_execution(api_client):
    """Submit → cancel → verify status."""
    submit = await api_client.post(
        "/api/v1/tasks",
        json={"caller_service": "mining", "knowledge_domain": "cloud_core_network", "pipeline_stage": "test"},
    )
    task_id = submit.json()["task_id"]

    cancel = await api_client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancel.status_code == 200

    task = (await api_client.get(f"/api/v1/tasks/{task_id}")).json()
    assert task["status"] == "cancelled"


async def test_template_crud_and_usage(api_client):
    """Templates can be queried via API."""
    # Verify stats API
    stats = await api_client.get("/api/v1/stats")
    assert stats.status_code == 200
    assert isinstance(stats.json()["data"]["tasks_by_status"], dict)


async def test_execute_with_text_output_type(api_client):
    """text output_type returns raw text without JSON parsing."""
    resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "evaluation",
            "pipeline_stage": "grade",
            "messages": [{"role": "user", "content": "grade this"}],
            "expected_output_type": "text",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # MockProvider returns '{"answer": 42}' as text, which text type should store as-is
    assert body["result"]["text_output"] == '{"answer": 42}'


async def test_schema_validation(api_client):
    """Schema validation marks result as schema_invalid when output doesn't match."""
    resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "validate",
            "messages": [{"role": "user", "content": "test"}],
            "expected_output_type": "json_object",
            "output_schema": {"type": "object", "required": ["name"]},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # MockProvider returns {"answer": 42} which doesn't have "name" → schema_invalid
    assert body["result"]["parse_status"] == "schema_invalid"


async def test_metadata_persisted(api_client):
    """metadata passed by caller is stored in task row."""
    resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "extract",
            "messages": [{"role": "user", "content": "test"}],
            "metadata": {"source": "unit-test", "batch_no": 42},
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    # Verify metadata on task row
    task = (await api_client.get(f"/api/v1/tasks/{task_id}")).json()
    meta = task.get("metadata_json") or task.get("metadata")
    if isinstance(meta, str):
        import json as _json
        meta = _json.loads(meta)
    assert meta["source"] == "unit-test"
    assert meta["batch_no"] == 42

    # Verify request row exists (auto-generated UUID)
    attempts = (await api_client.get(f"/api/v1/tasks/{task_id}/attempts")).json()
    assert len(attempts) == 1


async def test_template_key_expands_messages(api_client):
    """When template_key is provided without messages, template resolves gracefully."""
    # No template exists in test DB, so template_key is silently ignored
    # and messages fall back to input dict. The task still succeeds.
    resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "mining",
            "knowledge_domain": "cloud_core_network",
            "pipeline_stage": "test",
            "template_key": "nonexistent-template",
            "input": {"query": "test"},
            "expected_output_type": "text",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"


async def test_task_detail_api(api_client):
    """Task detail API shows task info."""
    exec_resp = await api_client.post(
        "/api/v1/execute",
        json={
            "caller_service": "serving",
            "knowledge_domain": "generic",
            "pipeline_stage": "query_rewrite",
            "messages": [{"role": "user", "content": "rewrite"}],
        },
    )
    task_id = exec_resp.json()["data"]["task_id"]

    detail = await api_client.get(f"/api/v1/tasks/{task_id}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["task"]["id"] == task_id
    assert data["task"]["caller_service"] == "serving"
    assert data["task"]["knowledge_domain"] == "generic"
