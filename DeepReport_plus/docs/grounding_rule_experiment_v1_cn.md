# Grounding 规则实验 v1（grounding_rule_experiment_v1）说明

## 1. 目标与边界

- 目标：在不改 baseline 默认逻辑的前提下，离线比较 baseline 规则与 rule-aware 规则。
- 边界：不修改 retrieval / writer / report；不覆盖默认配置；仅新增独立实验脚手架和产物。

## 2. 规则对比

### A. Baseline 规则

- `is_grounded = confidence >= 0.75`

### B. Rule-aware 规则

- direct factual extraction（直接事实提取）：
- 若命中 `direct_supported`，则可通过独立分支接受（即使低于 0.75）。
- 否则仍走 baseline。
- derived / aggregated claims（推断/聚合型 claim）：
- 保持严格规则，不放宽，仍走 baseline 分支。

## 3. direct / derived 分类逻辑

- 优先读取 review 表（`claim_review_backfill_v2.csv`）中的 `root_cause_primary`：
- 若为 `requires_manual_semantic_review`，判为 derived / aggregated。
- 否则结合 section 兜底：
- `valuation` / `risks` / `business_overview` 视为 derived / aggregated；
- 其余默认 direct factual extraction。

## 4. direct_supported 判定逻辑

- `high_trust_source`：证据中至少一条 `trust_level=high`。
- `direct_literal_alignment`：claim 文本可找到 numeric_values 的字面数字。
- `numeric_consistent_with_evidence`：证据文本可找到相同 numeric_values。
- 满足三者时：`direct_supported=True`。

## 5. 运行方式

在项目根目录执行：

```bash
python scripts/run_grounding_rule_experiment_v1.py
```

如需显式指定输入：

```bash
python scripts/run_grounding_rule_experiment_v1.py \
  --claim-table data/evaluation/eval_v1/runs/AAPL/2025Q4/bm25_real_writer/outputs/claim_table.json \
  --review-csv data/evaluation/eval_v1/runs/AAPL/2025Q4/bm25_real_writer/reports/claim_review_backfill_v2.csv \
  --manifest-json data/evaluation/eval_v1/runs/AAPL/2025Q4/bm25_real_writer/curated/real_data_manifest.json \
  --output-dir artifacts/grounding_rule_experiment_v1
```

## 6. 产物

- `artifacts/grounding_rule_experiment_v1/summary.json`
- `artifacts/grounding_rule_experiment_v1/summary.md`
- `artifacts/grounding_rule_experiment_v1/per_claim.csv`
- `artifacts/grounding_rule_experiment_v1/evidence_lookup.csv`

## 7. 注意事项

- 当前实验支持路径/字段轻度不一致时自适配（优先按仓库现有产物定位），不改主流程。
- 结论需结合样本覆盖范围解读，单样本结果不可直接外推为全量结论。
