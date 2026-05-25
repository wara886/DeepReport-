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
    assert parsed.confidence >= 0.72
    assert "600519.SS" in parsed.research_topic


def test_parse_amd_latest_report_request():
    parsed = parse_chat_task("生成 AMD 最新财报研报", today=date(2026, 5, 16))

    assert parsed.should_run is True
    assert parsed.symbol == "AMD"
    assert parsed.period == "2026Q1"


def test_parse_english_generate_latest_report_request():
    parsed = parse_chat_task("generate 600519 latest company report", today=date(2026, 5, 16))

    assert parsed.should_run is True
    assert parsed.symbol == "600519.SS"
    assert parsed.period == "2026Q1"


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


def test_parse_complete_chinese_report_sentence_runs_without_confirmation():
    parsed = parse_chat_task("2025\u5e74Q3\u82f1\u4f1f\u8fbe\u516c\u53f8\u8d22\u62a5", today=date(2026, 5, 22))

    assert parsed.symbol == "NVDA"
    assert parsed.period == "2025Q3"
    assert parsed.should_run is True
    assert parsed.needs_confirmation is False
    assert "直接生成" in parsed.reason


def test_parse_report_question_without_generation_needs_confirmation():
    parsed = parse_chat_task("AMD 研报怎么样", current_symbol="AAPL", current_period="2025Q4", today=date(2026, 5, 16))

    assert parsed.should_run is False
    assert parsed.needs_confirmation is True
    assert parsed.symbol == "AMD"
    assert parsed.period == "2025Q4"


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


def test_parse_year_only_financial_report_as_annual_period():
    parsed = parse_chat_task("生成特斯拉26年财报研报", today=date(2026, 5, 19))

    assert parsed.should_run is True
    assert parsed.symbol == "TSLA"
    assert parsed.period == "2026Q4"


@pytest.mark.parametrize(
    ("company_name", "symbol"),
    [
        ("\u82f9\u679c", "AAPL"),
        ("\u5fae\u8f6f", "MSFT"),
        ("\u8c37\u6b4c", "GOOGL"),
        ("\u82f1\u4f1f\u8fbe", "NVDA"),
        ("\u8d85\u5fae\u534a\u5bfc\u4f53", "AMD"),
        ("\u7279\u65af\u62c9", "TSLA"),
        ("\u5546\u6c64\u79d1\u6280", "0020.HK"),
        ("\u7b2c\u56db\u8303\u5f0f", "6682.HK"),
        ("\u817e\u8baf\u63a7\u80a1", "0700.HK"),
        ("\u5c0f\u7c73\u96c6\u56e2", "1810.HK"),
        ("\u7f8e\u56e2", "3690.HK"),
        ("\u767e\u5ea6\u96c6\u56e2", "9888.HK"),
        ("\u8d35\u5dde\u8305\u53f0", "600519.SS"),
        ("\u5b81\u5fb7\u65f6\u4ee3", "300750.SZ"),
        ("\u6bd4\u4e9a\u8fea", "002594.SZ"),
        ("\u4e2d\u56fd\u5e73\u5b89", "601318.SS"),
        ("\u62db\u5546\u94f6\u884c", "600036.SS"),
        ("\u4e2d\u82af\u56fd\u9645", "688981.SS"),
    ],
)
def test_parse_formal18_company_names_and_fiscal_year(company_name, symbol):
    parsed = parse_chat_task(f"\u8bf7\u751f\u6210{company_name} FY2024 \u516c\u53f8\u7814\u62a5", today=date(2026, 5, 25))

    assert parsed.should_run is True
    assert parsed.symbol == symbol
    assert parsed.period == "2024Q4"


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
    assert parsed.period == "2024Q4"


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
        "src.app.chat_task_parser.ModelAdapter.from_config",
        lambda **kwargs: WrongRouteModel(),
    )

    parsed = llm_parse_chat_task("\u8bf7\u751f\u6210\u817e\u8baf\u63a7\u80a1 FY2024 \u516c\u53f8\u7814\u62a5", today=date(2026, 5, 25))

    assert parsed.source == "llm"
    assert parsed.should_run is True
    assert parsed.symbol == "0700.HK"
    assert parsed.period == "2024Q4"
