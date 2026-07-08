from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'signal_context.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app)


def test_signal_can_enter_report_task_context(tmp_path):
    with build_client(tmp_path) as client:
        task = client.post(
            "/api/report-tasks",
            json={"task_id": "task-signal-context", "symbol": "AAPL", "period": "FY2024", "run_immediately": False},
        )
        fact = client.post(
            "/api/financial-facts",
            json={
                "company_name": "苹果公司",
                "symbol": "AAPL",
                "metric_name": "毛利率",
                "value": 42.0,
                "unit": "%",
                "period": "FY2024",
                "metadata": {"previous_value": 46.0},
            },
        )
        generated = client.post("/api/investment-signals/generate", json={"company": "AAPL", "period": "FY2024"})
        signal_id = next(item["id"] for item in generated.json()["items"] if item["signal_type"] == "margin_decline")
        linked = client.post(
            f"/api/investment-signals/{signal_id}/add-to-task",
            json={"task_id": "task-signal-context"},
        )
        detail = client.get("/api/report-tasks/task-signal-context")

    assert task.status_code == 201
    assert fact.status_code == 201
    assert generated.status_code == 201
    assert linked.status_code == 200
    assert linked.json()["signal"]["status"] == "in_context"
    context = detail.json()["metadata"]["investment_signals"]
    assert context[0]["type"] == "margin_decline"
    assert context[0]["boundary"] == "仅供研究，不构成投资建议"
