"""CLI entry for review_coverage_expansion_v1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.review_coverage_expansion_v1 import run_review_coverage_expansion_v1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run review coverage expansion v1.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--eval-runs-dir", default="data/evaluation/eval_v1/runs")
    parser.add_argument("--output-dir", default="artifacts/review_coverage_expansion_v1")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    summary = run_review_coverage_expansion_v1(
        project_root=root,
        eval_runs_dir=args.eval_runs_dir,
        output_dir=args.output_dir,
    )
    outputs = dict(summary.get("outputs", {}))
    print(f"[review_coverage_expansion_v1] case_inventory_csv={outputs.get('case_inventory_csv', '')}")
    print(f"[review_coverage_expansion_v1] review_queue_csv={outputs.get('review_queue_csv', '')}")
    print(f"[review_coverage_expansion_v1] review_template_csv={outputs.get('review_template_csv', '')}")
    print(f"[review_coverage_expansion_v1] coverage_summary_json={outputs.get('coverage_summary_json', '')}")
    print(f"[review_coverage_expansion_v1] coverage_summary_md={outputs.get('coverage_summary_md', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
