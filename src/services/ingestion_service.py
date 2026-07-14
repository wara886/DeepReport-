"""Ingestion batch lifecycle service for the P1 workbench."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.db.models import Company, DataSource, Document, EvidenceItem, IngestionBatch, IngestionBatchEvent, Workspace


class IngestionBatchNotFound(LookupError):
    """Raised when an ingestion batch cannot be found."""


class IngestionBatchConflict(RuntimeError):
    """Raised when a batch transition is not allowed."""


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RUNNING_STATUSES = {"running"}
RETRYABLE_STATUSES = {"failed", "cancelled"}


class IngestionService:
    """Create, inspect, and transition datasource ingestion batches."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def create_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _required_string(payload.get("name"), "name")
        batch_id = _optional_string(payload.get("batch_id")) or _generated_batch_id(payload)
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, payload.get("workspace_id") or payload.get("workspace"))
            datasource = _get_datasource_optional(session, payload.get("data_source_id") or payload.get("source_key"))
            batch = IngestionBatch(
                batch_id=batch_id,
                workspace_id=workspace.id if workspace else None,
                data_source_id=datasource.id if datasource else None,
                source_key=_optional_string(payload.get("source_key")) or (datasource.source_key if datasource else None),
                name=name,
                target_type=_optional_string(payload.get("target_type")) or "documents",
                symbol=_optional_string(payload.get("symbol")),
                period=_optional_string(payload.get("period")),
                query=_optional_string(payload.get("query")),
                status="queued",
                metadata_json=_dict_or_none(payload.get("metadata")) or {},
            )
            batch.events.append(
                IngestionBatchEvent(
                    batch_id=batch.batch_id,
                    stage="created",
                    status="queued",
                    message="采集批次已创建",
                    metadata_json={"source_key": batch.source_key, "target_type": batch.target_type},
                )
            )
            session.add(batch)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise IngestionBatchConflict(f"Ingestion batch already exists: {batch_id}") from exc
            return self.serialize_batch(batch, include_events=True)

    def list_batches(
        self,
        *,
        workspace_id: int | str | None = None,
        status: str | None = None,
        source_key: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session_factory() as session:
            stmt = (
                select(IngestionBatch)
                .options(selectinload(IngestionBatch.data_source), selectinload(IngestionBatch.events))
                .order_by(IngestionBatch.created_at.desc(), IngestionBatch.id.desc())
                .limit(limit)
            )
            if workspace_id not in (None, ""):
                workspace = _get_workspace_optional(session, workspace_id)
                stmt = stmt.where(IngestionBatch.workspace_id == (workspace.id if workspace else None))
            if status:
                stmt = stmt.where(IngestionBatch.status == status.strip())
            if source_key:
                stmt = stmt.where(IngestionBatch.source_key == source_key.strip())
            stmt = _apply_search(stmt, q=q)
            items = [self.serialize_batch(batch, include_events=False) for batch in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_batch(self, batch_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            return self.serialize_batch(_get_batch(session, batch_ref), include_events=True)

    def start_batch(self, batch_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            batch = _get_batch(session, batch_ref)
            if batch.status not in {"queued"}:
                raise IngestionBatchConflict(f"Batch {batch.batch_id} cannot be started from status {batch.status}")
            batch.status = "running"
            batch.started_at = _utc_now()
            batch.finished_at = None
            batch.error_message = None
            batch.events.append(IngestionBatchEvent(batch_id=batch.batch_id, stage="run", status="running", message="采集批次已启动"))
            session.commit()
            return self.serialize_batch(batch, include_events=True)

    def complete_batch(self, batch_ref: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as session:
            batch = _get_batch(session, batch_ref)
            if batch.status not in {"queued", "running"}:
                raise IngestionBatchConflict(f"Batch {batch.batch_id} cannot be completed from status {batch.status}")
            batch.status = "completed"
            if batch.started_at is None:
                batch.started_at = _utc_now()
            batch.finished_at = _utc_now()
            batch.error_message = None
            _apply_counts(batch, payload)
            persisted = _persist_ingested_records(session, batch=batch, payload=payload)
            if persisted["document_count"] or persisted["evidence_count"]:
                metadata = dict(batch.metadata_json or {})
                metadata["ingested_document_count"] = int(metadata.get("ingested_document_count") or 0) + persisted["document_count"]
                metadata["ingested_evidence_count"] = int(metadata.get("ingested_evidence_count") or 0) + persisted["evidence_count"]
                metadata["evidence_source_key"] = batch.source_key
                metadata["evidence_return_ready"] = persisted["evidence_count"] > 0
                batch.metadata_json = metadata
                if payload.get("item_count") is None:
                    batch.item_count = max(batch.item_count, persisted["document_count"] + persisted["evidence_count"])
                if payload.get("success_count") is None:
                    batch.success_count = max(batch.success_count, persisted["document_count"] + persisted["evidence_count"])
                if payload.get("failed_count") is None:
                    batch.failed_count = 0
            batch.events.append(
                IngestionBatchEvent(
                    batch_id=batch.batch_id,
                    stage="run",
                    status="completed",
                    message=_optional_string(payload.get("message")) or "采集批次已完成",
                    metadata_json={**(_dict_or_none(payload.get("metadata")) or {}), **persisted},
                )
            )
            _mark_datasource_health(batch.data_source, status="success", error=None)
            session.commit()
            return self.serialize_batch(batch, include_events=True)

    def fail_batch(self, batch_ref: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        error_message = _optional_string(payload.get("error_message")) or _optional_string(payload.get("message")) or "采集失败"
        with self.session_factory() as session:
            batch = _get_batch(session, batch_ref)
            if batch.status in TERMINAL_STATUSES and batch.status != "failed":
                raise IngestionBatchConflict(f"Batch {batch.batch_id} cannot be failed from status {batch.status}")
            batch.status = "failed"
            if batch.started_at is None:
                batch.started_at = _utc_now()
            batch.finished_at = _utc_now()
            batch.error_message = error_message
            _apply_counts(batch, payload)
            batch.events.append(
                IngestionBatchEvent(
                    batch_id=batch.batch_id,
                    stage="run",
                    status="failed",
                    message=error_message,
                    metadata_json=_dict_or_none(payload.get("metadata")),
                )
            )
            _mark_datasource_health(batch.data_source, status="failed", error=error_message)
            session.commit()
            return self.serialize_batch(batch, include_events=True)

    def retry_batch(self, batch_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            batch = _get_batch(session, batch_ref)
            if batch.status not in RETRYABLE_STATUSES:
                raise IngestionBatchConflict(f"Batch {batch.batch_id} cannot be retried from status {batch.status}")
            before = batch.status
            batch.status = "queued"
            batch.retry_count += 1
            batch.started_at = None
            batch.finished_at = None
            batch.error_message = None
            batch.events.append(
                IngestionBatchEvent(
                    batch_id=batch.batch_id,
                    stage="retry",
                    status="queued",
                    message="采集批次已进入重试队列",
                    metadata_json={"previous_status": before, "retry_count": batch.retry_count},
                )
            )
            session.commit()
            return self.serialize_batch(batch, include_events=True)

    def cancel_batch(self, batch_ref: int | str, *, reason: str | None = None) -> dict[str, Any]:
        with self.session_factory() as session:
            batch = _get_batch(session, batch_ref)
            if batch.status in TERMINAL_STATUSES:
                raise IngestionBatchConflict(f"Batch {batch.batch_id} cannot be cancelled from status {batch.status}")
            batch.status = "cancelled"
            batch.finished_at = _utc_now()
            batch.error_message = reason
            batch.events.append(
                IngestionBatchEvent(
                    batch_id=batch.batch_id,
                    stage="cancel",
                    status="cancelled",
                    message=reason or "采集批次已取消",
                )
            )
            session.commit()
            return self.serialize_batch(batch, include_events=True)

    def serialize_batch(self, batch: IngestionBatch, *, include_events: bool) -> dict[str, Any]:
        payload = {
            "id": batch.id,
            "batch_id": batch.batch_id,
            "workspace_id": batch.workspace_id,
            "data_source_id": batch.data_source_id,
            "source_key": batch.source_key,
            "source_name": batch.data_source.name if batch.data_source else None,
            "name": batch.name,
            "target_type": batch.target_type,
            "symbol": batch.symbol,
            "period": batch.period,
            "query": batch.query,
            "status": batch.status,
            "retry_count": batch.retry_count,
            "item_count": batch.item_count,
            "success_count": batch.success_count,
            "failed_count": batch.failed_count,
            "started_at": _dt(batch.started_at),
            "finished_at": _dt(batch.finished_at),
            "error_message": batch.error_message,
            "metadata": batch.metadata_json or {},
            "created_at": _dt(batch.created_at),
        }
        if include_events:
            payload["events"] = [serialize_event(event) for event in sorted(batch.events, key=lambda item: item.id or 0)]
        return payload


def serialize_event(event: IngestionBatchEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "batch_id": event.batch_id,
        "stage": event.stage,
        "status": event.status,
        "message": event.message,
        "metadata": event.metadata_json or {},
        "created_at": _dt(event.created_at),
    }


def _get_batch(session: Session, batch_ref: int | str) -> IngestionBatch:
    text = str(batch_ref).strip()
    condition = IngestionBatch.id == int(text) if text.isdigit() else IngestionBatch.batch_id == text
    batch = session.scalar(
        select(IngestionBatch)
        .where(condition)
        .options(selectinload(IngestionBatch.data_source), selectinload(IngestionBatch.events))
    )
    if batch is None:
        raise IngestionBatchNotFound(text)
    return batch


def _get_workspace_optional(session: Session, workspace_ref: int | str | None) -> Workspace | None:
    if workspace_ref in (None, ""):
        return None
    text = str(workspace_ref).strip()
    condition = Workspace.id == int(text) if text.isdigit() else Workspace.slug == text
    workspace = session.scalar(select(Workspace).where(condition))
    if workspace is None:
        raise IngestionBatchNotFound(f"Workspace not found: {workspace_ref}")
    return workspace


def _get_datasource_optional(session: Session, source_ref: int | str | None) -> DataSource | None:
    if source_ref in (None, ""):
        return None
    text = str(source_ref).strip()
    condition = DataSource.id == int(text) if text.isdigit() else DataSource.source_key == text
    datasource = session.scalar(select(DataSource).where(condition))
    if datasource is None:
        raise IngestionBatchNotFound(f"Datasource not found: {source_ref}")
    return datasource


def _apply_search(stmt: Select[tuple[IngestionBatch]], *, q: str | None) -> Select[tuple[IngestionBatch]]:
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                IngestionBatch.batch_id.ilike(needle),
                IngestionBatch.name.ilike(needle),
                IngestionBatch.symbol.ilike(needle),
                IngestionBatch.period.ilike(needle),
                IngestionBatch.query.ilike(needle),
            )
        )
    return stmt


def _apply_counts(batch: IngestionBatch, payload: dict[str, Any]) -> None:
    if payload.get("item_count") is not None:
        batch.item_count = max(0, int(payload["item_count"]))
    if payload.get("success_count") is not None:
        batch.success_count = max(0, int(payload["success_count"]))
    if payload.get("failed_count") is not None:
        batch.failed_count = max(0, int(payload["failed_count"]))


def _persist_ingested_records(session: Session, *, batch: IngestionBatch, payload: dict[str, Any]) -> dict[str, int]:
    documents_payload = _list_of_dicts(payload.get("documents"))
    evidence_payload = _list_of_dicts(payload.get("evidence_items") or payload.get("evidence"))
    if not documents_payload and not evidence_payload:
        return {"document_count": 0, "evidence_count": 0}

    company = _get_or_create_batch_company(session, batch)
    document_count = 0
    evidence_count = 0
    for document_payload in documents_payload:
        document, created = _get_or_create_document(session, batch=batch, company=company, payload=document_payload)
        if created:
            document_count += 1
        nested_evidence = _list_of_dicts(document_payload.get("evidence_items") or document_payload.get("evidence"))
        if not nested_evidence and _optional_string(document_payload.get("content")):
            nested_evidence = [document_payload]
        for item_payload in nested_evidence:
            if _create_evidence_item(session, batch=batch, company=company, document=document, payload=item_payload):
                evidence_count += 1
    for item_payload in evidence_payload:
        if _create_evidence_item(session, batch=batch, company=company, document=None, payload=item_payload):
            evidence_count += 1
    return {"document_count": document_count, "evidence_count": evidence_count}


def _get_or_create_batch_company(session: Session, batch: IngestionBatch) -> Company | None:
    symbol = _optional_string(batch.symbol)
    if not symbol:
        return None
    market = _market_for_source(batch.source_key)
    existing = session.scalar(select(Company).where(Company.symbol == symbol, Company.market == market))
    if existing is not None:
        return existing
    company = Company(name=symbol, symbol=symbol, market=market, aliases=[symbol])
    session.add(company)
    session.flush()
    return company


def _get_or_create_document(
    session: Session,
    *,
    batch: IngestionBatch,
    company: Company | None,
    payload: dict[str, Any],
) -> tuple[Document, bool]:
    title = _optional_string(payload.get("title")) or _default_document_title(batch)
    content_hash = _optional_string(payload.get("content_hash")) or _stable_hash(
        "document",
        batch.batch_id,
        title,
        payload.get("source_url"),
        payload.get("file_path"),
        payload.get("content"),
    )
    existing = session.scalar(select(Document).where(Document.content_hash == content_hash))
    if existing is not None:
        return existing, False
    document = Document(
        company_id=company.id if company else None,
        datasource_id=batch.data_source_id,
        batch_id=batch.batch_id,
        title=title,
        doc_type=_optional_string(payload.get("doc_type")) or _default_doc_type(batch),
        report_period=_optional_string(payload.get("report_period")) or _optional_string(payload.get("period")) or batch.period,
        source_url=_optional_string(payload.get("source_url")),
        file_path=_optional_string(payload.get("file_path")),
        content_hash=content_hash,
        parse_status=_optional_string(payload.get("parse_status")) or "parsed",
    )
    session.add(document)
    session.flush()
    return document, True


def _create_evidence_item(
    session: Session,
    *,
    batch: IngestionBatch,
    company: Company | None,
    document: Document | None,
    payload: dict[str, Any],
) -> bool:
    content = _optional_string(payload.get("content") or payload.get("snippet") or payload.get("text"))
    if not content:
        return False
    source_type = _optional_string(payload.get("source_type")) or batch.source_key or "local_evidence"
    evidence_id = _optional_string(payload.get("evidence_id")) or _stable_hash(
        "evidence",
        batch.batch_id,
        source_type,
        payload.get("title"),
        content,
    )[:48]
    existing = session.scalar(select(EvidenceItem).where(EvidenceItem.evidence_id == evidence_id))
    if existing is not None:
        return False
    metadata = {
        **(_dict_or_none(payload.get("metadata")) or {}),
        "batch_id": batch.batch_id,
        "source_key": batch.source_key,
        "symbol": _optional_string(payload.get("symbol")) or batch.symbol,
        "period": _optional_string(payload.get("report_period")) or _optional_string(payload.get("period")) or batch.period,
        "ingestion_target_type": batch.target_type,
    }
    from src.schemas.runtime_contracts import normalize_evidence_record

    normalized = normalize_evidence_record(
        {
            **payload,
            "evidence_id": evidence_id,
            "symbol": metadata["symbol"],
            "period": metadata["period"],
            "source_type": source_type,
            "trust_level": _optional_string(payload.get("trust_level")) or _default_trust_level(batch),
            "content": content,
            "source_url": _optional_string(payload.get("source_url")) or (document.source_url if document else ""),
            "metadata": metadata,
        },
        task_id=str(payload.get("task_id") or ""),
        target_period=str(metadata.get("period") or ""),
    )
    metadata.update(
        {
            "identity_key": normalized["identity_key"],
            "document_key": normalized["document_key"],
            "period_spec": normalized["period_spec"],
            "authority": normalized["authority"],
            "provenance": normalized["provenance"],
        }
    )
    item = EvidenceItem(
        evidence_id=evidence_id,
        company_id=company.id if company else None,
        document_id=document.id if document else None,
        chunk_id=_optional_string(payload.get("chunk_id")),
        source_type=source_type,
        trust_level=_optional_string(payload.get("trust_level")) or _default_trust_level(batch),
        title=_optional_string(payload.get("title")) or (document.title if document else _default_document_title(batch)),
        content=content,
        source_url=_optional_string(payload.get("source_url")) or (document.source_url if document else None),
        page_no=int(payload["page_no"]) if payload.get("page_no") not in (None, "") else None,
        metadata_json=metadata,
    )
    session.add(item)
    session.flush()
    return True


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _stable_hash(*values: Any) -> str:
    joined = "|".join(str(value or "") for value in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _market_for_source(source_key: str | None) -> str:
    source = str(source_key or "")
    if source.startswith("cninfo") or source in {"eastmoney", "eastmoney_financials"}:
        return "CN"
    if source.startswith("hkex") or source == "hk_financials":
        return "HK"
    return "US"


def _default_doc_type(batch: IngestionBatch) -> str:
    if batch.target_type == "filings":
        return "official_filing"
    return batch.target_type or "document"


def _default_document_title(batch: IngestionBatch) -> str:
    symbol = batch.symbol or "公司"
    period = batch.period or "当前期间"
    if batch.target_type == "filings":
        return f"{symbol} {period} 官方披露"
    return f"{symbol} {period} 采集资料"


def _default_trust_level(batch: IngestionBatch) -> str:
    if batch.data_source and batch.data_source.trust_level:
        return batch.data_source.trust_level
    if batch.source_key in {"sec_edgar", "cninfo_announcements", "hkex_announcements", "exchange_announcements"}:
        return "official"
    return "primary"


def _mark_datasource_health(datasource: DataSource | None, *, status: str, error: str | None) -> None:
    if datasource is None:
        return
    datasource.last_sync_at = _utc_now()
    datasource.last_status = status
    datasource.last_error = error


def _required_string(value: Any, field_name: str) -> str:
    text = _optional_string(value)
    if not text:
        raise IngestionBatchConflict(f"{field_name} is required")
    return text


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _generated_batch_id(payload: dict[str, Any]) -> str:
    metadata = _dict_or_none(payload.get("metadata")) or {}
    if metadata.get("source") == "evaluation_diagnostic_remediation":
        source_key = _safe_slug(payload.get("source_key") or "source")
        symbol = _safe_slug(payload.get("symbol") or "symbol")
        period = _safe_slug(payload.get("period") or "period")
        return f"rem-{source_key}-{symbol}-{period}-{uuid4().hex[:8]}"
    return f"ing-{uuid4().hex[:12]}"


def _safe_slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    chars = [ch if ch.isalnum() else "-" for ch in text]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:32] or "unknown"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
