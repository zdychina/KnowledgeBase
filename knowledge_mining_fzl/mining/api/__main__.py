"""Run Mining API: python -m knowledge_mining.mining.api"""
import asyncio
import os
import sys

# Windows: psycopg async requires SelectorEventLoop, not ProactorEventLoop.
# uvicorn hardcodes ProactorEventLoop on Windows, so we monkey-patch its factory.
if sys.platform == "win32":
    import uvicorn.loops.asyncio as _uv_loop

    _uv_loop.asyncio_loop_factory = lambda use_subprocess=False: asyncio.SelectorEventLoop

import uvicorn

port = int(os.environ.get("MINING_API_PORT", "8901"))
uvicorn.run(
    "knowledge_mining_fzl.mining.api.app:app",
    host="0.0.0.0",
    port=port,
)
