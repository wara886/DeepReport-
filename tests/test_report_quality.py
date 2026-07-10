import json

from src.evaluation.report_quality import _check_delivery_policy, evaluate_report_quality, write_quality_outputs


def test_quality_evaluator_blocks_cross_report_symbol_pollution(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# GOOGL FY2025 公司研报

## 执行摘要
Alphabet 保持搜索与云业务增长，但这里错误混入了 0700.HK。

## 业务概览
Alphabet Inc. (GOOGL) 的核心业务覆盖搜索、广告、云和 Other Bets。

## 风险评估
风险提示完整。

## 投资结论
基于估值与风险约束，维持中性。
""",
    )
    reports = run_dir / "company" / "reports"
    (reports / "report.html").write_text("<html><body><h1>Alphabet Inc. (GOOGL)</h1><p>Unexpected ticker 0700.HK leaked.</p></body></html>", encoding="utf-8")

    report = evaluate_report_quality(run_dir)

    assert any(issue["category"] == "cross_report_symbol_pollution" for issue in report["issues"])


def test_quality_evaluator_blocks_html_table_markdown_residue(tmp_path):
    run_dir = _write_run(tmp_path, report_md="# Test\n\n## 执行摘要\n完整。\n## 风险评估\n完整。\n## 投资结论\n完整。")
    reports = run_dir / "company" / "reports"
    (reports / "report.html").write_text("<html><body>| 公司 | 收入增速 |\n| --- | --- |\n| AMD | 10% |</body></html>", encoding="utf-8")

    report = evaluate_report_quality(run_dir)

    assert any(issue["category"] == "html_table_integrity" for issue in report["issues"])


def test_quality_evaluator_blocks_escaped_html_table_markup(tmp_path):
    run_dir = _write_run(tmp_path, report_md="# Test\n\n## 执行摘要\n完整。\n## 风险评估\n完整。\n## 投资结论\n完整。")
    reports = run_dir / "company" / "reports"
    (reports / "report.html").write_text(
        "<html><body>&lt;table class='report-table'&gt;&lt;thead&gt;&lt;tr&gt;&lt;th&gt;指标&lt;/th&gt;&lt;/tr&gt;&lt;/thead&gt;&lt;/table&gt;</body></html>",
        encoding="utf-8",
    )

    report = evaluate_report_quality(run_dir)

    assert any(
        issue["category"] == "html_table_integrity" and "escaped table markup" in issue["message"]
        for issue in report["issues"]
    )


def test_quality_evaluator_blocks_placeholder_and_mojibake_leakage(tmp_path):
    run_dir = _write_run(tmp_path, report_md="# Test\n\n## 执行摘要\n完整。\n## 风险评估\n完整。\n## 投资结论\n完整。")
    reports = run_dir / "company" / "reports"
    (reports / "report.html").write_text("<html><body><p>TODO: 正文应使用中文归纳</p><style>.x{content:'璇佹嵁';}</style></body></html>", encoding="utf-8")

    report = evaluate_report_quality(run_dir)
    categories = {issue["category"] for issue in report["issues"]}

    assert "developer_placeholder" in categories
    assert "mojibake_policy" in categories


def test_quality_evaluator_reads_mirrored_reports_user_path_and_sidecars(tmp_path):
    run_id = "20260604_134641_600519.ss_2026q1_collaborative"
    outputs = tmp_path / "data" / "outputs_user" / "runs" / run_id / "outputs"
    reports = tmp_path / "data" / "reports_user" / "runs" / run_id / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (outputs / "run_summary.json").write_text(
        json.dumps({"symbol": "600519.SS", "period": "2026Q1", "title": "璐㈠姟鐮旂┒"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (outputs / "charts.json").write_text(
        json.dumps([{"chart_id": "c1", "title": "璐㈠姟瑙勬ā"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (outputs / "citations.json").write_text(
        json.dumps([{"evidence_id": "ev1", "title": "璇佹嵁"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (reports / "report.md").write_text("# 璐㈠姟鐮旂┒\n\n## 鎵ц鎽樿\n正文", encoding="utf-8")
    (reports / "report.html").write_text("<html><body>璐㈠姟鐮旂┒</body></html>", encoding="utf-8")

    report = evaluate_report_quality(outputs)
    categories = {issue["category"] for issue in report["issues"]}

    assert report["reports_dir"].endswith("reports")
    assert "mojibake_policy" in categories


def test_quality_evaluator_blocks_business_overview_wrong_section_and_official_contradiction(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# 600519 FY2025 公司研报

## 业务概览
财务费用变动原因说明主要来自利息收入变动。尚未获得可直接支持分析的官方章节摘要。

## 风险评估
风险提示完整。

## 投资结论
基于估值与风险约束，维持中性。
""",
    )
    outputs = run_dir / "company" / "outputs"
    (outputs / "pdf_extraction_audit.json").write_text(json.dumps({"page_count": 120, "extracted_page_count": 40}, ensure_ascii=False), encoding="utf-8")
    (outputs / "pdf_section_summaries.json").write_text(
        json.dumps([{"section_type": "business_overview", "summary_zh": "主营业务包括高端白酒产品。", "usable_for_generation": True}], ensure_ascii=False),
        encoding="utf-8",
    )

    report = evaluate_report_quality(run_dir)
    messages = "\n".join(issue["message"] for issue in report["issues"])

    assert "business_overview appears to contain financial-note variance text" in messages
    assert "official PDF summary exists" in messages


def test_quality_evaluator_blocks_eastmoney_as_official_source(tmp_path):
    run_dir = _write_run(tmp_path, report_md="# Test\n\n## 执行摘要\n完整。\n## 风险评估\n完整。\n## 投资结论\n完整。")
    outputs = run_dir / "company" / "outputs"
    (outputs / "official_evidence_manifest.json").write_text(
        json.dumps({"sources": [{"name": "Eastmoney", "role": "official primary"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = evaluate_report_quality(run_dir)

    assert any(issue["category"] == "official_source_distribution" for issue in report["issues"])


def test_quality_evaluator_passes_complete_company_report(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2025Q4 公司研报

## 执行摘要
AMD 数据中心、客户端、游戏和嵌入式业务共同构成主营业务，本文基于 SEC 与行情来源形成中性投资结论。报告期内收入、利润、现金流和资产负债结构均围绕 2025Q4 口径展开，核心判断是公司仍具备产品组合优化和数据中心需求拉动的经营韧性，但估值已经反映较高增长预期。正式结论采用审慎表述：认可业务弹性，同时要求持续跟踪毛利率、库存和资本开支变化。

## 业务概览
公司产品覆盖 CPU、GPU、数据中心加速卡和嵌入式芯片，收入来源横跨数据中心、客户端、游戏和嵌入式业务。业务画像重点在于高性能计算产品和企业级客户需求，数据中心业务对整体收入增速和毛利率影响更大。客户端与游戏业务受消费电子周期影响较明显，嵌入式业务则提供相对稳定的工业和边缘计算需求。整体来看，公司商业模式依赖产品迭代、渠道覆盖、供应链执行和生态合作，长期竞争力来自架构迭代、软件生态和客户认证周期。

## 财务分析
收入和利润以亿美元展示，现金流和资产负债表口径与 2025Q4 对齐，毛利率为 50%。利润表关注收入增速、毛利率和费用率变化，资产负债表关注现金、存货和股东权益结构，现金流量表关注经营现金流能否支撑研发投入和资本开支。若经营现金流持续高于净利润，盈利质量更稳健；若存货增加快于收入增长，则需要警惕需求放缓或产品迭代造成的减值压力。综合三表看，公司仍处于增长投入期，财务质量需要结合收入结构和现金转换率判断，并进一步观察研发投入效率、应收账款周转、自由现金流稳定性和资产周转效率，避免只看利润忽略现金。

## 同行对比
同行比较以 NVIDIA、Intel、Broadcom 等半导体公司为参考，但不同公司在 GPU、CPU、网络芯片和企业软件暴露度上存在差异。对 AMD 而言，最重要的可比维度包括收入增速、毛利率、研发投入强度、数据中心业务占比和库存周转。若公司毛利率低于高端 GPU 龙头，但收入增速和现金流改善更快，则估值应体现成长弹性与竞争压力并存。同行对比不能简单给出同一倍数结论，必须说明业务结构和利润率差异。

## 估值观察
估值使用 P/E 约为 20x 和 P/B 约为 5x，敏感性分析覆盖收入增速、毛利率和费用率情景。当前估值判断重点不是单一倍数高低，而是增长假设能否被收入结构、毛利率改善和现金流质量支撑。如果数据中心业务继续扩大且费用率保持稳定，估值中枢有支撑；如果竞争加剧导致毛利率下行，估值溢价会收缩。DCF 输入仍需完整预测和折现率假设，因此本节只输出区间化观察，不给出确定性目标价，并把估值弹性主要绑定到收入增速、毛利率和现金流转换率。

## 风险评估
风险提示包括行业竞争、AI GPU 供给、库存和宏观需求风险。第一，AI 芯片和服务器 CPU 市场竞争激烈，竞争对手产品迭代可能压缩价格和毛利率。第二，供应链和先进制程产能如果出现约束，可能影响交付节奏和收入确认。第三，客户端与游戏需求受宏观消费周期影响，弱需求会放大库存和渠道折扣风险。第四，估值较依赖长期增长假设，若收入增速或现金流低于预期，市场可能重新定价。第五，出口管制、客户集中度和研发投入回报不确定性也会影响长期盈利弹性。

## 投资结论
维持中性观察评级，投资结论是估值与增长预期大体匹配。上行触发因素包括数据中心收入持续超预期、毛利率改善、经营现金流增强以及库存周转稳定。下行触发因素包括竞争导致价格压力、客户端需求恢复不及预期、资本开支拖累自由现金流，以及估值倍数回落。综合来看，公司经营质量具备韧性，但正式投资判断仍应以后续官方财报、现金流趋势和估值输入复核为前提。基于当前证据，报告更适合支持审慎跟踪和复核，而不是直接形成激进买入结论。

## 合规披露
资料来源：SEC EDGAR、Yahoo Finance。本文仅供参考，不构成投资建议；不存在利益冲突，保持独立性披露。
""",
    )

    report = evaluate_report_quality(run_dir)
    paths = write_quality_outputs(run_dir, report)

    assert report["objective_pass"] is True
    assert report["total_score"] >= 0.82
    assert report["issue_counts"]["fatal"] == 0
    assert (run_dir / "company" / "outputs" / "quality_report.json").exists()
    assert paths["quality_issues"].endswith("quality_issues.jsonl")


def test_quality_evaluator_detects_empty_sections_scientific_notation_and_missing_valuation(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# 600519 2025Q4 公司研报

## 执行摘要
暂无可验证结论。

## 财务分析
营业收入为 1.23e+10，缺少单位。

## 风险提示
暂无结论。
""",
        tables=[{"statement": "income_statement", "metric_name": "revenue", "value": 1.0}],
        charts=[],
        claims=[{"claim_id": "cl_1", "claim_text": "收入增长"}],
        citations=[],
    )

    report = evaluate_report_quality(run_dir)

    assert report["objective_pass"] is False
    messages = "\n".join(issue["message"] for issue in report["issues"])
    assert "scientific notation" in messages
    assert "missing balance summary" in messages
    assert "valuation_or_reason" in messages
    assert report["issue_counts"]["fatal"] >= 1


def test_quality_policy_blocks_ah_formal_delivery_when_official_evidence_is_incomplete():
    issues = []
    _check_delivery_policy(
        {
            "summary": {"symbol": "0700.HK", "entity_resolution": {"resolved_symbol": "0700.HK", "confidence": 0.9}},
            "search_meta": {},
            "report_md": "risk valuation source gap",
            "report_html": "",
            "evidence_coverage": {
                "degrade_required": True,
                "missing_requirements": ["period_matched_official_filing", "cash_flow_statement"],
            },
        },
        issues,
    )

    assert any(issue["category"] == "official_evidence" and issue["severity"] == "blocker" for issue in issues)


def test_quality_evaluator_reads_nested_statement_rows_and_cashflow_gap(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2026Q1 公司研报

## 执行摘要
收入和资产已披露。[sec_1]

## 业务概览
主营业务覆盖产品和业务画像。

## 三表摘要
利润表摘要显示收入；资产负债表摘要显示资产；现金流量表缺口：当前标准化表格尚未取得经营现金流或自由现金流字段。

## 同行对比
NVIDIA、Intel、Broadcom peer comparison。

## 估值观察
估值不可用原因：缺少市值或现金流。

## 估值敏感性
敏感性关注收入和毛利率。

## 风险评估
风险提示。

## 投资结论
中性评级，不构成投资建议。

## 合规披露
资料来源：SEC EDGAR。本文仅供参考，不构成投资建议；不存在利益冲突，保持独立性披露。
""",
        tables=[
            {
                "table_type": "income_statement",
                "rows": [
                    {"statement": "income_statement", "line_item": "revenue"},
                    {"statement": "balance_sheet", "line_item": "total_assets"},
                ],
            }
        ],
        claims=[
            {
                "claim_id": "cl_1",
                "section_name": "financial_statements",
                "claim_text": "AMD 2026Q1 利润表摘要、资产负债表摘要和现金流量表缺口。",
                "evidence_ids": ["ev_1"],
            }
        ],
    )

    report = evaluate_report_quality(run_dir)

    assert report["required_checks"]["details"]["has_three_table_summary"] is True


def test_quality_evaluator_fails_when_tables_exist_but_body_omits_three_statement_summary(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2026Q1 公司研报

## 执行摘要
核心观点完整。
## 业务概览
主营业务覆盖 CPU、GPU 和数据中心。
## 三表摘要
本节只讨论整体财务表现，没有拆开三张报表。
## 同行对比
相对 NVIDIA、Intel、Broadcom，AMD 存在竞争压力。
## 估值观察
估值不可用原因：缺少市值。
## 估值敏感性
收入增速变化会影响利润。
## 风险评估
风险提示充分。
## 投资结论
基于估值和风险，维持中性观察。
""",
    )

    report = evaluate_report_quality(run_dir)

    assert report["required_checks"]["details"]["has_three_table_summary"] is False


def test_quality_evaluator_blocks_framework_only_sections_and_weak_conclusion(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2026Q1 公司研报

## 执行摘要
核心观点完整。
## 业务概览
主营业务覆盖 CPU、GPU 和数据中心。
## 三表摘要
利润表显示收入，资产负债表显示总资产，现金流量表显示经营现金流。
## 同行对比
同行对比框架待补，缺少可量化同行指标。
## 估值观察
估值分析待补。
## 估值敏感性
敏感性分析框架待补。
## 风险评估
风险提示充分。
## 投资结论
维持观察。
""",
    )

    report = evaluate_report_quality(run_dir)
    messages = "\n".join(issue["message"] for issue in report["issues"])

    assert report["objective_pass"] is False
    assert "peer comparison is framework-only" in messages or "framework-only" in messages
    assert "valuation missing" in messages



def test_quality_evaluator_blocks_memory_as_fact_source(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# TEST 2025Q4 company report

## Executive Summary
[DurableMemory] says revenue improved, so the report keeps a neutral rating.
## Business
The business profile covers products and channels.
## Three Statement Summary
The income statement, balance sheet, and cash flow statement are summarized.
## Peer Comparison
Peer comparison includes a comparable-company pool and profitability conclusion.
## Valuation
P/E and P/B are explained.
## Sensitivity
Revenue growth changes would affect profit and valuation.
## Risk
Risk disclosure is complete.
## Investment Conclusion
Based on growth driver, competition pressure, and valuation constraint, keep neutral.
## Compliance
Data source: public sources. This is for reference only and is not investment advice. No conflict of interest.
""",
    )

    report = evaluate_report_quality(run_dir)
    messages = "\n".join(issue["message"] for issue in report["issues"])

    assert report["objective_pass"] is False
    assert "memory" in messages.lower()


def test_quality_evaluator_blocks_peer_compare_without_evidence_ids(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2025Q4 公司研报

## 执行摘要
核心观点完整。
## 业务概览
主营业务覆盖 CPU、GPU 和数据中心。
## 三表摘要
利润表显示收入，资产负债表显示总资产，现金流量表显示经营现金流。
## 同行对比
已识别 5 家可比公司数据，对标 NVIDIA、Intel、Broadcom，AMD 竞争压力中等。
## 估值观察
估值不可用原因：缺少市值或股本数据。
## 估值敏感性
收入增速和毛利率情景分析。
## 风险评估
风险提示充分。
## 投资结论
基于估值约束和竞争压力，维持中性评级。
""",
        claims=[
            {"claim_id": "cl_peer", "section_name": "peer_compare", "claim_text": "已识别 5 家可比公司",
             "evidence_ids": []},
            {"claim_id": "cl_1", "section_name": "financial_analysis", "claim_text": "收入利润",
             "evidence_ids": ["ev_1"]},
        ],
    )

    report = evaluate_report_quality(run_dir)
    messages = "\n".join(issue["message"] for issue in report["issues"])

    assert report["objective_pass"] is False
    assert "peer_compare claims have empty evidence_ids" in messages


def test_quality_evaluator_blocks_large_dcf_to_composite_divergence(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2025Q4 公司研报

## 执行摘要
核心观点完整。
## 业务概览
主营业务覆盖 CPU、GPU 和数据中心。
## 三表摘要
利润表显示收入，资产负债表显示总资产，现金流量表显示经营现金流。
## 同行对比
NVIDIA、Intel、Broadcom peer comparison。
## 估值观察
DCF 价值 150B，与 composite 50B 存在较大差异，但报告未解释方法分歧。
## 估值敏感性
收入增速和毛利率情景。
## 风险评估
风险提示充分。
## 投资结论
基于估值约束和竞争压力，维持中性评级。
## 合规披露
资料来源：SEC EDGAR。本文仅供参考，不构成投资建议；不存在利益冲突，保持独立性披露。
""",
    )
    outputs = run_dir / "company" / "outputs"
    (outputs / "valuation_model.json").write_text(
        json.dumps({
            "dcf_model": {"value_billion": 150.0, "assumptions": {"base_free_cash_flow_billion": 5.0}},
            "blended_equity_value_billion": 50.0,
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    report = evaluate_report_quality(run_dir)
    messages = "\n".join(issue["message"] for issue in report["issues"])

    assert any("valuation_consistency" in issue["category"] for issue in report["issues"])
    assert "DCF" in messages
    assert "composite" in messages


def test_quality_evaluator_passes_when_dcf_divergence_is_explained(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2025Q4 公司研报

## 执行摘要
核心观点完整。
## 业务概览
主营业务覆盖 CPU、GPU 和数据中心。
## 三表摘要
利润表显示收入，资产负债表显示总资产，现金流量表显示经营现金流。
## 同行对比
NVIDIA、Intel、Broadcom peer comparison。
## 估值观察
DCF 与 composite 存在估值方法差异，由于 FCF 增长假设不同导致两种估值方法分歧，估值区间 50-150B。
## 估值敏感性
收入增速和毛利率情景。
## 风险评估
风险提示充分。
## 投资结论
基于估值约束和竞争压力，维持中性评级。
## 合规披露
资料来源：SEC EDGAR。本文仅供参考，不构成投资建议；不存在利益冲突，保持独立性披露。
""",
    )
    outputs = run_dir / "company" / "outputs"
    (outputs / "valuation_model.json").write_text(
        json.dumps({
            "dcf_model": {"value_billion": 150.0, "assumptions": {"base_free_cash_flow_billion": 5.0}},
            "blended_equity_value_billion": 50.0,
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    report = evaluate_report_quality(run_dir)
    val_issues = [i for i in report["issues"] if i["category"] == "valuation_consistency"]

    assert val_issues
    assert val_issues[0]["severity"] == "warning"


def test_quality_evaluator_blocks_only_local_sources_without_gap_explanation(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# TEST 2025Q4 company report

## Executive Summary
Based on growth driver, competition pressure, and valuation constraint, keep neutral.
## Business
The business profile covers products and channels.
## Three Statement Summary
The income statement, balance sheet, and cash flow statement are summarized.
## Peer Comparison
Peer comparison includes a comparable-company pool and profitability conclusion.
## Valuation
P/E and P/B are explained.
## Sensitivity
Revenue growth changes would affect profit and valuation.
## Risk
Risk disclosure is complete.
## Investment Conclusion
Based on growth driver, competition pressure, and valuation constraint, keep neutral.
## Compliance
Data source: local index. This is for reference only and is not investment advice. No conflict of interest.
""",
    )
    outputs = run_dir / "company" / "outputs"
    (outputs / "run_summary.json").write_text(
        json.dumps({"symbol": "TEST", "period": "2025Q4", "search_engines": ["local_real_data", "local_evidence"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = evaluate_report_quality(run_dir)
    messages = "\n".join(issue["message"] for issue in report["issues"])

    assert report["objective_pass"] is False
    assert any(issue["category"] == "delivery_policy" and issue["severity"] == "blocker" for issue in report["issues"])

def _write_run(
    tmp_path,
    report_md,
    tables=None,
    charts=None,
    claims=None,
    citations=None,
):
    run_dir = tmp_path / "sample_run"
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    claims = claims if claims is not None else [
        {"claim_id": "cl_1", "claim_text": "业务覆盖 CPU/GPU", "evidence_ids": ["ev_1"], "confidence": 0.9},
        {"claim_id": "cl_2", "claim_text": "估值使用 P/E", "evidence_ids": ["ev_2"], "confidence": 0.85},
    ]
    evidence = [
        {"evidence_id": "ev_1", "source_type": "sec_edgar", "trust_level": "primary", "title": "SEC filing"},
        {"evidence_id": "ev_2", "source_type": "yahoo_finance", "trust_level": "secondary", "title": "Market snapshot"},
    ]
    tables = tables if tables is not None else [
        {"statement": "income_statement", "metric_name": "revenue", "value": 100, "unit": "亿美元", "period": "2025Q4"},
        {"statement": "balance_sheet", "metric_name": "equity", "value": 80, "unit": "亿美元", "period": "2025Q4"},
        {"statement": "cash_flow_statement", "metric_name": "operating_cash_flow", "value": 20, "unit": "亿美元", "period": "2025Q4"},
    ]
    charts = charts if charts is not None else [
        {"chart_id": "c1", "title": "关键财务指标对比", "output_path": "charts/key_metrics_bar.png"},
        {"chart_id": "c2", "title": "收入利润趋势", "output_path": "charts/revenue_income.png"},
    ]
    citations = citations if citations is not None else [
        {"evidence_id": "ev_1", "claim_ids": ["cl_1"], "title": "SEC filing"},
        {"evidence_id": "ev_2", "claim_ids": ["cl_2"], "title": "Market snapshot"},
    ]
    files = {
        "run_summary.json": {"symbol": "AMD", "period": "2025Q4", "verification_passed": True},
        "claims.json": claims,
        "evidence.json": evidence,
        "citations.json": citations,
        "tables.json": tables,
        "financial_metrics.json": {"revenue": {"value": 100, "unit": "亿美元"}},
        "charts.json": charts,
        "company_profile_extracted.json": {"business": "CPU/GPU"},
        "verification_report.json": {"passed": True},
    }
    for name, payload in files.items():
        (outputs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (reports / "report.md").write_text(report_md, encoding="utf-8")
    (reports / "report.html").write_text(f"<html><body>{report_md}</body></html>", encoding="utf-8")
    return run_dir


def _write_run_with_dossiers(
    tmp_path,
    report_md,
    section_dossiers=None,
    tables=None,
    charts=None,
    claims=None,
    citations=None,
):
    """Like _write_run but also writes section_dossiers.json."""
    run_dir = _write_run(tmp_path, report_md, tables=tables, charts=charts, claims=claims, citations=citations)
    outputs = run_dir / "company" / "outputs"
    if section_dossiers:
        (outputs / "section_dossiers.json").write_text(
            json.dumps(section_dossiers, ensure_ascii=False), encoding="utf-8"
        )
    return run_dir


def test_content_depth_gate_flags_sparse_sections(tmp_path):
    """Short sections without data_gap flag -> content_depth issues."""
    run_dir = _write_run_with_dossiers(
        tmp_path,
        report_md="""# Test

## 执行摘要
短。

## 业务概览
也很短。

## 财务分析
更短。

## 同行对比
无内容。

## 估值观察
估。

## 风险评估
风险。

## 投资结论
结论。
""",
        section_dossiers={
            "executive_summary": {"section_title": "执行摘要", "min_content_level": "full", "suggested_paragraphs": []},
            "business_overview": {"section_title": "业务概览", "min_content_level": "full", "suggested_paragraphs": []},
            "financial_analysis": {"section_title": "财务分析", "min_content_level": "full", "suggested_paragraphs": []},
            "peer_compare": {"section_title": "同行对比", "min_content_level": "full", "suggested_paragraphs": []},
            "valuation": {"section_title": "估值观察", "min_content_level": "full", "suggested_paragraphs": []},
            "risks": {"section_title": "风险评估", "min_content_level": "full", "suggested_paragraphs": []},
            "conclusion": {"section_title": "投资结论", "min_content_level": "full", "suggested_paragraphs": []},
        },
    )
    report = evaluate_report_quality(run_dir)
    cd_score = report.get("scores", {}).get("content_depth", 1.0)
    assert cd_score < 1.0, f"Expected content_depth < 1.0, got {cd_score}"
    # Should have content_depth related issues
    categories = {issue["category"] for issue in report.get("issues", [])}
    assert "content_depth" in categories, f"Expected content_depth issues, got categories: {categories}"


def test_content_depth_gate_runs_without_section_dossiers(tmp_path):
    """Core section contract must still run when section_dossiers.json is absent."""
    run_dir = _write_run(
        tmp_path,
        report_md="""# Test

## 执行摘要
短。

## 业务概览
短。

## 财务分析
短。

## 同行对比
短。

## 估值观察
短。

## 风险评估
短。

## 投资结论
短。
""",
    )

    report = evaluate_report_quality(run_dir)
    assert report["objective_pass"] is False
    cd_issues = [i for i in report.get("issues", []) if i["category"] == "content_depth"]
    assert any("执行摘要 content insufficient" in i["message"] for i in cd_issues)
    assert any("投资结论 content insufficient" in i["message"] for i in cd_issues)


def test_content_depth_gate_blocks_truncated_core_section(tmp_path):
    """Half-sentence truncation in a core section blocks formal delivery."""
    long_text = "公司收入、利润、现金流和资产负债结构均已形成可追溯分析，经营质量说明较完整。" * 8
    run_dir = _write_run_with_dossiers(
        tmp_path,
        report_md=f"""# Test

## 执行摘要
{long_text}

## 业务概览
{long_text}

## 财务分析
{long_text}

## 同行对比
{long_text}

## 估值观察
本报告分别披露相对估值与

## 风险评估
{long_text}

## 投资结论
{long_text}
""",
        section_dossiers={
            "executive_summary": {"min_content_level": "full"},
            "business_overview": {"min_content_level": "full"},
            "financial_analysis": {"min_content_level": "full"},
            "peer_compare": {"min_content_level": "full"},
            "valuation": {"min_content_level": "full"},
            "risks": {"min_content_level": "full"},
            "conclusion": {"min_content_level": "full"},
        },
    )

    report = evaluate_report_quality(run_dir)
    cd_issues = [i for i in report.get("issues", []) if i["category"] == "content_depth"]
    assert report["objective_pass"] is False
    assert any("估值观察 appears truncated" in i["message"] for i in cd_issues)


def test_content_depth_allows_data_gap_sections(tmp_path):
    """Sections with data_gap mark are not penalized for being short."""
    run_dir = _write_run_with_dossiers(
        tmp_path,
        report_md="""# Test

## 执行摘要
本期公司业务发展良好，整体经营状况稳健。收入同比增长显著，毛利率保持在健康水平，净利润持续改善。经营现金流表现强劲，自由现金流充裕，为资本开支和股东回报提供坚实基础。资产负债结构保持稳健，现金及等价物充足。综合来看，公司在本报告期内各项核心指标表现符合预期，财务状况良好。

## 业务概览
短文本，但应被 data_gap 豁免，不影响评分。

## 财务分析
本期公司收入同比增长百分之二十四，达到三十五点四亿美元，其中数据中心业务占比首次超过客户端业务成为最大收入来源。毛利率提升至百分之五十二点一，同比提升一点八个百分点，主要受益于高毛利的数据中心 GPU 出货占比提升。经营现金流十二点三亿美元，自由现金流九点八亿美元，均同比改善。资产负债方面总资产八十亿美元，股东权益五十亿美元，资产负债率约百分之三十七点五。盈利质量方面 ROE 约为百分之十五，ROA 约为百分之九，均处于健康水平。整体来看公司财务表现稳健，盈利能力和现金流生成能力均在改善，费用率变化也未显著削弱利润弹性。

## 同行对比
短文本，但应被 data_gap 豁免，不影响评分。

## 估值观察
本期采用 P/E、P/B 和 DCF 三种方法对公司进行估值。P/E 约为三十倍，基于过去十二个月净利润计算。P/B 约为十倍，反映市场对公司资产质量的定价。DCF 估值为一百八十亿美元，假设加权平均资本成本为百分之十，终端增长率为百分之三。综合估值在一百五十到二百亿美元区间。当前市值与模型估值差异在合理范围内，三种方法结果相互印证。估值差异主要来源于不同方法对增长假设和风险溢价的敏感度不同，投资者应参考多种方法综合判断，并关注假设调整带来的估值区间变化。

## 风险评估
公司面临多方面的风险因素。行业竞争加剧风险：AI 芯片市场份额争夺日趋激烈，主要竞争对手持续推出新产品。毛利率波动风险：产品组合变化可能影响整体毛利率水平，高毛利产品占比下降将压缩盈利空间。资本开支压力：为保持技术竞争力，公司持续加大研发和产能投入，可能对自由现金流形成压力。估值回调风险：当前估值倍数处于历史中高水平，市场情绪变化可能引发估值回调。数据覆盖限制：本报告风险分析基于公开披露信息，部分风险因素可能未被完整覆盖，投资者应结合自身判断做出决策。

## 投资结论
综合财务质量、估值水平和风险因素，当前对公司持中性观察态度。上行因素包括数据中心业务持续增长和产品结构优化带来的盈利能力提升。下行风险包括行业竞争加剧和毛利率面临的结构性压力。适用边界说明：本报告估值模型基于公开数据和标准假设，不构成投资建议。投资者在做出决策前应参考专业投资顾问的意见，并结合自身风险偏好进行判断。本报告所有结论均基于已获取的公开数据，数据截止日期以报告标注为准。
""",
        section_dossiers={
            "executive_summary": {"section_title": "执行摘要", "min_content_level": "full"},
            "business_overview": {"section_title": "业务概览", "min_content_level": "data_gap"},
            "financial_analysis": {"section_title": "财务分析", "min_content_level": "full"},
            "peer_compare": {"section_title": "同行对比", "min_content_level": "data_gap"},
            "valuation": {"section_title": "估值观察", "min_content_level": "full"},
            "risks": {"section_title": "风险评估", "min_content_level": "full"},
            "conclusion": {"section_title": "投资结论", "min_content_level": "full"},
        },
    )
    report = evaluate_report_quality(run_dir)
    assert "scores" in report
    cd_score = report.get("scores", {}).get("content_depth", 0)
    # All 5 full sections should have sufficient Chinese characters (> threshold)
    # and 2 data_gap sections are not penalized -> score should be 5/7 ≈ 0.71
    assert cd_score >= 0.7, f"content_depth score {cd_score} should be >= 0.7 (expected 5/7)"


def test_debug_leakage_hard_fails_quality_gate(tmp_path):
    """Report containing 'metric_count' or 'cl_' fails quality gate with objective_pass=False."""
    run_dir = _write_run_with_dossiers(
        tmp_path,
        report_md="""# AMD 2025Q4 报告

## 执行摘要
核心观点完整，本报告基于 metric_count=42 和 cl_0001 进行分析。

## 业务概览
主营业务覆盖 CPU、GPU 和数据中心。

## 三表摘要
利润表显示收入，资产负债表显示总资产，现金流量表显示经营现金流。

## 同行对比
NVIDIA、Intel、Broadcom peer comparison。

## 估值观察
估值使用 P/E 约为 20x。

## 估值敏感性
收入增速和毛利率情景分析。

## 风险评估
风险提示充分。

## 投资结论
基于估值约束和竞争压力，维持中性评级。

## 合规披露
本文仅供参考，不构成投资建议。
""",
        section_dossiers={
            "executive_summary": {"section_title": "执行摘要", "min_content_level": "full"},
            "business_overview": {"section_title": "业务概览", "min_content_level": "full"},
            "financial_analysis": {"section_title": "财务分析", "min_content_level": "full"},
            "peer_compare": {"section_title": "同行对比", "min_content_level": "full"},
            "valuation": {"section_title": "估值观察", "min_content_level": "full"},
            "risks": {"section_title": "风险评估", "min_content_level": "full"},
            "conclusion": {"section_title": "投资结论", "min_content_level": "full"},
        },
    )

    report = evaluate_report_quality(run_dir)
    assert report["objective_pass"] is False, "Report with debug leakage should fail quality gate"
    cd_issues = [i for i in report.get("issues", []) if i["category"] == "content_depth"]
    assert any("metric_count" in i["message"] for i in cd_issues), (
        f"Expected metric_count issue in content_depth, got: {[i['message'] for i in cd_issues]}"
    )
    assert any("cl_" in i["message"] for i in cd_issues), (
        f"Expected cl_ issue in content_depth, got: {[i['message'] for i in cd_issues]}"
    )


def test_template_phrases_blocker_not_warning(tmp_path):
    """Template phrases now cause blocker-level issues, not warnings."""
    run_dir = _write_run_with_dossiers(
        tmp_path,
        report_md="""# AMD 2025Q4 报告

## 执行摘要
核心观点完整。

## 业务概览
公司持续深耕主营业务，巩固核心竞争力。

## 三表摘要
利润表显示收入，资产负债表显示总资产，现金流量表显示经营现金流。

## 同行对比
NVIDIA、Intel、Broadcom peer comparison。

## 估值观察
估值使用 P/E 约为 20x。

## 估值敏感性
收入增速和毛利率情景分析。

## 风险评估
风险提示充分。

## 投资结论
基于估值约束和竞争压力，维持中性评级。

## 合规披露
本文仅供参考，不构成投资建议。
""",
        section_dossiers={
            "executive_summary": {"section_title": "执行摘要", "min_content_level": "full"},
            "business_overview": {"section_title": "业务概览", "min_content_level": "full"},
            "financial_analysis": {"section_title": "财务分析", "min_content_level": "full"},
            "peer_compare": {"section_title": "同行对比", "min_content_level": "full"},
            "valuation": {"section_title": "估值观察", "min_content_level": "full"},
            "risks": {"section_title": "风险评估", "min_content_level": "full"},
            "conclusion": {"section_title": "投资结论", "min_content_level": "full"},
        },
    )

    report = evaluate_report_quality(run_dir)
    cd_issues = [i for i in report.get("issues", []) if i["category"] == "content_depth"]
    # Template phrases should be blocker severity, not warning
    tmpl_issues = [i for i in cd_issues if "持续深耕" in i["message"] or "巩固核心竞争力" in i["message"]]
    assert tmpl_issues, f"Expected template phrase issues, got: {cd_issues}"
    for issue in tmpl_issues:
        assert issue["severity"] == "blocker", (
            f"Template phrase issue should be blocker, got {issue['severity']}: {issue['message']}"
        )
