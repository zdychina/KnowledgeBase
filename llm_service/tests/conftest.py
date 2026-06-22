import pytest

# Use auto mode for llm_service tests
pytest_plugins = []

collect_ignore_glob = []

# Single test config dict — import from test files as:
#   from llm_service.tests.conftest import TEST_CFG
TEST_CFG = {
    "host": "0.0.0.0",
    "port": 8900,
    "provider": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "test-key",
        "model": "test-model",
        "headers": {},
        "timeout": 30,
        "bypass_proxy": False,
    },
    "embedding": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "test-key",
        "model": "embedding-3",
        "dimensions": 1024,
    },
    "rerank": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "test-key",
        "model": "rerank-pro",
    },
    "model": {
        "timeout": 60,
        "bypass_proxy": False,
        "extra_headers": {},
    },
    "worker": {
        "concurrency": 4,
        "poll_interval": 1.0,
    },
    "persist_writer": {
        "queue_size": 10000,
        "batch_size": 20,
        "flush_interval": 0.5,
        "writer_count": 1,
    },
    "task": {
        "default_max_attempts": 3,
        "retry_backoff_base": 2.0,
        "retry_backoff_max": 60.0,
        "execute_timeout": 60,
        "lease_duration": 300,
        "lease_recovery_interval": 30.0,
    },
    "template": {
        "cache_ttl": 300.0,
    },
}


def pytest_configure(config):
    """Override asyncio mode for llm_service tests."""
    config.option.asyncio_mode = "auto"


@pytest.fixture
def config():
    return TEST_CFG
