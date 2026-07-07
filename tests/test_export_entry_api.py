from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportArtifact, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def build_export_client(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
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
    return service, TestClient(app)


def seed_export_task(service, *, rejected=False, pending=False):
    with service.session() as session:
        task = ReportTask(task_id="task-export", symbol="NVDA", period="FY2024", status="completed", quality_score=0.92)
        session.add(task)
        session.add_all(
            [
                ReportArtifact(task_id="task-export", artifact_type="html", path="report.html", url="/artifacts/report.html"),
                ReportArtifact(task_id="task-export", artifact_type="markdown", path="report.md", url="/artifacts/report.md"),
                ReportArtifact(task_id="task-export", artifact_type="json", path="report.json", url="/artifacts/report.json"),
                ReportArtifact(task_id="task-export", artifact_type="claims", path="claims.json", url="/artifacts/claims.json"),
                ReportArtifact(task_id="task-export", artifact_type="evidence", path="evidence.json", url="/artifacts/evidence.json"),
                ReportArtifact(
                    task_id="task-export",
                    artifact_type="verification_report",
                    path="verification_report.json",
                    url="/artifacts/verification_report.json",
                ),
                ReportClaim(task_id="task-export", claim_text="Approved claim.", review_status="approved"),
            ]
        )
        if rejected:
            session.add(ReportClaim(task_id="task-export", claim_text="Rejected claim.", review_status="rejected"))
        if pending:
            session.add(ReportClaim(task_id="task-export", claim_text="Pending claim.", review_status="pending"))
        session.commit()


def test_export_entry_api_reports_artifacts_and_readiness(temp_db_engine, tmp_path):
    service, client = build_export_client(temp_db_engine, tmp_path)
    seed_export_task(service)

    with client:
        listed = client.get("/api/exports")
        detail = client.get("/api/exports/task-export")
        missing = client.get("/api/exports/missing-task")

    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["task_id"] == "task-export"
    assert item["artifact_count"] == 6
    assert item["review_status_counts"] == {"approved": 1}
    assert item["official_export_ready"] is True
    assert item["blocked_reasons"] == []

    assert detail.status_code == 200
    assert [artifact["artifact_type"] for artifact in detail.json()["artifacts"]] == [
        "html",
        "markdown",
        "json",
        "claims",
        "evidence",
        "verification_report",
    ]
    assert detail.json()["claims"][0]["review_status"] == "approved"
    assert missing.status_code == 404


def test_export_entry_blocks_rejected_and_pending_claims(temp_db_engine, tmp_path):
    service, client = build_export_client(temp_db_engine, tmp_path)
    seed_export_task(service, rejected=True, pending=True)

    with client:
        response = client.get("/api/exports/task-export")

    assert response.status_code == 200
    body = response.json()
    assert body["official_export_ready"] is False
    assert body["rejected_claim_count"] == 1
    assert body["pending_claim_count"] == 1
    assert body["blocked_reasons"] == ["rejected_claims_present", "pending_claim_review"]
