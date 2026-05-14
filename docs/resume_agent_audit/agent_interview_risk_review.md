# Agent 面试高频审查点专项自查

## A. 是否属于“豆包就能解决”的伪需求？

- 当前判断：不是纯伪需求，但必须表述为“可信研报生成工程”，而不是“LLM 写研报”。
- 仓库证据：主链输出 `evidence.json`、`claims.json`、`citations.json`、`verification_report.json`、`task_trace.jsonl`；结构化计算在 `features/` 和 `company_valuation.py`；Verifier 检查引用、章节、标的、图表和估值。
- 面试风险：如果只讲“输入 ticker 输出报告”，面试官会认为 ChatGPT 直接能做。
- 建议表述：强调“可追溯证据链 + 财务复算 + 验证返工 + 工具化输出”。
- 是否应该写进简历：应该写，但不要写成普通聊天机器人。

## B. 是否存在为堆技术而堆技术？

- 当前判断：部分风险存在。Agent 数量较多，但多数有实际职责；MCP-style、Memory、RAG、Eval 需要克制表述。
- 仓库证据：Risk/Peer/Citation/Verifier 都接入主链；但 `MCPManager` 是 local-mcp-v1，`ConversationMemory` 是 run-level，不是长期 memory；RAG 有 fallback。
- 面试风险：把每个模块都吹成生产级，会被追问击穿。
- 建议表述：说“按金融研报失败模式拆分模块”，并承认哪些是初步支持。
- 是否应该写进简历：可写 Agent/Citation/Verifier/财务计算；Memory/MCP/RAG/Eval 要限定。

## C. 简历上的每一行是否都能答透？

- 当前判断：如果按本目录推荐版本写，可以答透；如果写行业宏观、长期 memory、正式 MCP、生产级 A 股，会有风险。
- 仓库证据：`project_fact_inventory.md` 已区分已实现和不应写内容。
- 面试风险：面试官可能要求指出代码文件、产物和失败案例。
- 建议表述：每个 bullet 都绑定代码证据和产物，例如 `CitationManager -> citations.json`、`VerifierAgent -> verification_report.json`。
- 是否应该写进简历：应该写可落地闭环，不写无证据指标。

## D. Workflow 与 Multi-Agent 是否表述准确？

- 当前判断：准确定位是 orchestrated multi-agent workflow。
- 仓库证据：`MultiAgentOrchestrator._execute_dynamic_tasks` 按依赖执行；`PlanningAgent` 生成任务图；`merge_task_result` 合并 state；全局控制在 orchestrator。
- 面试风险：如果写“自主多智能体协商系统”，会被问 agent 间协议、自治路由、冲突解决，目前支撑不足。
- 建议表述：写“多 Agent workflow / 由 orchestrator 管控的多 Agent 研报生成链路”。
- 是否应该写进简历：应该写，但加 workflow/orchestrator 限定。

## E. 上下文管理是否有实质内容？

- 当前判断：有实质内容。
- 仓库证据：`state` 存 evidence/claims/artifacts/report/verification；`context_packer.py` 做 claim/evidence/markdown 截断和优先级；`conversation_memory.py` 做 scope/working/evidence/reflection/domain memory；`conversation_context.json` 落盘。
- 面试风险：如果只说“用了上下文工程”，会显得空。
- 建议表述：讲清楚“状态容器 + 上下文预算 + verifier feedback 压缩”三件事。
- 是否应该写进简历：可写，但建议放在面试展开，不必在简历主 bullet 里占太多字。

## F. Memory 是否被过度包装？

- 当前判断：有过度包装风险。
- 仓库证据：`ConversationState` 是单次 run 级别；没有跨会话向量库记忆、用户记忆召回、记忆写入过滤模型。
- 面试风险：写“长期 Memory”会被问记忆提取、噪声过滤、召回排序，当前无法充分支撑。
- 建议表述：写“任务级 state / run-level memory / evidence persistence”，不要写“长期记忆系统”。
- 是否应该写进简历：主简历不建议写 Memory；面试中可诚实说明。

## G. 是否有 Eval，若不足，缺什么？

- 当前判断：有 QA/Eval 雏形，但不是完整 benchmark。
- 仓库证据：`eval_v1.py`、`numeric_audit.py`、`valuation_audit.py`、`multimodal_consistency.py`、`company_report_scorecard.py`、`docs/Open_DeepReport_financial_report_QA.md`、多份 `qa*` 产物。
- 面试风险：如果写量化提升，会被要求实验设计、样本量、baseline、显著性。
- 建议表述：写“建立 QA/Eval 意识和质量门禁”，不写虚构百分比。
- 是否应该写进简历：应该写“支持质量校验/回归检查”，不写“准确率提升 X%”。

## H. 是否存在“抄开源项目但没有二次开发”的风险？

- 当前判断：风险可控，但需要主动说明二次开发边界。
- 仓库证据：README 和 AGENTS 文档明确受 DeepReport 骨架启发；本仓库有自研的金融数据层、证据 schema、SEC/Yahoo/A股来源发现、财务计算、CitationManager、Verifier、Web UI、MCP-style 服务和 QA 修复。
- 面试风险：面试官可能问哪些是参考，哪些是自己做的。
- 建议表述：说“参考 DeepReport 的多 Agent 骨架和职责划分，重写公司/个股研报的数据、工具、分析、引用、验证和产物链路”。
- 是否应该写进简历：可以写项目，不建议强调“复用某开源项目”，除非面试被问来源。

## 技术点写法清单

可以写：

- 多 Agent workflow / orchestrator / task graph / state merge。
- SEC CompanyFacts、Yahoo Finance、本地 evidence store、搜索聚合。
- Evidence-Claim-Citation 链路和 CitationManager。
- 三表摘要、财务比率、估值、敏感性分析、风险识别、同业比较。
- VerifierAgent、规则校验、返工闭环、revision history。
- CLI、Web UI、MCP-style HTTP/JSON-RPC 工具服务。
- 质量校验：标的一致性、引用覆盖、估值 sanity、图表/表格 lineage、scorecard。

谨慎写：

- A/H 股支持：只能写“初步支持代码识别、权威来源发现、本地样例路径”。
- Memory：写 run-level state/context packing，不写长期 memory。
- RAG：写 BM25/vector/hybrid/reranker fallback，不写生产级 RAG 平台。
- Eval：写 QA/回归/质量门禁，不写指标提升。
- MCP：写 MCP-style/local-mcp-v1，不写正式 MCP 协议本体。

不要写：

- 完整行业/宏观研报生成。
- 生产级 A 股研报系统。
- 正式 MCP SDK 服务。
- 长期记忆系统。
- 大模型微调已提升主链效果。
- 无证据的百分比指标。
