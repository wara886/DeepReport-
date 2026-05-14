你现在进入 Phase 3，但必须基于当前已经完成的真实进度继续推进，而不是重复实现前序能力。

请先阅读以下文档：

1. docs/multiagent_upgrade/01_b_phase0_workflow_baseline_anchor.md
2. docs/multiagent_upgrade/00_5_b_request_understanding_e2e_acceptance.md
3. docs/multiagent_upgrade/02_b_phase1_routed_rework_execution.md
4. docs/multiagent_upgrade/03_phase2_message_taskboard_summary.md
5. docs/multiagent_upgrade/pre_phase3_readiness_review.md

当前项目状态必须作为事实前提：

- P0 已建立正式 `baseline_2_current_workflow_anchor`；
- P0.5 已完成 natural language query -> ResearchRequest -> Planner -> workflow -> report 的 E2E 验收；
- P1-B 已实现最小可用的 rule-based routed rework execution：
  - EVIDENCE_GAP -> DeepResearcherAgent
  - NUMERIC_GAP -> DeepAnalyzeAgent
  - CITATION_GAP -> DeepResearcherAgent 补证据
  - RISK_GAP -> RiskAgent
  - PEER_GAP -> PeerComparisonAgent
  - FORMAT_GAP -> FinalAnswerAgent
- Phase 2 的 AgentMessage / TaskBoard / Blackboard 已存在，并已被 P1-B routed rework 真实使用；
- 当前还不是完整 DynamicRouter；
- 当前 unresolved gap 的 resolved 判定仍主要依赖整体 verifier recheck，而不是逐 gap closure；
- SOURCE_CONFLICT 仍留待后续 Adjudicator 阶段，不要在本阶段提前实现完整冲突裁决。

==================================================
Phase 3 总目标
==================================================

把当前“rule-based routed rework”
升级为：

“基于 TaskBoard、open gaps、AgentMessages、Blackboard state、预算状态和执行反馈的 Dynamic Multi-Agent Router”。

本阶段目标不是：
- 重新实现 GapRouter；
- 重新新建 TaskBoard / AgentMessage；
- 实现 Adjudicator；
- 实现 Memory；
- 实现 SkillRegistry。

本阶段要实现的是：
1. DynamicRouter；
2. BudgetGuard；
3. Router decision trace；
4. `legacy_workflow / routed_rework / dynamic_multiagent` 三种执行模式并存；
5. 对 DynamicRouter 的单元测试与评测；
6. 为后续 Phase 4/5/6 保留清晰扩展点。

==================================================
A. 先做 Phase 3 前的行为审计
==================================================

在改代码前，先审查当前 P1-B routed rework 的实际执行逻辑，明确：

1. 当前 owner selection 具体在哪里实现；
2. 哪些 gap 类型已真实 executable；
3. 哪些 gap 类型仍显式 fallback；
4. 当前 routed rework 与统一 FinalAnswer rework 的执行顺序；
5. 当前 TaskBoard / AgentMessage / Blackboard 在 routed rework 中如何被更新；
6. 哪些逻辑可被 DynamicRouter 复用，哪些不应推倒重来。

输出：
docs/multiagent_upgrade/04_0_phase3_preimplementation_audit.md

==================================================
B. 实现 DynamicRouter
==================================================

新增：

- src/multiagent/router/dynamic_router.py
- src/multiagent/router/schema.py
- src/multiagent/router/__init__.py

设计 RouterInput，至少包含：

- current_state_summary
- open_gaps
- task_board_snapshot
- recent_agent_messages
- previous_router_decisions
- executed_agents_in_current_round
- unresolved_gap_history
- budget_state
- execution_mode

设计 RouterDecision，至少包含：

- decision_id
- selected_action
- selected_agent
- selected_task_type
- related_gap_ids
- reason
- expected_effect
- fallback_used
- stop_recommended
- created_at

DynamicRouter 的职责：

1. 在 routed rework / dynamic rework 场景下，决定下一步要调哪个 agent；
2. 避免重复调度同一 owner 处理同一个 unresolved gap；
3. 如果 gap 已多次返工未改善，允许：
   - fallback to final rewrite
   - stop with unresolved issue
   - wait for future adjudication / unsupported owner
4. 保持 SOURCE_CONFLICT route 为未来 Adjudicator 接口，不在本阶段实现真实裁决；
5. 对尚未真实支持 executable owner 的 gap：
   - VALUATION_GAP
   - COMPLIANCE_GAP
   - SYMBOL_PERIOD_MISMATCH
   - SOURCE_CONFLICT
   明确给出 fallback decision，不得 silent fail。

==================================================
C. 实现 BudgetGuard
==================================================

新增：

- src/multiagent/router/budget_guard.py

BudgetState 至少包含：

- max_total_rounds
- max_routed_rework_rounds
- max_dispatches_per_gap
- max_total_agent_dispatches
- max_total_runtime_sec
- current_round
- current_dispatch_count
- per_gap_dispatch_count
- elapsed_runtime_sec

BudgetGuard 需要提供：

- can_continue(...)
- should_stop(...)
- stop_reason(...)
- budget_snapshot(...)

Stop condition 至少支持：

1. 超过 max_total_rounds；
2. 超过 max_routed_rework_rounds；
3. 单 gap 重复调度超过阈值；
4. 总 dispatch 次数超过阈值；
5. 总 runtime 超过阈值；
6. 当前没有可执行 action。

==================================================
D. Orchestrator 接入
==================================================

修改：
- src/agents/multi_agent_orchestrator.py

要求新增三种 execution mode：

1. legacy_workflow
   - 原有 workflow，不使用 routed rework dynamic router；
   - 用于旧 baseline 对比。

2. routed_rework
   - 当前 P1-B rule-based routed rework；
   - 保留，不得被 DynamicRouter 覆盖；
   - 用于 P1-B baseline 对比。

3. dynamic_multiagent
   - 使用 DynamicRouter + BudgetGuard；
   - 读取 open gaps / task board / messages / budget；
   - 动态选择下一步 agent；
   - 仍复用已有 routed rework executors；
   - 不重新写一套重复执行器。

DynamicRouter 应该调度“已有可执行 routed rework owner”，而不是重新实现 agent 执行逻辑。

==================================================
E. 新增 Router Artifacts
==================================================

新增输出：

- router_decisions.jsonl
- budget_trace.jsonl

router_decisions.jsonl 每条至少记录：

- decision_id
- round
- selected_agent
- selected_action
- related_gap_ids
- reason
- expected_effect
- fallback_used
- stop_recommended

budget_trace.jsonl 每条至少记录：

- round
- current_dispatch_count
- per_gap_dispatch_count
- elapsed_runtime_sec
- can_continue
- stop_reason

run_summary.json 新增过程统计：

- router_decision_count
- dynamic_dispatch_count
- router_stop_reason
- budget_exceeded_count
- fallback_decision_count

==================================================
F. Eval 指标扩展
==================================================

修改：
- src/eval/metrics.py
- src/eval/evaluator.py

新增 Phase 3 过程指标：

- router_decision_count
- dynamic_dispatch_count
- fallback_decision_count
- budget_exceeded_count
- router_stop_reason_distribution
- repeated_dispatch_count
- unsupported_gap_fallback_count

保留并继续跟踪已有指标：

- task_completion_rate
- required_sections_coverage
- artifact_generation_pass_rate
- verification_pass_rate
- gap_detection_count_mean
- gap_resolution_rate_mean
- task_resolution_rate_mean
- total_latency_sec_mean
- claim_count_mean
- evidence_count_mean
- citation_count_mean
- message_count_mean

==================================================
G. 单元测试
==================================================

新增：
- tests/test_phase3_dynamic_router.py
- tests/test_phase3_budget_guard.py
- tests/test_phase3_orchestrator_modes.py

至少覆盖：

1. CITATION_GAP / EVIDENCE_GAP / NUMERIC_GAP 存在时，DynamicRouter 选择合理 owner；
2. 同一 gap 已被同一 owner 多次处理且未改善时，不无限重复派发；
3. unsupported gap 类型走显式 fallback；
4. BudgetGuard 达到限制时触发 stop；
5. `legacy_workflow / routed_rework / dynamic_multiagent` 三种 mode 不互相污染；
6. router_decisions.jsonl 与 budget_trace.jsonl 正确落盘；
7. DynamicRouter 复用已有 routed rework executor，而不是绕开原执行逻辑。

==================================================
H. 最小真实评测
==================================================

Phase 3 实现后，使用与正式 workflow anchor 相同的 case：

- eval/cases/phase0_workflow_anchor_cases.jsonl

运行：

baseline_4_dynamic_multiagent_router

输出：
eval_outputs/baseline_4_dynamic_multiagent_router/

并生成：
docs/multiagent_upgrade/04_phase3_dynamic_router_eval_summary.md

文档必须对比：

A. baseline_2_current_workflow_anchor
B. baseline_3_gaprouter_routed_rework（如果已存在）
C. baseline_4_dynamic_multiagent_router

至少比较：

- task_completion_rate
- required_sections_coverage
- verification_pass_rate
- gap_resolution_rate_mean
- task_resolution_rate_mean
- total_latency_sec_mean
- router_decision_count_mean
- fallback_decision_count_mean
- budget_exceeded_count

如果 baseline_3_gaprouter_routed_rework 尚未存在，
必须明确说明“无法进行三阶段独立归因”，并建议先补跑 baseline_3。

==================================================
I. 最终文档输出
==================================================

输出：

1. docs/multiagent_upgrade/04_0_phase3_preimplementation_audit.md
2. docs/multiagent_upgrade/04_phase3_dynamic_router_summary.md
3. docs/multiagent_upgrade/04_phase3_dynamic_router_eval_summary.md

`04_phase3_dynamic_router_summary.md` 必须明确回答：

1. Phase 3 新增了什么能力；
2. 它与 P1-B rule-based routed rework 的本质区别；
3. DynamicRouter 是否真正基于 state / gaps / task board / messages / budget 做调度；
4. 哪些决策仍是规则化而非模型化；
5. 哪些 gap 类型仍未完整 executable；
6. 为什么本阶段仍不实现 Adjudicator / Memory / Skill；
7. 是否具备进入 Phase 4 的条件。

==================================================
J. 约束
==================================================

1. 不要重写前序已经完成的 GapRouter / TaskBoard / AgentMessage；
2. 不要删除 routed_rework 模式；
3. 不要把 DynamicRouter 做成纯 if-else 的重复包装，必须明确使用多源状态输入；
4. 不要把 SOURCE_CONFLICT 的真实裁决提前塞进 Phase 3；
5. 不要把 Memory / SkillRegistry 提前塞进 Phase 3；
6. 不要夸大 Phase 3 效果，所有提升必须以 eval 输出为准；
7. 如果 DynamicRouter 没有带来质量提升，要如实记录；
8. 保证旧测试与新测试全部通过。