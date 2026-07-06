from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ClaimEvidence, Company, Document, EvidenceItem, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def build_client(temp_db_engine, tmp_path):
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


def seed_evidence_center(service):
    with service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US", industry="Semiconductors")
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            batch_id="batch-sec-2024",
            title="NVIDIA FY2024 10-K",
            doc_type="10-K",
            report_period="FY2024",
            source_url="https://example.com/nvda-10k",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        evidence = EvidenceItem(
            evidence_id="ev_nvda_revenue",
            company_id=company.id,
            document_id=document.id,
            chunk_id="chunk-7",
            source_type="sec_edgar",
            trust_level="official",
            title="Revenue disclosure",
            content="Revenue increased materially during fiscal 2024.",
            source_url="https://example.com/nvda-10k#page=42",
            page_no=42,
            metadata_json={"task_id": "task-evidence-api", "period": "FY2024"},
        )
        other = EvidenceItem(
            evidence_id="ev_other",
            source_type="news",
            trust_level="secondary",
            title="Unrelated news",
            content="A market article.",
            metadata_json={"period": "FY2023"},
        )
        task = ReportTask(task_id="task-evidence-api", symbol="NVDA", period="FY2024", status="completed")
        claim = ReportClaim(
            task_id="task-evidence-api",
            section_name="Revenue",
            claim_text="NVDA revenue increased in FY2024.",
            claim_type="financial",
            verification_status="supported",
            review_status="pending",
            confidence=0.91,
        )
        session.add_all([evidence, other, task, claim])
        session.flush()
        session.add(ClaimEvidence(claim_id=claim.id, evidence_item_id=evidence.id, support_type="supports"))
        session.commit()


def test_evidence_api_filters_by_task_source_and_period(temp_db_engine, tmp_path):
    service, client = build_client(temp_db_engine, tmp_path)
    seed_evidence_center(service)

    with client:
        response = client.get(
            "/api/evidence",
            params={"task_id": "task-evidence-api", "source_type": "sec_edgar", "period": "FY2024"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["evidence_id"] == "ev_nvda_revenue"
    assert body["items"][0]["snippet"] == "Revenue increased materially during fiscal 2024."
    assert body["items"][0]["claim_count"] == 1
    assert body["items"][0]["document"]["title"] == "NVIDIA FY2024 10-K"


def test_evidence_api_detail_returns_content_and_404(temp_db_engine, tmp_path):
    service, client = build_client(temp_db_engine, tmp_path)
    seed_evidence_center(service)

    with client:
        detail = client.get("/api/evidence/ev_nvda_revenue")
        missing = client.get("/api/evidence/does-not-exist")

    assert detail.status_code == 200
    body = detail.json()
    assert body["content"] == "Revenue increased materially during fiscal 2024."
    assert body["company"]["symbol"] == "NVDA"
    assert body["document"]["report_period"] == "FY2024"
    assert body["claims"][0]["task_id"] == "task-evidence-api"
    assert body["claims"][0]["verification_status"] == "supported"
    assert missing.status_code == 404
