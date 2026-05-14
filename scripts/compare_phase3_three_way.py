"""Three-way comparison: baseline_2 vs baseline_3 vs baseline_4 (Phase 3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
def _find_baseline4_path() -> Path:
    """Find the most recent baseline_4 output directory."""
    root = PROJECT_ROOT / "eval_outputs"
    candidates = sorted(
        [p for p in root.iterdir() if p.is_dir() and "baseline_4_dynamic_multiagent_router" in p.name],
        reverse=True,
    )
    if candidates:
        return candidates[0] / "eval_summary.json"
    return root / "baseline_4_dynamic_multiagent_router" / "eval_summary.json"


RUNS: Dict[str, Path] = {
    "baseline_2_current_workflow": PROJECT_ROOT / "eval_outputs" / "baseline_2_current_workflow_anchor" / "eval_summary.json",
    "baseline_3_gaprouter_routed_rework": PROJECT_ROOT / "eval_outputs" / "baseline_3_gaprouter_routed_rework" / "eval_summary.json",
    "baseline_4_dynamic_multiagent_router": _find_baseline4_path(),
}

CORE_METRICS = [
    "task_completion_rate",
    "required_sections_coverage",
    "artifact_generation_pass_rate",
    "verification_pass_rate",
    "gap_detection_count_mean",
    "gap_resolution_rate_mean",
    "task_resolution_rate_mean",
    "total_latency_sec_mean",
    "claim_count_mean",
    "evidence_count_mean",
    "citation_count_mean",
    "message_count_mean",
    "task_blocked_count_mean",
]

PHASE3_METRICS = [
    "router_decision_count_sum",
    "dynamic_dispatch_count_sum",
    "fallback_decision_count_sum",
    "budget_exceeded_count_sum",
    "repeated_dispatch_count_sum",
    "unsupported_gap_fallback_count_sum",
]


def main() -> int:
    summaries: Dict[str, Any] = {}
    for name, path in RUNS.items():
        if path.exists():
            summaries[name] = _read_json(path)
        else:
            summaries[name] = None

    rows: Dict[str, Dict[str, Any]] = {}
    for metric in CORE_METRICS:
        row: Dict[str, Any] = {}
        for name in summaries:
            metrics = summaries[name].get("metrics", {}) if summaries[name] else {}
            row[name] = _num(metrics.get(metric))
        row["delta_b3_vs_b2"] = _delta(row, "baseline_3_gaprouter_routed_rework", "baseline_2_current_workflow")
        row["delta_b4_vs_b3"] = _delta(row, "baseline_4_dynamic_multiagent_router", "baseline_3_gaprouter_routed_rework")
        rows[metric] = row

    phase3: Dict[str, Any] = {}
    b4 = summaries.get("baseline_4_dynamic_multiagent_router")
    if b4:
        b4m = b4.get("metrics", {})
        for metric in PHASE3_METRICS:
            phase3[metric] = _num(b4m.get(metric))
        phase3["router_stop_reasons"] = b4m.get("router_stop_reasons", {})

    payload: Dict[str, Any] = {
        "runs": {name: str(path) for name, path in RUNS.items()},
        "core_metrics": rows,
        "phase3_process_metrics": phase3,
    }
    out_path = _find_baseline4_path().parent / "three_way_comparison.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _delta(row: Dict[str, Any], new_key: str, old_key: str) -> float | None:
    old = row.get(old_key)
    new = row.get(new_key)
    if old is not None and new is not None:
        return round(new - old, 4)
    return None


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
