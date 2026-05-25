# Report Quality Evaluation

- objective_pass: `False`
- total_score: `0.8783`
- run_dir: `eval_outputs\benchmark_quick9_multi_agent\runs\20260524_065357_quick9_hk_tencent\company\outputs`

## Scores

- structure: `1.0`
- evidence: `0.9167`
- financial: `0.55`
- multimodal: `0.8`
- professional_depth: `1.0`
- compliance: `1.0`

## Required Checks

- passed: `False`

## Generalization Checks

- identity_consistency: `True`
- period_consistency: `True`
- market_route_coverage: `True`
- industry_profile_confidence: `True`
- pre_write_critic_passed: `False`
- analysis_role_outputs: `True`

## Top Issues

- **blocker / financial**: 缺少利润表摘要
- **blocker / financial**: 缺少资产负债表摘要
- **blocker / financial**: 缺少现金流量表摘要
- **blocker / gate**: 质量门禁未通过：has_three_table_summary
- **blocker / generalization**: 泛化质量检查未通过：pre_write_critic_passed
- **warning / evidence**: 权威/一手来源占比偏低：0.00
