from datetime import date

import pytest

from src.app.chat_task_parser import (
    latest_available_report_period,
    latest_completed_period,
    llm_parse_chat_task,
    parse_chat_task,
)


def test_parse_guizhou_maotai_latest_report_request():
    parsed = parse_chat_task("请生成贵州茅台最新财报研报", today=date(2026, 5, 16))

    assert parsed.should_run is True
    assert parsed.needs_confirmation is False
    assert parsed.symbol == "600519.SS"
    assert parsed.period == "2026Q1"
    assert parsed.period_kind == "latest"
    assert parsed.confidence >= 0.72
    assert "600519.SS" in parsed.research_topic


def test_parse_amd_latest_report_request():
    parsed = parse_chat_task("生成 AMD 最新财报研报", today=date(2026, 5, 16))

    assert parsed.should_run is True
    assert parsed.symbol == "AMD"
    assert parsed.period == "2026Q1"
    assert parsed.period_kind == "latest"


def test_parse_english_generate_latest_report_request():
    parsed = parse_chat_task("generate 600519 latest company report", today=date(2026, 5, 16))

    assert parsed.should_run is True
    assert parsed.symbol == "600519.SS"
    assert parsed.period == "2026Q1"
    assert parsed.period_kind == "latest"


def test_parse_nvidia_chinese_name_maps_to_nvda():
    parsed = parse_chat_task("生成英伟达最新财报研报", today=date(2026, 5, 16))

    assert parsed.should_run is True
    assert parsed.symbol == "NVDA"
    assert parsed.period == "2026Q1"
    assert parsed.confidence >= 0.72


def test_parse_nvidia_report_without_latest_term_infers_current_period():
    parsed = parse_chat_task("生成一份英伟达公司的研报", current_period="2025Q4", today=date(2026, 5, 17))

    assert parsed.should_run is True
    assert parsed.needs_confirmation is False
    assert parsed.symbol == "NVDA"
    assert parsed.period == "2026Q1"
    assert parsed.period_kind == "latest"


def test_parse_complete_chinese_report_sentence_runs_without_confirmation():
    parsed = parse_chat_task("2025年Q3英伟达公司财报", today=date(2026, 5, 22))

    assert parsed.symbol == "NVDA"
    assert parsed.period == "2025Q3"
    assert parsed.period_kind == "quarter"
    assert parsed.should_run is True
    assert parsed.needs_confirmation is False
    assert "direct report request" in parsed.reason


def test_parse_report_question_without_generation_needs_confirmation():
    parsed = parse_chat_task("AMD 研报怎么样", current_symbol="AAPL", current_period="2025Q4", today=date(2026, 5, 16))

    assert parsed.should_run is False
    assert parsed.needs_confirmation is True
    assert parsed.symbol == "AMD"
    assert parsed.period == "2025Q4"
    assert parsed.period_kind == "quarter"


def test_latest_completed_period_boundaries():
    assert latest_completed_period(date(2026, 2, 1)) == "2025Q4"
    assert latest_completed_period(date(2026, 5, 16)) == "2026Q1"
    assert latest_completed_period(date(2026, 8, 1)) == "2026Q2"
    assert latest_completed_period(date(2026, 11, 1)) == "2026Q3"


def test_latest_available_report_period_uses_current_date_upper_bound():
    assert latest_available_report_period("NVDA", today=date(2026, 5, 22)) == "2026Q1"


def test_parse_future_chinese_year_quarter_request():
    parsed = parse_chat_task("生成特斯拉26年第四季度财报研报", today=date(2026, 5, 19))

    assert parsed.should_run is True
    assert parsed.symbol == "TSLA"
    assert parsed.period == "2026Q4"
    assert parsed.period_kind == "quarter"


def test_parse_year_only_financial_report_as_annual_period():
    parsed = parse_chat_task("生成特斯拉26年财报研报", today=date(2026, 5, 19))

    assert parsed.should_run is True
    assert parsed.symbol == "TSLA"
    assert parsed.period == "FY2026"
    assert parsed.period_kind == "fiscal_year"


@pytest.mark.parametrize(
    ("company_name", "symbol"),
    [
        ("苹果", "AAPL"),
        ("微软", "MSFT"),
        ("谷歌", "GOOGL"),
        ("英伟达", "NVDA"),
        ("超微半导体", "AMD"),
        ("特斯拉", "TSLA"),
        ("商汤科技", "0020.HK"),
        ("第四范式", "6682.HK"),
        ("腾讯控股", "0700.HK"),
        ("小米集团", "1810.HK"),
        ("美团", "3690.HK"),
        ("百度集团", "9888.HK"),
        ("贵州茅台", "600519.SS"),
        ("宁德时代", "300750.SZ"),
        ("比亚迪", "002594.SZ"),
        ("中国平安", "601318.SS"),
        ("招商银行", "600036.SS"),
        ("中芯国际", "688981.SS"),
    ],
)
def test_parse_formal18_company_names_and_fiscal_year(company_name, symbol):
    parsed = parse_chat_task(f"请生成{company_name} FY2024 公司研报", today=date(2026, 5, 25))

    assert parsed.should_run is True
    assert parsed.symbol == symbol
    assert parsed.period == "FY2024"
    assert parsed.period_kind == "fiscal_year"


@pytest.mark.parametrize(
    ("input_symbol", "expected"),
    [
        ("0020.HK", "0020.HK"),
        ("0700.HK", "0700.HK"),
        ("6682.HK", "6682.HK"),
        ("300750.SZ", "300750.SZ"),
        ("002594.SZ", "002594.SZ"),
        ("601318.SS", "601318.SS"),
        ("600036.SS", "600036.SS"),
        ("688981.SS", "688981.SS"),
    ],
)
def test_parse_numeric_market_codes_before_exchange_suffix(input_symbol, expected):
    parsed = parse_chat_task(f"generate {input_symbol} FY2024 company report", today=date(2026, 5, 25))

    assert parsed.should_run is True
    assert parsed.symbol == expected
    assert parsed.period == "FY2024"
    assert parsed.period_kind == "fiscal_year"


def test_llm_parser_keeps_deterministic_company_and_fiscal_period(monkeypatch):
    class WrongRouteModel:
        def generate_json(self, **kwargs):
            return {
                "symbol": "HK",
                "period": "2026Q1",
                "generation_intent": False,
                "report_intent": False,
                "confidence": 0.1,
            }

    monkeypatch.setattr(
        "src.app.chat_task_parser.ModelAdapter.from_profile",
        lambda **kwargs: WrongRouteModel(),
    )

    parsed = llm_parse_chat_task("请生成腾讯控股 FY2024 公司研报", today=date(2026, 5, 25))

    assert parsed.source == "llm"
    assert parsed.should_run is True
    assert parsed.symbol == "0700.HK"
    assert parsed.period == "FY2024"
    assert parsed.period_kind == "fiscal_year"


def test_parse_unknown_company_does_not_silently_fallback_to_default_symbol():
    parsed = parse_chat_task("请生成海康威视 FY2024 公司研报", current_symbol="AAPL", today=date(2026, 5, 25))

    assert parsed.should_run is False
    assert parsed.needs_confirmation is True
    assert parsed.symbol == ""
    assert parsed.period == "FY2024"
