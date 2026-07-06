from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ClaimEvidence, Document, DocumentProcessingStep, EvidenceItem, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def test_dashboard_funnel_counts_database_steps(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        document = Document(title="10-K", parse_status="parsed")
        evidence = EvidenceItem(evidence_id="ev_fin", content="Revenue evidence")
        claim = ReportClaim(
            task_id="task-funnel",
            claim_text="Revenue improved.",
            claim_type="financial",
            verification_status="supported",
            review_status="pending",
        )
        signal = ReportClaim(
            task_id="task-funnel",
            claim_text="Cash flow signal.",
            claim_type="signal",
            verification_status="pending",
            review_status="pending",
        )
        session.add_all([ReportTask(task_id="task-funnel", symbol="AAPL", period="FY2024"), document, evidence, claim, signal])
        session.flush()
        session.add_all(
            [
                DocumentProcessingStep(document_id=document.id, step_name="table_extract", status="success"),
                DocumentProcessingStep(document_id=document.id, step_name="chunk_vectorize", status="success"),
                ClaimEvidence(claim_id=claim.id, evidence_item_id=evidence.id, support_type="supports"),
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
        response = client.get("/api/dashboard/funnel")

    assert response.status_code == 200
    steps = {item["key"]: item["count"] for item in response.json()["steps"]}
    assert steps == {
        "document_ingested": 1,
        "parse_success": 1,
        "table_extract_success": 1,
        "chunk_vectorized": 1,
        "financial_fact_extracted": 1,
        "investment_signal_generated": 1,
        "report_claim_generated": 2,
        "claim_verified": 1,
        "pending_review": 2,
    }
