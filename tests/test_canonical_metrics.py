from src.data.canonical_metrics import build_canonical_metrics_artifact
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
    assert artifact["conflicts"][0]["winner"]["source_evidence_id"] == "pdf_table_income"
    assert artifact["conflicts"][0]["losers"][0]["source_evidence_id"] == "yahoo_financials"


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
