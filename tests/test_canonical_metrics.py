from src.data.canonical_metrics import (
    build_canonical_metrics_artifact,
    canonical_metrics_as_financial_metrics,
    canonical_metrics_as_statement_tables,
)
from src.evaluation.report_quality import load_quality_artifacts, resolve_run_paths


def test_canonical_metrics_prefers_official_pdf_over_market_api_and_records_conflict():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={
            "metrics": [
                {
                    "metric_name": "revenue",
                    "value": 100.0,
                    "unit": "HKD_million",
                    "source_type": "market_api",
                    "source_evidence_id": "yahoo_financials",
                    "period_match": True,
                    "confidence": 0.9,
                },
                {
                    "metric_name": "revenue",
                    "value": 95.0,
                    "unit": "HKD_million",
                    "source_type": "pdf_statement_table",
                    "source_evidence_id": "pdf_table_income",
                    "source_table_id": "pdf_tbl_income",
                    "period_match": True,
                    "confidence": 0.86,
                },
            ]
        },
        tables=[],
        symbol="0700.HK",
        period="FY2025",
    )

    revenue = artifact["canonical_metrics"]["revenue"]
    assert revenue["value"] == 95.0
    assert revenue["source_type"] == "pdf_statement_table"
    assert artifact["conflict_count"] == 1
    assert artifact["resolved_conflict_count"] == 1
    assert artifact["unresolved_conflict_count"] == 0
    assert artifact["conflicts"][0]["resolution_status"] == "resolved"
    assert artifact["conflicts"][0]["winner"]["source_evidence_id"] == "pdf_table_income"
    assert artifact["conflicts"][0]["losers"][0]["source_evidence_id"] == "yahoo_financials"


def test_canonical_metrics_keeps_equal_authority_value_mismatch_unresolved():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={
            "metrics": [
                {
                    "metric_name": "revenue",
                    "value": 660257.0,
                    "unit": "CNY_million",
                    "source_type": "pdf_statement_table",
                    "source_evidence_id": "hkex_income_page_1",
                    "period_match": True,
                    "confidence": 0.9,
                },
                {
                    "metric_name": "revenue",
                    "value": 609015.0,
                    "unit": "CNY_million",
                    "source_type": "pdf_statement_table",
                    "source_evidence_id": "hkex_income_page_2",
                    "period_match": True,
                    "confidence": 0.88,
                },
            ]
        },
        tables=[],
        symbol="0700.HK",
        period="FY2024",
    )

    assert artifact["conflict_count"] == 1
    assert artifact["resolved_conflict_count"] == 0
    assert artifact["unresolved_conflict_count"] == 1
    assert artifact["conflicts"][0]["resolution_status"] == "unresolved"


def test_canonical_metrics_uses_table_rows_as_candidates():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={"metrics": []},
        tables=[
            {
                "table_id": "tbl_cash",
                "table_type": "cash_flow_statement",
                "source_evidence_id": "pdf_table_cash",
                "source_type": "pdf_statement_table",
                "unit": "HKD_thousand",
                "rows": [
                    {
                        "line_item": "operating_cash_flow",
                        "value": -23882.0,
                        "period_match": True,
                    }
                ],
            }
        ],
        symbol="0959.HK",
        period="FY2025",
    )

    assert artifact["canonical_metrics"]["operating_cash_flow"]["value"] == -23882.0
    assert artifact["canonical_metrics"]["operating_cash_flow"]["source_table_id"] == "tbl_cash"


def test_canonical_metrics_builds_auditable_derived_metric_lineage():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={
            "metrics": [
                {"metric_name": "revenue", "value": 200.0, "unit": "USD_billion", "source_type": "sec_companyfacts", "source_evidence_id": "sec-revenue", "period_match": True},
                {"metric_name": "net_income", "value": 40_000_000_000.0, "unit": "USD", "source_type": "sec_companyfacts", "source_evidence_id": "sec-income", "period_match": True},
                {"metric_name": "total_assets", "value": 500.0, "unit": "USD_billion", "source_type": "sec_companyfacts", "source_evidence_id": "sec-assets", "period_match": True},
                {"metric_name": "free_cash_flow", "value": 30.0, "unit": "USD_billion", "source_type": "sec_companyfacts", "source_evidence_id": "sec-fcf", "period_match": True},
            ]
        },
        tables=[],
        symbol="MSFT",
        period="FY2024",
    )

    net_margin = artifact["derived_metrics"]["net_margin"]
    assert artifact["schema_version"] == "canonical_metrics.v3"
    assert net_margin["value"] == 20.0
    assert net_margin["calculation_formula"] == "net_income / revenue * 100"
    assert net_margin["input_metric_names"] == ["net_income", "revenue"]
    assert net_margin["source_evidence_ids"] == ["sec-income", "sec-revenue"]
    assert len(net_margin["lineage"]["inputs"]) == 2

    financial_metrics = canonical_metrics_as_financial_metrics(artifact)
    assert any(row["metric_name"] == "net_margin" for row in financial_metrics["metrics"])


def test_canonical_metric_preserves_candidate_calculation_formula():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={
            "metrics": [
                {
                    "metric_name": "revenue_growth_pct",
                    "value": 2.02,
                    "unit": "pct",
                    "source_type": "sec_companyfacts",
                    "source_evidence_id": "sec-growth",
                    "period": "FY2024",
                    "period_match": True,
                    "calculation_formula": "(revenue - prior_revenue) / abs(prior_revenue) * 100",
                }
            ]
        },
        tables=[],
        symbol="AAPL",
        period="FY2024",
    )

    growth = artifact["canonical_metrics"]["revenue_growth_pct"]
    assert growth["source_type"] == "sec_companyfacts"
    assert growth["calculation_formula"].startswith("(revenue - prior_revenue)")


def test_canonical_metrics_rejects_wrong_fiscal_year_market_candidate():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={
            "metrics": [
                {
                    "metric_name": "revenue",
                    "value": 391035000000.0,
                    "unit": "USD",
                    "source_type": "sec_companyfacts",
                    "source_evidence_id": "sec_aapl_fy2024",
                    "period": "FY2024",
                    "report_date": "2024-09-28",
                    "period_match": True,
                    "confidence": 0.92,
                },
                {
                    "metric_name": "revenue",
                    "value": 416161000000.0,
                    "unit": "USD",
                    "source_type": "market_api",
                    "source_evidence_id": "aapl_yahoo_fy2024_wrong_end",
                    "period": "FY2024",
                    "report_date": "2025-09-30",
                    "confidence": 0.9,
                },
            ]
        },
        tables=[],
        symbol="AAPL",
        period="FY2024",
    )

    revenue = artifact["canonical_metrics"]["revenue"]
    assert revenue["value"] == 391035000000.0
    assert revenue["source_type"] == "sec_companyfacts"
    assert artifact["rejected_candidate_count"] == 1
    assert artifact["rejected_candidates"][0]["source_evidence_id"] == "aapl_yahoo_fy2024_wrong_end"


def test_canonical_metrics_extracts_period_matched_yahoo_statement_history():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={"metrics": []},
        tables=[],
        evidence_records=[
            {
                "evidence_id": "aapl_yahoo_financials",
                "symbol": "AAPL",
                "period": "FY2024",
                "source_type": "market_api",
                "source_url": "https://finance.yahoo.com/quote/AAPL/financials",
                "metadata": {
                    "target_period": "FY2024",
                    "financials": {
                        "totalRevenue": 451442016256.0,
                        "income_history": [
                            {
                                "end_date": "2024-09-30",
                                "Total Revenue": 391035000000.0,
                                "Net Income": 93736000000.0,
                                "Gross Profit": 180683000000.0,
                            }
                        ],
                        "balance_history": [
                            {
                                "end_date": "2024-09-30",
                                "Total Assets": 364980000000.0,
                                "Total Liabilities Net Minority Interest": 308030000000.0,
                                "Cash And Cash Equivalents": 29943000000.0,
                            }
                        ],
                        "cashflow_history": [
                            {
                                "end_date": "2024-09-30",
                                "Operating Cash Flow": 118254000000.0,
                                "Free Cash Flow": 108807000000.0,
                            }
                        ],
                    },
                },
            }
        ],
        symbol="AAPL",
        period="FY2024",
    )

    assert artifact["metric_count"] == 9
    assert artifact["canonical_metrics"]["gross_profit"]["value"] == 180.683
    assert artifact["canonical_metrics"]["revenue"]["value"] == 391.035
    assert artifact["canonical_metrics"]["net_income"]["value"] == 93.736
    assert artifact["canonical_metrics"]["total_assets"]["value"] == 364.98
    assert artifact["canonical_metrics"]["operating_cash_flow"]["value"] == 118.254
    assert artifact["canonical_metrics"]["revenue"]["source_evidence_id"] == "aapl_yahoo_financials"
    assert artifact["canonical_metrics"]["revenue"]["report_date"] == "2024-09-30"
    assert artifact["canonical_metrics"]["revenue"]["unit"] == "USD_billion"


def test_canonical_metrics_projects_detailed_three_statement_rows():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={"metrics": []},
        tables=[],
        evidence_records=[
            {
                "evidence_id": "aapl_detailed_statements",
                "symbol": "AAPL",
                "period": "FY2024",
                "source_type": "market_api",
                "metadata": {
                    "target_period": "FY2024",
                    "financials": {
                        "income_history": [{
                            "end_date": "2024-09-30",
                            "Total Revenue": 391035000000.0,
                            "Cost Of Revenue": 210352000000.0,
                            "Gross Profit": 180683000000.0,
                            "Operating Income": 123216000000.0,
                            "Pretax Income": 123485000000.0,
                            "Net Income": 93736000000.0,
                            "Basic EPS": 6.11,
                            "Diluted EPS": 6.08,
                        }],
                        "balance_history": [{
                            "end_date": "2024-09-30",
                            "Total Assets": 364980000000.0,
                            "Current Assets": 152987000000.0,
                            "Cash And Cash Equivalents": 29943000000.0,
                            "Inventory": 7286000000.0,
                            "Total Liabilities Net Minority Interest": 308030000000.0,
                            "Current Liabilities": 176392000000.0,
                            "Total Debt": 106629000000.0,
                            "Stockholders Equity": 56950000000.0,
                            "Ordinary Shares Number": 15116786000.0,
                        }],
                        "cashflow_history": [{
                            "end_date": "2024-09-30",
                            "Operating Cash Flow": 118254000000.0,
                            "Capital Expenditure": -9447000000.0,
                            "Free Cash Flow": 108807000000.0,
                            "Investing Cash Flow": 2935000000.0,
                            "Financing Cash Flow": -121983000000.0,
                            "Cash Dividends Paid": -15234000000.0,
                            "Repurchase Of Capital Stock": -94949000000.0,
                        }],
                    },
                },
            }
        ],
        symbol="AAPL",
        period="FY2024",
    )

    assert artifact["canonical_metrics"]["shares_outstanding"]["value"] == 15.116786
    assert artifact["canonical_metrics"]["total_equity"]["value"] == 56.95
    tables = {item["table_type"]: item for item in canonical_metrics_as_statement_tables(artifact)}
    assert len(tables["income_statement"]["rows"]) == 8
    assert len(tables["balance_sheet"]["rows"]) == 9
    assert len(tables["cash_flow_statement"]["rows"]) == 7
    assert {row["line_item"] for row in tables["cash_flow_statement"]["rows"]} >= {
        "operating_cash_flow",
        "capital_expenditure",
        "free_cash_flow",
    }


def test_canonical_metrics_extracts_yahoo_statements_in_chunk_parent_metadata():
    artifact = build_canonical_metrics_artifact(
        financial_metrics={"metrics": []},
        tables=[],
        evidence_records=[
            {
                "evidence_id": "aapl_yahoo_financials_chunk",
                "symbol": "AAPL",
                "period": "FY2024",
                "source_type": "market_api",
                "metadata": {
                    "target_period": "FY2024",
                    "parent_metadata": {
                        "financials": {
                            "income_history": [
                                {
                                    "end_date": "2024-09-30",
                                    "Total Revenue": 391035000000.0,
                                    "Net Income": 93736000000.0,
                                    "Gross Profit": 180683000000.0,
                                }
                            ],
                            "balance_history": [
                                {
                                    "end_date": "2024-09-30",
                                    "Total Assets": 364980000000.0,
                                    "Total Liabilities": 308030000000.0,
                                    "Cash And Cash Equivalents": 29943000000.0,
                                }
                            ],
                            "cashflow_history": [
                                {
                                    "end_date": "2024-09-30",
                                    "Operating Cash Flow": 118254000000.0,
                                    "Free Cash Flow": 108807000000.0,
                                }
                            ],
                        }
                    },
                },
            }
        ],
        symbol="AAPL",
        period="FY2024",
    )

    assert artifact["metric_count"] == 9
    assert artifact["canonical_metrics"]["gross_profit"]["value"] == 180.683


def test_canonical_metrics_resolves_historical_deep_chunk_metadata():
    nested = {
        "financials": {
            "income_history": [{
                "end_date": "2024-09-30",
                "Total Revenue": 391035000000.0,
                "Net Income": 93736000000.0,
                "Gross Profit": 180683000000.0,
            }],
            "balance_history": [{
                "end_date": "2024-09-30",
                "Total Assets": 364980000000.0,
                "Total Liabilities": 308030000000.0,
                "Cash And Cash Equivalents": 29943000000.0,
            }],
            "cashflow_history": [{
                "end_date": "2024-09-30",
                "Operating Cash Flow": 118254000000.0,
                "Free Cash Flow": 108807000000.0,
            }],
        }
    }
    for _ in range(12):
        nested = {"parent_metadata": nested, "chunking": {"strategy": "paragraph_table_metric_v1"}}

    artifact = build_canonical_metrics_artifact(
        financial_metrics={"metrics": []},
        tables=[],
        evidence_records=[{
            "evidence_id": "deep_existing_chunk",
            "symbol": "AAPL",
            "period": "FY2024",
            "source_type": "market_api",
            "metadata": nested,
        }],
        symbol="AAPL",
        period="FY2024",
    )

    assert artifact["coverage"]["missing_core_metrics"] == []
    assert artifact["canonical_metrics"]["revenue"]["value"] == 391.035
    assert artifact["canonical_metrics"]["free_cash_flow"]["value"] == 108.807
    assert artifact["canonical_metrics"]["revenue"]["source_evidence_id"] == "deep_existing_chunk"

    tables = canonical_metrics_as_statement_tables(artifact)
    assert [table["table_type"] for table in tables] == [
        "income_statement",
        "balance_sheet",
        "cash_flow_statement",
    ]
    assert tables[0]["extraction_method"] == "canonical_metric_projection"
    assert tables[0]["rows"][0]["metric_name"] == "revenue"
    assert tables[2]["rows"][1]["value"] == 108.807


def test_quality_artifact_loader_prefers_canonical_metrics(tmp_path):
    run_dir = tmp_path / "run"
    outputs = run_dir / "outputs"
    reports = run_dir / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (outputs / "financial_metrics.json").write_text(
        '{"metrics":[{"metric_name":"revenue","value":100,"source_type":"market_api"}]}',
        encoding="utf-8",
    )
    (outputs / "canonical_metrics.json").write_text(
        '{"metrics":[{"metric_name":"revenue","value":95,"source_type":"pdf_statement_table"}],"canonical_metrics":{"revenue":{"metric_name":"revenue","value":95,"source_type":"pdf_statement_table"}}}',
        encoding="utf-8",
    )

    artifacts = load_quality_artifacts(resolve_run_paths(run_dir))

    assert artifacts["financial_metrics"]["metrics"][0]["value"] == 95
    assert artifacts["financial_metrics"]["canonical_source"] == "canonical_metrics.json"
    assert artifacts["raw_financial_metrics"]["metrics"][0]["value"] == 100
