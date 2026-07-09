"""DB-backed report task lifecycle service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.app.chat_task_parser import latest_completed_period
from src.app.web_ui import run_delivery_quality_pipeline
from src.db.init_db import init_db
from src.db.models import (
    ClaimEvidence,
    EvidenceItem,
    LLMRun,
    PromptTemplate,
    ReportArtifact,
    ReportTask,
    ReportTaskEvent,
)
from src.db.session import create_engine_for_url
from src.llm.harness import serialize_llm_run
from src.llm.harness import LLMHarness
from src.rag.retrieval_diagnostics import build_retrieval_coverage
from src.services.artifact_importer import ArtifactImporter


class ReportTaskNotFound(LookupError):
    """Raised when a report task ID does not exist."""


class ReportTaskConflict(RuntimeError):
    """Raised when a report task operation conflicts with its current state."""


class ReportTaskService:
    """Create, run, inspect, and retry report generation tasks."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        output_root: str | Path = "data/outputs_user",
        report_root: str | Path = "data/reports_user",
        config_path: str = "configs/model_backends.yaml",
        memory_root: str | Path = "memory/chat",
        mode: str = "user",
        orchestrator_factory: Callable[..., Any] | None = None,
        quality_runner: Callable[..., dict[str, Any]] | None = None,
        engine: Engine | None = None,
    ) -> None:
        self.database_url = database_url
        self.output_root = Path(output_root)
        self.report_root = Path(report_root)
        self.config_path = config_path
        self.memory_root = Path(memory_root)
        self.mode = mode
        self.orchestrator_factory = orchestrator_factory or MultiAgentOrchestrator
        self.quality_runner = quality_runner or run_delivery_quality_pipeline
        self._engine = engine
        self._session_factory: sessionmaker[Session] | None = None
        self._init_lock = threading.Lock()

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = str(payload.get("symbol") or "AAPL").strip().upper()
        period = str(payload.get("period") or latest_completed_period()).strip().upper()
        task_id = self._new_task_id(payload.get("task_id"))
        report_type = str(payload.get("report_type") or "equity_research")
        metadata = self._build_task_metadata(task_id=task_id, payload=payload, symbol=symbol, period=period)

        with self.session() as session:
            task = ReportTask(
                task_id=task_id,
                workspace_id=_optional_int(payload.get("workspace_id")),
                company_id=_optional_int(payload.get("company_id")),
                symbol=symbol,
                period=period,
                report_type=report_type,
                status="queued",
                current_stage="queued",
                metadata_json=metadata,
            )
            session.add(task)
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage="queued",
                    status="queued",
                    message="Report task queued",
                    metadata_json={"source": "api"},
                )
            )
            session.commit()

        return self.get_task(task_id)

    def run_task(self, task_id: str) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if task.status == "running":
                raise ReportTaskConflict(f"Task {task_id} is already running")
            if task.status not in {"queued", "failed", "timeout", "quality_failed"}:
                return self.serialize_task(task)

            task.status = "running"
            task.current_stage = "evidence_gate"
            task.started_at = task.started_at or _utc_now()
            task.error_message = None
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="evidence_gate",
                    status="running",
                    message="生成前证据门禁开始",
                    metadata_json=None,
                )
            )
            session.commit()
            metadata = dict(task.metadata_json or {})

        try:
            evidence_gate = self.run_evidence_gate(task_id)
            if evidence_gate.get("blocked") is True:
                return self.get_task(task_id)
            with self.session() as session:
                task = self._get_task_for_update(session, task_id)
                task.current_stage = "orchestrator"
                session.add(
                    ReportTaskEvent(
                        task_id=task.task_id,
                        stage="orchestrator",
                        status="running",
                        message="研报生成流程开始",
                        metadata_json={"evidence_gate_status": evidence_gate.get("status")},
                    )
                )
                session.commit()
            self._run_orchestrator(task_id=task_id, metadata=metadata)
            artifacts = self.import_artifacts(task_id)
            quality_result = self.run_quality_gate(task_id)
            artifacts = self.import_artifacts(task_id)
            with self.session() as session:
                task = self._get_task_for_update(session, task_id)
                delivery_gate = _dict_path(quality_result, "delivery_gate")
                delivery_pass = delivery_gate.get("delivery_pass")
                task.status = "completed" if delivery_pass is True else "quality_failed"
                task.current_stage = task.status
                task.finished_at = _utc_now()
                task.error_message = None
                task.quality_score = _quality_score_from_result(quality_result)
                metadata = dict(task.metadata_json or {})
                metadata["quality_result"] = _compact_quality_result(quality_result)
                task.metadata_json = metadata
                session.add(
                    ReportTaskEvent(
                        task_id=task.task_id,
                        stage=task.status,
                        status=task.status,
                        message="Report task completed" if task.status == "completed" else "Report generated but quality gate failed",
                        metadata_json={
                            "artifact_count": len(artifacts),
                            "delivery_pass": delivery_pass,
                            "quality_score": task.quality_score,
                        },
                    )
                )
                session.commit()
        except Exception as exc:
            with self.session() as session:
                task = self._get_task_for_update(session, task_id)
                task.status = "failed"
                task.current_stage = "failed"
                task.finished_at = _utc_now()
                task.error_message = str(exc)
                session.add(
                    ReportTaskEvent(
                        task_id=task.task_id,
                        stage="failed",
                        status="failed",
                        message=str(exc),
                        metadata_json={"error_type": type(exc).__name__},
                    )
                )
                session.commit()

        return self.get_task(task_id)

    def retry_task(self, task_id: str, *, run_immediately: bool = True) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if task.status == "running":
                raise ReportTaskConflict(f"Task {task_id} is already running")
            if task.status == "archived":
                raise ReportTaskConflict(f"Task {task_id} cannot be retried from archived status")
            task.status = "queued"
            task.current_stage = "queued"
            task.error_message = None
            task.started_at = None
            task.finished_at = None
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="retry",
                    status="queued",
                    message="Report task queued for retry",
                    metadata_json=None,
                )
            )
            session.commit()
        if run_immediately:
            return self.run_task(task_id)
        return self.get_task(task_id)

    def start_task(self, task_id: str, *, run_immediately: bool = True) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if task.status == "running":
                raise ReportTaskConflict(f"Task {task_id} is already running")
            if task.status != "queued":
                raise ReportTaskConflict(f"Task {task_id} cannot be started from status {task.status}")
            task.current_stage = "queued"
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="start",
                    status="queued",
                    message="Report task started from workbench",
                    metadata_json=None,
                )
            )
            session.commit()
        if run_immediately:
            return self.run_task(task_id)
        return self.get_task(task_id)

    def cancel_task(self, task_id: str, *, reason: str | None = None) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if task.status in {"running", "completed", "failed", "cancelled", "archived"}:
                raise ReportTaskConflict(f"Task {task_id} cannot be cancelled from status {task.status}")
            task.status = "cancelled"
            task.current_stage = "cancelled"
            task.finished_at = _utc_now()
            task.error_message = reason or "Task cancelled by user"
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="cancelled",
                    status="cancelled",
                    message=task.error_message,
                    metadata_json={"source": "api"},
                )
            )
            session.commit()
        return self.get_task(task_id)

    def archive_task(self, task_id: str, *, reason: str | None = None) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if task.status == "running":
                raise ReportTaskConflict(f"Task {task_id} is running and cannot be archived")
            if task.status == "archived":
                raise ReportTaskConflict(f"Task {task_id} is already archived")
            previous_status = task.status
            task.status = "archived"
            task.current_stage = "archived"
            task.finished_at = task.finished_at or _utc_now()
            metadata = dict(task.metadata_json or {})
            metadata["archived_from_status"] = previous_status
            metadata["archive_reason"] = reason or "Archived by user"
            task.metadata_json = metadata
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="archived",
                    status="archived",
                    message=metadata["archive_reason"],
                    metadata_json={"previous_status": previous_status, "source": "api"},
                )
            )
            session.commit()
        return self.get_task(task_id)

    def import_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        importer = ArtifactImporter(
            session_factory=self.session,
            output_root=self.output_root,
            report_root=self.report_root,
        )
        importer.import_for_task(task_id)
        return self.get_task(task_id).get("artifacts", [])

    def run_quality_gate(self, task_id: str) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            output_dir = Path(str(metadata.get("output_dir") or ""))
            report_dir = Path(str(metadata.get("report_dir") or ""))
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage="quality_gate",
                    status="running",
                    message="Delivery quality pipeline started",
                    metadata_json=None,
                )
            )
            session.commit()

        result = self.quality_runner(
            output_dir,
            report_dir,
            config_path=self.config_path,
            memory_enabled=bool(metadata.get("memory_enabled", False)),
        )
        llm_run_id = self._record_quality_gate_harness_run(task_id, metadata=metadata, quality_result=result)
        score = _quality_score_from_result(result)
        delivery_pass = _dict_path(result, "delivery_gate").get("delivery_pass")
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if score is not None:
                task.quality_score = score
            metadata = dict(task.metadata_json or {})
            metadata["quality_result"] = _compact_quality_result(result)
            task.metadata_json = metadata
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage="quality_gate",
                    status="success" if delivery_pass is True else "failed",
                    message="Delivery quality gate passed" if delivery_pass is True else "Delivery quality gate failed",
                    metadata_json={
                        "delivery_pass": delivery_pass,
                        "quality_score": score,
                        "top_quality_issues": _top_quality_issues(result),
                        "llm_run_id": llm_run_id,
                    },
                )
            )
            session.commit()
        return result

    def run_evidence_gate(self, task_id: str) -> dict[str, Any]:
        """Check whether a task has enough persisted evidence before generation."""

        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            if _truthy(metadata.get("skip_evidence_gate")):
                gate = {
                    "status": "skipped",
                    "blocked": False,
                    "summary": "已跳过生成前证据门禁。",
                    "coverage": {},
                    "recommended_actions": [],
                }
                metadata["pre_generation_evidence_gate"] = gate
                task.metadata_json = metadata
                session.add(
                    ReportTaskEvent(
                        task_id=task.task_id,
                        stage="evidence_gate",
                        status="skipped",
                        message=gate["summary"],
                        metadata_json=gate,
                    )
                )
                session.commit()
                return gate

            candidates = self._evidence_candidates_for_gate(session, task=task, metadata=metadata)
            returned = [_evidence_gate_row(item) for item in candidates]
            company_label = str(metadata.get("company_name") or task.symbol or "")
            coverage = build_retrieval_coverage(
                candidates=candidates,
                returned=returned,
                company=company_label,
                source_type=None,
                mode_effective="pre_generation_gate",
            )
            blocking_reasons = _evidence_gate_blocking_reasons(coverage)
            enforced = _truthy(metadata.get("enforce_evidence_gate"))
            allow_weak = _truthy(metadata.get("allow_weak_evidence"))
            blocked = bool(blocking_reasons) and enforced and not allow_weak
            status = "failed" if blocked else ("warning" if blocking_reasons else "success")
            gate = {
                "status": status,
                "blocked": blocked,
                "enforced": enforced,
                "allow_weak_evidence": allow_weak,
                "summary": _evidence_gate_summary(coverage=coverage, blocking_reasons=blocking_reasons, blocked=blocked),
                "blocking_reasons": blocking_reasons,
                "coverage": coverage,
                "recommended_actions": _evidence_gate_actions(coverage),
            }
            metadata["pre_generation_evidence_gate"] = gate
            task.metadata_json = metadata
            if blocked:
                task.status = "quality_failed"
                task.current_stage = "evidence_gate_failed"
                task.finished_at = _utc_now()
                task.error_message = gate["summary"]
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="evidence_gate",
                    status=status,
                    message=gate["summary"],
                    metadata_json={
                        "blocked": blocked,
                        "enforced": enforced,
                        "coverage": coverage,
                        "recommended_actions": gate["recommended_actions"],
                    },
                )
            )
            session.commit()
            return gate

    def _record_quality_gate_harness_run(
        self,
        task_id: str,
        *,
        metadata: dict[str, Any],
        quality_result: dict[str, Any],
    ) -> str | None:
        prompt_key = "report_quality_gate"
        active_prompt = self._active_prompt(prompt_key)
        backend = QualityGateTraceBackend()
        harness = LLMHarness(session_factory=self.session, backend=backend)
        input_payload = {
            "task_id": task_id,
            "symbol": metadata.get("symbol"),
            "period": metadata.get("period"),
            "report_type": metadata.get("report_type"),
            "delivery_gate": _dict_path(quality_result, "delivery_gate"),
            "quality_report": _dict_path(quality_result, "quality_report"),
            "llm_quality_review": _dict_path(quality_result, "llm_quality_review"),
            "top_quality_issues": _top_quality_issues(quality_result),
        }
        prompt = active_prompt["content"] if active_prompt else "Record report quality gate result."
        result = harness.run_prompt(
            prompt_key=prompt_key,
            input=input_payload,
            schema={
                "type": "object",
                "required": ["delivery_pass", "issue_count", "summary"],
                "properties": {
                    "delivery_pass": {"type": "boolean"},
                    "issue_count": {"type": "integer"},
                    "summary": {"type": "string"},
                },
            },
            model_role="quality_gate",
            task_id=task_id,
            prompt=prompt,
            prompt_version_id=active_prompt["version_id"] if active_prompt else None,
            metadata={
                "source": "report_task_quality_gate",
                "promptops_bound": bool(active_prompt),
            },
        )
        return result.run_id

    def _active_prompt(self, prompt_key: str) -> dict[str, Any] | None:
        with self.session() as session:
            template = session.scalar(
                select(PromptTemplate)
                .where(PromptTemplate.prompt_key == prompt_key, PromptTemplate.is_active.is_(True))
                .options(selectinload(PromptTemplate.versions))
            )
            if template is None:
                return None
            versions = [version for version in template.versions if version.is_active]
            if not versions:
                versions = list(template.versions)
            if not versions:
                return None
            version = sorted(versions, key=lambda item: item.version, reverse=True)[0]
            return {"version_id": version.id, "content": version.content}

    def list_tasks(self, *, status: str | None = None, symbol: str | None = None, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session() as session:
            stmt = (
                select(ReportTask)
                .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.events))
                .order_by(ReportTask.created_at.desc(), ReportTask.id.desc())
                .limit(limit)
            )
            count_stmt = select(func.count()).select_from(ReportTask)
            if status:
                stmt = stmt.where(ReportTask.status == status)
                count_stmt = count_stmt.where(ReportTask.status == status)
            else:
                stmt = stmt.where(ReportTask.status != "archived")
                count_stmt = count_stmt.where(ReportTask.status != "archived")
            if symbol:
                normalized_symbol = symbol.strip().upper()
                stmt = stmt.where(ReportTask.symbol == normalized_symbol)
                count_stmt = count_stmt.where(ReportTask.symbol == normalized_symbol)
            items = [self.serialize_task(task) for task in session.scalars(stmt).all()]
            total = int(session.scalar(count_stmt) or 0)
        return {"items": items, "total": total}

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self.session() as session:
            task = session.scalar(
                select(ReportTask)
                .where(ReportTask.task_id == task_id)
                .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.events))
            )
            if task is None:
                raise ReportTaskNotFound(task_id)
            payload = self.serialize_task(task)
            llm_runs = list(
                session.scalars(
                    select(LLMRun)
                    .where(LLMRun.task_id == task_id)
                    .order_by(LLMRun.created_at.desc(), LLMRun.id.desc())
                    .limit(50)
                ).all()
            )
            payload["quality_diagnostics"] = build_quality_diagnostics(task, llm_runs)
            return payload

    def get_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        return {
            "task_id": task_id,
            "artifacts": task.get("artifacts", []),
            "report_links": _report_links(task.get("artifacts", [])),
        }

    def session(self) -> Session:
        self._ensure_db()
        assert self._session_factory is not None
        return self._session_factory()

    def serialize_task(self, task: ReportTask) -> dict[str, Any]:
        artifacts = [serialize_artifact(item) for item in sorted(task.artifacts, key=lambda item: item.id or 0)]
        events = [serialize_event(item) for item in sorted(task.events, key=lambda item: item.id or 0)]
        return {
            "id": task.id,
            "task_id": task.task_id,
            "workspace_id": task.workspace_id,
            "company_id": task.company_id,
            "symbol": task.symbol,
            "period": task.period,
            "report_type": task.report_type,
            "status": task.status,
            "current_stage": task.current_stage,
            "quality_score": task.quality_score,
            "created_at": _dt(task.created_at),
            "started_at": _dt(task.started_at),
            "finished_at": _dt(task.finished_at),
            "error_message": task.error_message,
            "metadata": task.metadata_json or {},
            "events": events,
            "artifacts": artifacts,
            "report_links": _report_links(artifacts),
        }

    def _ensure_db(self) -> None:
        if self._session_factory is not None:
            return
        with self._init_lock:
            if self._session_factory is not None:
                return
            engine = self._engine or create_engine_for_url(self.database_url)
            init_db(engine=engine)
            self._engine = engine
            self._session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

    def _new_task_id(self, explicit_task_id: Any) -> str:
        explicit = str(explicit_task_id or "").strip()
        if explicit:
            return _safe_id(explicit)
        return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}"

    def _build_task_metadata(self, *, task_id: str, payload: dict[str, Any], symbol: str, period: str) -> dict[str, Any]:
        execution_mode = str(payload.get("execution_mode") or "collaborative")
        output_dir = self.output_root / "runs" / task_id / "outputs"
        report_dir = self.report_root / "runs" / task_id / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "job_id.txt").write_text(task_id, encoding="utf-8")
        (output_dir / "run_id.txt").write_text(task_id, encoding="utf-8")
        request_state = {
            "run_id": task_id,
            "job_id": task_id,
            "symbol": symbol,
            "period": period,
            "request_id": str(payload.get("request_id") or task_id),
            "session_id": str(payload.get("session_id") or "api"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        (output_dir / "request_state.json").write_text(json.dumps(request_state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "run_id": task_id,
            "output_dir": str(output_dir),
            "report_dir": str(report_dir),
            "request_id": request_state["request_id"],
            "session_id": request_state["session_id"],
            "research_topic": str(payload.get("research_topic") or payload.get("topic") or f"Generate {symbol} {period} research report"),
            "company_name": str(payload.get("company_name") or symbol),
            "symbol": symbol,
            "period": period,
            "report_type": str(payload.get("report_type") or "equity_research"),
            "data_source_scope": str(payload.get("data_source_scope") or "official_first"),
            "execution_mode": execution_mode,
            "fast": bool(payload.get("fast", True)),
            "search_engines": _normalize_search_engines(payload.get("search_engines")),
            "enable_remote_data": bool(payload.get("enable_remote_data", False)),
            "data_source_config_path": str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
            "memory_enabled": bool(payload.get("memory_enabled", False)),
            "execution_tier": str(payload.get("execution_tier") or ("user_fast" if self.mode == "user" else "developer_fast")),
            "enforce_evidence_gate": _truthy(payload.get("enforce_evidence_gate", False)),
            "allow_weak_evidence": _truthy(payload.get("allow_weak_evidence", False)),
            "skip_evidence_gate": _truthy(payload.get("skip_evidence_gate", False)),
        }

    def _run_orchestrator(self, *, task_id: str, metadata: dict[str, Any]) -> Any:
        orchestrator = self.orchestrator_factory(
            output_dir=str(metadata["output_dir"]),
            report_dir=str(metadata["report_dir"]),
            config_path=self.config_path,
            memory_enabled=bool(metadata.get("memory_enabled", False)),
            memory_root=str(self.memory_root / "durable"),
            execution_tier=str(metadata.get("execution_tier") or "developer_fast"),
        )
        result = orchestrator.run(
            research_topic=str(metadata.get("research_topic") or ""),
            symbol=str(metadata.get("symbol") or ""),
            period=str(metadata.get("period") or ""),
            execution_mode=str(metadata.get("execution_mode") or "collaborative"),
            fast=bool(metadata.get("fast", True)),
            search_engines=list(metadata.get("search_engines") or []),
            enable_remote_data=bool(metadata.get("enable_remote_data", False)),
            data_source_config_path=str(metadata.get("data_source_config_path") or "configs/data_sources.yaml"),
        )
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            task.current_stage = "artifact_import"
            if isinstance(result, dict) and isinstance(result.get("quality_score"), (int, float)):
                task.quality_score = float(result["quality_score"])
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage="orchestrator",
                    status="success",
                    message="MultiAgentOrchestrator.run completed",
                    metadata_json={"result_keys": sorted(result.keys()) if isinstance(result, dict) else []},
                )
            )
            session.commit()
        return result

    def _get_task_for_update(self, session: Session, task_id: str) -> ReportTask:
        task = session.scalar(
            select(ReportTask)
            .where(ReportTask.task_id == task_id)
            .options(selectinload(ReportTask.artifacts), selectinload(ReportTask.events))
        )
        if task is None:
            raise ReportTaskNotFound(task_id)
        return task

    def _evidence_candidates_for_gate(
        self,
        session: Session,
        *,
        task: ReportTask,
        metadata: dict[str, Any],
    ) -> list[EvidenceItem]:
        stmt = (
            select(EvidenceItem)
            .options(
                selectinload(EvidenceItem.company),
                selectinload(EvidenceItem.document),
                selectinload(EvidenceItem.claim_links).selectinload(ClaimEvidence.claim),
            )
            .order_by(EvidenceItem.created_at.desc(), EvidenceItem.id.desc())
            .limit(1000)
        )
        items = list(session.scalars(stmt).unique().all())
        return [item for item in items if _evidence_matches_task_gate(item, task=task, metadata=metadata)]


def _evidence_matches_task_gate(item: EvidenceItem, *, task: ReportTask, metadata: dict[str, Any]) -> bool:
    item_metadata = item.metadata_json or {}
    task_id = str(task.task_id or "")
    if _norm(item_metadata.get("task_id")) == _norm(task_id):
        return True
    if item.document is not None and _norm(item.document.batch_id) == _norm(task_id):
        return True
    for link in item.claim_links:
        if link.claim is not None and _norm(link.claim.task_id) == _norm(task_id):
            return True

    company_match = _evidence_company_matches(item, task=task, metadata=metadata)
    period_match = _evidence_period_matches(item, task=task, metadata=metadata)
    if _norm(task.period or metadata.get("period")):
        return company_match and period_match
    return company_match


def _evidence_company_matches(item: EvidenceItem, *, task: ReportTask, metadata: dict[str, Any]) -> bool:
    expected_values = [
        task.symbol,
        metadata.get("symbol"),
        metadata.get("company_name"),
        metadata.get("company_symbol"),
    ]
    if task.company_id is not None and item.company_id == task.company_id:
        return True
    company = item.company
    item_values = [
        company.name if company else "",
        company.symbol if company else "",
        *((company.aliases or []) if company else []),
        (item.metadata_json or {}).get("symbol"),
        (item.metadata_json or {}).get("company_name"),
        (item.metadata_json or {}).get("company_symbol"),
    ]
    normalized_expected = [_norm(value) for value in expected_values if _norm(value)]
    normalized_items = [_norm(value) for value in item_values if _norm(value)]
    return any(
        expected in item_value or item_value in expected
        for expected in normalized_expected
        for item_value in normalized_items
    )


def _evidence_period_matches(item: EvidenceItem, *, task: ReportTask, metadata: dict[str, Any]) -> bool:
    expected = _norm(task.period or metadata.get("period"))
    if not expected:
        return True
    item_metadata = item.metadata_json or {}
    values = [
        item.document.report_period if item.document else "",
        item_metadata.get("period"),
        item_metadata.get("report_period"),
        item_metadata.get("fiscal_period"),
    ]
    return any(_norm(value) == expected for value in values if _norm(value))


def _evidence_gate_row(item: EvidenceItem) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "source_type": item.source_type,
        "trust_level": item.trust_level,
        "title": item.title,
    }


def _evidence_gate_blocking_reasons(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if not coverage.get("evidence_ready"):
        reasons.append(
            {
                "type": "no_evidence",
                "label": "缺少可用证据",
                "description": "当前任务没有命中公司和期间匹配的证据，不能生成正式研报。",
            }
        )
    missing_sources = list(coverage.get("missing_sources") or [])
    if missing_sources:
        reasons.append(
            {
                "type": "missing_required_source",
                "label": "权威来源缺口",
                "description": "当前任务缺少权威来源：" + "、".join(missing_sources),
                "sources": missing_sources,
            }
        )
    return reasons


def _evidence_gate_summary(
    *,
    coverage: dict[str, Any],
    blocking_reasons: list[dict[str, Any]],
    blocked: bool,
) -> str:
    if blocked:
        return "生成已暂停：证据覆盖不足，请先补充采集或导入权威资料。"
    if blocking_reasons:
        return "证据覆盖存在缺口，当前未强制拦截，任务继续生成；请在复核页补齐证据。"
    return coverage.get("summary") or "生成前证据门禁通过。"


def _evidence_gate_actions(coverage: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for gap in coverage.get("gaps") or []:
        gap_type = str(gap.get("type") or "")
        if gap_type == "no_candidates":
            actions.append({"label": "创建采集批次", "view": "ingestion", "reason": str(gap.get("description") or "")})
        elif gap_type == "source_gap":
            actions.append({"label": "检查数据源配置", "view": "datasources", "reason": str(gap.get("description") or "")})
        elif gap_type in {"no_hits", "retrieval_failed"}:
            actions.append({"label": "去证据库核对", "view": "evidence", "reason": str(gap.get("description") or "")})
    if not actions:
        actions.append({"label": "进入证据复核", "view": "evidence", "reason": "证据已命中，建议生成前核对原文。"})
    return actions


def serialize_event(event: ReportTaskEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "task_id": event.task_id,
        "stage": event.stage,
        "status": event.status,
        "message": event.message,
        "metadata": event.metadata_json or {},
        "created_at": _dt(event.created_at),
    }


def serialize_artifact(artifact: ReportArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "artifact_type": artifact.artifact_type,
        "path": artifact.path,
        "url": artifact.url,
        "created_at": _dt(artifact.created_at),
    }


def build_quality_diagnostics(task: ReportTask, llm_runs: list[LLMRun]) -> dict[str, Any]:
    """Build a compact task-level quality diagnosis for the workbench detail view."""

    metadata = task.metadata_json or {}
    quality_result = metadata.get("quality_result") if isinstance(metadata.get("quality_result"), dict) else {}
    quality_report = _dict_path(quality_result, "quality_report")
    llm_quality_review = _dict_path(quality_result, "llm_quality_review")
    delivery_gate = _dict_path(quality_result, "delivery_gate")
    remediation_plan = _dict_path(quality_result, "remediation_plan")
    top_issues = _normalize_quality_issues(_top_quality_issues(quality_result))
    llm_payloads = [_compact_llm_run(item) for item in llm_runs]
    role_runs = _quality_role_runs(llm_payloads)
    categories = _quality_failure_categories(
        delivery_gate=delivery_gate,
        quality_report=quality_report,
        llm_quality_review=llm_quality_review,
        remediation_plan=remediation_plan,
        top_issues=top_issues,
        runs=llm_payloads,
    )
    return {
        "delivery_pass": delivery_gate.get("delivery_pass"),
        "objective_pass": delivery_gate.get("objective_pass", quality_report.get("objective_pass")),
        "llm_review_pass": delivery_gate.get("llm_review_pass", llm_quality_review.get("llm_review_pass")),
        "quality_score": task.quality_score if task.quality_score is not None else _quality_score_from_result(quality_result),
        "failed_sections": _string_list(
            remediation_plan.get("failed_sections")
            or quality_report.get("failed_sections")
            or llm_quality_review.get("failed_sections")
        )[:8],
        "top_issues": top_issues,
        "required_fixes": _string_list(
            remediation_plan.get("required_fixes")
            or remediation_plan.get("fixes")
            or remediation_plan.get("actions")
        )[:8],
        "failure_categories": categories,
        "writer": role_runs.get("final_answer") or role_runs.get("writer"),
        "verifier": role_runs.get("verifier"),
        "quality_gate": role_runs.get("quality_gate"),
        "agent_runs": [run for run in llm_payloads if str(run.get("prompt_key") or "").startswith("agent.")],
        "llm_run_count": len(llm_payloads),
        "failed_llm_run_count": sum(1 for run in llm_payloads if run.get("status") == "failed"),
    }


def _compact_llm_run(item: LLMRun) -> dict[str, Any]:
    payload = serialize_llm_run(item)
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "run_id": payload.get("run_id"),
        "prompt_key": payload.get("prompt_key"),
        "model_role": payload.get("model_role"),
        "model_name": payload.get("model_name"),
        "status": payload.get("status"),
        "attempt_count": payload.get("attempt_count"),
        "fallback_used": payload.get("fallback_used"),
        "schema_valid": payload.get("schema_valid"),
        "latency_ms": payload.get("latency_ms"),
        "cost_usd": payload.get("cost_usd"),
        "created_at": payload.get("created_at"),
        "summary": _llm_output_summary(output),
        "output_keys": output.get("output_keys") if isinstance(output.get("output_keys"), list) else [],
        "metadata": {
            "source": metadata.get("source"),
            "route_profile": metadata.get("route_profile"),
            "memory_used": metadata.get("memory_used"),
            "quality_feedback_used": metadata.get("quality_feedback_used"),
            "model_enabled": metadata.get("model_enabled"),
            "promptops_bound": metadata.get("promptops_bound"),
        },
        "error_message": payload.get("error_message"),
    }


def _quality_role_runs(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    roles: dict[str, dict[str, Any]] = {}
    for run in runs:
        role = str(run.get("model_role") or "").strip()
        prompt_key = str(run.get("prompt_key") or "").strip()
        if role and role not in roles:
            roles[role] = run
        if prompt_key == "report_quality_gate":
            roles["quality_gate"] = run
    return roles


def _quality_failure_categories(
    *,
    delivery_gate: dict[str, Any],
    quality_report: dict[str, Any],
    llm_quality_review: dict[str, Any],
    remediation_plan: dict[str, Any],
    top_issues: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, int]:
    categories: dict[str, int] = {}
    for issue in top_issues:
        category = _string(issue.get("category") or issue.get("severity") or "未分类")
        categories[category] = categories.get(category, 0) + 1
    if delivery_gate.get("objective_pass") is False or quality_report.get("objective_pass") is False:
        categories["客观规则未通过"] = categories.get("客观规则未通过", 0) + 1
    if delivery_gate.get("llm_review_pass") is False or llm_quality_review.get("llm_review_pass") is False:
        categories["LLM复核未通过"] = categories.get("LLM复核未通过", 0) + 1
    for section in _string_list(remediation_plan.get("failed_sections")):
        categories[f"章节需修复:{section}"] = categories.get(f"章节需修复:{section}", 0) + 1
    for run in runs:
        status = run.get("status")
        if status == "failed":
            role = _string(run.get("model_role") or run.get("prompt_key") or "unknown")
            categories[f"模型运行失败:{role}"] = categories.get(f"模型运行失败:{role}", 0) + 1
        elif status == "skipped":
            role = _string(run.get("model_role") or run.get("prompt_key") or "unknown")
            categories[f"模型跳过:{role}"] = categories.get(f"模型跳过:{role}", 0) + 1
    return dict(sorted(categories.items(), key=lambda item: item[1], reverse=True)[:8])


def _normalize_quality_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for issue in issues:
        message = _string(issue.get("message") or issue.get("detail") or issue.get("reason"))
        if not message:
            continue
        normalized.append(
            {
                "severity": _string(issue.get("severity") or "warning"),
                "category": _string(issue.get("category") or ""),
                "message": message,
            }
        )
    return normalized[:5]


def _llm_output_summary(output: dict[str, Any]) -> str:
    summary = output.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    output_summary = output.get("output_summary")
    if isinstance(output_summary, dict):
        for key in ("summary", "decision", "finding", "message"):
            value = output_summary.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if output_summary:
            return json.dumps(output_summary, ensure_ascii=False, sort_keys=True)[:240]
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_string(item) for item in value if _string(item)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "_", value).strip("_")
    return safe or f"task_{uuid.uuid4().hex[:8]}"


def _normalize_search_engines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [part.strip() for part in str(value).split(",") if part.strip()]
    return []


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _norm(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def _dict_path(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _quality_score_from_result(result: dict[str, Any]) -> float | None:
    candidates = [
        _dict_path(result, "quality_report").get("total_score"),
        _dict_path(result, "llm_quality_review").get("total_score"),
    ]
    for value in candidates:
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _compact_quality_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "quality_report": _dict_path(result, "quality_report"),
        "llm_quality_review": _dict_path(result, "llm_quality_review"),
        "delivery_gate": _dict_path(result, "delivery_gate"),
        "remediation_plan": _dict_path(result, "remediation_plan"),
        "top_quality_issues": _top_quality_issues(result),
    }


def _top_quality_issues(result: dict[str, Any]) -> list[dict[str, Any]]:
    issues = result.get("top_quality_issues") if isinstance(result, dict) else []
    if not issues:
        issues = _dict_path(result, "delivery_gate").get("top_issues")
    if not isinstance(issues, list):
        return []
    return [issue for issue in issues[:5] if isinstance(issue, dict)]


class QualityGateTraceBackend:
    """Deterministic backend used to make quality-gate observability queryable."""

    name = "quality-gate-trace"

    def generate_structured(self, prompt: str, schema: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        gate = kwargs.get("delivery_gate") if isinstance(kwargs.get("delivery_gate"), dict) else {}
        issues = kwargs.get("top_quality_issues") if isinstance(kwargs.get("top_quality_issues"), list) else []
        delivery_pass = gate.get("delivery_pass") is True
        summary = "质量门禁通过" if delivery_pass else "质量门禁未通过"
        if issues:
            first = issues[0]
            if isinstance(first, dict) and first.get("message"):
                summary = f"{summary}: {first['message']}"
        return {
            "delivery_pass": delivery_pass,
            "issue_count": len(issues),
            "summary": summary,
        }


def _report_links(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    links: dict[str, Any] = {}
    for artifact in artifacts:
        artifact_type = artifact.get("artifact_type")
        url = artifact.get("url")
        path = artifact.get("path")
        if artifact_type == "html":
            links["html_web_url"] = url
            if path:
                try:
                    links["html_file_url"] = Path(str(path)).resolve().as_uri()
                except ValueError:
                    pass
        elif artifact_type == "markdown":
            links["markdown_web_url"] = url
        elif artifact_type == "json":
            links["json_web_url"] = url
    return links
