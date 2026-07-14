# 投研工作台阶段修复交接记录

> 更新时间：2026-07-13 23:35（Asia/Shanghai）
> 仓库：`/Users/yuan_dian/AI_project/DeepReport-fin-workbench-v2`  
> 分支：`feat/fin-research-agent-workbench-v2`  
> 用途：切换 Codex 对话后，从当前 checkpoint 和未提交工作区继续，不重新猜测或重复审计。

## 0. 23:35 最新 checkpoint（优先于下方历史记录）

阶段 2A 与 2B 已完成代码修复和真实任务验证。阶段 2 至阶段 9 均已完成并推送；随后完成一轮用户反馈驱动的工作台易用性修复。

最新提交：

```text
0c84f4b feat: improve workbench task and export usability
```

### 阶段 10：工作台 UI 与任务操作易用性修复已完成

- 创建任务弹窗统一字段顶部对齐、输入控件宽高和间距，默认运行方式改为“创建后立即在后台运行”。
- 研报任务页在普通桌面宽度使用完整单栏，表格不再被详情侧栏挤压；单次读取最多 200 条供筛选，页面只展示前 30 条，行距和日期格式均已压缩。
- 主列表隐藏内部 `task_id`，新增公司/代码/期间搜索，以及当前、全部、待启动、运行中、成功、待人工审核、失败、已归档筛选。
- 待启动任务直接显示“立即启动”；成功任务直接显示“查看研报”；失败任务直接显示“查看失败原因”；待复核任务直接显示“去复核”。
- 任务详情先读取基础任务，再读取高级分析；高级分析失败时仍展示基础信息、错误和产物。失败入口会自动打开质量页。
- 刷新按钮增加禁用、进行中和完成反馈；首页平均耗时及提示词健康平均耗时改为分钟。
- 新增失败任务批量清理接口 `/api/report-tasks/bulk-archive-failed`。清理采用可恢复归档，只处理失败、质检失败、超时、取消或证据阻塞任务，成功与待人工复核任务不会被清理。
- 导出中心直接提供 HTML、Markdown（`.md`）、PDF、DOCX、CSV、JSON 选择，默认勾选 HTML 和 Markdown；后端只生成所选格式，并保留不传格式时生成完整包的兼容行为。
- 补齐 `quarterly_review`、`annual_deep_dive` 和 `timeout` 等遗留英文枚举的中文显示。

验收结果：聚焦测试 28 项及后续相关契约 22 项通过；全量 `pytest` 960 项收集，4 项预期跳过，其余全部通过。真实浏览器确认创建弹窗对齐、任务页 30/80 分页摘要、成功研报筛选、失败原因质量页、HTML/Markdown 默认选择和刷新链路。工作台服务继续运行在 `http://127.0.0.1:7863/workbench`。

### 阶段 3：统一数据源状态已完成

API、首页与数据源管理页现在共同读取 `/api/data-sources` 的 registry 状态，并明确展示：

```text
configured
enabled
operational / last_status
evidence_count
```

后端按规范化来源别名聚合 evidence 数量，已统一 `cninfo/cninfo_announcement/cninfo_announcements`、`hkex/hkex_announcement/hkex_annual_report/hkex_announcements`、SEC 和 Yahoo 等来源键。首页不再用“证据数为 0”推断“待配置”。

真实 API 与浏览器验收：

```text
CNINFO: configured=true, enabled=true, operational=true, evidence_count=3, last_status=success
HKEX: configured=true, enabled=true, operational=true, evidence_count=2, last_status=success
Tushare: configured=true, enabled=true, operational=false, evidence_count=0,
         last_status=failed, last_error=permission_or_quota_error
```

浏览器中 Tushare 显示“已配置 / 已启用 / 权限或额度不足”，详情显示“可运行：否、证据数：0”，不再显示“待配置”；CNINFO/HKEX 显示“运行正常”及真实最近运行时间与证据数。阶段 3 后端/前端聚焦测试 16 项通过，并完成本地工作台客户端只读实测。

阶段 3 已通过提交 `16b70c2` 推送到当前远端分支。

### 阶段 4：任务列表和详情重构已完成

任务列表与详情已完成以下收口：

- `.table-scroll` 在所有视口启用横向滚动；工作区子项 `min-width: 0`，任务表稳定最小宽度 `940px`。
- 每行只突出一个“查看详情”主操作；启动、续跑、重试、取消、归档统一收进原生“更多”菜单。
- 列表产物列只显示“已生成/待生成”，产物链接集中到详情“产物”页，不再重复铺按钮。
- 详情保留桌面粘性侧栏、在 `<=1100px` 自动下沉，内部拆成“概览 / 运行节点 / 质量 / 证据 / 产物”五个 tabs。
- 状态优先级调整为证据阻塞、机器质检失败、待人工复核，再回退到通用生命周期状态。
- 删除旧“展开高级分析与诊断”折叠逻辑，详情动作不再重复渲染列表生命周期操作。

验收结果：阶段 4 聚焦 Web/API 测试 24 项通过；`py_compile` 与 `git diff --check` 通过。本地浏览器使用真实任务确认列表、更多菜单、详情五标签和标签切换；质量标签激活后概览内容正确隐藏。真实列表同时确认“证据不足，已阻塞”“机器质检未通过”“机器质检通过，待人工复核”三种优先状态。桌面截图确认列表独立滚动且详情即时可见；窄屏行为由响应式规则和静态页面合同覆盖。

浏览器还暴露一个既有数据问题：`stage2a-machine-pass-cn-fy2024-20260713/analysis` 会因数据库内某条 `evidence_items.metadata` 为 malformed JSON 导致 SQLite `JSON_EXTRACT` 失败；港股任务详情 API 正常。该问题不由阶段 4 前端改动引入，登记到后续数据治理/最终验收，不用展示层掩盖。

### 阶段 5：删除示意漏斗并重建真实指标已完成

- `/api/dashboard/funnel` 保留兼容路由名，但响应升级为 `dashboard_status_groups.v1`，不再返回跨分母伪漏斗。
- 文档组按 Document cohort 去重统计入库、解析、表格、切分、证据化。
- 任务组独立统计 queued、running、evidence_blocked、machine_pass、review_pending、delivered。
- Claim 组独立统计 generated、supported、pending、approved、rejected。
- 数据源组由前端合并 `/api/data-sources` registry，统计 configured、healthy、failed、not_run。
- 已删除 `funnelDemoSteps`、1280→58 全部演示数字、示意切换、转化率和最大流失展示，以及遗留 funnel CSS。

真实 API/浏览器验收显示四组指标均来自当前数据库与 registry；浏览器页面不再出现“示意漏斗”或黄色演示 KPI 提示。阶段 5 聚焦测试 13 项通过，未运行全量 pytest。

### 阶段 6：动态期间选择已完成

- 新增 `/api/report-periods`，响应 `report_period_options.v1`，动态返回最近 8 个完整季度、最近 5 个财年、自定义期间支持、目标分析期、行情时点和官方披露 readiness。
- 2026-07-13 默认最近完整季度为 `2026Q2`，最近财年为 `FY2025`。
- A 股季度窗口按一季报/半年报/三季报/年报法定截止日判断；港股明确 Q1/Q3 通常非强制披露；美股按 10-Q/10-K 代理窗口判断并提示发行人财年差异。
- 创建任务表单不再硬编码 FY2024 等旧选项；选择公司后自动按 A/H/US 刷新官方来源、预计可用日期和行情时点。
- 支持 `FY2025`、`2026Q2` 格式的自定义期间；前端和任务 API 均拒绝“最近一年”等模糊值。

阶段 6 聚焦测试 17 项通过。浏览器实测 `AAPL / 600519 / 0700.HK` 的 2026Q2 提示分别指向 SEC 2026-08-14、交易所/巨潮 2026-08-31、港交所 2026-09-30；自定义 `FY2020` 可正确识别为官方披露已可用。

### 阶段 7：导航和产品主线收口已完成

侧栏从 18 个平级入口收敛为 6 个一级工作区：投研首页、研报任务、数据与文档、证据与复核、运营与配置、导出中心。数据源、采集、导入、文档、事实、证据、线索、主张、词典、PromptOps、实体、图谱和评测均保留在可折叠二级入口。

顶部核心路径调整为“创建研报任务 → 主张复核 → 查看最新报告”，不需要在 18 个菜单间寻找。投研空间选择器已真实读取 `/api/workspaces`；当前选择会用于公司解析和新任务 `workspace_id` 绑定，新建空间后会自动刷新顶部选项。

阶段 7 聚焦 Web/workspace/task 测试 19 项通过。浏览器确认首页仅显示 6 个一级工作区，数据与文档二级入口可展开，研报任务、主张复核和导出中心可沿核心路径直接到达。

### 阶段 8：人工复核、记忆和可观测性闭环已完成

- 新增任务级“批量通过有证据支持的主张”，仅处理 `supported/verified/passed` 且存在 ClaimEvidence 的待审主张；每条 ReviewRecord 保存 before/after、审核人、理由和时间，任务事件保存审核数量与 Claim ID。
- 正式导出包的 JSON 与 `review_records.csv` 已包含审核 before/after，形成可追溯交付审计。
- 产物导入后自动、幂等地从任务正式证据沉淀实体和关系；结果或失败原因写入 `auto_memory_materialization` 与任务事件，不再依赖手工按钮。
- ToolRun 根据 agent/tool trace 推导 planning/research/analyze/write_report/verify_report 等真实节点；运行页新增当前节点、最近工具、节点/工具耗时、累计重试与失败根因。
- 修复历史非法 `evidence_items.metadata` 导致 SQLite `JSON_EXTRACT` 令所有任务分析 500 的问题；SQLite 使用 `json_valid + CASE` 安全读取，其他数据库保持原 JSON 查询。

真实验收任务：

```text
task_id: release-stage9-final-nvda-fy2024-20260713t085909z
symbol: NVDA
period: FY2024
batch approved supported claims: 25
pending claims after review: 0
checkpoint before resume: interrupted / [human_review]
checkpoint after resume: completed / []
delivery readiness: export_ready
official export ready: true
```

正式包已生成于 `data/export_packages/release-stage9-final-nvda-fy2024-20260713t085909z`，包含 JSON、Markdown、HTML、PDF、DOCX、claims/evidence/facts/review CSV 和 manifest 共 10 个文件，均记录 SHA-256。浏览器确认真实任务详情、运行诊断和批量审核入口正常。阶段 8 扩大聚焦套件 33 项通过；未提前运行全量 pytest。

### 阶段 9：最终统一验收已完成

全量 pytest 最终运行两次均 100% 通过：共收集 958 项，4 项环境预期跳过，其余全部通过。数据库 `init_db` 与 legacy SQLite migration smoke 7 项通过。新增移动端静态合同断言覆盖 1100px/760px 断点、单列导航、详情下沉、筛选器全宽和表格横向滚动。

FY2024 多市场验收：

```text
AAPL       release-stage9-aapl-fy2024-20260713t075908z       0.975  delivery_pass=true
NVDA       release-stage9-final-nvda-fy2024-20260713t085909z 0.975  delivery_pass=true / export_ready
MSFT       release-stage9-msft-fy2024-20260713t075908z       0.975  delivery_pass=true
600519.SS  stage2a-machine-pass-cn-fy2024-20260713            0.975  delivery_pass=true
0700.HK    stage9-final-hk-fy2024-20260713t2155z              0.9525 delivery_pass=true
```

新港股任务用当前代码完整重跑，objective/LLM/delivery 均为 true，停在正常 `human_review` interrupt；自动记忆最终记录 7 个实体、514 条关系；ToolRun 显示真实 `research` 节点，并能定位缺失 Serper key 的失败根因。浏览器任务详情无加载错误、五个标签正常、运行页不再出现 `generation`。

最新季度样本 `stage9-latest-quarter-aapl-2026q2-20260713` 验证了时间边界：截至 2026-07-13，AAPL 2026Q2 官方 SEC 披露预计不早于 2026-08-14，因此只允许草稿、正式交付为 `remediation_required`，明确返回 `no_evidence`、缺 `sec_edgar` 和补采集动作。裸 `600519` 期间 API 已修复为自动规范化 `600519.SS / cn_a / SSE`，2026Q2 披露日期为 2026-08-31。

正式导出复验：NVDA 包共 10 文件；PDF 为 29 页 A4，DOCX OOXML 完整性通过，manifest 中 JSON/Markdown/HTML/PDF/DOCX/4 个 CSV 的 SHA-256 全部匹配。审核包包含 pending→approved 的 before/after、审核人、理由和时间。

应用内浏览器固定为 1280×720，桌面全页面和真实任务详情已实测；创建 390px 标签仍返回 1280×720，且浏览器安全策略禁止嵌套移动视口，因此没有绕过安全限制，移动端以响应式 CSS 合同与全量测试完成验收。

### 阶段 2A：A 股机器质量已通过

最终验收任务：

```text
task_id: stage2a-machine-pass-cn-fy2024-20260713
symbol: 600519.SS
period: FY2024
quality_score: 0.975
objective_pass: true
llm_review_pass: true
delivery_pass: true
checkpoint next: [human_review]
LangGraph step: 15
```

机器门禁只剩 `pending_claim_review`，可进入人工复核。已完成：PDF 中文别名与递归 lineage、同行单一投影与章节白名单、CNY ticker 排除、风险官方 PDF fallback、完整 DCF 敏感性和估值单位修复。

### 阶段 2B：港股真实数据链与机器交付门已通过

最终真实生成任务：

```text
task_id: stage2b-final-hk-fy2024-20260713
symbol: 0700.HK
period: FY2024
quality_score: 0.9525
objective_pass: true
llm_review_pass: true (0.75, no issues)
official evidence coverage: ready
structured statements: income + balance + cashflow
statement currency: CNY
trading currency: HKD
checkpoint next: [human_review]
LangGraph step: 15
```

生成时最后仅因 PDF chunk 没有继承父 section 页码导致 verifier 失败。随后已修复递归页锚解析，并对该真实任务重算：

```text
verifier_passed: true
delivery_pass: true
fatal: 0
blocker: 0
warning: 5
```

三表金额已恢复正确量级：收入 `6602.57 亿元人民币`、总资产 `13334.25 亿元人民币`、经营现金流 `2585.21 亿元人民币`。报告明确显示 `报表货币 CNY / 交易货币 HKD`，没有混入美股 peer；同行不足采用边界披露。HKEX 年报 URL 为 `2025/0408/2025040800667.pdf`，发布日期对应 `2025-04-08`。

canonical metrics 离线重建后，收入、净利润、经营现金流、自由现金流均来自 `hk_financials` 且为 CNY；PDF 资产负债表以 `CNY_million` 保留原披露单位。仍有多源数值差异 warning（例如 PDF 与 Yahoo 资产规模差异），属于可观察冲突，不阻断机器交付。

### 本轮新增通用修复

- `hk_financials` 三表共享 URL 时按独立 evidence ID 保留，source cap 为 3。
- 0700.HK 发行人报表币种规则优先于 Yahoo 交易币种。
- 港股结构化三表补齐 evidence/table lineage，官方覆盖门可识别三表齐全。
- PDF 表头 `RMB’Million` 在显式 unit 缺失时可推断 `CNY_million`。
- 三表渲染按 `unit/thousand/million/billion` 还原基础金额后再格式化。
- `risk_uses_official_pdf` 等正向合同标志不再被当作 blocker。
- verifier 排除 ANNUAL/HKEX/HKG/REPORT/VAS/CICC/PUBG/TC 等非 ticker 缩写。
- PDF chunk 可沿显式 lineage 或规范化 chunk 父 ID 递归继承页码，含深度和循环保护。

### 测试与下一入口

扩大阶段 2 聚焦套件已全部通过，含 2 个预期环境跳过；未提前运行全量 pytest。覆盖 identity、HKEX/search、三表单位、feature layer、官方覆盖、peer contamination、quality、section/delivery contracts、cross-market currency、valuation currency 和 multi-agent workflow。

当前本地服务：

```text
http://127.0.0.1:7863/workbench
exec session 57240，PID 417
```

阶段 2 的提交步骤已经完成。下一步严格按阶段计划执行：

1. 本轮阶段 2–9 计划全部完成；后续新需求从本 checkpoint 继续，不要重跑已完成的真实基线。
2. 保留 `runtime_checkpoints.sqlite` 与正式任务数据库，不提交运行 artifacts、导出包或日志。

下方第 1–10 节保留为修复前历史诊断；如与本节冲突，以本节为准。

## 1. 当前 Git 状态

已完成并推送阶段 1：

```text
1a00723 fix: normalize report task market identity
```

阶段 1 已解决：

- 裸 A 股代码在任务 API 边界规范为 `.SS/.SZ`。
- `600519` 创建后保存为 `贵州茅台 / 600519.SS / cn_a / SSE / CNY`。
- 历史裸代码任务在运行前自动修复身份。
- 立即运行任务不再跳过 `company_id` 绑定。
- A/H/双重上市快捷候选已拆分，`9988.HK` 不再映射到 `BABA`，`1211.HK` 不再映射到 `002594.SZ`。
- 阶段 1 聚焦测试：12 项身份/生命周期测试通过；59 项报告任务相关测试通过。

阶段 2 正在进行，以下文件有未提交修改，**不要回退**：

```text
src/agents/deep_analyze_agent.py
src/data/company_universe.py
src/data/hkex_official_source.py
src/evaluation/report_quality.py
src/evaluation/section_verification.py
src/report/contract_builder.py
tests/test_company_identity.py
tests/test_hkex_official_source.py
tests/test_peer_contamination.py
tests/test_report_quality.py
```

阶段 2 当前改动内容：

- A 股 Research 路由加入 `baostock_financials`、`tushare_financials`，二者为非阻塞补充源。
- 港股 Research 路由加入 `hk_financials`，移除 Serper/Tavily 的 primary 身份。
- HKEX 支持 `DD/MM/YYYY HH:mm` 公告时间解析。
- A 股允许执行同市场外部同行发现，港股继续保持隔离。
- PDF 身份校验开始支持目标身份合同和父证据 lineage。
- 已清洗的业务概览 PDF boilerplate 不再直接阻断章节合同。

当前工作区未提交差异约 `10 files, +159/-6`。阶段 2 尚未达到提交条件。

## 2. 当前服务

本地服务仍在运行：

```text
http://127.0.0.1:7863/workbench
PID 94283
```

启动命令：

```bash
/Users/yuan_dian/anaconda3/anaconda3/bin/python -m uvicorn src.app.api_fastapi:app --host 127.0.0.1 --port 7863
```

如果新对话发现端口未启动，使用上述命令恢复。不要启动旧目录或其他分支。

## 3. 当前 LangGraph Checkpoint

当前真实 A 股回归任务：

```text
task_id: stage2-live-cn-fy2024-20260713
symbol: 600519.SS
period: FY2024
status: quality_failed
current_stage: quality_failed
quality_score: 0.975
last_node: finalize
next: human_review
checkpoint interrupt: claim_review_required
```

checkpoint 唯一查询入口：

```bash
curl -sS http://127.0.0.1:7863/api/report-tasks/stage2-live-cn-fy2024-20260713/runtime | jq
```

注意：不存在 `/runtime/checkpoint` 路由，使用该路径会得到 404。任务业务状态使用：

```bash
curl -sS http://127.0.0.1:7863/api/report-tasks/stage2-live-cn-fy2024-20260713 | jq
```

主张状态：

```text
total: 19
approved: 13
pending: 6
rejected: 0
unsupported: 0
```

当前 checkpoint 不是运行中断或模型崩溃。所有生成节点已完成，工作流停在正式人工复核前；由于机器质量仍失败，不能进入正式交付。

节点实测耗时：

| 节点 | 状态 | 耗时 ms |
| --- | --- | ---: |
| official_evidence_backfill | completed | 2931 |
| evidence | completed | 527 |
| planning | completed | 14353 |
| research | completed | 17516 |
| normalize_evidence | completed | 17395 |
| analyze | completed | 33514 |
| build_canonical_metrics | completed | 21 |
| build_section_evidence_packs | completed | 23 |
| write_report | completed | 61018 |
| verify_report | completed | 17540 |
| verify_sections | completed | 13 |
| repair_failed_sections | completed | 19576 |
| quality | completed | 12654 |
| finalize | completed | 6 |

结论：LangGraph checkpoint、节点调度、模型调用和章节返工正常；当前阻塞在质量规则和同行白名单投影，不是 Agent runtime 黑盒或数据源无法执行。

本次重新读取 checkpoint 得到的关键状态：

```text
LangGraph step: 15
last_node: finalize
next: [human_review]
checkpoint_status: interrupted
lifecycle_status: quality_blocked
section_verification: passed (13/13 contracts)
section_repair: repaired (risks, valuation)
quality_score: 0.975
objective_pass: false
```

因此不能对当前任务执行“从失败节点重试”来解决规则误报。代码修复后应先离线重算质量，再创建全新任务做生产链回归；旧 checkpoint 保留为修复前证据。

## 4. A 股真实数据链结果

`600519.SS / FY2024` 已打通：

- CNINFO：3 条，包含 2024 年报 PDF。
- 上交所：2 条，包含年度报告和摘要。
- 东方财富三表：3 条，收入/资产负债/现金流。
- BaoStock：6 组财务指标。
- 新浪行情：成功。
- Yahoo 行情/财务：成功。
- Tushare：Key 已配置，但账号没有 `income/balancesheet/cashflow/fina_indicator` 权限；不能作为阻塞源。
- 官方补采、PDF 下载解析、三表、canonical metrics、章节 evidence packs、正文、引用、返工均完成。
- 新任务导入 86 条 evidence、19 条 claims、54 条 financial facts。

因此“A 股不能生成是因为没有数据源”的判断已经被否定。数据链已经进入报告质量层。

## 5. 当前明确阻塞项

### 5.1 PDF 身份误报仍未完全修复

质量报告仍报：

```text
evidence_identity_pollution
```

示例 `pdf_section_e5806eef5c7e` 的正文明确包含：

```text
贵州茅台酒股份有限公司2024年年度报告摘要
```

且 `symbol=600519.SS`，但质量规则仍判污染。原因有两个：

1. `_identity_terms_for_symbol()` 主要得到代码和英文公司名，没有从 `company_aliases.py` 加载“贵州茅台/贵州茅台酒股份有限公司”。
2. 该片段父 ID 是另一个 `pdf_section`，当前 lineage 校验只检查一层，没有递归追溯到最终 CNINFO 父公告。

下一步不能删除身份门禁，应改为：

- 为目标 symbol 加载中英文标准名和别名。
- 对 `source_evidence_id` 做有深度上限和循环保护的递归 lineage 校验。
- 只有最终父记录为匹配公司、匹配期间、官方域名/官方 source type 时才接受。
- 保留现有“错误 HKEX PDF”负向测试。

### 5.2 合法同行代码被误判为跨报告污染

新 Analyze 已成功发现 5 家同市场同业：

```text
000995.SZ
002646.SZ
002304.SZ
600197.SS
603919.SS
```

`analysis_artifacts.peer_context.peer_count=5`，每家公司有 revenue growth、gross margin、net margin、ROE 等 TTM 指标。

但质量门禁将这些合法同行代码判为：

```text
cross_report_symbol_pollution
```

根因：

- `peer_context.peer_rows` 有完整同行。
- 顶层 `peer_rows` 和 `peer_analysis.peer_rows` 为空。
- `report_quality._approved_peer_symbols()` 没有读取 `analysis_artifacts.peer_context.peer_rows`。
- LLM review 也没有得到“这些 ticker 是已批准同行”的结构化白名单。

下一步：

- 统一 `peer_context -> peer_analysis -> section_dossiers -> quality` 的同行所有权。
- 同行代码只能在“同行对比”章节出现。
- 质量规则读取 approved peer symbols，不得全局放行任意 ticker。
- LLM review prompt 显式提供 approved peer symbols 和章节边界。

### 5.3 Peer 数据投影不一致

当前出现：

```text
peer_analysis.findings: 已识别 5 家
peer_analysis.verified: true
peer_analysis.peer_rows: []
peer_context.peer_rows: 6 行（含目标公司）
peer_analysis.dropped_peer_row_count: 1
```

这说明 Analyze 内部找到数据，但在 `peer_analysis` 投影/清洗时丢失。需要检查：

- `src/agents/deep_analyze_agent.py`
- `_sanitize_peer_context_for_market()`
- 构建 `peer_analysis` 的 `rows/peer_rows` 赋值
- `src/agents/section_dossier_builder.py`
- `_approved_peer_symbols_from_analysis()`

验收：三处读取到同一组 5 个同行代码，且只保留同市场、同行业、带指标记录。

### 5.4 其他质量误报/真实缺口

- Verifier 将 `CNY` 当 ticker mismatch，需要把货币代码加入统一排除集合。
- `valuation_sensitivity_earnings_bridge_only` 仍作为 contract blocker，需要核对最终敏感性章节是否确实只有利润桥接，不能直接降级。
- `risk_fallback_no_official_pdf` 与当前已存在 CNINFO 风险 PDF 片段矛盾，需要修 risk dossier 的证据投影。
- 图表已生成，但正文缺少对图表结论的显式解释，属于真实 warning，可在报告章节阶段处理。
- 质量曾出现 `llm_review=false` 但只有 warning；需要统一“warning 是否阻断”的唯一语义。

### 5.5 当前质量问题的精确分层

当前 `quality_report.json` 共有 4 项，不应再笼统描述为“报告质量差”：

| 等级 | 类别 | 当前判断 | 是否阻断 |
| --- | --- | --- | --- |
| fatal | evidence_identity_pollution | 规则误报；5 个 PDF section 正文均包含“贵州茅台酒股份有限公司” | 是 |
| blocker | cross_report_symbol_pollution | 规则误报；5 个代码均来自已批准的 A 股同行集 | 是 |
| warning | multimodal | 图表与财务结论的文字绑定不足，是真实可改进项 | 否 |
| warning | delivery_policy | trace 未明确“记忆不能替代事实证据”，属于观测文案缺口 | 否 |

`section_verification.json` 已经通过，风险与估值章节的两项失败已由章节返工修复。因此阶段 2A 不应再次重写报告章节，先修正质量门禁读取同一份身份和同行合同。

## 6. 已运行测试

阶段 2 当前聚焦测试均已通过：

- 公司身份、HKEX、BaoStock、Tushare、Search/Research、官方补采套件：通过，含 2 个环境跳过。
- Report Quality、Section Verification、Report Section Contracts、Peer Contamination：通过。
- Multi-agent workflow 相关套件：通过。
- 旧 A 股产物在最新确定性质量规则下已验证 `objective_pass=true`、无 blocking issue。

注意：新 A 股任务又暴露了多层 PDF lineage 和同行白名单问题，因此阶段 2 仍不能提交。

## 7. 接下来逐阶段计划

### 阶段 2A：完成 A 股机器质量闭环

执行顺序：

1. 修复 PDF 多层 lineage 与中文别名身份校验。
2. 修复 peer rows 的统一投影与 approved peer symbols。
3. 修复同行章节限定范围下的 ticker pollution 规则。
4. 修复 CNY/货币代码 verifier 误报。
5. 核对 risk 和 valuation sensitivity 的 contract blocker。
6. 运行上述模块聚焦测试。
7. 对 `stage2-live-cn-fy2024-20260713` 先做离线 objective quality 重算。
8. 创建新的 `600519.SS / FY2024` 任务完整回归，避免缓存掩盖问题。

文件级执行矩阵：

| 子任务 | 主要代码位置 | 聚焦测试 | 判断依据 |
| --- | --- | --- | --- |
| 中文身份别名 | `src/evaluation/report_quality.py`、公司别名/身份模块 | `tests/test_report_quality.py`、`tests/test_company_identity.py` | 目标代码、中文简称、中文全称、英文名均可匹配 |
| PDF 递归 lineage | `src/evaluation/report_quality.py` | `tests/test_report_quality.py` | 有深度上限、循环保护；最终父证据必须匹配公司/期间/官方来源 |
| Peer 单一所有权 | `src/agents/deep_analyze_agent.py`、section dossier builder | `tests/test_peer_contamination.py` | `peer_context`、`peer_analysis`、dossier 使用同一组 5 个 peer |
| 同行章节白名单 | `src/evaluation/report_quality.py`、LLM review 输入构建 | `tests/test_peer_contamination.py`、`tests/test_report_quality.py` | approved peer 只在同行章节合法，不做全局 ticker 放行 |
| 货币代码排除 | `src/evaluation/section_verification.py` | 对应 section/verifier 测试 | CNY/HKD/USD 不再被当作股票代码 |
| 风险证据投影 | `src/report/contract_builder.py`、dossier builder | contract/section verification 测试 | 已有 CNINFO 风险 PDF 时不生成 fallback blocker |
| 估值敏感性核验 | valuation contract/artifact | contract/section verification 测试 | 必须有变量、情景、结果和边界解释；不足则保留 blocker |

阶段 2A 的执行纪律：

1. 每次只修一个根因并先跑对应聚焦测试。
2. 通过 artifact 比较确认规则读到的 identity/peer 数据与 Writer 使用的数据一致。
3. 不删除污染门禁，不把 fatal/blocker 改成 warning 来制造通过。
4. 旧任务只用于离线重算；端到端验收必须创建新 task_id。
5. 只有 A 股新任务机器质量通过，才进入阶段 2B。

验收：

- `objective_pass=true`。
- LLM review 无 fatal/blocker。
- 合法同行不会被判污染。
- 同行章节至少包含 2 家同市场同行及量化指标、TTM 时点说明。
- 机器质量通过并进入 `human_review`；正式交付只剩人工复核。

### 阶段 2B：港股完整回归

已完成直连预检：

- HKEX `0700.HK FY2024` 返回 1 份 2024 年报。
- `hk_financials` 返回 income/balance/cashflow 3 张表。
- 新浪港股行情成功。

执行：

1. 创建全新 `0700.HK / FY2024 / annual_review` 任务。
2. 核对 HKEX 发布日期为 `2025-04-08`，不再回退到当天。
3. 核对港股三表币种 HKD/CNY 报表口径与交易货币。
4. 港股同行发现不足时允许明确边界，但不能混入美股 peer。
5. 根据真实节点结果修复通用问题。

验收：报告产物存在，官方证据和三表 ready；失败必须归因到具体章节/口径，不得再是来源未运行或身份 unknown。

完成 2A + 2B 后运行阶段 2 聚焦测试，独立 commit 并 push。建议提交信息：

```text
fix: complete cn and hk report source routing
```

阶段 2 提交边界只包含当前 10 个代码/测试文件及阶段 2 必要新增测试。运行目录、SQLite、向量库、日志、临时报告不得提交。

### 阶段 3：统一数据源状态

目标：前端不再把“没有证据”显示成“待配置”。

执行：

- Dashboard 改为读取 `/api/data-sources`。
- 明确四个字段：configured、enabled、last_status/operational、evidence_count。
- Tushare 显示“已配置但权限不足”，不是待配置。
- CNINFO/HKEX 显示真实最近成功时间和命中数。
- 修正 `cninfo`/`cninfo_announcement`、`hkex`/`hkex_announcement` 等来源分组键。

验收：数据源管理页与首页状态完全一致；通过 API 和客户端实测后独立提交推送。

### 阶段 4：重构任务列表和详情

目标：解决按钮混乱、桌面端横向无法滚动、双滚动条和详情过长。

执行：

- `.table-scroll` 在所有视口启用 `overflow-x:auto`。
- 列表区设置 `min-width:0`，表格设置稳定最小宽度。
- 任务主操作只保留一个，其他动作放“更多”菜单。
- 右侧详情改为抽屉或 tabs：概览、运行节点、质量、证据、产物。
- 不在列表和详情重复渲染同一组动作。
- 状态优先展示 evidence blocked / machine failed / review pending，不再混成“质量未通过”。

验收：桌面和移动截图、横向滚动、任务启动/重试/归档实测；独立提交推送。

### 阶段 5：删除示意漏斗并重建真实指标

当前漏斗混合文档数、事实数和 Claim 数，不能计算转化率。

改为四组真实指标：

- 文档处理：入库、解析、表格、切分、证据化，按 document cohort 统计。
- 研报任务：queued/running/evidence_blocked/machine_pass/review_pending/delivered。
- Claim：generated/supported/pending/approved/rejected。
- 数据源：configured/healthy/failed/not_run。

删除 `funnelDemoSteps` 和 `1280 -> 58` 所有示意数据。独立提交推送。

### 阶段 6：动态期间选择

执行：

- 后端提供 period options/readiness API。
- 前端动态展示最近完整季度 `2026Q2`、最近年度、最近 8 季度、最近 5 财年。
- 支持自定义期间。
- 标明“目标分析期”和“行情时点”。
- 创建前显示该市场该期间官方披露是否可用。

验收 A/H/US 三市场期间创建和门禁；独立提交推送。

### 阶段 7：导航和产品主线收口

将 18 个一级入口收敛为约 6 个工作区：

1. 首页
2. 研报任务
3. 数据与文档
4. 证据与复核
5. 运营与配置
6. 导出

实体、图谱、PromptOps、词典、评测作为二级入口。顶部投研空间必须真实可切换。验收核心用户从创建任务到报告复核不需要在 18 个菜单间跳转。

### 阶段 8：人工复核、记忆和可观测性闭环

执行：

- 支持按任务批量审核已获证据支持的 Claim。
- 保存审核前后、审核人、理由、时间。
- 自动从正式证据沉淀实体/关系，不再让实体数和关系数长期为 0。
- ToolRun 的 `langgraph_node` 改为真实 research/analyze 等节点，不再统一显示 generation。
- 运行页显示节点耗时、当前工具、重试和失败根因。

验收一个 A 股或美股任务完成 interrupt/resume，并生成正式导出包。

### 阶段 9：最终统一验收

用户已要求此前阶段取消全量测试，因此只在最终阶段执行：

- 全量 pytest。
- AAPL/NVDA/MSFT FY2024。
- 600519.SS FY2024。
- 0700.HK FY2024。
- 最新季度样本。
- 浏览器桌面/移动全页面复测。
- 数据库 migration smoke。
- PDF/DOCX/manifest/SHA 导出验证。

最终标准：机器质量多市场稳定通过，所有失败能定位到节点、来源、证据、指标或章节；前端不展示示意数据和错误状态。

## 8. 阶段提交与动态调整规则

后续每个阶段统一采用以下顺序：

1. 开始前读取最新 checkpoint、Git 状态和上一阶段验收结果。
2. 在对话中展开该阶段的文件、接口、数据迁移、聚焦测试和客户端路径。
3. 只修改该阶段边界内的问题；新暴露问题按依赖关系插入当前阶段或登记到后续阶段。
4. 运行聚焦测试和该阶段真实功能回归，不提前运行全量测试。
5. 检查 `git diff`，排除 DB、日志、向量库、导出包和运行 artifact。
6. 独立 commit 并 push 当前分支。
7. 在本文档更新提交号、实测结果、新 checkpoint 和下一阶段入口。

动态调整原则：

- 节点失败：先读 LangGraph checkpoint、node event 和对应 phase artifact。
- 数据源失败：区分未配置、权限不足、网络失败、无目标期间记录和解析失败。
- RAG 失败：区分候选为空、向量/重排异常、期间过滤、身份过滤和 Writer 未消费。
- 质量失败：区分确定性规则、LLM review、章节合同、数字一致性和人工复核。
- 前端异常：同时核对 API 原始值和 SQLite 持久化值，禁止只改展示掩盖后端状态。

## 9. 工作区恢复检查清单

新对话开始后先执行：

```bash
cd /Users/yuan_dian/AI_project/DeepReport-fin-workbench-v2
git status --short --branch
git log -3 --oneline --decorate
curl -sS http://127.0.0.1:7863/api/report-tasks/stage2-live-cn-fy2024-20260713/runtime | jq '{next, interrupts, created_at, metadata: {step: .metadata.step, thread_id: .metadata.thread_id}}'
```

预期：

```text
HEAD = 1a00723
分支 = feat/fin-research-agent-workbench-v2
阶段 2 的 10 个文件仍为 modified
本文档为 untracked 或 modified
checkpoint next = [human_review]
checkpoint step = 15
```

如果服务已停止，只恢复 7863 服务；不要删除 `runtime_checkpoints.sqlite`，否则当前 checkpoint 证据会丢失。

## 10. 新对话启动提示

新对话第一条可直接要求：

```text
读取 docs/fin_research_workbench_handoff_20260713.md，保持当前未提交改动，
从阶段 2A 的 PDF 多层 lineage 和同行 approved symbols 修复继续。
先读取 stage2-live-cn-fy2024-20260713 checkpoint，不要重新规划或回退阶段 1。
```

不要做的事情：

- 不要回退当前 10 个未提交文件。
- 不要重新扩充数据源；A 股当前不是来源不足。
- 不要通过降低 fatal/blocker 等级伪造通过。
- 不要先做全量测试。
- 不要重新跑美股基线，先完成阶段 2A。
