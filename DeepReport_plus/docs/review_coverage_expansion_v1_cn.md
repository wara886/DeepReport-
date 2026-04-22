# review_coverage_expansion_v1 说明

## 目标

- 在不修改 baseline 默认逻辑、不改 retrieval / writer / report 的前提下，
- 识别 `eval_v1` 中 review 覆盖缺口，形成可执行审核队列与回填模板。

## 输入自动扫描范围

- 扫描目录：`data/evaluation/eval_v1/runs`
- 逐 case 检查：
- `outputs/claim_table.json`（是否可抽取 claim）
- `reports/claim_review_backfill_v2.csv` 或 `reports/claim_review_backfill.csv`（是否已有 review）

## 产物说明

- `artifacts/review_coverage_expansion_v1/case_inventory.csv`
- 字段：`company_or_case, period, has_claim_table, has_review_csv, review_version, is_evaluable, missing_components`（并补充 `case_id, variant` 便于追踪）
- `artifacts/review_coverage_expansion_v1/review_queue.csv`
- 面向缺失 review 的 case，输出标准化待审 claim 队列
- `artifacts/review_coverage_expansion_v1/review_template.csv`
- 最小化人工回填模板，便于后续批量录入
- `artifacts/review_coverage_expansion_v1/coverage_summary.json`
- `artifacts/review_coverage_expansion_v1/coverage_summary.md`

## 建议优先审核顺序

- P0：direct factual extraction 且 `confidence < 0.75`
- 目标：优先发现“阈值误杀（false negative due to threshold）”
- P1：derived 低置信度条目 + direct 边界条目（约 `0.75/0.76`）
- 目标：控制语义风险与边界脆弱问题
- P2：其余常规抽检条目

## direct factual 与 derived 审核口径

- direct factual extraction：
- 看证据是否高信任、是否直接对齐、数值是否一致
- derived / aggregated claims：
- 看语义推断链与聚合口径，不应直接套用 direct 的放宽策略

## 运行方式

在项目根目录执行：

```bash
python scripts/run_review_coverage_expansion_v1.py
```

可选参数：

```bash
python scripts/run_review_coverage_expansion_v1.py \
  --eval-runs-dir data/evaluation/eval_v1/runs \
  --output-dir artifacts/review_coverage_expansion_v1
```
