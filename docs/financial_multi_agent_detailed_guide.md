# 金融多 Agent 项目详细说明

## 1. 项目定位

`DeepReport_plus` 当前的目标，不是继续扩展一条固定规则流水线，而是把已有的金融数据、检索、验证、报告能力重组为一个可运行、可验证、可扩展的金融研究多 Agent 系统。

它目前处于一个很明确的过渡阶段：

- 保留旧主链中已经比较稳定的数据处理、特征抽取、图表、验证能力。
- 在前台执行层引入 `Planning -> Research -> Browser -> Analyze -> FinalAnswer -> Verifier` 的角色化协作。
- 在检索层逐步从 `BM25` 过渡到 `BM25 + vector recall + rerank` 的真实 RAG 结构。
- 在输出层补齐引用、图表、验证报告和自动返工闭环。

这个版本已经不是“只有多 Agent 命名”的样子，而是已经具备一条能跑通的动态协作链路。

## 2. 当前可运行能力

当前仓库已经可以运行以下能力：

1. 以公司/股票代码和期间为输入，生成任务规划。
2. 联合本地样例数据、搜索引擎结果、Yahoo Finance 快照等数据源做证据搜集。
3. 将搜索结果、网页正文、PDF 内容归一为统一证据结构。
4. 生成三表摘要、财务分析、同行对比、估值观察等 claim。
5. 输出 Markdown / HTML / JSON 报告。
6. 自动生成引用表、图表、验证报告。
7. 当验证未通过时，触发一轮 `Verifier -> FinalAnswer` 自动返工。
8. 可选启用 durable memory；默认只作为 Planner/Router 历史提示，不替代证据和验证。
9. 通过静态 `SkillRegistry` 给 Planner/Router 提供金融技能摘要和 task routing trace。
10. 可通过 competition packaging smoke 导出公司/行业/宏观 DOCX 和 `results.zip`。

## 3. 系统架构

### 3.1 Agent 角色

- `PlanningAgent`
  - 将研究问题拆解为可执行任务图。
  - 输出 dependency-aware 的 task plan。

- `DeepResearcherAgent`
  - 统一调度本地证据检索和外部搜索。
  - 输出去重、排序后的 evidence candidates。

- `BrowserAgent`
  - 将 snippet、网页、PDF 等输入转成 citation-ready evidence records。
  - 可选调用 Jina Reader 或 Playwright 抽取正文。

- `DeepAnalyzeAgent`
  - 调用金融工具生成三表、财务指标、同行比较、估值结果。
  - 产出带 `evidence_id` 的 claims 和 analysis artifacts。

- `FinalAnswerAgent`
  - 基于 claims 和 evidence 生成中文研究报告。
  - 支持 revision request，能够根据 verifier 反馈返工。

- `VerifierAgent`
  - 组合规则验证和 LLM 验证。
  - 检查章节完整性、证据引用、数值支撑、图表来源。
  - 产出 `verification_report.json` 和返工建议。

### 3.2 工具与基础层

- `SearchManager`
  - 聚合 `local_real_data`、`local_evidence`、`yahoo_finance`、`tavily`、`serper` 等搜索/数据源。

- `ToolRegistry`
  - 暴露本地金融工具和 schema。

- `SkillRegistry`
  - 暴露静态金融技能摘要，如证据发现、财务分析、报告组装、验证返工。
  - Planner 会读取全局 skill brief；dynamic router 会按 task_type/query 选择技能并写入 `task_route_context.json`。

- `MCPManager`
  - 导出本地工具 manifest。
  - 支持轻量 HTTP/JSON-RPC MCP 风格服务。

- `CitationManager`
  - 统一生成 `citations.json`、`citations.md` 并回填报告。

- `ChartGenerator`
  - 基于 claims / evidence 生成报告图表。

## 4. 检索与 RAG 升级现状

当前检索层有四种模式：

- `bm25`
- `vector`
- `hybrid`
- `hybrid_rerank`

其中 multi-agent 动态主链默认使用：

```text
hybrid_rerank
```

它的执行思路是：

```text
BM25 lexical recall
  + vector recall
  + rerank
  -> top evidence
```

检索前会经过 `finance_query_expansion_v1`：

- 将中文财经词扩展成英文指标词，例如 `营收 -> revenue`、`毛利率 -> gross margin`、`现金流 -> cash flow`。
- 将 ticker、公司名、sector/industry、period 合并进本地检索 query。
- 在 search/retrieval meta 中记录 `query_original`、`query_adapted`、`query_terms_added`、`failure_reason`，方便 harness 定位召回失败原因。

### 4.1 vector 路径

`src/retrieval/chroma_index.py` 提供了 `ChromaIndex`：

- 优先尝试 `chromadb` 本地 ephemeral collection。
- 如果本地未安装 `chromadb` 或 `sentence-transformers`，自动回退到内存向量索引。
- 这里的 Chroma 是检索层，不是独立数据源；它只对已经进入 evidence 的记录做语义召回，不能替代 FRED、SEC、BLS、BEA 或行业数据库。
- embedding 默认对齐轻量模型路线：
  - `BAAI/bge-small-en-v1.5`

### 4.2 reranker 路径

`src/training/infer_reranker.py` 当前支持：

- 默认模型名与配置保持一致：
  - `BAAI/bge-reranker-base`
- 如果本地 `sentence-transformers` 可用，会优先按 checkpoint 中的 `model_name` 加载 `CrossEncoder`。
- 如果模型不可用，会回退到可校准的金融启发式 rerank：
  - base score
  - query overlap
  - numeric match
  - source authority
  - freshness
  - chunk type
- `src/training/train_reranker.py` 会从 reranker dataset 中估计 `feature_weights` 并写入 checkpoint；这不是完整神经微调，但已经是可复用的本地校准闭环。

这意味着本地没有下载模型时，系统不会中断，只是退回轻量 fallback。

## 5. Context Packer 与自动返工

### 5.1 为什么需要 Context Packer

Agent 架构里最容易失控的其实不是“有没有模型”，而是上下文会越来越大，最后 prompt 质量反而下降。

为此，项目里新增了 `src/agents/context_packer.py`，负责：

- 对 claims 做优先级排序和字符预算裁剪。
- 对 evidence 做按 `evidence_id` 优先级、可信度、支持 claim 数量的打包。
- 对 markdown 报告做 excerpt 截断。
- 对 verifier 报告生成 revision brief。

### 5.2 自动返工闭环

当前 dynamic 主链中，报告生成后会进入：

```text
FinalAnswerAgent -> Citation/Chart -> VerifierAgent
```

如果 `verification_report.passed == false`，则会触发：

```text
Verifier feedback
  -> revision brief
  -> FinalAnswerAgent rework
  -> VerifierAgent re-check
```

返工记录输出到：

```text
data/outputs/multi_agent/revision_history.json
```

当前默认最多返工 1 轮，目的是先把闭环建立起来，而不是过早引入复杂循环策略。

## 6. Memory 与 SkillRegistry

### 6.1 Durable Memory

`src/agents/durable_memory.py` 提供文件化 durable memory，默认关闭。显式开启时会写入：

- `memory/working/`
- `memory/episodic/`
- `memory/domain/`

当前默认策略是：

```text
memory.durable.context_scope: planner_router
```

也就是说，历史 brief 只作为 Planner/Router 的上下文提示使用，不会默认灌入所有下游 agent。报告事实仍必须来自 evidence records，并继续通过 citation、numeric audit、Verifier gate。

### 6.2 SkillRegistry

`src/tools/skill_registry.py` 提供静态金融技能目录。当前默认技能包括：

- `evidence_discovery`
- `financial_statement_analysis`
- `report_assembly`
- `verification_rework`
- `industry_research`
- `macro_context`

Planner 会读取全局 skill brief；dynamic router 会为每个 task 选择匹配 skill，写入 task metadata，并输出：

```text
data/outputs/multi_agent/task_route_context.json
```

默认目录位于：

```text
configs/skill_registry.yaml
```

这个模块目前是配置化 MVP，不是自动学习技能库。它的价值是先把“能力选择”和“可追溯路由”接入主链，后续再进入评估化。

## 7. 运行方式

### 7.1 基础环境

项目基于 Python 3.10+。

安装基础依赖：

```bash
pip install -e .
```

如果需要浏览器抽取：

```bash
pip install '.[browser]'
python -m playwright install chromium
```

如果需要本地轻量 RAG：

```bash
pip install '.[local_rag]'
```

### 7.2 模型配置

模型后端配置：

```text
configs/model_backends.yaml
```

常见环境变量：

```bash
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-v4-flash
TAVILY_API_KEY=...
SERPER_API_KEY=...
FRED_API_KEY=...
BLS_API_KEY=...
BEA_API_KEY=...
SEC_USER_AGENT='DeepReportPlus/0.1 your_email@example.com'
```

### 7.3 本地 RAG 模型预热

预热脚本：

```bash
python scripts/setup_local_rag_models.py
```

配置文件：

```text
configs/local_rag.yaml
```

默认模型：

- embedding: `BAAI/bge-small-en-v1.5`
- reranker: `BAAI/bge-reranker-base`

## 8. 常用运行命令

### 8.1 任务规划 smoke

```bash
python scripts/run_planning_agent_smoke.py
```

### 8.2 联网搜索 smoke

```bash
python scripts/run_tavily_smoke.py
python scripts/run_deepseek_smoke.py
```

### 8.2.1 独立数据源与 DeepSeek realtime smoke

默认不联网，只验证报告路径和 skip reason：

```bash
python scripts/run_realtime_data_smoke.py \
  --symbol AAPL \
  --period 2025Q4
```

启用远程数据源和 DeepSeek：

```bash
python scripts/run_realtime_data_smoke.py \
  --symbol AAPL \
  --period 2025Q4 \
  --enable-remote-data \
  --use-deepseek
```

缺少 `DEEPSEEK_API_KEY`、`FRED_API_KEY`、`BEA_API_KEY`、`TAVILY_API_KEY` 或 `SERPER_API_KEY` 时，脚本会在 summary 中记录 `missing_api_key`，而不是把 smoke 误判为业务失败。

### 8.3 动态多 Agent demo

```bash
python scripts/run_multi_agent_demo.py \
  --symbol AAPL \
  --period 2025Q4 \
  --execution-mode dynamic \
  --retrieval-ranking-mode hybrid_rerank \
  --engines local_real_data,yahoo_finance,tavily,local_evidence
```

更快的调试模式：

```bash
python scripts/run_multi_agent_demo.py \
  --symbol AAPL \
  --period 2025Q4 \
  --execution-mode dynamic \
  --fast
```

### 8.4 本地 UI

```bash
python scripts/run_financial_agent_ui.py --host 127.0.0.1 --port 8787
```

打开：

```text
http://127.0.0.1:8787
```

### 8.5 MCP 服务

```bash
python scripts/run_mcp_server.py --host 127.0.0.1 --port 8765
```

查看 manifest：

```bash
curl http://127.0.0.1:8765/mcp/manifest
```

### 8.6 Competition packaging smoke

从现有公司研报 artifacts 打包：

```bash
python scripts/run_competition.py --skip-company-run
```

重新跑公司主链并打包：

```bash
python scripts/run_competition.py --symbol AAPL --period 2025Q4 --fast
```

输出包括三份 DOCX、`results.zip`、`industry_report.json` 和 `macro_report.json`。默认情况下 Industry/Macro 可离线基于公司主链 artifacts 打包；如果需要把独立 SEC/宏观/政策 evidence 写入 Industry/Macro 报告，使用：

```bash
python scripts/run_competition.py \
  --symbol AAPL \
  --period 2025Q4 \
  --fast \
  --realtime-data
```

如果需要复现云端记录里的“rich baseline draft + agent audit”桥接模式，使用：

```bash
python scripts/run_competition.py \
  --skip-company-run \
  --baseline-deepseek-workflow
```

该模式会额外输出 `baseline_deepseek_report.md` 和 `baseline_deepseek_report.json`。它用于保留 DeepSeek 风格的丰富初稿，同时把 claims 分成“已证实 / 待补证 / 不支持”；它不替代 strict/realtime 交付门禁，也不会把缺证据内容提升为可验证结论。

最终本地 qwen3 交付路径：

```bash
python scripts/run_competition.py \
  --config configs/model_backends_local_ollama.yaml \
  --symbol AAPL \
  --period 2025Q4 \
  --fast
```

真实边界：`--realtime-data` 只表示系统会尝试拉取独立数据源；如果 key、网络或源端返回失败，报告会记录 `failure_reason`，不会宣称已经拿到最新宏观或行业事实。

## 9. 输出物说明

动态主链默认输出到：

```text
data/outputs/multi_agent/
data/reports/multi_agent/
```

关键文件说明：

- `task_plan.json`
  - PlanningAgent 生成的任务图。

- `task_trace.jsonl`
  - 每个 agent/task 的执行轨迹、状态、耗时。

- `task_route_context.json`
  - Router 为每个 task 选择的 skill 和 memory context policy。

- `search_meta.json`
  - 本轮研究用了哪些搜索源，各引擎返回了什么元信息。

- `evidence.json`
  - 浏览归一后的证据记录。当前会包含 `source_timestamp`、`data_cutoff`、`freshness_bucket`、`evidence_scope` 等时效与边界字段。

- `claims.json`
  - 分析生成的 claim 列表。

- `analysis_artifacts.json`
  - 三表、指标、同行、估值等中间分析结果。

- `citations.json`
  - 标准化引用表。

- `charts.json`
  - 报告图表元数据。

- `mcp_manifest.json`
  - 本地工具 manifest。

- `verification_report.json`
  - 最终验证结果。

- `revision_history.json`
  - 自动返工轮次和结果。

- `report.md`
  - Markdown 报告。

- `report.html`
  - HTML 报告。

- `report.json`
  - 结构化报告 payload。

Competition packaging 额外输出：

- `industry_report.md` / `industry_report.json`
  - IndustryResearchAgent 生成的行业报告；如果提供独立 evidence，会输出 `independent_evidence_count`、`freshness_summary`、`source_boundary`。

- `macro_report.md` / `macro_report.json`
  - MacroResearchAgent 生成的宏观传导框架报告；如果提供 FRED/BLS/BEA/Federal Reserve/SEC evidence，会输出对应 evidence ids 和 source boundary。

- `results.zip`
  - Company/Industry/Macro 三份 DOCX 打包文件。

## 10. 代码结构建议阅读顺序

如果是第一次接手这个仓库，建议按下面顺序读：

1. `README.md`
2. `docs/company_agent_architecture.md`
3. `docs/financial_multi_agent_detailed_guide.md`
4. `src/agents/planning_agent.py`
5. `src/agents/multi_agent_orchestrator.py`
6. `src/search/search_manager.py`
7. `src/retrieval/retrieve.py`
8. `src/agents/browser_agent.py`
9. `src/agents/deep_analyze_agent.py`
10. `src/agents/final_answer_agent.py`
11. `src/agents/verifier_agent.py`

## 11. 当前边界与不足

虽然动态多 Agent 主链已经建立，但项目还没有完全进入“成熟生产版”：

- 三表仍主要依赖本地财务摘要和规则提取。
- 估值模型还是第一版规则模型。
- PDF/公告表格还没有系统接入统一三表 schema。
- A 股公告、交易所、巨潮等中文金融源还没完全接入。
- 验证器虽然已有自动返工，但返工轮次控制、修复策略选择还较简单。
- SearchManager 已经是聚合层，但 source quality ranking 还可以继续做细。
- SkillRegistry 当前是配置化 MVP，尚未进入学习型技能系统。
- Industry/Macro 交付已有专用本地 Agent 与独立数据源 v1 适配器；但行业 TAM、市场份额、产业链价格和全球宏观终端覆盖仍需要后续增强。

## 12. 下一步建议

建议后续按这个优先级推进：

1. 把 PDF/公告表格抽取接到真实三表 schema。
2. 补股本、市值、EV、同行选择规则。
3. 把 verifier 的数值核查做得更细，增强图文一致性验证。
4. 完善中文金融源接入。
5. 用更宽 case set 评估 SkillRegistry routing 对验证通过率和 unsupported fallback 的影响。
6. 给 Industry/Macro Agent 继续补行业专用数据库、TAM/份额/供需周期和更多国家/地区宏观源。
7. 如果本地资源允许，再进一步增强 reranker / verifier / rewriter 的轻量训练闭环。

## 13. 对 GitHub 读者的建议

如果你是在 GitHub 上第一次看到这个项目，最重要的判断是：

- 这不是一个“只会输出模板报告”的 demo。
- 这也还不是一个完全成熟的生产金融研究系统。
- 它现在最有价值的地方，是已经搭起了一条可持续演进的金融多 Agent 骨架，而且验证、引用、图表、返工这些关键环节已经开始接上。

换句话说，它已经从“功能堆叠”转向“系统形态”了。
