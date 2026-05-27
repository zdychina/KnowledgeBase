import pytest

pytestmark = pytest.mark.asyncio


async def test_emit_creates_event_row(db):
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    await db.execute(
        "INSERT INTO agent_llm_tasks (id, caller_domain, caller_service, knowledge_domain, pipeline_stage, status, priority, attempt_count, max_attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t-1", "mining", "mining", "cloud_core_network", "test", "queued", 100, 0, 3, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    await db.commit()

    event_id = await bus.emit(task_id="t-1", event_type="submitted", message="task submitted")
    assert event_id is not None

    cursor = await db.execute("SELECT event_type, message FROM agent_llm_events WHERE id = ?", (event_id,))
    row = await cursor.fetchone()
    assert row["event_type"] == "submitted"
    assert row["message"] == "task submitted"


async def test_emit_stores_metadata(db):
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    await db.execute(
        "INSERT INTO agent_llm_tasks (id, caller_domain, caller_service, knowledge_domain, pipeline_stage, status, priority, attempt_count, max_attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t-2", "mining", "mining", "cloud_core_network", "test", "queued", 100, 0, 3, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    await db.commit()

    await bus.emit(task_id="t-2", event_type="claimed", metadata={"worker": "w1"})
    cursor = await db.execute("SELECT metadata_json FROM agent_llm_events WHERE task_id = 't-2'")
    row = await cursor.fetchone()
    import json
    assert json.loads(row["metadata_json"]) == {"worker": "w1"}
