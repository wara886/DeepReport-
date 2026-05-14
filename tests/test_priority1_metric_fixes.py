"""Tests for Priority 1 metric fixes:
1. Chart lineage: audit-category charts should not require source_evidence_ids
2. Evidence records: BrowserAgent returning empty should promote evidence_candidates
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.schemas.multimodal import audit_chart_lineage


# ─── Chart lineage fix tests ───────────────────────────────────────────────

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
    """Audit charts visualize metadata (confidence, ids), not financial data — no evidence required."""
    charts = [_chart("claim_confidence_bar", "audit", ["cl_risk_0001"], [])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[])
    assert result["passed"] is True
    assert result["results"][0]["passed"] is True
    assert "missing_source_evidence_ids" not in result["results"][0]["errors"]


def test_report_chart_passes_when_no_evidence_records_exist():
    """When evidence_records is empty, claims cannot have evidence_ids — not a lineage error."""
    charts = [_chart("peer_comparison_table", "report", ["cl_peer_0001"], [])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[])
    assert result["passed"] is True
    assert result["results"][0]["passed"] is True


def test_report_chart_fails_when_evidence_exists_but_not_linked():
    """When evidence_records is non-empty, a report chart must link to them."""
    charts = [_chart("financial_bar", "report", ["cl_fin_0001"], [])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[{"evidence_id": "ev1"}])
    assert result["passed"] is False
    assert "missing_source_evidence_ids" in result["results"][0]["errors"]


def test_report_chart_passes_when_evidence_correctly_linked():
    charts = [_chart("financial_bar", "report", ["cl_fin_0001"], ["ev1"])]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[{"evidence_id": "ev1"}])
    assert result["passed"] is True
    assert result["results"][0]["passed"] is True


def test_mixed_charts_audit_passes_report_fails():
    """Audit chart passes, report chart without evidence link fails."""
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
    """Both audit and report charts pass when evidence_records is empty."""
    charts = [
        _chart("claim_confidence_bar", "audit", ["cl_risk_0001"], []),
        _chart("peer_comparison_table", "report", ["cl_peer_0001"], []),
    ]
    result = audit_chart_lineage(charts=charts, tables=[], evidence_records=[])
    assert result["passed"] is True
    for r in result["results"]:
        assert r["passed"] is True, f"{r['chart_id']} should pass when no evidence records"


# ─── Evidence candidates promotion tests ───────────────────────────────────

from src.agents.multi_agent_orchestrator import _promote_candidates_to_records


def test_promote_candidates_to_records_basic():
    candidates = [
        {"result_id": "ev1", "title": "NVDA Q4 Revenue", "snippet": "Revenue was $22B", "url": "https://example.com/nvda", "source_type": "sec_filing", "score": 0.9},
        {"result_id": "ev2", "title": "NVDA Guidance", "snippet": "Q1 guidance raised", "url": "https://example.com/nvda2", "source_type": "earnings_call", "score": 0.8},
    ]
    records = _promote_candidates_to_records(candidates)
    assert len(records) == 2
    assert records[0]["evidence_id"] == "ev1"
    assert records[0]["content"] == "Revenue was $22B"
    assert records[0]["source_url"] == "https://example.com/nvda"
    assert records[0]["source_type"] == "sec_filing"
    assert records[1]["evidence_id"] == "ev2"


def test_promote_candidates_skips_missing_id():
    candidates = [
        {"title": "No ID", "snippet": "some text"},  # no result_id/evidence_id
        {"result_id": "ev1", "snippet": "valid"},
    ]
    records = _promote_candidates_to_records(candidates)
    assert len(records) == 1
    assert records[0]["evidence_id"] == "ev1"


def test_promote_candidates_empty_input():
    assert _promote_candidates_to_records([]) == []


def test_promote_candidates_uses_evidence_id_field():
    candidates = [{"evidence_id": "ev_direct", "snippet": "direct evidence_id field"}]
    records = _promote_candidates_to_records(candidates)
    assert len(records) == 1
    assert records[0]["evidence_id"] == "ev_direct"


def test_promote_candidates_uses_sample_id_fallback():
    candidates = [{"sample_id": "smp_001", "snippet": "sample id fallback"}]
    records = _promote_candidates_to_records(candidates)
    assert len(records) == 1
    assert records[0]["evidence_id"] == "smp_001"


def test_promote_candidates_default_source_type():
    candidates = [{"result_id": "ev1", "snippet": "no source_type"}]
    records = _promote_candidates_to_records(candidates)
    assert records[0]["source_type"] == "search_candidate"


def test_promote_candidates_default_score():
    candidates = [{"result_id": "ev1", "snippet": "no score"}]
    records = _promote_candidates_to_records(candidates)
    assert records[0]["score"] == 1.0


def test_promote_candidates_skips_non_dict():
    candidates = [{"result_id": "ev1", "snippet": "valid"}, "not_a_dict", None, 42]
    records = _promote_candidates_to_records(candidates)
    assert len(records) == 1
    assert records[0]["evidence_id"] == "ev1"
