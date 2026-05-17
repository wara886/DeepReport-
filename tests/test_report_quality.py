import json

from src.evaluation.report_quality import evaluate_report_quality, write_quality_outputs


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
估值使用 P/E 和 P/B，敏感性分析覆盖收入增速、毛利率和费用率情景。

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
