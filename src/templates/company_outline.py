"""Company report outline template utilities."""

from __future__ import annotations

from typing import List


def default_company_outline() -> List[dict]:
    return [
        {"section_name": "executive_summary", "section_title": "Executive Summary"},
        {"section_name": "business_overview", "section_title": "Business Overview"},
        {"section_name": "financial_analysis", "section_title": "Financial Analysis"},
        {"section_name": "valuation", "section_title": "Valuation"},
        {"section_name": "risks", "section_title": "Risk Assessment"},
        {"section_name": "conclusion", "section_title": "Conclusion"},
    ]

