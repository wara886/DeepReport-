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


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        Index("ix_workspaces_market_active", "market", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    excluded_keywords: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    focus_metrics: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    risk_types: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    evidence_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_gate_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_data_sources: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    report_template: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    companies: Mapped[list[WorkspaceCompany]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by="WorkspaceCompany.id",
    )
    data_sources: Mapped[list[DataSource]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by="DataSource.id",
    )


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
    workspace_links: Mapped[list[WorkspaceCompany]] = relationship(back_populates="company")


class WorkspaceCompany(Base):
    __tablename__ = "workspace_companies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "symbol", "market", name="uq_workspace_companies_symbol_market"),
        Index("ix_workspace_companies_workspace_active", "workspace_id", "is_active"),
        Index("ix_workspace_companies_symbol_market", "symbol", "market"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aliases: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    focus_metrics: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    risk_types: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="companies")
    company: Mapped[Company | None] = relationship(back_populates="workspace_links")


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_key", name="uq_data_sources_workspace_source_key"),
        Index("ix_data_sources_key_enabled", "source_key", "enabled"),
        Index("ix_data_sources_workspace_enabled", "workspace_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    market_scope: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    trust_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config_json: Mapped[dict[str, Any] | None] = mapped_column("config", JSONVariant, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    credential_status: Mapped[str] = mapped_column(String(32), default="not_required", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    workspace: Mapped[Workspace | None] = relationship(back_populates="data_sources")
    ingestion_batches: Mapped[list[IngestionBatch]] = relationship(back_populates="data_source")


class DictionaryTerm(Base):
    __tablename__ = "dictionary_terms"
    __table_args__ = (
        UniqueConstraint("term_type", "canonical_name", "market", name="uq_dictionary_terms_type_name_market"),
        Index("ix_dictionary_terms_type_active", "term_type", "is_active"),
        Index("ix_dictionary_terms_market_type", "market", "term_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    term_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False)
    market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    workspace: Mapped[Workspace | None] = relationship()
    aliases: Mapped[list[DictionaryAlias]] = relationship(
        back_populates="term",
        cascade="all, delete-orphan",
        order_by="DictionaryAlias.id",
    )


class DictionaryAlias(Base):
    __tablename__ = "dictionary_aliases"
    __table_args__ = (
        UniqueConstraint("term_id", "alias", name="uq_dictionary_aliases_term_alias"),
        Index("ix_dictionary_aliases_type_key", "term_type", "normalized_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("dictionary_terms.id", ondelete="CASCADE"), nullable=False)
    term_type: Mapped[str] = mapped_column(String(64), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    term: Mapped[DictionaryTerm] = relationship(back_populates="aliases")


class LLMRun(Base):
    __tablename__ = "llm_runs"
    __table_args__ = (
        Index("ix_llm_runs_task_created", "task_id", "created_at"),
        Index("ix_llm_runs_prompt_status", "prompt_key", "status"),
        Index("ix_llm_runs_model_role", "model_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_key: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schema_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    output_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONVariant, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("prompt_key", name="uq_prompt_templates_key"),
        Index("ix_prompt_templates_module_active", "module", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    module: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_json: Mapped[dict[str, Any] | None] = mapped_column("schema", JSONVariant, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version.desc()",
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),
        Index("ix_prompt_versions_template_active", "template_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    template: Mapped[PromptTemplate] = relationship(back_populates="versions")


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (
        UniqueConstraint("batch_id", name="uq_ingestion_batches_batch_id"),
        Index("ix_ingestion_batches_status_created", "status", "created_at"),
        Index("ix_ingestion_batches_workspace_status", "workspace_id", "status"),
        Index("ix_ingestion_batches_datasource_status", "data_source_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    data_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), default="documents", nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    data_source: Mapped[DataSource | None] = relationship(back_populates="ingestion_batches")
    workspace: Mapped[Workspace | None] = relationship()
    events: Mapped[list[IngestionBatchEvent]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="IngestionBatchEvent.id",
        primaryjoin="IngestionBatch.batch_id == foreign(IngestionBatchEvent.batch_id)",
    )


class IngestionBatchEvent(Base):
    __tablename__ = "ingestion_batch_events"
    __table_args__ = (
        Index("ix_ingestion_batch_events_batch_created", "batch_id", "created_at"),
        Index("ix_ingestion_batch_events_stage_status", "stage", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.batch_id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    batch: Mapped[IngestionBatch] = relationship(
        back_populates="events",
        primaryjoin="foreign(IngestionBatchEvent.batch_id) == IngestionBatch.batch_id",
    )


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


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        Index("ix_financial_facts_company_period", "company_id", "period"),
        Index("ix_financial_facts_metric_period", "metric_name", "period"),
        Index("ix_financial_facts_review_status", "review_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    evidence_item_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scale: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period: Mapped[str] = mapped_column(String(64), nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    company: Mapped[Company | None] = relationship()
    evidence_item: Mapped[EvidenceItem | None] = relationship()


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("entity_key", name="uq_entities_key"),
        Index("ix_entities_type_market", "entity_type", "market"),
        Index("ix_entities_symbol_market", "symbol", "market"),
        Index("ix_entities_workspace_type", "workspace_id", "entity_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    entity_key: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False)
    market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_evidence_item_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False)

    workspace: Mapped[Workspace | None] = relationship()
    source_evidence_item: Mapped[EvidenceItem | None] = relationship()
    outgoing_relations: Mapped[list[EntityRelation]] = relationship(
        back_populates="source_entity",
        foreign_keys="EntityRelation.source_entity_id",
        cascade="all, delete-orphan",
    )
    incoming_relations: Mapped[list[EntityRelation]] = relationship(
        back_populates="target_entity",
        foreign_keys="EntityRelation.target_entity_id",
        cascade="all, delete-orphan",
    )


class EntityRelation(Base):
    __tablename__ = "entity_relations"
    __table_args__ = (
        UniqueConstraint("relation_key", name="uq_entity_relations_key"),
        Index("ix_entity_relations_source_type", "source_entity_id", "relation_type"),
        Index("ix_entity_relations_target_type", "target_entity_id", "relation_type"),
        Index("ix_entity_relations_evidence", "source_evidence_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    target_entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_evidence_item_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False)

    source_entity: Mapped[Entity] = relationship(
        back_populates="outgoing_relations",
        foreign_keys=[source_entity_id],
    )
    target_entity: Mapped[Entity] = relationship(
        back_populates="incoming_relations",
        foreign_keys=[target_entity_id],
    )
    source_evidence_item: Mapped[EvidenceItem | None] = relationship()


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
