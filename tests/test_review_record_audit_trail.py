from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ReportClaim, ReportTask, ReviewRecord
from src.services.report_task_service import ReportTaskService


def test_review_record_audit_trail_keeps_before_after_values(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add(ReportTask(task_id="task-audit", symbol="AAPL", period="FY2024", status="completed"))
        claim = ReportClaim(task_id="task-audit", claim_text="Original claim.", review_status="pending")
        session.add(claim)
        session.commit()
        claim_id = claim.id

    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        approve = client.post(f"/api/claims/{claim_id}/approve", json={"reviewer": "alice", "comment": "verified"})
        edit = client.post(
            f"/api/claims/{claim_id}/edit",
            json={"claim_text": "Edited claim.", "reviewer": "bob", "comment": "tighten wording"},
        )
        detail = client.get(f"/api/claims/{claim_id}")

    assert approve.status_code == 200
    assert edit.status_code == 200
    assert detail.status_code == 200
    records = detail.json()["review_records"]
    assert [record["decision"] for record in records] == ["edit", "approve"]
    assert records[0]["before_value"]["claim_text"] == "Original claim."
    assert records[0]["after_value"]["claim_text"] == "Edited claim."
    assert records[1]["before_value"]["review_status"] == "pending"
    assert records[1]["after_value"]["review_status"] == "approved"

    with service.session() as session:
        db_records = session.query(ReviewRecord).order_by(ReviewRecord.id).all()
        assert len(db_records) == 2
        assert db_records[0].reviewer == "alice"
        assert db_records[1].comment == "tighten wording"
