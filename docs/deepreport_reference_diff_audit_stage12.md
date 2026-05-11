# DeepReport 参考实现差分审计（Stage 12 / 只读对照）

审计日期：2026-04-18  
参考仓库：`https://github.com/wisdom-pan/DeepReport.git`  
本地对照目录：`H:\cord\references\DeepReport_ref`  
参考提交：`afc6ee7`

---

## 0. 审计范围与约束

本次仅做“阅读与对照”，未修改本地主流程代码。  
本报告重点回答以下问题：

1. 主链路是否为 query -> planning -> search -> analyze -> report  
2. 公开模块、目录与关键文件  
3. 是否显式实现 verifier / reranker / numeric audit / claim-evidence 对齐  
4. 是否有 来源类型（source_type）与任务类型（task_type）差异处理  
5. 哪些可借、哪些不可借、哪些未公开  
6. 对你当前三类问题的帮助边界

---

## 1. 主链路审计（query -> planning -> search -> analyze -> report）

### 1.1 公开代码里的主运行链路

从 `main.py` 可见主入口为 `DeepReportApp.generate_report()`，链路是：

1. 输入研究主题（query）与需求
2. 调用 规划智能体（Planning Agent）生成任务计划（plan）
3. 按 `task_type` 分发执行：深度研究、浏览器、分析、最终报告
4. 汇总为 `report_data`
5. 交给 HTML 报告生成器输出

对应代码位置：
- `main.py`：`generate_report()`、`_execute_research_plan()`  
- `src/agents/planning_agent.py`：计划生成与 `task_type` 约束  
- `src/agents/deep_researcher_agent.py` / `deep_analyze_agent.py` / `final_answer_agent.py`

### 1.2 与“标准链路”一致性结论

高层流程上，它**近似** query -> planning -> research/analyze -> report。  
但“search”这一步并非单一路径：

- 有 搜索管理器（SearchManager）模块（`src/search/search_manager.py`），支持多引擎并发、去重与打分。  
- 但主链路里 `SearchManager` 初始化后并未在 `generate_report()` 内显式调用；深度研究智能体更多通过 DuckDuckGo + loader 工具链执行。

结论：  
- 逻辑上存在“搜索能力”，  
- 但工程上“App 主链路与 SearchManager 的耦合”并不强，属于可演进骨架而非严格闭环实现。

---

## 2. 公开模块、目录与关键文件

## 2.1 仓库目录树摘要

```text
DeepReport_ref/
  main.py
  config.py
  requirements.txt
  Dockerfile
  docker-compose.yml
  src/
    agents/
      base_agent.py
      planning_agent.py
      deep_researcher_agent.py
      browser_agent.py
      deep_analyze_agent.py
      final_answer_agent.py
      sub_agents.py
    search/
      search_manager.py
      engines.py
    report/
      html_generator.py
      chart_generator.py
      citation_manager.py
    utils/
      model_adapter.py
      mcp_manager.py
  docs/
  examples/
```

## 2.2 关键文件清单（按链路）

1. 入口与编排
- `main.py`

2. 任务分解与执行
- `src/agents/planning_agent.py`
- `src/agents/base_agent.py`
- `src/agents/deep_researcher_agent.py`
- `src/agents/deep_analyze_agent.py`
- `src/agents/final_answer_agent.py`
- `src/agents/browser_agent.py`

3. 搜索能力
- `src/search/search_manager.py`
- `src/search/engines.py`

4. 报告输出
- `src/report/html_generator.py`
- `src/report/chart_generator.py`
- `src/report/citation_manager.py`

5. 配置与运行
- `config.py`
- `docker-compose.yml`
- `Dockerfile`

---

## 3. 四项能力显式性审计

### 3.1 验证器（verifier）

结论：**未看到独立、显式的 verifier 模块**。  

现有“质量相关”能力主要是：
- 最终报告智能体内的质量评估工具（更偏报告完整性/结构检查）
- 不是 claim 级别、证据级别的验证器

### 3.2 重排器（reranker）

结论：**未看到显式 reranker 训练/推理模块**。  

现有排序主要是：
- `SearchManager` 的启发式相关性打分（位置、来源、关键词）
- 不属于神经 reranker 体系

### 3.3 数字审计（numeric audit）

结论：**未看到独立 numeric audit 管线**。  

现有分析里有数值统计与估值工具，但没有：
- “report 数字 claim 对齐 gold fact”的审计器  
- 错误类型分桶（value/unit/period/...）的标准产物

### 3.4 Claim-证据对齐（claim-evidence alignment）

结论：**未看到显式 claim table + evidence_id 对齐契约**。  

公开实现更偏“生成报告内容 + 引用展示”，而非：
- claim 结构化对象
- 每个 claim 的证据 ID 绑定
- 可回归的 grounded rate 口径

---

## 4. 来源类型与任务类型差异处理

### 4.1 来源类型（source_type）

有一定实现，但偏“检索/标注层”：
- `deep_researcher_agent.py` 的 `SourceDiscoveryTool` 参数里有 `source_type`
- `engines.py` / `search_manager.py` 的结果字段中有 `source`

不足：
- 缺少和“验证/评测口径”强绑定的来源策略
- 缺少你当前所需的 evidence-hit 回归体系

### 4.2 任务类型（task_type）

有显式实现：
- `planning_agent.py` 要求 `task_type` 在 `deep_researcher/browser_use/deep_analyze/final_answer` 之一
- `main.py` 按 `task_type` 分发执行

不足：
- `task_type` 更多用于执行路由，不是评测分层（例如按 task_type 诊断指标漂移）

---

## 5. 三列表：可借鉴 / 不可借鉴 / 尚未公开

| 分类 | 项目 | 审计结论 |
|---|---|---|
| 可借鉴 | 规划智能体（Planning Agent）+ 子智能体拆分 | 可借“角色分工”，不直接拷贝实现 |
| 可借鉴 | 搜索管理器（SearchManager）抽象边界 | 可借“manager + engines”分层 |
| 可借鉴 | 报告层分离（HTML/图表/引用） | 可借“report/chart/citation”解耦思路 |
| 可借鉴 | 任务类型（task_type）驱动调度 | 可借“调度骨架” |
| 不可借鉴 | 将质量评估等同于 verifier | 你需要 claim 级验证，不可混用 |
| 不可借鉴 | 启发式搜索排序代替 reranker | 与你当前 reranker 目标不一致 |
| 不可借鉴 | 仅凭报告引用视为 claim-evidence 对齐 | 无法支撑 grounded rate 回归 |
| 不可借鉴 | 直接并入 baseline 分支 | 会污染你当前 Stage 12 评测口径 |
| 尚未公开 | 明确的 verifier 训练与推理链路 | 公共仓库未见 |
| 尚未公开 | 标准化 numeric audit 数据契约 | 公共仓库未见 |
| 尚未公开 | claim-evidence 对齐数据结构与评测工具 | 公共仓库未见 |

---

## 6. 对你当前三类问题的帮助边界

你当前问题：

1. 验证阈值（verifier_checkpoint.threshold）偏严  
2. Top1 证据命中率（top1_evidence_hit_rate）为 0  
3. 近邻数字碰撞（nearest_number_collision）

### 6.1 验证阈值偏严

可提供帮助：
- 参考其“质量评估工具拆分方式”，用于组织离线诊断脚本结构

不能提供帮助：
- 该仓库没有公开的 verifier 判定链路与阈值扫描基线  
- 不能直接给出可复用阈值策略

### 6.2 Top1 命中率为 0

可提供帮助：
- `SearchManager` 的来源打分思路可借来做“诊断对比特征”  
- 可作为离线解释信号（source 权重、position 权重）

不能提供帮助：
- 无 reranker 模型与回归基准  
- 无 evidence-hit 指标体系，无法直接解决 top1 命中问题

### 6.3 近邻数字碰撞

可提供帮助：
- 提供“分析工具模块化”的组织方式（将数字分析拆工具）

不能提供帮助：
- 无 numeric audit 误差分类与 claim-gold 对齐标准  
- 不能直接消除你当前 `nearest_number_collision`

---

## 7. 针对当前项目的下一步建议（不改主流程版本）

以下建议仅面向“只读对照后的诊断增强”，不改默认主流程行为：

1. 保持你现有 Stage 12 baseline 评测口径不变，继续用独立目录输出诊断 run。  
2. 借鉴 DeepReport 的“模块边界”，但把验证与数字审计继续留在你现有 `evaluation/diagnostics` 体系中。  
3. 对 Top1 问题只做离线解释增强：补“来源类型（source_type）权重影响”与“位置分布”对照表。  
4. 对阈值问题只做离线扫描，不写回默认 `verifier_checkpoint.threshold`。  
5. 对数字问题继续沿你现有根因细分口径推进人工回填，避免引入参考仓库的宽泛分析逻辑污染回归指标。

---

## 8. 结论

公开 DeepReport 是一个“多智能体金融报告系统骨架”，适合作为结构参考；  
但在你当前 Stage 12 的核心诉求（Claim 支撑率（claim_grounded_rate）、数字准确率（numeric_accuracy）、证据命中回归）上，它**不能直接提供可替代实现**。  

建议继续坚持你当前“评测闭环优先”的路线，把参考仓库的价值限定在模块边界与工程组织层，不混入 baseline 代码路径。

