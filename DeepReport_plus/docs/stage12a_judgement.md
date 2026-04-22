# Stage 12A Judgement (Post Local Baseline Optimization)

## Executive Summary

本轮优化聚焦两条本地瓶颈：  
1) 关键财务指标抽检机制；2) real writer backend fallback 率。  
在不改大架构前提下，Stage 12A 已从“评测可跑”推进到“评测可审计”。

## Final Verdict

**PASS**

## Before vs After (Key Deltas)

- 样本数：`1 -> 5`
- 报告数（样本×变体）：`3 -> 15`
- 导出成功率（md/html/json）：`100% -> 100%`
- 多数 claim 含 evidence_ids：`40% -> 100%`
- writer fallback 率（real writer 变体）：`100% -> 0%`
- 数值抽检覆盖（关键指标）：`无机制 -> 75 checks`
- 数值抽检结果：`N/A -> exact_match 100%, mismatch 0%`

## 4-Dimension Scoring (100)

| Dimension | Score | Notes |
|---|---:|---|
| 闭环完成度 (25) | 24 | 5 样本闭环稳定，md/html/json、章节、图表、claim-first 全链路成立。 |
| 事实与数值一致性 (30) | 28 | 关键指标（营收增速/净利率/ROE/ROA/经营现金流）抽检 75/75 exact。 |
| 证据绑定与可验证性 (30) | 24 | evidence_ids 覆盖显著提升；reranker 对比可运行但质量增益仍不明显。 |
| 工程可用性与下一步价值 (15) | 13 | writer fallback 已定位并压降；评测产物支持下一步回归与云端训练决策。 |

**Total: 89 / 100**

## Hard Gates Check

| Gate | Result | Evidence |
|---|---|---|
| >=5 真实样本 | PASS | `AAPL/MSFT/GOOGL/NVDA/TSLA` |
| >=80% 样本成功导出 md+html+json | PASS | 15/15 |
| 每份报告核心章节齐全 | PASS | structure_completeness=1.0 |
| 每份报告大多数 claim 有 evidence_ids | PASS | majority_claim_evidence_rate=1.0 |
| 关键数值无系统性错配 | PASS | numeric_audit mismatch_rate=0.0 |
| reranker 与 baseline 可比较 | PASS | bm25 vs reranker variants present |
| 能指出主瓶颈 | PASS | 当前主瓶颈：检索增强有效性不足（非稳定性问题） |

## Primary Bottleneck

**证据召回不足（准确说：reranker 相对 BM25 的有效增益不足）**

原因：虽然对比已可运行，但 `bm25_vs_reranker` 关键指标几乎同值，说明当前排序增强尚未体现统计意义上的质量提升。

## Recommended Next Stage

**Stage 12C retrieval/reranker ablation**

理由：当前数据与评测框架已具备，最直接的收益在于把检索排序差异真正转化为 evidence 质量差异。

## Not Recommended as Immediate Priority

- **Stage 13A rewriter**（暂不优先）
  - 目前短板不是“文案表达”，而是“检索增强增益不足”。
  - 先做 rewriter 会掩盖证据层问题，不利于证据驱动目标。
