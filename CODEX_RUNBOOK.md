# Codex 运行手册（给你自己用）

这份文档不是给模型看的，而是给你在终端里启动 Codex 时用的。

## 先纠正一个关键点
**要精准复用 DeepReport 的骨架，必须先把 GitHub 代码拉到本地再审计。**

如果没有 `git clone` 这一步，最多只能叫“参考 README 做近似设计”，不能叫“精准复用骨架”。

因此，新的推荐顺序是：
1. 先 clone DeepReport 参考仓库
2. 让 Codex 审计参考仓库并生成映射文档
3. 再开始 Open DeepReport++ 的正式开发

---

## 方式 A：你先手动 clone，再让 Codex 读取 AGENTS.md（最稳）
在你的项目根目录执行：

```bash
mkdir -p references
git clone https://github.com/wisdom-pan/DeepReport.git references/DeepReport_ref
```

然后启动：

```bash
codex
```

进入后输入：

```text
请先读取仓库根目录的 AGENTS.md，检查 Stage -1 是否已经完成。如果参考仓库已存在，则直接执行 Stage -1 审计；完成后停止。
```

---

## 方式 B：让 Codex 自己 clone（依赖当前环境可联网且有 git）

```bash
codex "请读取 AGENTS.md，从 Stage -1 开始执行：如果 references/DeepReport_ref 不存在，就先 clone 参考仓库并完成审计；完成后停止。"
```

如果失败，通常是：
- 当前环境不能联网
- 当前环境没有 git
- GitHub 访问失败

这时不要让它继续开发，先手动 clone。

---

## 为什么必须先 clone
你后面要“精准复用”的东西，至少包括：
- 真实目录结构
- 主入口组织方式
- 配置文件入口
- `src/` 子模块边界
- Docker / 部署组织
- agent 与搜索模块如何切分
- 报告导出相关模块位置

这些东西**只有看真实仓库才能确定**，只看 README 不够精确。

---

## 推荐操作顺序

### Step 1：先做 Stage -1

```bash
codex "请严格按 AGENTS.md 执行 Stage -1。不要进入 Stage 0。完成后输出：1. 审计到的真实目录树 2. 可复用骨架 3. 需要重写的部分 4. 下一步建议。"
```

### Step 2：再做 Stage 0

```bash
codex "请严格按 AGENTS.md 执行 Stage 0。骨架必须参考 docs/deepreport_skeleton_mapping.md。完成后停止。"
```

### Step 3：后续分阶段推进

```bash
codex "请严格按 AGENTS.md 执行 Stage 1。不要进入 Stage 2。"
codex "请严格按 AGENTS.md 执行 Stage 2，只做 mock/local_file 数据层，不要联网。"
codex "请严格按 AGENTS.md 执行 Stage 3，完成程序化财务特征层。"
codex "请严格按 AGENTS.md 执行 Stage 4，完成 claim-first 最小报告流水线。"
codex "请严格按 AGENTS.md 执行 Stage 5，接入图表层。"
codex "请严格按 AGENTS.md 执行 Stage 6，完成 generation backend 抽象与 writer fallback。"
codex "请严格按 AGENTS.md 执行 Stage 7，只做 BM25 检索层，不要做真实 FAISS 实现。"
```

### 云端阶段
只有在本地 smoke test 稳定后，再做：

```bash
codex "请严格按 AGENTS.md 执行 Stage 8，导出 reranker/rewriter/verifier 训练数据。"
codex "请严格按 AGENTS.md 执行 Stage 9，生成云端训练脚本和本地 fallback 推理。"
codex "请严格按 AGENTS.md 执行 Stage 10，完成 markdown/html 报告导出与回归测试。"
```

---

## 每个阶段结束后建议输入的检查指令

```text
请不要继续下一阶段。先总结：
1. 当前完成了哪些文件
2. 如何运行
3. 还缺什么
4. 哪些地方仍然是 mock
5. 下一阶段最小任务是什么
```

---

## 如果 Codex 想一次做太多
直接输入：

```text
停止扩展。请回到 AGENTS.md，只允许执行当前阶段，不要跨阶段实现后续模块。
```

---

## 如果你要它先做“骨架映射报告”而不是立刻写代码
输入：

```text
先不要开发。请只完成 Stage -1，输出 deepreport_repo_audit.md 和 deepreport_skeleton_mapping.md，并说明哪些地方值得保留、哪些地方需要重写。
```

---

## 本地 3060 Ti 的定位
本地只做：
- Stage -1 到 Stage 7
- mock / template / BM25 / 小样本 smoke
- 不训练

不要在本地追求：
- 大模型训练
- 重型多模态推理
- 大规模 embedding 预计算

---

## 云端 48GB 的定位
云端只做：
- Stage 8 到 Stage 10
- 离线训练
- 大规模离线推理
- checkpoint 导出再回本地接入

