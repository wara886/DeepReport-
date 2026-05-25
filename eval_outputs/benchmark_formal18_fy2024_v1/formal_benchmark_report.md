# Formal Frozen-Snapshot Benchmark Report

## Protocol

- dataset_version: `formal18_fy2024_v1`
- snapshot_sha256: `d989a021754e5cd0f8c0d4f2015b40b444c02a784ba2a0cd860977983cffa54e`
- snapshot_complete: `True`; validated: `True`
- evaluated_reports: `54/54`
- All variants use the same frozen evidence snapshot; runtime evidence fetching is prohibited.
- Core metrics: `Delivery Pass Rate`, `Objective Quality Score`, `Traceable Claim Rate v1`.
- The primary traceability score is the macro-average of fixed-case claim rates; micro claim coverage is reported as a diagnostic below.

## Overall Results

| Variant | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |
| --- | ---: | ---: | ---: |
| `direct_llm` | 16.67% | 51.21 | 29.66% |
| `single_agent_rag` | 27.78% | 52.52 | 34.89% |
| `multi_agent_rag` | 72.22% | 86.27 | 70.01% |

## Market Results

| Variant | Market | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |
| --- | --- | ---: | ---: | ---: |
| `direct_llm` | US | 0.00% | 49.90 | 45.24% |
| `direct_llm` | HK | 33.33% | 53.19 | 33.33% |
| `direct_llm` | CN-A | 16.67% | 50.55 | 10.42% |
| `single_agent_rag` | US | 16.67% | 50.90 | 30.55% |
| `single_agent_rag` | HK | 16.67% | 54.16 | 45.24% |
| `single_agent_rag` | CN-A | 50.00% | 52.50 | 28.87% |
| `multi_agent_rag` | US | 100.00% | 85.06 | 100.00% |
| `multi_agent_rag` | HK | 66.67% | 87.53 | 37.80% |
| `multi_agent_rag` | CN-A | 50.00% | 86.22 | 72.22% |

## Secondary Diagnostics

| Variant | Runs Evaluated | Runtime/Model Failures | Delivery Failures | Traceable / Critical Claims | Micro Traceable Claim Rate v1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `direct_llm` | 18/18 | 0 | 15 | 40 / 128 | 31.25% |
| `single_agent_rag` | 18/18 | 0 | 13 | 44 / 116 | 37.93% |
| `multi_agent_rag` | 18/18 | 0 | 5 | 67 / 103 | 65.05% |

## Failure Taxonomy

| Failure Category | Direct LLM | Single-Agent RAG | Multi-Agent RAG | Total |
| --- | ---: | ---: | ---: | ---: |
| `citation_or_evidence_gap` | 15 | 16 | 9 | 40 |
| `delivery_requirement_failed` | 15 | 13 | 5 | 33 |

## Failure Retrospective

- Multi-Agent RAG traceability is weakest in `HK` (37.80%); the next repair priority is denser critical-claim citation and numeric-lineage coverage in that market.
- Multi-Agent RAG delivery is weakest in `CN-A` (50.00%); delivery blockers should be reviewed case by case before widening the benchmark.

## Interpretation Boundary

- These are formal results on the frozen FY2024 dataset version above, not results from live evidence retrieval.
- The results support a comparison under this fixed protocol; they do not establish production-grade coverage or investment accuracy.
- Detailed rows and failure labels are retained in `formal_runs.jsonl` and `formal_failures.csv`.
