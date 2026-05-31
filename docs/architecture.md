已按这个合并计划落地了核心 P0.8 修复，重点是把“币种安全门”和“FY 年报正文质量门”接进现有流水线，而不是只做展示层补丁。

完成内容

新增货币基础层：src/utils/money.py:14、src/market/currency_rules.py:29，不再把空币种默认成 USD。
新增 issuer override：configs/issuer_currency_overrides.yaml:1，0700.HK 报表货币 CNY、交易货币 HKD。
新增 currency_audit.json 产物：src/evaluation/financial_currency_audit.py:27，会记录 statement/trading/display currency、warnings、blockers。
修复 Tencent 链路：Yahoo 港股财务数据现在推断/标注为 CNY，不再标 USD；非美 FY 缺 official annual/HKEX/IR 时阻断确定性估值。
修复估值链路：src/features/company_valuation.py:365 开始做官方源、币种、FX 检查；跨 CNY/HKD 会走 FX 元数据，缺源/缺汇率就降级或阻断。
加强质量门禁：src/evaluation/report_quality.py:588 会拦截非美 RMB/HKD 被标 USD、估值币种不一致、raw English annual section/internal metric key 泄漏。
年报正文质量：src/agents/section_dossier_builder.py 不再把 10-K 原文长段直接塞进 business/strategy/risk dossier，改为中文摘要和风险表。
HTML 信心分不再轻易 95%：src/report/html_report_generator.py:800 对 degraded/blocked 报告降置信度。
验证

编译通过：
python -m py_compile ...
定向与相邻回归通过：
python -m pytest tests\test_currency_rules.py tests\test_money_value.py tests\test_financial_currency_audit.py tests\test_valuation_currency.py tests\test_currency_quality_gate.py tests\test_html_currency_rendering.py tests\test_section_dossier_builder.py tests\test_sec_annual_report_flow.py tests\test_report_quality.py tests\test_html_report_generator.py -q
结果：46 passed
另外，工作区里 README.md 和两个 SVG 仍是之前 README 视觉任务留下的未提交修改，我这轮没有回滚它们。下一步建议重启服务后重新生成 0700.HK FY2025 和 GOOGL FY2025，重点检查新增的 currency_audit.json、估值状态和报告里的“货币与数据质量说明”。


已编辑 21 个文件
+1,174
-226
撤销
审核

configs/issuer_currency_overrides.yaml
+8
-0

src/agents/deep_analyze_agent.py
+34
-10

src/agents/final_answer_agent.py
+65
-14

src/agents/multi_agent_orchestrator.py
+45
-28

src/agents/section_dossier_builder.py
+50
-9

src/data/financial_statement_metrics.py
+98
-46

src/evaluation/financial_currency_audit.py
+109
-0

src/evaluation/report_quality.py
+81
-43

src/features/company_valuation.py
+162
-61

src/features/financial_metric_lineage.py
+43
-9

src/market/__init__.py
+2
-0

src/market/currency_rules.py
+116
-0

src/report/deterministic_section_renderer.py
+5
-1

src/report/html_report_generator.py
+9
-5

src/utils/money.py
+147
-0

tests/test_currency_quality_gate.py
+29
-0

tests/test_currency_rules.py
+24
-0

tests/test_financial_currency_audit.py
+38
-0

tests/test_html_currency_rendering.py
+30
-0

tests/test_money_value.py
+27
-0

tests/test_valuation_currency.py
+52
-0

上面是刚才的修复，下面是你要做的接下来：
继续修复 FinSight / DeepReport++ 的港股/A股/非美股报告质量问题。本轮只做 P0.8.1 + P3.5 + P1.5，不要修前端按钮，不要做大规模架构重写。

你有明确用户授权，可以修改本项目中的相关 Python、HTML/JS 模板、测试文件和配置文件。请先审计，再改代码，再跑测试。

当前问题来自 0700.HK Tencent FY2025 报告：

已经部分修好的地方：
1. 三表金额已经从错误的 USD 改成 CNY。
2. 报告新增了：
   - 财务报表货币：CNY
   - 交易货币：HKD
   - 报告展示货币：CNY
   - degraded_due_to_unverified_financial_currency
   - official_source_missing_for_non_us_annual

但仍有严重未闭环问题：

一、执行摘要仍不显示货币单位
当前写法：
0700.HK FY2025 核心摘要：收入约 751.77B，净利润约 218.30B，净利率约 29.0%

问题：
- 751.77B 没写 CNY/HKD/USD。
- 港股刚修过货币问题，摘要必须明确写“人民币”。
- 应显示为：
  收入约 7,517.66 亿元人民币，净利润约 2,182.97 亿元人民币
  或 751.77 billion CNY / 218.30 billion CNY。

二、估值仍有跨货币风险
当前写法：
公开行情市值（单位：十亿美元）和三表数据为输入，P/E 约为 17.7x、P/S 约为 5.1x。

问题：
- 腾讯交易货币是 HKD，财务报表货币是 CNY。
- 不能直接用 CNY 利润和 HKD 市值算 P/E/P/S。
- 如果没有 FX rate 和 fx_date，估值倍数也不能输出确定性结果。
- 如果要输出 P/E/P/S，必须先给出：
  财务数据 CNY
  市值 HKD
  CNY/HKD 或 HKD/CNY 汇率
  换算后市值
  换算后 P/E、P/S
- 没有 FX 时估值状态应为 blocked/degraded，不能给“P/E 17.7x、P/S 5.1x”这种貌似确定的倍数。

三、官方来源仍缺失
当前 references 只有：
- Yahoo Finance financial data
- Yahoo Finance market snapshot
- WSJ financials
- Yahoo Finance financials

问题：
- 对港股年度报告，Yahoo/WSJ 只能作为降级来源。
- 应优先检索 Tencent IR、HKEX announcement、annual results、annual report。
- 如果没有官方来源，报告标题或 warning 应明确降级为“第三方结构化数据观察报告”，不能呈现为完整年度研报。
- official_source_missing_for_non_us_annual 应影响 confidence 和 report title/subtitle。

四、内部字段仍泄露
当前报告仍出现：
- adjusted_net_income
- non_recurring_gain
- equity
- revenue_growth_pct9.1
- gross_margin_pct56.45
- net_margin_pct30.61
- roe_pct20.52

要求：
用户报告里不允许出现这些内部 key。
必须映射为：
- 调整后净利润
- 非经常性收益
- 股东权益
- 收入增速
- 毛利率
- 净利率
- ROE

同行对比必须渲染为表格，不能写成 revenue_growth_pct9.1 这种拼接文本。

五、文案自相矛盾
当前写法：
“关键经营指标已通过公开财务数据交叉验证。”
但同时又说：
“核心三表来源为结构化季度三表数据，需等待一手公告复核。”

问题：
- 没有官方来源时，不能说“已交叉验证”。
- FY2025 年报不能写“季度三表数据”。
- 应改成：
  “当前三表数据主要来自第三方结构化数据，尚未完成官方年报或港交所公告交叉验证。”

六、中文报告 UI 仍有英文
当前仍有：
- Multi-Agent Deep Research Report
- Report Confidence
- Based on data coverage and citation analysis
- Data Gap Notice
- Table of Contents
- Interactive Charts
- Double-click a chart to save as PNG
- References

中文报告必须统一中文：
- 多智能体深度研究报告
- 报告置信度
- 基于数据覆盖与引用分析
- 数据缺口提示
- 目录
- 交互图表
- 双击图表可保存为 PNG
- 参考来源

七、业务/战略/治理仍空
这部分可以继续 data_gap，但要更专业：
- 业务概览不能只写“暂无充足证据支持详细分析。。”
- 应写清楚：
  “本轮未获取到腾讯官方年报、年度业绩公告或港交所公告中的业务分部说明，因此不展开业务结构分析。”
- 治理章节应说明：
  “未检索到年报治理章节、董事会构成或股东结构来源。”
- 战略章节应说明：
  “未检索到管理层讨论、业务展望或年度业绩公告文本。”
- 不要出现双句号“。。”。

==================================================
一、先诊断当前链路
==================================================

请先只读检查最新 0700.HK FY2025 run 的 artifacts：
- report.json
- report.md
- report.html
- currency_audit.json
- valuation_model.json
- financial_metrics.json
- market_snapshot.json
- section_dossiers.json
- company_profile_pack.json
- references/evidence records

输出诊断：
1. revenue/net_income 的 currency 从哪里来？
2. market_cap 的 currency 是 HKD、USD 还是 unknown？
3. valuation_model 是否混用了 CNY/HKD/USD？
4. 为什么估值观察仍写“单位：十亿美元”？
5. official source resolver 是否尝试查 Tencent IR/HKEX？
6. 为什么 references 没有 Tencent IR/HKEX？
7. 内部字段是 final_answer_agent 泄露，还是 deterministic renderer 泄露？
8. 英文 UI 是 html_report_generator 写死，还是 locale 未传入？

诊断后再改代码。

==================================================
二、修执行摘要货币显示
==================================================

修改 final_answer_agent.py / deterministic renderer / money formatter：

要求：
1. 所有金额摘要必须带货币。
2. 对 CNY 大额金额，中文报告优先显示：
   - 7517.66 亿元人民币
   - 2182.97 亿元人民币
   - 1.90 万亿元人民币
3. 不允许只显示：
   - 751.77B
   - 218.30B
4. 英文单位可以保留在括号里，但中文主文本必须明确：
   - 人民币
   - 港元
   - 美元
5. 执行摘要中如果 valuation_status degraded/blocked，不输出目标价或确定性估值结论。

新增测试：
- test_executive_summary_displays_cny_unit_for_tencent
- test_executive_summary_does_not_emit_b_without_currency
- test_degraded_currency_report_does_not_emit_target_price

==================================================
三、修估值货币一致性
==================================================

修改 valuation builder / valuation renderer：

要求：
1. 估值输入必须包含：
   - revenue_currency
   - earnings_currency
   - fcf_currency
   - market_cap_currency
   - trading_currency
   - statement_currency
   - valuation_currency
   - fx_rate
   - fx_date
2. 如果 revenue/earnings/FCF 是 CNY，market_cap 是 HKD：
   - 有 FX rate 才能输出 P/E、P/S、DCF。
   - 没有 FX rate 时：
     valuation_status="blocked_due_to_missing_fx_rate"
     不输出 P/E/P/S/DCF 的确定性数值。
3. 如果输出估值倍数，必须渲染一张货币换算表：
   项目 | 原始货币 | 原始数值 | 换算货币 | 汇率 | 换算后数值 | 来源
4. 对港股，不允许写“市值单位：十亿美元”，除非 market_cap 已明确转换为 USD 且有 fx_rate。
5. 如果使用 HKD 市值和 CNY 财务数据，不转换则 quality hard fail。

新增测试：
- test_valuation_blocks_pe_ps_without_fx_for_hk_stock
- test_valuation_renders_fx_table_when_cross_currency
- test_no_usd_market_cap_label_for_hk_stock_without_usd_conversion
- test_tencent_valuation_status_blocked_without_fx

==================================================
四、修港股官方来源优先级
==================================================

新增或修改 official source resolver：

目标：
对 0700.HK FY2025，优先尝试：
1. Tencent IR annual results / annual report
2. HKEX announcement / annual results
3. Company annual report PDF/HTML
4. 交易所公告

实现要求：
1. 新增 source priority：
   official_annual_report > HKEX announcement > company_ir > exchange_filing > financial_media > market_data
2. 如果 symbol 是 .HK 或 market=HK：
   - 年度报告必须先跑 official source resolver。
   - 找不到官方来源时，写入 artifacts/official_source_audit.json。
3. official_source_audit.json 字段：
   {
     "symbol": "0700.HK",
     "period": "FY2025",
     "attempted_sources": [...],
     "found_official_source": false,
     "primary_source_type": "market_data",
     "degrade_reason": "official_source_missing_for_non_us_annual"
   }
4. 找到官方来源后：
   - financial_metrics 优先使用官方来源。
   - Yahoo/WSJ 只能作为辅助校验。
5. 找不到官方来源：
   - delivery_status 降级。
   - report subtitle 改为“第三方结构化数据观察报告（缺少官方年报校验）”。
   - confidence 不超过 70。
   - 估值结论只能是观察，不可输出强结论。

新增测试：
- test_hk_annual_report_runs_official_source_resolver
- test_official_source_missing_degrades_report_title
- test_confidence_capped_without_hk_official_source
- test_yahoo_only_hk_annual_cannot_be_full_report

==================================================
五、修内部字段中文映射
==================================================

修改 final_answer_agent.py / deterministic_section_renderer.py / html_report_generator.py：

字段映射：
- adjusted_net_income -> 调整后净利润
- non_recurring_gain -> 非经常性收益
- equity -> 股东权益
- revenue_growth_pct -> 收入增速
- gross_margin_pct -> 毛利率
- net_margin_pct -> 净利率
- roe_pct -> ROE
- pe_ttm -> 市盈率
- ps_ttm -> 市销率
- market_cap -> 市值

要求：
1. 用户报告正文和表格不出现内部 key。
2. 同行对比必须表格化：
   公司 | 收入增速 | 毛利率 | 净利率 | ROE | 市盈率 | 市销率 | 说明
3. 三表摘要也不能出现 adjusted_net_income / non_recurring_gain / equity。
4. 如果某指标不是标准三表项目，可以放入“补充调整项”表，并中文化。

新增测试：
- test_no_internal_metric_keys_in_user_report
- test_peer_metrics_rendered_as_chinese_table
- test_income_statement_adjusted_items_are_chinese

==================================================
六、修文案冲突和 data gap 文案
==================================================

要求：
1. 没有官方来源时，不允许写：
   “关键经营指标已通过公开财务数据交叉验证”
2. FY2025 年报不允许写：
   “结构化季度三表数据”
3. 改为：
   “当前三表数据主要来自第三方结构化数据，尚未完成官方年报或港交所公告交叉验证。”
4. 业务/治理/战略缺口文案要具体说明缺少什么来源。
5. 删除双句号“。。”。

新增测试：
- test_no_cross_verified_claim_without_official_source
- test_annual_report_does_not_say_quarterly_tables
- test_data_gap_copy_mentions_missing_official_sources
- test_no_double_period_punctuation

==================================================
七、中文 UI 本地化
==================================================

修改 html_report_generator.py：

如果 report_language == zh-CN 或 title/body 为中文：
必须使用中文 UI label：
- Multi-Agent Deep Research Report -> 多智能体深度研究报告
- Report Confidence -> 报告置信度
- Based on data coverage and citation analysis -> 基于数据覆盖与引用分析
- Data Gap Notice -> 数据缺口提示
- Table of Contents -> 目录
- Interactive Charts -> 交互图表
- Double-click a chart to save as PNG -> 双击图表可保存为 PNG
- References -> 参考来源
- FinSight Multi-Agent Financial Research System -> FinSight 多智能体金融研报系统

新增测试：
- test_zh_report_ui_labels_are_chinese
- test_no_english_ui_labels_in_zh_report

==================================================
八、质量门禁
==================================================

修改 report_quality.py，新增/加强 hard blockers：

1. missing_currency_in_executive_summary
   摘要出现 “751.77B” 但附近无 CNY/HKD/USD/人民币/港元/美元。

2. valuation_without_fx_for_cross_currency
   港股财务货币和交易货币不同，但估值倍数/DCF没有 FX。

3. hk_annual_without_official_source_not_degraded
   港股年度报告无官方来源但没有降级。

4. internal_metric_key_leak
   adjusted_net_income、revenue_growth_pct 等出现在用户报告。

5. contradictory_source_validation
   无官方来源却写“已交叉验证”。

6. zh_report_english_ui_labels
   中文报告中出现英文 UI label。

7. double_period_punctuation
   出现“。。”。

新增测试：
- test_quality_blocks_missing_currency_in_summary
- test_quality_blocks_cross_currency_valuation_without_fx
- test_quality_blocks_internal_metric_keys
- test_quality_blocks_contradictory_cross_validation
- test_quality_blocks_english_ui_in_zh_report

==================================================
九、测试和编译
==================================================

运行：
python -m py_compile src\core\money.py
python -m py_compile src\market\currency_rules.py
python -m py_compile src\agents\final_answer_agent.py
python -m py_compile src\report\html_report_generator.py
python -m py_compile src\report\deterministic_section_renderer.py
python -m py_compile src\evaluation\report_quality.py

如果某些文件不存在，请先搜索对应模块名，不要盲目创建重复模块。

运行测试：
python -m pytest tests\test_money_value.py tests\test_currency_rules.py tests\test_financial_currency_audit.py tests\test_valuation_currency.py tests\test_final_answer_agent.py tests\test_html_report_generator.py tests\test_report_quality.py -q

如果测试文件不存在，请创建最小覆盖测试。

==================================================
十、完成后总结
==================================================

请最终总结：
1. 为什么上一版腾讯报告还不算修好。
2. 执行摘要货币如何修复。
3. 估值跨 CNY/HKD 如何阻断或换算。
4. 港股官方来源优先级如何处理。
5. 内部字段如何清理。
6. 中文 UI 如何统一。
7. 重新生成 0700.HK FY2025 后的验收标准。

验收标准：
重新生成“生成腾讯2025年报”后必须满足：
- 执行摘要明确显示“亿元人民币”或 CNY。
- 不出现 “751.77B” 这种无货币缩写。
- 三表显示 CNY。
- 市值显示 HKD，或有明确 FX 转换。
- 没有 FX 时不输出 P/E/P/S 确定性倍数。
- 没有官方来源时标题/提示明确降级，confidence <= 70。
- 不出现 adjusted_net_income、revenue_growth_pct 等内部 key。
- 不出现“已交叉验证”这种与来源状态矛盾的表述。
- 中文报告 UI 全部中文。
