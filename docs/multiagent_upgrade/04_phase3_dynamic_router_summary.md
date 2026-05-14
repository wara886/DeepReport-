# Phase 3: DynamicRouter — Multi-Source State-Aware Rework Routing

## Summary

Phase 3 replaces the rule-based routed rework (P1-B) with a state-aware `DynamicRouter` that reads multi-source state context (`RouterInput`) and produces explicit `RouterDecision` entries. A `BudgetGuard` enforces execution budgets across six stop conditions, preventing runaway rework loops.

## What Changed

### New Files

| File | Purpose |
|------|---------|
| `src/multiagent/router/__init__.py` | Package exports |
| `src/multiagent/router/schema.py` | `RouterInput` / `RouterDecision` dataclasses |
| `src/multiagent/router/budget_guard.py` | `BudgetGuard` / `BudgetState` — six stop conditions |
| `src/multiagent/router/dynamic_router.py` | `DynamicRouter.decide()` — gap-to-agent mapping |
| `tests/test_phase3_dynamic_router.py` | 22 unit tests for DynamicRouter behaviors |
| `tests/test_phase3_budget_guard.py` | 18 unit tests for BudgetGuard conditions |
| `tests/test_phase3_orchestrator_modes.py` | 7 unit tests for three-mode isolation |

### Modified Files

| File | Change |
|------|--------|
| `src/agents/multi_agent_orchestrator.py` | Added `_run_dynamic_multiagent_rework_loop()`, `rework_mode` parameter, Phase 3 metrics in `run_summary`, `router_decisions`/`budget_trace` artifacts |
| `src/eval/metrics.py` | Added Phase 3 process metrics: `router_decision_count`, `dynamic_dispatch_count`, `fallback_decision_count`, `budget_exceeded_count`, `router_stop_reason_distribution`, `repeated_dispatch_count`, `unsupported_gap_fallback_count` |
| `scripts/run_eval_baseline.py` | Added `BASELINE_4` / `dynamic_multiagent` execution mode |

### Three Execution Modes

| Mode | Behavior |
|------|----------|
| `legacy_workflow` | Original flow, no routed rework dispatches (pre-P1-B) |
| `routed_rework` | Rule-based routed gap rework (P1-B), no DynamicRouter |
| `dynamic_multiagent` | DynamicRouter + BudgetGuard, explicit decisions & budget enforcement |

### Core Architecture

```
DynamicRouter.decide(RouterInput) → List[RouterDecision]
  ├─ open_gaps → gap_type lookup → _EXECUTABLE_GAP_OWNERS
  ├─ unsupported types (VALUATION_GAP, COMPLIANCE_GAP, etc.) → fallback
  ├─ budget guard check → skip if max_dispatches_per_gap exceeded
  ├─ round dedup check → skip if owner already dispatched for this gap
  └─ no executable actions → stop

BudgetGuard
  ├─ max_total_rounds (default: 3)
  ├─ max_routed_rework_rounds (default: 2)
  ├─ max_dispatches_per_gap (default: 2)
  ├─ max_total_agent_dispatches (default: 12)
  ├─ max_total_runtime_sec (default: 300.0)
  └─ no_actionable_gaps
```

### Gap-to-Agent Mapping (identical to P1-B)

- `EVIDENCE_GAP` → research (deep_researcher)
- `NUMERIC_GAP` → analyze (deep_analyze)
- `CITATION_GAP` → research (deep_researcher)
- `RISK_GAP` → risk
- `PEER_GAP` → peer
- `FORMAT_GAP` → final_answer

Unsupported: VALUATION_GAP, COMPLIANCE_GAP, SYMBOL_PERIOD_MISMATCH, SOURCE_CONFLICT → deferred to unified final rewrite.

### Artifacts

- `router_decisions.jsonl` — per-decision trace with `selected_action`, `selected_agent`, `reason`, `fallback_used`, `unsupported_gap_type`
- `budget_trace.jsonl` — per-round budget snapshot with `current_round`, `can_continue`, `stop_reason`, `per_gap_dispatch_count`

### Key Design Decisions

1. **No executor rewrite**: DynamicRouter reuses the existing `_execute_one_routed_gap_rework()` path — it only changes *which* gaps get dispatched and *when* to stop.
2. **Explicit decision tracking**: Every router decision has a `decision_id` and full trace, enabling detailed post-hoc analysis.
3. **Fallback transparency**: Unsupported gap types are explicitly marked in `RouteDecision.unsupported_gap_type`, not silently skipped.
4. **Round dedup via `executed_agents_in_current_round`**: Prevents the same agent from running twice for the same gap in a single round.
5. **Budget overrides are available**: `BudgetState.from_profile("fast")` provides tighter limits for smoke tests.

### Constraints Met (per order.md)

- [x] Not rewriting GapRouter / TaskBoard / AgentMessage
- [x] Not deleting routed_rework mode
- [x] DynamicRouter uses multi-source state input (not pure if-else wrapper)
- [x] SOURCE_CONFLICT not prematurely promoted to real adjudication
- [x] Memory / SkillRegistry not introduced
- [x] Effects measured only through eval output
- [x] All existing + new tests pass

### Test Coverage

| Test File | Tests |
|-----------|-------|
| `test_phase3_dynamic_router.py` | Gap→agent mapping, fallback, dedup, budget integration, RouterInput parsing, RouterDecision serialization |
| `test_phase3_budget_guard.py` | All six stop conditions, profile selection, snapshot, repeated dispatch detection |
| `test_phase3_orchestrator_modes.py` | Three-mode isolation, artifact output, decision structure, budget trace structure |
