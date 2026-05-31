from src.evaluation.report_quality import _check_currency_policy


def test_report_quality_blocks_currency_unit_mismatch():
    issues = []
    _check_currency_policy(
        {
            "currency_audit": {"symbol": "0700.HK", "market": "hk", "blockers": ["currency_unit_mismatch"]},
            "financial_metrics": {"metrics": []},
            "valuation_model": {},
            "summary": {},
        },
        issues,
    )
    assert any(item["category"] == "currency_unit_mismatch" for item in issues)


def test_report_quality_blocks_non_us_valuation_usd():
    issues = []
    _check_currency_policy(
        {
            "currency_audit": {"symbol": "0700.HK", "market": "hk", "blockers": []},
            "financial_metrics": {"metrics": []},
            "valuation_model": {"currency": "USD"},
            "summary": {},
        },
        issues,
    )
    assert any(item["category"] == "valuation_currency_mismatch" for item in issues)
