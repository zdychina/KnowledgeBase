"""Mining pipeline configuration — all values from .env.

Uses pydantic-settings to load environment variables, same pattern as pg_config.py.
Mining calls llm_service for both chat (template-based) and embedding.
Only the embedding model name and dimensions need to be configured here;
the actual API key, base URL for embedding are handled by llm_service.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_REPO_ROOT = Path(__file__).resolve().parents[3]  # knowledge_mining/mining/infra/ -> CoreMasterKB/


class MiningConfig(BaseSettings):
    """Mining pipeline configuration, loaded from environment variables.

    Env vars:
        LLM_SERVICE_URL:        llm_service address (default: http://localhost:8900)
        EMBEDDING_MODEL:        model name sent to llm_service embedding endpoint
        EMBEDDING_DIMENSIONS:   embedding vector dimensions
        MINING_LLM_BYPASS_PROXY: bypass system proxy for LLM calls
        DOMAIN_PACK:            default domain pack ID
        MAX_WORKERS:            max concurrent workers for streaming pipeline
    """

    # LLM Service
    llm_service_url: str = "http://localhost:8900"
    mining_llm_bypass_proxy: bool = False

    # Embedding (via llm_service)
    embedding_model: str = "embedding-3"
    embedding_dimensions: int | None = None

    # Pipeline defaults
    domain_pack: str = "cloud_core_network"
    max_workers: int = 4

    model_config = {
        "env_prefix": "",
        "env_file": str(_REPO_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
