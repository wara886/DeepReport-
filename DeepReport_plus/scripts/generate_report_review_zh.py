"""Generate Chinese review-only markdown views for an existing report.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.report_review_zh import generate_report_review_zh


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Chinese human-review views for an existing report.md")
    parser.add_argument(
        "--report-md",
        required=True,
        help="Path to baseline report.md (e.g. data/evaluation/eval_v1/runs/.../reports/report.md)",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root containing data/outputs/checkpoints/verifier_checkpoint.json",
    )
    args = parser.parse_args()

    outputs = generate_report_review_zh(report_md_path=args.report_md, project_root=args.project_root)
    print(f"[review_zh] report_review_zh={outputs['report_review_zh_md']}")
    print(f"[review_zh] review_focus_summary={outputs['review_focus_summary_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
