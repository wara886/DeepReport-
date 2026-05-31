from src.data.financial_statement_metrics import build_standard_financial_metrics
from src.evaluation.financial_currency_audit import build_currency_audit


def _tencent_yahoo_record():
    return {
        "evidence_id": "0700.HK_FY2025_yahoo_financials",
        "symbol": "0700.HK",
        "period": "FY2025",
        "source_type": "market_api",
        "metadata": {
            "provider": "yahoo_finance",
            "financials": {
                "income_history": [{"end_date": "2025-12-31", "Total Revenue": 751766000000.0, "Net Income": 224842000000.0}],
                "cashflow_history": [{"end_date": "2025-12-31", "Free Cash Flow": 190171000000.0}],
                "balance_history": [{"end_date": "2025-12-31", "Total Assets": 2038986000000.0}],
            },
        },
    }


def test_tencent_yahoo_values_not_labeled_usd():
    metrics = build_standard_financial_metrics([_tencent_yahoo_record()])
    revenue = next(item for item in metrics["metrics"] if item["metric_name"] == "revenue")
    assert revenue["currency"] == "CNY"
    assert revenue["unit"] == "CNY"


def test_currency_audit_detects_rmb_marked_as_usd():
    metrics = {"metrics": [{"metric_name": "revenue", "value": 751766000000, "unit": "USD", "source_type": "market_api"}]}
    audit = build_currency_audit(symbol="0700.HK", period="FY2025", records=[_tencent_yahoo_record()], financial_metrics=metrics)
    assert "currency_unit_mismatch" in audit["blockers"]


def test_currency_audit_writes_blocker_for_unknown_currency():
    metrics = {"metrics": [{"metric_name": "revenue", "value": 100, "unit": "unknown", "source_type": "market_api"}]}
    audit = build_currency_audit(symbol="9999.HK", period="FY2025", records=[], financial_metrics=metrics)
    assert "unknown_financial_metric_currency" in audit["blockers"]
