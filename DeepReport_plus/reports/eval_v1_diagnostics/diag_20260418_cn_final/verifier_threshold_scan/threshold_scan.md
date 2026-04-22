# 验证阈值扫描诊断（Verifier Threshold Scan）

说明：本诊断仅离线分析，不修改默认验证阈值（verifier_checkpoint.threshold）。

| 阈值（verifier_checkpoint.threshold） | Claim 支撑率（claim_grounded_rate） |
|---:|---:|
| 0.5 | 1.0 |
| 0.55 | 1.0 |
| 0.6 | 1.0 |
| 0.65 | 1.0 |
| 0.7 | 1.0 |
| 0.75 | 0.5 |
| 0.8 | 0.1 |
| 0.85 | 0.0 |
| 0.9 | 0.0 |
| 0.95 | 0.0 |

- 最优阈值（best_threshold_by_grounded_rate）: 0.5，对应 Claim 支撑率（claim_grounded_rate）=1.0

## 按任务类型并排（task_type）

| 阈值 | event | financial | fundamental |
|---:|---:|---:|---:|
| 0.5 | 1.0 | 1.0 | 1.0 |
| 0.55 | 1.0 | 1.0 | 1.0 |
| 0.6 | 1.0 | 1.0 | 1.0 |
| 0.65 | 1.0 | 1.0 | 1.0 |
| 0.7 | 1.0 | 1.0 | 1.0 |
| 0.75 | 0.5 | 0.5 | 0.5 |
| 0.8 | 0.1 | 0.1 | 0.1 |
| 0.85 | 0.0 | 0.0 | 0.0 |
| 0.9 | 0.0 | 0.0 | 0.0 |
| 0.95 | 0.0 | 0.0 | 0.0 |