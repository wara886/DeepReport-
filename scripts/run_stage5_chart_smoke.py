#!/usr/bin/env python3
"""Stage 5 smoke runner."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.charts.render import attach_charts_to_report, render_all_charts


def main() -> int:
    metadata = render_all_charts(
        features_root="data/features",
        chart_output_dir="data/outputs/charts",
        metadata_path="data/outputs/chart_metadata.json",
    )
    attach_charts_to_report("data/reports/report.md", metadata)

    print("[stage5] metadata: data/outputs/chart_metadata.json")
    for item in metadata:
        print(f"[stage5] chart: {item['output_path']}")
    print("[stage5] report updated: data/reports/report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

