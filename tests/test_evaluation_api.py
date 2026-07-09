from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ClaimEvidence, EvidenceItem, LLMRun, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'evaluation.db'}",
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
    return TestClient(app), service


def seed_evaluation_state(service):
    with service.session() as session:
        task_ok = ReportTask(
            task_id="task-eval-ok",
            symbol="NVDA",
            period="FY2024",
            status="completed",
            quality_score=0.92,
            metadata_json={
                "company_name": "NVIDIA",
                "quality_result": {
                    "delivery_gate": {"delivery_pass": True},
                    "top_quality_issues": [],
                },
            },
        )
        task_bad = ReportTask(
            task_id="task-eval-bad",
            symbol="TSLA",
            period="FY2024",
            status="quality_failed",
            quality_score=0.62,
            metadata_json={
                "company_name": "Tesla",
                "quality_result": {
                    "delivery_gate": {"delivery_pass": False},
                    "top_quality_issues": [
                        {"category": "citation_missing", "severity": "blocker", "message": "风险段落缺少引用。"}
                    ],
                },
            },
        )
        task_archived = ReportTask(
            task_id="task-eval-archived",
            symbol="AAPL",
            period="FY2024",
            status="archived",
            quality_score=0.1,
        )
        session.add_all([task_ok, task_bad, task_archived])
        session.flush()
        evidence = EvidenceItem(
            evidence_id="ev-eval-1",
            content="Gross margin and revenue evidence.",
            source_type="sec_edgar",
            trust_level="official",
        )
        session.add(evidence)
        session.flush()
        supported_claim = ReportClaim(
            task_id="task-eval-ok",
            claim_text="NVIDIA revenue increased.",
            verification_status="supported",
            numeric_check_status="passed",
            citation_check_status="passed",
            review_status="approved",
        )
        weak_claim = ReportClaim(
            task_id="task-eval-bad",
            claim_text="Tesla margin pressure will continue.",
            verification_status="failed",
            numeric_check_status="failed",
            citation_check_status="failed",
            review_status="pending",
        )
        archived_claim = ReportClaim(
            task_id="task-eval-archived",
            claim_text="Archived claim should not affect metrics.",
            verification_status="supported",
            review_status="approved",
        )
        session.add_all([supported_claim, weak_claim, archived_claim])
        session.flush()
        session.add(ClaimEvidence(claim_id=supported_claim.id, evidence_item_id=evidence.id, support_type="supporting"))
        session.add_all(
            [
                LLMRun(
                    run_id="run-eval-ok",
                    task_id="task-eval-ok",
                    prompt_key="report_quality_gate",
                    model_role="quality_gate",
                    status="success",
                    schema_valid=True,
                    latency_ms=100,
                    cost_usd=0.002,
                ),
                LLMRun(
                    run_id="run-eval-failed",
                    task_id="task-eval-bad",
                    prompt_key="claim_verifier",
                    model_role="verifier",
                    status="failed",
                    schema_valid=False,
                    fallback_used=True,
                    latency_ms=300,
                    cost_usd=0.004,
                ),
            ]
        )
        session.commit()


def test_evaluation_summary_aggregates_quality_and_harness_metrics(tmp_path):
    client, service = build_client(tmp_path)
    seed_evaluation_state(service)

    with client:
        response = client.get("/api/evaluation/summary")

    assert response.status_code == 200
    body = response.json()
    metrics = body["metrics"]
    assert metrics["active_task_count"] == 2
    assert metrics["completed_task_count"] == 1
    assert metrics["delivery_pass_rate"] == 0.5
    assert metrics["average_quality_score"] == 0.77
    assert metrics["claim_count"] == 2
    assert metrics["traceable_claim_count"] == 1
    assert metrics["traceable_claim_rate"] == 0.5
    assert metrics["verified_claim_count"] == 1
    assert metrics["numeric_failed_count"] == 1
    assert metrics["numeric_consistency_rate"] == 0.5
    assert metrics["citation_failed_count"] == 1
    assert metrics["citation_support_rate"] == 0.5
    assert metrics["schema_valid_rate"] == 0.5
    assert metrics["llm_success_rate"] == 0.5
    assert metrics["average_llm_latency_ms"] == 200
    assert metrics["llm_cost_usd"] == 0.006
    failure_labels = {item["label"] for item in body["failure_categories"]}
    assert "质量门禁阻塞" in failure_labels
    assert "引用缺失或不支持" in failure_labels
    assert "模型运行失败" in failure_labels
    assert len(body["quality_gates"]) >= 7
    assert body["recent_tasks"][0]["task_id"] in {"task-eval-ok", "task-eval-bad"}
    assert body["model_health"]["fallback_count"] == 1


def test_evaluation_summary_handles_empty_state(tmp_path):
    client, _service = build_client(tmp_path)

    with client:
        response = client.get("/api/evaluation/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["active_task_count"] == 0
    assert body["metrics"]["delivery_pass_rate"] == 0.0
    assert body["failure_categories"] == []
    assert "暂无研报任务" in body["notes"][0]


def test_evaluation_task_diagnostics_explains_local_quality_blockers(tmp_path):
    client, service = build_client(tmp_path)
    seed_evaluation_state(service)

    with client:
        response = client.get("/api/evaluation/report-tasks/task-eval-bad/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["task_id"] == "task-eval-bad"
    assert body["summary"]["delivery_pass"] is False
    assert body["summary"]["missing_evidence_count"] == 1
    assert body["summary"]["unsupported_claim_count"] == 1
    assert body["summary"]["numeric_conflict_count"] == 1
    assert body["summary"]["citation_gap_count"] == 1
    assert body["summary"]["pending_review_count"] == 1
    blocker_labels = {item["label"] for item in body["blockers"]}
    assert "质量门禁未通过" in blocker_labels
    assert "主张未获支持" in blocker_labels
    assert "数字不一致" in blocker_labels
    assert "引用缺失" in blocker_labels
    assert body["claim_issues"]["numeric_conflicts"][0]["claim_text"] == "Tesla margin pressure will continue."
    assert body["model_issues"][0]["reason"] == "模型运行失败"
    action_views = {item["view"] for item in body["recommended_actions"]}
    assert {"claims", "facts", "evidence", "promptops"}.issubset(action_views)


def test_evaluation_task_diagnostics_returns_404_for_missing_task(tmp_path):
    client, _service = build_client(tmp_path)

    with client:
        response = client.get("/api/evaluation/report-tasks/not-found/diagnostics")

    assert response.status_code == 404
