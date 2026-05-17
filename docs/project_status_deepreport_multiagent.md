# DeepReport++ 项目状态与下一步计划

> 维护规则（2026-05-16 更新）：每次开工必须先读本文档和 `docs/web_ui_multimodal_workbench.md`；每完成一个功能必须记录改动、验证命令、质量结果、遗留问题和下一步，并单独提交一次 git。Chat memory 只用于用户偏好和任务上下文，不替代 evidence/citation/verifier。报告只有同时通过 verifier、本地 objective quality eval、LLM/Codex 主观 review，才标记为可交付。

## 2026-05-16 Chat-first 与质量门禁任务

- 当前最高优先级：把 Web UI 改为 ChatGPT-like 首屏，让用户只输入“生成某公司最新财报研报”即可触发解析、memory、实时数据、多 Agent 生成、质量评测和报告链接返回。
- 当前质量短板：600519.SS 与 AMD 样本仍存在空章节、估值/同行缺失、period/source 混入、数值格式不专业、报告质量 gate 偏宽等问题。
- 本轮执行顺序：编码与文档基线 -> Chat-first UI -> 自然语言解析与 memory 默认应用 -> 本地 objective quality eval -> LLM/Codex review -> Chat 链路接入 delivery gate -> 双样本质量修复 -> 重跑记录。

<!-- 以下为历史状态记录；新工作记录以本文档顶部和 docs/web_ui_multimodal_workbench.md 为准。 -->

更新日期：2026-05-16

本文档是当前 DeepReport++ 项目的唯一主状态文档。以后项目说明、阶段总结、下一步计划和验证记录默认使用中文，并优先更新本文档。

当前有效工作目录是：

```text
/Users/yuan_dian/AI_project/DeepReport_plus_main_clean
```

不要再把父目录、旧 zip 解压目录、`DeepReport_plus` 旧工作区或历史归档内容当作当前主线项目；旧工作区只可作为补丁来源参考。

## 最新更新

- 当前仓库主线是 `/Users/yuan_dian/AI_project/DeepReport_plus_main_clean`，分支为 `main`。
- 2026-05-16 主线目录已明确为 `/Users/yuan_dian/AI_project/DeepReport_plus_main_clean`；旧 `DeepReport_plus` 只用于参考未迁移补丁。
- P3 已完成静态 `SkillRegistry` MVP：新增 `src/tools/skill_registry.py`，定义 `SkillSpec`、选择/摘要渲染、金融技能默认目录，并接入 PlanningAgent prompt 与 dynamic router task metadata/trace。
- P3 继续升级：新增 `configs/skill_registry.yaml`，`SkillRegistry` 现在优先从 YAML 加载技能目录；默认技能已扩展到 `industry_research` 和 `macro_context`。
- Memory brief 已从“开启后进入所有上下文”收敛为默认 `planner_router` scope：`configs/app.yaml` 新增 `memory.durable.context_scope: planner_router`，Planner 可看到 durable memory hint，普通 agent 默认不继承全部历史上下文。
- 已补回旧工作区缺失的 competition/docx 交付链路：新增 `src/report/docx_exporter.py` 和 `scripts/run_competition.py`，可生成 Company/Industry/Macro 三份 DOCX 和 `results.zip`；随后已升级为调用专用 Industry/Macro 本地 Agent 生成交付内容。
- P5 已完成本地专用 Industry/Macro 交付 Agent：新增 `src/agents/industry_research_agent.py` 与 `src/agents/macro_research_agent.py`，`scripts/run_competition.py` 已改为调用这两个 Agent 生成行业/宏观 Markdown/JSON/DOCX，而不是固定占位文本。
- 本轮新增验证覆盖：`tests/test_skill_registry.py`、`tests/test_docx_exporter.py`、`tests/test_competition_runner.py`，并补充 dynamic workflow 对 skill routing、planner-router memory scope、`task_route_context.json` 的断言。
- 本轮继续新增验证覆盖：`tests/test_competition_agents.py`，并扩展 `tests/test_competition_runner.py` 检查 Industry/Macro Agent 生成器和 JSON 产物。
- 本轮完成 P2/P3/P5 最后一轮优化：新增 `src/data/evidence_metadata.py`，为 evidence 统一补齐 `source_timestamp`、`data_cutoff`、`freshness_bucket`、`evidence_scope`；`src/evaluation/multi_agent_harness.py` 已输出 unsupported fallback、verification pass、numeric/citation audit、skill routing 指标。
- 本轮新增独立数据源 v1：`src/data/independent_sources.py` 接入 FRED、BLS、BEA、Federal Reserve、SEC EDGAR companyfacts 的适配器；`configs/data_sources.yaml` 新增对应配置；`SearchManager` 新增 `independent_macro` 与 `sec_edgar` 引擎，默认不联网，显式 `enable_remote=True` 或 `--realtime-data` 才拉取远程数据。
- 本轮新增 `scripts/run_realtime_data_smoke.py`，用于 DeepSeek API + 实时数据源 smoke；当前环境未设置 `DEEPSEEK_API_KEY`，脚本会记录 `missing_api_key` 并安全跳过模型调用。
- 已从 `docs/cloud_readiness.md` 同步云端调试结论：新增 `scripts/run_competition.py --baseline-deepseek-workflow` 桥接模式，用 DeepSeek 风格 rich draft 保留可读性，再由当前 evidence audit 分层标注“已证实 / 待补证 / 不支持”，避免 strict/realtime 路线把缺证据内容误当成最终结论。
- 已同步云端 UI 修复：HTML 报告 Chart.js 容器固定高度，避免图表撑开页面；Web UI 报告页优先只展示 HTML iframe，不再在下方重复追加 Markdown 源文。
- 本轮 DeepSeek API 已通过本地 `.env` 连通；Company 主链 realtime 模式已拓宽为 `local_real_data + sec_edgar + yahoo_finance + eastmoney + independent_macro + local_evidence`，并把 `enable_remote` 传入 DeepResearcher/SearchManager，使 SEC companyfacts 能直接进入公司主报告。
- 本轮 API 实跑两家公司研报：`600519.SS` 输出 `eval_outputs/api_validation_20260516_600519SS_deepseek_broadened_v2/`，`competition_passed=true`、`company_report_score=0.625`；`AMD` 输出 `eval_outputs/api_validation_20260516_AMD_deepseek_broadened_v2/`，`competition_passed=true`、`company_report_score=0.6667`，且 Company 报告已引用 SEC companyfacts。
- 本轮新增 Agent Chat 工作台 v1：`src/app/agent_chat.py` 提供 Chat Router、短期滑动窗口、长期语义/TF 混合记忆、用户偏好规则抽取和本地 JSON 持久化；`src/app/web_ui.py` 新增 `/api/chat`、研究助手面板、三层记忆开关、Chat 启动研报开关和“思考/动作/观察/验证”时间线。
- Agent Chat 的边界已固定：memory 只作为上下文、偏好和路由提示，不替代 `evidence_id`、citation、numeric audit 或 verifier；Chat 启动研报时仍进入现有 `MultiAgentOrchestrator` 多 Agent 主链。
- 本轮补齐 A 股正式数据源 v1：`SearchManager` 新增 `cninfo_announcements`、`exchange_announcements`、`eastmoney_financials` 三个引擎；`configs/data_sources.yaml` 新增巨潮、上交所/深交所、东方财富财务表配置；source authority 将巨潮/交易所公告和东方财富财务表标为 primary，可支撑核心财务 claim。
- 本轮修复实时检索 source diversity：避免 topK 被同一类巨潮公告占满，并修复东方财富三张财务表共用 URL 被去重折叠的问题；东方财富财务表现在按 `period` 选择目标报告期，例如 `2025Q4` 优先选择 `2025-12-31`。
- 本轮完成下一阶段数据层补强 v1：新增统一三表指标标准化，将东方财富 income/balance/cashflow 与 SEC companyfacts 写入 `financial_metrics.json`、三表 rows 和 table artifacts；A 股 fast realtime 会保留东方财富三表各 1 条 evidence；新增 PDF artifact v1，输出 `pdf_manifest.json`、`pdf_sections.json`、`company_profile_extracted.json`，缺 PyMuPDF 或下载失败时记录 failure reason 而不中断主链。
- 本轮补强 rich baseline 桥：`--baseline-deepseek-workflow` 额外输出 `evidence_grounded_rewrite.json`，按 claim 记录 rich draft claim、matched evidence、rewrite result 与 verifier status。
- 本轮补齐 Chat UI smoke：新增 `scripts/run_chat_ui_smoke.py`，通过 `/api/chat` 验证普通 chat、RAG 路由、报告启动、tool_trace 和三层记忆写入；`AgentChatService` 报告路由响应会回填 `verification_passed` / `verifier_passed`。
- 本轮实跑评测：`eval_outputs/next_data_review_600519SS_2025Q4/` 通过，`company_report_score=0.9375`，evidence 包含巨潮 2、交易所 2、东方财富三表 3、市场 1；`eval_outputs/next_data_review_AMD_2025Q4/` 通过，`company_report_score=0.8542`，evidence 包含 SEC companyfacts、Yahoo market snapshot、BLS。Chat UI smoke 输出 `eval_outputs/chat_ui_smoke_next/`，`passed=true`。
- 本轮继续动态调整：PDF artifact manifest 已拆分 `cache_status` 与 `extraction_status`，当前 600519 两份巨潮 PDF 均已缓存到 `pdf_cache/` 并记录 sha256/size；本机缺 PyMuPDF 时只标记抽取失败，不再把缓存结果视为整体失败。新增 `scripts/summarize_next_data_review.py`，可汇总 A 股、美股和 Chat UI smoke 到 `eval_outputs/next_data_review_summary.json/md`。
- 本轮开始基线：`7ddf800 Add guarded durable memory foundation`。
- 主状态文档已改为中文，并把后续维护规则固定为中文。
- 本次继续补齐 P2：新增 `scripts/run_memory_ablation.py`，可从现有 multi-agent evaluation config 派生 `memory_enabled` / `memory_disabled` 两个 variant，输出 `memory_ablation_comparison.json` 和 `memory_ablation_comparison.md`。
- 当前 durable memory 已有默认关闭的基础工程能力和可复现 ablation runner；但它仍不是默认开启能力，必须通过质量/延迟门禁后才能进入更宽 smoke 或默认配置。
- 本轮新增本地 Ollama/qwen3 配置并完成 1 个 AAPL 样本的真实 ablation：`eval_outputs/memory_ablation_ollama_qwen3_20260515/memory_ablation_comparison.json`，结论为 `promote_memory`，但样本数仍太小，不能直接改成默认开启。
- 本轮真实复跑暴露并修复了 `build_trend_features` 对缺失 `symbol/period/sample_id` 的脆弱路径，避免动态任务拿到非标准 evidence records 时中断整份报告。
- 本轮回答并固定报告时效性边界：当前 Ollama/qwen3 ablation 报告只基于 `local_real_data` / `local_evidence` 提供的本地证据，不代表联网最新信息；模型本身不负责抓取实时数据。
- 本轮扩大到 AAPL/GOOGL/MSFT 三公司样本复跑，并修复 planner 乱序/反向依赖导致的 evidence 断链问题；修复后产物为 `eval_outputs/memory_ablation_ollama_qwen3_3company_after_dep_fix_20260515/memory_ablation_comparison.json`，结论为 `promote_memory`。
- 已完成 P1 仓库真实能力复核：`scripts/`、`configs/`、`src/agents/`、`src/evaluation/` 中的当前主线能力已经按真实文件重新登记；README 和 AGENTS 用 UTF-8 读取为正常中文，本轮不做编码修复。
- P2 Memory 正式工程化已完成第二阶段：`src/agents/durable_memory.py` 提供基础存取层，`scripts/run_memory_ablation.py` 提供 enabled/disabled 对照与质量/延迟 guard；开启后只注入“历史上下文提示”，不替代 evidence/citation/verifier 质量门禁。
- Chat-facing 三层记忆已完成 v1 工程落点：短期记忆在进程内按 session 滑动窗口保存；长期记忆写入 `memory/chat/long_term/`，优先使用 BGE/Chroma 相关 embedding 能力，缺依赖时降级到 hash/TF 混合；用户偏好写入 `memory/chat/users/`，规则即时生效，后续可再加 LLM NER 异步增强。

## 当前结论

DeepReport++ 当前主线是一个面向金融研报的证据驱动、多 Agent 报告生成工程。项目已经具备基础报告流水线、动态多 Agent 任务图、报告格式修复、图表 lineage 校验、durable memory guard、可配置 SkillRegistry、competition/docx packaging smoke，以及本地 Industry/Macro 交付 Agent。

当前 memory 与 SkillRegistry 的状态应准确表述为：durable memory 默认关闭，显式开启后默认只作为 Planner/Router 历史提示，不替代 evidence/citation/verifier；SkillRegistry 已完成 YAML 配置化和 Planner/Router 摘要注入、trace 记录与 harness 指标，但还不是自学习技能系统。Company 研报主链可运行；Industry/Macro 交付已由专用本地 Agent 生成，并已具备 SEC/宏观/政策独立 evidence v1 适配器，但远程实时拉取默认关闭，只有显式 `--realtime-data` 且具备 API key/网络时才会进入报告。

## 已完成

### 工程骨架与基础流水线

- Stage -1 到 Stage 10 的主工程骨架已位于仓库根目录。
- claim-first 基础链路已经存在：
  `src/app/main.py -> src/app/pipeline.py -> src/agents/orchestrator.py`。
- 报告导出、模板、图表、引用、验证、schema、data、features、retrieval、generation、training、evaluation 等模块目录已建立。
- generation backend 已抽象到 `src/generation`，包含 mock / local-small / remote 风格实现。

### 多 Agent 基础链路

- 当前多 Agent 入口在 `src/agents/multi_agent_orchestrator.py`。
- 当前可见链路为：
  `PlanningAgent -> DeepResearcherAgent -> BrowserAgent -> DeepAnalyzeAgent -> FinalAnswerAgent -> VerifierAgent`。
- `src/agents/conversation_memory.py` 已提供 run-level conversation memory 和上下文压缩能力。
- `src/agents/durable_memory.py` 已提供文件化 durable memory 存取层，默认关闭，开启后写入 working / episodic / domain 三类 memory 产物。
- `src/tools/skill_registry.py` 已提供可配置金融技能目录，Planner/Router 可按 task_type 与 query 选择并注入 skill brief。
- `src/agents/industry_research_agent.py` 与 `src/agents/macro_research_agent.py` 已提供本地行业/宏观交付 Agent。
- `src/data/independent_sources.py` 已提供 FRED/BLS/BEA/Federal Reserve/SEC EDGAR companyfacts 的独立证据适配器；无 key 或未启用远程时输出可追踪 skip/failure reason。
- `src/data/evidence_metadata.py` 已统一 evidence freshness/cutoff/scope 元数据，避免把模型记忆或无时效来源当作实时事实。
- `src/agents/planning_agent.py`、`src/agents/gap_router.py`、`src/evaluation/multi_agent_harness.py` 为 Planner/Router 策略、gap routing 与评估接入提供基础。

### 交付与包装链路

- `src/report/docx_exporter.py` 可将 Markdown 报告导出为 DOCX；优先使用 `python-docx`，缺依赖时使用轻量 OOXML fallback。
- `scripts/run_competition.py` 可运行本地 competition packaging smoke，生成公司/行业/宏观三份 DOCX 和 `results.zip`。
- `scripts/run_competition.py --baseline-deepseek-workflow` 可生成 `baseline_deepseek_report.md/json`，用于把 rich baseline 写作与当前多智能体证据审计连接起来。该模式不会放宽 verifier 或 citation 门禁：缺证据内容只进入“待补证 / 不支持”分层，不能当作最终可验证结论。
- Industry/Macro 报告现在由 `IndustryResearchAgent` / `MacroResearchAgent` 生成，并可合并独立 evidence records；默认仍可只基于公司主链 artifacts 离线打包，显式 `--realtime-data` 时会尝试拉取 SEC/宏观/政策证据，并额外输出 `industry_report.json` / `macro_report.json`。
- Company 主链的 `--realtime-data` 现在也会把 SEC EDGAR、Yahoo Finance、Eastmoney 和独立宏观 evidence 纳入搜索候选；其中 SEC companyfacts 已能生成确定性营收、净利润、资产和现金类 claim。

### 报告质量修复

- `FinalAnswerAgent` 已做报告标题规范化。
- 当本地模型漏写或改写公司研报章节标题时，`FinalAnswerAgent` 可根据 claims 做确定性章节补齐。
- 图表 lineage 已支持 claim-text 派生图表的合理通过路径。
- 相关测试包括：
  `tests/test_priority1_metric_fixes.py`、
  `tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections`。

### 已提交评估产物

- 本地 qwen3 canary 产物：
  `eval_outputs/codex_phase5b_qwen3_after_format_fix/eval_summary.json`。
- 该 canary 记录显示：
  `task_completion_rate=1.0`、
  `required_sections_coverage=1.0`、
  `verification_pass_rate=1.0`、
  `citation_support_rate=1.0`、
  `numeric_audit_pass_rate=0.9373`、
  `valuation_sanity_pass_rate=1.0`。
- memory ablation 产物：
  `eval_outputs/codex_phase5c_memory_ablation_after_format_fix/memory_ablation_comparison.json`。
- 该产物记录的结论为：
  `memory_has_measurable_benefit`。
- 本轮本地 Ollama/qwen3 复跑产物：
  `eval_outputs/memory_ablation_ollama_qwen3_20260515/memory_ablation_comparison.json`。
- 本轮复跑结论为：
  `decision=promote_memory`；
  `verification_pass_rate` 从 `0.0` 到 `1.0`；
  `contest_checklist_pass_rate_mean` 从 `0.7889` 到 `0.9514`；
  `numeric_accuracy` 保持 `1.0`；
  `latency_delta_sec=0.929`。
- 本轮三公司复跑产物：
  `eval_outputs/memory_ablation_ollama_qwen3_3company_after_dep_fix_20260515/memory_ablation_comparison.json`。
- 三公司复跑结论为：
  `decision=promote_memory`；
  `verification_pass_rate` 两组均为 `0.6667`；
  `evidence_coverage_mean` 两组均为 `1.0`；
  `contest_checklist_pass_rate_mean` 从 `0.8677` 到 `0.8951`；
  `numeric_accuracy` 保持 `1.0`；
  `latency_delta_sec=-5.0106`。

## 当前代码与历史产物差异

### 当前代码中可以确认存在

- `src/agents/conversation_memory.py`：会话级 memory / context brief。
- `src/agents/durable_memory.py`：文件化 durable memory store，负责历史 run snapshot、episodic memory、domain memory 和 bounded context brief。
- `src/agents/multi_agent_orchestrator.py`：多 Agent 编排入口。
- `src/agents/planning_agent.py`：规划 Agent。
- `src/agents/industry_research_agent.py`：基于公司主链 artifacts 生成行业研究报告。
- `src/agents/macro_research_agent.py`：基于公司主链 artifacts 生成宏观传导框架报告。
- `src/agents/gap_router.py`：gap resolution trace 相关能力。
- `src/tools/skill_registry.py`：SkillRegistry、SkillSpec schema、YAML 配置加载、query/task_type 选择和 prompt brief 渲染。
- `src/report/docx_exporter.py`：Markdown 到 DOCX 导出器，带 `python-docx` / OOXML fallback。
- `src/evaluation/`：多类评估、诊断、numeric/citation/multimodal audit 基础。
- `eval_outputs/`：已提交的 qwen3 canary 和 memory ablation 结果文件。
- `data/eval_v1/memory_ablation_3company_cases.jsonl`：AAPL/GOOGL/MSFT 三公司 memory ablation 小样本集。
- `scripts/run_multi_agent_demo.py`：当前多 Agent demo 入口，支持 `--execution-mode`、`--fast`、`--retrieval-ranking-mode`、`--engines`。
- `scripts/run_multi_agent_eval.py`：调用 `src.evaluation.multi_agent_harness` 的动态多 Agent 评估入口。
- `scripts/run_memory_ablation.py`：基于现有 multi-agent evaluation config 派生 memory enabled/disabled 对照评估，并生成质量/延迟门禁结论。
- `scripts/run_competition.py`：本地 competition packaging smoke，生成 Company/Industry/Macro DOCX 和 `results.zip`。
- `scripts/run_realtime_data_smoke.py`：独立数据源与 DeepSeek smoke；未启用远程或缺 key 时记录 skip reason，有 key 时把独立 evidence 写入 Industry/Macro JSON/DOCX。
- `configs/skill_registry.yaml`：默认金融技能目录配置。
- `configs/model_backends.yaml`、`configs/data_sources.yaml`、`configs/evaluation_multi_agent_react_smoke.yaml`、`configs/evaluation_stage12a.yaml`：当前可见的模型、数据源和评估配置。
- `configs/model_backends_local_ollama.yaml`：本地 Ollama/qwen3 OpenAI-compatible 模型配置，默认使用 `qwen3:8b`。
- `configs/evaluation_memory_ablation_ollama.yaml`：本地 qwen3 memory ablation 小样本评估配置。
- `configs/app.yaml`：已包含 `memory.durable` 开关、根目录、上下文长度、保留条数和 `context_scope: planner_router` 配置。

### 当前仓库尚未完整实现

- 尚未把本地 qwen3 memory 配置推广为默认模型配置。
- 尚未接入完整行业数据库或付费宏观终端；当前已完成独立数据源 v1 适配器，但远程拉取默认关闭，不能把“适配器存在”表述为“完整行业/宏观数据库覆盖”。

### 需要补回或正式工程化

- 更完整的 memory 选择策略、过期策略，以及真实数据源接入后的时效性标注。
- 更细的行业专用数据源策略，例如 TAM、市场份额、产业链价格、供需周期和监管分类。
- 当前评估产物与未来可复现脚本之间的追溯关系。

## 仓库代码结构

- `configs/`：运行配置、模型后端配置、数据源配置、评估配置。
- `scripts/`：本地 smoke、评估、UI/server、云端上传下载脚本。
- `src/app/`：CLI 与 pipeline 入口。
- `src/agents/`：基础 Agent、多 Agent 编排、规划、研究、分析、最终报告、验证、会话上下文。
- `src/data/`：fetcher、标准化、manifest、公司识别、数据源质量、evidence freshness/cutoff 元数据和独立数据源适配器。
- `src/features/`：财务指标、三表、趋势、同行对比、风险、估值、metric lineage。
- `src/retrieval/`：evidence store、BM25、Chroma/local RAG、检索 facade、FAISS 占位。
- `src/generation/`：生成后端抽象、writer/rewriter 模型访问。
- `src/evaluation/`：评估 harness、numeric/citation/multimodal audit、scorecard、诊断报告。
- `src/report/`：引用、图表、图文一致性、合规披露、HTML 报告增强。
- `src/templates/`：公司研报大纲、Markdown/HTML 模板、导出器。
- `src/schemas/`：Evidence、Claim、Chart、Report、Task、multimodal、table 数据契约。
- `tests/`：当前 root 项目的单元、集成、smoke 和回归测试。
- `eval_outputs/`：当前已提交的 canary 与 ablation 评估产物。

## 有效文档

当前保留为有效参考或契约的文档：

- `docs/project_status_deepreport_multiagent.md`：当前状态与下一步计划，也就是本文档。
- `docs/deepreport_repo_audit.md`：上游 DeepReport 审计。
- `docs/deepreport_skeleton_mapping.md`：DeepReport 到 DeepReport++ 的骨架映射。
- `docs/deepreport_reference_architecture.md`：参考架构说明。
- `docs/real_data_contract.md`：真实数据契约。
- `docs/cloud_training.md`、`docs/cloud_readiness.md`：云端训练与准备说明。
- `docs/company_agent_architecture.md`、`docs/company_stock_report_depth_plan.md`、`docs/financial_multi_agent_detailed_guide.md`：仍有参考价值的产品与架构说明。

不再作为当前计划依据：

- 旧 `docs/current_status.md`，其有效信息已经合并到本文档。
- 旧 review backfill、grounding-rule experiment、Stage 12 judgement、writer backend recap、acceptance report、regression guide 等历史复盘文档。
- 旧 `CODEX_RUNBOOK.md` 和 `Open_DeepReportpp_Stage12_Local_Plan.md`。

## 当前风险

- qwen3 canary 与历史 memory ablation 产物已提交；当前仓库现在已有可复跑的 memory ablation runner，并已完成 1 个样本和 3 公司样本复跑，但样本规模仍偏小，后续进入默认配置前仍需更宽 case set。
- Durable memory 现在已有默认关闭的基础存取层、enabled/disabled 质量/延迟 guard 和 `planner_router` scope；仍不建议直接默认开启全部历史上下文。
- 当前报告时效性取决于证据源，不取决于本地模型记忆；若只启用 `local_real_data` / `local_evidence`，报告只能覆盖本地数据和索引证据，不能宣称联网最新。
- SkillRegistry 当前已配置化并接入 harness 指标，但仍不是在线学习或自动发现技能；后续需要用更宽 case set 观察是否实际改善 unsupported fallback、verification pass、numeric/citation audit。
- competition/docx 交付链路已补回，Industry/Macro 也已有专用本地 Agent 与独立 evidence v1；但远程实时源需要显式 `--realtime-data`、API key 和网络，仍不能宣称已覆盖完整行业数据库或全球宏观数据库。
- `baseline_deepseek_workflow` 是质量桥接模式，不是 strict/realtime 的替代品；它适合生成 rich draft 并做审计分层，但最终比赛打包和回归测试仍以 evidence、citation、numeric audit、verifier 结果为准。
- A 股正式数据源已完成 v1 接入：巨潮公告、上交所/深交所公告索引、东方财富利润表/资产负债表/现金流量表可进入 evidence；但 PDF 正文/表格深抽取、公告附件缓存、A 股行业/股权/管理层专项结构化仍是后续缺口。
- PDF artifact v1 已能建 manifest 并缓存 PDF；当前 Windows 本地评测环境缺 PyMuPDF 时 `cache_status=cached`、`extraction_status=failed`、`extraction_failure_reason=pymupdf_unavailable`，因此仍不能宣称 PDF 正文抽取已稳定覆盖 A 股年报。
- FRED 与 BEA 当前仍因缺少 API key 记录为 `missing_api_key`；BLS/Federal Reserve 可用，但不能等价为完整宏观数据库覆盖。
- `AGENTS.md` 和部分 `README.md` 在当前 Windows 输出里有 mojibake，后续如果作为 onboarding 文档，需要单独修复编码/内容。

## 下一步计划

### P0：中文状态文档修正

- 已在本轮执行：本文档改为中文。
- 已在本轮执行：校准 memory / SkillRegistry 的真实状态。
- 后续所有任务完成后，都必须更新本文档的“最新更新、已完成、当前风险、下一步计划、验证记录”。

### P1：仓库真实能力复核

状态：已在本轮完成。

- 已复核 `src/agents`、`src/evaluation`、`scripts`、`configs` 的当前真实文件。
- 已明确区分“当前代码中存在”“仅有评估产物”“当前仓库尚未发现完整实现”“下一步要补回或正式工程化”。
- README 和 AGENTS 用 UTF-8 读取为正常中文；本轮不做内容改写，后续若发现与实际主线不一致再单独处理。

### P2：Memory 正式工程化

状态：第二阶段已完成，并已完成 1 个样本和 3 公司样本两轮本地 qwen3 复跑；Planner/Router memory 选择策略已接入静态版本。

1. 已完成：基于 `conversation_memory.py` 增加 `DurableMemoryStore`，写入 working / episodic / domain memory。
2. 已完成：增加 `memory_enabled`、memory root、上下文长度、保留条数和 `context_scope` 配置；默认关闭，显式开启才影响 prompt。
3. 已完成：接入 `MultiAgentOrchestrator` 的 planning context brief；默认 `planner_router` scope 只让 Planner/Router 使用 durable memory hint，brief 明确标注不能作为证据，报告事实仍必须走 evidence/citation/verifier。
4. 已完成：增加 durable memory 单测和多 Agent enabled/disabled smoke 测试。
5. 已完成：新增可复现的 memory enabled/disabled ablation runner：`scripts/run_memory_ablation.py`。
6. 已完成：runner 输出质量/延迟 guard，比较 verifier、evidence coverage/alignment、chart consistency、contest checklist、numeric audit 和平均耗时。
7. 已完成：用本地 Ollama `qwen3:8b` 跑通 1 个 AAPL 样本的 memory ablation，产物位于 `eval_outputs/memory_ablation_ollama_qwen3_20260515/`。
8. 已完成：扩大到 AAPL/GOOGL/MSFT 三公司样本复跑；修复 planner 乱序/反向依赖后，memory enabled 通过质量/延迟门禁。
9. 已完成：将稳定通过门禁的 memory brief 选择策略接入 Planner/Router，并避免默认把全部历史上下文注入普通 agent。
10. 已完成：给 evidence 与 Industry/Macro 报告增加 `source_timestamp`、`data_cutoff`、`freshness_bucket`、`source_boundary`，避免用户误以为本地模型具备实时联网信息。

### P3：SkillRegistry 正式接入

状态：YAML 配置化 MVP 与 harness 指标接入已完成，后续进入更宽样本策略评估阶段。

1. 已完成：实现静态 SkillRegistry MVP：`SkillSpec`、`SkillRegistry`、默认金融技能目录。
2. 已完成：定义 skill schema、metadata、摘要字段和测试。
3. 已完成：让 Planner/Router 可选择性读取 skill 摘要；dynamic route 输出 `task_route_context.json`，task trace 记录 `selected_skills`。
4. 已完成：将 skill registry 从硬编码静态目录升级为 `configs/skill_registry.yaml` 配置化目录，并加入 Industry/Macro skills 入口。
5. 已完成：在评估指标中跟踪 unsupported fallback、verification pass、numeric/citation audit、skill routing 命中率和 selected skill 分布，用于观察 routing 是否稳定改善质量。

### P4：重新跑本地验证与交付链路

状态：本轮 targeted tests、多 Agent dynamic smoke、competition/docx packaging smoke、Industry/Macro Agent 交付测试、独立数据源单元测试与 realtime smoke 已通过；DeepSeek 当前因缺少 `DEEPSEEK_API_KEY` 记录为 `missing_api_key` 安全跳过。qwen3 最终提交路径继续使用 `configs/model_backends_local_ollama.yaml` + `scripts/run_competition.py`。

1. 已完成：跑 SkillRegistry、ToolRegistry、config、DOCX、competition runner targeted tests。
2. 已完成：跑多 Agent dynamic smoke 与 durable memory scope 回归测试。
3. 条件完成：已保留 qwen3/Ollama 最终交付路径；若本地 Ollama 服务在线，可用 `python scripts/run_competition.py --config configs/model_backends_local_ollama.yaml --symbol AAPL --period 2025Q4 --fast` 复跑最终本地交付。
4. 已完成：重新验证 competition packaging 和三类 DOCX/zip 交付链路。
5. 已完成：新增 `scripts/run_realtime_data_smoke.py`，缺 key 时记录 `missing_api_key`/`remote_sources_disabled`，有 key 和网络时可把实时独立 evidence 写入 Industry/Macro JSON 与 DOCX。

### P5：Industry/Macro 本地交付 Agent

状态：基础版已完成，并升级到独立数据源 v1。

1. 已完成：新增 `IndustryResearchAgent`，基于公司 summary、evidence、claims、peer context 生成行业报告 Markdown/JSON。
2. 已完成：新增 `MacroResearchAgent`，基于公司 summary、market evidence 和验证状态生成宏观传导框架报告 Markdown/JSON。
3. 已完成：`scripts/run_competition.py` 调用专用 Agent 生成 Industry/Macro DOCX 和 JSON 产物，不再输出固定占位文案。
4. 已完成 v1：接入 FRED、BLS、BEA、Federal Reserve、SEC EDGAR companyfacts 适配器；`IndustryResearchAgent` / `MacroResearchAgent` 已消费 `independent_evidence_records`，报告 JSON/Markdown 中输出 `independent_evidence_count`、`freshness_summary`、`source_boundary`。
5. 后续增强：行业完整 TAM、份额、供需周期等仍需要更细的行业数据库或行业特定官方源；当前 v1 重点是把独立权威 evidence 入口和真实边界建立起来。

## 验证记录

本轮文档中文化后需要执行：

```powershell
git status --short
git diff -- docs/project_status_deepreport_multiagent.md
python -m pytest tests/test_priority1_metric_fixes.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections -q
python -m pytest tests/test_config_loader.py tests/test_schemas.py tests/test_generation_backends.py -q
```

本轮验证结果：

- `git status --short`：显示 `docs/project_status_deepreport_multiagent.md` 已修改。
- `git diff -- docs/project_status_deepreport_multiagent.md`：确认主状态文档已全量中文化，并校准了 memory / SkillRegistry 当前真实状态。
- `python -m pytest tests/test_priority1_metric_fixes.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections -q`：`8 passed`。
- `python -m pytest tests/test_config_loader.py tests/test_schemas.py tests/test_generation_backends.py -q`：`12 passed`。
- P1 复核命令：
  `rg --files scripts configs src/agents src/evaluation`、
  `rg "class |def |if __name__|argparse|click" scripts src/agents src/evaluation -n`、
  `Get-Content -Encoding UTF8 README.md`、
  `Get-Content -Encoding UTF8 AGENTS.md`。
- P1 复核结论：当前主线能力、评估产物和缺失模块已登记到本文档；README/AGENTS 当前 UTF-8 读取正常。
- P2 第一阶段验证命令：
  `python -m pytest tests/test_durable_memory.py -q`：`2 passed`。
- P2 多 Agent 质量保护验证命令：
  `python -m pytest tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_can_persist_durable_memory_without_quality_regression -q`：`2 passed`。
- P2 验证结论：默认关闭 memory 时现有动态链路不写 durable memory；显式开启 memory 时报告仍通过 verifier，citation/chart 输出保持有效，并写入 durable memory artifacts。
- P2 最终门禁命令：
  `python -m pytest tests/test_durable_memory.py tests/test_priority1_metric_fixes.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_can_persist_durable_memory_without_quality_regression -q`：`12 passed`。
- P2 扩展 smoke 命令：
  `python -m pytest tests/test_config_loader.py tests/test_schemas.py tests/test_generation_backends.py -q`：`13 passed`。
- P2 第二阶段 memory ablation runner 验证命令：
  `python -m pytest tests/test_memory_ablation_runner.py tests/test_multi_agent_harness.py -q`：`7 passed`。
- P2 第二阶段质量保护回归命令：
  `python -m pytest tests/test_durable_memory.py tests/test_priority1_metric_fixes.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_can_persist_durable_memory_without_quality_regression -q`：`12 passed`。
- P2 第二阶段扩展 smoke 命令：
  `python -m pytest tests/test_config_loader.py tests/test_schemas.py tests/test_generation_backends.py -q`：`13 passed`。
- P2 第二阶段验证结论：`scripts/run_memory_ablation.py` 已能生成 memory enabled/disabled 双 variant 配置，并在结果汇总中按 verifier、evidence、chart、contest checklist、numeric audit 和 latency 输出 `promote_memory` / `hold_memory` / `reject_memory` 决策。
- 本轮本地 qwen3 连通性验证：
  `ollama list`：确认存在 `qwen3:8b`；
  `python` 通过 `ModelAdapter.from_config('configs/model_backends_local_ollama.yaml')` 调用本地 OpenAI-compatible endpoint 成功。
- 本轮真实 ablation 命令：
  `python scripts/run_memory_ablation.py --config configs/evaluation_memory_ablation_ollama.yaml --run-id memory_ablation_ollama_qwen3_20260515 --max-samples 1 --latency-tolerance-sec 45`：首次暴露 `build_trend_features` 缺字段 `KeyError: 'symbol'`；修复后复跑成功，输出 `decision=promote_memory`。
- 本轮真实 ablation 指标：
  memory disabled：`verification_pass_rate=0.0`、`contest_checklist_pass_rate_mean=0.7889`、`numeric_accuracy=1.0`、`avg_duration_sec=136.575`；
  memory enabled：`verification_pass_rate=1.0`、`contest_checklist_pass_rate_mean=0.9514`、`numeric_accuracy=1.0`、`avg_duration_sec=137.504`；
  `latency_delta_sec=0.929`。
- 本轮三公司样本文件：
  `data/eval_v1/memory_ablation_3company_cases.jsonl`：包含 AAPL、GOOGL、MSFT 各 1 个 2025Q4 fundamental case。
- 本轮三公司 ablation 初跑：
  `python scripts/run_memory_ablation.py --config configs/evaluation_memory_ablation_ollama.yaml --eval-case-path data/eval_v1/memory_ablation_3company_cases.jsonl --run-id memory_ablation_ollama_qwen3_3company_20260515 --max-samples 3 --latency-tolerance-sec 45`：输出 `decision=hold_memory`；随后定位为 planner 输出乱序/反向依赖导致 AAPL disabled 未把 research evidence 传入 analyze，并已清理该诊断残留产物。
- 本轮动态任务依赖修复验证命令：
  `python -m pytest tests/test_multi_agent_workflow.py::test_prepare_dynamic_tasks_orders_evidence_flow_even_when_planner_outputs_tasks_out_of_order tests/test_multi_agent_workflow.py::test_prepare_dynamic_tasks_drops_reverse_dependencies_that_would_cycle_graph tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_multi_agent_harness.py tests/test_memory_ablation_runner.py -q`：`10 passed`。
- 本轮三公司 ablation 修复后复跑：
  `python scripts/run_memory_ablation.py --config configs/evaluation_memory_ablation_ollama.yaml --eval-case-path data/eval_v1/memory_ablation_3company_cases.jsonl --run-id memory_ablation_ollama_qwen3_3company_after_dep_fix_20260515 --max-samples 3 --latency-tolerance-sec 45`：`decision=promote_memory`。
- 本轮三公司 ablation 修复后指标：
  memory disabled：`verification_pass_rate=0.6667`、`evidence_coverage_mean=1.0`、`contest_checklist_pass_rate_mean=0.8677`、`numeric_accuracy=1.0`、`avg_duration_sec=123.8033`；
  memory enabled：`verification_pass_rate=0.6667`、`evidence_coverage_mean=1.0`、`contest_checklist_pass_rate_mean=0.8951`、`numeric_accuracy=1.0`、`avg_duration_sec=118.7927`；
  `latency_delta_sec=-5.0106`。
- 2026-05-16 P3/P4 语法验证：
  `python -m py_compile src/tools/skill_registry.py src/agents/planning_agent.py src/agents/multi_agent_orchestrator.py src/agents/deep_researcher_agent.py src/agents/deep_analyze_agent.py src/agents/final_answer_agent.py src/agents/verifier_agent.py src/report/docx_exporter.py scripts/run_competition.py`：通过。
- 2026-05-16 P3/P4 targeted tests：
  `python -m pytest tests/test_skill_registry.py tests/test_tool_registry.py tests/test_config_loader.py tests/test_docx_exporter.py tests/test_competition_runner.py -q`：`12 passed`。
- 2026-05-16 多 Agent route/memory 回归：
  `python -m pytest tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_can_persist_durable_memory_without_quality_regression tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_fast_mode_uses_smaller_context tests/test_multi_agent_workflow.py::test_prepare_dynamic_tasks_orders_evidence_flow_even_when_planner_outputs_tasks_out_of_order tests/test_multi_agent_workflow.py::test_prepare_dynamic_tasks_drops_reverse_dependencies_that_would_cycle_graph -q`：`5 passed`。
- 2026-05-16 交付链路验证结论：`scripts/run_competition.py --skip-company-run` 已在测试中基于临时 company artifacts 生成三份 DOCX 和 `results.zip`，并通过 package summary gate。
- 2026-05-16 全量回归：
  `python -m pytest -q`：通过；`tests/test_local_correction_v1.py` 和 `tests/test_report_review_zh.py` 因当前 checkout 未包含可选历史 eval/report fixtures 而按预期 skip。
- 2026-05-16 可选 fixture skip 明细：
  `python -m pytest -q -rA tests/test_local_correction_v1.py tests/test_report_review_zh.py`：`2 skipped`，原因分别为缺少 `reports/eval_v1_diagnostics/.../spot_check_10_root_cause_template.csv`、`data/evaluation/eval_v1/.../report.md` 等历史产物。
- 2026-05-16 SkillRegistry 配置化与 Industry/Macro Agent 语法验证：
  `python -m py_compile src/tools/skill_registry.py src/agents/industry_research_agent.py src/agents/macro_research_agent.py scripts/run_competition.py src/agents/multi_agent_orchestrator.py`：通过。
- 2026-05-16 SkillRegistry/competition targeted tests：
  `python -m pytest tests/test_skill_registry.py tests/test_competition_agents.py tests/test_competition_runner.py tests/test_config_loader.py -q`：`8 passed`。
- 2026-05-16 主链回归：
  `python -m pytest tests/test_tool_registry.py tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_can_persist_durable_memory_without_quality_regression tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_fast_mode_uses_smaller_context tests/test_memory_ablation_runner.py tests/test_multi_agent_harness.py tests/test_durable_memory.py -q`：`18 passed`。
- 2026-05-16 占位文案清理检查：
  `rg -n "确定性占位|尚未接入专用|dedicated Industry/Macro agents remain future work|静态 MVP" docs scripts src configs -g '!**/__pycache__/**'`：无残留匹配。
- 2026-05-16 diff 空白检查：
  `git diff --check`：通过。
- 2026-05-16 全量回归复跑：
  `python -m pytest -q -rA`：通过；除可选历史 eval/report fixtures 相关 2 个 skip 外，其余测试通过。Competition runner 输出确认 `industry_report_generated_by=IndustryResearchAgent`、`macro_report_generated_by=MacroResearchAgent`，三份 DOCX 和 `results.zip` 均生成。
- 2026-05-16 独立数据源与 freshness/cutoff 语法验证：
  `python -m py_compile src/data/evidence_metadata.py src/data/independent_sources.py src/data/source_authority.py src/data/source_quality.py src/retrieval/evidence_store.py src/search/search_manager.py src/agents/industry_research_agent.py src/agents/macro_research_agent.py src/evaluation/multi_agent_harness.py scripts/run_competition.py scripts/run_realtime_data_smoke.py`：通过。
- 2026-05-16 独立数据源 targeted tests：
  `python -m pytest tests/test_independent_sources.py tests/test_realtime_data_smoke.py tests/test_competition_agents.py tests/test_competition_runner.py tests/test_search_and_research_agent.py tests/test_source_authority_policy.py tests/test_multi_agent_harness.py -q`：`28 passed`。
- 2026-05-16 realtime data smoke：
  `python scripts/run_realtime_data_smoke.py --output-dir data/outputs/realtime_data_smoke_no_remote --symbol AAPL --period 2025Q4`：通过，`remote_data_enabled=false`，`independent_record_count=0`，`failure_reason=remote_sources_disabled`，Industry/Macro JSON 与 DOCX 均生成。
- 2026-05-16 DeepSeek 缺 key smoke：
  `python scripts/run_realtime_data_smoke.py --output-dir data/outputs/realtime_data_smoke_deepseek_missing_key --symbol AAPL --period 2025Q4 --use-deepseek`：通过，`deepseek.status=missing_api_key`，错误信息提示设置 `DEEPSEEK_API_KEY`。
- 2026-05-16 新增指标与交付 targeted tests：
  `python -m pytest tests/test_independent_sources.py tests/test_realtime_data_smoke.py tests/test_skill_registry.py tests/test_tool_registry.py tests/test_config_loader.py tests/test_docx_exporter.py tests/test_competition_agents.py tests/test_competition_runner.py tests/test_multi_agent_harness.py -q`：`26 passed`。
- 2026-05-16 diff 空白复查：
  `git diff --check`：通过。
- 2026-05-16 最终全量回归：
  `python -m pytest -q -rA`：通过；2 个 skip 仍为可选历史 eval/report fixture 缺失，非本轮功能失败。
- 2026-05-16 qwen3 本地模型连通性复查：
  `ollama list`：确认存在 `qwen3:8b`；
  `python scripts/run_deepseek_smoke.py --config-path configs/model_backends_local_ollama.yaml --prompt '用一句话回复 qwen3 本地模型 smoke 已连通。'`：通过，endpoint 为 `http://127.0.0.1:11434/v1/chat/completions`。
- 2026-05-16 qwen3 competition 长链路尝试：
  `python scripts/run_competition.py --config configs/model_backends_local_ollama.yaml --symbol AAPL --period 2025Q4 --fast --disable-memory --output-dir data/outputs/competition_qwen3_final_smoke`：首次暴露本地模型 planner 把 `evidence_records` 写成 `"evidence_records.json"` 字符串的问题，已修复 `enrich_task_parameters`，当模型输出 artifact 占位符时会回填 state 中真实 list。
- 2026-05-16 qwen3 competition 轻量路径调整：
  `scripts/run_competition.py --fast` 默认收窄为 `search_engines=["local_real_data"]`、`retrieval_ranking_mode="bm25"`；仍可通过 `--search-engines`、`--retrieval-ranking-mode` 显式切回重型检索。
- 2026-05-16 qwen3 competition 复跑说明：
  修复后复跑 qwen3 完整 competition 长链路时，本地模型生成阶段超过 6 分钟仍未完成，已手动停止并清理 ignored 输出目录；本轮上传门禁采用全量 pytest、competition packaging 单测、realtime smoke 与 qwen3 adapter smoke，不把长耗时本地模型全链路作为阻塞门禁。
- 2026-05-16 上传前最终 targeted tests：
  `python -m pytest tests/test_competition_runner.py tests/test_multi_agent_workflow.py::test_enrich_task_parameters_replaces_model_placeholder_artifact_names tests/test_independent_sources.py tests/test_realtime_data_smoke.py tests/test_multi_agent_harness.py -q`：`12 passed`。
- 2026-05-16 上传前最终全量回归：
  `python -m pytest -q -rA`：通过；2 个 skip 仍为可选历史 eval/report fixture 缺失，非本轮功能失败。
- 2026-05-16 云端记录同步语法验证：
  `python -m py_compile scripts/run_competition.py src/report/html_report_generator.py src/app/web_ui.py`：通过。
- 2026-05-16 云端记录同步 targeted tests：
  `python -m pytest tests/test_html_report_generator.py tests/test_web_ui.py tests/test_competition_runner.py -q`：`6 passed`。
- 2026-05-16 云端记录同步后全量回归：
  `python -m pytest -q -rA`：通过；2 个 skip 仍为可选历史 eval/report fixture 缺失，非本轮功能失败。
- 2026-05-16 DeepSeek API smoke：
  `python scripts/run_deepseek_smoke.py --config-path configs/model_backends.yaml --prompt '用一句话回复：DeepSeek API smoke 已连通。'`：通过，返回 `DeepSeek API smoke 测试通过，后端服务正常。`
- 2026-05-16 数据源拓宽语法与 targeted tests：
  `python -m py_compile src/search/search_manager.py src/agents/deep_analyze_agent.py src/agents/verifier.py src/agents/deep_researcher_agent.py src/agents/multi_agent_orchestrator.py scripts/run_competition.py`：通过；
  `python -m pytest tests/test_competition_runner.py tests/test_source_authority_policy.py tests/test_search_and_research_agent.py tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph -q`：`20 passed`。
- 2026-05-16 DeepSeek API + broadened realtime A 股验证：
  `python scripts/run_competition.py --config configs/model_backends.yaml --symbol 600519.SS --period 2025Q4 --fast --disable-memory --realtime-data --baseline-deepseek-workflow --output-dir eval_outputs/api_validation_20260516_600519SS_deepseek_broadened_v2`：`competition_passed=true`，`company_report_score=0.625`，baseline DeepSeek `model_used=true`。
- 2026-05-16 DeepSeek API + broadened realtime 美股验证：
  `python scripts/run_competition.py --config configs/model_backends.yaml --symbol AMD --period 2025Q4 --fast --disable-memory --realtime-data --baseline-deepseek-workflow --output-dir eval_outputs/api_validation_20260516_AMD_deepseek_broadened_v2`：`competition_passed=true`，`company_report_score=0.6667`，Company evidence 包含 Yahoo Finance、SEC companyfacts、BLS。
- 2026-05-16 Agent Chat 与三层记忆 targeted tests：
  `python -m pytest tests/test_agent_chat.py tests/test_web_ui.py tests/test_config_loader.py tests/test_conversation_memory.py tests/test_durable_memory.py tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_can_persist_durable_memory_without_quality_regression tests/test_memory_ablation_runner.py tests/test_multi_agent_harness.py -q`：`23 passed`。
- 2026-05-16 Agent Chat 最终全量回归：
  `python -m pytest -q -rA`：通过；2 个 skip 仍为可选历史 eval/report fixture 缺失，非本轮功能失败。
- 2026-05-16 A 股正式数据源 targeted tests：
  `python -m pytest tests/test_search_and_research_agent.py tests/test_source_authority_policy.py tests/test_competition_runner.py tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph -q`：`25 passed`。
- 2026-05-16 A 股正式数据源 live smoke：
  巨潮 `cninfo_announcements` 拉到 `贵州茅台2025年年度报告` 和 `2026年第一季度报告`；上交所 `exchange_announcements` 拉到对应官方 PDF；东方财富 `eastmoney_financials` 拉到 `2025-12-31` 利润表、资产负债表、现金流量表。
- 2026-05-16 A 股正式数据源 competition smoke：
  `python scripts/run_competition.py --config configs/model_backends.yaml --symbol 600519.SS --period 2025Q4 --fast --disable-memory --realtime-data --baseline-deepseek-workflow --output-dir eval_outputs/api_validation_20260516_600519SS_ashare_official_v3`：`competition_passed=true`，`company_report_score=0.7083`，Company evidence 包含巨潮公告、上交所公告、东方财富财务表和 Yahoo market snapshot，baseline DeepSeek `verified_claim_count=3`。

以后每次完成计划，都要在这里记录：

- 实际执行的命令。
- 通过/失败结果。
- 失败时的原因和下一步处理。
- 是否有测试缓存、权限、网络、模型不可用等非业务性警告。

## 动态更新规则

每次完成一个计划后，提交前必须更新本文档：

- `最新更新`：本轮做了什么，commit、run id 或产物在哪里。
- `已完成`：新增关闭的能力、修复或清理项。
- `当前风险`：新的阻塞、回归、未确认事实。
- `下一步计划`：下一轮按优先级排列的执行步骤。
- `验证记录`：实际运行过的命令和结果。

不要再新增与本文档竞争的状态文档。若必须新增设计文档或审计文档，应从本文档链接过去，并保持本文档作为入口。
## 2026-05-16 Web UI 多模态工作台修复

- Web UI 已从结果查看器形态推进到 chat-first 研究工作台形态：研究助手位于主配置区顶部，默认允许在确认参数后启动研报。
- 已修复最近结果与左侧表单脱节问题：`/api/latest` 返回 `symbol/period/research_topic/search_engines/output_dir/report_dir`，前端读取最近输出后同步回填表单并显示当前 artifact 来源。
- 已修复 Web UI 不能触发 A 股正式源链路问题：`/api/run` 与 `/api/chat` 透传 `enable_remote_data` 和 `data_source_config_path`；实时源开启时，A 股默认使用巨潮公告、交易所公告、东方财富三表、Yahoo/Eastmoney，本地 evidence 作为补充；美股默认使用 SEC EDGAR、Yahoo 与独立宏观源。
- 已增加 period guard：未结束季度会被阻止生成正式财报口径研报。按当前日期 2026-05-16，`2026Q2` 会提示尚未结束，并建议选择 `2026Q1` 或 `2025Q4`。
- UI 已新增多模态 tabs：三表表格、PDF 章节、公司画像、Claims，并继续保留图表、引用、执行轨迹、时间线和原始 JSON。
- PDF artifacts 已进入分析链：browser 阶段后会提前构建 PDF artifacts，把 `pdf_sections` 转成 `pdf_section` evidence records；`DeepAnalyzeAgent` 会从主营业务、管理层讨论、股东治理、风险、财务报表 PDF 片段派生 claims。
- 详细记录见 `docs/web_ui_multimodal_workbench.md`。
# 2026-05-16 Commit 2：Chat-first UI 状态更新

- 已完成 ChatGPT-like 首屏对话 UI：标题“你今天在想些什么？”，输入框“有问题，尽管问”，右侧圆形发送按钮。
- 高级设置默认折叠，默认开启 `allow_report_run=true`、`memory_enabled=true`、`enable_remote_data=true`、`fast=true`。
- `/api/latest` 与前端“质量评测”tab 已预留 `quality_report.json`、`llm_quality_review.json`、`delivery_gate.json` 展示。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_web_ui.py tests/test_agent_chat.py`。
- 质量结果：12 passed。
- 未完成项：自然语言任务解析、objective quality eval、LLM/Codex review、delivery gate 接入和 600519/AMD 内容修复仍待后续 commit。

# 2026-05-16 Commit 3：自然语言解析与 memory 应用状态更新

- 新增 `src/app/chat_task_parser.py`，支持把“生成贵州茅台最新财报研报”解析为 `600519.SS + 最近已结束期间`，把“生成 AMD 最新财报研报”解析为 `AMD + 最近已结束期间`。
- `/api/chat` 会在启动多智能体前用解析结果覆盖表单中的 stale symbol/period，并按 A 股/美股自动选择默认实时数据源。
- 若用户只泛泛提到“研报怎么看”但没有明确生成意图或参数不足，Chat 返回确认信息，不启动报告任务。
- Memory 默认用于偏好和上下文，Chat 回复明确提示“事实仍以 evidence_id/citation/verifier 为准”。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py`；`python -m py_compile src/app/chat_task_parser.py src/app/web_ui.py`。
- 质量结果：17 passed。
- 未完成项：objective quality eval、LLM/Codex review、delivery gate 接入和双样本内容修复仍待后续 commit。

# 2026-05-16 Commit 4：objective quality eval 状态更新

- 新增 `src/evaluation/report_quality.py` 和 `scripts/evaluate_report_quality.py`。
- 本地客观评测输出 `quality_report.json`、`quality_report.md`、`quality_issues.jsonl`，覆盖结构完整度、证据支撑、财务质量、多模态质量、专业深度和合规披露。
- 门禁规则已实现：总分 >= 0.82、无 fatal issue、执行摘要/风险/投资结论非空、公司/个股报告具备三表摘要/业务画像/风险提示；估值缺失时必须说明“估值不可用原因”。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_report_quality.py tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py`；`python scripts/evaluate_report_quality.py --run-dir eval_outputs/web_link_test_AMD_2025Q4`。
- 质量结果：19 passed；AMD 样本 `total_score=0.892` 但 `objective_pass=false`，硬门禁已能拦截不可交付报告。
- 未完成项：LLM/Codex review、delivery gate 接入和双样本内容修复仍待后续 commit。

# 2026-05-16 Commit 5：LLM/Codex review 状态更新

- 新增 `src/evaluation/llm_report_review.py` 和 `scripts/review_report_with_llm.py`。
- 主观复核读取 report markdown、objective quality report、verification、claims/evidence/citations 摘要，并按赛题维度判断专业研报形态、投资洞察、事实/期间一致性、公司报告要求、图表作用和语言质量。
- 主观门禁规则已实现：总分 >= 0.80、fatal issue 为 0；若出现“内容空洞 / 大量暂无结论 / 期间错配 / 明显乱码”，直接 fail。
- 无 API key 或模型调用失败时 `llm_review_pass=false`，不能假装通过。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_llm_report_review.py tests/test_report_quality.py tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py`；`python scripts/review_report_with_llm.py --run-dir eval_outputs/web_link_test_AMD_2025Q4`。
- 质量结果：22 passed；AMD 样本当前 `llm_review_pass=false`，本机模型调用状态为 `error`，交付门禁应阻断。
- 未完成项：delivery gate 接入和双样本内容修复仍待后续 commit。

# 2026-05-16 Commit 6：delivery gate 接入状态更新

- 新增 `src/evaluation/delivery_gate.py`，将 verifier、objective quality eval、LLM/Codex review 汇总为 `delivery_gate.json`。
- `/api/chat` 和 `/api/run` 生成报告后自动运行三层质量链路，并回传 `quality_report`、`llm_quality_review`、`delivery_gate` 摘要。
- Web UI“质量评测”tab 已能展示 objective 分数、LLM review 结论和 fatal/blocker/warning 问题。
- 最终可交付条件固定为：`verification_passed=true`、`objective_pass=true`、`llm_review_pass=true` 三者同时成立。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_delivery_gate.py tests/test_llm_report_review.py tests/test_report_quality.py tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py`。
- 质量结果：24 passed。
- 未完成项：600519 与 AMD 内容修复、双样本重跑和记录仍待后续 commit。

# 2026-05-16 Commit 7：600519/AMD 内容链路修复状态更新

- `DeepAnalyzeAgent` 已将 `expected_period` 注入 PDF-derived claims，`2025Q4` 报告不再把 `2026Q1` PDF 片段作为核心业务/财务 claim。
- period gate 新增中文季度/年度识别：`2026 年第一季度报告` -> `2026Q1`，`2025 年年度报告` -> `2025Q4`。
- AMD 缺少业务/同行/估值/风险/投资结论 claims 时，会补充证据约束下的业务画像框架、NVIDIA/Intel/Broadcom 同行框架、估值不可用原因、敏感性框架、风险和中性/审慎观察结论。
- Eastmoney 财务 claims 已改为“亿元”格式，避免科学计数法和原始超长数字。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections tests/test_report_quality.py tests/test_delivery_gate.py`；`python -m py_compile src/agents/deep_analyze_agent.py`。
- 质量结果：13 passed。
- 未完成项：双样本重跑和记录仍待 Commit 8。

# 2026-05-16 Commit 8：Chat-first 双样本重跑状态更新

- 修复 Chat 英文生成意图：`generate ... company report` 可进入 `report_run`。
- 修复 objective eval 科学计数法误报：不再把 evidence_id/hash 中的短片段误判为科学计数法。
- 已通过 Chat-first 链路重跑：
  - A 股：`600519.SS 2026Q1`，链接：`http://127.0.0.1:8790/eval_outputs/chat_first_delivery_600519SS_latest/company/reports/report.html`
  - 美股：`AMD 2026Q1`，链接：`http://127.0.0.1:8790/eval_outputs/chat_first_delivery_AMD_latest/company/reports/report.html`
- A 股结果：verifier=true，company_report_overall_score=0.9375，objective_pass=true，objective_total_score=1.0，llm_review_pass=false，delivery_pass=false。
- 美股结果：verifier=true，company_report_overall_score=0.8542，objective_pass=false，objective_total_score=0.8907，llm_review_pass=false，delivery_pass=false。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_chat_task_parser.py tests/test_agent_chat.py tests/test_data_enrichment.py tests/test_report_quality.py tests/test_llm_report_review.py tests/test_delivery_gate.py tests/test_web_ui.py`。
- 质量结果：33 passed。
- 当前结论：Chat-first + memory + 多 Agent + 双层质量门禁已经打通；两份样本都未达到“可交付”，原因已由 `delivery_gate.json` 明确记录。下一轮应优先修复内容空洞、三表正文写入、估值可计算路径和同行对比。

# 2026-05-17 Commit 9：质量失败反馈进入 Memory 和下一轮规划

- 新增 `src/evaluation/quality_remediation.py`，从 `delivery_gate.json`、`quality_report.json`、`llm_quality_review.json` 汇总 fatal/blocker/warning，写出 `quality_remediation_plan.json`。
- `quality_remediation_plan.json` 现在包含 `required_fixes`、`failed_sections`、`forbidden_patterns`、`planner_constraints` 和 memory 边界声明；该反馈只作为下一轮规划上下文，不作为事实证据。
- `run_delivery_quality_pipeline` 已在生成 delivery gate 后自动写出 remediation plan，并把 `quality_remediation_plan_path`、`quality_feedback_used`、`memory_quality_feedback_used` 写回 `run_summary.json`。
- Memory 开启时，质量失败摘要会通过 `DurableMemoryStore.persist_quality_feedback()` 写入 working / episodic / domain memory；Planner/Router 下一轮 brief 可读取“补三表、补估值、禁止暂无结论”等约束。
- Web UI “质量评测”tab 新增修复计划展示；Chat 报告结果会提示“已读取上一轮质量反馈，并生成本轮修复约束”，同时继续提示事实以 evidence/citation/verifier 为准。
- 验证命令：
  - `python -m py_compile src/evaluation/quality_remediation.py src/agents/durable_memory.py src/app/web_ui.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_quality_remediation.py tests/test_durable_memory.py tests/test_delivery_gate.py tests/test_web_ui.py`
- 质量结果：14 passed。
- 当前风险：质量反馈已经能进入 memory，但还没有强制 FinalAnswerAgent 按约束补正文；下一步优先修复 AMD 三表正文缺失。

# 2026-05-17 Commit 10：强制三表摘要进入正文

- 修复 AMD 三表摘要生成链路：`DeepAnalyzeAgent` 现在会从标准化 statement rows 生成利润表摘要、资产负债表摘要、现金流量表摘要；若现金流字段缺失，会生成“现金流量表缺口”claim，说明缺失字段和对现金转化率/估值敏感性判断的影响。
- 修复 `_statement_value` 只读取 `value_billion` 的问题；现在兼容 SEC/Eastmoney 标准化行中的原始 `value` 字段，避免 AMD revenue/net_income/assets/cash 已存在但无法形成三表 claim。
- `report_quality` 已能读取 `tables.json` 中的嵌套 `rows`，不再只看外层 `table_type`；当现金流量表数据不足但正文明确说明缺口时，三表门禁可识别为“已披露缺口”。
- 新增测试覆盖：
  - SEC rows 可生成利润表、资产负债表、现金流缺口三类 `financial_statements` claims。
  - objective evaluator 可识别嵌套 rows 和现金流缺口说明。
- 验证命令：
  - `python -m py_compile src/agents/deep_analyze_agent.py src/evaluation/report_quality.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_report_quality.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections tests/test_delivery_gate.py tests/test_quality_remediation.py`
- 质量结果：12 passed；5 passed。
- 当前风险：三表正文写入已补强，但 600519 PDF 业务画像、AMD 业务线/同行对比、估值和敏感性仍需后续 commit 继续做深。

# 2026-05-17 Commit 11：600519 业务画像和 PDF 片段深度写入

- `DeepAnalyzeAgent` 新增白酒/PDF insight claim 生成：当 PDF section 包含贵州茅台、茅台酒、系列酒、直销、批发代理、经销商、股东、分红/回购、风险等关键词时，会派生更贴近白酒研报的业务画像和治理/风险 claims。
- 600519 PDF 片段现在可进入以下正文素材：
  - 产品结构：茅台酒、系列酒。
  - 渠道结构：直销、批发代理、`i 茅台` 数字营销平台。
  - 经销商结构：国内/国外经销商数量和变动应进入渠道质量分析。
  - 股东结构：控股股东、香港中央结算和国资股东。
  - 股东回报：现金分红、回购注销。
  - 白酒风险：高端消费需求、渠道库存、批价波动、系列酒渠道调整和回购/分红执行不确定性。
- 这些 claims 仍绑定原始 PDF section evidence_id，不把 memory 或行业常识当作事实来源；行业语境只用于解释维度。
- 验证命令：
  - `python -m py_compile src/agents/deep_analyze_agent.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections`
- 质量结果：11 passed。
- 当前风险：600519 业务画像更完整，但估值、敏感性和同行对比仍未闭合；下一步修 AMD 业务线/同行对比。

# 2026-05-17 Commit 12：AMD 业务线、同行对比和投资结论补强

- 修复 AMD 报告中 BLS 宏观证据被写成 `Company` 业务概览的问题：无公司 symbol 的 trend row 不再生成公司业务画像 claim。
- AMD 最低正文 claims 现在强制覆盖：
  - Data Center、Client、Gaming、Embedded 四条业务线。
  - AI GPU/EPYC、PC 周期、Gaming/Embedded 存量业务韧性等投资含义。
  - NVIDIA、Intel、Broadcom 三组同行参照关系。
  - 中性/审慎观察结论中的增长驱动、竞争压力、估值约束和现金流/分部收入证据缺口。
- 同行对比仍保持证据边界：没有同业三表和估值倍数时不输出排名，只输出定性参照框架和待补数据。
- 新增测试覆盖：
  - AMD claims 必须包含 Data Center / Client / Gaming / Embedded、NVIDIA / Intel / Broadcom、增长驱动 / 竞争压力 / 估值约束。
  - BLS 等宏观证据不得生成 `Company 的证据覆盖` 公司业务概览。
- 验证命令：
  - `python -m py_compile src/agents/deep_analyze_agent.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_report_quality.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections`
- 质量结果：15 passed。
- 当前风险：AMD 业务线和同行框架已补强，但估值仍主要是不可用说明；下一步补最小估值与敏感性模块。

# 2026-05-17 Commit 13：最小估值模型和敏感性分析

- `DeepAnalyzeAgent` 新增最小估值 claims：基于公开行情市值和标准化三表数据，能计算时输出 P/E、P/B、P/S；不能计算时明确列出缺少市值/股本、净利润、净资产/股东权益或收入。
- 新增最小敏感性 claim：当收入和净利润可得时，计算当前净利率，并估算净利率变动 1pct 对净利润的方向性影响。
- AMD 敏感性正文要求已写入 claim：重点跟踪数据中心收入增速、毛利率和研发费用率；白酒公司重点跟踪收入增速、净利率和渠道价格。
- 估值 claims 仍绑定 market/financial evidence；没有市场市值或股本时不伪造 P/E/P/B/P/S。
- 新增测试覆盖：
  - market cap + revenue/net income/equity 可计算 P/E、P/B、P/S。
  - 收入 + 净利润可生成敏感性分析。
- 验证命令：
  - `python -m py_compile src/agents/deep_analyze_agent.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_report_quality.py tests/test_delivery_gate.py`
- 质量结果：17 passed。
- 当前风险：估值计算路径已具备最小版本，但 objective evaluator 仍可能对空洞正文放得过宽；下一步收紧客观质量评测。

# 2026-05-17 Commit 14：收紧客观质量评测，减少虚高分

- `objective_pass` 现在要求总分 >= 0.82、fatal=0、blocker=0 且 required gate 全通过；不再允许 blocker 存在时仍通过。
- 新增正文有效性规则：
  - “暂无结论/暂无可验证结论/待补充”等空洞占位过多会 fatal。
  - `tables.json` 有三表 artifact 但正文没有利润表/资产负债表/现金流量表或现金流缺口说明时，`has_three_table_summary=false`。
  - 同行对比或敏感性分析只有“框架/待补/缺少可量化”且没有方向性结论时 blocker。
  - 估值缺失但没有“估值不可用原因”或可计算倍数时 blocker。
  - 投资结论必须同时有方向和理由。
- 新增测试覆盖：
  - tables artifact 存在但正文未写三表时 fail。
  - 框架化同行/敏感性、弱投资结论会 fail。
  - 完整公司报告样例仍可通过。
- 验证命令：
  - `python -m py_compile src/evaluation/report_quality.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_report_quality.py tests/test_quality_remediation.py tests/test_delivery_gate.py`
- 质量结果：9 passed。
- 当前风险：客观评测已更严格，后续重跑可能暴露更多正文质量问题；下一步让 FinalAnswerAgent 消费质量修复约束并 hard backfill。

# 2026-05-17 Commit 15：FinalAnswerAgent 消费质量修复约束并 hard backfill

- `FinalAnswerAgent` 现在显式读取 `quality_remediation_plan` / `remediation_plan` / `quality_feedback`，并把失败章节、必须修复项、禁止空洞表达和 Planner 约束写入最终写作 prompt；该反馈仍只作为写作约束，不作为事实证据。
- `FinalAnswerAgent` 新增结构化 artifact 上下文输入：`tables`、`financial_metrics`、`pdf_sections`、`company_profile`，用于提示正文必须覆盖三表、PDF-derived 业务画像和公司画像，但引用仍必须来自 evidence_id-backed claims/evidence。
- 新增 deterministic hard backfill：当执行摘要、业务画像、三表、同行对比、估值、敏感性、风险或投资结论出现“暂无结论 / 待补 / 框架性 / 缺少可量化 / 弱投资结论”等表达，且对应 claims 已存在时，直接用 claim-backed bullets 覆盖该章节。
- `MultiAgentOrchestrator` 会在 run 开始时读取已有 `quality_remediation_plan.json`，并将质量修复计划与 analysis artifacts 传给静态/动态 final task；verifier rework loop 也会继续携带这些约束。
- 顺手将 fast profile 的 research `topk` 恢复为测试约定的 6，保持 fast mode 上下文预算稳定。
- 新增测试覆盖：
  - FinalAnswerAgent prompt 中包含质量修复约束。
  - LLM 输出框架化同行/估值/敏感性/弱结论时，会被 hard backfill 替换为对应 claims。
  - 独立 hard backfill helper 可替换框架正文。
- 验证命令：
  - `python -m py_compile src/agents/final_answer_agent.py src/agents/multi_agent_orchestrator.py src/app/web_ui.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_multi_agent_workflow.py::test_final_answer_hard_backfills_quality_failed_sections tests/test_multi_agent_workflow.py::test_hard_backfill_quality_sections_replaces_framework_body tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_auto_reworks_failed_report`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_agent_chat.py tests/test_web_ui.py tests/test_report_quality.py tests/test_delivery_gate.py tests/test_quality_remediation.py`
  - `$env:PYTHONPATH='.'; pytest -q tests/test_multi_agent_workflow.py tests/test_data_enrichment.py`
- 质量结果：3 passed；22 passed；37 passed。
- 当前风险：FinalAnswer 已能消费修复计划并做正文 hard backfill，但 600519/AMD 的真实 Chat-first 样本还未重跑；下一步进入 Commit 16，执行双样本网页验收并记录三层质量结果。

# 2026-05-17 Commit 16：Chat-first 双样本重跑与剩余 blocker 记录

- 使用 `configs/model_backends_local_ollama.yaml` 和本机 Ollama `qwen3:8b` 执行 Chat-first 双样本重跑；本机仍未设置 `DEEPSEEK_API_KEY`，因此本轮 LLM review 不伪装为 DeepSeek 通过。
- PowerShell here-string 中文输入会在本机命令管道中被转成问号，已改用 ASCII prompt 并显式指定标的/期间，避免 600519 样本误落到默认 AAPL。
- A 股样本：
  - prompt: `generate 600519.SS latest company report`
  - symbol/period: `600519.SS / 2026Q1`
  - report: `eval_outputs/chat_first_delivery_600519SS_latest/company/reports/report.html`
  - verifier: `true`
  - objective: `false`，score `0.992`
  - LLM review: `false`，score `0.0`
  - delivery: `false`
  - top blocker: 同行对比仍被 objective gate 判定为“只有框架或待补说明，缺少可读结论”。
- 美股样本：
  - prompt: `generate AMD latest company report`
  - symbol/period: `AMD / 2026Q1`
  - report: `eval_outputs/chat_first_delivery_AMD_latest/company/reports/report.html`
  - verifier: `true`
  - objective: `false`，score `0.9415`
  - LLM review: `false`，score `0.0`
  - delivery: `false`
  - top blockers: 同行对比仍偏框架化；估值缺失但正文没有明确估值不可用原因；delivery gate 还记录一个 verifier blocker `None`，需要下一轮清理 verifier issue message。
- 新增/更新重跑汇总：
  - `eval_outputs/chat_first_delivery_summary.json`
  - `eval_outputs/chat_first_delivery_summary.md`
- 验证命令：
  - Chat-first 600519 重跑：`AgentChatService + MultiAgentOrchestrator + run_delivery_quality_pipeline`，config=`configs/model_backends_local_ollama.yaml`
  - Chat-first AMD 重跑：`AgentChatService + MultiAgentOrchestrator + run_delivery_quality_pipeline`，config=`configs/model_backends_local_ollama.yaml`
- 当前结论：Commit 16 未达到 `delivery_pass=true`；但剩余问题已经从“泛化内容空洞”收敛为具体质量 blocker。下一轮优先修复同行对比正文判定、AMD 估值不可用原因写入和 verifier 空 message。
# 2026-05-17 Commit 17：通用公司身份解析与数据源计划

- 新增 `CompanyIdentity` 路由结构，统一输出 `symbol`、`canonical_symbol`、`market`、`exchange`、`currency`、`is_listed`、`resolution_confidence` 和 `data_source_plan`。
- `resolve_company_identity()` 现在可根据 A 股代码、港股代码、美股 ticker 和本地公司宇宙生成免费公开数据源计划；该结果只用于路由，不作为事实证据。
- Web UI 默认引擎选择改为读取身份解析的数据源计划：A 股走巨潮/交易所/东方财富/Yahoo，港股走 Yahoo/公开搜索，美股走 SEC/Yahoo/公开搜索，其他市场走 Yahoo/公开搜索并要求缺口说明。
- 新增测试覆盖 A 股、港股、美股、未知非上市输入和 Web UI 默认引擎选择。
- 验证命令：`$env:PYTHONPATH='.'; pytest -q tests/test_company_identity.py tests/test_chat_task_parser.py tests/test_web_ui.py`。
- 质量结果：`21 passed`。
- 剩余问题：当前只是通用路由层，后续还需要移除公司级补齐硬编码、补 collaboration/tool trace、GapResolver 和 delivery gate 同轮返工。

# 2026-05-17 Commit 18：移除公司级硬编码补齐

- `DeepAnalyzeAgent` 的最低研报补齐逻辑已从 AMD/600519 等 symbol 特判改为通用行业画像：半导体/硬件科技、互联网平台、消费品、金融和通用上市公司。
- 业务画像、同行对比、估值、敏感性、风险和投资结论现在基于行业关键词、市场/证据文本和数据缺口生成写作约束，不再按单个公司名称生成专属段落。
- PDF insight 从茅台专用业务/渠道/股东模板改为通用 PDF section + 关键词触发，覆盖业务、治理和风险片段。
- `FinalAnswerAgent` 示例和 objective/remediation 的同行关键词去除了固定竞品名单，避免质量规则绑定特定公司。
- 更新测试：公司专用断言改为通用 PDF 消费、科技行业画像和章节补齐断言。
- 验证命令：`python -m py_compile src/agents/deep_analyze_agent.py src/agents/final_answer_agent.py src/evaluation/report_quality.py src/evaluation/quality_remediation.py`；`$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_report_quality.py tests/test_quality_remediation.py`。
- 质量结果：`19 passed`。
- 剩余问题：还需要把多 Agent 协作、工具调用、GapResolver 和 delivery rework 做成可见 artifact。

# 2026-05-17 Commit 19：多 Agent 协作 Trace 可见化

- 新增 `agent_collaboration_trace.json`，从 `task_trace.jsonl` 汇总每个 Agent 的任务、输入摘要、输出 keys、handoff、memory 使用、质量反馈使用和返工/缺口状态。
- `MultiAgentOrchestrator` 的 static/dynamic 两条链路都会写出该 artifact，并在 run result 中返回 `agent_collaboration_trace` 路径。
- `/api/latest` 现在读取并返回 `agent_collaboration_trace`，为前端“多智能体协作”tab 做准备。
- trace 明确写入 memory 边界：Memory 只作为 routing/context，事实仍必须来自 evidence/citation/verifier。
- 验证命令：`python -m py_compile src/agents/multi_agent_orchestrator.py src/app/web_ui.py`；`$env:PYTHONPATH='.'; pytest -q tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_web_ui.py::test_load_run_payload_reads_latest_artifacts`。
- 质量结果：`2 passed`。
- 剩余问题：工具调用还未统一落到 `tool_trace.json`，GapResolver 和 delivery gate 同轮返工仍待实现。

# 2026-05-17 Commit 20：工具调用 Trace 统一记录

- `BaseAgent.call_tool()` 现在记录 deterministic tool call，包含 caller agent、tool name、输入/输出摘要、成功/失败、耗时、evidence ids 和 artifact paths。
- `MultiAgentOrchestrator` 新增 `tool_trace.json`，汇总 deterministic tools、ReAct metadata 和搜索引擎 meta。
- static/dynamic run result 都返回 `tool_trace` 路径；`/api/latest` 读取并返回该 artifact。
- 当前 trace 已能覆盖 `build_three_statement_view`、`build_peer_comparison`、`perform_company_valuation` 等分析工具，为前端展示“充分调用工具”打底。
- 验证命令：`python -m py_compile src/agents/base_agent.py src/agents/multi_agent_orchestrator.py src/app/web_ui.py`；`$env:PYTHONPATH='.'; pytest -q tests/test_agent_foundation.py tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph tests/test_web_ui.py::test_load_run_payload_reads_latest_artifacts`。
- 质量结果：`8 passed`。
- 剩余问题：还需要新增 GapResolver/DataRepairAgent，并让 delivery gate 失败后同轮返工。

# 2026-05-17 Commit 21：新增通用 GapResolver/DataRepairAgent

- 新增 `GapResolverAgent`，用于检测三表、估值、同行、敏感性、股权治理、PDF 消费和数据源失败缺口；规则按报告结构/数据源/质量问题触发，不按公司名称特判。
- dynamic 多 Agent 链路新增 GapResolver 步骤，输出 `gap_resolution_trace.json`、`gap_resolution_trace.jsonl`、`data_repair_summary.json`、`repair_constraints` 和 `required_backfill_sections`。
- `run_summary` 和后续 trace 可看到 gap count、blocker/warning 和待补正文章节，为 delivery gate 同轮返工做输入。
- 新增单测覆盖三表缺失、估值不可用原因缺失、数据源失败和 artifacts 有三表但正文未消费的场景。
- 验证命令：`python -m py_compile src/agents/gap_resolver_agent.py src/agents/multi_agent_orchestrator.py`；`$env:PYTHONPATH='.'; pytest -q tests/test_gap_resolver_agent.py tests/test_multi_agent_workflow.py::test_multi_agent_orchestrator_runs_dynamic_task_graph`。
- 质量结果：`3 passed`。
- 剩余问题：GapResolver 已产出修复约束，但 delivery gate 失败后尚未自动触发同轮 rewrite。
