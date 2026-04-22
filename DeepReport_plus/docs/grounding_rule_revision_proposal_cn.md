# Grounding 规则修订草案（中文）

## 目标

- 在不改 baseline 默认逻辑的前提下，提出下一步规则修订方向。
- 重点解决：direct extraction 的阈值误杀，以及 derived claims 的规则错配。

## 分层规则提案

### 第一层：Direct Factual Extraction（高信任、直接对齐）

- 适用对象：可被单条或少量高信任证据直接验证的财务/事实 claim。
- 建议判定要素：
- 1) 证据对齐：存在高信任 evidence 且字段可直接对应。
- 2) 数值一致：claim 数值与证据字段一致（允许小容差）。
- 3) 置信度辅助：confidence 作为辅助信号，而非唯一门槛。
- 建议输出：`grounded_direct = True/False`，并记录 `direct_alignment_reason`。

### 第二层：Derived / Aggregated Claims（排名、风险、聚合型）

- 适用对象：排名、风险等级、跨源聚合推断类 claim。
- 建议判定要素：
- 1) 语义约束：明确聚合口径与推断路径。
- 2) 多证据一致性：至少满足最小证据集与来源覆盖。
- 3) 规则边界：与 direct extraction 分开阈值和审核流程。
- 建议输出：`grounded_derived = manual_review_required|provisionally_grounded|not_grounded`。

## 判定流程（草案）

- 第一步：claim 类型判别（direct vs derived）。
- 第二步：按对应层规则判定 grounded。
- 第三步：仅在证据充分时再参考 confidence 辅助排序，不做唯一裁决。

## 对当前 AAPL case 的落地建议（非代码变更）

- `cl_0004 / cl_0005 / cl_0006`：按 direct 规则可判为“被阈值误杀”的已确认样本。
- `cl_0008 / cl_0009 / cl_0010`：保留在 derived 复核池，不提升确定性等级。
- `cl_0003 / cl_0007`：作为边界脆弱样本进入 boundary review 清单。

## 约束声明

- 本文件为规则修订草案，不改变当前 baseline 默认阈值，不触碰 retrieval / writer。
