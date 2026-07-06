"""Claim review workflow service for the P0 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import ClaimEvidence, EvidenceItem, ReportClaim, ReportTaskEvent, ReviewRecord


class ClaimNotFound(LookupError):
    """Raised when a report claim does not exist."""


class ClaimReviewService:
    """List claims and apply audited review decisions."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def list_claims(
        self,
        *,
        task_id: str | None = None,
        status: str | None = None,
        verification_status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session_factory() as session:
            stmt = (
                select(ReportClaim)
                .options(selectinload(ReportClaim.evidence_links).selectinload(ClaimEvidence.evidence_item))
                .order_by(ReportClaim.id.desc())
                .limit(limit)
            )
            stmt = self._apply_filters(
                stmt,
                task_id=task_id,
                status=status,
                verification_status=verification_status,
                q=q,
            )
            claims = [self.serialize_claim(claim, include_evidence=True) for claim in session.scalars(stmt).unique().all()]
        return {"items": claims, "total": len(claims)}

    def get_claim(self, claim_id: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            claim = self._get_claim(session, claim_id)
            return self.serialize_claim(claim, include_evidence=True, include_review_records=True, session=session)

    def approve(self, claim_id: int | str, *, reviewer: str | None = None, comment: str | None = None) -> dict[str, Any]:
        return self._set_review_status(claim_id, status="approved", decision="approve", reviewer=reviewer, comment=comment)

    def reject(self, claim_id: int | str, *, reviewer: str | None = None, comment: str | None = None) -> dict[str, Any]:
        return self._set_review_status(claim_id, status="rejected", decision="reject", reviewer=reviewer, comment=comment)

    def edit(
        self,
        claim_id: int | str,
        *,
        claim_text: str | None = None,
        review_status: str | None = None,
        reviewer: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            claim = self._get_claim(session, claim_id)
            before = snapshot_claim(claim)
            if claim_text is not None:
                claim.claim_text = claim_text
            if review_status:
                claim.review_status = review_status
            metadata = dict(claim.metadata_json or {})
            metadata["last_review_action"] = "edit"
            claim.metadata_json = metadata
            after = snapshot_claim(claim)
            session.add(
                ReviewRecord(
                    target_type="report_claim",
                    target_id=str(claim.id),
                    decision="edit",
                    comment=comment,
                    before_value=before,
                    after_value=after,
                    reviewer=reviewer,
                )
            )
            session.commit()
            return self.get_claim(claim.id)

    def regenerate(
        self,
        claim_id: int | str,
        *,
        reviewer: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            claim = self._get_claim(session, claim_id)
            before = snapshot_claim(claim)
            claim.review_status = "regenerate_requested"
            metadata = dict(claim.metadata_json or {})
            metadata["regenerate_requested"] = True
            metadata["last_review_action"] = "regenerate"
            claim.metadata_json = metadata
            after = snapshot_claim(claim)
            session.add(
                ReviewRecord(
                    target_type="report_claim",
                    target_id=str(claim.id),
                    decision="regenerate",
                    comment=comment,
                    before_value=before,
                    after_value=after,
                    reviewer=reviewer,
                )
            )
            session.add(
                ReportTaskEvent(
                    task_id=claim.task_id,
                    stage="claim_review",
                    status="regenerate_requested",
                    message=f"Regenerate requested for claim {claim.id}",
                    metadata_json={"claim_id": claim.id},
                )
            )
            session.commit()
            return self.get_claim(claim.id)

    def serialize_claim(
        self,
        claim: ReportClaim,
        *,
        include_evidence: bool,
        include_review_records: bool = False,
        session: Session | None = None,
    ) -> dict[str, Any]:
        payload = {
            "id": claim.id,
            "task_id": claim.task_id,
            "section_name": claim.section_name,
            "claim_text": claim.claim_text,
            "claim_type": claim.claim_type,
            "is_critical": claim.is_critical,
            "critical_claim_type": claim.critical_claim_type,
            "verification_status": claim.verification_status,
            "numeric_check_status": claim.numeric_check_status,
            "citation_check_status": claim.citation_check_status,
            "confidence": claim.confidence,
            "review_status": claim.review_status,
            "metadata": claim.metadata_json or {},
            "evidence_count": len(claim.evidence_links),
        }
        if include_evidence:
            payload["evidence"] = [
                serialize_evidence_link(link)
                for link in sorted(claim.evidence_links, key=lambda item: item.evidence_item_id)
            ]
        if include_review_records:
            active_session = session
            close_session = False
            if active_session is None:
                active_session = self.session_factory()
                close_session = True
            try:
                records = active_session.scalars(
                    select(ReviewRecord)
                    .where(ReviewRecord.target_type == "report_claim", ReviewRecord.target_id == str(claim.id))
                    .order_by(ReviewRecord.created_at.desc(), ReviewRecord.id.desc())
                ).all()
                payload["review_records"] = [serialize_review_record(record) for record in records]
            finally:
                if close_session:
                    active_session.close()
        return payload

    def _apply_filters(
        self,
        stmt: Select[tuple[ReportClaim]],
        *,
        task_id: str | None,
        status: str | None,
        verification_status: str | None,
        q: str | None,
    ) -> Select[tuple[ReportClaim]]:
        if task_id:
            stmt = stmt.where(ReportClaim.task_id == task_id.strip())
        if status:
            stmt = stmt.where(ReportClaim.review_status == status.strip())
        if verification_status:
            stmt = stmt.where(ReportClaim.verification_status == verification_status.strip())
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    ReportClaim.claim_text.ilike(needle),
                    ReportClaim.section_name.ilike(needle),
                    ReportClaim.claim_type.ilike(needle),
                )
            )
        return stmt

    def _set_review_status(
        self,
        claim_id: int | str,
        *,
        status: str,
        decision: str,
        reviewer: str | None,
        comment: str | None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            claim = self._get_claim(session, claim_id)
            before = snapshot_claim(claim)
            claim.review_status = status
            metadata = dict(claim.metadata_json or {})
            metadata["last_review_action"] = decision
            claim.metadata_json = metadata
            after = snapshot_claim(claim)
            session.add(
                ReviewRecord(
                    target_type="report_claim",
                    target_id=str(claim.id),
                    decision=decision,
                    comment=comment,
                    before_value=before,
                    after_value=after,
                    reviewer=reviewer,
                )
            )
            session.commit()
            return self.get_claim(claim.id)

    def _get_claim(self, session: Session, claim_id: int | str) -> ReportClaim:
        try:
            normalized_id = int(claim_id)
        except (TypeError, ValueError):
            raise ClaimNotFound(str(claim_id)) from None
        claim = session.scalar(
            select(ReportClaim)
            .where(ReportClaim.id == normalized_id)
            .options(selectinload(ReportClaim.evidence_links).selectinload(ClaimEvidence.evidence_item))
        )
        if claim is None:
            raise ClaimNotFound(str(claim_id))
        return claim


def snapshot_claim(claim: ReportClaim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "section_name": claim.section_name,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "verification_status": claim.verification_status,
        "numeric_check_status": claim.numeric_check_status,
        "citation_check_status": claim.citation_check_status,
        "confidence": claim.confidence,
        "review_status": claim.review_status,
        "metadata": claim.metadata_json or {},
    }


def serialize_evidence_link(link: ClaimEvidence) -> dict[str, Any]:
    item: EvidenceItem = link.evidence_item
    return {
        "support_type": link.support_type,
        "id": item.id,
        "evidence_id": item.evidence_id,
        "title": item.title,
        "snippet": _snippet(item.content),
        "source_type": item.source_type,
        "trust_level": item.trust_level,
        "source_url": item.source_url,
        "page_no": item.page_no,
    }


def serialize_review_record(record: ReviewRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "target_type": record.target_type,
        "target_id": record.target_id,
        "decision": record.decision,
        "comment": record.comment,
        "before_value": record.before_value,
        "after_value": record.after_value,
        "reviewer": record.reviewer,
        "created_at": _dt(record.created_at),
    }


def _snippet(content: str | None, *, limit: int = 220) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
