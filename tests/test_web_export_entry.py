from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportArtifact, ReportTask
from src.services.report_task_service import ReportTaskService


def test_workbench_exposes_export_center_entry_contract(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add(ReportTask(task_id="task-web-export", symbol="TSLA", period="FY2024", status="completed"))
        session.add(ReportArtifact(task_id="task-web-export", artifact_type="html", path="report.html", url="/artifacts/report.html"))
        session.commit()
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        page = client.get("/workbench")
        exports = client.get("/api/exports")

    assert page.status_code == 200
    html = page.text
    assert "Export Center" in html
    assert 'getJson("/api/exports" + suffix)' in html
    assert 'getJson(`/api/exports/${encodeURIComponent(taskId)}`)' in html
    assert "Official Export" in html
    assert exports.status_code == 200
    assert exports.json()["items"][0]["task_id"] == "task-web-export"
