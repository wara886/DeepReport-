# LLM/Codex Quality Review

- llm_review_pass: `False`
- total_score: `0.34`
- model_status: `completed`

## Verdict

Fail - 报告严重内容空洞，大量暂无结论，不满足公司研报基本要求

## Dimension Scores

- professional_report_likeness: `0.2`
- investment_insight: `0.1`
- fact_period_consistency: `0.6`
- company_report_requirement_fit: `0.15`
- chart_usefulness: `0.5`
- language_quality: `0.5`

## Issues

- **fatal / llm_review**: fatal: 内容空洞 / 大量暂无结论 - 几乎所有章节均以'数据缺口说明'开头，缺乏实际分析和结论
- **blocker / llm_review**: blocker: 缺少三表摘要（利润表、资产负债表、现金流量表），不满足公司研报核心要求
- **blocker / llm_review**: blocker: 无投资洞察和原创分析，仅为框架性描述及证据缺口说明
- **blocker / llm_review**: blocker: 同行对比仅为框架，无具体可比公司数据和指标对比
- **blocker / llm_review**: blocker: 估值不可用，无任何估值模型或目标价，敏感性分析也仅为变量方向说明
- **warning / llm_review**: warning: 图表（关键指标、结论置信度、证据来源结构）与报告内容关联度低，对分析助益有限
- **warning / llm_review**: warning: 语言虽流畅但内容重复，大量使用'边界说明'等套话，可读性较差
