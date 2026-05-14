# Phase 2 Agent Message / TaskBoard Summary

## 目标

Phase 2 为后续真正多智能体协作补齐基础设施：

```text
显式 AgentMessage -> 统一 TaskBoard -> Blackboard 状态接口 -> 可记录 / 可回放协作过程
```

本阶段保持现有主链路可运行，不一次性重构全部 agent 行为；新增协作状态作为 additive artifacts 输出。

## AgentMessage Schema

新增：

- `src/multiagent/messages/schema.py`
- `src/multiagent/messages/__init__.py`

定义 `MessageType`：

- `REQUEST_EVIDENCE`
- `CHALLENGE_CLAIM`
- `REQUEST_RECALCULATION`
- `PROPOSE_REVISION`
- `APPROVE_SECTION`
- `REJECT_SECTION`
- `ESCALATE_CONFLICT`
- `STATUS_UPDATE`

定义 `MessageStatus`：

- `created`
- `sent`
- `handled`
- `failed`

`AgentMessage` 字段：

- `message_id`
- `sender_agent`
- `receiver_agent`
- `message_type`
- `related_task_id`
- `related_gap_id`
- `related_claim_ids`
- `payload`
- `priority`
- `created_at`
- `status`

提供：

- `AgentMessage.create(...)`
- `to_dict()`
- `from_dict(...)`
- `with_status(...)`

## TaskBoard

新增：

- `src/multiagent/taskboard/board.py`
- `src/multiagent/taskboard/__init__.py`

任务状态：

- `queued`
- `running`
- `blocked`
- `waiting_review`
- `resolved`
- `failed`

`TaskBoardItem` 字段：

- `task_id`
- `task_type`
- `owner_agent`
- `dependencies`
- `related_gap_ids`
- `status`
- `last_update`
- `result_ref`

`TaskBoard` 提供：

- `upsert`
- `update_status`
- `add_gap_task`
- `open_tasks`
- `blocked_count`
- `resolution_rate`
- `to_dict`
- `from_plan_tasks`

## Blackboard

新增：

- `src/multiagent/blackboard/state.py`
- `src/multiagent/blackboard/__init__.py`

接口：

- `read_state(key="")`
- `write_state(key, value)`
- `append_message(message)`
- `append_gap(gap)`
- `get_open_tasks()`

Blackboard 目前是现有 `state` dict 的轻量 wrapper，不替换原有数据流，避免破坏现有编排器逻辑。

## Orchestrator 接入

修改：

- `src/agents/multi_agent_orchestrator.py`

动态执行流程新增：

1. 在 `_execute_dynamic_tasks` 开始时，从 plan tasks 初始化 `TaskBoard`。
2. 每个 task 执行前：
   - TaskBoard 状态更新为 `running`；
   - 写入 Orchestrator -> Agent 的 `STATUS_UPDATE` message。
3. 每个 task 执行后：
   - 写入 Agent -> Orchestrator 的 `STATUS_UPDATE` message；
   - 成功时 TaskBoard 状态更新为 `resolved`；
   - 失败时 TaskBoard 状态更新为 `failed`。
4. 如果动态图依赖无法满足：
   - pending task 标记为 `blocked`；
   - 抛出原有阻塞异常，避免静默死循环。
5. Verifier 产生 structured gaps 后：
   - GapRouter route 写入 TaskBoard gap rework task；
   - route action 写入 `agent_messages`；
   - gap payload 同步到 Blackboard `gaps`。
6. Rework loop 中的 final rewrite / verifier recheck 也写入 TaskBoard 与 AgentMessage。

## 新增 Artifacts

动态主链新增输出：

```text
task_board.json
agent_messages.jsonl
```

`run(...)` 返回 artifacts 中新增：

- `task_board`
- `agent_messages`

`run_summary.json` 新增过程统计：

- `message_count`
- `task_blocked_count`
- `task_resolution_rate`

## Eval 过程指标

修改：

- `src/eval/metrics.py`

新增指标：

- `message_count`
- `task_blocked_count`
- `task_resolution_rate`

`compute_case_metrics(...)` 会从 artifacts 中读取：

- `agent_messages.jsonl`
- `task_board.json`

`aggregate_metrics(...)` 新增聚合：

- `message_count_mean`
- `task_blocked_count_mean`
- `task_resolution_rate_mean`

## 测试

新增：

- `tests/test_phase2_message_taskboard.py`

覆盖：

1. `AgentMessage` schema roundtrip 与 priority clamp；
2. `TaskBoard` open / blocked / resolution rate；
3. `Blackboard` read / write / append / open tasks；
4. GapRouter route 写入 TaskBoard 与 AgentMessage；
5. 动态执行流程记录 TaskBoard 与 message log；
6. Phase 2 eval process metrics。

执行：

```text
PYTHONPATH=/Users/yuan_dian/AI_project/DeepReport_plus python -m pytest \
  /Users/yuan_dian/AI_project/DeepReport_plus/tests/test_phase2_message_taskboard.py \
  /Users/yuan_dian/AI_project/DeepReport_plus/tests/test_phase0_eval_metrics.py \
  /Users/yuan_dian/AI_project/DeepReport_plus/tests/test_gap_router_phase1.py
```

结果：

```text
20 passed in 0.52s
```

## Review

### 是否出现死循环

未发现。动态图原本在无 ready task 时抛出异常；Phase 2 保留该行为，并在抛出前把 pending task 标记为 `blocked`。

### 是否影响现有报告生成

保持 additive 接入：现有 `state`、`task_trace.jsonl`、`gap_resolution_trace.jsonl`、`rework_trace.json` 仍保留；新增 `task_board.json` 与 `agent_messages.jsonl` 不改变核心 agent 输出格式。

### 是否能从 artifacts 回放协作过程

可以进行基础回放：

- `agent_messages.jsonl` 记录每个 agent task 的开始 / 结束与 GapRouter 协作请求；
- `task_board.json` 记录 plan task、gap rework task、状态、依赖与 owner；
- `task_trace.jsonl` 仍保留详细执行 trace。

### schema 是否过度复杂

当前 schema 保持最小可用：只包含消息、任务、状态、关联 task/gap/claim 与 payload。复杂协商、冲突裁决、权限和长期 memory 没有在本阶段引入。

## 后续建议

1. Phase 3 可将 GapRouter 创建的 gap rework task 真正调度到对应 Agent，而不是只记录 route。
2. 为 `SOURCE_CONFLICT` 引入真实 Adjudicator 后，将 `FutureAdjudicator` route 替换为可执行 agent。
3. 增加 replay 工具，从 `agent_messages.jsonl` + `task_board.json` 重建一次协作时序。
