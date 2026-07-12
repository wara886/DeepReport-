from __future__ import annotations

from src.agents.annual_report_section_extractor import AnnualReportSectionExtractor, annual_sections_to_evidence_records
from src.agents.multi_agent_orchestrator import attach_annual_report_sections_to_state
from src.agents.section_dossier_builder import SectionDossierBuilder
from src.data.sec_filing_resolver import resolve_sec_annual_filing, resolve_sec_proxy_filing
from src.report.chart_generator import sanitize_chart_payloads
from src.report.deterministic_section_renderer import render_all_deterministic_blocks


MINIMAL_10K = """
<html><body>
<h1>Item 1. Business</h1>
<p>NVIDIA pioneered accelerated computing. The company reports data center,
gaming, professional visualization, automotive, and OEM revenue platforms.
Competition is intense across accelerated computing and AI infrastructure.</p>
<h1>Item 1A. Risk Factors</h1>
<p>Demand for our products can fluctuate materially. We face intense competition,
supply constraints, export controls, customer concentration, and manufacturing
dependencies that could adversely affect revenue and margins.</p>
<h1>Item 7. Management's Discussion and Analysis</h1>
<p>Management discusses revenue growth, gross margin, operating expenses,
liquidity and capital resources. Liquidity and Capital Resources include cash,
marketable securities, operating cash flow, and capital allocation priorities.</p>
<h1>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</h1>
<p>Market risk includes interest rate and foreign currency exposure.</p>
<h1>Item 8. Financial Statements and Supplementary Data</h1>
<p>Consolidated financial statements follow.</p>
</body></html>
"""


def test_sec_resolver_selects_nvda_fy2025_10k(monkeypatch):
    def fake_get_json(url, headers=None, timeout=20):
        return {
            "filings": {
                "recent": {
                    "form": ["10-Q", "10-K"],
                    "accessionNumber": ["0001045810-25-000010", "0001045810-25-000023"],
                    "filingDate": ["2025-11-20", "2025-02-26"],
                    "reportDate": ["2025-10-26", "2025-01-26"],
                    "primaryDocument": ["nvda-20251026.htm", "nvda-20250126.htm"],
                }
            }
        }

    monkeypatch.setattr("src.data.sec_filing_resolver._get_json", fake_get_json)
    monkeypatch.setattr("src.data.sec_filing_resolver._get_text", lambda *args, **kwargs: MINIMAL_10K)
    payload = resolve_sec_annual_filing("NVDA", "FY2025", fetch_document=True)
    data = payload.to_dict()
    assert data["meta"]["status"] == "resolved"
    assert data["meta"]["filing"]["primary_document"] == "nvda-20250126.htm"
    assert data["evidence_records"][0]["source_type"] == "sec_10k_filing"
    assert "000104581025000023" in data["meta"]["filing_url"]


def test_sec_resolver_prefers_original_10k_over_later_amendment(monkeypatch):
    def fake_get_json(url, headers=None, timeout=20):
        return {
            "filings": {
                "recent": {
                    "form": ["10-K/A", "10-K"],
                    "accessionNumber": ["0000000000-26-000002", "0000000000-26-000001"],
                    "filingDate": ["2026-04-30", "2026-02-15"],
                    "reportDate": ["2025-12-31", "2025-12-31"],
                    "primaryDocument": ["amendment.htm", "original10k.htm"],
                }
            }
        }

    monkeypatch.setattr("src.data.sec_filing_resolver._get_json", fake_get_json)
    monkeypatch.setattr("src.data.sec_filing_resolver._get_text", lambda *args, **kwargs: MINIMAL_10K)

    payload = resolve_sec_annual_filing("TSLA", "FY2025", fetch_document=True)

    assert payload.meta["filing"]["form"] == "10-K"
    assert payload.meta["filing"]["primary_document"] == "original10k.htm"


def test_sec_proxy_resolver_extracts_bounded_governance_evidence(monkeypatch):
    monkeypatch.setattr(
        "src.data.sec_filing_resolver._get_json",
        lambda *args, **kwargs: {
            "filings": {
                "recent": {
                    "form": ["DEF 14A", "10-K"],
                    "accessionNumber": ["0001045810-25-000030", "0001045810-25-000023"],
                    "filingDate": ["2025-05-10", "2025-02-26"],
                    "reportDate": ["2025-01-26", "2025-01-26"],
                    "primaryDocument": ["nvda-proxy.htm", "nvda-10k.htm"],
                }
            }
        },
    )
    monkeypatch.setattr(
        "src.data.sec_filing_resolver._get_text",
        lambda *args, **kwargs: (
            "<html><body><h1>Corporate Governance</h1>"
            "<p>The board of directors has independent audit, compensation, and nominating committees.</p>"
            "<h2>Security Ownership</h2><p>Beneficial ownership is disclosed for directors and named officers.</p>"
            "</body></html>"
        ),
    )

    payload = resolve_sec_proxy_filing("NVDA", "FY2025")

    assert payload.meta["status"] == "resolved"
    assert payload.evidence_records[0]["source_type"] == "sec_proxy_filing"
    assert "board of directors" in payload.evidence_records[0]["content"].lower()
    assert len(payload.evidence_records[0]["content"]) <= 6000


def test_annual_report_extractor_emits_sections_and_evidence_records():
    payload = AnnualReportSectionExtractor(html_text=MINIMAL_10K).extract(
        symbol="NVDA",
        period="FY2025",
        filing_url="https://www.sec.gov/Archives/test/nvda.htm",
        filing_evidence_id="sec_10k_nvda_fy2025",
    )
    assert payload["coverage"]["business"] is True
    assert payload["coverage"]["risk_factors"] is True
    assert payload["coverage"]["mda"] is True
    records = annual_sections_to_evidence_records(payload)
    assert any(record["source_type"] == "sec_10k_section" for record in records)
    assert any("Item 1A" in record["title"] for record in records)


def test_attach_annual_report_sections_merges_10k_evidence(monkeypatch, tmp_path):
    class FakePayload:
        def to_dict(self):
            return {
                "evidence_records": [
                    {
                        "evidence_id": "sec_10k_nvda_fy2025",
                        "sample_id": "sec_10k_nvda_fy2025",
                        "source_type": "sec_10k_filing",
                        "title": "NVDA FY2025 Form 10-K",
                        "source_url": "https://www.sec.gov/test",
                        "content": "Resolved filing",
                    }
                ],
                "sections_input": {
                    "html_text": MINIMAL_10K,
                    "filing_url": "https://www.sec.gov/test",
                    "filing_title": "NVDA FY2025 Form 10-K",
                    "filing_evidence_id": "sec_10k_nvda_fy2025",
                },
                "meta": {"status": "resolved", "filing_url": "https://www.sec.gov/test"},
            }

    monkeypatch.setattr("src.agents.multi_agent_orchestrator.resolve_sec_annual_filing", lambda **kwargs: FakePayload())
    monkeypatch.setattr("src.agents.multi_agent_orchestrator.resolve_sec_proxy_filing", lambda **kwargs: FakePayload())
    state = {
        "symbol": "NVDA",
        "period": "FY2025",
        "enable_remote_data": True,
        "allow_document_enrichment": True,
        "chart_output_dir": str(tmp_path / "charts"),
        "evidence_records": [],
        "analysis_artifacts": {},
    }
    attach_annual_report_sections_to_state(state)
    assert state["annual_report_sections"]["coverage"]["business"] is True
    assert state["analysis_artifacts"]["annual_report_section_count"] >= 3
    assert any(record["source_type"] == "sec_10k_section" for record in state["evidence_records"])


def test_dossier_prefers_annual_sections_and_filters_internal_metrics():
    extracted = AnnualReportSectionExtractor(html_text=MINIMAL_10K).extract(
        symbol="NVDA",
        period="FY2025",
        filing_url="https://www.sec.gov/test",
        filing_evidence_id="sec_10k_nvda_fy2025",
    )
    dossiers = SectionDossierBuilder().build(
        state={"symbol": "NVDA", "period": "FY2025", "claims": [], "annual_report_sections": extracted},
        claims=[],
        evidence_records=[],
        analysis_artifacts={"financial_metrics": {"metric_count": 17, "rejected_metric_count": 2, "revenue": 100.0}},
        bundles=[],
    )
    assert dossiers["business_overview"]["min_content_level"] == "full"
    assert dossiers["risks"]["supporting_evidence_ids"]
    summary_text = " ".join(dossiers["executive_summary"]["key_facts"])
    assert "metric_count" not in summary_text
    assert "revenue" in summary_text


def test_deterministic_tables_and_chart_labels_are_user_readable():
    blocks = render_all_deterministic_blocks(
        peer_rows=[{"company_name": "NVIDIA", "revenue_growth_pct": 85.2, "gross_margin_pct": 74.1}],
        valuation_model={"dcf_value": 1200.0, "pe_ratio": 30.0},
        sensitivity={"scenarios": [{"name": "Base", "fcf_growth": 0.05, "discount_rate": 0.1, "dcf_value": 1200}]},
        financial_metrics={"metric_count": 17, "revenue": 100.0},
    )
    assert "peer_compare" in blocks
    assert "valuation" in blocks
    assert "metric_count" not in blocks["financial_analysis"]
    charts = sanitize_chart_payloads(
        [
            {
                "chart_id": "evidence_source_mix",
                "title": "evidence_source_mix",
                "chart_js": {"labels": ["sec_10k_section", "sec_companyfacts", "unknown_raw_key"], "data": [2, 1, 1], "label": "指标"},
            }
        ]
    )
    labels = charts[0]["chart_js"]["labels"]
    assert "SEC 10-K 章节" in labels
    assert "SEC companyfacts" in labels
    assert all(not label.startswith("指标 ") for label in labels)
