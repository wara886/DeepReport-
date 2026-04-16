#!/usr/bin/env python3
"""Stage 10 smoke runner for final report export."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.templates.exporter import export_reports


def main() -> int:
    outputs = export_reports(
        claim_path="data/outputs/claim_table.json",
        chart_meta_path="data/outputs/chart_metadata.json",
        report_dir="data/reports",
    )
    for k, v in outputs.items():
        print(f"[stage10] {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

