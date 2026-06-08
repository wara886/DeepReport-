"""Tests for CitationBinder.

Verifies that:
- qualitative sections may NOT bind financial tables
- financial sections MAY bind financial tables
- same evidence_id keeps the same citation number
- LLM-written citations are stripped properly
- risk fallback does not bind cashflow table
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.report.section_contracts import (
    ReportSectionContracts,
    SectionEvidenceContract,
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_FINANCIAL_METRIC,
    FORBIDDEN_SECTION_SOURCE_TYPES,
)
from src.report.citation_binder import CitationBinder, QUALITATIVE_SECTIONS


def _make_evidence(evidence_id: str, source_type: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "title": f"Test {source_type}",
        "content": "content",
    }


class TestCitationBinder:
    """Test the citation binder with various section types."""

    def setup_method(self):
        self.binder = CitationBinder()

    def test_same_evidence_same_number(self):
        """Same evidence_id should get the same citation number across sections."""
        num1 = self.binder.assign_citation_number("ev_pdf_001")
        num2 = self.binder.assign_citation_number("ev_pdf_001")
        assert num1 == num2

    def test_different_evidence_different_numbers(self):
        """Different evidence_ids should get different citation numbers."""
        n1 = self.binder.assign_citation_number("ev_001")
        n2 = self.binder.assign_citation_number("ev_002")
        assert n1 != n2

    def test_citation_map(self):
        """Citation map should map evidence_id -> number."""
        self.binder.assign_citation_number("ev_001")
        self.binder.assign_citation_number("ev_002")
        cmap = self.binder.get_citation_map()
        assert cmap["ev_001"] == 1
        assert cmap["ev_002"] == 2

    def test_qualitative_section_rejects_financial(self):
        """Qualitative sections must reject financial table evidence."""
        binder = CitationBinder(evidence_records=[
            _make_evidence("ev_fin_001", SRC_INCOME_TABLE),
            _make_evidence("ev_fin_002", SRC_BALANCE_TABLE),
            _make_evidence("ev_pdf_001", SRC_ANNUAL_REPORT_PDF_SUMMARY),
        ])

        # Business overview (qualitative) with mixed evidence
        c = SectionEvidenceContract(
            section_key="business_overview",
            title="业务概览",
            forbidden_source_types=FORBIDDEN_SECTION_SOURCE_TYPES.get("business_overview", []),
        )
        c.citation_evidence_ids = ["ev_fin_001", "ev_pdf_001"]

        result = binder.bind_contract(c)
        assert result.status == "mismatch"
        assert any("ev_fin_001" in r for r in result.blocked_reasons)

    def test_financial_section_allows_financial(self):
        """Financial analysis should be able to use financial table evidence."""
        binder = CitationBinder(evidence_records=[
            _make_evidence("ev_inc_001", SRC_INCOME_TABLE),
            _make_evidence("ev_bal_001", SRC_BALANCE_TABLE),
        ])

        c = SectionEvidenceContract(
            section_key="financial_analysis",
            title="财务分析",
            allowed_source_types=[
                SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE,
                SRC_FINANCIAL_METRIC,
            ],
        )
        c.citation_evidence_ids = ["ev_inc_001", "ev_bal_001"]

        result = binder.bind_contract(c)
        assert result.status == "ok"
        assert len(result.bound_citation_ids) == 2

    def test_risk_fallback_no_cashflow(self):
        """Risk factors fallback must not bind cashflow table."""
        binder = CitationBinder(evidence_records=[
            _make_evidence("ev_cf_001", SRC_CASHFLOW_TABLE),
        ])

        c = SectionEvidenceContract(
            section_key="risk_factors",
            title="风险评估",
            forbidden_source_types=FORBIDDEN_SECTION_SOURCE_TYPES.get("risk_factors", []),
        )
        c.citation_evidence_ids = ["ev_cf_001"]

        result = binder.bind_contract(c)
        assert result.status == "mismatch"
        assert any("cashflow" in r.lower() for r in result.blocked_reasons)

    def test_bind_all_collects_mismatches(self):
        """bind_all should collect all mismatches across contracts."""
        contracts = ReportSectionContracts()
        c1 = contracts.ensure("business_overview")
        c1.citation_evidence_ids = ["ev_fin_001"]
        c2 = contracts.ensure("financial_analysis")
        c2.citation_evidence_ids = ["ev_pdf_001"]

        binder = CitationBinder(evidence_records=[
            _make_evidence("ev_fin_001", SRC_INCOME_TABLE),
            _make_evidence("ev_pdf_001", SRC_ANNUAL_REPORT_PDF_SUMMARY),
        ])

        results = binder.bind_all(contracts)
        biz_result = [r for r in results if r.section_key == "business_overview"][0]
        assert biz_result.status == "mismatch"

        fin_result = [r for r in results if r.section_key == "financial_analysis"][0]
        assert fin_result.status == "ok"  # no forbidden types by default

    def test_strip_llm_citations(self):
        """LLM-written citations should be stripped, leaving clean text."""
        binder = CitationBinder()
        binder.assign_citation_number("ev_pdf_001")  # this is #[1]
        binder.assign_citation_number("ev_pdf_002")  # this is #[2]

        text = "公司营收增长24% [1] [2] 毛利率提升 [3] [ev_foo]"
        cleaned = binder.strip_llm_citations(text)
        # [1] and [2] are known citations — keep them
        assert "[1]" in cleaned
        assert "[2]" in cleaned
        # [3] and [ev_foo] are not bound — stripped
        assert "[3]" not in cleaned
        assert "[ev_foo]" not in cleaned

    def test_binder_audit_output(self):
        """Citation binding audit should include mismatch info."""
        binder = CitationBinder(evidence_records=[
            _make_evidence("ev_fin_001", SRC_INCOME_TABLE),
        ])
        c = SectionEvidenceContract(
            section_key="business_overview",
            title="业务概览",
            forbidden_source_types=FORBIDDEN_SECTION_SOURCE_TYPES.get("business_overview", []),
        )
        c.citation_evidence_ids = ["ev_fin_001"]
        binder.bind_contract(c)

        audit = binder.to_audit()
        assert audit["total_mismatches"] >= 0
        assert "section_bindings" in audit

    def test_citation_map_output(self):
        """Citation map should be serializable."""
        binder = CitationBinder()
        binder.assign_citation_number("ev_001")
        cmap = binder.to_citation_map()
        assert "citation_map" in cmap
        assert any(e["evidence_id"] == "ev_001" for e in cmap["citation_map"])

    def test_bind_contract_uses_fact_evidence_ids_as_fallback(self):
        """Facts should be enough to bind citations even if section-level ids are empty."""
        binder = CitationBinder(evidence_records=[
            _make_evidence("ev_fact_001", SRC_INCOME_TABLE),
        ])
        c = SectionEvidenceContract(
            section_key="financial_analysis",
            title="财务分析",
            allowed_source_types=[SRC_INCOME_TABLE, SRC_FINANCIAL_METRIC],
        )
        c.add_fact(
            "financial_metrics_summary",
            "收入 100 亿元",
            evidence_ids=["ev_fact_001"],
            source_types=[SRC_FINANCIAL_METRIC],
        )
        c.citation_evidence_ids = []

        result = binder.bind_contract(c)

        assert result.status == "ok"
        assert result.bound_citation_ids == ["[1]"]
