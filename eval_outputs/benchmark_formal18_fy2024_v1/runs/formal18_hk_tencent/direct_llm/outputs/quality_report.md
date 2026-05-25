# Report Quality Evaluation

- objective_pass: `False`
- total_score: `0.6158`
- run_dir: `eval_outputs\benchmark_formal18_fy2024_v1\runs\formal18_hk_tencent\direct_llm`

## Scores

- structure: `1.0`
- evidence: `0.7812`
- financial: `0.4125`
- multimodal: `0.0`
- professional_depth: `0.6667`
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

- **blocker / financial**: 缺少利润表摘要
- **blocker / financial**: 缺少资产负债表摘要
- **blocker / financial**: 缺少现金流量表摘要
- **blocker / gate**: 质量门禁未通过：has_three_table_summary
- **blocker / multimodal**: 缺少图表产物
- **blocker / professional_depth**: 估值缺失但没有明确估值不可用原因
- **blocker / professional_depth**: 投资结论缺少明确方向和理由
- **warning / compliance**: 合规披露不足：缺少 use_limitation
- **warning / compliance**: 合规披露不足：缺少 conflict_statement
- **warning / delivery_policy**: 多智能体 trace 未清楚声明 memory 不可替代事实证据
- **warning / delivery_policy**: 免费公开数据源尝试不足，至少应记录两个以上数据源/搜索引擎
- **warning / evidence**: 权威/一手来源占比偏低：0.00
