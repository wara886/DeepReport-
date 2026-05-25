# Report Quality Evaluation

- objective_pass: `False`
- total_score: `0.8506`
- run_dir: `eval_outputs\benchmark_formal18_fy2024_v1\runs\formal18_us_tsla\multi_agent_rag`

## Scores

- structure: `1.0`
- evidence: `0.7778`
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
- pre_write_critic_passed: `True`
- analysis_role_outputs: `True`

## Top Issues

- **blocker / financial**: 缺少利润表摘要
- **blocker / financial**: 缺少资产负债表摘要
- **blocker / financial**: 缺少现金流量表摘要
- **blocker / gate**: 质量门禁未通过：has_three_table_summary
- **warning / delivery_policy**: 免费公开数据源尝试不足，至少应记录两个以上数据源/搜索引擎
- **warning / financial**: 正文缺少清晰单位或百分比表达
