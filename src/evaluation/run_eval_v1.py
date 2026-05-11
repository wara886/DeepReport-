"""Run regression_v1 on eval_v1 and emit fixed report outputs."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import yaml

from src.evaluation.stage12a_harness import run_stage12a_evaluation
from src.evaluation.summarize_eval_v1 import build_regression_v1_outputs


def _build_temp_config(
    base_config_path: Path,
    output_root: str,
    eval_case_path: str,
    max_samples: int | None,
) -> Path:
    cfg = yaml.safe_load(base_config_path.read_text(encoding="utf-8")) or {}
    evaluation = dict(cfg.get("evaluation", {}))
    evaluation["output_root"] = output_root
    evaluation["eval_case_path"] = eval_case_path
    if max_samples is not None:
        evaluation["max_samples"] = int(max_samples)
    cfg["evaluation"] = evaluation

    fd, tmp_raw = tempfile.mkstemp(prefix=".tmp_eval_v1_", suffix=".yaml", dir=base_config_path.parent)
    os.close(fd)
    Path(tmp_raw).unlink(missing_ok=True)
    tmp_path = Path(tmp_raw)
    tmp_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return tmp_path


def run_eval_v1(
    config_path: str = "configs/evaluation_stage12a.yaml",
    eval_output_root: str = "data/evaluation/eval_v1",
    eval_case_path: str = "data/eval_v1/cases.jsonl",
    report_root: str = "reports/eval_v1",
    primary_variant: str = "bm25_real_writer",
    max_samples: int | None = None,
) -> dict:
    base = Path(config_path)
    if not base.exists():
        raise FileNotFoundError(f"Config file not found: {base}")
    temp_cfg = _build_temp_config(
        base_config_path=base,
        output_root=eval_output_root,
        eval_case_path=eval_case_path,
        max_samples=max_samples,
    )
    try:
        run_stage12a_evaluation(config_path=str(temp_cfg))
    finally:
        temp_cfg.unlink(missing_ok=True)
    return build_regression_v1_outputs(
        eval_output_root=eval_output_root,
        eval_case_path=eval_case_path,
        report_root=report_root,
        primary_variant=primary_variant,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run eval_v1 regression and summarize outputs.")
    parser.add_argument("--config", default="configs/evaluation_stage12a.yaml")
    parser.add_argument("--eval-output-root", default="data/evaluation/eval_v1")
    parser.add_argument("--eval-case-path", default="data/eval_v1/cases.jsonl")
    parser.add_argument("--report-root", default="reports/eval_v1")
    parser.add_argument("--primary-variant", default="bm25_real_writer")
    parser.add_argument("--max-samples", type=int, default=None)
    args = parser.parse_args()

    summary = run_eval_v1(
        config_path=args.config,
        eval_output_root=args.eval_output_root,
        eval_case_path=args.eval_case_path,
        report_root=args.report_root,
        primary_variant=args.primary_variant,
        max_samples=args.max_samples,
    )
    print(f"[eval_v1] summary_json={summary['outputs']['summary_json']}")
    print(f"[eval_v1] summary_md={summary['outputs']['summary_md']}")
    print(f"[eval_v1] per_case_csv={summary['outputs']['per_case_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
