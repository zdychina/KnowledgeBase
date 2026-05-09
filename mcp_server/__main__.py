"""Entry point for `python -m mcp_server`.

Transport modes:
  stdio           — default, for Claude Code local integration
  streamable-http — HTTP mode, for network exposure / Postman testing
  sse             — SSE mode, for legacy MCP clients

Controlled by MCP_TRANSPORT env var, or --transport CLI flag.
Host/port via MCP_HOST / MCP_PORT env vars, or --host / --port CLI flags.
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Cloud Core Knowledge MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=None,
        help="Transport mode (default: MCP_TRANSPORT env var, or stdio)",
    )
    parser.add_argument("--host", default=None, help="HTTP bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="HTTP bind port (default: 9000)")
    args = parser.parse_args()

    transport = args.transport or os.environ.get("MCP_TRANSPORT", "stdio")

    # Set env vars before importing server (FastMCP reads them in constructor)
    if args.host:
        os.environ["MCP_HOST"] = args.host
    if args.port:
        os.environ["MCP_PORT"] = str(args.port)

    from mcp_server.server import mcp

    if transport in ("streamable-http", "sse"):
        host = os.environ.get("MCP_HOST", "0.0.0.0")
        port = os.environ.get("MCP_PORT", "9000")
        print(f"MCP Server starting on http://{host}:{port} (transport={transport})")

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
