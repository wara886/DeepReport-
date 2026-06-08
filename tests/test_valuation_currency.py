from src.features import company_valuation


def test_valuation_blocks_non_us_annual_without_official_source(monkeypatch):
    monkeypatch.setattr(company_valuation, "build_peer_comparison", lambda **_: {
        "peer_rows": [{
            "symbol": "0700.HK",
            "revenue_billion": 751.766,
            "net_income_billion": 224.842,
            "adjusted_net_income_billion": 224.842,
            "free_cash_flow_billion": 190.171,
            "revenue_growth_pct": 6.5,
            "free_cash_flow_period_basis": "annual",
            "valuation_input_usable": True,
        }],
        "peer_count": 0,
    })
    result = company_valuation.perform_company_valuation(
        "0700.HK",
        "FY2025",
        records=[{"symbol": "0700.HK", "period": "FY2025", "source_type": "market_api", "metadata": {"financials": {"marketCap": 3856740122624}}}],
    )
    assert result["valuation_available"] is False
    assert result["valuation_status"] == "degraded_due_to_unverified_financial_currency"


def test_valuation_outputs_hkd_after_fx_conversion(monkeypatch):
    monkeypatch.setattr(company_valuation, "build_peer_comparison", lambda **_: {
        "peer_rows": [{
            "symbol": "0700.HK",
            "revenue_billion": 751.766,
            "net_income_billion": 224.842,
            "adjusted_net_income_billion": 224.842,
            "free_cash_flow_billion": 190.171,
            "revenue_growth_pct": 6.5,
            "free_cash_flow_period_basis": "annual",
            "valuation_input_usable": True,
        }],
        "peer_count": 0,
    })
    monkeypatch.setattr(company_valuation, "_get_fred_risk_free_rate", lambda: None)
    monkeypatch.setattr(company_valuation, "_get_yahoo_market_multiples", lambda symbol: {})
    result = company_valuation.perform_company_valuation(
        "0700.HK",
        "FY2025",
        records=[
            {"symbol": "0700.HK", "period": "FY2025", "source_type": "hkex_announcement", "metadata": {"currency": "CNY"}},
            {"symbol": "0700.HK", "period": "FY2025", "source_type": "market_api", "metadata": {"financials": {"marketCap": 3856740122624, "currentPrice": 427.2}}},
        ],
    )
    assert result["valuation_available"] is True
    assert result["valuation_currency"] == "HKD"
    assert result["valuation_model"]["currency"] == "HKD"
    assert result["fx_conversion"]["rate"] == 1.09


def test_valuation_blocks_deterministic_value_when_inputs_incomplete(monkeypatch):
    monkeypatch.setattr(company_valuation, "build_peer_comparison", lambda **_: {
        "peer_rows": [{
            "symbol": "AAPL",
            "revenue_billion": 400.0,
            "net_income_billion": 100.0,
            "adjusted_net_income_billion": 100.0,
            "free_cash_flow_billion": 90.0,
            "free_cash_flow_period_basis": "annual",
            "valuation_input_usable": True,
        }],
        "peer_count": 0,
    })
    monkeypatch.setattr(company_valuation, "_get_fred_risk_free_rate", lambda: None)
    monkeypatch.setattr(company_valuation, "_get_yahoo_market_multiples", lambda symbol: {})

    result = company_valuation.perform_company_valuation(
        "AAPL",
        "FY2025",
        records=[{"symbol": "AAPL", "period": "FY2025", "source_type": "sec_companyfacts", "metadata": {"currency": "USD"}}],
    )

    assert result["valuation_available"] is False
    assert result["valuation_status"] == "rough_observation_only"
    assert "revenue_growth_pct" in result["missing_inputs"]
    assert "market_cap_billion" in result["missing_inputs"]
    assert "valuation_model" not in result
