# DeepReport++ 项目状态与下一步计划

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
