# Phase 3 Pre-Implementation Audit

## 目标

在修改代码前，审查当前 P1-B routed rework 的实际执行逻辑，明确哪些可被 DynamicRouter 复用，哪些不应推倒重来。

## 1. 当前 owner selection 具体在哪里实现

文件：`src/agents/multi_agent_orchestrator.py`

函数：`_supported_rework_owner(gap_type, routed_to)` (line ~1834)

```python
candidates = {
    "EVIDENCE_GAP": [("ResearchAgent", "research"), ("BrowserAgent", "browser")],
    "NUMERIC_GAP": [("AnalyzeAgent", "analyze")],
    "CITATION_GAP": [("ResearchAgent", "research")],
    "RISK_GAP": [("RiskAgent", "risk")],
    "PEER_GAP": [("PeerComparisonAgent", "peer")],
    "FORMAT_GAP": [("FinalWriterAgent", "final_answer")],
}
```

逻辑：遍历 candidates，找到第一个 route_agent 在 `routed_to` 中的 owner_key 返回；否则返回 `None`（fallback）。

这是纯 rule-based 静态映射，不读取 state / task board / message history / budget。

## 2. 哪些 gap 类型已真实 executable

| GapType | owner_key | 实际执行 agent |
|---|---|---|
| `EVIDENCE_GAP` | `research` | `DeepResearcherAgent` |
| `NUMERIC_GAP` | `analyze` | `DeepAnalyzeAgent` |
| `CITATION_GAP` | `research` | `DeepResearcherAgent` |
| `RISK_GAP` | `risk` | `RiskAgent` |
| `PEER_GAP` | `peer` | `PeerComparisonAgent` |
| `FORMAT_GAP` | `final_answer` | `FinalAnswerAgent` |

## 3. 哪些 gap 类型仍显式 fallback

| GapType | fallback 行为 |
|---|---|
| `VALUATION_GAP` | `actually_executed_agent = "fallback_unified_final_answer"` |
| `COMPLIANCE_GAP` | 同上 |
| `SYMBOL_PERIOD_MISMATCH` | 同上 |
| `SOURCE_CONFLICT` | 同上 |

Fallback 会写入 `rework_trace` 和 `agent_messages`，不 silent fail。

## 4. 当前 routed rework 与统一 FinalAnswer rework 的执行顺序

在 `_run_verifier_rework_loop` 中（line ~995）：

```text
for round_index in range(1, max_rounds + 1):
    1. build_revision_brief(verification_report)
    2. _run_routed_gap_rework(state, round_index, blackboard)   <- P1-B targeted pre-rework
    3. FinalAnswerAgent rewrite (unified)                        <- 原统一 rework
    4. VerifierAgent recheck
    5. _update_gap_trace_after_rework
    6. _sync_gap_routes_to_blackboard
```

P1-B 是在统一 FinalAnswer rework 前的 targeted pre-rework，不是替换。

## 5. 当前 TaskBoard / AgentMessage / Blackboard 在 routed rework 中如何被更新

### Blackboard 初始化

在 `_run_verifier_rework_loop` 开始时：

```python
blackboard = self._active_blackboard or Blackboard(state=state)
self._active_blackboard = blackboard
```

### TaskBoard 更新

每个 routed gap task：

- `add_gap_task(gap_id, gap_type, owner_agent)` -> `queued`
- `update_status(task_id, RUNNING)` -> 执行前
- `update_status(task_id, RESOLVED / FAILED)` -> 执行后
- unsupported gap: `update_status(task_id, WAITING_REVIEW)`

### AgentMessage 更新

每个 routed gap 产生 3 条消息：

1. `VerifierAgent -> GapRouter`: `routed_rework_requested`
2. `GapRouter -> owner_agent`: `routed_rework_assigned`
3. `owner_agent -> VerifierAgent`: `routed_rework_completed / routed_rework_failed`

unsupported gap 产生 1 条：

- `GapRouter -> Orchestrator`: `routed_rework_fallback`

### rework_trace 更新

每个 gap 写入：

- `gap_id`, `gap_type`, `routed_to`, `actually_executed_agent`
- `before_state_ref`, `after_state_ref`
- `resolved`, `latency`, `status`

## 6. 哪些逻辑可被 DynamicRouter 复用，哪些不应推倒重来

### 可复用（不应重写）

- `_execute_one_routed_gap_rework(...)` — 实际 agent 执行逻辑
- `_routed_rework_task(...)` — 构建 AgentTask
- `_ensure_rework_row(...)` — rework_trace 行管理
- `_state_snapshot_ref(...)` — state 快照
- `_supported_rework_owner(...)` — 可作为 DynamicRouter 的 fallback 查询
- `_sync_gap_routes_to_blackboard(...)` — gap -> TaskBoard 同步
- `_message_type_for_gap(...)` — gap type -> message type 映射
- `merge_task_result(...)` — state merge
- `TaskBoard`, `AgentMessage`, `Blackboard` — Phase 2 基础设施

### 不应推倒重来

- `GapRouter` — Phase 1 已完成，DynamicRouter 读取其 route 结果
- `TaskBoard / AgentMessage / Blackboard` — Phase 2 已完成
- `_run_verifier_rework_loop` 的整体结构 — 保留，DynamicRouter 作为其中一种 rework 策略

### DynamicRouter 新增的职责

- 读取 open gaps、task board snapshot、recent messages、budget state、执行历史
- 决定下一步 action（execute / fallback / stop）
- 避免重复派发同一 owner 处理同一 unresolved gap
- 多次返工未改善时允许 fallback 或 stop
- 输出 RouterDecision，写入 `router_decisions.jsonl`
- 与 BudgetGuard 协作，在预算耗尽时停止

## 结论

P1-B 的 rule-based owner selection 是 DynamicRouter 的一个特殊情况（无状态、无历史、无预算）。Phase 3 应在不删除 P1-B 路径的前提下，把 DynamicRouter 作为 `dynamic_multiagent` 模式下的调度层，复用已有 executor 逻辑。

三种模式并存：

| mode | rework 策略 |
|---|---|
| `legacy_workflow` | 无 routed rework，只有统一 FinalAnswer rework |
| `routed_rework` | P1-B rule-based routed rework + 统一 FinalAnswer rework |
| `dynamic_multiagent` | DynamicRouter + BudgetGuard + 复用 P1-B executors |
