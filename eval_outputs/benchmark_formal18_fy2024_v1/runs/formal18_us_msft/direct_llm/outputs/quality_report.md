# Report Quality Evaluation

- objective_pass: `False`
- total_score: `0.5377`
- run_dir: `eval_outputs\benchmark_formal18_fy2024_v1\runs\formal18_us_msft\direct_llm`

## Scores

- structure: `0.8333`
- evidence: `0.7071`
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

- **blocker / evidence**: claim 缺少 evidence_ids：cl_0005
- **blocker / financial**: 缺少利润表摘要
- **blocker / financial**: 缺少资产负债表摘要
- **blocker / financial**: 缺少现金流量表摘要
- **blocker / gate**: 质量门禁未通过：has_three_table_summary
- **blocker / gate**: 质量门禁未通过：has_business_profile
- **blocker / multimodal**: 缺少图表产物
- **blocker / professional_depth**: 专业深度不足：缺少 business_profile
- **blocker / professional_depth**: 估值缺失但没有明确估值不可用原因
- **blocker / professional_depth**: 投资结论缺少明确方向和理由
- **blocker / structure**: 缺少必备章节或段落：business_profile
- **warning / compliance**: 合规披露不足：缺少 use_limitation
