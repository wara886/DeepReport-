"""Run Stage12 local correction phase v1 (offline, baseline-preserving)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.local_correction_v1 import run_local_correction_v1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local correction phase v1.")
    parser.add_argument(
        "--template-csv",
        default="reports/eval_v1_diagnostics/diag_20260418_cn_final/spot_check_10_root_cause_template.csv",
    )
    parser.add_argument("--eval-output-root", default="data/evaluation/eval_v1")
    parser.add_argument("--eval-case-path", default="data/eval_v1/cases.jsonl")
    parser.add_argument(
        "--threshold-scan-json",
        default="reports/eval_v1_diagnostics/diag_20260418_cn_final/verifier_threshold_scan/threshold_scan.json",
    )
    parser.add_argument("--output-root", default="reports/local_correction_v1")
    parser.add_argument("--primary-variant", default="bm25_real_writer")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    index = run_local_correction_v1(
        template_csv_path=args.template_csv,
        eval_output_root=args.eval_output_root,
        eval_case_path=args.eval_case_path,
        threshold_scan_json=args.threshold_scan_json,
        output_root=args.output_root,
        primary_variant=args.primary_variant,
        run_id=args.run_id,
    )
    print(f"[local_correction_v1] run_id={index['run_id']}")
    print(f"[local_correction_v1] run_index={Path(args.output_root) / index['run_id'] / 'run_index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

