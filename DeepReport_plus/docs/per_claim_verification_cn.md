# 逐条 Claim 验证明细说明（per_claim_verification）

## 1. 目标

`per_claim_verification.json` / `per_claim_verification.csv` 是新增的审核诊断产物，用于给出逐条 claim 的 grounded 判定（是否被当前阈值规则接受），避免将 `verification_report.json` 误用为语义级验证结果。

当前 grounded 判定规则显式为：

- `is_grounded = (confidence >= threshold)`

其中 `threshold` 来自 `verifier_checkpoint.json` 的 `confidence_threshold`；若 checkpoint 不存在，则回退为 `0.5`。

## 2. 字段定义

逐条记录至少包含以下字段：

- `claim_id`：claim 唯一标识
- `claim_text`：claim 原文
- `section_name`：所属章节
- `confidence`：claim 置信度
- `threshold`：当前判定阈值
- `is_grounded`：是否满足 grounded（`confidence >= threshold`）
- `evidence_ids`：证据 ID 列表
- `numeric_values`：claim 绑定的数值字段
- `review_priority`：审核优先级（`high` / `medium` / `low`）
- `notes`：规则说明与风险提示

## 3. 与现有文件的区别

`claim_table.json`：

- 定位：claim 生成结果表（生成侧产物）
- 粒度：逐条 claim
- 作用：记录 claim 本身及其证据、数值、置信度等原始信息
- 不做：不直接给出 grounded 判定

`verification_report.json`：

- 定位：baseline 规则校验摘要（规则侧产物）
- 粒度：整体 case 级摘要
- 作用：输出 `passed` / `error_count` / `warning_count` / `claim_count` 等汇总信号
- 不做：不提供逐条 claim 的 grounded 明细，也不等同语义验证结果

`report_review_zh.md`：

- 定位：人工审核中文视图（人工审核侧产物）
- 粒度：以章节和审核提示组织
- 作用：帮助人工审阅 claim 文本、风险点和优先级
- 不做：不是标准化机器可读逐条判定表

`per_claim_verification.json` / `per_claim_verification.csv`（新增）：

- 定位：逐条 claim grounded 诊断表（诊断侧产物）
- 粒度：逐条 claim
- 作用：显式给出 `threshold` 与 `is_grounded`，并携带审核优先级和说明字段
- 适用：用于诊断、回归分析、抽检排序，不替代 baseline 报告导出

## 4. 使用建议

- 需要逐条判断 grounded 时，优先使用 `per_claim_verification.*`。
- 需要看 baseline 是否通过规则门槛时，使用 `verification_report.json`。
- 需要查看 claim 原始内容与证据绑定时，使用 `claim_table.json`。
- 需要人工阅读和审稿引导时，使用 `report_review_zh.md`。
