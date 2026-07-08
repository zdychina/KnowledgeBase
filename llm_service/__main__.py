"""Run LLM Service: python -m llm_service"""
import asyncio
import sys

# Windows: psycopg async requires SelectorEventLoop, not ProactorEventLoop.
# Set the policy so uvicorn's internal asyncio.run() builds a SelectorEventLoop.
# (uvicorn 0.29's asyncio_setup only switches the policy when use_subprocess=True,
# so we must set it ourselves here.)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402

from llm_service.config import load_llm_config, dig  # noqa: E402
from llm_service.main import set_startup_config  # noqa: E402

cfg = load_llm_config()
set_startup_config(cfg)

uvicorn.run(
    "llm_service.main:create_app_from_startup_config",
    host=dig(cfg, "host"),
    port=dig(cfg, "port"),
    factory=True,
)
