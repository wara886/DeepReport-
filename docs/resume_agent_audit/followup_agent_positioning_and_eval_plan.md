# Agent 项目定位、Eval 指标与后续升级说明

## 1. 为什么简历和报告里没有写 baseline 提升指标

当前金融 DeepReport++ 项目里有 QA、Verifier、scorecard、numeric audit、valuation audit、multimodal consistency、trace 和多轮样例产物，但还没有形成严格 baseline 实验，因此不应该写“提升 X%”。

要写提升指标，至少需要：

- 固定测试集：例如 30-50 个 `ticker + period + query`，覆盖科技、金融、消费、A 股样例。
- 固定 baseline：例如 `single_prompt_llm`、`single_agent_rag`、`old_pipeline`、`multi_agent_workflow`。
- 固定判分规则：任务完成率、工具调用准确率、引用覆盖率、数字准确率、估值公式通过率、平均耗时。
- 固定运行配置：同一模型、同一搜索源、同一温度、同一超时、同一输出格式。
- 可复现报告：每次实验输出 `eval_summary.json`、case-level 明细和失败原因。

所以当前推荐表述是“建立了质量门禁 / QA 机制 / 可审计产物 / 支持后续评测”，而不是“准确率提升 xx%”。

## 2. 当前项目为什么是 workflow，不是完全自主协商式 multi-agent

当前系统是“orchestrated multi-agent workflow”。

原因：

- 全局控制权在 `MultiAgentOrchestrator`，不是各 Agent 自己协商下一步。
- 任务依赖由 task graph 和 `apply_implicit_dependencies` 控制，执行顺序基本是 Research -> Browser -> Analyze -> Final -> Verifier。
- Agent 之间不是自由消息通信，而是通过共享 state 和标准产物传递信息。
- Verifier 可以触发返工，但返工轮次、触发条件和目标 Agent 仍由 orchestrator 控制。
- RiskAgent 和 PeerComparisonAgent 是 analyze 后的补充专职模块，不是自主发起协作的 agent 社会。

这不是缺点。金融研报场景需要可控、可审计、可复现，所以 workflow 化反而更适合现阶段简历和答辩。

## 3. 如果要做“更真正”的多智能体，还差什么

如果目标是更接近自主多智能体系统，需要补：

- Agent 间消息协议：每个 Agent 不只返回结果，还能发起 request、challenge、revise、approve 等消息。
- 动态路由策略：下一步由 Router/Planner 根据状态和 verifier gaps 决定，而不是固定顺序。
- 多轮协商机制：Analyze 可以质疑 Research 证据不足，Research 再补证据；Verifier 可以把具体 claim 退回给对应 Agent。
- 共享黑板或任务池：所有 Agent 读写统一 task board，任务状态包括 queued/running/blocked/reviewed/resolved。
- 冲突解决：多个 Agent 对同一 claim 给出不同结论时，需要 adjudicator 或 judge。
- Agent-level eval：评估每个 Agent 是否完成自己的子任务，而不仅是最终报告是否通过。
- 成本和超时治理：自主协商会增加轮次，必须有 max_round、budget、stop condition。

推荐升级路径：不要直接做“群聊式 multi-agent”，先做 `GapRouter` 增强版，让 Verifier 的 evidence_gaps 能精准路由回 Research/Analyze/Final/Risk/Peer。

## 4. 邮件 tool-use 数据生成项目是不是 agentic RL

`/Users/yuan_dian/AI_project/agent_train_data_generater` 更准确叫：

```text
tool-use / function-calling 监督数据生成框架
```

它做了：

- 动态扫描 `tools/` 目录加载邮件工具。
- 使用 GPT/Gemini 生成多轮 tool-use 对话。
- 执行真实/模拟工具，形成 assistant tool_calls + tool response 轨迹。
- 用 checking agent 校验工具调用过程是否符合任务。
- 产出 JSONL 训练样本和工具使用分布图。

它不是严格意义上的 agentic RL，因为：

- 没有 reward model 训练。
- 没有 PPO/GRPO/DPO 这类策略优化循环。
- 没有环境 rollout 后基于 reward 更新 assistant policy。
- 主要训练目标是 assistant 生成正确 tool call，属于 SFT/tool-use imitation 数据。

可以谨慎表述为：

- “构建了面向邮件 Agent 的 tool-use 训练数据生成与校验框架。”
- “生成 assistant function-calling 轨迹，用于 SFT/指令微调数据。”
- “具备 agentic data generation / tool-use trajectory synthesis 特征。”

不建议写：

- “完成 agentic RL 训练。”
- “基于 GRPO/PPO 优化 Agent 策略。”
- “训练完整 Agent 系统。”

## 5. 金融项目不训练时，harness 工程应该满足什么

金融多 Agent 项目不一定要训练。它更应该满足 harness 工程：

- 固定输入：symbol、period、topic、engines、execution_mode。
- 固定输出：report、claims、evidence、citations、trace、verification。
- 固定工具：每个 tool 有 JSON schema、参数类型、默认值和错误返回。
- 固定评测：同一 case 可以重复跑，输出 case-level pass/fail 和失败原因。
- 固定基线：single prompt、single RAG、old pipeline、multi-agent workflow。
- 固定观测：每个 Agent 耗时、工具调用次数、失败次数、token/cost、返工次数。

当前已有一部分 harness 基础，但还缺专门的 baseline runner 和汇总指标。

## 6. Memory 应该放在哪里，和 Prompt 是什么关系

当前金融项目应该把 Memory 定位为 task-state memory，而不是长期记忆。

应该使用 Memory 的地方：

- Planning：记住本轮任务范围、symbol、period、输出要求，避免任务漂移。
- Research/Browser：记住已找到的 primary source、market source、弱来源和缺口。
- Analyze：记住可用财务指标、估值假设、缺失字段。
- FinalAnswer：记住必须覆盖的 claims、Verifier 反馈、禁止再犯的问题。
- Verifier：记住本轮检查出的 errors/warnings/evidence gaps。

Prompt 与 Memory 的关系：

- Prompt 是角色和规则。
- Memory 是本轮任务状态和压缩事实。
- Schema 是 Agent 之间交换数据的契约。
- Tool 是可执行能力。

不要把所有历史对话塞进 Prompt。应由 `context_packer` 把 memory 压缩成 `conversation_brief`，只把当前阶段需要的信息传给 Agent。

## 7. 是否需要 Skill，哪些可以沉淀成 Skill

需要，但不是一开始就把所有模块都做成 skill。

适合沉淀成 Skill 的能力：

- SEC CompanyFacts 财报抽取与指标口径说明。
- A/H 股公告来源发现和中文财报抽取流程。
- 估值模型选择：科技公司、银行、消费品、白酒不同方法。
- Citation QA：弱来源识别、引用去重、claim-evidence 对齐。
- Verifier 返工策略：不同 gap 路由到哪个 Agent。
- 金融报告模板：公司/个股研报章节、合规披露、评级说明。

Skill 的价值是把“可复用领域流程”从 Prompt 里拿出来，变成可版本化、可动态加载的能力说明和脚本。

## 8. Skill 怎么动态加载

推荐设计：

- `skills/skill_name/SKILL.md`：说明适用场景、输入、输出、约束。
- `skills/skill_name/schema.json`：定义可调用参数。
- `skills/skill_name/tools.py`：可选工具函数。
- `SkillRegistry`：扫描 skill 目录，读取 metadata。
- `SkillRouter`：根据 task_type、symbol market、report_type、verification gaps 选择 skill。
- `ContextPacker`：只把选中 skill 的摘要放进 Agent prompt，避免上下文爆炸。

金融项目里可以先做静态 registry，后续再让 PlanningAgent/Router 动态选择。

## 9. MCP 应该接哪些外部协议或服务

当前是 MCP-style HTTP/JSON-RPC，不是正式 MCP SDK。

如果升级，优先接：

- 官方 MCP SDK：让工具能被标准 MCP client 发现和调用。
- SEC filings / CompanyFacts tool。
- Yahoo Finance / market data tool。
- 本地 evidence store retrieval tool。
- 文件系统报告产物读取 tool。
- 浏览器/PDF reader tool。
- 数据库或对象存储 tool：保存 runs、eval cases、trace。
- 可选：GitHub/Notion/Slack 等协作工具，但这不是金融报告主链核心。

核心原则：先把金融工具协议化，不要为了 MCP 而接一堆无关外部服务。

## 10. ReAct 当前怎么做，哪里不足

当前 ReAct 在 `src/agents/react_loop.py`，Research 和 Analyze 可选启用：

- 模型收到 tool schemas。
- 模型产生 tool_calls。
- 代码执行工具。
- Observation 作为 tool message 回填。
- 循环到无 tool call 或 max_steps。

不足：

- ReAct 只覆盖部分 Agent，不是全链路。
- 工具选择没有严格的 tool-call accuracy 评估。
- stop condition 比较简单，主要靠无 tool call 或 max_steps。
- 工具失败后的恢复策略较弱。
- Observation 压缩较粗，可能丢关键字段。
- 没有把每次 ReAct trace 统一纳入 eval 指标。

## 11. 可观测性怎么完善

当前已有 `task_trace.jsonl`、`run_summary.json`、`verification_report.json`、`revision_history.json`。

建议补：

- 每个 Agent 的 input/output token、cost、latency。
- 每次 tool call 的 name、arguments、result size、success/error、duration。
- 每个 claim 的来源路径：claim -> evidence -> source_url -> table/metric。
- 每轮 rework 的 diff：修改了哪些 section、哪些 citation。
- failure taxonomy：missing_primary_source、symbol_mismatch、period_mismatch、unsupported_number、tool_error、timeout。
- dashboard：按 case 聚合 pass rate、latency、tool count、cost、rework rounds。

## 12. 每次优化什么，怎么优化

建议按失败类型优化：

- 引用缺失：优化 CitationManager 和 FinalAnswer citation instruction。
- 数字错误：优化 financial_ratios、CompanyFacts 映射和 numeric audit。
- 估值不合理：优化 valuation assumptions、行业方法选择和 sanity check。
- 搜索质量差：优化 SearchManager engine ranking 和 source authority。
- 报告空章节：优化 claim packing 和 FinalAnswer backfill。
- 耗时过长：优化 fast/default profile、缓存、并发和 pro model 条件路由。
- 工具乱调用：优化 tool schema、参数 enum、工具描述和 ReAct max_steps。

## 13. 项目中有没有 schema 工具设计，怎么考虑参数

有。金融项目有两类 schema：

- 数据 schema：EvidenceItem、ClaimItem、ReportDocument、ReportTask。
- 工具 schema：`ToolRegistry` 中每个 ToolSpec 的 JSON schema。

工具参数设计原则：

- 必填参数少而明确，例如 `symbol`、`period`、`records`、`query`。
- 枚举收窄选择，例如 `ranking_mode` 限定 bm25/vector/hybrid/reranker/hybrid_rerank。
- 结果必须结构化，不返回纯文本。
- 参数名和业务口径一致，例如 `raw_data_root`、`use_chunks`、`range_`、`interval`。
- 工具职责单一，不把检索、计算、写作塞进同一个工具。
- 对金融高风险字段保留 metadata、source_url、evidence_id，便于后续验证。

## 14. Baseline 指标应该怎么设计

建议三个核心指标可以映射成金融项目版本。

### 任务完成率

SQL 场景是“SQL 能执行、结果也对”。金融项目可定义为：

- report artifacts 是否全部生成。
- `verification_report.passed == true`。
- required sections 是否齐全。
- `claim_count/citation_count/evidence_count` 达到最低阈值。
- `company_report_scorecard.passed == true`。

### 工具调用准确率

SQL 场景是“有没有多余调用、该调用是否调用”。金融项目可定义为：

- 需要财务数据时是否调用 SEC/local financials。
- 需要行情时是否调用 Yahoo/market data。
- 需要 A 股时是否调用 china_finance source discovery，而不是 SEC。
- 估值前是否调用 ratios/statement/valuation tools。
- 无关工具调用次数占比。
- tool arguments 是否符合 schema，symbol/period 是否正确。

### 平均耗时

金融项目可以统计：

- total_duration_sec。
- 每个 Agent duration_sec。
- 每个 tool duration_sec。
- rework rounds 带来的额外耗时。
- fast/default profile 的耗时差异。

推荐 baseline：

- `baseline_0_single_prompt`：只给原始问题，让 LLM 直接写。
- `baseline_1_single_rag`：检索 top-k evidence 后一次生成。
- `baseline_2_old_pipeline`：Planner/Analyst/Writer/Verifier 旧规则链。
- `baseline_3_multi_agent_workflow`：当前多 Agent workflow。

只有把这些跑完，才能写“相比 baseline 提升”。
