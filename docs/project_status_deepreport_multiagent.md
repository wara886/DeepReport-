# DeepReport++ 项目状态与下一步计划

更新日期：2026-05-15

本文档是当前 DeepReport++ 项目的唯一主状态文档。以后项目说明、阶段总结、下一步计划和验证记录默认使用中文，并优先更新本文档。

当前有效工作目录是：

```text
G:\cord\DeepReport_plus
```

不要再把父目录 `G:\cord`、旧 zip 解压目录、旧嵌套目录或历史归档内容当作当前主线项目。

## 最新更新

- 当前仓库是从 GitHub `origin/main` 干净 clone 到 `G:\cord\DeepReport_plus` 的项目。
- 本轮开始基线：`7ddf800 Add guarded durable memory foundation`。
- 主状态文档已改为中文，并把后续维护规则固定为中文。
- 本次继续补齐 P2：新增 `scripts/run_memory_ablation.py`，可从现有 multi-agent evaluation config 派生 `memory_enabled` / `memory_disabled` 两个 variant，输出 `memory_ablation_comparison.json` 和 `memory_ablation_comparison.md`。
- 当前 durable memory 已有默认关闭的基础工程能力和可复现 ablation runner；但它仍不是默认开启能力，必须通过质量/延迟门禁后才能进入更宽 smoke 或默认配置。
- 本轮新增本地 Ollama/qwen3 配置并完成 1 个 AAPL 样本的真实 ablation：`eval_outputs/memory_ablation_ollama_qwen3_20260515/memory_ablation_comparison.json`，结论为 `promote_memory`，但样本数仍太小，不能直接改成默认开启。
- 本轮真实复跑暴露并修复了 `build_trend_features` 对缺失 `symbol/period/sample_id` 的脆弱路径，避免动态任务拿到非标准 evidence records 时中断整份报告。
- 已完成 P1 仓库真实能力复核：`scripts/`、`configs/`、`src/agents/`、`src/evaluation/` 中的当前主线能力已经按真实文件重新登记；README 和 AGENTS 用 UTF-8 读取为正常中文，本轮不做编码修复。
- P2 Memory 正式工程化已完成第二阶段：`src/agents/durable_memory.py` 提供基础存取层，`scripts/run_memory_ablation.py` 提供 enabled/disabled 对照与质量/延迟 guard；开启后只注入“历史上下文提示”，不替代 evidence/citation/verifier 质量门禁。

## 当前结论

DeepReport++ 当前主线是一个面向金融研报的证据驱动、多 Agent 报告生成工程。项目已经具备基础报告流水线、多 Agent 骨架、报告格式修复、图表 lineage 校验和一批已提交评估产物。

但从当前仓库代码看，下一步仍不应直接宣称 memory / SkillRegistry 已全面接入 Planner/Router。Memory 已进入“默认关闭、可复现实验、受门禁控制”的工程阶段；SkillRegistry 仍需要正式实现、测试和注入策略。

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
- `src/agents/planning_agent.py`、`src/agents/gap_router.py`、`src/evaluation/multi_agent_harness.py` 为后续 Planner/Router 策略接入提供基础。

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

## 当前代码与历史产物差异

### 当前代码中可以确认存在

- `src/agents/conversation_memory.py`：会话级 memory / context brief。
- `src/agents/durable_memory.py`：文件化 durable memory store，负责历史 run snapshot、episodic memory、domain memory 和 bounded context brief。
- `src/agents/multi_agent_orchestrator.py`：多 Agent 编排入口。
- `src/agents/planning_agent.py`：规划 Agent。
- `src/agents/gap_router.py`：gap resolution trace 相关能力。
- `src/evaluation/`：多类评估、诊断、numeric/citation/multimodal audit 基础。
- `eval_outputs/`：已提交的 qwen3 canary 和 memory ablation 结果文件。
- `scripts/run_multi_agent_demo.py`：当前多 Agent demo 入口，支持 `--execution-mode`、`--fast`、`--retrieval-ranking-mode`、`--engines`。
- `scripts/run_multi_agent_eval.py`：调用 `src.evaluation.multi_agent_harness` 的动态多 Agent 评估入口。
- `scripts/run_memory_ablation.py`：基于现有 multi-agent evaluation config 派生 memory enabled/disabled 对照评估，并生成质量/延迟门禁结论。
- `configs/model_backends.yaml`、`configs/data_sources.yaml`、`configs/evaluation_multi_agent_react_smoke.yaml`、`configs/evaluation_stage12a.yaml`：当前可见的模型、数据源和评估配置。
- `configs/model_backends_local_ollama.yaml`：本地 Ollama/qwen3 OpenAI-compatible 模型配置，默认使用 `qwen3:8b`。
- `configs/evaluation_memory_ablation_ollama.yaml`：本地 qwen3 memory ablation 小样本评估配置。
- `configs/app.yaml`：已包含 `memory.durable` 开关、根目录、上下文长度和保留条数配置。

### 当前仓库尚未发现完整实现

- 未发现 `SkillRegistry` 或 `src/skills/` 相关正式实现。
- 尚未把本地 qwen3 memory 配置推广为默认模型配置。

### 需要补回或正式工程化

- 更完整的 memory 选择策略、过期策略，以及在真实 qwen3/本地模型样本上的质量/延迟 guard 复跑。
- SkillRegistry 静态 MVP、schema、测试和 Planner/Router prompt 注入。
- 当前评估产物与未来可复现脚本之间的追溯关系。

## 仓库代码结构

- `configs/`：运行配置、模型后端配置、数据源配置、评估配置。
- `scripts/`：本地 smoke、评估、UI/server、云端上传下载脚本。
- `src/app/`：CLI 与 pipeline 入口。
- `src/agents/`：基础 Agent、多 Agent 编排、规划、研究、分析、最终报告、验证、会话上下文。
- `src/data/`：fetcher、标准化、manifest、公司识别、数据源质量。
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

- 文档中曾经把 memory / SkillRegistry 描述得过于接近“已完整工程化”，但当前仓库代码只能确认 conversation memory 和评估产物。
- qwen3 canary 与历史 memory ablation 产物已提交；当前仓库现在已有可复跑的 memory ablation runner，并已完成 1 个本地 qwen3 样本复跑，但样本数太小，仍需扩大到 3-5 个样本确认稳定性。
- Durable memory 现在已有默认关闭的基础存取层和 enabled/disabled 质量/延迟 guard；当前小样本结论支持进入更宽 smoke，但不支持直接默认开启。
- SkillRegistry 仍需正式实现和注入策略，不能只靠文档描述。
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

状态：第二阶段已完成，并已完成 1 个本地 qwen3 样本复跑；下一步扩大样本后，再把稳定收益接入 Planner/Router 策略。

1. 已完成：基于 `conversation_memory.py` 增加 `DurableMemoryStore`，写入 working / episodic / domain memory。
2. 已完成：增加 `memory_enabled`、memory root、上下文长度和保留条数配置；默认关闭，显式开启才影响 prompt。
3. 已完成：接入 `MultiAgentOrchestrator` 的 planning context brief；brief 明确标注不能作为证据，报告事实仍必须走 evidence/citation/verifier。
4. 已完成：增加 durable memory 单测和多 Agent enabled/disabled smoke 测试。
5. 已完成：新增可复现的 memory enabled/disabled ablation runner：`scripts/run_memory_ablation.py`。
6. 已完成：runner 输出质量/延迟 guard，比较 verifier、evidence coverage/alignment、chart consistency、contest checklist、numeric audit 和平均耗时。
7. 已完成：用本地 Ollama `qwen3:8b` 跑通 1 个 AAPL 样本的 memory ablation，产物位于 `eval_outputs/memory_ablation_ollama_qwen3_20260515/`。
8. 待完成：扩大到 3-5 个真实样本复跑，确认收益不是单样本偶然结果。
9. 待完成：将稳定通过门禁的 memory brief 选择策略进一步接入 Planner/Router，而不是直接默认开启全部历史上下文。

### P3：SkillRegistry 正式接入

1. 实现静态 SkillRegistry MVP。
2. 定义 skill schema、metadata、摘要字段和测试。
3. 让 Planner/Router 可选择性读取 skill 摘要。
4. 在评估指标中跟踪 unsupported fallback、verification pass、numeric/citation audit。

### P4：重新跑本地验证与交付链路

1. 跑 targeted tests。
2. 跑多 Agent smoke。
3. 根据当前可用配置决定是否重跑 qwen3 canary。
4. 重新验证 competition packaging 或三类研报交付链路。

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
