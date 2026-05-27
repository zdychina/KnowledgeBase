import pytest

pytestmark = pytest.mark.asyncio


async def test_client_build_payload():
    from llm_service.client import LLMClient

    client = LLMClient(base_url="http://test")
    payload = client._build_submit_payload(
        caller_service="mining",
        knowledge_domain="cloud_core_network",
        pipeline_stage="extract",
        messages=[{"role": "user", "content": "test"}],
        idempotency_key="k1",
    )
    assert payload["caller_service"] == "mining"
    assert payload["knowledge_domain"] == "cloud_core_network"
    assert payload["pipeline_stage"] == "extract"
    assert payload["idempotency_key"] == "k1"


async def test_client_execute_against_server(api_client):
    from llm_service.client import LLMClient

    c = LLMClient(base_url="http://test", http_client=api_client)
    result = await c.execute(
        caller_service="mining",
        knowledge_domain="cloud_core_network",
        pipeline_stage="test",
        messages=[{"role": "user", "content": "test"}],
    )
    assert result["status"] == "succeeded"
    assert "task_id" in result


async def test_client_submit_and_get_task(api_client):
    from llm_service.client import LLMClient

    c = LLMClient(base_url="http://test", http_client=api_client)
    task_id = await c.submit(
        caller_service="serving",
        knowledge_domain="generic",
        pipeline_stage="search",
        messages=[{"role": "user", "content": "query"}],
    )
    assert task_id is not None

    task = await c.get_task(task_id)
    assert task["id"] == task_id
    assert task["status"] == "queued"


async def test_client_cancel(api_client):
    from llm_service.client import LLMClient

    c = LLMClient(base_url="http://test", http_client=api_client)
    task_id = await c.submit(
        caller_service="mining",
        knowledge_domain="cloud_core_network",
        pipeline_stage="test",
        messages=[{"role": "user", "content": "cancel me"}],
    )
    await c.cancel(task_id)
    task = await c.get_task(task_id)
    assert task["status"] == "cancelled"


async def test_client_embed(api_client):
    from llm_service.client import LLMClient

    c = LLMClient(base_url="http://test", http_client=api_client)
    result = await c.embed(
        ["alpha", "beta"],
        caller_service="serving",
        knowledge_domain="cloud_core_network",
        pipeline_stage="embedding",
    )
    assert result["model"] == "embedding-3"
    assert [item["index"] for item in result["data"]] == [0, 1]


async def test_client_rerank(api_client):
    from llm_service.client import LLMClient

    c = LLMClient(base_url="http://test", http_client=api_client)
    result = await c.rerank(
        query="what is upf",
        documents=["doc-1", "doc-2"],
        top_n=1,
        caller_service="serving",
        knowledge_domain="cloud_core_network",
        pipeline_stage="rerank",
    )
    assert result["model"] == "rerank-pro"
    assert len(result["results"]) == 1
    assert result["results"][0]["index"] == 0
