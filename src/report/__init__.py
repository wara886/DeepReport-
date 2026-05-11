"""Report post-processing utilities."""

from src.report.citation_manager import (
    append_references_to_html,
    append_references_to_markdown,
    build_citation_artifacts,
    build_citations,
    render_citations_markdown,
)
from src.report.chart_generator import generate_report_charts
from src.report.chart_consistency import audit_chart_consistency
from src.report.compliance_disclosure import append_compliance_disclosures, append_compliance_disclosures_to_html
from src.report.html_report_generator import render_professional_html_report
from src.report.report_enhancer import attach_charts_to_html, attach_charts_to_markdown, polish_report_html

__all__ = [
    "append_references_to_html",
    "append_references_to_markdown",
    "append_compliance_disclosures",
    "append_compliance_disclosures_to_html",
    "attach_charts_to_html",
    "attach_charts_to_markdown",
    "audit_chart_consistency",
    "build_citation_artifacts",
    "build_citations",
    "generate_report_charts",
    "polish_report_html",
    "render_professional_html_report",
    "render_citations_markdown",
]
