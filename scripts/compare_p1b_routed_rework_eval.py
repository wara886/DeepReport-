"""Compare baseline_2 anchor against P1-B routed rework eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OLD_RUN = PROJECT_ROOT / "eval_outputs" / "baseline_2_current_workflow_anchor" / "eval_summary.json"
NEW_RUN = PROJECT_ROOT / "eval_outputs" / "baseline_3_gaprouter_routed_rework" / "eval_summary.json"
OUT = PROJECT_ROOT / "eval_outputs" / "baseline_3_gaprouter_routed_rework" / "delta_vs_baseline_2_anchor.json"

METRICS = [
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
]


def main() -> int:
    old_summary = _read_json(OLD_RUN)
    new_summary = _read_json(NEW_RUN)
    old_metrics = old_summary.get("metrics", {}) if isinstance(old_summary.get("metrics"), dict) else {}
    new_metrics = new_summary.get("metrics", {}) if isinstance(new_summary.get("metrics"), dict) else {}
    rows: Dict[str, Dict[str, Any]] = {}
    for metric in METRICS:
        old_value = _num(old_metrics.get(metric))
        new_value = _num(new_metrics.get(metric))
        rows[metric] = {
            "baseline_2_current_workflow_anchor": old_value,
            "baseline_3_gaprouter_routed_rework": new_value,
            "delta": round(new_value - old_value, 4),
            "relative_delta": round((new_value - old_value) / old_value, 4) if old_value else None,
        }
    payload = {
        "old_run": str(OLD_RUN),
        "new_run": str(NEW_RUN),
        "metrics": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
