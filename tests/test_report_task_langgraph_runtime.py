import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.app.api_fastapi import create_fastapi_app
from src.db.models import LLMRun
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
        (self.output_dir / "search_meta.json").write_text(
            json.dumps(
                {
                    "engine_meta": {
                        "local_evidence": {
                            "source_record_count": 1,
                            "candidate_count": 1,
                            "returned_hit_count": 1,
                            "vector_hit_count": 1,
                            "vector_score_max": 0.42,
                            "vector_score_mean": 0.42,
                            "coverage": {"missing_sources": [], "summary": "test coverage ready"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.output_dir / "section_dossiers.json").write_text(
            json.dumps({"financial_analysis": {"supporting_evidence_ids": ["ev-runtime"]}}),
            encoding="utf-8",
        )
        (self.output_dir / "report_section_contracts.json").write_text(
            json.dumps(
                {
                    "contracts": {
                        "financial_analysis": {
                            "status": "supported",
                            "citation_evidence_ids": ["ev-runtime"],
                        }
                    }
                }
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
        (self.output_dir / "financial_metrics.json").write_text(
            json.dumps(
                {
                    "metrics": [
                        {
                            "metric_name": "revenue",
                            "value": 100.0,
                            "unit": "USD_million",
                            "source_type": "sec_companyfacts",
                            "source_evidence_id": "ev-runtime",
                            "period_match": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (self.output_dir / "run_summary.json").write_text(
            json.dumps(
                {
                    "symbol": "NVDA",
                    "period": "FY2024",
                    "executed_agents": ["research", "final_answer"],
                    "model_usage_by_agent": {
                        "research": {"provider": "test", "model_name": "fixture"},
                        "final_answer": {"provider": "test", "model_name": "fixture"},
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.output_dir / "agent_collaboration_trace.json").write_text(
            json.dumps(
                {
                    "agents": [
                        {"agent": "research", "task_type": "research", "status": "completed", "error": ""},
                        {"agent": "final_answer", "task_type": "writing", "status": "completed", "error": ""},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (self.output_dir / "tool_trace.json").write_text(
            json.dumps(
                {
                    "calls": [
                        {
                            "caller_agent": "research",
                            "tool_name": "local_evidence",
                            "success": True,
                            "failure_reason": "",
                        }
                    ]
                }
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


def test_section_repair_callback_uses_observable_llm_harness(monkeypatch, tmp_path):
    class FakeRepairAdapter:
        api_key = "test-key"
        timeout = 5
        route_profile = "user_fast"
        model_name = "fake-repair-model"
        max_tokens = 1000

        def generate_json(self, prompt, system_prompt=None, **kwargs):
            assert "Section repair input" in prompt
            assert "valid JSON only" in system_prompt
            return {"section_markdown": "基于正式证据维持中性判断。[ev1]"}

    monkeypatch.setattr(
        "src.services.report_task_service._build_role_model_adapter",
        lambda **kwargs: FakeRepairAdapter(),
    )
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    service.create_task(
        {
            "task_id": "task-section-repair-harness",
            "symbol": "AAPL",
            "period": "FY2024",
            "execution_tier": "user_fast",
        }
    )
    metadata = service._task_metadata("task-section-repair-harness")
    callback = service._build_section_repair_callback(
        task_id="task-section-repair-harness",
        metadata=metadata,
    )

    assert callback is not None
    result = callback(
        {
            "section_key": "conclusion",
            "title": "投资结论",
            "original_section": "短。",
            "contract": {},
            "evidence_pack": {"must_use_evidence_ids": ["ev1"]},
            "verification": {"reasons": ["too_short"]},
        }
    )

    assert result["section_markdown"].endswith("[ev1]")
    assert result["llm_run_id"].startswith("llm_")
    with service.session() as session:
        run = session.scalar(select(LLMRun).where(LLMRun.run_id == result["llm_run_id"]))
        assert run is not None
        assert run.task_id == "task-section-repair-harness"
        assert run.model_role == "section_repair"
        assert run.status == "success"


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
        "inspect_agent_execution",
        "verify_sections",
        "repair_failed_sections",
        "quality",
        "finalize",
        "human_review",
    }
    assert body["task"]["metadata"]["report_runtime"]["canonical_metrics"]["status"] == "ready"
    generation_execution = body["task"]["metadata"]["report_runtime"]["generation_execution"]
    assert generation_execution["status"] == "ready"
    assert generation_execution["agent_count"] == 2
    assert generation_execution["failed_agent_count"] == 0
    assert body["task"]["metadata"]["report_runtime"]["official_evidence_backfill"]["status"] in {"not_required", "remote_disabled"}
    assert body["task"]["metadata"]["report_runtime"]["retrieval_attribution"]["status"] == "ready"
    assert body["task"]["metadata"]["report_runtime"]["retrieval_attribution"]["similarity_status"] == "ok"
    assert body["task"]["metadata"]["report_runtime"]["section_verification"]["status"] in {"passed", "failed"}
    assert body["task"]["metadata"]["report_runtime"]["section_repair"]["status"] in {
        "not_required",
        "repaired",
        "attempted",
        "no_change",
        "skipped_missing_report",
    }
    assert any(artifact["artifact_type"] == "canonical_metrics" for artifact in body["task"]["artifacts"])
    assert any(artifact["artifact_type"] == "evidence_retrieval_attribution" for artifact in body["task"]["artifacts"])
    assert any(artifact["artifact_type"] == "section_verification" for artifact in body["task"]["artifacts"])
    assert any(artifact["artifact_type"] == "section_repair" for artifact in body["task"]["artifacts"])
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
    assert len(evidence_events) == 1


def test_report_task_remote_runtime_executes_official_backfill(monkeypatch, tmp_path):
    calls = []

    def fake_backfill(**kwargs):
        calls.append(kwargs)
        return {
            "acquired_record_count": 2,
            "merged_record_count": 3,
            "pdf_record_count": 1,
            "table_count": 3,
            "attempts": [{"source_key": "sec_edgar", "status": "success", "record_count": 2}],
            "coverage": {"formal_delivery_allowed": True, "missing_requirements": []},
            "backfill_remaining": {"tasks": []},
        }

    monkeypatch.setattr("src.services.report_task_service.execute_official_evidence_backfill", fake_backfill)

    with make_client(tmp_path, ReviewArtifactOrchestrator) as client:
        created = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-runtime-backfill",
                "symbol": "AAPL",
                "period": "FY2024",
                "enable_remote_data": True,
                "run_immediately": True,
            },
        )

    assert created.status_code == 201
    assert len(calls) == 1
    assert calls[0]["symbol"] == "AAPL"
    assert calls[0]["period"] == "FY2024"
    backfill = created.json()["metadata"]["report_runtime"]["official_evidence_backfill"]
    assert backfill["status"] == "completed"
    assert backfill["acquired_record_count"] == 2
    assert backfill["formal_delivery_allowed"] is True


def test_official_backfill_is_imported_before_enforced_evidence_gate(monkeypatch, tmp_path):
    def fake_backfill(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evidence.json").write_text(
            json.dumps(
                [
                    {
                        "evidence_id": "aapl-fy2024-official",
                        "title": "Apple FY2024 Form 10-K",
                        "content": "Apple FY2024 official annual filing.",
                        "source_type": "sec_edgar",
                        "source_url": "https://www.sec.gov/Archives/aapl-fy2024",
                        "trust_level": "official",
                        "symbol": "AAPL",
                        "period": "FY2024",
                        "metadata": {"symbol": "AAPL", "period": "FY2024"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        return {
            "acquired_record_count": 1,
            "merged_record_count": 1,
            "pdf_record_count": 1,
            "table_count": 0,
            "attempts": [{"source_key": "sec_edgar", "status": "success", "record_count": 1}],
            "coverage": {"formal_delivery_allowed": True, "missing_requirements": []},
            "backfill_remaining": {"tasks": []},
        }

    monkeypatch.setattr("src.services.report_task_service.execute_official_evidence_backfill", fake_backfill)

    with make_client(tmp_path, ReviewArtifactOrchestrator) as client:
        created = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-backfill-before-gate",
                "symbol": "AAPL",
                "period": "FY2024",
                "enable_remote_data": True,
                "enforce_evidence_gate": True,
                "run_immediately": True,
            },
        )

    body = created.json()
    assert created.status_code == 201
    assert body["status"] == "completed"
    assert body["metadata"]["pre_generation_evidence_gate"]["blocked"] is False
    completed_stages = [
        event["stage"]
        for event in body["events"]
        if event["stage"] != "runtime_start"
    ]
    assert completed_stages.index("official_evidence_backfill") < completed_stages.index("evidence_gate")


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
