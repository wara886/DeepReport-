from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def test_workbench_exposes_claim_review_contract(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add(ReportTask(task_id="task-web-claim", symbol="MSFT", period="FY2024", status="completed"))
        session.add(ReportClaim(task_id="task-web-claim", claim_text="A claim for review.", review_status="pending"))
        session.commit()
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        page = client.get("/workbench")
        claims = client.get("/api/claims")

    assert page.status_code == 200
    html = page.text
    assert "主张复核" in html
    assert 'getJson("/api/claims" + suffix)' in html
    assert 'postJson(`/api/claims/${encodeURIComponent(claimId)}/${encodeURIComponent(action)}`' in html
    assert "通过" in html
    assert "驳回" in html
    assert "重生成" in html
    assert "批量通过有证据支持的主张" in html
    assert "/claims/approve-supported" in html
    assert claims.status_code == 200
    assert claims.json()["items"][0]["claim_text"] == "A claim for review."
