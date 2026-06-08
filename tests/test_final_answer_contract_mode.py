"""Tests for FinalAnswerAgent contract-mode execution.

Verifies that:
- FinalAnswer can render from contracts without global evidence
- Old global peer_rows / citations don't affect output
- Gap sections don't reference financial tables
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.report.section_contracts import (
    ReportSectionContracts,
    SectionEvidenceContract,
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_INCOME_TABLE,
)
from src.report.contract_renderer import (
    render_section_from_contract,
    render_section_to_markdown,
    render_full_report_from_contracts,
)
from src.agents.final_answer_agent import (
    dedupe_section_paragraphs,
    enforce_section_depth,
    remove_instructional_report_text,
)


class TestContractRenderer:
    """Test contract-based section rendering."""

    def test_render_supported_section(self):
        """Supported section should render facts as prose."""
        c = SectionEvidenceContract(
            section_key="business_overview",
            title="业务概览",
            status="supported",
        )
        c.add_fact("business_model", "公司主营业务为白酒生产与销售。")
        c.add_fact("sales_channel", "通过批发代理和直销渠道实现销售。")
        md = render_section_from_contract(c)
        assert "公司主营业务为白酒生产与销售" in md
        assert "批发代理" in md or "直销" in md

    def test_render_gap_section(self):
        """Gap section should show blocked reasons, not financial tables."""
        c = SectionEvidenceContract(
            section_key="ownership_governance",
            title="股权结构与公司治理",
            status="gap",
        )
        c.add_blocked_reason("governance_section_not_found")
        md = render_section_from_contract(c)
        assert "governance_section_not_found" in md
        assert "不展开" in md

    def test_render_fallback_section(self):
        """Fallback section should disclose the fallback source."""
        c = SectionEvidenceContract(
            section_key="risk_factors",
            title="风险评估",
            status="fallback",
        )
        c.add_fact("industry_risk_fallback", "行业竞争风险：消费品行业面临品牌替代风险。",
                   source_types=["industry_policy"])
        c.add_blocked_reason("risk_official_pdf_not_found")
        md = render_section_from_contract(c)
        assert "品牌替代" in md or "行业竞争" in md
        assert "补充性说明" in md or "待官方" in md

    def test_render_full_report(self):
        """Full report should include all sections."""
        contracts = ReportSectionContracts()
        contracts.metadata["target_symbol"] = "600519.SS"
        contracts.metadata["target_period"] = "FY2025"

        biz = contracts.ensure("business_overview")
        biz.status = "supported"
        biz.add_fact("business_model", "白酒生产与销售。")

        gov = contracts.ensure("ownership_governance")
        gov.status = "gap"
        gov.add_blocked_reason("governance_section_not_found")

        md = render_full_report_from_contracts(contracts, "Test Report")
        assert "业务概览" in md
        assert "白酒" in md
        assert "股权结构与公司治理" in md

    def test_no_citation_numbers_in_render(self):
        """Contract renderer should not produce [1][2][3] citation numbers."""
        c = SectionEvidenceContract(
            section_key="business_overview",
            title="业务概览",
            status="supported",
        )
        c.add_fact("business_model", "公司主营业务为白酒。",
                   evidence_ids=["ev_pdf_001"],
                   source_types=[SRC_ANNUAL_REPORT_PDF_SUMMARY])
        md = render_section_from_contract(c)
        # Should not have citation numbers like [1]
        assert "[1]" not in md
        assert "[ev_pdf_001]" not in md

    def test_gap_section_no_financial_table_reference(self):
        """Gap section should not reference income/balance/cashflow tables."""
        c = SectionEvidenceContract(
            section_key="ownership_governance",
            title="股权结构与公司治理",
            status="gap",
        )
        c.add_blocked_reason("governance_section_not_found")
        md = render_section_from_contract(c)
        # Should not contain financial table source types
        assert "income" not in md.lower()
        assert "balance" not in md.lower()
        assert "cashflow" not in md.lower()

    def test_top_blockers_not_shown_as_user_diagnostics(self):
        """Top blockers stay in diagnostics and should not be shown as a report banner."""
        contracts = ReportSectionContracts()
        c1 = contracts.ensure("ownership_governance")
        c1.add_blocked_reason("governance_section_not_found")
        c2 = contracts.ensure("period_note")
        c2.add_blocked_reason("period_metadata_missing")

        md = render_full_report_from_contracts(contracts, "Test", top_blockers=contracts.top_blockers())
        assert "质量诊断建议" not in md
        assert "governance_section_not_found" in md or "period_metadata_missing" in md


def test_depth_fallback_dedupes_and_removes_instructional_text():
    md = "# X\n\n## 执行摘要\n\n太短。\n\n## 同行对比\n\n太短。\n"
    out = enforce_section_depth(md, {"executive_summary": {}, "peer_compare": {}})
    out = remove_instructional_report_text(dedupe_section_paragraphs(out))

    assert out.count("本报告当前证据链主要覆盖") == 1
    assert "正文应" not in out
    assert "本节不得" not in out
    assert "避免把" not in out


def test_final_cleanup_removes_key_value_fact_leakage():
    md = (
        "# X\n\n"
        "## 业务概览\n\n"
        "业务概览应围绕产品结构、销售渠道、品牌或工艺壁垒以及收入贡献展开。\n\n"
        "关键事实为：公司Kweichow Moutai；products茅台酒；core_competitiveness品牌。\n\n"
        "## 财务分析\n\n"
        "关键事实为：has_financial_data是。\n\n"
        "本节可用事实\n"
    )
    out = remove_instructional_report_text(md)

    assert "业务概览应围绕" not in out
    assert "关键事实为" not in out
    assert "本节可用事实" not in out
    assert "products" not in out
    assert "core_competitiveness" not in out
    assert "has_financial_data" not in out


class TestContractModeNoGlobalLeakage:
    """Test that contract mode doesn't leak old global state."""

    def test_old_peer_rows_not_used(self):
        """Old global peer_rows should not appear in contract-mode rendering."""
        contracts = ReportSectionContracts()

        # Even though old peer data might exist in state, contracts should
        # have empty peer if no contract was built
        peer = contracts.ensure("peer_compare")
        peer.status = "gap"
        peer.add_blocked_reason("peer_rows_not_available")

        md = render_section_from_contract(peer)
        # Should not magically have peer data
        assert "PG/KO" not in md
        assert "WMT/COST" not in md

    def test_old_citations_not_injected(self):
        """Old global citations should not be injected into contract-mode output."""
        contracts = ReportSectionContracts()
        c = contracts.ensure("business_overview")
        c.status = "supported"
        c.add_fact("business_model", "主营业务。",
                   evidence_ids=["ev_pdf_001"],
                   source_types=[SRC_ANNUAL_REPORT_PDF_SUMMARY])

        md = render_section_from_contract(c)
        # Old citation format should not appear
        assert "[ev_old_001]" not in md
        assert "ref_001" not in md
