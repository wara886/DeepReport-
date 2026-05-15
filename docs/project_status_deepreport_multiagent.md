# DeepReport++ 金融多智能体项目状态

更新日期：2026-05-15

## 当前结论

DeepReport++ 当前主线是金融多智能体研报系统的质量闭环、durable memory 证明、SkillRegistry 接入，以及天池三类研报交付准备。

当前事实来源以这些文件和产物为准：

- `docs/current_status.md`
- `docs/fixed.md`
- `docs/financial_deepreport_multiagent_upgrade_spec.md`
- `eval_outputs/codex_phase5b_qwen3_after_format_fix/eval_summary.json`
- `eval_outputs/codex_phase5c_memory_smoke_after_fix/eval_summary.json`

旧 Stage12 文档、重复总结和历史审计类文档已归档到 `docs/archive/2026-05-15/`，不再作为当前计划依据。

## 最新评估事实

### Phase 5B 本地 qwen3 canary

产物：`eval_outputs/codex_phase5b_qwen3_after_format_fix/eval_summary.json`

- 本地模型：Ollama `qwen3:8b`
- case：JPM 与 600519.SS valuation-gap cases
- `task_completion_rate=1.0`
- `required_sections_coverage=1.0`
- `verification_pass_rate=1.0`
- `citation_support_rate=1.0`
- `numeric_audit_pass_rate=0.9373`
- `valuation_sanity_pass_rate=1.0`
- `unsupported_gap_fallback_count_sum=0`
- `failure_cases.jsonl` 为空

说明：重跑命令触发外层 shell timeout，但 `eval_summary.json`、`per_case_metrics.jsonl` 和空 failure file 已完整落盘，按产物判断该轮完成且通过。

### 本轮修复

- `FinalAnswerAgent` 增加确定性章节补齐：当 claim 存在但本地模型漏写或改写章节标题时，自动插入对应公司研报章节，并再次做 heading normalization。
- 图表 lineage 放宽 claim-text 派生图表：能追到 `input_claim_ids` 即可通过 multimodal lineage；证据缺口仍由 citation/evidence audit 负责。
- NumericAudit 已支持合法 0 值 count 类指标，例如 `core_peer_count=0`。
- 关键单元测试已通过：Phase 5B audits、memory loader、memory ablation、SkillRegistry、Priority1 metric fixes、最终报告章节补齐。

### Phase 5C memory ablation smoke

产物：`eval_outputs/codex_phase5c_memory_ablation_after_format_fix_smoke/memory_ablation_comparison.json`

- 范围：1-case 本地 qwen3 enabled/disabled smoke。
- 两个 variant 都完成产物落盘，但 `verification_pass_rate=0.0`，不能标记为 memory promotion 完成。
- memory enabled 相比 disabled 的信号：`numeric_audit_pass_rate` 从 `0.5714` 提升到 `0.8889`，`citation_support_rate=1.0`，且 `unsupported_gap_fallback_count_sum=0`。
- 风险：memory enabled 延迟更高，且 LLM verifier 仍给出估值引用、重复章节、期间不一致等错误。
- 当前判断：memory 有质量信号，但还需要完整 2-case ablation 与 verifier 稳定性修复后再接入 Planner/Router 策略。

### Phase 5C full memory ablation

产物：`eval_outputs/codex_phase5c_memory_ablation_after_format_fix/memory_ablation_comparison.json`

- 范围：2-case 本地 qwen3 enabled/disabled ablation。
- 结论：`decision=memory_has_measurable_benefit`。
- memory enabled：`verification_pass_rate=1.0`、`task_completion_rate=1.0`、`numeric_audit_pass_rate=0.9217`、`citation_support_rate=1.0`、`unsupported_gap_fallback_count_sum=0`。
- memory disabled：`verification_pass_rate=0.5`、`task_completion_rate=0.5`、`numeric_audit_pass_rate=0.8889`、`citation_support_rate=1.0`、`unsupported_gap_fallback_count_sum=0`。
- delta：verification +0.5、task completion +0.5、numeric audit +0.0328；代价是平均延迟约 +31.5 秒。
- 当前判断：memory 可以进入下一轮 Planner/Router context selection，但必须保留 latency 和 quality guard。

## 已具备能力

- RequestUnderstandingAgent、PlanningAgent、DeepResearcherAgent、BrowserAgent、DeepAnalyzeAgent、RiskAgent、PeerComparisonAgent、ValuationAgent、AdjudicatorAgent、FinalAnswerAgent、VerifierAgent、IndustryResearchAgent、MacroResearchAgent 已具备最小链路能力。
- DynamicRouter、BudgetGuard、TaskBoard、AgentMessage、Blackboard 已输出可审计 artifacts。
- durable memory 已写入 `memory/working/<run_id>/`、`memory/episodic/`、`memory/domain/`。
- `scripts/run_memory_ablation.py` 已可做 memory enabled/disabled 对照。
- SkillRegistry MVP 已包含四个 roadmap skills：`valuation_method_selection`、`numeric_consistency_audit`、`citation_support_audit`、`gap_routing`。

## 当前风险

1. Memory 已有写入、读取和 ablation runner；完整 2-case ablation 已证明质量收益，但延迟更高，接入 Planner/Router 时需要 guard。
2. SkillRegistry 仍是静态 MVP，尚未动态注入 Planner/Router。
3. 天池三类报告能生成不等于质量交付完成；仍需重跑 `scripts/run_competition.py` 并检查 company/industry/macro docx、`results.zip` 和质量门禁。
4. qwen3 本地 canary 已通过，但端到端比赛 run 仍可能受检索质量、公开来源稀疏和模型耗时影响。

## 下一步执行顺序

### P0：Memory 证明

1. 将 memory brief 选择性接入 Planner/Router context selection。
2. 保留 verification、numeric audit、unsupported fallback、latency guard。
3. 接入后重跑同一组 ablation，确认收益没有退化。

### P1：SkillRegistry 接入

1. 保持静态 registry 测试通过。
2. 让 Planner/Router 选择性读取 skill 摘要。
3. 增加 eval-visible 指标，确认没有增加 unsupported fallback。

### P2：天池交付闭环

1. 使用 `configs/model_backends_local.yaml` 重跑三类报告。
2. 检查三份 `.docx`、`results.zip`、run summary、verification、multimodal consistency。
3. 若公司报告或图文一致性失败，先修质量，不标记交付完成。

## 常用命令

```powershell
python -m pytest tests/test_phase5b_audits.py tests/test_memory_loader.py tests/test_memory_ablation.py tests/test_skill_registry.py tests/test_priority1_metric_fixes.py -q

python scripts/run_eval_baseline.py --baseline baseline_5_adjudicator_source_conflict --cases eval/cases/phase5a_valuation_gap_cases.jsonl --run-id codex_phase5b_qwen3_after_format_fix --execution-mode dynamic_multiagent --fast

python scripts/run_memory_ablation.py --run-id codex_phase5c_memory_ablation_after_format_fix

python scripts/run_competition.py --config configs/model_backends_local.yaml --output-dir eval_outputs/competition_local_open_model --fast
```
