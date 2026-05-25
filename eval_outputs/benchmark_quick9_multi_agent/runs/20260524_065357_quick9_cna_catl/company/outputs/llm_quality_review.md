# LLM/Codex Quality Review

- llm_review_pass: `False`
- total_score: `1.0`
- model_status: `completed`

## Verdict

Fail - 致命问题：大量暂无结论，期间错配

## Dimension Scores

- professional_report_likeness: `1.0`
- investment_insight: `1.0`
- fact_period_consistency: `1.0`
- company_report_requirement_fit: `1.0`
- chart_usefulness: `1.0`
- language_quality: `1.0`

## Issues

- **fatal / content_hollowness**: 报告在同行对比、估值分析、投资结论等部分大量出现'缺乏数据'、'无法判断'等表述，缺乏实质分析和投资洞察，不符合专业研报要求。
- **fatal / period_mismatch**: 报告虽以2026Q1为目标期间，但引用了2025年年报证据（如evidence_id: 300750_2026Q1_cninfo_ff323defb4），存在期间错配风险。
- **blocker / generalization**: 泛化质量检查未通过：pre_write_critic_passed失败。
- **warning / symbol_consistency**: 目标符号300750.SZ未在报告claims或正文中明确提及，存在符号一致性警告。
- **warning / requirement_gap**: 公司研报赛题要求包括同行对比、估值/敏感性、投资建议，本报告均缺失或仅说明缺少数据。
