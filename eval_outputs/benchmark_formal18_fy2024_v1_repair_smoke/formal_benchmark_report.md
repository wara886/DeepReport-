# Formal Frozen-Snapshot Benchmark Report

## Protocol

- dataset_version: `formal18_fy2024_v1`
- snapshot_sha256: `d989a021754e5cd0f8c0d4f2015b40b444c02a784ba2a0cd860977983cffa54e`
- snapshot_complete: `True`; validated: `True`
- evaluated_reports: `2/54`
- All variants use the same frozen evidence snapshot; runtime evidence fetching is prohibited.
- Core metrics: `Delivery Pass Rate`, `Objective Quality Score`, `Traceable Claim Rate v1`.
- The primary traceability score is the macro-average of fixed-case claim rates; micro claim coverage is reported as a diagnostic below.

## Overall Results

| Variant | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |
| --- | ---: | ---: | ---: |
| `direct_llm` | - | - | - |
| `single_agent_rag` | - | - | - |
| `multi_agent_rag` | 100.00% | 90.66 | 95.00% |

## Market Results

| Variant | Market | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |
| --- | --- | ---: | ---: | ---: |
| `direct_llm` | US | - | - | - |
| `direct_llm` | HK | - | - | - |
| `direct_llm` | CN-A | - | - | - |
| `single_agent_rag` | US | - | - | - |
| `single_agent_rag` | HK | - | - | - |
| `single_agent_rag` | CN-A | - | - | - |
| `multi_agent_rag` | US | - | - | - |
| `multi_agent_rag` | HK | 100.00% | 85.06 | 100.00% |
| `multi_agent_rag` | CN-A | 100.00% | 96.25 | 90.00% |

## Secondary Diagnostics

| Variant | Runs Evaluated | Runtime/Model Failures | Delivery Failures | Traceable / Critical Claims | Micro Traceable Claim Rate v1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `direct_llm` | 0/0 | 0 | 0 | 0 / 0 | 0.00% |
| `single_agent_rag` | 0/0 | 0 | 0 | 0 / 0 | 0.00% |
| `multi_agent_rag` | 2/2 | 0 | 0 | 14 / 15 | 93.33% |

## Failure Taxonomy

| Failure Category | Direct LLM | Single-Agent RAG | Multi-Agent RAG | Total |
| --- | ---: | ---: | ---: | ---: |
| `citation_or_evidence_gap` | 0 | 0 | 1 | 1 |

## Failure Retrospective

- Multi-Agent RAG traceability is weakest in `CN-A` (90.00%); the next repair priority is denser critical-claim citation and numeric-lineage coverage in that market.
- Multi-Agent RAG delivery is weakest in `HK` (100.00%); delivery blockers should be reviewed case by case before widening the benchmark.

## Interpretation Boundary

- These are formal results on the frozen FY2024 dataset version above, not results from live evidence retrieval.
- The results support a comparison under this fixed protocol; they do not establish production-grade coverage or investment accuracy.
- Detailed rows and failure labels are retained in `formal_runs.jsonl` and `formal_failures.csv`.
