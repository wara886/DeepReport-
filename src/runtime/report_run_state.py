"""Canonical runtime state and readiness rules for financial report tasks.

The database keeps the legacy ``status`` and ``current_stage`` columns for API
compatibility.  This module owns their meaning: services transition through the
canonical lifecycle below and consumers derive delivery/export decisions from
one report-run projection.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Literal, TypedDict


ReportLifecycleStatus = Literal[
    "queued",
    "evidence_checking",
    "evidence_blocked",
    "generating",
    "quality_checking",
    "quality_blocked",
    "generation_completed",
    "failed",
    "timeout",
    "cancelled",
    "archived",
]


class DeliveryReadiness(TypedDict):
    status: str
    can_generate_draft: bool
    can_enter_human_review: bool
    can_deliver_formal_report: bool
    can_export_formal_package: bool
    blocking_reasons: list[str]
    warnings: list[str]
    required_actions: list[str]


class ReportRunState(TypedDict):
    schema_version: str
    task_id: str
    symbol: str
    period: str
    report_type: str
    run_mode: str
    lifecycle_status: ReportLifecycleStatus
    legacy_status: str
    legacy_current_stage: str
    evidence_state: dict[str, Any]
    quality_state: dict[str, Any]
    claim_state: dict[str, Any]
    artifact_state: dict[str, Any]
    delivery_readiness: DeliveryReadiness
    export_readiness: dict[str, Any]


class InvalidReportTransition(ValueError):
    """Raised when a report task attempts an illegal lifecycle transition."""


_LEGAL_TRANSITIONS: dict[ReportLifecycleStatus, set[ReportLifecycleStatus]] = {
    "queued": {"evidence_checking", "cancelled", "archived"},
    "evidence_checking": {"evidence_blocked", "generating", "failed", "timeout", "cancelled"},
    "evidence_blocked": {"queued", "archived"},
    "generating": {"quality_checking", "failed", "timeout", "cancelled"},
    "quality_checking": {"quality_blocked", "generation_completed", "failed", "timeout"},
    "quality_blocked": {"queued", "archived"},
    "generation_completed": {"queued", "archived"},
    "failed": {"queued", "archived"},
    "timeout": {"queued", "archived"},
    "cancelled": {"queued", "archived"},
    "archived": set(),
}

_LEGACY_PROJECTION: dict[ReportLifecycleStatus, tuple[str, str]] = {
    "queued": ("queued", "queued"),
    "evidence_checking": ("running", "evidence_gate"),
    "evidence_blocked": ("quality_failed", "evidence_gate_failed"),
    "generating": ("running", "orchestrator"),
    "quality_checking": ("running", "quality_gate"),
    "quality_blocked": ("quality_failed", "quality_failed"),
    "generation_completed": ("completed", "completed"),
    "failed": ("failed", "failed"),
    "timeout": ("timeout", "timeout"),
    "cancelled": ("cancelled", "cancelled"),
    "archived": ("archived", "archived"),
}

_FAILED_VERIFICATION_STATUSES = {"failed", "unsupported", "missing_evidence", "numeric_mismatch"}
_REPORT_ARTIFACT_TYPES = {"markdown", "html", "json"}


def resolve_lifecycle_status(task: Any) -> ReportLifecycleStatus:
    """Project legacy task columns into the canonical lifecycle."""

    status = _text(getattr(task, "status", None)) or "queued"
    stage = _text(getattr(task, "current_stage", None))
    if status == "running":
        if stage == "evidence_gate":
            return "evidence_checking"
        if stage == "quality_gate":
            return "quality_checking"
        return "generating"
    if status == "quality_failed":
        return "evidence_blocked" if stage == "evidence_gate_failed" else "quality_blocked"
    mapping: dict[str, ReportLifecycleStatus] = {
        "queued": "queued",
        "completed": "generation_completed",
        "failed": "failed",
        "timeout": "timeout",
        "cancelled": "cancelled",
        "archived": "archived",
    }
    return mapping.get(status, "failed")


def apply_report_transition(
    task: Any,
    target: ReportLifecycleStatus,
    *,
    stage_override: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Validate and apply a canonical transition to a legacy ORM task object."""

    current = resolve_lifecycle_status(task)
    if target != current and target not in _LEGAL_TRANSITIONS[current]:
        raise InvalidReportTransition(f"Illegal report transition: {current} -> {target}")
    legacy_status, legacy_stage = _LEGACY_PROJECTION[target]
    if stage_override:
        legacy_stage = stage_override
    task.status = legacy_status
    task.current_stage = legacy_stage
    metadata = dict(getattr(task, "metadata_json", None) or {})
    runtime = dict(metadata.get("report_runtime") or {})
    transition = {
        "from": current,
        "to": target,
        "legacy_status": legacy_status,
        "legacy_current_stage": legacy_stage,
    }
    if reason:
        transition["reason"] = reason
    runtime.update(
        {
            "schema_version": "report_runtime.v1",
            "lifecycle_status": target,
            "last_transition": transition,
        }
    )
    metadata["report_runtime"] = runtime
    task.metadata_json = metadata
    return transition


def restore_report_transition(
    task: Any,
    target: ReportLifecycleStatus,
    *,
    reason: str = "checkpoint_restore",
) -> dict[str, Any]:
    """Restore an in-progress lifecycle when retrying a checkpointed node.

    This is intentionally narrower than a normal transition: only a failed or
    timed-out task may be restored, and only to a node execution stage.
    """

    current = resolve_lifecycle_status(task)
    allowed_targets: set[ReportLifecycleStatus] = {"evidence_checking", "generating", "quality_checking"}
    if current not in {"failed", "timeout"} or target not in allowed_targets:
        raise InvalidReportTransition(f"Illegal checkpoint restore: {current} -> {target}")
    legacy_status, legacy_stage = _LEGACY_PROJECTION[target]
    task.status = legacy_status
    task.current_stage = legacy_stage
    metadata = dict(getattr(task, "metadata_json", None) or {})
    runtime = dict(metadata.get("report_runtime") or {})
    transition = {
        "from": current,
        "to": target,
        "legacy_status": legacy_status,
        "legacy_current_stage": legacy_stage,
        "reason": reason,
        "checkpoint_restore": True,
    }
    runtime.update(
        {
            "schema_version": "report_runtime.v1",
            "lifecycle_status": target,
            "last_transition": transition,
        }
    )
    metadata["report_runtime"] = runtime
    task.metadata_json = metadata
    return transition


def build_report_run_state(task: Any) -> ReportRunState:
    """Build the single product-facing state/readiness projection for a task."""

    metadata = dict(getattr(task, "metadata_json", None) or {})
    lifecycle = resolve_lifecycle_status(task)
    legacy_task = "report_runtime" not in metadata
    evidence_state = _evidence_state(metadata, lifecycle=lifecycle, legacy_task=legacy_task)
    quality_state = _quality_state(task, metadata, lifecycle=lifecycle, legacy_task=legacy_task)
    claim_state = _claim_state(list(getattr(task, "claims", None) or []))
    artifact_state = _artifact_state(list(getattr(task, "artifacts", None) or []))
    delivery = _delivery_readiness(
        lifecycle=lifecycle,
        evidence_state=evidence_state,
        quality_state=quality_state,
        claim_state=claim_state,
        artifact_state=artifact_state,
    )
    return {
        "schema_version": "report_run_state.v1",
        "task_id": _text(getattr(task, "task_id", None)),
        "symbol": _text(getattr(task, "symbol", None)),
        "period": _text(getattr(task, "period", None)),
        "report_type": _text(getattr(task, "report_type", None)) or "equity_research",
        "run_mode": _text(metadata.get("run_mode")) or "queue_only",
        "lifecycle_status": lifecycle,
        "legacy_status": _text(getattr(task, "status", None)),
        "legacy_current_stage": _text(getattr(task, "current_stage", None)),
        "evidence_state": evidence_state,
        "quality_state": quality_state,
        "claim_state": claim_state,
        "artifact_state": artifact_state,
        "delivery_readiness": delivery,
        "export_readiness": {
            "status": "ready" if delivery["can_export_formal_package"] else "blocked",
            "can_export_formal_package": delivery["can_export_formal_package"],
            "blocking_reasons": list(delivery["blocking_reasons"]),
            "required_actions": list(delivery["required_actions"]),
            "supported_formats": ["markdown", "html", "pdf", "docx", "json", "csv"],
            "pending_formats": [],
        },
    }


def _evidence_state(
    metadata: dict[str, Any],
    *,
    lifecycle: ReportLifecycleStatus,
    legacy_task: bool,
) -> dict[str, Any]:
    gate = metadata.get("pre_generation_evidence_gate")
    if not isinstance(gate, dict):
        inferred = legacy_task and lifecycle == "generation_completed"
        return {
            "status": "legacy_inferred" if inferred else "pending",
            "checked": inferred,
            "blocked": lifecycle == "evidence_blocked",
            "draft_ready": inferred,
            "delivery_ready": inferred,
            "blocking_reasons": [] if inferred else ["evidence_check_pending"],
            "inferred_from_legacy_status": inferred,
        }
    reasons = [_reason_code(item) for item in gate.get("delivery_blocked_reasons") or gate.get("blocking_reasons") or []]
    return {
        "status": _text(gate.get("status")) or "pending",
        "checked": True,
        "blocked": bool(gate.get("blocked")),
        "draft_ready": bool(gate.get("draft_ready")),
        "delivery_ready": bool(gate.get("delivery_ready")),
        "blocking_reasons": [item for item in reasons if item],
        "inferred_from_legacy_status": False,
    }


def _quality_state(
    task: Any,
    metadata: dict[str, Any],
    *,
    lifecycle: ReportLifecycleStatus,
    legacy_task: bool,
) -> dict[str, Any]:
    result = metadata.get("quality_result")
    result = result if isinstance(result, dict) else {}
    gate = result.get("delivery_gate")
    gate = gate if isinstance(gate, dict) else {}
    delivery_pass = gate.get("delivery_pass")
    inferred = delivery_pass is None and legacy_task and lifecycle == "generation_completed"
    if inferred:
        delivery_pass = True
    issues = result.get("top_quality_issues")
    return {
        "status": "passed" if delivery_pass is True else ("failed" if delivery_pass is False else "pending"),
        "checked": delivery_pass is not None,
        "delivery_pass": delivery_pass,
        "quality_score": getattr(task, "quality_score", None),
        "issue_count": len(issues) if isinstance(issues, list) else 0,
        "inferred_from_legacy_status": inferred,
    }


def _claim_state(claims: list[Any]) -> dict[str, Any]:
    statuses = Counter(_text(getattr(claim, "review_status", None)) or "pending" for claim in claims)
    unsupported = sum(
        1
        for claim in claims
        if (_text(getattr(claim, "verification_status", None)) or "pending") in _FAILED_VERIFICATION_STATUSES
    )
    pending = int(statuses.get("pending", 0)) + int(statuses.get("regenerate_requested", 0))
    return {
        "total_count": len(claims),
        "approved_count": int(statuses.get("approved", 0)),
        "pending_count": pending,
        "rejected_count": int(statuses.get("rejected", 0)),
        "unsupported_count": unsupported,
        "review_status_counts": dict(sorted(statuses.items())),
        "review_complete": bool(claims) and pending == 0 and int(statuses.get("rejected", 0)) == 0,
    }


def _artifact_state(artifacts: list[Any]) -> dict[str, Any]:
    types = sorted({_text(getattr(item, "artifact_type", None)) for item in artifacts if _text(getattr(item, "artifact_type", None))})
    return {
        "count": len(artifacts),
        "types": types,
        "report_available": bool(set(types).intersection(_REPORT_ARTIFACT_TYPES)),
    }


def _delivery_readiness(
    *,
    lifecycle: ReportLifecycleStatus,
    evidence_state: dict[str, Any],
    quality_state: dict[str, Any],
    claim_state: dict[str, Any],
    artifact_state: dict[str, Any],
) -> DeliveryReadiness:
    blockers: list[str] = []
    warnings: list[str] = []
    if lifecycle != "generation_completed":
        blockers.append("report_task_not_completed")
    if claim_state["rejected_count"]:
        blockers.append("rejected_claims_present")
    if claim_state["pending_count"]:
        blockers.append("pending_claim_review")
    if not evidence_state["checked"]:
        blockers.append("evidence_check_pending")
    elif not evidence_state["delivery_ready"]:
        blockers.append("evidence_not_delivery_ready")
    if not quality_state["checked"]:
        blockers.append("quality_check_pending")
    elif quality_state["delivery_pass"] is not True:
        blockers.append("quality_gate_failed")
    if claim_state["unsupported_count"]:
        blockers.append("unsupported_claims_present")
    if claim_state["total_count"] == 0:
        blockers.append("claims_missing")
    elif claim_state["approved_count"] == 0:
        blockers.append("approved_claims_missing")
    if not artifact_state["report_available"]:
        blockers.append("report_artifact_missing")
    if evidence_state.get("inferred_from_legacy_status"):
        warnings.append("legacy_evidence_state_inferred")
    if quality_state.get("inferred_from_legacy_status"):
        warnings.append("legacy_quality_state_inferred")
    blockers = _dedupe(blockers)
    review_blockers = {"pending_claim_review", "rejected_claims_present", "approved_claims_missing"}
    can_review = artifact_state["report_available"] and bool(review_blockers.intersection(blockers))
    can_deliver = not blockers
    if can_deliver:
        status = "export_ready"
    elif can_review:
        status = "review_required"
    elif artifact_state["report_available"] and lifecycle == "quality_blocked":
        status = "remediation_required"
    elif lifecycle in {"evidence_checking", "generating", "quality_checking"}:
        status = "in_progress"
    elif lifecycle == "queued":
        status = "queued"
    else:
        status = "blocked"
    return {
        "status": status,
        "can_generate_draft": lifecycle == "queued",
        "can_enter_human_review": can_review,
        "can_deliver_formal_report": can_deliver,
        "can_export_formal_package": can_deliver,
        "blocking_reasons": blockers,
        "warnings": warnings,
        "required_actions": _required_actions(blockers),
    }


def _required_actions(blockers: list[str]) -> list[str]:
    actions: list[str] = []
    mapping = {
        "report_task_not_completed": "complete_report_generation",
        "rejected_claims_present": "resolve_rejected_claims",
        "pending_claim_review": "review_pending_claims",
        "evidence_check_pending": "run_evidence_gate",
        "evidence_not_delivery_ready": "supplement_authoritative_evidence",
        "quality_check_pending": "run_quality_gate",
        "quality_gate_failed": "resolve_quality_blockers",
        "unsupported_claims_present": "resolve_unsupported_claims",
        "claims_missing": "import_or_generate_claims",
        "approved_claims_missing": "approve_supported_claims",
        "report_artifact_missing": "generate_report_artifact",
    }
    for blocker in blockers:
        action = mapping.get(blocker)
        if action and action not in actions:
            actions.append(action)
    return actions


def _reason_code(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("type") or value.get("key") or value.get("code"))
    return _text(value)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip() if value is not None else ""
