import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


class MinimalReportOrchestrator:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)

    def run(self, **kwargs):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir / "report.md").write_text("# Report\n\nToo thin.", encoding="utf-8")
        (self.report_dir / "report.html").write_text("<html><body>Too thin.</body></html>", encoding="utf-8")
        (self.report_dir / "report.json").write_text(json.dumps({"title": "Report"}), encoding="utf-8")
        (self.output_dir / "run_summary.json").write_text(json.dumps({"symbol": kwargs["symbol"]}), encoding="utf-8")
        (self.output_dir / "verification_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
        return {"verification_passed": True}


def failing_quality_runner(output_dir, report_dir, **kwargs):
    output_dir.mkdir(parents=True, exist_ok=True)
    quality = {"objective_pass": False, "total_score": 0.73}
    llm_review = {"llm_review_pass": False, "total_score": 0.71, "model_status": "test"}
    gate = {"delivery_pass": False, "objective_pass": False, "llm_review_pass": False}
    (output_dir / "quality_report.json").write_text(json.dumps(quality), encoding="utf-8")
    (output_dir / "llm_quality_review.json").write_text(json.dumps(llm_review), encoding="utf-8")
    (output_dir / "delivery_gate.json").write_text(json.dumps(gate), encoding="utf-8")
    return {
        "quality_report": quality,
        "llm_quality_review": llm_review,
        "delivery_gate": gate,
        "top_quality_issues": [{"severity": "blocker", "message": "执行摘要深度不足"}],
    }


def passing_quality_runner(output_dir, report_dir, **kwargs):
    output_dir.mkdir(parents=True, exist_ok=True)
    quality = {"objective_pass": True, "total_score": 0.91}
    gate = {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True}
    (output_dir / "quality_report.json").write_text(json.dumps(quality), encoding="utf-8")
    (output_dir / "delivery_gate.json").write_text(json.dumps(gate), encoding="utf-8")
    return {
        "quality_report": quality,
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.89, "model_status": "test"},
        "delivery_gate": gate,
        "top_quality_issues": [],
    }


def make_client(tmp_path, quality_runner):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=MinimalReportOrchestrator,
        quality_runner=quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app)


def test_report_task_quality_gate_failure_marks_task_as_quality_failed(tmp_path):
    with make_client(tmp_path, failing_quality_runner) as client:
        response = client.post(
            "/api/report-tasks",
            json={"task_id": "task-quality-failed", "symbol": "NVDA", "period": "FY2024"},
        )
        artifacts = client.get("/api/report-tasks/task-quality-failed/artifacts")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "quality_failed"
    assert body["current_stage"] == "quality_failed"
    assert body["quality_score"] == 0.73
    assert body["metadata"]["quality_result"]["delivery_gate"]["delivery_pass"] is False
    quality_events = [event for event in body["events"] if event["stage"] == "quality_gate"]
    assert quality_events[-1]["status"] == "failed"
    assert body["events"][-1]["stage"] == "quality_failed"
    artifact_types = {item["artifact_type"] for item in artifacts.json()["artifacts"]}
    assert {"quality_report", "llm_quality_review", "delivery_gate"}.issubset(artifact_types)


def test_report_task_quality_failed_task_can_be_retried(tmp_path):
    with make_client(tmp_path, failing_quality_runner) as client:
        failed = client.post(
            "/api/report-tasks",
            json={"task_id": "task-quality-retry", "symbol": "NVDA", "period": "FY2024"},
        )

    assert failed.json()["status"] == "quality_failed"

    with make_client(tmp_path, passing_quality_runner) as client:
        retried = client.post("/api/report-tasks/task-quality-retry/retry", json={})

    assert retried.status_code == 200
    body = retried.json()
    assert body["status"] == "completed"
    assert body["quality_score"] == 0.91
    stages = [event["stage"] for event in body["events"]]
    assert "quality_failed" in stages
    assert stages[-1] == "completed"
