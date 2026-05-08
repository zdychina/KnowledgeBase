"""Run the agent serving API server.

Usage:
    python -m agent_serving.scripts.run_serving
    python -m agent_serving.scripts.run_serving --port 8080
"""

import argparse
import asyncio
import sys

# Must be set BEFORE any async import on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    parser = argparse.ArgumentParser(description="Cloud Core Knowledge Backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    # On Windows, uvicorn defaults to ProactorEventLoop which breaks psycopg.
    # Force SelectorEventLoop via custom server factory.
    config = uvicorn.Config(
        "agent_serving.serving.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
