"""Final delivery gate combining verifier, objective eval, and LLM review."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

from src.evaluation.report_quality import resolve_run_paths


def build_delivery_gate(run_dir: str | Path) -> Dict[str, Any]:
    paths = resolve_run_paths(run_dir)
    return build_delivery_gate_from_outputs(paths.outputs_dir, paths.run_dir)


def build_delivery_gate_from_outputs(outputs_dir: str | Path, run_dir: str | Path | None = None) -> Dict[str, Any]:
    outputs = Path(outputs_dir)
    summary = _read_json(outputs / "run_summary.json", {})
    verification = _read_json(outputs / "verification_report.json", {})
    quality = _read_json(outputs / "quality_report.json", {})
    llm_review = _read_json(outputs / "llm_quality_review.json", {})
    verifier_passed = bool(verification.get("passed", summary.get("verification_passed", False)))
    objective_pass = bool(quality.get("objective_pass", False))
    llm_review_pass = bool(llm_review.get("llm_review_pass", False))
    issues = _collect_issues(verification, quality, llm_review)
    delivery_pass = bool(verifier_passed and objective_pass and llm_review_pass)
    return {
        "schema_version": "delivery_gate.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs),
        "delivery_pass": delivery_pass,
        "verifier_passed": verifier_passed,
        "objective_pass": objective_pass,
        "llm_review_pass": llm_review_pass,
        "scores": {
            "objective_total_score": quality.get("total_score"),
            "llm_total_score": llm_review.get("total_score"),
            "company_report_score": summary.get("company_report_overall_score") or summary.get("company_report_score"),
        },
        "gate_requirements": {
            "verification_passed": verifier_passed,
            "objective_pass": objective_pass,
            "llm_review_pass": llm_review_pass,
        },
        "issue_counts": {
            "fatal": sum(1 for item in issues if item.get("severity") == "fatal"),
            "blocker": sum(1 for item in issues if item.get("severity") == "blocker"),
            "warning": sum(1 for item in issues if item.get("severity") == "warning"),
            "info": sum(1 for item in issues if item.get("severity") == "info"),
        },
        "top_issues": issues[:5],
        "issues": issues,
    }


def write_delivery_gate(run_dir: str | Path, gate: Dict[str, Any] | None = None) -> Dict[str, str]:
    paths = resolve_run_paths(run_dir)
    return write_delivery_gate_for_outputs(paths.outputs_dir, gate or build_delivery_gate(run_dir))


def write_delivery_gate_for_outputs(outputs_dir: str | Path, gate: Dict[str, Any]) -> Dict[str, str]:
    outputs = Path(outputs_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / "delivery_gate.json"
    path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"delivery_gate": str(path)}


def _collect_issues(verification: Dict[str, Any], quality: Dict[str, Any], llm_review: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for item in quality.get("top_issues") or quality.get("issues") or []:
        issues.append(_normalize_issue(item, "objective"))
    for item in llm_review.get("issues") or []:
        issues.append(_normalize_issue(item, "llm_review"))
    for error in verification.get("errors") or []:
        issues.append({"issue_id": f"verifier_{len(issues) + 1:04d}", "severity": "fatal", "category": "verifier", "message": str(error)})
    for gap in verification.get("evidence_gaps") or []:
        message = gap.get("message") if isinstance(gap, dict) else str(gap)
        issues.append({"issue_id": f"verifier_{len(issues) + 1:04d}", "severity": "blocker", "category": "verifier", "message": str(message)})
    order = {"fatal": 0, "blocker": 1, "warning": 2, "info": 3}
    return sorted(issues, key=lambda item: (order.get(item.get("severity"), 9), item.get("category", "")))


def _normalize_issue(item: Any, source: str) -> Dict[str, Any]:
    if isinstance(item, dict):
        return {
            "issue_id": str(item.get("issue_id") or f"{source}_issue"),
            "severity": str(item.get("severity") or "warning"),
            "category": str(item.get("category") or source),
            "message": str(item.get("message") or item.get("detail") or item.get("issue") or ""),
            "source": source,
        }
    return {"issue_id": f"{source}_issue", "severity": "warning", "category": source, "message": str(item), "source": source}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
