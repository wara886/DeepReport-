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
import importlib.util
import os
import sys

import uvicorn

from src.app.api_fastapi import create_fastapi_app
from src.utils.logging import configure_logging


REQUIRED_RUNTIME_MODULES = (
    ("langgraph.graph", "langgraph"),
    ("langgraph.checkpoint.sqlite", "langgraph-checkpoint-sqlite"),
)


def dependency_preflight() -> list[str]:
    """Return actionable missing runtime packages before app startup."""

    missing: list[str] = []
    for module_name, package_name in REQUIRED_RUNTIME_MODULES:
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, AttributeError):
            available = False
        if not available:
            missing.append(package_name)
    return missing


def main() -> int:
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

    missing = dependency_preflight()
    if missing:
        packages = " ".join(sorted(set(missing)))
        print(
            f"FinSight cannot start because runtime dependencies are missing: {packages}. "
            f"Install them with: python -m pip install {packages}",
            file=sys.stderr,
        )
        return 2

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
    )

    local_url = "http://127.0.0.1:{}/".format(args.port)
    print("=" * 60)
    print("  FinSight DeepReport++")
    print("  Open: {}".format(local_url))
    if args.host == "0.0.0.0":
        print("  Bound to 0.0.0.0 for external access; use 127.0.0.1 or localhost in this browser.")
    print("=" * 60)

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
