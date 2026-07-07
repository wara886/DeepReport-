import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


class ArtifactWritingOrchestrator:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)

    def run(self, **kwargs):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir / "report.md").write_text("# Report", encoding="utf-8")
        (self.report_dir / "report.html").write_text("<html><body>Report</body></html>", encoding="utf-8")
        (self.report_dir / "report.json").write_text(json.dumps({"title": "Report"}), encoding="utf-8")
        (self.output_dir / "run_summary.json").write_text(
            json.dumps({"symbol": kwargs["symbol"], "period": kwargs["period"]}),
            encoding="utf-8",
        )
        (self.output_dir / "verification_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
        return {"verification_passed": True}


def passing_quality_runner(output_dir, report_dir, **kwargs):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quality_report.json").write_text(
        json.dumps({"objective_pass": True, "total_score": 0.93}),
        encoding="utf-8",
    )
    (output_dir / "delivery_gate.json").write_text(
        json.dumps({"delivery_pass": True, "objective_pass": True, "llm_review_pass": True}),
        encoding="utf-8",
    )
    return {
        "quality_report": {"objective_pass": True, "total_score": 0.93},
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.9, "model_status": "test"},
        "delivery_gate": {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True},
        "top_quality_issues": [],
    }


def test_report_task_artifact_import_links_completed_outputs(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=ArtifactWritingOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-artifacts-001", "symbol": "AAPL", "period": "FY2024"},
        )
        artifacts = client.get("/api/report-tasks/task-artifacts-001/artifacts")

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert artifacts.status_code == 200
    artifact_types = {artifact["artifact_type"] for artifact in artifacts.json()["artifacts"]}
    assert {"markdown", "html", "json", "run_summary", "verification_report", "quality_report", "delivery_gate"}.issubset(artifact_types)
    assert artifacts.json()["report_links"]["html_web_url"].endswith("/runs/task-artifacts-001/reports/report.html")
    assert artifacts.json()["report_links"]["markdown_web_url"].endswith("/runs/task-artifacts-001/reports/report.md")
