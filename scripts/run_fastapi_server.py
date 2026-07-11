"""Run the deployable FastAPI service for FinSight."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


REQUIRED_RUNTIME_MODULES = (
    ("langgraph.graph", "langgraph"),
    ("langgraph.checkpoint.sqlite", "langgraph-checkpoint-sqlite"),
)


def dependency_preflight() -> list[str]:
    """Return actionable missing runtime packages before importing the app graph."""

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
    parser = argparse.ArgumentParser(description="Run the FinSight FastAPI service.")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")))
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--output-dir", default="data/outputs/multi_agent")
    parser.add_argument("--report-dir", default="data/reports/multi_agent")
    parser.add_argument("--memory-root", default="memory/chat")
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
    from src.app.api_fastapi import create_fastapi_app

    app = create_fastapi_app(
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        config_path=args.config_path,
        memory_root=args.memory_root,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
