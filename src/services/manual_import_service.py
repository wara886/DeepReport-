"""Manual document import workflow for the P1 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import Company, Document, DocumentProcessingStep, IngestionBatch, IngestionBatchEvent, Workspace


class ManualImportConflict(RuntimeError):
    """Raised when manual import input is invalid or conflicts with existing data."""


class ManualImportService:
    """Import text, PDF stubs, and URL records into the document processing center."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def import_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        import_type = _optional_string(payload.get("import_type")) or "text"
        if import_type not in {"text", "pdf", "url"}:
            raise ManualImportConflict(f"Unsupported import type: {import_type}")
        title = _optional_string(payload.get("title")) or _default_title(import_type, payload)
        content = _optional_string(payload.get("content"))
        source_url = _optional_string(payload.get("source_url") or payload.get("url"))
        file_path = _optional_string(payload.get("file_path") or payload.get("filename"))
        if import_type == "text" and not content:
            raise ManualImportConflict("Text import requires content")
        if import_type == "url" and not source_url:
            raise ManualImportConflict("URL import requires source_url")
        if import_type == "pdf" and not (file_path or source_url or content):
            raise ManualImportConflict("PDF import requires file_path, source_url, or content")

        doc_type = _optional_string(payload.get("doc_type")) or _doc_type(import_type)
        period = _optional_string(payload.get("period") or payload.get("report_period"))
        content_hash = _content_hash(import_type=import_type, title=title, content=content, source_url=source_url, file_path=file_path)
        batch_id = _optional_string(payload.get("batch_id")) or f"manual-{uuid4().hex[:12]}"
        now = _utc_now()

        with self.session_factory() as session:
            existing = session.scalar(select(Document).where(Document.content_hash == content_hash))
            if existing is not None:
                return {
                    "created": False,
                    "duplicate": True,
                    "batch_id": existing.batch_id,
                    "document": serialize_document(existing),
                    "message": "相同内容已导入，已返回已有文档。",
                }

            workspace = _get_workspace_optional(session, payload.get("workspace_id") or payload.get("workspace"))
            company = _get_or_create_company(
                session,
                name=_optional_string(payload.get("company_name")),
                symbol=_optional_string(payload.get("symbol")),
                market=_optional_string(payload.get("market")),
            )
            parse_status = "parsed" if content else "pending"
            batch = IngestionBatch(
                batch_id=batch_id,
                workspace_id=workspace.id if workspace else None,
                source_key="manual_import",
                name=f"手动导入：{title}",
                target_type="manual_import",
                symbol=company.symbol if company else _optional_string(payload.get("symbol")),
                period=period,
                query=source_url or file_path or _snippet(content, limit=120),
                status="completed",
                item_count=1,
                success_count=1,
                failed_count=0,
                started_at=now,
                finished_at=now,
                metadata_json={"import_type": import_type},
            )
            batch.events.append(
                IngestionBatchEvent(
                    batch_id=batch_id,
                    stage="manual_import",
                    status="completed",
                    message="手动导入已入库",
                    metadata_json={"import_type": import_type, "title": title},
                )
            )
            document = Document(
                company=company,
                batch_id=batch_id,
                title=title,
                doc_type=doc_type,
                report_period=period,
                source_url=source_url,
                file_path=file_path,
                content=content or "",
                content_hash=content_hash,
                parse_status=parse_status,
            )
            document.processing_steps.extend(_initial_steps(import_type, now, content=content, source_url=source_url, file_path=file_path))
            session.add_all([batch, document])
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ManualImportConflict("Manual import conflicts with existing document or batch") from exc
            return {
                "created": True,
                "duplicate": False,
                "batch_id": batch.batch_id,
                "document": serialize_document(document),
                "message": "手动导入已进入文档处理中心。",
            }


def serialize_document(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "batch_id": document.batch_id,
        "title": document.title,
        "doc_type": document.doc_type,
        "report_period": document.report_period,
        "source_url": document.source_url,
        "file_path": document.file_path,
        "content_hash": document.content_hash,
        "parse_status": document.parse_status,
        "created_at": _dt(document.created_at),
    }


def _initial_steps(
    import_type: str,
    now: datetime,
    *,
    content: str | None,
    source_url: str | None,
    file_path: str | None,
) -> list[DocumentProcessingStep]:
    ingest_metadata = {
        "import_type": import_type,
        "source_url": source_url,
        "file_path": file_path,
        "content_chars": len(content or ""),
    }
    steps = [
        DocumentProcessingStep(
            step_name="ingest",
            status="success",
            started_at=now,
            finished_at=now,
            metadata_json=ingest_metadata,
        )
    ]
    if content:
        steps.append(
            DocumentProcessingStep(
                step_name="parse",
                status="success",
                started_at=now,
                finished_at=now,
                metadata_json={"parser": "manual_import"},
            )
        )
    else:
        steps.append(
            DocumentProcessingStep(
                step_name="parse",
                status="pending",
                started_at=None,
                finished_at=None,
                metadata_json={"parser": "pdf_stub", "requires_parser": True},
            )
        )
    return steps


def _get_or_create_company(session: Session, *, name: str | None, symbol: str | None, market: str | None) -> Company | None:
    normalized_symbol = symbol.upper() if symbol else None
    normalized_market = market.upper() if market else None
    if not (name or normalized_symbol):
        return None
    if normalized_symbol:
        company = session.scalar(select(Company).where(Company.symbol == normalized_symbol, Company.market == normalized_market))
        if company is not None:
            if name and company.name == normalized_symbol:
                company.name = name
            return company
    elif name:
        company = session.scalar(select(Company).where(Company.name == name, Company.market == normalized_market))
        if company is not None:
            return company
    company = Company(
        name=name or normalized_symbol or "未知公司",
        symbol=normalized_symbol,
        market=normalized_market,
        aliases=[item for item in [name, normalized_symbol] if item],
    )
    session.add(company)
    session.flush()
    return company


def _get_workspace_optional(session: Session, workspace_ref: int | str | None) -> Workspace | None:
    if workspace_ref in (None, ""):
        return None
    text = str(workspace_ref).strip()
    condition = Workspace.id == int(text) if text.isdigit() else Workspace.slug == text
    workspace = session.scalar(select(Workspace).where(condition))
    if workspace is None:
        raise ManualImportConflict(f"Workspace not found: {workspace_ref}")
    return workspace


def _default_title(import_type: str, payload: dict[str, Any]) -> str:
    if import_type == "url":
        return _optional_string(payload.get("source_url") or payload.get("url")) or "手动导入链接"
    if import_type == "pdf":
        return _optional_string(payload.get("filename") or payload.get("file_path")) or "手动导入 PDF"
    return "手动导入文本"


def _doc_type(import_type: str) -> str:
    return {"text": "manual_text", "pdf": "manual_pdf", "url": "manual_url"}[import_type]


def _content_hash(*, import_type: str, title: str, content: str | None, source_url: str | None, file_path: str | None) -> str:
    del title
    raw = "\n".join([import_type, content or "", source_url or "", file_path or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _snippet(content: str | None, *, limit: int) -> str:
    text = " ".join(str(content or "").split())
    return text[:limit]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
