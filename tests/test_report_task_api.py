from fastapi.testclient import TestClient
from sqlalchemy import select

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportArtifact, ReportClaim, ReportTask
from src.runtime.report_run_state import apply_report_transition
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
    assert body["metadata"]["execution_mode"] == "static"
    assert body["metadata"]["enable_remote_data"] is False

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["task_id"] == "task-api-001"

    assert detail.status_code == 200
    assert detail.json()["events"][0]["stage"] == "queued"


def test_report_task_allows_explicit_offline_mode(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-api-offline",
                "symbol": "MSFT",
                "period": "FY2024",
                "enable_remote_data": False,
                "run_immediately": False,
            },
        )

    assert created.status_code == 201
    assert created.json()["metadata"]["enable_remote_data"] is False


def test_production_report_task_defaults_to_remote_sources(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'production-tasks.db'}",
        output_root=tmp_path / "production-outputs",
        report_root=tmp_path / "production-reports",
        memory_root=tmp_path / "production-memory",
    )

    task = service.create_task({"task_id": "task-production-default", "symbol": "MSFT", "period": "FY2024"})

    assert task["metadata"]["enable_remote_data"] is True


def test_report_task_can_explicitly_select_diagnostic_orchestrator_mode(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-explicit-collaborative",
                "symbol": "AAPL",
                "period": "FY2024",
                "execution_mode": "collaborative",
                "run_immediately": False,
            },
        )

    assert created.status_code == 201
    assert created.json()["metadata"]["execution_mode"] == "collaborative"


def test_report_task_api_accepts_auto_run_false_alias(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-api-auto-run-alias", "symbol": "AAPL", "period": "FY2024", "auto_run": False},
        )
        cancelled = client.post("/api/report-tasks/task-api-auto-run-alias/cancel", json={"reason": "不再生成"})

    assert created.status_code == 201
    assert created.json()["status"] == "queued"
    assert created.json()["started_at"] is None
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_report_task_binds_default_workspace_and_existing_company(tmp_path):
    with build_client(tmp_path) as client:
        workspace = client.post("/api/workspaces", json={"name": "默认投研空间", "slug": "default"}).json()
        company = client.post(
            f"/api/workspaces/{workspace['id']}/companies",
            json={"name": "Apple Inc.", "symbol": "AAPL", "market": "US"},
        ).json()
        task = client.post(
            "/api/report-tasks",
            json={"task_id": "task-bound", "symbol": "AAPL", "period": "FY2024"},
        ).json()

    assert task["workspace_id"] == workspace["id"]
    assert task["company_id"] == company["company_id"]
    assert task["metadata"]["company_name"] == "Apple Inc."


def test_report_task_api_defaults_to_queue_only_and_exposes_runtime_readiness(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-api-queue-default", "symbol": "AAPL", "period": "FY2024"},
        )

    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "queued"
    assert body["started_at"] is None
    assert body["workspace_id"] is not None
    assert body["company_id"] is not None
    assert body["run_state"]["run_mode"] == "queue_only"
    assert body["run_state"]["lifecycle_status"] == "queued"
    assert body["delivery_readiness"]["can_generate_draft"] is True
    assert body["delivery_readiness"]["can_deliver_formal_report"] is False
    assert body["export_readiness"]["can_export_formal_package"] is False


def test_report_task_records_live_agent_stage(tmp_path):
    service = build_service(tmp_path)
    service.create_task({"task_id": "task-live-agent", "symbol": "AAPL", "period": "FY2024"})

    service._record_agent_stage(
        "task-live-agent",
        {
            "phase": "started",
            "agent_key": "research",
            "agent_name": "DeepResearcherAgent",
            "task_type": "deep_researcher",
            "model_name": "test-model",
            "provider": "test",
        },
    )
    service._record_agent_stage(
        "task-live-agent",
        {
            "phase": "finished",
            "agent_key": "research",
            "agent_name": "DeepResearcherAgent",
            "task_type": "deep_researcher",
            "status": "completed",
            "duration_ms": 125,
            "react_used": True,
        },
    )

    task = service.get_task("task-live-agent")
    agent_events = [item for item in task["events"] if item["stage"] == "agent.research"]
    assert task["current_stage"] == "agent_research"
    assert [item["status"] for item in agent_events] == ["running", "success"]
    current = task["metadata"]["report_runtime"]["current_agent"]
    assert current["agent_key"] == "research"
    assert current["duration_ms"] == 125
    assert current["react_used"] is True


def test_task_evaluation_and_export_share_readiness_after_claim_review(tmp_path):
    service = build_service(tmp_path)
    service.create_task({"task_id": "task-readiness-shared", "symbol": "NVDA", "period": "FY2024"})
    with service.session() as session:
        task = session.scalar(select(ReportTask).where(ReportTask.task_id == "task-readiness-shared"))
        assert task is not None
        apply_report_transition(task, "evidence_checking")
        apply_report_transition(task, "generating")
        apply_report_transition(task, "quality_checking")
        apply_report_transition(task, "generation_completed")
        metadata = dict(task.metadata_json or {})
        metadata["pre_generation_evidence_gate"] = {
            "status": "success",
            "blocked": False,
            "draft_ready": True,
            "delivery_ready": True,
        }
        metadata["quality_result"] = {"delivery_gate": {"delivery_pass": True}, "top_quality_issues": []}
        task.metadata_json = metadata
        task.quality_score = 0.92
        session.add(ReportArtifact(task_id=task.task_id, artifact_type="markdown", path="report.md"))
        claim = ReportClaim(
            task_id=task.task_id,
            claim_text="Revenue increased.",
            review_status="pending",
            verification_status="supported",
        )
        session.add(claim)
        session.commit()
        claim_id = claim.id

    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    with TestClient(app) as client:
        task_before = client.get("/api/report-tasks/task-readiness-shared").json()
        export_before = client.get("/api/exports/task-readiness-shared").json()
        evaluation_before = client.get("/api/evaluation/summary").json()
        approved = client.post(f"/api/claims/{claim_id}/approve", json={"reviewer": "analyst"})
        task_after = client.get("/api/report-tasks/task-readiness-shared").json()
        export_after = client.get("/api/exports/task-readiness-shared").json()
        evaluation = client.get("/api/evaluation/summary").json()

    assert task_before["delivery_readiness"]["can_deliver_formal_report"] is False
    assert export_before["official_export_ready"] is False
    assert task_before["delivery_readiness"]["blocking_reasons"] == export_before["blocked_reasons"]
    assert evaluation_before["metrics"]["machine_quality_pass_count"] == 1
    assert evaluation_before["metrics"]["formal_delivery_pass_count"] == 0
    assert evaluation_before["metrics"]["delivery_pass_count"] == 0
    assert approved.status_code == 200
    assert task_after["delivery_readiness"]["can_deliver_formal_report"] is True
    assert export_after["official_export_ready"] is True
    assert task_after["delivery_readiness"]["blocking_reasons"] == export_after["blocked_reasons"] == []
    assert evaluation["metrics"]["delivery_pass_count"] == 1
    assert evaluation["metrics"]["machine_quality_pass_count"] == 1
    assert evaluation["metrics"]["formal_delivery_pass_count"] == 1


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


def test_report_task_api_bulk_archives_only_failed_tasks(tmp_path):
    service = build_service(tmp_path)
    with service.session() as session:
        session.add_all(
            [
                ReportTask(task_id="task-bulk-failed", symbol="AAPL", period="FY2024", status="failed"),
                ReportTask(task_id="task-bulk-review", symbol="NVDA", period="FY2024", status="completed"),
                ReportTask(task_id="task-bulk-running", symbol="TSLA", period="FY2024", status="running"),
            ]
        )
        session.commit()
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/report-tasks/bulk-archive-failed",
            json={"task_ids": ["task-bulk-failed", "task-bulk-review", "task-bulk-running"]},
        )
        failed = client.get("/api/report-tasks/task-bulk-failed")
        review = client.get("/api/report-tasks/task-bulk-review")
        running = client.get("/api/report-tasks/task-bulk-running")

    assert response.status_code == 200
    assert response.json()["archived_task_ids"] == ["task-bulk-failed"]
    assert response.json()["skipped_count"] == 2
    assert failed.json()["status"] == "archived"
    assert review.json()["status"] == "completed"
    assert running.json()["status"] == "running"


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
            json={
                "task_id": "task-api-start",
                "symbol": "MSFT",
                "period": "FY2024",
                "enable_remote_data": False,
                "run_immediately": False,
            },
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
