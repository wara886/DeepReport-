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
    ReportArtifact,
    ReportClaim,
    ReportTask,
)


FUNNEL_STEPS = [
    ("document_ingested", "原始资料入库"),
    ("parse_success", "解析成功"),
    ("table_extract_success", "表格抽取成功"),
    ("chunk_vectorized", "切分向量化"),
    ("financial_fact_extracted", "财务事实提取"),
    ("investment_signal_generated", "投资线索生成"),
    ("report_claim_generated", "研报 Claim 生成"),
    ("claim_verified", "Claim 校验通过"),
    ("pending_review", "待人工复核"),
]


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
            }

    def funnel(self) -> dict[str, Any]:
        with self.session_factory() as session:
            counts = {
                "document_ingested": _count(session, Document.id),
                "parse_success": _document_step_success_count(session, "parse", fallback_status="parsed"),
                "table_extract_success": _document_step_success_count(session, "table_extract"),
                "chunk_vectorized": _document_step_success_count(session, "chunk"),
                "financial_fact_extracted": _count(session, FinancialFact.id),
                "investment_signal_generated": _count_where(session, ReportClaim.id, ReportClaim.claim_type == "signal"),
                "report_claim_generated": _count(session, ReportClaim.id),
                "claim_verified": _verified_claim_count(session),
                "pending_review": _count_where(session, ReportClaim.id, ReportClaim.review_status == "pending"),
            }
            steps = [{"key": key, "label": label, "count": int(counts.get(key, 0))} for key, label in FUNNEL_STEPS]
            return {"steps": steps}


def _count(session: Session, column: Any) -> int:
    return int(session.scalar(select(func.count(column))) or 0)


def _count_where(session: Session, column: Any, condition: Any) -> int:
    return int(session.scalar(select(func.count(column)).where(condition)) or 0)


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
