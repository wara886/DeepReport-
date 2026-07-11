from src.data.canonical_metrics import build_canonical_metrics_artifact


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
