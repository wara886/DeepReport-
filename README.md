# Open DeepReport++ Core

本仓库当前保留的是金融多 Agent 系统的核心工程组件，不再把历史评测、竞赛实验和 shadow/grounded 产物混在主目录里。

目标不是继续做固定流水线脚本，而是借鉴 `DeepReport` 的多智能体骨架，接入我们自己的金融数据 API、模型 API 和工具/MCP 服务，重建一个真正的金融研究多 Agent：

```text
Planning Agent
  -> DeepResearcher Agent
  -> Browser Agent
  -> DeepAnalyze Agent
  -> FinalAnswer Agent
  -> Verifier/Critic Agent
```

## 当前保留内容

```text
configs/       配置
data/raw/      mock 原始样例数据
docs/          少量必要文档
scripts/       核心 smoke / ingestion / pipeline 脚本
src/app/       当前入口
src/agents/    Agent 基类、DeepSeek PlanningAgent、旧规则模块兼容层
src/models/    DeepSeek/OpenAI-compatible 模型适配层
src/tools/     本地金融工具注册表和 function/tool schema
src/search/    SearchManager，本地/远程搜索引擎聚合接口
src/data/      数据读取、标准化、manifest
src/features/  财务指标、趋势、风险、peer 特征
src/retrieval/ 本地 evidence store、BM25、reranker fallback
src/generation writer backend 抽象
src/schemas/   Evidence/Claim/Chart/Report/Task 数据契约
src/charts/    图表生成
src/templates/ Markdown/HTML/JSON 导出
src/training/  reranker/verifier/rewriter 轻量训练占位
tests/         核心组件测试
```

## 当前可运行链路

当前默认链仍然是核心组件验证用的 claim-first pipeline：

```text
src/app/main.py
  -> src/app/pipeline.py
  -> src/agents/orchestrator.py
  -> Planner
  -> Analyst
  -> optional Retrieval
  -> Writer
  -> Verifier
```

这条链路不是最终多 Agent 形态，只是保留现有数据/报告能力的基础闭环。

## DeepSeek 模型配置

当前已经预留 DeepSeek 作为金融多 Agent 的第一版底层模型后端。你只需要填：

```text
DeepReport_plus/.env
```

把第一行改成：

```bash
DEEPSEEK_API_KEY=你的 DeepSeek API Key
```

默认配置在：

```text
configs/model_backends.yaml
```

默认模型是 `deepseek-v4-flash`。如果要换成更强但可能更慢的模型，可以改 `.env` 里的：

```bash
DEEPSEEK_MODEL=deepseek-v4-pro
```

Agent 侧统一通过下面的适配层调用模型：

```text
src/models/model_adapter.py
```

填好 key 后可以先跑：

```bash
python scripts/run_deepseek_smoke.py
```

## Tavily Search 配置

Tavily 的 key 填在本地 secrets 文件：

```text
DeepReport_plus/.env
```

新增这一行：

```bash
TAVILY_API_KEY=你的 Tavily API Key
```

非密钥配置在：

```text
configs/data_sources.yaml
```

填好后可以先跑：

```bash
python scripts/run_tavily_smoke.py
```

生成第一版多 Agent 任务规划：

```bash
python scripts/run_planning_agent_smoke.py
```

运行完整多 Agent 协作 demo：

```bash
python scripts/run_multi_agent_demo.py --symbol AAPL --period 2025Q4 --execution-mode dynamic
```

启动本地可视化 UI：

```bash
python scripts/run_financial_agent_ui.py --host 127.0.0.1 --port 8787
```

浏览器打开：

```text
http://127.0.0.1:8787
```

推荐第一轮输入：

```text
研究任务: 分析 AAPL 2025Q4 财务表现，并生成带引用、图表和验证报告的研究报告
股票代码: AAPL
期间: 2025Q4
搜索/数据源: local_real_data,yahoo_finance,tavily,local_evidence
执行模式: dynamic
Fast profile: 勾选
```

点击 `生成多智能体研究报告` 后，正常会在 40-120 秒左右看到：

```text
Overview: agent_count=6, evidence_count≈6, claim_count>0, citation_count>0, chart_count=3, verification_passed=true
报告: 可阅读的中文 HTML/Markdown 研报，含图表和参考来源
图表: key_metrics_bar、claim_confidence_bar、evidence_source_mix
引用: evidence_id、来源、claim_ids、source_url
轨迹: Planning/Research/Browser/Analyze/FinalAnswer/Verifier 每步耗时
原始数据: 完整 JSON 调试 payload
```

启动本地 MCP-style 工具服务：

```bash
python scripts/run_mcp_server.py --host 127.0.0.1 --port 8765
```

检查工具清单：

```bash
curl http://127.0.0.1:8765/mcp/manifest
```

调用一个工具：

```bash
curl -X POST http://127.0.0.1:8765/mcp/rpc \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"fetch_yahoo_market_snapshot","arguments":{"symbol":"AAPL","period":"2025Q4"}}}'
```

正常会返回一个 `market_api` evidence，其中包含 Yahoo Finance 来源 URL、latest close、previous close、1mo price change 等字段。

如果已经申请 Serper，可以在 `.env` 填：

```bash
SERPER_API_KEY=你的 Serper API Key
```

然后把 UI 或 CLI 的搜索源改成：

```text
local_real_data,yahoo_finance,serper,tavily,local_evidence
```

如果要启用 BrowserAgent 的真实浏览器读取，需要安装 Playwright 和浏览器内核：

```bash
pip install '.[browser]'
python -m playwright install chromium
```

未安装 Playwright 时系统会自动回退到 Jina Reader，不会中断报告生成。

如果要启用本地小模型 RAG 组合，可以安装可选依赖：

```bash
pip install '.[local_rag]'
```

它会为 `local_evidence` 打开 `ChromaIndex + small embedding + small reranker` 这条路径；如果这些依赖缺失，系统会自动回退到内存向量召回和启发式 rerank。

可复用的本地模型预热脚本：

```bash
python scripts/setup_local_rag_models.py
```

默认配置在：

```text
configs/local_rag.yaml
```

如果要把无 key 的 Yahoo Finance 行情 API 也加入证据搜索，可以显式指定 engines：

```bash
python scripts/run_multi_agent_demo.py \
  --symbol AAPL \
  --period 2025Q4 \
  --execution-mode dynamic \
  --retrieval-ranking-mode hybrid_rerank \
  --engines local_real_data,yahoo_finance,tavily,local_evidence
```

更快的联网 demo：

```bash
python scripts/run_multi_agent_demo.py --symbol AAPL --period 2025Q4 --execution-mode dynamic --fast
```

`--fast` 会减少搜索结果和传给模型的上下文，并跳过 BrowserAgent 的可选 LLM 摘要抽取；适合反复调试。
`task_trace.jsonl` 会记录每个 Agent 的 `duration_sec`，`run_summary.json` 会记录 `total_duration_sec`。
当前 multi-agent 主链默认会对 `local_evidence` 使用 `hybrid_rerank`，也就是 `BM25 + vector recall + rerank/fallback rerank`；如果想退回老行为，可以显式传 `--retrieval-ranking-mode bm25`。

输出会落在：

```text
data/outputs/multi_agent/
data/reports/multi_agent/
```

其中 `data/outputs/multi_agent/search_meta.json` 会记录本轮 ResearchAgent 调用了哪些搜索源，例如 `local_real_data`、`tavily`、`local_evidence`。
默认动态模式还会让 BrowserAgent 对部分 Tavily URL 调用 Jina Reader（`https://r.jina.ai/`）抽取网页正文；`--fast` 会跳过这一步以节省时间。
最终报告前会经过 CitationManager 整理，额外输出：

```text
data/outputs/multi_agent/citations.json
data/outputs/multi_agent/citations.md
data/outputs/multi_agent/charts.json
data/outputs/multi_agent/mcp_manifest.json
data/outputs/multi_agent/revision_history.json
```

`citations.json` 会把 `evidence_id`、来源 URL、标题、证据类型、支持的 `claim_id` 统一成引用表；`report.md` 和 `report.html` 末尾会自动追加中文 `参考来源`。
`charts.json` 会记录本轮由 claims/evidence 生成的图表，图片位于 `data/outputs/multi_agent/charts/`；`mcp_manifest.json` 会导出当前可用的本地金融工具清单和参数 schema。
`revision_history.json` 会记录 `VerifierAgent -> FinalAnswerAgent` 的自动返工轮次、返工指令和返工后是否通过。
`report.html` 现在由 `HTMLReportGenerator` 生成，并内嵌 Chart.js 交互图表；如果浏览器不能访问 Chart.js CDN，Markdown 报告和 PNG 图表仍可正常查看。

`dynamic` 是默认模式：它会读取 `PlanningAgent` 生成的 `task_plan.json`，按依赖关系动态分发给 `DeepResearcherAgent`、`BrowserAgent`、`DeepAnalyzeAgent`、`FinalAnswerAgent`、`VerifierAgent`。如果要对比上一版固定链路，可以用：

```bash
python scripts/run_multi_agent_demo.py --execution-mode static
```

## 快速运行

```bash
python scripts/run_stage2_data_smoke.py
python scripts/run_stage3_feature_smoke.py
python scripts/run_stage4_pipeline_smoke.py
python scripts/run_stage5_chart_smoke.py
python scripts/run_stage10_export_smoke.py
```

真实本地样例数据闭环：

```bash
python scripts/run_stage11a_real_data_smoke.py
```

## 改造说明

核心判断和下一步改造计划见：

```text
FINANCIAL_AGENT_PROJECT_SUMMARY.md
```

更适合放到 GitHub 仓库首页后继续阅读的详细说明见：

```text
docs/financial_multi_agent_detailed_guide.md
```

下一阶段只聚焦公司/个股研报深度、多模态一致性、权威数据源、严谨估值建模和 Agent 自主补证闭环，具体落地方案见：

```text
docs/company_stock_report_depth_plan.md
```

DeepReport 原始骨架参考：

```text
/Users/yuan_dian/Downloads/deep_learn/DeepReport_award2_ref
```

尤其参考：

```text
docs/deepreport_reference_architecture.md
src/agents/base_agent.py
src/agents/planning_agent.py
src/agents/deep_researcher_agent.py
src/agents/browser_agent.py
src/agents/deep_analyze_agent.py
src/agents/final_answer_agent.py
src/search/search_manager.py
src/utils/model_adapter.py
src/utils/mcp_manager.py
```
