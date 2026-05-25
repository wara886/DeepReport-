# LLM/Codex Quality Review

- llm_review_pass: `False`
- total_score: `1.0`
- model_status: `completed`

## Verdict

需大幅修改

## Dimension Scores

- professional_report_likeness: `1.0`
- investment_insight: `1.0`
- fact_period_consistency: `1.0`
- company_report_requirement_fit: `1.0`
- chart_usefulness: `1.0`
- language_quality: `1.0`

## Issues

- **fatal / llm_review**: 存在致命问题：大量章节出现'数据缺口说明'或'暂无结论'，内容空洞，缺乏实质性分析。
- **blocker / llm_review**: 缺少投资洞察和原创分析，报告仅复述财务数据，未提供趋势、驱动因素或竞争优劣解读。
- **warning / llm_review**: 未满足公司/个股赛题要求：同行对比直接声明数据缺口；估值部分显示'Valuation availability: False'，未提供有效估值；投资结论为'审慎观察'而非明确建议。
- **warning / llm_review**: PDF片段提取不完整，如'54 (7.1) 稀释每股收益...'疑似乱码或格式错误，影响可读性。
- **warning / llm_review**: 标的符号在报告中未明确使用，存在警告指出的符号混淆问题。
- **warning / llm_review**: 图表（结论置信度、证据来源结构）与投资分析关联性弱，对研报核心论述帮助有限。
