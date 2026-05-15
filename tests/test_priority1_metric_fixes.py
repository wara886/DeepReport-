"""Tests for chart lineage edge cases used by report quality gates."""

from __future__ import annotations

from typing import Any, Dict, List

from src.schemas.multimodal import audit_chart_lineage


def _chart(chart_id: str, category: str, input_claim_ids: List[str], source_evidence_ids: List[str]) -> Dict[str, Any]:
    return {
        "chart_id": chart_id,
        "chart_type": "bar",
        "chart_category": category,
        "source_fields": "claims.confidence",
        "input_claim_ids": input_claim_ids,
        "source_evidence_ids": source_evidence_ids,
    }


def test_audit_chart_passes_without_source_evidence_ids():
    charts = [_chart("claim_confidence_bar", "audit", ["cl_risk_0001"], [])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[])
    assert result["passed"] is True
    assert result["results"][0]["passed"] is True
    assert "missing_source_evidence_ids" not in result["results"][0]["errors"]


def test_report_chart_passes_when_no_evidence_records_exist():
    charts = [_chart("peer_comparison_table", "report", ["cl_peer_0001"], [])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[])
    assert result["passed"] is True
    assert result["results"][0]["passed"] is True


def test_report_chart_fails_when_evidence_exists_but_not_linked():
    charts = [_chart("financial_bar", "report", ["cl_fin_0001"], [])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[{"evidence_id": "ev1"}])
    assert result["passed"] is False
    assert "missing_source_evidence_ids" in result["results"][0]["errors"]


def test_claim_text_report_chart_passes_without_source_evidence_ids():
    chart = _chart("peer_comparison_table", "report", ["cl_peer_0001"], [])
    chart["source_fields"] = "claims.claim_text"
    result = audit_chart_lineage(charts=[chart], tables=[], evidence_records=[{"evidence_id": "ev1"}])
    assert result["passed"] is True
    assert "missing_source_evidence_ids" not in result["results"][0]["errors"]


def test_report_chart_passes_when_evidence_correctly_linked():
    charts = [_chart("financial_bar", "report", ["cl_fin_0001"], ["ev1"])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[{"evidence_id": "ev1"}])
    assert result["passed"] is True
    assert result["results"][0]["passed"] is True


def test_mixed_charts_audit_passes_report_fails():
    charts = [
        _chart("claim_confidence_bar", "audit", ["cl_risk_0001"], []),
        _chart("peer_comparison_table", "report", ["cl_peer_0001"], []),
    ]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[{"evidence_id": "ev1"}])
    assert result["passed"] is False
    audit_r = next(r for r in result["results"] if r["chart_id"] == "claim_confidence_bar")
    report_r = next(r for r in result["results"] if r["chart_id"] == "peer_comparison_table")
    assert audit_r["passed"] is True
    assert report_r["passed"] is False


def test_both_charts_pass_when_no_evidence_records():
    charts = [
        _chart("claim_confidence_bar", "audit", ["cl_risk_0001"], []),
        _chart("peer_comparison_table", "report", ["cl_peer_0001"], []),
    ]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[])
    assert result["passed"] is True
    for row in result["results"]:
        assert row["passed"] is True
