# P0.5-B Request Understanding E2E Acceptance

## 目标

验证自然语言研究请求可以从：

```text
natural_language_query -> RequestUnderstandingAgent -> ResearchRequest -> Planner -> 主 workflow -> report artifacts
```

完整进入报告生成链路，并且在无附件情况下可运行。

## 实际运行命令

新增验收脚本：

```text
scripts/run_request_understanding_e2e_acceptance.py
```

执行命令：

```text
cd /Users/yuan_dian/AI_project/DeepReport_plus && PYTHONPATH=. python scripts/run_request_understanding_e2e_acceptance.py
```

输出目录：

```text
eval_outputs/request_understanding_e2e_acceptance/
```

汇总文件：

```text
eval_outputs/request_understanding_e2e_acceptance/acceptance_results.json
eval_outputs/request_understanding_e2e_acceptance/acceptance_results.jsonl
```

## Case 1：英伟达

Query：

```text
分析英伟达最近一个季度的经营情况，判断当前估值是否偏贵，并给出主要风险。
```

ResearchRequest 摘要：

```json
{
  "company_name": "NVIDIA Corporation",
  "symbol": "NVDA",
  "market": "US",
  "confidence": 0.795,
  "report_type": "company_research",
  "period_type": "latest_quarter",
  "focus_areas": ["估值", "经营情况", "主要风险"],
  "language": "zh",
  "format": "markdown_html_json",
  "depth": "standard",
  "attachments_optional": true,
  "clarification_needed": false
}
```

产物路径：

- RequestUnderstanding artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_nvda_latest_quarter/outputs/request_understanding.json`
- ResearchRequest artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_nvda_latest_quarter/outputs/request_understanding.json`
- Planner artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_nvda_latest_quarter/outputs/task_plan.json`
- Report Markdown: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_nvda_latest_quarter/reports/report.md`
- Report JSON: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_nvda_latest_quarter/reports/report.json`
- Verification: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_nvda_latest_quarter/outputs/verification_report.json`

验收结果：

- natural_language_query 进入 RequestUnderstandingAgent：是
- request_understanding / research_request artifact：是
- 进入 Planner / 后续 workflow：是
- 最终产出 report：是
- 无附件情况下可运行：是
- 保留结构化 ResearchRequest：是
- status：`completed`
- duration_sec：116.1371

## Case 2：贵州茅台

Query：

```text
帮我生成一份贵州茅台的最新深度金融研报，重点关注盈利质量、估值、行业风险和同业对比。
```

ResearchRequest 摘要：

```json
{
  "company_name": "Kweichow Moutai Co., Ltd.",
  "symbol": "600519.SS",
  "market": "CN-A",
  "confidence": 0.797,
  "report_type": "deep_company_research",
  "period_type": "latest_quarter",
  "focus_areas": ["盈利质量", "估值", "行业风险", "同业对比", "主要风险"],
  "language": "zh",
  "format": "markdown_html_json",
  "depth": "deep",
  "attachments_optional": true,
  "clarification_needed": false
}
```

产物路径：

- RequestUnderstanding artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_moutai_deep_report/outputs/request_understanding.json`
- ResearchRequest artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_moutai_deep_report/outputs/request_understanding.json`
- Planner artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_moutai_deep_report/outputs/task_plan.json`
- Report Markdown: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_moutai_deep_report/reports/report.md`
- Report JSON: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_moutai_deep_report/reports/report.json`
- Verification: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_moutai_deep_report/outputs/verification_report.json`

验收结果：

- natural_language_query 进入 RequestUnderstandingAgent：是
- request_understanding / research_request artifact：是
- 进入 Planner / 后续 workflow：是
- 最终产出 report：是
- 无附件情况下可运行：是
- 保留结构化 ResearchRequest：是
- status：`completed`
- duration_sec：118.3182

## Case 3：Meta

Query：

```text
做一份 Meta 最新财报后的公司研究，重点分析广告业务、资本开支和估值压力。
```

ResearchRequest 摘要：

```json
{
  "company_name": "Meta Platforms, Inc.",
  "symbol": "META",
  "market": "US",
  "confidence": 1.0,
  "report_type": "valuation_analysis",
  "period_type": "latest_quarter",
  "focus_areas": ["估值"],
  "language": "zh",
  "format": "markdown_html_json",
  "depth": "standard",
  "attachments_optional": true,
  "clarification_needed": false
}
```

产物路径：

- RequestUnderstanding artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_meta_post_earnings/outputs/request_understanding.json`
- ResearchRequest artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_meta_post_earnings/outputs/request_understanding.json`
- Planner artifact: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_meta_post_earnings/outputs/task_plan.json`
- Report Markdown: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_meta_post_earnings/reports/report.md`
- Report JSON: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_meta_post_earnings/reports/report.json`
- Verification: `eval_outputs/request_understanding_e2e_acceptance/ru_e2e_meta_post_earnings/outputs/verification_report.json`

验收结果：

- natural_language_query 进入 RequestUnderstandingAgent：是
- request_understanding / research_request artifact：是
- 进入 Planner / 后续 workflow：是
- 最终产出 report：是
- 无附件情况下可运行：是
- 保留结构化 ResearchRequest：是
- status：`completed`
- duration_sec：118.2724

注意：该 case 的流程验收通过，但解析质量存在偏差：用户说“公司研究”，实际 `report_type` 解析为 `valuation_analysis`，且 focus_areas 只保留了“估值”，未完整保留“广告业务 / 资本开支 / 估值压力”。这不是 E2E 路由失败，但应作为 RequestUnderstanding 后续质量改进项。

## 总体验收结论

三条无歧义自然语言请求均：

1. 进入 `RequestUnderstandingAgent`；
2. 生成 `request_understanding.json` / `research_request` artifact；
3. 进入 Planner；
4. 完成后续动态 workflow；
5. 生成 Markdown / HTML / JSON report；
6. 在无附件情况下运行；
7. 保留结构化 ResearchRequest。

失败情况：

- 无流程失败；
- Meta case 存在 intent/focus parsing 质量偏差，需要后续优化解析规则。
