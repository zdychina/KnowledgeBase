"""Run Mining API: python -m knowledge_mining.mining.api"""
import asyncio
import copy
import logging
import os
import sys

# Windows: psycopg async requires SelectorEventLoop, not ProactorEventLoop.
# uvicorn hardcodes ProactorEventLoop on Windows, so we monkey-patch its factory.
if sys.platform == "win32":
    import uvicorn.loops.asyncio as _uv_loop  # noqa: E402

    _uv_loop.asyncio_loop_factory = lambda use_subprocess=False: asyncio.SelectorEventLoop

import uvicorn  # noqa: E402
from uvicorn.config import LOGGING_CONFIG  # noqa: E402

from knowledge_mining.mining.api.app import app  # noqa: E402

_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _timestamped_log_config() -> dict:
    """Application + uvicorn logging with timestamps (see llm_service for rationale)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt=_DATEFMT,
    )
    cfg = copy.deepcopy(LOGGING_CONFIG)
    cfg["formatters"]["default"]["fmt"] = "%(asctime)s %(levelprefix)s %(message)s"
    cfg["formatters"]["default"]["datefmt"] = _DATEFMT
    cfg["formatters"]["access"]["fmt"] = (
        '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    cfg["formatters"]["access"]["datefmt"] = _DATEFMT
    return cfg


if __name__ == "__main__":
    port = int(os.environ.get("MINING_API_PORT", "8901"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=_timestamped_log_config())
