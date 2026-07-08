"""Import generated report artifacts into the workbench database."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
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
    ReportTaskEvent,
)


REPORT_ARTIFACTS = {
    "report.md": "markdown",
    "report.html": "html",
    "report.json": "json",
}

OUTPUT_ARTIFACTS = {
    "run_summary.json": "run_summary",
    "evidence.json": "evidence",
    "claims.json": "claims",
    "verification_report.json": "verification_report",
    "delivery_gate.json": "delivery_gate",
    "quality_report.json": "quality_report",
    "llm_quality_review.json": "llm_quality_review",
    "quality_remediation_plan.json": "quality_remediation_plan",
    "performance_trace.json": "performance_trace",
}


@dataclass(frozen=True)
class ArtifactImportResult:
    task_id: str
    artifact_count: int
    evidence_count: int
    claim_count: int
    claim_evidence_count: int
    financial_fact_count: int
    llm_run_count: int
    document_count: int
    document_processing_step_count: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "artifact_count": self.artifact_count,
            "evidence_count": self.evidence_count,
            "claim_count": self.claim_count,
            "claim_evidence_count": self.claim_evidence_count,
            "financial_fact_count": self.financial_fact_count,
            "llm_run_count": self.llm_run_count,
            "document_count": self.document_count,
            "document_processing_step_count": self.document_processing_step_count,
            "warnings": list(self.warnings),
        }


class ArtifactImporter:
    """Import P0 report artifacts while tolerating older partial outputs."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        output_root: str | Path,
        report_root: str | Path,
    ) -> None:
        self.session_factory = session_factory
        self.output_root = Path(output_root)
        self.report_root = Path(report_root)

    def import_for_task(self, task_id: str) -> ArtifactImportResult:
        warnings: list[str] = []
        with self.session_factory() as session:
            task = session.scalar(select(ReportTask).where(ReportTask.task_id == task_id))
            if task is None:
                raise LookupError(f"Report task not found: {task_id}")

            metadata = dict(task.metadata_json or {})
            output_dir = Path(str(metadata.get("output_dir") or ""))
            report_dir = Path(str(metadata.get("report_dir") or ""))
            period = str(task.period or metadata.get("period") or "")
            company_id = task.company_id or _get_or_create_company_id(
                session,
                symbol=str(task.symbol or metadata.get("symbol") or ""),
                name=str(metadata.get("company_name") or task.symbol or ""),
                market=str(metadata.get("market") or ""),
            )

            artifacts = self._import_artifacts(session, task_id, output_dir, report_dir)
            document = self._upsert_task_document(
                session,
                task=task,
                company_id=company_id,
                period=period,
                output_dir=output_dir,
                report_dir=report_dir,
                artifacts=artifacts,
            )
            evidence_by_external_id = self._import_evidence(
                session,
                task_id=task_id,
                company_id=company_id,
                document_id=document.id if document is not None else None,
                period=period,
                output_dir=output_dir,
                warnings=warnings,
            )
            claim_count, link_count = self._import_claims(
                session,
                task_id=task_id,
                period=period,
                output_dir=output_dir,
                evidence_by_external_id=evidence_by_external_id,
                warnings=warnings,
            )
            financial_fact_count = self._import_financial_facts(
                session,
                task_id=task_id,
                company_id=company_id,
                period=period,
                output_dir=output_dir,
                evidence_by_external_id=evidence_by_external_id,
                warnings=warnings,
            )
            llm_run_count = self._import_agent_llm_runs(
                session,
                task_id=task_id,
                output_dir=output_dir,
            )
            document_step_count = (
                self._replace_document_processing_steps(
                    session,
                    document=document,
                    artifacts=artifacts,
                    output_dir=output_dir,
                    report_dir=report_dir,
                    evidence_count=len(evidence_by_external_id),
                    claim_count=claim_count,
                    claim_evidence_count=link_count,
                    financial_fact_count=financial_fact_count,
                )
                if document is not None
                else 0
            )

            result = ArtifactImportResult(
                task_id=task_id,
                artifact_count=len(artifacts),
                evidence_count=len(evidence_by_external_id),
                claim_count=claim_count,
                claim_evidence_count=link_count,
                financial_fact_count=financial_fact_count,
                llm_run_count=llm_run_count,
                document_count=1 if document is not None else 0,
                document_processing_step_count=document_step_count,
                warnings=warnings,
            )
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage="artifact_import",
                    status="success",
                    message="Report artifacts imported",
                    metadata_json=result.to_dict(),
                )
            )
            session.commit()
            return result

    def _import_artifacts(self, session: Session, task_id: str, output_dir: Path, report_dir: Path) -> list[ReportArtifact]:
        session.execute(delete(ReportArtifact).where(ReportArtifact.task_id == task_id))
        rows: list[ReportArtifact] = []
        for filename, artifact_type in REPORT_ARTIFACTS.items():
            path = report_dir / filename
            if path.exists() and path.is_file():
                rows.append(
                    ReportArtifact(
                        task_id=task_id,
                        artifact_type=artifact_type,
                        path=str(path),
                        url=_artifact_url(
                            path=path,
                            root=self.report_root,
                            task_id=task_id,
                            filename=filename,
                            artifact_root="reports",
                        ),
                    )
                )
        for filename, artifact_type in OUTPUT_ARTIFACTS.items():
            path = output_dir / filename
            if path.exists() and path.is_file():
                rows.append(
                    ReportArtifact(
                        task_id=task_id,
                        artifact_type=artifact_type,
                        path=str(path),
                        url=_artifact_url(
                            path=path,
                            root=self.output_root,
                            task_id=task_id,
                            filename=filename,
                            artifact_root="outputs",
                        ),
                    )
                )
        session.add_all(rows)
        return rows

    def _upsert_task_document(
        self,
        session: Session,
        *,
        task: ReportTask,
        company_id: int | None,
        period: str,
        output_dir: Path,
        report_dir: Path,
        artifacts: list[ReportArtifact],
    ) -> Document | None:
        if not artifacts and not _has_importable_outputs(output_dir, report_dir):
            return None

        task_id = task.task_id
        content_hash = _task_document_hash(task_id)
        document = session.scalar(select(Document).where(Document.content_hash == content_hash))
        if document is None:
            document = Document(title="", content_hash=content_hash)
            session.add(document)

        title = _report_title(report_dir / "report.json") or _task_document_title(task, period)
        primary_artifact = _primary_report_artifact(artifacts)
        document.company_id = company_id
        document.batch_id = task_id
        document.title = title
        document.doc_type = "report_artifact"
        document.report_period = period or task.period
        document.source_url = primary_artifact.url if primary_artifact is not None else None
        document.file_path = primary_artifact.path if primary_artifact is not None else None
        document.parse_status = "parsed"
        session.flush()
        return document

    def _replace_document_processing_steps(
        self,
        session: Session,
        *,
        document: Document,
        artifacts: list[ReportArtifact],
        output_dir: Path,
        report_dir: Path,
        evidence_count: int,
        claim_count: int,
        claim_evidence_count: int,
        financial_fact_count: int,
    ) -> int:
        session.execute(delete(DocumentProcessingStep).where(DocumentProcessingStep.document_id == document.id))
        now = datetime.now(timezone.utc)
        verification = _read_json(output_dir / "verification_report.json", default={})
        verification_exists = (output_dir / "verification_report.json").exists()
        verification_passed = bool(verification.get("passed")) if isinstance(verification, dict) else False
        has_report_file = any((report_dir / filename).exists() for filename in REPORT_ARTIFACTS)
        artifact_types = sorted({artifact.artifact_type for artifact in artifacts})
        steps = [
            _processing_step(
                "ingest",
                "success",
                now,
                {"artifact_count": len(artifacts), "artifact_types": artifact_types},
            ),
            _processing_step(
                "parse",
                "success" if has_report_file else "skipped",
                now,
                {"report_files": [filename for filename in REPORT_ARTIFACTS if (report_dir / filename).exists()]},
            ),
            _processing_step(
                "table_extract",
                "success" if financial_fact_count else "skipped",
                now,
                {"financial_fact_count": financial_fact_count},
            ),
            _processing_step(
                "chunk_vectorize",
                "success" if evidence_count else "skipped",
                now,
                {"evidence_count": evidence_count},
            ),
            _processing_step(
                "evidence",
                "success" if evidence_count else "skipped",
                now,
                {"evidence_count": evidence_count},
            ),
            _processing_step(
                "claim_bind",
                _claim_bind_step_status(claim_count=claim_count, claim_evidence_count=claim_evidence_count),
                now,
                {"claim_count": claim_count, "claim_evidence_count": claim_evidence_count},
            ),
            _processing_step(
                "verify",
                _verify_step_status(verification_exists=verification_exists, verification_passed=verification_passed),
                now,
                {"verification_passed": verification_passed, "verification_exists": verification_exists},
            ),
        ]
        for step in steps:
            step.document_id = document.id
        session.add_all(steps)
        session.flush()
        return len(steps)

    def _import_evidence(
        self,
        session: Session,
        *,
        task_id: str,
        company_id: int | None,
        document_id: int | None,
        period: str,
        output_dir: Path,
        warnings: list[str],
    ) -> dict[str, EvidenceItem]:
        records = _read_records(output_dir / "evidence.json", preferred_key="evidence", warnings=warnings)
        imported: dict[str, EvidenceItem] = {}
        for index, record in enumerate(records):
            evidence_id = _string(record.get("evidence_id") or record.get("id") or f"{task_id}:evidence:{index + 1}")
            missing = [key for key in ("evidence_id", "content") if not record.get(key)]
            metadata = _metadata(record, task_id=task_id, period=period, missing_fields=missing)
            item = session.scalar(select(EvidenceItem).where(EvidenceItem.evidence_id == evidence_id))
            if item is None:
                item = EvidenceItem(evidence_id=evidence_id, content="")
                session.add(item)
            item.company_id = _optional_int(record.get("company_id")) or company_id
            item.document_id = _optional_int(record.get("document_id")) or document_id
            item.chunk_id = _string_or_none(record.get("chunk_id"))
            item.source_type = _string_or_none(record.get("source_type"))
            item.trust_level = _string_or_none(record.get("trust_level"))
            item.title = _string_or_none(record.get("title"))
            item.content = _string(record.get("content") or record.get("text") or record.get("snippet") or "")
            item.source_url = _string_or_none(record.get("source_url") or record.get("url"))
            item.page_no = _optional_int(record.get("page_no") or record.get("page"))
            item.metadata_json = metadata
            imported[evidence_id] = item
        if records:
            session.flush()
        return imported

    def _import_claims(
        self,
        session: Session,
        *,
        task_id: str,
        period: str,
        output_dir: Path,
        evidence_by_external_id: dict[str, EvidenceItem],
        warnings: list[str],
    ) -> tuple[int, int]:
        existing_claim_ids = list(session.scalars(select(ReportClaim.id).where(ReportClaim.task_id == task_id)).all())
        if existing_claim_ids:
            session.execute(delete(ClaimEvidence).where(ClaimEvidence.claim_id.in_(existing_claim_ids)))
            session.execute(delete(ReportClaim).where(ReportClaim.id.in_(existing_claim_ids)))

        claims = _read_records(output_dir / "claims.json", preferred_key="claims", warnings=warnings)
        verification = _read_json(output_dir / "verification_report.json", default={})
        link_count = 0
        for index, record in enumerate(claims):
            external_claim_id = _string(record.get("claim_id") or record.get("id") or f"{task_id}:claim:{index + 1}")
            evidence_ids = _extract_evidence_ids(record)
            missing = [key for key in ("claim_id", "claim_text") if not record.get(key)]
            metadata = _metadata(record, task_id=task_id, period=period, missing_fields=missing)
            metadata["original_claim_id"] = external_claim_id
            metadata["evidence_ids"] = evidence_ids
            verification_summary = _claim_verification_summary(verification, external_claim_id)
            metadata["verification_summary"] = verification_summary
            linked_evidence = [evidence_by_external_id[evidence_id] for evidence_id in evidence_ids if evidence_id in evidence_by_external_id]
            verification_status = _claim_verification_status(record, verification_summary, linked_evidence)
            numeric_check_status = _claim_numeric_check_status(record, linked_evidence)
            citation_check_status = _claim_citation_check_status(evidence_ids, linked_evidence)
            metadata["import_checks"] = {
                "linked_evidence_count": len(linked_evidence),
                "missing_evidence_ids": [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_by_external_id],
                "verification_status": verification_status,
                "numeric_check_status": numeric_check_status,
                "citation_check_status": citation_check_status,
            }

            claim = ReportClaim(
                task_id=task_id,
                section_name=_string_or_none(record.get("section_name") or record.get("section")),
                claim_text=_string(record.get("claim_text") or record.get("text") or record.get("claim") or ""),
                claim_type=_string_or_none(record.get("claim_type") or record.get("type")),
                is_critical=bool(record.get("is_critical", record.get("critical", False))),
                critical_claim_type=_string_or_none(record.get("critical_claim_type")),
                verification_status=verification_status,
                numeric_check_status=numeric_check_status,
                citation_check_status=citation_check_status,
                confidence=_optional_float(record.get("confidence")),
                review_status=_string(record.get("review_status") or "pending"),
                metadata_json=metadata,
            )
            session.add(claim)
            session.flush()
            for evidence_id in evidence_ids:
                evidence_item = evidence_by_external_id.get(evidence_id)
                if evidence_item is None:
                    warnings.append(f"claim {external_claim_id} references missing evidence {evidence_id}")
                    continue
                session.add(
                    ClaimEvidence(
                        claim_id=claim.id,
                        evidence_item_id=evidence_item.id,
                        support_type=_string(record.get("support_type") or "supports"),
                    )
                )
                link_count += 1
        return len(claims), link_count

    def _import_financial_facts(
        self,
        session: Session,
        *,
        task_id: str,
        company_id: int | None,
        period: str,
        output_dir: Path,
        evidence_by_external_id: dict[str, EvidenceItem],
        warnings: list[str],
    ) -> int:
        existing_ids = list(
            session.scalars(
                select(FinancialFact.id).where(FinancialFact.metadata_json["task_id"].as_string() == task_id)
            ).all()
        )
        if existing_ids:
            session.execute(delete(FinancialFact).where(FinancialFact.id.in_(existing_ids)))

        fact_records = _extract_fact_records(output_dir, task_id=task_id, period=period, warnings=warnings)
        rows: list[FinancialFact] = []
        seen: set[tuple[str, str, float, str | None]] = set()
        for record in fact_records:
            metric_name = _string_or_none(record.get("metric_name") or record.get("metric"))
            value = _optional_float(record.get("value"))
            fact_period = _string_or_none(record.get("period")) or period
            if not metric_name or value is None or not fact_period:
                warnings.append(f"financial fact skipped due to missing metric/value/period: {metric_name or '<unknown>'}")
                continue
            evidence_id = _fact_evidence_id(record)
            evidence = evidence_by_external_id.get(evidence_id) if evidence_id else None
            dedupe_key = (metric_name, fact_period, value, evidence_id)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            metadata = _metadata(record, task_id=task_id, period=fact_period, missing_fields=[])
            rows.append(
                FinancialFact(
                    company_id=_optional_int(record.get("company_id")) or company_id,
                    evidence_item_id=evidence.id if evidence is not None else None,
                    metric_name=metric_name,
                    metric_type=_string_or_none(record.get("metric_type")) or _infer_metric_type(metric_name, record),
                    value=value,
                    unit=_fact_unit(record),
                    currency=_fact_currency(record),
                    scale=_string_or_none(record.get("scale")),
                    period=fact_period,
                    fiscal_year=_optional_int(record.get("fiscal_year")) or _fiscal_year_from_period(fact_period),
                    source_url=_string_or_none(record.get("source_url")) or _string_or_none(record.get("url")) or (evidence.source_url if evidence else None),
                    confidence=_optional_float(record.get("confidence")),
                    review_status=_string(record.get("review_status") or "pending"),
                    metadata_json=metadata,
                )
            )
        if rows:
            session.add_all(rows)
            session.flush()
        return len(rows)

    def _import_agent_llm_runs(
        self,
        session: Session,
        *,
        task_id: str,
        output_dir: Path,
    ) -> int:
        existing_ids = list(
            session.scalars(
                select(LLMRun.id).where(
                    LLMRun.task_id == task_id,
                    LLMRun.metadata_json["source"].as_string() == "agent_trace_import",
                )
            ).all()
        )
        if existing_ids:
            session.execute(delete(LLMRun).where(LLMRun.id.in_(existing_ids)))

        summary = _read_json(output_dir / "run_summary.json", default={})
        trace = _read_json(output_dir / "agent_collaboration_trace.json", default={})
        if not isinstance(summary, dict):
            return 0
        executed_agents = summary.get("executed_agents")
        model_usage = summary.get("model_usage_by_agent")
        if not isinstance(executed_agents, list) or not isinstance(model_usage, dict):
            return 0
        trace_by_role = _agent_trace_by_role(trace)
        rows: list[LLMRun] = []
        for role in executed_agents:
            role_key = _string(role).strip()
            if not role_key:
                continue
            usage = model_usage.get(role_key)
            if not isinstance(usage, dict):
                usage = {}
            trace_item = trace_by_role.get(role_key, {})
            model_enabled = bool(usage.get("model_enabled", True))
            status = _string(trace_item.get("status") or "success")
            if not model_enabled:
                status = "skipped"
            elif status == "completed":
                status = "success"
            rows.append(
                LLMRun(
                    run_id=f"agent_{task_id}_{role_key}_{uuid4().hex[:8]}",
                    task_id=task_id,
                    prompt_key=f"agent.{role_key}",
                    prompt_version_id=None,
                    model_role=role_key,
                    model_name=_string_or_none(usage.get("model_name")) or _string_or_none(usage.get("provider")) or "unknown",
                    status=status,
                    attempt_count=1,
                    fallback_used=bool(usage.get("model_fallback_used", False)),
                    schema_valid=None,
                    input_json=_dict_or_none(trace_item.get("input_summary")) or {},
                    output_json={
                        "output_keys": trace_item.get("output_keys") if isinstance(trace_item.get("output_keys"), list) else [],
                        "output_summary": trace_item.get("output_summary") if isinstance(trace_item.get("output_summary"), dict) else {},
                    },
                    error_message=_string_or_none(trace_item.get("error")),
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    cost_usd=0.0,
                    latency_ms=_duration_to_ms(trace_item.get("duration_sec")),
                    metadata_json={
                        "source": "agent_trace_import",
                        "agent": trace_item.get("agent"),
                        "task_type": trace_item.get("task_type") or role_key,
                        "route_profile": usage.get("route_profile"),
                        "api_key_present": usage.get("api_key_present"),
                        "model_enabled": model_enabled,
                        "memory_used": trace_item.get("memory_used"),
                        "quality_feedback_used": trace_item.get("quality_feedback_used"),
                    },
                )
            )
        if rows:
            session.add_all(rows)
            session.flush()
        return len(rows)


def _has_importable_outputs(output_dir: Path, report_dir: Path) -> bool:
    return any((report_dir / filename).exists() for filename in REPORT_ARTIFACTS) or any(
        (output_dir / filename).exists() for filename in OUTPUT_ARTIFACTS
    )


def _task_document_hash(task_id: str) -> str:
    return hashlib.sha256(f"report_task:{task_id}".encode("utf-8")).hexdigest()


def _report_title(path: Path) -> str | None:
    payload = _read_json(path, default={})
    if isinstance(payload, dict):
        return _string_or_none(payload.get("title") or payload.get("report_title"))
    return None


def _task_document_title(task: ReportTask, period: str) -> str:
    symbol = _string_or_none(task.symbol) or "未知标的"
    suffix = f" {period}" if period else ""
    return f"{symbol}{suffix} 研报任务产物"


def _primary_report_artifact(artifacts: list[ReportArtifact]) -> ReportArtifact | None:
    by_type = {artifact.artifact_type: artifact for artifact in artifacts}
    for artifact_type in ("html", "markdown", "json"):
        if artifact_type in by_type:
            return by_type[artifact_type]
    return artifacts[0] if artifacts else None


def _processing_step(
    step_name: str,
    status: str,
    now: datetime,
    metadata: dict[str, Any],
) -> DocumentProcessingStep:
    completed_at = now if status in {"success", "failed", "skipped"} else None
    return DocumentProcessingStep(
        step_name=step_name,
        status=status,
        started_at=now if status != "skipped" else None,
        finished_at=completed_at if status != "skipped" else None,
        metadata_json=metadata,
    )


def _claim_bind_step_status(*, claim_count: int, claim_evidence_count: int) -> str:
    if claim_count <= 0:
        return "skipped"
    if claim_evidence_count <= 0:
        return "failed"
    return "success"


def _verify_step_status(*, verification_exists: bool, verification_passed: bool) -> str:
    if not verification_exists:
        return "skipped"
    return "success" if verification_passed else "failed"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_records(path: Path, *, preferred_key: str, warnings: list[str]) -> list[dict[str, Any]]:
    payload = _read_json(path, default=[])
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        value = payload.get(preferred_key) or payload.get("items") or payload.get("records") or []
        raw_rows = value if isinstance(value, list) else []
    else:
        raw_rows = []
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        if isinstance(row, dict):
            rows.append(row)
        else:
            warnings.append(f"{path.name} row {index} is not an object")
    return rows


def _extract_evidence_ids(record: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("evidence_ids", "supporting_evidence_ids", "citation_evidence_ids"):
        if isinstance(record.get(key), list):
            values.extend(record[key])
    if record.get("evidence_id"):
        values.append(record["evidence_id"])
    for key in ("citations", "supporting_evidence", "evidence"):
        items = record.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    values.append(item.get("evidence_id") or item.get("id"))
                else:
                    values.append(item)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _string(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _claim_verification_summary(verification: Any, claim_id: str) -> dict[str, Any]:
    if not isinstance(verification, dict):
        return {}
    for key in ("claims", "claim_results", "per_claim", "results"):
        rows = verification.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and _string(row.get("claim_id") or row.get("id")) == claim_id:
                    return row
        elif isinstance(rows, dict) and claim_id in rows:
            value = rows[claim_id]
            return value if isinstance(value, dict) else {"value": value}
    return {"passed": verification.get("passed")} if "passed" in verification else {}


def _claim_verification_status(
    record: dict[str, Any],
    verification_summary: dict[str, Any],
    linked_evidence: list[EvidenceItem],
) -> str:
    explicit = _string_or_none(record.get("verification_status") or record.get("status"))
    if explicit and explicit not in {"pending", "unknown"}:
        return explicit
    if verification_summary.get("passed") is True:
        return "supported" if linked_evidence else "failed"
    if verification_summary.get("passed") is False:
        return "failed"
    if linked_evidence and not _extract_numeric_values(record):
        return "supported"
    return explicit or "pending"


def _claim_numeric_check_status(record: dict[str, Any], linked_evidence: list[EvidenceItem]) -> str | None:
    explicit = _string_or_none(record.get("numeric_check_status"))
    if explicit:
        return explicit
    numeric_values = _extract_numeric_values(record)
    if not numeric_values:
        return None
    searchable = " ".join([item.content or "" for item in linked_evidence])
    if not searchable:
        return "failed"
    missing = [
        value
        for value in numeric_values.values()
        if not _numeric_value_appears_in_text(value, searchable)
    ]
    return "failed" if missing else "passed"


def _claim_citation_check_status(evidence_ids: list[str], linked_evidence: list[EvidenceItem]) -> str:
    if not evidence_ids:
        return "failed"
    return "passed" if len(evidence_ids) == len(linked_evidence) else "failed"


def _extract_numeric_values(record: dict[str, Any]) -> dict[str, Any]:
    numeric_values = record.get("numeric_values")
    return numeric_values if isinstance(numeric_values, dict) else {}


def _numeric_value_appears_in_text(value: Any, text: str) -> bool:
    number = _optional_float(value)
    if number is None:
        return False
    candidates = {
        str(value),
        f"{number}",
        f"{number:.0f}",
        f"{number:.1f}",
        f"{number:.2f}",
    }
    if abs(number) >= 1_000_000_000:
        candidates.add(f"{number / 1_000_000_000:.2f}B")
        candidates.add(f"{number / 1_000_000_000:.1f}B")
        candidates.add(f"{number / 1_000_000_000:.2f} billion")
    if abs(number) >= 1_000_000:
        candidates.add(f"{number / 1_000_000:.2f}M")
        candidates.add(f"{number / 1_000_000:.1f}M")
    compact_text = text.replace(",", "")
    return any(candidate.replace(",", "") in compact_text for candidate in candidates if candidate)


def _metadata(record: dict[str, Any], *, task_id: str, period: str, missing_fields: list[str]) -> dict[str, Any]:
    metadata = dict(record.get("metadata", {})) if isinstance(record.get("metadata"), dict) else {}
    metadata["raw_artifact_record"] = dict(record)
    metadata["task_id"] = task_id
    metadata["period"] = period
    if missing_fields:
        metadata["missing_fields"] = missing_fields
    return metadata


def _artifact_url(*, path: Path, root: Path, task_id: str, filename: str, artifact_root: str) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
        return f"/artifacts/{relative.as_posix()}"
    except (OSError, ValueError):
        return f"/artifacts/runs/{task_id}/{artifact_root}/{filename}"


def _string(value: Any) -> str:
    return "" if value is None else str(value)


def _string_or_none(value: Any) -> str | None:
    text = _string(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _agent_trace_by_role(trace: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(trace, dict):
        return {}
    agents = trace.get("agents")
    if not isinstance(agents, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in agents:
        if not isinstance(item, dict):
            continue
        task_type = _string(item.get("task_type")).strip()
        role = _normalize_agent_role(task_type or item.get("agent"))
        if role:
            result[role] = item
    return result


def _normalize_agent_role(value: Any) -> str:
    text = _string(value).strip()
    mapping = {
        "planning": "planning",
        "deep_researcher": "research",
        "research": "research",
        "browser": "browser",
        "deep_analyze": "analyze",
        "analyze": "analyze",
        "final_answer": "final_answer",
        "writer": "final_answer",
        "verifier": "verifier",
        "gap_resolver": "gap_resolver",
        "PlanningAgent": "planning",
        "DeepResearcherAgent": "research",
        "BrowserAgent": "browser",
        "DeepAnalyzeAgent": "analyze",
        "FinalAnswerAgent": "final_answer",
        "VerifierAgent": "verifier",
        "GapResolverAgent": "gap_resolver",
    }
    return mapping.get(text, text)


def _duration_to_ms(value: Any) -> int | None:
    number = _optional_float(value)
    if number is None:
        return None
    return max(0, int(number * 1000))


def _extract_fact_records(output_dir: Path, *, task_id: str, period: str, warnings: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(_extract_fact_records_from_claims(output_dir / "claims.json", task_id=task_id, period=period, warnings=warnings))
    records.extend(_extract_fact_records_from_financial_metrics(output_dir / "financial_metrics.json", task_id=task_id, period=period))
    return records


def _extract_fact_records_from_claims(path: Path, *, task_id: str, period: str, warnings: list[str]) -> list[dict[str, Any]]:
    rows = _read_records(path, preferred_key="claims", warnings=warnings)
    facts: list[dict[str, Any]] = []
    for row in rows:
        numeric_values = row.get("numeric_values")
        if not isinstance(numeric_values, dict):
            continue
        evidence_ids = _extract_evidence_ids(row)
        evidence_id = evidence_ids[0] if evidence_ids else None
        claim_id = _string_or_none(row.get("claim_id") or row.get("id"))
        for metric_name, value in numeric_values.items():
            if _optional_float(value) is None:
                continue
            facts.append(
                {
                    "metric_name": metric_name,
                    "value": value,
                    "period": row.get("period") or period,
                    "evidence_id": evidence_id,
                    "confidence": row.get("confidence"),
                    "source": "claims.numeric_values",
                    "claim_id": claim_id,
                    "review_status": "pending",
                    "metadata": {
                        "task_id": task_id,
                        "claim_id": claim_id,
                        "source": "claims.numeric_values",
                        "evidence_ids": evidence_ids,
                    },
                }
            )
    return facts


def _extract_fact_records_from_financial_metrics(path: Path, *, task_id: str, period: str) -> list[dict[str, Any]]:
    payload = _read_json(path, default={})
    if not payload:
        return []
    raw_rows: list[Any]
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        for key in ("facts", "items", "records", "metrics"):
            if isinstance(payload.get(key), list):
                raw_rows = payload[key]
                break
        else:
            raw_rows = [{"metric_name": key, "value": value} for key, value in payload.items() if _optional_float(value) is not None]
    else:
        raw_rows = []

    records: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        metric_name = row.get("metric_name") or row.get("metric") or row.get("metric_key") or row.get("name")
        value = row.get("value")
        if metric_name is None or _optional_float(value) is None:
            continue
        record = dict(row)
        record["metric_name"] = metric_name
        record["value"] = value
        record["period"] = row.get("period") or period
        metadata = dict(row.get("metadata", {})) if isinstance(row.get("metadata"), dict) else {}
        metadata.setdefault("task_id", task_id)
        metadata.setdefault("source", "financial_metrics")
        record["metadata"] = metadata
        records.append(record)
    return records


def _infer_metric_type(metric_name: str, record: dict[str, Any]) -> str:
    unit = _string(record.get("unit") or "").lower()
    if unit in {"pct", "%", "percent", "percentage"}:
        return "ratio"
    currency = _fact_currency(record)
    lower = metric_name.lower()
    if "margin" in lower or "rate" in lower or "ratio" in lower or "率" in metric_name:
        return "ratio"
    if currency or any(token in lower for token in ("revenue", "income", "profit", "cash", "asset", "liabilit", "equity", "capex", "fcf")):
        return "money"
    return "number"


def _fact_unit(record: dict[str, Any]) -> str | None:
    unit = _string_or_none(record.get("unit"))
    if unit and unit.lower() in {"pct", "percent", "percentage"}:
        return "%"
    if unit and unit.lower() not in {"unknown"}:
        return unit
    currency = _fact_currency(record)
    if currency:
        return "raw"
    metric_name = _string(record.get("metric_name") or record.get("metric"))
    if _infer_metric_type(metric_name, record) == "ratio":
        return "%"
    return None


def _fact_currency(record: dict[str, Any]) -> str | None:
    currency = _optional_upper(record.get("currency"))
    if currency and currency not in {"UNKNOWN", "N/A", "NA"}:
        return currency
    metric_name = _string(record.get("metric_name") or record.get("metric"))
    lower = metric_name.lower()
    if "margin" in lower or "rate" in lower or "ratio" in lower or "率" in metric_name:
        return None
    return "USD" if any(token in lower for token in ("revenue", "income", "profit", "cash", "asset", "liabilit", "equity", "capex", "fcf")) else None


def _fact_evidence_id(record: dict[str, Any]) -> str | None:
    for key in ("evidence_id", "source_evidence_id", "source_id"):
        value = _string_or_none(record.get(key))
        if value:
            return value
    return None


def _optional_upper(value: Any) -> str | None:
    text = _string_or_none(value)
    return text.upper() if text else None


def _fiscal_year_from_period(period: str) -> int | None:
    text = str(period or "").upper()
    if text.startswith("FY"):
        return _optional_int(text.removeprefix("FY"))
    return None


def _get_or_create_company_id(session: Session, *, symbol: str, name: str, market: str) -> int | None:
    normalized_symbol = symbol.strip().upper()
    normalized_market = market.strip().upper() or None
    normalized_name = name.strip() or normalized_symbol
    if not normalized_symbol and not normalized_name:
        return None
    if normalized_symbol:
        company = session.scalar(select(Company).where(Company.symbol == normalized_symbol, Company.market == normalized_market))
        if company is not None:
            return company.id
    company = Company(
        name=normalized_name or normalized_symbol or "未知公司",
        symbol=normalized_symbol or None,
        market=normalized_market,
        aliases=[item for item in [normalized_name, normalized_symbol] if item],
    )
    session.add(company)
    session.flush()
    return company.id
