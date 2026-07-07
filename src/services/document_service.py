"""Document processing center query service for the P0 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import ClaimEvidence, Company, Document, DocumentProcessingStep, EvidenceItem


class DocumentNotFound(LookupError):
    """Raised when a document does not exist."""


class DocumentService:
    """List documents and inspect processing paths."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def list_documents(
        self,
        *,
        company: str | None = None,
        batch_id: str | None = None,
        status: str | None = None,
        step: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session_factory() as session:
            stmt = (
                select(Document)
                .options(
                    selectinload(Document.company),
                    selectinload(Document.processing_steps),
                    selectinload(Document.evidence_items),
                )
                .order_by(Document.created_at.desc(), Document.id.desc())
                .limit(limit)
            )
            stmt = self._apply_filters(stmt, company=company, batch_id=batch_id, status=status, step=step, q=q)
            items = [self.serialize_document(document, include_detail=False) for document in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_document(self, document_id: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            document = self._get_document(session, document_id)
            return self.serialize_document(document, include_detail=True)

    def serialize_document(self, document: Document, *, include_detail: bool) -> dict[str, Any]:
        steps = sorted(document.processing_steps, key=lambda item: item.id or 0)
        evidence_items = sorted(document.evidence_items, key=lambda item: item.id or 0)
        claims = linked_claims(evidence_items)
        payload = {
            "id": document.id,
            "company_id": document.company_id,
            "company": serialize_company(document.company),
            "datasource_id": document.datasource_id,
            "batch_id": document.batch_id,
            "title": document.title,
            "doc_type": document.doc_type,
            "report_period": document.report_period,
            "source_url": document.source_url,
            "file_path": document.file_path,
            "content_hash": document.content_hash,
            "parse_status": document.parse_status,
            "created_at": _dt(document.created_at),
            "step_count": len(steps),
            "failed_step_count": sum(1 for step in steps if step.status == "failed"),
            "evidence_count": len(evidence_items),
            "claim_count": len(claims),
            "latest_step": serialize_step(steps[-1]) if steps else None,
        }
        if include_detail:
            payload["processing_steps"] = [serialize_step(step) for step in steps]
            payload["evidence"] = [serialize_evidence(item) for item in evidence_items]
            payload["claims"] = claims
        return payload

    def _apply_filters(
        self,
        stmt: Select[tuple[Document]],
        *,
        company: str | None,
        batch_id: str | None,
        status: str | None,
        step: str | None,
        q: str | None,
    ) -> Select[tuple[Document]]:
        if company:
            needle = f"%{company.strip()}%"
            stmt = stmt.where(Document.company.has(or_(Company.name.ilike(needle), Company.symbol.ilike(needle))))
        if batch_id:
            stmt = stmt.where(Document.batch_id == batch_id.strip())
        if status:
            stmt = stmt.where(Document.parse_status == status.strip())
        if step:
            stmt = stmt.where(Document.processing_steps.any(DocumentProcessingStep.step_name == step.strip()))
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    Document.title.ilike(needle),
                    Document.doc_type.ilike(needle),
                    Document.source_url.ilike(needle),
                    Document.file_path.ilike(needle),
                    Document.batch_id.ilike(needle),
                )
            )
        return stmt

    def _get_document(self, session: Session, document_id: int | str) -> Document:
        try:
            normalized_id = int(document_id)
        except (TypeError, ValueError):
            raise DocumentNotFound(str(document_id)) from None
        document = session.scalar(
            select(Document)
            .where(Document.id == normalized_id)
            .options(
                selectinload(Document.company),
                selectinload(Document.processing_steps),
                selectinload(Document.evidence_items)
                .selectinload(EvidenceItem.claim_links)
                .selectinload(ClaimEvidence.claim),
            )
        )
        if document is None:
            raise DocumentNotFound(str(document_id))
        return document


def serialize_company(company: Company | None) -> dict[str, Any] | None:
    if company is None:
        return None
    return {
        "id": company.id,
        "name": company.name,
        "symbol": company.symbol,
        "market": company.market,
        "industry": company.industry,
    }


def serialize_step(step: DocumentProcessingStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "document_id": step.document_id,
        "step_name": step.step_name,
        "status": step.status,
        "started_at": _dt(step.started_at),
        "finished_at": _dt(step.finished_at),
        "error_message": step.error_message,
        "metadata": step.metadata_json or {},
    }


def serialize_evidence(item: EvidenceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "evidence_id": item.evidence_id,
        "chunk_id": item.chunk_id,
        "source_type": item.source_type,
        "trust_level": item.trust_level,
        "title": item.title,
        "snippet": _snippet(item.content),
        "source_url": item.source_url,
        "page_no": item.page_no,
    }


def linked_claims(evidence_items: list[EvidenceItem]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    claims: list[dict[str, Any]] = []
    for item in evidence_items:
        for link in item.claim_links:
            claim = link.claim
            if claim.id in seen:
                continue
            seen.add(claim.id)
            claims.append(
                {
                    "id": claim.id,
                    "task_id": claim.task_id,
                    "section_name": claim.section_name,
                    "claim_text": claim.claim_text,
                    "claim_type": claim.claim_type,
                    "verification_status": claim.verification_status,
                    "review_status": claim.review_status,
                }
            )
    return sorted(claims, key=lambda item: int(item["id"]))


def _snippet(content: str | None, *, limit: int = 220) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
