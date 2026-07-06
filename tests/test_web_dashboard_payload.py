from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import EvidenceItem, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def test_web_dashboard_payload_and_page_contract(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add_all(
            [
                ReportTask(task_id="task-dashboard-web", symbol="NVDA", period="FY2024", status="completed"),
                EvidenceItem(evidence_id="ev_dashboard", content="Evidence", source_type="sec_edgar"),
                ReportClaim(task_id="task-dashboard-web", claim_text="Claim", verification_status="supported", review_status="pending"),
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
        page = client.get("/workbench")
        summary = client.get("/api/dashboard/summary")
        funnel = client.get("/api/dashboard/funnel")

    assert page.status_code == 200
    html = page.text
    assert "FinSight Research Workbench" in html
    assert 'getJson("/api/dashboard/summary")' in html
    assert 'getJson("/api/dashboard/funnel")' in html
    assert "/api/report-tasks" in html
    assert "/api/latest" not in html

    assert summary.status_code == 200
    assert summary.json()["evidence_count"] == 1
    assert summary.json()["review_pending_claim_count"] == 1
    assert funnel.status_code == 200
    assert any(step["key"] == "report_claim_generated" for step in funnel.json()["steps"])
