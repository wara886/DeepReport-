"""Dashboard aggregation service for the P0 research workbench."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from src.db.models import (
    ClaimEvidence,
    Company,
    Document,
    DocumentProcessingStep,
    EvidenceItem,
    FinancialFact,
    LLMRun,
    ReportArtifact,
    ReportClaim,
    ReportTask,
)


class DashboardService:
    """Aggregate dashboard cards and funnel counts from database state."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def summary(self) -> dict[str, Any]:
        with self.session_factory() as session:
            active_task_condition = ReportTask.status != "archived"
            task_status = _counter(
                session.execute(
                    select(ReportTask.status, func.count()).where(active_task_condition).group_by(ReportTask.status)
                ).all()
            )
            source_distribution = _counter(
                session.execute(select(EvidenceItem.source_type, func.count()).group_by(EvidenceItem.source_type)).all(),
                empty_key="unknown",
            )
            artifact_distribution = _counter(
                session.execute(select(ReportArtifact.artifact_type, func.count()).group_by(ReportArtifact.artifact_type)).all(),
                empty_key="unknown",
            )
            verified_claims = _verified_claim_count(session)
            total_claims = _count(session, ReportClaim.id)
            quality_scores = list(
                session.scalars(
                    select(ReportTask.quality_score).where(
                        active_task_condition,
                        ReportTask.quality_score.is_not(None),
                    )
                ).all()
            )
            completed_tasks = int(task_status.get("completed", 0))
            failed_tasks = int(task_status.get("failed", 0))
            total_tasks = sum(task_status.values())
            llm_total = _count(session, LLMRun.id)
            llm_failed = _count_where(session, LLMRun.id, LLMRun.status != "success")
            llm_latency_values = [
                value
                for value in session.scalars(select(LLMRun.latency_ms).where(LLMRun.latency_ms.is_not(None))).all()
                if isinstance(value, int)
            ]
            llm_cost = float(session.scalar(select(func.coalesce(func.sum(LLMRun.cost_usd), 0.0))) or 0.0)

            return {
                "company_count": _count(session, Company.id),
                "document_count": _count(session, Document.id),
                "evidence_count": _count(session, EvidenceItem.id),
                "financial_fact_count": _count(session, FinancialFact.id),
                "claim_count": total_claims,
                "review_pending_claim_count": _count_where(session, ReportClaim.id, ReportClaim.review_status == "pending"),
                "verified_claim_count": verified_claims,
                "quality_pass_rate": _ratio(completed_tasks, total_tasks),
                "average_quality_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else None,
                "report_task_status_distribution": task_status,
                "data_source_distribution": source_distribution,
                "artifact_distribution": artifact_distribution,
                "failed_task_count": failed_tasks,
                "llm_run_count": llm_total,
                "llm_failed_run_count": llm_failed,
                "llm_failure_rate": _ratio(llm_failed, llm_total),
                "average_llm_latency_ms": round(sum(llm_latency_values) / len(llm_latency_values), 2) if llm_latency_values else None,
                "llm_cost_usd": round(llm_cost, 6),
            }

    def funnel(self) -> dict[str, Any]:
        with self.session_factory() as session:
            groups = [
                {
                    "key": "documents",
                    "label": "文档处理",
                    "metrics": [
                        _metric("ingested", "入库", _count(session, Document.id)),
                        _metric("parsed", "解析", _document_step_success_count(session, "parse", fallback_status="parsed")),
                        _metric("table_extracted", "表格", _document_step_success_count(session, "table_extract")),
                        _metric("chunked", "切分", _document_step_success_count(session, "chunk")),
                        _metric("evidenced", "证据化", _distinct_non_null_count(session, EvidenceItem.document_id)),
                    ],
                },
                {
                    "key": "tasks",
                    "label": "研报任务",
                    "metrics": [
                        _metric("queued", "排队", _task_status_count(session, "queued")),
                        _metric("running", "运行中", _task_status_count(session, "running")),
                        _metric("evidence_blocked", "证据阻塞", _task_stage_count(session, "evidence")),
                        _metric("machine_pass", "机器通过", _task_status_count(session, "completed")),
                        _metric("review_pending", "待复核", _distinct_pending_task_count(session)),
                        _metric("delivered", "已交付", _task_status_count(session, "delivered")),
                    ],
                },
                {
                    "key": "claims",
                    "label": "主张复核",
                    "metrics": [
                        _metric("generated", "已生成", _count(session, ReportClaim.id)),
                        _metric("supported", "有证据支持", _verified_claim_count(session)),
                        _metric("pending", "待复核", _count_where(session, ReportClaim.id, ReportClaim.review_status == "pending")),
                        _metric("approved", "已通过", _count_where(session, ReportClaim.id, ReportClaim.review_status == "approved")),
                        _metric("rejected", "已驳回", _count_where(session, ReportClaim.id, ReportClaim.review_status == "rejected")),
                    ],
                },
            ]
            return {"schema_version": "dashboard_status_groups.v1", "groups": groups}


def _count(session: Session, column: Any) -> int:
    return int(session.scalar(select(func.count(column))) or 0)


def _count_where(session: Session, column: Any, condition: Any) -> int:
    return int(session.scalar(select(func.count(column)).where(condition)) or 0)


def _metric(key: str, label: str, count: int) -> dict[str, Any]:
    return {"key": key, "label": label, "count": int(count)}


def _distinct_non_null_count(session: Session, column: Any) -> int:
    return int(session.scalar(select(func.count(distinct(column))).where(column.is_not(None))) or 0)


def _task_status_count(session: Session, status: str) -> int:
    return _count_where(session, ReportTask.id, ReportTask.status == status)


def _task_stage_count(session: Session, stage_fragment: str) -> int:
    return _count_where(session, ReportTask.id, ReportTask.current_stage.ilike(f"%{stage_fragment}%"))


def _distinct_pending_task_count(session: Session) -> int:
    return int(session.scalar(select(func.count(distinct(ReportClaim.task_id))).where(ReportClaim.review_status == "pending")) or 0)


def _counter(rows: list[tuple[Any, int]], *, empty_key: str = "unknown") -> dict[str, int]:
    counter: Counter[str] = Counter()
    for key, count in rows:
        counter[str(key or empty_key)] += int(count or 0)
    return dict(counter)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _document_step_success_count(session: Session, step_name: str, *, fallback_status: str | None = None) -> int:
    like_pattern = f"%{step_name}%"
    count = int(
        session.scalar(
            select(func.count(distinct(DocumentProcessingStep.document_id))).where(
                DocumentProcessingStep.step_name.ilike(like_pattern),
                DocumentProcessingStep.status == "success",
            )
        )
        or 0
    )
    if count == 0 and fallback_status:
        count = _count_where(session, Document.id, Document.parse_status == fallback_status)
    return count


def _verified_claim_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(ReportClaim.id)).where(
                ReportClaim.verification_status.in_(["supported", "verified", "passed"]),
            )
        )
        or 0
    )


def _distinct_evidence_linked_claim_count(session: Session, *, claim_type: str) -> int:
    return int(
        session.scalar(
            select(func.count(distinct(ReportClaim.id)))
            .join(ClaimEvidence, ClaimEvidence.claim_id == ReportClaim.id)
            .where(ReportClaim.claim_type == claim_type)
        )
        or 0
    )
