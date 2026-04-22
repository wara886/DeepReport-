# Open DeepReport++ 阶段总结与本地任务拆解（供 Codex 执行）

## 0. 当前项目一句话定位
本项目不是原样复现 AFAC2025 二等奖方案，而是基于 DeepReport 的工程骨架，重构为一个 **证据驱动（evidence-driven）的金融研报生成系统**。系统核心目标不是“生成像样的长文”，而是：

1. 先检索并排序可用证据；
2. 再判断 claim 是否被证据支撑；
3. 最后在可追溯证据约束下生成报告；
4. 对关键数字与 fallback 链路做可回归的质量监控。

---

## 1. 当前项目推进到哪一步了

### 1.1 已完成的大阶段
当前已完成：

- **Stage 2–10**：工程主链路基本跑通，形成从 retrieval / rerank / writer 到 report 输出的系统闭环；
- **Stage 11A**：接入真实数据，不再只依赖 mock 示例；
- **Stage 11B**：接入真实 writer backend 路径，不再停留在伪生成或假接口；
- **Stage 11C**：reranker 云端训练链路打通，具备后续离线训练与替换能力。

### 1.2 当前阶段的准确判断
当前项目状态不是“demo 搭起来了”，而是：

> **已经从 mock/demo 阶段，进入 Stage 12 的质量验证阶段。**

这意味着系统现在最重要的问题已经不再是“能不能跑”，而是：

- 输出结论是否真的有证据支撑；
- 财务数字是否可靠；
- fallback 是否在悄悄吞掉质量；
- 训练集 / 评测集 / 规则 / 指标 是否已经固定并可回归。

---

## 2. Stage 12A 到底在验证什么

### 2.1 不是验证“功能可用”
Stage 12A 不是做一次普通 smoke test，也不是再次证明系统能成功产出一篇报告。

### 2.2 它真正验证的是三个项目目标
Stage 12A 的核心是验证以下三件事：

1. **证据覆盖是否足够**：报告中的关键 claim 是否能追溯到 evidence_ids；
2. **关键数字是否准确**：尤其是营收、净利润、同比、毛利率等关键财务指标；
3. **writer 行为是否稳定**：是否频繁 fallback，fallback 是合理保守还是错误退化。

### 2.3 当前已知现状
前面已经补齐了一些硬门槛：

- 样本数提高了；
- evidence_ids 覆盖有所补足；
- 整体链路从 mock 走向真实路径；

但当前最主要短板仍然是：

- **关键财务指标抽检不足**；
- **writer fallback 缺少清晰诊断与日志归因**。

---

## 3. 当前阶段最核心的判断

### 3.1 本地不该继续堆功能
当前阶段本地重点 **不是**：

- 再加新的 agent 能力；
- 继续扩功能模块；
- 先上 rewriter；
- 为了“更像报告”先调文风。

### 3.2 本地应该做的事情
本地当前应该聚焦四类工作：

1. **补数字抽检**；
2. **查 writer fallback**；
3. **固化评测集与训练集**；
4. **做回归与消融**。

### 3.3 云端应该做的事情
云端当前应该只做低频、重计算、离线训练类工作：

1. **第一优先级：verifier**；
2. **第二优先级：reranker 强化**；
3. **最后才考虑：rewriter**。

原因：当前主要瓶颈是可信性与 claim-evidence 对齐，而不是文风。

---

## 4. 当前项目的主要难点与优势

### 4.1 难点
本项目真正难的不是“把报告写长”，而是以下问题：

- **可信性（trustworthiness）**：生成结论必须可追溯；
- **异构数据清洗**：网页、表格、段落、财报字段口径不统一；
- **claim-evidence 对齐**：句子写出来了，但未必真有证据支撑；
- **评测困难**：普通生成指标很难真实反映报告质量；
- **fallback 隐性退化**：系统看似成功输出，但实际走了降级路径。

### 4.2 优势
这个项目对简历和面试有辨识度，原因在于它不是单一模型微调，而是一个完整系统：

- Agent orchestration
- Retrieval / Reranking
- Verification
- Evidence-grounded report generation
- Quality evaluation / regression / ablation

相比普通“RAG 聊天机器人”或者“简单报告生成器”，它更接近真实工业研究系统。

---

## 5. 下一步总策略（必须先执行的路线）

### 5.1 总体路线
下一步必须遵循：

> **先在本地建立质量评测闭环，再把 verifier 数据准备好，最后再上云做 verifier 训练。**

### 5.2 不建议的路线
当前不建议：

- 先调 rewriter；
- 继续扩 agent 功能；
- 大规模重构 retrieval；
- 未冻结评测集就直接大规模云训。

原因：没有固定评测闭环，后面的优化都不可比较。

---

# 6. 本地下一步任务拆解（这是 Codex 需要落实的重点）

以下任务按优先级排序，并按“先建设基础设施，再跑回归，再给云端喂数据”的逻辑拆解。

---

## Task A：建立固定评测集 `eval_v1`

### 目标
建立一版 **可复用、可回归、可比较** 的 Stage 12 固定评测集，用于后续所有本地回归与云端训练前验证。

### 任务要求
创建或整理一个评测集目录，例如：

```text
project_root/
  data/
    eval_v1/
      cases.jsonl
      README.md
      schema.json
```

### 每个 case 至少包含字段

```json
{
  "case_id": "...",
  "query": "...",
  "task_type": "fundamental|financial|event",
  "source_scope": ["filing", "news", "company_page"],
  "gold_claims": ["..."],
  "gold_evidence_ids": ["..."],
  "gold_numeric_facts": [
    {
      "metric": "revenue",
      "value": "...",
      "unit": "...",
      "period": "..."
    }
  ],
  "allow_fallback": false
}
```

### 规模建议
先做 **30–50 个 case**，不求多，但必须高质量。

### 覆盖建议
至少覆盖 3 类任务：

1. 公司基本面总结；
2. 财务指标解读；
3. 事件驱动分析 / 风险提示。

### 验收标准
- 可以被主评测脚本稳定加载；
- case schema 固定；
- 训练 / 评测边界明确；
- 后续新模型或新规则都能直接复用。

### 为什么优先做
没有固定 eval set，所有优化都无法判断是否真的有效。

---

## Task B：实现关键财务数字抽检 `numeric_audit_v1`

### 目标
建立一个**专门检查财务数字可信性**的评测模块，而不是只看文本好不好看。

### 第一版只检查这 4 类核心字段

1. revenue / 营收
2. net_income / 净利润
3. yoy / 同比
4. gross_margin / 毛利率

### 推荐目录

```text
project_root/
  evaluation/
    numeric_audit.py
    numeric_extract.py
    numeric_matchers.py
    tests/
      test_numeric_audit.py
```

### 第一版要实现的能力
1. 从 report 中抽取数字 claim；
2. 尝试把数字 claim 对齐到对应 evidence / table cell；
3. 判断是否存在以下错误：
   - value mismatch
   - unit mismatch
   - period mismatch
   - unsupported number
   - hallucinated number
4. 输出结构化审计结果。

### 推荐输出格式

```json
{
  "case_id": "...",
  "numeric_claims": 6,
  "supported_numeric_claims": 4,
  "unsupported_numeric_claims": 2,
  "error_breakdown": {
    "value_mismatch": 1,
    "unit_mismatch": 0,
    "period_mismatch": 1,
    "hallucinated_number": 0
  }
}
```

### 这一步的关键点
不要一开始追求全量财务字段；先把最关键、最容易出错、最能说明问题的数字打通。

### 验收标准
- 能对固定评测集批量跑；
- 能输出每个 case 的数字错误类型；
- 能统计总体 numeric accuracy / grounded rate。

---

## Task C：补全 writer fallback trace

### 目标
把 writer fallback 从“看起来偶尔发生”变成“可统计、可定位、可归因”。

### 推荐目录

```text
project_root/
  logs/
  tracing/
    writer_trace.py
```

### 需要新增或固化的日志字段
每次 report 生成至少记录：

```json
{
  "case_id": "...",
  "query": "...",
  "retrieved_doc_count": 0,
  "reranked_topk_ids": ["..."],
  "evidence_coverage": 0.0,
  "verifier_accept_rate": 0.0,
  "writer_mode": "normal|fallback",
  "fallback_reason": "...",
  "final_report_path": "..."
}
```

### 需要重点回答的问题
1. fallback 发生率是多少；
2. 哪些 task_type 最容易 fallback；
3. fallback 前一跳失败在哪；
4. fallback 后的数字准确率是否显著下降。

### 验收标准
- 可以按 case 聚合；
- 可以按 task_type 聚合；
- 可以导出 CSV / JSON 供后续分析。

---

## Task D：跑一轮固定回归 `regression_v1`

### 目标
在 `eval_v1` 上对当前系统跑一轮完整回归，建立第一份真正有参考价值的 baseline 报告。

### 推荐目录

```text
project_root/
  evaluation/
    run_eval_v1.py
    summarize_eval_v1.py
  reports/
    eval_v1/
      summary.json
      summary.md
      per_case.csv
```

### 回归至少输出这些指标
1. evidence coverage
2. claim grounded rate
3. numeric accuracy
4. fallback rate
5. fallback 后 numeric accuracy
6. top-1 / top-3 evidence hit rate
7. per-case error taxonomy

### 验收标准
- 每次修改 retrieval/rerank/writer/verifier 前后都能复跑；
- 能清楚看出“变好还是变差”；
- summary.md 可直接用于人工阅读与汇报。

---

## Task E：做最小可用消融 `ablation_v1`

### 目标
不是做论文级大消融，而是最小代价搞清楚：当前主要问题到底出在哪一段。

### 第一轮建议只做 4 个开关
1. 是否启用 reranker
2. 是否启用 verifier 过滤（如果已有弱版）
3. 是否允许 writer fallback
4. 是否启用 numeric post-check / repair

### 推荐输出
产出一个 `ablation_v1.md`，至少包含：

- 配置差异；
- 样本数；
- evidence coverage 对比；
- numeric accuracy 对比；
- fallback rate 对比；
- 结论：当前最值得优先优化哪一段。

### 验收标准
不是表格越多越好，而是能回答一句话：

> 当前系统的主要误差来自 retrieval、verification 还是 writer。

---

## Task F：冻结训练 / 评测 schema 与 split

### 目标
在云训 verifier 之前，冻结本地的数据定义，避免边训边改口径。

### 要冻结的内容
1. 数据 schema v1
2. 清洗规则 v1
3. train/val/test split v1
4. eval_v1 case 集合
5. 指标定义 v1

### 推荐目录

```text
project_root/
  data_contracts/
    schema_v1.json
    cleaning_rules_v1.md
    split_v1.md
```

### 验收标准
- 团队或 Codex 后续迭代不再随意改字段；
- 云端训练数据和本地评测口径一致；
- 后续结果具备可比性。

---

## Task G：准备 verifier 云训数据 `verifier_dataset_v1`

### 目标
在本地整理出可直接上传云端训练的 verifier 数据。

### 推荐字段

```json
{
  "query": "...",
  "claim": "...",
  "candidate_evidence": "...",
  "evidence_id": "...",
  "source_doc_id": "...",
  "label": "supported|unsupported",
  "numeric_flag": true,
  "task_type": "financial"
}
```

### 第一版标签建议
先做二分类：

- supported
- unsupported

不要一开始就扩成太复杂的标签体系。

### 验收标准
- 支持离线训练 verifier baseline；
- 与本地 eval_v1 口径一致；
- 可以单独抽取 numeric claim 子集。

---

# 7. 本地任务的实际执行顺序（必须按这个顺序推进）

## 第一优先级（立刻做）
1. Task A：`eval_v1`
2. Task B：`numeric_audit_v1`
3. Task C：`writer_fallback_trace`

## 第二优先级（基础设施完成后）
4. Task D：`regression_v1`
5. Task E：`ablation_v1`

## 第三优先级（准备上云）
6. Task F：冻结 schema / split
7. Task G：导出 `verifier_dataset_v1`

---

# 8. Codex 执行原则

## 8.1 这阶段不要乱扩功能
当前阶段禁止把主要精力放在：

- 新 agent 能力扩展；
- rewriter 美化；
- 大规模 UI 重构；
- 与质量验证无关的花哨功能。

## 8.2 任何代码改动都必须服务于一个明确问题
每次改动前必须先写清楚：

- 该改动是为了解决什么具体问题；
- 会影响哪个指标；
- 如何在 `eval_v1` 上验证有效性。

## 8.3 所有输出都要可追溯
后续新增脚本与日志必须尽量结构化，避免“看日志靠猜”。

---

# 9. 最终一句话结论

当前 Open DeepReport++ **已经完成 Stage 11ABC，进入 Stage 12 质量验证阶段**。  
下一步本地最重要的不是继续堆功能，而是尽快建立：

- 固定评测集 `eval_v1`
- 关键财务数字抽检 `numeric_audit_v1`
- writer fallback trace
- 回归与最小消融
- verifier 训练数据整理

只有这套本地质量闭环稳定后，云端 verifier 训练才真正有意义。
