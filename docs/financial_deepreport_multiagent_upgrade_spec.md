# 金融 DeepReport++：从可控 Workflow 升级为协作式 Multi-Agent 系统的说明文档

## 0. 这份文档要解决什么

当前项目已经具备金融研报自动生成链路：任务规划、检索、网页抽取、结构化分析、风险与同业比较、引用治理、报告生成、Verifier 校验与返工，并且已有 claims / evidence / citations / verification / trace 等可审计产物。

但如果项目的最终目标是一个**真正值得写进简历、也能经得住 Agent 技术面深挖的“金融多智能体研究系统”**，那么后续不能只停留在：

- 固定顺序执行的一条工作流；
- “多 Agent”命名，但没有真实协作；
- 有 QA 但没有正式 baseline / eval harness；
- 有 state 但没有清晰的 memory 设计；
- 有大量领域流程，但没有沉淀成可复用的 skill。

本说明文档明确：

1. 这个项目最终要达到什么效果；
2. 从当前 orchestrated workflow 升级为真正 multi-agent 还缺什么；
3. 评测指标、Memory、Skill、Observability 应如何围绕金融研报任务落地；
4. 后续 Codex / Claude Code 应按什么路线修改、review、测评，直到达到目标状态。

---

# 1. 项目最终想达到的效果

## 1.1 项目最终定位

最终目标不是“一个会生成金融研报的流程编排器”，而是：

> **一个面向公司/个股研究的、可审计、可返工、可评测、具备协作决策能力的金融 Multi-Agent Deep Research 系统。**

更准确地说，它应当是：

- **研究型 Agent 系统**：不是纯问答，而是围绕一个研究任务完成规划、取证、分析、质疑、修订和最终成文；
- **多智能体系统**：Agent 之间不是简单串行，而是具备任务委派、证据挑战、缺口补全、冲突裁决和结果审批；
- **金融高可靠性系统**：核心不是“文风像研报”，而是数字可核、引用可追、结论可解释；
- **工程化系统**：每次改 Prompt、Tool、Agent 或 Skill 后，都能跑 baseline / eval / regression，知道效果是变好还是变坏。

---

## 1.2 最终用户侧体验

最终用户主入口应是**自然语言研究请求**，而不是要求普通用户先理解 `symbol / period / topic / 上传文件` 等工程化参数。

用户可以直接输入：

```text
帮我生成一份贵州茅台的最新深度金融研报，重点关注盈利质量、估值、行业风险和同业对比。
分析英伟达最近一个季度的经营情况，判断当前估值是否偏贵，并给出主要风险。
```

系统首先进入 Request Understanding 层，自动解析：

```text
company_name / symbol / market
report_type
period
focus_areas
output_preferences
clarification_needed / clarification_questions
```

若公司实体、上市市场或时间范围存在高风险歧义，系统应先追问澄清，而不是贸然生成研报。例如“招商银行”需要确认 A 股还是 H 股，“苹果分析”需要确认 Apple Inc. 还是商品品类。

结构化参数仍保留，但定位为**开发、CLI、Eval、回归测试入口**：

```text
symbol = NVDA
period = latest_quarter / FY / TTM
topic = 公司基本面、盈利质量、估值、风险与同业比较
```

文件上传应是 optional evidence，用于补充私有材料、会议纪要或用户已有文档；对公开上市公司研报任务，它不应是默认前置条件。

系统最终不只是生成一篇报告，而是自动完成：

1. **规划研究任务**
   - 判断应该研究哪些维度；
   - 拆成财务、行情、行业、风险、估值、同业等子任务；
   - 给出每个子任务的完成条件。

2. **自主取证**
   - 识别主数据源、次数据源与弱来源；
   - 优先查官方或可信来源；
   - 若来源不足，主动发起补检索，而不是硬写。

3. **结构化分析**
   - 财务三表摘要；
   - 指标派生；
   - 盈利质量、现金流、杠杆、估值；
   - 同业比较；
   - 风险识别。

4. **Agent 间协作与互相挑战**
   - AnalyzeAgent 可以指出 ResearchAgent 证据不足；
   - RiskAgent 可以指出主结论过于乐观；
   - CitationQA 可以要求补来源；
   - Verifier 可以将问题精准退回给具体 Agent，而不是只让 Writer 重写。

5. **冲突解决**
   - 如果两个来源数字不一致；
   - 如果两个 Agent 对结论有冲突；
   - 系统需要进入 adjudication / conflict resolution 流程。

6. **形成可审计报告**
   - report.md / report.html / report.json；
   - claims.json；
   - evidence.json；
   - citations.json；
   - verification_report.json；
   - agent_messages.jsonl；
   - task_board.json；
   - eval_summary.json。

7. **生成质量评测**
   - 报告是否完成；
   - 引用是否支撑结论；
   - 数值是否通过 audit；
   - 工具调用是否合理；
   - 返工是否有效；
   - 耗时和成本是否在预算内。

---

# 2. 当前项目与目标项目的差距

## 2.1 当前状态：Orchestrated Multi-Agent Workflow

当前项目更接近：

```text
Planner
→ Research
→ Browser
→ Analyze
→ Risk / Peer
→ Citation
→ Final
→ Verifier
→ Rework
```

其特点是：

- 有多个 Agent；
- 角色拆分基本合理；
- 有共享 state；
- 有产物沉淀；
- 有 Verifier 返工；
- 但总体仍是中心化 orchestrator 驱动；
- 下一步执行顺序大多由固定图决定；
- Agent 之间缺少显式协商与消息协议；
- 返工更多是 orchestrator 发起，而不是 Agent 之间形成较完整的“质疑—回应—修订”闭环。

这个阶段已经优于普通 RAG / Prompt 项目，但若想把项目目标明确设定为“多智能体系统”，还需要继续升级。

---

## 2.2 目标状态：Bounded Autonomous Multi-Agent System

目标不是做“Agent 群聊”，而是做：

> **有边界约束的自主协作式 Multi-Agent。**

它必须有：

### 1. 显式 Agent 消息协议
Agent 不只是返回结果，而是可以发送：

- `REQUEST_EVIDENCE`
- `CHALLENGE_CLAIM`
- `REQUEST_RECALCULATION`
- `PROPOSE_REVISION`
- `APPROVE_SECTION`
- `REJECT_SECTION`
- `ESCALATE_CONFLICT`

### 2. 共享任务板 / Blackboard
统一维护：

- 待执行任务；
- 已完成任务；
- 被阻塞任务；
- 待补证据任务；
- 被挑战的 claim；
- 已解决 gap；
- 未解决 conflict。

### 3. 动态路由
不是固定阶段流，而是根据当前状态决定下一步：

- 缺主来源 → 退回 Research；
- 数值冲突 → 退回 Analyze + NumericAudit；
- 引用不足 → 退回 Research / CitationQA；
- 估值方法不匹配 → 退回 ValuationSkill / Analyze；
- 风险章节空泛 → 退回 RiskAgent；
- 同业维度不足 → 退回 PeerComparisonAgent。

### 4. 多轮协作
同一个问题可以跨 Agent 反复迭代：

```text
Research 提供初证据
→ Analyze 提出 claim
→ CitationQA 发现 claim 支撑不足
→ GapRouter 退回 Research 补证据
→ Research 补充 primary source
→ Analyze 更新 claim
→ Verifier 通过
```

### 5. 冲突裁决
出现以下情况时，需要专门机制处理：

- 不同来源的财务数字不一致；
- 不同 Agent 对风险等级判断相反；
- 估值区间与市场数据严重背离；
- 引用来源支持不了强结论。

可引入：

- `AdjudicatorAgent`
- 或 `Judge / Arbitration Module`

负责：

- 汇总冲突；
- 检查来源优先级；
- 选择更可信结论；
- 或保留“不确定性”表述。

### 6. Agent-level Eval
不仅看最终报告，还评估：

- 哪个 Agent 任务完成；
- 哪个 Agent 经常触发返工；
- 哪类 gap 最难解决；
- 哪个 Agent 造成报告失败；
- 哪个 Agent 贡献了主要增益。

---

# 3. 目标 Multi-Agent 架构建议

## 3.1 推荐架构

```text
User Request
   ↓
PlannerAgent
   ↓
TaskBoard + Shared Blackboard
   ↓
┌──────────────────────────────────────────┐
│ Dynamic Router / GapRouter / BudgetGuard │
└──────────────────────────────────────────┘
   ↓           ↓            ↓            ↓
ResearchAgent BrowserAgent AnalyzeAgent RiskAgent
   ↓           ↓            ↓            ↓
Evidence Memory  Financial Memory  Risk Memory
   ↓           ↓            ↓            ↓
PeerComparisonAgent / ValuationAgent / CitationQAAgent
   ↓
VerifierAgent
   ↓
AdjudicatorAgent（仅在冲突时触发）
   ↓
FinalWriterAgent
   ↓
Report + Trace + Eval
```

---

## 3.2 推荐 Agent 角色重组

### A. PlannerAgent
职责：

- 理解 query；
- 判断 report_type；
- 拆分 task；
- 设定 mandatory outputs；
- 给出最初 task board。

输出：

- `research_plan.json`
- `task_board.json`

### B. ResearchAgent
职责：

- 找主来源 / 次来源；
- 收集事实；
- 标记 evidence quality；
- 识别来源缺口。

输出：

- `evidence.json`
- `source_quality_report.json`

### C. BrowserAgent
职责：

- 打开网页、公告、PDF、正文；
- 抽取可验证内容；
- 对页面噪声做清洗；
- 识别正文与 metadata。

输出：

- `browser_extracts.json`

### D. AnalyzeAgent
职责：

- 财务分析；
- 比率计算；
- 趋势判断；
- 形成初版 claims；
- 指出需要补证据 / 补计算的地方。

输出：

- `financial_analysis.json`
- `claims_draft.json`

### E. ValuationAgent
建议从 AnalyzeAgent 中拆出来。
职责：

- 估值方法选择；
- DCF / relative valuation / bank-specific valuation 等；
- sanity check；
- assumptions 暴露。

输出：

- `valuation_analysis.json`

### F. RiskAgent
职责：

- 非经常项；
- 经营风险；
- 行业风险；
- 宏观 / 政策风险；
- 估值风险；
- 从“反证视角”质疑主结论。

输出：

- `risk_memo.json`

### G. PeerComparisonAgent
职责：

- 选 peer；
- 统一口径；
- 形成横向比较；
- 识别单公司叙事中的偏差。

输出：

- `peer_comparison.json`

### H. CitationQAAgent
职责：

- 检查 claim-evidence-citation 对齐；
- 找到 unsupported claim；
- 识别弱来源；
- 检查 source_url / evidence_id / citation span。

输出：

- `citation_audit.json`
- `evidence_gaps.json`

### I. VerifierAgent
职责：

- 做最终 quality gate；
- 检查 report completeness；
- 检查 symbol / period / ticker；
- 检查 numeric audit；
- 检查 valuation audit；
- 检查 consistency；
- 输出返工建议。

输出：

- `verification_report.json`

### J. AdjudicatorAgent
职责：

- 只在冲突时触发；
- 裁决多 Agent 分歧；
- 标记“无法确认 / 存在不确定性”；
- 保留依据。

输出：

- `conflict_resolution.json`

### K. FinalWriterAgent
职责：

- 只消费已通过的结构化材料；
- 生成最终报告；
- 不再自由捏造事实；
- 对不确定结论做边界化表达。

输出：

- `report.md`
- `report.html`
- `report.json`

---

# 4. 核心机制一：GapRouter 与多轮返工

## 4.1 为什么 GapRouter 是从 Workflow 迈向 Multi-Agent 的关键

固定 workflow 的问题是：

- Verifier 发现问题后，常常只能整体退回；
- 不知道该让谁修；
- 修完是否解决问题也不够结构化。

GapRouter 负责把具体问题精准送回正确 Agent。

---

## 4.2 Gap 类型定义

建议至少定义：

```text
EVIDENCE_GAP
NUMERIC_GAP
VALUATION_GAP
CITATION_GAP
RISK_GAP
PEER_GAP
FORMAT_GAP
COMPLIANCE_GAP
SYMBOL_PERIOD_MISMATCH
SOURCE_CONFLICT
```

---

## 4.3 路由策略

| Gap 类型 | 优先路由对象 |
|---|---|
| EVIDENCE_GAP | ResearchAgent / BrowserAgent |
| NUMERIC_GAP | AnalyzeAgent / NumericAudit |
| VALUATION_GAP | ValuationAgent |
| CITATION_GAP | CitationQAAgent + ResearchAgent |
| RISK_GAP | RiskAgent |
| PEER_GAP | PeerComparisonAgent |
| FORMAT_GAP | FinalWriterAgent |
| COMPLIANCE_GAP | FinalWriterAgent / ComplianceModule |
| SYMBOL_PERIOD_MISMATCH | PlannerAgent + ResearchAgent |
| SOURCE_CONFLICT | AdjudicatorAgent |

---

## 4.4 返工闭环

每次返工必须记录：

- gap_id；
- gap_type；
- raised_by；
- routed_to；
- status；
- before_state；
- after_state；
- resolved / unresolved；
- 本轮返工耗时与成本。

---

# 5. 核心机制二：评测体系与 baseline 设计

## 5.1 为什么必须做 Eval

目标项目不是 Demo，而是一个“可迭代优化”的 Agent 系统。

没有 Eval，会出现：

- 改 Prompt 后不知道是好是坏；
- 新增 Agent 可能只是让耗时更高；
- 增加 Multi-Agent 复杂度后，真实报告质量未必提升；
- 无法在简历中写出可信的“相比 baseline 改善”。

---

## 5.2 固定 Eval 数据集

建议建立 `eval/cases/`：

```text
eval/
  cases/
    us_tech/
    us_finance/
    us_consumer/
    china_a/
    hard_cases/
```

每个 case 定义：

```json
{
  "case_id": "nvda_latest_quarter_001",
  "symbol": "NVDA",
  "period": "latest_quarter",
  "topic": "基本面、估值、风险、同业比较",
  "expected_report_type": "company_research",
  "required_sections": [
    "business_overview",
    "financials",
    "valuation",
    "risks",
    "peer_comparison"
  ],
  "must_use_sources": [
    "primary_financial_source",
    "market_data_source"
  ],
  "difficulty": "normal"
}
```

---

## 5.3 Baseline 设计

### Baseline 0：Single Prompt LLM
- 不检索；
- 不调用工具；
- 直接写报告。

### Baseline 1：Single-Agent RAG
- 检索 top-k evidence；
- 单 Agent 一次生成报告。

### Baseline 2：Current Workflow
- 当前 orchestrated multi-agent workflow；
- 作为“现有版本”。

### Baseline 3：Enhanced Workflow + GapRouter
- 引入精准返工；
- 还未引入完整 agent negotiation。

### Baseline 4：Target Multi-Agent System
- 消息协议；
- task board；
- dynamic routing；
- conflict arbitration；
- memory；
- skills；
- eval harness。

这样能看清：

- Multi-Agent 是否真的优于 Workflow；
- GapRouter 是否是主要增益来源；
- Memory / Skill 是否带来稳定收益。

---

## 5.4 指标体系

### 一级指标：最终任务质量

#### 1. Task Completion Rate
判断：

- report 产物是否齐全；
- 必要章节是否存在；
- verification 是否通过；
- 无 critical gap。

#### 2. Report Completeness Score
检查：

- business overview；
- financials；
- valuation；
- risks；
- peer comparison；
- conclusion / caveat。

#### 3. Claim Support Rate
定义：

```text
被 evidence 支持的 claim 数 / 总 claim 数
```

#### 4. Citation Support Rate
定义：

```text
引用能直接支撑对应 claim 的 citation 数 / 总 citation 数
```

#### 5. Numeric Audit Pass Rate
检查：

- 财务数字；
- 同比 / 环比；
- 百分比；
- 市值 / 估值；
- 图表口径。

#### 6. Valuation Sanity Pass Rate
检查：

- 估值方法是否与行业匹配；
- assumptions 是否完整；
- 输出是否存在数量级异常；
- 估值结果是否标明不确定性。

---

### 二级指标：Agent 与工具过程质量

#### 7. Tool Selection Accuracy
该调用的工具是否调用；
不该调用的工具是否避免调用。

#### 8. Tool Argument Validity
参数是否符合 schema；
symbol / period / query 是否正确。

#### 9. Gap Detection Recall
真正存在的问题，有多少被 Verifier / CitationQA 检测出来。

#### 10. Gap Resolution Rate
被检测出的 gap，有多少在返工后解决。

#### 11. Rework Effectiveness
返工后指标是否改善，而不是形式返工。

#### 12. Conflict Resolution Accuracy
有来源冲突或 agent 分歧时，裁决是否合理。

---

### 三级指标：工程效率

#### 13. Total Latency
总耗时。

#### 14. Agent Latency Breakdown
每个 Agent 耗时。

#### 15. Tool Latency Breakdown
每个 Tool 耗时。

#### 16. Rework Cost
返工引入的额外耗时 / token / cost。

#### 17. Token & Cost Budget
每个 case 总 token；
每个 agent token；
每类工具开销。

---

## 5.5 Eval 输出产物

```text
eval_outputs/
  run_id/
    eval_summary.json
    per_case_metrics.jsonl
    failure_taxonomy.json
    baseline_comparison.json
    regression_diff.md
    dashboard_ready.csv
```

---

# 6. 核心机制三：Memory 设计

## 6.1 金融研报项目里，Memory 应该如何理解

这个项目里的 Memory 不应只理解成“记住用户偏好”。

更重要的是：

> **在长链路、多 Agent、多轮返工中，维护任务状态、研究事实、历史失败与可复用知识。**

建议分四层：

---

## 6.2 Layer 1：Working Memory（单次 run 内）

这是最重要、必须做的。

保存：

- symbol / period / topic；
- research plan；
- task board；
- 已收集 evidence；
- 已形成 claims；
- 已识别 gaps；
- 当前 verifier findings；
- 当前冲突与裁决状态。

特点：

- 当前任务结束后可以归档；
- 是 Agent 协作的共享事实基础。

---

## 6.3 Layer 2：Episodic Memory（历史 run 经验）

保存：

- 某类 case 常见失败；
- 某类 gap 常见触发点；
- 某次返工是否有效；
- 某个工具在哪类问题中经常失败；
- 历史 QA 失败样本。

作用：

- 给 Planner / Verifier / GapRouter 提供经验；
- 支持 regression；
- 支持失败 taxonomy 迭代。

---

## 6.4 Layer 3：Domain Memory（稳定金融知识与策略）

保存：

- 行业差异化估值方法；
- 银行、消费、科技公司的分析模板差异；
- 来源可信度规则；
- Primary > Secondary > Weak；
- 财务 period 口径规则；
- A股 / 美股数据源差异；
- 证据优先级策略。

这部分不一定存成向量记忆，很多内容更适合结构化 YAML / JSON / Skill。

---

## 6.5 Layer 4：User Preference Memory（可选，不是当前核心）

如果未来要做产品化，才考虑：

- 用户偏好的报告长度；
- 偏好中文 / 英文；
- 偏好的覆盖市场；
- 偏好的风险风格；
- 偏好的报告模板。

但这不是当前项目的主卖点，不能混同于 DeepReport 主能力。

---

## 6.6 Memory 数据结构建议

```text
memory/
  working/
    run_id/
      state.json
      task_board.json
      messages.jsonl
  episodic/
    failure_cases.jsonl
    resolved_gaps.jsonl
    tool_failures.jsonl
  domain/
    source_policy.yaml
    valuation_policy.yaml
    report_policy.yaml
    market_policy.yaml
  user/
    preferences.json
```

---

## 6.7 Memory 与 Prompt 的关系

必须严格区分：

- **Prompt**：角色、规则、输出协议；
- **Memory**：当前任务状态或跨任务可复用信息；
- **Schema**：Agent 之间交换信息的数据契约；
- **Tool**：执行外部动作；
- **Skill**：一类复杂任务的可复用 SOP / 策略能力。

---

## 6.8 ContextPacker

不能把全部 memory 塞进 prompt。

需要 `ContextPacker`：

- 按当前 Agent 角色挑选上下文；
- 对 evidence 做摘要；
- 对历史 messages 做压缩；
- 对 resolved gaps 不重复注入；
- 对当前任务最关键的 unresolved gaps 提权。

---

# 7. 核心机制四：Skill 沉淀

## 7.1 为什么需要 Skill

随着项目复杂化，一些能力不应该继续散落在：

- Prompt；
- 零散脚本；
- Agent 内部 if-else；
- README 文档。

它们应沉淀为：

> **可版本化、可动态加载、可评估的领域 Skill。**

---

## 7.2 适合沉淀的金融 Skill

### 1. `sec_companyfacts_skill`
- SEC 数据抽取；
- period 口径判断；
- latest 判定；
- 基础财务指标映射。

### 2. `a_share_disclosure_skill`
- A股公告源发现；
- 中文财报 / 公告检索；
- 中文字段抽取；
- A股来源可信度规则。

### 3. `valuation_method_selection_skill`
- 科技公司；
- 银行；
- 消费；
- 白酒；
- 不同行业采用不同估值框架。

### 4. `numeric_consistency_audit_skill`
- 数字复算；
- 比率检查；
- 百分比检查；
- market movement 检查；
- 数量级 sanity check。

### 5. `citation_support_audit_skill`
- claim-evidence-citation 对齐；
- unsupported claim；
- weak source；
- citation span 检查。

### 6. `risk_counterargument_skill`
- 从空头 / 反证角度补风险；
- 检查结论是否单边偏乐观。

### 7. `peer_selection_skill`
- 同业筛选；
- peer 口径一致化；
- 比较维度自动生成。

### 8. `gap_routing_skill`
- gap 分类；
- gap → agent 路由；
- 返工优先级；
- stop condition。

### 9. `report_quality_gate_skill`
- 必备章节；
- 合规披露；
- unsupported statement；
- verification gate。

---

## 7.3 Skill 的目录设计

```text
skills/
  sec_companyfacts/
    SKILL.md
    schema.json
    examples/
    tests/
  valuation_method_selection/
    SKILL.md
    schema.json
    policies.yaml
    tests/
  citation_support_audit/
    SKILL.md
    schema.json
    tests/
```

---

## 7.4 SkillRegistry / SkillRouter

### SkillRegistry
负责：

- 扫描 skill 目录；
- 读取 metadata；
- 加载 schema；
- 暴露 skill catalog。

### SkillRouter
根据：

- task_type；
- market；
- industry；
- report_type；
- verifier gaps；
- agent role；

动态选取 skill。

---

## 7.5 Skill 评测

每个 Skill 都应有：

- unit test；
- sample input / expected output；
- regression case；
- 失败原因；
- 版本号。

例如：

- citation audit skill：unsupported claim recall；
- numeric audit skill：数字错误检出率；
- valuation skill：方法选择准确率；
- gap routing skill：路由准确率。

---

# 8. 核心机制五：Observability 与 Review

## 8.1 为什么要强化可观测性

项目要从“能跑”升级到“能改、能解释、能证明”。

要回答：

- 哪个 Agent 耗时最多？
- 哪个 Tool 最常失败？
- 哪类 Gap 最常出现？
- 返工是否真提升质量？
- 新增 Skill 是否有效？
- Multi-Agent 是否比 Workflow 更好？

---

## 8.2 建议新增观测项

### Agent 级
- agent_name；
- start_time / end_time；
- input tokens；
- output tokens；
- cost；
- status；
- produced_artifacts。

### Tool 级
- tool_name；
- arguments；
- schema_valid；
- success/error；
- latency；
- result_size。

### Message 级
- sender；
- receiver；
- message_type；
- payload_summary；
- triggered_task_id。

### Gap 级
- gap_id；
- type；
- severity；
- detected_by；
- routed_to；
- resolved；
- resolution_rounds。

### Claim 级
- claim_id；
- status；
- evidence_ids；
- citation_ids；
- verification_result。

---

## 8.3 Review 机制

每次迭代都要做三类 review：

### A. Code Review
- 架构是否清晰；
- schema 是否一致；
- 是否引入隐式耦合；
- 是否破坏现有产物。

### B. Agent Behavior Review
- 是否真的动态路由；
- 是否出现无意义协商；
- 是否 agent 数量变多但质量没提升；
- 是否产生死循环。

### C. Eval Review
- 指标是否变好；
- 是否牺牲耗时 / 成本；
- 是否只优化了 easy cases；
- hard cases 是否改善。

---

# 9. 分阶段实施路线

## Phase 0：固化现状与建立 baseline
目标：

- 先把当前版本固定成 baseline；
- 形成可重复 eval harness；
- 避免边改边丢失对比基准。

交付物：

- baseline runner；
- fixed eval cases；
- eval metrics；
- current workflow baseline result。

---

## Phase 1：GapRouter 与精准返工
目标：

- 不改变所有 Agent；
- 先让 Verifier 发现的问题能精准路由；
- 建立 gap schema。

交付物：

- `gap_schema.py`
- `gap_router.py`
- `rework_trace.json`
- gap-resolution eval。

---

## Phase 2：消息协议与 TaskBoard
目标：

- 从“函数式串行调用”转向“Agent 间显式协作”；
- 建立消息类型和状态机。

交付物：

- `agent_message.py`
- `task_board.py`
- `agent_messages.jsonl`
- `task_board.json`

---

## Phase 3：动态 Router 与多轮协商
目标：

- 下一步执行不再只由固定 graph 决定；
- 可基于 gap / task board / budget 动态选择 agent。

交付物：

- `dynamic_router.py`
- negotiation loop；
- max_round / budget guard；
- route accuracy eval。

---

## Phase 4：Adjudicator 与冲突解决
目标：

- 面对来源冲突、Agent 判断冲突时，能裁决或保留不确定性。

交付物：

- `adjudicator_agent.py`
- conflict schema；
- conflict resolution eval。

---

## Phase 5：Memory 体系
目标：

- working memory；
- episodic memory；
- domain memory；
- context packer。

交付物：

- `memory_store.py`
- `context_packer.py`
- memory snapshots；
- memory effectiveness ablation。

---

## Phase 6：SkillRegistry 与领域 Skill
目标：

- 把高复用领域能力沉淀成 skill；
- 支持动态加载；
- 支持 skill-level eval。

交付物：

- `skills/`
- `skill_registry.py`
- `skill_router.py`
- skill tests。

---

## Phase 7：完整 Multi-Agent Eval 与简历级成果沉淀
目标：

- 跑 baseline；
- 做 ablation；
- 汇总指标；
- 形成可写进简历的量化结果。

交付物：

- `baseline_comparison.json`
- `ablation_study.md`
- `final_eval_report.md`
- 简历项目 bullet；
- 面试问答稿。

---

# 10. 最终验收标准

当满足以下条件时，项目可以说已经从 workflow 升级成了更完整的 multi-agent system：

## 10.1 架构验收
- 有显式 agent message 协议；
- 有 task board / blackboard；
- 有 dynamic routing；
- 有 gap-based rework；
- 有 conflict adjudication；
- 有 memory；
- 有 skill routing。

## 10.2 质量验收
- Multi-Agent 版本相较 current workflow，在固定 eval set 上：
  - Task Completion Rate 提升；
  - Citation Support Rate 提升；
  - Numeric Audit Pass Rate 提升；
  - Gap Resolution Rate 提升；
  - 代价增加可控。

## 10.3 工程验收
- 所有核心流程可观测；
- 所有产物可回溯；
- 每次改动可回归评测；
- 指标可复现。

## 10.4 简历验收
到这个阶段，简历就可以真实地写：

- 构建金融多智能体研究系统；
- 实现基于 gap 的动态路由与多轮返工；
- 引入消息协议、任务黑板、冲突裁决；
- 搭建 baseline / eval harness；
- 基于固定 case 集验证多 Agent 架构相对 workflow 的收益。

---

# 11. 不要走偏的原则

1. **不要为了“多智能体”做无意义群聊。**
2. **不要让所有 Agent 都拥有无限自由度。**
3. **不要在没有 baseline 前写提升百分比。**
4. **不要把 task-state memory 乱写成用户长期记忆。**
5. **不要把 Skill 当概念贴纸，必须是可加载、可测试、可版本化。**
6. **不要只测最终报告，不测 Agent 中间行为。**
7. **不要只看质量，不看 token、耗时、返工成本。**
8. **不要为了架构炫技牺牲金融事实可信度。**

---

# 12. 一句话总结

> 这个项目的最终目标，是把当前“可控的金融研报 Agent Workflow”，升级为“具备显式协作、动态路由、缺口补全、冲突裁决、Memory 与 Skill 沉淀、并能通过系统 Eval 证明其价值的金融 Multi-Agent Deep Research 系统”。
