# Grounding 规则实验 v1 总结

## 样本范围

- 当前样本仅包含 AAPL 单 case（结论仅对当前样本成立，不外推泛化）。

## 问题 1：哪些条目从误杀变成通过

- 由误杀转通过（false_negative_to_pass）: ['cl_0004', 'cl_0005', 'cl_0006']

## 问题 2：direct factual claims 的 grounded rate 提升多少

- baseline: 0.5714
- rule-aware: 1.0
- 提升（delta）: 0.4286

## 问题 3：derived claims 是否保持稳定

- derived 变动条目数: 0
- derived 变动条目: []

## 问题 4：是否出现明显假阳性风险

- 判断: 未见明显假阳性风险：新增通过条目均落在人审确认的阈值误杀集合内。
- 可疑新增通过条目: []

## 问题 5：当前是否足以进入更大范围灰度

- 结论: False
- 原因: 当前仅覆盖 AAPL 单 case，样本范围不足，不建议直接进入大范围灰度。

## 风险与局限

- 当前仅为单样本离线实验，不能代表跨行业、跨时期稳定性。
- direct_supported 仍依赖字面对齐与数字匹配，未覆盖复杂语义等价表达。
- derived/aggregated 分支仍偏保守，需要后续人工语义规则细化。
