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


# Integration tests below require a running llm_service with real PostgreSQL.
# Run manually: python -m pytest llm_service/tests/test_client.py -v --run-integration

@pytest.mark.skip(reason="Integration test — requires running llm_service")
async def test_client_execute_against_server():
    pass


@pytest.mark.skip(reason="Integration test — requires running llm_service")
async def test_client_submit_and_get_task():
    pass


@pytest.mark.skip(reason="Integration test — requires running llm_service")
async def test_client_cancel():
    pass


@pytest.mark.skip(reason="Integration test — requires running llm_service")
async def test_client_embed():
    pass


@pytest.mark.skip(reason="Integration test — requires running llm_service")
async def test_client_rerank():
    pass
