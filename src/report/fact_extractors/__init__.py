"""Fact extraction utilities: encoding repair, section detection, structured fact extraction."""

from src.report.fact_extractors.pdf_encoding import (
    auto_repair_mojibake,
    batch_auto_repair,
    clean_mojibake,
    detect_mojibake,
    has_mojibake,
    repair_mojibake,
)

from src.report.fact_extractors.pdf_section_detector import (
    detect_sections,
    detect_section_boundaries,
    detect_report_type,
    get_heading_patterns,
    split_by_heading,
)

__all__ = [
    "auto_repair_mojibake",
    "batch_auto_repair",
    "clean_mojibake",
    "detect_mojibake",
    "has_mojibake",
    "repair_mojibake",
    "detect_sections",
    "detect_section_boundaries",
    "detect_report_type",
    "get_heading_patterns",
    "split_by_heading",
]
