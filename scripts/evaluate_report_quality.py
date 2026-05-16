"""Evaluate objective quality for a generated DeepReport++ run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.report_quality import evaluate_report_quality, write_quality_outputs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate generated report quality.")
    parser.add_argument("--run-dir", required=True, help="Run root, company dir, outputs dir, or eval output dir.")
    parser.add_argument("--fail-on-gate", action="store_true", help="Return non-zero when objective_pass is false.")
    args = parser.parse_args()

    report = evaluate_report_quality(args.run_dir)
    paths = write_quality_outputs(args.run_dir, report)
    print(json.dumps({"objective_pass": report["objective_pass"], "total_score": report["total_score"], **paths}, ensure_ascii=False, indent=2))
    if args.fail_on_gate and not report["objective_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
