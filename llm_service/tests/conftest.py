import pytest

# Use auto mode for llm_service tests
pytest_plugins = []

collect_ignore_glob = []


def pytest_configure(config):
    """Override asyncio mode for llm_service tests."""
    config.option.asyncio_mode = "auto"


@pytest.fixture
async def db(tmp_path):
    """Create a fresh test database with schema initialized."""
    from llm_service.db import init_db

    db_path = str(tmp_path / "test_llm.sqlite")
    conn = await init_db(db_path)
    yield conn
    await conn.close()


@pytest.fixture
def config(tmp_path):
    from llm_service.config import LLMServiceConfig

    return LLMServiceConfig(
        db_path=str(tmp_path / "test_llm.sqlite"),
        provider_base_url="http://localhost:11434/v1",
        provider_api_key="test-key",
        provider_model="test-model",
    )


def _mock_provider():
    from llm_service.providers.mock import MockProvider

    return MockProvider(
        responses=[{"choices": [{"message": {"content": '{"answer": 42}'}}]}]
    )


def _mock_model_provider():
    class MockModelProvider:
        async def embed(self, texts, *, model=None, dimensions=None):
            return {
                "model": model or "embedding-3",
                "data": [
                    {"index": idx, "embedding": [float(idx + 1), float(len(text))]}
                    for idx, text in enumerate(texts)
                ],
                "usage": {"prompt_tokens": sum(len(text) for text in texts)},
            }

        async def rerank(self, query, documents, *, model=None, top_n=None):
            limit = top_n or len(documents)
            results = [
                {
                    "index": idx,
                    "relevance_score": float(limit - idx) / float(limit),
                    "document": documents[idx],
                }
                for idx in range(min(limit, len(documents)))
            ]
            return {
                "model": model or "rerank",
                "results": results,
            }

    return MockModelProvider()


@pytest.fixture
async def api_client(tmp_path):
    """HTTP client pointing at a test ASGI app with MockProvider."""
    from httpx import ASGITransport, AsyncClient

    from llm_service.config import LLMServiceConfig
    from llm_service.main import create_app

    cfg = LLMServiceConfig(
        db_path=str(tmp_path / "test_api.sqlite"),
        provider_base_url="http://localhost:11434/v1",
        provider_api_key="test-key",
        provider_model="test-model",
    )
    app = create_app(
        cfg,
        provider_factory=_mock_provider,
        model_provider_factory=_mock_model_provider,
        start_worker=False,
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
