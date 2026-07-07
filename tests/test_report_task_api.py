import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportTask
from src.services.report_task_service import ReportTaskService


class FakeOrchestrator:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        return {"verification_passed": True, "quality_score": 0.88}


def passing_quality_runner(output_dir, report_dir, **kwargs):
    return {
        "quality_report": {"objective_pass": True, "total_score": 0.91},
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.9, "model_status": "test"},
        "delivery_gate": {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True},
        "top_quality_issues": [],
    }


def build_service(tmp_path):
    return ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=FakeOrchestrator,
        quality_runner=passing_quality_runner,
    )


def build_client(tmp_path):
    service = build_service(tmp_path)
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
                "company_name": "NVIDIA",
                "data_source_scope": "official_first",
                "report_type": "annual_review",
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
    assert body["metadata"]["company_name"] == "NVIDIA"
    assert body["metadata"]["data_source_scope"] == "official_first"
    assert body["metadata"]["report_type"] == "annual_review"

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["task_id"] == "task-api-001"

    assert detail.status_code == 200
    assert detail.json()["events"][0]["stage"] == "queued"


def test_report_task_api_cancel_and_archive_lifecycle(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-api-cancel", "symbol": "AAPL", "period": "FY2024", "run_immediately": False},
        )
        cancelled = client.post("/api/report-tasks/task-api-cancel/cancel", json={"reason": "用户取消"})
        conflict = client.post("/api/report-tasks/task-api-cancel/cancel", json={})
        archived = client.post("/api/report-tasks/task-api-cancel/archive", json={"reason": "清理误建任务"})
        retry_archived = client.post("/api/report-tasks/task-api-cancel/retry", json={})
        archive_again = client.post("/api/report-tasks/task-api-cancel/archive", json={})
        listed = client.get("/api/report-tasks")
        archived_list = client.get("/api/report-tasks", params={"status": "archived"})

    assert created.status_code == 201
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["current_stage"] == "cancelled"
    assert cancelled.json()["events"][-1]["stage"] == "cancelled"
    assert conflict.status_code == 409

    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["metadata"]["archived_from_status"] == "cancelled"
    assert retry_archived.status_code == 409
    assert archive_again.status_code == 409
    assert listed.json()["total"] == 0
    assert archived_list.json()["total"] == 1


def test_report_task_api_rejects_cancel_running_task(tmp_path):
    service = build_service(tmp_path)
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-api-running-cancel", "symbol": "AAPL", "period": "FY2024", "run_immediately": False},
        )
        with service.session() as session:
            task = session.scalar(select(ReportTask).where(ReportTask.task_id == "task-api-running-cancel"))
            assert task is not None
            task.status = "running"
            task.current_stage = "orchestrator"
            session.commit()
        cancelled = client.post("/api/report-tasks/task-api-running-cancel/cancel", json={"reason": "用户取消"})

    assert created.status_code == 201
    assert cancelled.status_code == 409


def test_report_task_api_start_queued_task(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-api-start", "symbol": "MSFT", "period": "FY2024", "run_immediately": False},
        )
        started = client.post("/api/report-tasks/task-api-start/start", json={"run_async": False})

    assert created.status_code == 201
    assert created.json()["status"] == "queued"
    assert started.status_code == 200
    body = started.json()
    assert body["status"] == "completed"
    stages = [event["stage"] for event in body["events"]]
    assert "start" in stages
    assert stages[-1] == "completed"


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
            quality_runner=passing_quality_runner,
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/run", json={"symbol": "TSLA"})

    assert response.status_code == 200
    assert captured == {"path": "/api/run", "method": "POST", "body": {"symbol": "TSLA"}}
