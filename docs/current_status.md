# DeepReport++ Current Status

Updated: 2026-05-15

This is the short current-status companion to `docs/fixed.md`.

## What Is Closed

- Phase 0 eval harness and fixed cases.
- Phase 1 routed rework executor for currently executable gap owners.
- Phase 2 AgentMessage, Blackboard, and TaskBoard.
- Phase 3 DynamicRouter and BudgetGuard.
- Phase 4 SOURCE_CONFLICT adjudication canary.
- Phase 5A minimum VALUATION_GAP executable path:
  `VALUATION_GAP -> DynamicRouter -> ValuationAgent -> valuation_audit -> valuation_sanity_pass_rate`.
- Phase 5B minimum artifact-backed CitationAudit / NumericAudit metrics:
  `claims + evidence + citations + analysis_artifacts -> citation_audit.json / numeric_audit.json -> eval metrics`.
- Phase 5C minimum durable memory writer:
  `run_summary + task_board + messages + gaps -> memory/working/<run_id>/ + memory/episodic/ + memory/domain/`.

## Latest Eval Fact

Latest valuation-focused local open-model canary:

- `eval_outputs/codex_phase5b_qwen3_after_format_fix/eval_summary.json`
- Model: local Ollama `qwen3:8b`.
- Cases: JPM and 600519.SS valuation-gap cases.
- Result: `task_completion_rate=1.0`, `required_sections_coverage=1.0`, `verification_pass_rate=1.0`.
- Dynamic chain: `dynamic_dispatch_count_sum=6`, `fallback_decision_count_sum=0`, `unsupported_gap_fallback_count_sum=0`.
- Metrics: `citation_support_rate=1.0`, `numeric_audit_pass_rate=0.9373`, `valuation_sanity_pass_rate=1.0`.
- Note: the shell command hit the outer timeout after artifacts were written, but `eval_summary.json`, `per_case_metrics.jsonl`, and empty `failure_cases.jsonl` confirm completion.

Previous valuation-focused canary:

- `eval_outputs/codex_phase5b_numeric_artifact_canary/eval_summary.json`
- Cases: JPM and 600519.SS valuation-gap cases.
- Result: `verification_pass_rate=1.0`, `task_completion_rate=1.0`, `task_resolution_rate_mean=1.0`.
- Dynamic chain: `dynamic_dispatch_count_sum=10`, `fallback_decision_count_sum=0`, `unsupported_gap_fallback_count_sum=0`.
- Metrics: `citation_support_rate=1.0`, `numeric_audit_pass_rate=0.8621`, `valuation_sanity_pass_rate=1.0`.

Latest durable-memory smoke:

- `eval_outputs/codex_phase5c_memory_smoke_after_fix/eval_summary.json`
- Result: `verification_pass_rate=1.0`, `task_completion_rate=1.0`, `unsupported_gap_fallback_count_sum=0`.
- Memory artifact: `run_summary.json` includes `durable_memory.snapshot`, and the run writes `memory/working/<run_id>/snapshot.json`.

Latest full memory ablation:

- `eval_outputs/codex_phase5c_memory_ablation_after_format_fix/memory_ablation_comparison.json`
- Scope: 2-case local qwen3 enabled vs disabled ablation.
- Result: `decision=memory_has_measurable_benefit`.
- Memory enabled: `verification_pass_rate=1.0`, `task_completion_rate=1.0`, `numeric_audit_pass_rate=0.9217`, `citation_support_rate=1.0`, `unsupported_gap_fallback_count_sum=0`.
- Memory disabled: `verification_pass_rate=0.5`, `task_completion_rate=0.5`, `numeric_audit_pass_rate=0.8889`, `citation_support_rate=1.0`, `unsupported_gap_fallback_count_sum=0`.
- Deltas: verification +0.5, task completion +0.5, numeric audit +0.0328. Latency increased by about 31.5 seconds per case.
- Decision: memory has measurable quality benefit and can be promoted cautiously into the next Planner/Router iteration, while keeping latency visible.

Previous memory ablation smoke:

- `eval_outputs/codex_phase5c_memory_ablation_after_format_fix_smoke/memory_ablation_comparison.json`
- Scope: 1-case local qwen3 smoke, memory enabled vs disabled.
- Result: both variants completed artifacts but `verification_pass_rate=0.0`; do not treat as promotion proof.
- Signal: memory enabled improved `numeric_audit_pass_rate` from `0.5714` to `0.8889` and restored citation support to `1.0`, but added latency and did not clear verifier.
- Decision: keep memory as useful artifact/context path; run the full 2-case ablation before promoting memory into Planner/Router policy.

The previous verification blockers were fixed:

- Core financial numeric claims supported only by news/tertiary evidence are now rejected by the evidence gate.
- Three-statement equity now prefers nested `metadata.parent_metadata`, preventing 600519.SS shareholder equity mismatch.
- NumericAudit now recognizes model/peer artifacts in addition to raw evidence values.
- NumericAudit accepts legitimate zero count metrics such as `core_peer_count=0`.
- FinalAnswerAgent now deterministically inserts missing company-report sections when claims exist but the local model omits or renames the header.
- Claim-text charts can pass chart lineage via `input_claim_ids`; missing evidence remains the responsibility of citation/evidence audits instead of failing the multimodal gate.

## What Is Still Open

- NumericAudit is above the current 0.90 canary target on the latest qwen3 run, but remaining misses are still mostly derived/peer/model edge cases and should be tracked as refinement.
- `valuation_sanity_pass_rate` can still be `null` on cases that do not execute valuation work; this is expected.
- Durable memory can write and load artifacts; `MultiAgentOrchestrator` now has a `memory_enabled` switch, and `scripts/run_memory_ablation.py` can compare memory-enabled vs memory-disabled canaries.
- SkillRegistry MVP exists with four static domain skills: valuation method selection, numeric consistency audit, citation support audit, and gap routing. It is tested but not yet dynamically injected into Planner/Router prompts.
- Final memory ablation and resume-grade benchmark report are not complete.

## Current Best Next Step

Continue Phase 5C durable memory and SkillRegistry integration, because the first write/load path and static skill contracts are now in place:

1. Promote memory cautiously into Planner/Router context selection, guarded by metrics and latency.
2. Integrate selected SkillRegistry summaries into Planner/Router without increasing unsupported fallback.
3. Rerun competition packaging after the quality gates stay green.

Keep NumericAudit refinement as a parallel cleanup item, but do not block Memory on reaching a perfect numeric pass rate.

## New Chat Reading Order

1. `docs/current_status.md`
2. `docs/fixed.md`
3. `docs/financial_deepreport_multiagent_upgrade_spec.md`
4. `eval_outputs/codex_phase5c_memory_smoke_after_fix/eval_summary.json`
5. `eval_outputs/codex_phase5b_numeric_artifact_canary/eval_summary.json`
6. `eval_outputs/codex_phase5b_numeric_artifact_canary/per_case_metrics.jsonl`
7. `eval_outputs/codex_phase5a_valuation_gap_smoke_bank_equity/eval_summary.json`
8. `eval_outputs/codex_phase4_b5_smoke_after_docs/eval_summary.json`
9. `src/agents/multi_agent_orchestrator.py`
10. `src/agents/durable_memory.py`
11. `src/multiagent/router/dynamic_router.py`
12. `src/multiagent/gaps/router.py`
13. `src/agents/valuation_agent.py`
14. `src/evaluation/citation_audit.py`
15. `src/evaluation/numeric_support_audit.py`
16. `tests/test_durable_memory.py`
17. `tests/test_phase5b_audits.py`
18. `tests/test_valuation_agent.py`
19. `tests/test_phase4_adjudicator.py`

Old `docs/multiagent_upgrade/*` files are historical notes. When they conflict with this file or `docs/fixed.md`, use the current-status files.

## Next Prompt

```text
Please read DeepReport_plus/docs/current_status.md, docs/fixed.md, docs/financial_deepreport_multiagent_upgrade_spec.md, eval_outputs/codex_phase5b_qwen3_after_format_fix/eval_summary.json, and eval_outputs/codex_phase5c_memory_smoke_after_fix/eval_summary.json. Continue from the current state: Phase 5A/5B are passing local qwen3 canary eval, deterministic format/chart-lineage repairs are in place, and Phase 5C writes durable memory artifacts under memory/working, memory/episodic, and memory/domain. Next run memory-enabled vs memory-disabled eval comparison and then decide whether to promote SkillRegistry into Planner/Router.
```
