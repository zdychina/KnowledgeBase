"""FastAPI application with SQLite dev mode and DB injection.

Supports two modes:
- Production: COREMASTERKB_ASSET_DB_PATH points to Mining-generated SQLite DB
- Dev/test: in-memory SQLite with shared DDL (no data by default)

v2: Initializes LLM client, embedding generator, and caches DomainProfile.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, Request

from agent_serving.serving.api.health import router as health_router
from agent_serving.serving.api.search import router as search_router
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite
from agent_serving.serving.domain_pack_reader import load_serving_profile

logger = logging.getLogger(__name__)

_DB_PATH_ENV = "COREMASTERKB_ASSET_DB_PATH"
_DOMAIN_ENV = "COREMASTERKB_DOMAIN"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get(_DB_PATH_ENV)
    if db_path:
        # Read-only connection to Mining-generated SQLite DB
        db = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        # Dev/test mode: in-memory with shared DDL
        db = await aiosqlite.connect(":memory:")
        await create_asset_tables_sqlite(db)
    db.row_factory = aiosqlite.Row
    app.state.db = db

    # Cache domain profile if configured
    domain_id = os.environ.get(_DOMAIN_ENV)
    if domain_id:
        try:
            app.state.domain_profile = load_serving_profile(domain_id)
        except Exception:
            pass  # Domain pack not found, will use defaults
    else:
        app.state.domain_profile = None

    # Initialize LLM client (lazy — no health check at startup)
    app.state.llm_client = None
    try:
        from agent_serving.serving.infrastructure.llm_client import ServingLlmClient
        llm_base_url = os.environ.get("LLM_SERVICE_URL", "http://localhost:8900")
        app.state.llm_client = ServingLlmClient(base_url=llm_base_url)
        logger.info("LLM client configured for %s (availability checked at first use)", llm_base_url)
    except Exception:
        logger.warning("Failed to initialize LLM client, using rule fallback", exc_info=True)

    # Initialize embedding generator
    app.state.embedding_generator = None
    embedding_api_key = os.environ.get("EMBEDDING_API_KEY")
    if embedding_api_key:
        try:
            from knowledge_mining.mining.embedding import ZhipuEmbeddingGenerator
            app.state.embedding_generator = ZhipuEmbeddingGenerator(
                api_key=embedding_api_key,
                model=os.environ.get("EMBEDDING_MODEL", "embedding-3"),
                base_url=os.environ.get("EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
                dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", "2048")),
            )
            logger.info("Embedding generator initialized (model=%s)", os.environ.get("EMBEDDING_MODEL", "embedding-3"))
        except Exception:
            logger.warning("Failed to initialize embedding generator", exc_info=True)

    yield

    # Cleanup
    if app.state.llm_client:
        app.state.llm_client.close()
    await db.close()


def get_repo(request: Request) -> AssetRepository:
    return AssetRepository(request.app.state.db)


app = FastAPI(
    title="Cloud Core Knowledge Backend",
    version="0.2.0",
    description="Agent Knowledge Backend for cloud core network — Retrieval Orchestrator.",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(search_router)
