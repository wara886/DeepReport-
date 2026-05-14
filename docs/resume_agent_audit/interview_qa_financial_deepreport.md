# 金融 DeepReport++ Agent 面试问答稿

## 1. 这个金融研报场景，ChatGPT / 豆包直接对话不能解决吗？

面试官可能怎么问：你这个不就是把财报丢给大模型写报告吗，为什么不用 ChatGPT 直接问？

推荐回答：直接对话可以写一版“像研报的文字”，但很难稳定保证数据来源、财务口径、引用绑定、图表 lineage 和返工记录。这个项目的重点不是让 LLM 写得更漂亮，而是把研报拆成证据获取、结构化计算、claim 生成、citation 管理、Verifier 校验和报告导出。仓库里每轮会产出 `evidence.json`、`claims.json`、`citations.json`、`verification_report.json`、`task_trace.jsonl`，这些是直接对话很难自然留下的工程证据链。

技术关键词：evidence-backed claims、citation governance、structured financial calculation、verifier、traceability。

继续追问怎么展开：可以讲 `SEC CompanyFacts -> financial evidence -> financial ratios/valuation -> ClaimItem.evidence_ids -> CitationManager -> VerifierAgent` 这条链路。

不能讲过头：不能说完全替代金融分析师，也不能说所有事实都能自动核验；当前只是公开数据上的公司/个股研报原型。

## 2. 为什么要做 Agent，而不是普通 RAG 或一个大 Prompt？

面试官可能怎么问：RAG 检索几篇资料，再让大模型生成不就够了吗？

推荐回答：普通 RAG 主要解决“给模型更多上下文”，但金融研报的问题还包括计算、口径、来源权威性、引用对齐和质量返工。项目里 Research 负责找证据，Browser 负责规范化来源，Analyze 调工具做三表、比率、估值和敏感性，FinalAnswer 负责写作，Verifier 负责检查并给出 revision brief。这个拆分让系统能把不同失败模式分开定位，而不是把所有问题塞进一个 Prompt 里。

技术关键词：tool calling、task state、claim-first pipeline、quality gate、revision loop。

继续追问怎么展开：举例说估值不能靠 Prompt 心算，`company_valuation.py` 会输出估值模型、假设和敏感性，`valuation_audit.py` 会复查公式。

不能讲过头：不要说“RAG 没用”；准确说法是项目包含 RAG/检索，但 RAG 只是证据获取层，不是完整研报系统。

## 3. 为什么要多 Agent？为什么不是单 Agent？

面试官可能怎么问：一个强模型一个 agent 不能完成吗？

推荐回答：单 Agent 可以完成 demo，但很难定位失败来源。金融报告至少有信息搜索、正文抽取、财务计算、风险判断、同业比较、写作和校验七类不同职责。拆成多 Agent 后，每个 Agent 的输入输出更窄，trace 里能看到哪个阶段失败，例如 research 没拿到 primary source、analyze 缺财务指标、final 缺 citation、verifier 不通过。

技术关键词：separation of concerns、task graph、specialist agents、observable trace。

继续追问怎么展开：代码里 `MultiAgentOrchestrator._execute_dynamic_tasks` 按依赖执行任务，`merge_task_result` 把各 Agent 结果合并到 state。

不能讲过头：不能说它是完全自治的多 Agent 社会；它是 orchestrator 管控下的多 Agent workflow。

## 4. 你的系统到底是 Workflow，还是 Multi-Agent？

面试官可能怎么问：你这是不是只是 workflow，套了几个 Agent 名字？

推荐回答：准确定位是“多 Agent 化的工作流编排”，不是去中心化的 agent 群聊。它有明确的 Agent 类、角色 prompt、工具集合和标准 TaskResult，也有 PlanningAgent 生成任务图；但执行层由 orchestrator 控制依赖、state merge、产物落盘和 rework loop。因此简历上我会写“多 Agent workflow / orchestrated multi-agent system”，不会写成完全自主协商式 multi-agent。

技术关键词：orchestrated multi-agent workflow、AgentTask、TaskResult、state merge、dependency graph。

继续追问怎么展开：解释 `PlanningAgent` 允许 LLM 规划任务，但 `ensure_minimum_task_graph` 和 `apply_implicit_dependencies` 保证最小链路可控。

不能讲过头：不要说“每个 Agent 都自主决定下一步全局路径”；当前全局控制权在 orchestrator。

## 5. 每个 Agent 为什么这样拆？拆分依据是什么？

面试官可能怎么问：Agent 拆分不是为了堆数量吗？

推荐回答：拆分依据是金融研报的失败模式。信息不够由 Research/Browser 处理；财务口径和估值错由 Analyze 和特征工具处理；风险薄由 RiskAgent 处理；缺少横向参照由 PeerComparisonAgent 处理；写作结构散由 FinalAnswerAgent 处理；引用、章节和事实不稳由 CitationManager + VerifierAgent 处理。每个角色都有明确输入输出，而不是只换一个 Prompt 名字。

技术关键词：failure-mode driven decomposition、specialist tool set、state contract。

继续追问怎么展开：可以逐个讲 evidence_candidates、evidence_records、claims、analysis_artifacts、markdown/html、verification_report 的流转。

不能讲过头：不要说所有 Agent 都同等智能；Risk/Peer 当前偏规则和数据工具驱动。

## 6. 为什么要设计 claim-evidence-citation 链路？

面试官可能怎么问：为什么不直接把引用插进报告正文？

推荐回答：金融研报最怕“结论和来源对不上”。项目先生成结构化 `ClaimItem`，每条 claim 有 `evidence_ids` 和 `numeric_values`；再由 CitationManager 根据 evidence 和 claims 生成引用表，报告正文只是一种最终展示。这样 Verifier 可以机器检查 claim 引用的 evidence 是否存在、是否在 Markdown 中出现、来源是否足够权威。

技术关键词：ClaimItem、EvidenceItem、evidence_ids、citations.json、source authority。

继续追问怎么展开：讲 `build_citations` 会对 evidence_id/URL 去重，弱新闻源挂估值 claim 会被标记。

不能讲过头：不要说 citation 能证明结论一定正确；它证明“结论有可追溯来源”，正确性还要靠规则、数据和人工复核。

## 7. CitationManager 和 VerifierAgent 分别解决什么问题？

面试官可能怎么问：CitationManager 和 Verifier 不都是检查引用吗？

推荐回答：CitationManager 是引用产物生成器，负责把 evidence、claim 和 report 组合成 `citations.json/citations.md`，去重、关联 claim_ids、标记弱来源，并把参考来源追加到报告。VerifierAgent 是质量门禁，负责判断报告是否通过，包括章节完整性、引用覆盖、标的一致性、primary source、图表/表格 lineage、估值公式和 LLM judge 建议。

技术关键词：citation artifact builder、quality gate、rule verifier、LLM-assisted verifier。

继续追问怎么展开：`CitationManager` 产出引用，`VerifierAgent` 消费 claims/evidence/markdown/charts/tables/valuation 并输出 `verification_report` 和 `revision_brief`。

不能讲过头：CitationManager 不做完整事实核验，VerifierAgent 也不是外部事实 oracle。

## 8. 为什么要做 RiskAgent 和 PeerComparisonAgent？

面试官可能怎么问：风险和同业比较不能让写作 Agent 顺便写吗？

推荐回答：这两个模块很容易被写作模型写空或写泛。RiskAgent 把非经常项、估值 gap、资本开支、金融行业特征和网页风险关键词转成风险 claim；PeerComparisonAgent 负责 peer universe、财期对齐和同业指标表。把它们拆出来，可以避免 FinalAnswerAgent 只写“宏观不确定性、竞争加剧”这类套话。

技术关键词：risk-specific claim generation、peer universe、period alignment、sector benchmark。

继续追问怎么展开：讲 A 股白酒 peer group 和美股 SEC peer fetch 的差异，以及 stale peer period 过滤测试。

不能讲过头：不要说风险识别已经达到投研专家水平；当前更多是规则 + 证据提示的第一版。

## 9. 你做了哪些上下文管理？

面试官可能怎么问：别空谈 context，你代码里具体怎么管？

推荐回答：有三层。第一层是 orchestrator state，包含 evidence_candidates、evidence_records、claims、analysis_artifacts、markdown、citations、charts、verification_report、revision_history。第二层是 `context_packer.py`，对 claims、evidence、markdown excerpt 做数量和字符预算，优先保留被引用和高置信内容。第三层是 `conversation_memory.py`，把 scope、working、evidence、reflection、domain memory 压缩成 `conversation_brief` 传给 Planning/Final/Verifier，并落盘 `conversation_context.json`。

技术关键词：state object、context packing、character budget、conversation_brief、reflection memory。

继续追问怎么展开：举例 `pack_evidence_records` 会优先保留 claim 已引用的 evidence_id，防止 verifier/final answer 看不到关键证据。

不能讲过头：不要把它说成长期 Memory 系统；它主要是单次任务内的状态压缩和持久化。

## 10. 你做了 Memory 吗？

面试官可能怎么问：你的 Memory 提取和召回怎么做？

推荐回答：我会诚实区分。项目里做的是 task-state / run-level memory，而不是跨会话长期 Memory。`ConversationState` 保存本轮 scope、hard constraints、pinned facts、working memory、evidence memory、verifier feedback 和 reflection memory；每个阶段刷新 `conversation_brief`，作为压缩上下文给后续 Agent。证据和产物通过 JSON 文件持久化，但没有把历史会话写入向量库并做长期召回。

技术关键词：run-level memory、task state persistence、reflection from verifier feedback、not long-term memory。

继续追问怎么展开：说明如果要升级长期 memory，会拆成短期对话、跨会话项目记忆、系统知识库三层，并加写入过滤和召回策略。

不能讲过头：不能写“实现长期记忆/用户画像/跨会话个性化记忆”。

## 11. 你做了 Eval 吗？当前做到什么程度？

面试官可能怎么问：怎么证明效果变好了？

推荐回答：当前做了工程质量和研报一致性的 eval 雏形，包括 `eval_v1` case schema、numeric audit、valuation audit、multimodal consistency、company report scorecard、Verifier report，以及 QA 文档中的多轮人工检查记录。它能检查标的一致性、latest 财报识别、财务口径、行情复算、估值 sanity、引用-结论对齐等问题。但还没有大规模人工标注 benchmark 和稳定量化提升指标，所以简历不会写提升百分比。

技术关键词：numeric audit、valuation reproducibility、multimodal consistency、scorecard、QA regression。

继续追问怎么展开：下一步会建立固定 ticker-period benchmark，给 gold facts/gold citations/gold section coverage，并记录 pass rate、numeric accuracy、citation coverage、latency/cost。

不能讲过头：不能说“模型准确率提升 X%”。

## 12. 项目最真实的优势和短板是什么？

面试官可能怎么问：你自己觉得这个项目哪里强、哪里弱？

推荐回答：优势是把金融报告拆成可审计的工程链路：证据、claim、引用、图表、验证、返工和产物都能追踪；财务计算尽量由代码工具完成，不全靠 LLM。短板是覆盖面还窄，主要是公司/个股研报；A/H 股结构化财报抽取、行业/宏观研报、大规模 eval、生产部署和正式 MCP 协议都还不足。

技术关键词：auditability、financial lineage、bounded scope、known limitations。

继续追问怎么展开：承认它是可演示原型，不是证券公司生产系统。

不能讲过头：不要为了显得大而把短板包装成已完成能力。

## 13. A股支持目前到哪一步？

面试官可能怎么问：你说支持 A 股，具体支持什么？

推荐回答：当前 A/H 股支持是第一层：能规范化 `600519.SS/000858.SZ/00700.HK` 这类代码，返回巨潮、交易所、港交所披露易、东方财富/同花顺等来源候选；本地有白酒样例 financials 和 peer/risk/valuation 测试，A 股 peer group 能跑通。但官方年报 PDF、交易所公告正文、东方财富/同花顺结构化数据还没形成稳定抽取层。

技术关键词：source discovery、symbol normalization、local A-share fixtures、not full extractor。

继续追问怎么展开：可以展示 `china_finance.py`、`test_china_a_share_report_path.py` 和 `data/raw/real_data/600519.SS/latest`。

不能讲过头：不要写“生产级 A 股研报自动生成”。

## 14. 如果继续优化，最优先补什么？

面试官可能怎么问：下一步你会怎么做？

推荐回答：我会优先补 eval 和数据抽取。第一，固定 20-50 个 ticker-period case，建立 gold facts、gold evidence、gold citations 和人工评分，形成能复现的质量指标。第二，补 A/H 股官方公告/PDF 结构化抽取，因为这决定中文金融场景能否从 demo 变成可用系统。第三，再做成本/延迟路由，把 expensive model 只用于 verifier fail 或复杂估值返工。

技术关键词：benchmark set、gold facts、A/H filing extraction、model routing、latency/cost tradeoff。

继续追问怎么展开：说明现有 `pro_policy`、`pro_triggers`、`revision_history` 已经为条件路由打了基础。

不能讲过头：不要说“继续优化就是换更大模型”；核心还是数据、评测和质量门禁。

## 15. MCP-style HTTP 服务是不是 MCP 协议本体？

面试官可能怎么问：你简历写 MCP-style，这是不是 Anthropic MCP 标准实现？

推荐回答：不是正式 MCP SDK 实现，所以我会写 MCP-style 或 MCP-like。当前服务提供了类似 MCP 工具发现和调用的边界：`/mcp/manifest`、JSON-RPC `/mcp/rpc`、`tools/list`、`tools/call`、`inputSchema`、`content`、`structuredContent`。它适合本地工具服务化和面试演示，但如果要接入标准 MCP 客户端，还需要引入正式 MCP SDK、协议握手和资源/提示等完整能力。

技术关键词：HTTP/JSON-RPC、tools/list、tools/call、inputSchema、structuredContent、not official MCP SDK。

继续追问怎么展开：展示 `src/utils/mcp_http_server.py` 和 `src/utils/mcp_manager.py`。

不能讲过头：不能写“实现正式 MCP 协议服务”。

## fixed.md 建议专项回答

### 建议一：Agent 学习/项目答辩路线

通用回答：我认可“先理解 Agent 的失败模式，再学框架”的路线。Agent 不是 LangChain/LangGraph API 堆叠，核心是 Function Calling 怎么被 schema 约束、ReAct 循环如何停止、上下文如何压缩、工具输入输出如何结构化、失败如何观测和回滚。真正能面试的项目要有可判断对错的场景、明确 eval 指标和问题复盘，而不是只展示一个会聊天的 demo。

映射到本金融项目：这个项目没有先套 LangGraph，而是先把金融研报最容易崩的点拆出来：事实来源、财务计算、引用对齐、标的一致性、估值复算、报告空章节和 verifier 返工。代码里对应 `ToolRegistry`、`run_react_tool_loop`、`context_packer`、`conversation_memory`、`task_trace.jsonl`、`verification_report.json`。简历里应强调“失败模式驱动的多 Agent workflow”，而不是“我会某某框架”。

### 建议二：Memory、噪声处理、效率/质量/cost、skills 动态感知

通用回答：Memory 不能泛泛说“把历史都塞进去”。严谨做法是区分短期会话、长期用户/项目记忆、系统知识库，并设计写入过滤、召回排序、过期机制和噪声剔除。效率、质量和成本的平衡通常靠上下文预算、工具结果结构化、模型分层路由、失败后再升级模型、可观测 trace。技能/工具感知则依赖工具注册表、schema 描述、manifest 暴露和按任务动态选择，而不是让模型凭空知道可用能力。

映射到本金融项目：本项目做了 run-level memory，而不是长期 memory；噪声处理主要体现在 source authority、CitationManager 弱来源标记、context packer 优先保留被 claim 引用的 evidence、Verifier evidence gaps。效率/质量/cost 方面有 fast/default profile、`max_tokens/max_records/content_limit`、conditional pro model route 和 `duration_sec` trace。工具感知通过 `ToolRegistry`、`MCPManager.export_manifest` 和 HTTP `tools/list` 暴露，但还没有像 Claude Code 那样完整的 skill 动态加载生态。
