# 多智能体竞赛对齐说明

## 当前已经能证明的多 Agent 能力

- `PlanningAgent -> DeepResearcherAgent -> BrowserAgent -> DeepAnalyzeAgent -> FinalAnswerAgent -> VerifierAgent -> GapResolverAgent` 已形成端到端链路。
- `task_trace.jsonl` 记录逐任务执行，`agent_collaboration_trace.json` 汇总 Agent handoff、输入输出、memory 使用、quality feedback 和返工轮次。
- `tool_trace.json` 记录 deterministic tools、ReAct 工具和搜索/数据源调用，能展示三表、估值、同行、检索等工具使用情况。
- `delivery_gate.json`、`quality_report.json`、`llm_quality_review.json` 和 `quality_remediation_plan.json` 构成三层质量门禁。
- delivery gate 失败后，Web UI 链路会把 remediation plan 传回 orchestrator，最多执行 2 轮同请求返工，并写出 `delivery_rework_history.json`。
- durable memory 只作为偏好、上下文和质量反馈约束；trace 中明确声明 memory 不能替代 evidence/citation/verifier。

## 相比普通可编排 workflow 的差异

- 普通 workflow 主要是固定 DAG；当前系统有 Planner/Router、SkillRegistry、memory brief、quality remediation 和 GapResolver 参与任务约束。
- 普通 workflow 只看最终报告；当前系统保留 evidence、claims、tables、financial metrics、tool trace、agent trace、quality gate 和 rework history。
- 普通 workflow 失败后通常只报错；当前系统能把失败转成 remediation plan、memory feedback 和下一轮/同轮 writer constraints。
- 普通 workflow 很难解释“为什么没通过”；当前系统能把 blocker/fatal 归因到三表、估值、同行、敏感性、上市身份、来源尝试或正文空洞。

## 当前距离竞赛要求的差距

- 公司/个股主链已优先补强，但“任意上市公司高质量”仍受免费公开数据源可得性影响；三表不可得时必须清楚说明缺口，不能假装通过。
- 行业/子行业和宏观/策略已有本地 Agent 与接口，但还没有达到公司主链同等的数据融合、情景模拟和质量门禁深度。
- MCP 当前有工具 manifest 和本地 tool registry 接口，A2A 主要体现为 artifact/state handoff，还不是标准化外部 A2A 协议实现。
- 前端已经能展示多 Agent 和工具 trace，但完整报告生成时的实时进度推送仍是轮询/结果式，不是流式 timeline。
- LLM review 若缺 API/key 会保持 `llm_review_pass=false`，不会伪造通过。

## 后续优先级

1. 用腾讯、A 股、美股和一个非预置 ticker 做完整 Chat-first 验收，记录 delivery gate 和 blocker。
2. 扩展港股公告/年报免费来源，减少港股三表只依赖 Yahoo 的不稳定性。
3. 为行业/宏观链路补独立 quality gate 和情景模拟 artifacts。
4. 把 Agent Timeline 做成生成中可刷新的实时进度，而不是只看最终 artifacts。
5. 增加单 Agent baseline，对比 evidence count、tool count、objective score、delivery pass 和 rework rounds。
