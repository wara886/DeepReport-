"""Import generated report artifacts into the workbench database."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db.models import ClaimEvidence, EvidenceItem, ReportArtifact, ReportClaim, ReportTask, ReportTaskEvent


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
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "artifact_count": self.artifact_count,
            "evidence_count": self.evidence_count,
            "claim_count": self.claim_count,
            "claim_evidence_count": self.claim_evidence_count,
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
            company_id = task.company_id

            artifacts = self._import_artifacts(session, task_id, output_dir, report_dir)
            evidence_by_external_id = self._import_evidence(
                session,
                task_id=task_id,
                company_id=company_id,
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

            result = ArtifactImportResult(
                task_id=task_id,
                artifact_count=len(artifacts),
                evidence_count=len(evidence_by_external_id),
                claim_count=claim_count,
                claim_evidence_count=link_count,
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

    def _import_evidence(
        self,
        session: Session,
        *,
        task_id: str,
        company_id: int | None,
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
            item.document_id = _optional_int(record.get("document_id"))
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
            metadata["verification_summary"] = _claim_verification_summary(verification, external_claim_id)

            claim = ReportClaim(
                task_id=task_id,
                section_name=_string_or_none(record.get("section_name") or record.get("section")),
                claim_text=_string(record.get("claim_text") or record.get("text") or record.get("claim") or ""),
                claim_type=_string_or_none(record.get("claim_type") or record.get("type")),
                is_critical=bool(record.get("is_critical", record.get("critical", False))),
                critical_claim_type=_string_or_none(record.get("critical_claim_type")),
                verification_status=_string(record.get("verification_status") or record.get("status") or "pending"),
                numeric_check_status=_string_or_none(record.get("numeric_check_status")),
                citation_check_status=_string_or_none(record.get("citation_check_status")),
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
