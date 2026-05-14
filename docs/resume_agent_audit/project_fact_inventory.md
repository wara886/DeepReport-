# Open DeepReport++ 项目事实盘点

审计对象：当前仓库中的“金融 Deep Report / Open DeepReport++ 多 Agent 金融研报生成系统”。

审计结论先说：这个项目可以写成“公司/个股研报生成的多 Agent workflow 原型”，优势在证据治理、结构化财务计算、验证返工和工具化输出；不能写成“完整覆盖宏观/行业/公司三类研报的生产级金融研究平台”，也不能把 MCP-style HTTP 服务包装成正式 MCP 协议本体。

## 已真实实现

### 主流程与入口

- CLI 入口：`scripts/run_multi_agent_demo.py` 调用 `src/agents/multi_agent_orchestrator.py::MultiAgentOrchestrator`，支持 `dynamic/static` 两种执行模式、`--fast`、搜索引擎列表和检索排序模式。
- Web UI：`src/app/web_ui.py` 使用 `ThreadingHTTPServer` 提供本地工作台，`/api/run` 会触发完整 orchestrator，`/api/latest` 读取最新产物。
- MCP-style HTTP 服务：`src/utils/mcp_http_server.py` 提供 `/mcp/manifest`、`/mcp/rpc`，支持 `initialize`、`tools/list`、`tools/call`，返回 `inputSchema`、`content`、`structuredContent`。
- 多 Agent orchestrator：`MultiAgentOrchestrator` 维护 run-level state、依赖执行、trace、产物落盘、Verifier 返工循环和模型路由信息。
- 报告产物：动态链路落盘 `task_plan.json`、`task_trace.jsonl`、`search_meta.json`、`evidence.json`、`claims.json`、`citations.json`、`charts.json`、`verification_report.json`、`revision_history.json`、`report.md/html/json` 等。

### Agent 角色与职责

- `PlanningAgent`：通过 LLM JSON plan 或 fallback plan 生成任务图，任务类型覆盖 research/browser/analyze/final/verifier。
- `DeepResearcherAgent`：使用 `SearchManager` 聚合本地真实数据、本地 evidence、SEC、Yahoo、Tavily/Serper 等搜索；可选 ReAct 工具循环调用本地 evidence 和 Yahoo snapshot。
- `BrowserAgent`：把 search candidates 规范化为 citation-ready evidence records；支持 Jina Reader、可选 Playwright、PDF 读取和 LLM key point 抽取。
- `DeepAnalyzeAgent`：调用财务比率、三表视图、同行比较、估值工具，生成带 evidence_id 的 claims；支持可选 ReAct 工具调用和 LLM claim merge。
- `RiskAgent`：基于非经常项、估值 gap、资本开支、金融行业特征和证据关键词生成风险 claim。
- `PeerComparisonAgent`：按行业/标的选择 peer group，美股优先 SEC CompanyFacts，离线时回退本地 peer data；A 股白酒有本地 peer universe。
- `FinalAnswerAgent`：基于 claims/evidence 生成中文 Markdown/HTML/JSON，并对空章节做 claim backfill；支持 verifier revision request。
- `VerifierAgent`：规则校验 + 可选 LLM judge，检查章节、引用、标的一致性、primary source、图表/表格/估值一致性，并生成 `revision_brief`。
- 辅助模块：`CitationManager`、`ChartGenerator`、`ComplianceDisclosure`、`ContextPacker`、`ConversationMemory`、`ToolRegistry`、`MCPManager` 都有代码实现并接入主链。

### 数据与证据层

- SEC CompanyFacts：`src/data/sec_companyfacts.py` 从 SEC ticker mapping 和 companyfacts API 抽取收入、利润、现金流、资产负债、权益、EPS、非经常项等，转成 evidence record。
- Yahoo Finance：`src/data/yahoo_finance.py` 调用 keyless chart endpoint，生成 market snapshot evidence，包含 latest close、previous close、区间涨跌幅、市值和 shares outstanding 等字段。
- 本地 evidence store：`src/retrieval/evidence_store.py` 读取 curated parquet；`src/retrieval/retrieve.py` 支持 BM25、vector、hybrid、reranker、hybrid_rerank；`src/retrieval/chunking.py` 支持 paragraph/table/metric chunk。
- 搜索聚合：`src/search/search_manager.py` 注册 `local_real_data`、`china_finance`、`yahoo_finance`、`sec_companyfacts`、`serper`、`tavily`、`metaso`、`sogou`、`local_evidence`。
- A/H 股来源发现：`src/data/china_finance.py` 可识别 A 股、港股代码，返回巨潮、交易所、港交所披露易、东方财富/同花顺等 evidence-like source candidates。
- Source authority：`src/data/source_authority.py` 对 official/company official/market/newswire/media/web source 分级，限制不同来源可支撑的 claim 类型。
- Schema：`src/schemas/evidence.py`、`claim.py`、`report.py`、`task.py` 定义 EvidenceItem、ClaimItem、ReportDocument、ReportTask 等契约。

### 结构化金融分析

- 三表摘要：`src/features/financial_statements.py` 从 financial evidence 构建 income statement、cash flow statement、balance sheet rows，并标记 estimated rows。
- 财务比率：`src/features/financial_ratios.py` 从 metadata 或文本抽取 revenue、growth、margin、ROE/ROA、OCF、FCF 等。
- 趋势分析：`src/features/trend_analysis.py` 生成 evidence coverage、source count、latest publish time 等偏证据覆盖的趋势特征。
- 估值模型：`src/features/company_valuation.py` 实现 P/E、P/S、DCF；对金融行业使用 P/B、DDM、P/E 的组合，并保留假设、DCF 明细、敏感性和 sanity audit。
- 敏感性分析：估值模块输出 `valuation_sensitivity`，`src/evaluation/valuation_audit.py` 校验方向和公式。
- 风险识别：`RiskAgent` 与 `src/features/risk_signals.py` 支持风险关键词、非经常项、估值 gap、行业风险提示。
- 同业比较：`src/features/company_valuation.py::build_peer_comparison` 和 `PeerComparisonAgent` 支持本地 peer 表和 SEC peer fetch。

### 可观测性与产物

- `task_trace.jsonl` 记录 agent、model、task、status、metadata、duration_sec。
- `conversation_context.json` 记录 run scope、working/evidence/reflection/domain memory，以及压缩后的 `context_brief`。
- `revision_history.json` 记录 Verifier 失败后的 FinalAnswer 返工轮次、revision request、模型路由、返工后是否通过。
- `company_report_scorecard.json` 汇总 source authority、numeric lineage、multimodal consistency、valuation reproducibility、gap resolution。
- `chart_consistency.json` 和 `multimodal_consistency.json` 校验图表、表格、claims、evidence 的 lineage。

### Eval / QA / 质量校验

- 规则 Verifier 检查 required headers、company-report sections、空章节、标的一致性、evidence ids 是否存在且在 markdown 中引用、核心 financial claims 是否有 primary source、图表支持、估值公式。
- `src/evaluation/numeric_audit.py` 支持 claim 数字与 gold numeric facts 的匹配和错误类型统计。
- `src/evaluation/eval_v1.py` 定义 eval case schema，包含 query、task type、source scope、gold claims、gold evidence ids、gold numeric facts。
- `src/evaluation/company_report_scorecard.py` 提供公司研报质量 scorecard，但分数是内部回归信号，不等同人工研报质量分。
- 测试覆盖多 Agent workflow、MCP server、tool registry、context packer、conversation memory、source authority、A 股路径、QA fixes 等。
- `docs/Open_DeepReport_financial_report_QA.md` 记录了项目从 pipeline 到 multi-agent 的构建过程、赛题对标、当前边界和 QA 结论。

## 部分实现

- 多 Agent：代码上有多个专职 agent、任务图、state merge、trace 和 rework loop；但整体是 orchestrated workflow，不是完全自治的去中心化多 agent 群聊，也没有复杂协商协议。
- ReAct 工具调用：`DeepResearcherAgent` 和 `DeepAnalyzeAgent` 有 ReAct loop，可让模型选择工具；但很多关键路径仍有规则 fallback，并非所有 agent 都依赖 ReAct。
- Memory：有 run-level conversation/task state、context packing、evidence persistence 和 verifier reflection；没有跨会话长期向量记忆、用户画像记忆或生产级 memory lifecycle。
- A/H 股支持：有 symbol normalize、官方/市场来源发现、本地 A 股白酒样例数据、A 股 peer/risk/valuation 路径测试；但尚无稳定的巨潮 PDF/交易所公告正文结构化抽取和大规模 A 股财务解析。
- 行业/宏观研报：文档承认赛题包含这些方向，但当前主链是公司/个股研报；行业和宏观没有独立数据链、模板、指标体系和 eval。
- Browser：支持 Jina Reader、可选 Playwright、PDF 读取；但真实复杂网页/PDF 表格抽取、OCR、多模态输入理解仍是初级能力。
- Eval：有 schema、规则检查、scorecard、numeric/valuation/multimodal audits 和 QA 文档；但缺少稳定公开 benchmark、大样本指标、人工标注集和可复现的横向对比结论。
- 本地 RAG：有 BM25/vector/hybrid/reranker fallback；Chroma/sentence-transformers 依赖缺失时会退化，不能写成稳定生产级向量检索平台。

## 文档提到但代码支撑不足

- “完整三类研报覆盖”：代码和 QA 都显示当前只完整落地公司/个股研报，行业/宏观不应写成已实现。
- “正式 MCP 协议服务”：当前是 HTTP/JSON-RPC 的 MCP-style 工具边界，没有使用正式 MCP SDK/完整协议能力。
- “生产部署”：有 CLI、Web UI、本地 HTTP 服务，但没有 Docker/部署编排/权限/审计/监控/多租户能力。
- “正式开源模型替换和训练落地”：仓库有 reranker/verifier/rewriter 训练占位和 checkpoint 文件，但主链使用 ModelAdapter 配置 DeepSeek/OpenAI-compatible 后端，不能写成大模型微调已落地到主链。
- “多模态金融研报理解”：有图表生成与一致性校验，但没有 PDF 图像表格深度理解、OCR、图像问答等成熟多模态链路。
- “实时 A 股结构化财报”：本地样例和来源发现存在，真实官方公告/年报结构化抽取不足。

## 当前不应写进简历

- 不应写“覆盖公司、行业、宏观三类金融研报自动生成”。
- 不应写“正式 MCP 协议服务 / 已接入外部 MCP 客户端生态”。
- 不应写“长期 Memory / 个性化记忆 / 跨会话记忆系统”。
- 不应写“完成大模型微调并上线推理服务显著提升效果”，除非后续有真实训练、评测和主链接入证据。
- 不应写“实现生产级 A 股研报生成”，只能写“初步支持 A/H 股代码识别、权威来源发现和本地样例路径”。
- 不应写“准确率提升 X% / 成本下降 X% / 生成速度提升 X%”，仓库没有稳定量化实验支撑。
- 不应写“完全自动事实核验”，当前 Verifier 是规则 + 可选 LLM judge，能发现部分风险，但不能替代人工审阅。
- 不应写“抄 DeepReport 原项目并复用业务逻辑”。更准确说法是“参考 DeepReport 多 Agent 骨架，重写金融公司研报数据、证据、分析、验证和导出链路”。
