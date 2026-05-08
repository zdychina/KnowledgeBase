"""FastAPI application with PostgreSQL backend.

Reads PG connection from .env (PG_HOST, PG_PORT, etc.) via ServingDbConfig.
Uses psycopg async pool for all database operations.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

# Windows: psycopg async requires SelectorEventLoop, not ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from psycopg_pool import AsyncConnectionPool

from agent_serving.serving.api.health import router as health_router
from agent_serving.serving.api.search import router as search_router
from agent_serving.serving.infrastructure.pg_config import ServingDbConfig
from agent_serving.serving.repositories.asset_repo import AssetRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = ServingDbConfig()
    pool = config.create_pool()
    await pool.open()
    app.state.pool = pool
    app.state.embedding_dimensions = config.embedding_dimensions

    # Cache domain profile if configured
    domain_id = os.environ.get("COREMASTERKB_DOMAIN")
    if domain_id:
        try:
            from agent_serving.serving.domain_pack_reader import load_serving_profile
            app.state.domain_profile = load_serving_profile(domain_id)
        except Exception:
            app.state.domain_profile = None
    else:
        app.state.domain_profile = None

    # Initialize LLM client (lazy — no health check at startup)
    app.state.llm_client = None
    if llm_base_url:
        try:
            from agent_serving.serving.infrastructure.llm_client import ServingLlmClient
            app.state.llm_client = ServingLlmClient(base_url=llm_base_url)
            logger.info("LLM client configured for %s (availability checked at first use)", llm_base_url)
    except Exception:
        logger.warning("Failed to initialize LLM client, using rule fallback", exc_info=True)

    # Initialize embedding generator
    app.state.embedding_generator = None
    embedding_api_key = os.environ.get("EMBEDDING_API_KEY")
    if embedding_api_key:
        try:
            from agent_serving.serving.infrastructure.embedding import EmbeddingGenerator
            app.state.embedding_generator = EmbeddingGenerator(
                api_key=embedding_api_key,
                model=os.environ.get("EMBEDDING_MODEL"),
                base_url=os.environ.get("EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
                dimensions=int(d) if (d := os.environ.get("EMBEDDING_DIMENSIONS")) else None,
            )
            logger.info("Embedding generator initialized (model=%s)", os.environ.get("EMBEDDING_MODEL"))
        except Exception:
            logger.warning("Failed to initialize embedding generator", exc_info=True)

    yield

    # Cleanup
    if app.state.llm_client:
        await app.state.llm_client.close()
    await pool.close()


async def get_repo(request: Request) -> AssetRepository:
    return AssetRepository(request.app.state.pool)


app = FastAPI(
    title="Cloud Core Knowledge Backend",
    version="0.4.0",
    description="Agent Knowledge Backend for cloud core network — Retrieval Orchestrator (PostgreSQL).",
    lifespan=lifespan,
)


@app.middleware("http")
async def reencode_body_to_utf8(request: Request, call_next):
    """Auto-detect GBK body and re-encode to UTF-8 for Windows curl clients."""
    if request.method == "POST" and request.headers.get("content-type", "").startswith("application/json"):
        body = await request.body()
        try:
            body.decode("utf-8")
        except UnicodeDecodeError:
            try:
                body = body.decode("gbk").encode("utf-8")
                request._body = body
            except (UnicodeDecodeError, LookupError):
                pass
    return await call_next(request)


app.include_router(health_router)
app.include_router(search_router)
