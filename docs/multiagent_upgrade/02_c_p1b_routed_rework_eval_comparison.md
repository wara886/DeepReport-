# P1-B Routed Rework Eval Comparison

## 目标

本次评测在进入 Phase 3 DynamicRouter 前，单独量化 P1-B rule-based routed rework execution 的收益，避免后续 Phase 3 改动后无法区分收益来源。

对比对象：

| Run | 说明 |
|---|---|
| `baseline_2_current_workflow_anchor` | P0-B 固化的旧 workflow anchor |
| `baseline_3_gaprouter_routed_rework` | 当前代码版本，包含 P1-B routed rework execution |

## Case 文件

两次 run 使用完全相同 case 文件：

```text
eval/cases/phase0_workflow_anchor_cases.jsonl
```

Case 列表：

1. `anchor_nvda_us_tech_latest_quarter`：NVDA，美股科技；
2. `anchor_jpm_us_financial_latest_quarter`：JPM，美股金融；
3. `anchor_600519_cn_consumer_latest`：600519.SS，A 股消费；
4. `anchor_meta_hard_post_earnings_capex`：META hard case。

## 实际运行命令

先在 eval runner 中增加独立 baseline id：

```text
baseline_3_gaprouter_routed_rework
```

它复用当前主 workflow 代码路径，但以独立 baseline id 输出，避免覆盖旧 anchor。

执行命令：

```text
cd /Users/yuan_dian/AI_project/DeepReport_plus && PYTHONPATH=. python scripts/run_eval_baseline.py \
  --baseline baseline_3_gaprouter_routed_rework \
  --cases eval/cases/phase0_workflow_anchor_cases.jsonl \
  --output-root eval_outputs \
  --run-id baseline_3_gaprouter_routed_rework \
  --execution-mode dynamic \
  --fast \
  --search-engines local_real_data,local_evidence \
  --retrieval-ranking-mode hybrid_rerank
```

输出目录：

```text
eval_outputs/baseline_3_gaprouter_routed_rework/
```

已生成：

- `eval_outputs/baseline_3_gaprouter_routed_rework/eval_summary.json`
- `eval_outputs/baseline_3_gaprouter_routed_rework/per_case_metrics.jsonl`
- `eval_outputs/baseline_3_gaprouter_routed_rework/failure_cases.jsonl`
- `eval_outputs/baseline_3_gaprouter_routed_rework/baseline_comparison.json`
- `eval_outputs/baseline_3_gaprouter_routed_rework/delta_vs_baseline_2_anchor.json`

Delta 生成命令：

```text
cd /Users/yuan_dian/AI_project/DeepReport_plus && python scripts/compare_p1b_routed_rework_eval.py
```

## 指标对比

| Metric | baseline_2_current_workflow_anchor | baseline_3_gaprouter_routed_rework | Delta | 结论 |
|---|---:|---:|---:|---|
| `task_completion_rate` | 0.0000 | 0.0000 | 0.0000 | 无改善 |
| `required_sections_coverage` | 0.5714 | 0.5357 | -0.0357 | 下降 |
| `artifact_generation_pass_rate` | 1.0000 | 1.0000 | 0.0000 | 持平 |
| `verification_pass_rate` | 0.0000 | 0.0000 | 0.0000 | 无改善 |
| `gap_detection_count_mean` | 4.7500 | 5.0000 | +0.2500 | gap 暴露略增，不等于质量改善 |
| `gap_resolution_rate_mean` | 0.0000 | 0.0000 | 0.0000 | 无改善 |
| `task_resolution_rate_mean` | 0.4698 | 0.5488 | +0.0790 | 过程执行状态改善 |
| `total_latency_sec_mean` | 138.0531 | 169.7446 | +31.6915 | latency 明显增长 |
| `claim_count_mean` | 4.7500 | 4.7500 | 0.0000 | 持平 |
| `evidence_count_mean` | 2.2500 | 2.2500 | 0.0000 | 持平 |
| `citation_count_mean` | 1.2500 | 2.7500 | +1.5000 | 改善 |

## Failure cases

P1-B run 中 4 个 case 仍全部进入 `failure_cases.jsonl`，但 status 都是 `completed`，不是流程崩溃。

| case_id | reasons | required_sections_coverage |
|---|---|---:|
| `anchor_nvda_us_tech_latest_quarter` | `required_sections_incomplete`, `verification_failed` | 0.4286 |
| `anchor_jpm_us_financial_latest_quarter` | `required_sections_incomplete`, `verification_failed` | 0.5714 |
| `anchor_600519_cn_consumer_latest` | `required_sections_incomplete`, `verification_failed` | 0.5714 |
| `anchor_meta_hard_post_earnings_capex` | `required_sections_incomplete`, `verification_failed` | 0.5714 |

与旧 anchor 相比，NVDA 的 section coverage 从 0.5714 降到 0.4286，其余 case 持平。

## P1-B routed rework 是否相较旧 workflow 有改善？

结论：**有局部过程改善，但没有形成最终质量改善。**

改善点：

1. `citation_count_mean` 从 1.25 提升到 2.75，说明 routed rework 后引用数量增加；
2. `task_resolution_rate_mean` 从 0.4698 提升到 0.5488，说明 TaskBoard 中更多 routed / rework task 被执行到 resolved 状态；
3. `message_count_mean` 从 23.75 提升到 33.0，虽然不是用户指定核心 delta 指标，但说明 P1-B 确实产生了更多可观测协作事件；
4. artifact 生成率保持 1.0，没有破坏主流程产物输出。

未改善点：

1. `task_completion_rate` 仍为 0.0；
2. `verification_pass_rate` 仍为 0.0；
3. `gap_resolution_rate_mean` 仍为 0.0；
4. `claim_count_mean` 持平；
5. `evidence_count_mean` 持平；
6. `required_sections_coverage` 反而从 0.5714 降到 0.5357。

因此，P1-B 的独立收益目前主要体现在“过程可执行 / 可观测”和“citation 数量增加”，还没有转化为 Verifier 认可的报告质量提升。

## 是否带来明显 latency 增长？

是。

`total_latency_sec_mean`：

```text
138.0531 -> 169.7446
```

Delta：

```text
+31.6915 sec / +22.96%
```

这属于明显增长。原因很直接：P1-B 在原 unified FinalAnswer rework 前增加了 routed rework agent execution，因此每个有 gap 的 case 会多执行若干 agent task 和 message/taskboard 更新。

## 如果效果不明显，可能原因是什么？

1. **P1-B 仍是 rule-based minimal execution**  
   它只根据 gap type 选择一个 owner 执行，不具备 Phase 3 的动态任务规划、依赖调整、预算控制或逐 gap 终止策略。

2. **routed execution 后没有逐 gap closure judge**  
   当前 `rework_trace.resolved` 仍依赖整体 verifier recheck。即使某个 routed agent 执行了任务，也不会被逐 gap 判定为 resolved。

3. **证据与 claim 数没有提升**  
   `evidence_count_mean` 和 `claim_count_mean` 都持平，说明 routed rework 没有实质增加可用 evidence / claims，只增加了部分 citations。

4. **Final report structure 仍是瓶颈**  
   `required_sections_coverage` 未提升，NVDA 甚至下降，说明 routed rework 没有稳定改善 Writer 对 required sections 的覆盖。

5. **Verifier gate 仍然更严格**  
   `verification_pass_rate = 0.0`，说明新增 routed execution 没有解决 Verifier 关注的核心问题，例如缺 evidence、section 缺失、格式/引用不匹配。

6. **unsupported gap 仍 fallback**  
   `VALUATION_GAP`、`COMPLIANCE_GAP`、`SYMBOL_PERIOD_MISMATCH`、`SOURCE_CONFLICT` 等仍未进入真实专用 execution，因此相关问题不会被 targeted repair。

## Phase 3 DynamicRouter 应优先针对哪些薄弱点设计？

Phase 3 不应只把现有 rule-based route 包一层动态调度，而应优先解决以下问题：

1. **逐 gap closure**  
   为每个 gap 建立 `open -> routed -> executed -> verified_resolved / still_open` 的闭环，而不是只看整体 verifier pass。

2. **Evidence/claim 实质增量判断**  
   routed rework 后应检查 evidence_count、claim_count、claim-evidence coverage 是否真的增加；如果没有增量，应停止重复执行或换 route。

3. **Writer section coverage control**  
   `FORMAT_GAP` 和 required section 缺失应生成强约束 writer task，确保 required sections 全覆盖，而不是泛化 rewrite。

4. **Valuation / compliance / symbol-period routes 可执行化**  
   当前这些 gap 仍 fallback，是 Phase 3 应优先补齐的 executable owners。

5. **Budget / latency-aware routing**  
   P1-B 平均 latency 增长约 23%，Phase 3 需要按 gap severity、expected benefit、remaining budget 决定是否执行 route。

6. **TaskBoard 从记录状态升级为调度依据**  
   当前 TaskBoard 主要记录 task 状态。Phase 3 应让 TaskBoard 参与 ready task selection、dependency updates、blocked reason handling。

7. **Citation repair 专用路径**  
   citation_count 虽提升，但 verification 未过，说明 CitationManager 需要成为真实执行 owner，处理 claim-citation alignment，而不是只补 evidence。

## 总结

```text
P1-B routed rework 相对 baseline_2 有局部过程改善：citation_count 和 task_resolution_rate 提升。
但核心质量指标未改善：task_completion_rate、verification_pass_rate、gap_resolution_rate 仍为 0。
同时 latency 明显增加约 31.7 秒 / 23%。
```

因此，P1-B 的价值主要是证明 routed execution 基础设施可运行、可观测，而不是证明报告质量已经提升。Phase 3 应以“逐 gap 闭环 + 动态调度 + 可执行 owner 补齐 + latency budget”为重点。
