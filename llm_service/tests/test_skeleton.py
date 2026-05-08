import pytest

pytestmark = pytest.mark.asyncio


async def test_db_init_creates_all_tables(db):
    """All agent_llm_* tables must exist after init."""
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'agent_llm_%' ORDER BY name"
    )
    tables = [row[0] for row in await cursor.fetchall()]
    expected = [
        "agent_llm_attempts",
        "agent_llm_events",
        "agent_llm_model_calls",
        "agent_llm_prompt_templates",
        "agent_llm_requests",
        "agent_llm_results",
        "agent_llm_tasks",
    ]
    assert tables == expected


async def test_tasks_table_has_task_type(db):
    """agent_llm_tasks should have task_type column after migration."""
    cursor = await db.execute("PRAGMA table_info(agent_llm_tasks)")
    columns = {row["name"] for row in await cursor.fetchall()}
    assert "task_type" in columns


async def test_config_defaults():
    from llm_service.config import LLMServiceConfig

    cfg = LLMServiceConfig()
    assert cfg.port == 8900
    assert cfg.default_max_attempts == 3
    assert cfg.retry_backoff_base == 2.0


async def test_fastapi_app_creates():
    from llm_service.main import create_app

    app = create_app(start_worker=False)
    assert app.title == "LLM Service"


async def test_submit_embedding_task(api_client):
    """POST /api/v1/tasks/embed creates an embedding task."""
    resp = await api_client.post("/api/v1/tasks/embed", json={
        "input": ["hello world", "test text"],
        "caller_domain": "test",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "queued"


async def test_submit_rerank_task(api_client):
    """POST /api/v1/tasks/rerank creates a rerank task."""
    resp = await api_client.post("/api/v1/tasks/rerank", json={
        "query": "what is 5G",
        "documents": ["5G is a cellular network", "4G is older"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "queued"


async def test_task_type_stored_in_db(api_client):
    """Embedding tasks should have task_type='embedding' in the DB."""
    resp = await api_client.post("/api/v1/tasks/embed", json={
        "input": ["test"],
    })
    task_id = resp.json()["task_id"]

    # Query the DB directly
    db = api_client._transport.app.state.db
    cur = await db.execute("SELECT task_type FROM agent_llm_tasks WHERE id = ?", (task_id,))
    row = await cur.fetchone()
    assert row["task_type"] == "embedding"
