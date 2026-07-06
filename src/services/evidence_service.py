"""Evidence center query service for the P0 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import ClaimEvidence, Company, Document, EvidenceItem, ReportClaim


class EvidenceNotFound(LookupError):
    """Raised when an evidence item does not exist."""


class EvidenceService:
    """List and inspect DB-backed evidence with claim/document joins."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def list_evidence(
        self,
        *,
        company: str | None = None,
        period: str | None = None,
        source_type: str | None = None,
        trust_level: str | None = None,
        task_id: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session_factory() as session:
            stmt = (
                select(EvidenceItem)
                .options(
                    selectinload(EvidenceItem.company),
                    selectinload(EvidenceItem.document),
                    selectinload(EvidenceItem.claim_links).selectinload(ClaimEvidence.claim),
                )
                .order_by(EvidenceItem.created_at.desc(), EvidenceItem.id.desc())
                .limit(limit)
            )
            stmt = self._apply_filters(
                stmt,
                company=company,
                period=period,
                source_type=source_type,
                trust_level=trust_level,
                task_id=task_id,
                q=q,
            )
            items = [self.serialize_evidence(item, include_content=False) for item in session.scalars(stmt).unique().all()]

        return {"items": items, "total": len(items)}

    def get_evidence(self, evidence_ref: str | int) -> dict[str, Any]:
        with self.session_factory() as session:
            stmt = (
                select(EvidenceItem)
                .options(
                    selectinload(EvidenceItem.company),
                    selectinload(EvidenceItem.document),
                    selectinload(EvidenceItem.claim_links).selectinload(ClaimEvidence.claim),
                )
                .where(_evidence_ref_clause(evidence_ref))
            )
            item = session.scalar(stmt)
            if item is None:
                raise EvidenceNotFound(str(evidence_ref))
            return self.serialize_evidence(item, include_content=True)

    def serialize_evidence(self, item: EvidenceItem, *, include_content: bool) -> dict[str, Any]:
        metadata = item.metadata_json or {}
        claims = [serialize_claim(link.claim) for link in sorted(item.claim_links, key=lambda link: link.claim_id)]
        document = serialize_document(item.document)
        task_ids = sorted({claim["task_id"] for claim in claims if claim.get("task_id")})
        if not task_ids and metadata.get("task_id"):
            task_ids = [str(metadata["task_id"])]
        payload = {
            "id": item.id,
            "evidence_id": item.evidence_id,
            "company_id": item.company_id,
            "company": serialize_company(item),
            "document_id": item.document_id,
            "document": document,
            "chunk_id": item.chunk_id,
            "source_type": item.source_type,
            "trust_level": item.trust_level,
            "title": item.title,
            "snippet": _snippet(item.content),
            "source_url": item.source_url,
            "page_no": item.page_no,
            "metadata": metadata,
            "task_ids": task_ids,
            "claims": claims,
            "claim_count": len(claims),
            "created_at": _dt(item.created_at),
        }
        if include_content:
            payload["content"] = item.content
        return payload

    def _apply_filters(
        self,
        stmt: Select[tuple[EvidenceItem]],
        *,
        company: str | None,
        period: str | None,
        source_type: str | None,
        trust_level: str | None,
        task_id: str | None,
        q: str | None,
    ) -> Select[tuple[EvidenceItem]]:
        if source_type:
            stmt = stmt.where(EvidenceItem.source_type == source_type)
        if trust_level:
            stmt = stmt.where(EvidenceItem.trust_level == trust_level)
        if company:
            normalized = f"%{company.strip()}%"
            stmt = stmt.where(
                EvidenceItem.company.has(
                    or_(
                        Company.name.ilike(normalized),
                        Company.symbol.ilike(normalized),
                    )
                )
            )
        if period:
            normalized_period = period.strip()
            stmt = stmt.where(
                or_(
                    EvidenceItem.document.has(Document.report_period == normalized_period),
                    EvidenceItem.metadata_json["period"].as_string() == normalized_period,
                )
            )
        if task_id:
            normalized_task_id = task_id.strip()
            stmt = stmt.where(
                or_(
                    EvidenceItem.claim_links.any(
                        ClaimEvidence.claim.has(ReportClaim.task_id == normalized_task_id)
                    ),
                    EvidenceItem.metadata_json["task_id"].as_string() == normalized_task_id,
                    EvidenceItem.document.has(Document.batch_id == normalized_task_id),
                )
            )
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    EvidenceItem.evidence_id.ilike(needle),
                    EvidenceItem.title.ilike(needle),
                    EvidenceItem.content.ilike(needle),
                    EvidenceItem.source_url.ilike(needle),
                )
            )
        return stmt


def serialize_company(item: EvidenceItem) -> dict[str, Any] | None:
    if item.company is None:
        return None
    return {
        "id": item.company.id,
        "name": item.company.name,
        "symbol": item.company.symbol,
        "market": item.company.market,
        "industry": item.company.industry,
    }


def serialize_document(document: Document | None) -> dict[str, Any] | None:
    if document is None:
        return None
    return {
        "id": document.id,
        "company_id": document.company_id,
        "datasource_id": document.datasource_id,
        "batch_id": document.batch_id,
        "title": document.title,
        "doc_type": document.doc_type,
        "report_period": document.report_period,
        "source_url": document.source_url,
        "file_path": document.file_path,
        "parse_status": document.parse_status,
        "created_at": _dt(document.created_at),
    }


def serialize_claim(claim: ReportClaim) -> dict[str, Any]:
    return {
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
    }


def _evidence_ref_clause(evidence_ref: str | int) -> Any:
    text = str(evidence_ref).strip()
    if text.isdigit():
        return or_(EvidenceItem.id == int(text), EvidenceItem.evidence_id == text)
    return EvidenceItem.evidence_id == text


def _snippet(content: str | None, *, limit: int = 220) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
