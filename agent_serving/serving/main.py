"""FastAPI application with PostgreSQL backend.

Reads PG connection from .env (PG_HOST, PG_PORT, etc.) via ServingDbConfig.
Uses psycopg sync pool for all database operations.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from psycopg_pool import ConnectionPool

from agent_serving.serving.api.health import router as health_router
from agent_serving.serving.api.search import router as search_router
from agent_serving.serving.infrastructure.pg_config import ServingDbConfig
from agent_serving.serving.repositories.asset_repo import AssetRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = ServingDbConfig()

    # --- PG startup diagnostics ---
    print("=" * 60)
    print("[PG Diagnostics]")
    print(f"  host:     {config.pg_host}")
    print(f"  port:     {config.pg_port}")
    print(f"  dbname:   {config.pg_dbname}")
    print(f"  user:     {config.pg_user}")
    print(f"  sslmode:  {config.pg_sslmode}")
    print(f"  gssenc:   {config.pg_gssencmode}")
    print(f"  pool:     {config.pg_pool_min}-{config.pg_pool_max}")
    print(f"  conninfo: {config.conninfo.replace(config.pg_password, '***') if config.pg_password else config.conninfo}")
    print("=" * 60)

    pool = config.create_pool()

    try:
        pool.open()
        print("[PG] Pool opened — testing connection ...")
        with pool.connection() as conn:
            result = conn.execute("SELECT version()").fetchone()
            print(f"[PG] Connected! {result['version']}")
            tables = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            ).fetchall()
            print(f"[PG] Tables ({len(tables)}): {[t['tablename'] for t in tables]}")
            release = conn.execute(
                "SELECT id, status, channel FROM asset_publish_releases WHERE status = 'active' LIMIT 5"
            ).fetchall()
            print(f"[PG] Active releases: {len(release)}")
            for r in release:
                print(f"       - id={r['id'][:12]}... status={r['status']} channel={r['channel']}")
    except Exception as e:
        print(f"[PG] CONNECTION FAILED: {type(e).__name__}: {e}")
        print("[PG] Service will start but search WILL NOT work!")
    print("=" * 60)

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
    llm_base_url = os.environ.get("LLM_SERVICE_URL")
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
    pool.close()


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
    """Auto-detect GBK body and re-encode to UTF-8 for Windows curl clients.

    Intercepts the ASGI receive function so the body stream is NOT consumed
    before FastAPI reads it. This keeps the request debuggable in PyCharm.
    """
    if request.method == "POST" and request.headers.get("content-type", "").startswith("application/json"):
        original_receive = request.receive

        async def _gbk_safe_receive():
            message = await original_receive()
            if message.get("type") == "http.request":
                raw = message.get("body", b"")
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        raw = raw.decode("gbk").encode("utf-8")
                        return {**message, "body": raw}
                    except (UnicodeDecodeError, LookupError):
                        pass
            return message

        request.receive = _gbk_safe_receive

    return await call_next(request)


app.include_router(health_router)
app.include_router(search_router)
