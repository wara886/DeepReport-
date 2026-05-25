# Report Quality Evaluation

- objective_pass: `False`
- total_score: `0.4434`
- run_dir: `eval_outputs\benchmark_formal18_fy2024_v1\runs\formal18_hk_4paradigm\direct_llm`

## Scores

- structure: `0.8333`
- evidence: `0.2357`
- financial: `0.4125`
- multimodal: `0.0`
- professional_depth: `0.5`
- compliance: `0.6`

## Required Checks

- passed: `False`

## Generalization Checks

- identity_consistency: `True`
- period_consistency: `True`
- market_route_coverage: `True`
- industry_profile_confidence: `True`
- pre_write_critic_passed: `True`

## Top Issues

- **blocker / evidence**: claim 缺少 evidence_ids：cl_0001
- **blocker / evidence**: claim 缺少 evidence_ids：cl_0002
- **blocker / evidence**: claim 缺少 evidence_ids：cl_0003
- **blocker / evidence**: claim 缺少 evidence_ids：cl_0004
- **blocker / evidence**: claim 缺少 evidence_ids：cl_0005
- **blocker / evidence**: claim 缺少 evidence_ids：cl_0006
- **blocker / evidence**: claim 缺少 evidence_ids：cl_0007
- **blocker / financial**: 缺少利润表摘要
- **blocker / financial**: 缺少资产负债表摘要
- **blocker / financial**: 缺少现金流量表摘要
- **blocker / gate**: 质量门禁未通过：has_three_table_summary
- **blocker / gate**: 质量门禁未通过：has_business_profile
