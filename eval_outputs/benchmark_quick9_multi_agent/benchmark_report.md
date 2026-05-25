# Quick-9 Multi-Agent Cross-Market Diagnostic Report

## Scope

- Phase: `Quick 9 Multi-Agent Benchmark`.
- Variant: `multi_agent` only. No `Direct LLM` or `Single-Agent RAG` baseline was run.
- This is an online-source engineering diagnostic, not a frozen-snapshot fair model comparison.
- Fixed denominator: `9` configured cases; completed artifacts: `9`.
- Target period: `2026Q1`; retrieval mode: `hybrid_rerank`.
- `Traceable Claim Rate (artifact-derived)` remains an initial sidecar-derived metric, not formal `Traceable Claim Rate v1`.
- Delivery and traceability rates use all fixed cases; Objective Quality Score averages only cases with evaluable quality artifacts.

## Core Metrics

| Metric | Overall | US | HK | CN-A |
| --- | ---: | ---: | ---: | ---: |
| Delivery Pass Rate | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Objective Quality Score | 94.84 | 96.76 | 87.83 | 99.92 |
| Traceable Claim Rate (artifact-derived) | 0.9777 | 1.0000 | 1.0000 | 0.9331 |

## Case Results

| Case | Market | Status | Delivery | Quality | Traceable | Primary Blocker |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `AAPL` | US | `evaluated` | fail | 96.76 | 1.0000 | `quality_gate_blocker` |
| `AMD` | US | `evaluated` | fail | 96.76 | 1.0000 | `quality_gate_blocker` |
| `TSLA` | US | `evaluated` | fail | 96.76 | 1.0000 | `quality_gate_blocker` |
| `0020.HK` | HK | `evaluated` | fail | 87.83 | 1.0000 | `three_statement_coverage` |
| `6682.HK` | HK | `evaluated` | fail | 87.83 | 1.0000 | `three_statement_coverage` |
| `0700.HK` | HK | `evaluated` | fail | 87.83 | 1.0000 | `three_statement_coverage` |
| `600519.SS` | CN-A | `evaluated` | fail | 100.00 | 0.9286 | `citation_or_evidence_gap` |
| `300750.SZ` | CN-A | `evaluated` | fail | 100.00 | 0.9333 | `citation_or_evidence_gap` |
| `601318.SS` | CN-A | `evaluated` | fail | 99.75 | 0.9375 | `citation_or_evidence_gap` |

## Failure Taxonomy

- `quality_gate_blocker`: 9
- `citation_or_evidence_gap`: 3
- `source_access_or_fetch`: 3
- `three_statement_coverage`: 3

## Boundary

- These results locate current cross-market engineering failures only; they do not show that Multi-Agent outperforms another architecture.
- A formal result table requires common frozen evidence inputs and baseline variants in Phase 3.
