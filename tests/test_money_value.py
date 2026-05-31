import pytest

from src.utils.money import MoneyValue, convert_money, format_money_for_report


def test_money_value_requires_currency():
    value = MoneyValue(100, "")
    assert value.currency == "unknown"
    assert value.confidence == "unknown"


def test_format_cny_billions_in_chinese():
    text = format_money_for_report(MoneyValue(751.766, "CNY", "billion"), language="zh-CN")
    assert "7517.66" in text
    assert "人民币" in text


def test_convert_cny_to_usd_with_fx_metadata():
    converted = convert_money(
        MoneyValue(710, "CNY", "billion"),
        "USD",
        {("CNY", "USD"): {"rate": 1 / 7.1, "date": "2026-05-31"}},
    )
    assert converted.currency == "USD"
    assert converted.source_currency == "CNY"
    assert converted.fx_date == "2026-05-31"
    assert converted.amount == pytest.approx(100)
