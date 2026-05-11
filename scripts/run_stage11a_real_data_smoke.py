#!/usr/bin/env python3
"""Stage 11A smoke runner for real_data/local_file minimal closed-loop."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.app.stage11a_real_data_pipeline import run_real_data_pipeline


def main() -> int:
    outputs = run_real_data_pipeline("configs/local_real_smoke.yaml")
    for k, v in outputs.items():
        print(f"[stage11a] {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

