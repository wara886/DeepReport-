# Grounding 规则实验 v2 批量总结

## 样本覆盖

- 发现 case 数: 15
- 可评估 case 数: 1
- review 输入不足 case 数: 14
- 覆盖率: 0.0667

## direct factual grounded rate 提升

- baseline: 0.5714
- rule-aware: 1.0
- 提升 delta: 0.4286

## derived 稳定性

- derived claim 总数: 3
- derived 变化数: 0
- 稳定率: 1.0

## 潜在假阳性

- 潜在假阳性条目数: 0
- 条目列表: []

## 误杀转通过条目

- false_negative_to_pass: ['AAPL:2025Q4:bm25_real_writer:cl_0004', 'AAPL:2025Q4:bm25_real_writer:cl_0005', 'AAPL:2025Q4:bm25_real_writer:cl_0006']

## 灰度前置条件

- ready: False
- reason: 未满足灰度前置条件：请先补齐 review 数据并扩展多样本验证后再评估灰度。

## 数据完整性提示

- 对缺失 review 输入的 case，本批次统一标记为 insufficient_review_data，并且不输出伪造结论。
- insufficient case 列表: ['AAPL:2025Q4:bm25_template', 'AAPL:2025Q4:reranker_template', 'GOOGL:2025Q4:bm25_real_writer', 'GOOGL:2025Q4:bm25_template', 'GOOGL:2025Q4:reranker_template', 'MSFT:2025Q4:bm25_real_writer', 'MSFT:2025Q4:bm25_template', 'MSFT:2025Q4:reranker_template', 'NVDA:2025Q4:bm25_real_writer', 'NVDA:2025Q4:bm25_template', 'NVDA:2025Q4:reranker_template', 'TSLA:2025Q4:bm25_real_writer', 'TSLA:2025Q4:bm25_template', 'TSLA:2025Q4:reranker_template']

## 风险与局限

- 本批次仍是离线规则实验，不等于线上策略切换。
- 若 review 覆盖不足，汇总结果可能低估或高估真实效果。
- 当前结果依赖现有 review 质量与字段一致性，需持续抽检。
