# Quick-9 Repair Comparison

## Method

- Before artifacts: `eval_outputs\benchmark_quick9_multi_agent`.
- `recorded_before` is the metric value written by the original Phase 2 implementation.
- `before_reassessed` re-evaluates the original Phase 2 artifacts with the corrected deterministic delivery contract, so metric-rule correction is not misreported as repair gain.
- `after_repair` is the Phase 2R `diagnostic_full` rerun with configured source routing and one delivery rework round.
- Both sides remain `multi_agent` online-source diagnostics; this is not a baseline comparison or frozen-snapshot benchmark.

## Metrics

| Metric | Recorded Before | Before Reassessed | After Repair | Repair Delta |
| --- | ---: | ---: | ---: | ---: |
| Delivery Pass Rate | 0.0000 | 1.0000 | 1.0000 | 0.0000 |
| Objective Quality Score | 94.84 | 94.84 | 95.86 | 1.02 |
| Traceable Claim Rate (artifact-derived) | 0.9777 | 0.9777 | 0.8591 | -0.1186 |

## Cases

| Case | Market | Delivery Before | Delivery After | Traceable Before | Traceable After |
| --- | --- | ---: | ---: | ---: | ---: |
| `AAPL` | US | pass | pass | 1.0000 | 1.0000 |
| `AMD` | US | pass | pass | 1.0000 | 1.0000 |
| `TSLA` | US | pass | pass | 1.0000 | 1.0000 |
| `0020.HK` | HK | pass | pass | 1.0000 | 0.0000 |
| `6682.HK` | HK | pass | pass | 1.0000 | 0.9333 |
| `0700.HK` | HK | pass | pass | 1.0000 | 1.0000 |
| `600519.SS` | CN-A | pass | pass | 0.9286 | 0.9286 |
| `300750.SZ` | CN-A | pass | pass | 0.9333 | 0.9286 |
| `601318.SS` | CN-A | pass | pass | 0.9375 | 0.9412 |

## Remaining Gaps

- Treat passed delivery cases with `citation_or_evidence_gap` or `quality_gate_blocker` diagnostics as repair follow-ups, not formal-quality successes.
- Phase 3 remains blocked on frozen evidence inputs, baseline variants, and explicit `Traceable Claim Rate v1` labeling.
