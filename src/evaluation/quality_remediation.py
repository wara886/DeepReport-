"""Build remediation plans from delivery quality gates.

The remediation plan is operational guidance for the next run. It is never
evidence and must not be cited as a source in the report.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

from src.evaluation.report_quality import resolve_run_paths


EMPTY_PHRASES = [
    "no conclusion",
    "no verifiable conclusion",
    "unable to judge",
    "to be filled",
    "framework-only conclusion",
]


def build_quality_remediation_plan(run_dir: str | Path) -> Dict[str, Any]:
    paths = resolve_run_paths(run_dir)
    return build_quality_remediation_plan_from_outputs(paths.outputs_dir, paths.run_dir)


def build_quality_remediation_plan_from_outputs(
    outputs_dir: str | Path,
    run_dir: str | Path | None = None,
) -> Dict[str, Any]:
    outputs = Path(outputs_dir)
    summary = _read_json(outputs / "run_summary.json", {})
    delivery_gate = _read_json(outputs / "delivery_gate.json", {})
    quality = _read_json(outputs / "quality_report.json", {})
    llm_review = _read_json(outputs / "llm_quality_review.json", {})
    issues = _normalize_issues(delivery_gate.get("issues") or delivery_gate.get("top_issues") or [])
    if not issues:
        issues = _normalize_issues((quality.get("issues") or []) + (llm_review.get("issues") or []))

    required_fixes = _required_fixes(issues, quality, llm_review)
    failed_sections = _failed_sections(issues, quality)
    forbidden_patterns = _forbidden_patterns(issues)
    responsible_agents = _responsible_agents(issues, failed_sections)
    summary_text = _summary_text(summary, delivery_gate, issues, required_fixes)
    return {
        "schema_version": "quality_remediation_plan.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs),
        "symbol": str(summary.get("symbol") or ""),
        "period": str(summary.get("period") or ""),
        "delivery_pass": bool(delivery_gate.get("delivery_pass", False)),
        "quality_feedback_used": bool(issues or not delivery_gate.get("delivery_pass", True)),
        "issue_counts": dict(delivery_gate.get("issue_counts") or {}),
        "failed_sections": failed_sections,
        "responsible_agents": responsible_agents,
        "required_fixes": required_fixes,
        "forbidden_patterns": forbidden_patterns,
        "top_issues": issues[:8],
        "planner_constraints": _planner_constraints(required_fixes, forbidden_patterns),
        "memory_note": summary_text,
        "boundary": "Quality feedback is planning context only; report facts still require evidence_id citations and verifier gates.",
    }


def write_quality_remediation_plan(run_dir: str | Path, plan: Dict[str, Any] | None = None) -> Dict[str, str]:
    paths = resolve_run_paths(run_dir)
    return write_quality_remediation_plan_for_outputs(paths.outputs_dir, plan or build_quality_remediation_plan(run_dir))


def write_quality_remediation_plan_for_outputs(outputs_dir: str | Path, plan: Dict[str, Any]) -> Dict[str, str]:
    outputs = Path(outputs_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / "quality_remediation_plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_run_summary(outputs / "run_summary.json", path, plan)
    return {"quality_remediation_plan": str(path)}


def _normalize_issues(items: List[Any]) -> List[Dict[str, Any]]:
    severity_order = {"fatal": 0, "blocker": 1, "warning": 2, "info": 3}
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            rows.append(
                {
                    "issue_id": str(item.get("issue_id") or f"quality_{index:04d}"),
                    "severity": str(item.get("severity") or "warning"),
                    "category": str(item.get("category") or item.get("source") or "quality"),
                    "message": _issue_message(item, "quality issue"),
                    "source": str(item.get("source") or "quality"),
                }
            )
        else:
            rows.append(
                {
                    "issue_id": f"quality_{index:04d}",
                    "severity": "warning",
                    "category": "quality",
                    "message": str(item),
                    "source": "quality",
                }
            )
    rows.sort(key=lambda row: (severity_order.get(row["severity"], 9), row["category"], row["issue_id"]))
    return rows


def _required_fixes(issues: List[Dict[str, Any]], quality: Dict[str, Any], llm_review: Dict[str, Any]) -> List[str]:
    text = _norm(" ".join(issue["category"] + " " + issue["message"] for issue in issues))
    fixes: List[str] = []
    if "content_depth" in text or any(term in text for term in ["content insufficient", "truncated", "unfinished", "正文完整度", "section missing"]):
        fixes.append("Rewrite thin, missing, or truncated core sections to meet the formal section contract before delivery.")
    if _mentions_financial_statements(text):
        fixes.append("Backfill income statement, balance sheet, and cash flow statement summaries from primary or structured evidence.")
    if any(term in text for term in ["valuation", "sensitivity", "p/e", "p/b", "p/s"]):
        fixes.append("Add a minimum valuation path, or explain the missing inputs and impact on investment judgment.")
    if any(term in text for term in ["peer", "comparison", "同行", "对比"]):
        fixes.append("Add peer comparison metrics and explicit boundaries instead of framework-only text.")
    if any(term in text for term in ["hollow", "empty", "framework", "内容空洞", "空壳"]):
        fixes.append("Rewrite hollow sections with evidence-backed business implications, investment judgment, and risk boundaries.")
    if any(term in text for term in ["investment conclusion", "recommendation", "投资结论", "投资建议"]):
        fixes.append("Investment conclusion must include direction, reasons, cited evidence, and risk constraints.")

    required = quality.get("required_checks", {}) if isinstance(quality.get("required_checks"), dict) else {}
    failed = _failed_required_keys(required) if required and not required.get("passed", True) else []
    if failed:
        fixes.append("Repair failed objective gate checks: " + ", ".join(failed) + ".")
    if llm_review.get("llm_review_pass") is False:
        fixes.append("Prioritize fatal/blocker issues from the LLM review before final delivery.")
    return _dedupe(fixes) or ["Preserve delivery gate feedback and improve professional depth and readability."]


def _failed_sections(issues: List[Dict[str, Any]], quality: Dict[str, Any] | None = None) -> List[str]:
    text = _norm(" ".join(issue["category"] + " " + issue["message"] for issue in issues))
    required = quality.get("required_checks", {}) if isinstance(quality, dict) and isinstance(quality.get("required_checks"), dict) else {}
    failed_required = set(_failed_required_keys(required)) if required and not required.get("passed", True) else set()
    output: List[str] = []
    if any(term in text for term in ["content_depth", "content insufficient", "truncated", "unfinished", "section missing", "正文完整度"]):
        output.extend(_sections_from_content_depth_issues(issues))
    if _mentions_financial_statements(text) or "has_three_table_summary" in failed_required:
        output.append("three_statement_analysis")
    if any(term in text for term in ["business", "identity", "industry", "主营", "业务"]):
        output.append("business_profile")
    if any(term in text for term in ["peer", "comparison", "同行", "对比"]):
        output.append("peer_comparison")
    if any(term in text for term in ["valuation", "p/e", "p/b", "p/s", "估值"]):
        output.append("valuation")
    if any(term in text for term in ["sensitivity", "scenario", "敏感"]):
        output.append("sensitivity")
    if any(term in text for term in ["risk", "风险"]):
        output.append("risk")
    if any(term in text for term in ["investment conclusion", "recommendation", "投资结论", "投资建议"]):
        output.append("investment_conclusion")
    if any(term in text for term in ["executive", "summary", "摘要"]):
        output.append("executive_summary")
    return _dedupe(output)


def _sections_from_content_depth_issues(issues: List[Dict[str, Any]]) -> List[str]:
    mappings = [
        ("executive_summary", ("执行摘要", "executive summary", "summary")),
        ("business_profile", ("业务概览", "business overview", "business profile")),
        ("financial_analysis", ("财务分析", "financial analysis")),
        ("peer_comparison", ("同行对比", "peer", "comparison")),
        ("valuation", ("估值观察", "valuation")),
        ("sensitivity", ("估值敏感性", "sensitivity")),
        ("risk", ("风险评估", "risk")),
        ("investment_conclusion", ("投资结论", "investment conclusion", "recommendation")),
    ]
    output: List[str] = []
    for issue in issues:
        if issue.get("category") != "content_depth":
            continue
        message = _norm(str(issue.get("message") or ""))
        for section, terms in mappings:
            if any(_norm(term) in message for term in terms):
                output.append(section)
    return _dedupe(output)


def _responsible_agents(issues: List[Dict[str, Any]], failed_sections: List[str]) -> List[Dict[str, str]]:
    text = _norm(" ".join((issue.get("category", "") + " " + issue.get("message", "")) for issue in issues))
    failed_text = _norm(" ".join(failed_sections))
    financial_terms = [
        "financial",
        "has_three_table_summary",
        "three_table",
        "three statement",
        "income statement",
        "balance sheet",
        "cash flow",
        "three_statement_analysis",
        "fact_period_consistency",
        "non_recurring_gain_unadjusted",
        "valuation_input_invalid",
        "dcf",
        "single quarter fcf",
    ]
    mappings = [
        ("DeepResearcherAgent", ["missing_or_unknown_evidence", "source", "evidence missing", "citation"] + financial_terms),
        ("BrowserAgent", ["missing_or_unknown_evidence", "source", "evidence missing", "citation"] + financial_terms),
        (
            "DeepAnalyzeAgent",
            [
                "period_mismatch",
                "different_fiscal_period",
                "unsupported_numeric",
                "metric_lineage",
                "financial number",
                "period",
                "valuation",
                "sensitivity",
                "p/e",
                "p/b",
                "p/s",
            ]
            + financial_terms,
        ),
        ("StatementAgent", ["three_statement_analysis_role"]),
        ("IdentityAgent", ["identity", "industry", "business_profile"]),
        ("PeerAgent", ["peer_comparison", "peer", "comparison"]),
        ("ValuationAgent", ["valuation_analysis_role"]),
        ("RiskAgent", ["risk"]),
        (
            "FinalAnswerAgent",
            [
                "company_report_requirement_fit",
                "professional_report_likeness",
                "content_depth",
                "content insufficient",
                "truncated",
                "unfinished",
                "section missing",
                "正文完整度",
                "empty",
                "hollow",
                "framework",
            ],
        ),
    ]
    rows: List[Dict[str, str]] = []
    for agent, terms in mappings:
        if any(term in text for term in terms) or any(term in failed_text for term in terms):
            rows.append({"agent": agent, "reason": ", ".join(term for term in terms[:3])})
    return rows or [{"agent": "FinalAnswerAgent", "reason": "generic report-quality remediation"}]


def _forbidden_patterns(issues: List[Dict[str, Any]]) -> List[str]:
    text = _norm(" ".join(issue["message"] for issue in issues))
    patterns = list(EMPTY_PHRASES)
    if any(term in text for term in ["hollow", "empty", "framework", "内容空洞", "空壳"]):
        patterns.extend(["framework-only description", "unsupported investment insight"])
    return _dedupe(patterns)


def _issue_message(item: Dict[str, Any], fallback: str) -> str:
    for key in ["message", "detail", "description", "reason", "issue", "claim_id", "section_name"]:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _planner_constraints(required_fixes: List[str], forbidden_patterns: List[str]) -> List[str]:
    constraints = list(required_fixes)
    if forbidden_patterns:
        constraints.append("Do not repeat hollow placeholder patterns: " + ", ".join(forbidden_patterns[:5]) + ".")
    constraints.append("All facts and numbers must remain bound to evidence_id/citation and pass verifier gates.")
    return constraints


def _summary_text(
    summary: Dict[str, Any],
    delivery_gate: Dict[str, Any],
    issues: List[Dict[str, Any]],
    required_fixes: List[str],
) -> str:
    symbol = summary.get("symbol") or "unknown"
    period = summary.get("period") or "unknown"
    gate = delivery_gate.get("delivery_pass")
    top = "; ".join(issue["message"] for issue in issues[:3])
    fixes = "; ".join(required_fixes[:3])
    return f"Quality feedback for {symbol} {period}: delivery_pass={gate}; issues={top}; next fixes={fixes}"


def _failed_required_keys(required: Dict[str, Any]) -> List[str]:
    details = required.get("details")
    if isinstance(details, dict):
        return [key for key, value in details.items() if value is False]
    return [key for key, value in required.items() if key != "passed" and value is False]


def _mentions_financial_statements(text: str) -> bool:
    terms = [
        "financial",
        "has_three_table_summary",
        "three_table",
        "three statement",
        "income statement",
        "balance sheet",
        "cash flow",
        "profit statement",
        "利润表",
        "资产负债表",
        "现金流量表",
        "三表",
    ]
    return any(term in text for term in terms)


def _norm(value: str) -> str:
    return str(value or "").lower()


def _update_run_summary(path: Path, plan_path: Path, plan: Dict[str, Any]) -> None:
    summary = _read_json(path, {})
    if not isinstance(summary, dict):
        summary = {}
    summary["quality_remediation_plan_path"] = str(plan_path)
    summary["quality_feedback_used"] = bool(plan.get("quality_feedback_used", False))
    summary["memory_quality_feedback_used"] = bool(plan.get("quality_feedback_used", False))
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    return payload
