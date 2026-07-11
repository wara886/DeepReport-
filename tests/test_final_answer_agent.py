"""Tests for FinalAnswerAgent: enforce_section_depth, remove_broken_or_half_sentences,
remove_debug_leakage, remove_internal_ids, remove_template_phrases."""

from src.agents.final_answer_agent import (
    auto_rewrite_core_sections,
    enforce_section_depth,
    remove_broken_or_half_sentences,
    remove_debug_leakage,
    remove_internal_ids,
    remove_template_phrases,
)


def test_enforce_section_depth_fills_thin_sections():
    """enforce_section_depth fills sections below threshold with suggested_paragraphs."""
    markdown = """# 测试报告

## 执行摘要
短。

## 业务概览
也很短。

## 财务分析
这节内容也很少。

## 风险评估
风险内容不足。

## 投资结论
结论太少。
"""
    section_dossiers = {
        "executive_summary": {
            "section_title": "执行摘要",
            "min_content_level": "brief",
            "suggested_paragraphs": ["这是执行摘要的建议段落。"],
            "key_facts": ["fact1"],
        },
        "business_overview": {
            "section_title": "业务概览",
            "min_content_level": "full",
            "suggested_paragraphs": ["这是业务概览的建议段落，包含公司描述和行业分析。"],
            "key_facts": [],
        },
        "financial_analysis": {
            "section_title": "财务分析",
            "min_content_level": "full",
            "suggested_paragraphs": ["这是财务分析的建议段落，包含收入、利润、现金流等指标分析。"],
            "key_facts": [],
        },
        "risks": {
            "section_title": "风险评估",
            "min_content_level": "full",
            "suggested_paragraphs": ["这是风险评估的建议段落，涵盖行业竞争、利润率压力等风险。"],
            "key_facts": [],
        },
        "conclusion": {
            "section_title": "投资结论",
            "min_content_level": "full",
            "suggested_paragraphs": ["这是投资结论的建议段落，包含财务质量、估值判断和风险提示。"],
            "key_facts": [],
        },
    }
    result = enforce_section_depth(markdown, section_dossiers)
    # business_overview should be replaced by suggested_paragraphs since it's below threshold
    assert "这是业务概览的建议段落" in result
    assert "这是财务分析的建议段落" in result
    assert "这是投资结论的建议段落" in result


def test_enforce_section_depth_skips_data_gap():
    """Sections with data_gap min_content_level are not filled when short."""
    markdown = """# 测试报告

## 业务概览
内容很少。
"""
    section_dossiers = {
        "business_overview": {
            "section_title": "业务概览",
            "min_content_level": "data_gap",
            "suggested_paragraphs": ["公开资料不足以展开"],
            "key_facts": [],
        },
    }
    result = enforce_section_depth(markdown, section_dossiers)
    # Should NOT be replaced because min_content_level is data_gap
    assert "内容很少" in result


def test_auto_rewrite_core_sections_repairs_thin_and_truncated_sections():
    markdown = """# 测试报告

## 执行摘要
短。

## 估值观察
本报告分别披露相对估值与

## 风险评估
风险较多。

## 投资结论
观察。
"""
    claims = [
        {
            "section_name": "valuation",
            "claim_text": "估值需要同时参考收入增速、毛利率和现金流质量。",
            "evidence_ids": ["ev_val"],
        },
        {
            "section_name": "risks",
            "claim_text": "需求放缓和竞争加剧可能压缩利润率。",
            "evidence_ids": ["ev_risk"],
        },
        {
            "section_name": "conclusion",
            "claim_text": "基于估值约束和风险边界，维持审慎观察。",
            "evidence_ids": ["ev_conclusion"],
        },
    ]
    result = auto_rewrite_core_sections(
        markdown,
        claims=claims,
        evidence_records=[
            {
                "evidence_id": "ev_sec",
                "title": "FY2024 Form 10-K",
                "source_type": "sec_edgar",
                "period": "FY2024",
            }
        ],
        financial_metrics={"metrics": [{"metric_name": "收入", "value": 100, "unit": "亿元", "period": "FY2024", "source_type": "official_filing"}]},
        quality_remediation_plan={"quality_feedback_used": True, "failed_sections": ["valuation", "risk", "investment_conclusion", "executive_summary"]},
    )

    assert "本报告分别披露相对估值与" not in result
    assert "估值观察以已披露财务和市场输入为边界" in result
    assert "风险评估围绕证据池" in result
    assert "投资结论维持审慎观察" in result
    assert "执行摘要不直接给出强买卖结论" in result
    assert "[ev_val]" in result or "[ev_sec]" in result
    assert "收入为100亿元" in result


def test_remove_broken_half_sentences():
    """remove_broken_or_half_sentences removes empty template patterns."""
    markdown = """## 业务概览

TSLA 需关注相关的。
公司具备完善的公司治理结构。
持续深耕核心业务领域。
巩固核心竞争力。
作为上市公司。
包括：收入、利润、现金流等。
"""
    result = remove_broken_or_half_sentences(markdown)
    # "相关的。" should be removed
    assert "相关的" not in result
    # "具备完善的公司治理结构" should be replaced
    assert "具备完善的公司治理结构" not in result
    # "包括：" should be removed
    assert "包括：" not in result
    # "持续深耕" should be removed
    assert "持续深耕" not in result
    # "巩固核心竞争力" should be removed
    assert "巩固核心竞争力" not in result
    # Normal text should survive
    assert "## 业务概览" in result


def test_remove_half_sentences_preserves_good_text():
    """remove_broken_or_half_sentences preserves substantive prose."""
    markdown = """## 执行摘要

本期公司收入同比增长 24%，毛利率提升至 52.1%，经营现金流改善明显。
估值基于 DCF 和 P/E 方法，合理估值区间为 150-180。

## 财务分析

收入 35.4 亿美元，净利润 9.7 亿美元，自由现金流 8.2 亿美元。
"""
    result = remove_broken_or_half_sentences(markdown)
    assert "同比增长 24%" in result
    assert "DCF" in result
    assert "自由现金流" in result


def test_remove_debug_leakage_strips_internal_fields():
    """remove_debug_leakage removes debug/tracking field names."""
    markdown = """## 执行摘要

本报告基于 metric_count=42 和 rejected_metric_count=5 进行分析。
statement_line_item_count=10 个科目。
Risk-related claim evidence count 为 8。
supported metrics 包括收入。

## 财务分析

正常正文内容。
"""
    result = remove_debug_leakage(markdown)
    assert "metric_count" not in result
    assert "rejected_metric_count" not in result
    assert "statement_line_item_count" not in result
    assert "Risk-related claim evidence count" not in result
    assert "supported metrics" not in result
    assert "正常正文内容" in result


def test_remove_debug_leakage_strips_cl_pattern():
    """remove_debug_leakage strips cl_XXXX patterns."""
    markdown = "cl_0001 shows data and cl_0042 also appears."
    result = remove_debug_leakage(markdown)
    assert "cl_0001" not in result
    assert "cl_0042" not in result


def test_remove_internal_ids_strips_claim_id_labels():
    """remove_internal_ids strips cl_XXXX:metric_key patterns."""
    markdown = "Revenue from cl_0001:revenue_billion grew 24%."
    result = remove_internal_ids(markdown)
    assert "cl_0001:revenue_billion" not in result
    assert "revenue_billion" not in result
    assert "Revenue from" in result


def test_remove_internal_ids_preserves_citation_brackets():
    """remove_internal_ids should not strip evidence IDs inside citation brackets."""
    markdown = "正文引用 [ev_001] 来源，正文有 ev_001 泄漏。"
    result = remove_internal_ids(markdown)
    assert "[ev_001]" in result  # citation brackets preserved
    assert "正文有" in result


def test_remove_template_phrases_strips_buzzwords():
    """remove_template_phrases removes hollow buzzword phrases."""
    markdown = """## 业务概览

公司持续深耕主营业务，巩固核心竞争力。
拥有长期发展空间。

## 财务分析

正常内容。
"""
    result = remove_template_phrases(markdown)
    assert "持续深耕" not in result
    assert "巩固核心竞争力" not in result
    assert "长期发展空间" not in result
    assert "正常内容" in result


def test_remove_template_phrases_preserves_good_text():
    """remove_template_phrases preserves normal Chinese prose."""
    markdown = "公司收入同比增长 24%，毛利率 52%。"
    result = remove_template_phrases(markdown)
    assert "收入同比增长" in result
    assert "毛利率" in result
