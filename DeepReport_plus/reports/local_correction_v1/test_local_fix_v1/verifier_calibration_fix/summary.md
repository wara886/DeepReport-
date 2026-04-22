# Verifier 校准修复实验（verifier_calibration_fix_v1）

- 基线阈值（verifier_checkpoint.threshold）: 0.75
- 基线 Claim 支撑率（claim_grounded_rate）: 0.5
- 候选阈值（candidate_thresholds）: [0.7, 0.65, 0.6]
- 离线推荐阈值（recommended_threshold_offline）: 0.7

## 候选阈值对比

- 阈值=0.7: Claim 支撑率（claim_grounded_rate）=1.0, 相对基线增量=0.5, 假阳性风险代理（potential_false_positive_rate_proxy）=0.5
- 阈值=0.65: Claim 支撑率（claim_grounded_rate）=1.0, 相对基线增量=0.5, 假阳性风险代理（potential_false_positive_rate_proxy）=0.5
- 阈值=0.6: Claim 支撑率（claim_grounded_rate）=1.0, 相对基线增量=0.5, 假阳性风险代理（potential_false_positive_rate_proxy）=0.5

## 风险说明

- potential_false_positive_rate_proxy 基于新增放行 claim 的离线代理估计，不等价真实假阳性标注。