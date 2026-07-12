# Production Baseline v5 - 2026-07-12

## Scope

This baseline was executed through the running FastAPI application, `ReportTaskService`, SQLite, and the LangGraph runtime. It did not call `MultiAgentOrchestrator` directly.

All cases used the delivery profile, remote data, durable memory, the strict evidence gate, and `FY2024`:

| Symbol | Status | Quality score | Formal delivery | Runtime |
| --- | --- | ---: | --- | ---: |
| AAPL | quality_failed | 0.8266 | no | 468.88s |
| NVDA | quality_failed | 0.8037 | no | 384.64s |
| MSFT | quality_failed | 0.9010 | no | 468.19s |

Formal delivery rate: **0/3**.

## Confirmed Working

- The production API, SQLite persistence, LangGraph outer runtime, evidence gate, artifact import, quality gate, and human-review interrupt all completed.
- SEC filing sections, SEC Company Facts, Yahoo market data, FRED, BEA, Tavily, and company profiles entered final evidence artifacts.
- MiMo and DeepSeek model routes executed without model fallback.
- Research and analysis ReAct loops called their configured seven tools.
- All three tasks produced Markdown, HTML, JSON, evidence, claims, citations, contracts, verification, and quality artifacts.

## P0 Findings

1. `generation` remains a long-running black-box LangGraph node. It took roughly six minutes per case before LangGraph could expose another stage.
2. All three tasks bound to workspace `1` but retained `company_id = null`.
3. Local hybrid retrieval reported `no_records_for_symbol_period` during quality-gap rework even though final evidence artifacts contained 23-35 records. Task evidence and rework retrieval are not using one stable retrieval contract.
4. Canonical metrics were empty for AAPL and NVDA, while MSFT produced 11 metrics. This is a data normalization/selection failure, not a lack of SEC/Yahoo evidence.
5. Section evidence packs contained must-use evidence, but core report sections were still reported as not consuming it.
6. Claims and Markdown citations diverged: verifier blockers reported evidence IDs present on claims but absent from the report body.
7. Chart and three-statement artifacts were empty for multiple cases despite structured financial sources being present.

## P1 Findings

- BLS timed out in all observed runs; BEA also failed once. These partial failures were recorded but not isolated behind tool-level retry/circuit-breaker metadata.
- Quality checks still produce suspicious ticker detections from ordinary English tokens and raw-English leakage findings.
- The final delivery status combines quality failure, unsupported claims, and pending human review, but does not identify one canonical primary blocker.
- Section pack aliases remain duplicated: 15 packs are generated for a report with fewer canonical sections.

## Reproduction

Start the production app, then run:

```bash
python scripts/run_production_baseline.py --base-url http://127.0.0.1:7863 --period FY2024
```

The runner creates a timestamped directory under `data/evaluation/production_baseline_v5/` and never overwrites a previous result.

## Next Gate

The next implementation stage is ReAct runtime hardening. It must add argument validation, correct terminal semantics, bounded timeout/retry behavior, and deterministic merging of ReAct research with standard search before LangGraph generation is split into independently checkpointed agent nodes.
