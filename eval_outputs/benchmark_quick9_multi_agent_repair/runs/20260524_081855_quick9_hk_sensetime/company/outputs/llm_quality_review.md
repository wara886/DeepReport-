# LLM/Codex Quality Review

- llm_review_pass: `False`
- total_score: `0.2`
- model_status: `completed`

## Verdict

fail

## Dimension Scores

- professional_report_likeness: `0.1`
- investment_insight: `0.05`
- fact_period_consistency: `0.3`
- company_report_requirement_fit: `0.2`
- chart_usefulness: `0.2`
- language_quality: `0.4`

## Issues

- **fatal / llm_review**: 报告内容空洞，大量章节使用'数据缺口说明'，无实际投资分析，大量引用不存在的证据，不符合研报要求
- **blocker / llm_review**: 缺少利润表摘要
- **blocker / llm_review**: 缺少资产负债表摘要
- **blocker / llm_review**: 缺少现金流量表摘要
- **blocker / llm_review**: 质量门禁未通过：has_three_table_summary
- **blocker / llm_review**: 所有8条声明引用了不存在的证据ID unstructured_record_0
- **warning / llm_review**: 权威/一手来源占比偏低：0.00
- **warning / llm_review**: 图表未明显服务于财务分析
