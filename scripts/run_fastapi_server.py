"""Run the deployable FastAPI service for FinSight."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.api_fastapi import create_fastapi_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FinSight FastAPI service.")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")))
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--output-dir", default="data/outputs/multi_agent")
    parser.add_argument("--report-dir", default="data/reports/multi_agent")
    parser.add_argument("--memory-root", default="memory/chat")
    args = parser.parse_args()
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
