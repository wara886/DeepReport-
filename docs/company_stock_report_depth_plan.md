# 公司/个股研报深化落地方案

## 0. 当前决策

下一阶段只聚焦一个方向：公司/个股研报。

暂时不扩展宏观策略研报、行业专题研报和跨资产报告。原因是公司/个股研报最适合把赛题要求拆成可验证的工程闭环：数据源权威性、财务数字准确性、多模态图文一致性、估值建模严谨性、Agent 自主补证能力，都可以围绕同一家公司、同一报告期形成固定测试集和可复跑 harness。

目标不是把报告写得更长，而是让系统能稳定输出一份接近专业卖方研报结构的 evidence-driven company research report。

## 0.1 优先级顺序与逐步验收

后续按下面顺序推进。每完成一个模块，都必须同时满足“代码落地、测试通过、文档更新、git 发布仓库更新”四个条件。

| 优先级 | 模块 | 目的 | 必须产物 | 检验标准 |
| --- | --- | --- | --- | --- |
| P0 | SourceAuthorityPolicy | 先解决数据源是否权威，给后续数字、图表、估值建立可信底座 | `src/data/source_authority.py`、证据 authority 字段、测试 | SEC/交易所/公司 IR 被标为 primary；Yahoo/AkShare/TuShare/Wind-style 行情源被标为 market_data；新闻/搜索 snippet 不能支撑核心财务结论 |
| P1 | Table/Chart/Visual schema | 解决多模态对象没有统一契约的问题 | `src/schemas/table.py`、`src/schemas/multimodal.py`、`tables.json`/`charts.json` 契约 | 图表必须引用 table/claim/source；缺 lineage 的图表无法通过 verifier |
| P2 | Financial table lineage | 让三表和核心指标都能追溯到表格/证据 | `financial_metrics.json`、`table_numeric_audit` | revenue、net_income、gross_margin、free_cash_flow 有 period、unit、source_table_id、source_evidence_id |
| P3 | Multimodal consistency verifier | 解决图文一致性 | `multimodal_consistency.py`、verifier issue | 正文趋势与图表趋势冲突时阻断；图表缺来源时阻断 |
| P4 | Relative valuation + simple DCF | 解决估值可复算 | `valuation_model.json`、`valuation_sensitivity.json` | P/E、P/S、DCF 的分子分母、假设、目标价可独立复算 |
| P5 | EvidenceGap routing | 增强 Agent 自主性 | `EvidenceGap`、`gap_router`、`gap_resolution_trace.jsonl` | 缺 primary evidence 时自动回到 Research/Browser；补证失败则降级结论 |
| P6 | Company report harness | 形成赛题式总分 | `authority_score`、`numeric_lineage_score`、`multimodal_consistency_score`、`valuation_reproducibility_score` | 每次 demo 能输出模块化评分和失败原因 |

当前立即执行 P0。P0 完成后才进入 P1，避免在没有权威来源分层的情况下继续堆图表和估值。

### 当前执行进度

| 模块 | 状态 | 最近提交 | 验证 |
| --- | --- | --- | --- |
| P0 SourceAuthorityPolicy | 已完成 | `751af9b` | `tests/test_source_authority_policy.py`、search/feature/multi-agent 核心回归通过 |
| P1 Table/Chart/Visual schema | 已完成 | `bf018a0` | `tests/test_schemas.py` 加入 TableArtifact、ChartArtifact、VisualEvidence 和 chart lineage audit 回归 |
| P2a 核心财务指标 lineage builder | 已完成 | `4669002` | `tests/test_feature_layer.py` 覆盖 revenue、net_income、gross_margin、free_cash_flow 的 source_table/source_evidence lineage |
| P2b DeepAnalyzeAgent 输出 financial_metrics/tables | 已完成 | 待提交 | `DeepAnalyzeAgent` 输出 `financial_metrics`/`tables`，`MultiAgentOrchestrator` 落盘 `financial_metrics.json`/`tables.json`；multi-agent 回归覆盖非空指标 lineage |

## 1. 目标研报形态

一份合格的公司/个股研报至少包含以下章节：

1. 投资摘要与核心结论
2. 公司概况、主营业务与收入结构
3. 股权结构、治理与管理层
4. 行业位置与竞争格局
5. 三张财务报表摘要与关键指标
6. 增长驱动、利润率、现金流与资本开支分析
7. 同行对比与相对估值
8. DCF 或多情景估值
9. 风险因素与敏感性分析
10. 参考来源、数据口径、免责声明

每个事实性段落必须能回溯到 `evidence_id`；每个关键数字必须能回溯到原始表格、公告、API 响应或结构化数据行；每张图必须能回溯到生成它的数据字段。

## 2. 多模态要求怎么解决

这里的多模态不应只理解为“报告里有图”。对公司研报来说，多模态至少包括四层：

1. 文本：报告段落、claim、引用、风险提示。
2. 表格：三张报表、分业务收入、同行对比、估值假设。
3. 图表：收入/利润趋势、利润率、现金流、估值敏感性、同行倍数。
4. 原始材料：PDF 年报/季报、公告网页、新闻稿截图或网页正文。

### 2.1 数据对象设计

新增或固化三个结构：

```text
TableArtifact
  table_id
  source_evidence_id
  source_url
  source_page
  table_type: income_statement|balance_sheet|cash_flow|segment|peer|valuation
  rows
  columns
  period
  currency
  extraction_method
  confidence

ChartArtifact
  chart_id
  chart_type
  input_table_ids
  input_claim_ids
  source_fields
  output_path
  alt_text
  consistency_status

VisualEvidence
  evidence_id
  source_url
  page_number
  image_path
  ocr_text
  linked_table_ids
```

这些对象不能只存在于 HTML 里，而要落盘到：

```text
data/outputs/multi_agent/tables.json
data/outputs/multi_agent/charts.json
data/outputs/multi_agent/visual_evidence.json
data/outputs/multi_agent/chart_consistency.json
```

### 2.2 图文一致性校验

`VerifierAgent` 需要新增 `multimodal_consistency` 检查：

1. 报告正文提到的图表编号必须存在于 `charts.json`。
2. 图表标题、纵轴单位、period、currency 必须与输入表格一致。
3. 图表里的最大值、最小值、同比方向不能与正文 claim 冲突。
4. 关键图表必须能追溯到 `input_table_ids` 和 `source_evidence_id`。
5. 图表如果由 fallback 或估算数据生成，报告必须显式标注“估算/样例/未审计/非公司披露”。

### 2.3 第一阶段要做的图表

先做 5 类公司研报最常用图表：

1. `revenue_profit_trend`：收入、营业利润、净利润趋势。
2. `margin_trend`：毛利率、营业利润率、净利率趋势。
3. `cashflow_capex`：经营现金流、自由现金流、资本开支。
4. `segment_revenue_mix`：分业务或分地区收入结构。
5. `valuation_sensitivity`：WACC/terminal growth 或 P/E/EPS 情景敏感性。

验收标准：每张图都有 `chart_id`、`input_table_ids`、`source_fields`、`period`、`unit`，并被 verifier 检查。

## 3. 实时权威数据源怎么解决

数据源分成三层，不要把所有来源混在一个 search engine 里。

### 3.1 第一层：权威披露源

优先级最高，用来支撑财务数字和公司基本面。

美股方向：

1. SEC EDGAR company facts / submissions / filing documents。
2. 公司 Investor Relations 页面。
3. 公司 10-K、10-Q、8-K、earnings release、presentation。
4. Nasdaq/NYSE 公司资料和交易所公告。

A 股方向：

1. 巨潮资讯公告。
2. 上交所、深交所、北交所公告。
3. 公司官网投资者关系。
4. 财报 PDF、年度报告、季度报告。

这一层必须输出结构化 `authority_level=primary`，并且进入关键财务数字的优先证据池。

### 3.2 第二层：行情和估值数据

用于行情、股本、市值、EV、beta、交易量、同行倍数。

可选方案：

1. Yahoo Finance：无 key，适合 demo 和美股行情快照。
2. Alpha Vantage / Polygon / IEX Cloud：适合行情和基础财务指标。
3. AkShare / TuShare：适合 A 股公开行情和部分财务数据。
4. Wind / Choice / 同花顺 iFinD：如果后续有账号，作为专业数据源插件接入。

这一层输出 `market_snapshot`、`share_count`、`market_cap`、`enterprise_value`、`peer_multiples`，必须记录 `as_of_date`。

### 3.3 第三层：新闻和事件源

用于事件解释、风险提示和短期催化。

可用来源：

1. 公司新闻稿和公告。
2. 交易所问询函、监管公告。
3. Reuters、CNBC、Business Wire、PR Newswire 等公开新闻源。
4. Tavily/Serper/Metaso/Sogou 作为检索入口，但不能直接等同于权威证据。

这一层输出 `authority_level=secondary` 或 `tertiary`，除非新闻来自公司或交易所原始公告。

### 3.4 数据源工程改造

新增 `SourceAuthorityPolicy`：

```text
source_url/domain -> source_type -> authority_level -> allowed_claim_types
```

规则示例：

1. SEC、交易所、公司 IR 可以支撑财务数字、公告事实、管理层表述。
2. Yahoo Finance 可以支撑行情、市值、价格、交易量，但不能单独支撑财报核心数字。
3. 新闻源可以支撑事件背景，但不能单独支撑收入、净利润、现金流等核心财务结论。
4. 搜索结果 snippet 默认只能作为候选证据，必须经过 Browser/PDF 正文抽取后才能进入高置信证据池。

验收标准：`claims.json` 中每条 claim 都有 `source_authority_level`，关键财务 claim 必须至少有一个 `primary` evidence。

## 4. 专业研报深度怎么补齐

### 4.1 公司画像

补齐字段：

1. 公司全称、ticker、交易所、行业、GICS/申万行业。
2. 主营业务、产品线、收入分部、地区分布。
3. 上下游、核心客户、供应商风险。
4. 股权结构、实际控制人、机构持股。
5. 董事会、管理层、薪酬激励、回购和分红。

落地方式：

```text
src/data/company_profile_enrichment.py
src/features/company_profile_features.py
```

输出：

```text
analysis_artifacts.company_profile
analysis_artifacts.segment_breakdown
analysis_artifacts.governance_profile
```

### 4.2 财务分析

先固定 20 个核心指标：

1. revenue
2. gross_profit
3. operating_income
4. net_income
5. diluted_eps
6. gross_margin
7. operating_margin
8. net_margin
9. revenue_yoy
10. net_income_yoy
11. operating_cash_flow
12. capex
13. free_cash_flow
14. cash_and_equivalents
15. total_debt
16. net_debt
17. current_ratio
18. debt_to_equity
19. ROE
20. ROIC

每个指标必须有：

```text
metric_name
value
unit
period
source_table_id
source_evidence_id
calculation_formula
confidence
```

### 4.3 行业位置与同行对比

同行选择不能靠写死。需要新增 peer selection 规则：

1. 同交易所/同市场优先。
2. 同 GICS/申万行业优先。
3. 相近市值区间优先。
4. 相近业务描述 embedding 相似度辅助。
5. 明显业务不一致的公司进入 excluded_peers，并记录原因。

输出：

```text
peer_set.json
peer_comparison_table.json
peer_selection_rationale.md
```

报告中必须说明“为什么选这些同行”。

## 5. 如何完善严谨建模

估值不要一步到位追求复杂，先做可审计的两条线。

### 5.1 相对估值模型

第一版支持：

1. P/E：price / forward EPS 或 market cap / net income。
2. P/S：market cap / revenue。
3. EV/EBITDA：enterprise value / EBITDA。
4. P/B：market cap / book value。

关键要求：

1. 每个倍数必须记录分子、分母、period、currency、source。
2. 同行倍数必须去极值或标注异常值。
3. 输出 median、mean、25/75 percentile。
4. 目标价不能只给一个点，要给 bear/base/bull 三情景。

### 5.2 DCF 模型

第一版 DCF 只做 5 年显式预测 + terminal value：

```text
Revenue forecast
  -> EBIT margin
  -> tax rate
  -> NOPAT
  -> D&A
  -> capex
  -> working capital change
  -> free cash flow
  -> WACC discount
  -> terminal value
  -> enterprise value
  -> equity value
  -> target price
```

必要假设：

1. revenue CAGR
2. terminal growth
3. EBIT margin
4. tax rate
5. WACC
6. capex/revenue
7. working capital/revenue
8. shares outstanding
9. net debt

输出：

```text
valuation_model.json
valuation_assumptions.json
valuation_sensitivity.json
```

### 5.3 模型严谨性校验

`VerifierAgent` 增加 valuation checks：

1. 目标价 = equity value / shares outstanding。
2. enterprise value = PV(FCF) + PV(terminal value)。
3. equity value = enterprise value - net debt + non-operating assets。
4. terminal growth 不能高于长期名义 GDP 的合理上限，默认警戒线 5%。
5. WACC 不能低于无风险利率，默认警戒线 4%。
6. bull/base/bear 情景必须方向一致：bull target >= base target >= bear target。
7. 估值结论必须标注“模型假设，不构成投资建议”。

## 6. Agent 自主性怎么继续增强

当前闭环主要是：

```text
Verifier -> FinalAnswer rework
```

下一阶段要升级成：

```text
Verifier -> Research/Browser补证 -> Analyze重算 -> FinalAnswer改写 -> Verifier复核
```

### 6.1 新增 EvidenceGap 对象

`VerifierAgent` 不只返回错误文本，而要返回结构化缺口：

```json
{
  "gap_id": "gap_revenue_2025q4_primary_source",
  "gap_type": "missing_primary_evidence",
  "claim_id": "claim_revenue_growth",
  "required_source_type": ["10-Q", "earnings_release", "company_ir"],
  "required_fields": ["revenue", "period", "currency"],
  "suggested_queries": [
    "AMD 2025 Q4 revenue earnings release",
    "Advanced Micro Devices 2025 Form 10-Q revenue"
  ],
  "blocking": true
}
```

### 6.2 Orchestrator 调度升级

`MultiAgentOrchestrator` 增加 rework route：

1. 如果是缺引用、缺证据，回到 `DeepResearcherAgent`。
2. 如果是网页/PDF 没抽干净，回到 `BrowserAgent`。
3. 如果是数字不一致或估值错误，回到 `DeepAnalyzeAgent`。
4. 如果只是文字表达、章节缺失，回到 `FinalAnswerAgent`。

每次返工写入：

```text
revision_history.json
gap_resolution_trace.jsonl
```

### 6.3 Agent 自主补证终止条件

为了避免无限循环，设置硬约束：

1. 每个 gap 最多补证 2 次。
2. 每轮新增 evidence 最多 10 条。
3. primary evidence 仍缺失时，报告必须降级结论，不允许硬写财务结论。
4. 关键财务 claim 如果只有 secondary evidence，claim status 标为 `qualified`。
5. blocking gap 未解决，`verification_passed=false`。

### 6.4 并行化方向

公司研报里可以并行的任务：

1. 公司公告检索。
2. 新闻/事件检索。
3. 行情和估值数据获取。
4. 同行数据获取。
5. PDF 表格抽取。

`dynamic scheduler` 后续支持 ready task 并行执行，但同一 `state` 写入必须通过 `merge_task_result` 统一归并，避免多个 Agent 同时覆盖 `claims` 或 `evidence`。

## 7. 分阶段实施路线

### Phase 1：公司研报数据底座

新增：

```text
src/data/source_authority.py
src/data/filing_fetchers.py
src/data/company_profile_enrichment.py
src/schemas/table.py
```

目标：

1. SEC/公司 IR/交易所公告进入 primary evidence。
2. Yahoo/AkShare/TuShare/Wind-style adapter 统一行情字段。
3. `evidence.json` 增加 `authority_level`、`as_of_date`、`source_document_type`。

验收：

1. AMD/AAPL/NVDA 至少 3 家公司能生成 primary evidence。
2. 核心财务数字不再由新闻或 search snippet 单独支撑。

### Phase 2：三表与指标

新增：

```text
src/data/financial_table_extractor.py
src/features/financial_modeling.py
src/evaluation/table_numeric_audit.py
```

目标：

1. income statement、balance sheet、cash flow schema 固定。
2. 20 个核心指标全部带 source lineage。
3. numeric audit 从 claim 级扩展到 table cell 级。

验收：

1. revenue、net_income、gross_margin、free_cash_flow 支持 period gate。
2. Q3 数字不能写成 Q4 结论。
3. 单位、币种、期间冲突会被 verifier 拦截。

### Phase 3：估值建模

新增：

```text
src/features/relative_valuation.py
src/features/dcf_model.py
src/evaluation/valuation_audit.py
```

目标：

1. 相对估值输出 peer multiples。
2. DCF 输出 assumptions、forecast、sensitivity。
3. 目标价和估值区间可复算。

验收：

1. valuation_model.json 可独立复算。
2. sensitivity chart 与 valuation_sensitivity.json 一致。
3. verifier 能发现 WACC、terminal growth、shares outstanding 异常。

### Phase 4：多模态一致性

新增：

```text
src/report/table_renderer.py
src/evaluation/multimodal_consistency.py
```

目标：

1. 报告图表、表格、正文 claim 三者有共同 lineage。
2. 图表生成使用 TableArtifact，不直接从自由文本抽数。
3. HTML 报告展示图表、表格、引用、数据口径。

验收：

1. chart_consistency.json 包含每张图的 pass/fail。
2. 正文说“收入上升”但图表下降时 verifier 拦截。
3. 图表缺来源时 `verification_passed=false`。

### Phase 5：自主补证闭环

新增：

```text
src/agents/evidence_gap.py
src/agents/gap_router.py
src/evaluation/gap_resolution_audit.py
```

目标：

1. Verifier 输出 EvidenceGap。
2. Orchestrator 按 gap_type 回路由到 Research/Browser/Analyze/Writer。
3. 补证过程可审计。

验收：

1. 缺 primary evidence 时自动补采。
2. 补采失败时报告降级，而不是编造结论。
3. `gap_resolution_trace.jsonl` 能解释每个缺口如何处理。

## 8. 最小可交付版本

第一轮不要同时做完所有能力。建议最小交付版本只覆盖：

1. AMD、AAPL、NVDA 三家公司。
2. 10-K/10-Q 或 earnings release primary evidence。
3. revenue、net_income、gross_margin、free_cash_flow 四个核心指标。
4. revenue/profit trend、margin trend、valuation sensitivity 三类图。
5. P/E、P/S 相对估值和一个简化 DCF。
6. Verifier 能拦截主体错配、period 错配、primary evidence 缺失、图文不一致。

这版做完后，项目就能明确回答赛题里最关键的质疑：

```text
数据是否权威？
数字是否准确？
图表是否可信？
估值是否可复算？
Agent 是否能发现问题并自主补证？
```

## 9. 近期任务清单

1. 新增 `SourceAuthorityPolicy`，把 SEC/交易所/公司 IR/Yahoo/新闻源分层。
2. 固化 `TableArtifact`、`ChartArtifact`、`VisualEvidence` schema。
3. 把 `DeepAnalyzeAgent` 的财务指标输出改成带 `source_table_id` 和 `source_evidence_id`。
4. 新增 `valuation_model.json` 和简化 P/E、P/S、DCF 输出。
5. 给 `VerifierAgent` 增加 `missing_primary_evidence`、`period_mismatch`、`chart_claim_conflict`、`valuation_formula_error` 四类 blocking issue。
6. 新增 `EvidenceGap` 和 gap route 设计，先实现缺证据回到 Research/Browser 的一条闭环。
7. 扩展 harness：每份报告输出 `authority_score`、`numeric_lineage_score`、`multimodal_consistency_score`、`valuation_reproducibility_score`、`gap_resolution_score`。
