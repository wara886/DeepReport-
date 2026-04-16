# 两个项目细致总结：ReceiptVLM 与 Novel-to-Video Agentic 多模态生成系统

更新时间：2026-04-14（补充 Novel-to-Video 工程补强项）  
用途：简历扩写、面试复盘、项目答辩、后续补实验记录

> 这份文档的写法刻意区分“已经有本地文件支撑的数据”和“简历/面试口径中提到但仍需补充可复现实验记录的数据”。面试时最怕的不是项目不够复杂，而是数字口径不统一。这里优先把能自洽、能展开讲的主线整理清楚。

---

## 0. 两个项目的定位

| 项目 | 一句话定位 | 更适合投递方向 |
|---|---|---|
| ReceiptVLM | 面向收据图片的多模态结构化抽取后训练项目，通过数据治理、Curriculum SFT、GRPO 奖励建模和离线评估，把通用 VLM 推向稳定 JSON 抽取。 | 多模态理解、文档智能、MLLM 后训练、结构化抽取、应用算法 |
| Novel-to-Video | 面向小说/短句生成短视频的 Agentic 多模态生成系统，通过 Planner / Router / Executor / Judge / Retry / Memory / RAG，把旧版单次生成流程升级为可追踪、可质检、可恢复的多模型工作流。 | AIGC 应用算法、多模态生成、Agent workflow、RAG 应用、生成式产品工程 |

两个项目刚好互补：

- ReceiptVLM 证明你能做“模型后训练 + 数据治理 + 评测闭环”。
- Novel-to-Video 证明你能做“多模型生成系统 + Agentic workflow + 工程上线”。
- 面试时可以统一成一个大的能力画像：不是只会调 API，而是能围绕真实任务建立数据、模型、工作流、评估和失败恢复闭环。

---

# 1. ReceiptVLM：基于课程学习与 GRPO 的收据结构化理解

## 1.1 业务问题

目标场景是报销录入、财务归档、票据审核等，需要把收据图片抽取成固定结构：

```json
{
  "menu": [
    {
      "name": "",
      "count": "",
      "unit_price": "",
      "price": ""
    }
  ],
  "subtotal": {
    "subtotal_price": "",
    "tax_price": "",
    "service_price": "",
    "discount_price": ""
  },
  "total": {
    "total_price": "",
    "cash_price": "",
    "change_price": "",
    "card_price": ""
  }
}
```

旧问题不是“模型不会看图”这么简单，而是结构化任务有几类典型失败：

- 输出不是合法 JSON，后处理无法解析。
- 有 JSON 但缺少 `menu / subtotal / total` 顶层 schema。
- 金额格式混乱，例如货币符号、千分位、`.00`、逗号小数等。
- 长菜单容易截断、闭合失败、字段错位。
- subtotal 和 total 容易混淆，尤其税费、服务费、折扣字段。
- 空菜单、稀疏字段容易幻觉生成。

因此这个项目的核心不是“简单微调一个 VLM”，而是把收据理解重新定义为一个 **固定 schema 的多模态结构化抽取任务**。

## 1.2 旧版/初始方案的问题

从仓库已有评估文件看，早期版本的可解析性很差：

| 版本/文件 | sample_count | JSON 合法率 | schema 命中率 | total exact | subtotal exact | menu_count_mae | menu_field_micro_f1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `full_sft_validation_metrics.json` | 100 | 4% | 4% | 2% | 1% | 1.75 | 0.000 |
| `full_grpo_v4_validation_metrics.json` | 100 | 6% | 6% | 1% | 1% | 1.75 | 0.000 |

这说明早期链路最大问题不是某个字段差一点，而是整体输出经常不可解析。对业务来说，不合法 JSON 基本等于不可用。

旧版的核心短板：

- 数据没有充分清洗，坏图和脏标签会直接污染训练。
- prompt 虽然要求“严格 JSON”，但没有把输出结构稳定性作为训练目标逐步建立。
- SFT 一次性学习完整复杂结构，模型容易同时被长菜单、金额格式、JSON 闭合拖垮。
- GRPO reward 如果只粗粒度打分，容易奖励不到具体字段，训练信号稀疏。
- 评估缺少 detail 级 bad case 分析，很难知道失败来自 JSON、schema、金额还是菜单。

## 1.3 当前改进点

### 1. 数据治理与 schema 统一

做了坏图筛除、标签清洗、金额归一化、字段 canonicalize，把收据抽取统一到固定 schema。

当前仓库可复现的数据报告：

| split | 原始输入 | 清洗后 | 丢弃 | 修正 |
|---|---:|---:|---:|---:|
| train | 800 | 774 | 26 | 38 |
| validation | 100 | 98 | 2 | 3 |
| test | 100 | 95 | 5 | 5 |

说明：简历中曾写过 `2974/198/195` 的扩展数据口径，但仓库当前能直接验证的 `sft_curriculum/report.json` 是 `774/98/95`。如果继续在简历中使用 `2974/198/195`，建议补一份“扩展数据来源、划分脚本、最新评估文件”的可复现实验记录。

### 2. Curriculum SFT

把训练样本按复杂度分阶段，而不是一上来就让模型学习所有长菜单复杂样本：

- `stage1_core`：核心金额和短结构，先让模型稳定输出 JSON 和关键字段。
- `stage2_short_menu`：引入较短菜单，学习 item 字段。
- `stage3_full_clean`：使用完整清洗样本，学习最终分布。

这个设计的价值：

- 先解决“输出能不能解析”，再解决“字段准不准”。
- 降低长菜单和复杂字段对早期训练的干扰。
- 让同一套 LoRA adapter 接力训练，而不是每个阶段重新训一套孤立权重。

### 3. GRPO 奖励建模

在 SFT 基线之上，用 GRPO 做结构化抽取优化。任务特定 reward 主要围绕：

- JSON 合法性
- schema 完整性
- total / subtotal 金额命中
- subtotal / total 字段 F1
- menu 数量接近度
- menu 字段 micro-F1
- 空菜单误生成惩罚
- 菜单幻觉惩罚
- placeholder 值惩罚

GRPO 适合这个任务的原因：

- 结构化抽取可以程序化打分，不完全依赖人工偏好。
- 同一个 prompt 下多候选可以组内比较，形成相对优势信号。
- 不需要额外训练 value model，工程上比 PPO 更轻。
- 适合在 SFT 已经具备基本格式能力后继续做字段级修正。

### 4. 评估闭环

评估不只看一个总分，而是拆成结构、金额、菜单三层：

- `json_valid_rate`
- `schema_hit_rate`
- `total_total_price_exact`
- `subtotal_subtotal_price_exact`
- `menu_count_mae`
- `menu_field_micro_f1`
- `end_to_end_exact_match`

同时生成：

- prediction 文本
- detail JSONL
- pretty JSON
- bad case 分析材料

这比“准确率达到 xx%”更容易经得起面试追问。

## 1.4 当前可复现指标

仓库当前最新可直接读取的主线指标：

| 版本 | JSON 合法率 | schema 命中率 | total exact | subtotal exact | menu_count_mae | menu_field_micro_f1 |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-VL stage3 SFT | 93% | 93% | 0% | 34% | 0.71 | 0.445 |
| Qwen3-VL GRPO v1 | 100% | 100% | 0% | 33% | 0.49 | 0.483 |
| Qwen3-VL GRPO v2 | 100% | 100% | 98% | 66% | 0.47 | 0.488 |

关键改进：

- JSON 合法率：93% -> 100%
- schema 命中率：93% -> 100%
- total exact：0% -> 98%
- menu_count_mae：0.71 -> 0.47
- menu_field_micro_f1：0.445 -> 0.488

注意：简历/面试手册中曾出现 `subtotal exact 86%` 口径，但当前本地 `qwen3vl4b_grpo_v2_validation_metrics.json` 显示为 `66%`。更稳的做法是：

- 简历正式投递前，要么改成 66%，要么补齐 86% 的可复现实验记录。
- 面试中如果被追问，建议说：“当前仓库可复现版本是 66%，我之前有一个扩展数据/评估口径下的 86% 结果，但需要按统一脚本补实验记录。”

## 1.5 跑一次的时间与资源口径

当前仓库没有保留完整 `trainer_state.json` 或训练 wall-clock 日志，因此不能严谨给出“完整 SFT + GRPO 总训练耗时”的精确秒数。

已有文档和脚本能支持的口径：

- 云端训练由 `ms-swift` 执行。
- SFT 使用 LoRA，训练精度口径为 `bf16`。
- 推理侧使用 `fp16`。
- 课程式训练不是一次 full train，而是分阶段接力。
- 文档中提到显存约 `12~15GB`，每阶段为“数分钟级”。
- GRPO 使用 `swift rlhf --rlhf_type grpo`，自定义 reward plugin 注入任务目标。

推荐面试口径：

> 我不会把训练耗时编成一个精确数字。当前仓库缺少完整 wall-clock 日志，所以我更愿意说训练是单卡可跑的 LoRA 后训练，显存约 12~15GB，课程式 SFT 每阶段为分钟级；正式复现实验需要补 trainer_state 和完整日志。这个项目里我更关注的是数据清洗、课程划分、reward 设计和评估闭环。

这个回答比硬说“训练只要 xx 分钟”更安全。

## 1.6 相比旧版的优势

| 维度 | 旧版/初始问题 | 当前改进 |
|---|---|---|
| 输出格式 | 大量伪 JSON，解析失败 | JSON 合法率提升到 100% |
| schema | 顶层字段缺失、字段不稳定 | 固定 `menu/subtotal/total` schema，命中率 100% |
| 数据 | 坏图、脏标签、金额格式不统一 | 坏图筛除、金额归一化、课程式样本拆分 |
| 训练 | 单阶段学习复杂结构 | Curriculum SFT 分阶段学习 |
| 对齐 | reward 粗粒度，字段信号弱 | GRPO reward 拆到 JSON、schema、金额、菜单 |
| 评估 | 只看整体结果，不知道错在哪 | detail JSONL + pretty JSON + 字段级指标 |
| 可解释性 | 面试只能说“微调了模型” | 能讲清楚问题、训练路线、reward 和 bad case |

## 1.7 不足与后续改进

当前最该补的不是继续堆新模型，而是统一实验口径：

1. 补一份最新可复现评估记录，统一 `66%` 和 `86%` 的指标分歧。
2. 补完整训练日志，包括 SFT/GRPO 的 wall-clock、显存、batch、epoch。
3. 加外部 baseline，例如 OCR + rule、OCR + LLM、Donut/LayoutLM 类方案的对比。
4. 对剩余 subtotal 错误做 bad case 分类：OCR 误读、行对齐错位、subtotal/total 混淆、稀疏字段漏抽。
5. 如果要上线，需要增加输入图片质量检测、置信度估计和人工复核入口。

---

# 2. Novel-to-Video Agentic 多模态生成系统

## 2.1 业务问题

目标是把小说文本、短句或用户参考图转成短视频片段。一个典型 1 分钟视频需要 8~12 个分镜，每个分镜要生成：

- 画面 prompt
- 角色一致性约束
- 场景/道具/动作
- 分镜图片
- 后续可接 img2video / 视听合成

旧版使用方式很简单：

```powershell
python txt2img.py
```

这种方式适合 demo，但不适合真实小说转视频：

- 只能按固定 prompt 跑，缺少计划能力。
- 长文本没有记忆，角色容易漂移。
- 用户传图无法系统化沉淀成 reference。
- 每个镜头失败后缺少判断与恢复。
- 不知道慢在哪里，也不知道哪一步失败。
- 无法回答“相比 baseline 改了什么”。

## 2.2 当前 Agentic 链路

现在可以称为 **Agentic 多模态生成工作流**。更准确地说，它不是泛化聊天 Agent，而是面向 Novel-to-Video 的任务型工作流 Agent。

核心模块：

| 模块 | 作用 |
|---|---|
| Planner | 短句扩写、小说分镜规划、生成 10-shot / 60s 视频分镜 |
| CharacterMemoryBank | 保存角色静态设定和跨镜头状态 |
| NarrativeRAGIndex | 对小说剧情构建检索索引，按镜头召回上下文 |
| ReferenceAssetBank | 管理用户上传图和已接受镜头图，作为角色/场景参考资产 |
| RetrievalPlanner | 决定当前镜头是否需要检索、检索什么 |
| ShotRouter | 按镜头类型和参考图选择 T2I/I2I、模型和候选数 |
| Executor | 调用 WaveSpeed Nano-banana、Flux/SD、ComfyUI 等模型 |
| Judge | 本地 sanity check + 可选 Gemini VLM Judge |
| RetryPolicy | 根据质量问题 rewrite prompt、扩候选、reroute、fallback |
| ExperimentTracker | 记录 shot_plan、judge_report、retry_policy、accept |

主链路可以概括为：

```text
用户输入小说/短句/参考图
 -> LLM 扩写或分镜规划
 -> 构建角色记忆与 Narrative RAG
 -> 每个 shot 注入 memory + retrieval constraints
 -> ShotRouter 选择模型/模式/候选数
 -> WaveSpeed/ComfyUI 生成候选图
 -> 本地检测或 VLM Judge 打分
 -> RetryPolicy 决定是否重试/改写/reroute
 -> 接受图片并更新 memory/reference bank
 -> 输出 summary、events、runtime_profile
```

## 2.3 相比旧版增加的功能

| 能力 | 旧版 | 当前版本 |
|---|---|---|
| 入口 | `python txt2img.py` 单一路径 | `run_agent_demo.py` / `txt2img.py` 兼容新 Agent demo |
| 输入 | 固定文本 prompt | 小说、短句、用户参考图 |
| 计划 | 人手写或固定脚本 | Gemini planner / deterministic fallback |
| 分镜 | 少量固定 shot | 支持 1 分钟 8~12 shot，当前测试为 10 shot |
| 记忆 | 无系统化角色记忆 | CharacterMemoryBank + prompt suffix |
| RAG | 无 | NarrativeRAGIndex + RetrievalPlanner |
| 参考图 | 临时传入 | ReferenceAssetBank 管理用户图和已接受图 |
| 路由 | 固定模型 | ShotRouter 自动选择 T2I/I2I、模型、候选数 |
| 质检 | 基本无 | 本地 sanity check + 可选 Gemini VLM Judge |
| 失败恢复 | 出错就停或人工改 | RetryPolicy 支持 rewrite/reroute/fallback |
| 观测 | 终端日志为主 | summary.json、events.jsonl、runtime_profile、baseline_comparison |
| 评估 | 很难说比 baseline 强在哪 | 每个 shot 都能列出 memory/RAG/reference/routing 改进 |

## 2.4 实测：短句/小说生成 1 分钟视频分镜图片

由于 WaveSpeed 余额已耗尽，后续不再测试。下面是已经跑过的真实结果。

### 短文本链路

测试目标：

- 短句/短 premise -> 尝试 LLM 扩写 -> 10 个分镜 -> 10 张 Nano-banana 文生图。
- 不测图生图。
- `candidate_cap=1`
- `judge_mode=lightweight`
- `max_retry_rounds=0`

结果：

| 阶段 | 耗时 |
|---|---:|
| LLM 扩写尝试 | 10.114s |
| Gemini 分镜规划尝试 | 1.236s |
| 写入输入文件 | 0.003s |
| RAG/Memory/路由准备 | 0.012s |
| 10 张图生成 + 轻量评估 | 814.754s |
| case_total | 826.278s |
| 终端实测 | 827.871s |

分镜图耗时：

| 指标 | 数值 |
|---|---:|
| shot 数量 | 10 |
| 平均单张 | 81.475s |
| 最快单张 | 38.075s |
| 最慢单张 | 195.226s |

质量检测：

| 指标 | 数值 |
|---|---:|
| 平均轻量分 | 3.535 / 5 |
| hard fail | 0 |
| 黑边 | 0 |
| 分栏/漫画格 | 0 |
| accepted images | 10 / 10 |

解释：

- 真正耗时瓶颈是图片生成，不是 RAG 或 planner。
- RAG/Memory/Router 几乎是毫秒级。
- 单张耗时波动很大，说明后续很适合做有限并发。
- 因为 `max_retry_rounds=0`，低于阈值的镜头没有重试，直接接受；因此这次证明的是链路跑通和基础 sanity，而不是最终美学质量。

### 长文本链路

测试目标：

- 一段小说 -> 10 个分镜 -> Nano-banana 文生图。
- 不测图生图。

结果：

- 跑到第 6 张时 WaveSpeed 返回余额不足。
- 已生成前 5 张。

| shot | 约耗时 |
|---|---:|
| 1 | 50.3s |
| 2 | 96.1s |
| 3 | 42.8s |
| 4 | 101.6s |
| 5 | 177.7s |

前 5 张平均约 `93.7s/张`。按这个速度估算，完整 10 张大概是 `15.6 分钟`，但这只是估算，不是完整实测。

## 2.5 dry-run 时间

dry-run 不调用 WaveSpeed，因此能看出 LLM/RAG/路由本身的时间。

短文本 dry-run：

| 阶段 | 耗时 |
|---|---:|
| short_plot_to_novel_expansion | 9.092s |
| gemini_storyboard_planning | 9.572s |
| memory_and_rag_index_build | 0.015s |
| shot_retrieval_and_routing | 0.002s |
| manual_prepare_total | 0.024s |
| case_total | 18.711s |

长文本 dry-run：

| 阶段 | 耗时 |
|---|---:|
| gemini_storyboard_planning | 3.185s |
| memory_and_rag_index_build | 0.002s |
| shot_retrieval_and_routing | 0.002s |
| manual_prepare_total | 0.012s |
| case_total | 3.203s |

结论：

- 没有图片生成时，RAG/Memory/Router 的成本极低。
- 短文本比长文本多一次扩写，所以 dry-run 更慢。
- 图片生成一旦开启，WaveSpeed T2I 是绝对主耗时。

## 2.6 旧版对比优势

### 工程能力提升

旧版可以说是“多模型 API 调用脚本”，新版更像“生成系统”：

- 旧版：输入 prompt -> 调模型 -> 输出图片/视频。
- 新版：输入故事 -> 规划 -> 检索记忆 -> 路由模型 -> 生成候选 -> 质检 -> 失败恢复 -> 记录指标。

### 质量稳定性提升

新增：

- 角色记忆：固定发型、服装、身份描述。
- 剧情 RAG：每个镜头召回相关剧情，减少道具和事件遗忘。
- 参考图资产库：用户上传图和已生成图可作为后续镜头参考。
- 质量检测：本地检测黑边、分栏、硬失败。
- 可选 VLM：用 Gemini 进一步看图验收。

### 可解释性提升

现在能回答：

- 这个 shot 为什么检索？
- 检索到了哪些剧情？
- 为什么走 T2I 或 I2I？
- 为什么选 Nano-banana？
- 这个候选图哪里不合格？
- 是否触发 retry？
- 整条链路时间花在哪？

这正好对应截图里的自检点：Agent 不是只调用 API，而是有计划、记忆、检索、工具调用、失败恢复和可观测记录。

## 2.7 本轮已落实的工程修复

这轮没有停在“优化设想”，而是把真实运行暴露出的几个问题直接落到了本地代码里。改动集中在 `novei2video/txt2img-comfyui` 和 `novei2video/agent_api`，并用 dry-run 和本地 monkeypatch 做了验证。

### 1. WaveSpeed 候选级并发池

已在 `generate_candidates_for_shot(...)` 中加入候选级线程池，并把默认并发控制为 `max_concurrency=3`。并发只发生在同一个 shot 内：例如一个镜头有 2-3 个候选，就并发提交这些候选，等候选全部回来后再进入 judge 和 accept；不会一上来把 10 个 shot 全片乱序提交。

本轮验证命令使用：

```bash
python run_agent_demo.py --case text --mode dry-run --text-source long --max-shots 10 --candidate-cap 2 --force-text-model Nano-banana --max-concurrency 3 --output-root outputs/codex_verify_force_stats
```

dry-run 不调用 WaveSpeed，但能验证 plan、route、candidate_count 和 artifact 落盘逻辑。验证结果显示 10 个 shot 全部是 `text2img / Nano-banana / candidates=2`，并且保留同一 shot 内候选并发的执行入口。

### 2. VLM Judge 改为按需触发

`judge_candidates_for_shot(...)` 已经改成“本地 lightweight + sanity 先筛，再按需调 VLM”的策略。Hybrid 模式下，VLM 只在这些场景触发：

- 本地分数低或 `retry_needed=true`。
- 本地 sanity 检出 hard fail。
- 关键角色镜头，例如 close-up、dialogue、action、emotional_focus。
- 用户图或 reference image 参与的镜头。
- 多候选场景下，只把本地 top-k 候选交给 Gemini。
- 连续性敏感的角色镜头。

同时在 judge report 里写入 `vlm_decision`，记录 `use_vlm`、`reasons` 和 `top_k`，后面复盘时能直接看出某张图为什么进了 VLM，而不是靠猜。

### 3. WaveSpeed 失败处理已改成显式异常

已新增 `wavespeed_utils.py`，把 WaveSpeed submit、poll、下载统一收口：

- 非 200 创建任务直接抛 `WaveSpeedAPIError`。
- 任务 completed 但 `outputs` 为空时抛 `WaveSpeedEmptyOutputError`。
- 下载前先校验 URL，空 URL 或 `None` 不再进入 `requests.get(None)`。
- 下载失败抛 `WaveSpeedDownloadError`。
- `run_closed_loop_shot(...)` 继续把生成失败写入 `tool_failure` event。

本地 monkeypatch 验证余额不足时返回：

```text
WaveSpeedAPIError(model=Nano-banana, status_code=402, reason=Insufficient credits. Please top up.)
```

这比之前的 `Invalid URL 'None'` 更接近真实故障源，排查时不会被下载层误导。

### 4. retrieval / memory 统计已修正

`ExperimentTracker.log_shot_plan(...)` 现在记录 `retrieval_needed`、`retrieval_used`、`retrieved_chunk_count`、`rag_prompt_suffix_present`、`rag_method`、`has_memory_suffix`。`summarize_events(...)` 会统计 `retrieval_used_shots` 和 `memory_used_shots`，并统计 `tool_failure_types`。

同时新增 `summarize_prompt_plan(...)` 和 `apply_prompt_plan_consistency(...)`：当 events 和 `prompt_plan.json` 的 RAG/Memory 统计不一致时，summary 会写入 `plan_consistency_warnings`，并以 prompt_plan 中的真实增强使用情况为准。

本轮 dry-run 验证生成的 summary 为：

```json
{
  "shots_total": 10,
  "retrieval_planned_shots": 10,
  "retrieval_used_shots": 10,
  "memory_used_shots": 10
}
```

也就是说，现在可以准确说“10/10 shot 使用了 RAG/Memory”，不会再出现 plan 已经注入 RAG、summary 却显示 0 的口径冲突。

### 5. `--force-text-model` artifact 一致性已修正

`prepare_manual_agent_plan(...)` 已新增 `force_text_model` 参数，并在写 `prompt_plan.json` 前完成强制路由。`run_closed_loop_story(...)` 和 `Novel2VideoClosedLoopPipeline.prepare_story(...)` 也补了同样的 force 入口，保证 Gemini planner/full story 路径不会在真实执行和落盘计划之间分裂。

本轮验证的新 `prompt_plan.json` 统计结果：

```json
{
  "total": 10,
  "generators": "Nano-banana",
  "routes": "text2img",
  "rag": 10,
  "memory": 10,
  "candidates": 2
}
```

之前旧文件里保留 Flux/Imagen hint 的问题已经在新生成计划中消失。

### 6. 本轮验证状态

- `python -m py_compile` 已通过核心文件编译检查。
- dry-run 已验证强制模型、候选数、RAG/Memory 统计和 summary 一致性。
- monkeypatch 已验证余额不足会抛 `WaveSpeedAPIError`，不会继续下载 `None`。

仍然没有重新跑 WaveSpeed real-run，因为当前余额不足已经在真实测试中确认过；这轮重点是把失败路径、artifact 和统计口径修实。

## 2.8 面试时推荐讲法

2 分钟版本：

> 这个项目最初只是一个 Novel-to-Video 生成脚本，能把文本 prompt 接到 text2img / img2img / img2video 模型。但真实上线后发现，小说场景会遇到角色漂移、剧情遗忘、用户参考图无法沉淀、模型失败不可恢复、耗时不可解释等问题。所以我把它升级成一个任务型 Agentic workflow：前面有 planner 做短句扩写和 10-shot 分镜，中间用 CharacterMemoryBank 和 NarrativeRAGIndex 给每个镜头补角色和剧情约束，再由 ShotRouter 决定 T2I/I2I、模型和候选数，最后用本地 sanity check 和按需 Gemini VLM Judge 做质检，并通过 RetryPolicy 做 prompt rewrite、reroute 和 fallback。实测 10-shot/60s 文生图链路完整跑完约 826 秒，其中图片生成占 815 秒，RAG/Memory/路由只占毫秒级。基于这个瓶颈定位，我已经补上 WaveSpeed 候选级并发池、按需 VLM、显式 provider 错误、RAG/Memory 统计一致性和 `--force-text-model` artifact 一致性。

---

# 3. 两个项目横向对比

| 维度 | ReceiptVLM | Novel-to-Video |
|---|---|---|
| 任务类型 | 多模态理解/结构化抽取 | 多模态生成/短视频生成 |
| 核心对象 | 收据图片 -> JSON | 小说/短句/参考图 -> 分镜图/视频 |
| 技术主线 | 数据治理 + SFT + GRPO + 评估 | Agent workflow + RAG + Memory + 多模型调度 + Judge |
| 主要难点 | JSON 稳定性、金额准确、菜单抽取 | 长叙事一致性、角色漂移、生成失败、耗时 |
| 旧版痛点 | 不合法 JSON、schema 不稳 | 固定 prompt、无记忆、无质检、无恢复 |
| 关键改进 | Curriculum SFT、任务 reward、detail eval | Planner/Router/Executor/Judge/Retry、RAG、ReferenceBank |
| 指标 | JSON/schema 100%，total exact 98%，menu_mae 0.47 | 10-shot 实测 826s，RAG/Memory 覆盖 10/10，无黑边/分栏硬失败 |
| 风险点 | 66%/86% 指标口径需统一 | 质量 A/B 仍需人工补评；并发、失败处理和统计口径已落地 |

---

# 4. 简历/面试可直接提炼的 bullet

## ReceiptVLM

- 面向报销录入/财务归档场景，将收据理解定义为固定 `menu / subtotal / total` schema 的多模态 JSON 抽取任务，完成坏图筛除、标签清洗、金额归一化与课程式样本拆分。
- 基于 Qwen3-VL-4B-Instruct + LoRA 实现三阶段 Curriculum SFT，按 `stage1_core -> stage2_short_menu -> stage3_full_clean` 逐步学习合法 JSON、核心金额字段和复杂菜单结构。
- 在 SFT 基线之上引入 GRPO，围绕 JSON 合法性、schema 完整性、金额 exact match、菜单数量与字段 F1 设计程序化 reward，缓解伪 JSON、长菜单截断和空菜单幻觉。
- 重构离线评估链路，输出 metrics、detail JSONL 和 pretty JSON；当前可复现版本在 100 条验证样本上实现 100% JSON 合法、100% schema 命中、total exact 98%、menu_count_mae 0.47。

## Novel-to-Video

- 将旧版固定 Prompt + 单次模型调用的小说生成脚本升级为 Planner-Router-Executor-Judge 的 Agentic 多模态生成工作流，支持短句扩写、10-shot 分镜规划和多模型统一调用。
- 实现 CharacterMemoryBank、ReferenceAssetBank、NarrativeRAGIndex 和 RetrievalPlanner，按镜头动态注入角色记忆、剧情检索上下文和用户参考图约束，缓解长叙事角色漂移与道具遗忘。
- 实现 ShotRouter、RetryPolicy 和 ExperimentTracker，按镜头风险选择 T2I/I2I、模型与候选数，结合本地 sanity check 和可选 Gemini VLM Judge 检测黑边、分栏、主体缺失与 prompt mismatch。
- 建立 dry-run/real-run、baseline_comparison、runtime_profile 和 events.jsonl 追踪；10-shot/60s 文生图实测总耗时 826s，其中图片生成占 815s，并已补上 `max_concurrency=3` 的同 shot 候选级并发、按需 VLM、WaveSpeed 显式失败处理和 RAG/Memory summary 一致性校验。

---

# 5. 已落实与仍需补充

## ReceiptVLM

1. 统一 `66%` 和 `86%` 的指标口径。
2. 补完整训练日志：耗时、显存、epoch、batch、checkpoint。
3. 加外部 baseline：OCR + rule、OCR + LLM、Donut/LayoutLM。
4. 补 bad case 分类和代表样例图。
5. 把 README 从旧 Qwen2.5 口径更新到当前 Qwen3-VL 主线。

## Novel-to-Video

1. 已落地 WaveSpeed 候选级并发池，默认 `max_concurrency=3`，并发范围限定在同一 shot 的候选内。
2. 已落地按需 VLM：低分、关键角色、用户图、最终 top-k、本地 sanity 可疑项才触发，并在 `vlm_decision` 中记录原因。
3. 已落地 WaveSpeed 失败处理：余额不足、非 200、outputs 为空和下载失败都会保留 provider 错误，不再继续 `requests.get(None)`。
4. 已落地 tracker 统计修复：summary 按 `rag_context.prompt_suffix`、chunks 和 memory suffix 统计 RAG/Memory 覆盖，并输出 prompt_plan consistency warning。
5. 已落地 `--force-text-model Nano-banana` artifact 一致性：强制路由发生在 `prompt_plan.json` 落盘之前，dry-run 验证 10/10 都是 Nano-banana。
6. 仍需补人工 A/B：旧版 vs Agent+RAG，评估角色一致性、剧情对齐、美学质量、重试收益和并发前后质量回归。

---

# 6. 最安全的整体项目回答

> 我现在主要有两个项目，一个偏多模态理解后训练，一个偏多模态生成工作流。ReceiptVLM 里我做的是收据图片到结构化 JSON 的任务，通过数据清洗、课程式 LoRA SFT、GRPO reward 和字段级评估，把模型从输出不稳定推进到结构稳定、金额字段可靠。Novel-to-Video 里我做的是小说转视频的 Agentic workflow，把旧版单次 prompt 调模型升级成 Planner、RAG Memory、Router、Executor、Judge、Retry 的闭环系统。前者证明我能做模型后训练和评测，后者证明我能把多模型能力落到真实生成链路里，并且能追踪耗时、失败和改进点。
