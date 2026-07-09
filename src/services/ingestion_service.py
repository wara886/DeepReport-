"""Ingestion batch lifecycle service for the P1 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.db.models import DataSource, IngestionBatch, IngestionBatchEvent, Workspace


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
            batch.events.append(
                IngestionBatchEvent(
                    batch_id=batch.batch_id,
                    stage="run",
                    status="completed",
                    message=_optional_string(payload.get("message")) or "采集批次已完成",
                    metadata_json=_dict_or_none(payload.get("metadata")),
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
