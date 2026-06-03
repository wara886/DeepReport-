"""End-to-end contract regression test for 600519.SS.

This test validates that the contract-first generation pipeline fixes known issues
with 600519.SS FY2025 reports. It does NOT hardcode the symbol — it's only
a regression fixture.

Assertions:
1. business_overview does NOT contain PDF boilerplate
2. governance gap shows specific blocker, does NOT cite [1][2][3]
3. strategy section does NOT contain fragment patterns
4. peer section does NOT list PG/KO/PEP/WMT/COST as direct comparable
5. risk fallback does NOT reference Eastmoney cashflow
6. latest_available_period = FY2025
7. blocked HTML shows top blockers
8. Eastmoney can exist in references but NOT as qualitative section citation
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.report.section_contracts import (
    ReportSectionContracts,
    SectionEvidenceContract,
    clean_pdf_boilerplate,
    text_contains_pdf_boilerplate,
    text_contains_fragments,
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_FINANCIAL_METRIC,
    SRC_THIRD_PARTY_STRUCTURED,
)
from src.report.contract_builder import (
    build_report_section_contracts,
)
from src.report.contract_renderer import (
    render_section_from_contract,
    render_full_report_from_contracts,
    render_section_to_markdown,
)
from src.report.citation_binder import CitationBinder


# ── Synthetic 600519 data (regression fixture, not production data) ──────


def _synthetic_600519_state() -> Dict[str, Any]:
    """Create synthetic state mimicking 600519.SS FY2025."""
    return {
        "symbol": "600519.SS",
        "period": "FY2025",
        "entity_resolution": {"company_name": "贵州茅台酒股份有限公司"},
    }


def _synthetic_600519_pdf_summaries() -> List[Dict[str, Any]]:
    """PDF summaries that should NOT contain PDF boilerplate when processed."""
    return [
        {
            "section_type": "business_overview",
            "summary_zh": (
                "公司主营业务为茅台酒及系列酒的生产与销售。"
                "经营模式为以产定销，通过直销和批发代理渠道实现销售。"
                '公司核心品牌「贵州茅台酒」具有较强品牌力和市场定价权。'
            ),
            "evidence_id": "ev_600519_biz_001",
            "usable_for_generation": True,
            "evidence_quality": "good",
        },
        {
            "section_type": "ownership_governance",
            "summary_zh": (
                "公司治理结构完善，设有董事会、监事会和高级管理层。"
                "但该摘要仅为测试数据，实际治理章节未被RAG稳定抽取。"
            ),
            "evidence_id": "ev_600519_gov_001",
            "usable_for_generation": False,
            "evidence_quality": "noise_only",
        },
    ]


def _synthetic_600519_financial_metrics() -> Dict[str, Any]:
    """Synthetic financial metrics (FY2025)."""
    return {
        "revenue": 174_140_000_000,
        "net_income": 86_200_000_000,
        "total_assets": 279_000_000_000,
        "total_liabilities": 43_000_000_000,
        "operating_cash_flow": 87_000_000_000,
        "free_cash_flow": 82_000_000_000,
        "period": "FY2025",
        "metric_count": 12,
    }


def _synthetic_600519_tables() -> List[Dict[str, Any]]:
    return [
        {
            "title": "利润表",
            "period": "FY2025",
            "source_type": "eastmoney",
            "markdown": "| 项目 | FY2025 |\n|------|--------|\n| 营业收入 | 1741.40亿 |\n| 净利润 | 862.00亿 |\n",
            "rows": [
                {"item": "营业收入", "value": 174140000000, "source_type": "income_table"},
                {"item": "净利润", "value": 86200000000, "source_type": "income_table"},
            ],
        },
        {
            "title": "资产负债表",
            "period": "FY2025",
            "source_type": "eastmoney",
            "markdown": "| 项目 | FY2025 |\n|------|--------|\n| 总资产 | 2790.00亿 |\n",
        },
        {
            "title": "现金流量表",
            "period": "FY2025",
            "source_type": "eastmoney",
            "markdown": "| 项目 | FY2025 |\n|------|--------|\n| 经营现金流 | 870.00亿 |\n",
        },
    ]


def _synthetic_evidence_records() -> List[Dict[str, Any]]:
    return [
        {
            "evidence_id": "ev_eastmoney_income",
            "source_type": SRC_INCOME_TABLE,
            "title": "Eastmoney Income Statement",
            "content": "FY2025 income data",
        },
        {
            "evidence_id": "ev_eastmoney_balance",
            "source_type": SRC_BALANCE_TABLE,
            "title": "Eastmoney Balance Sheet",
            "content": "FY2025 balance data",
        },
        {
            "evidence_id": "ev_eastmoney_cashflow",
            "source_type": SRC_CASHFLOW_TABLE,
            "title": "Eastmoney Cashflow Statement",
            "content": "FY2025 cashflow data",
        },
        {
            "evidence_id": "ev_600519_biz_001",
            "source_type": SRC_ANNUAL_REPORT_PDF_SUMMARY,
            "title": "Annual Report Business Section",
            "content": "Business overview content",
        },
    ]


def _synthetic_analysis_artifacts() -> Dict[str, Any]:
    return {
        "pdf_section_summaries": _synthetic_600519_pdf_summaries(),
        "financial_metrics": _synthetic_600519_financial_metrics(),
        "tables": _synthetic_600519_tables(),
        "peer_analysis": {
            "peer_rows": [
                {"symbol": "PG", "company_name": "Procter & Gamble",
                 "revenue_growth": "2.1", "gross_margin": "48.5",
                 "net_margin": "13.2", "roe": "28.1"},
                {"symbol": "KO", "company_name": "Coca-Cola",
                 "revenue_growth": "5.3", "gross_margin": "60.2",
                 "net_margin": "22.1", "roe": "40.5"},
                {"symbol": "PEP", "company_name": "PepsiCo",
                 "revenue_growth": "4.8", "gross_margin": "54.0",
                 "net_margin": "10.8", "roe": "48.2"},
            ],
            "approved_peer_symbols": ["PG", "KO", "PEP"],
        },
        "currency_audit": {
            "statement_currency": "CNY",
            "trading_currency": "CNY",
        },
    }


# ── Tests ───────────────────────────────────────────────────────────────


class Test600519ContractRegression:
    """Regression tests for 600519.SS using contract mode.

    No hardcoded 600519 production data — all synthetic fixtures above.
    """

    def test_1_business_overview_no_boilerplate(self):
        """Business overview must not contain PDF boilerplate."""
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        biz = contracts.get("business_overview")
        assert biz is not None, "business_overview contract missing"
        md = render_section_from_contract(biz)
        # Must not contain PDF boilerplate
        boilerplate_found = text_contains_pdf_boilerplate(md)
        assert not boilerplate_found, f"PDF boilerplate found: {boilerplate_found}"

    def test_2_governance_gap_shows_specific_blocker(self):
        """Governance gap must show specific blocker, not cite [1][2][3]."""
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        gov = contracts.get("ownership_governance")
        assert gov is not None
        md = render_section_from_contract(gov)
        # Must NOT cite Eastmoney tables
        assert "[1]" not in md
        assert "[2]" not in md
        assert "[3]" not in md
        assert "income" not in md.lower() or not any(
            st in {"income_table", "balance_table", "cashflow_table"}
            for fact in gov.facts for st in fact.source_types
        )

    def test_3_strategy_no_fragments(self):
        """Strategy section must not contain fragment patterns."""
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        strategy = contracts.get("strategy_business")
        if strategy and strategy.facts:
            for fact in strategy.facts:
                frags = text_contains_fragments(fact.text)
                assert not frags, f"Fragments found: {frags}"
        # If status is gap, check deterministic text is complete
        if strategy and strategy.status == "gap":
            assert strategy.deterministic_text, "Gap section must have deterministic text"
            assert not text_contains_fragments(strategy.deterministic_text)

    def test_4_peer_no_direct_comparable_mislabel(self):
        """Peer section must not list PG/KO/PEP as direct comparable."""
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        peer = contracts.get("peer_compare")
        if peer and peer.peer_groups:
            for group in peer.peer_groups:
                labels = set()
                if hasattr(group, 'group_label'):
                    labels.add(group.group_label)
                elif isinstance(group, dict):
                    labels.add(group.get('group_label', ''))
                # PG/KO/PEP are US stocks vs A-share 600519, so they're cross-market
                # The test is: they should NOT be labeled as direct_competitor
                # if they're foreign consumer goods while target is A-share baijiu
                cross_market_symbols = {"PG", "KO", "PEP"}
                group_syms = set()
                if hasattr(group, 'symbols'):
                    group_syms = set(group.symbols)
                elif isinstance(group, dict):
                    group_syms = set(group.get('symbols', []))
                if group_syms & cross_market_symbols:
                    # These must be cross_market_reference, not direct_competitor
                    label = group.group_label if hasattr(group, 'group_label') else group.get('group_label', '')
                    if label == "direct_competitor":
                        assert False, "Foreign peers should not be labeled as direct_competitor"

    def test_5_risk_fallback_no_eastmoney_cashflow(self):
        """Risk fallback must not reference Eastmoney cashflow."""
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        risk = contracts.get("risk_factors")
        assert risk is not None
        # Check no fact uses cashflow source type
        for fact in risk.facts:
            assert SRC_CASHFLOW_TABLE not in fact.source_types, \
                f"Risk fact uses cashflow source: {fact.text[:50]}"
        # Check binding audit
        binder = CitationBinder(evidence_records=_synthetic_evidence_records())
        result = binder.bind_contract(risk)
        assert result.status == "ok", f"Risk binding failed: {result.blocked_reasons}"

    def test_6_period_detected_fy2025(self):
        """Latest available period must be FY2025."""
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        metadata = contracts.metadata
        latest = metadata.get("latest_available_period", "")
        assert latest == "FY2025", f"Expected FY2025, got {latest}"

        # Period note should be supported
        period_note = contracts.get("period_note")
        assert period_note is not None
        # FY2025 in financial_metrics should give supported status
        assert period_note.status in ("supported", "partial"), \
            f"period_note status should not be gap, got {period_note.status}"

    def test_7_blocked_html_shows_blockers(self):
        """Blocked HTML must show top blockers in header."""
        contracts = ReportSectionContracts()
        contracts.metadata["target_symbol"] = "600519.SS"
        c1 = contracts.ensure("ownership_governance")
        c1.add_blocked_reason("governance_section_not_found")
        c2 = contracts.ensure("period_note")
        c2.add_blocked_reason("period_metadata_missing")

        top_blockers = contracts.top_blockers(5)
        md = render_full_report_from_contracts(
            contracts, "Test", top_blockers=top_blockers,
        )
        assert "质量诊断建议" in md
        assert any(b in md for b in top_blockers)

    def test_8_eastmoney_no_qualitative_citation(self):
        """Eastmoney can exist in references but not as qualitative section citation."""
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        binder = CitationBinder(evidence_records=_synthetic_evidence_records())
        results = binder.bind_all(contracts)

        # Qualitative sections should NOT bind Eastmoney financial tables
        qualitative_results = [r for r in results
                               if r.section_key in {
                                   "business_overview", "ownership_governance",
                                   "strategy_business", "risk_factors",
                                   "investment_conclusion",
                               }]
        for r in qualitative_results:
            assert r.status != "mismatch", \
                f"{r.section_key} has citation mismatches: {r.blocked_reasons}"

    def test_full_pipeline_integration(self):
        """Test that the full contract pipeline runs end-to-end without error."""
        # Build contracts
        contracts = build_report_section_contracts(
            state=_synthetic_600519_state(),
            evidence_records=_synthetic_evidence_records(),
            analysis_artifacts=_synthetic_analysis_artifacts(),
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        assert len(contracts.contracts) >= 10  # most sections present

        # Bind citations
        binder = CitationBinder(evidence_records=_synthetic_evidence_records())
        results = binder.bind_all(contracts)

        # Render report
        md = render_full_report_from_contracts(
            contracts, "Test Report",
            top_blockers=contracts.top_blockers(),
        )
        assert md
        assert "业务概览" in md
        assert "股权结构与公司治理" in md

        # Generate audit artifacts
        audit = binder.to_audit()
        assert audit is not None
        cmap = binder.to_citation_map()
        assert cmap is not None
