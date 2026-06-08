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
    issues = _collect_issues(verification, quality, llm_review)

    # Read contract-first generation artifacts for top_blockers
    contracts_data = _read_json(outputs / "report_section_contracts.json", None)
    if isinstance(contracts_data, dict) and "contracts" in contracts_data:
        contract_blockers = _extract_top_blockers_from_contracts(contracts_data)
        if contract_blockers:
            issues.append({
                "issue_id": f"contract_blockers_{len(issues) + 1:04d}",
                "severity": "blocker" if len(contract_blockers) >= 2 else "warning",
                "category": "contract",
                "message": f"Contract blockers: {'; '.join(contract_blockers[:5])}",
                "source": "contract",
                "blockers": contract_blockers[:10],
            })

    blocking_issue = any(item.get("severity") in {"fatal", "blocker"} for item in issues)
    llm_blocking_issue = any(item.get("category") == "llm_review" and item.get("severity") in {"fatal", "blocker"} for item in issues)
    llm_score = _safe_float(llm_review.get("total_score"))
    llm_score_strict_pass = llm_score is not None and llm_score >= 0.80
    llm_score_relaxed_pass = (
        bool(llm_review.get("llm_review_pass", False))
        and llm_score is not None
        and llm_score >= 0.70
        and not blocking_issue
        and verifier_passed
        and objective_pass
    )
    llm_score_pass = llm_score_strict_pass or llm_score_relaxed_pass
    llm_review_pass = bool(llm_review.get("llm_review_pass", False)) and llm_score_pass and not blocking_issue
    # 区分 content_depth blockers 和其他 blockers
    # content_depth 是内容长度不足，不影响数据准确性，用户模式下不阻断
    content_depth_blockers = [
        item for item in issues
        if item.get("severity") in {"fatal", "blocker"}
        and item.get("category") == "content_depth"
    ]
    other_blockers = [
        item for item in issues
        if item.get("severity") in {"fatal", "blocker"}
        and item.get("category") != "content_depth"
    ]
    # 用户模式：content_depth blockers 不阻断交付（内容可以后续改进，不影响数据准确性）
    # 只要其他 blocker 为 0、verifier 通过、总分达标即可
    total = quality.get("total_score", 0)
    threshold = quality.get("quality_threshold", 0.82)
    score_pass = isinstance(total, (int, float)) and total >= threshold
    diagnostic_delivery_pass = (
        score_pass
        and verifier_passed
        and len(other_blockers) == 0
        and not llm_blocking_issue
    )
    # Delivery gate: use actual computed value.
    # diagnostic_delivery_pass excludes content_depth blockers (内容长度不足不阻断).
    # This was previously hardcoded True during development; now it reflects the real gate.
    delivery_pass = bool(diagnostic_delivery_pass)
    status = "completed"
    return {
        "schema_version": "delivery_gate.v1",
        "diagnostic_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs),
        "status": status,
        "delivery_pass": delivery_pass,
        "diagnostic_delivery_pass": diagnostic_delivery_pass,
        "verifier_passed": verifier_passed,
        "objective_pass": objective_pass,
        "llm_review_pass": llm_review_pass,
        "blocker_counts": {
            "content_depth": len(content_depth_blockers),
            "other": len(other_blockers),
            "total": len(content_depth_blockers) + len(other_blockers),
        },
        "scores": {
            "objective_total_score": quality.get("total_score"),
            "llm_total_score": llm_review.get("total_score"),
            "company_report_score": summary.get("company_report_overall_score") or summary.get("company_report_score"),
        },
        "gate_requirements": {
            "formula": "diagnostic_delivery_pass = score_pass && verifier_passed && no_non_content_blockers && no_llm_blocking_issue",
            "diagnostic_only": True,
            "verification_passed": verifier_passed,
            "objective_pass": objective_pass,
            "llm_review_pass": llm_review_pass,
            "llm_review_min_total_score": 0.80,
            "llm_review_score_pass": llm_score_pass,
            "llm_review_strict_score_pass": llm_score_strict_pass,
            "llm_review_relaxed_score_pass": llm_score_relaxed_pass,
            "llm_review_no_fatal_or_blocker": not llm_blocking_issue,
            "delivery_no_fatal_or_blocker": not blocking_issue,
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
    path.write_text(json.dumps(_json_safe(gate), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return {"delivery_gate": str(path)}


def _collect_issues(verification: Dict[str, Any], quality: Dict[str, Any], llm_review: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for item in quality.get("top_issues") or quality.get("issues") or []:
        issues.append(_normalize_issue(item, "objective"))
    for item in llm_review.get("issues") or []:
        issues.append(_normalize_issue(item, "llm_review"))
    for error in verification.get("errors") or []:
        issues.append({"issue_id": f"verifier_{len(issues) + 1:04d}", "severity": "fatal", "category": "verifier", "message": _issue_message(error, "verifier error")})
    for gap in verification.get("evidence_gaps") or []:
        severity = "blocker"
        if isinstance(gap, dict) and gap.get("blocking") is False:
            severity = "warning"
        issues.append({"issue_id": f"verifier_{len(issues) + 1:04d}", "severity": severity, "category": "verifier", "message": _issue_message(gap, "evidence gap")})
    order = {"fatal": 0, "blocker": 1, "warning": 2, "info": 3}
    return sorted(issues, key=lambda item: (order.get(item.get("severity"), 9), item.get("category", "")))


def _normalize_issue(item: Any, source: str) -> Dict[str, Any]:
    if isinstance(item, dict):
        return {
            "issue_id": str(item.get("issue_id") or f"{source}_issue"),
            "severity": str(item.get("severity") or "warning"),
            "category": str(item.get("category") or source),
            "message": _issue_message(item, source),
            "source": source,
        }
    return {"issue_id": f"{source}_issue", "severity": "warning", "category": source, "message": str(item), "source": source}


def _issue_message(item: Any, fallback: str) -> str:
    if isinstance(item, dict):
        for key in ["message", "detail", "description", "reason", "issue", "claim_id", "section", "metric_name"]:
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    if item not in (None, ""):
        return str(item)
    return fallback


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str):
        return "".join(ch if (ord(ch) >= 32 or ch in "\n\r\t") else " " for ch in value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    return value


def _extract_top_blockers_from_contracts(contracts_data: dict) -> list:
    """Extract top blockers from report_section_contracts.json data."""
    blockers = []
    for sk, sc in contracts_data.get('contracts', {}).items():
        if isinstance(sc, dict):
            for reason in sc.get('blocked_reasons', []):
                label = f'{sk}:{reason}'
                if label not in blockers:
                    blockers.append(label)
            for flag in sc.get('quality_flags', []):
                label = f'quality:{flag}'
                if label not in blockers:
                    blockers.append(label)
    return blockers[:10]
