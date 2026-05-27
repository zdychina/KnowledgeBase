"""Run Mining API: python -m knowledge_mining.mining.api"""
import asyncio
import os
import sys

# Windows: psycopg async requires SelectorEventLoop, not ProactorEventLoop.
# uvicorn hardcodes ProactorEventLoop on Windows, so we monkey-patch its factory.
if sys.platform == "win32":
    import uvicorn.loops.asyncio as _uv_loop  # noqa: E402

    _uv_loop.asyncio_loop_factory = lambda use_subprocess=False: asyncio.SelectorEventLoop

import uvicorn  # noqa: E402

from knowledge_mining.mining.api.app import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("MINING_API_PORT", "8901"))
    uvicorn.run(app, host="0.0.0.0", port=port)
