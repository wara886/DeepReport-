# DeepReport Skeleton Mapping

Stage: `Stage -1`
Reference repository: `references/DeepReport_ref/`
Reference commit: `afc6ee7`
Audit date: 2026-04-16

This mapping records how the DeepReport reference skeleton should influence Open DeepReport++ without copying its business logic.

## Mapping Table

| DeepReport original module | Open DeepReport++ corresponding module | Strategy |
| --- | --- | --- |
| Repository root with `main.py`, `config.py`, Docker files, `src/`, `docs/`, `examples/` | Repository root with `README.md`, `pyproject.toml`, `.env.example`, `configs/`, `scripts/`, `src/`, `tests/`, `data/`, `docs/`, `references/` | Rewrite |
| `main.py` as Gradio application and orchestration entry | `src/app/main.py`, `src/app/pipeline.py`, plus `scripts/run_local_smoke.py` | Rewrite |
| `DeepReportApp.generate_report()` end-to-end orchestration | Claim-first pipeline: fetch/normalize -> feature extraction -> claim generation -> verification -> export | Rewrite |
| `config.py` using `.env` and Pydantic settings | `src/utils/config.py` reading YAML configs from `configs/*.yaml` | Rewrite |
| `.env` API-key centric configuration | `.env.example` for secrets only; YAML for model, path, top-k, batch size, backend, switches | Rewrite |
| `src/agents/base_agent.py` with `Task`, `TaskResult`, and status enum | `src/agents/` plus `src/schemas/task.py`; typed task/result boundaries | Preserve with rewrite |
| `src/agents/planning_agent.py` | `src/agents/planner.py` | Rewrite |
| `src/agents/deep_researcher_agent.py` | `src/data/*` in early stages, later `src/retrieval/*` and `src/agents/analyst.py` | Rewrite |
| `src/agents/browser_agent.py` | Later browser/PDF ingestion adapter if needed; no Stage 0/2 dependency | Defer |
| `src/agents/deep_analyze_agent.py` | `src/features/financial_ratios.py`, `src/features/trend_analysis.py`, `src/features/peer_compare.py`, `src/features/risk_signals.py`, and `src/agents/analyst.py` | Rewrite |
| `src/agents/final_answer_agent.py` | `src/agents/writer.py`, `src/templates/*`, `src/generation/*`, `src/evaluation/*` | Rewrite |
| `src/agents/sub_agents.py` re-export layer | `src/agents/__init__.py` package exports | Preserve |
| `src/search/search_manager.py` | `src/retrieval/retrieve.py` and later retrieval manager abstraction | Preserve with rewrite |
| `src/search/engines.py` with Serper/Metaso/Sogou online engines | `src/data/fetch_base.py`, `src/data/fetch_news.py`, `src/data/fetch_filings.py`, and later optional online adapters | Rewrite / Defer |
| URL deduplication and relevance ranking in `SearchManager` | `src/data/dedup.py`, `src/retrieval/bm25_index.py`, later reranker training data | Preserve with rewrite |
| `src/report/html_generator.py` | `src/templates/html_template.py`, `src/templates/markdown_template.py`, `src/app/pipeline.py` export step | Rewrite |
| `src/report/chart_generator.py` | `src/charts/line_chart.py`, `src/charts/bar_chart.py`, `src/charts/table_chart.py`, `src/charts/render.py` | Preserve with rewrite |
| `src/report/citation_manager.py` | Citation fields inside `EvidenceItem`, `ClaimItem`, `ReportSection`, and report export layer | Preserve with rewrite |
| `src/utils/model_adapter.py` | `src/generation/backend_base.py`, `backend_mock.py`, `backend_local_small.py`, `backend_remote.py`, later finetuned backend | Rewrite |
| `src/utils/mcp_manager.py` | Optional external tool integration layer after local pipeline is stable | Defer |
| `requirements.txt` single heavy dependency list | `pyproject.toml` with minimal local dependencies first; optional groups later | Rewrite |
| `Dockerfile` installing Chrome/browser stack | Later deployment Dockerfile after local smoke pipeline exists | Defer |
| `docker-compose.yml` for Gradio app on port 7860 | Later app service and optional workers; no Stage 0 requirement | Defer |
| `start.sh` / `stop.sh` | Later scripts under `scripts/` if Docker is introduced | Defer |
| `examples/simple_report.py`, `examples/mcp_integration.py` | `scripts/run_local_smoke.py` and `tests/fixtures` | Rewrite |
| `docs/en`, `docs/zh`, `docs/README.md`, `CHANGELOG.md` | `docs/` with audit docs, architecture notes, cloud training docs later | Preserve with rewrite |

## Required Coverage Summary

### Directory Structure

DeepReport uses a compact structure centered on `src/agents`, `src/search`, `src/report`, and `src/utils`.

Open DeepReport++ should expand this into staged engineering layers:

- `src/app`
- `src/schemas`
- `src/data`
- `src/features`
- `src/retrieval`
- `src/agents`
- `src/templates`
- `src/charts`
- `src/generation`
- `src/training`
- `src/evaluation`
- `src/utils`

Strategy: rewrite the skeleton while preserving the idea that each layer owns one responsibility.

### Runtime Entry

DeepReport runtime:

- `python main.py`
- Gradio UI
- `DeepReportApp` owns initialization and orchestration.

Open DeepReport++ runtime:

- `scripts/run_local_smoke.py` for Stage 0 smoke.
- Later `src/app/main.py` and `src/app/pipeline.py` for structured report generation.

Strategy: rewrite. Keep the single runnable entry idea, but make it pipeline-first rather than UI-first.

### Configuration Layer

DeepReport configuration:

- `config.py`
- `.env`
- API-key and runtime settings read into a global object.

Open DeepReport++ configuration:

- `configs/app.yaml`
- `configs/local_debug.yaml`
- `configs/local_smoke.yaml`
- `configs/cloud_train.yaml`
- `configs/data_sources.yaml`
- `configs/report_company.yaml`
- `configs/model_backends.yaml`
- `configs/reranker.yaml`
- `configs/rewriter.yaml`
- `configs/verifier.yaml`
- `src/utils/config.py`

Strategy: rewrite. Secrets may stay in `.env`, but model/backend/path/batch/top-k/switches must live in YAML.

### Agent Orchestration Layer

DeepReport orchestration:

- `PlanningAgent` creates a JSON plan.
- Specialized agents perform research, browser tasks, analysis, and final answer generation.
- The main app loops over plan tasks.

Open DeepReport++ orchestration:

- `planner.py` creates fixed company-report section plans in the first version.
- `analyst.py` creates claim tables from normalized local data and programmatic features.
- `writer.py` uses templates by default and generation backends only after the backend abstraction stage.
- `verifier.py` performs rule checks first.
- `orchestrator.py` wires the claim-first flow.

Strategy: preserve the role boundaries, rewrite the behavior.

### Search / Retrieval Layer

DeepReport search:

- Online search adapters: Serper, Metaso, Sogou.
- Manager-level concurrent search, deduplication, and heuristic ranking.

Open DeepReport++ retrieval:

- Stage 2 starts with `mock`, `local_file`, and `future_api` fetch modes.
- Stage 7 adds BM25 retrieval.
- FAISS is an interface placeholder at first.
- Reranker data export appears later.

Strategy: preserve the adapter shape and dedup/ranking ideas, defer online engines.

### Report Export Layer

DeepReport export:

- HTML-focused report generator.
- Embedded Jinja2 template.
- Chart.js configs.
- Citation formatting.

Open DeepReport++ export:

- Markdown and HTML both first-class.
- Templates live in `src/templates`.
- Charts live in `src/charts`.
- Citations are generated from typed evidence and claims.
- Exported report should include verifiable claim/evidence links.

Strategy: preserve chart/citation/report separation, rewrite templates and data contracts.

### Docker Layer

DeepReport Docker:

- Full browser-capable image.
- Chrome system dependencies.
- Gradio service on port 7860.
- Optional Redis/Nginx blocks.

Open DeepReport++ Docker:

- Not needed for Stage 0.
- Should be introduced after local smoke pipeline and dependency boundaries are stable.
- Browser-heavy image should wait until browser/PDF ingestion is explicitly required.

Strategy: defer.

### Dependency Management

DeepReport dependency management:

- `requirements.txt` with all runtime dependencies in one file.
- Includes UI, browser, search, LLM, MCP, finance, charting, and data dependencies together.

Open DeepReport++ dependency management:

- `pyproject.toml`.
- Minimal local dependencies first.
- Optional dependency groups can be added later for retrieval, charts, training, cloud, and browser support.

Strategy: rewrite.

## Recommended Stage 0 Implications

Stage 0 should reflect the mapping above without implementing later functionality:

1. Create the expanded directory skeleton from `AGENTS.md`.
2. Add YAML config files with placeholders and safe defaults.
3. Add a small config loader that reads `local_debug.yaml`.
4. Keep all `src` packages importable.
5. Add a smoke script and a minimal test.
6. Do not add online search, browser automation, heavy model dependencies, training code, or Docker behavior yet.

## Decision Summary

The reference repository is useful for boundaries, not for direct code reuse.

- Preserve: role separation, manager/adapter boundaries, chart/citation/report layering, Docker as later deployment concept.
- Rewrite: configuration, data contracts, orchestration, report templates, dependency management.
- Delete from early skeleton: UI-first flow, online-first data fetching, loose report dictionaries.
- Defer: browser automation, MCP integration, Docker production layer, cloud training, reranker/verifier/rewriter model code.
