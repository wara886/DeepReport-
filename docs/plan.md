# 通用上市公司研报 Agent 交付计划

## Summary

本轮目标升级为：不再为 600519、AMD、腾讯等单个公司写本地特判补丁，而是建设“任意上市公司可尝试生成高质量研报”的通用链路。核心路径是：通用公司识别 → 免费实时数据源路由 → 多 Agent 协作 trace → 缺口修复 Agent → delivery gate 返工 → 前端 Chat UI 可见化 → 每个功能独立 commit。

执行纪律：

- 每个功能一个 commit。
- 每个 commit 后更新项目状态文档。
- 不把 memory 当事实来源。
- 不把某家公司名称写死为质量补丁。
- 所有补齐逻辑必须基于市场、行业、报告类型、数据源能力和质量 gate，而不是 symbol 特判。

## Key Changes

### 1. 通用公司识别与数据源路由

把当前“少量 fallback 公司宇宙 + 部分市场引擎选择”升级为通用上市公司解析层。

实现目标：

- 输入可以是：
  - 中文公司名
  - 英文公司名
  - ticker
  - A 股代码
  - 港股代码
  - 美股 ticker
- 输出统一 `CompanyIdentity`：
  - `symbol`
  - `canonical_symbol`
  - `company_name`
  - `market`
  - `exchange`
  - `currency`
  - `country_region`
  - `is_listed`
  - `resolution_confidence`
  - `data_source_plan`
- 不再依赖“本地写死某家公司该怎么补”。
- 对无法确认上市身份的公司，要求 Chat UI 先确认，不直接生成研报。

数据源路由规则：

- A 股：
  - 巨潮资讯
  - 交易所公告
  - 东方财富财务表
  - 东方财富行情
  - Yahoo Finance 作为行情补充
- 港股：
  - Yahoo Finance
  - 港交所/公司公告入口若可免费访问则作为公告源
  - Tavily/Serper 搜索作为公开网页补充
- 美股：
  - SEC EDGAR companyfacts
  - SEC filings
  - Yahoo Finance
  - company IR / public news search
- 其他市场：
  - Yahoo Finance 优先
  - 搜索引擎补充
  - 若三表不可得，必须写清缺口和来源尝试。

### 2. 去除公司级硬编码补齐

清理 `DeepAnalyzeAgent`、`FinalAnswerAgent`、quality remediation 中类似 `if symbol == "AMD"` 的公司特判。

替换为通用规则：

- 根据市场判断披露来源。
- 根据行业分类选择分析模板：
  - 消费
  - 科技
  - 金融
  - 医药
  - 制造
  - 周期
  - 平台互联网
  - 半导体
  - 其他
- 根据可得数据生成必备章节：
  - 业务画像
  - 三表摘要
  - 财务质量
  - 股权结构/治理
  - 同行对比
  - 估值
  - 敏感性
  - 风险
  - 投资结论
- 如果行业分类不确定，使用通用公司研报模板，不输出伪行业结论。

### 3. 多 Agent 协作可见化

新增 `agent_collaboration_trace.json`。

记录：

- 每个 Agent 的任务、输入、输出。
- 上下游 handoff。
- 使用了哪些工具。
- 使用了哪些 memory。
- 哪些质量问题触发了返工。
- 哪些缺口仍未解决。

保留现有 `task_trace.jsonl`，新增 trace 作为前端展示和评审说明。

### 4. Tool Trace

新增或统一 `tool_trace.json`。

覆盖：

- deterministic tool call
- ReAct tool call
- search engine call
- data source adapter call
- chart generation
- valuation calculation
- table extraction

每条记录包含：

- `caller_agent`
- `tool_name`
- `input_summary`
- `output_summary`
- `success`
- `failure_reason`
- `evidence_ids`
- `artifact_paths`

### 5. GapResolver / DataRepairAgent

新增通用缺口修复 Agent。

职责：

- 发现三表缺失。
- 发现 artifacts 有三表但正文没写。
- 发现估值缺数据。
- 发现同行对比为空。
- 发现敏感性分析只有框架。
- 发现股权结构/治理信息缺失。
- 发现 PDF/公告有信息但正文没消费。
- 发现数据源失败并生成替代查询。

输出：

- `gap_resolution_trace.json`
- `data_repair_summary.json`
- 修复后的 `financial_metrics.json`
- 修复后的 `tables.json`
- 修复后的 claims
- 给 Writer 的 `required_backfill_sections`

该 Agent 不能写公司特判，只能根据报告类型、市场、行业、数据源和 quality issue 类型行动。

### 6. Delivery Gate 返工闭环

当前问题是质量不合格后通常只产出 remediation plan，不一定同轮返工。本轮改为：

- 报告生成后运行：
  - verifier
  - objective evaluator
  - LLM review
  - delivery gate
- 若 `delivery_pass=false`：
  - 生成 remediation plan。
  - 调用 GapResolver/DataRepairAgent。
  - 再调用 FinalAnswerAgent 重写或 hard backfill。
  - 再跑 verifier/objective/LLM review/delivery gate。
- 最多 2 轮返工。
- 每轮记录：
  - `revision_history.json`
  - `agent_collaboration_trace.json`
  - `quality_remediation_plan.json`

### 7. FinalAnswer 通用高质量写作约束

FinalAnswerAgent 必须消费：

- claims
- evidence
- tables
- financial_metrics
- company_profile
- peer_context
- valuation
- sensitivity
- PDF/filing-derived claims
- quality_remediation_plan
- gap repair constraints

正文必须包含：

- 执行摘要
- 主营业务与行业地位
- 三表财务分析
- 财务比率与质量判断
- 股权结构与治理
- 同行对比
- 估值模型
- 敏感性分析
- 风险提示
- 投资建议
- 合规披露与数据来源说明

若数据不可得，必须写：

- 缺什么。
- 尝试了哪些免费公开来源。
- 为什么不能确认。
- 对投资判断有什么影响。

禁止输出：

- 大量“暂无结论”
- 空泛“持续关注”
- 无来源方向性判断
- 只有框架没有实质分析的估值/同行/敏感性章节

### 8. Objective Quality Evaluator 升级

质量门禁从“样本特化”升级为“通用研报交付门禁”。

新增规则：

- 三表缺失且无原因：fail。
- 三表在 artifacts 里但正文没写：fail。
- 估值缺失且无原因：fail。
- 同行对比只有框架：fail。
- 敏感性分析没有变量或方向：fail。
- 投资结论没有方向和理由：fail。
- 引用不足：fail 或 warning，按严重程度区分。
- 内容空洞比例过高：blocker。
- 不是上市公司或无法确认上市身份：blocker。
- 使用 memory 当事实来源：blocker。
- 免费公开来源尝试不足：warning/blocker。

### 9. 前端 Chat UI 修复

针对当前截图中的问题，前端需要改成真正的工作台，而不是大空白首屏。

修复方向：

- 首屏不再过度 hero 化，改为 ChatGPT-like 但更紧凑。
- 输入框固定在底部或主工作区，不占据巨大空白。
- “Ready”和“输出路径”合并成状态条。
- 报告生成中显示 Agent Timeline。
- 普通聊天和研报任务状态分开。
- 最近输出、质量门禁、报告链接、trace 入口要更醒目。
- 移动端避免输入框、状态栏、按钮挤压。
- 修复 mojibake 文案，所有中文 UI 使用 UTF-8 正常文本。
- 质量 tab 增加：
  - delivery pass
  - top blockers
  - repaired issues
  - remaining issues
- 新增“多智能体协作”tab：
  - Agent Timeline
  - Tool Trace
  - Memory Used
  - Rework Rounds

### 10. 三类研报竞赛要求对齐

公司/个股作为当前主链优先补强，同时为行业/宏观留接口。

公司/个股：

- 通用上市公司解析。
- 三大会计报表。
- 股权结构。
- 主营业务。
- 核心竞争力。
- 行业地位。
- 财务比率。
- 同行对比。
- 估值与预测。
- 敏感性分析。
- 投资建议与风险。

行业/子行业：

- 保留现有 IndustryResearchAgent。
- 增加后续接口，不在本轮深扩。
- 本轮只确保 UI 和任务路由能识别行业报告请求，并给出能力边界。

宏观/策略：

- 保留现有 MacroResearchAgent。
- 本轮只确保 UI 和任务路由能识别宏观报告请求，并给出能力边界。

## Commit Plan

### Commit 1：通用公司身份解析与数据源计划

- 新增或扩展 `CompanyIdentity`。
- 统一 A 股/港股/美股/其他市场识别。
- 生成 `data_source_plan`。
- 测试中文名、英文名、ticker、港股代码、A 股代码。

### Commit 2：去除公司级硬编码补齐

- 清理 AMD/600519 等 symbol 特判。
- 改为行业/市场/数据源驱动模板。
- 加测试确保新增任意 symbol 不需要写新 if 分支。

### Commit 3：Agent Collaboration Trace

- 新增 `agent_collaboration_trace.json`。
- 汇总 task trace、handoff、memory、tools、rework。
- `/api/latest` 返回该 artifact。

### Commit 4：Tool Trace

- 记录 analyzer/search/data/tool/chart/valuation 调用。
- 前端和 run summary 暴露 top tool calls。

### Commit 5：GapResolver/DataRepairAgent

- 新增缺口修复 Agent。
- 支持三表、估值、同行、敏感性、股权结构、PDF 消费缺口。
- 输出 `gap_resolution_trace.json` 和 repair constraints。

### Commit 6：Delivery Gate Rework Loop

- delivery fail 后进入同轮返工。
- 最多 2 轮。
- 返工后重跑三层质量门禁。

### Commit 7：FinalAnswer 通用正文 backfill

- 强制消费 gap repair constraints。
- 强制补公司研报必备章节。
- 不可得数据必须写原因和影响。

### Commit 8：Objective Evaluator 通用质量门禁

- 增加空洞、三表正文、估值、同行、敏感性、投资结论、上市身份、来源尝试规则。
- 补单测。

### Commit 9：Chat UI 修复

- 重做首屏布局。
- 增加多智能体协作 tab。
- 增加 tool trace / rework / quality blockers 展示。
- 修复中文 mojibake。

### Commit 10：Chat UI + 任意公司 Smoke

- 普通聊天 smoke。
- 腾讯 2025 年财报 smoke。
- A 股样本 smoke。
- 美股样本 smoke。
- 一个非预置上市公司 smoke。
- 一个无法确认上市公司身份的确认流程 smoke。

### Commit 11：文档和竞赛对齐说明

- 更新项目状态文档。
- 增加“多 Agent 相比普通 workflow 的优势与证据”说明。
- 增加“当前距离竞赛要求的差距”说明。
- 记录剩余行业/宏观扩展项。

## Test Plan

基础测试：

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py
```

多 Agent 测试：

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_multi_agent_workflow.py tests/test_react_tool_loop.py
```

质量测试：

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_report_quality.py tests/test_delivery_gate.py tests/test_quality_remediation.py
```

数据源测试：

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_search_and_research_agent.py
```

Chat UI smoke：

```powershell
python scripts/run_chat_ui_smoke.py
```

验收样本：

- `生成2025年腾讯的财报`
- `生成贵州茅台最新财报研报`
- `生成 AMD 最新财报研报`
- `生成 苹果公司 2025 年财报研报`
- `生成 一个未预置但可由 Yahoo/SEC/搜索识别的上市公司财报研报`
- `生成 某个非上市公司财报研报`

## Acceptance Criteria

公司/个股研报：

- 任意上市公司请求不能依赖本地 symbol 特判。
- 系统必须给出数据源尝试路径。
- 三表可得时必须进入正文。
- 三表不可得时必须写清来源尝试和影响。
- objective quality 不能因空洞正文虚高通过。
- delivery fail 必须触发返工或明确不可修复阻塞。
- 前端能看见多 Agent、工具、memory、返工和质量问题。

Chat UI：

- 普通聊天不触发报告。
- 研报请求自动解析 symbol / period / report_type。
- 生成中有清晰状态。
- 生成后有报告链接、质量结果、Agent Timeline、Tool Trace。
- 首屏布局不再大面积空白。
- 中文无乱码。

竞赛技术点：

- 多 Agent 分工可见。
- RAG / 免费公开数据源调用可见。
- 工具调用可见。
- memory 使用边界可见。
- 自检与反馈循环可见。
- MCP/A2A 相关能力至少有工程接口和 trace 说明。

## Assumptions

- 本轮仍以公司/个股研报质量为主，行业/宏观先做路由和展示边界，不深扩完整数据模型。
- 不接入付费第三方整理数据 API。
- 可使用免费公开网络数据源、交易所/公告、SEC、Yahoo Finance、东方财富、巨潮、公开新闻搜索。
- 若 API key 缺失，必须记录 `missing_api_key`，不能假装数据可用。
- 每个 commit 都独立提交 git，并在状态文档记录改动、验证命令、质量结果和剩余问题。
