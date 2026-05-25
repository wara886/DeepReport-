# Ablation And Diagnostics

This document keeps pre-formal diagnostic context out of the project landing page. These experiments helped repair the evaluation workflow; they are not the headline benchmark.

## Fixed Quick-9 Diagnostic

On 2026-05-24, a fixed nine-company run exercised the current multi-agent route over US, HK and CN-A names using runtime-accessible sources. It was not a frozen-input comparison and did not run `direct_llm` or `single_agent_rag` baselines.

| Metric | Overall | US | HK | CN-A |
| --- | ---: | ---: | ---: | ---: |
| Delivery Pass Rate | 100.00% | 100.00% | 100.00% | 100.00% |
| Objective Quality Score | 94.84 | 96.76 | 87.83 | 99.92 |
| Traceable Claim Rate, artifact-derived | 97.77% | 100.00% | 100.00% | 93.31% |

The traceability statistic above used then-existing artifacts and is not `Traceable Claim Rate v1`.

## Phase 2R Repair Diagnostic

Phase 2R corrected a delivery-contract issue that had double-counted independent quality diagnostics, then reran the nine-case path with repair behavior enabled.

| Metric | Original recorded value | Reassessed source artifacts | Repair rerun |
| --- | ---: | ---: | ---: |
| Delivery Pass Rate | 0.00% | 100.00% | 100.00% |
| Objective Quality Score | 94.84 | 94.84 | 95.86 |
| Traceable Claim Rate, artifact-derived | 97.77% | 97.77% | 85.91% |

The original delivery increase must not be framed as model-quality improvement: it primarily reflects the repaired evaluation contract. These diagnostics motivated the frozen Formal-18 protocol, which is the public comparative result.
