#!/usr/bin/env python3
"""Stage 6 smoke runner for generation backend abstraction."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.app.pipeline import run_pipeline


def main() -> int:
    # 1) backend_generate + mock backend (expected success through backend)
    result_mock = run_pipeline(
        output_dir="data/outputs",
        report_dir="data/reports",
        writer_mode="backend_generate",
        writer_backend="mock",
    )
    print(f"[stage6] backend_generate(mock) -> {result_mock['report_markdown']}")

    # 2) backend_generate + local_small backend (expected fallback to template)
    result_fallback = run_pipeline(
        output_dir="data/outputs",
        report_dir="data/reports",
        writer_mode="backend_generate",
        writer_backend="local_small",
    )
    print(f"[stage6] backend_generate(local_small fallback) -> {result_fallback['report_markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

