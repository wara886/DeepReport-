金融 Deep Report / Open DeepReport++ 多 Agent 金融研报生成系统

- 【多 Agent 研报工作流与任务编排】围绕公司/个股研报场景，将“检索、网页/正文抽取、财务分析、风险识别、同业比较、撰写、验证”拆成 PlanningAgent、DeepResearcherAgent、BrowserAgent、DeepAnalyzeAgent、RiskAgent、PeerComparisonAgent、FinalAnswerAgent、VerifierAgent 等角色，并由 orchestrator 维护任务依赖、共享 state、trace 与返工轮次；相比单轮 Prompt 生成，系统能够把信息不足、财务口径错误、引用缺失和报告结构问题拆开处理，形成可追踪的研报生成闭环。

- 【证据治理与引用可信链路建设】设计并落地 Evidence / Claim / Citation 数据契约，将 SEC CompanyFacts、Yahoo Finance、本地 evidence store、Tavily/Serper 搜索结果和 A/H 股来源发现统一归一为 evidence records，再要求每条核心 claim 绑定 evidence_id；通过 CitationManager 生成 `citations.json/citations.md` 并追加到 Markdown/HTML 报告中，解决研报类场景中“结论从哪里来、哪些来源支撑哪些判断、弱来源是否误挂估值结论”的可审计问题。

- 【结构化财务计算与研报分析模块】将大模型不擅长的精确计算下沉到代码工具层，构建三表摘要、财务比率、趋势特征、P/E/P/S/DCF 与金融行业 P/B/DDM 估值、敏感性分析、非经常项风险和同业比较模块；DeepAnalyzeAgent、RiskAgent、PeerComparisonAgent 基于这些结构化结果生成 claims，避免报告只依赖自然语言生成，使财务指标、估值假设和风险提示具备可复算的基础。

- 【验证返工、可观测性与工具化落地】实现 VerifierAgent + 规则 Verifier 的质量门禁，检查标的一致性、章节完整性、引用覆盖、primary source、图表/表格 lineage 和估值 sanity check，并在失败时触发 FinalAnswerAgent 返工生成 `revision_history.json`；同时提供 CLI、本地 Web UI、MCP-style HTTP/JSON-RPC 工具服务，输出 `claims/evidence/citations/verification_report/task_trace/report.md/report.html/report.json` 等产物，便于演示、调试和后续评测扩展。
