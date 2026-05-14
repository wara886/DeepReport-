# Phase 1 GapRouter Summary

## 目标

Phase 1 将 Verifier 发现问题后的返工流程，从旧的“泛化重写”推进为：

```text
结构化 gap 检测 -> gap 分类 -> 精准路由到对应 Agent / 模块 -> 返工后记录解决状态
```

本阶段保持 backward compatibility：旧的 `errors` / `warnings` / `evidence_gaps` / `gap_resolution_trace.jsonl` 仍保留，同时新增 canonical `gaps` 与 `rework_trace.json`。

## 新增 Gap Schema

新增：

- `src/multiagent/gaps/schema.py`

定义：

- `GapType`
  - `EVIDENCE_GAP`
  - `NUMERIC_GAP`
  - `VALUATION_GAP`
  - `CITATION_GAP`
  - `RISK_GAP`
  - `PEER_GAP`
  - `FORMAT_GAP`
  - `COMPLIANCE_GAP`
  - `SYMBOL_PERIOD_MISMATCH`
  - `SOURCE_CONFLICT`
- `GapStatus`
  - `open`
  - `routed`
  - `in_progress`
  - `resolved`
  - `unresolved`
- `GapSeverity`
  - `low`
  - `medium`
  - `high`
  - `critical`
- `GapItem`
  - `gap_id`
  - `gap_type`
  - `severity`
  - `detected_by`
  - `related_claim_ids`
  - `related_evidence_ids`
  - `section`
  - `description`
  - `recommended_action`
  - `status`
  - `routed_to_agents`
  - `created_at`
  - `resolved_at`

## 新增 GapRouter

新增：

- `src/multiagent/gaps/router.py`

基础路由规则：

| GapType | Routed To |
|---|---|
| `EVIDENCE_GAP` | `ResearchAgent`, `BrowserAgent` |
| `NUMERIC_GAP` | `AnalyzeAgent` |
| `VALUATION_GAP` | `ValuationAgent`, `CompanyValuationModule` |
| `CITATION_GAP` | `CitationManager`, `ResearchAgent` |
| `RISK_GAP` | `RiskAgent` |
| `PEER_GAP` | `PeerComparisonAgent` |
| `FORMAT_GAP` | `FinalWriterAgent` |
| `COMPLIANCE_GAP` | `FinalWriterAgent`, `ComplianceModule` |
| `SYMBOL_PERIOD_MISMATCH` | `PlannerAgent`, `ResearchAgent` |
| `SOURCE_CONFLICT` | `FutureAdjudicator` |

`SOURCE_CONFLICT` 当前只标记为 future Adjudicator，不假装已完成冲突裁决。

## Verifier 接入

新增：

- `src/multiagent/gaps/detector.py`

`VerifierAgent` 现在会在原有输出基础上新增：

```json
{
  "gaps": [...],
  "gap_count": 3
}
```

兼容性保留：

- `passed`
- `errors`
- `warnings`
- `llm_errors`
- `llm_warnings`
- `fix_recommendations`
- `evidence_gaps`
- `revision_brief`

不会破坏旧 verifier 消费方。

## Rework Trace

新增产物：

```text
rework_trace.json
```

记录字段：

- `gap_id`
- `gap_type`
- `routed_to`
- `before_revision`
- `after_revision`
- `resolved`
- `rounds`
- `latency`
- `status`
- `created_at`
- `resolved_at`

现有动态 rework loop 会在返工后更新：

- still open -> `resolved = false`, `status = unresolved`
- disappeared / downgraded -> `resolved = true`, `status = resolved`

旧产物 `gap_resolution_trace.jsonl` 仍继续写出。

## Eval 指标

已在 `src/eval/metrics.py` 新增：

- `gap_detection_count`
- `gap_resolution_rate`

说明：

- `gap_detection_count` 优先统计 canonical `verification_report.gaps`，若没有则回退到 legacy `evidence_gaps`。
- `gap_resolution_rate` 当前是粗略指标，基于 `rework_trace[].resolved` 统计；未运行返工或无 gap 时为 `0.0`，并在 per-case metrics 中写入备注。

## 测试

新增：

- `tests/test_gap_router_phase1.py`

覆盖：

1. 至少 5 类 gap 的路由正确性；
2. `SOURCE_CONFLICT` 路由到 `FutureAdjudicator`；
3. verifier 文本问题可转 canonical gaps；
4. verifier 输出保留旧字段并新增 `gaps`；
5. `rework_trace` 记录 route / resolved / rounds；
6. eval gap metrics 统计正确。

执行：

```text
cd /Users/yuan_dian/AI_project/DeepReport_plus && PYTHONPATH=. python -m pytest tests/test_gap_router_phase1.py tests/test_phase0_eval_metrics.py tests/test_multi_agent_workflow.py

32 passed in 4.41s
```

## Review

### 是否破坏旧 verifier 输出

未破坏。旧字段仍保留，新增字段为 additive：`gaps`、`gap_count`。

### 是否保持 backward compatibility

保持。旧 `evidence_gaps` 与 `gap_resolution_trace.jsonl` 仍存在；新 `rework_trace.json` 是补充产物。

### 是否能在现有报告样例中触发 gap

可以。单元测试中构造了缺失 evidence、估值复现失败、symbol mismatch、格式缺失、numeric mismatch 等 verifier messages，并验证会生成 canonical gaps。

### 是否能完整记录返工链路

可以记录基础链路：gap -> route -> before_revision -> after_revision -> resolved / unresolved -> rounds。当前 latency 预留为 `0.0`，后续可在真正按 agent 精准重跑时记录各 gap 的 wall-clock latency。

## 后续建议

1. 下一阶段将 `_run_verifier_rework_loop` 从统一 FinalAnswer rework 进一步拆成按 `routed_to_agents` 调用对应 agent。
2. 为 `SOURCE_CONFLICT` 引入 Adjudicator 后，再把 `FutureAdjudicator` 替换为真实 agent route。
3. 将 `gap_resolution_rate` 与 Phase 0 baseline outputs 做多 baseline 对比，形成 GapRouter 引入前后的 delta。
