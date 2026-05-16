# Web UI 与质量门禁工作记录

更新时间：2026-05-16

## 工作规则

- 每次开工先读取 `docs/project_status_deepreport_multiagent.md` 和本文档，再检查最新 eval 输出。
- 每完成一个功能都要更新文档、记录验证命令和质量问题，并单独提交一次 git。
- Chat memory 只用于用户偏好和任务上下文，不替代 `evidence_id`、citation、numeric audit 或 verifier。
- 只有 `verifier + objective quality eval + LLM/Codex review` 三层都通过，报告才标记为可交付。

## 当前问题

- Web UI 已有 `/api/chat`，但首屏仍像侧栏工作台，不像 ChatGPT 式主入口。
- Chat 还不能稳定从“生成某公司最新财报研报”自动解析公司、最新期间和数据源确认。
- 当前报告生成后只有 verifier/scorecard，缺少独立的本地质量问题清单和主观复核门禁。
- 600519.SS 与 AMD 样本暴露出空章节、估值缺失、同行对比缺失、数值格式不专业、period/source 混入等问题。

## 本轮计划

1. 修复编码和中文路由基线。
2. 将 Web UI 改为 ChatGPT-like 首屏。
3. 增加自然语言任务解析和默认启用 memory。
4. 增加本地 objective quality eval。
5. 增加 LLM/Codex subjective review。
6. 将质量门禁接入 Chat 生成链路。
7. 修复 600519.SS 与 AMD 的核心报告质量问题。
8. 重跑双样本并记录链接、分数和未解决项。

## 最近验证命令

```powershell
$env:PYTHONPATH='.'; pytest -q tests/test_web_ui.py tests/test_agent_chat.py tests/test_data_enrichment.py tests/test_competition_runner.py
python scripts/run_chat_ui_smoke.py
```
