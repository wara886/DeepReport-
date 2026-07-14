"""Run the fixed quick-9 cross-market benchmark through multi-agent only.

Phase 2 is a diagnostic execution wrapper. A Phase 2R configuration may
exercise the existing delivery-rework loop, but it does not introduce
baseline variants or frozen-snapshot claims.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator  # noqa: E402
from src.evaluation.benchmark_metrics import (  # noqa: E402
    ARTIFACT_DERIVED_TRACE_LABEL,
    evaluate_existing_run,
)
from src.evaluation.delivery_pipeline import run_delivery_quality_pipeline, run_delivery_rework_loop  # noqa: E402
from src.utils.config import load_config  # noqa: E402


DEFAULT_OUTPUT_ROOT = "eval_outputs/benchmark_quick9_multi_agent"


def load_quick9_config(config_path: str | Path) -> Dict[str, Any]:
    """Load and validate the fixed multi-agent benchmark contract."""

    payload = load_config(config_path)
    benchmark = payload.get("benchmark", {}) if isinstance(payload.get("benchmark"), dict) else {}
    cases = benchmark.get("cases", [])
    execution = benchmark.get("execution", {})
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark config must contain cases")
    if not isinstance(execution, dict) or execution.get("variant") != "multi_agent":
        raise ValueError("Phase 2 supports the multi_agent variant only")
    if not execution.get("target_period"):
        raise ValueError("benchmark.execution.target_period is required")
    return benchmark


def run_quick9_multi_agent_benchmark(
    config_path: str | Path = "configs/benchmark_quick9_multi_agent.yaml",
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    orchestrator_factory: Callable[..., Any] = MultiAgentOrchestrator,
    run_stamp: str | None = None,
) -> Dict[str, Any]:
    """Execute every configured case and write fixed-denominator outputs."""

    benchmark = load_quick9_config(config_path)
    execution = dict(benchmark["execution"])
    cases = [dict(case) for case in benchmark["cases"]]
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = run_stamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rows: List[Dict[str, Any]] = []
    for case in cases:
        rows.append(
            run_benchmark_case(
                case=case,
                execution=execution,
                root=root,
                stamp=stamp,
                orchestrator_factory=orchestrator_factory,
            )
        )
    summary = summarize_quick9_records(rows)
    paths = write_quick9_outputs(root, rows, summary, execution)
    baseline_root = str(benchmark.get("comparison_baseline_root") or "").strip()
    if baseline_root:
        paths.update(
            write_repair_comparison(
                output_root=root,
                after_rows=rows,
                after_summary=summary,
                baseline_root=Path(baseline_root),
                cases=cases,
            )
        )
    return {**summary, "records": rows, "paths": paths}


def reassess_quick9_existing_artifacts(
    config_path: str | Path,
    source_output_root: str | Path,
    output_root: str | Path,
) -> Dict[str, Any]:
    """Recompute Phase 2 metrics from recorded artifacts without running agents."""

    benchmark = load_quick9_config(config_path)
    execution = dict(benchmark["execution"])
    execution["reassessment_only"] = True
    execution["reassessment_source_root"] = str(source_output_root)
    source_rows = {
        str(row.get("case_id") or ""): row
        for row in _read_jsonl(Path(source_output_root) / "benchmark_runs.jsonl")
    }
    rows: List[Dict[str, Any]] = []
    for case in [dict(item) for item in benchmark["cases"]]:
        recorded = source_rows.get(str(case.get("case_id") or ""))
        if not recorded:
            rows.append(_failed_row(case, Path(""), Path(""), "recorded Phase 2 run is missing"))
            continue
        outputs = Path(str(recorded.get("outputs_dir") or ""))
        reports = Path(str(recorded.get("reports_dir") or ""))
        row = evaluate_existing_run(outputs, case=case, reports_dir=reports)
        if row.get("status") != "evaluated":
            row = _failed_row(case, outputs, reports, str(row.get("not_evaluable_reason") or "artifacts missing"))
        row.update(
            {
                key: recorded.get(key)
                for key in (
                    "variant",
                    "target_period",
                    "actual_report_period",
                    "available_data_periods",
                    "execution_mode",
                    "model",
                    "run_dir",
                    "metadata_path",
                    "source_failure_reasons",
                    "rework_round_count",
                )
                if key in recorded
            }
        )
        row["reassessed_from_recorded_run"] = True
        rows.append(_apply_source_failure_taxonomy(row))
    summary = summarize_quick9_records(rows)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    paths = write_quick9_outputs(root, rows, summary, execution)
    return {**summary, "records": rows, "paths": paths}


def run_benchmark_case(
    case: Dict[str, Any],
    execution: Dict[str, Any],
    root: Path,
    stamp: str,
    orchestrator_factory: Callable[..., Any] = MultiAgentOrchestrator,
) -> Dict[str, Any]:
    """Run a single case, persisting execution diagnostics even on failure."""

    case_id = str(case["case_id"])
    run_dir = root / "runs" / f"{stamp}_{case_id}"
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    outputs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    target_period = str(execution["target_period"])
    engines = _engines_for_case(execution, case)
    metadata: Dict[str, Any] = {
        "schema_version": "benchmark_quick9_run.v1",
        "variant": "multi_agent",
        "evaluation_stage": "phase_2r_repair" if execution.get("repair_evaluation") else "phase_2_quick9",
        "case": case,
        "run_started_at": datetime.now(timezone.utc).isoformat(),
        "target_period": target_period,
        "execution": {
            "execution_mode": execution.get("execution_mode", "collaborative"),
            "fast": bool(execution.get("fast", True)),
            "enable_remote_data": bool(execution.get("enable_remote_data", True)),
            "model_config_path": str(execution.get("model_config_path", "configs/model_backends.yaml")),
            "data_source_config_path": str(execution.get("data_source_config_path", "configs/data_sources.yaml")),
            "retrieval_ranking_mode": str(execution.get("retrieval_ranking_mode", "hybrid_rerank")),
            "engines": engines,
        },
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
    }
    try:
        orchestrator = orchestrator_factory(
            output_dir=str(outputs),
            report_dir=str(reports),
            config_path=str(execution.get("model_config_path", "configs/model_backends.yaml")),
            raw_data_root=str(execution.get("raw_data_root", "data/raw/real_data")),
            app_config_path=str(execution.get("app_config_path", "configs/app.yaml")),
            memory_enabled=False,
        )
        run_kwargs = {
            "research_topic": _research_topic(case, target_period),
            "symbol": str(case["canonical_symbol"]),
            "period": target_period,
            "requirements": _report_requirements(),
            "execution_mode": str(execution.get("execution_mode", "collaborative")),
            "fast": bool(execution.get("fast", True)),
            "search_engines": engines,
            "retrieval_ranking_mode": str(execution.get("retrieval_ranking_mode", "hybrid_rerank")),
            "enable_remote_data": bool(execution.get("enable_remote_data", True)),
            "data_source_config_path": str(execution.get("data_source_config_path", "configs/data_sources.yaml")),
        }
        result_paths = orchestrator.run(**run_kwargs)
        quality_pipeline = run_delivery_quality_pipeline(
            output_root=outputs,
            report_root=reports,
            config_path=str(execution.get("model_config_path", "configs/model_backends.yaml")),
            memory_enabled=False,
        )
        rework_result: Dict[str, Any] = {"rounds": [], "reworked": False, "quality_result": quality_pipeline}
        if int(execution.get("max_rework_rounds", 0) or 0) > 0:
            rework_result = run_delivery_rework_loop(
                orchestrator=orchestrator,
                output_path=outputs,
                report_path=reports,
                config_path=str(execution.get("model_config_path", "configs/model_backends.yaml")),
                initial_quality_result=quality_pipeline,
                run_kwargs=run_kwargs,
                memory_enabled=False,
                max_rounds=int(execution.get("max_rework_rounds", 0) or 0),
            )
            quality_pipeline = dict(rework_result.get("quality_result") or quality_pipeline)
        row = evaluate_existing_run(outputs, case=case, reports_dir=reports)
        if row.get("status") != "evaluated":
            row = _failed_row(case, outputs, reports, str(row.get("not_evaluable_reason") or "artifacts missing"))
        metadata.update(
            {
                "status": "completed" if row.get("status") == "evaluated" else "failed",
                "result_paths": result_paths,
                "quality_pipeline": quality_pipeline,
                "delivery_rework": rework_result,
            }
        )
    except Exception as exc:
        row = _failed_row(case, outputs, reports, f"{type(exc).__name__}: {exc}")
        metadata.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
    summary = _read_dict(outputs / "run_summary.json")
    search_meta = _read_dict(outputs / "search_meta.json")
    metadata.update(
        {
            "run_finished_at": datetime.now(timezone.utc).isoformat(),
            "model": summary.get("model", ""),
            "actual_report_period": summary.get("period", ""),
            "available_data_periods": _available_periods(outputs),
            "source_attempts": search_meta.get("engine_meta", {}),
        }
    )
    metadata_path = outputs / "benchmark_run_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    row.update(
        {
            "variant": "multi_agent",
            "target_period": target_period,
            "actual_report_period": str(summary.get("period") or ""),
            "available_data_periods": metadata["available_data_periods"],
            "execution_mode": metadata["execution"]["execution_mode"],
            "model": str(summary.get("model") or ""),
            "run_dir": str(run_dir),
            "metadata_path": str(metadata_path),
            "source_failure_reasons": _source_failure_reasons(search_meta),
            "rework_round_count": len(metadata.get("delivery_rework", {}).get("rounds", []))
            if isinstance(metadata.get("delivery_rework"), dict)
            else 0,
        }
    )
    return _apply_source_failure_taxonomy(row)


def summarize_quick9_records(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate Phase 2 records with all configured cases in fixed denominators."""

    markets = ["US", "HK", "CN-A"]
    overall = _fixed_metric_summary(rows)
    by_market = {market: _fixed_metric_summary([row for row in rows if row.get("market") == market]) for market in markets}
    counts: Dict[str, int] = {}
    for row in rows:
        for category in row.get("failure_categories", []):
            counts[str(category)] = counts.get(str(category), 0) + 1
    return {
        "schema_version": "benchmark_quick9_multi_agent.v1",
        "metric_scope": "artifact_derived_v0",
        "variant": "multi_agent",
        "case_count": len(rows),
        "completed_artifact_count": sum(1 for row in rows if row.get("status") == "evaluated"),
        "reworked_case_count": sum(1 for row in rows if int(row.get("rework_round_count", 0) or 0) > 0),
        "overall": overall,
        "by_market": by_market,
        "failure_counts": counts,
    }


def write_quick9_outputs(
    output_root: Path,
    rows: List[Dict[str, Any]],
    summary: Dict[str, Any],
    execution: Dict[str, Any],
) -> Dict[str, str]:
    """Write Phase 2 summary, detail, failure and market output files."""

    summary_path = output_root / "benchmark_summary.csv"
    report_path = output_root / "benchmark_report.md"
    runs_path = output_root / "benchmark_runs.jsonl"
    failures_path = output_root / "benchmark_failures.csv"
    market_path = output_root / "market_breakdown.csv"
    _write_metric_csv(summary_path, summary)
    with market_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "market",
                "case_count",
                "quality_evaluable_count",
                "delivery_pass_rate",
                "objective_quality_score",
                "traceable_claim_rate_artifact_derived",
            ],
        )
        writer.writeheader()
        for market in ["Overall", "US", "HK", "CN-A"]:
            values = summary["overall"] if market == "Overall" else summary["by_market"][market]
            writer.writerow(
                {
                    "market": market,
                    "case_count": values["case_count"],
                    "quality_evaluable_count": values["quality_evaluable_count"],
                    "delivery_pass_rate": values["delivery_pass_rate"],
                    "objective_quality_score": values["objective_quality_score"],
                    "traceable_claim_rate_artifact_derived": values["traceable_claim_rate"],
                }
            )
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    with failures_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["case_id", "market", "canonical_symbol", "status", "primary_blocker", "all_categories", "detail", "run_dir"],
        )
        writer.writeheader()
        for row in rows:
            if row.get("delivery_pass") is True:
                continue
            categories = list(row.get("failure_categories") or ["runtime_or_model_failure"])
            writer.writerow(
                {
                    "case_id": row.get("case_id", ""),
                    "market": row.get("market", ""),
                    "canonical_symbol": row.get("canonical_symbol", ""),
                    "status": row.get("status", ""),
                    "primary_blocker": _primary_blocker(categories),
                    "all_categories": ",".join(categories),
                    "detail": row.get("failure_detail", row.get("not_evaluable_reason", "")),
                    "run_dir": row.get("run_dir", ""),
                }
            )
    report_path.write_text(_render_report(rows, summary, execution), encoding="utf-8")
    return {
        "benchmark_summary": str(summary_path),
        "benchmark_report": str(report_path),
        "benchmark_runs": str(runs_path),
        "benchmark_failures": str(failures_path),
        "market_breakdown": str(market_path),
    }


def write_repair_comparison(
    output_root: Path,
    after_rows: List[Dict[str, Any]],
    after_summary: Dict[str, Any],
    baseline_root: Path,
    cases: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Compare repair results against original artifacts under the current metric contract."""

    stored_rows = {str(row.get("case_id") or ""): row for row in _read_jsonl(baseline_root / "benchmark_runs.jsonl")}
    recorded_before_rows = [
        dict(stored_rows[str(case.get("case_id") or "")])
        for case in cases
        if str(case.get("case_id") or "") in stored_rows
    ]
    recorded_before_summary = summarize_quick9_records(recorded_before_rows)
    before_rows: List[Dict[str, Any]] = []
    for case in cases:
        stored = stored_rows.get(str(case.get("case_id") or ""))
        if not stored:
            before_rows.append(_failed_row(case, Path(""), Path(""), "baseline run record missing"))
            continue
        row = evaluate_existing_run(
            Path(str(stored.get("outputs_dir") or "")),
            case=case,
            reports_dir=Path(str(stored.get("reports_dir") or "")),
        )
        row.update(
            {
                "run_dir": stored.get("run_dir", ""),
                "source_failure_reasons": list(stored.get("source_failure_reasons") or []),
            }
        )
        before_rows.append(_apply_source_failure_taxonomy(row))
    before_summary = summarize_quick9_records(before_rows)
    summary_path = output_root / "repair_comparison.csv"
    report_path = output_root / "repair_comparison.md"
    with summary_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["metric", "recorded_before", "before_reassessed", "after_repair", "repair_delta"])
        writer.writeheader()
        for key, label in (
            ("delivery_pass_rate", "Delivery Pass Rate"),
            ("objective_quality_score", "Objective Quality Score"),
            ("traceable_claim_rate", ARTIFACT_DERIVED_TRACE_LABEL),
        ):
            before = before_summary["overall"].get(key)
            after = after_summary["overall"].get(key)
            delta = round(float(after) - float(before), 4) if before is not None and after is not None else None
            writer.writerow(
                {
                    "metric": label,
                    "recorded_before": recorded_before_summary["overall"].get(key),
                    "before_reassessed": before,
                    "after_repair": after,
                    "repair_delta": delta,
                }
            )
    report_path.write_text(
        _render_repair_comparison(
            recorded_before_summary,
            before_rows,
            before_summary,
            after_rows,
            after_summary,
            baseline_root,
        ),
        encoding="utf-8",
    )
    return {"repair_comparison_csv": str(summary_path), "repair_comparison_report": str(report_path)}


def _render_repair_comparison(
    recorded_before_summary: Dict[str, Any],
    before_rows: List[Dict[str, Any]],
    before_summary: Dict[str, Any],
    after_rows: List[Dict[str, Any]],
    after_summary: Dict[str, Any],
    baseline_root: Path,
) -> str:
    before_by_case = {str(row.get("case_id") or ""): row for row in before_rows}
    lines = [
        "# Quick-9 Repair Comparison",
        "",
        "## Method",
        "",
        f"- Before artifacts: `{baseline_root}`.",
        "- `recorded_before` is the metric value written by the original Phase 2 implementation.",
        "- `before_reassessed` re-evaluates the original Phase 2 artifacts with the corrected deterministic delivery contract, so metric-rule correction is not misreported as repair gain.",
        "- `after_repair` is the Phase 2R `diagnostic_full` rerun with configured source routing and one delivery rework round.",
        "- Both sides remain `multi_agent` online-source diagnostics; this is not a baseline comparison or frozen-snapshot benchmark.",
        "",
        "## Metrics",
        "",
        "| Metric | Recorded Before | Before Reassessed | After Repair | Repair Delta |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, label in (
        ("delivery_pass_rate", "Delivery Pass Rate"),
        ("objective_quality_score", "Objective Quality Score"),
        ("traceable_claim_rate", ARTIFACT_DERIVED_TRACE_LABEL),
    ):
        before = before_summary["overall"].get(key)
        after = after_summary["overall"].get(key)
        delta = round(float(after) - float(before), 4) if before is not None and after is not None else None
        lines.append(
            f"| {label} | {_fmt(recorded_before_summary['overall'].get(key))} | "
            f"{_fmt(before)} | {_fmt(after)} | {_fmt(delta)} |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Market | Delivery Before Reassessed | Delivery After | Traceable Before | Traceable After |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for after in after_rows:
        before = before_by_case.get(str(after.get("case_id") or ""), {})
        lines.append(
            f"| `{after.get('canonical_symbol', '')}` | {after.get('market', '')} | "
            f"{_fmt(before.get('delivery_pass'))} | {_fmt(after.get('delivery_pass'))} | "
            f"{_fmt(before.get('traceable_claim_rate'))} | {_fmt(after.get('traceable_claim_rate'))} |"
        )
    lines.extend(
        [
            "",
            "## Remaining Gaps",
            "",
            "- Treat passed delivery cases with `citation_or_evidence_gap` or `quality_gate_blocker` diagnostics as repair follow-ups, not formal-quality successes.",
            "- Phase 3 remains blocked on frozen evidence inputs, baseline variants, and explicit `Traceable Claim Rate v1` labeling.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_metric_csv(path: Path, summary: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["metric", "overall", "US", "HK", "CN-A"])
        writer.writeheader()
        for key, label in (
            ("delivery_pass_rate", "Delivery Pass Rate"),
            ("objective_quality_score", "Objective Quality Score"),
            ("traceable_claim_rate", ARTIFACT_DERIVED_TRACE_LABEL),
        ):
            writer.writerow(
                {
                    "metric": label,
                    "overall": summary["overall"][key],
                    "US": summary["by_market"]["US"][key],
                    "HK": summary["by_market"]["HK"][key],
                    "CN-A": summary["by_market"]["CN-A"][key],
                }
            )


def _render_report(rows: List[Dict[str, Any]], summary: Dict[str, Any], execution: Dict[str, Any]) -> str:
    repair_evaluation = bool(execution.get("repair_evaluation", False))
    reassessment_only = bool(execution.get("reassessment_only", False))
    lines = [
        "# Quick-9 Multi-Agent Existing-Artifact Reassessment Report"
        if reassessment_only
        else (
            "# Quick-9 Multi-Agent Repair Diagnostic Report"
            if repair_evaluation
            else "# Quick-9 Multi-Agent Cross-Market Diagnostic Report"
        ),
        "",
        "## Scope",
        "",
        "- Phase: `Phase 2 - Read-only Contract Reassessment`."
        if reassessment_only
        else (
            "- Phase: `Phase 2R - Pre-Phase-3 Repair Evaluation`."
        if repair_evaluation
            else "- Phase: `Quick 9 Multi-Agent Benchmark`."
        ),
        "- Variant: `multi_agent` only. No `Direct LLM` or `Single-Agent RAG` baseline was run.",
        "- This is an online-source engineering diagnostic, not a frozen-snapshot fair model comparison.",
        f"- Fixed denominator: `{summary['case_count']}` configured cases; completed artifacts: `{summary['completed_artifact_count']}`.",
        f"- Target period: `{execution.get('target_period', '')}`; retrieval mode: `{execution.get('retrieval_ranking_mode', '')}`.",
        f"- `{ARTIFACT_DERIVED_TRACE_LABEL}` remains an initial sidecar-derived metric, not formal `Traceable Claim Rate v1`.",
        "- `Delivery Pass Rate` uses deterministic delivery requirements only; objective quality and traceability remain separate diagnostics.",
        "- Delivery and traceability rates use all fixed cases; Objective Quality Score averages only cases with evaluable quality artifacts.",
    ]
    if reassessment_only:
        lines.extend(
            [
                f"- Source artifacts: `{execution.get('reassessment_source_root', '')}`.",
                "- No agents or remote sources were invoked during this reassessment; it applies the corrected deterministic delivery contract to the recorded Phase 2 artifacts.",
            ]
        )
    if repair_evaluation:
        lines.extend(
            [
                f"- Repair route: `{execution.get('execution_mode', '')}` with up to `{int(execution.get('max_rework_rounds', 0) or 0)}` delivery rework round(s); reworked cases: `{summary.get('reworked_case_count', 0)}`.",
                "- This repair rerun is a checkpoint before Phase 3; it does not freeze evidence or introduce baseline variants.",
            ]
        )
    lines.extend(
        [
            "",
            "## Core Metrics",
            "",
            "| Metric | Overall | US | HK | CN-A |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in (
        ("delivery_pass_rate", "Delivery Pass Rate"),
        ("objective_quality_score", "Objective Quality Score"),
        ("traceable_claim_rate", ARTIFACT_DERIVED_TRACE_LABEL),
    ):
        lines.append(
            f"| {label} | {_fmt(summary['overall'][key])} | {_fmt(summary['by_market']['US'][key])} | "
            f"{_fmt(summary['by_market']['HK'][key])} | {_fmt(summary['by_market']['CN-A'][key])} |"
        )
    lines.extend(["", "## Case Results", "", "| Case | Market | Status | Delivery | Quality | Traceable | Blocker / Diagnostic |", "| --- | --- | --- | ---: | ---: | ---: | --- |"])
    for row in rows:
        categories = list(row.get("failure_categories", []))
        lines.append(
            f"| `{row['canonical_symbol']}` | {row['market']} | `{row.get('status', '')}` | "
            f"{_fmt(row.get('delivery_pass'))} | {_fmt(row.get('objective_quality_score'))} | "
            f"{_fmt(row.get('traceable_claim_rate'))} | `{_primary_blocker(categories) if categories else '-'}` |"
        )
    lines.extend(["", "## Failure And Diagnostic Taxonomy", ""])
    if summary.get("failure_counts"):
        for category, count in sorted(summary["failure_counts"].items(), key=lambda pair: (-pair[1], pair[0])):
            lines.append(f"- `{category}`: {count}")
    else:
        lines.append("- No delivery blockers or diagnostics recorded.")
    lines.extend(["", "## Boundary", "", "- These results locate current cross-market engineering failures only; they do not show that Multi-Agent outperforms another architecture.", "- A formal result table requires common frozen evidence inputs and baseline variants in Phase 3.", ""])
    return "\n".join(lines)


def _fixed_metric_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(rows)
    if not count:
        return {
            "case_count": 0,
            "quality_evaluable_count": 0,
            "delivery_pass_rate": None,
            "objective_quality_score": None,
            "traceable_claim_rate": None,
        }
    quality = [float(row["objective_quality_score"]) for row in rows if row.get("objective_quality_score") is not None]
    traces = [float(row.get("traceable_claim_rate") or 0.0) for row in rows]
    return {
        "case_count": count,
        "quality_evaluable_count": len(quality),
        "delivery_pass_rate": round(sum(1 for row in rows if row.get("delivery_pass") is True) / count, 4),
        "objective_quality_score": round(sum(quality) / len(quality), 2) if quality else None,
        "traceable_claim_rate": round(sum(traces) / count, 4),
    }


def _failed_row(case: Dict[str, Any], outputs: Path, reports: Path, reason: str) -> Dict[str, Any]:
    return {
        "case_id": str(case.get("case_id", "")),
        "market": str(case.get("market", "")),
        "company_name": str(case.get("company_name", "")),
        "canonical_symbol": str(case.get("canonical_symbol", "")),
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
        "metric_scope": "artifact_derived_v0",
        "status": "failed",
        "delivery_pass": False,
        "objective_quality_score": None,
        "traceable_claim_rate": 0.0,
        "critical_claim_count": 0,
        "traceable_claim_count": 0,
        "failure_categories": ["runtime_or_model_failure"],
        "failure_detail": reason,
    }


def _engines_for_case(execution: Dict[str, Any], case: Dict[str, Any]) -> List[str]:
    mapping = execution.get("engines_by_market", {})
    engines = mapping.get(case.get("market"), []) if isinstance(mapping, dict) else []
    return [str(engine) for engine in engines]


def _research_topic(case: Dict[str, Any], target_period: str) -> str:
    return (
        f"Generate a company stock research report for {case.get('company_name')} "
        f"({case.get('canonical_symbol')}) for {target_period}, with citations, "
        "three-statement coverage or disclosed gaps, valuation limitations, risks, and investment conclusion."
    )


def _report_requirements() -> List[str]:
    return [
        "Provide executive summary, risk assessment, and investment conclusion.",
        "Cover three statements or explicitly disclose unavailable statement evidence.",
        "Include valuation analysis or explicitly state why valuation is unavailable.",
        "Bind critical conclusions to evidence IDs and citations used in report.",
    ]


def _available_periods(outputs: Path) -> List[str]:
    values: set[str] = set()
    for name in ("evidence.json", "claims.json"):
        payload = _read_list(outputs / name)
        for item in payload:
            if item.get("period"):
                values.add(str(item["period"]))
    financial = _read_dict(outputs / "financial_metrics.json")
    for item in financial.get("metrics", []) if isinstance(financial.get("metrics"), list) else []:
        if isinstance(item, dict) and item.get("period"):
            values.add(str(item["period"]))
    return sorted(values)


def _source_failure_reasons(search_meta: Dict[str, Any]) -> List[str]:
    output: List[str] = []
    engine_meta = search_meta.get("engine_meta", {}) if isinstance(search_meta.get("engine_meta"), dict) else {}
    for engine, payload in engine_meta.items():
        if not isinstance(payload, dict):
            continue
        reason = str(payload.get("failure_reason") or payload.get("error") or "")
        if reason:
            output.append(f"{engine}: {reason}")
    return output


def _apply_source_failure_taxonomy(row: Dict[str, Any]) -> Dict[str, Any]:
    """Attach actionable source failures without treating normal local fallback as a blocker."""

    updated = dict(row)
    categories = list(updated.get("failure_categories", []))
    reasons = [str(value).lower() for value in updated.get("source_failure_reasons", [])]
    actionable = any(
        any(marker in reason for marker in ("fetch_error", "url error", "http ", "missing_api_key", "timeout"))
        for reason in reasons
    )
    if updated.get("delivery_pass") is False and actionable and "source_access_or_fetch" not in categories:
        categories.append("source_access_or_fetch")
    updated["failure_categories"] = categories
    return updated


def _primary_blocker(categories: List[str]) -> str:
    direct_gate_order = [
        "identity_resolution",
        "three_statement_coverage",
        "valuation_input_missing",
        "citation_or_evidence_gap",
        "chart_text_mismatch",
        "quality_gate_blocker",
        "source_access_or_fetch",
        "runtime_or_model_failure",
    ]
    known = [category for category in direct_gate_order if category in set(categories)]
    return known[0] if known else "runtime_or_model_failure"


def _read_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _read_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(dict(payload))
    return rows


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "pass" if value else "fail"
    if isinstance(value, float):
        return f"{value:.4f}" if value <= 1 else f"{value:.2f}"
    return str(value)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 2 fixed quick-9 multi-agent diagnostic benchmark.")
    parser.add_argument("--config", default="configs/benchmark_quick9_multi_agent.yaml")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--reassess-source-root",
        default="",
        help="Read an existing Phase 2 benchmark root and recompute metrics without executing agents.",
    )
    args = parser.parse_args(argv)
    if args.reassess_source_root:
        summary = reassess_quick9_existing_artifacts(
            config_path=args.config,
            source_output_root=args.reassess_source_root,
            output_root=args.output_root,
        )
    else:
        summary = run_quick9_multi_agent_benchmark(config_path=args.config, output_root=args.output_root)
    print(
        json.dumps(
            {
                "variant": summary["variant"],
                "case_count": summary["case_count"],
                "delivery_pass_rate": summary["overall"]["delivery_pass_rate"],
                "benchmark_report": summary["paths"]["benchmark_report"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
