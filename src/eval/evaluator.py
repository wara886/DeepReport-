"""Phase 0 evaluator orchestration for fixed baseline comparisons."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping

from src.eval.metrics import aggregate_metrics, compute_case_metrics
from src.eval.schema import EvalCase


BaselineAdapter = Callable[[EvalCase, Path], Dict[str, Any]]


@dataclass(frozen=True)
class EvalRunConfig:
    baseline_id: str
    run_id: str
    output_root: Path


class BaselineEvaluator:
    def __init__(self, adapters: Mapping[str, BaselineAdapter]):
        self.adapters = dict(adapters)

    def run(
        self,
        cases: Iterable[EvalCase],
        baseline_id: str,
        output_root: str | Path = "eval_outputs",
        run_id: str | None = None,
    ) -> Dict[str, Any]:
        if baseline_id not in self.adapters:
            raise ValueError(f"Unsupported baseline `{baseline_id}`. Available: {sorted(self.adapters)}")
        run_name = run_id or _default_run_id(baseline_id)
        run_root = Path(output_root) / run_name
        run_root.mkdir(parents=True, exist_ok=True)

        adapter = self.adapters[baseline_id]
        rows: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []
        case_list = list(cases)
        for case in case_list:
            case_root = run_root / "artifacts" / case.case_id / baseline_id
            case_root.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            try:
                result = adapter(case, case_root)
                result.setdefault("total_latency_sec", round(time.perf_counter() - started, 4))
                metrics = compute_case_metrics(case=case, result=result)
                metrics["baseline_id"] = baseline_id
                metrics["status"] = str(result.get("status", "completed"))
                metrics["error"] = str(result.get("error", ""))
                metrics["artifacts"] = {key: str(value) for key, value in dict(result.get("artifacts", {})).items()}
                rows.append(metrics)
                if metrics["task_completion_rate"] < 1.0 or metrics["status"] != "completed":
                    failures.append(_failure_row(case, baseline_id, metrics, result))
            except Exception as exc:  # pragma: no cover - exercised by integration failure paths.
                metrics = compute_case_metrics(case=case, result={"total_latency_sec": round(time.perf_counter() - started, 4)})
                metrics["baseline_id"] = baseline_id
                metrics["status"] = "failed"
                metrics["error"] = str(exc)
                metrics["artifacts"] = {}
                rows.append(metrics)
                failures.append(_failure_row(case, baseline_id, metrics, {"error": str(exc)}))

        summary = {
            "run_id": run_name,
            "baseline_id": baseline_id,
            "case_count": len(case_list),
            "created_at_unix": int(time.time()),
            "metrics": aggregate_metrics(rows),
            "outputs": {
                "eval_summary": str(run_root / "eval_summary.json"),
                "per_case_metrics": str(run_root / "per_case_metrics.jsonl"),
                "baseline_comparison": str(run_root / "baseline_comparison.json"),
                "failure_cases": str(run_root / "failure_cases.jsonl"),
            },
        }
        comparison = {
            "run_id": run_name,
            "baselines": {baseline_id: summary["metrics"]},
            "comparison_note": "Phase 0 may contain a single baseline; future runs can append additional baselines for deltas.",
        }

        _write_json(run_root / "eval_summary.json", summary)
        _write_jsonl(run_root / "per_case_metrics.jsonl", rows)
        _write_json(run_root / "baseline_comparison.json", comparison)
        _write_jsonl(run_root / "failure_cases.jsonl", failures)
        return summary


def _failure_row(case: EvalCase, baseline_id: str, metrics: Mapping[str, Any], result: Mapping[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    if metrics.get("artifact_generation_pass") is not True:
        reasons.append("artifact_generation_failed")
    if float(metrics.get("required_sections_coverage", 0.0) or 0.0) < 1.0:
        reasons.append("required_sections_incomplete")
    if metrics.get("verification_pass") is not True:
        reasons.append("verification_failed")
    if metrics.get("status") != "completed":
        reasons.append(str(metrics.get("status") or "not_completed"))
    return {
        "case_id": case.case_id,
        "baseline_id": baseline_id,
        "reasons": reasons,
        "status": metrics.get("status", ""),
        "error": metrics.get("error") or result.get("error", ""),
        "task_completion_rate": metrics.get("task_completion_rate", 0.0),
        "required_sections_coverage": metrics.get("required_sections_coverage", 0.0),
    }


def _default_run_id(baseline_id: str) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{baseline_id}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(dict(row), ensure_ascii=False) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")
