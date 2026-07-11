# Legacy Cleanup

## 2026-07-11

The current FastAPI workbench is now the only published web application.

Removed:

- the legacy chat UI launchers;
- the duplicate FastAPI launcher under `scripts/`;
- the Stage 4 CLI wrapper under `src/app/main.py`;
- the obsolete forward-metrics utility;
- the legacy chat service, parser, query-understanding layer, HTML UI, and their tests;
- the FastAPI proxy routes for `/api/chat`, `/api/run`, `/api/latest`, and `/api/job_status`.

Changed:

- `/` and `/workbench` now render the same current workbench;
- FastAPI no longer starts a second internal HTTP server;
- report tasks use `/api/report-tasks` as the canonical lifecycle API;
- report quality and bounded rework now live in `src/evaluation/delivery_pipeline.py`;
- market-specific engines now come from `src/data/company_universe.py`;
- missing artifact paths return a local `404` instead of proxying to the old server;
- runtime output directories are ignored by Git and Docker.

Retained:

- the orchestrator, RAG, quality gates, benchmark fixtures, and evaluation
  scripts remain because they are part of the current report-generation and
  regression workflow.

Recovery:

All removed files remain available in Git history before this cleanup commit.
