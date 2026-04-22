# Grounding 规则实验 v2 批量版（grounding_rule_experiment_v2_batch）说明

## 1. 目标与约束

- 目标：在 `eval_v1` 多 case 范围内，批量评估 rule-aware grounded 判定相对 baseline 的收益与风险。
- 约束：
- 不修改 baseline 默认逻辑。
- 不修改 retrieval / writer / report。
- 不覆盖默认配置。
- 仅新增独立实验脚手架和实验产物。

## 2. 输入自动发现

- 扫描目录：`data/evaluation/eval_v1/runs/*/*/*/outputs/claim_table.json`。
- 每个 case 自动匹配：
- `claim_table.json`
- `curated/real_data_manifest.json`
- review CSV（优先 `claim_review_backfill_v2.csv`，其次 `claim_review_backfill.csv`）
- 若缺失 review CSV，则该 case 标记为 `insufficient_review_data`，并禁止输出伪造结论。

## 3. 规则口径（复用 v1）

- baseline：`is_grounded = confidence >= 0.75`
- rule-aware：
- direct factual extraction：`baseline OR direct_supported`
- derived / aggregated claims：保持 baseline 严格分支，不放宽

`direct_supported` 定义：

- 高信任来源（high trust source）
- claim 字面对齐（direct literal alignment）
- 与证据数值一致（numeric consistent with evidence）

## 4. 产物

- `artifacts/grounding_rule_experiment_v2_batch/batch_summary.json`
- `artifacts/grounding_rule_experiment_v2_batch/batch_summary.md`
- `artifacts/grounding_rule_experiment_v2_batch/per_case_summary.csv`
- `artifacts/grounding_rule_experiment_v2_batch/per_claim_all.csv`

## 5. 关键统计项

- direct factual grounded rate（baseline vs rule-aware）与提升值
- derived stability（变化数与稳定率）
- 潜在假阳性（potential false positive）标记与条目列表
- case 覆盖数（discovered/sufficient/insufficient）
- 是否满足灰度前置条件（precondition for canary）

## 6. 运行方式

在项目根目录执行：

```bash
python scripts/run_grounding_rule_experiment_v2_batch.py
```

可选指定目录：

```bash
python scripts/run_grounding_rule_experiment_v2_batch.py \
  --eval-runs-dir data/evaluation/eval_v1/runs \
  --output-dir artifacts/grounding_rule_experiment_v2_batch
```

## 7. 解释注意点

- 若 `insufficient_review_data` 较多，batch 汇总结论仅代表可评估子集，不应直接外推全量 case。
- v2 仍是离线实验层，不等于生产规则切换；上线前需要补齐 review 覆盖与抽检闭环。
