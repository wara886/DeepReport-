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
