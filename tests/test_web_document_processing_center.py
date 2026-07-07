from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import Document, DocumentProcessingStep
from src.services.report_task_service import ReportTaskService


def test_workbench_exposes_document_processing_center_contract(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        document = Document(title="Document web contract", parse_status="parsed", batch_id="batch-web")
        session.add(document)
        session.flush()
        session.add(DocumentProcessingStep(document_id=document.id, step_name="parse", status="success"))
        session.commit()
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        page = client.get("/workbench")
        documents = client.get("/api/documents")

    assert page.status_code == 200
    html = page.text
    assert "文档处理中心" in html
    assert 'getJson("/api/documents" + suffix)' in html
    assert 'getJson(`/api/documents/${encodeURIComponent(documentId)}`)' in html
    assert "处理路径" in html
    assert documents.status_code == 200
    assert documents.json()["items"][0]["title"] == "Document web contract"
