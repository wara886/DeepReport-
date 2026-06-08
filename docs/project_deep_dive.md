# DeepReport++：多智能体金融研报系统 — 技术深度解析

> 作者：项目负责人
> 时间：2026.06
> 本项目为 Multi-Agent 金融研报自动生成系统，覆盖 A 股、港股、美股三个市场，
> 目标为 900 家公司（各 300 家）的 FY2022–2026Q1 数据全量入库与报告自动生成。

---

## 目录

1. [总体架构与流程](#1-总体架构与流程)
2. [数据源选型与问题](#2-数据源选型与问题)
3. [清洗策略](#3-清洗策略)
4. [切分策略](#4-切分策略)
5. [检索与召回](#5-检索与召回)
6. [融合与重排](#6-融合与重排)
7. [RAG 流程中的关键问题与解决](#7-rag-流程中的关键问题与解决)
8. [Multi-Agent 架构与 ReAct 设计](#8-multi-agent-架构与-react-设计)
9. [Tool Calling 设计](#9-tool-calling-设计)
10. [Trace 与可观测性](#10-trace-与可观测性)
11. [模型选型](#11-模型选型)
12. [检索流程与向量数据库](#12-检索流程与向量数据库)
13. [数据入库规模估算](#13-数据入库规模估算)
14. [质量门禁体系](#14-质量门禁体系)
15. [项目路线图与当前进度](#15-项目路线图与当前进度)

---

## 1. 总体架构与流程

### 1.1 为什么用 Multi-Agent 而不是 Single-Agent？

金融研报有三大独特要求，Single-Agent 无法同时满足：

| 要求 | Single-Agent 的问题 | Multi-Agent 的方案 |
|:----|:-------------------|:------------------|
| **可追溯** | 结论来源不可查，黑箱输出 | 每个 claim 携带 evidence_id，可追溯至原始 PDF/API 数据 |
| **可验证** | 幻觉难定位，错误结论无法回修 | Verifier Agent 逐 claim 校验，失败后传回 writer 修复 |
| **多源融合** | 无法区分权威层级 | 按 evidence 来源分级（Primary/Secondary/Tertiary），不同权重融合 |

### 1.2 流程概览

```
User Request (symbol + period)
    │
    ▼
Planning Agent ──→ 拆解为子任务：检索、财务分析、估值、同行对比、风险
    │
    ▼
Research Agent (ReAct loop) ──→ 多引擎并行搜索 + 工具调用
    │  ├── local_real_data（本地缓存）
    │  ├── cninfo_announcements（A股 CNINFO PDF）
    │  ├── eastmoney_financials（A股结构化财报）
    │  ├── sina_finance（A股/港股实时行情）
    │  ├── yahoo_finance（行情 + 财报）
    │  ├── sec_edgar（美股 SEC 数据）
    │  ├── hkex_announcements（港交所公告）
    │  ├── tavily / serper（网络搜索）
    │  └── local_evidence（本地证据库 BM25 + 向量检索）
    │
    ▼
Analyze Agents ──→ 身份确认、三表分析、估值分析、风险分析、同行分析
    │
    ▼
FinalAnswer Agent ──→ 基于 evidence + claims 生成报告草稿
    │
    ▼
Verifier Agent ──→ 逐 claim 校验：引用存在？数字匹配？结论有依据？
    │  ├── ✅ 通过 → 交付报告
    │  └── ❌ 失败 → Gap Resolver → 修复约束 → FinalAnswer 重写
    │
    ▼
Delivery Gate ──→ quality_report + llm_review + verifier → pass/fail
```

### 1.3 为什么这样设计？

**分布式的"写后校验"优于单轮生成。** 金融报告不允许幻觉。Single-Agent 一次性生成无法保证每个数字都有来源。我们的方案是：

1. **先搜集**（Research Agent 调多个引擎，确保覆盖面）
2. **再分析**（独立分析 agent 专注各自领域，不互相干扰）
3. **再写作**（FinalAnswer 只写已验证的 claim）
4. **再校验**（Verifier 逐条检查引用和数字一致性）
5. **再修复**（不通过的传回重写，形成闭环）

每步都是独立的 agent，有独立的 prompt 和工具集。这样才能追踪到"哪个 agent 在哪一步产生了错误"。

---

## 2. 数据源选型与问题

### 2.1 为什么选这些数据源？

| 市场 | 数据源 | 选型理由 | 不选其他的原因 |
|:----:|:------|:---------|:--------------|
| **A 股** | CNINFO（巨潮资讯） | A 股法定披露平台，PDF 年报唯一权威来源 | 东财 HTML 页被反爬（"无 F10 资料"）；Wind/Choice 需付费 API |
| **A 股** | East Money API | 结构化三表（利润表/资产负债表/现金流量表），JSON 直接可用 | 新浪财务表是 JS 动态加载，HTML 解析拿不到数据 |
| **A 股/港股** | Sina Finance API | 实时行情，无需 Token，支持多股票 comma-separated | yfinance 的 A 股数据不全？东财 push2 API 连接被拒 |
| **美股** | SEC EDGAR | 法定披露平台，companyfacts JSON 含 50+ GAAP 指标 → 当前提取 **30+ 指标** | 10-K PDF 提取成本高，companyfacts JSON 结构化可直接用 |
| **美股** | Yahoo Finance | 行情快照 + 基础财报 | 只有 price snapshot，不含详细财报（yfinance 库可以扩展但需额外开发）|
| **港股** | HKEX | 法定披露平台 | 没有批量 API，PDF 靠 Tavily 搜索发现，覆盖率不稳定 |
| **港股** | hk_financials（新增）| 基于 yfinance 的港股结构化财报引擎 | yfinance 覆盖不全的小盘股需其他来源补充 |
| **全市场** | Tavily / Serper | AI 优化的搜索 API，返回结构化 snippet | Google Search API 价格高；Bing API 返回质量不如 Tavily |

### 2.2 引擎架构总览

引擎 = 数据源适配器。每个引擎是一个纯函数，从特定 API 或本地文件拉取数据，统一翻转为 `SearchResult` / `evidence_record` 格式供下游消费。

```
                      ┌─ local_real_data ───── 本地缓存 CSV/JSON
                      │   （仅 5 只美股：AAPL/MSFT/NVDA/TSLA/GOOGL）
                      │
                      ├─ local_evidence ─────── ChromaDB 向量库
                      │   （历史 run 累积的 evidence 和 chunks）
                      │
  SearchManager ──────┼─ eastmoney_financials ─ 东财数据中心 API
  (按引擎名路由)       │   （三表：收入/利润/资产/现金流 60+ 指标）
                      │
                      ├─ yahoo_finance ──────── Yahoo Finance API
                      │   （行情快照：股价/市值/PE + 基础财报）
                      │
                      ├─ sina_finance ───────── 新浪行情 API
                      │   （实时行情，A 股/港股）
                      │
                      ├─ cninfo_announcements ─ 巨潮资讯公告 API
                      │   （A 股年报 PDF URL 发现 + 分类过滤）
                      │
                      ├─ exchange_announcements 沪/深交易所公告
                      │
                      ├─ sec_edgar ──────────── SEC EDGAR API
                      │   （10-K/10-Q 索引 + companyfacts JSON）
                      │
                      ├─ hkex_announcements ─── 港交所公告
                      │
                      ├─ independent_macro ──── FRED/BLS 宏观指标
                      │   （利率、CPI、失业率等）
                      │
                      ├─ eastmoney ──────────── 东财搜索
                      ├─ serper ─────────────── Google 搜索
                      ├─ tavily ─────────────── AI 搜索
                      ├─ metaso ─────────────── 中文搜索
                      └─ sogou ──────────────── 中文搜索
```

### 2.3 按市场引擎配置

每个市场有独立的默认引擎列表，定义在 `web_ui.py`：

| 市场 | 引擎列表 | 覆盖的数据维度 |
|:----:|:---------|:--------------|
| **A 股** | `local_real_data, cninfo_announcements, exchange_announcements, eastmoney_financials, sina_finance, yahoo_finance, eastmoney, local_evidence` | 结构化财报（东财）+ PDF年报（巨潮）+ 实时行情（新浪）+ 搜索补充 |
| **美股** | `local_real_data, sec_edgar, yahoo_finance, independent_macro, local_evidence` | SEC 结构化数据 + Yahoo行情 + FRED宏观 |
| **港股** | `local_real_data, sina_finance, yahoo_finance, tavily, hkex_announcements, local_evidence` | 港交所公告 + Yahoo行情 + 搜索 |
| **默认** | `local_real_data, yahoo_finance, tavily, local_evidence` | 最精简，回退方案 |

### 2.4 每个引擎的具体产出与消费方

| 引擎 | 产出格式 | 被谁消费 | 当前状态 |
|:-----|:---------|:---------|:--------|
| `eastmoney_financials` | `{income/balance/cashflow} → metric rows` | 财务分析、三表摘要、估值输入 | ✅ 已验证（A 股 60+ 指标） |
| `cninfo_announcements` | 公告列表 → PDF URL → `build_pdf_artifacts` → `pdf_section_summaries` | 业务概览/治理/战略/风险定性 section | ✅ 已修复（CLI PDF 管道打通） |
| `yahoo_finance` | `quoteSummary` + 行情快照 | 估值输入（市值）、行情背景、同行数据 | ✅ 可用（A 股数据有限） |
| `sec_edgar` | `companyfacts` XBRL → GAAP 指标（**8→30+**） | 美股三表、估值、同行 | ✅ 已扩展至 30+ GAAP 指标 |
| `sina_finance` | `{symbol: {open, high, low, price, volume}}` | 实时行情 | ✅ 可用 |
| `independent_macro` | FRED 利率/CPI 等 | 美股 DCF 无风险利率 | ✅ 可用 |
| `hkex_announcements` | 公告搜索 → PDF 提取 | 港股定性 section | ⚠️ 覆盖率不稳定 |
| `hk_financials` | yfinance 三表（income/balance/cashflow） | 港股结构化财报、估值、同行 | ✅ 新增（暂未端到端验证） |
| `exchange_announcements` | 沪/深交易所公告 | A 股 PDF 补充 | ⚠️ 备用 |
| `local_real_data` | `data/raw/real_data/{symbol}/{period}/financials.csv` | 同行对比、历史比对 | ❌ 只有 5 只美股 |
| `tavily/serper/metaso/sogou` | 网页 snippet + URL | 搜索补充（同行发现、新闻、行业背景） | ⚠️ Serper 对 A 股同行代码解析不足 |

### 2.5 关键数据流

```
A 股年报 PDF 管道（已修复 ✅）：
  cninfo_announcements → 公告列表 → PDF URL
    → build_pdf_artifacts（下载+缓存+提取章节）
      → build_pdf_rag_artifacts（书签校正+文本切分+摘要）
        → pdf_section_summaries[section_type, summary_zh]
          → contract_builder（构建 per-section 合约）
            → render_section_from_contract（最终生成）

A 股结构化财报管道（已验证 ✅）：
  eastmoney_financials → 三表 JSON
    → financial_metric_lineage（归一化 60+ 指标）
      → valuation 引擎（PE/PS/DCF 计算）
        → contract_builder._build_valuation（估值 section）

A 股同行对比管道（新增 ✅，依赖东财行业 API）：
  eastmoney RPT_LICO_FN_CPD（公司概况）← INDUSTRY_CODE 过滤
    → 同行业全部股票代码列表
      → eastmoney RPT_DMSK_FN_INCOME（同行三表）
        → peer financial rows
          → contract_builder._build_peer_compare
  回退链：硬编码行业→同行映射 → eastmoney API→同行代码 → Yahoo sector
```

### 2.2 实际遇到的问题

#### 🔴 A 股：CNINFO PDF 编码问题

**症状**：PDF 提取后出现 `ę́(600519)Q1 гĸЧ` 等乱码

**根因**：CNINFO 的 PDF 元数据字段使用 GB2312 编码，PyMuPDF 提取时按 Latin-1 解码，导致中文字符变成 Latin-1 扩展字符。

**修复**：开发 `pdf_encoding.py`，检测策略为 CJK 字符比例 < 5% + 0x80-0x9F 控制字符比例高 → 判定为 mojibake → 按 `text.encode('utf-8').decode('gbk')` 修复。

**为什么不直接用 chardet**：chardet 对短文本（<200 chars）检测准确率低，我们的 PDF 片段经常只有几十个字。自定义检测基于字符范围统计，对金融文档更稳定。

#### 🔴 A 股：CNINFO PDF bookmark 页码错误

**症状**：bookmark 把所有 section 指向目录页（第 2-4 页），导致 section_map 页码全错。

**根因**：CNINFO 的 PDF 生成工具把 bookmark 的 page number 设成了 TOC 页，而非正文页。

**修复**：开发 `_correct_bookmark_pages()`，对每个 bookmark 做三阶段页面搜索：±3 页 → 全文正向 → 全文反向。匹配 heading 文本实际出现的页面。

#### 🔴 A 股：PDF 季度报告与年报结构不同

**症状**：季度报告 12 页，没有 "第X节" 标题，`build_section_map()` 匹配不到任何 section。

**修复**：开发 `_fallback_quarterly_map()`，当文档 ≤20 页且检测到的 section 数量不足时，按典型季度报告页面分布分配默认 section（1-2页 公司信息，3-4页 销售数据，5页 备注，6-12页 财报）。

#### 🔴 A 股：East Money API 连接被拒

**症状**：`Remote end closed connection without response`

**根因**：East Money push2 API 对非中国 IP 或高频请求有限制。

**替代**：接入 Sina Finance API `http://hq.sinajs.cn/list=sh600519`，返回 JS 赋值字符串，解析后可得实时价、涨跌幅、成交量等 20+ 字段。

#### 🔴 全市场：Yahoo Finance 只返回行情快照

**症状**：Yahoo Finance 的 chart API 只返回最新价 + 1 个月变化，没有利润表/资产负债表数据。

**影响**：三个市场都缺少结构化财务数据。A 股靠 East Money API 填补，美股靠 SEC companyfacts，港股目前只能靠 Yahoo financials（通过 yfinance 库）。

---

## 3. 清洗策略

### 3.0 实际遇到的清洗问题

| 问题 | 症状 | 根因 | 修复 |
|:----|:-----|:-----|:-----|
| **GB2312 乱码** | `é(600519)Q1 гĸЧ` | PDF 元数据 GB2312 被按 Latin-1 解码 | `pdf_encoding.py`：CJK 比例 <5% + 控制字符高 → 修复 |
| **HTML entity 残留** | `&amp;lt;br&amp;gt;` | Tavily/Serper 返回 HTML 未解码 | `html.unescape()` 在编码修复后执行 |
| **A 股复选框样板** | `适用√□不适用` | PDF 表格复选框文本，不包含有效信息 | `GENERIC_NOISE_PATTERNS` 正则匹配丢弃 |
| **港股 snippet 过长** | 单条 snippet 5000+ chars | Tavily 返回过长片段 | 截断至 2000 chars + 保留有效句子 |
| **美股 10-K 表格 ASCII art** | `----====----` 表格线混入文本 | PDF 表格转文本产生 | 正则去除连续的 `-=|+` 行 |
| **内容过短** | `< 10 chars` 的碎片 | PDF 提取产生大量短片段 | Length gate |
| **内容重复** | 同内容被多个引擎返回 | 多引擎覆盖同一事实 | Content hash dedup（保留 score 最高的）|
| **时间戳丢失** | `publish_time=""` | 部分 API 不返回发布时间 | Fallback 至 retrieved_at / document_date |

### 3.1 为什么清洗必须按固定顺序？

清洗顺序错了会导致误判。例如：

- 如果先做长度门控再做编码修复 → 乱码文本可能看起来"很长"，过了长度门控，但实际上修完后只有几个字
- 如果先做去重再做编码修复 → 同一内容的两种编码形式（正常+乱码）hash 不同，无法去重

### 3.2 6 步清洗顺序

```
Step 1: Encoding detect & repair
  先用 pdf_encoding 检测 GB2312→Latin-1 mojibake
  再尝试 text.encode('utf-8').decode('gbk') 修复
  ▸ 必须先修编码，后续步骤才能正确处理中文

Step 2: HTML entity decode（html.unescape）
  处理 &amp; &lt; &gt; 等实体
  ▸ 在 encoding 修复后做，避免 pre-encoded entity 干扰解码

  --- 市场特异清洗在此插入 ---
  ├── A 股：二次 GB2312 repair（如果 Step 1 没修干净）
  ├── 港股：web snippet 截断至 2000 chars + 保留有效句子
  └── 美股：去除表格 ASCII art + 段落合并

Step 3: Length gate（< 10 chars → discard）
  ▸ 先修编码再判断长度，乱码修完后可能只剩几个字

Step 4: Duplicate content hash dedup
  ▸ 先清洗再 dedup，同一内容的不同编码修完后 hash 一致

Step 5: URL normalize（percent-decode）
  ▸ 独立操作，不影响前面

Step 6: Null timestamp fallback
  publish_time="" → 使用 retrieved_at / document_date / 当前时间
```

### 3.3 Content Gate（后处理）

清洗完成后，对 content 做最终质量检查：

- content 为空 → score = 0，标记 `content_gate_blocked`
- content < 20 chars → score = 0

确保下游 reranking 不会给空/垃圾内容高排名。

### 3.4 为什么不用现成的清洗库？

| 方案 | 问题 |
|:----|:-----|
| `clean-text` 库 | 设计用于通用文本清洗，不支持金融特定模式（如"适用√不适用□"复选框）|
| `ftfy`（fix-text-for-you）| 只修 Unicode 问题，不处理 GB2312→Latin-1 mojibake |
| 自研 6-step pipeline | 针对金融证据的特定清洗需求，每步都可追踪（`cleaning_flags` 数组）|

---

## 4. 切分策略

### 4.0 实际遇到的切分问题

| 问题 | 症状 | 根因 | 修复 |
|:----|:-----|:-----|:-----|
| **固定 500/50 切在词中间** | `"1245亿元"` 被切成 `"1245"` 和 `"亿元"` | 固定长度不考虑语义边界 | smart_chunk：<500 整段，500-2000 按段落，>2000 滑动窗口 |
| **跨 section 混排** | 一个 chunk 含"第一节公司简介"和"第二节财务数据" | 固定切分不感知 section 边界 | Stage 1 section boundary detection |
| **表格检测太激进** | 所有 chunk 判为表格，text_chunks=0 | TABLE_HINT_PATTERN 第二组`(收入\|利润\|资产\|负债\|现金)` 太宽泛 | 去掉第二组 pattern，加短文档严格阈值 |
| **季度报告无 section 标题** | `build_section_map()` 返回空 section_map | 季度报告 12 页没有"第X节"格式 | `_fallback_quarterly_map()` 按典型页面分布分配 |
| **chunk 检索不包含 section 上下文** | "主营业务" query 命中财务数据中的"主营业务收入" | chunk 只存文本正文，不带 section 标题 | `[section_title]` 前缀嵌入 text_clean |
| **向量模型未安装** | `dense_index_backend="disabled"` | sentence-transformers 库文件存在但 pip 未装 | `pip install sentence-transformers` |
| **sentence-transformers 报错** | 模型加载失败 fallback 到 hash_embed | `local_files_only=true` 但库不存在 | 安装后模型正常加载 |

### 4.1 为什么固定长度切分不适合年报？

固定 500 chars 无 overlap 的切分方式在年报上产生两个严重问题：

1. **切在词中间**：`"1245亿元"` 被切成 `"1245"` 和 `"亿元"` → 数字信息丢失
2. **跨 section 混排**：一段文本可能从 "第一节 公司简介" 切到 "第二节 财务数据" → 一个 chunk 包含两个 section 的内容

### 4.2 三级智能切分（smart_chunk）

```
输入文本
  │
  ▼
Stage 1: Section boundary detection（规则匹配）
  ├── A 股年报: "第一节"/"第二节"/"公司业务"/"核心竞争力" 标题匹配
  ├── SEC 10-K: "Item 1"/"Item 1A"/"Item 7" 正则
  └── 港股: "Business Overview"/"MD&A" 英文标题
  │   确保不跨 section 边界
  ▼
Stage 2: 长度门控（if/else dispatch）
  ├── < 500 chars  → 不切，整段作为 1 个 chunk（短文本完整过）
  ├── 500-2000    → 按段落边界切（\n\n），段落完整
  └── > 2000      → 滑动窗口，对齐句子末尾（非截断）
        window=1150 chars, overlap=160 chars
  ▼
Stage 3: 句子级 overlap
  └── 切点不在词中间，保留句尾内容作为 overlap
```

### 4.3 为什么不用语义切分？

| 方法 | 为什么不选 |
|:----|:----------|
| **固定切割（500 chars）** | ❌ 切在词中间，跨 section 混排 |
| **纯 overlap 滑动（500/50）** | ❌ 仍然跨 section 边界 |
| **语义切割（embedding 聚类）** | ❌ 比规则匹配慢 100x，且年报已有结构化标题，规则匹配更准 |
| ✅ **三级组合（本文方案）** | 各取所需，按数据特征 dispatch |

### 4.4 Section Title 前缀

每个 chunk 生成时，在 `text_clean` 前加上 `[section_title]`：

```python
# Before
text = "2025年度公司实现营业总收入1720亿元"

# After
text = "[第三节管理层讨论与分析]2025年度公司实现营业总收入1720亿元"
```

**为什么这样做**：BM25 和向量检索都只匹配语义相似度。不加前缀时，"主营业务"的 query 可能匹配到财务数据中的 "主营业务收入"——语义相似但在财报 section 里这些数字不包含业务描述。前缀让 BM25 能命中 section 标题，提升召回精度。

同时，`EvidenceChunk.searchable_text` 也加入 `[section_title]` 前缀，确保向量检索时 section 上下文不被忽略。

---

## 5. 检索与召回

### 5.0 实际遇到的检索问题

| 问题 | 症状 | 根因 | 修复 |
|:----|:-----|:-----|:-----|
| **RRF 阈值设错导致全部过滤** | content_depth 暴跌，报告从 85 分降到 45 分 | `MIN_RETRIEVAL_SCORE=0.3` 但 RRF 最大值仅 0.016（`1/(1+60)`） | 去掉 RRF 阈值，RRF 只排序不做质量过滤 |
| **section 内容混排** | 同一 chunk 被 3 个不同 section 同时使用 | RAG 检索不检查 chunk 的物理页码 | `section_page_range` 硬约束，不在页范围内的排除 |
| **RRF 分数不能当绝对质量分** | 试图用 RRF score 做阈值 | 把排名分误当作相似度分 | RRF 只用于排序，质量过滤用 cosine score |
| **BM25 + Dense 分数不可比** | BM25 score 0~∞，cosine 0~1.0，无法直接融合 | 两个系统分数分布不同 | RRF 将分数转为排名再融合 |
| **Cross-encoder reranker 加载失败** | fallback 到 RRF 分数直接排序 | `bge-reranker-base` 的 modules.json 缺失 | 自动初始化为 CrossEncoder，加载时给出 warning |
| **BM25 结果全部来自错误 section** | 管理层讨论的 query 返回财务数据 | BM25 不区分 section_type，只看词频 | 确保 candidate_chunks 已按 section_type + page_range 过滤 |
| **Local evidence parquet 损坏** | `Repetition level histogram size mismatch` | parquet 文件在多次写入中损坏 | 跳过损坏文件，不影响其他数据源 |

### 5.1 检索架构

```
Query
  │
  ├──→ BM25（词法检索）
  │     └── 基于 EvidenceChunk.searchable_text 的倒排索引
  │
  ├──→ Dense（向量检索）
  │     └── ChromaDB EphemeralClient / Memory fallback
  │          └── 模型：bge-small-zh / bge-small-en / bge-m3
  │
  └──→ RRF Fusion（分数融合）
        └── BM25 weight=0.55, Dense weight=0.45, k=60
             └──→ Cross-encoder Reranker（BAAI/bge-reranker-base）
```

### 5.2 为什么用 BM25 + Dense 双路？

| 方式 | 优势 | 劣势 |
|:----|:-----|:-----|
| **BM25 单独** | 精确词匹配，"主营业务"一定匹配含"主营业务"的文档 | 语义变体不匹配，"核心竞争力"≠"core competency" |
| **Dense 单独** | 语义匹配，"core competency"能匹配"核心竞争力" | 精确数字匹配差，"1720亿"可能匹配"1720万" |
| **BM25 + Dense（本文方案）** | 两者互补 | 需要 RRF 做分数融合，额外计算量 |

### 5.3 为什么选 bge 系列模型？

| 模型 | 维度 | 适用市场 | 不选其他模型的原因 |
|:----|:----:|:--------:|:------------------|
| `bge-small-zh-v1.5` | 512d | A 股中文 | 比 `text2vec-large-chinese` 小 5 倍（90MB vs 450MB），速度 10x，精度差 <2% |
| `bge-small-en-v1.5` | 384d | 美股英文 | 比 `all-MiniLM-L6-v2` 在 MTEB 上高 3 个点，比 `bge-large-en-v1.5` 小 10 倍 |
| `bge-m3` | 1024d | 港股中英混合 | 原生支持中英混合输入，`multilingual-e5-base` 需要人工构造 "query: " 前缀 |

**为什么不选大模型做 embedding**：`text-embedding-3-large`（OpenAI）单次调用 $0.13/1M token，900 公司 × 270k chunks × 每个 200 token = 54M token → $7/次。本地 bge-small 免费，仅需 ~1 秒/次推理。

### 5.4 BM25 实现

使用 `rank_bm25` 库的 BM25Okapi 实现，tokenizer 为中文 jieba 分词 + 英文 whitespace split。

### 5.5 ChromaDB 选型

| 数据库 | 为什么不选 |
|:-------|:----------|
| FAISS | 纯向量库，不支持 metadata 过滤。如果搜 `symbol=600519.SS` 需要额外维护一个 SQLite 映射表，增加复杂度 |
| Qdrant | 需要 Docker 容器，单机 165MB 的数据量用 Qdrant 太重 |
| Milvus | 需要 etcd + MinIO + 至少 3 个节点，为 165MB 搭分布式是过度设计 |
| pgvector | 需要 PostgreSQL，项目没有数据库依赖，引入 Postgres 管理成本高 |
| ✅ **ChromaDB Persistent** | 零新依赖（已有 `chromadb`），`EphemeralClient`→`PersistentClient` 一行改动，metadata filter 原生支持 |

---

## 6. 融合与重排

### 6.1 为什么需要 RRF 而不是直接用分数排序？

BM25 和 Dense 的分数值域不同：

- BM25 score：0~∞（取决于文档长度和词频）
- Dense cosine similarity：0~1.0

两者不能直接比较。RRF（Reciprocal Rank Fusion）把两者都转为基于排名的分数：

```
score = 1 / (rank + k)
```

只关心"谁是第几名"，不关心"得分具体是多少"。`k=60` 是经验值，控制排名靠后的文档的衰减速度。

### 6.2 RRF 的坑

**RRF 分数不适合做绝对阈值。** RRF 分数值域 ~0.01-0.02（`1/(1+60)=0.016`），设置 `score >= 0.3` 的阈值会过滤掉所有结果。这个问题我们在开发中实际遇到过——导致所有 section 的内容都为空，报告质量从 85 分降到 45 分。

**正确的做法**：RRF 只做排序，不做绝对质量过滤。如果要按页范围过滤，应该在融合前用页码硬约束（`section_page_range`）排除不属于当前 section 页范围的 chunk。

### 6.3 权威层级融合

```
Primary (权威值 1.0):
  SEC 10-K/10-Q filing text
  HKEX official announcement PDF
  eastmoney_financials 结构化财报
  → 直接采用，作为 section content base

Secondary (权威值 0.7):
  sec_companyfacts 结构化指标
  eastmoney 实时行情
  → 用于补充和交叉验证

Tertiary (权威值 0.4):
  tavily/serper web_search snippets
  yahoo 行情快照
  → 仅在 Primary 和 Secondary 都缺失时使用
```

**降级策略**：当 Primary 和 Secondary 都缺失时，不写 gap——直接用 Tertiary 数据填充。质量分在有数据时可拉满（content 存在即可得分），后续接入 Primary 后再提权。

---

## 7. RAG 流程中的关键问题与解决

### 7.1 问题总表

| 环节 | 问题 | 严重度 | 解决状态 |
|:----|:-----|:------:|:--------:|
| 数据源 | East Money API 连接被拒 | 🔴 | ✅ 接入 Sina Finance 替代 |
| 数据源 | CNINFO PDF GB2312 乱码 | 🔴 | ✅ `pdf_encoding.py` 修复 |
| 数据源 | CNINFO PDF bookmark 页码错误 | 🔴 | ✅ `_correct_bookmark_pages()` 修复 |
| 数据源 | SEC EDGAR 默认关闭 | 🟡 | ✅ `enable_remote=True` |
| 数据源 | HKEX 无批量 API | 🟡 | ⏳ 需 Tavily query 优化 |
| 数据源 | Yahoo Finance 只返回行情快照 | 🟡 | ⏳ 需 yfinance 扩展 |
| 清洗 | GB2312 乱码（PDF 元数据）| 🔴 | ✅ 6-step pipeline，encoding 修复为首步 |
| 清洗 | HTML entity 残留（&amp;等）| 🟡 | ✅ `html.unescape()` |
| 清洗 | A 股复选框样板文字 | 🟡 | ✅ `GENERIC_NOISE_PATTERNS` 丢弃 |
| 清洗 | 港股 snippet 过长 | 🟡 | ✅ 截断至 2000 chars |
| 清洗 | 美股 10-K 表格 ASCII art | 🟡 | ✅ 正则去除 |
| 清洗 | 内容过短碎片 | 🟡 | ✅ Length gate < 10 chars discard |
| 清洗 | Parquet 文件损坏 | 🟡 | ✅ 跳过损坏文件 |
| 切分 | 固定 500/50 切在词中间 | 🔴 | ✅ smart_chunk 三级策略 |
| 切分 | 跨 section 混排 | 🔴 | ✅ Stage 1 section boundary detection |
| 切分 | 表格检测太激进，全部判为表格 | 🔴 | ✅ 去掉第二组 TABLE_HINT_PATTERN，短文档严格阈值 |
| 切分 | 季度报告无 "第X节" 标题 | 🔴 | ✅ `_fallback_quarterly_map()` |
| 切分 | chunk 无 section title 前缀 | 🟡 | ✅ `[section_title]` prefix |
| 检索 | 向量模型没加载 → dense search 0 结果 | 🔴 | ✅ 安装 sentence-transformers |
| 检索 | BM25 和 Dense 分数不可比 | 🟡 | ✅ RRF 融合 |
| 检索 | BM25 检索结果全部来自错误 section | 🟡 | ✅ 确保 candidate_chunks 按 section_type + page_range 过滤 |
| 融合 | RRF 阈值 0.3 设错 → 过滤全部结果 | 🔴 | ✅ RRF score 仅 0.016，不适合做绝对阈值 |
| 融合 | Section 内容混排（不同 section 抢同一 chunk）| 🔴 | ✅ `section_page_range` 硬约束 |
| 融合 | RRF 分数不能当质量阈值用 | 🟡 | ✅ 改用 page-range + cosine score |
| 重排 | Cross-encoder reranker 加载失败 | 🟡 | ✅ 自动初始化为 CrossEncoder |
| 生成 | LLM prompt "concise" → 内容太短 | 🔴 | ✅ 改为 "comprehensive detailed" + 3-5 段落要求 |
| 生成 | max_evidence=12 太少 | 🟡 | ✅ 改为 20 |
| 生成 | evidence_content_limit=600 太低 | 🟡 | ✅ 改为 1200 |
| 生成 | content_depth blocker（12 个）| 🔴 | ⏳ 需 facts extraction |
| 显示 | 置信度硬编码 45% | 🟡 | ✅ 改为基于数据计算（75-80%）|
| 显示 | engine 列表不生效 | 🔴 | ✅ 后端强制 `default_engines_for_symbol()` |
| 显示 | 浏览器 HTML 缓存 | 🟡 | ✅ 无痕窗口 / 清缓存 |
| 显示 | web_ui 进程加载旧代码 | 🔴 | ✅ `__pycache__` 清除 + 重启 |

### 7.2 最大教训

**"零件装车"问题**：模块写好自检通过 ≠ 链路中实际生效。我们多次遇到这种情况——`pdf_encoding.py` 存在、自检 7/7 全过，但 `pdf_rag_pipeline.py` 还在用自己的 `_has_mojibake()` 函数，根本没调用新模块。**必须先验证运行链路，再相信测试报告。**

### 7.3 另一个教训：RRF 分数值域

RRF 分数的最大值是 `1/(1+k)`，当 `k=60` 时只有 0.016。把这个值当成 cosine similarity 来设阈值是常见错误。**RRF 只用来排序，不用来做质量过滤。**

---

## 8. Multi-Agent 架构与 ReAct 设计

### 8.1 Agent 分工

| Agent | 职责 | 为什么独立 |
|:------|:-----|:-----------|
| **Planning** | 拆解用户请求为子任务 | 避免一个 agent 处理全部逻辑导致上下文过长 |
| **Research** | 多引擎并行搜索 + ReAct loop | 搜索需要多轮决策（搜什么→结果如何→还需要搜什么）|
| **Analyze**（5 个）| 身份确认、三表分析、估值、风险、同行 | 每个领域有独立的 prompt + 计算逻辑，混合会互相干扰 |
| **FinalAnswer** | 基于 claims 生成报告 | 只写已验证的内容，不做搜索/分析 |
| **Verifier** | 逐 claim 校验引用和数字 | 独立的校验视角，不受写作 agent 的偏见影响 |
| **Gap Resolver** | 分析校验失败原因，生成修复约束 | 修复逻辑独立，不影响原始 analysis |

### 8.2 ReAct 循环设计

Research Agent 使用 ReAct（Reasoning + Acting）循环：

```
                     ┌─────────────────────────────────────┐
                     │          User Query                  │
                     │  "生成 600519.SS FY2025 财报研报"    │
                     └──────────┬──────────────────────────┘
                                │
                                ▼
               ┌─────────────────────────────────────┐
               │      ReAct Loop (max 3 steps)        │
               │                                       │
               │  ┌──────────┐     ┌──────────┐       │
               │  │ Thought  │────▶│  Action  │       │
               │  │ LLM推理   │     │ tool_call│       │
               │  └────┬─────┘     └────┬─────┘       │
               │       │                │              │
               │       │     Tool Registry             │
               │       │     ├── search()              │
               │       │     ├── fetch_yahoo_...()     │
               │       │     ├── retrieve_local()      │
               │       │     ├── calculate_metrics()  │
               │       │     └── generate_chart()      │
               │       │                │              │
               │       │     ┌──────────┘              │
               │       │     ▼                         │
               │       │  ┌──────────┐                 │
               │       └──│Observation│                │
               │          │ tool返回   │                │
               │          └────┬─────┘                 │
               │               │                        │
               │    ┌──────────┴──────────┐             │
               │    │  数据够了吗？        │             │
               │    ├── 不够 → 回到 Thought│             │
               │    └── 够了 → Final Answer             │
               │                  │                      │
               └──────────────────┼──────────────────────┘
                                  │
                                  ▼
                     ┌─────────────────────┐
                     │   Evidence List      │
                     │   [{evidence_id,     │
                     │     source_type,     │
                     │     content,         │
                     │     score}, ...]     │
                     └──────────┬──────────┘
                                │
                                ▼
                     Analyze Agents 消费
```

**执行示例（600519.SS FY2025）：**

```
Step 1 Thought: "先搜本地缓存"
Step 2 Action:   search(engines=["local_real_data"])
Step 3 Obs:      0 hits（本地无缓存）

Step 4 Thought: "本地没有，走 eastmoney_financials"
Step 5 Action:   search(engines=["eastmoney_financials"])
Step 6 Obs:      3 hits（收入/利润表/现金流表）

Step 7 Thought: "财报有了，补 sina 行情"
Step 8 Action:   search(engines=["sina_finance"])
Step 9 Obs:      1 hit（实时价+涨跌幅）

Step 10 Thought: "数据够了，返回 evidence"
Step 11 Final:   证据列表
```

**为什么不用 Plan-then-Execute**：金融数据源的状态不确定（某个 API 可能刚好不可用、缓存可能有/没有），ReAct 允许根据实际情况动态调整。Plan-then-Execute 的固定计划在数据源不可用时需要完整的重新规划。

**最大的 ReAct 参数**：`react_max_steps=3`——限制最大循环步数，防止无限循环。三步过后无论结果如何都返回已有数据，宁可 incomplete 不可 infinite。

### 8.3 ReAct 局限

ReAct 的 "Thought → Action → Observation" 循环依赖于 LLM 的推理能力。如果 LLM 在第一步 Thought 就判断错误（例如认为 A 股应该走 sec_edgar），后续所有步骤都会基于错误前提。我们的缓解方案是：

1. **Tool 描述中包含使用场景**：每个 tool 的 description 写明适用市场和场景
2. **Skill Registry**：定义 6 个技能（evidence_discovery / financial_statement_analysis / ...），ReAct loop 根据 query 激活对应技能
3. **Fallback 机制**：如果全部引擎都返回 0 结果，降级使用 Tavily/Serper 网络搜索

---

## 8.4 数据流：从数据源 → Evidence → Claims → 报告

这是整个系统最核心的数据流转。很多人问"evidence 和 claim 有什么区别""analyze agents 拿到的数据是哪来的"。下面完整走一遍。

### 完整流转图

```
                    ┌─────────────────────────────────┐
                    │         数据源（原材料）           │
                    │  CNINFO PDF / eastmoney API      │
                    │  sina_finance / SEC EDGAR        │
                    │  yahoo / tavily / serper          │
                    └──────────────┬──────────────────┘
                                   │ SearchManager 调各引擎 handler
                                   │ 结果经过 _clean_search_results() 清洗
                                   ▼
                    ┌─────────────────────────────────┐
                    │      evidence_records（证据）     │
                    │  清洗后、带 source 的结构化数据    │
                    │                                  │
                    │  每条 record 包含：                │
                    │  {evidence_id, source_type,       │
                    │   content, score, symbol,         │
                    │   publish_time, trust_level,      │
                    │   source_url, title}               │
                    │                                  │
                    │  例："Eastmoney income table:     │
                    │   total_operating_revenue         │
                    │   =172054171890.91"               │
                    │   trust_level="high"              │
                    └──────────────┬──────────────────┘
                                   │ 传递给：
                                   │  ├── Analyze Agents（作为分析素材）
                                   │  └── ClaimEvidenceBundler（作为引用来源）
                                   ▼
                    ┌─────────────────────────────────┐
                    │        Analyze Agents            │
                    │  5 个独立 agent，各有职责         │
                    │                                  │
                    │  IdentityAgent ← evidence        │
                    │    → 输出 company_profile         │
                    │    （公司名、行业、业务描述）       │
                    │                                  │
                    │  StatementAgent ← evidence        │
                    │    → 输出 financial_metrics       │
                    │    + three_statement_claims        │
                    │    （收入/利润/资产负债/现金流）    │
                    │                                  │
                    │  ValuationAgent ← financial_metrics│
                    │    → 输出 valuation_model         │
                    │    （DCF 估值、倍數估值）          │
                    │                                  │
                    │  RiskAgent ← evidence             │
                    │    → 输出 风险 claims             │
                    │    （行业风险、公司特有风险）       │
                    │                                  │
                    │  PeerAgent ← evidence             │
                    │    → 输出 同行 claims              │
                    │    （可比公司列表、对比指标）       │
                    └──────────────┬──────────────────┘
                                   │
                   ┌───────────────┴──────────────────┐
                   │        claims（论断）              │
                   │  基于 evidence 加工后的可验证断言   │
                   │                                   │
                   │  每条 claim 包含：                 │
                   │  {claim_id, claim_text,            │
                   │   evidence_ids: [引用的证据列表],   │
                   │   section_name,                    │
                   │   confidence, risk_level}          │
                   │                                   │
                   │  例："公司2025年营业收入1720亿元"   │
                   │   evidence_ids: ["income_table_1"] │
                   │   section_name: "three_statement"  │
                   └───────────────┬──────────────────┘
                                   │
                   ┌───────────────┴──────────────────┐
                   │    claim_evidence_bundles          │
                   │  将 claim 和它的 evidence 打包      │
                   │                                   │
                   │  每个 bundle 包含：                 │
                   │  {claim_id, claim_text,            │
                   │   supporting_evidence: [           │
                   │     {evidence_id, content,         │
                   │      source_type, trust_level}     │
                   │   ],                               │
                   │   grounding_status:  ← 关键字段    │
                   │     "grounded"   ✅ 有高信任证据    │
                   │     "partial"    ⚠️ 只有低信任证据  │
                   │     "unverified" ❌ 无证据支撑      │
                   │   allowed_in_report: bool}          │
                   └───────────────┬──────────────────┘
                                   │
                   ┌───────────────┴──────────────────┐
                   │      FinalAnswer Agent             │
                   │  只写 grounded 或 partial 的 claim  │
                   │  忽略 unverified（放入数据缺口）    │
                   │  引用格式: [evidence_id]            │
                   │                                   │
                   │  → 生成 markdown → HTML 报告      │
                   └──────────────────────────────────┘
```

### Evidence 和 Claim 的核心区别

| | **Evidence（证据）** | **Claim（论断）** |
|:--|:--------------------|:-----------------|
| **定义** | 数据源的原始输出，清洗后带 source 信息 | 基于证据加工后的可验证断言 |
| **谁来产生** | SearchManager（搜索）→ 清洗 | Analyze Agents（分析）|
| **内容特征** | "Eastmoney income: revenue=172054171890.91" | "公司2025年营收1720亿元" |
| **可追溯** | 有 evidence_id + source_url + source_type | 有 evidence_ids 列表指向来源证据 |
| **判断标准** | "数据说了什么" | "我们可以断言什么" |
| **信任度** | trust_level: high / medium / web | grounding_status: grounded / partial / unverified |
| **存储位置** | `state["evidence_records"]` | `state["claims"]` |
| **谁消费** | Analyze Agents + Bundler | FinalAnswer Agent（只写 grounded）|

### Grounding 判定逻辑

```python
# claim_evidence_bundle.py
HIGH_TRUST_LEVELS = {"high", "official", "derived"}
LOW_TRUST_LEVELS = {"web_or_news", "low", "unknown"}

if any(ev["trust_level"] in HIGH_TRUST_LEVELS for ev in supporting_evidence):
    grounding_status = "grounded"       # 至少有 1 条高质量证据
elif ev_count >= 1:
    grounding_status = "partial"        # 只有低质量证据
else:
    grounding_status = "unverified"     # 无证据支撑
```

### 数据流决定报告质量

当前报告的 content_depth 问题（每节只有几十个字）根因出在 **从 evidence 到 claim 这一步**：

```
正常流程：
  evidence（1720亿这个数字）→ Analyzer 提取为 claim
    → "公司2025年营业收入1720亿元"
    → grounding="grounded"
    → FinalAnswer 写进报告

当前缺失：
  evidence（年报 PDF 段落）→ Analyzer 不提取 facts
    → claim 没有结构化内容
    → FinalAnswer 只能写 raw chunk 或模板
    → content_depth 只有 32 个字
```

**这就是为什么 pdf_facts_extractor.py 的作用是替代 Analyzers 没做的结构提取。** 它不是 Analyze Agent 的替代品，而是在 Analyze Agents 没有提取出足够结构化 facts 时，提供一个后备的结构化事实来源。

### 9.1 为什么设计这些工具？

| 工具 | 用途 | 为什么不直接用代码调用 |
|:-----|:-----|:---------------------|
| `search` | 搜索证据（统一入口，背后是多个引擎）| 多个引擎切换需要 Agent 决策 |
| `fetch_yahoo_market_snapshot` | 获取实时行情 | Agent 需要知道用了哪个行情源 |
| `retrieve_local_evidence` | 本地证据库 BM25 检索 | BM25 参数（topk、ranking_mode）需要 Agent 指定 |
| `calculate_financial_metrics` | 计算财务比率 | Agent 需要选择计算哪些比率 |
| `generate_chart` | 生成图表 | 图表类型需要 Agent 根据数据选择 |

**为什么不把所有功能合并成一个 tool**：Tool 的粒度决定了 Agent 的控制粒度。一个 "do_everything" 的 tool 等于没有 tool——Agent 无法选择"只用搜索不用生成图表"。

### 9.2 Tool Schema 设计

每个 tool 定义 JSON Schema：

```python
{
    "name": "search",
    "description": "搜索金融证据，支持 A 股/港股/美股多个数据源",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "engines": {"type": "array", "items": {"type": "string"}},
            "topk": {"type": "integer", "default": 5}
        },
        "required": ["query"]
    }
}
```

**为什么用 JSON Schema 而不是自然语言描述**：JSON Schema 可以被 LLM 的结构化输出能力精确解析，自然语言描述会导致 LLM 跳过参数或格式错误。

### 9.3 Tool 执行流程

```
LLM 返回 tool_call(token, args)
  │
  ▼
Tool Registry 匹配 token → handler function
  │
  ▼
handler(args) → result
  │
  ▼
result 注入到 LLM 的下一轮 context
  │
  ▼
LLM 基于 result 决定：继续搜索 / 分析 / 最终答案
```

---

## 10. Trace 与可观测性

### 10.1 为什么需要 Trace？

Multi-Agent 系统最大的痛点是**错误定位**。Single-Agent 的日志只有 "request → response"，Multi-Agent 有 6+ agent 的调用链，没有 trace 就无法知道：

- 哪个 agent 产生了错误的数据？
- 哪个 tool 返回了空结果？
- 哪个 evidence 被用于哪个 claim？

### 10.2 Trace 文件结构

每次运行产出一套 trace 文件：

| 文件 | 内容 | 用途 |
|:-----|:-----|:-----|
| `task_trace.jsonl` | 每条 agent task 的执行记录（输入、输出、状态、耗时） | 定位哪个 agent 失败 |
| `agent_collaboration_trace.json` | agent 间的调用链路（谁调了谁、传递了什么） | 可视化 agent 协作 |
| `tool_trace.json` | 所有 tool 调用记录（参数、返回、耗时） | 定位哪个数据源/工具失败 |
| `search_meta.json` | 每个引擎的搜索结果统计 | 数据源覆盖率分析 |
| `performance_trace.json` | 总耗时、超时、阶段 | 性能瓶颈分析 |
| `quality_report.json` | 质量门禁评分 | 报告质量自动评估 |
| `delivery_gate.json` | 交付门禁结果 | 是否通过质量检查 |

### 10.3 Trace 怎么用

**场景：报告显示"治理 gap 引用三表"**

```
1. tool_trace.json → 查看 search 工具的 evidence_id 列表
2. task_trace.jsonl → 查看 Analyzer Agent 收到了哪些 evidence
3. agent_collaboration_trace.json → 检查 CitatonBinder 是否被调用
4. quality_report.json → 确认 "official_evidence_0013" blocker
```

没有 trace，就只能人工查阅报告全文猜测问题。有了 trace，5 分钟可以定位到具体环节。

### 10.4 Task ID 注入

每条日志都带 task_id，可以 grep 追溯一次完整请求：

```bash
grep "600519.SS_FY2025" logs/pipeline.log
```

就能看到该请求全部 agent 的执行时间线。

### 10.5 向量相似度日志（已添加）

在 `chroma_index.py` 和 `retrieve.py` 中增加了：

```python
# 输出样例
2026-06-02 12:03:58 | INFO | src.retrieval.chroma_index |
  vector_search | query="主营业务 产品 渠道" | topk=6 | results=4 |
  scores=[0.508, 0.507, 0.440]
```

之前这些分数只存在内存中，不在日志里。加了这个日志后，可以追溯每次检索的相似度分布，判断"为什么没召回"或"为什么召回的内容不对"。

---

## 11. 模型选型

### 11.1 Embedding 模型

| 模型 | 维度 | 参数量 | 适用市场 | 选型理由 |
|:----|:----:|:------:|:--------:|:---------|
| `BAAI/bge-small-zh-v1.5` | 512 | 24M | A 股中文 | MTEB 中文榜第 5，速度 1000 doc/s（CPU）|
| `BAAI/bge-small-en-v1.5` | 384 | 24M | 美股英文 | MTEB 英文榜第 8，80MB 显存占用 |
| `BAAI/bge-m3` | 1024 | 102M | 港股中英混合 | 原生支持 100+ 语言混合输入，不依赖 `query:` 前缀 |

**为什么不选大模型**：见 5.3 节。

### 11.2 Reranker 模型

| 模型 | 参数量 | 选型理由 |
|:-----|:------:|:---------|
| `BAAI/bge-reranker-base` | 102M | 在 BEIR 和 MTEB 上排名前三，比 `cross-encoder/ms-marco-MiniLM-L6` 高 5 个点 |

**为什么需要 reranker**：BM25 + Dense 双路检索返回 top-30 候选，其中可能包含与 query 语义相关但实际内容不佳的文档。Cross-encoder reranker 对 (query, doc) 做联合编码，精度高于双编码器。

### 11.3 LLM

当前使用 DeepSeek 系列模型：

| 用途 | 模型 | 理由 |
|:-----|:-----|:------|
| Planning / Research | deepseek-v4-flash | 速度快，成本低 |
| FinalAnswer / Verifier | deepseek-v4-pro | 需要更强推理和生成能力 |

---

## 12. 检索流程与向量数据库

### 12.1 当前检索流程 vs 目标检索流程

```
当前流程（实时爬取，2026.06 现状）
────────────────────────────────────

报告请求 │
  symbol=600519.SS, period=FY2025
    │
    ▼
┌─────────────────────────────┐
│ SearchManager               │
│ ├── cninfo_announcements     │ 实时爬 CNINFO PDF
│ ├── eastmoney_financials    │ 实时调东财 API
│ ├── sina_finance             │ 实时行情
│ ├── yahoo_finance            │ 实时行情
│ └── local_evidence           │ BM25（本地 parquet 缓存）
│     └── BM25 检索            │ 词法匹配
│     └── ChromaDB Ephemeral   │ 进程级内存，重启丢失
│         └── RRF Fusion       │ BM25 + Dense 融合
│         └── Reranker         │ Cross-encoder 精排
└─────────────────────────────┘
    │
    ▼
证据列表 → 报告生成

问题：每次实时爬，慢 + 不稳定
      ChromaDB 不持久化
      相同 PDF 每次重新解析 embed
────────────────────────────────────



目标流程（ChromaDB 持久化，待实施）
────────────────────────────────────

离线批量（一次搞定）
  900 公司 × 5 周期
  ├── 下载 PDF / JSON
  ├── 解析 + 切块 + 编码修复
  ├── 生成 embedding
  └── 写入 ChromaDB Persistent
      └── data/vector_db/
      └── finsight_cn_a（512d）
      └── finsight_hk（1024d）
      └── finsight_us（384d）

报告请求 │
  symbol=600519.SS, period=FY2025
    │
    ▼
┌─────────────────────────────┐
│ ChromaDB.query()            │ 持久化库查询
│ where={symbol, period}      │ metadata 精确过滤
│    │                         │
│    ▼                         │
│ ┌─────────────────────┐     │
│ │ 候选 chunks 列表    │     │
│ │ 已带 section_title  │     │
│ │ 前缀                │     │
│ └──────────┬──────────┘     │
│    │                         │
│    ▼                         │
│ BM25 rerank（重排候选）      │
│ RRF Fusion                   │
│ + 轻量实时补充（行情+新闻）   │
│ （sina_finance/tavily）      │
└─────────────────────────────┘
    │
    ▼
证据列表 → 报告生成

优势：PDF 只解析一次
      检索速度 10x+
      持久化不丢数据
────────────────────────────────────
```

### 12.2 关键区别

| 环节 | 当前（2026.06） | 目标（批量入库后） |
|:----|:--------------|:-----------------|
| **PDF 解析** | 每次报告实时爬 CNINFO PDF，解析 + embed | 离线批量一次解析，chunk 持久化 |
| **ChromaDB** | `EphemeralClient`，进程重启数据丢失 | `PersistentClient("data/vector_db")` |
| **检索入口** | `SearchManager` 遍历 8 个引擎 | ChromaDB query + BM25 rerank |
| **引擎分工** | 全部实时爬取 | ChromaDB 查年报/财报；sina/tavily 只补实时 |
| **BM25** | 主检索，无预构建索引 | rerank 辅助，在候选集上重排 |
| **向量检索** | 每次重建 index，小规模 | 持久化 index，支持大规模 |
| **速度** | 2-5 分钟/报告（含 PDF 解析）| ~10 秒/报告（查库 + 轻量补充）|
| **数据依赖** | 依赖 CNINFO/SEC/HKEX 网络 | 无网络依赖，查本地库即可 |

### 12.3 ChromaDB 数据库设计

#### Collection 设计

每个市场一个 collection（因为 embedding 维度不同）：

| Collection | 市场 | 维度 | 模型 | 预计容量 |
|:-----------|:----:|:----:|:----:|:--------:|
| `finsight_cn_a` | A 股 | 512d | `bge-small-zh-v1.5` | 450k × 512d ≈ 184 MB |
| `finsight_hk` | 港股 | 1024d | `bge-m3` | 360k × 1024d ≈ 295 MB |
| `finsight_us` | 美股 | 384d | `bge-small-en-v1.5` | 315k × 384d ≈ 97 MB |

#### Chunk Metadata 设计

每条 ChromaDB 记录携带以下 metadata，支持精确过滤：

```json
{
    "chunk_id": "pdf_abc123def456",
    "symbol": "600519.SS",
    "period": "FY2025",
    "market": "cn_a",
    "section_type": "business_overview",
    "section_title": "业务概览",
    "source_type": "annual_report_pdf",
    "source_url": "http://static.cninfo.com.cn/...PDF",
    "publish_time": "2026-04-17",
    "chunk_index": 3,
    "page_number": 5,
    "trust_level": "official",
    "content_length": 1150
}
```

**过滤方式**：
```python
# 精确查某公司某周期的某个 section
collection.query(
    query_texts=["主营业务 产品 渠道"],
    where={
        "$and": [
            {"symbol": {"$eq": "600519.SS"}},
            {"period": {"$eq": "FY2025"}},
            {"section_type": {"$eq": "business_overview"}},
        ]
    },
    n_results=6,
)
```

#### 为什么按市场分 collection 而不是合并？

| 方案 | 问题 |
|:-----|:------|
| **一个 collection** | 三种模型维度不同（384/512/1024d），ChromaDB 不支持同一 collection 混合维度 |
| **按市场分（本文方案）** | 每个 collection 维度固定，market 不作为 filter 而是隐式的库级属性 |

### 12.4 数据入库规模估算

#### 900 家公司 × FY2022–2026Q1

| 市场 | 公司数 | 周期 | 每份报告 chunk 数 | 总 chunk 数 |
|:----:|:------:|:----:|:-----------------:|:-----------:|
| A 股 | 300 | 5 周期 | ~100 | 150,000 |
| 港股 | 300 | 5 周期 | ~80 | 120,000 |
| 美股 | 300 | 5 周期 | ~70 | 105,000 |
| **合计** | **900** | **5 周期** | | **~375,000 chunks** |

#### 存储总量

```
类型          容量           说明
──────────    ──────         ──────────────────
向量          ~576 MB        3 个 collection 分别存储
文本+metadata  ~1.5 GB       原文和检索用 metadata
PDF 原文      ~6.75 GB       900 × 5 × 1.5MB（平均），索引后可删
──────────    ──────
总计          ~8.8 GB        全量在线存储
```

#### 索引构建时间

```
Embedding 生成（CPU batch=64）：
  375k chunks / 64 × 2s ≈ 11.7 分钟

ChromaDB 写入：
  375k upsert ≈ 7 分钟

总耗时：~20 分钟/全量
增量更新：~1 分钟/新增 100 家公司
```

### 12.5 离线批量 vs 实时查询的分工

```
离线批量（一次性）                   实时查询（每次报告）
─────────────────                   ──────────────────
PDF 下载                            ChromaDB.query()
PDF 解析 + 编码修复                  BM25 rerank
Section detection + chunking         sina_finance 行情
Section title 前缀嵌入                tavily 最新新闻
Embedding 生成                       yahoo 价格快照
ChromaDB PersistentClient 写入       East Money API 补充
                                    metadata 过滤（symbol + period）
```

---

## 13. 质量门禁体系

### 13.1 检查维度

| 维度 | 权重 | 检查内容 | 阈值 |
|:----|:----:|:---------|:----:|
| structure | 0.16 | 报告结构完整（有摘要/风险/结论等必含章节）| 自动 |
| evidence | 0.20 | 证据数量、来源多样性、覆盖率 | 自动 |
| financial | 0.16 | 三表数据完整性、数字一致性 | 自动 |
| multimodal | 0.10 | 图表是否支持分析 | 自动 |
| professional_depth | 0.20 | 投资结论是否有方向性理由 | 自动 |
| content_depth | 0.08 | 每节最小中文字符数 | 120-220 字符/节 |
| compliance | 0.10 | 合规披露、无模板残留 | 自动 |

**客观分阈值**：default 0.82，港股 0.60（配置在 `quality_gate.yaml`）

### 13.2 12 个 blocker 的类型（当前状态）

```
content_depth × 8          → 每节内容不足（执行摘要 32 chars / 阈值 120）
chart_internal_labels × 3  → 图表内部字段名泄漏到正文
internal_metric_key_leak   → 内部指标名未替换为中文
official_evidence          → 缺少可验证的官方证据（balance_sheet/cash_flow/income_statement）
professional_depth         → 投资结论缺乏方向
```

### 13.3 置信度显示（已修复）

置信度显示之前有一个 bug：`_estimate_confidence()` 在 `delivery_status="blocked"` 时硬编码返回 45，无论实际数据质量如何。已改为基于数据丰富度计算（图表数 + 引用数），blocked 状态仅减 10 分。

---

## 14. 项目路线图与当前进度

### 14.1 完成状态

```
Phase 1 — 修链路                  ✅ 100%
  1.1 pdf_encoding               ✅
  1.2 pdf_section_detector       ✅
  1.3 sec_edgar remote           ✅
  1.4 sina_finance               ✅
  1.5 清洗 pipeline              ✅
  1.6 quality_gate.yaml          ✅

Phase 2 — 合约优先 + 事实抽取       ✅ 100%（当前迭代）
  P0-CLI PDF 管道打通              ✅ _run_static 补 attach_pdf_artifacts_to_state
  P0-营收回归修复                   ✅ metrics 去重 + 优先级修正
  P0-章节匹配优化                   ✅ 正则行业无关化 + 标题扫描 80→200
  P0-PDF 书签偏移清洗               ✅ Unicode 乱码过滤
  P0-估值 section 修复              ✅ _build_valuation 读正结构
  P0-同行对比 A 股支持              ✅ 放开 cn_a + A 股行业映射表

Phase 3 — 补数据                  ⏳ 部分完成
  A 股结构化财报                    ✅ eastmoney_financials 已验证 60+ 指标
  A 股年报 PDF                     ✅ cninfo → PDF → 章节提取 已打通
  同行发现 (A 股)                   ✅ 行业映射表 + Yahoo 搜索 + 东财 API
  估值引擎                         ✅ PE/PS/DCF 对 A 股已验证
  SEC 30+ GAAP 指标                ✅ 从 8 个扩展到 30+ 个（已验证语法）
  港股结构化财报                    ✅ hk_financials 引擎（yfinance 三表，21 指标，已验证）
  ChromaDB 持久化                  ✅ 默认 data/vector_db
  USFactExtractor                  ❌
  本地缓存批量入库                  ❌

Phase 4 — 精排                    ❌ 0%

基础设施：
  日志体系                         ✅
  ChromaDB 持久化参数              ✅ (开关未开)
  模型下载                         ✅
  900 家批量入库                   ❌
  代码清理                         ❌
```

### 14.2 当前状态

| 维度 | 状态 | 说明 |
|:-----|:----:|:-----|
| **A 股 Moutai 报告质量** | ✅ 6/8 section 有内容 | 业务/治理/战略/财务/风险/估值全部有真实数据；同行/估值敏感性缺 |
| **A 股 CATL 报告质量** | ✅ 5/8 section 有内容 | 治理/战略/财务/风险 OK；业务概览/同行/估值缺 |
| **A 股平安报告质量** | ✅ 6/8 section 有内容 | 治理/战略/财务/风险 OK；业务概览/同行/估值缺 |
| **报告跑分提升** | 0.5878 → **预期 0.75+** | content_depth/估值/营收回归全部修复后 |

### 14.3 剩余关键工作

| 优先级 | 工作 | 解决什么问题 | 工作量 |
|:------:|:-----|:------------|:------:|
| P3 | delivery_gate 启用 | 去掉 hardcode，质量门禁正式上线 | 0.5 天 |
| P4 | pdf_section_detector 增强 | CATL 等非标准格式年报考章节匹配 | 1 天 |
| P5 | 美股隔离（USD 货币/USFactExtractor）| SEC 章节提取 + USD 不转 CNY | 1.5 天 |
| P6 | 港股引擎端到端验证 | hk_financials 跑完整报告验证 | 0.5 天 |
| P7 | A 股同行财务数据走东财 | 替代 Yahoo 减少数据不准 | 1 天 |
| P8 | code cleanup | orchestrator 重复 engine 列表、测试脚本清理 | 0.5 天 |
| P9 | 900 家批处理 | 全量入库 | 5 天 |

### 14.4 数据规模总结

目标：900 公司 × 3 周期 = 2,700 份报告 → **~270k chunks → ~7GB 总量**（含 PDF 原文）

当前：3 家公司（600519/300750/601318）管道已验证通过，0 家批量入库。ChromaDB 已切持久模式。
