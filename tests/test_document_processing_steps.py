from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import Document, DocumentProcessingStep
from src.services.report_task_service import ReportTaskService


def test_document_processing_steps_filter_by_step_name(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        doc_ok = Document(title="Parsed document", parse_status="parsed", batch_id="batch-a")
        doc_failed = Document(title="Failed table document", parse_status="parsed", batch_id="batch-b")
        session.add_all([doc_ok, doc_failed])
        session.flush()
        session.add_all(
            [
                DocumentProcessingStep(document_id=doc_ok.id, step_name="parse", status="success"),
                DocumentProcessingStep(document_id=doc_failed.id, step_name="table_extract", status="failed"),
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
        response = client.get("/api/documents", params={"step": "table_extract"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Failed table document"
    assert body["items"][0]["latest_step"]["step_name"] == "table_extract"
    assert body["items"][0]["latest_step"]["status"] == "failed"
