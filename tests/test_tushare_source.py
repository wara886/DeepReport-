import pandas as pd

from src.data.tushare_source import fetch_tushare_financials


class Client:
    def __getattr__(self, name):
        if name in {"income", "balancesheet", "cashflow", "fina_indicator"}:
            return lambda **_kwargs: pd.DataFrame([
                {"ts_code": "600519.SH", "ann_date": "20250403", "end_date": "20241231", "revenue": 100.0}
            ])
        raise AttributeError(name)


def test_tushare_source_builds_a_share_structured_records():
    result = fetch_tushare_financials(symbol="600519.SS", period="FY2024", client=Client())

    assert result["meta"]["record_count"] == 4
    assert result["meta"]["ts_code"] == "600519.SH"
    assert result["hits"][0]["source_type"] == "tushare_financials"
    assert result["hits"][0]["source_authority"] == "third_party_structured"
    assert result["hits"][0]["authority_level"] == "secondary"


def test_tushare_source_rejects_us_symbols():
    result = fetch_tushare_financials(symbol="AAPL", period="FY2024", client=Client())
    assert result["meta"]["failure_reason"] == "unsupported_symbol_or_period"
