# Open DeepReport++ — Codex 自动执行说明

你是当前仓库中的代码代理。你的目标不是一次性写完所有功能，而是**按阶段**构建一个“证据驱动的公司/个股研报生成系统”。

## 一个重要前提：先拉取参考仓库，再谈“精准复用骨架”
如果当前仓库中**还没有**参考实现 `DeepReport` 的本地副本，那么你**不能声称已经精准复用其骨架**。

因此，正式开发前必须先执行一个“参考仓库获取与审计阶段”。

默认参考仓库：
- GitHub: `https://github.com/wisdom-pan/DeepReport.git`
- 本地只读放置路径：`references/DeepReport_ref/`

### 参考仓库处理原则
1. 参考仓库只用于阅读、审计、抽取骨架，不作为主开发目录。
2. 不要直接在 `references/DeepReport_ref/` 里开发新功能。
3. 你必须先产出一份“骨架映射报告”，说明哪些结构保留、哪些重写、哪些删除。
4. 如果当前环境无法联网 clone，立刻停止，并明确告诉用户需要手动执行 clone 命令。
5. 如果 `references/DeepReport_ref/` 已存在，则跳过 clone，直接进入审计。

## 项目目标
构建 `Open DeepReport++`：一个面向公司/个股研报的、多阶段、可验证、可训练增强的报告系统。

第一阶段只做：
- 公司/个股研报
- markdown/html 输出
- claim-first 管线
- 图表、引用、规则校验
- 本地可跑的最小工程闭环

## 资源约束
### 本地开发机
- GPU: 3060 Ti
- 本地**不做训练**
- 本地优先 mock / template / 小样本
- 本地只做工程闭环、数据结构、流程调试、测试

### 云端训练机
- 单卡 48GB
- 只负责离线训练与大规模离线推理
- 训练模块限制为：
  1. reranker
  2. verifier
  3. rewriter
- 云端不承担高频调试开销

## 硬性工程原则
1. 先参考仓库审计，后本仓库开发。
2. 先 schema，后 pipeline。
3. 先 mock，后真实数据。
4. 先规则 verifier，后模型 verifier。
5. 先本地调通，后云端训练。
6. generation backend 必须抽象为：
   - mock
   - local_small
   - remote
   - finetuned
7. 所有模型名、路径、batch size、topk、开关必须进 yaml。
8. 训练脚本不得依赖在线抓取。
9. 任何阶段都不要直接引入重型本地大模型依赖，除非该阶段明确要求。
10. 复用“骨架”指的是复用：目录组织、模块职责切分、运行入口、配置方式、agent 协作边界；不是照抄业务逻辑。

## 输出习惯
每完成一个阶段，必须输出：
1. 已修改文件列表
2. 新增命令/脚本
3. 当前可运行入口
4. 未完成项与风险
5. 下一阶段建议

不要一口气越过阶段边界。**每次只执行当前阶段**，执行完就停下并总结。

---

# 阶段计划

## Stage -1：下载并审计参考仓库（DeepReport）
### 目标
把“复用骨架”建立在真实代码审计之上，而不是建立在 README 猜测上。

### 必做项
1. 检查 `references/DeepReport_ref/` 是否存在。
2. 如果不存在，则尝试执行：
   - `mkdir -p references`
   - `git clone https://github.com/wisdom-pan/DeepReport.git references/DeepReport_ref`
3. 如果 clone 失败：
   - 停止后续工作
   - 明确输出失败原因
   - 告诉用户需要手动执行的命令
4. clone 成功或目录已存在后，读取并审计：
   - `README.md`
   - `main.py`
   - `config.py`
   - `docker-compose.yml`
   - `requirements.txt`
   - `src/` 目录结构
   - `docs/` 目录结构
5. 生成以下文档：
   - `docs/deepreport_repo_audit.md`
   - `docs/deepreport_skeleton_mapping.md`

### 审计文档必须回答的问题
#### `deepreport_repo_audit.md`
- 仓库真实目录结构是什么
- 主入口是什么
- 配置入口是什么
- agent/工具/搜索/报告相关模块在哪里
- 哪些部分是我们可以直接借鉴的工程骨架
- 哪些部分明显与我们目标不一致

#### `deepreport_skeleton_mapping.md`
必须给出三列映射：
- DeepReport 原模块
- Open DeepReport++ 对应模块
- 处理策略（保留 / 改写 / 删除 / 延后）

至少覆盖：
- 目录结构
- 运行入口
- 配置层
- agent 编排层
- 搜索/检索层
- 报告导出层
- Docker 层
- 依赖管理

### 验收标准
- 参考仓库已拉到本地，或明确说明无法拉取
- `docs/deepreport_repo_audit.md` 已生成
- `docs/deepreport_skeleton_mapping.md` 已生成
- 只有在这一步完成后，才允许进入 Stage 0

### 完成后停止
不要进入 Stage 0。先输出审计结论和建议。

---

## Stage 0：仓库骨架与配置体系
### 目标
在参考仓库审计结论的基础上，建立可维护工程骨架，暂不接真实模型与真实数据。

### 必做项
创建：
- `configs/`
- `scripts/`
- `src/app`
- `src/schemas`
- `src/data`
- `src/features`
- `src/retrieval`
- `src/agents`
- `src/templates`
- `src/charts`
- `src/generation`
- `src/training`
- `src/evaluation`
- `src/utils`
- `tests/`
- `data/raw`
- `data/curated`
- `data/features`
- `data/cache`
- `data/outputs`
- `data/reports`
- `docs/`
- `references/`

创建文件：
- `pyproject.toml`
- `README.md`
- `.env.example`
- `scripts/run_local_smoke.py`
- `src/utils/config.py`
- `configs/app.yaml`
- `configs/local_debug.yaml`
- `configs/local_smoke.yaml`
- `configs/cloud_train.yaml`
- `configs/data_sources.yaml`
- `configs/report_company.yaml`
- `configs/model_backends.yaml`
- `configs/reranker.yaml`
- `configs/rewriter.yaml`
- `configs/verifier.yaml`

### 额外要求
- `README.md` 顶部必须说明：本项目受 `DeepReport` 工程骨架启发，但不直接复制其业务逻辑。
- `docs/deepreport_skeleton_mapping.md` 中被标记为“保留/改写”的结构，优先反映到当前骨架中。

### 验收标准
- 所有 `src` 子模块可 import
- 配置加载器可读取 `local_debug.yaml`
- `pytest -q` 至少能跑一个基础测试

### 完成后停止
执行完后不要进入 Stage 1。输出总结并等待下一条指令。

---

## Stage 1：Schema 层
### 目标
统一模块间的输入输出结构。

### 必做项
实现：
- `src/schemas/evidence.py` -> `EvidenceItem`
- `src/schemas/claim.py` -> `ClaimItem`
- `src/schemas/chart.py` -> `ChartSpec`
- `src/schemas/report.py` -> `ReportSection`, `ReportDocument`
- `src/schemas/task.py` -> `ReportTask`

### 关键字段
#### EvidenceItem
- evidence_id
- source_type
- title
- source_url
- publish_time
- content
- symbol
- period
- trust_level
- metadata

#### ClaimItem
- claim_id
- section_name
- claim_text
- evidence_ids
- numeric_values
- risk_level
- confidence
- notes

#### ChartSpec
- chart_id
- chart_type
- title
- source_tables
- source_fields
- output_path
- caption

#### ReportSection
- section_name
- section_title
- claims
- charts
- body_markdown
- citations

#### ReportDocument
- report_id
- symbol
- period
- report_type
- sections
- generated_at
- export_paths

### 验收标准
- 每个 schema 有类型注解与文档注释
- 支持 `from_dict` / `to_dict`
- 有 `tests/test_schemas.py`
- round-trip 测试通过

### 完成后停止
不要进入 Stage 2。

---

## Stage 2：本地最小数据层（仅 mock / local_file）
### 目标
先打通数据结构，不接外网。

### 必做项
实现：
- `src/data/fetch_base.py`
- `src/data/fetch_market.py`
- `src/data/fetch_financials.py`
- `src/data/fetch_news.py`
- `src/data/fetch_filings.py`
- `src/data/normalize.py`
- `src/data/dedup.py`
- `src/data/manifest.py`

### 要求
- `BaseFetcher` 抽象类
- mode 支持：
  - `mock`
  - `local_file`
  - `future_api`
- 第一版不得联网
- 从 `tests/fixtures` 或 `data/raw/mock` 读样例
- 输出到 `data/curated/*.parquet`

### 统一 manifest 字段
- sample_id
- source_type
- symbol
- period
- title
- publish_time
- content
- source_url
- trust_level

### 完成后停止
不要进入下一阶段。

---

## Stage 3：程序化特征层
### 目标
把“报告系统”建立在程序化分析上，而不是建立在 LLM 自由发挥上。

### 必做项
实现：
- `src/features/financial_ratios.py`
- `src/features/trend_analysis.py`
- `src/features/peer_compare.py`
- `src/features/risk_signals.py`

### 输出
- `data/features/*.parquet`
- `feature_report.json`

### 完成后停止
不要进入下一阶段。

---

## Stage 4：claim-first 最小报告流水线
### 目标
在本地先生成一份“结构正确、证据挂钩、可导出”的公司研报。

### 必做项
实现：
- `src/agents/planner.py`
- `src/agents/analyst.py`
- `src/agents/writer.py`
- `src/agents/verifier.py`
- `src/agents/orchestrator.py`
- `src/app/pipeline.py`
- `src/app/main.py`

### 第一版限制
- planner 固定章节模板
- analyst 基于规则生成 claim table
- writer 默认 template_only
- verifier 默认 rule-based

### 输出
- `claim_table.json`
- `report.md`
- `verification_report.json`

### 完成后停止
不要进入下一阶段。

---

## Stage 5：图表层
### 目标
把结构化分析可视化，并接入报告。

### 必做项
实现：
- `src/charts/line_chart.py`
- `src/charts/bar_chart.py`
- `src/charts/table_chart.py`
- `src/charts/render.py`

### 输出
- 图表 png
- metadata json

### 完成后停止
不要进入下一阶段。

---

## Stage 6：generation backend 抽象
### 目标
让报告生成不绑定具体模型实现。

### 必做项
实现：
- `src/generation/backend_base.py`
- `src/generation/backend_mock.py`
- `src/generation/backend_local_small.py`
- `src/generation/backend_remote.py`

并让 writer 支持：
- `template_only`
- `backend_generate`
- 失败自动 fallback

### 完成后停止
不要进入下一阶段。

---

## Stage 7：最小检索层（本地先 BM25）
### 目标
为后续 reranker 数据构造和章节证据选择打底。

### 必做项
实现：
- `src/retrieval/evidence_store.py`
- `src/retrieval/bm25_index.py`
- `src/retrieval/retrieve.py`
- `src/retrieval/faiss_index.py`（只留接口）

### 第一版限制
- 只做 BM25
- 不做真实 FAISS 实现

### 完成后停止
不要进入下一阶段。

---

## Stage 8：导出训练数据（供云端使用）
### 目标
把本地工程结果转成可训练的离线样本。

### 必做项
实现：
- `src/training/build_reranker_dataset.py`
- `src/training/build_rewriter_dataset.py`
- `src/training/build_verifier_dataset.py`

### 输出
- parquet
- jsonl
- dataset_report.json

### 完成后停止
不要进入下一阶段。

---

## Stage 9：云端训练与本地 fallback 接入
### 目标
让 48GB 云卡只负责训练，不负责高频调试。

### 必做项
实现：
- `src/training/train_reranker.py`
- `src/training/train_rewriter.py`
- `src/training/train_verifier.py`
- `src/training/infer_reranker.py`
- `src/training/infer_verifier.py`
- `src/generation/rewriter_infer.py`
- `scripts/upload_to_cloud.sh`
- `scripts/download_from_cloud.sh`
- `docs/cloud_training.md`

### 限制
- 所有训练脚本只吃离线导出数据
- 不允许直接依赖在线抓取
- 本地没有 checkpoint 时必须自动 fallback

### 完成后停止
不要进入下一阶段。

---

## Stage 10：报告导出与回归测试
### 目标
完成 markdown/html 报告导出，并建立基本回归测试。

### 必做项
实现：
- `src/templates/company_outline.py`
- `src/templates/section_prompts.py`
- `src/templates/html_template.py`
- `src/templates/markdown_template.py`
- 回归测试与 smoke test

### 输出
- `report.md`
- `report.html`
- `report.json`

### 完成后停止
不要自行扩展新功能。
