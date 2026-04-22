# Review 覆盖扩展 v1 总结

## 覆盖现状

- 总 case 数: 15
- 可评估 case 数: 1
- 缺 review 的 case 数: 14
- 缺 claim_table 的 case 数: 0
- 当前覆盖率: 0.0667

## 审核队列规模

- 待审 claim 总数: 140
- P0: 42
- P1: 56
- P2: 42
- direct factual: 98
- derived/aggregated: 42

## 建议审核顺序

- 第一优先级（P0）：direct factual 且 confidence < 0.75 的条目，优先识别阈值误杀。
- 第二优先级（P1）：derived 低置信度条目与 direct 边界条目（约 0.75/0.76）。
- 第三优先级（P2）：其余常规抽检条目。

## 审核口径提示

- direct factual：重点核对高信任证据是否直接支撑、数字是否一致。
- derived/aggregated：重点做语义和口径复核，不应直接复用 direct 放宽规则。

## 产物路径

- case_inventory.csv: H:\cord\DeepReport_plus\artifacts\review_coverage_expansion_v1\case_inventory.csv
- review_queue.csv: H:\cord\DeepReport_plus\artifacts\review_coverage_expansion_v1\review_queue.csv
- review_template.csv: H:\cord\DeepReport_plus\artifacts\review_coverage_expansion_v1\review_template.csv
- coverage_summary.json: H:\cord\DeepReport_plus\artifacts\review_coverage_expansion_v1\coverage_summary.json
- coverage_summary.md: H:\cord\DeepReport_plus\artifacts\review_coverage_expansion_v1\coverage_summary.md
