import json

from src.evaluation.report_quality import _check_delivery_policy, evaluate_report_quality, write_quality_outputs


def test_quality_evaluator_passes_complete_company_report(tmp_path):
    run_dir = _write_run(
        tmp_path,
        report_md="""
# AMD 2025Q4 公司研报

## 执行摘要
AMD 数据中心、客户端、游戏和嵌入式业务共同构成主营业务，本文基于 SEC 与行情来源形成中性投资结论。

## 主营业务与业务画像
公司产品覆盖 CPU、GPU、数据中心加速卡和嵌入式芯片，并与 NVIDIA、Intel、Broadcom 做同行比较。

## 财务分析与三表摘要
收入和利润以亿美元展示，现金流和资产负债表口径与 2025Q4 对齐，毛利率为 50%。

## 估值与敏感性
估值使用 P/E 约为 20x 和 P/B 约为 5x，敏感性分析覆盖收入增速、毛利率和费用率情景。

## 投资建议
维持中性评级，投资结论是估值与增长预期大体匹配。

## 风险提示
风险提示包括行业竞争、AI GPU 供给、库存和宏观需求风险。

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
    assert "科学计数法" in messages
    assert "缺少资产负债表摘要" in messages
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
    assert "同行对比只有框架" in messages
    assert "估值缺失" in messages
    assert "投资结论缺少明确方向和理由" in messages



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
    assert "同行对比缺少证据支持" in messages


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
    citations = citations if citations is not None else [{"evidence_id": "ev_1", "claim_ids": ["cl_1"], "title": "SEC filing"}]
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
