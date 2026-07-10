"""Report post-processing utilities."""

from src.report.citation_manager import (
    append_references_to_html,
    append_references_to_markdown,
    build_citation_artifacts,
    build_citations,
    build_citations_from_map,
    render_citations_markdown,
)
from src.report.chart_generator import generate_report_charts
from src.report.chart_consistency import audit_chart_consistency
from src.report.compliance_disclosure import append_compliance_disclosures, append_compliance_disclosures_to_html
from src.report.docx_exporter import export_markdown_to_docx
from src.report.pdf_exporter import export_markdown_to_pdf
from src.report.html_report_generator import render_professional_html_report
from src.report.report_enhancer import attach_charts_to_html, attach_charts_to_markdown, inject_chart_references, polish_report_html
from src.report.section_contracts import (
    ReportSectionContracts,
    SectionEvidenceContract,
    SECTION_TITLES,
    ALL_SECTION_KEYS,
)
from src.report.contract_builder import build_report_section_contracts
from src.report.citation_binder import CitationBinder
from src.report.contract_renderer import render_section_from_contract, render_full_report_from_contracts

__all__ = [
    "append_references_to_html",
    "append_references_to_markdown",
    "append_compliance_disclosures",
    "append_compliance_disclosures_to_html",
    "attach_charts_to_html",
    "attach_charts_to_markdown",
    "audit_chart_consistency",
    "inject_chart_references",
    "build_citation_artifacts",
    "build_citations",
    "build_citations_from_map",
    "export_markdown_to_docx",
    "export_markdown_to_pdf",
    "generate_report_charts",
    "polish_report_html",
    "render_professional_html_report",
    "render_citations_markdown",
    "ReportSectionContracts",
    "SectionEvidenceContract",
    "SECTION_TITLES",
    "ALL_SECTION_KEYS",
    "build_report_section_contracts",
    "CitationBinder",
    "render_section_from_contract",
    "render_full_report_from_contracts",
]
