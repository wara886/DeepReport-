# Existing Artifact Benchmark Report

## Scope

- Phase: `Existing Artifact Evaluator`.
- This report only summarizes existing multi-agent artifacts; it is not a completed quick-9 rerun or a baseline comparison.
- observed_runs=5/9; evaluable_runs=5.
- Core metric denominators include evaluated runs only; `not_run` and `not_evaluable` rows are shown as coverage gaps and excluded from metric averages.
- `Delivery Pass Rate` uses eight deterministic delivery checks only: identity, summary, risk, conclusion, body citation, three statements or disclosed gap, valuation or reason, and chart consistency.
- Objective quality blockers and traceability gaps remain diagnostics and separate metrics; they are not counted a second time inside `Delivery Pass Rate`.
- `Traceable Claim Rate (artifact-derived)` is an initial metric derived from current sidecars, not the formal frozen-snapshot `Traceable Claim Rate v1`.

## Core Metrics

| Metric | Overall | US | HK | CN-A |
| --- | ---: | ---: | ---: | ---: |
| Delivery Pass Rate | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| Objective Quality Score | 95.72 | 96.70 | 89.50 | 99.00 |
| Traceable Claim Rate (artifact-derived) | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

## Coverage

- `AAPL` (US): `evaluated`; 2026Q1
- `AMD` (US): `evaluated`; 2026Q1
- `TSLA` (US): `evaluated`; 2026Q1
- `0020.HK` (HK): `not_run`; -
- `6682.HK` (HK): `not_run`; -
- `0700.HK` (HK): `evaluated`; 2026Q1
- `600519.SS` (CN-A): `evaluated`; 2026Q1
- `300750.SZ` (CN-A): `not_run`; -
- `601318.SS` (CN-A): `not_run`; -

## Not Run Or Not Evaluable

- `0020.HK`: not_run - no matching existing run
- `6682.HK`: not_run - no matching existing run
- `300750.SZ`: not_run - no matching existing run
- `601318.SS`: not_run - no matching existing run

## Failure Reasons

- `quality_gate_blocker`: 2
- `citation_or_evidence_gap`: 1

## Interpretation Boundary

- Phase 1 does not implement `Direct LLM` or `Single-Agent RAG`, freeze evidence snapshots, modify claim schema, or modify the Agent pipeline.
- Metrics above describe only selected existing artifacts. Formal cross-system claims require the later frozen-snapshot benchmark phase.
