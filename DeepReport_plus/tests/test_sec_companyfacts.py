from src.data.sec_companyfacts import cik_for_symbol, companyfacts_to_evidence
from src.features.company_valuation import perform_company_valuation
from src.features.financial_metric_lineage import build_financial_metric_lineage, build_financial_metric_tables
from src.features.financial_statements import build_three_statement_view


def test_companyfacts_to_evidence_feeds_statement_lineage_and_valuation():
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _fact(80_000_000_000, fy=2025, fp="Q3", start="2025-01-01", end="2025-03-31", filed="2025-04-25"),
                            _fact(100_000_000_000, fy=2026, fp="Q3", start="2026-01-01", end="2026-03-31", filed="2026-04-25"),
                        ]
                    }
                },
                "GrossProfit": {"units": {"USD": [_fact(60_000_000_000)]}},
                "OperatingIncomeLoss": {"units": {"USD": [_fact(45_000_000_000)]}},
                "NetIncomeLoss": {"units": {"USD": [_fact(30_000_000_000)]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_fact(35_000_000_000)]}},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_fact(10_000_000_000)]}},
                "Assets": {"units": {"USD": [_instant(500_000_000_000)]}},
                "Liabilities": {"units": {"USD": [_instant(250_000_000_000)]}},
                "StockholdersEquity": {"units": {"USD": [_instant(250_000_000_000)]}},
            }
        }
    }

    evidence = companyfacts_to_evidence(
        symbol="MSFT",
        cik="0000789019",
        company_name="Microsoft Corporation",
        facts_payload=payload,
        requested_period="latest",
    )

    assert evidence["source_type"] == "financials"
    assert evidence["period"] == "FY2026 Q3"
    assert evidence["metadata"]["revenue_billion"] == 100.0
    assert evidence["metadata"]["revenue_growth_pct"] == 25.0
    assert evidence["metadata"]["free_cash_flow_billion"] == 25.0

    records = [evidence]
    statements = build_three_statement_view(records)
    assert statements["coverage"]["has_three_statement_view"] is True
    assert statements["coverage"]["line_item_count"] >= 9

    lineage = build_financial_metric_lineage(records)
    assert lineage["coverage"]["has_core_metric_lineage"] is True

    tables = build_financial_metric_tables(records)
    assert len(tables) == 3

    valuation = perform_company_valuation(symbol="MSFT", period="latest", records=records)
    assert valuation["valuation_available"] is True
    assert valuation["valuation_model"]["dcf_model"]["assumptions"]["base_free_cash_flow_billion"] == 25.0


def test_cik_for_symbol_reads_sec_ticker_mapping_shape():
    cik, name = cik_for_symbol("MSFT", {"0": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"}})
    assert cik == "0000789019"
    assert name == "Microsoft Corp"


def _fact(
    val,
    fy=2026,
    fp="Q3",
    start="2026-01-01",
    end="2026-03-31",
    filed="2026-04-25",
    form="10-Q",
    accn="0000789019-26-000123",
):
    return {"val": val, "fy": fy, "fp": fp, "start": start, "end": end, "filed": filed, "form": form, "accn": accn}


def _instant(val, fy=2026, fp="Q3", end="2026-03-31", filed="2026-04-25", form="10-Q", accn="0000789019-26-000123"):
    return {"val": val, "fy": fy, "fp": fp, "end": end, "filed": filed, "form": form, "accn": accn}
