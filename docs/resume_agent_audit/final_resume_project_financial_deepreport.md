金融 Deep Report / Open DeepReport++ 多 Agent 金融研报生成系统

- 【多 Agent 研报工作流构建】面向公司/个股研报，将任务规划、证据检索、网页正文抽取、财务分析、风险与同业比较、报告撰写和验证拆成专职 Agent，并由 orchestrator 统一管理任务依赖、共享 state、trace 与返工轮次，解决单轮 Prompt 难以追踪事实来源和错误阶段的问题。

- 【Claim-Evidence-Citation 引用治理】设计 Evidence / Claim / Citation 数据契约，统一接入 SEC CompanyFacts、Yahoo Finance、本地 evidence store、网页搜索及 A/H 股来源发现，要求核心结论绑定 evidence_id，并通过 CitationManager 输出引用表和参考来源，使研报结论能够回溯到具体数据与来源。

- 【结构化财务分析与工具调用】将三表摘要、财务比率、趋势特征、估值模型、敏感性分析、风险识别和同业比较下沉到代码工具层，再由 DeepAnalyze/Risk/Peer Agent 生成可验证 claims，避免大模型直接编写财务数字，增强报告中指标、估值假设和风险提示的可复算性。

- 【Verifier 返工闭环与工具化输出】实现 VerifierAgent 对标的一致性、引用覆盖、章节完整性、图表/表格 lineage 和估值 sanity check 的校验，并在失败时触发 FinalAnswerAgent 返工；支持 CLI、Web UI、MCP-style HTTP 服务，输出 Markdown/HTML/JSON、claims、evidence、citations、trace 和 verification report 等可审计产物。
