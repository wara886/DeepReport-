from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'manual-import.db'}",
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


def test_manual_import_text_enters_document_processing_center(tmp_path):
    with build_client(tmp_path) as client:
        imported = client.post(
            "/api/manual-import",
            json={
                "import_type": "text",
                "title": "NVDA FY2024 revenue note",
                "content": "NVIDIA revenue increased significantly in FY2024.",
                "symbol": "NVDA",
                "company_name": "NVIDIA Corporation",
                "period": "FY2024",
            },
        )
        body = imported.json()
        listed = client.get("/api/documents", params={"batch_id": body["batch_id"]})
        detail = client.get(f"/api/documents/{body['document']['id']}")
        duplicate = client.post(
            "/api/manual-import",
            json={
                "import_type": "text",
                "title": "Same content with a different title",
                "content": "NVIDIA revenue increased significantly in FY2024.",
                "symbol": "NVDA",
                "company_name": "NVIDIA Corporation",
                "period": "FY2024",
            },
        )

    assert imported.status_code == 201
    assert body["created"] is True
    assert body["document"]["parse_status"] == "parsed"
    assert body["document"]["doc_type"] == "manual_text"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["title"] == "NVDA FY2024 revenue note"
    steps = detail.json()["processing_steps"]
    assert [step["step_name"] for step in steps] == ["ingest", "parse", "chunk"]
    assert [step["status"] for step in steps] == ["success", "success", "success"]
    assert body["processing_status"] == "evidence_ready"
    assert detail.json()["evidence_count"] == 1
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert duplicate.json()["duplicate"] is True


def test_manual_import_url_requires_source_and_records_link(tmp_path):
    with build_client(tmp_path) as client:
        missing = client.post("/api/manual-import", json={"import_type": "url", "title": "missing url"})
        imported = client.post(
            "/api/manual-import",
            json={
                "import_type": "url",
                "title": "AAPL official filing link",
                "source_url": "https://www.sec.gov/aapl/10-k",
                "symbol": "AAPL",
                "period": "FY2024",
            },
        )
        detail = client.get(f"/api/documents/{imported.json()['document']['id']}")

    assert missing.status_code == 409
    assert imported.status_code == 201
    assert imported.json()["document"]["source_url"] == "https://www.sec.gov/aapl/10-k"
    assert detail.json()["source_url"] == "https://www.sec.gov/aapl/10-k"
    assert imported.json()["processing_status"] == "awaiting_content"
    assert detail.json()["parse_status"] == "pending"
    assert detail.json()["processing_steps"][1]["status"] == "pending"
    assert detail.json()["evidence_count"] == 0


def test_manual_import_reuses_company_when_only_name_is_provided(tmp_path):
    with build_client(tmp_path) as client:
        first = client.post(
            "/api/manual-import",
            json={
                "import_type": "text",
                "title": "Company name only note 1",
                "content": "First note for a private company.",
                "company_name": "Private Research Target",
            },
        )
        second = client.post(
            "/api/manual-import",
            json={
                "import_type": "text",
                "title": "Company name only note 2",
                "content": "Second note for a private company.",
                "company_name": "Private Research Target",
            },
        )
        first_doc = client.get(f"/api/documents/{first.json()['document']['id']}")
        second_doc = client.get(f"/api/documents/{second.json()['document']['id']}")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first_doc.json()["company"]["id"] == second_doc.json()["company"]["id"]
