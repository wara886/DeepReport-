"""Company report outline template utilities."""

from __future__ import annotations

from typing import List


def default_company_outline() -> List[dict]:
    """中证协对齐的公司研究报告章节结构（含一级编号）。"""
    return [
        {"section_name": "executive_summary",    "section_title": "一、投资摘要"},
        {"section_name": "business_overview",    "section_title": "二、公司概况"},
        {"section_name": "ownership_governance", "section_title": "三、股权结构与公司治理"},
        {"section_name": "strategy_business",    "section_title": "四、主营业务与战略"},
        {"section_name": "financial_statements", "section_title": "五、财务报表摘要"},
        {"section_name": "financial_analysis",   "section_title": "六、财务分析"},
        {"section_name": "peer_compare",         "section_title": "七、同行业对比"},
        {"section_name": "valuation",            "section_title": "八、估值分析"},
        {"section_name": "valuation_sensitivity","section_title": "九、估值敏感性分析"},
        {"section_name": "risks",                "section_title": "十、风险因素"},
        {"section_name": "conclusion",           "section_title": "十一、投资建议"},
    ]
