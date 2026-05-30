# DeepReport Plus：前端 / 后端 / 算法质量闭环修复 Plan

plan:
DeepReport_plus UI & Report Quality Enhancement Plan
Context
The DeepReport_plus project is a multi-agent financial research report system that works but has three intertwined issues: (1) its chat entry UI mixes developer debugging info (quality gates, LLM reviews, tool traces) into the user experience, (2) generated HTML reports lack professional polish compared to the DeepReport_official_run's output, and (3) the quality/RAG pipeline has known gaps identified in the existing fix plan at docs/deepreport_ui_quality_rag_fix_plan.md. After comparing both projects' report output and UI code, this plan synthesizes what to fix and in what order.

Phase 1: UI Separation (User Mode vs Developer Mode)
Current State
G:\cord\DeepReport_plus\src\app\web_ui.py has a single render_index_html() (line 2324) that shows both user chat and developer diagnostics
Developer panel is collapsed under <details class="developer"> labeled "开发者诊断"
Critical issue: buildResultText() (line 2710) in JavaScript always shows 事实校验, 客观评分, LLM 复核, 交付状态, and topIssues() in chat bubbles — even to end users
load_run_payload() (line 712) returns the full payload with ALL debug data, no filtering
Required Changes
1.1 Create sanitize_payload_for_user() in web_ui.py

New function that strips: delivery_gate, quality_report, llm_quality_review, verification_report, quality_remediation_plan, agent_collaboration_trace, research_blackboard, tool_trace, delivery_rework_history, search_meta, trace, mcp_manifest, pdf_manifest, pdf_sections, revision_history, rejected_metrics, claim_rejection_report, source_health
Returns only: summary (safe fields), answer, report_links, report_html_url, citations (count + summary only), charts (public), run_id, report_markdown
1.2 Create payload_for_mode() dispatcher

Routes to sanitize_payload_for_user() by default
Returns full payload when mode=developer
1.3 Modify _handle_chat() response (line 265-590)

After getting result from orchestrator, pass through payload_for_mode()
User mode responses only contain: natural language answer, report_links, citations summary, public status
No verification/quality/gate data in the chat bubble
1.4 Modify renderChatAnswer() JS function (line 2702)

Remove call to buildResultText() for user mode
Instead show: generation status indicator, report link button, source count
Developer mode still shows full buildResultText() output
1.5 Modify buildResultText() JS function (line 2710)

Keep for developer mode
User mode gets a simpler version: report object + symbol/period + link to report
Files to modify:

G:\cord\DeepReport_plus\src\app\web_ui.py (lines ~265-590, ~700-760, ~2324-2864)
Phase 2: Report Link Delivery (file:// + Web URL)
Current State
Only report_html_url (a single string) returned in payload (web_ui.py line 720)
No html_file_url, markdown_web_url, or json_web_url
No build_report_links() function exists
Required Changes
2.1 Create build_report_links() in web_ui.py

def build_report_links(output_dir: Path, report_dir: Path) -> dict:
    report_html = report_dir / "report.html"
    report_md = report_dir / "report.md"
    report_json = report_dir / "report.json"
    return {
        "html_web_url": artifact_url(report_html),
        "html_file_url": report_html.resolve().as_uri() if report_html.exists() else "",
        "markdown_web_url": artifact_url(report_md),
        "json_web_url": artifact_url(report_json),
        "local_report_dir": str(report_dir.resolve()),
    }
2.2 Add report_links to load_run_payload() response (line 712)

Call build_report_links() and include in payload
2.3 Update _handle_chat() report_run response (line ~505-571)

Include report_links in the JSON response
The answer field should say "报告已生成，可点击查看 HTML 研报" with the link
2.4 Update JavaScript frontend (line ~2702-2725)

In renderChatAnswer(): when data.report_links exists, render clickable links
Show html_web_url as a primary button ("打开研报")
Show html_file_url as secondary text (file path for manual opening)
Add download buttons for MD and JSON formats
2.5 Modify renderReport() JS (line 2758)

Show the file:// path in a copyable text field below the iframe
Add "在浏览器中打开" button for the html_web_url
Files to modify:

G:\cord\DeepReport_plus\src\app\web_ui.py (add function ~line 760, modify ~505-590, ~2702-2766)
Phase 3: Professional Report HTML Template
Current State
G:\cord\DeepReport_plus\src\report\html_report_generator.py (194 lines) produces simple output
No cover page, no TOC, no print CSS, no professional styling
Debug phrases like "暂无充足的可验证证据" appear in content
White/teal minimal theme — no gradient headers or polished card layouts
What to learn from DeepReport_official_run's HTML template (G:\cord\DeepReport_official_run\src\report\html_generator.py)
Their template (Jinja2-based) has these valuable patterns:

Gradient header: linear-gradient(135deg, #667eea 0%, #764ba2 100%) with confidence score card in the right column
Bootstrap 5 for responsive layout, nav-tabs, cards, badges
Font Awesome icons on every section heading
Color-coded callout boxes: blue for executive summary, green/orange/red for risk levels
Tabbed chart navigation: Bootstrap nav-tabs with purple accent styling
Citation blocks: 3px blue left border, numbered APA-style
Metric cards: pink gradient, white text, large numeric display
Search result grid: 2-column card grid with View Source buttons
Professional footer: Report ID, version, dark background
Double-click chart download: canvas dblclick event → PNG download
Required Changes
3.1 Enhanced render_professional_html_report() in html_report_generator.py

Add Bootstrap 5 + Font Awesome CDN (like the official report)
Cover section: company name, ticker, report period, generation time, confidence badge
Table of contents (generated from h2 headings)
Tabbed chart navigation (matching official report's pattern)
Color-coded risk assessment cards
Professional citations section with numbered blocks
Print CSS stylesheet
Light theme (for readability/print) — the official report's light theme is better for reports
Gradient header pattern from official report
Smooth scroll for anchor links
3.2 Content validation before rendering

Scan the rendered markdown for banned debug phrases: "暂无充足的可验证证据", "PDF section:", "本节暂无", "待补", "框架性", "N/A"
Move sections with only debug content to a "数据缺口与降级说明" appendix
Never show debug/tool language in final report
3.3 Chart rendering improvement

Learn from official report's chart.js pattern: tab-per-chart, 400px containers, datalabels plugin
Ensure chart data structure matches what ChartRenderer expects (currently there's a mismatch: flat labels+values vs nested datasets array)
Files to modify:

G:\cord\DeepReport_plus\src\report\html_report_generator.py (major rewrite)
G:\cord\DeepReport_plus\src\report\chart_generator.py (fix dataset format)
Phase 4: Plan Document Assessment
The existing plan at G:\cord\DeepReport_plus\docs\deepreport_ui_quality_rag_fix_plan.md is largely correct and comprehensive but has these gaps:

What it gets right:

✅ UI split diagnosis (developer info leaking to users)
✅ Report link problem (no file:// or structured links)
✅ ClaimEvidenceBundle concept (claims must be grounded to evidence)
✅ Derived Evidence for internal models (valuation, metrics, charts as traceable evidence)
✅ CompanyPeriodQualityProfile (different companies/periods need different handling)
✅ Valuation Policy (P/E not for loss-making companies, no DCF for financial companies)
✅ Banned debug phrases in reports
✅ Issue-type-specific repair routing (not all problems need full re-run)
✅ Final rework loop must re-run gate checks
What's missing or unclear:

Gap	Detail	Impact
No template rendering architecture	Plan says "enhance standalone HTML template" but doesn't say who generates it (FinalAnswer vs post-process)	Need to clarify: post-process step in orchestrator, not agent output
No coverage detection mechanism	CompanyPeriodQualityProfile needs to know if source coverage is full/partial/missing — but HOW?	Need to add: data collection stage scores coverage, not hardcoded
No prompt changes	Evidence grounding changes imply FinalAnswer prompt rewrite — not included	Must update FinalAnswer system prompt
No error states	What if user mode report generation fails? Empty report_links?	Add error handling: report_links.error, report_links.status
No performance consideration	Derived evidence increases storage/IO for long agent traces	Acceptable for now; optimize later if needed
Agreement with the plan's approach: The plan's 5-task breakdown is sound. Task 1 (UI) and Task 2 (HTML template) should be done first as they're the most visible. Task 3 (ClaimEvidenceBundle) and Task 4 (CompanyPeriodQualityProfile) are deeper algorithmic work. Task 5 (repair routing) depends on the foundation from Tasks 3 and 4.

Recommended execution order:

Phase 1 (UI separation) — quick wins, immediate UX improvement
Phase 2 (report links) — productization, complements Phase 1
Phase 3 (HTML template) — visual polish, learn from official run
Phase 4 (ClaimEvidenceBundle + Derived Evidence) — deep algorithmic fix
Phase 5 (CompanyPeriodQualityProfile + Valuation Policy) — coverage-aware generation
Phase 6 (Issue-type repair routing) — final quality loop optimization
Phases 1-3 address the user-facing/product issues. Phases 4-6 address the underlying quality/RAG issues that cause generic content.

Verification Plan
UI separation: Access / (or default route) — should show only chat + report links, no quality gates or tool traces. Access ?mode=dev or /dev — should show all debug panels.
Report links: After report generation, verify report_links contains html_web_url (clickable in browser), html_file_url (file:/// path), and local_report_dir. Open the file:// path in a browser — should display the report.
HTML template: Open the generated report.html — should have gradient header, TOC, tabbed charts, professional citations, print CSS. No debug phrases visible.
Chart rendering: Charts should display actual data (not empty datasets as in the official run).
Content quality: Generated report should contain company-specific financial data, not generic boilerplate.
Critical Files Reference
File	Role
G:\cord\DeepReport_plus\src\app\web_ui.py	Main UI — HTML template, chat handler, payload loading, JS frontend (3137 lines)
G:\cord\DeepReport_plus\src\report\html_report_generator.py	Professional HTML report renderer (194 lines, needs enhancement)
G:\cord\DeepReport_plus\src\report\chart_generator.py	Chart.js config generation (needs dataset format fix)
G:\cord\DeepReport_plus\src\app\api_fastapi.py	FastAPI endpoints (may need mode routing)
G:\cord\DeepReport_plus\src\agents\multi_agent_orchestrator.py	Orchestrator — report generation pipeline, quality loops (3099 lines)
G:\cord\DeepReport_plus\src\evaluation\delivery_gate.py	Delivery gate logic
G:\cord\DeepReport_plus\docs\deepreport_ui_quality_rag_fix_plan.md	Existing plan document (reference, will be superseded by implementation)
G:\cord\DeepReport_official_run\src\report\html_generator.py	Official run's Jinja2 HTML template (reference for visual design patterns)
G:\cord\DeepReport_official_run\reports\financial_report_20260529_205325.html	Official generated report (visual reference for the target look)

p1-p3看一下代码部分是不是已经修复完成？





## 0. 目标

当前 DeepReport Plus 不是“多智能体没跑通”，而是存在三类混在一起的问题：

1. **产品形态问题**：本地开发者界面和终端用户界面混在一起，用户会看到质量门禁、LLM 复核、Tool Calls、Agent Timeline 等开发调试信息。
2. **报告交付问题**：生成完成后，用户应得到一个可直接打开的 HTML 研报链接，而不是只在后台 artifacts 里存在 `report.html`。
3. **质量闭环问题**：不同公司、不同时间段会触发不同 LLM review / delivery gate blocker，不能只修 TSLA 或某一个季度，必须建立通用 issue taxonomy、claim-level grounding、derived evidence、降级和定向返工机制。

---

## 1. HTML / UI 差异判断

> 注意：当前没有直接读取 `G:\cord\DeepReport_official_run\reports\financial_report_20260527_122902.html` 的文件内容，因此这里不是逐行 diff，而是基于你描述的 official report HTML 形态、当前 DeepReport Plus Web UI 代码和你截图中的界面状态做的产品层对比。

### 1.1 official_run HTML 的优点，应该借鉴

从你给的 `file:///G:/cord/DeepReport_official_run/reports/financial_report_20260527_122902.html` 这种形态来看，它更像一个**可独立交付的静态研报 HTML**。它的优点大概率包括：

- 双击即可打开，不依赖开发者工作台；
- 用户看到的是完整研报，而不是调试仪表盘；
- 适合作为最终交付物保存、分享、归档；
- 文件路径明确，用户知道“报告已经生成在哪里”；
- UI 重点是排版、章节、表格、图表、参考来源，而不是 Agent trace。

### 1.2 DeepReport Plus 当前 UI 的问题

当前 Web UI 更像一个**本地开发者工作台**，会把以下信息一起暴露出来：

- 客观评分；
- 客观门禁；
- LLM 复核；
- 交付门禁；
- blocker / warning；
- Tool Calls；
- Agent Timeline；
- Rework Rounds；
- search_meta / evidence / claims / tool_trace 等 artifacts。

这些对开发者有价值，但对普通用户是噪声。普通用户只需要：

- 像聊天机器人一样提问；
- 看到生成进度的自然语言提示；
- 生成完成后拿到“查看 HTML 研报 / 下载报告 / 查看来源摘要”的入口；
- 不需要知道 delivery gate 是 true 还是 false。

---

## 2. 前端需要解决的问题与方案

### 2.1 问题 A：用户端和开发者端混在一起

#### 现象

用户界面显示了质量门禁、Tool Calls、Agent Timeline、rework round、debug issue。这些内容应该属于本地开发者模式。

#### 解决方案

拆成两个 UI 模式：

1. **User Mode / Chat Mode**
   - 路径：`/` 或 `/chat`
   - 只显示聊天窗口、生成状态、报告卡片、报告链接、来源摘要。
   - 不显示：quality gate、LLM review、Tool Calls、Agent Timeline、raw JSON、debug traces。

2. **Developer Mode / Dev Console**
   - 路径：`/dev` 或 `?mode=dev`
   - 显示所有质量门禁、tool trace、Agent timeline、source health、rework history、artifacts。
   - 仅本地可见，或由 `APP_EXPOSE_DEV_UI=true` 控制。

#### 前端验收

- 普通用户访问 `/` 看不到“客观门禁”“LLM 复核”“Tool Calls”。
- 开发者访问 `/dev` 可以看到所有调试信息。
- 同一份 run payload 进入前端前应经过 `sanitize_payload_for_user()` 过滤。

---

### 2.2 问题 B：生成完成后没有显式 HTML 研报链接

#### 现象

报告虽然生成了 `report.html`，但是用户没有明确收到一个可以点击或双击打开的研报链接。

#### 解决方案

生成完成后返回 `report_links`：

```json
{
  "report_links": {
    "html_web_url": "/artifacts/runs/20260527_xxx/reports/report.html?v=...",
    "html_file_url": "file:///G:/cord/DeepReport_plus/data/reports/multi_agent/runs/.../reports/report.html",
    "markdown_url": "/artifacts/runs/.../reports/report.md",
    "json_url": "/artifacts/runs/.../reports/report.json"
  }
}
```

其中：

- `html_web_url` 给浏览器点击；
- `html_file_url` 给本地双击/复制路径；
- `markdown_url` 用于导出；
- `json_url` 给开发者或系统集成。

#### 注意

浏览器安全策略可能限制网页直接打开 `file://`，所以用户端优先显示 `http://127.0.0.1:8787/artifacts/.../report.html`。同时在报告卡片里显示本地文件路径，方便用户去资源管理器双击。

---

### 2.3 问题 C：报告 HTML 排版还不够像正式研报

#### 解决方案

新增或增强 standalone report template：

- 顶部封面区：公司、ticker、报告期、生成时间、评级/降级状态；
- 左侧目录：执行摘要、业务概览、三表摘要、估值、风险、投资结论、数据缺口、参考来源；
- 正文区域：正式研报排版，不显示 debug；
- 图表卡片：关键指标、结论置信度、证据来源结构；
- 表格样式：财务三表、同行对比、估值敏感性；
- 引用样式：正文引用简洁，参考来源集中展示；
- 打印 CSS：支持浏览器打印为 PDF；
- 深色/浅色不要过度花哨，以可读性优先。

#### 不要借鉴的部分

- 不要把质量门禁直接塞进用户版 HTML；
- 不要把 Tool Calls、Agent Timeline、raw JSON 放入正式报告；
- 不要在正式报告中出现“PDF section 提示”“暂无充足证据”这类调试式语言。

---

## 3. 后端需要解决的问题与方案

### 3.1 问题 A：report artifact 已存在，但返回不够产品化

当前后端已有 `/artifacts/...` 的静态文件读取能力，也会在 `load_run_payload()` 中计算 `report_html_url`。需要把它产品化地返回给 `/api/chat` 和 `/api/run`。

#### 解决方案

新增函数：

```python
def build_report_links(output_dir: Path, report_dir: Path) -> dict:
    report_html = report_dir / "report.html"
    report_md = report_dir / "report.md"
    report_json = report_dir / "report.json"
    return {
        "html_web_url": artifact_url(report_html),
        "html_file_url": report_html.resolve().as_uri() if report_html.exists() else "",
        "markdown_web_url": artifact_url(report_md),
        "json_web_url": artifact_url(report_json),
        "local_report_dir": str(report_dir.resolve()),
    }
```

然后在报告生成完成 response 中加入：

```json
{
  "mode": "report_run",
  "answer": "报告已生成，可点击查看 HTML 研报。",
  "report_links": {...}
}
```

---

### 3.2 问题 B：用户 payload 没有过滤

#### 解决方案

新增：

```python
def sanitize_payload_for_user(payload: dict) -> dict:
    return {
        "summary": safe_summary,
        "answer": answer,
        "report_links": report_links,
        "report_status": public_status,
        "citations_summary": citations_summary,
        "charts": public_charts,
    }
```

开发者模式才返回完整 payload：

```python
def payload_for_mode(payload: dict, mode: str) -> dict:
    if mode == "developer":
        return payload
    return sanitize_payload_for_user(payload)
```

---

### 3.3 问题 C：最后一轮 rework 后必须重新跑完整 gate

#### 解决方案

确保 delivery rework 结束后执行：

```text
FinalAnswer repair
→ rebuild citations
→ Verifier
→ ObjectiveQuality
→ LLMReview
→ DeliveryGate
```

不要让最后一步停在 FinalAnswer。`delivery_pass_after_round` 必须读取最新的 `delivery_gate.json`。

---

## 4. 算法 / RAG / 质量闭环需要解决的问题与方案

### 4.1 问题 A：FinalAnswer 看起来“没有 RAG”

#### 根因

FinalAnswer 当前消费了前面 RAG 的产物，但更像：

```text
Claims: [...]
Evidence: [...]
```

不是：

```text
claim_1 → evidence A/B/C
claim_2 → evidence D/E/F
valuation claim → raw inputs + internal valuation evidence
```

#### 解决方案：ClaimEvidenceBundle

在 FinalAnswer 前构造：

```json
{
  "claim_id": "cl_001",
  "section_name": "valuation",
  "claim_text": "...",
  "numeric_values": {...},
  "supporting_evidence": [
    {"evidence_id": "sec_xxx", "content": "..."},
    {"evidence_id": "internal_valuation_xxx", "content": "..."}
  ],
  "allowed_in_report": true,
  "grounding_status": "grounded"
}
```

FinalAnswer 只允许基于 bundle 写作。

---

### 4.2 问题 B：内部模型没有 evidence 化

#### 根因

估值、敏感性分析、图表、同行对比、财务指标是内部计算产物，但没有统一生成 `derived evidence_id`。

#### 解决方案：Derived Evidence Builder

统一生成：

- `internal_valuation_{symbol}_{period}_v1`
- `internal_financial_metrics_{symbol}_{period}_v1`
- `internal_peer_comparison_{symbol}_{period}_v1`
- `internal_chart_{symbol}_{period}_{chart_id}`
- `internal_sensitivity_{symbol}_{period}_v1`

要求包含：

- `source_type = internal_model / derived_metric / derived_chart`
- `trust_level = derived`
- `input_evidence_ids`
- `assumptions`
- `limitations`
- `generated_by_agent`

---

### 4.3 问题 C：不同公司/不同期间问题不同

#### 解决方案：CompanyPeriodQualityProfile

在写作前生成：

```json
{
  "symbol": "...",
  "period": "...",
  "official_source_coverage": "full/partial/missing",
  "three_statement_coverage": "full/partial/missing",
  "market_data_coverage": "full/partial/missing",
  "valuation_input_coverage": "full/partial/missing",
  "peer_data_coverage": "full/partial/missing",
  "business_profile_coverage": "full/partial/missing",
  "degradation_level": "full_delivery/limited_delivery/evidence_gap_delivery/no_delivery",
  "allowed_report_sections": [...],
  "prohibited_claim_types": [...],
  "required_disclosures": [...]
}
```

写作阶段根据 profile 决定：

- 能不能写估值；
- 能不能输出目标价；
- 能不能写强投资结论；
- 哪些章节必须跳过；
- 是否降级为事实摘要。

---

### 4.4 问题 D：估值方法不适配不同公司

#### 通用 Valuation Policy

- 盈利成熟公司：可用 P/E、P/S、DCF，但必须有输入证据；
- 亏损公司：不得使用 P/E；
- 金融公司：普通 DCF 不适用，优先 P/B、ROE 框架，证据不足就降级；
- 现金流缺失或为负：不输出 DCF target price；
- 股本缺失：不输出每股目标价；
- DCF 与 blended/composite value 差异超过 50%：必须解释方法分歧；
- 解释不足：删除 target price，结论降级为“未评级/审慎观察”。

---

### 4.5 问题 E：报告不像正式研报

#### 禁止正式报告出现

- “暂无充足的可验证证据支持详细分析”
- “资料缺口：本节”
- “提示了相关风险或运营关注点”
- “PDF section:”
- “web_search 提示”
- “本节暂无”
- “待补”
- “框架性”
- “N/A”

#### 正确做法

- 有 grounded claims 的章节才写；
- 无证据的内容放到“数据缺口与降级说明”；
- 风险评估要归纳成研报式风险，而不是罗列来源标题。

---

## 5. Codex / Claude 总命令

```text
请修复 DeepReport Plus 的 UI 交付形态和多智能体质量闭环。不要针对某个公司或某个季度硬编码。

一、前端：
1. 将普通用户 UI 和开发者 UI 分离。
2. 普通用户访问 / 或 /chat，只看到聊天机器人界面、生成状态、报告卡片、HTML 报告链接、下载按钮和简要来源摘要。
3. 开发者访问 /dev，才显示客观评分、LLM 复核、交付门禁、Tool Calls、Agent Timeline、rework history、raw artifacts。
4. 生成报告完成后，在 chat response 中返回 report_links，包括 html_web_url、html_file_url、markdown_web_url、json_web_url、local_report_dir。
5. 增强 report.html 的静态研报模板：封面、目录、章节、图表、表格、引用、打印 CSS。正式报告不显示 debug 信息。

二、后端：
1. 新增 build_report_links(output_dir, report_dir)，使用 Path.as_uri() 生成 file:/// 本地链接，同时保留 /artifacts/... 的 web 链接。
2. 新增 sanitize_payload_for_user，只返回用户需要的字段；开发者模式才返回完整 payload。
3. 检查 delivery rework loop，确保最后一次 FinalAnswer repair 后重新执行 Citation、Verifier、ObjectiveQuality、LLMReview、DeliveryGate。
4. delivery_pass_after_round 必须来自最新 delivery_gate.json。

三、算法 / RAG / 质量闭环：
1. 新增 CompanyPeriodQualityProfile，用于判断任意公司和报告期的数据覆盖、可写章节、禁止结论和降级等级。
2. 新增 Derived Evidence Builder，把 valuation、financial metrics、peer comparison、charts、sensitivity 等内部计算统一转成 derived evidence，带 input_evidence_ids。
3. 新增 ClaimEvidenceBundle，把每个 claim 和自己的 supporting evidence 绑定后传给 FinalAnswer。
4. FinalAnswer 只能基于 ClaimEvidenceBundle 写作，没有 supporting evidence 的 claim 不得进入正式正文。
5. 建立通用 Valuation Policy：亏损公司不用 P/E，金融公司不套普通 DCF，现金流/股本缺失不输出 target price，DCF 与 composite 差异过大必须解释，否则降级。
6. 建立 Source Tier Policy：核心财务、估值、投资结论不能只由 web_or_news 支撑。
7. 禁止最终报告出现“暂无充足的可验证证据支持详细分析”“提示了相关风险或运营关注点”“PDF section:”等空洞/调试式表达。
8. 按 issue_type 做定向 repair routing，不要所有问题都重跑完整链路。
9. 新增跨公司、跨报告期 benchmark matrix，验证完整数据 case 能交付，数据不足 case 能明确降级或 no_delivery。

不要降低 gate 阈值，不要把 blocker 改成 warning 来绕过门禁。目标是让系统对不同公司、不同年份、不同季度稳定做到：用户界面像聊天机器人，开发者界面保留调试能力；报告可一键打开；有证据就写，无证据就降级；内部模型可追溯；核心 claim 可验证。
```

---

## 6. 分任务命令

### Task 1：UI 分层和报告链接

```text
请先只做前端/后端 UI 分层：新增 user mode 和 developer mode。普通用户只能看到聊天界面和报告链接，开发者才看到质量门禁、Tool Calls、Agent Timeline。生成报告后返回 report_links，包括 /artifacts/... 的 html_web_url 和 Path.as_uri() 的 html_file_url。不要改算法。
```

### Task 2：HTML 研报模板

```text
请增强 standalone report.html 模板，使其像正式金融研报：封面、目录、章节、表格、图表、引用、打印 CSS。正式报告中不要显示 debug 信息、quality gate、tool calls、agent timeline。保留 citations 和数据缺口说明。
```

### Task 3：Claim-level RAG 和 derived evidence

```text
请新增 Derived Evidence Builder 和 ClaimEvidenceBundle。把 valuation、financial metrics、peer comparison、charts、sensitivity 等内部计算转成 derived evidence；每个 claim 绑定自己的 supporting evidence 后再传给 FinalAnswer。FinalAnswer 不得使用没有 supporting evidence 的 claim。
```

### Task 4：通用质量 profile 和降级策略

```text
请新增 CompanyPeriodQualityProfile，判断任意 symbol + period 的 official source、三表、市场数据、估值输入、同行、业务画像覆盖情况，并据此决定 full_delivery、limited_delivery、evidence_gap_delivery 或 no_delivery。证据不足时降级，不要硬写完整报告。
```

### Task 5：定向 rework 和最终 gate 闭环

```text
请新增 issue_type repair router，将 valuation_divergence、citation_gap、unsupported_numeric、empty_section、source_quality_low、period_mismatch 等问题分派给对应 Agent 修复。最后一轮 FinalAnswer 后必须重新跑 Citation、Verifier、ObjectiveQuality、LLMReview、DeliveryGate。
```
