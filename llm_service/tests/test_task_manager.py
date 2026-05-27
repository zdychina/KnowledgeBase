import pytest

pytestmark = pytest.mark.asyncio


async def test_submit_creates_task(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    task_id = await mgr.submit(
        caller_service="mining",
        knowledge_domain="cloud_core_network",
        pipeline_stage="summary_generation",
    )
    assert task_id is not None

    cur = await db.execute(
        "SELECT status, caller_service, knowledge_domain, pipeline_stage FROM agent_llm_tasks WHERE id = ?",
        (task_id,),
    )
    row = await cur.fetchone()
    assert row["status"] == "queued"
    assert row["caller_service"] == "mining"
    assert row["knowledge_domain"] == "cloud_core_network"


async def test_submit_with_idempotency_key_returns_same(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    t1 = await mgr.submit(caller_service="mining", pipeline_stage="test", idempotency_key="key-1")
    t2 = await mgr.submit(caller_service="mining", pipeline_stage="test", idempotency_key="key-1")
    assert t1 == t2


async def test_claim_picks_queued_task(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    task_id = await mgr.submit(caller_service="mining", pipeline_stage="test")
    claimed = await mgr.claim()
    assert claimed == task_id

    cur = await db.execute("SELECT status FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "running"


async def test_claim_returns_none_when_empty(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    result = await mgr.claim()
    assert result is None


async def test_complete_transitions_task(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    task_id = await mgr.submit(caller_service="mining", pipeline_stage="test")
    await mgr.claim()
    await mgr.complete(task_id)

    cur = await db.execute("SELECT status, finished_at FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "succeeded"
    assert row["finished_at"] is not None


async def test_fail_with_retry_marks_queued(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    task_id = await mgr.submit(caller_service="mining", pipeline_stage="test", max_attempts=3)
    await mgr.claim()
    await mgr.fail(task_id, error_type="timeout", error_message="timed out")

    cur = await db.execute("SELECT status, attempt_count, available_at FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "queued"
    assert row["attempt_count"] == 1
    assert row["available_at"] is not None


async def test_fail_exhausted_marks_dead_letter(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    task_id = await mgr.submit(caller_service="mining", pipeline_stage="test", max_attempts=1)
    await mgr.claim()
    await mgr.fail(task_id, error_type="timeout", error_message="timed out")

    cur = await db.execute("SELECT status FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "dead_letter"


async def test_cancel(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    task_id = await mgr.submit(caller_service="mining", pipeline_stage="test")
    await mgr.cancel(task_id)

    cur = await db.execute("SELECT status FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "cancelled"


async def test_idempotency_failed_allows_new(db):
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.event_bus import EventBus

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    t1 = await mgr.submit(caller_service="mining", pipeline_stage="test", idempotency_key="key-2", max_attempts=1)
    await mgr.claim()
    await mgr.fail(t1, error_type="timeout", error_message="failed")
    # Should be dead_letter now, allow new
    t2 = await mgr.submit(caller_service="mining", pipeline_stage="test", idempotency_key="key-2")
    assert t2 != t1
