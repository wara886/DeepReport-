from src.agents.section_dossier_builder import sanitize_peer_rows_for_report
from src.evaluation.report_quality import evaluate_report_quality


def test_peer_row_sanitizer_removes_unapproved_row_metrics():
    analysis = {
        "symbol": "600519.SS",
        "peer_analysis": {
            "approved_peer_symbols": ["600519.SS"],
            "peer_rows": [
                {"symbol": "600519.SS", "company_name": "Kweichow Moutai", "revenue_growth_pct": 10.0},
                {"symbol": "0700.HK", "company_name": "Tencent", "revenue_growth_pct": 6.5, "gross_margin_pct": 90.51, "net_margin_pct": 48.05, "roe_pct": 31.2},
            ],
        },
    }

    rows = sanitize_peer_rows_for_report(analysis, {}, target_symbol="600519.SS")
    payload = str(rows)

    assert len(rows) == 1
    assert "0700.HK" not in payload
    assert "90.51" not in payload
    assert "48.05" not in payload
    assert "31.2" not in payload


def test_peer_sanitizer_filters_cross_industry_direct_peers():
    analysis = {
        "symbol": "TSLA",
        "company_profile": {
            "company_name": "Tesla, Inc.",
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
        },
        "peer_analysis": {
            "approved_peer_symbols": ["AAPL", "AMZN", "GOOG", "GM", "LCID"],
            "peer_rows": [
                {"symbol": "AAPL", "company_name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "revenue": 1},
                {"symbol": "AMZN", "company_name": "Amazon.com, Inc.", "sector": "Consumer Cyclical", "industry": "Internet Retail", "revenue": 2},
                {"symbol": "GOOG", "company_name": "Alphabet Inc.", "sector": "Communication Services", "industry": "Internet Content", "revenue": 3},
                {"symbol": "GM", "company_name": "General Motors", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers", "revenue": 4},
                {"symbol": "LCID", "company_name": "Lucid Group", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers", "revenue": 5},
            ],
        },
    }

    rows = sanitize_peer_rows_for_report(analysis, {}, target_symbol="TSLA")
    payload = str(rows)

    assert "GM" in payload
    assert "LCID" in payload
    assert "AAPL" not in payload
    assert "AMZN" not in payload
    assert "GOOG" not in payload
    assert "1" not in payload
    assert "2" not in payload
    assert "3" not in payload


def test_orphan_peer_metric_residue_blocks_quality(tmp_path):
    run_dir = _write_run(
        tmp_path,
        """
# 600519 FY2025 公司研报

## 执行摘要
核心观点完整。
## 业务概览
公司主营白酒产品与渠道。
## 三表摘要
利润表显示收入，资产负债表显示资产，现金流量表显示经营现金流。
## 同行对比
收入增速6.5；毛利率90.51；净利率48.05；ROE31.2。
## 估值观察
估值不可用原因：缺少完整市场输入。
## 估值敏感性
敏感性输入不足。
## 风险评估
风险提示充分。
## 投资结论
基于估值约束与风险，维持中性。
""",
    )

    report = evaluate_report_quality(run_dir)

    assert any(issue["category"] == "peer_metric_contamination" for issue in report["issues"])


def _write_run(tmp_path, report_md):
    run_dir = tmp_path / "sample_run"
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (outputs / "run_summary.json").write_text('{"symbol":"600519.SS","verification_passed":true}', encoding="utf-8")
    (outputs / "claims.json").write_text('[{"claim_id":"cl_1","claim_text":"主营业务","evidence_ids":["ev_1"]}]', encoding="utf-8")
    (outputs / "evidence.json").write_text('[{"evidence_id":"ev_1","source_type":"cninfo_announcement","trust_level":"primary","title":"年报"}]', encoding="utf-8")
    (outputs / "citations.json").write_text('[{"evidence_id":"ev_1","claim_ids":["cl_1"]}]', encoding="utf-8")
    (outputs / "tables.json").write_text('[{"statement":"income_statement"},{"statement":"balance_sheet"},{"statement":"cash_flow_statement"}]', encoding="utf-8")
    (outputs / "financial_metrics.json").write_text('{"revenue":{"value":100,"unit":"亿元"}}', encoding="utf-8")
    (outputs / "charts.json").write_text('[{"chart_id":"c1","title":"收入利润趋势"},{"chart_id":"c2","title":"关键财务指标"}]', encoding="utf-8")
    (outputs / "company_profile_extracted.json").write_text('{"business":"白酒"}', encoding="utf-8")
    (outputs / "verification_report.json").write_text('{"passed":true}', encoding="utf-8")
    (reports / "report.md").write_text(report_md, encoding="utf-8")
    (reports / "report.html").write_text(f"<html><body>{report_md}</body></html>", encoding="utf-8")
    return run_dir
