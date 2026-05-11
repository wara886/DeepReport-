# DeepReport 参考骨架

参考仓库：

```text
/Users/yuan_dian/Downloads/deep_learn/DeepReport_award2_ref
https://github.com/wisdom-pan/DeepReport
```

官方中文 README 对 DeepReport 的定位是：AI 驱动的金融研究和报告生成系统，通过 Planning Agent 与多个 Sub-Agent 协作，生成带可视化、引用和数据溯源的综合金融报告。

## 1. 应借鉴的核心骨架

```text
User / UI
  -> PlanningAgent
  -> DeepResearcherAgent
  -> BrowserAgent
  -> DeepAnalyzeAgent
  -> FinalAnswerAgent
  -> Report Generator

SearchManager
MCPManager / Tool Registry
ModelAdapter
```

## 2. 本地参考模块

```text
DeepReport_award2_ref/
├── main.py
├── config.py
├── src/agents/base_agent.py
├── src/agents/planning_agent.py
├── src/agents/deep_researcher_agent.py
├── src/agents/browser_agent.py
├── src/agents/deep_analyze_agent.py
├── src/agents/final_answer_agent.py
├── src/search/search_manager.py
├── src/search/engines.py
├── src/report/html_generator.py
├── src/report/chart_generator.py
├── src/report/citation_manager.py
├── src/utils/model_adapter.py
└── src/utils/mcp_manager.py
```

## 3. 当前仓库的映射方向

| DeepReport 参考模块 | 当前仓库保留组件 | 改造策略 |
| --- | --- | --- |
| `BaseAgent` | 暂无真实基类 | 新增 `src/agents/base_agent.py` |
| `PlanningAgent` | `src/agents/planner.py` | 从固定模板改为 LLM 规划 |
| `DeepResearcherAgent` | `src/retrieval/*`、`src/data/*` | 新增 Agent，复用检索/数据层作为工具 |
| `BrowserAgent` | 暂无 | 新增网页/PDF 抽取 Agent |
| `DeepAnalyzeAgent` | `src/agents/analyst.py`、`src/features/*` | 改成 LLM + finance tools |
| `FinalAnswerAgent` | `src/agents/writer.py`、`src/templates/*` | 改成 LLM writer + exporter |
| `SearchManager` | `src/retrieval/*` | 新增 `src/search/`，接多引擎/金融 API |
| `MCPManager` | 暂无 | 新增 `src/tools/mcp_manager.py` |
| `ModelAdapter` | `src/generation/backend_remote.py` | 新增通用 `src/models/model_adapter.py` |
| `Report Generator` | `src/templates/*`、`src/charts/*` | 保留并被 FinalAnswerAgent 调用 |

## 4. 关键原则

- 不把固定 Python 流水线伪装成多 Agent。
- Agent 需要有独立角色 prompt、模型调用、工具集合和任务输入输出。
- 多个 Agent 可以共享同一个底层模型，但职责和上下文必须分离。
- 现有 `data/features/retrieval/templates/charts` 都应该变成 Agent 可调用工具，而不是由固定 orchestrator 顺序调用。
- 我们自己的金融 API 应优先接入工具层和 SearchManager，而不是散落在 Agent 代码里。

