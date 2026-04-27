import pytest

pytestmark = pytest.mark.asyncio


async def test_execute_success(db):
    from llm_service.runtime.event_bus import EventBus
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.executor import Executor
    from llm_service.providers.mock import MockProvider

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    provider = MockProvider(
        responses=[{"choices": [{"message": {"content": '{"summary": "ok"}'}}]}]
    )
    executor = Executor(db, mgr, bus, provider)

    task_id = await mgr.submit(caller_domain="mining", pipeline_stage="test")
    # Create request row for the task
    import uuid
    from datetime import datetime, timezone
    await db.execute(
        "INSERT INTO agent_llm_requests (id, task_id, provider, model, messages_json, input_json, params_json, expected_output_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), task_id, "mock", "mock-model", "[]", "{}", "{}", "json_object", datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()

    result = await executor.run(task_id, messages=[{"role": "user", "content": "test"}], params={})

    assert result.parse_status == "succeeded"
    assert result.parsed_output == {"summary": "ok"}

    cur = await db.execute("SELECT status, latency_ms FROM agent_llm_attempts WHERE task_id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "succeeded"
    assert row["latency_ms"] is not None


async def test_execute_retries_on_failure(db):
    from llm_service.runtime.event_bus import EventBus
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.executor import Executor
    from llm_service.providers.mock import MockProvider
    from llm_service.providers.base import ProviderError
    import uuid
    from datetime import datetime, timezone

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    provider = MockProvider(
        responses=[{"choices": [{"message": {"content": '{"answer": 42}'}}]}]
    )
    call_count = 0
    original_complete = provider.complete

    async def flaky_complete(messages, params, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ProviderError("timeout", "first call timed out")
        return await original_complete(messages, params, **kwargs)

    provider.complete = flaky_complete
    executor = Executor(db, mgr, bus, provider)

    task_id = await mgr.submit(caller_domain="mining", pipeline_stage="test", max_attempts=3)
    await db.execute(
        "INSERT INTO agent_llm_requests (id, task_id, provider, model, messages_json, input_json, params_json, expected_output_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), task_id, "mock", "mock-model", "[]", "{}", "{}", "json_object", datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()

    result = await executor.run(task_id, messages=[{"role": "user", "content": "test"}], params={})

    assert result.parse_status == "succeeded"

    cur = await db.execute("SELECT COUNT(*) as cnt FROM agent_llm_attempts WHERE task_id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["cnt"] == 2


async def test_execute_exhausted(db):
    from llm_service.runtime.event_bus import EventBus
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.executor import Executor
    from llm_service.providers.mock import MockProvider
    from llm_service.providers.base import ProviderError
    import uuid
    from datetime import datetime, timezone

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    provider = MockProvider(error=ProviderError("timeout", "always fails"))
    executor = Executor(db, mgr, bus, provider)

    task_id = await mgr.submit(caller_domain="mining", pipeline_stage="test", max_attempts=2)
    await db.execute(
        "INSERT INTO agent_llm_requests (id, task_id, provider, model, messages_json, input_json, params_json, expected_output_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), task_id, "mock", "mock-model", "[]", "{}", "{}", "json_object", datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()

    result = await executor.run(task_id, messages=[], params={})
    assert result is None

    cur = await db.execute("SELECT status FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["status"] == "dead_letter"


async def test_execute_records_result_row(db):
    from llm_service.runtime.event_bus import EventBus
    from llm_service.runtime.task_manager import TaskManager
    from llm_service.runtime.executor import Executor
    from llm_service.providers.mock import MockProvider
    import uuid
    from datetime import datetime, timezone

    bus = EventBus(db)
    mgr = TaskManager(db, bus)
    provider = MockProvider(
        responses=[{"choices": [{"message": {"content": '{"name": "test"}'}}]}]
    )
    executor = Executor(db, mgr, bus, provider)

    task_id = await mgr.submit(caller_domain="serving", pipeline_stage="test")
    await db.execute(
        "INSERT INTO agent_llm_requests (id, task_id, provider, model, messages_json, input_json, params_json, expected_output_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), task_id, "mock", "mock-model", "[]", "{}", "{}", "json_object", datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()

    await executor.run(task_id, messages=[], params={})

    cur = await db.execute("SELECT parse_status, parsed_output_json FROM agent_llm_results WHERE task_id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["parse_status"] == "succeeded"
    import json
    assert json.loads(row["parsed_output_json"]) == {"name": "test"}
