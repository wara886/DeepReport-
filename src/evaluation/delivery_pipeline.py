"""Delivery quality pipeline shared by report tasks and regression runners."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from src.evaluation.delivery_gate import build_delivery_gate_from_outputs, write_delivery_gate_for_outputs
from src.evaluation.llm_report_review import review_report_with_llm_from_paths, write_llm_review_outputs_for_paths
from src.evaluation.quality_remediation import (
    build_quality_remediation_plan_from_outputs,
    write_quality_remediation_plan_for_outputs,
)
from src.evaluation.report_quality import evaluate_report_quality_from_paths, write_quality_outputs_for_paths


DEFAULT_OUTPUT_DIR = "data/outputs/multi_agent"
DEFAULT_REPORT_DIR = "data/reports/multi_agent"


def run_delivery_quality_pipeline(
    output_root: str | Path = DEFAULT_OUTPUT_DIR,
    report_root: str | Path = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    durable_memory_store: Any | None = None,
    memory_enabled: bool = False,
    deadline: float | None = None,
    review_mode: str = "full",
) -> dict[str, Any]:
    output_path = Path(output_root)
    report_path = Path(report_root)
    try:
        quality_report = evaluate_report_quality_from_paths(output_path, report_path, run_dir=output_path)
        write_quality_outputs_for_paths(output_path, report_path, quality_report)
        if _deadline_expired(deadline):
            return _empty_quality_pipeline_result("deadline exceeded after objective quality")

        if review_mode == "heuristic":
            llm_review = {"llm_review_pass": None, "total_score": None, "model_status": "skipped_heuristic"}
        else:
            llm_review = review_report_with_llm_from_paths(
                output_path,
                report_path,
                run_dir=output_path,
                config_path=config_path,
            )
        write_llm_review_outputs_for_paths(output_path, report_path, llm_review)
        if _deadline_expired(deadline):
            return _empty_quality_pipeline_result("deadline exceeded after llm review")

        delivery_gate = build_delivery_gate_from_outputs(output_path, run_dir=output_path)
        write_delivery_gate_for_outputs(output_path, delivery_gate)
        if _deadline_expired(deadline):
            return _empty_quality_pipeline_result("deadline exceeded after delivery gate")

        remediation_plan = build_quality_remediation_plan_from_outputs(output_path, run_dir=output_path)
        write_quality_remediation_plan_for_outputs(output_path, remediation_plan)
        memory_quality_feedback: dict[str, Any] = {}
        if memory_enabled and durable_memory_store is not None and remediation_plan.get("quality_feedback_used"):
            memory_quality_feedback = durable_memory_store.persist_quality_feedback(remediation_plan)
            _update_summary_quality_feedback(output_path / "run_summary.json", memory_quality_feedback)

        return {
            "quality_report": {
                "objective_pass": quality_report.get("objective_pass"),
                "total_score": quality_report.get("total_score"),
            },
            "llm_quality_review": {
                "llm_review_pass": llm_review.get("llm_review_pass"),
                "total_score": llm_review.get("total_score"),
                "model_status": llm_review.get("model_status"),
            },
            "delivery_gate": {
                "status": delivery_gate.get("status"),
                "delivery_pass": delivery_gate.get("delivery_pass"),
                "verifier_passed": delivery_gate.get("verifier_passed"),
                "objective_pass": delivery_gate.get("objective_pass"),
                "llm_review_pass": delivery_gate.get("llm_review_pass"),
            },
            "remediation_plan": {
                "quality_feedback_used": remediation_plan.get("quality_feedback_used"),
                "required_fixes": remediation_plan.get("required_fixes", [])[:5],
                "failed_sections": remediation_plan.get("failed_sections", []),
                "memory_quality_feedback_used": bool(memory_quality_feedback),
            },
            "top_quality_issues": delivery_gate.get("top_issues", []),
        }
    except Exception as exc:
        _write_run_error(output_path, exc)
        failed_gate = {
            "status": "completed",
            "delivery_pass": False,
            "diagnostic_delivery_pass": False,
            "diagnostic_only": True,
            "quality_pipeline_error": str(exc),
        }
        try:
            write_delivery_gate_for_outputs(output_path, failed_gate)
        except Exception:
            pass
        return {
            "quality_report": None,
            "llm_quality_review": None,
            "delivery_gate": failed_gate,
            "remediation_plan": None,
            "top_quality_issues": [{"category": "quality_pipeline_error", "message": str(exc)}],
            "_quality_pipeline_exception": str(exc),
        }


def run_delivery_rework_loop(
    *,
    orchestrator: Any,
    output_path: str | Path,
    report_path: str | Path,
    config_path: str,
    initial_quality_result: dict[str, Any],
    run_kwargs: dict[str, Any],
    durable_memory_store: Any | None = None,
    memory_enabled: bool = False,
    max_rounds: int = 1,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Rerun the current orchestrator with structured quality feedback."""

    output_dir = Path(output_path)
    report_dir = Path(report_path)
    current_quality = dict(initial_quality_result or {})
    rounds: list[dict[str, Any]] = []
    if _delivery_passed(current_quality):
        return {"rounds": rounds, "reworked": False, "quality_result": current_quality}

    if orchestrator is None:
        rounds.append(
            {
                "round": 0,
                "status": "skipped",
                "trigger": "quality_diagnostic",
                "handled": False,
                "unfixable_reasons": ["orchestrator unavailable"],
            }
        )
        _write_rework_history(output_dir, rounds)
        return {"rounds": rounds, "reworked": False, "quality_result": current_quality}

    for round_index in range(1, max(0, int(max_rounds)) + 1):
        if _deadline_expired(deadline):
            rounds.append(
                {
                    "round": round_index,
                    "status": "skipped",
                    "trigger": "quality_diagnostic",
                    "handled": False,
                    "unfixable_reasons": ["delivery rework deadline exceeded"],
                }
            )
            break

        remediation = _read_json(output_dir / "quality_remediation_plan.json")
        if not isinstance(remediation, dict):
            remediation = {}
        remediation.setdefault("quality_feedback_used", True)
        remediation.setdefault("required_fixes", _quality_issue_messages(current_quality))

        rerun_kwargs = dict(run_kwargs or {})
        rerun_kwargs["quality_remediation_plan"] = remediation
        orchestrator.run(**rerun_kwargs)
        current_quality = run_delivery_quality_pipeline(
            output_root=output_dir,
            report_root=report_dir,
            config_path=config_path,
            durable_memory_store=durable_memory_store,
            memory_enabled=memory_enabled,
            deadline=deadline,
        )
        passed = _delivery_passed(current_quality)
        rounds.append(
            {
                "round": round_index,
                "status": "completed",
                "trigger": "quality_diagnostic",
                "handled": True,
                "rework_mode": "current_orchestrator_rerun",
                "delivery_pass_after_round": passed,
                "required_fixes": remediation.get("required_fixes", []),
            }
        )
        if passed:
            break

    _write_rework_history(output_dir, rounds)
    return {"rounds": rounds, "reworked": bool(rounds and any(item.get("handled") for item in rounds)), "quality_result": current_quality}


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _empty_quality_pipeline_result(reason: str) -> dict[str, Any]:
    return {
        "quality_report": {"objective_pass": False, "total_score": 0.0},
        "llm_quality_review": {"llm_review_pass": None, "total_score": None, "model_status": "skipped_deadline"},
        "delivery_gate": {
            "status": "completed",
            "delivery_pass": False,
            "diagnostic_delivery_pass": False,
            "diagnostic_only": True,
            "verifier_passed": False,
            "objective_pass": False,
            "llm_review_pass": None,
        },
        "remediation_plan": {"quality_feedback_used": False, "required_fixes": [], "failed_sections": []},
        "top_quality_issues": [],
        "_deadline_reason": reason,
    }


def _update_summary_quality_feedback(summary_path: Path, feedback: dict[str, Any]) -> None:
    summary = _read_json(summary_path)
    if not isinstance(summary, dict):
        return
    summary["memory_quality_feedback_used"] = bool(feedback)
    summary["memory_quality_feedback"] = feedback
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_run_error(output_path: Path, exc: Exception) -> None:
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "run_error.json").write_text(
            json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _delivery_passed(quality_result: dict[str, Any]) -> bool:
    gate = quality_result.get("delivery_gate")
    return isinstance(gate, dict) and gate.get("delivery_pass") is True


def _quality_issue_messages(quality_result: dict[str, Any]) -> list[str]:
    issues = quality_result.get("top_quality_issues")
    if not isinstance(issues, list):
        return []
    messages: list[str] = []
    for item in issues:
        if isinstance(item, dict):
            message = str(item.get("message") or item.get("category") or "").strip()
        else:
            message = str(item).strip()
        if message and message not in messages:
            messages.append(message)
    return messages[:8]


def _write_rework_history(output_path: Path, rounds: list[dict[str, Any]]) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "delivery_rework_history.json").write_text(
        json.dumps(rounds, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
