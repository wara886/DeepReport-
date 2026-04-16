"""Stage 4 planner with fixed section templates."""

from __future__ import annotations

from typing import List


class Planner:
    """Generate a fixed claim-first report plan."""

    DEFAULT_SECTIONS = [
        ("executive_summary", "Executive Summary"),
        ("business_overview", "Business Overview"),
        ("financial_analysis", "Financial Analysis"),
        ("valuation", "Valuation"),
        ("risks", "Risk Assessment"),
        ("conclusion", "Conclusion"),
    ]

    def build_plan(self) -> List[dict]:
        return [
            {"section_name": section_name, "section_title": section_title}
            for section_name, section_title in self.DEFAULT_SECTIONS
        ]

