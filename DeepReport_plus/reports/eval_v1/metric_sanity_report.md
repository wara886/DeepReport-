# 指标健康诊断报告（Metric Sanity Report）

- 主分析变体（primary_variant）: bm25_real_writer
- 样本数（sample_count）: 30
- Claim 支撑率（claim_grounded_rate）唯一值: [0.5]
- 数字准确率（numeric_accuracy）唯一值: [0.75]
- Top1 证据命中率（top1_evidence_hit_rate）唯一值: [0.0]
- 验证阈值（verifier_checkpoint.threshold）: 0.75

## 桶塌缩原因说明

- claim_grounded_rate: Claim 支撑率（claim_grounded_rate）来自基于置信度阈值的过滤；当前验证阈值（verifier_checkpoint.threshold）=0.75，且 claim 置信度分布较稳定，所以每个 case 收敛到 0.5。
- numeric_accuracy: 数字准确率（numeric_accuracy）中每个 case 基本固定出现 1 个错误，形成 3/4=0.75；细分根因见 numeric_root_cause_breakdown_zh。
- top1_evidence_hit_rate: Top1 证据命中率（top1_evidence_hit_rate）为 0，主要因为 top1 的来源类型（source_type）稳定为 market，而 gold 证据主要是 financials/filings/news。

## 支撑证据

- Top1 来源类型（source_type）分布: {'market': 30}
- 数字错误类型分布（numeric_mismatch_error_distribution）: {'value_mismatch': 30}
- 数字错误指标分布（numeric_mismatch_metric_distribution）: {'revenue': 30}
- Numeric 根因细分（numeric_root_cause_breakdown）: {'数值错': 0, '单位错': 0, '期间错': 0, '近邻数字碰撞': 30, '重写损坏': 0}