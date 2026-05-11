"""Report-level multimodal consistency checks."""

from __future__ import annotations

from typing import Any, Dict, List

from src.report.chart_consistency import audit_chart_consistency
from src.schemas.multimodal import audit_chart_lineage


def audit_multimodal_consistency(
    charts: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    markdown: str = "",
    require_files: bool = False,
) -> Dict[str, Any]:
    """Validate that report charts are traceable to text, tables, and evidence."""

    chart_text = audit_chart_consistency(
        charts=charts,
        claims=claims,
        evidence_records=evidence_records,
        markdown=markdown,
        require_files=require_files,
    )
    lineage = audit_chart_lineage(
        charts=charts,
        tables=tables,
        evidence_records=evidence_records,
    )
    table_gate = _audit_table_backed_financial_charts(charts=charts, tables=tables)
    passed = bool(chart_text.get("passed", False)) and bool(lineage.get("passed", False)) and table_gate["passed"]
    return {
        "passed": passed,
        "chart_count": len(charts),
        "chart_text_consistency": chart_text,
        "chart_lineage": lineage,
        "table_backed_financial_charts": table_gate,
    }


def _audit_table_backed_financial_charts(
    charts: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Require numeric claim charts to point at tables once tables exist."""

    available_table_ids = {str(item.get("table_id", "")) for item in tables if isinstance(item, dict)}
    details: List[Dict[str, Any]] = []
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        source_fields = chart.get("source_fields", [])
        source_field_text = " ".join(source_fields) if isinstance(source_fields, list) else str(source_fields)
        if "numeric_values" not in source_field_text:
            continue
        input_table_ids = [str(item) for item in chart.get("input_table_ids", []) if str(item).strip()]
        issues: List[str] = []
        if available_table_ids and not input_table_ids:
            issues.append("financial_chart_missing_input_table_ids")
        missing = [table_id for table_id in input_table_ids if table_id not in available_table_ids]
        if missing:
            issues.append("financial_chart_missing_tables:" + ",".join(missing))
        details.append(
            {
                "chart_id": str(chart.get("chart_id", "")),
                "passed": not issues,
                "issues": issues,
            }
        )
    return {
        "passed": all(item["passed"] for item in details),
        "checked_chart_count": len(details),
        "details": details,
    }
