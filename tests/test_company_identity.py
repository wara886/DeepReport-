from src.data.company_universe import (
    build_data_source_plan,
    infer_market_from_symbol,
    resolve_company_identity,
)


def test_resolve_a_share_identity_from_code():
    identity = resolve_company_identity("600519")

    assert identity.canonical_symbol == "600519.SS"
    assert identity.market == "cn_a"
    assert identity.exchange == "SSE"
    assert identity.is_listed is True
    assert "eastmoney_financials" in identity.data_source_plan["engines"]
    assert "cninfo_announcements" in identity.data_source_plan["primary_sources"]


def test_resolve_hk_identity_from_code():
    identity = resolve_company_identity("700.HK")

    assert identity.canonical_symbol == "0700.HK"
    assert identity.market == "hk"
    assert identity.exchange == "HKEX"
    assert "yahoo_finance" in identity.data_source_plan["engines"]


def test_resolve_us_identity_from_ticker_pattern():
    identity = resolve_company_identity("AAPL")

    assert identity.symbol == "AAPL"
    assert identity.market == "us"
    assert identity.currency == "USD"
    assert "sec_edgar" in identity.data_source_plan["engines"]


def test_unknown_company_needs_confirmation():
    identity = resolve_company_identity("一家还没有上市的本地咖啡店")

    assert identity.is_listed is False
    assert identity.needs_confirmation is True


def test_default_engines_come_from_identity_plan():
    assert "eastmoney_financials" in build_data_source_plan("600519.SS", "cn_a")["engines"]
    assert "sec_edgar" in build_data_source_plan("AAPL", "us")["engines"]
    assert "sec_edgar" not in build_data_source_plan("0700.HK", "hk")["engines"]


def test_market_inference_for_other_exchange_suffix():
    meta = infer_market_from_symbol("7203.T")
    assert meta["market"] == "other"
    assert build_data_source_plan("7203.T", meta["market"])["free_public_only"] is True
