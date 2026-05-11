"""Company report scorecard for contest-style evaluation."""

from __future__ import annotations

from typing import Any, Dict, List

from src.evaluation.valuation_audit import audit_valuation_model


def build_company_report_scorecard(
    evidence_records: List[Dict[str, Any]],
    financial_metrics: Dict[str, Any],
    multimodal_consistency: Dict[str, Any],
    valuation: Dict[str, Any],
    verification_report: Dict[str, Any],
    gap_resolution_trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate core company-report quality signals into normalized scores."""

    scores = {
        "authority_score": _authority_score(evidence_records=evidence_records, verification_report=verification_report),
        "numeric_lineage_score": _numeric_lineage_score(financial_metrics),
        "multimodal_consistency_score": _multimodal_consistency_score(multimodal_consistency),
        "valuation_reproducibility_score": _valuation_reproducibility_score(valuation, verification_report),
        "gap_resolution_score": _gap_resolution_score(gap_resolution_trace),
    }
    weights = {
        "authority_score": 0.25,
        "numeric_lineage_score": 0.25,
        "multimodal_consistency_score": 0.18,
        "valuation_reproducibility_score": 0.22,
        "gap_resolution_score": 0.10,
    }
    overall = sum(scores[key] * weight for key, weight in weights.items())
    return {
        "overall_score": round(overall, 4),
        "scores": {key: round(value, 4) for key, value in scores.items()},
        "weights": weights,
        "passed": overall >= 0.75 and bool(verification_report.get("passed", False)),
        "diagnostics": {
            "evidence_count": len(evidence_records),
            "metric_count": int(financial_metrics.get("metric_count", 0) or 0) if isinstance(financial_metrics, dict) else 0,
            "verification_passed": bool(verification_report.get("passed", False)),
            "open_gap_count": _open_gap_count(gap_resolution_trace),
        },
    }


def _authority_score(evidence_records: List[Dict[str, Any]], verification_report: Dict[str, Any]) -> float:
    if verification_report.get("errors"):
        primary_errors = [str(item) for item in verification_report.get("errors", []) if "primary evidence" in str(item).lower()]
        if primary_errors:
            return 0.0
    if not evidence_records:
        return 0.0
    primary = 0
    known = 0
    for record in evidence_records:
        if not isinstance(record, dict):
            continue
        level = str(record.get("authority_level") or record.get("metadata", {}).get("authority_level") or "").lower()
        if level:
            known += 1
        if level == "primary":
            primary += 1
    if known:
        return primary / known
    high_trust = sum(1 for record in evidence_records if str(record.get("trust_level", "")).lower() == "high")
    return high_trust / len(evidence_records)


def _numeric_lineage_score(financial_metrics: Dict[str, Any]) -> float:
    if not isinstance(financial_metrics, dict):
        return 0.0
    coverage = financial_metrics.get("coverage") if isinstance(financial_metrics.get("coverage"), dict) else {}
    required = coverage.get("required_metrics", []) if isinstance(coverage.get("required_metrics"), list) else []
    present = set(coverage.get("present_metrics", []) if isinstance(coverage.get("present_metrics"), list) else [])
    if not required:
        return 0.0
    lineage_rows = [
        row
        for row in financial_metrics.get("metrics", [])
        if isinstance(row, dict) and row.get("source_table_id") and row.get("source_evidence_id")
    ]
    coverage_score = len([item for item in required if item in present]) / len(required)
    lineage_score = len(lineage_rows) / max(int(financial_metrics.get("metric_count", 0) or 0), 1)
    return (coverage_score + lineage_score) / 2


def _multimodal_consistency_score(multimodal_consistency: Dict[str, Any]) -> float:
    if not isinstance(multimodal_consistency, dict):
        return 0.0
    if multimodal_consistency.get("passed", False):
        return 1.0
    chart_text = multimodal_consistency.get("chart_text_consistency", {})
    passed = float(chart_text.get("passed_chart_count", 0) or 0)
    total = float(chart_text.get("chart_count", 0) or 0)
    return passed / total if total else 0.0


def _valuation_reproducibility_score(valuation: Dict[str, Any], verification_report: Dict[str, Any]) -> float:
    audit = verification_report.get("valuation_audit") if isinstance(verification_report.get("valuation_audit"), dict) else None
    if audit is None:
        audit = audit_valuation_model(valuation)
    if audit.get("passed", False):
        return 1.0
    error_count = len(audit.get("errors", [])) if isinstance(audit.get("errors"), list) else 1
    return max(0.0, 1.0 - error_count * 0.25)


def _gap_resolution_score(gap_resolution_trace: List[Dict[str, Any]]) -> float:
    if not gap_resolution_trace:
        return 1.0
    closed = 0
    total = 0
    for row in gap_resolution_trace:
        if not isinstance(row, dict):
            continue
        total += 1
        if str(row.get("status")) in {"resolved_or_downgraded", "not_blocking"}:
            closed += 1
    return closed / total if total else 1.0


def _open_gap_count(gap_resolution_trace: List[Dict[str, Any]]) -> int:
    return sum(1 for row in gap_resolution_trace if isinstance(row, dict) and str(row.get("status")) in {"queued", "still_open"})
