from pathlib import Path

import pytest

from src.runtime.langgraph_report_runtime import CallbackReportGraphHandlers, LangGraphReportRuntime


def initial_state():
    return {
        "schema_version": "report_run_state.v1",
        "task_id": "task-langgraph",
        "symbol": "NVDA",
        "period": "FY2024",
        "report_type": "equity_research",
        "run_mode": "sync_generation",
        "lifecycle_status": "evidence_checking",
        "legacy_status": "running",
        "legacy_current_stage": "evidence_gate",
        "evidence_state": {"status": "pending", "checked": False, "blocked": False},
        "quality_state": {"status": "pending", "checked": False, "delivery_pass": None},
        "claim_state": {"total_count": 0, "approved_count": 0, "pending_count": 0},
        "artifact_state": {"count": 0, "types": [], "report_available": False},
        "delivery_readiness": _readiness("in_progress", ["report_task_not_completed"]),
        "export_readiness": {"status": "blocked", "can_export_formal_package": False, "blocking_reasons": ["report_task_not_completed"]},
    }


def _readiness(status, blockers):
    ready = not blockers
    return {
        "status": status,
        "can_generate_draft": False,
        "can_enter_human_review": status == "review_required",
        "can_deliver_formal_report": ready,
        "can_export_formal_package": ready,
        "blocking_reasons": list(blockers),
        "warnings": [],
        "required_actions": ["review_pending_claims"] if "pending_claim_review" in blockers else [],
    }


def successful_handlers(calls, *, pending_review=True):
    def evidence(_state):
        calls.append("evidence")
        return {
            "lifecycle_status": "generating",
            "evidence_state": {"status": "success", "checked": True, "blocked": False, "delivery_ready": True},
        }

    def generation(_state):
        calls.append("generation")
        return {
            "lifecycle_status": "quality_checking",
            "artifact_state": {"count": 1, "types": ["markdown"], "report_available": True},
            "claim_state": {"total_count": 1, "approved_count": 0 if pending_review else 1, "pending_count": 1 if pending_review else 0},
        }

    def quality(_state):
        calls.append("quality")
        return {
            "quality_state": {"status": "passed", "checked": True, "delivery_pass": True},
        }

    def finalize(_state):
        calls.append("finalize")
        blockers = ["pending_claim_review"] if pending_review else []
        return {
            "lifecycle_status": "generation_completed",
            "delivery_readiness": _readiness("review_required" if blockers else "export_ready", blockers),
            "export_readiness": {
                "status": "blocked" if blockers else "ready",
                "can_export_formal_package": not blockers,
                "blocking_reasons": blockers,
            },
        }

    def review(_state, decision):
        calls.append("review")
        assert decision == {"approved": True, "reviewer": "analyst"}
        return {
            "claim_state": {"total_count": 1, "approved_count": 1, "pending_count": 0},
            "delivery_readiness": _readiness("export_ready", []),
            "export_readiness": {"status": "ready", "can_export_formal_package": True, "blocking_reasons": []},
        }

    return CallbackReportGraphHandlers(evidence, generation, quality, finalize, review)


def test_langgraph_runtime_runs_typed_nodes_and_interrupts_for_claim_review():
    calls = []
    runtime = LangGraphReportRuntime(successful_handlers(calls))

    paused = runtime.invoke(initial_state(), thread_id="task-langgraph")

    assert calls == ["evidence", "generation", "quality", "finalize"]
    assert paused["lifecycle_status"] == "generation_completed"
    assert paused["delivery_readiness"]["status"] == "review_required"
    assert paused["interrupts"][0]["value"]["type"] == "claim_review_required"
    assert runtime.snapshot(thread_id="task-langgraph")["next"] == ["human_review"]

    completed = runtime.resume(
        thread_id="task-langgraph",
        decision={"approved": True, "reviewer": "analyst"},
    )

    assert calls[-1] == "review"
    assert completed["delivery_readiness"]["can_deliver_formal_report"] is True
    assert completed["export_readiness"]["can_export_formal_package"] is True
    assert completed["review_decision"]["approved"] is True
    assert [item["node"] for item in completed["runtime_events"]] == [
        "evidence",
        "generation",
        "quality",
        "finalize",
        "human_review",
    ]
    assert runtime.snapshot(thread_id="task-langgraph")["next"] == []


def test_evidence_block_stops_before_generation():
    calls = []

    def evidence(_state):
        calls.append("evidence")
        return {
            "lifecycle_status": "evidence_blocked",
            "evidence_state": {"status": "failed", "checked": True, "blocked": True, "delivery_ready": False},
            "delivery_readiness": _readiness("blocked", ["evidence_not_delivery_ready"]),
        }

    def should_not_run(_state):
        raise AssertionError("downstream node must not run")

    runtime = LangGraphReportRuntime(
        CallbackReportGraphHandlers(evidence, should_not_run, should_not_run, should_not_run)
    )

    result = runtime.invoke(initial_state(), thread_id="task-blocked")

    assert calls == ["evidence"]
    assert result["lifecycle_status"] == "evidence_blocked"
    assert runtime.snapshot(thread_id="task-blocked")["next"] == []


def test_failed_node_can_retry_from_checkpoint_without_repeating_completed_nodes():
    calls = []
    generation_calls = 0

    base = successful_handlers(calls, pending_review=False)

    def flaky_generation(state):
        nonlocal generation_calls
        generation_calls += 1
        if generation_calls == 1:
            raise RuntimeError("temporary generation failure")
        return base.generation(state)

    handlers = CallbackReportGraphHandlers(base.evidence, flaky_generation, base.quality, base.finalize)
    runtime = LangGraphReportRuntime(handlers)

    with pytest.raises(RuntimeError, match="temporary generation failure"):
        runtime.invoke(initial_state(), thread_id="task-retry")

    snapshot = runtime.snapshot(thread_id="task-retry")
    assert snapshot["next"] == ["generation"]
    assert calls == ["evidence"]

    completed = runtime.retry_from_checkpoint(thread_id="task-retry")

    assert generation_calls == 2
    assert calls == ["evidence", "generation", "quality", "finalize"]
    assert completed["delivery_readiness"]["can_deliver_formal_report"] is True


def test_sqlite_checkpoint_survives_runtime_recreation(tmp_path: Path):
    checkpoint = tmp_path / "report_runtime.sqlite"
    first_calls = []
    first = LangGraphReportRuntime(successful_handlers(first_calls), checkpoint_path=checkpoint)
    paused = first.invoke(initial_state(), thread_id="task-durable")
    assert paused["interrupts"][0]["value"]["type"] == "claim_review_required"
    first.close()

    second_calls = []
    second = LangGraphReportRuntime(successful_handlers(second_calls), checkpoint_path=checkpoint)
    completed = second.resume(
        thread_id="task-durable",
        decision={"approved": True, "reviewer": "analyst"},
    )
    second.close()

    assert second_calls == ["review"]
    assert completed["delivery_readiness"]["can_deliver_formal_report"] is True


def test_node_cannot_create_an_unowned_state_channel():
    def invalid_evidence(_state):
        return {"task_status": "completed"}

    runtime = LangGraphReportRuntime(
        CallbackReportGraphHandlers(invalid_evidence, lambda _state: {}, lambda _state: {}, lambda _state: {})
    )

    with pytest.raises(ValueError, match="unsupported state keys"):
        runtime.invoke(initial_state(), thread_id="task-invalid-patch")
