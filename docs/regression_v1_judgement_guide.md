# regression_v1 结果评判指南

## 1. 每次先看哪个文件

1. `reports/eval_v1/summary.json`：总体指标（用于版本对比）
2. `reports/eval_v1/per_case.csv`：逐 case 定位问题
3. `data/evaluation/eval_v1/per_case_numeric_audit_v1.jsonl`：数字错误细分

## 2. 核心判分指标（按优先级）

1. `numeric_accuracy`：关键财务数字正确率（越高越好）
2. `claim_grounded_rate`：claim 被 verifier 接受的比例（越高越好）
3. `evidence_coverage`：claim 是否绑定证据（越高越好）
4. `fallback_rate`：writer fallback 发生率（越低越好）
5. `top1_evidence_hit_rate / top3_evidence_hit_rate`：检索命中率（越高越好）

## 3. 建议硬门槛（Go/No-Go）

- `sample_count >= 30`
- `evidence_coverage >= 0.90`
- `claim_grounded_rate >= 0.70`
- `numeric_accuracy >= 0.80`
- `fallback_rate <= 0.10`
- `top3_evidence_hit_rate >= 0.70`

任一硬门槛不达标：判定本轮不可作为“质量提升版本”。

## 4. 结果解释模板

- 结论：`PASS` 或 `FAIL`
- 主要提升：列 1-2 项提升最大的指标
- 主要退化：列 1-2 项下降最大的指标
- 主瓶颈归因：
  - 若 `top3 hit` 低：优先查 retrieval/reranker
  - 若 `top3 hit` 高但 `grounded` 低：优先查 verifier/claim 对齐
  - 若 `grounded` 高但 `numeric` 低：优先查 numeric audit 与 writer 数字表达
  - 若 `fallback` 高：优先查 writer backend 稳定性/配置

## 5. 最小对比规则

对比新旧两版 `summary.json`，至少满足：

- `numeric_accuracy` 不下降
- `claim_grounded_rate` 不下降
- `fallback_rate` 不上升

在此基础上再追求 `top1/top3 hit rate` 上升。

