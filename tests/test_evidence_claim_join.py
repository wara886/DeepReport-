from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ClaimEvidence, EvidenceItem, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def test_evidence_claim_join_includes_multiple_claims(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        evidence = EvidenceItem(
            evidence_id="ev_margin",
            content="Gross margin changed during the fiscal year.",
            source_type="sec_edgar",
            trust_level="official",
            metadata_json={"task_id": "task-join"},
        )
        session.add_all(
            [
                ReportTask(task_id="task-join", symbol="AAPL", period="FY2024", status="completed"),
                evidence,
            ]
        )
        session.flush()
        claim_a = ReportClaim(task_id="task-join", claim_text="Margin changed.", review_status="approved")
        claim_b = ReportClaim(task_id="task-join", claim_text="Margin needs review.", review_status="pending")
        session.add_all([claim_a, claim_b])
        session.flush()
        session.add_all(
            [
                ClaimEvidence(claim_id=claim_a.id, evidence_item_id=evidence.id),
                ClaimEvidence(claim_id=claim_b.id, evidence_item_id=evidence.id),
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
        response = client.get("/api/evidence", params={"task_id": "task-join"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["evidence_id"] == "ev_margin"
    assert item["claim_count"] == 2
    assert [claim["review_status"] for claim in item["claims"]] == ["approved", "pending"]
