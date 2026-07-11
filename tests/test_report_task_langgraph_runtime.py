import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


class ReviewArtifactOrchestrator:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)

    def run(self, **kwargs):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir / "report.md").write_text("# NVDA report", encoding="utf-8")
        (self.report_dir / "report.html").write_text("<html><body>NVDA report</body></html>", encoding="utf-8")
        (self.report_dir / "report.json").write_text(json.dumps({"title": "NVDA report"}), encoding="utf-8")
        (self.output_dir / "evidence.json").write_text(
            json.dumps(
                [
                    {
                        "evidence_id": "ev-runtime",
                        "title": "NVDA FY2024 filing",
                        "content": "Revenue increased.",
                        "source_type": "sec_edgar",
                        "trust_level": "official",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (self.output_dir / "claims.json").write_text(
            json.dumps(
                [
                    {
                        "claim_id": "cl-runtime",
                        "section_name": "financial_analysis",
                        "claim_text": "NVDA revenue increased.",
                        "evidence_ids": ["ev-runtime"],
                        "verification_status": "supported",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return {"verification_passed": True}


class FailingOnceOrchestrator:
    calls = 0

    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)

    def run(self, **kwargs):
        type(self).calls += 1
        if type(self).calls == 1:
            raise RuntimeError("temporary graph node failure")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir / "report.md").write_text("# recovered", encoding="utf-8")
        return {"verification_passed": True}


def passing_quality_runner(output_dir, report_dir, **kwargs):
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "quality_report": {"objective_pass": True, "total_score": 0.91},
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.89, "model_status": "test"},
        "delivery_gate": {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True},
        "top_quality_issues": [],
    }


def make_client(tmp_path, orchestrator_factory, *, runtime_enabled=True):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        runtime_checkpoint_path=tmp_path / "runtime.sqlite",
        langgraph_runtime_enabled=runtime_enabled,
        orchestrator_factory=orchestrator_factory,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app)


def test_report_task_pauses_and_resumes_at_claim_review_checkpoint(tmp_path):
    with make_client(tmp_path, ReviewArtifactOrchestrator) as client:
        created = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-runtime-review",
                "symbol": "NVDA",
                "period": "FY2024",
                "request_id": "request-runtime-review",
                "run_immediately": True,
            },
        )
        checkpoint = client.get("/api/report-tasks/task-runtime-review/runtime")
        claims = client.get("/api/claims", params={"task_id": "task-runtime-review"}).json()["items"]
        approved = client.post(f"/api/claims/{claims[0]['id']}/approve", json={"reviewer": "analyst"})
        resumed = client.post(
            "/api/report-tasks/task-runtime-review/runtime/resume",
            json={"decision": {"approved": True, "reviewer": "analyst"}},
        )

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert created.json()["metadata"]["report_runtime"]["checkpoint_status"] == "interrupted"
    assert created.json()["trace_context"] == {
        "request_id": "request-runtime-review",
        "run_id": "task-runtime-review",
        "task_id": "task-runtime-review",
    }
    assert checkpoint.status_code == 200
    assert checkpoint.json()["next"] == ["human_review"]
    assert checkpoint.json()["interrupts"][0]["value"]["type"] == "claim_review_required"
    assert approved.status_code == 200
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["checkpoint"]["next"] == []
    assert body["runtime"]["review_decision"]["approved"] is True
    assert body["task"]["metadata"]["report_runtime"]["checkpoint_status"] == "completed"
    observability = body["task"]["runtime_observability"]
    assert observability["trace_context"]["request_id"] == "request-runtime-review"
    assert observability["checkpoint_status"] == "completed"
    assert set(observability["node_latency_ms"]) == {
        "evidence",
        "official_evidence_backfill",
        "build_canonical_metrics",
        "build_section_evidence_packs",
        "generation",
        "verify_sections",
        "repair_failed_sections",
        "quality",
        "finalize",
        "human_review",
    }
    assert body["task"]["metadata"]["report_runtime"]["canonical_metrics"]["status"] in {"ready", "missing"}
    assert body["task"]["metadata"]["report_runtime"]["section_verification"]["status"] in {"passed", "needs_repair"}
    assert any(event["stage"] == "claim_review" and event["status"] == "resumed" for event in body["task"]["events"])


def test_report_task_retries_failed_generation_node_from_checkpoint(tmp_path):
    FailingOnceOrchestrator.calls = 0
    with make_client(tmp_path, FailingOnceOrchestrator) as client:
        failed = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-runtime-retry",
                "symbol": "NVDA",
                "period": "FY2024",
                "run_immediately": True,
            },
        )
        checkpoint = client.get("/api/report-tasks/task-runtime-retry/runtime")
        retried = client.post("/api/report-tasks/task-runtime-retry/runtime/retry")

    assert failed.status_code == 201
    assert failed.json()["status"] == "failed"
    assert failed.json()["metadata"]["runtime_failure"]["checkpoint_available"] is True
    assert checkpoint.status_code == 200
    assert checkpoint.json()["next"] == ["generation"]
    assert retried.status_code == 200
    body = retried.json()
    assert body["task"]["status"] == "completed"
    assert body["checkpoint"]["next"] == []
    assert FailingOnceOrchestrator.calls == 2
    evidence_events = [event for event in body["task"]["events"] if event["stage"] == "evidence_gate"]
    assert len(evidence_events) == 2


def test_report_task_can_use_legacy_pipeline_compatibility_switch(tmp_path):
    with make_client(tmp_path, ReviewArtifactOrchestrator, runtime_enabled=False) as client:
        created = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-runtime-disabled",
                "symbol": "NVDA",
                "period": "FY2024",
                "run_immediately": True,
            },
        )
        runtime = client.get("/api/report-tasks/task-runtime-disabled/runtime")

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert created.json()["metadata"]["report_runtime"].get("checkpoint_status") is None
    assert runtime.status_code == 409
    assert "disabled" in runtime.json()["error"]


def test_report_task_api_propagates_request_id_header(tmp_path):
    with make_client(tmp_path, ReviewArtifactOrchestrator) as client:
        response = client.post(
            "/api/report-tasks",
            headers={"X-Request-ID": "request-from-client"},
            json={
                "task_id": "task-request-trace",
                "symbol": "NVDA",
                "period": "FY2024",
            },
        )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == "request-from-client"
    assert response.json()["trace_context"]["request_id"] == "request-from-client"
