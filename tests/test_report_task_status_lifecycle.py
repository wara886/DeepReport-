from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportTask
from src.services.report_task_service import ReportTaskService


class SuccessfulOrchestrator:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        return {"verification_passed": True}


class FailingThenSuccessfulOrchestrator:
    calls = 0

    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        type(self).calls += 1
        if type(self).calls == 1:
            raise RuntimeError("upstream model failed")
        return {"verification_passed": True}


def passing_quality_runner(output_dir, report_dir, **kwargs):
    return {
        "quality_report": {"objective_pass": True, "total_score": 0.9},
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.88, "model_status": "test"},
        "delivery_gate": {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True},
        "top_quality_issues": [],
    }


def make_client(tmp_path, orchestrator_factory):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=orchestrator_factory,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app)


def test_report_task_status_lifecycle_records_events(tmp_path):
    with make_client(tmp_path, SuccessfulOrchestrator) as client:
        response = client.post(
            "/api/report-tasks",
            json={"task_id": "task-lifecycle-001", "symbol": "MSFT", "period": "FY2024", "run_immediately": True},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["current_stage"] == "completed"
    assert body["started_at"]
    assert body["finished_at"]
    stages = [event["stage"] for event in body["events"]]
    expected_order = [
        "queued",
        "runtime_start",
        "official_evidence_backfill",
        "evidence_gate",
        "build_canonical_metrics",
        "build_section_evidence_packs",
        "orchestrator",
        "inspect_agent_execution",
        "verify_sections",
        "repair_failed_sections",
        "quality_gate",
        "completed",
    ]
    positions = [stages.index(stage) for stage in expected_order]
    assert positions == sorted(positions)
    assert stages.count("orchestrator") == 2
    assert "artifact_import" in stages
    assert "quality_gate" in stages
    assert stages[-1] == "completed"
    assert [event["status"] for event in body["events"]][-1] == "completed"


def test_report_task_retry_moves_failed_task_back_to_completed(tmp_path):
    FailingThenSuccessfulOrchestrator.calls = 0
    with make_client(tmp_path, FailingThenSuccessfulOrchestrator) as client:
        failed = client.post(
            "/api/report-tasks",
            json={"task_id": "task-retry-001", "symbol": "TSLA", "period": "FY2024", "run_immediately": True},
        )
        retried = client.post("/api/report-tasks/task-retry-001/retry", json={})

    assert failed.status_code == 201
    assert failed.json()["status"] == "failed"
    assert "upstream model failed" in failed.json()["error_message"]

    assert retried.status_code == 200
    body = retried.json()
    assert body["status"] == "completed"
    stages = [event["stage"] for event in body["events"]]
    assert "failed" in stages
    assert "retry" in stages
    assert stages[-1] == "completed"


def test_startup_recovers_only_stale_running_tasks(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=SuccessfulOrchestrator,
        quality_runner=passing_quality_runner,
    )
    service.create_task({"task_id": "stale-task", "symbol": "MSFT", "period": "FY2024"})
    service.create_task({"task_id": "fresh-task", "symbol": "NVDA", "period": "FY2024"})
    with service.session() as session:
        stale = session.scalar(select(ReportTask).where(ReportTask.task_id == "stale-task"))
        fresh = session.scalar(select(ReportTask).where(ReportTask.task_id == "fresh-task"))
        assert stale is not None and fresh is not None
        for task in (stale, fresh):
            task.status = "running"
            task.current_stage = "agent_browser"
        stale.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
        fresh.started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.commit()

    recovered = service.recover_stale_running_tasks(max_age_minutes=60)

    assert recovered == ["stale-task"]
    stale_result = service.get_task("stale-task")
    fresh_result = service.get_task("fresh-task")
    assert stale_result["status"] == "timeout"
    assert stale_result["current_stage"] == "timeout"
    assert stale_result["metadata"]["runtime_failure"]["checkpoint_available"] is True
    assert stale_result["events"][-1]["metadata"]["previous_stage"] == "agent_browser"
    assert fresh_result["status"] == "running"
