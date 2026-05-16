from datetime import date

from src.app.chat_task_parser import latest_completed_period, parse_chat_task


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
