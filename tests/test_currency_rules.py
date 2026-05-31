from src.market.currency_rules import infer_statement_currency, infer_trading_currency


def test_hk_stock_trading_currency_hkd():
    assert infer_trading_currency("0700.HK") == "HKD"


def test_a_share_statement_currency_cny():
    meta = infer_statement_currency("600519.SS", market="cn_a")
    assert meta.statement_currency == "CNY"
    assert meta.trading_currency == "CNY"


def test_us_stock_default_usd():
    meta = infer_statement_currency("AAPL", market="us")
    assert meta.statement_currency == "USD"
    assert meta.trading_currency == "USD"


def test_issuer_currency_override_for_tencent():
    meta = infer_statement_currency("0700.HK", market="hk")
    assert meta.statement_currency == "CNY"
    assert meta.trading_currency == "HKD"
    assert meta.inferred_from == "issuer_currency_overrides"
