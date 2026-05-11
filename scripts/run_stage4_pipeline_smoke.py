#!/usr/bin/env python3
"""Stage 4 smoke runner."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.app.pipeline import run_pipeline


def main() -> int:
    result = run_pipeline(output_dir="data/outputs", report_dir="data/reports")
    for key, value in result.items():
        print(f"[stage4] {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

