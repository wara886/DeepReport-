"""Export center service for artifact review and formal package assembly."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import csv
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import ClaimEvidence, EvidenceItem, FinancialFact, ReportArtifact, ReportClaim, ReportTask, ReviewRecord
from src.services.report_task_service import serialize_artifact


class ExportTaskNotFound(LookupError):
    """Raised when export review is requested for an unknown task."""


class ExportService:
    """Summarize task artifacts and review readiness."""

    REVIEWED_ARTIFACT_TYPES = {
        "markdown",
        "html",
        "json",
        "claims",
        "evidence",
        "verification_report",
    }

    def __init__(self, *, session_factory: Callable[[], Session], package_root: str | Path = "data/export_packages") -> None:
        self.session_factory = session_factory
        self.package_root = Path(package_root)

    def list_export_entries(self, *, status: str | None = None, symbol: str | None = None, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session_factory() as session:
            stmt = (
                select(ReportTask)
                .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.claims))
                .order_by(ReportTask.created_at.desc(), ReportTask.id.desc())
                .limit(limit)
            )
            if status:
                stmt = stmt.where(ReportTask.status == status)
            if symbol:
                stmt = stmt.where(ReportTask.symbol == symbol.strip().upper())
            items = [self.serialize_export_entry(task) for task in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_export_entry(self, task_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            task = session.scalar(
                select(ReportTask)
                .where(ReportTask.task_id == task_id)
                .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.claims))
            )
            if task is None:
                raise ExportTaskNotFound(task_id)
            return self.serialize_export_entry(task, include_claims=True)

    def serialize_export_entry(self, task: ReportTask, *, include_claims: bool = False) -> dict[str, Any]:
        artifacts = [serialize_artifact(item) for item in sorted(task.artifacts, key=lambda item: item.id or 0)]
        claim_counts = Counter(claim.review_status for claim in task.claims)
        blocked_reasons = export_blockers(task, claim_counts)
        payload = {
            "task_id": task.task_id,
            "symbol": task.symbol,
            "period": task.period,
            "status": task.status,
            "quality_score": task.quality_score,
            "created_at": _dt(task.created_at),
            "finished_at": _dt(task.finished_at),
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "review_status_counts": dict(sorted(claim_counts.items())),
            "approved_claim_count": int(claim_counts.get("approved", 0)),
            "pending_claim_count": int(claim_counts.get("pending", 0)),
            "rejected_claim_count": int(claim_counts.get("rejected", 0)),
            "official_export_ready": not blocked_reasons,
            "blocked_reasons": blocked_reasons,
            "formal_export_note": "正式导出包已接入 Markdown、HTML、JSON 和 CSV；PDF/DOCX 可基于同一导出包继续生成。",
        }
        if include_claims:
            payload["claims"] = [serialize_claim(claim) for claim in sorted(task.claims, key=lambda item: item.id or 0)]
        return payload

    def build_export_package(self, task_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            task = session.scalar(
                select(ReportTask)
                .where(ReportTask.task_id == task_id)
                .options(
                    selectinload(ReportTask.artifacts),
                    selectinload(ReportTask.claims).selectinload(ReportClaim.evidence_links).selectinload(ClaimEvidence.evidence_item),
                )
            )
            if task is None:
                raise ExportTaskNotFound(task_id)
            entry = self.serialize_export_entry(task, include_claims=False)
            ordered_claims = sorted(task.claims, key=lambda item: item.id or 0)
            approved_claims = [claim for claim in ordered_claims if claim.review_status == "approved"]
            excluded_claims = [claim for claim in ordered_claims if claim.review_status != "approved"]
            evidence_items = _package_evidence(approved_claims)
            financial_facts = _package_financial_facts(session, task)
            review_records = _package_review_records(session, ordered_claims)

            json_payload = {
                "task": _package_task(task),
                "readiness": {
                    "official_export_ready": entry["official_export_ready"],
                    "blocked_reasons": entry["blocked_reasons"],
                    "approved_claim_count": len(approved_claims),
                    "pending_claim_count": entry["pending_claim_count"],
                    "rejected_claim_count": entry["rejected_claim_count"],
                    "excluded_claim_count": len(excluded_claims),
                },
                "claims": [_package_claim(claim) for claim in approved_claims],
                "excluded_claims": [_package_claim(claim, include_evidence=False) for claim in excluded_claims],
                "evidence": evidence_items,
                "financial_facts": financial_facts,
                "review_records": review_records,
                "quality_report": _quality_report(task),
                "artifacts": entry["artifacts"],
            }

        return {
            "task_id": task_id,
            "formats": ["json", "markdown", "html", "claims_csv", "evidence_csv", "facts_csv", "review_csv"],
            "json": json_payload,
            "markdown": _render_package_markdown(json_payload),
            "html": _render_package_html(json_payload),
            "csv": {
                "claims": _claims_csv(json_payload["claims"]),
                "evidence": _evidence_csv(evidence_items),
                "financial_facts": _facts_csv(financial_facts),
                "review_records": _review_csv(review_records),
            },
        }

    def write_export_package(self, task_id: str) -> dict[str, Any]:
        package = self.build_export_package(task_id)
        target_dir = self.package_root / _safe_task_dir(task_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "json": ("package.json", json.dumps(package["json"], ensure_ascii=False, indent=2)),
            "markdown": ("report_package.md", package["markdown"]),
            "html": ("report_package.html", package["html"]),
            "claims_csv": ("claims.csv", package["csv"]["claims"]),
            "evidence_csv": ("evidence.csv", package["csv"]["evidence"]),
            "facts_csv": ("financial_facts.csv", package["csv"]["financial_facts"]),
            "review_csv": ("review_records.csv", package["csv"]["review_records"]),
        }
        written = []
        for key, (filename, content) in files.items():
            path = target_dir / filename
            path.write_text(content, encoding="utf-8")
            written.append(
                {
                    "format": key,
                    "filename": filename,
                    "path": str(path),
                    "download_url": f"/api/exports/{task_id}/package/files/{filename}",
                    "size_bytes": path.stat().st_size,
                }
            )
        return {
            "task_id": task_id,
            "package_dir": str(target_dir),
            "files": written,
            "readiness": package["json"]["readiness"],
        }

    def get_package_file(self, task_id: str, filename: str) -> Path:
        allowed = {
            "package.json",
            "report_package.md",
            "report_package.html",
            "claims.csv",
            "evidence.csv",
            "financial_facts.csv",
            "review_records.csv",
        }
        if filename not in allowed:
            raise FileNotFoundError(filename)
        path = self.package_root / _safe_task_dir(task_id) / filename
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(filename)
        return path

    def artifact_distribution(self) -> dict[str, int]:
        with self.session_factory() as session:
            rows = session.execute(select(ReportArtifact.artifact_type, func.count()).group_by(ReportArtifact.artifact_type)).all()
        return {str(key or "unknown"): int(value or 0) for key, value in rows}


def export_blockers(task: ReportTask, claim_counts: Counter[str]) -> list[str]:
    blockers: list[str] = []
    if task.status != "completed":
        blockers.append("report_task_not_completed")
    if int(claim_counts.get("rejected", 0)) > 0:
        blockers.append("rejected_claims_present")
    if int(claim_counts.get("pending", 0)) > 0:
        blockers.append("pending_claim_review")
    artifact_types = {artifact.artifact_type for artifact in task.artifacts}
    if not artifact_types.intersection({"markdown", "html", "json"}):
        blockers.append("report_artifact_missing")
    return blockers


def serialize_claim(claim: ReportClaim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "section_name": claim.section_name,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "verification_status": claim.verification_status,
        "review_status": claim.review_status,
    }


def _package_task(task: ReportTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "symbol": task.symbol,
        "period": task.period,
        "report_type": task.report_type,
        "status": task.status,
        "quality_score": task.quality_score,
        "created_at": _dt(task.created_at),
        "finished_at": _dt(task.finished_at),
    }


def _package_claim(claim: ReportClaim, *, include_evidence: bool = True) -> dict[str, Any]:
    payload = {
        "id": claim.id,
        "section_name": claim.section_name,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "is_critical": claim.is_critical,
        "verification_status": claim.verification_status,
        "numeric_check_status": claim.numeric_check_status,
        "citation_check_status": claim.citation_check_status,
        "confidence": claim.confidence,
        "review_status": claim.review_status,
    }
    if include_evidence:
        payload["evidence_ids"] = [link.evidence_item.evidence_id for link in claim.evidence_links if link.evidence_item is not None]
    return payload


def _package_evidence(claims: list[ReportClaim]) -> list[dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for claim in claims:
        for link in claim.evidence_links:
            item = link.evidence_item
            if item is None or item.id in rows:
                continue
            rows[item.id] = _package_evidence_item(item)
    return list(rows.values())


def _package_evidence_item(item: EvidenceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "evidence_id": item.evidence_id,
        "source_type": item.source_type,
        "trust_level": item.trust_level,
        "title": item.title,
        "content": item.content,
        "source_url": item.source_url,
        "page_no": item.page_no,
        "metadata": item.metadata_json or {},
        "created_at": _dt(item.created_at),
    }


def _package_financial_facts(session: Session, task: ReportTask) -> list[dict[str, Any]]:
    if task.company_id is None:
        return []
    facts = session.scalars(
        select(FinancialFact)
        .where(FinancialFact.company_id == task.company_id, FinancialFact.period == task.period)
        .order_by(FinancialFact.metric_name.asc(), FinancialFact.id.asc())
    ).all()
    return [
        {
            "id": fact.id,
            "metric_name": fact.metric_name,
            "metric_type": fact.metric_type,
            "value": fact.value,
            "unit": fact.unit,
            "currency": fact.currency,
            "scale": fact.scale,
            "period": fact.period,
            "fiscal_year": fact.fiscal_year,
            "source_url": fact.source_url,
            "confidence": fact.confidence,
            "review_status": fact.review_status,
        }
        for fact in facts
    ]


def _package_review_records(session: Session, claims: list[ReportClaim]) -> list[dict[str, Any]]:
    claim_ids = [str(claim.id) for claim in claims if claim.id is not None]
    if not claim_ids:
        return []
    records = session.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.target_type == "report_claim", ReviewRecord.target_id.in_(claim_ids))
        .order_by(ReviewRecord.created_at.desc(), ReviewRecord.id.desc())
    ).all()
    return [
        {
            "id": record.id,
            "target_type": record.target_type,
            "target_id": record.target_id,
            "decision": record.decision,
            "comment": record.comment,
            "reviewer": record.reviewer,
            "created_at": _dt(record.created_at),
        }
        for record in records
    ]


def _quality_report(task: ReportTask) -> dict[str, Any]:
    metadata = task.metadata_json or {}
    quality_result = metadata.get("quality_result") if isinstance(metadata.get("quality_result"), dict) else {}
    return {
        "quality_score": task.quality_score,
        "delivery_gate": quality_result.get("delivery_gate") or {},
        "top_quality_issues": quality_result.get("top_quality_issues") or [],
    }


def _render_package_markdown(payload: dict[str, Any]) -> str:
    task = payload["task"]
    readiness = payload["readiness"]
    lines = [
        f"# {task['symbol']} {task['period']} 正式导出包",
        "",
        "## 导出状态",
        "",
        f"- 正式导出：{'可导出' if readiness['official_export_ready'] else '存在阻塞'}",
        f"- 已通过主张：{readiness['approved_claim_count']}",
        f"- 已排除主张：{readiness['excluded_claim_count']}",
        "",
        "## 已通过主张",
        "",
    ]
    for claim in payload["claims"]:
        evidence_ids = "、".join(claim.get("evidence_ids") or []) or "未绑定证据"
        lines.append(f"- {claim.get('claim_text')}（证据：{evidence_ids}）")
    lines.extend(["", "## 证据", ""])
    for item in payload["evidence"]:
        lines.append(f"- {item.get('evidence_id')}: {item.get('title') or item.get('source_type') or '证据'}")
    lines.extend(["", "## 财务事实", ""])
    for fact in payload["financial_facts"]:
        lines.append(f"- {fact.get('metric_name')}: {fact.get('value')} {fact.get('currency') or ''} {fact.get('unit') or ''}".strip())
    return "\n".join(lines).rstrip() + "\n"


def _render_package_html(payload: dict[str, Any]) -> str:
    task = payload["task"]
    readiness = payload["readiness"]
    claims = "".join(f"<li>{_html_escape(item.get('claim_text'))}</li>" for item in payload["claims"])
    evidence = "".join(f"<li>{_html_escape(item.get('evidence_id'))}: {_html_escape(item.get('title') or item.get('source_type') or '证据')}</li>" for item in payload["evidence"])
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>正式导出包</title></head><body>"
        f"<h1>{_html_escape(task['symbol'])} {_html_escape(task['period'])} 正式导出包</h1>"
        f"<p>正式导出：{'可导出' if readiness['official_export_ready'] else '存在阻塞'}；已排除主张：{readiness['excluded_claim_count']}</p>"
        f"<h2>已通过主张</h2><ul>{claims}</ul>"
        f"<h2>证据</h2><ul>{evidence}</ul>"
        "</body></html>"
    )


def _claims_csv(rows: list[dict[str, Any]]) -> str:
    return _write_csv(rows, ["id", "section_name", "claim_text", "verification_status", "review_status"])


def _evidence_csv(rows: list[dict[str, Any]]) -> str:
    return _write_csv(rows, ["evidence_id", "source_type", "trust_level", "title", "source_url", "page_no"])


def _facts_csv(rows: list[dict[str, Any]]) -> str:
    return _write_csv(rows, ["metric_name", "metric_type", "value", "currency", "unit", "scale", "period", "review_status"])


def _review_csv(rows: list[dict[str, Any]]) -> str:
    return _write_csv(rows, ["id", "target_type", "target_id", "decision", "comment", "reviewer", "created_at"])


def _write_csv(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _html_escape(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _safe_task_dir(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value or "").strip())
    return safe or "task"


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
