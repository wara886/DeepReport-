from src.agents.section_dossier_builder import sanitize_peer_rows_for_report
from src.agents.verifier import _ticker_mentions
from src.agents.deep_analyze_agent import _allow_external_peer_discovery


def test_external_peer_discovery_is_market_scoped_for_a_shares():
    assert _allow_external_peer_discovery("600519.SS") is True
    assert _allow_external_peer_discovery("AAPL") is True
    assert _allow_external_peer_discovery("0700.HK") is False


def test_currency_codes_are_not_ticker_mentions():
    assert not ({"CNY", "HKD", "USD"} & _ticker_mentions("报表货币 CNY，交易货币 HKD，对照货币 USD"))
from src.agents.deep_analyze_agent import build_role_outputs
from src.evaluation.report_quality import evaluate_report_quality
from src.features.company_valuation import build_peer_comparison


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


def test_role_outputs_sanitize_a_share_peer_and_risk_contamination():
    records = [
        {
            "evidence_id": "ev1",
            "sample_id": "ev1",
            "source_type": "eastmoney_financials",
            "symbol": "600519.SS",
            "period": "FY2025",
            "trust_level": "high",
        }
    ]
    claims = [
        {
            "section_name": "risks",
            "claim_text": "宏观利率、资本开支周期和云厂商采购节奏会放大收入波动。",
            "evidence_ids": ["ev1"],
        }
    ]
    metrics = {
        "metric_count": 3,
        "metrics": [
            {"metric_name": "revenue", "value": 172054171890.91, "unit": "CNY", "evidence_id": "ev1"},
            {"metric_name": "net_income", "value": 82320067101.68, "unit": "CNY", "evidence_id": "ev1"},
            {"metric_name": "operating_cash_flow", "value": 61522204989.35, "unit": "CNY", "evidence_id": "ev1"},
        ],
    }
    peer_context = {
        "peer_count": 5,
        "peer_symbols": ["PG", "KO", "PEP", "WMT", "COST"],
        "peer_rows": [{"symbol": "PG"}, {"symbol": "KO"}],
    }

    outputs = build_role_outputs(
        records=records,
        claims=claims,
        symbol="600519.SS",
        period="FY2025",
        financial_metric_lineage=metrics,
        peer_context=peer_context,
    )
    payload = str(outputs)
    statement = "\n".join(outputs["three_statement_analysis"]["findings"])

    assert "PG" not in payload
    assert "KO" not in payload
    assert "云厂商" not in payload
    assert "收入 1720.54亿元" in statement
    assert "净利润 823.20亿元" in statement
    assert "经营现金流 615.22亿元" in statement


def test_role_outputs_project_peer_context_into_peer_analysis():
    peer_context = {
        "peer_count": 2,
        "peer_rows": [
            {"symbol": "600519.SS", "is_target": True, "industry": "Distillers", "revenue_growth_pct": 6.5},
            {"symbol": "002304.SZ", "is_target": False, "industry": "Distillers", "revenue_growth_pct": -26.0},
            {"symbol": "600197.SS", "is_target": False, "industry": "Distillers", "revenue_growth_pct": -23.8},
        ],
    }

    outputs = build_role_outputs([], [], "600519.SS", "FY2024", peer_context=peer_context)
    peer_analysis = outputs["peer_analysis"]

    assert peer_analysis["approved_peer_symbols"] == ["002304.SZ", "600197.SS"]
    assert [row["symbol"] for row in peer_analysis["peer_rows"]] == ["002304.SZ", "600197.SS"]


def test_a_share_peer_builder_does_not_fallback_to_us_yahoo_when_local_missing(tmp_path):
    result = build_peer_comparison("600519.SS", "FY2025", raw_data_root=tmp_path / "missing")
    payload = str(result)

    assert result["target_market"] == "cn_a"
    assert result["peer_count"] == 0
    assert result["peer_rows"] == []
    assert result["source"] == "local_only_market_isolated"
    for token in ["PG", "KO", "PEP", "WMT", "COST"]:
        assert token not in payload


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
