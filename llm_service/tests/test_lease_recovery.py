"""Tests for LeaseRecovery, Template API, and startup validation."""
import json

import pytest

pytestmark = pytest.mark.asyncio


# ---- Lease Recovery ----

async def test_lease_recovery_requeues_expired_task(db):
    """Expired running task gets re-queued by LeaseRecovery."""
    from datetime import datetime, timedelta, timezone

    from llm_service.config import LLMServiceConfig
    from llm_service.providers.mock import MockProvider
    from llm_service.runtime.event_bus import EventBus
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.worker import LeaseRecovery

    bus = EventBus(db)
    cfg = LLMServiceConfig(db_path=":memory:", provider_api_key="test")
    mgr = TaskManager(db, bus)

    # Submit and manually set to running with expired lease
    task_id = await mgr.submit("mining", "test")
    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat()
    await db.execute(
        "UPDATE agent_llm_tasks SET status = 'running', lease_expires_at = ?, started_at = ? WHERE id = ?",
        (past, past, task_id),
    )
    await db.commit()

    recovery = LeaseRecovery(db, mgr, bus, interval=999)
    await recovery._recover()

    cur = await db.execute("SELECT status FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "queued"


async def test_lease_recovery_dead_letters_exhausted(db):
    """Expired running task with exhausted attempts gets dead_lettered."""
    from datetime import datetime, timedelta, timezone

    from llm_service.config import LLMServiceConfig
    from llm_service.providers.mock import MockProvider
    from llm_service.runtime.event_bus import EventBus
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.worker import LeaseRecovery

    bus = EventBus(db)
    cfg = LLMServiceConfig(db_path=":memory:", provider_api_key="test")
    mgr = TaskManager(db, bus)

    task_id = await mgr.submit("mining", "test", max_attempts=1)
    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat()
    await db.execute(
        "UPDATE agent_llm_tasks SET status = 'running', lease_expires_at = ?, attempt_count = 1 WHERE id = ?",
        (past, task_id),
    )
    await db.commit()

    recovery = LeaseRecovery(db, mgr, bus, interval=999)
    await recovery._recover()

    cur = await db.execute("SELECT status FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "dead_letter"


# ---- Template API ----

async def test_template_api_crud(api_client):
    """Template API supports create, read, update, archive."""
    # Create
    resp = await api_client.post(
        "/api/v1/templates",
        json={
            "template_key": "test-summary",
            "template_version": "1",
            "knowledge_domain": "cloud_core_network",
            "purpose": "Summarize text",
            "system_prompt": "You are a summarizer.",
            "user_prompt_template": "Summarize: $text",
            "expected_output_type": "json_object",
        },
    )
    assert resp.status_code == 200
    tpl = resp.json()
    tpl_id = tpl["id"]
    assert tpl["template_key"] == "test-summary"
    assert tpl["knowledge_domain"] == "cloud_core_network"

    # List
    resp = await api_client.get("/api/v1/templates", params={"domain": "cloud_core_network"})
    assert resp.status_code == 200
    templates = resp.json()
    assert any(t["template_key"] == "test-summary" for t in templates)

    # Get by key
    resp = await api_client.get("/api/v1/templates/test-summary", params={"domain": "cloud_core_network"})
    assert resp.status_code == 200
    assert resp.json()["purpose"] == "Summarize text"

    # Update
    resp = await api_client.put(
        f"/api/v1/templates/{tpl_id}",
        json={"purpose": "Summarize text v2"},
    )
    assert resp.status_code == 200
    assert resp.json()["purpose"] == "Summarize text v2"

    # Archive (delete)
    resp = await api_client.delete(f"/api/v1/templates/{tpl_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

    # Get by key should return 404 (archived)
    resp = await api_client.get("/api/v1/templates/test-summary", params={"domain": "cloud_core_network"})
    assert resp.status_code == 404


async def test_template_api_resolves_global_fallback(api_client):
    """Domain lookup should fall back to a global template when no override exists."""
    resp = await api_client.post(
        "/api/v1/templates",
        json={
            "template_key": "fallback-summary",
            "template_version": "1",
            "purpose": "Global fallback",
            "system_prompt": "You are a summarizer.",
            "user_prompt_template": "Summarize: $text",
            "expected_output_type": "json_object",
        },
    )
    assert resp.status_code == 200

    resp = await api_client.get("/api/v1/templates/fallback-summary", params={"domain": "cloud_core_network"})
    assert resp.status_code == 200
    tpl = resp.json()
    assert tpl["template_key"] == "fallback-summary"
    assert tpl["knowledge_domain"] is None


# ---- Startup validation ----

async def test_startup_without_api_key_raises():
    """create_app with no API key and no provider factory should raise."""
    from llm_service.config import LLMServiceConfig
    from llm_service.main import create_app

    cfg = LLMServiceConfig(
        db_path=":memory:",
        provider_api_key="",
    )
    with pytest.raises(ValueError, match="PROVIDER_API_KEY"):
        create_app(config=cfg, start_worker=False)


async def test_startup_with_provider_factory_ok():
    """create_app with provider factory should not require API key."""
    from llm_service.config import LLMServiceConfig
    from llm_service.main import create_app
    from llm_service.providers.mock import MockProvider

    cfg = LLMServiceConfig(
        db_path=":memory:",
        provider_api_key="",
    )
    app = create_app(config=cfg, provider_factory=lambda: MockProvider(), start_worker=False)
    assert app.title == "LLM Service"
