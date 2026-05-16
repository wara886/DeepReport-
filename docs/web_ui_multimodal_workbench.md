# Web UI 多模态研究工作台修复记录

更新时间：2026-05-16

## 本轮修复

- Web UI 从“最近结果查看器 + 弱聊天框”调整为对话优先的研究工作台：研究助手移动到左侧顶部，默认允许 Chat 在确认参数后启动研报。
- `/api/latest` 现在返回 `claims/evidence/tables/financial_metrics/pdf_manifest/pdf_sections/company_profile_extracted`，并带上当前 `output_dir` 与 `report_dir`，前端会把最近报告的 `symbol/period/research_topic/search_engines` 同步回表单。
- `/api/run` 与 `/api/chat` 增加 `enable_remote_data` 和 `data_source_config_path` 透传。实时源打开后，A 股默认使用 `cninfo_announcements/exchange_announcements/eastmoney_financials/yahoo_finance/eastmoney`，美股默认使用 `sec_edgar/yahoo_finance/independent_macro`。
- 增加 period guard：未结束季度会被拦截。例如在 2026-05-16 请求 `2026Q2` 会提示季度尚未结束，并建议 `2026Q1` 或 `2025Q4`。
- UI 新增多模态 tabs：三表表格、PDF 章节、公司画像、Claims。右上角状态不再只显示“读取最近一次输出”，而是明确输出目录、报告目录、标的、期间、模式和实时源状态。
- PDF section artifacts 现在会在 browser 阶段后提前转换为 `pdf_section` evidence records，并在 `DeepAnalyzeAgent` 中派生主营业务、管理层讨论、股东治理、风险提示、财务报表相关 claims。

## 仍需后续增强

- `evidence_grounded_rewrite.json` 仍主要服务 competition baseline 桥接，尚未作为默认 FinalAnswerAgent 输入。
- PDF section 抽取仍依赖 PyMuPDF；缺依赖或下载失败时只记录 manifest failure，不中断主链。
- Chat 目前能路由并启动任务，但更细的多轮参数确认、自然语言自动改写表单、任务排队和运行中流式反馈仍是后续产品化项。

## 验证

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_web_ui.py tests/test_data_enrichment.py
python -m py_compile src/app/web_ui.py src/app/agent_chat.py src/agents/multi_agent_orchestrator.py src/agents/deep_analyze_agent.py tests/test_web_ui.py tests/test_data_enrichment.py
```
