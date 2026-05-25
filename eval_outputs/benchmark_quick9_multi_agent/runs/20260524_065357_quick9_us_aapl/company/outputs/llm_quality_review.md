# LLM/Codex Quality Review

- llm_review_pass: `False`
- total_score: `0.42`
- model_status: `completed`

## Verdict

不合格，存在大量数据缺口与事实错误

## Dimension Scores

- professional_report_likeness: `0.6`
- investment_insight: `0.2`
- fact_period_consistency: `0.3`
- company_report_requirement_fit: `0.5`
- chart_usefulness: `0.3`
- language_quality: `0.6`

## Issues

- **fatal / evidence**: 多个关键财务指标（毛利率、调整净利润、总负债、权益）缺乏证据支持，存在事实错误。
- **fatal / insight**: 报告大量篇幅为'数据缺口说明'，缺乏实质性投资洞察与原创分析，投资结论仅为'中性观察'。
- **warning / generalization**: 存在目标股票符号不匹配（提及FRED），且同行对比与估值敏感性部分完全缺失量化分析。
- **warning / chart**: 图表（结论置信度、证据来源结构）为元数据展示，无助于理解公司基本面。
