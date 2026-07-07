from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'ingestion.db'}",
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


def test_ingestion_batch_create_start_fail_retry_and_complete(tmp_path):
    with build_client(tmp_path) as client:
        client.post("/api/data-sources", json={"source_key": "sec_edgar"})
        created = client.post(
            "/api/ingestion-batches",
            json={
                "batch_id": "ing-sec-nvda",
                "name": "NVDA FY2024 年报采集",
                "source_key": "sec_edgar",
                "target_type": "filings",
                "symbol": "NVDA",
                "period": "FY2024",
                "query": "NVDA 10-K FY2024",
            },
        )
        started = client.post("/api/ingestion-batches/ing-sec-nvda/start")
        failed = client.post(
            "/api/ingestion-batches/ing-sec-nvda/fail",
            json={"error_message": "rate limited", "item_count": 3, "success_count": 1, "failed_count": 2},
        )
        source_after_fail = client.get("/api/data-sources/sec_edgar")
        retried = client.post("/api/ingestion-batches/ing-sec-nvda/retry")
        restarted = client.post("/api/ingestion-batches/ing-sec-nvda/start")
        completed = client.post(
            "/api/ingestion-batches/ing-sec-nvda/complete",
            json={"item_count": 4, "success_count": 4, "failed_count": 0},
        )
        detail = client.get("/api/ingestion-batches/ing-sec-nvda")
        listed = client.get("/api/ingestion-batches", params={"status": "completed"})
        source_after_complete = client.get("/api/data-sources/sec_edgar")

    assert created.status_code == 201
    assert created.json()["status"] == "queued"
    assert created.json()["source_name"] == "美国证监会年报"
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["error_message"] == "rate limited"
    assert source_after_fail.json()["last_status"] == "failed"
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["retry_count"] == 1
    assert restarted.status_code == 200
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["success_count"] == 4
    assert completed.json()["failed_count"] == 0
    assert detail.status_code == 200
    assert [event["stage"] for event in detail.json()["events"]] == ["created", "run", "run", "retry", "run", "run"]
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["batch_id"] == "ing-sec-nvda"
    assert source_after_complete.json()["last_status"] == "success"
    assert source_after_complete.json()["last_error"] is None


def test_ingestion_batch_rejects_invalid_transitions(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post("/api/ingestion-batches", json={"batch_id": "ing-invalid", "name": "测试采集"})
        completed = client.post("/api/ingestion-batches/ing-invalid/complete", json={})
        retry = client.post("/api/ingestion-batches/ing-invalid/retry")
        cancel = client.post("/api/ingestion-batches/ing-invalid/cancel", json={"reason": "no longer needed"})

    assert created.status_code == 201
    assert completed.status_code == 200
    assert retry.status_code == 409
    assert cancel.status_code == 409
