# Multi-Agent Regression Summary

## Core Metrics

- sample_count: 1
- report_count: 2
- evidence_coverage: 1.0
- claim_grounded_rate: 0.5
- numeric_accuracy: 1.0
- chart_consistency_pass_rate: 1.0
- contest_checklist_score_mean: 87.0187
- contest_checklist_pass_rate_mean: 0.8701
- revision_rate: 1.0
- avg_duration_sec: 137.0395

## Failure Taxonomy

- company_depth_incomplete: 2
- numeric_inconsistency: 2
- section_missing: 1
- verifier_failed: 1

## Retrieval Ablation

- hybrid_rerank: alignment=1.0, coverage=1.0, verifier_pass=0.5

## Regression Topics

- entity_mismatch: ticker/公司名混淆，例如 Nvda 不应解析成 NADA。
- evidence_gap: claim 缺少 evidence_id 或引用了不存在的证据。
- chart_text_mismatch: 图表来源、数值和正文 claim 不一致。
- numeric_error: 收入、利润率、现金流等数值与证据不匹配。
- section_missing: 赛题要求章节缺失，例如三表、治理、战略、估值敏感性。
