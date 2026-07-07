from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'manual-import-pdf.db'}",
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


def test_manual_import_pdf_stub_creates_pending_parse_document(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%stub\n")

    with build_client(tmp_path) as client:
        imported = client.post(
            "/api/manual-import",
            json={
                "import_type": "pdf",
                "title": "AAPL FY2024 annual report PDF",
                "file_path": str(pdf_path),
                "symbol": "AAPL",
                "company_name": "Apple Inc.",
                "period": "FY2024",
            },
        )
        body = imported.json()
        detail = client.get(f"/api/documents/{body['document']['id']}")
        batch = client.get(f"/api/ingestion-batches/{body['batch_id']}")

    assert imported.status_code == 201
    assert body["document"]["doc_type"] == "manual_pdf"
    assert body["document"]["file_path"] == str(pdf_path)
    assert body["document"]["parse_status"] == "pending"
    steps = detail.json()["processing_steps"]
    assert [step["step_name"] for step in steps] == ["ingest", "parse"]
    assert steps[0]["status"] == "success"
    assert steps[1]["status"] == "pending"
    assert steps[1]["metadata"]["requires_parser"] is True
    assert batch.status_code == 200
    assert batch.json()["source_key"] == "manual_import"
    assert batch.json()["status"] == "completed"
