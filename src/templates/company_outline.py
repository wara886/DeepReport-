"""Company report outline template utilities."""

from __future__ import annotations

from typing import List


def default_company_outline() -> List[dict]:
    return [
        {"section_name": "executive_summary", "section_title": "执行摘要"},
        {"section_name": "business_overview", "section_title": "业务概览"},
        {"section_name": "ownership_governance", "section_title": "股权结构与公司治理"},
        {"section_name": "strategy_business", "section_title": "战略与主营业务"},
        {"section_name": "financial_statements", "section_title": "三表摘要"},
        {"section_name": "financial_analysis", "section_title": "财务分析"},
        {"section_name": "peer_compare", "section_title": "同行对比"},
        {"section_name": "valuation", "section_title": "估值观察"},
        {"section_name": "valuation_sensitivity", "section_title": "估值敏感性"},
        {"section_name": "risks", "section_title": "风险评估"},
        {"section_name": "conclusion", "section_title": "投资结论"},
    ]
