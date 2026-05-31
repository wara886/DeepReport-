from src.agents.final_answer_agent import _append_currency_gate_note
from src.report.html_report_generator import render_professional_html_report


def test_cross_currency_note_rendered():
    markdown = _append_currency_gate_note(
        "# 报告",
        {
            "statement_currency": "CNY",
            "trading_currency": "HKD",
            "display_currency": "CNY",
            "blockers": ["official_source_missing_for_non_us_annual"],
            "warnings": [],
        },
        {"valuation_status": "degraded_due_to_unverified_financial_currency"},
    )
    assert "财务报表货币：CNY" in markdown
    assert "交易货币：HKD" in markdown


def test_degraded_html_confidence_is_not_95():
    html = render_professional_html_report(
        markdown="# 报告\n\n## 执行摘要\n\n内容",
        title="测试报告",
        charts=[{"chart_id": "a", "chart_js": {"labels": ["收入", "利润"], "data": [1, 2]}}],
        citations=[{"title": "x"} for _ in range(20)],
        delivery_status="degraded_due_to_currency_quality",
    )
    assert "68%" in html
    assert "95%" not in html
