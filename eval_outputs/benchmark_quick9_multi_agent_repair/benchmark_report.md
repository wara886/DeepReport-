# Quick-9 Multi-Agent Repair Diagnostic Report

## Scope

- Phase: `Phase 2R - Pre-Phase-3 Repair Evaluation`.
- Variant: `multi_agent` only. No `Direct LLM` or `Single-Agent RAG` baseline was run.
- This is an online-source engineering diagnostic, not a frozen-snapshot fair model comparison.
- Fixed denominator: `9` configured cases; completed artifacts: `9`.
- Target period: `2026Q1`; retrieval mode: `hybrid_rerank`.
- `Traceable Claim Rate (artifact-derived)` remains an initial sidecar-derived metric, not formal `Traceable Claim Rate v1`.
- `Delivery Pass Rate` uses deterministic delivery requirements only; objective quality and traceability remain separate diagnostics.
- Delivery and traceability rates use all fixed cases; Objective Quality Score averages only cases with evaluable quality artifacts.
- Repair route: `diagnostic_full` with up to `1` delivery rework round(s); reworked cases: `9`.
- This repair rerun is a checkpoint before Phase 3; it does not freeze evidence or introduce baseline variants.

## Core Metrics

| Metric | Overall | US | HK | CN-A |
| --- | ---: | ---: | ---: | ---: |
| Delivery Pass Rate | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| Objective Quality Score | 95.86 | 96.70 | 91.03 | 99.84 |
| Traceable Claim Rate (artifact-derived) | 0.8591 | 1.0000 | 0.6444 | 0.9328 |

## Case Results

| Case | Market | Status | Delivery | Quality | Traceable | Primary Blocker |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `AAPL` | US | `evaluated` | pass | 96.67 | 1.0000 | `-` |
| `AMD` | US | `evaluated` | pass | 96.76 | 1.0000 | `-` |
| `TSLA` | US | `evaluated` | pass | 96.67 | 1.0000 | `-` |
| `0020.HK` | HK | `evaluated` | pass | 85.25 | 0.0000 | `citation_or_evidence_gap` |
| `6682.HK` | HK | `evaluated` | pass | 100.00 | 0.9333 | `citation_or_evidence_gap` |
| `0700.HK` | HK | `evaluated` | pass | 87.83 | 1.0000 | `quality_gate_blocker` |
| `600519.SS` | CN-A | `evaluated` | pass | 100.00 | 0.9286 | `citation_or_evidence_gap` |
| `300750.SZ` | CN-A | `evaluated` | pass | 100.00 | 0.9286 | `citation_or_evidence_gap` |
| `601318.SS` | CN-A | `evaluated` | pass | 99.52 | 0.9412 | `citation_or_evidence_gap` |

## Failure Taxonomy

- `citation_or_evidence_gap`: 5
- `quality_gate_blocker`: 2

## Boundary

- These results locate current cross-market engineering failures only; they do not show that Multi-Agent outperforms another architecture.
- A formal result table requires common frozen evidence inputs and baseline variants in Phase 3.
