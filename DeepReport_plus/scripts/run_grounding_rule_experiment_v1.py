"""CLI entry for grounding rule experiment v1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.grounding_rule_experiment import ExperimentPaths, auto_discover_paths, run_grounding_rule_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description="Run standalone grounding rule experiment v1.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--claim-table", default="")
    parser.add_argument("--review-csv", default="")
    parser.add_argument("--manifest-json", default="")
    parser.add_argument("--verification-report", default="")
    parser.add_argument("--output-dir", default="artifacts/grounding_rule_experiment_v1")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if args.claim_table and args.review_csv and args.manifest_json:
        paths = ExperimentPaths(
            claim_table=(root / args.claim_table).resolve() if not Path(args.claim_table).is_absolute() else Path(args.claim_table),
            review_csv=(root / args.review_csv).resolve() if not Path(args.review_csv).is_absolute() else Path(args.review_csv),
            manifest_json=(root / args.manifest_json).resolve()
            if not Path(args.manifest_json).is_absolute()
            else Path(args.manifest_json),
            verification_report=(
                (root / args.verification_report).resolve()
                if (args.verification_report and not Path(args.verification_report).is_absolute())
                else (Path(args.verification_report) if args.verification_report else None)
            ),
            output_dir=(root / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir),
        )
    else:
        paths = auto_discover_paths(root)
        if args.output_dir:
            paths.output_dir = (root / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)

    summary = run_grounding_rule_experiment(paths)
    print(f"[grounding_rule_experiment_v1] summary_json={summary['outputs']['summary_json']}")
    print(f"[grounding_rule_experiment_v1] summary_md={summary['outputs']['summary_md']}")
    print(f"[grounding_rule_experiment_v1] per_claim_csv={summary['outputs']['per_claim_csv']}")
    print(f"[grounding_rule_experiment_v1] evidence_lookup_csv={summary['outputs']['evidence_lookup_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
