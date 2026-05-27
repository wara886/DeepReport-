# DeepReport Reference Repository Audit

## Scope

- Reference repository: `https://github.com/wisdom-pan/DeepReport.git`
- Local read-only copy: `references/DeepReport_ref/`
- Reviewed surface: `README.md`, `main.py`, `config.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `src/`, and `docs/`
- Review date: `2026-05-27`

## Observed Layout

The reference project keeps a compact public root:

```text
DeepReport/
|-- docs/
|-- examples/
|-- src/
|-- main.py
|-- config.py
|-- Dockerfile
|-- docker-compose.yml
|-- start.sh
|-- stop.sh
`-- README.md
```

Its README presents documentation, Docker quick start, project structure, feature claims, and a demo link before implementation detail.

## Runtime Shape

- `main.py` creates the Gradio application and initializes planning, research, browser, analysis, and final-answer agents.
- `config.py` reads API, model, report, browser, and MCP settings from environment variables.
- `src/agents/` contains the planning and sub-agent roles.
- `src/search/` contains multi-engine search integration.
- `src/report/` contains HTML, chart, and citation generation.
- `docker-compose.yml` exposes `7860`, mounts report/log directories, and configures container health checking.

## Reusable Structure

- Short root-level deployment entrypoint and Docker-first README organization.
- Clear module boundaries for agents, search, report export, and utilities.
- Container port `7860` as a convenient public demonstration surface.

## Required Rewrites

- FinSight is evidence-first: it preserves claim, citation, verification, quality-gate, and official-source artifacts rather than treating citations as presentation metadata.
- FinSight requires fiscal-period matching, A/H official disclosure handling, PDF page anchors, and frozen benchmark evaluation.
- FinSight keeps configuration in YAML plus environment secrets and uses FastAPI as the deployable surface while retaining its existing workbench behavior.

## Not Adopted

- SmolAgents-specific runtime coupling is not introduced.
- General topic generation is not presented as equivalent to verified company-report delivery.
- Online-search output is not treated as a reproducible formal benchmark input.
