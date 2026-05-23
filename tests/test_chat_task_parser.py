from datetime import date

from src.app.chat_task_parser import latest_available_report_period, latest_completed_period, parse_chat_task


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
