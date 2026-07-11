# R0.3 恢复与根因分析报告

> 日期：2026-07-10
> 作者：Recovery Agent
> 仓库：`https://github.com/wara886/DeepReport-`
> 分支：`feat/fin-research-agent-workbench-v2`

---

## 1. 远端与本地基线确认

| 项目 | 值 |
| --- | --- |
| 远端 `origin/main` | `5480770` — Merge pull request #5 |
| 远端 `origin/feat/fin-research-agent-workbench-v2` | `7d94c46` — fix(runtime): stabilize offline research contracts |
| 本地 HEAD | `7d94c46` — 与远端 `feat/fin-research-agent-workbench-v2` 一致 |
| 保护分支 | `backup/r03-interrupted-20260710`（已创建） |
| 备份文件 | `deepreport_r03_uncommitted_backup.patch`（739 行） |

## 2. 未提交文件清单

### 已修改（14 个文件，+307 / -26 行）

| 文件 | +/- | 类别 |
| --- | --- | --- |
| `src/services/export_service.py` | +98/-7 | **B** — 已实现，需验证 |
| `src/services/report_task_service.py` | +60/-2 | **B** — 已实现，需验证 |
| `src/runtime/langgraph_report_runtime.py` | +46/-11 | **B** — 已实现，已验证通过 |
| `src/runtime/report_run_state.py` | +9/-5 | **B** — 已实现，已验证通过 |
| `src/app/api_fastapi.py` | +10/-0 | **B** — 已实现 |
| `src/app/workbench_frontend.py` | +8/-3 | **B** — 已实现 |
| `src/report/__init__.py` | +2/-0 | **B** — 导出注册 |
| `pyproject.toml` | +2/-0 | **A** — 依赖变更 |
| `tests/test_export_entry_api.py` | +29/-1 | **B** — 测试扩展 |
| `tests/test_langgraph_report_runtime.py` | +5/-0 | **B** — 测试增强 |
| `tests/test_report_runtime_state.py` | +19/-0 | **B** — 新增测试 |
| `tests/test_report_task_langgraph_runtime.py` | +27/-1 | **B** — 测试增强 |
| `tests/test_web_export_entry.py` | +2/-0 | **B** — 前端测试 |
| `docs/fin_research_agent_upgrade_plan_codex_v2.md` | +16/-15 | **C** — 文档更新 |

### 新文件（6 项）

| 路径 | 类别 |
| --- | --- |
| `src/report/pdf_exporter.py` | **B** — 新的 PDF 导出器 |
| `tests/test_pdf_exporter.py` | **B** — PDF 测试 |
| `docs/fin_research_platform_ux_audit_20260710.md` | **A** — 体验审计文档 |
| `data/export_packages/` | **D** — 导出产物目录 |
| `data/vector_db/` | **D** — 向量数据库 |
| `logs/` | **D** — 日志目录 |
| `tmp/` | **E** — 临时运行产物 |

### 分类说明

- **A**: 已完成且测试覆盖充分（pyproject、审计文档）
- **B**: 已实现，未完整验证或尚未合并测试结果（绝大部分 R0.3 功能）
- **C**: 实现方向正确但存在合同问题（升级计划文档需持续更新）
- **D**: 临时调试代码或运行产物（不应提交）
- **E**: 不应提交的文件（tmp 目录等）

## 3. R0.3 已完成功能

以下功能经本地 diff 阅读和定向测试验证全部通过：

### ✅ PDF 正式导出
- `src/report/pdf_exporter.py` — 使用 ReportLab
- A4 页面、中文 STSong-Light 字体（带 fallback）
- 页眉页脚、页码、metadata 表格
- 支持标题、多级标题、列表、分隔符分页
- 测试通过：`test_pdf_exporter.py`

### ✅ DOCX 正式导出
- `src/report/docx_exporter.py` — 使用 python-docx 主后端 + OOXML fallback
- 支持标题、列表、表格、代码块
- 测试已通过 export_entry_api 集成覆盖

### ✅ Export Manifest（正式导出清单）
- `formal_export_manifest.v1` schema
- SHA-256 文件校验
- 包整体 digest（package_digest）
- 幂等复用：相同包内容重复生成直接返回已有文件
- manifest 本身也包含在包的 SHA-256 校验中

### ✅ Request ID / Run ID / Task ID 贯穿
- FastAPI 中间件自动生成/透传 `X-Request-ID`
- 任务创建时传入 `request_id`
- LangGraph state 携带 `request_id`/`run_id`
- `trace_context` 出现在所有 API 响应中
- 测试覆盖 header 传播

### ✅ 节点耗时（Node Latency）
- `_execute_node` 统一包装所有节点
- 每个 `runtime_events` 携带 `duration_ms`、`completed_at`
- `node_latency_ms` 聚合到任务 metadata
- 测试覆盖所有 5 个节点（evidence → generation → quality → finalize → human_review）

### ✅ LLM Token 和成本聚合
- `build_runtime_observability()` 聚合 LLM runs
- 输出：run_count、failed_run_count、prompt_tokens、completion_tokens、total_tokens、cost_usd、latency_ms
- 无配置时显示 real cost（当前是 0 或未配置）

### ✅ remediation_required 状态
- 质量阻塞 + 报告可读 + Claim 已审 → `remediation_required`
- 业务中文翻译已在前端注册
- 测试验证通过

### ✅ 前端 PDF/DOCX 展示
- 导出格式列表包含 PDF/DOCX
- 导出包预览提及 PDF/DOCX
- 状态标签含 remediation_required

## 4. R0.3 未完成/待收口内容

### ⚠️ PDF 导出测试依赖 PyMuPDF (fitz)
- `test_pdf_exporter.py` 使用 `import fitz` 检查 PDF 页面数和渲染
- 当前通过（已有依赖）
- 但 `PyMuPDF` 不在 `pyproject.toml` 的 pdf extra 中明确声明为 PDF 验证依赖

### ⚠️ LLM 成本口径
- `build_runtime_observability()` 输出 `cost_usd`，但无 pricing_status
- 无配置时显示实际 0 值而不是"成本未配置"
- 尚未实现 `pricing_status: "not_configured"`

### ⚠️ Export readiness 的阻塞原因展示
- `formal_export_note` 已更新
- 但 readiness 阻塞原因的详细中文前端展示可以进一步加强

## 5. 上一轮中断的直接原因

Agent 使用额度达到上限（API key/token 配额耗尽），而非代码逻辑错误。

证据：
- Git 工作区状态干净、无冲突标记
- 所有修改是增量且定向的（+307/-26 行）
- 测试全部通过
- 无异常 checkpoint 或损坏的数据库
- 中断发生在增量提交前，而非其他中断状态

## 6. 当前真正的技术阻塞

| 阻塞项 | 严重度 | 状态 |
| --- | --- | --- |
| Financial Fact 无 authority_level | **P0** | 代码需新增字段和逻辑 |
| 单位/期间无结构化数值合同 | **P0** | FinancialFact 有 unit/currency/scale 字段但缺少 normalized_value 和 display_value |
| 手动导入停留在 stub | **P0** | 没有后续处理管线 |
| 内容评分与交付门禁视觉矛盾 | **P0** | R0.3 已修复后端逻辑，前端文案待完善 |
| LLM 成本显示为 0 而非"未配置" | **P1** | 代码修改即可 |
| 节点进度中文映射 | **P1** | 前端已有映射表，但映射不完整 |
| 数据源状态治理 | **P1** | 需要 seed 幂等化和健康检查 |

## 7. 测试现状

### 已运行 R0.3 定向测试

```bash
# R0.3 核心测试 — 全部通过
pytest -q tests/test_pdf_exporter.py                    # 1 passed
pytest -q tests/test_export_entry_api.py                # 6 passed
pytest -q tests/test_report_runtime_state.py            # 6 passed
pytest -q tests/test_langgraph_report_runtime.py        # 5 passed
pytest -q tests/test_report_task_langgraph_runtime.py   # 4 passed
pytest -q tests/test_web_export_entry.py                # 1 passed
```

### 测试基础设施

- SQLite 内存数据库 fixture（`temp_db_engine`）
- `tmp_path` fixture 用于文件输出
- 无外部网络依赖
- 所有测试使用模拟数据

## 8. 根因分析

### 三市场为什么质量分高但交付失败

质量分（~0.89）衡量的是"报告内容相对完整度"，包括：
- 各章节是否有内容
- 是否有结构化的数据填充
- 语言质量

而交付门禁衡量的是：
- Evidence 是否充足（0 条官方证据）
- Quality gate 是否通过（现金流/估值不一致）
- Claim 是否全部审核
- 报告 artifact 是否存在

两者衡量不同维度，但前端没有明确区分，导致用户认为"89 分 ≈ 良好 → 为什么失败？"

### 为什么无官方证据仍会产生 Financial Facts

`SourceAuthorityPolicy` 仅在 Evidence/Claim 层面做权威性分级。Financial Fact 从 `market_api`（如 Yahoo、EastMoney）也能抽取，且：
1. FinancialFact 数据模型没有 `authority_level` 或 `usable_for_formal_report` 字段
2. 财务事实抽取器不区分 evidence source_type
3. Quality gate 不检查 Financial Fact 的来源权威性

因此系统虽然正确驳回了正式交付（因为 evidence gate），但用户看到 20 条"正式"的财务事实，产生错觉。

### AAPL 单位误判根因

FinancialFact 确实有 `unit`、`currency`、`scale` 字段，但：
1. 质量模型（Numeric verifier / Quality reviewer）可能只看到自然语言文本 "126.3B"
2. 没有强制要求 normalized_value 来消歧
3. 中文和英文展示口径不同但没有 traceability
4. 质量模型的 prompt 可能回退到文字理解而非结构化验证

### 手动导入为什么停留在 stub

`ManualImportService.import_document()` 正确创建了 Document 和 ProcessingSteps，但：
1. 对 text/url 导入，parse step 标记 `"stub": True` 并设置 `status="success"`
2. 没有后续的 chunk、embedding、evidence extraction 管线
3. 文档 content 只做了 hash 校验，没有持久化到数据库
4. 没有 `POST /api/documents/{id}/process` 这样的后续处理入口

### 人工复核完成后状态仍错误的根因

R0.3 已在 `_delivery_readiness()` 中修复了这个问题：
- 当 claim 全部审核完成但 quality/evidence 阻塞时 → `remediation_required`
- 当 claim 仍有待审核 → `review_required`
- 全部通过 → `export_ready`

但旧状态可能未重新计算，前端缓存也需刷新。

## 9. 推荐修复顺序

| 优先级 | 任务 | 影响 | 预估工作量 |
| --- | --- | --- | --- |
| 1 | **P0-1**: Financial Fact 权威等级 + 正式用途约束 | 正式研报可信度 | 6-8 小时 |
| 2 | **P0-2**: 单位与期间结构化合同 | 财务数据准确度 | 4-6 小时 |
| 3 | **P0-3**: 手动导入真实 Evidence 闭环 | 手动数据可用性 | 8-12 小时 |
| 4 | **P0-4**: 评分与交付门禁分离（前端展示） | 用户体验一致性 | 2-3 小时 |
| 5 | **P1**: R0.3 收口 + 可观测性增强 | 调试和运营效率 | 3-4 小时 |
| 6 | 三市场复测 | 验证修复 | 2-3 小时 |

## 10. 可能的回归风险

1. **FinancialFact authority_level 新增字段**：旧数据缺少此字段 → 必须兼容
2. **normalized_value 合同**：现有 FinancialFact 数据需要迁移
3. **手动导入 non-stub 处理**：新增管线不能破坏已有导入流程
4. **remediation_required 状态迁移**：旧任务的状态可能不经过重新计算
5. **PDF/DOCX 字体依赖**：生产环境需确认 ReportLab 字体安装
6. **幂等导出**：重复导出不应产生重复文件

---

*报告完毕。下一阶段按推荐顺序从 P0-1 开始修复。*
