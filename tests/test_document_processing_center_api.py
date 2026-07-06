from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import (
    ClaimEvidence,
    Company,
    Document,
    DocumentProcessingStep,
    EvidenceItem,
    ReportClaim,
    ReportTask,
)
from src.services.report_task_service import ReportTaskService


def build_document_client(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
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
    return service, TestClient(app)


def seed_document_processing(service):
    with service.session() as session:
        company = Company(name="Apple Inc.", symbol="AAPL", market="US")
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            batch_id="batch-doc-001",
            title="AAPL FY2024 10-K",
            doc_type="10-K",
            report_period="FY2024",
            source_url="https://example.com/aapl-10k",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                DocumentProcessingStep(
                    document_id=document.id,
                    step_name="ingest",
                    status="success",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"source": "sec_edgar"},
                ),
                DocumentProcessingStep(
                    document_id=document.id,
                    step_name="table_extract",
                    status="failed",
                    started_at=now,
                    finished_at=now,
                    error_message="No table parser available",
                    metadata_json={"parser": "p0_stub"},
                ),
            ]
        )
        evidence = EvidenceItem(
            evidence_id="ev_doc_aapl",
            document_id=document.id,
            company_id=company.id,
            content="AAPL disclosed revenue by segment.",
            source_type="sec_edgar",
            trust_level="official",
            page_no=17,
        )
        claim = ReportClaim(task_id="task-doc", claim_text="AAPL disclosed segment revenue.", review_status="pending")
        session.add_all([ReportTask(task_id="task-doc", symbol="AAPL", period="FY2024"), evidence, claim])
        session.flush()
        session.add(ClaimEvidence(claim_id=claim.id, evidence_item_id=evidence.id))
        session.commit()
        return document.id


def test_document_processing_center_api_lists_and_details_steps(temp_db_engine, tmp_path):
    service, client = build_document_client(temp_db_engine, tmp_path)
    document_id = seed_document_processing(service)

    with client:
        listed = client.get("/api/documents", params={"company": "AAPL", "batch_id": "batch-doc-001"})
        detail = client.get(f"/api/documents/{document_id}")
        missing = client.get("/api/documents/99999")

    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["title"] == "AAPL FY2024 10-K"
    assert item["company"]["symbol"] == "AAPL"
    assert item["step_count"] == 2
    assert item["failed_step_count"] == 1
    assert item["evidence_count"] == 1
    assert item["claim_count"] == 1

    assert detail.status_code == 200
    body = detail.json()
    assert [step["step_name"] for step in body["processing_steps"]] == ["ingest", "table_extract"]
    assert body["processing_steps"][1]["status"] == "failed"
    assert body["processing_steps"][1]["error_message"] == "No table parser available"
    assert body["evidence"][0]["evidence_id"] == "ev_doc_aapl"
    assert body["claims"][0]["task_id"] == "task-doc"
    assert missing.status_code == 404
