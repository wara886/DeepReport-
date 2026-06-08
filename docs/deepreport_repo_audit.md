# DeepReport 仓库审计

审计对象：`references/DeepReport_ref/`

## 1. 仓库真实目录结构

参考仓库是一个偏轻量的 Python 应用骨架，核心结构如下：

- `main.py`：Gradio 主入口，负责装配 agent、search、report 和 UI。
- `config.py`：环境变量驱动的配置入口，包含 API key、模型、输出目录、浏览器参数等。
- `src/agents/`：agent 编排与子 agent 实现。
- `src/search/`：搜索引擎封装与搜索管理。
- `src/report/`：HTML 报告、图表、引用管理。
- `src/utils/`：模型适配、MCP 管理等通用工具。
- `docs/en/` 与 `docs/zh/`：双语文档。
- `docker-compose.yml`、`Dockerfile`、`start.sh`：容器化与本地启动入口。

仓库没有明显的“data pipeline / schema / evaluation / training”分层，说明它更像一个能快速运行的研报生成原型，而不是完整的可训练工程平台。

## 2. 主入口

主入口是 `main.py`。

这个入口完成了：

- Gradio 应用初始化
- `PlanningAgent`、`DeepResearcherAgent`、`BrowserAgent`、`DeepAnalyzeAgent`、`FinalAnswerAgent` 组装
- 搜索管理器和 MCP 管理器初始化
- 报告生成器初始化
- 研究任务执行与 HTML 报告导出

从骨架角度看，`main.py` 是“单入口调度器 + UI 入口”的典型实现，适合作为我们 Stage 0 里 `src/app/main.py` 和 `src/app/pipeline.py` 的参考模板。

## 3. 配置入口

配置入口是 `config.py`，通过环境变量驱动。

特点：

- 使用 `BaseSettings`
- 将 OpenAI、Anthropic、搜索 API、MCP、浏览器、报告输出目录集中管理
- 提供 `get_model_config()` 之类的派生配置函数

这说明它的工程思路是“代码里少写硬编码，多靠环境变量”，这一点可以保留，但需要改造成我们目标中的 YAML 配置体系。

## 4. agent / 工具 / 搜索 / 报告模块位置

### Agent

- `src/agents/planning_agent.py`
- `src/agents/deep_researcher_agent.py`
- `src/agents/browser_agent.py`
- `src/agents/deep_analyze_agent.py`
- `src/agents/final_answer_agent.py`
- `src/agents/sub_agents.py`
- `src/agents/base_agent.py`

### 搜索

- `src/search/search_manager.py`
- `src/search/engines.py`

### 报告

- `src/report/html_generator.py`
- `src/report/chart_generator.py`
- `src/report/citation_manager.py`

### 工具与适配

- `src/utils/model_adapter.py`
- `src/utils/mcp_manager.py`

这些模块切分方式比较清楚，适合借鉴为我们自己的 `agents / retrieval / report / generation / utils` 分层。

## 5. 可直接借鉴的工程骨架

可保留或部分保留的结构：

- `main.py` 的“入口聚合器”思路
- `config.py` 的集中配置管理模式
- `src/agents/` 的多 agent 职责切分
- `src/search/` 的搜索引擎抽象
- `src/report/` 的图表、引用、HTML 导出分层
- `docker-compose.yml` 的容器化启动方式
- `docs/en`、`docs/zh` 的文档分层

## 6. 明显与目标不一致的部分

以下内容与 `Open DeepReport++` 的目标差异较大，不能直接照搬：

- 现有入口是“Gradio + 单次问答式生成”，不是“claim-first、可验证、可训练增强”的报告流水线。
- 配置入口依赖 `.env` 和 Pydantic Settings，和我们要求的 `configs/*.yaml` 不一致。
- 缺少 `schemas / data / features / retrieval / training / evaluation` 这些可持续扩展层。
- 没有明确的 `mock / local_small / remote / finetuned` generation backend 抽象。
- 没有离线训练数据导出路径。
- 报告导出层更偏展示型，缺少我们需要的证据绑定、规则 verifier、质量门、回归测试链路。

## 7. 结论

DeepReport 的骨架可以复用，但复用范围应限定为：

- 目录组织的分层思路
- 多 agent 编排方式
- 搜索 / 报告 / 工具模块的职责切分
- 容器化和本地启动入口

对于研报系统的核心业务逻辑、schema、claim-first 流水线、质量门、训练导出链路，应按 `Open DeepReport++` 目标重写。
