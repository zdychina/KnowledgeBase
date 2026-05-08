"""Run the agent serving API server.

Usage:
    python -m agent_serving.scripts.run_serving
    python -m agent_serving.scripts.run_serving --port 8080
"""

import argparse
import asyncio
from pathlib import Path

# Load .env into os.environ BEFORE any app imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cloud Core Knowledge Backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

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
