# Open DeepReport++ 面试项目汇总

本文面向面试讲解，按“为什么做、怎么从 0 到 1 搭起来、当前能做什么、质量如何证明”的顺序复盘当前仓库。内容基于当前代码实现与项目文档整理，尽量区分已实现能力、可选依赖、fallback 和后续规划，避免把路线图写成已上线功能。

## 1. 项目一句话定位

Open DeepReport++ 是一个面向公司/个股研报的证据驱动多 Agent 报告生成系统。它不是让 LLM 直接自由写报告，而是把报告拆成：

1. 数据与证据采集；
2. Evidence 标准化；
3. RAG 检索与重排；
4. 财务、估值、风险等结构化分析；
5. claim-first 报告生成；
6. Verifier 与 Quality Gate；
7. 可观测 trace 与回归评测。

核心目标是让每个关键结论都能回到 `evidence_id`、数值 lineage、图表来源和质量门禁，而不是只看最终报告是否“像一篇研报”。

面试时可以这样概括：

> 我做的是一个金融研报 Agent 系统。它把“生成报告”拆成证据检索、结构化分析、写作、验证和返工多个阶段。系统默认用精简 Agent 流水线保证效率，在诊断模式下展开专业角色 Agent；报告输出 Markdown/HTML/JSON，同时产出 evidence、claims、charts、verification、scorecard、trace，方便定位质量问题。

## 2. 从 0 到 1 的全流程

当前主链路入口集中在 `src/agents/multi_agent_orchestrator.py`，面向 Web UI、脚本和评测 harness 提供公司研报生成能力。

整体流程如下：

```text
用户任务
  -> PlanningAgent 生成任务图
  -> DeepResearcherAgent 调用本地/公开数据源检索候选证据
  -> BrowserAgent 标准化为 citation-ready evidence_records
  -> DeepAnalyzeAgent 生成财务指标、claims、role_outputs、估值/风险/同行分析
  -> FinalAnswerAgent 组装 Markdown / HTML / JSON
  -> VerifierAgent 校验证据、引用、结构、数值、估值、图表
  -> GapResolverAgent / Quality Gate 记录缺口、返工建议与交付状态
  -> 输出报告、trace、quality artifacts、scorecard
```

默认 `collaborative` 模式并不会把所有角色 Agent 都作为顶层任务跑一遍。现在的默认任务图更偏精简，通常是：

```text
PlanningAgent
DeepResearcherAgent
BrowserAgent
DeepAnalyzeAgent
FinalAnswerAgent
VerifierAgent
Quality Gate
```

`Quality Gate` 不是一个独立 LLM Agent，而是评测与交付门禁层，主要由 `src/evaluation/report_quality.py`、`src/evaluation/llm_report_review.py`、`src/evaluation/delivery_gate.py` 等模块汇总。

`diagnostic_full` 模式才会把下列角色展开成顶层步骤：

- `IdentityAgent`
- `StatementAgent`
- `PeerAgent`
- `ValuationAgent`
- `RiskAgent`
- `CriticAgent`

这样做的取舍是：默认运行时减少 0 秒噪声 Agent 和无效 timeline；需要调试某个模块时，再打开诊断模式观察角色输出。

## 3. 当前能完成什么任务

当前系统已经能完成的主任务：

- 生成公司/个股研报，输出 `report.md`、`report.html`、`report.json`。
- 生成结构化中间产物：`evidence.json`、`claims.json`、`analysis_artifacts.json`、`financial_metrics.json`、`tables.json`、`charts.json`。
- 对每个 factual claim 做 evidence/citation 约束，报告中保留 `evidence_id`。
- 生成图表，并做 chart consistency / multimodal consistency 审计。
- 做财务指标、三表覆盖、同行数据缺口、估值可用性、风险证据等分析。
- 输出 `verification_report.json`、`quality_report.json`、`llm_quality_review.json`、`delivery_gate.json`。
- 输出 `task_trace.jsonl`、`agent_collaboration_trace.json`、`tool_trace.json`、`research_blackboard.json` 等可观测产物。
- 通过本地 MCP-style HTTP 服务暴露金融工具 manifest 和 tool call 能力。
- 运行多公司/多模式评测、RAG ablation、memory ablation、generalization regression。

需要明确的边界：

- 远程实时数据源默认受配置、网络和 API key 约束；本地 smoke 更依赖 mock/local evidence。
- Chroma 和 sentence-transformers 是可选依赖；没有安装时系统会 fallback。
- SkillRegistry 是静态/配置化能力目录，不是自动学习技能系统。
- Memory 只作为上下文提示，不能替代证据、引用和 verifier。
- 行业/宏观能力已有本地专用 Agent 与配置痕迹，但公司研报主线仍是当前最完整的闭环。

## 4. 数据层与 Evidence 标准化

项目的数据思路是先把所有来源统一成 evidence，再让后续模块只消费规范化证据，而不是直接从网页或 API 文本中写报告。

主要数据边界：

- 本地真实数据：`data/raw/real_data`
- 本地整理数据：`data/curated`
- mock / fixture 数据：用于 smoke、schema、feature、回归测试
- SEC、Yahoo/yfinance、Tavily、local evidence 等公开来源：通过配置和 SearchManager 接入
- 财务标准化：`src/data/financial_statement_metrics.py`
- 财务质量守卫：`src/data/financial_quality.py`
- 数据权威等级：`src/data/source_authority.py`

Evidence 的关键字段包括：

- `evidence_id` / `sample_id`
- `source_type`
- `title`
- `source_url`
- `publish_time`
- `symbol`
- `period`
- `trust_level`
- `metadata`
- `content`

这个设计有两个好处：

- Agent 不需要知道每个数据源的原始格式；
- Verifier 可以反向检查报告里的 claim 是否真的有对应 evidence。

### 财务口径守卫

GOOGL 质量失败暴露的问题不是“某家公司特例”，而是通用财务口径问题：如果 Yahoo/yfinance 中存在一次性收益，不能直接用未调整净利润计算净利率、P/E 或估值。

当前实现里 `src/data/financial_quality.py` 会抽取并计算：

- `Normalized Income`
- `Normalized EBITDA`
- `Total Unusual Items`
- `Gain On Sale Of Security`
- `adjusted_net_income`
- `non_recurring_gain`
- `non_recurring_gain_ratio`
- `net_income_quality_flag`
- `valuation_input_usable`
- `valuation_input_rejection_reason`

默认阈值是 `DEFAULT_NON_RECURRING_THRESHOLD = 0.15`。当非经常性收益占净利润比例过高时，系统优先使用 adjusted / normalized 口径；如果无法调整，就把估值输入标为不可用。

相关测试在 `tests/test_feature_layer.py` 中覆盖了 GOOGL 2026Q1 样例：未调整净利润不得进入净利率/估值，单季度 FCF 不能直接当 DCF 年度基础。

## 5. RAG 怎么做

RAG 的核心入口是 `src/retrieval/retrieve.py`，核心函数是 `retrieve_evidence_with_mode()`。它不是单一路径，而是多种检索模式可切换：

- `bm25`
- `vector`
- `hybrid`
- `reranker`
- `hybrid_rerank`

默认配置中 `configs/local_rag.yaml` 写的是：

- embedding model：`BAAI/bge-small-en-v1.5`
- reranker model：`BAAI/bge-reranker-base`
- retrieval ranking mode：`hybrid_rerank`
- vector store：`chroma`

### 5.1 EvidenceStore

`EvidenceStore` 负责从 `data/curated` 加载证据记录，并按 `symbol`、`period` 过滤。后续 BM25、vector、hybrid 都在过滤后的记录上运行。

如果开启 chunking，`chunk_records()` 会把长 evidence 切块，提升局部召回能力。检索 meta 会记录：

- `source_record_count`
- `record_count`
- `chunking_enabled`
- `chunk_count`
- `loaded_file_count`
- `skipped_files`
- `load_errors`

### 5.2 BM25

`BM25Index` 是关键词召回 baseline。它适合公司名、ticker、财务指标名、报告期等高精度词匹配，也是 retrieval ablation 中最重要的基线。

系统在评测中会把 BM25 与 `hybrid`、`hybrid_rerank` 等模式做对照，比较 evidence coverage、alignment、verifier pass delta。

### 5.3 向量检索与向量库

向量检索由 `src/retrieval/chroma_index.py` 的 `ChromaIndex` 提供。

真实边界如下：

- 优先尝试 `chromadb.EphemeralClient()`；
- collection 名称是 `deepreport_local_evidence`；
- 默认 embedding 模型是 `BAAI/bge-small-en-v1.5`；
- 如果安装了 `sentence-transformers`，用 SentenceTransformer 编码；
- 如果未安装或加载失败，fallback 到 96 维 hash embedding；
- 如果 Chroma 不可用，fallback 到内存向量列表和 cosine similarity。

所以当前不能吹成“生产级持久化向量数据库”。更准确的说法是：

> 项目实现了 Chroma 优先、内存 fallback 的本地向量检索层；它足够用于本地闭环、ablation 和工程验证，但还不是线上持久化向量库方案。

### 5.4 Hybrid 与 reranker

`hybrid` 模式将 BM25 与 vector 结果合并：

- BM25 权重：0.55
- vector 权重：0.45
- 使用 reciprocal-rank 风格融合

`hybrid_rerank` 会先做 hybrid seed，再调用 `rerank_hits_with_meta()`。meta 中会保留：

- `checkpoint_used`
- `fallback_used`
- `vector_backend`
- `bm25_hit_count`
- `vector_hit_count`
- `returned_hit_count`
- `failure_reason`

这让评测可以判断：报告质量差到底是模型写作问题、证据缺失、检索 fallback，还是重排 checkpoint 不可用。

## 6. 多 Agent 体系

### 6.1 当前注册的 Agent

`MultiAgentOrchestrator` 当前注册了这些 Agent：

- `PlanningAgent`
- `DeepResearcherAgent`
- `BrowserAgent`
- `DeepAnalyzeAgent`
- `IdentityAgent`
- `StatementAgent`
- `PeerAgent`
- `ValuationAgent`
- `RiskAgent`
- `FinalAnswerAgent`
- `CriticAgent`
- `VerifierAgent`
- `GapResolverAgent`

注意：`run_summary.agent_count` 统计的是注册 Agent 数量，不等于默认 timeline 中实际执行的顶层步骤数量。

### 6.2 默认核心 Agent

`PlanningAgent`

- 输入用户研究主题、symbol、period、requirements。
- 输出任务图。
- 当前 planner 允许的核心 task type 包括 `deep_researcher`、`browser`、`deep_analyze`、`final_answer`、`verifier`。
- 如果 planner 输出不完整，orchestrator 会通过 `ensure_minimum_task_graph()` 补齐最小图。

`DeepResearcherAgent`

- 负责证据发现。
- 调用 SearchManager、本地证据、Yahoo、SEC、Tavily 等配置化数据源。
- 输出 `evidence_candidates` 和 `search_meta`。
- 检索参数包括 `ranking_mode`、`topk`、`use_chunks`、`engines`、`enable_remote`。

`BrowserAgent`

- 负责把候选证据清洗成 citation-ready `evidence_records`。
- 它是“网页/候选数据”和“后续 claims”之间的规范化层。
- 可配置 reader / playwright / LLM extraction，fast 模式下会降低读取成本。

`DeepAnalyzeAgent`

- 系统中最重的分析 Agent。
- 负责生成 claims、财务指标、三表视图、同行上下文、估值结果、图表/表格输入。
- 同时生成 `analysis_artifacts.role_outputs`，包括 identity、three statement、peer、valuation、risk 五类逻辑角色输出。
- 默认模式下这些 role outputs 展示为分析模块，而不是顶层 0 秒 Agent。

`FinalAnswerAgent`

- 消费 claims、evidence、charts、tables、role_outputs、revision brief。
- 输出 Markdown、HTML、JSON。
- 需要遵守 citation、章节、披露和 gap 表达约束。

`VerifierAgent`

- 检查 evidence_id、claim support、数值支撑、章节完整性、图表来源、entity/period 一致性、估值审计等。
- 输出 `verification_report`、errors、evidence_gaps、revision brief。
- 默认 verifier 写作返工最多 1 轮，避免无意义反复重写。

`GapResolverAgent`

- 识别三表、估值、同行、数据源、PDF 消费、缺口表达等问题。
- 更适合处理“缺数据/缺分析口径”的问题，而不是让 FinalAnswerAgent 反复改措辞。

### 6.3 诊断角色 Agent

`diagnostic_full` 模式会调用 `prepare_collaborative_tasks()` 插入角色 Agent：

- `IdentityAgent`：公司身份、业务画像、主体一致性；
- `StatementAgent`：收入表、资产负债表、现金流三表覆盖；
- `PeerAgent`：同行数据覆盖与比较边界；
- `ValuationAgent`：估值输入、模型可用性、缺失假设；
- `RiskAgent`：风险证据与披露边界；
- `CriticAgent`：写作前基于 research blackboard 做 deterministic objections。

这些 Agent 本质上复用 `DeepAnalyzeAgent` 的结构化 role outputs，所以默认不需要作为顶层任务出现。它们的价值在诊断：当报告失败时，可以快速定位是身份、三表、同行、估值还是风险模块的问题。

## 7. Blackboard 与协作方式

Agent 之间不是只靠自然语言上下文传递。项目有一个共享 `research_blackboard`，实现位于 `src/agents/research_blackboard.py`。

Blackboard 保存：

- `company_identity`
- `market_route`
- `industry_profile`
- `period_state`
- `coverage`
- `role_outputs`
- `agent_writes`
- `critic`

每个 Agent 完成后，orchestrator 调用 `update_blackboard_for_task()` 刷新状态。这样下游可以看到：

- 哪些主数据源尝试过；
- 三表是否齐全；
- 同行数据是否真实可用；
- 估值是否可复现；
- 是否存在 period mismatch；
- 哪些 role output 是 complete、partial、missing。

这个设计解决了一个常见 Agent 系统问题：如果所有状态都藏在 prompt 文本里，后续质量门禁很难做结构化审计。

## 8. 记忆管理：两套三层记忆

项目里有两套“记忆”概念，面试时要讲清楚。

### 8.1 Chat 工作台三层记忆

实现位于 `src/app/agent_chat.py`。

第一层：`ShortTermChatMemory`

- session 内滑动窗口；
- 保存最近对话 turn；
- 保存 pinned facts 和 verifier feedback；
- 适合短期上下文、用户刚刚补充的信息。

第二层：`UserPreferenceMemory`

- 文件化用户偏好；
- 通过规则抽取偏好；
- 保存用户喜欢的报告风格、语言、重点等。

第三层：`LongTermChatMemory`

- 持久语义记忆；
- 存储 embedding；
- recall 时综合 vector score、词频 overlap、importance、recency、entity boost；
- embedding 复用 `embed_texts()`，因此也具备 sentence-transformers / hash fallback。

这三层都受同一个边界约束：

> Memory is context only and never substitutes for evidence_id citations or verifier gates.

也就是说，Memory 可以影响路由、偏好、检索词，但不能直接成为报告事实来源。

### 8.2 Agent 运行持久化三层记忆

实现位于 `src/agents/durable_memory.py`，核心类是 `DurableMemoryStore`。

第一层：`working`

- 当前 run 的 snapshot；
- 路径形态：`memory/working/<run_id>/snapshot.json`；
- 也会保存质量反馈：`quality_feedback.json`。

第二层：`episodic`

- 某个 symbol / period 的历史运行片段；
- 路径形态：`memory/episodic/<symbol>/<period>/<run_id>.json`；
- 用于下一次 planner/router 看到最近 run 的失败或质量反馈。

第三层：`domain`

- 按 symbol 聚合的长期领域记忆；
- 路径形态：`memory/domain/<symbol>.json`；
- 保存历史质量指标、open gaps、verification 结果摘要。

配置默认在 `configs/app.yaml`，durable memory 默认关闭，开启后默认 `context_scope` 是 `planner_router`。这意味着历史记忆主要给 Planner/Router 提示，不会默认塞进所有 Agent 的事实上下文。

## 9. SkillRegistry：项目内 Skill，不是外部插件

项目使用了 Skill，但它是内部 `SkillRegistry`，实现位于 `src/tools/skill_registry.py`，配置在 `configs/skill_registry.yaml`。

它的定位是：

- 给 Planner/Router 提供能力摘要；
- 帮助选择 specialist flow；
- 把相关 tool、输入输出、guardrails 压缩成 prompt brief；
- 写入 task metadata / trace，方便评测。

它不是：

- 不是 Codex 的外部 skill 插件；
- 不是自动学习技能系统；
- 不是工具执行器；
- 不能替代 evidence / citation / verifier。

当前配置化技能包括：

- `evidence_discovery`
- `financial_statement_analysis`
- `report_assembly`
- `verification_rework`
- `industry_research`
- `macro_context`

选择逻辑大致是按 task type、query trigger terms、tool names 计分，最多选若干个渲染为 `[SkillRegistry]` brief。

面试说法：

> 我没有让 Agent 自由决定“会什么技能”，而是把技能目录配置化，作为 planner/router 的能力提示。这样可以提升路由稳定性，同时保留可审计性。Skill 本身不执行工具，也不能绕过证据门禁。

## 10. MCP 相关协议与工具边界

项目实现了一个 MCP-style 本地工具管理层：

- `src/utils/mcp_manager.py`
- `src/utils/mcp_http_server.py`

协议名是 `local-mcp-v1`。

`MCPManager` 能做：

- 从 core tool registry 注册工具；
- `list_tools()` 输出工具 manifest；
- `tool_schemas()` 输出 OpenAI function-style schema；
- `call_tool()` 根据工具名调用 handler；
- `export_manifest()` 写出 `mcp_manifest.json`。

HTTP 服务提供：

- `GET /health`
- `GET /manifest`
- `GET /mcp/manifest`
- `GET /tools`
- `GET /mcp/tools`
- `POST /rpc`
- `POST /mcp/rpc`
- `POST /call`
- `POST /mcp/call`

JSON-RPC 支持：

- `initialize`
- `tools/list`
- `list_tools`
- `tools/call`
- `call_tool`
- `resources/list`
- `prompts/list`

`initialize` 返回：

- `protocolVersion: local-mcp-v1`
- `serverInfo.name: DeepReportPlusMCP`
- `serverInfo.version: 0.1.0`
- `capabilities.tools: true`

准确表述应该是：

> 当前实现是 MCP-style local protocol surface，用来把项目金融工具以 manifest、schema、JSON-RPC 形式暴露出来；它覆盖了工具发现和工具调用，不是完整远程资源生态。

## 11. 可观测性设计

项目在每次 run 后会输出大量可观测 artifact，方便回答“为什么这份报告失败”。

关键产物：

- `task_plan.json`：planner 输出的任务图；
- `task_route_context.json`：任务路由上下文、skill/memory 选择；
- `task_trace.jsonl`：每个 Agent 的执行记录；
- `agent_collaboration_trace.json`：Agent timeline、blackboard writes、handoff 视图；
- `tool_trace.json`：工具调用与工具可用性；
- `research_blackboard.json`：共享黑板最终状态；
- `search_meta.json`：检索源、ranking mode、fallback、hit count；
- `evidence.json`：标准化证据；
- `claims.json`：结构化 claim 表；
- `financial_metrics.json`：指标、lineage、coverage；
- `rejected_metrics.json`：被质量规则拒绝的指标；
- `claim_rejection_report.json`：claim 级拒绝原因；
- `chart_consistency.json`：图表与 claim 的一致性；
- `multimodal_consistency.json`：表格、图表、文本一致性；
- `verification_report.json`：Verifier 输出；
- `quality_report.json` / `quality_issues.jsonl`：客观质量评测；
- `delivery_gate.json`：最终交付门禁；
- `delivery_rework_history.json`：Web UI 返工历史；
- `run_summary.json`：本次运行摘要。

这些 trace 可以定位：

- Agent 是否空转；
- 默认 timeline 是否过长；
- 检索是否没有命中；
- vector 是否 fallback；
- reranker checkpoint 是否使用；
- 是否缺 SEC / official primary evidence；
- claim 是否没有 citation；
- 数值是否没有 lineage；
- 估值是否不可复现；
- quality gate 是因为 evidence、financial、multimodal、compliance 还是 LLM review 失败。

Web UI 中也读取这些 artifact，用 timeline、质量页、多 Agent 协作页、工具调用页展示运行状态。

## 12. 质量评测体系

项目不是只靠人工读最终报告，而是组合多层质量评测。

### 12.1 VerifierAgent

Verifier 是报告生成后的第一道硬门禁，检查：

- report sections；
- factual claim 是否有 evidence；
- evidence_id 是否有效；
- symbol / period 是否一致；
- 数值是否可追溯；
- 图表是否有来源；
- 估值模型是否可复算；
- 是否需要 rework。

### 12.2 Objective Quality Evaluator

实现位于 `src/evaluation/report_quality.py`。

它输出：

- `quality_report.json`
- `quality_report.md`
- `quality_issues.jsonl`

评分组包括：

- `structure`，权重 0.18；
- `evidence`，权重 0.20；
- `financial`，权重 0.18；
- `multimodal`，权重 0.12；
- `professional_depth`，权重 0.20；
- `compliance`，权重 0.12。

通过条件包括：

- total score >= 0.82；
- 无 fatal；
- 无 blocker；
- required checks passed。

### 12.3 LLM Review

`src/evaluation/llm_report_review.py` 提供主观复核层，关注报告是否像专业研报、是否有空洞章节、是否有明显逻辑问题。它不替代规则 verifier，而是和客观评测一起进入交付门禁。

### 12.4 Delivery Gate

实现位于 `src/evaluation/delivery_gate.py`。

核心公式是：

```text
delivery_pass = verifier_passed && objective_pass && llm_review_pass
```

其中 LLM review 默认要求 score >= 0.80；如果 review pass、score >= 0.70、且没有 fatal/blocker，并且 verifier/objective 都过，则可以走 relaxed pass。

### 12.5 Company Report Scorecard

实现位于 `src/evaluation/company_report_scorecard.py`。

它聚合 contest-style 指标：

- `authority_score`：主来源/高可信来源覆盖；
- `numeric_lineage_score`：财务指标 coverage 与 source lineage；
- `multimodal_consistency_score`：图表、表格、文本一致性；
- `valuation_reproducibility_score`：估值审计是否可复算；
- `gap_resolution_score`：缺口是否关闭或降级。

权重：

- authority：0.25；
- numeric lineage：0.25；
- multimodal：0.18；
- valuation reproducibility：0.22；
- gap resolution：0.10。

### 12.6 泛化质量检查

`research_blackboard.quality_generalization_checks()` 和相关测试用于防止“只对某几家公司打补丁”：

- 不混用 symbol；
- 不混用 period；
- 非经常性收益未调整不能进入估值；
- 单季度 FCF 不能直接进入 DCF；
- 同行数据缺失时不能伪造完整同行比较；
- 本地数据缺失时要输出数据缺口，而不是空洞章节。

## 13. Baseline 与 ablation

项目里的 baseline 不止一种，面试时可以分层讲。

### 13.1 RAG baseline

BM25 是检索 baseline。评测 harness 会比较：

- `bm25`
- `vector`
- `hybrid`
- `hybrid_rerank`

比较指标包括：

- evidence alignment；
- evidence coverage；
- verifier pass rate；
- retrieval fallback rate；
- retrieved doc count。

### 13.2 执行模式 baseline

`execution_mode` 支持：

- `static`
- `dynamic`
- `collaborative`
- `diagnostic_full`

可以把 static / 简化 pipeline 当作 orchestration baseline，用 dynamic/collaborative 对比任务图生成、返工和质量表现。

### 13.3 Memory baseline

Durable memory 默认关闭。`scripts/run_memory_ablation.py` 可以派生：

- memory enabled；
- memory disabled。

对比质量、延迟、verifier、evidence、chart、numeric audit 等指标，再决定是否 promote memory。

### 13.4 Rich baseline bridge

`scripts/run_competition.py --baseline-deepseek-workflow` 是一种 baseline bridge：

- 用 DeepSeek 风格 rich draft 提供更强可读性；
- 再由当前 evidence audit 分层标注已证实、待补证、不支持；
- 不放宽 verifier 或 citation 门禁。

它适合比较“强写作 baseline”和“证据驱动 pipeline”的差异，但不能替代 strict evidence workflow。

## 14. 返工逻辑与 GOOGL 复盘

这套系统早期的问题是：质量门禁失败后，容易让 FinalAnswerAgent 反复重写文本，但底层数据/分析口径没有修，导致 timeline 变长、质量仍然 false。

GOOGL 2026Q1 失败暴露出三个本质问题：

1. Yahoo/yfinance 的净利润可能包含大额证券出售收益；
2. 未调整净利润不能直接用于净利率、P/E 或 DCF；
3. 单季度 FCF 不能直接当作长期年度 FCF 基础。

当前修复方向是通用规则：

- 在标准化层抽取 unusual items / normalized income；
- 生成 adjusted net income 和 non-recurring gain ratio；
- 非经常性收益超过阈值时，估值必须使用 adjusted/normalized 口径；
- 无法调整时，估值不可用；
- 仅有季度 FCF 时，不生成正式 DCF 目标价；
- 同行数据不足时输出数据缺口，而不是 synthetic benchmark。

这比“给 GOOGL 写特例”更适合泛化到 AAPL、AMD、TSLA、NVDA 等公司。

## 15. 工程亮点

面试可重点讲这些亮点：

- Claim-first：先生成结构化 claims，再组装报告，便于校验和返工。
- Evidence boundary：所有事实 claim 必须绑定 evidence，不让 memory 或 LLM 常识直接进正文。
- RAG 可切换：BM25、vector、hybrid、reranker、hybrid_rerank 都能通过参数和 config 对照。
- 向量库 fallback：Chroma 可用时走 ephemeral collection，不可用时内存向量和 hash embedding 保证本地可跑。
- 多 Agent 可收缩：默认精简，诊断模式展开角色 Agent，平衡效率和可解释性。
- Blackboard 协作：把 Agent 输出变成结构化共享状态，而不是全靠 prompt 拼接。
- 两套三层记忆：Chat 记忆服务用户体验，Durable memory 服务跨 run 规划，但都不替代证据。
- MCP-style 工具边界：工具 discovery、schema、call、manifest 都有本地协议面。
- 可观测性完整：task、tool、blackboard、search、quality、delivery 全链路可追踪。
- 质量评测组合：Verifier + objective quality + LLM review + scorecard + ablation。

## 16. 工程取舍与不足

真实不足也适合面试中主动讲：

- 向量库目前是本地 ephemeral / fallback，不是生产级持久化检索服务。
- 部分旧文档或中文字符串存在编码异常，说明项目快速迭代中还需要文档治理。
- 远程数据依赖网络、API key、数据源稳定性；本地闭环更稳定。
- Memory 虽已有 ablation runner，但默认仍谨慎关闭或限制 scope，避免污染事实。
- SkillRegistry 还不是自学习系统，只是配置化技能目录。
- LLM review 会受模型质量影响，所以不能单独作为硬门禁。
- 行业/宏观报告能力有基础，但最成熟的是公司/个股研报主链。

## 17. 面试讲述模板

可以用三分钟版本这样讲：

> 这个项目是一个证据驱动的金融研报多 Agent 系统。最开始我没有直接让 LLM 写报告，而是先定义 Evidence、Claim、Report 等结构，再搭建数据采集、RAG、分析、写作、验证的流水线。RAG 层支持 BM25、Chroma 向量检索、hybrid 和 reranker，Chroma 是可选 ephemeral，本地没有依赖时会 fallback 到内存向量和 hash embedding。Agent 层默认是 Planning、Research、Browser、Analyze、Writer、Verifier 的精简链路，诊断模式才展开 Identity、Statement、Peer、Valuation、Risk 等角色 Agent。中间通过 research blackboard 共享结构化状态，避免所有上下文都塞进 prompt。

> 我还做了两套记忆：Chat 侧有短期对话、用户偏好、长期语义记忆；报告运行侧有 working、episodic、domain durable memory。但所有 memory 都只能做上下文提示，不能替代 evidence。工具侧实现了 local-mcp-v1 的 MCP-style manager 和 HTTP JSON-RPC 接口，可以暴露金融工具 schema 和 tool call。

> 质量上我做了 Verifier、客观 quality evaluator、LLM review、delivery gate 和 company scorecard。指标包括 citation coverage、claim support、numeric lineage、source authority、valuation reproducibility、multimodal consistency、gap closure 等。GOOGL 的 case 暴露出非经常性收益和单季度 FCF 估值的问题，所以我没有写公司特例，而是把财务口径守卫放在标准化层，保证泛化到多家公司。

## 18. 建议展示材料

面试项目展示时建议准备：

- 一张架构图：Data -> RAG -> Multi-Agent -> Report -> Quality Gate -> Trace。
- 一份实际报告产物：`report.md` / `report.html`。
- 一组中间产物截图：`claims.json`、`evidence.json`、`verification_report.json`、`delivery_gate.json`。
- 一张 timeline 截图：默认精简模式 vs `diagnostic_full`。
- 一个失败复盘案例：GOOGL 非经常性收益导致质量失败，如何用通用规则修。
- 一个 ablation 表：BM25 vs hybrid_rerank，memory enabled vs disabled。

## 19. 代码路径速查

| 主题 | 关键路径 |
| --- | --- |
| 多 Agent 编排 | `src/agents/multi_agent_orchestrator.py` |
| 默认规划 Agent | `src/agents/planning_agent.py` |
| 研究 Agent | `src/agents/deep_researcher_agent.py` |
| 证据标准化 Agent | `src/agents/browser_agent.py` |
| 分析 Agent | `src/agents/deep_analyze_agent.py` |
| 角色 Agent | `src/agents/analysis_role_agents.py` |
| 写作 Agent | `src/agents/final_answer_agent.py` |
| 验证 Agent | `src/agents/verifier_agent.py` |
| 缺口修复 Agent | `src/agents/gap_resolver_agent.py` |
| Blackboard | `src/agents/research_blackboard.py` |
| RAG 入口 | `src/retrieval/retrieve.py` / `retrieve_evidence_with_mode()` |
| BM25 | `src/retrieval/bm25_index.py` |
| Chroma / vector fallback | `src/retrieval/chroma_index.py` |
| EvidenceStore | `src/retrieval/evidence_store.py` |
| 财务质量守卫 | `src/data/financial_quality.py` |
| 财务指标标准化 | `src/data/financial_statement_metrics.py` |
| Chat 三层记忆 | `src/app/agent_chat.py` |
| Durable memory | `src/agents/durable_memory.py` / `DurableMemoryStore` |
| SkillRegistry | `src/tools/skill_registry.py` |
| Skill 配置 | `configs/skill_registry.yaml` |
| MCP Manager | `src/utils/mcp_manager.py` |
| MCP HTTP Server | `src/utils/mcp_http_server.py` |
| 客观质量评测 | `src/evaluation/report_quality.py` |
| LLM 质量复核 | `src/evaluation/llm_report_review.py` |
| Delivery Gate | `src/evaluation/delivery_gate.py` |
| Company scorecard | `src/evaluation/company_report_scorecard.py` |
| 多 Agent harness | `src/evaluation/multi_agent_harness.py` |
| Memory ablation | `scripts/run_memory_ablation.py` |
| Competition runner | `scripts/run_competition.py` |
