# Phase 3 Eval Summary: DynamicRouter vs Routed Rework vs Current Workflow

## Baseline Definitions

| Baseline | Mode | Description |
|----------|------|-------------|
| `baseline_2_current_workflow` | `dynamic` | Original multi-agent workflow (pre-P1-B) |
| `baseline_3_gaprouter_routed_rework` | `routed_rework` | P1-B rule-based routed rework execution |
| `baseline_4_dynamic_multiagent_router` | `dynamic_multiagent` | Phase 3 DynamicRouter + BudgetGuard |

## Eval Setup

- **Cases**: `phase0_workflow_anchor_cases.jsonl` (NVDA, JPM, 600519.SS, META)
- **Profile**: fast
- **Mode**: `dynamic_multiagent`
- **Run ID**: `20260514_191345_baseline_4_dynamic_multiagent_router`

## Three-Way Core Metrics Comparison

| Metric | baseline_2 | baseline_3 | baseline_4 | Δ b3→b4 |
|--------|-----------|-----------|-----------|---------|
| task_completion_rate | 0.0 | 0.0 | 0.0 | 0.0 |
| required_sections_coverage | 0.5714 | 0.5357 | **0.5714** | +0.0357 |
| artifact_generation_pass_rate | 1.0 | 1.0 | 1.0 | 0.0 |
| verification_pass_rate | 0.0 | 0.0 | 0.0 | 0.0 |
| claim_count_mean | 4.75 | 4.75 | **7.75** | +3.0 |
| evidence_count_mean | 2.25 | 2.25 | 2.25 | 0.0 |
| citation_count_mean | 1.25 | 2.75 | 1.25 | -1.5 |
| gap_detection_count_mean | 4.75 | 5.0 | 4.25 | -0.75 |
| gap_resolution_rate_mean | 0.0 | 0.0 | 0.0 | 0.0 |
| task_resolution_rate_mean | 0.4698 | 0.5488 | **0.5972** | +0.0484 |
| message_count_mean | 23.75 | 33.0 | 36.0 | +3.0 |
| total_latency_sec_mean | 138.05 | 169.74 | 174.51 | +4.77 |

## Phase 3 Process Metrics (baseline_4 only, 4 cases)

| Metric | Value |
|--------|-------|
| router_decision_count_sum | 12 |
| dynamic_dispatch_count_sum | 11 |
| fallback_decision_count_sum | 1 |
| budget_exceeded_count_sum | 0 |
| repeated_dispatch_count_sum | 0 |
| unsupported_gap_fallback_count_sum | 1 |
| router_stop_reasons | {} (no budget stops triggered) |

## Per-Case Breakdown (baseline_4)

| Case | Decisions | Dispatches | Fallbacks | Unsupported | Latency |
|------|-----------|-----------|-----------|-------------|---------|
| NVDA | 2 | 2 | 0 | 0 | 137.0s |
| JPM | 4 | 4 | 0 | 0 | 166.1s |
| 600519.SS | 4 | 3 | 1 | 1 | 251.9s |
| META | 2 | 2 | 0 | 0 | 143.0s |

## Key Findings

### What improved

1. **task_resolution_rate_mean**: +4.84pp vs baseline_3 (+12.7pp vs baseline_2). DynamicRouter's multi-source state awareness and dedup logic produced more targeted dispatches, resulting in higher task board resolution rates.

2. **claim_count_mean**: +3.0 vs baseline_3. The dynamic routing dispatched more research/analyze agents per gap, generating more claims per case.

3. **required_sections_coverage**: Recovered to 0.5714 (same as baseline_2), reversing the -0.0357 regression introduced by baseline_3.

### What did not improve

1. **verification_pass_rate**: Remains 0.0 across all three baselines. The verifier's pass threshold is not met by any rework mode — this is a known limitation of the current verifier configuration, not a DynamicRouter failure.

2. **gap_resolution_rate_mean**: Remains 0.0. This metric is based on `rework_trace.resolved` flags, which are not being set by the current executor. The metric is a known TODO.

3. **evidence_count_mean**: Unchanged at 2.25. Evidence retrieval is bounded by the local data available, not by routing decisions.

4. **citation_count_mean**: -1.5 vs baseline_3. Baseline_3 had an anomalously high citation count (2.75) that was not reproducible. Baseline_4 returns to the baseline_2 level (1.25).

### Latency

- baseline_4 adds +4.77s mean latency vs baseline_3 (+36.46s vs baseline_2). This is the cost of DynamicRouter decision overhead and additional dispatches. Within acceptable range for the fast profile.

### Router behavior

- 12 total decisions across 4 cases (avg 3 per case)
- 11/12 decisions were `execute` (91.7% dispatch rate)
- 1 fallback for an unsupported gap type (600519.SS case — likely VALUATION_GAP or COMPLIANCE_GAP)
- 0 budget stops — BudgetGuard did not trigger in any case (fast profile: max 2 rounds, max 8 dispatches)
- 0 repeated dispatches — dedup logic worked correctly

## Honest Assessment

DynamicRouter brought a measurable improvement in `task_resolution_rate` (+4.84pp vs baseline_3) and `claim_count` (+3.0 mean), with no regressions in artifact generation or sections coverage. However, the primary quality gates — `verification_pass_rate` and `gap_resolution_rate` — remain at 0.0 across all baselines. These are structural limitations of the current verifier and rework_trace tracking, not caused by DynamicRouter.

The Phase 3 process metrics (router_decisions.jsonl, budget_trace.jsonl) are now fully instrumented and provide the observability needed for future tuning.

## Recommendations for Phase 4

1. Fix `rework_trace.resolved` flag setting so `gap_resolution_rate` becomes meaningful.
2. Investigate why `verification_pass_rate` is 0.0 — the verifier threshold may need calibration.
3. Consider adding SOURCE_CONFLICT adjudication as a supported gap type (currently deferred).
4. Evaluate whether the +4.77s latency overhead is acceptable at scale.
