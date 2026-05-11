# DeepReport_plus 清理后现状与金融多 Agent 改造方向

## 1. 结论先说

2026-05-11 这轮已经把“下一步要升级”的几块能力真正接到主链里了：

```text
可控 context packer
Chroma-style 本地向量检索（缺依赖时自动 fallback）
small reranker 适配器（cross-encoder 优先，启发式保底）
Verifier -> FinalAnswer 一次自动返工闭环
```

现在 `dynamic` multi-agent 路径里，`local_evidence` 默认会走：

```text
BM25 + vector recall + hybrid_rerank
```

如果首轮验证没过，会额外生成：

```text
data/outputs/multi_agent/revision_history.json
```

本地小模型下载/预热也补了统一入口：

```bash
python scripts/setup_local_rag_models.py
```

你刚才的判断是对的：清理前的 `DeepReport_plus` 默认主链不是严格意义上的金融多 Agent，而是一个 `Planner -> Analyst -> Writer -> Verifier` 的规则化研报流水线。

当前已经开始从“规则流水线”升级到“真实多 Agent 协作”：

```text
DeepSeek shared model
  -> PlanningAgent
  -> DeepResearcherAgent
  -> BrowserAgent
  -> DeepAnalyzeAgent
  -> FinalAnswerAgent
  -> VerifierAgent
```

已可运行：

```bash
python scripts/run_multi_agent_demo.py --symbol AAPL --period 2025Q4
```

本轮 demo 输出：

```text
data/outputs/multi_agent/task_plan.json
data/outputs/multi_agent/task_trace.jsonl
data/outputs/multi_agent/search_meta.json
data/outputs/multi_agent/evidence.json
data/outputs/multi_agent/claims.json
data/outputs/multi_agent/citations.json
data/outputs/multi_agent/citations.md
data/outputs/multi_agent/charts.json
data/outputs/multi_agent/mcp_manifest.json
data/outputs/multi_agent/verification_report.json
data/reports/multi_agent/report.md
data/reports/multi_agent/report.html
data/reports/multi_agent/report.json
```

最新一次运行结果：

```text
model: deepseek-v4-flash
execution_mode: dynamic
agent_count: 6
trace_count: 6
evidence_count: 6
claim_count: 3
citation_count: 6
chart_count: 3
verification_passed: true
total_duration_sec: 64.479
```

调试时可用 fast 模式：

```bash
python scripts/run_multi_agent_demo.py --symbol AAPL --period 2025Q4 --execution-mode dynamic --fast
```

`--fast` 会把搜索/证据上下文收小，并跳过 BrowserAgent 的可选 LLM key point 抽取，适合频繁测试。
每条 `task_trace.jsonl` 现在会记录 `duration_sec`，`run_summary.json` 会记录 `total_duration_sec`，便于继续定位慢点。

Tavily 接入后，`DeepResearcherAgent` 默认搜索源已经变成：

```text
local_real_data + tavily + local_evidence
```

最近一次 Tavily 联网 demo 产出 `web_search` 证据，包括 Yahoo Finance、Business Wire、Apple Newsroom、CNBC 等来源，并通过 `VerifierAgent`。

BrowserAgent 也已接入 Jina Reader 第一版网页正文抽取：

```text
Tavily URL -> https://r.jina.ai/<url> -> LLM-friendly text -> evidence content
```

默认动态模式会尝试读取少量网页正文；`--fast` 会跳过 Reader，保留 snippet 级证据以节省时间。

现在 FinalAnswerAgent 和 VerifierAgent 之间已经加入 `CitationManager` 后处理层：

```text
evidence_records + claims + draft report
  -> citations.json / citations.md
  -> report.md/report.html 追加中文参考来源
  -> VerifierAgent
```

它负责把 `evidence_id`、标题、来源 URL、来源类型、发布时间、支持的 `claim_id` 统一整理成引用表；Verifier 验证的是已经追加中文参考来源的最终报告。

本轮继续补上三块完整度：

```text
ToolRegistry -> MCPManager -> mcp_manifest.json
Yahoo Finance chart API -> fetch_yahoo_market_snapshot / yahoo_finance search engine
claims + evidence -> chart images / charts.json -> report.md/report.html
```

后续已继续补齐四个接近二等奖方案的模块：

```text
SerperEngine -> Google/Serper 搜索 API 封装，可加入 SearchManager
Playwright BrowserAgent -> 可选真实浏览器正文抽取，失败自动回退 Jina Reader
MCP HTTP/JSON-RPC -> tools/list 使用 inputSchema，tools/call 返回 MCP-style content
HTMLReportGenerator -> 专业中文 HTML 报告 + Chart.js 交互图表
```

Yahoo Finance 是无 key 的行情快照工具，默认不强塞进每次搜索；需要时通过：

```bash
python scripts/run_multi_agent_demo.py --symbol AAPL --period 2025Q4 --execution-mode dynamic --engines local_real_data,yahoo_finance,tavily,local_evidence
```

开启后，`search_meta.json` 会记录 `yahoo_finance`，报告的 evidence/citation 里会出现 `market_api` 来源。

当前还新增了两个本地服务入口：

```bash
python scripts/run_financial_agent_ui.py --host 127.0.0.1 --port 8787
python scripts/run_mcp_server.py --host 127.0.0.1 --port 8765
```

UI 是完整端到端工作台：输入 symbol/period/topic/engines 后，会跑 Planning -> Research -> Browser -> Analyze -> FinalAnswer -> Citation/Chart -> Verifier，并在页面展示总览、报告、图表、引用、轨迹、原始数据。

MCP 服务是轻量 HTTP/JSON-RPC 版本：`/mcp/manifest` 查看工具，`/mcp/rpc` 可用 `tools/list` 和 `tools/call`。当前返回结构已接近 MCP 工具协议：工具使用 `inputSchema`，调用结果使用 `content: [{type:"text"}]` 和 `structuredContent`。

需要用户补充/授权的信息：

```text
SERPER_API_KEY: 启用 serper 搜索时需要。
Playwright 浏览器运行环境: 需要允许安装 playwright 包和 chromium 内核。
Chart.js CDN 网络访问: report.html 的交互图表需要浏览器能访问 jsdelivr；不通时仍有 PNG 图表。
METASO_API_KEY / SOGOU_API_KEY: 如果继续补齐二等奖里的 Metaso/Sogou 搜索，需要另外申请。
正式 MCP SDK/远程 MCP: 如果要对接外部 MCP 客户端，需要确认允许安装 mcp SDK，并确认对外监听 host/port。
```

这次清理后的定位要改成：

```text
保留现有项目中可复用的金融数据、特征、检索、报告、验证组件；
删除偏离主线的竞赛评测/grounded/shadow/benchmark 产物；
下一步按 DeepReport 的多 Agent 骨架重建前台执行层；
把我们自己的金融 API、模型 API、MCP/工具服务接进 Agent 工具层。
```

也就是说，它不应该继续沿着“阶段流水线脚本”方向堆功能，而应该回到 DeepReport 原始骨架：

```text
User/UI
  -> Planning Agent
  -> Sub-Agents: DeepResearcher / Browser / DeepAnalyze / FinalAnswer
  -> SearchManager
  -> MCPManager / Tool Registry
  -> Report Generator / Chart Generator / Citation Manager
```

## 2. DeepReport 官方骨架要点

根据官方中文 README 和本地参考仓库 `DeepReport_award2_ref`，DeepReport 的核心不是单条 pipeline，而是多 Agent 协作系统：

- `PlanningAgent`：把研究主题拆成可执行子任务。
- `DeepResearcherAgent`：发现并筛选高质量数据源。
- `BrowserAgent`：做网页交互、PDF 浏览、结构化信息提取。
- `DeepAnalyzeAgent`：做金融指标、估值、情绪、风险等分析。
- `FinalAnswerAgent`：生成 HTML 报告、图表、引用、质量检查。
- `SearchManager`：协调 Serper、Metaso、Sogou 等搜索引擎。
- `MCPManager`：动态注册、发现、调用本地/远程工具。
- `ModelAdapter`：连接 OpenAI、Anthropic 等模型。

注意：所谓“六个 Agent”不一定表示六个不同大模型，但每个核心 Agent 至少应该有自己的角色 prompt、任务输入输出和工具集合；它们可以共享同一个底层模型，也可以按职责使用不同模型。

## 3. 当前项目保留的核心组件

这次清理后，项目保留这些可复用基础层：

```text
configs/          # 配置
data/raw/         # mock 原始样例数据
docs/             # 少量必要说明
scripts/          # 核心 smoke / ingestion / pipeline 脚本
src/app/          # 当前 pipeline 入口
src/agents/       # 当前规则 planner/analyst/writer/verifier，后续要重构为 LLM Agent
src/data/         # 数据读取、标准化、manifest
src/features/     # 金融指标、风险、趋势、peer 特征
src/retrieval/    # EvidenceStore、BM25、reranker fallback
src/generation/   # writer backend 抽象
src/schemas/      # Evidence/Claim/Chart/Report/Task 数据契约
src/charts/       # PNG 图表生成
src/templates/    # Markdown/HTML/JSON 导出
src/training/     # reranker/verifier/rewriter 的轻量占位训练闭环
src/evaluation/   # 仅保留 claim 级轻量验证导出
tests/            # 核心组件测试
```

删除掉的主要是：

- `artifacts/` 下所有历史实验产物。
- `reports/` 下历史评测输出。
- 大量 Stage12 / competition / benchmark / grounded / shadow / review 文档。
- 可选 skeleton/backfill 临时实验链。
- eval_v1、numeric audit、writer trace 等偏比赛评测的复杂支线。
- 与当前金融多 Agent 主线无关的根目录文档。

## 4. 当前还不是多 Agent 的原因

保留下来的主链仍然是：

```text
src/app/main.py
  -> src/app/pipeline.py::run_pipeline
  -> src/agents/orchestrator.py::Orchestrator.run
  -> Planner.build_plan()
  -> Analyst.build_claims()
  -> optional retrieve_evidence_with_mode()
  -> Writer.render_markdown()
  -> Verifier.verify()
```

这里的问题是：

- `Planner` 是固定章节模板，不是 LLM planning。
- `Analyst` 是 pandas + 规则生成 claim，不是 LLM financial analyst。
- `Writer` 默认是 template，不是 LLM final answer agent。
- `Verifier` 是规则检查，不是 critic/verifier agent。
- 没有 SearchManager 多搜索引擎抽象。
- 没有 Browser Agent。
- 没有 MCPManager / Tool Registry。
- 没有 agent task queue、dependency routing、task result 状态机。

所以当前它只能叫“核心研报组件库 + 旧 pipeline”，不能叫真正的金融多 Agent。

## 5. 应该怎么改

### 5.1 新增真正的 Agent 基类

参考 `DeepReport_award2_ref/src/agents/base_agent.py`，需要在当前项目新增或重写：

```text
src/agents/base_agent.py
```

核心结构：

```text
Task
TaskResult
AgentStatus
BaseAgent
```

每个 Agent 都应该有：

- `name`
- `model`
- `memory`
- `tools`
- `execute_task(task)`
- `get_capabilities()`
- `submit_task()`
- `wait_for_task()`
- `process_tasks()`

### 5.2 新增 Model Adapter

当前 `src/generation/backend_remote.py` 只是 writer HTTP backend，不够。

应该新增：

```text
src/models/model_adapter.py
```

支持：

- OpenAI-compatible API
- Anthropic API
- 我们自己的金融模型 API
- model name、base_url、api_key、temperature、max_tokens 全部走配置

Agent 调模型应该统一走：

```python
await model.generate(prompt, system_prompt=..., response_format=...)
```

### 5.3 新增工具注册层

参考 DeepReport 的 `MCPManager`，我们应该新增：

```text
src/tools/registry.py
src/tools/mcp_manager.py
```

工具层要支持两类：

1. 本地 Python 工具：
   - 查行情
   - 查财报
   - 查估值
   - 查新闻
   - 跑财务指标计算
   - 生成图表
   - 导出报告

2. MCP/远程工具：
   - 公司数据 API
   - market data API
   - SEC/公告 API
   - 搜索服务
   - 浏览器服务

这样才接近 DeepReport 的“Tool Registry + MCPManager”架构。

### 5.4 新增 SearchManager

当前只有 BM25 本地检索。要改成：

```text
src/search/search_manager.py
src/search/engines.py
```

支持：

- Serper / Google search
- Metaso
- Sogou
- 本地 evidence store
- 我们自己的金融搜索 API
- 统一去重、打分、source quality、rerank

`DeepResearcherAgent` 不应该直接读 parquet，而应该调用 SearchManager。

### 5.5 新增 Browser Agent

需要：

```text
src/agents/browser_agent.py
```

职责：

- 打开网页/PDF
- 抽正文
- 抽表格
- 抽财务指标上下文
- 处理 source_url / filing URL / PDF URL

可以先做轻量版本：

- HTML requests + readability
- PDF text extraction
- 表格抽取后续再加

### 5.6 重写 Planning Agent

当前 `planner.py` 固定章节，不够。

应该改成：

```text
src/agents/planning_agent.py
```

输入：

```text
research_topic
requirements
output_format
```

输出 JSON plan：

```json
{
  "overview": "...",
  "tasks": [
    {
      "task_id": "task_001",
      "task_type": "deep_researcher",
      "description": "...",
      "parameters": {},
      "dependencies": [],
      "priority": 5
    }
  ],
  "expected_output": "...",
  "data_sources": [],
  "citations_required": []
}
```

这一步必须由 LLM 完成，不是模板。

### 5.7 重写 Research Agent

新增：

```text
src/agents/deep_researcher_agent.py
```

职责：

- 根据 planning task 调 SearchManager。
- 发现高质量金融来源。
- 对 source 做质量评分。
- 输出 evidence candidates。

它应使用工具：

- `search_web`
- `search_financial_data`
- `retrieve_local_evidence`
- `assess_source_quality`

### 5.8 重写 Analyze Agent

新增：

```text
src/agents/deep_analyze_agent.py
```

职责：

- 读取 Research/Browser 输出。
- 调用金融 API 和本地 feature 工具。
- 形成结构化 claims。
- 做估值、风险、财务指标、同行对比。

可以复用当前：

- `src/features/*`
- `src/schemas/claim.py`
- `src/schemas/evidence.py`

但 Agent 决策应该由 LLM + tools 完成。

### 5.9 重写 Final Answer Agent

新增：

```text
src/agents/final_answer_agent.py
```

职责：

- 汇总 claims、evidence、charts、citations。
- 生成 Markdown/HTML/JSON 报告。
- 调 `ChartGenerator` 和 `CitationManager`。
- 输出最终报告。

可以复用当前：

- `src/templates/*`
- `src/charts/*`

但最终写作应该可以接 LLM，不应只靠模板。

### 5.10 重写 Orchestrator

当前 `Orchestrator.run()` 是固定 pipeline。

应该改成：

```text
src/agents/orchestrator.py
```

职责：

1. 调 PlanningAgent 生成 plan。
2. 根据 `task_type` 把 task 分发给对应 Agent。
3. 处理 dependencies。
4. 收集 TaskResult。
5. 把中间结果交给下游 Agent。
6. 输出 trace、report、citations、artifacts。

执行图应从固定链：

```text
planner -> analyst -> writer -> verifier
```

改成动态任务图：

```text
PlanningAgent
  -> DeepResearcherAgent
  -> BrowserAgent
  -> DeepAnalyzeAgent
  -> FinalAnswerAgent
  -> Verifier/CriticAgent
```

## 6. 推荐保留与改造的现有代码

### 6.1 可直接复用

```text
src/schemas/*
src/data/*
src/features/*
src/retrieval/evidence_store.py
src/retrieval/bm25_index.py
src/charts/*
src/templates/*
src/utils/config.py
configs/*.yaml
```

### 6.2 需要重构

```text
src/agents/planner.py      -> planning_agent.py，接 LLM
src/agents/analyst.py      -> deep_analyze_agent.py，接 LLM + finance tools
src/agents/writer.py       -> final_answer_agent.py，接 LLM + report tools
src/agents/verifier.py     -> verifier_agent.py / critic_agent.py
src/agents/orchestrator.py -> task graph orchestrator
src/generation/*           -> model adapter + backend 拆分
```

### 6.3 应该新增

```text
src/models/model_adapter.py
src/tools/registry.py
src/tools/mcp_manager.py
src/tools/finance_tools.py
src/search/search_manager.py
src/search/engines.py
src/report/html_generator.py
src/report/chart_generator.py
src/report/citation_manager.py
src/app/gradio_app.py 或 src/app/main.py
```

## 7. 建议的最小金融多 Agent v1

不要一口气做复杂系统，先做一个能跑通的 v1：

```text
User query:
  "分析 AAPL 2025Q4 财务表现，并生成带引用的研究报告"

PlanningAgent:
  生成 research/analyze/write/verify task graph

DeepResearcherAgent:
  调 SearchManager + 本地/远程金融 API，收集 evidence

BrowserAgent:
  抽取网页/PDF/公告正文和表格

DeepAnalyzeAgent:
  调 finance tools，生成 ClaimItem[]

FinalAnswerAgent:
  调 LLM 写报告，调图表/引用工具导出 HTML/Markdown

VerifierAgent:
  检查 claim 是否有 evidence，数字是否来自来源，引用是否完整
```

最小输出：

```text
data/outputs/task_plan.json
data/outputs/task_trace.jsonl
data/outputs/evidence.json
data/outputs/claims.json
data/outputs/citations.json
data/reports/report.md
data/reports/report.html
data/reports/report.json
```

## 8. 下一步开发顺序

建议按这个顺序动代码：

1. 新增 `src/models/model_adapter.py`，把我们的模型 API 接进去。当前已先接 DeepSeek OpenAI-compatible ChatCompletions，配置入口是 `DeepReport_plus/.env` 和 `configs/model_backends.yaml`。
2. 新增 `src/agents/base_agent.py`，建立 Task/TaskResult/AgentStatus。当前已完成第一版同步 Agent 基类。
3. 把 `Planner` 改成 LLM `PlanningAgent`。当前已新增 `src/agents/planning_agent.py`，旧 `Planner.build_plan()` 保持兼容，`Planner.build_research_plan()` 可委托 DeepSeek 生成任务图。
4. 新增 `src/tools/registry.py`，把现有 data/features/retrieval/charts/templates 包装成工具。当前已完成第一版 `ToolRegistry`，可暴露 OpenAI/DeepSeek function tool schema，并包装本地 evidence retrieval、财务指标、趋势特征和图表工具。
5. 新增 `SearchManager`，先接本地 evidence + 一个真实搜索/金融 API。当前已完成第一版 `src/search/search_manager.py`，支持多搜索引擎注册、聚合、去重、排序，本地 evidence 检索可作为一个 engine。
6. 新增 `DeepResearcherAgent`。当前已完成第一版 `src/agents/deep_researcher_agent.py`，可通过 `SearchManager` 返回 evidence candidates。
7. 新增 `DeepAnalyzeAgent`，复用现有 features 但由 Agent 调用。当前已完成第一版，可调用工具层生成 ratio/trend，并由 DeepSeek 产出 evidence-backed claims。
8. 新增 `FinalAnswerAgent`，接 LLM writer + report exporter。当前已完成第一版，可生成 Markdown/HTML/JSON 报告。
9. 重写 `Orchestrator` 为 task graph executor。当前已新增 `src/agents/multi_agent_orchestrator.py`，并已支持 `execution_mode=dynamic`：先由 `PlanningAgent` 生成 `task_plan.json`，再按依赖关系动态分发给 Research/Browser/Analyze/Final/Verifier。`execution_mode=static` 仅作为上一版固定链路回退。
10. 最后再加 Gradio UI 和 MCP。

## 9. 当前清理后的判断

现在仓库已经比之前清楚很多：实验垃圾少了，核心组件还在。

但下一步不能继续补 smoke 或评测脚本了。真正该做的是：

```text
把 src/agents 从“命名像 Agent 的规则模块”
重构成“真实由模型驱动、可调用工具、可分发任务的金融多 Agent 层”。
```
