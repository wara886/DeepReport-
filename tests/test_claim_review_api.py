from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ClaimEvidence, EvidenceItem, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def build_claim_review_client(temp_db_engine, tmp_path):
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


def seed_claim(service, *, review_status="pending"):
    with service.session() as session:
        task = ReportTask(task_id="task-claim-review", symbol="NVDA", period="FY2024", status="completed")
        evidence = EvidenceItem(
            evidence_id="ev_claim_review",
            content="Revenue increased during FY2024.",
            source_type="sec_edgar",
            trust_level="official",
        )
        claim = ReportClaim(
            task_id="task-claim-review",
            section_name="Revenue",
            claim_text="NVDA revenue increased during FY2024.",
            claim_type="financial",
            verification_status="supported",
            numeric_check_status="passed",
            citation_check_status="passed",
            confidence=0.93,
            review_status=review_status,
        )
        session.add_all([task, evidence, claim])
        session.flush()
        session.add(ClaimEvidence(claim_id=claim.id, evidence_item_id=evidence.id, support_type="supports"))
        session.commit()
        return claim.id


def test_claim_review_api_list_detail_and_actions(temp_db_engine, tmp_path):
    service, client = build_claim_review_client(temp_db_engine, tmp_path)
    claim_id = seed_claim(service)

    with client:
        listed = client.get("/api/claims", params={"task_id": "task-claim-review", "status": "pending"})
        detail = client.get(f"/api/claims/{claim_id}")
        approved = client.post(f"/api/claims/{claim_id}/approve", json={"reviewer": "analyst", "comment": "ok"})
        edited = client.post(
            f"/api/claims/{claim_id}/edit",
            json={"claim_text": "Edited claim text.", "review_status": "pending", "reviewer": "analyst"},
        )
        rejected = client.post(f"/api/claims/{claim_id}/reject", json={"reviewer": "analyst", "comment": "bad source"})
        regenerated = client.post(f"/api/claims/{claim_id}/regenerate", json={"reviewer": "analyst"})
        missing = client.get("/api/claims/99999")

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["evidence_count"] == 1
    assert listed.json()["items"][0]["evidence"][0]["evidence_id"] == "ev_claim_review"

    assert detail.status_code == 200
    assert detail.json()["review_status"] == "pending"
    assert detail.json()["evidence"][0]["source_type"] == "sec_edgar"

    assert approved.status_code == 200
    assert approved.json()["review_status"] == "approved"
    assert edited.status_code == 200
    assert edited.json()["claim_text"] == "Edited claim text."
    assert edited.json()["review_status"] == "pending"
    assert rejected.status_code == 200
    assert rejected.json()["review_status"] == "rejected"
    assert regenerated.status_code == 200
    assert regenerated.json()["review_status"] == "regenerate_requested"
    assert missing.status_code == 404


def test_claim_review_regenerate_writes_task_event(temp_db_engine, tmp_path):
    service, client = build_claim_review_client(temp_db_engine, tmp_path)
    claim_id = seed_claim(service)

    with client:
        response = client.post(f"/api/claims/{claim_id}/regenerate", json={"comment": "refresh wording"})
        task = client.get("/api/report-tasks/task-claim-review")

    assert response.status_code == 200
    assert any(event["stage"] == "claim_review" for event in task.json()["events"])
    assert any(event["status"] == "regenerate_requested" for event in task.json()["events"])


def test_task_bulk_review_approves_only_supported_claims_and_audits_each_decision(temp_db_engine, tmp_path):
    service, client = build_claim_review_client(temp_db_engine, tmp_path)
    supported_id = seed_claim(service)
    with service.session() as session:
        session.add(
            ReportClaim(
                task_id="task-claim-review",
                claim_text="Unsupported claim remains pending.",
                verification_status="failed",
                review_status="pending",
            )
        )
        session.commit()

    with client:
        result = client.post(
            "/api/report-tasks/task-claim-review/claims/approve-supported",
            json={"reviewer": "lead-analyst", "comment": "evidence checked"},
        )
        supported = client.get(f"/api/claims/{supported_id}")
        pending = client.get("/api/claims", params={"task_id": "task-claim-review", "status": "pending"})
        task = client.get("/api/report-tasks/task-claim-review")

    assert result.status_code == 200
    assert result.json()["approved_count"] == 1
    assert result.json()["pending_count"] == 1
    assert result.json()["review_complete"] is False
    assert supported.json()["review_status"] == "approved"
    assert supported.json()["review_records"][0]["reviewer"] == "lead-analyst"
    assert supported.json()["review_records"][0]["before_value"]["review_status"] == "pending"
    assert supported.json()["review_records"][0]["after_value"]["review_status"] == "approved"
    assert pending.json()["items"][0]["claim_text"] == "Unsupported claim remains pending."
    assert any(event["message"] == "Batch approved 1 supported claims" for event in task.json()["events"])
