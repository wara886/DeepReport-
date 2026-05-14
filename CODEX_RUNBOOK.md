# Codex 交接手册 — DeepReport++ 多智能体升级

> 本手册给下一个 Codex / Claude Code 用，说明当前项目状态、关键上下文、下一步做什么。

## 一、项目阶段总览

当前项目已经走过了多智能体升级的 Phase 0-3，Phase 4 代码层面已完成但**评测闭环尚未确认**。不要推进 Phase 5/6/7。

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 0-2 | Eval Harness, GapRouter, TaskBoard | ✅ 完成 |
| Phase 3 | DynamicRouter + BudgetGuard | ✅ 完成 |
| **Phase 4** | Adjudicator + SOURCE_CONFLICT | **⏳ 代码完成，评测未闭环** |
| Phase 5 | Memory（Agent 长期记忆） | ❌ 不要做 |
| Phase 6 | SkillRegistry | ❌ 不要做 |
| Phase 7 | 最终评测 + Ablation | ❌ 不要做 |

## 二、Phase 4 当前状态

### 已完成
- `AdjudicatorAgent` — rule-based 冲突裁决（trust_level + source_type bonus）
- Gap detector `infer_gap_type()` — 识别 SOURCE_CONFLICT
- DynamicRouter — SOURCE_CONFLICT → "adjudicator" 路由
- MultiAgentOrchestrator — run_summary 写入 adjudication 数据
- Eval metrics — 统计 `conflict_resolution_count`, `adjudication_decision_distribution`
- All 41 Phase 4 单元测试通过

### 阻塞项（最优先）
1. **baseline_5 需要重新跑** — 上次跑的时候 Phase 4 修复代码还没生效
2. **验证条件**: `conflict_resolution_count_sum > 0` 或 `adjudication_decision_distribution` 非空
3. **对比 baseline_4**: 确认 verification_pass_rate 和 task_resolution_rate 不退化

### 已知问题
- 1 个测试失败: `test_local_correction_v1.py::test_local_correction_v1_outputs_exist` — 缺少数据模板文件，不影响核心
- `_count_dynamic_dispatches` 缺失函数 — **已修复**
- 43 个文件有未提交变更（含 Phase 4 修复），建议先提交再继续

## 三、关键命令

```bash
# 运行所有测试（在 DeepReport_plus 目录）
PYTHONPATH=. python -m pytest tests/ --tb=short -q

# 只跑 Phase 4 相关测试
PYTHONPATH=. python -m pytest tests/test_phase4_adjudicator.py --tb=short -v

# 跑 baseline_5 评测（1 个 case 快速验证）
PYTHONPATH=. python scripts/run_eval_baseline.py baseline_5_adjudicator_source_conflict --max-cases 1

# 跑完整 baseline_5（4 个 anchor cases，耗时长）
PYTHONPATH=. python scripts/run_eval_baseline.py baseline_5_adjudicator_source_conflict
```

## 四、关键文件

| 文件 | 作用 |
|------|------|
| `src/agents/adjudicator_agent.py` | 冲突裁决逻辑 |
| `src/multiagent/gaps/detector.py` | Gap 检测（含 SOURCE_CONFLICT） |
| `src/multiagent/gaps/schema.py` | GapType 枚举 + GapItem |
| `src/multiagent/router/dynamic_router.py` | 动态路由 |
| `src/agents/multi_agent_orchestrator.py` | 编排器 + run_summary |
| `src/eval/metrics.py` | 评测指标 |
| `scripts/run_eval_baseline.py` | Baseline 定义与执行 |
| `tests/test_phase4_adjudicator.py` | Phase 4 单元测试 |
| `docs/financial_deepreport_multiagent_upgrade_spec.md` | 完整升级路线文档 |

## 五、Memory 系统

项目关键状态已持久化到 `/Users/yuan_dian/.claude/projects/-Users-yuan-dian-AI-project/memory/`，包括：
- 项目阶段状态
- Baseline 评测数据
- 用户画像（偏好、工作风格）
- 反馈记录（动态调整原则）
- 关键文件索引

首次启动 Codex 时，读取 memory 目录即可获得完整上下文。

## 六、下一步建议（按优先级）

1. 提交当前代码变更（git add + commit）
2. 验收 plan → eval/outputs 中检查是否已有最新 run
3. 跑 baseline_5 smoke eval: `--max-cases 1` 验证 SOURCE_CONFLICT case
4. 如果达标: 对比 baseline_4，确认无退化
5. 如果未达标: 分析 router_decisions.jsonl 中 adjudicator 为何没触发
6. 达标后: 定义 baseline_6，考虑推进 Phase 5 Memory

## 七、不要做的事
- 不要直接推进 Phase 5 Memory / Phase 6 SkillRegistry
- 不要创建 baseline_6 直到 Phase 4 闭环被验证
- 不要简单调低 verifier threshold 造假象提升
- 不要修改 AGENTS.md（已过时，属于旧版 Stage 体系）
