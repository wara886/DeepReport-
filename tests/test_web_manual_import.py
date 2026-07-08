from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.app.workbench_frontend import render_workbench_html
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'web-manual-import.db'}",
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


def test_workbench_manual_import_page_contract(tmp_path):
    html = render_workbench_html()

    assert 'data-view="manual"' in html
    assert 'id="manualImportType"' in html
    assert 'id="submitManualImport"' in html
    assert 'postJson("/api/manual-import", payload)' in html
    assert 'activateView("documents")' in html
    assert 'loadDocuments();\n          if (doc.id) loadDocumentDetail(doc.id);' in html
    assert 'activateView("ingestion")' in html

    with build_client(tmp_path) as client:
        page = client.get("/workbench")
        imported = client.post(
            "/api/manual-import",
            json={
                "import_type": "text",
                "title": "Workbench manual import contract",
                "content": "Manual import should appear in document center.",
                "symbol": "MSFT",
                "period": "FY2024",
            },
        )
        documents = client.get("/api/documents", params={"batch_id": imported.json()["batch_id"]})

    assert page.status_code == 200
    assert "手动导入" in page.text
    assert imported.status_code == 201
    assert imported.json()["document"]["title"] == "Workbench manual import contract"
    assert documents.status_code == 200
    assert documents.json()["total"] == 1
