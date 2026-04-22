"""CLI for grounding_rule_experiment_v2_batch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.grounding_rule_experiment_v2_batch import run_grounding_rule_experiment_v2_batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Run grounding_rule_experiment_v2_batch.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--eval-runs-dir", default="data/evaluation/eval_v1/runs")
    parser.add_argument("--output-dir", default="artifacts/grounding_rule_experiment_v2_batch")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    summary = run_grounding_rule_experiment_v2_batch(
        project_root=root,
        eval_runs_dir=args.eval_runs_dir,
        output_dir=args.output_dir,
    )
    outputs = dict(summary.get("outputs", {}))
    print(f"[grounding_rule_experiment_v2_batch] batch_summary_json={outputs.get('batch_summary_json', '')}")
    print(f"[grounding_rule_experiment_v2_batch] batch_summary_md={outputs.get('batch_summary_md', '')}")
    print(f"[grounding_rule_experiment_v2_batch] per_case_summary_csv={outputs.get('per_case_summary_csv', '')}")
    print(f"[grounding_rule_experiment_v2_batch] per_claim_all_csv={outputs.get('per_claim_all_csv', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
