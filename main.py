"""
FinSight - Server entry point with mode-aware configuration.

Usage:
    python main.py                           # user mode on port 7860
    python main.py --mode developer          # developer mode on port 7861
    python main.py --port 8080 --mode user   # custom port + mode
    python main.py --host 0.0.0.0            # expose on LAN / container
    python main.py --mode developer --output-dir data/shared --report-dir data/shared_reports
"""

from __future__ import annotations

import argparse
import os

import uvicorn

from src.app.api_fastapi import create_fastapi_app
from src.utils.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="FinSight DeepReport++ Web UI")
    parser.add_argument("--port", type=int, default=7860, help="Server port")
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "127.0.0.1"),
        help="Bind host. Use 0.0.0.0 only when exposing the service outside this machine.",
    )
    parser.add_argument(
        "--mode", default="user", choices=["user", "developer"],
        help="Server mode (user = simplified UI, developer = full diagnostics)",
    )
    parser.add_argument("--output-dir", default=None, help="Output root (default: auto per mode)")
    parser.add_argument("--report-dir", default=None, help="Report root (default: auto per mode)")
    args = parser.parse_args()

    # 初始化日志
    configure_logging(log_dir="logs", run_name="webui_{}_{}".format(args.mode, args.port))

    # Mode-aware default directories
    if args.output_dir is None:
        output_dir = "data/outputs_user" if args.mode == "user" else "data/outputs_dev"
    else:
        output_dir = args.output_dir

    if args.report_dir is None:
        report_dir = "data/reports_user" if args.mode == "user" else "data/reports_dev"
    else:
        report_dir = args.report_dir

    app = create_fastapi_app(
        mode=args.mode,
        output_dir=output_dir,
        report_dir=report_dir,
        frontend_port=args.port,
    )

    local_url = "http://127.0.0.1:{}/".format(args.port)
    print("=" * 60)
    print("  FinSight DeepReport++")
    print("  Open: {}".format(local_url))
    if args.host == "0.0.0.0":
        print("  Bound to 0.0.0.0 for external access; use 127.0.0.1 or localhost in this browser.")
    print("=" * 60)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
