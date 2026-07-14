"""Export center service for artifact review and formal package assembly."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import csv
from datetime import datetime
import hashlib
from io import StringIO
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import ClaimEvidence, EvidenceItem, FinancialFact, ReportArtifact, ReportClaim, ReportTask, ReviewRecord
from src.runtime.report_run_state import build_report_run_state
from src.report import export_markdown_to_docx, export_markdown_to_pdf
from src.services.report_task_service import serialize_artifact


class ExportTaskNotFound(LookupError):
    """Raised when export review is requested for an unknown task."""


class ExportNotReady(RuntimeError):
    """Raised when a formal package action is blocked by canonical readiness."""

    def __init__(self, task_id: str, blocked_reasons: list[str]) -> None:
        self.task_id = task_id
        self.blocked_reasons = blocked_reasons
        super().__init__(f"Formal export is blocked for {task_id}: {', '.join(blocked_reasons)}")


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
        run_state = build_report_run_state(task)
        claim_state = run_state["claim_state"]
        export_readiness = run_state["export_readiness"]
        blocked_reasons = list(export_readiness["blocking_reasons"])
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
            "review_status_counts": claim_state["review_status_counts"],
            "approved_claim_count": claim_state["approved_count"],
            "pending_claim_count": claim_state["pending_count"],
            "rejected_claim_count": claim_state["rejected_count"],
            "official_export_ready": export_readiness["can_export_formal_package"],
            "blocked_reasons": blocked_reasons,
            "delivery_readiness": run_state["delivery_readiness"],
            "export_readiness": export_readiness,
            "formal_export_note": "正式导出包已接入 Markdown、HTML、PDF、DOCX、JSON 和 CSV，并统一遵守 ExportReadiness。",
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
                "trace_context": {
                    "request_id": str((task.metadata_json or {}).get("request_id") or task.task_id),
                    "run_id": str((task.metadata_json or {}).get("run_id") or task.task_id),
                    "task_id": task.task_id,
                },
                "task": _package_task(task),
                "readiness": {
                    "official_export_ready": entry["official_export_ready"],
                    "blocked_reasons": entry["blocked_reasons"],
                    "delivery_readiness": entry["delivery_readiness"],
                    "export_readiness": entry["export_readiness"],
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
            "formats": ["json", "markdown", "html", "pdf", "docx", "claims_csv", "evidence_csv", "facts_csv", "review_csv"],
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

    def write_export_package(self, task_id: str, *, formats: list[str] | None = None) -> dict[str, Any]:
        package = self.build_export_package(task_id)
        readiness = package["json"]["readiness"]
        if not readiness["official_export_ready"]:
            raise ExportNotReady(task_id, list(readiness["blocked_reasons"]))
        supported_formats = {"json", "markdown", "html", "pdf", "docx", "csv"}
        default_formats = ["json", "markdown", "html", "pdf", "docx", "csv"]
        requested_formats = list(dict.fromkeys(str(item).strip().lower() for item in (formats or default_formats) if str(item).strip()))
        unsupported = sorted(set(requested_formats) - supported_formats)
        if unsupported:
            raise ValueError(f"Unsupported export formats: {', '.join(unsupported)}")
        if not requested_formats:
            raise ValueError("At least one export format is required")
        target_dir = self.package_root / _safe_task_dir(task_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        selection_digest = hashlib.sha256(json.dumps(sorted(requested_formats)).encode("utf-8")).hexdigest()
        package_digest = hashlib.sha256(f"{_package_digest(package)}:{selection_digest}".encode("utf-8")).hexdigest()
        existing_manifest = _read_json(target_dir / "export_manifest.json")
        if existing_manifest.get("package_digest") == package_digest:
            existing_files = existing_manifest.get("files") if isinstance(existing_manifest.get("files"), list) else []
            if existing_files and all((target_dir / str(item.get("filename") or "")).is_file() for item in existing_files):
                return {
                    "task_id": task_id,
                    "package_dir": str(target_dir),
                    "files": existing_files,
                    "readiness": readiness,
                    "trace_context": package["json"]["trace_context"],
                    "selected_formats": requested_formats,
                    "idempotent_reuse": True,
                }
        candidate_files = {
            "json": ("package.json", json.dumps(package["json"], ensure_ascii=False, indent=2)),
            "markdown": ("report_package.md", package["markdown"]),
            "html": ("report_package.html", package["html"]),
            "claims_csv": ("claims.csv", package["csv"]["claims"]),
            "evidence_csv": ("evidence.csv", package["csv"]["evidence"]),
            "facts_csv": ("financial_facts.csv", package["csv"]["financial_facts"]),
            "review_csv": ("review_records.csv", package["csv"]["review_records"]),
        }
        files = {
            key: value for key, value in candidate_files.items()
            if key in requested_formats or (key.endswith("_csv") and "csv" in requested_formats)
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
        title = f"{package['json']['task']['symbol']} {package['json']['task']['period']} 金融研究报告"
        export_metadata = {
            "task_id": task_id,
            "request_id": package["json"]["trace_context"]["request_id"],
            "run_id": package["json"]["trace_context"]["run_id"],
            "quality_score": package["json"]["task"].get("quality_score"),
        }
        binary_exports = []
        if "pdf" in requested_formats:
            binary_exports.append(("pdf", "report_package.pdf", export_markdown_to_pdf(package["markdown"], target_dir / "report_package.pdf", title=title, metadata=export_metadata)))
        if "docx" in requested_formats:
            binary_exports.append(("docx", "report_package.docx", export_markdown_to_docx(package["markdown"], target_dir / "report_package.docx", title=title, metadata=export_metadata)))
        for key, filename, path in binary_exports:
            written.append(
                {
                    "format": key,
                    "filename": filename,
                    "path": str(path),
                    "download_url": f"/api/exports/{task_id}/package/files/{filename}",
                    "size_bytes": path.stat().st_size,
                }
            )
        for item in written:
            item["sha256"] = _sha256(Path(item["path"]))
        manifest_path = target_dir / "export_manifest.json"
        manifest_payload = {
            "schema_version": "formal_export_manifest.v1",
            "package_digest": package_digest,
            "trace_context": package["json"]["trace_context"],
            "selected_formats": requested_formats,
            "files": written,
        }
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_item = {
            "format": "manifest",
            "filename": "export_manifest.json",
            "path": str(manifest_path),
            "download_url": f"/api/exports/{task_id}/package/files/export_manifest.json",
            "size_bytes": manifest_path.stat().st_size,
            "sha256": _sha256(manifest_path),
        }
        written.append(manifest_item)
        manifest_payload["files"] = written
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "task_id": task_id,
            "package_dir": str(target_dir),
            "files": written,
            "readiness": package["json"]["readiness"],
            "trace_context": package["json"]["trace_context"],
            "selected_formats": requested_formats,
            "idempotent_reuse": False,
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
            "report_package.pdf",
            "report_package.docx",
            "export_manifest.json",
        }
        if filename not in allowed:
            raise FileNotFoundError(filename)
        with self.session_factory() as session:
            task = session.scalar(
                select(ReportTask)
                .where(ReportTask.task_id == task_id)
                .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.claims))
            )
            if task is None:
                raise ExportTaskNotFound(task_id)
            readiness = build_report_run_state(task)["export_readiness"]
            if not readiness["can_export_formal_package"]:
                raise ExportNotReady(task_id, list(readiness["blocking_reasons"]))
        path = self.package_root / _safe_task_dir(task_id) / filename
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(filename)
        return path

    def artifact_distribution(self) -> dict[str, int]:
        with self.session_factory() as session:
            rows = session.execute(select(ReportArtifact.artifact_type, func.count()).group_by(ReportArtifact.artifact_type)).all()
        return {str(key or "unknown"): int(value or 0) for key, value in rows}


def export_blockers(task: ReportTask, claim_counts: Counter[str]) -> list[str]:
    del claim_counts  # Kept for the public compatibility signature.
    return list(build_report_run_state(task)["export_readiness"]["blocking_reasons"])


def _package_digest(package: dict[str, Any]) -> str:
    payload = {
        "json": package["json"],
        "markdown": package["markdown"],
        "html": package["html"],
        "csv": package["csv"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
            "before_value": record.before_value,
            "after_value": record.after_value,
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
    return _write_csv(
        rows,
        ["id", "target_type", "target_id", "decision", "comment", "before_value", "after_value", "reviewer", "created_at"],
    )


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
