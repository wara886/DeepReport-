# Phase 3: Formal Frozen-Snapshot Benchmark Protocol

## Status

- Protocol implementation date: `2026-05-24`.
- Dataset version: `formal18_fy2024_v1`.
- Snapshot coverage: `18/18` ready cases (`US 6/6`, `HK 6/6`, `CN-A 6/6`).
- Snapshot SHA-256: `d989a021754e5cd0f8c0d4f2015b40b444c02a784ba2a0cd860977983cffa54e`.
- Run state: `54/54` variant/case runs evaluated with no runtime or model failure.

This phase introduces the reproducibility contract for comparing `direct_llm`, `single_agent_rag`, and `multi_agent_rag`. It does not reuse online Quick-9 reports as formal inputs.

## Fixed Cases

| Market | Symbols |
| --- | --- |
| US | `AAPL`, `MSFT`, `GOOGL`, `NVDA`, `AMD`, `TSLA` |
| HK | `0020.HK`, `6682.HK`, `0700.HK`, `1810.HK`, `3690.HK`, `9888.HK` |
| CN-A | `600519.SS`, `300750.SZ`, `002594.SZ`, `601318.SS`, `600036.SS`, `688981.SS` |

All cases target `FY2024`.

## Acquisition And Staging

Network acquisition is isolated in `scripts/stage_formal18_fy2024_evidence.py`; it is not called by the formal runner.

| Market | Accepted staging route | Current result |
| --- | --- | --- |
| US | SEC EDGAR `companyfacts` with `fy=2024`, `fp=FY`, annual filing form, and current fiscal-year `end` selected from comparative columns | `6/6` staged |
| CN-A | CNINFO full FY2024 annual-report disclosure plus FY2024-matched Eastmoney income/balance/cashflow structured rows | `6/6` staged |
| HK | HKEXnews official annual-report title search, company/code match, FY2024 document check and PDF extraction | `6/6` staged |

The formal HK route uses official HKEXnews disclosure records and validates stock code and annual-report period before freezing extracted evidence. Indirect general-search results are not accepted into the formal snapshot.

## Frozen Input Contract

Evidence must first be staged under `data/benchmark_sources/fy2024/`, using either:

```text
<case_id>/evidence.jsonl
<case_id>/evidence.json
<canonical_symbol>/FY2024/evidence.jsonl
<canonical_symbol>/FY2024/evidence.json
```

Each evidence record must contain:

```text
evidence_id, source_type, title, source_url, publish_time,
content, symbol, period, trust_level
```

The snapshot builder performs no online fetch. It accepts only records matching the configured symbol and `FY2024`, freezes them to `data/benchmarks/frozen_fy2024_v1/cases/`, and writes:

- Per-case SHA-256 hashes.
- One deterministic `snapshot_sha256`.
- Explicit missing/invalid case statuses.
- `complete=true` only after all formal-18 cases are ready.

The formal runner refuses to score an incomplete or hash-invalid snapshot.

## Variant Contract

| Variant | Frozen Context Use | Retrieval | Orchestration |
| --- | --- | --- | --- |
| `direct_llm` | Same frozen case evidence pool | None | One generation call |
| `single_agent_rag` | Same frozen case evidence pool | Local BM25 selection | One generation call |
| `multi_agent_rag` | Same frozen case evidence pool | Snapshot-only local BM25 engine | Current `MultiAgentOrchestrator` `diagnostic_full` chain, including verification/rework |

Runtime evidence fetching is prohibited for all three variants. The model configuration path is shared through `configs/model_backends.yaml`.
For `multi_agent_rag`, the runner injects a search manager exposing only `formal_snapshot_bm25` and an isolated empty raw-data root, so the current orchestrator cannot silently fall through to runtime or existing non-snapshot evidence.

## Traceable Claim Rate V1

`ClaimItem` now supports:

- `is_critical`
- `critical_claim_type`

Allowed types are:

```text
revenue, profit, cash_flow, margin, valuation,
peer_comparison, risk, investment_rationale
```

A critical claim counts as traceable only when all conditions hold:

1. It has an explicit allowed critical label.
2. Its cited evidence ID exists in the frozen snapshot for that case.
3. The report body uses the linked citation.
4. Numeric claims pass the formal linked-evidence numeric audit.

The formal multi-agent path enables an analyzer-side `formal_v1` claim contract that persists labels from structured claim sections and numeric fields before scoring. The evaluator itself does not infer formal labels from claim prose. A generated claim without `is_critical=true` and a permitted `critical_claim_type` cannot enter the v1 numerator or denominator.

The primary reported `Traceable Claim Rate v1` is the macro-average of the 18 fixed case-level rates for each variant. A micro claim-level ratio is emitted as a secondary diagnostic to disclose differences in generated claim volume.

## Formal Results

| Variant | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |
| --- | ---: | ---: | ---: |
| `direct_llm` | `16.67%` | `51.21` | `29.66%` |
| `single_agent_rag` | `27.78%` | `52.52` | `34.89%` |
| `multi_agent_rag` | `72.22%` | `86.27` | `70.01%` |

| Multi-Agent RAG Market | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |
| --- | ---: | ---: | ---: |
| US | `100.00%` | `85.06` | `100.00%` |
| HK | `66.67%` | `87.53` | `37.80%` |
| CN-A | `50.00%` | `86.22` | `72.22%` |

All 54 runs were evaluable. Multi-Agent RAG recorded five delivery failures and nine `citation_or_evidence_gap` labels; its weak point is especially visible in Hong Kong claim traceability. The comparison therefore supports superiority under this frozen protocol, but does not establish stable production coverage or investment accuracy.

## Commands

Acquire period-verified public source records into the local staging directory:

```powershell
python scripts/stage_formal18_fy2024_evidence.py --config configs/benchmark_formal18_fy2024.yaml
```

This stages the 18 period-verified case inputs. Network access occurs only in this explicit staging command.

Build or refresh the offline snapshot manifest:

```powershell
python scripts/build_frozen_snapshot.py --config configs/benchmark_formal18_fy2024.yaml
```

This writes the complete, hash-verifiable `formal18_fy2024_v1` snapshot used in the recorded comparison.

Run the formal comparison after the snapshot reaches `complete=true`:

```powershell
python scripts/run_formal_benchmark.py --config configs/benchmark_formal18_fy2024.yaml
```

## Result Artifacts

- `data/benchmarks/frozen_fy2024_v1/snapshot_manifest.json`: versioned input inventory and hashes.
- `eval_outputs/benchmark_formal18_fy2024_v1/formal_benchmark_report.md`: readable formal result and failure summary.
- `eval_outputs/benchmark_formal18_fy2024_v1/formal_results_overall.csv`: primary comparison table.
- `eval_outputs/benchmark_formal18_fy2024_v1/formal_results_by_market.csv`: market breakdown.
- `eval_outputs/benchmark_formal18_fy2024_v1/formal_secondary_metrics.csv`: run and claim-level diagnostics.
- `eval_outputs/benchmark_formal18_fy2024_v1/formal_failures.csv`: failure taxonomy detail.

## Reporting Boundary

The published result may state that Multi-Agent RAG outperformed the two one-shot baselines on the frozen Formal-18 protocol. It must remain linked to dataset version `formal18_fy2024_v1`, must retain the identified HK/CN-A weaknesses, and must not be presented as production stability or investment recommendation accuracy.
