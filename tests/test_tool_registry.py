from src.tools import build_core_tool_registry


def _records():
    return [
        {
            "sample_id": "ev_1",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "financials",
            "publish_time": "2025-10-30",
            "content": (
                "Revenue 120.0B, revenue growth 8.5%, gross margin 45.0%, net margin 26.0%, "
                "ROE 150.0%, ROA 30.0%, operating cash flow 30.0B and free cash flow 25.0B."
            ),
        },
        {
            "sample_id": "ev_2",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "news",
            "publish_time": "2025-11-01",
            "content": "Operating cash flow 30.0B and free cash flow 25.0B.",
        },
    ]


def test_core_tool_registry_exposes_function_schemas():
    registry = build_core_tool_registry()
    schemas = registry.tool_schemas()

    assert "calculate_financial_ratios" in registry.names()
    assert "build_three_statement_view" in registry.names()
    assert "build_peer_comparison" in registry.names()
    assert "perform_company_valuation" in registry.names()
    assert "fetch_yahoo_market_snapshot" in registry.names()
    assert "retrieve_local_evidence" in registry.names()
    assert all(item["type"] == "function" for item in schemas)
    assert schemas[0]["function"]["parameters"]["type"] == "object"


def test_financial_ratio_tool_wraps_existing_feature_logic():
    registry = build_core_tool_registry()

    result = registry.call("calculate_financial_ratios", records=_records())

    rows = result["rows"]
    assert rows[0]["revenue_billion"] == 120.0
    assert rows[0]["gross_margin_pct"] == 45.0
    assert rows[1]["operating_cash_flow_billion"] == 30.0


def test_trend_tool_wraps_existing_feature_logic():
    registry = build_core_tool_registry()

    result = registry.call("build_trend_features", records=_records())

    assert result["rows"][0]["evidence_count"] == 2
    assert result["rows"][0]["unique_sources"] == 2


def test_trend_tool_backfills_missing_group_columns_from_metadata():
    registry = build_core_tool_registry()

    result = registry.call(
        "build_trend_features",
        records=[
            {
                "evidence_id": "ev_meta",
                "content": "Revenue 120.0B.",
                "metadata": {
                    "symbol": "MSFT",
                    "period": "2025Q4",
                    "source_type": "financials",
                    "publish_time": "2026-01-31",
                },
            }
        ],
    )

    assert result["rows"][0]["symbol"] == "MSFT"
    assert result["rows"][0]["period"] == "2025Q4"
    assert result["rows"][0]["evidence_count"] == 1


def test_company_report_tools_return_statements_peers_and_valuation():
    registry = build_core_tool_registry()

    statements = registry.call("build_three_statement_view", records=_records())
    peers = registry.call("build_peer_comparison", symbol="AAPL", period="2025Q4", raw_data_root="data/raw/real_data")
    valuation = registry.call(
        "perform_company_valuation",
        symbol="AAPL",
        period="2025Q4",
        records=_records(),
        raw_data_root="data/raw/real_data",
    )

    assert statements["coverage"]["has_three_statement_view"] is True
    assert peers["peer_count"] >= 1
    assert valuation["valuation_available"] is True


def test_yahoo_market_snapshot_tool_returns_evidence(monkeypatch):
    def fake_yahoo_snapshot_to_evidence(symbol, period="", range_="1mo", interval="1d"):
        return {
            "evidence_id": f"{symbol}_{period}_yahoo",
            "source_type": "market_api",
            "source_url": f"https://finance.yahoo.com/quote/{symbol}",
        }

    monkeypatch.setattr("src.tools.registry.yahoo_snapshot_to_evidence", fake_yahoo_snapshot_to_evidence)
    registry = build_core_tool_registry()

    result = registry.call("fetch_yahoo_market_snapshot", symbol="AAPL", period="2025Q4")

    assert result["evidence"]["evidence_id"] == "AAPL_2025Q4_yahoo"
    assert result["evidence"]["source_type"] == "market_api"
