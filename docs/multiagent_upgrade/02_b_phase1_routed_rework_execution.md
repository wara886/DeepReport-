# P1-B Routed Rework Execution

## 目标

Phase 1 已完成：

```text
canonical gap detection -> GapRouter route planning -> rework_trace metadata
```

P1-B 在不引入 Phase 3 DynamicRouter 的前提下，补齐最小可用的 rule-based routed rework execution：

```text
Verifier gaps -> GapRouter -> rule-based owner selection -> execute corresponding Agent -> update state / TaskBoard / AgentMessage / rework_trace
```

原统一 `FinalAnswerAgent` rework loop 保留，不回退。

## 实现位置

修改：

- `src/agents/multi_agent_orchestrator.py`

新增 / 更新逻辑：

- `_run_routed_gap_rework(...)`
- `_execute_one_routed_gap_rework(...)`
- `_supported_rework_owner(...)`
- `_routed_rework_task(...)`
- `_ensure_rework_row(...)`
- `_state_snapshot_ref(...)`
- `merge_task_result(...)` 支持 `risk` / `peer` routed task merge
- `agent_key_for_task(...)` 支持 `risk` / `peer`

## 已支持真实执行的 gap 类型

当前为 rule-based minimal execution，支持以下类型真实调用对应 agent：

| GapType | route metadata | actually executed owner | 执行动作 |
|---|---|---|---|
| `EVIDENCE_GAP` | `ResearchAgent / BrowserAgent` | `research` -> `DeepResearcherAgent` | 重新检索证据并 merge `evidence_candidates` |
| `NUMERIC_GAP` | `AnalyzeAgent` | `analyze` -> `DeepAnalyzeAgent` | 基于现有 evidence 重新分析并 merge claims / analysis_artifacts |
| `CITATION_GAP` | `CitationManager / ResearchAgent` | `research` -> `DeepResearcherAgent` | 先通过 ResearchAgent 补证据，CitationManager 尚未作为独立 agent 执行 |
| `RISK_GAP` | `RiskAgent` | `risk` -> `RiskAgent` | 重新生成 risk claims 并 merge claims |
| `PEER_GAP` | `PeerComparisonAgent` | `peer` -> `PeerComparisonAgent` | 重新生成 peer claims / evidence 并 merge |
| `FORMAT_GAP` | `FinalWriterAgent` | `final_answer` -> `FinalAnswerAgent` | 用 format repair revision_request 重写 report |

## 尚未支持真实执行的 gap 类型

以下类型仍是 route metadata 或显式 fallback，不 silent fail：

| GapType | 当前行为 |
|---|---|
| `VALUATION_GAP` | 显式 fallback 到 unified FinalAnswer rework；估值模块尚未作为 routed executable owner 接入 |
| `COMPLIANCE_GAP` | 显式 fallback；ComplianceModule 尚未作为独立 agent 接入 |
| `SYMBOL_PERIOD_MISMATCH` | 显式 fallback；PlannerAgent + ResearchAgent 的重规划尚未拆入 routed execution |
| `SOURCE_CONFLICT` | 显式 fallback；FutureAdjudicator 未实现 |

Fallback 会在 `rework_trace` 中写入：

- `actually_executed_agent = "fallback_unified_final_answer"`
- `fallback_reason = "unsupported_gap_type:<TYPE>"`

并在 `task_board.json` 中记录 `waiting_review` 状态。

## rework_trace 更新

P1-B 后 `rework_trace.json` 行会尽量包含：

- `gap_id`
- `gap_type`
- `routed_to`
- `actually_executed_agent`
- `before_state_ref`
- `after_state_ref`
- `resolved`
- `latency`
- `status`

其中：

- `before_state_ref` / `after_state_ref` 是 lightweight state snapshot，例如 claims/evidence/citation/report size 计数；
- `resolved` 仍需后续 verifier recheck 才能最终确认；routed agent 执行完成后先标记为 `executed_pending_verification`；
- 原统一 FinalAnswer rework 仍会继续运行并进行 verifier recheck。

## TaskBoard / AgentMessage

P1-B routed execution 会写入：

### task_board.json

每个 routed gap rework 都会有对应 task：

- supported gap：`queued -> running -> resolved / failed`
- unsupported gap：`waiting_review`

### agent_messages.jsonl

新增消息事件包括：

- Verifier -> GapRouter：`routed_rework_requested`
- GapRouter -> Agent：`routed_rework_assigned`
- Orchestrator -> Agent：`task_started`
- Agent -> Orchestrator：`task_finished`
- Agent -> Verifier：`routed_rework_completed` / `routed_rework_failed`
- unsupported gap：`routed_rework_fallback`

## 与原统一 FinalAnswer rework 的差异

原逻辑：

```text
Verifier failed -> build_revision_brief -> FinalAnswerAgent rewrite -> Verifier recheck
```

P1-B 新逻辑：

```text
Verifier failed -> for each canonical gap:
  GapRouter route -> supported owner executes targeted task -> state merge / trace
then:
  原 unified FinalAnswer rework -> Verifier recheck
```

也就是说，P1-B 不是替换原 loop，而是在原统一重写前增加一层 targeted pre-rework，使证据、分析、风险、同业或格式类 gap 有机会先由对应 agent 更新 state。

## 测试

新增：

- `tests/test_phase1_b_routed_rework_execution.py`

覆盖：

1. `EVIDENCE_GAP` 触发 `DeepResearcherAgent` 路径；
2. `NUMERIC_GAP` 触发 `DeepAnalyzeAgent` 路径；
3. `FORMAT_GAP` 触发 `FinalAnswerAgent` 路径；
4. `SOURCE_CONFLICT` 等未支持 gap 类型显式 fallback，不 silent fail；
5. `rework_trace` 写入 `actually_executed_agent`、`before_state_ref`、`after_state_ref`；
6. `task_board` 和 `agent_messages` 记录真实执行状态。

执行命令：

```text
cd /Users/yuan_dian/AI_project/DeepReport_plus && PYTHONPATH=. python -m pytest \
  tests/test_phase1_b_routed_rework_execution.py \
  tests/test_phase2_message_taskboard.py \
  tests/test_gap_router_phase1.py \
  tests/test_request_understanding.py \
  tests/test_phase0_eval_metrics.py
```

结果：

```text
33 passed in 0.59s
```

## 是否已具备进入 Phase 3 的条件

P1 已从 route planning 进入最小 route execution，但还不是完整 Phase 3 级动态调度。

已具备的条件：

- GapRouter route 可以触发真实 agent execution；
- TaskBoard 能记录 routed gap task 的状态；
- AgentMessage 能记录 routed request / assignment / completion；
- unsupported gap 显式 fallback；
- 原 workflow 与原 rework loop 未被破坏。

仍需 Phase 3 解决：

1. route execution 目前是 rule-based，不是通用 DynamicRouter；
2. `VALUATION_GAP`、`COMPLIANCE_GAP`、`SYMBOL_PERIOD_MISMATCH`、`SOURCE_CONFLICT` 尚未接入真实 executable owners；
3. routed execution 后的 gap-level resolved 判定仍依赖后续整体 verifier recheck，未做到逐 gap closure；
4. CitationManager / ComplianceModule / Adjudicator 仍不是完整 agent。

结论：P1-B 已完成进入 Phase 3 前所需的“最小 routed execution”收口，但 Phase 3 仍需要把 rule-based owner selection 升级为更通用的动态调度与逐 gap 闭环。
