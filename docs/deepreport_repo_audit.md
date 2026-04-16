# DeepReport Reference Repository Audit

Stage: `Stage -1`
Reference repository: `references/DeepReport_ref/`
Reference commit: `afc6ee7`
Audit date: 2026-04-16

## Completion Check

- `references/DeepReport_ref/` exists locally.
- Clone was skipped because the reference repository was already present.
- Before this audit, Stage -1 was not complete because `docs/deepreport_repo_audit.md` and `docs/deepreport_skeleton_mapping.md` did not exist.
- This document records the required repository audit for Stage -1.

## Real Directory Structure

The audited repository is a compact Gradio application with a small `src/` package and Docker deployment files:

```text
references/DeepReport_ref/
├── README.md
├── LICENSE
├── config.py
├── docker-compose.yml
├── Dockerfile
├── main.py
├── nginx.conf
├── requirements.txt
├── requirements-dev.txt
├── setup.py
├── start.sh
├── stop.sh
├── examples/
│   ├── mcp_integration.py
│   └── simple_report.py
├── docs/
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── en/
│   │   ├── README.md
│   │   ├── CONTRIBUTING.md
│   │   └── CODE_OF_CONDUCT.md
│   └── zh/
│       ├── README.md
│       ├── CONTRIBUTING.md
│       └── CODE_OF_CONDUCT.md
└── src/
    ├── __init__.py
    ├── agents/
    │   ├── __init__.py
    │   ├── base_agent.py
    │   ├── browser_agent.py
    │   ├── deep_analyze_agent.py
    │   ├── deep_researcher_agent.py
    │   ├── final_answer_agent.py
    │   ├── planning_agent.py
    │   └── sub_agents.py
    ├── report/
    │   ├── __init__.py
    │   ├── chart_generator.py
    │   ├── citation_manager.py
    │   └── html_generator.py
    ├── search/
    │   ├── __init__.py
    │   ├── engines.py
    │   └── search_manager.py
    └── utils/
        ├── __init__.py
        ├── mcp_manager.py
        └── model_adapter.py
```

## Main Entry Point

The main runtime entry is `main.py`.

Key behavior:

- Defines `DeepReportApp`.
- Initializes `SearchManager`, `MCPManager`, and `HTMLReportGenerator`.
- Initializes five agent roles:
  - `PlanningAgent`
  - `DeepResearcherAgent`
  - `BrowserAgent`
  - `DeepAnalyzeAgent`
  - `FinalAnswerAgent`
- Exposes a Gradio UI through `create_gradio_interface()`.
- Runs the app with `demo.launch(server_name="0.0.0.0", server_port=7860, ...)`.
- Saves generated HTML reports into `config.output_dir`, defaulting to `./reports`.

The orchestration is application-centric: `DeepReportApp.generate_report()` creates a plan, executes tasks, assembles `report_data`, and delegates HTML rendering.

## Configuration Entry

The configuration entry is `config.py`.

Observed configuration style:

- Uses a global `Config()` instance named `config`.
- Reads environment variables through `BaseSettings`.
- Centralizes API keys, model parameters, search keys, report switches, MCP settings, and browser settings.
- Provides `get_model_config()` to select model API key and basic generation parameters.

Important caveat:

- `requirements.txt` pins `pydantic==2.8.2`, while `config.py` imports `BaseSettings` from `pydantic`. In Pydantic v2, `BaseSettings` moved to `pydantic-settings`. This is a compatibility risk and should not be copied as-is.
- The project uses `.env`-driven configuration, not YAML. Open DeepReport++ requires YAML-based configuration, so this layer should be redesigned rather than reused directly.

## Agent Modules

Agent code lives in `src/agents/`.

Observed modules:

- `base_agent.py`
  - Defines `AgentStatus`, `Task`, `TaskResult`, and `BaseAgent`.
  - `BaseAgent` inherits from `smolagents.Agent`.
  - Provides queueing, task status, retries-related fields, and a generic `run_task_with_smolagents()` path.
- `planning_agent.py`
  - Defines `PlanningTool` and `PlanningAgent`.
  - Turns a research topic and requirements into structured task plans.
  - Parses expected model output as JSON.
- `deep_researcher_agent.py`
  - Defines source discovery, content extraction, and quality assessment tools.
  - Uses DuckDuckGo, LangChain loaders, URL domain scoring, and web content chunking.
- `browser_agent.py`
  - Wraps `browser-use` and PyMuPDF for web navigation, form interaction, structured extraction, and PDF analysis.
- `deep_analyze_agent.py`
  - Provides financial metrics, sentiment, valuation, and risk assessment tools.
  - Much of the analysis logic is heuristic or placeholder-grade.
- `final_answer_agent.py`
  - Provides HTML, Markdown, quality assessment, and visualization tools.
  - Generates final report artifacts and quality scores.
- `sub_agents.py`
  - Re-exports specialized agent classes.

What is useful for Open DeepReport++:

- The role split is useful as an inspiration: planner, researcher, browser/retriever, analyst, final writer.
- The `Task` / `TaskResult` pattern is a useful lightweight orchestration skeleton.
- The current implementation is too LLM-first for our claim-first target. Open DeepReport++ should introduce explicit schemas, evidence IDs, claim tables, and verifiers before free-form generation.

## Tool, Search, And Retrieval Modules

Search code lives in `src/search/`.

Observed modules:

- `search_manager.py`
  - Initializes enabled engines from API keys.
  - Runs searches across engines concurrently with `asyncio.gather`.
  - Aggregates, deduplicates by URL, and ranks results using a simple heuristic.
- `engines.py`
  - Defines abstract `SearchEngine`.
  - Implements `SerperEngine`, `MetasoEngine`, and `SogouEngine`.
  - Normalizes outputs into dictionaries with `title`, `url`, `snippet`, `source`, and ranking metadata.

What is useful for Open DeepReport++:

- Keep the abstraction boundary: manager + engine adapters + normalized result objects.
- Rework the actual data source strategy. Stage 2 requires local `mock` / `local_file` first and no online fetching in the first data layer.
- Add a separate retrieval layer later: BM25 first, FAISS only as an interface placeholder when the stage asks for it.

## Report Modules

Report code lives in `src/report/`.

Observed modules:

- `html_generator.py`
  - Uses Jinja2 templates embedded in Python strings.
  - Produces an HTML report with sections, metrics, charts, citations, risk assessment, recommendations, and data sources.
  - Calls `ChartGenerator` and `CitationManager`.
- `chart_generator.py`
  - Emits Chart.js configurations for line, bar, pie, doughnut, radar, scatter, area, heatmap-like bubble, and financial charts.
- `citation_manager.py`
  - Formats citations in APA, MLA, Chicago, and Harvard styles.
  - Extracts URLs and DOIs from text.
  - Deduplicates and sorts citations.

What is useful for Open DeepReport++:

- Preserve the separation between report assembly, chart rendering, and citation management.
- Replace embedded HTML strings with `src/templates/` modules or template files.
- Add markdown export as a first-class output, because Open DeepReport++ explicitly targets markdown/html.
- Tie every section to claim and evidence schema rather than passing loosely shaped dictionaries.

## Docker And Runtime Layer

Observed Docker files:

- `Dockerfile`
  - Uses `python:3.11-slim`.
  - Installs Chrome and browser dependencies.
  - Installs `requirements.txt`.
  - Runs `python main.py`.
  - Exposes port `7860`.
- `docker-compose.yml`
  - Builds local image.
  - Exposes `7860:7860`.
  - Passes OpenAI, Anthropic, search, report, MCP, browser, and Gradio environment variables.
  - Mounts `./reports` and `./logs`.
  - Includes optional commented Redis and Nginx services.
- `start.sh` / `stop.sh`
  - Provide convenience wrappers for Docker Compose.

What is useful for Open DeepReport++:

- Keep containerization and a single local app entry eventually.
- Delay browser-heavy and Chrome-heavy dependencies until the relevant retrieval/browser stage.
- Do not pull in the full Docker/browser stack in Stage 0.

## Dependency Management

Dependency files:

- `requirements.txt`
- `requirements-dev.txt`
- `setup.py`

Important dependencies in `requirements.txt`:

- UI/runtime: `gradio`
- LLM and agent stack: `openai`, `anthropic`, `smolagents`, `langchain`
- Search/web: `requests`, `beautifulsoup4`, `selenium`, `browser-use`, `aiohttp`
- Data/charting: `pandas`, `numpy`, `matplotlib`, `plotly`, `jinja2`, `markdown`
- PDF/browser: `PyMuPDF`, `webdriver-manager`, `chromedriver-autoinstaller`
- Finance: `yfinance`, `financial-datasets`
- MCP: `fastmcp`

Audit notes:

- Dependencies are heavy for a local-first staged build.
- Some packages are duplicated in `requirements.txt`.
- Version compatibility risks exist around Pydantic settings and possibly `smolagents` API usage.
- Open DeepReport++ should start with minimal dependencies and add heavier packages only when a stage requires them.

## Directly Borrowable Engineering Skeleton

The following engineering ideas are worth borrowing:

1. Top-level `main.py` as a thin runnable entry, later moved or mirrored into `src/app/main.py`.
2. A clear `src/agents/`, `src/search/`, `src/report/`, `src/utils/` separation.
3. Agent role decomposition into planner, researcher/retriever, analyst, writer/finalizer.
4. Lightweight task/result contracts for agent orchestration.
5. Search engine adapter pattern: abstract base engine, concrete engines, manager-level aggregation.
6. Report layer split into HTML generation, chart generation, and citation management.
7. Docker Compose as a later deployment wrapper.
8. Example scripts as a place for smoke and integration examples.

## Parts That Do Not Match Open DeepReport++ Goals

The following parts should be rewritten, deleted, or delayed:

1. LLM-first planning and writing before schemas. Our project requires schema-first and claim-first flow.
2. Online search as an early data dependency. Our Stage 2 requires local mock/local-file data first.
3. Direct dependency on browser automation and Chrome in early stages. This is too heavy for local engineering closure.
4. Environment-only configuration. Our project requires model names, paths, batch sizes, top-k, and switches in YAML.
5. Loose dictionary-shaped report data. Our project needs typed schemas for evidence, claims, charts, sections, and reports.
6. No explicit verifier boundary. Our pipeline needs rule verifier first, then model verifier later.
7. Embedded templates inside Python strings. Our project should use explicit template modules/files.
8. Generic financial examples and broad web research. Open DeepReport++ is scoped to company/stock research reports with verifiable evidence.
9. Heavy training/runtime dependencies in one requirements file. Our local machine should not inherit cloud training or heavy model dependencies.

## Stage -1 Audit Conclusion

DeepReport provides a useful high-level skeleton for a financial report system: multi-agent roles, search abstraction, report rendering, chart/citation helpers, and Docker deployment. It should be treated as an architectural reference, not as code to copy directly.

For Open DeepReport++, the most important adaptation is to invert the control flow:

- DeepReport: topic -> LLM plan -> web/search/analysis -> loose report data -> HTML.
- Open DeepReport++: typed task -> local/mock data -> evidence manifest -> claim table -> verifier -> markdown/html report.

The next allowed step is Stage 0 only after this Stage -1 audit is accepted.
