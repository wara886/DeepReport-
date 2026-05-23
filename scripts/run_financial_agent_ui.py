"""Run the local DeepReport+ financial multi-agent web UI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.web_ui import run_ui_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the DeepReport+ local web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--output-dir", default="data/outputs/multi_agent")
    parser.add_argument("--report-dir", default="data/reports/multi_agent")
    parser.add_argument("--memory-root", default="memory/chat")
    args = parser.parse_args()

    server, url = run_ui_server(
        host=args.host,
        port=args.port,
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        config_path=args.config_path,
        memory_root=args.memory_root,
    )
    print(f"DeepReport+ UI running at {url}")
    print("Open the URL in your browser, then click Run Multi-Agent Report.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping UI server...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
