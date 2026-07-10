from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import EvidenceItem, LLMRun, ReportArtifact, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def test_dashboard_summary_aggregates_database_state(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add_all(
            [
                ReportTask(task_id="task-ok", symbol="NVDA", period="FY2024", status="completed", quality_score=0.9),
                ReportTask(task_id="task-failed", symbol="TSLA", period="FY2024", status="failed"),
                ReportTask(task_id="task-archived", symbol="AAPL", period="FY2024", status="archived", quality_score=0.1),
                EvidenceItem(evidence_id="ev_sec", content="10-K evidence", source_type="sec_edgar", trust_level="official"),
                EvidenceItem(evidence_id="ev_news", content="news evidence", source_type="news", trust_level="secondary"),
                ReportClaim(task_id="task-ok", claim_text="Supported claim", verification_status="supported", review_status="pending"),
                ReportClaim(task_id="task-ok", claim_text="Rejected claim", verification_status="failed", review_status="rejected"),
                ReportArtifact(task_id="task-ok", artifact_type="html", path="report.html", url="/artifacts/report.html"),
                LLMRun(
                    run_id="llm-dashboard-ok",
                    task_id="task-ok",
                    prompt_key="report_quality_gate",
                    model_role="quality_gate",
                    model_name="quality-gate-trace",
                    status="success",
                    attempt_count=1,
                    fallback_used=False,
                    latency_ms=120,
                    cost_usd=0.002,
                ),
                LLMRun(
                    run_id="llm-dashboard-failed",
                    task_id="task-failed",
                    prompt_key="claim_verifier",
                    model_role="verifier",
                    model_name="mock",
                    status="failed",
                    attempt_count=2,
                    fallback_used=True,
                    latency_ms=240,
                    cost_usd=0.004,
                ),
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
        response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_count"] == 2
    assert body["claim_count"] == 2
    assert body["review_pending_claim_count"] == 1
    assert body["verified_claim_count"] == 1
    assert body["quality_pass_rate"] == 0.5
    assert body["average_quality_score"] == 0.9
    assert body["report_task_status_distribution"] == {"completed": 1, "failed": 1}
    assert body["data_source_distribution"] == {"news": 1, "sec_edgar": 1}
    assert body["artifact_distribution"] == {"html": 1}
    assert body["llm_run_count"] == 2
    assert body["llm_failed_run_count"] == 1
    assert body["llm_failure_rate"] == 0.5
    assert body["average_llm_latency_ms"] == 180
    assert body["llm_cost_usd"] == 0.006
