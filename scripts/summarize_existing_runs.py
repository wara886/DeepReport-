"""Summarize existing multi-agent artifacts for Phase 1 benchmark metrics."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.benchmark_metrics import (  # noqa: E402
    basic_artifact_gaps,
    canonical_symbol,
    evaluate_existing_run,
    locate_report_dir,
    summarize_records,
    write_benchmark_outputs,
)
from src.utils.config import load_config  # noqa: E402


def load_benchmark_config(config_path: str | Path) -> Dict[str, Any]:
    payload = load_config(config_path)
    benchmark = payload.get("benchmark", {}) if isinstance(payload.get("benchmark"), dict) else {}
    if not isinstance(benchmark.get("cases"), list) or not benchmark["cases"]:
        raise ValueError("benchmark config must contain at least one case")
    return benchmark


def discover_existing_outputs(
    patterns: List[str],
    project_root: str | Path = PROJECT_ROOT,
    excluded_patterns: List[str] | None = None,
) -> List[Path]:
    """Expand configured run roots without writing or triggering any workflow."""

    root = Path(project_root)
    found: set[Path] = set()
    for pattern in patterns:
        raw = Path(pattern)
        target = str(raw if raw.is_absolute() else root / raw)
        for matched in glob.glob(target, recursive=True):
            path = Path(matched)
            if path.is_dir():
                found.add(path)
    excluded: set[Path] = set()
    for pattern in excluded_patterns or []:
        raw = Path(pattern)
        target = str(raw if raw.is_absolute() else root / raw)
        for matched in glob.glob(target, recursive=True):
            path = Path(matched)
            if path.is_dir():
                excluded.add(path)
    return sorted(found - excluded)


def select_existing_runs(
    benchmark: Dict[str, Any],
    discovered_outputs: List[Path],
) -> List[Dict[str, Any]]:
    """Choose the latest complete existing run for each configured case."""

    candidates_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for outputs in discovered_outputs:
        summary = _read_dict(outputs / "run_summary.json")
        recorded_symbol = str(summary.get("symbol") or _symbol_from_path(outputs) or "")
        normalized = canonical_symbol(recorded_symbol)
        if not normalized:
            continue
        reports = locate_report_dir(outputs)
        gaps = basic_artifact_gaps(outputs, reports)
        candidates_by_symbol.setdefault(normalized, []).append(
            {
                "outputs_dir": outputs,
                "reports_dir": reports,
                "complete": not gaps,
                "missing_artifacts": gaps,
                "period": str(summary.get("period") or ""),
                "sort_key": _sort_key(outputs),
            }
        )

    rows: List[Dict[str, Any]] = []
    for raw_case in benchmark["cases"]:
        case = dict(raw_case)
        target = canonical_symbol(str(case.get("canonical_symbol") or ""))
        matches = sorted(
            candidates_by_symbol.get(target, []),
            key=lambda item: (bool(item["complete"]), item["sort_key"]),
            reverse=True,
        )
        if not matches:
            rows.append(
                {
                    "case_id": case.get("case_id", ""),
                    "market": case.get("market", ""),
                    "company_name": case.get("company_name", ""),
                    "canonical_symbol": target,
                    "status": "not_run",
                    "period": "",
                    "ignored_run_dirs": [],
                    "failure_categories": [],
                }
            )
            continue
        selected = matches[0]
        record = evaluate_existing_run(
            selected["outputs_dir"],
            case=case,
            reports_dir=selected["reports_dir"],
        )
        record["ignored_run_dirs"] = [str(item["outputs_dir"]) for item in matches[1:]]
        rows.append(record)
    return rows


def summarize_existing_runs(
    config_path: str | Path = "configs/benchmark_quick9_multi_agent.yaml",
    output_dir: str | Path = "eval_outputs/benchmark_existing_artifacts",
    project_root: str | Path = PROJECT_ROOT,
) -> Dict[str, Any]:
    """Run the Phase 1 read-only aggregation and write its reporting outputs."""

    benchmark = load_benchmark_config(config_path)
    outputs = discover_existing_outputs(
        list(benchmark.get("existing_run_roots", [])),
        project_root=project_root,
        excluded_patterns=list(benchmark.get("excluded_run_roots", [])),
    )
    records = select_existing_runs(benchmark, outputs)
    summary = summarize_records(records, total_case_count=len(benchmark["cases"]))
    paths = write_benchmark_outputs(output_dir, records, summary)
    return {**summary, "paths": paths, "records": records}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize existing company-report runs for Phase 1 benchmark metrics.")
    parser.add_argument("--config", default="configs/benchmark_quick9_multi_agent.yaml")
    parser.add_argument("--output-dir", default="eval_outputs/benchmark_existing_artifacts")
    args = parser.parse_args(argv)
    summary = summarize_existing_runs(config_path=args.config, output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "observed_runs": f"{summary['observed_run_count']}/{summary['total_case_count']}",
                "evaluable_runs": summary["evaluable_run_count"],
                "benchmark_report": summary["paths"]["benchmark_report"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _symbol_from_path(outputs: Path) -> str:
    text = outputs.parent.name
    match = re.search(r"_(\d{4}\.hk|\d{6}\.(?:ss|sz)|[a-z]{1,6})_(?:20\d{2}q[1-4])_", text, flags=re.I)
    return match.group(1).upper() if match else ""


def _sort_key(outputs: Path) -> tuple[float, str]:
    try:
        modified = outputs.stat().st_mtime
    except OSError:
        modified = 0.0
    return modified, str(outputs)


if __name__ == "__main__":
    raise SystemExit(main())
