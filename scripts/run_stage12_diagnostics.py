"""Run Stage12 diagnostic-only reports and ablation."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.diagnostic_ablation import run_diagnostic_ablation
from src.evaluation.diagnostic_reports import (
    build_metric_sanity_report,
    build_spot_check_root_cause_summary,
    build_spot_check_root_cause_template,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage12 diagnostic-only reports.")
    parser.add_argument("--eval-output-root", default="data/evaluation/eval_v1")
    parser.add_argument("--baseline-report-root", default="reports/eval_v1")
    parser.add_argument("--eval-case-path", default="data/eval_v1/cases.jsonl")
    parser.add_argument("--diagnostic-output-root", default="reports/eval_v1_diagnostics")
    parser.add_argument("--primary-variant", default="bm25_real_writer")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    run_id = args.run_id or "diag_run"
    run_root = Path(args.diagnostic_output_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    baseline_spot = Path(args.baseline_report_root) / "spot_check_10.csv"
    if not baseline_spot.exists():
        raise FileNotFoundError(f"spot_check_10.csv not found under baseline report root: {baseline_spot}")
    shutil.copy2(baseline_spot, run_root / "spot_check_10.csv")

    sanity = build_metric_sanity_report(
        eval_output_root=args.eval_output_root,
        report_root=run_root,
        eval_case_path=args.eval_case_path,
        primary_variant=args.primary_variant,
    )
    template = build_spot_check_root_cause_template(report_root=run_root)
    spot_summary = build_spot_check_root_cause_summary(report_root=run_root)
    comparison = run_diagnostic_ablation(
        eval_output_root=args.eval_output_root,
        baseline_report_root=args.baseline_report_root,
        eval_case_path=args.eval_case_path,
        output_root=args.diagnostic_output_root,
        primary_variant=args.primary_variant,
        run_id=run_id,
    )
    print(f"[stage12_diag] 指标健康诊断（metric_sanity_report）: {sanity['outputs']['metric_sanity_report_md']}")
    print(f"[stage12_diag] 根因回填模板（root_cause_template）: {template['spot_check_root_cause_template_csv']}")
    print(f"[stage12_diag] 根因频次统计（root_cause_frequency）: {spot_summary['spot_check_root_cause_frequency_json']}")
    print(f"[stage12_diag] 诊断并排对比（comparison_summary）: {comparison['outputs']['comparison_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
