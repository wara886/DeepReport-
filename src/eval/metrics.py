"""Minimal Phase 0 metrics for baseline and future architecture comparisons."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from src.eval.schema import EvalCase


CITATION_PATTERN = re.compile(r"\[[A-Za-z0-9_:\-./]+\]")


def compute_case_metrics(case: EvalCase, result: Mapping[str, Any]) -> Dict[str, Any]:
    artifacts = _artifact_paths(result.get("artifacts", {}))
    report_text = _report_text(result, artifacts)
    claims = _as_list(result.get("claims")) or _read_json_list(artifacts.get("claims"))
    evidence = _as_list(result.get("evidence")) or _read_json_list(artifacts.get("evidence"))
    citations = _as_list(result.get("citations")) or _read_json_list(artifacts.get("citations"))
    verification = _as_dict(result.get("verification")) or _read_json_dict(artifacts.get("verification_report"))
    run_summary = _as_dict(result.get("run_summary")) or _read_json_dict(artifacts.get("run_summary"))
    rework_trace = _as_list(result.get("rework_trace")) or _read_json_list(artifacts.get("rework_trace"))
    agent_messages = _as_list(result.get("agent_messages")) or _read_jsonl(artifacts.get("agent_messages"))
    task_board = _as_dict(result.get("task_board")) or _read_json_dict(artifacts.get("task_board"))
    router_decisions = _as_list(result.get("router_decisions")) or _read_jsonl(artifacts.get("router_decisions"))
    budget_trace = _as_list(result.get("budget_trace")) or _read_jsonl(artifacts.get("budget_trace"))

    sections_coverage = required_sections_coverage(report_text, case.required_sections)
    artifact_pass = artifact_generation_pass(artifacts)
    verification_ok = verification_pass(verification)
    claim_count = count_claims(claims, report_text)
    evidence_count = count_evidence(evidence)
    citation_count = count_citations(citations, report_text)
    gap_count = gap_detection_count(verification)
    gap_rate = gap_resolution_rate(rework_trace, verification_passed=verification_ok)
    msg_count = message_count(agent_messages)
    blocked_count = task_blocked_count(task_board)
    task_rate = task_resolution_rate(task_board)
    total_latency = _float_or_default(result.get("total_latency_sec"), _float_or_default(run_summary.get("total_duration_sec"), 0.0))
    task_done = task_completion_rate(
        artifact_generation=artifact_pass,
        required_sections=sections_coverage,
        verification=verification_ok,
    )

    # Phase 3 DynamicRouter process metrics
    _phase3 = _compute_phase3_metrics(router_decisions, budget_trace, run_summary)

    unsupported = _unsupported_metric_placeholders()
    return {
        "case_id": case.case_id,
        "symbol": case.symbol,
        "market": case.market,
        "period": case.period,
        "report_type": case.report_type,
        "difficulty": case.difficulty,
        "task_completion_rate": task_done,
        "required_sections_coverage": sections_coverage,
        "artifact_generation_pass": artifact_pass,
        "verification_pass": verification_ok,
        "claim_count": claim_count,
        "evidence_count": evidence_count,
        "citation_count": citation_count,
        "gap_detection_count": gap_count,
        "gap_resolution_rate": gap_rate,
        "gap_resolution_rate_note": "粗略指标：基于 rework_trace.resolved 统计；未运行返工或无 gap 时为 0.0。",
        "message_count": msg_count,
        "task_blocked_count": blocked_count,
        "task_resolution_rate": task_rate,
        "total_latency_sec": round(total_latency, 4),
        "rework_mode": _phase3["rework_mode"],
        "router_decision_count": _phase3["router_decision_count"],
        "dynamic_dispatch_count": _phase3["dynamic_dispatch_count"],
        "fallback_decision_count": _phase3["fallback_decision_count"],
        "budget_exceeded_count": _phase3["budget_exceeded_count"],
        "router_stop_reason": _phase3["router_stop_reason"],
        "router_stop_reason_distribution": _phase3["router_stop_reason_distribution"],
        "repeated_dispatch_count": _phase3["repeated_dispatch_count"],
        "unsupported_gap_fallback_count": _phase3["unsupported_gap_fallback_count"],
        # Phase 4 adjudicator metrics
        "conflict_resolution_count": _phase3["conflict_resolution_count"],
        "adjudication_decision_distribution": _phase3["adjudication_decision_distribution"],
        **unsupported,
    }


def task_completion_rate(artifact_generation: bool, required_sections: float, verification: bool) -> float:
    return 1.0 if artifact_generation and required_sections >= 1.0 and verification else 0.0


def required_sections_coverage(report_text: str, required_sections: Iterable[str]) -> float:
    sections = [section.strip() for section in required_sections if section and section.strip()]
    if not sections:
        return 1.0
    normalized_text = _normalize_section_text(report_text)
    covered = sum(1 for section in sections if _section_present(normalized_text, section))
    return round(covered / float(len(sections)), 4)


def artifact_generation_pass(artifacts: Mapping[str, Path]) -> bool:
    report_md = artifacts.get("report_md")
    report_json = artifacts.get("report_json")
    verification_report = artifacts.get("verification_report")
    candidates = [report_md, report_json, verification_report]
    return all(path is not None and path.exists() and path.stat().st_size > 0 for path in candidates)


def verification_pass(verification: Mapping[str, Any]) -> bool:
    if not verification:
        return False
    if "passed" in verification:
        return bool(verification.get("passed"))
    if "verification_passed" in verification:
        return bool(verification.get("verification_passed"))
    errors = verification.get("errors")
    if isinstance(errors, list):
        return len(errors) == 0
    return False


def count_claims(claims: List[Any], report_text: str = "") -> int:
    if claims:
        return len(claims)
    return len([line for line in report_text.splitlines() if _looks_like_claim(line)])


def count_evidence(evidence: List[Any]) -> int:
    return len(evidence)


def count_citations(citations: List[Any], report_text: str = "") -> int:
    if citations:
        return len(citations)
    return len(CITATION_PATTERN.findall(report_text or ""))


def gap_detection_count(verification: Mapping[str, Any]) -> int:
    gaps = verification.get("gaps", []) if isinstance(verification, Mapping) else []
    if isinstance(gaps, list):
        return len(gaps)
    legacy = verification.get("evidence_gaps", []) if isinstance(verification, Mapping) else []
    return len(legacy) if isinstance(legacy, list) else 0


def gap_resolution_rate(rework_trace: List[Any], verification_passed: bool = False) -> float:
    rows = [row for row in rework_trace if isinstance(row, Mapping)]
    if not rows:
        # No rework was needed: either verifier passed on first try (all gaps resolved)
        # or the pipeline never ran rework (gaps unresolved). Distinguish by verification result.
        return 1.0 if verification_passed else 0.0
    resolved = sum(1 for row in rows if bool(row.get("resolved")))
    return round(resolved / float(len(rows)), 4)


def message_count(agent_messages: List[Any]) -> int:
    return len([item for item in agent_messages if isinstance(item, Mapping)])


def task_blocked_count(task_board: Mapping[str, Any]) -> int:
    summary = task_board.get("summary", {}) if isinstance(task_board, Mapping) else {}
    if isinstance(summary, Mapping):
        return int(_float_or_default(summary.get("blocked_count"), 0.0))
    tasks = task_board.get("tasks", []) if isinstance(task_board, Mapping) else []
    return sum(1 for task in tasks if isinstance(task, Mapping) and task.get("status") == "blocked")


def task_resolution_rate(task_board: Mapping[str, Any]) -> float:
    summary = task_board.get("summary", {}) if isinstance(task_board, Mapping) else {}
    if isinstance(summary, Mapping) and "resolution_rate" in summary:
        return round(_float_or_default(summary.get("resolution_rate"), 0.0), 4)
    tasks = [task for task in task_board.get("tasks", []) if isinstance(task, Mapping)] if isinstance(task_board, Mapping) else []
    if not tasks:
        return 0.0
    resolved = sum(1 for task in tasks if task.get("status") == "resolved")
    return round(resolved / float(len(tasks)), 4)


def aggregate_metrics(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    def _empty() -> Dict[str, Any]:
        return {
            "case_count": 0,
            "task_completion_rate": 0.0,
            "required_sections_coverage": 0.0,
            "artifact_generation_pass_rate": 0.0,
            "verification_pass_rate": 0.0,
            "claim_count_mean": 0.0,
            "evidence_count_mean": 0.0,
            "citation_count_mean": 0.0,
            "gap_detection_count_mean": 0.0,
            "gap_resolution_rate_mean": 0.0,
            "message_count_mean": 0.0,
            "task_blocked_count_mean": 0.0,
            "task_resolution_rate_mean": 0.0,
            "total_latency_sec_sum": 0.0,
            "total_latency_sec_mean": 0.0,
            "router_decision_count_sum": 0,
            "dynamic_dispatch_count_sum": 0,
            "fallback_decision_count_sum": 0,
            "budget_exceeded_count_sum": 0,
            "repeated_dispatch_count_sum": 0,
            "unsupported_gap_fallback_count_sum": 0,
            "router_stop_reasons": {},
            "conflict_resolution_count_sum": 0,
            "adjudication_decision_distribution": {},
        }
    if not rows:
        return _empty()

    # Collect all stop reasons across cases
    all_stop_reasons: Dict[str, int] = {}
    for row in rows:
        reasons = row.get("router_stop_reason_distribution", {})
        if isinstance(reasons, dict):
            for k, v in reasons.items():
                all_stop_reasons[k] = all_stop_reasons.get(k, 0) + v

    return {
        "case_count": len(rows),
        "task_completion_rate": _mean(row.get("task_completion_rate", 0.0) for row in rows),
        "required_sections_coverage": _mean(row.get("required_sections_coverage", 0.0) for row in rows),
        "artifact_generation_pass_rate": _mean(1.0 if row.get("artifact_generation_pass") else 0.0 for row in rows),
        "verification_pass_rate": _mean(1.0 if row.get("verification_pass") else 0.0 for row in rows),
        "claim_count_mean": _mean(row.get("claim_count", 0.0) for row in rows),
        "evidence_count_mean": _mean(row.get("evidence_count", 0.0) for row in rows),
        "citation_count_mean": _mean(row.get("citation_count", 0.0) for row in rows),
        "gap_detection_count_mean": _mean(row.get("gap_detection_count", 0.0) for row in rows),
        "gap_resolution_rate_mean": _mean(row.get("gap_resolution_rate", 0.0) for row in rows),
        "message_count_mean": _mean(row.get("message_count", 0.0) for row in rows),
        "task_blocked_count_mean": _mean(row.get("task_blocked_count", 0.0) for row in rows),
        "task_resolution_rate_mean": _mean(row.get("task_resolution_rate", 0.0) for row in rows),
        "total_latency_sec_sum": round(sum(_float_or_default(row.get("total_latency_sec"), 0.0) for row in rows), 4),
        "total_latency_sec_mean": _mean(row.get("total_latency_sec", 0.0) for row in rows),
        "router_decision_count_sum": sum(int_or_zero(row.get("router_decision_count")) for row in rows),
        "dynamic_dispatch_count_sum": sum(int_or_zero(row.get("dynamic_dispatch_count")) for row in rows),
        "fallback_decision_count_sum": sum(int_or_zero(row.get("fallback_decision_count")) for row in rows),
        "budget_exceeded_count_sum": sum(int_or_zero(row.get("budget_exceeded_count")) for row in rows),
        "repeated_dispatch_count_sum": sum(int_or_zero(row.get("repeated_dispatch_count")) for row in rows),
        "unsupported_gap_fallback_count_sum": sum(int_or_zero(row.get("unsupported_gap_fallback_count")) for row in rows),
        "router_stop_reasons": all_stop_reasons,
        "conflict_resolution_count_sum": sum(int_or_zero(row.get("conflict_resolution_count")) for row in rows),
        "adjudication_decision_distribution": _merge_adj_distributions(rows),
    }


def citation_support_rate(*_: Any, **__: Any) -> None:
    raise NotImplementedError("TODO Phase 1+: citation_support_rate requires claim-citation alignment judging.")


def numeric_audit_pass_rate(*_: Any, **__: Any) -> None:
    raise NotImplementedError("TODO Phase 1+: numeric_audit_pass_rate requires numeric fact extraction/audit integration.")


def valuation_sanity_pass_rate(*_: Any, **__: Any) -> None:
    raise NotImplementedError("TODO Phase 1+: valuation_sanity_pass_rate requires valuation-specific audit rules.")


def _unsupported_metric_placeholders() -> Dict[str, Any]:
    return {
        "citation_support_rate": None,
        "numeric_audit_pass_rate": None,
        "valuation_sanity_pass_rate": None,
        "unsupported_metric_todos": [
            "citation_support_rate: TODO claim-citation support judge",
            "numeric_audit_pass_rate: TODO numeric extraction and tolerance rules",
            "valuation_sanity_pass_rate: TODO valuation methodology sanity checks",
        ],
    }


def _compute_phase3_metrics(
    router_decisions: List[Any],
    budget_trace: List[Any],
    run_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute Phase 3 DynamicRouter process metrics from artifacts and run_summary."""

    # Fallback to run_summary values when artifacts are empty
    rework_mode = run_summary.get("rework_mode", "unknown")
    total_decisions = run_summary.get("router_decision_count") if router_decisions is None else len(router_decisions)
    dispatch_count = run_summary.get("dynamic_dispatch_count")
    fallback_count = run_summary.get("fallback_decision_count")
    budget_exceeded = run_summary.get("budget_exceeded_count")
    stop_reason = run_summary.get("router_stop_reason", "")

    # Compute from router_decisions if available
    valid_decisions = [d for d in router_decisions if isinstance(d, dict)]
    if valid_decisions:
        total_decisions = len(valid_decisions)
        dispatch_count = sum(1 for d in valid_decisions if d.get("selected_action") == "execute")
        fallback_count = sum(1 for d in valid_decisions if d.get("fallback_used"))
        unsupported_count = sum(1 for d in valid_decisions if d.get("unsupported_gap_type"))
    else:
        unsupported_count = 0

    # Stop reason distribution from budget_trace
    stop_reasons: Dict[str, int] = {}
    valid_trace = [t for t in budget_trace if isinstance(t, dict)]
    if valid_trace:
        for entry in valid_trace:
            sr = str(entry.get("stop_reason", ""))
            if sr:
                stop_reasons[sr] = stop_reasons.get(sr, 0) + 1
        if not budget_exceeded:
            budget_exceeded = sum(1 for t in valid_trace if not t.get("can_continue", True))

        # repeated_dispatch_count: max(per_gap_dispatch_count) entries >= max_dispatches_per_gap
        repeated = 0
        for entry in valid_trace:
            per_gap = entry.get("per_gap_dispatch_count", {})
            max_per_gap = entry.get("max_dispatches_per_gap", 2)
            if isinstance(per_gap, dict):
                repeated = max(repeated, sum(1 for v in per_gap.values() if isinstance(v, (int, float)) and v >= max_per_gap))
    else:
        repeated = 0

    # Phase 4: adjudicator metrics from run_summary or adjudication_decisions artifact
    adj_decisions = run_summary.get("adjudication_decisions", [])
    valid_adj = [d for d in adj_decisions if isinstance(d, dict)] if isinstance(adj_decisions, list) else []
    if valid_adj:
        conflict_resolution_count = sum(1 for d in valid_adj if d.get("decision") not in ("uncertain", ""))
        adj_dist = {}
        for d in valid_adj:
            verdict = str(d.get("decision", "unknown") or "unknown")
            adj_dist[verdict] = adj_dist.get(verdict, 0) + 1
    elif isinstance(run_summary.get("conflict_resolution_count"), int):
        conflict_resolution_count = int(run_summary.get("conflict_resolution_count", 0))
        adj_dist = dict(run_summary.get("adjudication_decision_distribution", {}))
    else:
        conflict_resolution_count = 0
        adj_dist = {}

    return {
        "rework_mode": rework_mode,
        "router_decision_count": total_decisions or 0,
        "dynamic_dispatch_count": dispatch_count or 0,
        "fallback_decision_count": fallback_count or 0,
        "budget_exceeded_count": budget_exceeded or 0,
        "router_stop_reason": stop_reason or "",
        "router_stop_reason_distribution": stop_reasons,
        "repeated_dispatch_count": repeated,
        "unsupported_gap_fallback_count": unsupported_count,
        "conflict_resolution_count": conflict_resolution_count,
        "adjudication_decision_distribution": adj_dist,
    }


def _artifact_paths(value: Any) -> Dict[str, Path]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): Path(str(path)) for key, path in value.items() if path}


def _report_text(result: Mapping[str, Any], artifacts: Mapping[str, Path]) -> str:
    markdown = result.get("markdown")
    if isinstance(markdown, str) and markdown:
        return markdown
    report_md = artifacts.get("report_md")
    if report_md and report_md.exists():
        return report_md.read_text(encoding="utf-8")
    return ""


def _normalize_section_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[#*_`：:，,。.!?？\-\s]+", "", lowered)
    return lowered


def _section_present(normalized_text: str, section: str) -> bool:
    normalized_section = _normalize_section_text(section)
    aliases = {
        "business_overview": ["businessoverview", "业务概览", "公司概览"],
        "financials": ["financials", "financialanalysis", "financialstatements", "财务分析", "三表摘要"],
        "valuation": ["valuation", "估值", "估值观察"],
        "risks": ["risks", "riskassessment", "风险", "风险评估"],
        "peer_comparison": ["peercomparison", "同业比较", "可比公司", "同行对比"],
        "investment_conclusion": ["investmentconclusion", "conclusion", "投资结论"],
        "reference_sources": ["referencesources", "参考来源", "引用来源"],
    }
    # Look up by original section name (before normalization) to preserve underscore-based keys
    raw_aliases = aliases.get(section.strip(), [])
    candidates = [normalized_section] + [_normalize_section_text(a) for a in raw_aliases]
    return any(candidate and candidate in normalized_text for candidate in candidates)


def _looks_like_claim(line: str) -> bool:
    text = line.strip()
    if len(text) < 20 or text.startswith("#"):
        return False
    return any(token in text for token in ["。", ".", "%", "同比", "revenue", "margin", "risk", "估值", "风险"])


def _read_json_list(path: Path | None) -> List[Any]:
    if not path or not path.exists():
        return []
    data = _read_json(path)
    return data if isinstance(data, list) else []


def _read_json_dict(path: Path | None) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path | None) -> List[Any]:
    if not path or not path.exists():
        return []
    rows: List[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json_loads(line))
    return rows


def _read_json(path: Path) -> Any:
    return json_loads(path.read_text(encoding="utf-8"))


def json_loads(text: str) -> Any:
    import json

    return json.loads(text) if text.strip() else None


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _merge_adj_distributions(rows: List[Mapping[str, Any]]) -> Dict[str, int]:
    merged: Dict[str, int] = {}
    for row in rows:
        dist = row.get("adjudication_decision_distribution", {})
        if isinstance(dist, dict):
            for k, v in dist.items():
                merged[k] = merged.get(k, 0) + int_or_zero(v)
    return merged


def int_or_zero(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: Iterable[Any]) -> float:
    nums = [_float_or_default(value, 0.0) for value in values]
    return round(sum(nums) / float(len(nums)), 4) if nums else 0.0
