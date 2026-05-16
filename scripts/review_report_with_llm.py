"""Run LLM/Codex-style subjective review for a generated report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.llm_report_review import review_report_with_llm, write_llm_review_outputs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Review generated report quality with configured LLM.")
    parser.add_argument("--run-dir", required=True, help="Run root, company dir, outputs dir, or eval output dir.")
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--fail-on-gate", action="store_true", help="Return non-zero when llm_review_pass is false.")
    args = parser.parse_args()

    review = review_report_with_llm(run_dir=args.run_dir, config_path=args.config_path)
    paths = write_llm_review_outputs(args.run_dir, review)
    print(
        json.dumps(
            {
                "llm_review_pass": review["llm_review_pass"],
                "total_score": review["total_score"],
                "model_status": review.get("model_status"),
                **paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.fail_on_gate and not review["llm_review_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
