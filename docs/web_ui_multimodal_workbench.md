# Web UI 与质量门禁工作记录

更新时间：2026-05-16

## 工作规则

- 每次开工先读取 `docs/project_status_deepreport_multiagent.md` 和本文档，再检查最新 eval 输出。
- 每完成一个功能都要更新文档，记录改动、验证命令、质量结果、问题清单和下一步，并单独提交一次 git。
- Chat memory 只用于用户偏好和任务上下文，不替代 `evidence_id`、citation、numeric audit 或 verifier。
- 只有 `verifier + objective quality eval + LLM/Codex review` 三层都通过，报告才标记为可交付。

## 当前问题

- Chat-first UI 已开始落地，但自然语言任务解析还需要继续增强，不能长期依赖高级表单中的 symbol/period。
- 当前报告生成后只展示 verifier/scorecard 结果，独立本地质量问题清单和主观复核门禁还未接入。
- 600519.SS 与 AMD 样本仍需修复业务画像、估值、同行对比、period/source 混入和专业数值格式问题。

## 本轮计划

1. 修复编码和中文路由基线。
2. 将 Web UI 改为 ChatGPT-like 首屏。
3. 增加自然语言任务解析和默认启用 memory。
4. 增加本地 objective quality eval。
5. 增加 LLM/Codex subjective review。
6. 将质量门禁接入 Chat 生成链路。
7. 修复 600519.SS 与 AMD 的核心报告质量问题。
8. 重跑双样本并记录链接、分数和未解决项。

## 2026-05-16 Commit 2：ChatGPT-like 首屏对话 UI

改动：

- `src/app/web_ui.py` 已重写为 Chat-first 首屏，首屏标题为“你今天在想些什么？”，主输入框 placeholder 为“有问题，尽管问”，右侧为圆形发送按钮。
- 高级表单默认折叠，Chat 成为主入口；默认开启 Chat 启动研报、memory、实时数据/A股正式源和快速模式。
- 页面状态显示覆盖 `Thinking / Planning / Evaluating / Ready / Error`，报告完成后在对话中回填报告链接、verifier、本地测评、LLM/Codex review、交付门禁和 Top issues。
- UI tabs 新增“质量评测”，并保留总览、报告、图表、引用、表格、PDF章节、公司画像、Claims、轨迹、时间线和原始数据。
- `/api/latest` 读取 `quality_report.json`、`llm_quality_review.json`、`delivery_gate.json`，为后续双层质量门禁接入预留展示面。

验证命令：

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_web_ui.py tests/test_agent_chat.py
```

质量结果：

- 12 passed。
- 当前只是 UI 展示和接口承接，objective quality eval 与 LLM/Codex review 仍未实际接入生成链路。

下一步：

- Commit 3：自然语言任务解析与 memory 默认应用，让“生成贵州茅台最新财报研报 / 生成 AMD 最新财报研报”不依赖高级表单。

## 2026-05-16 Commit 3：自然语言任务解析与 memory 应用

改动：

- 新增 `src/app/chat_task_parser.py`，规则解析用户输入中的公司、期间和生成意图。
- 已支持“贵州茅台/茅台/600519”映射到 `600519.SS`，“AMD”映射到 `AMD`。
- “最新财报”会按当前日期解析为最近已结束期间；例如 2026-05-16 解析为 `2026Q1`。
- `/api/chat` 在运行前会用解析结果覆盖 stale 表单值，并按标的自动切换 A 股/美股默认数据源。
- 参数不足时返回确认信息，不再用默认 `AAPL/2025Q4` 偷跑。
- Chat 回复会显示“已使用记忆偏好”和“事实仍以 evidence_id/citation/verifier 为准”，同时展示识别到的任务参数。

验证命令：

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py
python -m py_compile src/app/chat_task_parser.py src/app/web_ui.py
```

质量结果：

- 17 passed。
- 解析器仍是规则优先，暂未接入 LLM NER；但已满足先验证 Chat-first 生成入口的需要。

下一步：

- Commit 4：完善本地多 Agent/objective quality eval，生成 `quality_report.json/md` 和 `quality_issues.jsonl`。

## 2026-05-16 Commit 4：本地 objective quality eval

改动：

- 新增 `src/evaluation/report_quality.py`，提供可 import 的本地客观质量评测器。
- 新增 `scripts/evaluate_report_quality.py`，支持 `--run-dir` 指向 eval 根目录、`company/`、`outputs/` 或普通 run 目录。
- 输出 `quality_report.json`、`quality_report.md`、`quality_issues.jsonl`。
- 指标覆盖结构完整度、证据支撑、财务质量、多模态质量、专业深度和合规披露。
- 质量门禁要求：总分 >= 0.82、无 fatal issue、执行摘要/风险/投资结论非空、公司报告具备三表摘要/业务画像/风险提示，估值缺失时必须说明不可用原因。

验证命令：

```powershell
python -m py_compile src/evaluation/report_quality.py scripts/evaluate_report_quality.py
$env:PYTHONPATH='.'; pytest -q tests/test_report_quality.py tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py
python scripts/evaluate_report_quality.py --run-dir eval_outputs/web_link_test_AMD_2025Q4
```

质量结果：

- 19 passed。
- AMD 样本本地客观评测：`total_score=0.892`，但 `objective_pass=false`，说明硬门禁已能拦截“分数不错但仍不可交付”的报告。

下一步：

- Commit 5：新增 LLM/Codex 主观质量复核，输出 `llm_quality_review.json/md`。

## 2026-05-16 Commit 5：LLM/Codex 主观质量复核

改动：

- 新增 `src/evaluation/llm_report_review.py`，提供可 import 的主观复核能力。
- 新增 `scripts/review_report_with_llm.py`，读取 report markdown、objective quality report、verification、claims/evidence/citations 摘要，并按赛题评分标准 prompt 请求模型输出 JSON。
- 输出 `llm_quality_review.json` 和 `llm_quality_review.md`。
- 主观门禁要求：`total_score >= 0.80`、fatal issue 为 0；若模型指出“内容空洞 / 大量暂无结论 / 期间错配 / 明显乱码”，直接 fail。
- 无 API key 或模型调用失败时，`llm_review_pass=false`，不能伪装成通过。

验证命令：

```powershell
python -m py_compile src/evaluation/llm_report_review.py scripts/review_report_with_llm.py
$env:PYTHONPATH='.'; pytest -q tests/test_llm_report_review.py tests/test_report_quality.py tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py
python scripts/review_report_with_llm.py --run-dir eval_outputs/web_link_test_AMD_2025Q4
```

质量结果：

- 22 passed。
- 当前 AMD 样本主观复核输出 `llm_review_pass=false`，本机模型调用状态为 `error`，已明确阻断交付门禁。

下一步：

- Commit 6：把 verifier、objective eval、LLM review 汇总成 `delivery_gate.json`，并接入 Chat 生成链路与 Web UI。

## 2026-05-16 Commit 6：质量评测接入 Chat 生成链路

改动：

- 新增 `src/evaluation/delivery_gate.py`，合并 verifier、objective eval、LLM review 三层结果。
- `src/app/web_ui.py` 新增 `run_delivery_quality_pipeline()`，报告生成完成后自动运行：
  1. objective quality eval；
  2. LLM/Codex 主观 review；
  3. delivery gate 汇总。
- `/api/chat` 和 `/api/run` 都会写出 `quality_report.json`、`llm_quality_review.json`、`delivery_gate.json`。
- Chat 返回中包含三层质量结果；前端“质量评测”tab 可直接展示 objective 分数、LLM review 和 fatal/blocker/warning 问题。

验证命令：

```powershell
python -m py_compile src/evaluation/report_quality.py src/evaluation/llm_report_review.py src/evaluation/delivery_gate.py src/app/web_ui.py scripts/evaluate_report_quality.py scripts/review_report_with_llm.py
$env:PYTHONPATH='.'; pytest -q tests/test_delivery_gate.py tests/test_llm_report_review.py tests/test_report_quality.py tests/test_chat_task_parser.py tests/test_web_ui.py tests/test_agent_chat.py
```

质量结果：

- 24 passed。
- 当前最终交付门禁严格要求 `verification_passed=true`、`objective_pass=true`、`llm_review_pass=true` 三者同时成立。

下一步：

- Commit 7：针对 600519 和 AMD 的内容缺陷做报告链路修复。

## 2026-05-16 Commit 7：双样本内容质量修复

改动：

- `DeepAnalyzeAgent` 生成 PDF-derived claims 时新增 `expected_period` 过滤，避免 `2025Q4` 主报告把 `2026Q1` PDF 片段当作核心业务/财务 claim。
- 中文年度报告片段会识别为 `Q4`，中文季度报告片段会识别为对应季度，用于 period gate。
- AMD 若缺少完整业务/同行/估值/风险/投资结论 claims，会补充证据约束下的业务画像框架、NVIDIA/Intel/Broadcom 同行框架、估值不可用原因、敏感性框架、风险与中性/审慎观察结论。
- Eastmoney 财务 claims 使用“亿元”格式展示，不再用科学计数法或原始超长数字。
- 估值不足时显式写“估值不可用原因”，避免伪造 P/E、P/B 或 DCF 目标价。

验证命令：

```powershell
python -m py_compile src/agents/deep_analyze_agent.py
$env:PYTHONPATH='.'; pytest -q tests/test_data_enrichment.py tests/test_multi_agent_workflow.py::test_final_answer_inserts_missing_claim_sections tests/test_report_quality.py tests/test_delivery_gate.py
```

质量结果：

- 13 passed。
- 这一步修复的是生成链路，旧的 `web_link_test_*` 产物需要在 Commit 8 重跑后才能反映新内容。

下一步：

- Commit 8：重新跑“贵州茅台最新财报研报”和“AMD 最新财报研报”，生成网页链接和三层质量结果。

## 2026-05-16 Commit 8：双样本重跑与记录

改动：

- 修复 Chat 英文生成意图：`generate ... company report` 现在能进入 `report_run`。
- 修复 objective eval 科学计数法误报：不再把 evidence_id/hash 中的 `2e0` 片段当成科学计数法。
- 重跑 Chat-first 双样本，并写出 `quality_report.json/md`、`llm_quality_review.json/md`、`delivery_gate.json`。
- 结果汇总写入 `eval_outputs/chat_first_delivery_summary.json`。

验证命令：

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_chat_task_parser.py tests/test_agent_chat.py tests/test_data_enrichment.py tests/test_report_quality.py tests/test_llm_report_review.py tests/test_delivery_gate.py tests/test_web_ui.py
```

质量结果：

- 33 passed。
- A 股样本：`600519.SS 2026Q1`，report: `http://127.0.0.1:8790/eval_outputs/chat_first_delivery_600519SS_latest/company/reports/report.html`
  - verifier: `true`
  - company_report_overall_score: `0.9375`
  - objective_pass: `true`，objective_total_score: `1.0`
  - llm_review_pass: `false`，llm_total_score: `1.0` 但存在 fatal issue
  - delivery_pass: `false`
  - 主要问题：LLM/Codex 认为内容仍偏空洞，估值/敏感性/同行对比仍偏框架化。
- 美股样本：`AMD 2026Q1`，report: `http://127.0.0.1:8790/eval_outputs/chat_first_delivery_AMD_latest/company/reports/report.html`
  - verifier: `true`
  - company_report_overall_score: `0.8542`
  - objective_pass: `false`，objective_total_score: `0.8907`
  - llm_review_pass: `false`，llm_total_score: `0.45`
  - delivery_pass: `false`
  - 主要问题：三表摘要不完整，缺资产负债表/现金流完整摘要，内容仍偏框架化，投资洞察不足。

下一步：

- 下一轮应集中修复“内容空洞”而不是继续堆 UI：把三表表格行强制写入正文、补估值可计算路径、对 AMD 增加 SEC 10-Q/10-K 业务分部与现金流证据，对 600519 增加同行白酒对比和可复核估值。
