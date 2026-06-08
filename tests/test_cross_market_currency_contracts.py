from src.report.chart_generator import generate_report_charts
from src.report.contract_builder import build_report_section_contracts
from src.utils.money import build_currency_context, format_amount_for_context


def test_us_currency_context_formats_tsla_in_billions():
    context = build_currency_context(symbol="TSLA")

    assert context.display_currency == "USD"
    assert context.unit_label == "十亿美元"
    assert format_amount_for_context(22_387_000_000, context) == "22.39 十亿美元"


def test_us_charts_use_usd_and_support_scenario_values(tmp_path):
    charts = generate_report_charts(
        claims=[
            {
                "claim_id": "cl_tsla_financials",
                "section_name": "financial_analysis",
                "claim_text": "TSLA quarterly financial scale.",
                "evidence_ids": ["sec_companyfacts_tsla"],
                "numeric_values": {
                    "revenue": 22_387_000_000,
                    "net_income": 477_000_000,
                    "total_assets": 143_724_000_000,
                    "operating_cash_flow": 2_160_000_000,
                },
            }
        ],
        evidence_records=[],
        output_dir=tmp_path,
        analysis_artifacts={
            "valuation_sensitivity": {
                "scenario_values": {
                    "bear": {"target_price": 180},
                    "base": {"target_price": 240},
                    "bull": {"target_price": 320},
                }
            }
        },
        currency_context=build_currency_context(symbol="TSLA"),
    )

    by_id = {row["chart_id"]: row for row in charts}
    scale = by_id["financial_scale_bar"]["chart_js"]
    assert scale["unit_label"] == "十亿美元"
    assert scale["display_currency"] == "USD"
    assert scale["data"][0] == 22.387
    assert "人民币" not in str(charts)
    assert "valuation_sensitivity_bar" in by_id


def test_us_contract_uses_profile_fallback_us_governance_and_usd_tables():
    contracts = build_report_section_contracts(
        state={
            "symbol": "TSLA",
            "period": "2026Q1",
            "company_name": "Tesla, Inc.",
            "entity_resolution": {
                "company_name": "Tesla, Inc.",
                "symbol_resolution": {
                    "business_summary": (
                        "Tesla designs, develops, manufactures, leases and sells electric vehicles, "
                        "energy generation products and energy storage systems."
                    ),
                    "period": "2025Q4",
                },
            },
            "research_blackboard": {},
        },
        evidence_records=[],
        analysis_artifacts={
            "financial_metrics": {
                "metrics": [
                    {
                        "metric_name": "revenue",
                        "value": 22_387_000_000,
                        "period": "2026Q1",
                        "currency": "USD",
                        "source_evidence_id": "sec_companyfacts_tsla",
                    }
                ]
            },
            "tables": [
                {
                    "table_type": "income_statement",
                    "rows": [
                        {
                            "line_item": "revenue",
                            "value": 22_387_000_000,
                            "period": "2026Q1",
                            "currency": "USD",
                            "source_type": "sec_companyfacts",
                            "source_evidence_id": "sec_companyfacts_tsla",
                        }
                    ],
                },
                {
                    "table_type": "balance_sheet",
                    "rows": [
                        {
                            "line_item": "total_assets",
                            "value": 143_724_000_000,
                            "period": "2026Q1",
                            "currency": "USD",
                            "source_type": "sec_companyfacts",
                            "source_evidence_id": "sec_companyfacts_tsla",
                        },
                        {
                            "line_item": "total_liabilities",
                            "value": 58_922_000_000,
                            "period": "2026Q1",
                            "currency": "USD",
                            "source_type": "sec_companyfacts",
                            "source_evidence_id": "sec_companyfacts_tsla",
                        },
                    ],
                },
                {
                    "table_type": "cash_flow_statement",
                    "rows": [
                        {
                            "line_item": "operating_cash_flow",
                            "value": 2_160_000_000,
                            "period": "2026Q1",
                            "currency": "USD",
                            "source_type": "sec_companyfacts",
                            "source_evidence_id": "sec_companyfacts_tsla",
                        }
                    ],
                },
            ],
            "valuation_sensitivity": {
                "scenario_values": {
                    "bear": {"target_price": 180},
                    "base": {"target_price": 240},
                    "bull": {"target_price": 320},
                }
            },
        },
        section_dossiers={},
        citations=[],
    )

    business = contracts.get("business_overview")
    governance = contracts.get("ownership_governance")
    statements = contracts.get("three_statement_summary")
    sensitivity = contracts.get("valuation_sensitivity")

    assert business is not None and business.status == "fallback"
    assert "2025Q4" in business.facts[0].text
    assert governance is not None
    assert "监事会" not in governance.deterministic_text
    assert "审计委员会" in governance.deterministic_text
    assert statements is not None
    assert "22.39 十亿美元" in statements.deterministic_text
    assert "人民币" not in statements.deterministic_text
    assert sensitivity is not None and sensitivity.status == "supported"
    assert "基准情景" in sensitivity.deterministic_text
    assert "目标价=240" in sensitivity.deterministic_text
