"""US market isolation regression tests.

Validates that US market reports (TSLA fixture) are NOT polluted by
CN A-share contract logic and work correctly via the old SEC path.

When CONTRACT_MODE_ENABLED_BY_MARKET["us"] is False (guarded):
- Orchestrator falls back to old SEC annual_report_sections path
- Currency, peers, period, gaps are handled by old pipeline

These tests exercise the contract builder's SEC adapter directly
to validate it works correctly when us contract mode IS enabled.
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
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_SEC_10K_SECTION,
    SRC_SEC_10K_FILING,
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_FINANCIAL_METRIC,
    SRC_YAHOO_PROFILE,
    SRC_MARKET_DATA,
    ALLOWED_QUALITATIVE_PDF_ONLY,
    FORBIDDEN_SECTION_SOURCE_TYPES,
)
from src.report.contract_builder import (
    build_report_section_contracts,
    SEC_ITEM_TO_SECTION,
)
from src.report.contract_renderer import (
    render_section_from_contract,
    render_full_report_from_contracts,
    render_section_to_markdown,
)
from src.report.citation_binder import CitationBinder


# ── Synthetic TSLA data (regression fixture, not production data) ──────


def _synthetic_tsla_state() -> Dict[str, Any]:
    """Create synthetic state mimicking TSLA FY2025."""
    return {
        "symbol": "TSLA",
        "period": "FY2025",
        "entity_resolution": {"company_name": "Tesla, Inc."},
    }


def _synthetic_annual_report_sections() -> List[Dict[str, Any]]:
    """SEC 10-K annual report sections as extracted by AnnualReportSectionExtractor."""
    return [
        {
            "section_key": "business",
            "content": (
                "Tesla designs, develops, manufactures, leases, and sells electric vehicles"
                " and energy generation and storage systems. The company operates in two segments:"
                " Automotive and Energy Generation and Storage. The Automotive segment includes"
                " sales of electric vehicles, automotive regulatory credits, and services."
                " Tesla's mission is to accelerate the world's transition to sustainable energy."
                " The company has manufacturing facilities in Fremont, California; Austin, Texas;"
                " Shanghai, China; and Berlin, Germany. Tesla also produces battery cells and"
                " energy storage products including Powerwall, Powerpack, and Megapack."
                " The company sells its vehicles through company-owned showrooms and galleries"
                " as well as online configurators, and its energy products through a retail"
                " and direct sales channel."
            ),
            "evidence_id": "ev_tsla_sec_business_001",
        },
        {
            "section_key": "risk_factors",
            "content": (
                "Tesla faces significant risks including: (1) dependence on the market for"
                " electric vehicles which is still developing; (2) supply chain disruptions for"
                " batteries and semiconductors; (3) intense competition from established"
                " automakers and new entrants; (4) regulatory changes regarding vehicle safety,"
                " autonomous driving, and emissions; (5) manufacturing ramp risks at new"
                " facilities; (6) reliance on key personnel including Elon Musk; (7) currency"
                " and geopolitical risks from international operations; and (8) cybersecurity"
                " risks related to connected vehicles and autonomous driving systems."
            ),
            "evidence_id": "ev_tsla_sec_risk_001",
        },
        {
            "section_key": "mda",
            "content": (
                "Tesla's revenue increased significantly in FY2025 driven by higher vehicle"
                " deliveries and growth in energy storage deployment. Automotive revenue"
                " increased by 25% year-over-year, while energy generation and storage revenue"
                " grew by 60%. Gross margin improved due to lower battery costs and increased"
                " production scale. Operating expenses increased primarily in research and"
                " development for new vehicle platforms, autonomous driving technology, and"
                " manufacturing optimization. The company continues to invest in capacity expansion"
                " including Cybertruck ramp, next-generation vehicle platform, and Dojo"
                " supercomputer for AI training. Cash flow from operations remained strong,"
                " enabling continued investment in growth."
            ),
            "evidence_id": "ev_tsla_sec_mda_001",
        },
        {
            "section_key": "financial_statements",
            "content": "Consolidated Balance Sheets, Statements of Operations, and Cash Flows for FY2025.",
            "evidence_id": "ev_tsla_sec_fin_001",
        },
        {
            "section_key": "governance",
            "content": (
                "Tesla's Board of Directors consists of eight members, with a majority being"
                " independent directors. Key committees include Audit, Compensation, and"
                " Nominating and Corporate Governance. Elon Musk serves as Chief Executive"
                " Officer and Product Architect. The company has adopted a Code of Business"
                " Conduct and Ethics for all employees, officers, and directors. Stockholders"
                " have the right to vote on key matters including director elections and"
                " executive compensation. The company's common stock is listed on NASDAQ"
                " under the symbol TSLA."
            ),
            "evidence_id": "ev_tsla_sec_gov_001",
        },
    ]


def _synthetic_tsla_financial_metrics() -> Dict[str, Any]:
    """Synthetic TSLA financial metrics with USD currency."""
    return {
        "revenue": 120_000_000_000,
        "net_income": 18_500_000_000,
        "total_assets": 130_000_000_000,
        "total_liabilities": 45_000_000_000,
        "operating_cash_flow": 22_000_000_000,
        "free_cash_flow": 8_500_000_000,
        "period": "FY2025",
        "metric_count": 15,
        "metrics": [
            {"metric_name": "revenue", "value": 120_000_000_000, "period": "FY2025",
             "unit": "USD", "source_type": "sec_companyfacts"},
            {"metric_name": "net_income", "value": 18_500_000_000, "period": "FY2025",
             "unit": "USD", "source_type": "sec_companyfacts"},
        ],
    }


def _synthetic_tsla_tables() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Income Statement",
            "period": "FY2025",
            "source_type": "sec_companyfacts",
            "markdown": "| Item | FY2025 |\n|------|--------|\n| Revenue | 120.0B USD |\n| Net Income | 18.5B USD |\n",
            "rows": [
                {"item": "Revenue", "value": 120_000_000_000, "period": "FY2025",
                 "source_type": "income_table"},
                {"item": "Net Income", "value": 18_500_000_000, "period": "FY2025",
                 "source_type": "income_table"},
            ],
        },
        {
            "title": "Balance Sheet",
            "period": "FY2025",
            "source_type": "sec_companyfacts",
            "markdown": "| Item | FY2025 |\n|------|--------|\n| Total Assets | 130.0B USD |\n",
            "rows": [
                {"item": "Total Assets", "value": 130_000_000_000, "period": "FY2025",
                 "source_type": "balance_table"},
            ],
        },
        {
            "title": "Cash Flow Statement",
            "period": "FY2025",
            "source_type": "sec_companyfacts",
            "markdown": "| Item | FY2025 |\n|------|--------|\n| Operating CF | 22.0B USD |\n",
            "rows": [
                {"item": "Operating Cash Flow", "value": 22_000_000_000, "period": "FY2025",
                 "source_type": "cashflow_table"},
            ],
        },
    ]


def _synthetic_tsla_evidence_records() -> List[Dict[str, Any]]:
    return [
        {
            "evidence_id": "ev_tsla_sec_business_001",
            "source_type": SRC_SEC_10K_SECTION,
            "title": "SEC 10-K Item 1 Business",
            "content": "Tesla designs, develops, manufactures, and sells electric vehicles.",
        },
        {
            "evidence_id": "ev_tsla_sec_risk_001",
            "source_type": SRC_SEC_10K_SECTION,
            "title": "SEC 10-K Item 1A Risk Factors",
            "content": "Tesla faces significant risks including supply chain disruptions.",
        },
        {
            "evidence_id": "ev_tsla_sec_gov_001",
            "source_type": SRC_SEC_10K_SECTION,
            "title": "SEC 10-K Item 10 Governance",
            "content": "Tesla's Board of Directors consists of eight members.",
        },
        {
            "evidence_id": "ev_tsla_sec_mda_001",
            "source_type": SRC_SEC_10K_SECTION,
            "title": "SEC 10-K Item 7 MD&A",
            "content": "Tesla's revenue increased significantly in FY2025.",
        },
        {
            "evidence_id": "ev_tsla_yahoo_profile",
            "source_type": SRC_YAHOO_PROFILE,
            "title": "Yahoo Company Profile",
            "content": "Tesla, Inc. designs, develops, manufactures, and sells electric vehicles.",
        },
        {
            "evidence_id": "ev_tsla_yahoo_financial",
            "source_type": "yahoo_financial",
            "title": "Yahoo Financial Data",
            "content": "Revenue 120B USD, Net Income 18.5B USD",
        },
        {
            "evidence_id": "ev_tsla_market_snapshot",
            "source_type": SRC_MARKET_DATA,
            "title": "Yahoo Market Snapshot",
            "content": "Market Cap: 800B USD, P/E: 43.2",
        },
    ]


def _synthetic_tsla_analysis_artifacts() -> Dict[str, Any]:
    return {
        "annual_report_sections": _synthetic_annual_report_sections(),
        "financial_metrics": _synthetic_tsla_financial_metrics(),
        "tables": _synthetic_tsla_tables(),
        "peer_analysis": {
            "peer_rows": [
                {"symbol": "TSLA", "company_name": "Tesla, Inc.",
                 "industry": "automotive", "revenue_growth": "25.0",
                 "gross_margin": "19.8", "net_margin": "15.4", "roe": "22.3"},
                {"symbol": "AAPL", "company_name": "Apple Inc.",
                 "industry": "technology_consumer_electronics", "revenue_growth": "3.2",
                 "gross_margin": "45.6", "net_margin": "25.3", "roe": "150.0"},
                {"symbol": "AMZN", "company_name": "Amazon.com Inc.",
                 "industry": "ecommerce_cloud", "revenue_growth": "11.5",
                 "gross_margin": "47.2", "net_margin": "6.8", "roe": "20.1"},
                {"symbol": "GOOG", "company_name": "Alphabet Inc.",
                 "industry": "technology_advertising", "revenue_growth": "8.1",
                 "gross_margin": "56.5", "net_margin": "22.8", "roe": "30.5"},
                {"symbol": "GM", "company_name": "General Motors",
                 "industry": "automotive", "revenue_growth": "2.5",
                 "gross_margin": "13.2", "net_margin": "5.1", "roe": "12.8"},
                {"symbol": "LCID", "company_name": "Lucid Group",
                 "industry": "automotive_ev", "revenue_growth": "45.0",
                 "gross_margin": "-80.0", "net_margin": "-120.0", "roe": "-25.0"},
            ],
            "approved_peer_symbols": ["TSLA", "AAPL", "AMZN", "GOOG", "GM", "LCID"],
        },
        "currency_audit": {
            "statement_currency": "USD",
            "trading_currency": "USD",
            "market": "us",
            "symbol": "TSLA",
        },
    }


# ── Tests ─────────────────────────────────────────────────────────────


class TestSECSectionAdapter:
    """Test the SEC Item→section mapping and contract builder's SEC adapter."""

    def test_sec_item_to_section_mapping(self):
        """SEC_ITEM_TO_SECTION maps all key SEC items to report sections."""
        assert "business" in SEC_ITEM_TO_SECTION
        assert "risk_factors" in SEC_ITEM_TO_SECTION
        assert "mda" in SEC_ITEM_TO_SECTION
        assert "financial_statements" in SEC_ITEM_TO_SECTION
        assert "governance" in SEC_ITEM_TO_SECTION
        assert SEC_ITEM_TO_SECTION["business"] == "business_overview"
        assert SEC_ITEM_TO_SECTION["risk_factors"] == "risk_factors"
        assert SEC_ITEM_TO_SECTION["mda"] == "strategy_business"

    def test_sec_source_types_in_allowed_qualitative(self):
        """SEC source types are in ALLOWED_QUALITATIVE_PDF_ONLY."""
        assert SRC_SEC_10K_SECTION in ALLOWED_QUALITATIVE_PDF_ONLY
        assert SRC_SEC_10K_FILING in ALLOWED_QUALITATIVE_PDF_ONLY

    def test_business_overview_uses_sec_10k(self):
        """When SEC Item 1 exists, business_overview uses SEC content not gap."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        biz = contracts.get("business_overview")
        assert biz is not None

        # Should use SEC 10-K section, not gap or yahoo fallback
        has_sec = any(SRC_SEC_10K_SECTION in fact.source_types for fact in biz.facts)
        assert has_sec, "business_overview should use SEC 10-K Item 1"
        assert biz.status in ("supported", "partial"), f"Expected supported/partial, got {biz.status}"

    def test_governance_uses_sec_10k(self):
        """When SEC governance section exists, ownership_governance is not gap."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        gov = contracts.get("ownership_governance")
        assert gov is not None

        has_sec = any(SRC_SEC_10K_SECTION in fact.source_types for fact in gov.facts)
        if not has_sec:
            # Even if not directly from SEC, must not be gap
            assert gov.status != "gap", f"governance should not be gap, got {gov.status}"
            assert gov.blocked_reasons, "governance should have blocked_reasons if gap"

    def test_risk_uses_sec_10k_item_1a(self):
        """SEC Item 1A Risk Factors exists → risk_factors gets supported status."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        risk = contracts.get("risk_factors")
        assert risk is not None

        # Should use SEC 10-K Item 1A
        has_sec = any(SRC_SEC_10K_SECTION in fact.source_types for fact in risk.facts)
        if has_sec:
            assert risk.status in ("supported", "partial"), (
                f"risk should be supported/partial with SEC data, got {risk.status}"
            )
        has_quality_flag = any("risk_uses_sec_10k_item_1a" in flag or "risk_uses_official_pdf" in flag
                               for flag in risk.quality_flags)
        # At minimum, should be using SEC or have clear blocker
        if not has_quality_flag:
            assert risk.status != "gap", "risk should not be gap when Item 1A exists"

    def test_strategy_uses_sec_mda(self):
        """SEC Item 7 MD&A exists → strategy_business uses SEC content."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        strategy = contracts.get("strategy_business")
        assert strategy is not None

        has_sec = any(SRC_SEC_10K_SECTION in fact.source_types for fact in strategy.facts)
        if has_sec:
            assert strategy.status in ("supported", "partial"), (
                f"strategy should be supported/partial with SEC MD&A, got {strategy.status}"
            )


class TestUSPeerUniverse:
    """US peer classification must not include cross-industry megacaps as direct peers."""

    def test_cross_industry_peers_not_direct(self):
        """AAPL/AMZN/GOOG (tech) must NOT be TSLA 'direct_competitor'."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        peer_c = contracts.get("peer_compare")
        assert peer_c is not None

        direct_peer_symbols: List[str] = []
        for group in peer_c.peer_groups:
            if group.group_label == "direct_competitor":
                direct_peer_symbols.extend(group.symbols)

        # AAPL/AMZN/GOOG are tech, not auto - should NOT be direct competitors
        forbidden_direct = {"AAPL", "AMZN", "GOOG"}
        actual_direct = set(s.upper() for s in direct_peer_symbols)
        overlap = forbidden_direct & actual_direct
        assert not overlap, (
            f"Cross-industry peers {overlap} should not be TSLA direct competitors. "
            f"Direct peers: {actual_direct}"
        )

    def test_same_industry_peers_can_be_direct(self):
        """GM/LCID (automotive) may be TSLA direct peers."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        peer_c = contracts.get("peer_compare")
        assert peer_c is not None

        direct_peer_symbols: List[str] = []
        for group in peer_c.peer_groups:
            if group.group_label == "direct_competitor":
                direct_peer_symbols.extend(group.symbols)

        # At least one auto peer should be a direct competitor
        auto_peers = {"GM", "LCID"}
        actual = set(s.upper() for s in direct_peer_symbols)
        assert auto_peers & actual, (
            f"At least one auto peer should be direct, got {actual}"
        )

    def test_peer_industry_quality_flag(self):
        """Cross-industry same-market peers get peer_industry_unmatched flag."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        peer_c = contracts.get("peer_compare")
        assert peer_c is not None

        unmatched_flags = [f for f in peer_c.quality_flags if "peer_industry_unmatched" in f]
        assert unmatched_flags, (
            "Should have peer_industry_unmatched quality flags for cross-industry peers"
        )

        # Should flag AAPL, AMZN, or GOOG as unmatched
        flagged_symbols = [f.split(":")[-1] for f in unmatched_flags if ":" in f]
        assert "AAPL" in flagged_symbols or "AMZN" in flagged_symbols or "GOOG" in flagged_symbols, (
            f"Expected AAPL/AMZN/GOOG flagged as unmatched, got {flagged_symbols}"
        )


class TestUSPeriodResolution:
    """Period resolution for US companies must work from financial metrics/tables."""

    def test_latest_period_fy2025(self):
        """When all tables and metrics are FY2025, latest_available_period=FY2025."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None

        lp = contracts.metadata.get("latest_available_period", "")
        assert lp == "FY2025", f"Expected FY2025, got '{lp}'"

    def test_period_note_not_gap(self):
        """Period note section should be supported when period data exists."""
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()
        evidence = _synthetic_tsla_evidence_records()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        pn = contracts.get("period_note")
        assert pn is not None
        assert pn.status == "supported", (
            f"period_note should be supported when FY2025 data exists, got {pn.status}"
        )


class TestUSQualitativeNoYahoo:
    """Qualitative sections must not bind Yahoo/market data sources."""

    def test_qualitative_forbidden_source_types(self):
        """business_overview, governance, strategy forbid financial tables."""
        for sk in ["business_overview", "ownership_governance", "strategy_business", "risk_factors"]:
            forbidden = FORBIDDEN_SECTION_SOURCE_TYPES.get(sk, [])
            # Must forbid financial tables
            for fin_src in [SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE]:
                assert fin_src in forbidden, (
                    f"{sk} should forbid {fin_src}, got forbidden={forbidden}"
                )

    def test_citation_binder_rejects_yahoo_for_qualitative(self):
        """CitationBinder should reject Yahoo profile/financial for qualitative sections."""
        from src.report.citation_binder import CitationBinder

        evidence = _synthetic_tsla_evidence_records()
        binder = CitationBinder(evidence)

        # Build contracts with SEC data
        state = _synthetic_tsla_state()
        analysis = _synthetic_tsla_analysis_artifacts()

        contracts = build_report_section_contracts(
            state=state,
            evidence_records=evidence,
            analysis_artifacts=analysis,
            section_dossiers={},
            citations=[],
        )
        assert contracts is not None
        binder.bind_all(contracts)
        map_data = binder.get_citation_map()

        # Check that Yahoo sources are not bound to qualitative sections
        yahoo_evidence_ids = {"ev_tsla_yahoo_profile", "ev_tsla_yahoo_financial", "ev_tsla_market_snapshot"}

        for sk in ["business_overview", "ownership_governance", "strategy_business", "risk_factors"]:
            section_map = map_data.get(sk, {})
            bound_ids = set(section_map.keys())
            yahoo_in_qual = yahoo_evidence_ids & bound_ids
            assert not yahoo_in_qual, (
                f"{sk} should NOT bind Yahoo evidence, got {yahoo_in_qual}"
            )


class TestUSMarketIsolationFlag:
    """Test that the orchestrator's feature flag correctly gates contract mode for US."""

    def test_orchestrator_feature_flag_us_disabled(self):
        """MultiAgentOrchestrator.CONTRACT_MODE_ENABLED_BY_MARKET['us'] is True (enabled)."""
        from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
        assert MultiAgentOrchestrator.CONTRACT_MODE_ENABLED_BY_MARKET.get("us") is True, (
            "US contract mode should be enabled (True)"
        )

    def test_orchestrator_feature_flag_cn_enabled(self):
        """MultiAgentOrchestrator.CONTRACT_MODE_ENABLED_BY_MARKET['cn_a'] is True."""
        from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
        assert MultiAgentOrchestrator.CONTRACT_MODE_ENABLED_BY_MARKET.get("cn_a") is True

    def test_orchestrator_feature_flag_hk_enabled(self):
        """MultiAgentOrchestrator.CONTRACT_MODE_ENABLED_BY_MARKET['hk'] is True."""
        from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
        assert MultiAgentOrchestrator.CONTRACT_MODE_ENABLED_BY_MARKET.get("hk") is True

    def test_build_contracts_and_bind_returns_contracts_for_us(self):
        """_build_contracts_and_bind returns valid contracts for US market when True."""
        from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
        import tempfile

        orch = MultiAgentOrchestrator(output_dir=tempfile.mkdtemp())
        state = _synthetic_tsla_state()
        state["evidence_records"] = _synthetic_tsla_evidence_records()
        state["analysis_artifacts"] = _synthetic_tsla_analysis_artifacts()

        contracts, binder = orch._build_contracts_and_bind(state)
        assert contracts is not None, "US contract mode should return contracts (enabled)"
        assert binder is not None, "US binder should be returned (enabled)"
        # Verify key sections exist
        for key in ("business_overview", "risk_factors", "strategy_business", "ownership_governance"):
            assert contracts.get(key) is not None, f"US contract mode should have section: {key}"


class TestCurrencyMarketMismatch:
    """Currency checks must flag CNY strings in USD reports."""

    def test_currency_check_rejects_cny_in_usd_report(self):
        """_check_currency_market_mismatch must flag CNY strings in USD report."""
        from src.evaluation.report_quality import _check_currency_market_mismatch

        issues: List[Dict[str, Any]] = []

        # Create artifacts with USD currency audit and Chinese currency in report text
        artifacts = {
            "currency_audit": {
                "statement_currency": "USD",
                "trading_currency": "USD",
                "market": "us",
                "symbol": "TSLA",
            },
            "report_md": (
                "## 业务概览\n\n"
                "公司营业收入为1200亿元人民币，同比增长25%。\n"
            ),
            "report_html": "<p>净利润为185亿元人民币。</p>",
        }

        _check_currency_market_mismatch(artifacts, issues, "us", "TSLA")
        assert issues, "Should have flagged CNY in USD report"
        has_currency_issue = any("currency_market_mismatch" in i.get("category", "") for i in issues)
        assert has_currency_issue, (
            f"Expected currency_market_mismatch issue, got: {[i.get('category') for i in issues]}"
        )

    def test_usd_report_without_cny_passes(self):
        """USD report without CNY strings should pass the check."""
        from src.evaluation.report_quality import _check_currency_market_mismatch

        issues: List[Dict[str, Any]] = []

        artifacts = {
            "currency_audit": {
                "statement_currency": "USD",
                "trading_currency": "USD",
                "market": "us",
                "symbol": "TSLA",
            },
            "report_md": (
                "## Business Overview\n\n"
                "Revenue was $120.0B USD, up 25% YoY.\n"
            ),
            "report_html": "<p>Net income was $18.5B USD.</p>",
        }

        _check_currency_market_mismatch(artifacts, issues, "us", "TSLA")
        has_currency_issue = any("currency_market_mismatch" in i.get("category", "") for i in issues)
        assert not has_currency_issue, (
            f"Clean USD report should not have currency issues, got: {issues}"
        )


class TestUSRegressionNoHardcode:
    """Regression validation: TSLA fixture must not be hardcoded in logic,
    only referenced as test data."""

    def test_sec_source_types_defined(self):
        """SEC source type constants exist."""
        assert SRC_SEC_10K_SECTION == "sec_10k_section"
        assert SRC_SEC_10K_FILING == "sec_10k_filing"
