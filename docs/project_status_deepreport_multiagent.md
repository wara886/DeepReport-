# DeepReport++ Project Status and Execution Plan

Updated: 2026-05-15

This is the single source of truth for the current DeepReport++ task status, codebase map, cleanup state, validation record, and next execution plan. Future work must update this document after each completed plan.

## Latest Update

- Remote `origin/main` is aligned at `ff44ec4 Stabilize report gates and memory ablation`.
- The active project root is the repository root. The old nested `DeepReport_plus/` tree is a migration remnant and is no longer a source of truth.
- The previous root-vs-`DeepReport_plus` autostash conflict has been resolved by keeping root `HEAD/main` files and removing the migrated nested project files.
- `docs/current_status.md` has been folded into this document and removed.
- Historical review, experiment, and Stage 12 recap documents are removed from the active docs set. Current reference/contract docs remain in `docs/`.
- Cleanup validation passed on the targeted report-format tests and the wider config/schema/generation smoke tests.

## Completed

### Core pipeline

- Stage -1 through Stage 10 scaffolding exists at the repository root.
- The claim-first path is available through `src/app/main.py`, `src/app/pipeline.py`, and `src/agents/orchestrator.py`.
- Markdown, HTML, JSON, chart, citation, verification, and report export components are present.
- Generation backends are abstracted under `src/generation` with mock, local-small, and remote-oriented implementations.

### Multi-agent workflow

- The current multi-agent path is orchestrated by `src/agents/multi_agent_orchestrator.py`.
- The visible agent chain is:
  `PlanningAgent -> DeepResearcherAgent -> BrowserAgent -> DeepAnalyzeAgent -> FinalAnswerAgent -> VerifierAgent`.
- Tooling and data connectors are represented through `src/tools`, `src/search`, `src/data`, `src/retrieval`, and `src/models`.
- `FinalAnswerAgent` now performs deterministic report heading normalization and inserts missing company-report sections when supported claims exist.

### Evaluation and quality gates

- Local qwen3 canary output:
  `eval_outputs/codex_phase5b_qwen3_after_format_fix/eval_summary.json`.
- Latest qwen3 canary passed with:
  `task_completion_rate=1.0`, `required_sections_coverage=1.0`, `verification_pass_rate=1.0`, `citation_support_rate=1.0`, `numeric_audit_pass_rate=0.9373`, `valuation_sanity_pass_rate=1.0`.
- Full memory ablation output:
  `eval_outputs/codex_phase5c_memory_ablation_after_format_fix/memory_ablation_comparison.json`.
- Full memory ablation decision:
  `memory_has_measurable_benefit`.
- Memory-enabled run:
  `verification_pass_rate=1.0`, `task_completion_rate=1.0`, `numeric_audit_pass_rate=0.9217`, `citation_support_rate=1.0`.
- Memory-disabled run:
  `verification_pass_rate=0.5`, `task_completion_rate=0.5`, `numeric_audit_pass_rate=0.8889`, `citation_support_rate=1.0`.

## Repository Code Map

- `configs/`: runtime configuration, model backend settings, data source settings, evaluation settings.
- `scripts/`: local smoke scripts, evaluation runners, UI/server launchers, cloud upload/download helpers.
- `src/app/`: CLI and pipeline entrypoints.
- `src/agents/`: rule-based and model-backed agents, multi-agent orchestration, final answer generation, verification, memory/context helpers.
- `src/data/`: fetchers, normalization, manifests, company identity and source quality helpers.
- `src/features/`: financial ratios, statements, trend analysis, peer comparison, risk signals, valuation, metric lineage.
- `src/retrieval/`: evidence store, BM25, optional Chroma/local RAG, retrieval facade, FAISS placeholder.
- `src/generation/`: backend abstraction and writer/rewriter model access.
- `src/evaluation/`: eval harnesses, numeric/citation/multimodal audits, scorecards, diagnostic reports.
- `src/report/`: citation artifacts, chart generation, chart consistency, compliance disclosure, HTML polish.
- `src/templates/`: report outlines, Markdown/HTML templates, exporter.
- `src/schemas/`: Evidence, Claim, Chart, Report, Task, multimodal, and table contracts.
- `tests/`: unit, integration, smoke, and regression tests for the active root project.
- `eval_outputs/`: committed canary and ablation artifacts used as current quality evidence.

## Active Documentation

Keep these as active reference or contract documents:

- `docs/project_status_deepreport_multiagent.md`: current status and next plan.
- `docs/deepreport_repo_audit.md`: upstream DeepReport audit.
- `docs/deepreport_skeleton_mapping.md`: DeepReport-to-DeepReport++ skeleton mapping.
- `docs/deepreport_reference_architecture.md`: reference architecture summary.
- `docs/real_data_contract.md`: real-data contract.
- `docs/cloud_training.md` and `docs/cloud_readiness.md`: cloud training/readiness references.
- `docs/company_agent_architecture.md`, `docs/company_stock_report_depth_plan.md`, `docs/financial_multi_agent_detailed_guide.md`: still-useful product and architecture notes.

Removed from the active docs set:

- `docs/current_status.md`, because its current facts are now folded into this document.
- Review backfill, grounding-rule experiment, Stage 12 judgement, writer-backend recap, acceptance-report, and regression-guide documents, because they are historical notes and should not compete with this document.
- Root `CODEX_RUNBOOK.md` and `Open_DeepReportpp_Stage12_Local_Plan.md`, because their useful current facts are represented here or in the active source-of-truth docs.

## Current Risks

- Memory has measurable quality benefit, but it adds latency. Planner/Router promotion must keep latency visible and guarded.
- SkillRegistry is tested as a static MVP, but it is not yet dynamically injected into Planner/Router prompts.
- NumericAudit is above the current canary target but still has edge cases around derived/model/peer metrics.
- Competition packaging and Tianchi-style delivery are not yet revalidated after the latest memory and formatting fixes.
- `AGENTS.md` and parts of `README.md` currently display mojibake in this Windows environment; they should be repaired in a future documentation pass if they remain active onboarding documents.

## Next Plan

1. Promote durable memory into Planner/Router context selection behind explicit quality and latency guards.
2. Inject selected SkillRegistry summaries into Planner/Router while tracking unsupported fallback counts.
3. Rerun the same local qwen3 canary and memory ablation after the Planner/Router integration.
4. Rerun competition packaging with `configs/model_backends_local.yaml` or the current local equivalent.
5. Inspect generated company, industry, macro reports and package artifacts before marking delivery complete.

## Validation

Latest validation after this cleanup:

```powershell
git ls-files -u
python -m pytest tests/test_priority1_metric_fixes.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections -q
python -m pytest tests/test_config_loader.py tests/test_schemas.py tests/test_generation_backends.py -q
```

Result:

- `git ls-files -u`: no output, so no unmerged paths remain.
- Targeted tests: `8 passed`.
- Wider smoke tests: `12 passed`.
- Pytest emitted cache write warnings for `G:\cord\.pytest_cache`, caused by local Windows permissions; tests passed.

Required validation after any future plan:

```powershell
git ls-files -u
git status --short
python -m pytest tests/test_priority1_metric_fixes.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections -q
python -m pytest tests/test_config_loader.py tests/test_schemas.py tests/test_generation_backends.py -q
```

Record the exact command results in this section after every completed plan.

## Dynamic Update Rule

After each completed plan, update this file before committing:

- `Latest Update`: what changed in this turn and which commit/run/artifact proves it.
- `Completed`: newly closed capabilities or cleanup tasks.
- `Current Risks`: new blockers, regressions, or remaining uncertainty.
- `Next Plan`: the next ordered execution steps.
- `Validation`: exact commands run and pass/fail results.

Do not reintroduce competing status documents. If a new design or audit document is needed, link it from this file and keep this file as the entry point.
