# Production Path Boundary

This document defines the runtime path used by the workbench and prevents
historical benchmark rows from being mistaken for a current production run.

## Production Path

```text
main.py
  -> src.app.api_fastapi
  -> ReportTaskService
  -> LangGraphReportRuntime
  -> MultiAgentOrchestrator
  -> SQLite task state + versioned report artifacts
```

The production path uses `data/finsight_workbench.db` for business state,
`data/outputs_user/runtime_checkpoints.sqlite` for LangGraph checkpoints,
`data/outputs_user` and `data/reports_user` for task artifacts, and
`data/vector_db` for the local retrieval index.

Production retrieval is BM25 plus BGE dense retrieval, followed by the
configured reranker. The entity-relation graph is visible in the workbench but
does not participate in RAG ranking. PromptOps test execution is available only
for modules with a bound runtime executor; unbound templates remain version
management records and return an explicit conflict instead of mock success.

Dashboard charts render database aggregates only. Empty datasets render empty
states and never substitute demonstration rows.

The production datasource configuration contains remote/official adapters only.
Mock file sources are confined to `configs/local_*.yaml`, test fixtures, and
benchmark scripts.

## Non-Production Paths

The following paths remain for compatibility, benchmarks, or controlled tests:

- `src/app/pipeline.py`
- `src/agents/orchestrator.py`
- `src/agents/collaborative_orchestrator.py`
- `scripts/run_*benchmark*.py`
- `configs/local_*.yaml`

They must not be used to calculate the current workbench delivery rate.

## Baseline Scope

Run `scripts/build_production_baseline_manifest.py` before a release or stage
regression. The manifest records the commit, production prefixes, historical
task distribution, and current production task distribution without modifying
the database.

Only tasks whose IDs use an explicitly configured production prefix belong to a
current production baseline. Historical rows remain available for audit but are
excluded from release metrics.
