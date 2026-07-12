from types import SimpleNamespace

import pytest

from src.runtime.report_run_state import InvalidReportTransition, apply_report_transition, build_report_run_state


def task_stub(
    *,
    status="queued",
    current_stage="queued",
    metadata=None,
    claims=None,
    artifacts=None,
):
    return SimpleNamespace(
        task_id="task-runtime",
        symbol="NVDA",
        period="FY2024",
        report_type="equity_research",
        status=status,
        current_stage=current_stage,
        quality_score=0.92,
        metadata_json=metadata or {},
        claims=claims or [],
        artifacts=artifacts or [],
    )


def approved_claim():
    return SimpleNamespace(review_status="approved", verification_status="supported")


def report_artifact():
    return SimpleNamespace(artifact_type="markdown")


def completed_runtime_metadata():
    return {
        "report_runtime": {"schema_version": "report_runtime.v1", "lifecycle_status": "generation_completed"},
        "run_mode": "sync_generation",
        "pre_generation_evidence_gate": {
            "status": "success",
            "blocked": False,
            "draft_ready": True,
            "delivery_ready": True,
        },
        "quality_result": {
            "delivery_gate": {"delivery_pass": True},
            "top_quality_issues": [],
        },
    }


def test_report_runtime_rejects_illegal_transition_and_projects_legacy_columns():
    task = task_stub()

    apply_report_transition(task, "evidence_checking", reason="start")
    assert task.status == "running"
    assert task.current_stage == "evidence_gate"

    apply_report_transition(task, "evidence_blocked", reason="missing_official_source")
    assert task.status == "quality_failed"
    assert task.current_stage == "evidence_gate_failed"
    assert task.metadata_json["report_runtime"]["last_transition"]["to"] == "evidence_blocked"

    with pytest.raises(InvalidReportTransition):
        apply_report_transition(task, "generating")


def test_queued_task_has_one_canonical_readiness_projection():
    state = build_report_run_state(task_stub(metadata={"report_runtime": {"schema_version": "report_runtime.v1"}}))

    assert state["schema_version"] == "report_run_state.v2"
    assert state["company_identity"]["symbol"] == "NVDA"
    assert state["period_spec"]["target_period"] == "FY2024"
    assert state["delivery_readiness"]["schema_version"] == "delivery_readiness.v2"
    assert state["lifecycle_status"] == "queued"
    assert state["delivery_readiness"]["can_generate_draft"] is True
    assert state["delivery_readiness"]["can_deliver_formal_report"] is False
    assert state["export_readiness"]["can_export_formal_package"] is False
    assert set(state["delivery_readiness"]["blocking_reasons"]) >= {
        "report_task_not_completed",
        "evidence_check_pending",
        "quality_check_pending",
        "claims_missing",
        "report_artifact_missing",
    }


def test_completed_reviewed_task_is_formally_deliverable_and_exportable():
    task = task_stub(
        status="completed",
        current_stage="completed",
        metadata=completed_runtime_metadata(),
        claims=[approved_claim()],
        artifacts=[report_artifact()],
    )

    state = build_report_run_state(task)

    assert state["lifecycle_status"] == "generation_completed"
    assert state["delivery_readiness"]["blocking_reasons"] == []
    assert state["delivery_readiness"]["can_deliver_formal_report"] is True
    assert state["delivery_readiness"]["machine_quality_pass"] is True
    assert state["delivery_readiness"]["human_review_status"] == "completed"
    assert state["delivery_readiness"]["formal_delivery_pass"] is True
    assert state["export_readiness"]["can_export_formal_package"] is True


def test_quality_pass_does_not_override_pending_claim_review():
    task = task_stub(
        status="completed",
        current_stage="completed",
        metadata=completed_runtime_metadata(),
        claims=[SimpleNamespace(review_status="pending", verification_status="supported")],
        artifacts=[report_artifact()],
    )

    state = build_report_run_state(task)

    assert state["quality_state"]["delivery_pass"] is True
    assert state["delivery_readiness"]["can_deliver_formal_report"] is False
    assert state["delivery_readiness"]["machine_quality_pass"] is True
    assert state["delivery_readiness"]["human_review_status"] == "pending"
    assert state["delivery_readiness"]["formal_delivery_pass"] is False
    assert state["export_readiness"]["can_export_formal_package"] is False
    assert state["delivery_readiness"]["blocking_reasons"] == ["pending_claim_review", "approved_claims_missing"]


def test_quality_blocked_task_with_review_complete_requires_remediation():
    metadata = completed_runtime_metadata()
    metadata["report_runtime"]["lifecycle_status"] = "quality_blocked"
    metadata["quality_result"]["delivery_gate"]["delivery_pass"] = False
    task = task_stub(
        status="quality_failed",
        current_stage="quality_failed",
        metadata=metadata,
        claims=[approved_claim()],
        artifacts=[report_artifact()],
    )

    state = build_report_run_state(task)

    assert state["delivery_readiness"]["status"] == "remediation_required"
    assert state["delivery_readiness"]["draft_generated"] is True
    assert state["delivery_readiness"]["can_generate_draft"] is True
    assert state["delivery_readiness"]["can_enter_human_review"] is False
    assert "report_task_not_completed" not in state["delivery_readiness"]["blocking_reasons"]
    assert "quality_gate_failed" in state["delivery_readiness"]["blocking_reasons"]


def test_legacy_completed_task_is_compatible_but_marks_inferred_gates():
    task = task_stub(
        status="completed",
        current_stage="completed",
        claims=[approved_claim()],
        artifacts=[report_artifact()],
    )

    state = build_report_run_state(task)

    assert state["delivery_readiness"]["can_deliver_formal_report"] is True
    assert state["delivery_readiness"]["warnings"] == [
        "legacy_evidence_state_inferred",
        "legacy_quality_state_inferred",
    ]
