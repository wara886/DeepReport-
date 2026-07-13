from datetime import date

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_period_service import report_period_options
from src.services.report_task_service import ReportTaskService


def test_period_options_cover_recent_quarters_years_and_market_readiness():
    as_of = date(2026, 7, 13)
    us = report_period_options(symbol="AAPL", as_of=as_of)
    cn = report_period_options(symbol="600519.SS", period="2026Q2", as_of=as_of)
    hk = report_period_options(symbol="0700.HK", period="2026Q1", as_of=as_of)

    assert us["latest_completed_quarter"] == "2026Q2"
    assert us["latest_fiscal_year"] == "FY2025"
    assert len([item for item in us["options"] if item["kind"] == "quarter"]) == 8
    assert len([item for item in us["options"] if item["kind"] == "fiscal_year"]) == 5
    assert us["options"][0]["readiness"]["status"] == "scheduled"
    assert us["options"][0]["readiness"]["available_from"] == "2026-08-14"
    assert next(item for item in us["options"] if item["value"] == "FY2025")["readiness"]["official_disclosure_available"] is True
    assert cn["selected"]["readiness"]["available_from"] == "2026-08-31"
    assert cn["selected"]["readiness"]["official_disclosure_available"] is False
    assert hk["selected"]["readiness"]["status"] == "not_standard"
    assert "港股通常不强制披露" in hk["selected"]["readiness"]["reason"]


def test_report_period_api_and_task_creation_reject_invalid_period(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    app = create_fastapi_app(report_task_service=service)

    with TestClient(app) as client:
        response = client.get("/api/report-periods", params={"symbol": "0700.HK", "period": "2026Q2", "as_of": "2026-07-13"})
        invalid_date = client.get("/api/report-periods", params={"as_of": "13-07-2026"})
        invalid_period = client.post("/api/report-tasks", json={"symbol": "AAPL", "period": "最近一年"})

    assert response.status_code == 200
    assert response.json()["market"] == "hk"
    assert response.json()["selected"]["readiness"]["expected_official_source"] == "港交所披露"
    assert invalid_date.status_code == 422
    assert invalid_period.status_code == 422


def test_workbench_uses_dynamic_period_options_and_custom_period():
    from src.app.workbench_frontend import render_workbench_html

    html = render_workbench_html()
    assert 'getJson(`/api/report-periods?symbol=' in html
    assert "最近 8 个完整季度" in html
    assert "最近 5 个财年" in html
    assert "自定义期间" in html
    assert "目标分析期" in html
    assert "行情时点" in html
    assert '<option value="FY2024">FY2024</option>' not in html
    assert "最近一年" not in html
