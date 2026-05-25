# Phase 2R: Quick-9 修复评测记录

## 范围

- 日期：2026-05-24。
- 仅评测当前 `multi_agent` 路线，不实现 `Direct LLM` 或 `Single-Agent RAG`。
- 仍使用运行时可访问的数据源，不是冻结 evidence snapshot 上的公平对照。
- `Traceable Claim Rate (artifact-derived)` 仍是现有 artifacts 的初版统计，不是正式 `v1`。

## 修复内容

- 校正 benchmark 的确定性交付口径：Delivery 只计算公司身份、摘要、风险、投资结论、正文引用、三表或显式缺口、估值或不可用原因、严重图文冲突八项要求。
- 客观质量 blocker 与关键结论可追溯缺口仍保留为独立诊断，不再重复决定 Delivery 指标。
- 区分 `pre_write_critic` 未执行与执行失败；修复评测使用 `diagnostic_full` 真实执行写前质疑。
- 修正 GapResolver 的逐表缺失识别和现金流表键名，并接入已有的一轮 delivery rework。
- 港股路线加入 `hkex_announcements`；A 股修复配置移除本次重复失败且非关键财务来源的冗余 `eastmoney` 行情调用。

## 结果

| 指标 | 原记录值 | 按修正合同重算原产物 | 修复后重跑 | 实际修复变化 |
| --- | ---: | ---: | ---: | ---: |
| Delivery Pass Rate | `0.0000` | `1.0000` | `1.0000` | `0.0000` |
| Objective Quality Score | `94.84` | `94.84` | `95.86` | `+1.02` |
| Traceable Claim Rate (artifact-derived) | `0.9777` | `0.9777` | `0.8591` | `-0.1186` |

修复后分市场结果：

| Metric | Overall | US | HK | CN-A |
| --- | ---: | ---: | ---: | ---: |
| Delivery Pass Rate | `1.0000` | `1.0000` | `1.0000` | `1.0000` |
| Objective Quality Score | `95.86` | `96.70` | `91.03` | `99.84` |
| Traceable Claim Rate (artifact-derived) | `0.8591` | `1.0000` | `0.6444` | `0.9328` |

## 解读边界

- 原始 Delivery `0%` 在同一原产物上重算后已为 `100%`，因此不能把它描述成系统质量修复带来的提升。
- Phase 2R 真正观察到的质量变化是 Objective Quality Score 增加 `1.02`，同时初版可追溯率下降 `11.86` 个百分点。
- 港股来源路线已实际尝试：`6682.HK` 在返工阶段取得 4 条匹配 HKEX 结果；`0020.HK` 与 `0700.HK` 未取得匹配结果。港股可追溯率是进入 Phase 3 前仍需处理的首要风险。
- 修复后通过 Delivery 不等于达到 formal benchmark 标准；仍有 `citation_or_evidence_gap` 与 `quality_gate_blocker` 诊断存在。

## 产物与命令

- 配置：`configs/benchmark_quick9_multi_agent_repair.yaml`
- 汇总：`eval_outputs/benchmark_quick9_multi_agent_repair/benchmark_report.md`
- 前后对照：`eval_outputs/benchmark_quick9_multi_agent_repair/repair_comparison.md`
- 运行命令：

```powershell
python scripts/run_quick9_multi_agent_benchmark.py --config configs/benchmark_quick9_multi_agent_repair.yaml --output-root eval_outputs/benchmark_quick9_multi_agent_repair
```

## Phase 3 门槛

本轮停止在 Phase 2R。进入 Phase 3 前仍需明确接受港股引用覆盖风险，随后再建设冻结 FY2024 snapshot、三种 variant 与显式标注的 `Traceable Claim Rate v1`。
