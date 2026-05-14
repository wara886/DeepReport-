# Phase 0 Eval Harness Summary

## 目标

Phase 0 已建立可重复的 baseline / eval harness，用于在后续 Prompt、Tool、Agent、Router 或 workflow 架构改动后，与当前 workflow 做同口径对比。

## 交付内容

### 1. 固定 eval case 格式

新增目录：

```text
eval/
  cases/
  baselines/
  outputs/
```

新增文件：

- `eval/cases/case_schema.json`
- `eval/cases/phase0_smoke_cases.jsonl`
- `eval/baselines/baseline_registry.json`
- `src/eval/schema.py`

Case schema 至少包含并校验：

- `case_id`
- `symbol`
- `market`
- `period`
- `topic`
- `report_type`
- `required_sections`
- `required_source_types`
- `difficulty`
- `tags`

### 2. Baseline runner

新增：

- `scripts/run_eval_baseline.py`

支持 baseline：

- `baseline_0_single_prompt`
  - 单 prompt 直写报告。
  - 依赖 `configs/model_backends.yaml` 中的模型配置。
  - 无可用模型或 API key 时会显式失败，不伪造成功。
- `baseline_1_single_rag`
  - 当前为 adapter stub。
  - 输出 `not_implemented` 和失败原因，保留未来 single-agent RAG 接入点。
- `baseline_2_current_workflow`
  - 调用现有 `MultiAgentOrchestrator`。
  - 作为 Phase 0 固化的当前 workflow baseline。

示例：

```bash
python scripts/run_eval_baseline.py \
  --baseline baseline_2_current_workflow \
  --cases eval/cases/phase0_smoke_cases.jsonl \
  --run-id phase0_current_workflow
```

### 3. Metrics 框架

新增：

- `src/eval/metrics.py`
- `src/eval/evaluator.py`

已实现基础指标：

- `task_completion_rate`
- `required_sections_coverage`
- `artifact_generation_pass`
- `verification_pass`
- `claim_count`
- `evidence_count`
- `citation_count`
- `total_latency_sec`

已预留但未假装完成的指标：

- `citation_support_rate`
- `numeric_audit_pass_rate`
- `valuation_sanity_pass_rate`

这些指标当前在 per-case metrics 中输出为 `null`，并附带 `unsupported_metric_todos`；直接调用对应函数会抛出 `NotImplementedError`。

### 4. 统一 eval 输出

新增统一输出目录：

```text
eval_outputs/<run_id>/
  eval_summary.json
  per_case_metrics.jsonl
  baseline_comparison.json
  failure_cases.jsonl
```

`baseline_comparison.json` 当前支持单 baseline 汇总，后续可扩展为多 baseline delta 对比。

## 验证结果

### 单元测试

已新增：

- `tests/test_phase0_eval_schema.py`
- `tests/test_phase0_eval_metrics.py`
- `tests/test_phase0_evaluator.py`

执行结果：

```text
PYTHONPATH=/Users/yuan_dian/AI_project/DeepReport_plus python -m pytest \
  /Users/yuan_dian/AI_project/DeepReport_plus/tests/test_phase0_eval_schema.py \
  /Users/yuan_dian/AI_project/DeepReport_plus/tests/test_phase0_eval_metrics.py \
  /Users/yuan_dian/AI_project/DeepReport_plus/tests/test_phase0_evaluator.py

15 passed in 0.01s
```

### Runner smoke

已验证单 case 输出：

```bash
python scripts/run_eval_baseline.py \
  --baseline baseline_1_single_rag \
  --cases eval/cases/phase0_smoke_cases.jsonl \
  --max-cases 1 \
  --run-id phase0_stub_smoke
```

已验证多 case 批量输出：

```bash
python scripts/run_eval_baseline.py \
  --baseline baseline_1_single_rag \
  --cases eval/cases/phase0_smoke_cases.jsonl \
  --run-id phase0_stub_batch
```

生成输出：

- `eval_outputs/phase0_stub_smoke/`
- `eval_outputs/phase0_stub_batch/`

这两个 smoke run 使用的是 `baseline_1_single_rag` stub，目的是验证 harness 输出结构、单 case 路径和多 case 批量路径，而不是声明 RAG baseline 已完成。

## 自查

### 是否影响现有主流程

未修改现有 `src/evaluation/`、`MultiAgentOrchestrator`、报告生成、检索或主业务 pipeline。Phase 0 新增的是独立 `src/eval/` 包和 `scripts/run_eval_baseline.py`，对现有主流程无侵入。

### 是否能单 case 跑通

可以。已通过 `--max-cases 1` 生成 `eval_outputs/phase0_stub_smoke/` 标准输出。

### 是否能多 case 批量跑

可以。已用 `eval/cases/phase0_smoke_cases.jsonl` 两条 case 生成 `eval_outputs/phase0_stub_batch/` 标准输出。

### 是否有可复现输出

可以。通过显式 `--run-id` 固定输出目录；每次运行都会生成同名 run 下的四个标准文件。

## 后续建议

1. 用可用模型配置运行一次 `baseline_2_current_workflow`，将结果作为正式 `baseline_2_current_workflow` 锚点。
2. 接入真正的 `baseline_1_single_rag` adapter 后，再开始写 baseline 提升百分比。
3. 在 Phase 1 后把 GapRouter 指标接入 `baseline_comparison.json`，形成 current workflow vs enhanced workflow 的首个真实 delta。
