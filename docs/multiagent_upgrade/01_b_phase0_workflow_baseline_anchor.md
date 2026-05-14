# P0-B Workflow Baseline Anchor

## 目标

本次收口将当前主流程正式固化为：

```text
baseline_2_current_workflow_anchor
```

输出目录：

```text
eval_outputs/baseline_2_current_workflow_anchor/
```

本次运行发生在进入 Phase 3 之前，用作后续架构改动的真实 workflow baseline。

## 实际运行命令

第一次从父目录执行失败，原因是脚本相对路径不在 `/Users/yuan_dian/AI_project` 下：

```text
PYTHONPATH=. python scripts/run_eval_baseline.py --baseline baseline_2_current_workflow --cases eval/cases/phase0_workflow_anchor_cases.jsonl --output-root eval_outputs --run-id baseline_2_current_workflow_anchor --execution-mode dynamic --fast --search-engines local_real_data,local_evidence --retrieval-ranking-mode hybrid_rerank
```

失败信息：

```text
python: can't open file '/Users/yuan_dian/AI_project/scripts/run_eval_baseline.py': [Errno 2] No such file or directory
```

随后在项目根目录重新执行成功：

```text
cd /Users/yuan_dian/AI_project/DeepReport_plus && PYTHONPATH=. python scripts/run_eval_baseline.py \
  --baseline baseline_2_current_workflow \
  --cases eval/cases/phase0_workflow_anchor_cases.jsonl \
  --output-root eval_outputs \
  --run-id baseline_2_current_workflow_anchor \
  --execution-mode dynamic \
  --fast \
  --search-engines local_real_data,local_evidence \
  --retrieval-ranking-mode hybrid_rerank
```

## Case 列表

Case 文件：

```text
eval/cases/phase0_workflow_anchor_cases.jsonl
```

| case_id | symbol | market | difficulty | 覆盖点 |
|---|---:|---|---|---|
| `anchor_nvda_us_tech_latest_quarter` | `NVDA` | US | normal | 美股科技、经营情况、估值、风险 |
| `anchor_jpm_us_financial_latest_quarter` | `JPM` | US | normal | 美股金融、NII、资产质量、资本充足率 |
| `anchor_600519_cn_consumer_latest` | `600519.SS` | CN-A | normal | A 股消费、盈利质量、估值、行业风险、同业对比 |
| `anchor_meta_hard_post_earnings_capex` | `META` | US | hard | hard case、财报后广告业务、capex、AI 投资回报、估值压力 |

## 输出路径

```text
eval_outputs/baseline_2_current_workflow_anchor/
  eval_summary.json
  per_case_metrics.jsonl
  failure_cases.jsonl
  baseline_comparison.json
  artifacts/
```

四类 required outputs 已生成：

- `eval_outputs/baseline_2_current_workflow_anchor/eval_summary.json`
- `eval_outputs/baseline_2_current_workflow_anchor/per_case_metrics.jsonl`
- `eval_outputs/baseline_2_current_workflow_anchor/failure_cases.jsonl`
- `eval_outputs/baseline_2_current_workflow_anchor/baseline_comparison.json`

每个 case 的 artifacts 下也包含主流程产物，例如：

- `reports/report.md`
- `reports/report.html`
- `reports/report.json`
- `outputs/verification_report.json`
- `outputs/task_trace.jsonl`
- `outputs/task_board.json`
- `outputs/agent_messages.jsonl`
- `outputs/rework_trace.json`

## 指标摘要

来自 `eval_summary.json`：

```json
{
  "case_count": 4,
  "task_completion_rate": 0.0,
  "required_sections_coverage": 0.5714,
  "artifact_generation_pass_rate": 1.0,
  "verification_pass_rate": 0.0,
  "claim_count_mean": 4.75,
  "evidence_count_mean": 2.25,
  "citation_count_mean": 1.25,
  "gap_detection_count_mean": 4.75,
  "gap_resolution_rate_mean": 0.0,
  "message_count_mean": 23.75,
  "task_blocked_count_mean": 0.0,
  "task_resolution_rate_mean": 0.4698,
  "total_latency_sec_sum": 552.2124,
  "total_latency_sec_mean": 138.0531
}
```

## 失败 Case

`failure_cases.jsonl` 中 4 个 case 均记录为失败，但失败类型不是流程崩溃，而是质量门未通过：

| case_id | status | reasons | required_sections_coverage |
|---|---|---|---:|
| `anchor_nvda_us_tech_latest_quarter` | completed | `required_sections_incomplete`, `verification_failed` | 0.5714 |
| `anchor_jpm_us_financial_latest_quarter` | completed | `required_sections_incomplete`, `verification_failed` | 0.5714 |
| `anchor_600519_cn_consumer_latest` | completed | `required_sections_incomplete`, `verification_failed` | 0.5714 |
| `anchor_meta_hard_post_earnings_capex` | completed | `required_sections_incomplete`, `verification_failed` | 0.5714 |

说明：

- `artifact_generation_pass_rate = 1.0`：四个 case 均产出了报告和核心 artifact。
- `verification_pass_rate = 0.0`：Verifier 均未通过。
- `task_completion_rate = 0.0`：当前定义要求 artifact、required sections、verification 三个 gate 全部通过，因此四个 case 均为 0。
- `gap_detection_count_mean = 4.75`：当前 workflow 能检测结构化 gaps，但 gap resolution 尚未有效闭环。

## 当前 Workflow 的真实基线水平

当前 `baseline_2_current_workflow` 的真实 baseline 是：

1. **流程可运行**：4/4 case status 为 `completed`，没有 runner 级异常。
2. **artifact 可生成**：4/4 case 生成 core artifacts。
3. **质量未达验收**：required sections 覆盖均为 0.5714，Verifier 通过率为 0。
4. **gap 可检测但不可闭环**：平均每 case 检测 4.75 个 gap，`gap_resolution_rate_mean = 0.0`。
5. **多智能体过程可观测**：`agent_messages.jsonl`、`task_board.json` 已输出，可作为 Phase 2 process baseline。

因此，此 anchor 是一个真实但偏弱的 workflow baseline，不应被描述为质量达标基线。

## 后续可对比指标

后续 Phase 1-B / Phase 3 及之后可直接与该 anchor 对比：

- `artifact_generation_pass_rate`
- `required_sections_coverage`
- `verification_pass_rate`
- `task_completion_rate`
- `gap_detection_count_mean`
- `gap_resolution_rate_mean`
- `claim_count_mean`
- `evidence_count_mean`
- `citation_count_mean`
- `message_count_mean`
- `task_blocked_count_mean`
- `task_resolution_rate_mean`
- `total_latency_sec_mean`

重点关注：

1. routed rework 是否提升 `gap_resolution_rate_mean`；
2. targeted agent execution 是否提升 `verification_pass_rate`；
3. Planner / Writer 是否提升 `required_sections_coverage`；
4. Process infrastructure 是否降低 blocked task 或提高 task resolution rate；
5. 改进质量时是否显著增加 latency。
