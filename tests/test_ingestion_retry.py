from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'ingestion-retry.db'}",
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
    return TestClient(app)


def test_ingestion_retry_resets_failed_batch_for_queue(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post("/api/ingestion-batches", json={"batch_id": "ing-retry", "name": "失败后重试采集"})
        client.post("/api/ingestion-batches/ing-retry/start")
        failed = client.post("/api/ingestion-batches/ing-retry/fail", json={"error_message": "network timeout"})
        retried = client.post("/api/ingestion-batches/ing-retry/retry")
        detail = client.get("/api/ingestion-batches/ing-retry")

    assert created.status_code == 201
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["retry_count"] == 1
    assert retried.json()["error_message"] is None
    retry_events = [event for event in detail.json()["events"] if event["stage"] == "retry"]
    assert retry_events
    assert retry_events[0]["metadata"]["previous_status"] == "failed"
