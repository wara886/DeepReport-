from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportArtifact, ReportTask
from src.services.report_task_service import ReportTaskService


def test_web_report_task_links_are_task_scoped(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add(
            ReportTask(
                task_id="task-links-web",
                symbol="AAPL",
                period="FY2024",
                status="completed",
                current_stage="completed",
            )
        )
        session.add_all(
            [
                ReportArtifact(
                    task_id="task-links-web",
                    artifact_type="html",
                    path=str(tmp_path / "reports" / "runs" / "task-links-web" / "reports" / "report.html"),
                    url="/artifacts/runs/task-links-web/reports/report.html",
                ),
                ReportArtifact(
                    task_id="task-links-web",
                    artifact_type="markdown",
                    path=str(tmp_path / "reports" / "runs" / "task-links-web" / "reports" / "report.md"),
                    url="/artifacts/runs/task-links-web/reports/report.md",
                ),
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
        tasks = client.get("/api/report-tasks")
        page = client.get("/workbench")

    assert tasks.status_code == 200
    task = tasks.json()["items"][0]
    assert task["task_id"] == "task-links-web"
    assert task["report_links"]["html_web_url"] == "/artifacts/runs/task-links-web/reports/report.html"
    assert task["report_links"]["markdown_web_url"] == "/artifacts/runs/task-links-web/reports/report.md"

    assert page.status_code == 200
    html = page.text
    assert '/api/report-tasks/${encodeURIComponent(task.task_id)}/artifacts' in html
    assert '/api/report-tasks/${encodeURIComponent(task.task_id)}' in html
    assert 'id="workbenchNotice"' in html
    assert "showNotice(`研报任务已创建：" in html
    assert "humanReviewText(readiness.human_review_status, readiness.can_enter_human_review)" in html
    assert '/api/report-tasks?limit=200' in html
    assert "const displayRows = rows.slice(0, 30)" in html
