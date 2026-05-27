# DeepReport Skeleton Mapping

| DeepReport module | FinSight / DeepReport++ module | Strategy |
| --- | --- | --- |
| Root `main.py` Gradio entry | `main.py`, `src/app/api_fastapi.py`, `src/app/web_ui.py` | Rewrite: FastAPI deployment with compatible workbench routes |
| `config.py` environment settings | `configs/*.yaml`, `.env.example`, `src/utils/config.py` | Rewrite: versioned policy config plus local secrets |
| `src/agents/` sub-agents | `src/agents/` and `MultiAgentOrchestrator` | Rewrite: claim-first workflow and verifier gates |
| `src/search/` engines | `src/search/`, `src/data/independent_sources.py` | Rewrite: market-aware official-source routing |
| `src/report/` export helpers | `src/report/`, `src/templates/`, `src/charts/` | Extend: Markdown/HTML/JSON plus page-located citations |
| Citation presentation | `citations.json`, `official_evidence_manifest.json`, `evidence_coverage.json` | Rewrite: source-to-claim audit artifacts |
| No frozen benchmark surface | `bench/formal18_fy24`, `data/benchmarks/` | Add: reproducible published evaluation |
| `Dockerfile`, `docker-compose.yml` | `Dockerfile`, `docker-compose.yml`, `start.*`, `stop.*` | Retain pattern: containerized `7860` service |
| `requirements.txt`, `setup.py` | `pyproject.toml` | Rewrite: modern package/dependency management |
| `docs/` bilingual/project docs | `docs/` architecture, limitations, audit, protocol docs | Retain and specialize |

## Public Layout Decision

The public repository remains slightly larger than the reference because evidence archives, benchmark policy, and regression tests are core product assets. To keep the landing page readable, published result artifacts use the short path `bench/formal18_fy24`; runtime experiment outputs remain ignored under `eval_outputs/`.
