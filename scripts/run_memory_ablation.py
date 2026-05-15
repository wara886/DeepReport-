"""Run enabled/disabled durable memory ablation for the multi-agent path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.multi_agent_harness import run_multi_agent_evaluation
from src.evaluation.numeric_audit import summarize_numeric_audit
from src.utils.config import load_config


QUALITY_METRICS = [
    "verification_pass_rate",
    "evidence_coverage_mean",
    "evidence_alignment_mean",
    "chart_consistency_pass_rate",
    "contest_checklist_pass_rate_mean",
    "numeric_accuracy",
]


def build_memory_ablation_config(base_config: Dict[str, Any], output_root: Path) -> Dict[str, Any]:
    """Build a two-variant eval config from an existing multi-agent config."""

    eval_cfg = dict(base_config.get("evaluation", {}))
    ma_cfg = dict(eval_cfg.get("multi_agent", {}))
    base_variant = _first_variant(ma_cfg)
    common = {
        key: value
        for key, value in base_variant.items()
        if key not in {"id", "memory_enabled", "memory_root"}
    }
    ma_cfg["output_root"] = str(output_root)
    ma_cfg["variants"] = [
        {
            **common,
            "id": "memory_enabled",
            "memory_enabled": True,
            "memory_root": str(output_root / "memory_enabled_store"),
        },
        {
            **common,
            "id": "memory_disabled",
            "memory_enabled": False,
            "memory_root": str(output_root / "memory_disabled_store"),
        },
    ]
    eval_cfg["multi_agent"] = ma_cfg
    return {"evaluation": eval_cfg}


def summarize_memory_ablation(
    report_rows: List[Dict[str, Any]],
    numeric_rows: List[Dict[str, Any]],
    latency_tolerance_sec: float = 45.0,
    quality_tolerance: float = 0.0,
) -> Dict[str, Any]:
    """Compare memory_enabled against memory_disabled with quality guards."""

    variants = {
        variant_id: _summarize_variant(
            variant_id=variant_id,
            report_rows=[row for row in report_rows if str(row.get("variant_id")) == variant_id],
            numeric_rows=[row for row in numeric_rows if str(row.get("variant_id")) == variant_id],
        )
        for variant_id in sorted({str(row.get("variant_id")) for row in report_rows})
    }
    enabled = variants.get("memory_enabled", _empty_variant_summary("memory_enabled"))
    disabled = variants.get("memory_disabled", _empty_variant_summary("memory_disabled"))
    deltas = {
        metric: round(float(enabled.get(metric, 0.0)) - float(disabled.get(metric, 0.0)), 4)
        for metric in QUALITY_METRICS + ["avg_duration_sec"]
    }
    deltas["latency_delta_sec"] = deltas.pop("avg_duration_sec")

    regressions = [
        metric
        for metric in QUALITY_METRICS
        if float(deltas.get(metric, 0.0)) < -abs(float(quality_tolerance))
    ]
    latency_guard_passed = float(deltas["latency_delta_sec"]) <= float(latency_tolerance_sec)
    quality_guard_passed = not regressions

    if not quality_guard_passed:
        decision = "reject_memory"
    elif not latency_guard_passed:
        decision = "hold_memory"
    elif any(float(deltas.get(metric, 0.0)) > 0.0 for metric in QUALITY_METRICS):
        decision = "promote_memory"
    else:
        decision = "hold_memory"

    return {
        "baseline_variant": "memory_disabled",
        "candidate_variant": "memory_enabled",
        "decision": decision,
        "quality_guard_passed": quality_guard_passed,
        "latency_guard_passed": latency_guard_passed,
        "latency_tolerance_sec": latency_tolerance_sec,
        "quality_tolerance": quality_tolerance,
        "regressions": regressions,
        "variants": variants,
        "deltas": deltas,
        "recommendation": _recommendation(decision),
    }


def render_memory_ablation_markdown(comparison: Dict[str, Any]) -> str:
    """Render a compact markdown summary for review."""

    variants = comparison.get("variants", {})
    deltas = comparison.get("deltas", {})
    lines = [
        "# Memory Ablation Comparison",
        "",
        f"- decision: {comparison.get('decision')}",
        f"- quality_guard_passed: {comparison.get('quality_guard_passed')}",
        f"- latency_guard_passed: {comparison.get('latency_guard_passed')}",
        f"- recommendation: {comparison.get('recommendation')}",
        "",
        "## Variant Metrics",
        "",
    ]
    for variant_id in ["memory_disabled", "memory_enabled"]:
        metrics = variants.get(variant_id, {})
        lines.extend(
            [
                f"### {variant_id}",
                "",
                f"- report_count: {metrics.get('report_count', 0)}",
                f"- verification_pass_rate: {metrics.get('verification_pass_rate', 0.0)}",
                f"- evidence_coverage_mean: {metrics.get('evidence_coverage_mean', 0.0)}",
                f"- evidence_alignment_mean: {metrics.get('evidence_alignment_mean', 0.0)}",
                f"- chart_consistency_pass_rate: {metrics.get('chart_consistency_pass_rate', 0.0)}",
                f"- contest_checklist_pass_rate_mean: {metrics.get('contest_checklist_pass_rate_mean', 0.0)}",
                f"- numeric_accuracy: {metrics.get('numeric_accuracy', 0.0)}",
                f"- avg_duration_sec: {metrics.get('avg_duration_sec', 0.0)}",
                "",
            ]
        )
    lines.extend(["## Deltas", ""])
    for key in QUALITY_METRICS + ["latency_delta_sec"]:
        lines.append(f"- {key}: {deltas.get(key, 0.0)}")
    lines.append("")
    return "\n".join(lines)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(dict(json.loads(line)))
    return rows


def _first_variant(ma_cfg: Dict[str, Any]) -> Dict[str, Any]:
    variants = ma_cfg.get("variants")
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        return dict(variants[0])
    return {
        "execution_mode": "dynamic",
        "fast": True,
        "engines": ["local_real_data", "local_evidence"],
        "retrieval_ranking_mode": "hybrid_rerank",
    }


def _summarize_variant(
    variant_id: str,
    report_rows: List[Dict[str, Any]],
    numeric_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    numeric_summary = summarize_numeric_audit(numeric_rows)
    return {
        "variant_id": variant_id,
        "report_count": len(report_rows),
        "verification_pass_rate": _mean(1.0 if row.get("rule_verifier_passed") else 0.0 for row in report_rows),
        "evidence_coverage_mean": _mean(row.get("evidence_coverage", 0.0) for row in report_rows),
        "evidence_alignment_mean": _mean(row.get("evidence_alignment", 0.0) for row in report_rows),
        "chart_consistency_pass_rate": _mean(1.0 if row.get("chart_consistency_passed") else 0.0 for row in report_rows),
        "contest_checklist_pass_rate_mean": _mean(row.get("contest_checklist_pass_rate", 0.0) for row in report_rows),
        "avg_duration_sec": _mean(row.get("total_duration_sec", 0.0) for row in report_rows),
        "numeric_accuracy": float(numeric_summary.get("numeric_accuracy", 0.0)),
        "numeric_audit": numeric_summary,
    }


def _empty_variant_summary(variant_id: str) -> Dict[str, Any]:
    return _summarize_variant(variant_id=variant_id, report_rows=[], numeric_rows=[])


def _mean(values: Iterable[Any]) -> float:
    parsed = [float(value) for value in values]
    return round(sum(parsed) / float(len(parsed)), 4) if parsed else 0.0


def _recommendation(decision: str) -> str:
    if decision == "promote_memory":
        return "Memory passed quality and latency guards; it can be promoted for broader smoke tests."
    if decision == "reject_memory":
        return "Memory regressed quality metrics; keep it disabled and inspect failed reports."
    return "Memory did not regress quality, but benefit or latency is not strong enough for default enablement."


def main() -> int:
    parser = argparse.ArgumentParser(description="Run durable memory enabled/disabled ablation.")
    parser.add_argument("--config", default="configs/evaluation_multi_agent_react_smoke.yaml")
    parser.add_argument("--run-id", default="memory_ablation")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--eval-case-path", default=None)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--latency-tolerance-sec", type=float, default=45.0)
    parser.add_argument("--quality-tolerance", type=float, default=0.0)
    args = parser.parse_args()

    output_root = Path(args.output_root or Path("eval_outputs") / args.run_id)
    output_root.mkdir(parents=True, exist_ok=True)
    ablation_config = build_memory_ablation_config(load_config(args.config), output_root=output_root)
    temp_config_path = output_root / "memory_ablation_config.yaml"
    temp_config_path.write_text(yaml.safe_dump(ablation_config, sort_keys=False, allow_unicode=True), encoding="utf-8")

    summary = run_multi_agent_evaluation(
        config_path=str(temp_config_path),
        output_root=output_root,
        eval_case_path=args.eval_case_path,
        max_samples=args.max_samples,
    )
    report_rows = read_jsonl(output_root / "per_report_metrics.jsonl")
    numeric_rows = read_jsonl(output_root / "per_case_numeric_audit_v1.jsonl")
    comparison = summarize_memory_ablation(
        report_rows=report_rows,
        numeric_rows=numeric_rows,
        latency_tolerance_sec=args.latency_tolerance_sec,
        quality_tolerance=args.quality_tolerance,
    )
    comparison["harness_summary"] = summary
    comparison_path = output_root / "memory_ablation_comparison.json"
    comparison_md_path = output_root / "memory_ablation_comparison.md"
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison_md_path.write_text(render_memory_ablation_markdown(comparison), encoding="utf-8")
    print(f"[memory_ablation] config: {temp_config_path}")
    print(f"[memory_ablation] comparison: {comparison_path}")
    print(f"[memory_ablation] decision: {comparison['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
