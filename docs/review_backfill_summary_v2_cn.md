# 回填人审结论摘要 v2（AAPL）

## 范围与约束

- 本轮仅修 review 层，不修改 baseline 默认逻辑。
- 不修改 retrieval 主逻辑，不修改 writer，不改 report 生成逻辑。
- grounded 现行规则仍为：`is_grounded = confidence >= 0.75`。

## 已坐实结论（Confirmed）

- `cl_0004 / cl_0005 / cl_0006` 属于 direct factual extraction（直接事实提取）。
- 三条均已人工确认由高信任证据直接支撑。
- 在现行全局阈值规则下被拒，属于阈值误杀（false negative due to threshold）。
- 该问题同时暴露 grounding 规则过于简化（oversimplified_grounding_rule）。

## 尚未坐实结论（Not Yet Confirmed）

- `cl_0008 / cl_0009 / cl_0010` 为 derived / aggregated claims（推断/聚合型 claim）。
- 当前只可标记为 `requires_manual_semantic_review`，并采用 `keep_separate_rules_for_derived_claims`。
- 这些条目在 v2 中将 `confidence_after_review` 下调为 `medium`，`is_systematic` 下调为 `False`。
- 其最优 grounded 规则尚未坐实，仍需后续人工语义复核。

## 为什么“单纯把阈值改成 0.70”不是最终方案

- 下调全局阈值只能缓解 direct extraction 的一部分误杀，不能区分 claim 类型。
- 对 derived / aggregated claims，单纯降阈值可能引入新的误接收（false positive）。
- 因此最终方案应是分层 grounded 规则（rule-aware grounding），而非单一全局阈值。

## 本轮输出

- review 回填 v2：`data/evaluation/eval_v1/runs/AAPL/2025Q4/bm25_real_writer/reports/claim_review_backfill_v2.csv`
- grounded 规则修订草案：`docs/grounding_rule_revision_proposal_cn.md`
