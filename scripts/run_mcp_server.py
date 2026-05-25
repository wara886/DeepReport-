"""Run the local FinSight MCP-style tool server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.mcp_http_server import run_mcp_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local MCP-style financial tool server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server, url = run_mcp_server(host=args.host, port=args.port)
    print(f"FinSight MCP-style server running at {url}")
    print(f"Manifest: {url}/mcp/manifest")
    print(f"JSON-RPC: {url}/mcp/rpc")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping MCP server...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
