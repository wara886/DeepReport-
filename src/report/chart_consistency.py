"""Lightweight chart-text consistency checks for generated reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def audit_chart_consistency(
    charts: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    markdown: str = "",
    require_files: bool = False,
) -> Dict[str, Any]:
    """Check whether chart artifacts are traceable to report inputs.

    This is a metadata audit, not OCR or visual recognition. It catches the
    common failure mode where a report has decorative or empty charts that are
    not tied to claims, evidence, or report text.
    """

    details: List[Dict[str, Any]] = []
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        issues = _chart_issues(
            chart=chart,
            claims=claims,
            evidence_records=evidence_records,
            markdown=markdown,
            require_files=require_files,
        )
        details.append(
            {
                "chart_id": str(chart.get("chart_id") or ""),
                "title": str(chart.get("title") or ""),
                "passed": not issues,
                "issues": issues,
            }
        )

    failed = [item for item in details if not item["passed"]]
    return {
        "chart_count": len(details),
        "passed_chart_count": len(details) - len(failed),
        "failed_chart_count": len(failed),
        "passed": len(failed) == 0,
        "details": details,
    }


def _chart_issues(
    chart: Dict[str, Any],
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    markdown: str,
    require_files: bool,
) -> List[str]:
    issues: List[str] = []
    chart_id = str(chart.get("chart_id") or "").strip()
    title = str(chart.get("title") or "").strip()
    source_fields = str(chart.get("source_fields") or "").strip()
    chart_js = chart.get("chart_js") if isinstance(chart.get("chart_js"), dict) else {}
    output_path = str(chart.get("output_path") or "").strip()

    if not chart_id:
        issues.append("missing_chart_id")
    if not title:
        issues.append("missing_title")
    if not source_fields:
        issues.append("missing_source_fields")
    if chart_js and not _has_chart_data(chart_js):
        issues.append("empty_chart_data")
    if output_path and require_files and not Path(output_path).exists():
        issues.append("missing_output_file")
    if title and markdown and title not in markdown:
        issues.append("title_not_referenced_in_report")
    if source_fields.startswith("claims.") and not _claims_support_chart(source_fields, claims):
        issues.append("no_supporting_claim_data")
    if source_fields.startswith("evidence_records.") and not _evidence_supports_chart(source_fields, evidence_records):
        issues.append("no_supporting_evidence_data")
    return issues


def _has_chart_data(chart_js: Dict[str, Any]) -> bool:
    labels = chart_js.get("labels", [])
    data = chart_js.get("data", [])
    return isinstance(labels, list) and isinstance(data, list) and bool(labels) and bool(data)


def _claims_support_chart(source_fields: str, claims: List[Dict[str, Any]]) -> bool:
    field = source_fields.removeprefix("claims.").strip()
    if not field:
        return bool(claims)
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        value = claim.get(field)
        if value not in (None, "", [], {}):
            return True
        if "." in field:
            first, rest = field.split(".", 1)
            nested = claim.get(first)
            if isinstance(nested, dict) and nested.get(rest) not in (None, "", [], {}):
                return True
            if isinstance(nested, dict) and nested:
                return True
    return False


def _evidence_supports_chart(source_fields: str, evidence_records: List[Dict[str, Any]]) -> bool:
    field = source_fields.removeprefix("evidence_records.").strip()
    if not field:
        return bool(evidence_records)
    return any(isinstance(item, dict) and item.get(field) not in (None, "", [], {}) for item in evidence_records)
