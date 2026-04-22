# 诊断型消融并排对比（Diagnostic Ablation Comparison）

- 运行编号（run_id）: diag_20260418_cn_final
- 主分析变体（primary_variant）: bm25_real_writer
- 基线摘要（baseline_summary）: reports\eval_v1\summary.json

## 全局并排

| 场景（scenario） | verifier 开关 | writer 命中代理开关 | numeric 匹配器 | Claim 支撑率（claim_grounded_rate） | Writer 命中代理（writer_hit_proxy） | 数字准确率（numeric_accuracy） |
|---|---|---|---|---:|---:|---:|
| baseline_diag | on | top3 | strict | 0.5 | 1.0 | 0.75 |
| verifier_off_diag | off | top3 | strict | 1.0 | 1.0 | 0.75 |
| writer_top1_diag | on | top1 | strict | 0.5 | 0.0 | 0.75 |
| numeric_relaxed_diag | on | top3 | relaxed | 0.5 | 1.0 | 1.0 |

## 按任务类型并排（task_type）

### 任务类型（task_type）: event

| 场景 | Claim 支撑率（claim_grounded_rate） | Writer 命中代理（writer_hit_proxy） | 数字准确率（numeric_accuracy） |
|---|---:|---:|---:|
| baseline_diag | 0.5 | 1.0 | 0.75 |
| verifier_off_diag | 1.0 | 1.0 | 0.75 |
| writer_top1_diag | 0.5 | 0.0 | 0.75 |
| numeric_relaxed_diag | 0.5 | 1.0 | 1.0 |

### 任务类型（task_type）: financial

| 场景 | Claim 支撑率（claim_grounded_rate） | Writer 命中代理（writer_hit_proxy） | 数字准确率（numeric_accuracy） |
|---|---:|---:|---:|
| baseline_diag | 0.5 | 1.0 | 0.75 |
| verifier_off_diag | 1.0 | 1.0 | 0.75 |
| writer_top1_diag | 0.5 | 0.0 | 0.75 |
| numeric_relaxed_diag | 0.5 | 1.0 | 1.0 |

### 任务类型（task_type）: fundamental

| 场景 | Claim 支撑率（claim_grounded_rate） | Writer 命中代理（writer_hit_proxy） | 数字准确率（numeric_accuracy） |
|---|---:|---:|---:|
| baseline_diag | 0.5 | 1.0 | 0.75 |
| verifier_off_diag | 1.0 | 1.0 | 0.75 |
| writer_top1_diag | 0.5 | 0.0 | 0.75 |
| numeric_relaxed_diag | 0.5 | 1.0 | 1.0 |

## 风险说明

- 本诊断只读取既有产物进行离线计算，不改默认流程。
- 未修改 retrieval 主逻辑、writer 核心生成策略、verifier 判定逻辑。
- verifier 阈值扫描为离线分析结果，不会写回 checkpoint。