"""SQLAlchemy models for the P0 FinSight workbench tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


JSONVariant = JSON().with_variant(postgresql.JSONB, "postgresql")


class Base(DeclarativeBase):
    """Base class for database models."""


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("symbol", "market", name="uq_companies_symbol_market"),
        Index("ix_companies_market_symbol", "market", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aliases: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    documents: Mapped[list[Document]] = relationship(back_populates="company", cascade="all, delete-orphan")
    evidence_items: Mapped[list[EvidenceItem]] = relationship(back_populates="company")
    report_tasks: Mapped[list[ReportTask]] = relationship(back_populates="company")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_documents_content_hash"),
        Index("ix_documents_company_period", "company_id", "report_period"),
        Index("ix_documents_batch_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    datasource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    company: Mapped[Company | None] = relationship(back_populates="documents")
    processing_steps: Mapped[list[DocumentProcessingStep]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentProcessingStep.id",
    )
    evidence_items: Mapped[list[EvidenceItem]] = relationship(back_populates="document")


class DocumentProcessingStep(Base):
    __tablename__ = "document_processing_steps"
    __table_args__ = (
        Index("ix_document_processing_steps_document_status", "document_id", "status"),
        Index("ix_document_processing_steps_step_status", "step_name", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)

    document: Mapped[Document] = relationship(back_populates="processing_steps")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        UniqueConstraint("evidence_id", name="uq_evidence_items_evidence_id"),
        Index("ix_evidence_items_company_source", "company_id", "source_type"),
        Index("ix_evidence_items_document_chunk", "document_id", "chunk_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[str] = mapped_column(String(128), nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trust_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    company: Mapped[Company | None] = relationship(back_populates="evidence_items")
    document: Mapped[Document | None] = relationship(back_populates="evidence_items")
    claim_links: Mapped[list[ClaimEvidence]] = relationship(back_populates="evidence_item", cascade="all, delete-orphan")


class ReportTask(Base):
    __tablename__ = "report_tasks"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_report_tasks_task_id"),
        Index("ix_report_tasks_status_created", "status", "created_at"),
        Index("ix_report_tasks_symbol_period", "symbol", "period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(64), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), default="equity_research", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)

    company: Mapped[Company | None] = relationship(back_populates="report_tasks")
    events: Mapped[list[ReportTaskEvent]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ReportTaskEvent.id",
        primaryjoin="ReportTask.task_id == foreign(ReportTaskEvent.task_id)",
    )
    artifacts: Mapped[list[ReportArtifact]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ReportArtifact.id",
        primaryjoin="ReportTask.task_id == foreign(ReportArtifact.task_id)",
    )
    claims: Mapped[list[ReportClaim]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ReportClaim.id",
        primaryjoin="ReportTask.task_id == foreign(ReportClaim.task_id)",
    )


class ReportTaskEvent(Base):
    __tablename__ = "report_task_events"
    __table_args__ = (
        Index("ix_report_task_events_task_created", "task_id", "created_at"),
        Index("ix_report_task_events_stage_status", "stage", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("report_tasks.task_id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    task: Mapped[ReportTask] = relationship(
        back_populates="events",
        primaryjoin="foreign(ReportTaskEvent.task_id) == ReportTask.task_id",
    )


class ReportArtifact(Base):
    __tablename__ = "report_artifacts"
    __table_args__ = (Index("ix_report_artifacts_task_type", "task_id", "artifact_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("report_tasks.task_id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    task: Mapped[ReportTask] = relationship(
        back_populates="artifacts",
        primaryjoin="foreign(ReportArtifact.task_id) == ReportTask.task_id",
    )


class ReportClaim(Base):
    __tablename__ = "report_claims"
    __table_args__ = (
        Index("ix_report_claims_task_review", "task_id", "review_status"),
        Index("ix_report_claims_verification", "verification_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("report_tasks.task_id", ondelete="CASCADE"), nullable=False)
    section_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    critical_claim_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    numeric_check_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    citation_check_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)

    task: Mapped[ReportTask] = relationship(
        back_populates="claims",
        primaryjoin="foreign(ReportClaim.task_id) == ReportTask.task_id",
    )
    evidence_links: Mapped[list[ClaimEvidence]] = relationship(back_populates="claim", cascade="all, delete-orphan")


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (Index("ix_claim_evidence_evidence_item_id", "evidence_item_id"),)

    claim_id: Mapped[int] = mapped_column(ForeignKey("report_claims.id", ondelete="CASCADE"), primary_key=True)
    evidence_item_id: Mapped[int] = mapped_column(ForeignKey("evidence_items.id", ondelete="CASCADE"), primary_key=True)
    support_type: Mapped[str] = mapped_column(String(32), default="supporting", nullable=False)

    claim: Mapped[ReportClaim] = relationship(back_populates="evidence_links")
    evidence_item: Mapped[EvidenceItem] = relationship(back_populates="claim_links")


class ReviewRecord(Base):
    __tablename__ = "review_records"
    __table_args__ = (
        Index("ix_review_records_target", "target_type", "target_id"),
        Index("ix_review_records_decision_created", "decision", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_value: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONVariant, nullable=True)
    after_value: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONVariant, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
