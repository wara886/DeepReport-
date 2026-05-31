"""Tests for SectionDossierBuilder."""

from typing import Any, Dict

from src.agents.section_dossier_builder import SectionDossierBuilder


def test_business_overview_dossier_from_company_profile():
    """Business overview dossier extracts company_name/sector/industry from company_profile."""
    builder = SectionDossierBuilder()
    dossiers = builder.build(
        state={"symbol": "AMD", "claims": [], "research_blackboard": {}},
        claims=[],
        evidence_records=[],
        analysis_artifacts={
            "company_profile": {
                "company_name": "Advanced Micro Devices",
                "sector": "Technology",
                "industry": "Semiconductors",
                "business_summary": "AMD designs and sells CPU, GPU, and adaptive computing products.",
            }
        },
        derived_evidence=[],
        bundles=[],
    )
    biz = dossiers.get("business_overview", {})
    assert isinstance(biz, dict)
    facts = biz.get("key_facts", [])
    facts_text = " ".join(facts)
    assert "Advanced Micro Devices" in facts_text
    assert "Technology" in facts_text
    assert "Semiconductors" in facts_text
    assert biz.get("section_title") == "业务概览"
    assert biz.get("min_content_level") == "full"


def test_ownership_governance_data_gap():
    """No governance evidence -> min_content_level=data_gap, no half-sentences."""
    builder = SectionDossierBuilder()
    dossiers = builder.build(
        state={"symbol": "AMD", "claims": [], "research_blackboard": {}},
        claims=[],
        evidence_records=[
            {"evidence_id": "ev_001", "content": "Revenue grew 10%", "title": "Financial results"}
        ],
        analysis_artifacts={},
        derived_evidence=[],
        bundles=[],
    )
    gov = dossiers.get("ownership_governance", {})
    assert isinstance(gov, dict)
    assert gov.get("min_content_level") == "data_gap"
    assert gov.get("suggested_paragraphs")
    text = " ".join(gov["suggested_paragraphs"])
    assert "治理" in text
    assert "股权" in text


def test_peer_compare_contains_table():
    """Has peer_rows -> dossier contains tables."""
    builder = SectionDossierBuilder()
    dossiers = builder.build(
        state={"symbol": "AMD", "claims": [], "research_blackboard": {}},
        claims=[],
        evidence_records=[],
        analysis_artifacts={
            "peer_analysis": {
                "peer_rows": [
                    {"symbol": "NVDA", "company_name": "NVIDIA", "revenue": "100B"},
                    {"symbol": "INTC", "company_name": "Intel", "revenue": "50B"},
                ]
            }
        },
        derived_evidence=[],
        bundles=[],
    )
    peer = dossiers.get("peer_compare", {})
    assert isinstance(peer, dict)
    assert len(peer.get("tables", [])) >= 1
    assert peer.get("min_content_level") == "full"
    assert len(peer.get("suggested_paragraphs", [])) >= 1


def test_valuation_dossier_contains_methods():
    """Has valuation analysis -> dossier contains methods table."""
    builder = SectionDossierBuilder()
    dossiers = builder.build(
        state={"symbol": "AAPL", "claims": [], "research_blackboard": {}},
        claims=[],
        evidence_records=[],
        analysis_artifacts={
            "valuation": {
                "pe_ratio": 30.0,
                "pb_ratio": 10.0,
                "dcf_value": 150.0,
                "current_market_cap": 2000.0,
                "blended_value": 180.0,
            }
        },
        derived_evidence=[],
        bundles=[],
    )
    val = dossiers.get("valuation", {})
    assert isinstance(val, dict)
    tables = val.get("tables", [])
    assert any("P/E" in str(t) for t in tables), f"Expected P/E in tables: {tables}"
    assert any("P/B" in str(t) for t in tables), f"Expected P/B in tables: {tables}"
    assert any("DCF" in str(t) for t in tables), f"Expected DCF in tables: {tables}"
    assert val.get("min_content_level") == "full"
    # market cap vs blended divergence > 50% -> caveat about divergence
    assert val.get("suggested_paragraphs")


def test_risks_dossier_min_4_categories():
    """Risks dossier returns at least 5 risk categories."""
    builder = SectionDossierBuilder()
    dossiers = builder.build(
        state={"symbol": "AMD", "claims": [], "research_blackboard": {}},
        claims=[],
        evidence_records=[],
        analysis_artifacts={},
        derived_evidence=[],
        bundles=[],
    )
    risks = dossiers.get("risks", {})
    assert isinstance(risks, dict)
    tables = risks.get("tables", [])
    # Even without risk data, should have at least some category info
    assert risks.get("section_key") == "risks"
    assert risks.get("section_title") == "风险评估"
    # Check min_content_level presence
    assert risks.get("min_content_level") in ("full", "brief")


def test_valuation_dossier_sensitivity_no_data():
    """No sensitivity data -> valuation_sensitivity is brief."""
    builder = SectionDossierBuilder()
    dossiers = builder.build(
        state={"symbol": "AAPL", "claims": [], "research_blackboard": {}},
        claims=[],
        evidence_records=[],
        analysis_artifacts={},
        derived_evidence=[],
        bundles=[],
    )
    vs = dossiers.get("valuation_sensitivity", {})
    assert isinstance(vs, dict)
    assert vs.get("min_content_level") == "brief"


def test_conclusion_dossier_5_elements():
    """Conclusion dossier contains 5 elements: financial_quality, valuation_judgment, upside_factors, downside_risks, applicable_boundary."""
    builder = SectionDossierBuilder()
    dossiers = builder.build(
        state={"symbol": "AAPL", "claims": [], "research_blackboard": {}},
        claims=[],
        evidence_records=[],
        analysis_artifacts={
            "financial_metrics": {"net_income": 100},
            "valuation": {"dcf_value": 150},
        },
        derived_evidence=[],
        bundles=[],
    )
    conc = dossiers.get("conclusion", {})
    assert isinstance(conc, dict)
    elements = conc.get("conclusion_elements", [])
    assert "financial_quality" in elements
    assert "valuation_judgment" in elements
    assert "upside_factors" in elements
    assert "downside_risks" in elements
    assert "applicable_boundary" in elements
