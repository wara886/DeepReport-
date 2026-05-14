# 00.5 Request Understanding Layer Summary

## 目标

本次补充了“自然语言研究需求理解层”，使系统可以从工程化输入：

```text
symbol / period / topic / uploaded files
```

逐步升级为最终用户主入口：

```text
用户输入一句真实自然语言研究请求 -> 系统解析 ResearchRequest -> 进入 Planner / 多 Agent 研究流程
```

结构化参数模式仍保留，用于 CLI、Eval 和回归测试；文件上传改为 optional evidence，不再是公开公司研报任务的默认前置条件。

## 新增模块

### Schema

新增：

- `src/request_understanding/schema.py`

核心对象：

- `ResearchRequest`
- `ResolvedEntity`
- `PeriodSpec`
- `OutputPreferences`
- `AttachmentSpec`

字段覆盖：

- `original_query`
- `resolved_entity.company_name`
- `resolved_entity.symbol`
- `resolved_entity.market`
- `resolved_entity.confidence`
- `report_type`
- `period.type`
- `period.explicit_start_date`
- `period.explicit_end_date`
- `period.granularity`
- `focus_areas`
- `output_preferences.language`
- `output_preferences.format`
- `output_preferences.depth`
- `attachments.optional`
- `clarification_needed`
- `clarification_questions`

### Entity Resolution

新增：

- `src/request_understanding/entity_resolver.py`

实现方式：

1. 复用现有 `src/data/company_universe.py` 中的 `resolve_company_identifier_with_diagnostics`。
2. 增加面向自然语言请求的内置别名表，覆盖当前 eval 需要的中英文常见公司名：
   - 英伟达 / NVIDIA -> `NVDA`, US
   - 贵州茅台 -> `600519.SS`, CN-A
   - 招商银行 -> A/H 两地候选，默认触发澄清
   - 腾讯 / 腾讯控股 -> `0700.HK`, HK
   - Apple Inc. / AAPL
3. 支持模糊候选与 confidence 输出。

### RequestUnderstandingAgent

新增：

- `src/agents/request_understanding_agent.py`

职责：

- 从自然语言中抽取研究目标；
- 解析公司实体、市场、股票代码；
- 识别 period 与 report_type；
- 抽取 focus_areas 与 output_preferences；
- 判断是否需要澄清；
- 输出 `ResearchRequest`。

当前实现是 deterministic parser + resolver，便于测试和回归；后续可以在该 Agent 内加入 LLM parser，但输出 contract 不变。

## Orchestrator 接入

已在 `MultiAgentOrchestrator.run()` 增加两种可选入口：

### 1. natural_language_query 模式

```python
orchestrator.run(
    natural_language_query="分析英伟达最近一个季度的经营情况，判断当前估值是否偏贵，并给出主要风险。"
)
```

流程：

```text
natural_language_query
 -> RequestUnderstandingAgent
 -> ResearchRequest
 -> PlannerAgent / 后续多 Agent workflow
```

如果 `clarification_needed = true`，orchestrator 会写出 `request_understanding.json` 并返回：

```json
{"status": "clarification_needed"}
```

不会在无法确认标的时贸然生成研报。

### 2. structured_request 模式

```python
orchestrator.run(
    structured_request={
        "symbol": "NVDA",
        "market": "US",
        "period": "latest_quarter",
        "report_type": "company_research"
    }
)
```

该模式用于 CLI / Eval / 回归测试，直接构造 `ResearchRequest`，不要求自然语言解析。

## Clarification Logic

当前会触发澄清的情况：

- 未解析出上市公司或 ticker；
- 公司存在多个上市市场或候选项，例如“招商银行”A/H 股；
- 公司名存在公司 / 品类歧义，例如“苹果分析”；
- 实体解析置信度过低；
- 时间表达过于模糊且没有季度 / 财年线索。

## Eval

新增：

- `eval/request_understanding/cases.jsonl`
- `src/request_understanding/eval.py`

覆盖 case：

1. 英伟达最新季度研报；
2. 贵州茅台最新深度研报；
3. 招商银行研报，测试 A/H 股歧义；
4. 苹果分析，测试公司 / 品类歧义；
5. 分析腾讯估值，测试港股实体解析。

评估指标：

- `entity_resolution_accuracy`
- `report_type_accuracy`
- `period_parse_accuracy`
- `clarification_precision`
- `clarification_recall`

## 测试

新增：

- `tests/test_request_understanding.py`

验证内容：

- NVDA 自然语言解析；
- 贵州茅台深度研报解析；
- 招商银行 A/H 股歧义澄清；
- 苹果公司 / 品类歧义澄清；
- 腾讯港股估值解析；
- structured_request 兼容 CLI / Eval；
- request understanding eval metrics；
- orchestrator 在歧义请求下返回 clarification，不进入报告生成。

执行结果：

```text
cd /Users/yuan_dian/AI_project/DeepReport_plus && PYTHONPATH=. python -m pytest tests/test_feature_layer.py tests/test_request_understanding.py

22 passed in 0.40s
```

## 对现有主流程影响

- 原有 `run(research_topic=..., symbol=..., period=...)` 仍兼容。
- 新增入口是 optional 参数，不强制改变既有 CLI / Eval 调用方式。
- 文件上传只进入 `attachments.optional`，作为补充证据提示传给 planner requirements。
- 公开公司研报任务不再假设必须先上传文件。

## 后续建议

1. 将 RequestUnderstanding eval 接入 Phase 0 `baseline_comparison.json`，形成入口层独立回归指标。
2. 在 UI 中把 natural language query 设为主输入框，把 symbol / period / upload 收敛到高级选项。
3. 后续引入 LLM parser 时，保持 `ResearchRequest` schema 与 deterministic fallback，避免不可复现。
