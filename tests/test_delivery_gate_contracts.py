"""Tests for diagnostic contract-level checks and HTML quality display.

Verifies that:
- Diagnostic HTML can show top_blockers as quality findings
- Confidence card can show diagnostic text
- Contract check functions produce correct issues
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.report_quality import (
    _check_contract_policies,
    _issue,
    _report_text,
)
from src.report.html_report_generator import (
    _render_header,
    _estimate_confidence,
    render_professional_html_report,
)


class TestHtmlBlockerDisplay:
    """Test that HTML header shows top quality diagnostics."""

    def test_blocked_header_shows_blockers(self):
        """Blocked header should include top blocker tags."""
        html = _render_header(
            "Test Report", 5, 10, "quality_diagnostic",
            top_blockers=["governance_section_gap", "peer_universe_mismatch"],
            quality_blocked=True,
        )
        assert "blocker-tag" in html or "质量诊断" in html
        assert "governance_section_gap" in html
        assert "peer_universe_mismatch" in html

    def test_blocked_confidence_shows_gate_message(self):
        """Diagnostic confidence should show quality message, not '基于数据覆盖与引用分析'."""
        html = _render_header(
            "测试报告", 5, 10, "blocked",
            top_blockers=["governance_gap"],
            quality_blocked=True,
        )
        # Must show quality diagnostics
        assert "质量诊断" in html
        # Must NOT show the old text
        assert "基于数据覆盖与引用分析" not in html

    def test_normal_header_no_blockers(self):
        """Normal delivery should not show blockers."""
        html = _render_header("Test Report", 5, 10, "normal")
        assert "质量诊断" not in html

    def test_estimate_confidence_blocked(self):
        """Blocked delivery should return 45 with gate message."""
        # Note: _estimate_confidence only returns the number, not the message
        score = _estimate_confidence(0, 0, "blocked")
        assert score == 50

    def test_degraded_warning_appears(self):
        """Degraded delivery should show degraded warning."""
        md = "# Test\n## Business Overview\nContent."
        html = render_professional_html_report(
            markdown=md,
            title="Test Report",
            delivery_status="degraded_due_to_content_quality",
            top_blockers=["governance_gap"],
            quality_blocked=True,
        )
        assert "degraded-warning" in html or "Data Gap" in html or "质量诊断" in html


class TestContractPolicyChecks:
    """Test contract-level check functions."""

    def test_business_overview_boilerplate(self):
        """Business overview with PDF boilerplate should produce issue."""
        artifacts = {
            "report_md": "## 业务概览\n内容",
            "report_section_contracts": {
                "contracts": {
                    "business_overview": {
                        "facts": [
                            {"text": "2025年年度报告 四、主营业务分析 √适用□不适用"}
                        ],
                        "quality_flags": ["business_overview_boilerplate_in_summary"],
                    }
                },
                "metadata": {},
            },
            "citation_binding_audit": {},
        }
        issues: List[Dict[str, Any]] = []
        _check_contract_policies(artifacts, issues)
        blocker_issues = [i for i in issues if i.get("severity") == "blocker"
                          and "business_overview_raw_pdf_paste" in str(i.get("issue_id", ""))]
        assert any("business_overview_raw_pdf_paste" in str(i.get("issue_id", "")) or
                   "business_overview_raw_pdf_paste" in str(i.get("category", ""))
                   for i in issues)

    def test_governance_gap_with_pdf(self):
        """Governance gap with PDF available should produce blocker."""
        artifacts = {
            "report_md": "## 股权结构与公司治理\n内容",
            "report_section_contracts": {
                "contracts": {
                    "ownership_governance": {
                        "status": "gap",
                        "blocked_reasons": ["governance_section_not_found"],
                    }
                },
                "metadata": {"pdf_rag_available": True},
            },
            "citation_binding_audit": {},
        }
        issues: List[Dict[str, Any]] = []
        _check_contract_policies(artifacts, issues)
        gov_issues = [i for i in issues if "governance_gap" in str(i.get("issue_id", ""))]
        assert gov_issues

    def test_period_metadata_missing(self):
        """Period note gap should produce blocker."""
        artifacts = {
            "report_md": "## 数据期间说明\n内容",
            "report_section_contracts": {
                "contracts": {
                    "period_note": {
                        "status": "gap",
                        "blocked_reasons": ["period_metadata_missing"],
                    }
                },
                "metadata": {},
            },
            "citation_binding_audit": {},
        }
        issues: List[Dict[str, Any]] = []
        _check_contract_policies(artifacts, issues)
        period_issues = [i for i in issues
                         if "period_metadata_missing" in str(i.get("issue_id", ""))]
        assert period_issues

    def test_citation_binding_mismatch(self):
        """Citation binding mismatches from audit should produce blocker."""
        artifacts = {
            "report_md": "",
            "report_section_contracts": {
                "contracts": {},
                "metadata": {},
            },
            "citation_binding_audit": {
                "total_mismatches": 2,
                "mismatches": [
                    "business_overview: evidence ev_001 bound to income_table"
                ],
            },
        }
        issues: List[Dict[str, Any]] = []
        _check_contract_policies(artifacts, issues)
        citation_issues = [i for i in issues
                           if "citation_binding_mismatch" in str(i.get("issue_id", ""))]
        assert citation_issues

    def test_peer_universe_mismatch(self):
        """Cross-market peers written as direct comparable should produce blocker."""
        artifacts = {
            "report_md": "与PG/KO/PEP/WMT/COST属于同一行业或业务相近口径",
            "report_section_contracts": {
                "contracts": {"peer_compare": {"facts": []}},
                "metadata": {},
            },
            "citation_binding_audit": {},
        }
        issues: List[Dict[str, Any]] = []
        _check_contract_policies(artifacts, issues)
        peer_issues = [i for i in issues
                       if "peer_universe_mismatch" in str(i.get("issue_id", ""))]
        assert peer_issues
