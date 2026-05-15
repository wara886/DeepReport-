# Memory Ablation Comparison

- decision: promote_memory
- quality_guard_passed: True
- latency_guard_passed: True
- recommendation: Memory passed quality and latency guards; it can be promoted for broader smoke tests.

## Variant Metrics

### memory_disabled

- report_count: 3
- verification_pass_rate: 0.6667
- evidence_coverage_mean: 1.0
- evidence_alignment_mean: 1.0
- chart_consistency_pass_rate: 1.0
- contest_checklist_pass_rate_mean: 0.8677
- numeric_accuracy: 1.0
- avg_duration_sec: 123.8033

### memory_enabled

- report_count: 3
- verification_pass_rate: 0.6667
- evidence_coverage_mean: 1.0
- evidence_alignment_mean: 1.0
- chart_consistency_pass_rate: 1.0
- contest_checklist_pass_rate_mean: 0.8951
- numeric_accuracy: 1.0
- avg_duration_sec: 118.7927

## Deltas

- verification_pass_rate: 0.0
- evidence_coverage_mean: 0.0
- evidence_alignment_mean: 0.0
- chart_consistency_pass_rate: 0.0
- contest_checklist_pass_rate_mean: 0.0274
- numeric_accuracy: 0.0
- latency_delta_sec: -5.0106
