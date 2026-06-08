"""Tests for ReportSectionContracts and ContractBuilder.

Verifies that contracts enforce source-type routing, fact-level granularity,
and blocked-reason specificity.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.report.section_contracts import (
    ReportSectionContracts,
    SectionEvidenceContract,
    clean_pdf_boilerplate,
    text_contains_pdf_boilerplate,
    text_contains_fragments,
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_INCOME_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_FINANCIAL_METRIC,
)
from src.report.contract_builder import (
    build_report_section_contracts,
    _build_business_overview,
    _build_ownership_governance,
    _build_risk_factors,
    _build_strategy_business,
)
from src.report.citation_binder import CitationBinder


# ── helpers ─────────────────────────────────────────────────────────────


def _make_pdf_summary(section_type: str, text: str, eid: str = "ev_pdf_001") -> Dict[str, Any]:
    return {
        "section_type": section_type,
        "summary_zh": text,
        "evidence_id": eid,
        "usable_for_generation": True,
        "evidence_quality": "good",
    }


def _make_pdf_chunk(section_type: str, text: str, eid: str = "ev_chunk_001") -> Dict[str, Any]:
    return {
        "section_type": section_type,
        "summary_zh": text,
        "evidence_id": eid,
        "text": text,
        "usable_for_generation": True,
    }


def _make_evidence_record(source_type: str, eid: str = "ev_rec_001") -> Dict[str, Any]:
    return {
        "evidence_id": eid,
        "source_type": source_type,
        "title": f"Test {source_type}",
        "content": "test content",
    }


# ── Tests ───────────────────────────────────────────────────────────────


class TestSectionContractData:
    """Test the basic data structures."""

    def test_ensure_and_get(self):
        contracts = ReportSectionContracts()
        c = contracts.ensure("business_overview")
        assert c.section_key == "business_overview"
        assert c.title == "业务概览"
        assert c.status == "gap"
        assert c.forbidden_source_types  # should have forbidden types

    def test_status_lifecycle(self):
        contracts = ReportSectionContracts()
        c = contracts.ensure("business_overview")
        assert c.status == "gap"
        c.status = "supported"
        assert c.status == "supported"
        c.status = "partial"
        assert c.status == "partial"

    def test_add_fact(self):
        c = SectionEvidenceContract(
            section_key="business_overview",
            title="业务概览",
            allowed_source_types=["annual_report_pdf_section_summary"],
        )
        c.add_fact(
            fact_type="business_model",
            text="公司主营业务为白酒生产与销售。",
            evidence_ids=["ev_pdf_001"],
            source_types=["annual_report_pdf_section_summary"],
        )
        assert len(c.facts) == 1
        assert c.facts[0].fact_type == "business_model"
        assert "ev_pdf_001" in c.citation_evidence_ids

    def test_blocked_reasons_are_specific(self):
        c = SectionEvidenceContract(
            section_key="ownership_governance",
            title="股权结构与公司治理",
        )
        # Must not be a vague message
        c.add_blocked_reason("governance_section_not_found")
        assert "governance_section_not_found" in c.blocked_reasons

    def test_top_blockers(self):
        contracts = ReportSectionContracts()
        c1 = contracts.ensure("business_overview")
        c1.add_blocked_reason("business_overview_pdf_chunks_not_found")
        c2 = contracts.ensure("ownership_governance")
        c2.add_blocked_reason("governance_section_not_found")
        blockers = contracts.top_blockers(3)
        assert len(blockers) == 2
        assert any("business_overview" in b for b in blockers)
        assert any("ownership_governance" in b for b in blockers)


class TestContractBuilder:
    """Test the contract builder with A-share PDF summaries."""

    def test_business_overview_binds_only_pdf_evidence(self):
        """Business overview must only use PDF source types, not financial tables."""
        contracts = ReportSectionContracts()
        pdf_summaries = [
            _make_pdf_summary("business_overview",
                              "公司主要业务为白酒生产与销售，主导产品为飞天茅台酒。"
                              "经营模式为以产定销，通过批发代理和直销渠道实现销售。",
                              "ev_biz_001"),
        ]
        state = {"symbol": "600519.SS", "period": "FY2025"}
        _build_business_overview(
            contracts, pdf_summaries, [], [],
            {"company_profile": {"company_name": "贵州茅台"}},
            state,
        )
        c = contracts.get("business_overview")
        assert c is not None
        # Check that only PDF source types are used
        for fact in c.facts:
            for st in fact.source_types:
                assert st in {"annual_report_pdf_section_summary", "annual_report_pdf_chunk",
                              "official_filing", "sec_edgar"}, f"Unexpected source type: {st}"
        assert c.status in ("supported", "partial")

    def test_business_overview_no_financial_table(self):
        """Business overview must NOT reference income/balance/cashflow tables."""
        contracts = ReportSectionContracts()
        pdf_summaries = []
        evidence_records = [
            _make_evidence_record("income_table", "ev_fin_001"),
            _make_evidence_record("balance_table", "ev_fin_002"),
        ]
        state = {"symbol": "600519.SS", "period": "FY2025"}
        _build_business_overview(
            contracts, pdf_summaries, [], evidence_records,
            {"company_profile": {}},
            state,
        )
        c = contracts.get("business_overview")
        assert c is not None
        for fact in c.facts:
            for st in fact.source_types:
                assert st not in {"income_table", "balance_table", "cashflow_table",
                                  "third_party_structured"}

    def test_risk_fallback_no_cashflow(self):
        """Risk factors fallback must not reference cashflow table."""
        contracts = ReportSectionContracts()
        pdf_summaries = []
        pdf_chunks = []
        state = {"symbol": "600519.SS", "period": "FY2025"}
        _build_risk_factors(
            contracts, pdf_summaries, pdf_chunks, [], {},
            state,
        )
        c = contracts.get("risk_factors")
        assert c is not None
        for fact in c.facts:
            for st in fact.source_types:
                assert st != "cashflow_table", "risk fallback must not bind cashflow"

    def test_governance_missing_has_specific_blocker(self):
        """Governance gap should have specific blocked_reason, not a generic one."""
        contracts = ReportSectionContracts()
        _build_ownership_governance(
            contracts, [], [], [],
            {"symbol": "600519.SS", "period": "FY2025"},
        )
        c = contracts.get("ownership_governance")
        assert c is not None
        assert c.blocked_reasons  # must have some reason
        reason = c.blocked_reasons[0]
        # Must be specific, not vague
        assert reason in {"governance_section_not_found", "governance_chunks_noise_only",
                          "governance_summary_not_injected"}, f"Unexpected reason: {reason}"

    def test_strategy_business_no_fragments(self):
        """Strategy section must not contain fragment patterns."""
        contracts = ReportSectionContracts()
        pdf_chunks = [
            _make_pdf_chunk("management_discussion",
                            "将共同决定其。行业竞争格局和公司战略执行综上",
                            "ev_mda_001"),
        ]
        _build_strategy_business(
            contracts, [], pdf_chunks, [], {},
            {},
        )
        c = contracts.get("strategy_business")
        assert c is not None
        if c.facts:
            for fact in c.facts:
                has_frag = text_contains_fragments(fact.text)
                if has_frag:
                    assert c.quality_flags  # fragments should be flagged

    def test_strategy_pdf_fallback_clears_not_found_blocker(self):
        """A usable MD&A PDF summary should support strategy, not remain not-found."""
        contracts = ReportSectionContracts()
        pdf_summaries = [
            _make_pdf_summary(
                "management_discussion",
                (
                    "公司坚持以消费者为中心、市场需求为驱动，稳步推进全面向C战略，"
                    "通过场景、客群、服务转型以及产品端、渠道端、终端变革提升市场韧性。"
                ),
                "ev_mda_001",
            )
        ]
        _build_strategy_business(contracts, pdf_summaries, [], [], {}, {})

        c = contracts.get("strategy_business")
        assert c is not None
        assert c.status in {"partial", "supported"}
        assert "strategy_pdf_sections_not_found" not in c.blocked_reasons
        assert c.citation_evidence_ids == ["ev_mda_001"]

    def test_strategy_pdf_fallback_in_full_builder_clears_not_found_blocker(self):
        """Full builder fallback must not leave contradictory not-found blockers."""
        contracts = build_report_section_contracts(
            state={"symbol": "600519.SS", "period": "FY2025"},
            evidence_records=[],
            analysis_artifacts={
                "pdf_section_summaries": [
                    _make_pdf_summary(
                        "management_discussion",
                        (
                            "公司坚持以消费者为中心、市场需求为驱动，稳步推进全面向C战略，"
                            "通过场景、客群、服务转型以及产品端、渠道端、终端变革提升市场韧性。"
                        ),
                        "ev_mda_001",
                    )
                ]
            },
            section_dossiers={},
            citations=[],
        )

        c = contracts.get("strategy_business")
        assert c is not None
        assert c.status == "partial"
        assert "strategy_pdf_sections_not_found" not in c.blocked_reasons
        assert "ev_mda_001" in c.citation_evidence_ids

    def test_boilerplate_detection(self):
        """PDF boilerplate should be detected and cleaned."""
        text = "贵州茅台酒股份有限公司2025年年度报告 四、主营业务分析 √适用□不适用"
        found = text_contains_pdf_boilerplate(text)
        assert found  # should detect at least one pattern
        cleaned = clean_pdf_boilerplate(text)
        assert "年度报告" not in cleaned
        assert "四、" not in cleaned
        assert "√适用" not in cleaned

    def test_contract_builder_full(self):
        """Full contract builder should produce all sections."""
        state = {"symbol": "600519.SS", "period": "FY2025"}
        contracts = build_report_section_contracts(
            state=state,
            evidence_records=[],
            analysis_artifacts={},
            section_dossiers={},
            citations=[],
        )
        # Should have all expected sections
        for sk in ["executive_summary", "business_overview", "ownership_governance",
                    "strategy_business", "three_statement_summary", "financial_analysis",
                    "peer_compare", "valuation", "valuation_sensitivity", "risk_factors",
                    "investment_conclusion", "period_note", "currency_data_quality"]:
            assert contracts.get(sk) is not None, f"Missing section: {sk}"


class TestCleanPdfBoilerplate:

    def test_removes_section_numbers(self):
        assert "四、" not in clean_pdf_boilerplate("四、主营业务分析")

    def test_removes_checkbox_boilerplate(self):
        assert "√适用" not in clean_pdf_boilerplate("√适用□不适用")

    def test_preserves_meaningful_text(self):
        text = "公司主营业务为白酒生产与销售。√适用□不适用"
        cleaned = clean_pdf_boilerplate(text)
        assert "公司主营业务为白酒生产与销售" in cleaned


def _build_strategy_business(contracts, summaries, chunks, evidence_records, financial_metrics, analysis):
    """Direct call to the contract builder's strategy section builder."""
    from src.report.contract_builder import _build_strategy_business
    _build_strategy_business(contracts, summaries, chunks, evidence_records,
                             financial_metrics, analysis)
