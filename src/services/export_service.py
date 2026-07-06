"""Export center entry service for artifact review in P0."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import ReportArtifact, ReportClaim, ReportTask
from src.services.report_task_service import serialize_artifact


class ExportTaskNotFound(LookupError):
    """Raised when export review is requested for an unknown task."""


class ExportService:
    """Summarize task artifacts and review readiness."""

    REVIEWED_ARTIFACT_TYPES = {
        "markdown",
        "html",
        "json",
        "claims",
        "evidence",
        "verification_report",
    }

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def list_export_entries(self, *, status: str | None = None, symbol: str | None = None, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session_factory() as session:
            stmt = (
                select(ReportTask)
                .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.claims))
                .order_by(ReportTask.created_at.desc(), ReportTask.id.desc())
                .limit(limit)
            )
            if status:
                stmt = stmt.where(ReportTask.status == status)
            if symbol:
                stmt = stmt.where(ReportTask.symbol == symbol.strip().upper())
            items = [self.serialize_export_entry(task) for task in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_export_entry(self, task_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            task = session.scalar(
                select(ReportTask)
                .where(ReportTask.task_id == task_id)
                .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.claims))
            )
            if task is None:
                raise ExportTaskNotFound(task_id)
            return self.serialize_export_entry(task, include_claims=True)

    def serialize_export_entry(self, task: ReportTask, *, include_claims: bool = False) -> dict[str, Any]:
        artifacts = [serialize_artifact(item) for item in sorted(task.artifacts, key=lambda item: item.id or 0)]
        claim_counts = Counter(claim.review_status for claim in task.claims)
        blocked_reasons = export_blockers(task, claim_counts)
        payload = {
            "task_id": task.task_id,
            "symbol": task.symbol,
            "period": task.period,
            "status": task.status,
            "quality_score": task.quality_score,
            "created_at": _dt(task.created_at),
            "finished_at": _dt(task.finished_at),
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "review_status_counts": dict(sorted(claim_counts.items())),
            "approved_claim_count": int(claim_counts.get("approved", 0)),
            "pending_claim_count": int(claim_counts.get("pending", 0)),
            "rejected_claim_count": int(claim_counts.get("rejected", 0)),
            "official_export_ready": not blocked_reasons,
            "blocked_reasons": blocked_reasons,
            "formal_export_note": "P0 entry only; PDF/DOCX/CSV package generation is implemented in P3.2.",
        }
        if include_claims:
            payload["claims"] = [serialize_claim(claim) for claim in sorted(task.claims, key=lambda item: item.id or 0)]
        return payload

    def artifact_distribution(self) -> dict[str, int]:
        with self.session_factory() as session:
            rows = session.execute(select(ReportArtifact.artifact_type, func.count()).group_by(ReportArtifact.artifact_type)).all()
        return {str(key or "unknown"): int(value or 0) for key, value in rows}


def export_blockers(task: ReportTask, claim_counts: Counter[str]) -> list[str]:
    blockers: list[str] = []
    if task.status != "completed":
        blockers.append("report_task_not_completed")
    if int(claim_counts.get("rejected", 0)) > 0:
        blockers.append("rejected_claims_present")
    if int(claim_counts.get("pending", 0)) > 0:
        blockers.append("pending_claim_review")
    artifact_types = {artifact.artifact_type for artifact in task.artifacts}
    if not artifact_types.intersection({"markdown", "html", "json"}):
        blockers.append("report_artifact_missing")
    return blockers


def serialize_claim(claim: ReportClaim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "section_name": claim.section_name,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "verification_status": claim.verification_status,
        "review_status": claim.review_status,
    }


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
