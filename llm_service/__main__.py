"""Run LLM Service: python -m llm_service"""
import asyncio
import sys

import uvicorn

from llm_service.config import LLMServiceConfig

cfg = LLMServiceConfig()
config = uvicorn.Config(
    "llm_service.main:create_app",
    host=cfg.host,
    port=cfg.port,
    factory=True,
)
server = uvicorn.Server(config)

if sys.platform == "win32":
    # psycopg async is incompatible with ProactorEventLoop (Windows default).
    asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
else:
    asyncio.run(server.serve())
