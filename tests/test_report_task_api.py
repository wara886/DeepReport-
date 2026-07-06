import json

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


class FakeOrchestrator:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        return {"verification_passed": True, "quality_score": 0.88}


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=FakeOrchestrator,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app)


def test_report_task_api_create_list_detail_without_running(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-api-001",
                "symbol": "nvda",
                "period": "FY2024",
                "research_topic": "Generate NVDA FY2024 report",
                "run_immediately": False,
            },
        )
        listed = client.get("/api/report-tasks")
        detail = client.get("/api/report-tasks/task-api-001")

    assert created.status_code == 201
    body = created.json()
    assert body["task_id"] == "task-api-001"
    assert body["symbol"] == "NVDA"
    assert body["status"] == "queued"
    assert body["metadata"]["research_topic"] == "Generate NVDA FY2024 report"

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["task_id"] == "task-api-001"

    assert detail.status_code == 200
    assert detail.json()["events"][0]["stage"] == "queued"


def test_report_task_api_preserves_legacy_run_route(monkeypatch, tmp_path):
    captured = {}

    def fake_forward(app, path, *, method, body=None):
        captured["path"] = path
        captured["method"] = method
        captured["body"] = json.loads(body.decode("utf-8"))
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True})

    monkeypatch.setattr("src.app.api_fastapi._forward", fake_forward)
    app = create_fastapi_app(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        memory_root=str(tmp_path / "memory"),
        report_task_service=ReportTaskService(
            database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
            output_root=tmp_path / "task_outputs",
            report_root=tmp_path / "task_reports",
            orchestrator_factory=FakeOrchestrator,
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/run", json={"symbol": "TSLA"})

    assert response.status_code == 200
    assert captured == {"path": "/api/run", "method": "POST", "body": {"symbol": "TSLA"}}
