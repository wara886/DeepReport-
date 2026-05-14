金融 Deep Report / Open DeepReport++ 多 Agent 金融研报生成系统

- 【多 Agent 研报生成链路搭建】面向公司/个股研报，将任务规划、证据检索、网页/正文抽取、财务分析、风险与同业比较、报告撰写和验证拆分为专职 Agent，并由 orchestrator 管理任务依赖、共享 state、trace 和返工轮次；相比单轮 Prompt，系统能针对信息缺口、引用缺失和财务口径问题分阶段处理，形成可解释的研报生成 workflow。

- 【Claim-Evidence-Citation 可信引用治理】设计 Evidence / Claim / Citation schema，把 SEC CompanyFacts、Yahoo Finance、本地 evidence、网页搜索和 A/H 股来源发现统一为 evidence records，要求核心结论绑定 evidence_id，并通过 CitationManager 输出引用表和报告参考来源；该链路让每条研报结论能回溯来源，也为 Verifier 检查弱来源、缺引用和结论-证据错配提供结构化依据。

- 【财务计算、验证返工与工具化输出】将三表摘要、财务比率、估值模型、敏感性分析、风险识别和同业比较下沉到代码工具层，再由 Agent 汇总成报告；实现 VerifierAgent 对标的一致性、引用覆盖、图表/表格 lineage、估值 sanity check 的校验，并支持 CLI、Web UI、MCP-style HTTP 服务及 Markdown/HTML/JSON、trace、verification report 等产物输出。
