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
    section_verification = _read_json(outputs / "section_verification.json", {})
    section_packs = _read_json(outputs / "section_evidence_packs.json", {})
    section_repair = _read_json(outputs / "section_repair.json", {})
    retrieval_attribution = _read_json(outputs / "evidence_retrieval_attribution.json", {})
    verifier_passed = bool(verification.get("passed", summary.get("verification_passed", False)))
    objective_pass = bool(quality.get("objective_pass", False))
    issues = _collect_issues(verification, quality, llm_review)
    if isinstance(section_verification, dict) and section_verification.get("status") == "failed":
        for item in section_verification.get("issues") or []:
            issues.append(_normalize_issue(item, "section_verification"))
    if isinstance(retrieval_attribution, dict):
        attribution_issues = _attribution_diagnostic_issues(retrieval_attribution, start_index=len(issues) + 1)
        issues.extend(attribution_issues)
    issues.extend(_section_delivery_issues(section_packs, section_verification, section_repair, len(issues) + 1))

    # Read contract-first generation artifacts for top_blockers
    contracts_data = _read_json(outputs / "report_section_contracts.json", None)
    if isinstance(contracts_data, dict) and "contracts" in contracts_data:
        contract_blockers = _extract_top_blockers_from_contracts(contracts_data)
        if contract_blockers:
            contract_severity = "blocker" if len(contract_blockers) >= 2 else "warning"
            if objective_pass and _contract_blockers_are_boundary_disclosures(contract_blockers):
                contract_severity = "warning"
            issues.append({
                "issue_id": f"contract_blockers_{len(issues) + 1:04d}",
                "severity": contract_severity,
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
    issues.extend(
        _missing_gate_failure_issues(
            issues,
            verifier_passed=verifier_passed,
            objective_pass=objective_pass,
            llm_review_pass=llm_review_pass,
        )
    )
    blocking_issue = any(item.get("severity") in {"fatal", "blocker"} for item in issues)
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
    total = quality.get("total_score", 0)
    threshold = quality.get("quality_threshold", 0.82)
    score_pass = isinstance(total, (int, float)) and total >= threshold
    diagnostic_delivery_pass = (
        score_pass
        and objective_pass
        and verifier_passed
        and llm_review_pass
        and not blocking_issue
    )
    # Delivery gate: use actual computed value.
    # Content-depth blockers are formal delivery blockers: a truncated or
    # placeholder report may be a draft, but it is not a deliverable report.
    delivery_pass = bool(diagnostic_delivery_pass)
    status = "completed"
    return {
        "schema_version": "delivery_gate.v1",
        "diagnostic_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs),
        "status": status,
        "delivery_pass": delivery_pass,
        "machine_quality_pass": delivery_pass,
        "formal_delivery_pass": None,
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
            "formula": "delivery_pass = score_pass && objective_pass && verifier_passed && llm_review_pass && no_fatal_or_blocker",
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
            "content_depth_blocks_formal_delivery": bool(content_depth_blockers),
            "section_verification_passed": bool(section_verification.get("formal_delivery_allowed", True)),
        },
        "evidence_retrieval_attribution": _attribution_summary(retrieval_attribution),
        "section_evidence_contract": {
            "available": bool(section_packs.get("packs")) if isinstance(section_packs, dict) else False,
            "repair_status": section_repair.get("status") if isinstance(section_repair, dict) else None,
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


def _missing_gate_failure_issues(
    issues: List[Dict[str, Any]],
    *,
    verifier_passed: bool,
    objective_pass: bool,
    llm_review_pass: bool,
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    requirements = [
        ("verifier", verifier_passed, "Verifier did not pass, but no blocking verifier issue was emitted."),
        ("objective_quality", objective_pass, "Objective quality checks did not pass."),
        ("llm_review", llm_review_pass, "LLM review did not satisfy the formal quality contract."),
    ]
    for category, passed, message in requirements:
        if passed:
            continue
        explained = any(
            str(item.get("category") or "") in {category, "content", "content_depth", "gate"}
            and str(item.get("severity") or "") in {"fatal", "blocker"}
            for item in issues
        )
        if explained:
            continue
        output.append(
            {
                "issue_id": f"gate_requirement_{category}_{len(issues) + len(output) + 1:04d}",
                "severity": "blocker",
                "category": category,
                "message": message,
                "source": "delivery_gate",
            }
        )
    return output


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


def _attribution_diagnostic_issues(attribution: Dict[str, Any], *, start_index: int) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    roots = attribution.get("overall_root_causes") if isinstance(attribution.get("overall_root_causes"), list) else []
    for index, row in enumerate(roots[:3], start=start_index):
        if not isinstance(row, dict):
            continue
        cause = str(row.get("cause") or "")
        if not cause:
            continue
        output.append(
            {
                "issue_id": f"retrieval_attribution_{index:04d}",
                "severity": "warning",
                "category": "retrieval_attribution",
                "message": f"{row.get('label') or cause}: {row.get('recommended_action') or ''}".strip(),
                "source": "evidence_retrieval_attribution",
                "cause": cause,
            }
        )
    return output


def _section_delivery_issues(packs: Any, verification: Any, repair: Any, start_index: int) -> List[Dict[str, Any]]:
    if not isinstance(packs, dict) or not isinstance(packs.get("packs"), dict):
        return []
    results = verification.get("section_results") if isinstance(verification, dict) else {}
    results = results if isinstance(results, dict) else {}
    core_sections = {"executive_summary", "business_overview", "financial_analysis", "valuation", "risks", "conclusion"}
    output: List[Dict[str, Any]] = []
    for section, pack in packs["packs"].items():
        if section not in core_sections or not isinstance(pack, dict):
            continue
        result = results.get(section) if isinstance(results.get(section), dict) else {}
        unsupported = pack.get("unsupported_claim_ids") or []
        required = pack.get("must_use_evidence_ids") or []
        consumed = result.get("consumed_evidence_ids") or []
        if unsupported:
            output.append({
                "issue_id": f"section_evidence_{start_index + len(output):04d}",
                "severity": "blocker",
                "category": "claim_support",
                "section": section,
                "message": f"Core section has unsupported claims: {', '.join(map(str, unsupported[:5]))}",
                "source": "section_evidence_packs",
            })
        if required and not consumed:
            output.append({
                "issue_id": f"section_evidence_{start_index + len(output):04d}",
                "severity": "blocker",
                "category": "evidence_consumption",
                "section": section,
                "message": "Core section did not consume any must-use evidence.",
                "source": "section_evidence_packs",
            })
    if isinstance(repair, dict) and repair.get("failed_sections_after"):
        output.append({
            "issue_id": f"section_repair_{start_index + len(output):04d}",
            "severity": "blocker",
            "category": "section_repair",
            "message": "Section repair completed with unresolved core sections.",
            "source": "section_repair",
        })
    return output


def _attribution_summary(attribution: Any) -> Dict[str, Any]:
    if not isinstance(attribution, dict):
        return {"available": False}
    roots = attribution.get("overall_root_causes") if isinstance(attribution.get("overall_root_causes"), list) else []
    top = roots[0] if roots and isinstance(roots[0], dict) else {}
    retrieval = attribution.get("retrieval_summary") if isinstance(attribution.get("retrieval_summary"), dict) else {}
    return {
        "available": True,
        "top_root_cause": top.get("cause"),
        "top_root_cause_label": top.get("label"),
        "top_recommended_action": top.get("recommended_action"),
        "similarity_status": retrieval.get("similarity_status"),
        "vector_score_max": retrieval.get("vector_score_max"),
        "local_candidate_count": retrieval.get("local_candidate_count"),
        "local_returned_count": retrieval.get("local_returned_count"),
    }


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
                if _nonblocking_contract_reason(str(reason)):
                    continue
                label = f'{sk}:{reason}'
                if label not in blockers:
                    blockers.append(label)
            for flag in sc.get('quality_flags', []):
                if _nonblocking_contract_flag(str(flag)):
                    continue
                label = f'quality:{flag}'
                if label not in blockers:
                    blockers.append(label)
    return blockers[:10]


def _nonblocking_contract_reason(reason: str) -> bool:
    return reason in {
        "business_overview_used_profile_fallback",
        "risk_industry_fallback_used",
    } or reason.startswith("valuation_model_status:")


def _nonblocking_contract_flag(flag: str) -> bool:
    return (
        flag.endswith("_uses_section_evidence_pack")
        or "_uses_sec_10k" in flag
        or flag.endswith("_evidence_fallback")
        or flag == "valuation_directional_only"
        or flag.endswith("_pdf_summary_fallback")
        or flag.endswith("_pdf_chunk_fallback")
    )


def _contract_blockers_are_boundary_disclosures(blockers: list) -> bool:
    """Return true for contract diagnostics already covered by objective checks.

    These are not ignored: delivery_gate still surfaces them as warnings.  They
    should not double-block once objective quality and section verification have
    accepted the report as a constrained draft/formal package.
    """

    boundary_terms = {
        "ownership_governance:governance_section_not_found",
        "strategy_business:strategy_pdf_sections_not_found",
        "quality:valuation_sensitivity_framework_only",
        "risk_factors:risk_official_pdf_not_found_and_no_industry_fallback",
        "quality:risk_generic_fallback_no_industry_policy",
        "ownership_governance:governance_summary_not_injected",
        "quality:peer_compare_boundary_only",
        "quality:valuation_sensitivity_boundary_only",
        "quality:valuation_sensitivity_earnings_bridge_only",
    }
    return all(str(item) in boundary_terms for item in blockers)
