"""DB-backed report task lifecycle service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
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
from src.agents.base_agent import AgentTask
from src.agents.verifier_agent import VerifierAgent
from src.data.company_universe import infer_market_from_symbol, resolve_company_identity
from src.data.canonical_metrics import write_canonical_metrics_artifact
from src.data.evidence_intake_gate import PERIOD_GATED_SOURCE_TYPES, record_period_status
from src.data.official_evidence_archive import build_official_evidence_artifacts
from src.data.official_evidence_backfill import execute_official_evidence_backfill
from src.data.source_authority import grade_source_authority
from src.db.init_db import init_db
from src.db.models import (
    ClaimEvidence,
    Company,
    EvidenceItem,
    LLMRun,
    PromptTemplate,
    ReportArtifact,
    ReportTask,
    ReportTaskEvent,
    ToolRun,
    Workspace,
)
from src.db.session import create_engine_for_url
from src.llm.harness import serialize_llm_run
from src.llm.harness import LLMHarness
from src.models.model_adapter import ModelAdapter
from src.evaluation.evidence_retrieval_attribution import write_evidence_retrieval_attribution
from src.evaluation.delivery_pipeline import run_delivery_quality_pipeline
from src.evaluation.section_repair import repair_failed_sections_for_outputs
from src.evaluation.section_evidence_pack import build_section_evidence_packs
from src.evaluation.section_verification import write_section_verification
from src.rag.retrieval_diagnostics import build_retrieval_coverage
from src.report.citation_manager import build_citation_artifacts
from src.report.compliance_disclosure import append_compliance_disclosures
from src.report.html_report_generator import render_professional_html_report
from src.runtime.report_run_state import (
    InvalidReportTransition,
    ReportLifecycleStatus,
    apply_report_transition,
    build_report_run_state,
    resolve_lifecycle_status,
    restore_report_transition,
)
from src.runtime.langgraph_report_runtime import (
    CallbackReportGraphHandlers,
    LangGraphReportRuntime,
    ReportGraphState,
    project_run_state_patch,
)
from src.runtime.run_manifest import commit_run_artifacts, validate_run_manifest
from src.services.artifact_importer import ArtifactImporter
from src.services.datasource_service import DataSourceService
from src.services.entity_service import EntityService
from src.utils.config import load_config
from src.utils.periods import latest_completed_period


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
        langgraph_runtime_enabled: bool = True,
        runtime_checkpoint_path: str | Path | None = None,
        engine: Engine | None = None,
        section_repair_callback_factory: Callable[[str, dict[str, Any]], Callable[[dict[str, Any]], dict[str, Any]] | None] | None = None,
    ) -> None:
        self.database_url = database_url
        self.output_root = Path(output_root)
        self.report_root = Path(report_root)
        self.config_path = config_path
        self.memory_root = Path(memory_root)
        self.mode = mode
        self._uses_production_orchestrator = orchestrator_factory is None
        self.orchestrator_factory = orchestrator_factory or MultiAgentOrchestrator
        self.quality_runner = quality_runner or run_delivery_quality_pipeline
        self.langgraph_runtime_enabled = bool(langgraph_runtime_enabled)
        self.runtime_checkpoint_path = Path(runtime_checkpoint_path) if runtime_checkpoint_path else self.output_root / "runtime_checkpoints.sqlite"
        self._langgraph_runtime: LangGraphReportRuntime | None = None
        self._runtime_lock = threading.Lock()
        self._engine = engine
        self._session_factory: sessionmaker[Session] | None = None
        self._init_lock = threading.Lock()
        self.section_repair_callback_factory = section_repair_callback_factory
        self._enable_model_section_repair = orchestrator_factory is None or section_repair_callback_factory is not None

    def recover_stale_running_tasks(self, *, max_age_minutes: int = 60) -> list[str]:
        """Mark abandoned in-process tasks as timed out after a service restart."""

        cutoff = _utc_now() - timedelta(minutes=max(1, int(max_age_minutes)))
        recovered: list[str] = []
        with self.session() as session:
            tasks = list(
                session.scalars(
                    select(ReportTask).where(
                        ReportTask.status == "running",
                        ReportTask.started_at.is_not(None),
                        ReportTask.started_at < cutoff,
                    )
                ).all()
            )
            for task in tasks:
                previous_stage = str(task.current_stage or "running")
                self._transition_task(task, "timeout", reason="stale_running_task_recovered_on_startup")
                task.finished_at = _utc_now()
                task.error_message = "服务重启后发现该任务已失去执行进程，可从 LangGraph 断点重试。"
                metadata = dict(task.metadata_json or {})
                metadata["runtime_failure"] = {
                    "error_type": "OrphanedRuntime",
                    "message": task.error_message,
                    "checkpoint_available": self.langgraph_runtime_enabled,
                    "previous_stage": previous_stage,
                }
                task.metadata_json = metadata
                session.add(
                    ReportTaskEvent(
                        task_id=task.task_id,
                        stage="timeout",
                        status="timeout",
                        message=task.error_message,
                        metadata_json={
                            "reason": "stale_running_task_recovered_on_startup",
                            "previous_stage": previous_stage,
                            "checkpoint_available": self.langgraph_runtime_enabled,
                        },
                    )
                )
                recovered.append(task.task_id)
            session.commit()
        return recovered

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = _normalize_task_identity_payload(payload)
        symbol = str(payload.get("symbol") or "AAPL").strip().upper()
        period = str(payload.get("period") or latest_completed_period()).strip().upper()
        if not re.fullmatch(r"(?:FY\d{4}|\d{4}Q[1-4])", period):
            raise ValueError("period must use FY2025 or 2026Q2 format")
        task_id = self._new_task_id(payload.get("task_id"))
        report_type = str(payload.get("report_type") or "equity_research")
        metadata = self._build_task_metadata(task_id=task_id, payload=payload, symbol=symbol, period=period)

        with self.session() as session:
            workspace_id, company_id = _resolve_task_bindings(session, payload=payload, symbol=symbol)
            if company_id is not None:
                bound_company = session.get(Company, company_id)
                if bound_company is not None:
                    metadata["company_name"] = bound_company.name
            task = ReportTask(
                task_id=task_id,
                workspace_id=workspace_id,
                company_id=company_id,
                symbol=symbol,
                period=period,
                report_type=report_type,
                status="queued",
                current_stage="queued",
                metadata_json=metadata,
            )
            self._transition_task(task, "queued", reason="task_created")
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
            _repair_persisted_task_identity(session, task)
            if task.status == "running":
                raise ReportTaskConflict(f"Task {task_id} is already running")
            if task.status not in {"queued", "failed", "timeout", "quality_failed"}:
                return self.serialize_task(task)

            if resolve_lifecycle_status(task) != "queued":
                self._transition_task(task, "queued", reason="implicit_retry_before_run")
            self._transition_task(task, "evidence_checking", reason="report_run_started")
            task.started_at = task.started_at or _utc_now()
            task.error_message = None
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="runtime_start",
                    status="running",
                    message="研报运行开始",
                    metadata_json={"runtime": "langgraph" if self.langgraph_runtime_enabled else "legacy"},
                )
            )
            session.commit()
            metadata = dict(task.metadata_json or {})

        try:
            if self.langgraph_runtime_enabled:
                initial_state = self.get_task(task_id)["run_state"]
                initial_state["request_id"] = str(metadata.get("request_id") or task_id)
                initial_state["run_id"] = str(metadata.get("run_id") or task_id)
                runtime_result = self._get_langgraph_runtime().invoke(initial_state, thread_id=task_id)
                self._record_runtime_result(task_id, runtime_result)
            else:
                self._run_task_legacy_pipeline(task_id=task_id, metadata=metadata)
        except Exception as exc:
            with self.session() as session:
                task = self._get_task_for_update(session, task_id)
                lifecycle = resolve_lifecycle_status(task)
                if lifecycle in {"evidence_checking", "generating", "quality_checking"}:
                    self._transition_task(task, "failed", reason=type(exc).__name__)
                metadata = dict(task.metadata_json or {})
                metadata["runtime_failure"] = {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "checkpoint_available": self.langgraph_runtime_enabled,
                }
                task.metadata_json = metadata
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

    def get_runtime_checkpoint(self, task_id: str) -> dict[str, Any]:
        self.get_task(task_id)
        return self._get_langgraph_runtime().snapshot(thread_id=task_id)

    def resume_runtime(self, task_id: str, *, decision: Any) -> dict[str, Any]:
        self.get_task(task_id)
        result = self._get_langgraph_runtime().resume(thread_id=task_id, decision=decision)
        self._record_runtime_result(task_id, result)
        return {"task": self.get_task(task_id), "runtime": result, "checkpoint": self.get_runtime_checkpoint(task_id)}

    def retry_runtime_checkpoint(self, task_id: str) -> dict[str, Any]:
        self.get_task(task_id)
        result = self._get_langgraph_runtime().retry_from_checkpoint(thread_id=task_id)
        self._record_runtime_result(task_id, result)
        return {"task": self.get_task(task_id), "runtime": result, "checkpoint": self.get_runtime_checkpoint(task_id)}

    def _get_langgraph_runtime(self) -> LangGraphReportRuntime:
        if not self.langgraph_runtime_enabled:
            raise ReportTaskConflict("LangGraph report runtime is disabled")
        if self._langgraph_runtime is not None:
            return self._langgraph_runtime
        with self._runtime_lock:
            if self._langgraph_runtime is None:
                handlers = CallbackReportGraphHandlers(
                    evidence_callback=self._graph_evidence_node,
                    generation_callback=self._graph_generation_node,
                    quality_callback=self._graph_quality_node,
                    finalize_callback=self._graph_finalize_node,
                    review_callback=self._graph_review_node,
                    official_evidence_backfill_callback=self._graph_official_evidence_backfill_node,
                    build_canonical_metrics_callback=self._graph_build_canonical_metrics_node,
                    build_section_evidence_packs_callback=self._graph_build_section_evidence_packs_node,
                    verify_sections_callback=self._graph_verify_sections_node,
                    repair_failed_sections_callback=self._graph_repair_failed_sections_node,
                    inspect_agent_execution_callback=self._graph_inspect_agent_execution_node,
                    planning_callback=lambda state: self._graph_static_agent_phase_node(state, "planning"),
                    research_callback=lambda state: self._graph_static_agent_phase_node(state, "research"),
                    normalize_evidence_callback=lambda state: self._graph_static_agent_phase_node(state, "normalize_evidence"),
                    analyze_callback=lambda state: self._graph_static_agent_phase_node(state, "analyze"),
                    verify_report_callback=self._graph_verify_report_node,
                )
                self._langgraph_runtime = LangGraphReportRuntime(
                    handlers,
                    checkpoint_path=self.runtime_checkpoint_path,
                )
        return self._langgraph_runtime

    def _graph_evidence_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if resolve_lifecycle_status(task) in {"failed", "timeout"}:
                restore_report_transition(task, "evidence_checking")
                task.error_message = None
                task.finished_at = None
                session.commit()
        self.run_evidence_gate(task_id)
        return self._current_run_state_patch(task_id)

    def _graph_official_evidence_backfill_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        summary = self._run_official_evidence_backfill(task_id)
        metadata = self._task_metadata(task_id)
        output_dir = Path(str(metadata.get("output_dir") or ""))
        _sync_task_retrieval_curated_dir(output_dir)
        evidence_path = output_dir / "evidence.json"
        if evidence_path.is_file():
            self.import_artifacts(task_id)
        self._record_runtime_stage(
            task_id,
            stage="official_evidence_backfill",
            status="success" if summary.get("status") in {"not_required", "completed", "remote_disabled"} else "warning",
            message="官方证据补齐检查完成" if summary.get("status") != "failed" else "官方证据补齐执行失败",
            metadata=summary,
        )
        return self._current_run_state_patch(task_id)

    def _graph_build_canonical_metrics_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        summary = self._refresh_canonical_metrics(task_id)
        self._commit_run_artifacts(task_id, ["evidence", "canonical_metrics"])
        self._update_runtime_metadata(task_id, "canonical_metrics", summary)
        self._record_runtime_stage(
            task_id,
            stage="build_canonical_metrics",
            status="success",
            message="正式指标候选池已建立",
            metadata=summary,
        )
        return self._current_run_state_patch(task_id)

    def _graph_build_section_evidence_packs_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        metadata = self._task_metadata(task_id)
        output_dir = Path(str(metadata.get("output_dir") or ""))
        artifact = build_section_evidence_packs(output_dir)
        self._commit_run_artifacts(task_id, ["claims", "section_evidence_packs"])
        summary = _build_section_pack_manifest(output_dir, artifact=artifact)
        self._update_runtime_metadata(task_id, "section_evidence_packs", summary)
        self._record_runtime_stage(
            task_id,
            stage="build_section_evidence_packs",
            status="success",
            message="章节证据包索引已建立",
            metadata=summary,
        )
        return self._current_run_state_patch(task_id)

    def _graph_generation_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            lifecycle = resolve_lifecycle_status(task)
            if lifecycle in {"failed", "timeout"}:
                restore_report_transition(task, "generating")
            else:
                self._transition_task(task, "generating", reason="evidence_gate_passed")
            task.error_message = None
            task.finished_at = None
            metadata = dict(task.metadata_json or {})
            evidence_gate = metadata.get("pre_generation_evidence_gate")
            evidence_gate = evidence_gate if isinstance(evidence_gate, dict) else {}
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="orchestrator",
                    status="running",
                    message="研报生成流程开始",
                    metadata_json={"evidence_gate_status": evidence_gate.get("status"), "runtime": "langgraph"},
                )
            )
            session.commit()
        if self.orchestrator_factory is MultiAgentOrchestrator and str(metadata.get("execution_mode") or "static") == "static":
            self._run_orchestrator_instance(
                task_id=task_id,
                metadata=metadata,
                stop_after_phase="final_answer",
                resume_from_phase_artifacts=True,
            )
        else:
            self._run_orchestrator(task_id=task_id, metadata=metadata)
        self._enhance_artifacts_with_task_evidence(task_id)
        self._refresh_canonical_metrics(task_id)
        refreshed_metadata = self._task_metadata(task_id)
        refreshed_output_dir = Path(str(refreshed_metadata.get("output_dir") or ""))
        build_section_evidence_packs(refreshed_output_dir)
        self.import_artifacts(task_id)
        self._commit_run_artifacts(
            task_id,
            ["evidence", "canonical_metrics", "claims", "section_evidence_packs", "citations", "report"],
        )
        return self._current_run_state_patch(task_id)

    def _graph_verify_report_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        metadata = self._task_metadata(task_id)
        if self.orchestrator_factory is not MultiAgentOrchestrator or str(metadata.get("execution_mode") or "static") != "static":
            return self._current_run_state_patch(task_id)
        output_dir = Path(str(metadata.get("output_dir") or ""))
        report_dir = Path(str(metadata.get("report_dir") or ""))
        claims = _read_json_list(output_dir / "claims.json")
        evidence = _read_json_list(output_dir / "evidence.json")
        markdown = (report_dir / "report.md").read_text(encoding="utf-8") if (report_dir / "report.md").exists() else ""
        adapter = _build_role_model_adapter(
            config_path=self.config_path,
            role="verifier",
            execution_tier=str(metadata.get("execution_tier") or "delivery"),
        )
        result = VerifierAgent(model=adapter if adapter.api_key else None).execute_task(
            AgentTask(
                task_id="task_005_verifier",
                task_type="verifier",
                description="Verify the persisted report artifact.",
                parameters={
                    "claims": claims,
                    "markdown": markdown,
                    "evidence_records": evidence,
                    "charts": _read_json_list(output_dir / "charts.json"),
                    "tables": _read_json_list(output_dir / "tables.json"),
                    "valuation": _read_json_object(output_dir / "valuation_model.json"),
                    "expected_symbol": metadata.get("symbol"),
                    "period": metadata.get("period"),
                },
            )
        )
        verification = dict(result.output.get("verification_report") or {})
        (output_dir / "verification_report.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        self._record_runtime_stage(
            task_id,
            stage="verify_report",
            status="success" if verification.get("passed") else "warning",
            message="独立报告校验节点完成",
            metadata={
                "passed": bool(verification.get("passed")),
                "error_count": int(verification.get("error_count") or len(verification.get("errors") or [])),
                "warning_count": int(verification.get("warning_count") or len(verification.get("warnings") or [])),
                "llm_used": bool(verification.get("llm_used")),
            },
        )
        return self._current_run_state_patch(task_id)

    def _graph_static_agent_phase_node(self, state: ReportGraphState, phase: str) -> dict[str, Any]:
        task_id = str(state["task_id"])
        metadata = self._task_metadata(task_id)
        if self.orchestrator_factory is not MultiAgentOrchestrator or str(metadata.get("execution_mode") or "static") != "static":
            return self._current_run_state_patch(task_id)
        result = self._run_orchestrator_instance(
            task_id=task_id,
            metadata=metadata,
            stop_after_phase=phase,
            resume_from_phase_artifacts=True,
        )
        if phase in {"research", "normalize_evidence"}:
            self._record_datasource_health(task_id=task_id, output_dir=Path(str(metadata.get("output_dir") or "")))
        self._record_runtime_stage(
            task_id,
            stage=phase,
            status="success",
            message=f"Agent phase {phase} completed",
            metadata={"checkpoint": result.get("checkpoint"), "result_keys": sorted(result)},
        )
        return self._current_run_state_patch(task_id)

    def _graph_inspect_agent_execution_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        metadata = self._task_metadata(task_id)
        output_dir = Path(str(metadata.get("output_dir") or ""))
        if self.orchestrator_factory is not MultiAgentOrchestrator:
            # Compatibility path for injected legacy orchestrators that still
            # create analysis artifacts inside the generation callback.
            self._refresh_canonical_metrics(task_id)
            section_packs = build_section_evidence_packs(output_dir)
            self._update_runtime_metadata(
                task_id,
                "section_evidence_packs",
                _build_section_pack_manifest(output_dir, artifact=section_packs),
            )
            self._commit_run_artifacts(
                task_id,
                ["evidence", "canonical_metrics", "claims", "section_evidence_packs", "citations", "report"],
            )
        summary = _build_generation_execution_summary(output_dir)
        datasource_health = self._record_datasource_health(task_id=task_id, output_dir=output_dir)
        summary["datasource_health"] = datasource_health
        self._update_runtime_metadata(task_id, "generation_execution", summary)
        self._record_runtime_stage(
            task_id,
            stage="inspect_agent_execution",
            status="success" if summary.get("status") == "ready" else "warning",
            message="Agent 与工具执行轨迹检查完成",
            metadata=summary,
        )
        return self._current_run_state_patch(task_id)

    def _record_datasource_health(self, *, task_id: str, output_dir: Path) -> dict[str, Any]:
        search_meta = _read_json_object(output_dir / "search_meta.json")
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            workspace_id = task.workspace_id
        return DataSourceService(session_factory=self.session).record_search_run(
            search_meta=search_meta,
            task_id=task_id,
            workspace_id=workspace_id,
        )

    def _graph_verify_sections_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        metadata = self._task_metadata(task_id)
        output_dir = Path(str(metadata.get("output_dir") or ""))
        report_dir = Path(str(metadata.get("report_dir") or ""))
        summary = _build_section_verification_manifest(output_dir=output_dir, report_dir=report_dir)
        self._update_runtime_metadata(task_id, "section_verification", summary)
        self._record_runtime_stage(
            task_id,
            stage="verify_sections",
            status="success" if not summary.get("failed_sections") else "warning",
            message="章节结构合同检查完成",
            metadata=summary,
        )
        return self._current_run_state_patch(task_id)

    def _graph_repair_failed_sections_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        metadata = self._task_metadata(task_id)
        section_verification = dict(_dict_path(metadata, "report_runtime").get("section_verification") or {})
        failed_sections = list(section_verification.get("failed_sections") or [])
        output_dir = Path(str(metadata.get("output_dir") or ""))
        report_dir = Path(str(metadata.get("report_dir") or ""))
        repair_callback = self._build_section_repair_callback(task_id=task_id, metadata=metadata)
        repair = repair_failed_sections_for_outputs(
            output_dir=output_dir,
            report_dir=report_dir,
            section_verification=_read_json_object(output_dir / "section_verification.json") or section_verification,
            repair_callback=repair_callback,
        )
        verification = _build_section_verification_manifest(output_dir=output_dir, report_dir=report_dir)
        self._commit_run_artifacts(task_id, ["report", "section_verification"])
        self._update_runtime_metadata(task_id, "section_verification", verification)
        summary = {
            "schema_version": "section_repair_runtime.v1",
            "status": repair.get("status", "unknown"),
            "failed_section_count_before": len(failed_sections),
            "failed_sections_before": failed_sections,
            "failed_section_count_after": len(verification.get("failed_sections") or []),
            "failed_sections_after": list(verification.get("failed_sections") or []),
            "repaired": bool(repair.get("repaired", False)),
            "repair_strategy": str(repair.get("repair_strategy") or "deterministic_section_rewrite"),
            "model_status": str(repair.get("model_status") or "unavailable"),
            "llm_run_ids": [
                str(item.get("llm_run_id"))
                for item in repair.get("attempts") or []
                if isinstance(item, dict) and item.get("llm_run_id")
            ],
            "source_files": {
                "section_repair": str(output_dir / "section_repair.json"),
                "section_verification": str(output_dir / "section_verification.json"),
            },
        }
        self._update_runtime_metadata(task_id, "section_repair", summary)
        self._record_runtime_stage(
            task_id,
            stage="repair_failed_sections",
            status="success" if not summary.get("failed_sections_after") else "warning",
            message="章节返工调度检查完成",
            metadata=summary,
        )
        return self._current_run_state_patch(task_id)

    def _build_section_repair_callback(
        self,
        *,
        task_id: str,
        metadata: dict[str, Any],
    ) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
        if self.section_repair_callback_factory is not None:
            return self.section_repair_callback_factory(task_id, metadata)
        if not self._enable_model_section_repair:
            return None
        adapter = _build_role_model_adapter(
            config_path=self.config_path,
            role="final_answer",
            execution_tier=str(metadata.get("execution_tier") or "delivery"),
        )
        if not adapter.api_key:
            return None
        active_prompt = self._active_prompt("report_section_repair")
        backend = SectionRepairModelBackend(adapter)
        harness = LLMHarness(
            session_factory=self.session,
            backend=backend,
            max_retries=1,
            timeout_seconds=min(float(adapter.timeout or 90), 120.0),
        )

        def repair(payload: dict[str, Any]) -> dict[str, Any]:
            result = harness.run_prompt(
                prompt_key="report_section_repair",
                input=payload,
                schema={
                    "type": "object",
                    "required": ["section_markdown"],
                    "properties": {"section_markdown": {"type": "string"}},
                },
                model_role="section_repair",
                task_id=task_id,
                prompt=(active_prompt or {}).get("content") or _DEFAULT_SECTION_REPAIR_PROMPT,
                prompt_version_id=(active_prompt or {}).get("version_id"),
                metadata={
                    "source": "langgraph_section_repair",
                    "section_key": payload.get("section_key"),
                    "route_profile": adapter.route_profile,
                },
            )
            output = dict(result.output)
            output["llm_run_id"] = result.run_id
            return output

        return repair

    def _graph_quality_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if resolve_lifecycle_status(task) in {"failed", "timeout"}:
                restore_report_transition(task, "quality_checking")
                task.error_message = None
                task.finished_at = None
                session.commit()
        self.run_quality_gate(task_id)
        self._validate_run_manifest(task_id)
        self._refresh_retrieval_attribution(task_id)
        self.import_artifacts(task_id)
        return self._current_run_state_patch(task_id)

    def _commit_run_artifacts(self, task_id: str, artifact_names: list[str]) -> dict[str, Any]:
        metadata = self._task_metadata(task_id)
        manifest = commit_run_artifacts(
            Path(str(metadata.get("output_dir") or "")),
            Path(str(metadata.get("report_dir") or "")),
            artifact_names,
        )
        self._update_runtime_metadata(task_id, "run_manifest", _run_manifest_summary(manifest))
        return manifest

    def _validate_run_manifest(self, task_id: str) -> dict[str, Any]:
        metadata = self._task_metadata(task_id)
        manifest = validate_run_manifest(
            Path(str(metadata.get("output_dir") or "")),
            Path(str(metadata.get("report_dir") or "")),
        )
        self._update_runtime_metadata(task_id, "run_manifest", _run_manifest_summary(manifest))
        return manifest

    def _task_metadata(self, task_id: str) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            return dict(task.metadata_json or {})

    def _refresh_canonical_metrics(self, task_id: str) -> dict[str, Any]:
        metadata = self._task_metadata(task_id)
        output_dir = Path(str(metadata.get("output_dir") or ""))
        financial_metrics = _read_json_any(output_dir / "financial_metrics.json", default={})
        tables = _read_json_any(output_dir / "tables.json", default=[])
        evidence_records = _read_json_any(output_dir / "evidence.json", default=[])
        artifact = write_canonical_metrics_artifact(
            output_dir,
            financial_metrics=financial_metrics,
            tables=tables,
            evidence_records=evidence_records,
            symbol=str(metadata.get("symbol") or ""),
            period=str(metadata.get("period") or ""),
        )
        summary = _canonical_metrics_summary(output_dir=output_dir, artifact=artifact)
        self._update_runtime_metadata(task_id, "canonical_metrics", summary)
        return summary

    def _update_runtime_metadata(self, task_id: str, key: str, value: dict[str, Any]) -> None:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            runtime = dict(metadata.get("report_runtime") or {})
            runtime[key] = value
            metadata["report_runtime"] = runtime
            task.metadata_json = metadata
            session.commit()

    def _record_runtime_stage(
        self,
        task_id: str,
        *,
        stage: str,
        status: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.session() as session:
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage=stage,
                    status=status,
                    message=message,
                    metadata_json=metadata or {},
                )
            )
            session.commit()

    def _graph_finalize_node(self, state: ReportGraphState) -> dict[str, Any]:
        task_id = str(state["task_id"])
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if resolve_lifecycle_status(task) in {"failed", "timeout"}:
                restore_report_transition(task, "quality_checking")
            metadata = dict(task.metadata_json or {})
            quality_result = metadata.get("quality_result")
            quality_result = quality_result if isinstance(quality_result, dict) else {}
            delivery_pass = _dict_path(quality_result, "delivery_gate").get("delivery_pass")
            target: ReportLifecycleStatus = "generation_completed" if delivery_pass is True else "quality_blocked"
            self._transition_task(task, target, reason="quality_gate_completed")
            task.finished_at = _utc_now()
            task.error_message = None
            task.quality_score = _quality_score_from_result(quality_result)
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage=task.current_stage or task.status,
                    status=task.status,
                    message="Report task completed" if delivery_pass is True else "Report generated but quality gate failed",
                    metadata_json={
                        "artifact_count": len(task.artifacts),
                        "delivery_pass": delivery_pass,
                        "quality_score": task.quality_score,
                        "runtime": "langgraph",
                    },
                )
            )
            session.commit()
        return self._current_run_state_patch(task_id)

    def _graph_review_node(self, state: ReportGraphState, decision: Any) -> dict[str, Any]:
        task_id = str(state["task_id"])
        decision_payload = dict(decision) if isinstance(decision, dict) else {"approved": bool(decision)}
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            runtime = dict(metadata.get("report_runtime") or {})
            runtime["checkpoint_status"] = "resumed"
            runtime["interrupts"] = []
            metadata["report_runtime"] = runtime
            task.metadata_json = metadata
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage="claim_review",
                    status="resumed",
                    message="LangGraph claim review checkpoint resumed",
                    metadata_json={"decision": decision_payload, "runtime": "langgraph"},
                )
            )
            session.commit()
        return self._current_run_state_patch(task_id)

    def _record_runtime_result(self, task_id: str, result: dict[str, Any]) -> None:
        interrupts = list(result.get("interrupts") or [])
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            runtime = dict(metadata.get("report_runtime") or {})
            runtime["checkpoint_status"] = "interrupted" if interrupts else "completed"
            runtime["interrupts"] = interrupts
            events = list(result.get("runtime_events") or [])
            runtime["events"] = events
            runtime["node_latency_ms"] = {
                str(item.get("node")): float(item.get("duration_ms") or 0.0)
                for item in events
                if isinstance(item, dict) and item.get("node")
            }
            runtime["total_node_latency_ms"] = round(sum(runtime["node_latency_ms"].values()), 3)
            runtime["request_id"] = str(result.get("request_id") or metadata.get("request_id") or task_id)
            runtime["run_id"] = str(result.get("run_id") or metadata.get("run_id") or task_id)
            metadata["report_runtime"] = runtime
            task.metadata_json = metadata
            if interrupts:
                session.add(
                    ReportTaskEvent(
                        task_id=task_id,
                        stage="claim_review",
                        status="interrupted",
                        message="LangGraph paused for Claim review",
                        metadata_json={"interrupts": interrupts, "runtime": "langgraph"},
                    )
                )
            session.commit()

    def _current_run_state_patch(self, task_id: str) -> dict[str, Any]:
        return project_run_state_patch(self.get_task(task_id)["run_state"])

    def _run_task_legacy_pipeline(self, *, task_id: str, metadata: dict[str, Any]) -> None:
        evidence_gate = self.run_evidence_gate(task_id)
        if evidence_gate.get("blocked") is True:
            return
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            self._transition_task(task, "generating", reason="evidence_gate_passed")
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage="orchestrator",
                    status="running",
                    message="研报生成流程开始",
                    metadata_json={"evidence_gate_status": evidence_gate.get("status"), "runtime": "legacy"},
                )
            )
            session.commit()
        self._run_orchestrator(task_id=task_id, metadata=metadata)
        self._enhance_artifacts_with_task_evidence(task_id)
        self._run_official_evidence_backfill(task_id)
        self._refresh_retrieval_attribution(task_id, metadata=metadata)
        self.import_artifacts(task_id)
        quality_result = self.run_quality_gate(task_id)
        self.import_artifacts(task_id)
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            delivery_pass = _dict_path(quality_result, "delivery_gate").get("delivery_pass")
            target: ReportLifecycleStatus = "generation_completed" if delivery_pass is True else "quality_blocked"
            self._transition_task(task, target, reason="quality_gate_completed")
            task.finished_at = _utc_now()
            task.error_message = None
            task.quality_score = _quality_score_from_result(quality_result)
            task_metadata = dict(task.metadata_json or {})
            task_metadata["quality_result"] = _compact_quality_result(quality_result)
            task.metadata_json = task_metadata
            session.add(
                ReportTaskEvent(
                    task_id=task.task_id,
                    stage=task.current_stage or task.status,
                    status=task.status,
                    message="Report task completed" if delivery_pass is True else "Report generated but quality gate failed",
                    metadata_json={
                        "artifact_count": len(task.artifacts),
                        "delivery_pass": delivery_pass,
                        "quality_score": task.quality_score,
                        "runtime": "legacy",
                    },
                )
            )
            session.commit()

    def retry_task(self, task_id: str, *, run_immediately: bool = True) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if task.status == "running":
                raise ReportTaskConflict(f"Task {task_id} is already running")
            if task.status == "archived":
                raise ReportTaskConflict(f"Task {task_id} cannot be retried from archived status")
            self._transition_task(task, "queued", reason="task_retry_requested")
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
            self._transition_task(task, "queued", reason="task_start_requested")
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
            self._transition_task(task, "cancelled", reason=reason or "user_cancelled")
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
            self._transition_task(task, "archived", reason=reason or "user_archived")
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

    def bulk_archive_failed_tasks(self, task_ids: list[str] | None = None) -> dict[str, Any]:
        """Move failed tasks to the archive without touching deliverable or reviewable work."""

        requested = {str(item).strip() for item in (task_ids or []) if str(item).strip()}
        failure_statuses = {"failed", "quality_failed", "timeout", "cancelled"}
        archived_ids: list[str] = []
        skipped_ids: list[str] = []
        with self.session() as session:
            stmt = select(ReportTask).where(ReportTask.status != "archived")
            if requested:
                stmt = stmt.where(ReportTask.task_id.in_(requested))
            tasks = list(session.scalars(stmt).all())
            found_ids = {task.task_id for task in tasks}
            skipped_ids.extend(sorted(requested - found_ids))
            for task in tasks:
                metadata = dict(task.metadata_json or {})
                evidence_gate = metadata.get("pre_generation_evidence_gate")
                evidence_gate = evidence_gate if isinstance(evidence_gate, dict) else {}
                failed = task.status in failure_statuses or evidence_gate.get("blocked") is True or evidence_gate.get("status") == "failed"
                if not failed or task.status in {"completed", "running", "archived"}:
                    skipped_ids.append(task.task_id)
                    continue
                previous_status = task.status
                self._transition_task(task, "archived", reason="bulk_failed_cleanup")
                task.finished_at = task.finished_at or _utc_now()
                metadata["archived_from_status"] = previous_status
                metadata["archive_reason"] = "Bulk archived failed task from workbench"
                task.metadata_json = metadata
                session.add(
                    ReportTaskEvent(
                        task_id=task.task_id,
                        stage="archived",
                        status="archived",
                        message="失败任务已从当前列表移入归档",
                        metadata_json={"previous_status": previous_status, "source": "workbench_bulk_cleanup"},
                    )
                )
                archived_ids.append(task.task_id)
            session.commit()
        return {
            "archived_count": len(archived_ids),
            "archived_task_ids": archived_ids,
            "skipped_count": len(skipped_ids),
            "skipped_task_ids": skipped_ids,
        }

    def import_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        importer = ArtifactImporter(
            session_factory=self.session,
            output_root=self.output_root,
            report_root=self.report_root,
        )
        importer.import_for_task(task_id)
        self._materialize_task_memory(task_id)
        return self.get_task(task_id).get("artifacts", [])

    def _materialize_task_memory(self, task_id: str) -> dict[str, Any]:
        """Best-effort, idempotent entity/relation materialization after evidence import."""

        try:
            extracted = EntityService(session_factory=self.session).extract_from_task(task_id)
            summary = {
                "status": "ready" if extracted.get("evidence_count", 0) else "no_evidence",
                "evidence_count": int(extracted.get("evidence_count") or 0),
                "entity_count": int(extracted.get("entity_count") or 0),
                "relation_count": int(extracted.get("relation_count") or 0),
                "materialized_at": _dt(_utc_now()),
            }
        except Exception as exc:
            summary = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "materialized_at": _dt(_utc_now()),
            }

        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            previous = metadata.get("auto_memory_materialization")
            previous = previous if isinstance(previous, dict) else {}
            metadata["auto_memory_materialization"] = summary
            task.metadata_json = metadata
            comparable_keys = ("status", "evidence_count", "entity_count", "relation_count", "error_type", "error_message")
            if any(previous.get(key) != summary.get(key) for key in comparable_keys):
                session.add(
                    ReportTaskEvent(
                        task_id=task_id,
                        stage="memory_materialization",
                        status="success" if summary["status"] in {"ready", "no_evidence"} else "failed",
                        message="任务证据已自动沉淀为实体与关系" if summary["status"] == "ready" else "任务记忆自动沉淀完成",
                        metadata_json=summary,
                    )
                )
            session.commit()
        return summary

    def run_quality_gate(self, task_id: str) -> dict[str, Any]:
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            self._transition_task(task, "quality_checking", reason="quality_gate_started")
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
        attribution = self._refresh_retrieval_attribution(task_id, metadata=metadata)
        llm_run_id = self._record_quality_gate_harness_run(task_id, metadata=metadata, quality_result=result)
        score = _quality_score_from_result(result)
        delivery_pass = _dict_path(result, "delivery_gate").get("delivery_pass")
        if delivery_pass is not True:
            _mark_report_html_as_delivery_blocked(report_dir, result)
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
                        "retrieval_attribution": attribution,
                        "llm_run_id": llm_run_id,
                    },
                )
            )
            session.commit()
            return result

    def _refresh_retrieval_attribution(self, task_id: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = dict(metadata or self._task_metadata(task_id))
        output_dir = Path(str(metadata.get("output_dir") or ""))
        report_dir = Path(str(metadata.get("report_dir") or ""))
        if not str(output_dir):
            return {"schema_version": "retrieval_attribution_runtime.v1", "status": "missing_output_dir"}
        paths = write_evidence_retrieval_attribution(output_dir, reports_dir=report_dir, run_dir=output_dir.parent)
        artifact = _read_json_object(output_dir / "evidence_retrieval_attribution.json")
        roots = artifact.get("overall_root_causes") if isinstance(artifact.get("overall_root_causes"), list) else []
        top = roots[0] if roots and isinstance(roots[0], dict) else {}
        retrieval = artifact.get("retrieval_summary") if isinstance(artifact.get("retrieval_summary"), dict) else {}
        summary = {
            "schema_version": "retrieval_attribution_runtime.v1",
            "status": artifact.get("status", "ready") if artifact else "missing",
            "top_root_cause": top.get("cause"),
            "top_root_cause_label": top.get("label"),
            "similarity_status": retrieval.get("similarity_status"),
            "vector_score_max": retrieval.get("vector_score_max"),
            "local_candidate_count": retrieval.get("local_candidate_count"),
            "local_returned_count": retrieval.get("local_returned_count"),
            "source_file": paths.get("evidence_retrieval_attribution"),
        }
        self._update_runtime_metadata(task_id, "retrieval_attribution", summary)
        self._record_runtime_stage(
            task_id,
            stage="retrieval_attribution",
            status="success" if summary["status"] == "ready" else "warning",
            message="证据召回归因诊断已生成",
            metadata=summary,
        )
        return summary

    def _run_official_evidence_backfill(self, task_id: str) -> dict[str, Any]:
        metadata = self._task_metadata(task_id)
        output_dir = Path(str(metadata.get("output_dir") or ""))
        symbol = str(metadata.get("symbol") or "")
        period = str(metadata.get("period") or "")
        if not output_dir or not symbol or not period:
            summary = {
                "schema_version": "official_evidence_backfill_runtime.v1",
                "status": "skipped",
                "reason": "missing_task_context",
                "blocks_generation": False,
            }
            self._update_runtime_metadata(task_id, "official_evidence_backfill", summary)
            return summary

        output_dir.mkdir(parents=True, exist_ok=True)
        existing_records = _read_json_list(output_dir / "evidence.json")
        existing_tables = _read_json_list(output_dir / "tables.json")
        if not existing_records:
            with self.session() as session:
                task = self._get_task_for_update(session, task_id)
                evidence_items = self._evidence_candidates_for_gate(session, task=task, metadata=metadata)
                existing_records = [
                    _artifact_record_from_evidence(item, task=task, metadata=metadata)
                    for item in evidence_items
                ]
            if existing_records:
                _write_json_list(output_dir / "evidence.json", existing_records)

        official_artifacts = build_official_evidence_artifacts(
            existing_records,
            symbol=symbol,
            period=period,
            tables=existing_tables,
        )
        coverage = official_artifacts["evidence_coverage"]
        plan = official_artifacts["official_evidence_backfill_plan"]
        _write_json_object(output_dir / "official_evidence_manifest.json", official_artifacts["official_evidence_manifest"])
        _write_json_object(output_dir / "evidence_coverage.json", coverage)
        _write_json_object(output_dir / "official_evidence_backfill_plan.json", plan)

        if not bool(plan.get("backfill_required")):
            summary = {
                "schema_version": "official_evidence_backfill_runtime.v1",
                "status": "not_required",
                "symbol": symbol,
                "period": period,
                "formal_delivery_allowed": bool(coverage.get("formal_delivery_allowed")),
                "missing_requirements": list(coverage.get("missing_requirements") or []),
                "blocks_generation": False,
                "source_file": str(output_dir / "official_evidence_backfill_plan.json"),
            }
            self._update_runtime_metadata(task_id, "official_evidence_backfill", summary)
            return summary

        if not bool(metadata.get("enable_remote_data", False)):
            summary = {
                "schema_version": "official_evidence_backfill_runtime.v1",
                "status": "remote_disabled",
                "symbol": symbol,
                "period": period,
                "formal_delivery_allowed": bool(coverage.get("formal_delivery_allowed")),
                "missing_requirements": list(coverage.get("missing_requirements") or []),
                "task_count": len(plan.get("tasks") or []),
                "blocks_generation": False,
                "source_file": str(output_dir / "official_evidence_backfill_plan.json"),
            }
            self._update_runtime_metadata(task_id, "official_evidence_backfill", summary)
            return summary

        try:
            result = execute_official_evidence_backfill(
                symbol=symbol,
                period=period,
                output_dir=output_dir,
                existing_records=existing_records,
                existing_tables=existing_tables,
                plan=plan,
            )
        except Exception as exc:  # noqa: BLE001 - source acquisition is best-effort before draft generation.
            summary = {
                "schema_version": "official_evidence_backfill_runtime.v1",
                "status": "failed",
                "symbol": symbol,
                "period": period,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "blocks_generation": False,
                "source_file": str(output_dir / "official_evidence_backfill_plan.json"),
            }
            self._update_runtime_metadata(task_id, "official_evidence_backfill", summary)
            return summary

        remaining = result.get("backfill_remaining") if isinstance(result.get("backfill_remaining"), dict) else {}
        coverage_after = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
        summary = {
            "schema_version": "official_evidence_backfill_runtime.v1",
            "status": "completed",
            "symbol": symbol,
            "period": period,
            "acquired_record_count": int(result.get("acquired_record_count") or 0),
            "merged_record_count": int(result.get("merged_record_count") or 0),
            "pdf_record_count": int(result.get("pdf_record_count") or 0),
            "table_count": int(result.get("table_count") or 0),
            "formal_delivery_allowed": bool(coverage_after.get("formal_delivery_allowed")),
            "missing_requirements": list(coverage_after.get("missing_requirements") or []),
            "remaining_task_count": len(remaining.get("tasks") or []),
            "attempts": list(result.get("attempts") or []),
            "blocks_generation": False,
            "source_file": str(output_dir / "official_evidence_backfill_run.json"),
        }
        _sync_task_retrieval_curated_dir(output_dir)
        self._update_runtime_metadata(task_id, "official_evidence_backfill", summary)
        return summary

    def _enhance_artifacts_with_task_evidence(self, task_id: str) -> None:
        """Attach persisted task evidence to generated artifacts before import/quality gates."""

        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            output_dir = Path(str(metadata.get("output_dir") or ""))
            report_dir = Path(str(metadata.get("report_dir") or ""))
            candidates = self._evidence_candidates_for_gate(session, task=task, metadata=metadata)
            evidence_records = [_artifact_record_from_evidence(item, task=task, metadata=metadata) for item in candidates]

        if not output_dir or not report_dir or not evidence_records:
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)

        existing_evidence = _read_json_list(output_dir / "evidence.json")
        merged_evidence = _merge_records_by_id(existing_evidence, evidence_records, id_keys=("evidence_id", "sample_id", "id"))
        _write_json_list(output_dir / "evidence.json", merged_evidence)

        official_records = [record for record in evidence_records if _is_official_artifact_evidence(record)]
        if not official_records:
            return

        claims = _read_json_list(output_dir / "claims.json")
        claims = _patch_claims_with_official_evidence(claims, official_records=official_records, task_id=task_id)
        _write_json_list(output_dir / "claims.json", claims)

        report_md_path = report_dir / "report.md"
        markdown = report_md_path.read_text(encoding="utf-8") if report_md_path.exists() else ""
        markdown = _patch_report_markdown_with_official_evidence(markdown, official_records=official_records, claims=claims, metadata=metadata)
        citation_artifacts = build_citation_artifacts(
            evidence_records=merged_evidence,
            claims=claims,
            markdown=markdown,
            html="",
        )
        citations = list(citation_artifacts.get("citations") or [])
        markdown_with_refs = append_compliance_disclosures(str(citation_artifacts.get("markdown") or markdown), citations=citations)
        report_md_path.write_text(markdown_with_refs, encoding="utf-8")

        _write_json_list(output_dir / "citations.json", citations)
        (output_dir / "citations.md").write_text(str(citation_artifacts.get("citations_markdown") or ""), encoding="utf-8")

        charts = _read_json_list(output_dir / "charts.json")
        title = _report_title_from_markdown(markdown_with_refs) or f"{metadata.get('symbol') or task_id} {metadata.get('period') or ''} 研报"
        html = render_professional_html_report(markdown_with_refs, title=title, charts=charts, citations=citations)
        (report_dir / "report.html").write_text(html, encoding="utf-8")

        report_json_path = report_dir / "report.json"
        report_json = _read_json_object(report_json_path)
        if report_json:
            report_json["markdown"] = markdown_with_refs
            report_json["citations"] = citations
            report_json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_evidence_gate(self, task_id: str) -> dict[str, Any]:
        """Check whether a task has enough persisted evidence before generation."""

        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            metadata = dict(task.metadata_json or {})
            if _truthy(metadata.get("skip_evidence_gate")):
                gate = {
                    "status": "skipped",
                    "blocked": False,
                    "draft_ready": True,
                    "delivery_ready": False,
                    "delivery_blocked_reasons": [
                        {
                            "type": "evidence_gate_skipped",
                            "label": "未完成证据检查",
                            "description": "已跳过生成前证据检查，当前只能作为草稿，正式交付前需要补做证据检查。",
                        }
                    ],
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
            draft_ready = not blocked
            delivery_ready = bool(coverage.get("quality_ready")) and not blocking_reasons
            status = "failed" if blocked else ("warning" if blocking_reasons else "success")
            gate = {
                "status": status,
                "blocked": blocked,
                "draft_ready": draft_ready,
                "delivery_ready": delivery_ready,
                "enforced": enforced,
                "allow_weak_evidence": allow_weak,
                "summary": _evidence_gate_summary(
                    coverage=coverage,
                    blocking_reasons=blocking_reasons,
                    blocked=blocked,
                    delivery_ready=delivery_ready,
                ),
                "blocking_reasons": blocking_reasons,
                "delivery_blocked_reasons": [] if delivery_ready else blocking_reasons,
                "coverage": coverage,
                "recommended_actions": _evidence_gate_actions(coverage),
            }
            metadata["pre_generation_evidence_gate"] = gate
            task.metadata_json = metadata
            if blocked and resolve_lifecycle_status(task) == "evidence_checking":
                self._transition_task(task, "evidence_blocked", reason="evidence_gate_blocked")
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
                        "draft_ready": draft_ready,
                        "delivery_ready": delivery_ready,
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
                .options(
                    selectinload(ReportTask.artifacts),
                    selectinload(ReportTask.events),
                    selectinload(ReportTask.claims),
                )
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
            items = [self.serialize_task(task) for task in session.scalars(stmt).unique().all()]
            total = int(session.scalar(count_stmt) or 0)
        return {"items": items, "total": total}

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self.session() as session:
            task = session.scalar(
                select(ReportTask)
                .where(ReportTask.task_id == task_id)
                .options(
                    selectinload(ReportTask.artifacts),
                    selectinload(ReportTask.events),
                    selectinload(ReportTask.claims),
                )
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
            tool_runs = list(
                session.scalars(
                    select(ToolRun)
                    .where(ToolRun.task_id == task_id)
                    .order_by(ToolRun.created_at.desc(), ToolRun.id.desc())
                    .limit(200)
                ).all()
            )
            payload["quality_diagnostics"] = build_quality_diagnostics(task, llm_runs)
            payload["tool_runs"] = [serialize_tool_run(item) for item in tool_runs]
            payload["runtime_observability"] = build_runtime_observability(task, llm_runs, tool_runs)
            return payload

    def get_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        return {
            "task_id": task_id,
            "artifacts": task.get("artifacts", []),
            "report_links": _report_links(task.get("artifacts", [])),
        }

    def get_tool_runs(self, task_id: str, *, limit: int = 200) -> dict[str, Any]:
        with self.session() as session:
            task_exists = session.scalar(select(ReportTask.id).where(ReportTask.task_id == task_id))
            if task_exists is None:
                raise ReportTaskNotFound(task_id)
            total = int(session.scalar(select(func.count(ToolRun.id)).where(ToolRun.task_id == task_id)) or 0)
            rows = list(
                session.scalars(
                    select(ToolRun)
                    .where(ToolRun.task_id == task_id)
                    .order_by(ToolRun.created_at.desc(), ToolRun.id.desc())
                    .limit(max(1, min(int(limit), 500)))
                ).all()
            )
        return {"task_id": task_id, "items": [serialize_tool_run(item) for item in rows], "total": total}

    def session(self) -> Session:
        self._ensure_db()
        assert self._session_factory is not None
        return self._session_factory()

    def close(self) -> None:
        """Release runtime checkpoint resources owned by this service."""

        with self._runtime_lock:
            if self._langgraph_runtime is not None:
                self._langgraph_runtime.close()
                self._langgraph_runtime = None

    def serialize_task(self, task: ReportTask) -> dict[str, Any]:
        artifacts = [serialize_artifact(item) for item in sorted(task.artifacts, key=lambda item: item.id or 0)]
        events = [serialize_event(item) for item in sorted(task.events, key=lambda item: item.id or 0)]
        run_state = build_report_run_state(task)
        metadata = task.metadata_json or {}
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
            "metadata": metadata,
            "trace_context": {
                "request_id": str(metadata.get("request_id") or task.task_id),
                "run_id": str(metadata.get("run_id") or task.task_id),
                "task_id": task.task_id,
            },
            "events": events,
            "artifacts": artifacts,
            "report_links": _report_links(artifacts),
            "run_state": run_state,
            "delivery_readiness": run_state["delivery_readiness"],
            "export_readiness": run_state["export_readiness"],
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
        # Keep the production path single-pass. The collaborative modes remain
        # available for explicit diagnostics while LangGraph nodes are split.
        execution_mode = str(payload.get("execution_mode") or "static")
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
            "market": str(payload.get("market") or ""),
            "exchange": str(payload.get("exchange") or ""),
            "currency": str(payload.get("currency") or ""),
            "country_region": str(payload.get("country_region") or ""),
            "period": period,
            "report_type": str(payload.get("report_type") or "equity_research"),
            "data_source_scope": str(payload.get("data_source_scope") or "official_first"),
            "execution_mode": execution_mode,
            "fast": bool(payload.get("fast", True)),
            "search_engines": _normalize_search_engines(payload.get("search_engines")),
            "enable_remote_data": _truthy(
                payload.get("enable_remote_data", self.mode == "user" and self._uses_production_orchestrator)
            ),
            "data_source_config_path": str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
            "memory_enabled": bool(payload.get("memory_enabled", False)),
            "execution_tier": str(payload.get("execution_tier") or ("user_fast" if self.mode == "user" else "developer_fast")),
            "run_mode": str(payload.get("run_mode") or "queue_only"),
            "enforce_evidence_gate": _truthy(payload.get("enforce_evidence_gate", False)),
            "allow_weak_evidence": _truthy(payload.get("allow_weak_evidence", False)),
            "skip_evidence_gate": _truthy(payload.get("skip_evidence_gate", False)),
        }

    def _run_orchestrator(self, *, task_id: str, metadata: dict[str, Any]) -> Any:
        phased_static = self.orchestrator_factory is MultiAgentOrchestrator and str(metadata.get("execution_mode") or "static") == "static"
        result = self._run_orchestrator_instance(
            task_id=task_id,
            metadata=metadata,
            resume_from_phase_artifacts=phased_static,
        )
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            self._transition_task(task, "generating", stage_override="artifact_import", reason="orchestrator_completed")
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

    def _run_orchestrator_instance(
        self,
        *,
        task_id: str,
        metadata: dict[str, Any],
        stop_after_phase: str = "",
        resume_from_phase_artifacts: bool = False,
    ) -> Any:
        orchestrator_kwargs: dict[str, Any] = {
            "output_dir": str(metadata["output_dir"]),
            "report_dir": str(metadata["report_dir"]),
            "config_path": self.config_path,
            "memory_enabled": bool(metadata.get("memory_enabled", False)),
            "memory_root": str(self.memory_root / "durable"),
            "execution_tier": str(metadata.get("execution_tier") or "developer_fast"),
        }
        if _supports_agent_stage_callback(self.orchestrator_factory):
            orchestrator_kwargs["stage_callback"] = lambda payload: self._record_agent_stage(task_id, payload)
        orchestrator = self.orchestrator_factory(
            **orchestrator_kwargs,
        )
        run_kwargs: dict[str, Any] = {
            "research_topic": str(metadata.get("research_topic") or ""),
            "symbol": str(metadata.get("symbol") or ""),
            "period": str(metadata.get("period") or ""),
            "execution_mode": str(metadata.get("execution_mode") or "static"),
            "fast": bool(metadata.get("fast", True)),
            "search_engines": list(metadata.get("search_engines") or []),
            "enable_remote_data": bool(metadata.get("enable_remote_data", False)),
            "data_source_config_path": str(metadata.get("data_source_config_path") or "configs/data_sources.yaml"),
        }
        if self.orchestrator_factory is MultiAgentOrchestrator:
            run_kwargs["stop_after_phase"] = stop_after_phase
            run_kwargs["resume_from_phase_artifacts"] = resume_from_phase_artifacts
        return orchestrator.run(**run_kwargs)

    def _record_agent_stage(self, task_id: str, payload: dict[str, Any]) -> None:
        phase = str(payload.get("phase") or "running")
        agent_key = str(payload.get("agent_key") or "unknown")
        status = "running" if phase == "started" else ("success" if payload.get("status") == "completed" else "failed")
        with self.session() as session:
            task = self._get_task_for_update(session, task_id)
            if phase == "started":
                task.current_stage = f"agent_{agent_key}"
            metadata = dict(task.metadata_json or {})
            runtime = dict(metadata.get("report_runtime") or {})
            runtime["current_agent"] = {
                "agent_key": agent_key,
                "agent_name": payload.get("agent_name"),
                "task_type": payload.get("task_type"),
                "phase": phase,
                "status": payload.get("status") or status,
                "duration_ms": payload.get("duration_ms"),
                "model_name": payload.get("model_name"),
                "provider": payload.get("provider"),
                "route_profile": payload.get("route_profile"),
                "react_used": payload.get("react_used"),
                "error": payload.get("error"),
                "updated_at": _utc_now().isoformat(),
            }
            metadata["report_runtime"] = runtime
            task.metadata_json = metadata
            session.add(
                ReportTaskEvent(
                    task_id=task_id,
                    stage=f"agent.{agent_key}",
                    status=status,
                    message=(
                        f"{payload.get('agent_name') or agent_key} started"
                        if phase == "started"
                        else f"{payload.get('agent_name') or agent_key} finished"
                    ),
                    metadata_json=dict(payload),
                )
            )
            session.commit()

    def _get_task_for_update(self, session: Session, task_id: str) -> ReportTask:
        task = session.scalar(
            select(ReportTask)
            .where(ReportTask.task_id == task_id)
            .options(
                selectinload(ReportTask.artifacts),
                selectinload(ReportTask.events),
                selectinload(ReportTask.claims),
            )
        )
        if task is None:
            raise ReportTaskNotFound(task_id)
        return task

    def _transition_task(
        self,
        task: ReportTask,
        target: ReportLifecycleStatus,
        *,
        stage_override: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            return apply_report_transition(task, target, stage_override=stage_override, reason=reason)
        except InvalidReportTransition as exc:
            raise ReportTaskConflict(str(exc)) from exc

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
        matched = [item for item in items if _evidence_matches_task_gate(item, task=task, metadata=metadata)]
        return _dedupe_task_evidence_candidates(matched)


def _evidence_matches_task_gate(item: EvidenceItem, *, task: ReportTask, metadata: dict[str, Any]) -> bool:
    item_metadata = item.metadata_json or {}
    task_id = str(task.task_id or "")
    company_match = _evidence_company_matches(item, task=task, metadata=metadata)
    if not company_match:
        return False
    if _norm(item_metadata.get("task_id")) == _norm(task_id):
        return True
    if item.document is not None and _norm(item.document.batch_id) == _norm(task_id):
        return True
    for link in item.claim_links:
        if link.claim is not None and _norm(link.claim.task_id) == _norm(task_id):
            return True

    period_match = _evidence_period_matches(item, task=task, metadata=metadata)
    if company_match and period_match and str(item.source_type or "").lower() in PERIOD_GATED_SOURCE_TYPES:
        record = _artifact_record_from_evidence(item, task=task, metadata=metadata)
        period_match = record_period_status(
            record,
            target_period=str(task.period or metadata.get("period") or ""),
        ) != "mismatch"
    if _norm(task.period or metadata.get("period")):
        return company_match and period_match
    return company_match


def _dedupe_task_evidence_candidates(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Keep the newest reusable record for snapshot-like datasource outputs."""

    seen: set[str] = set()
    output: list[EvidenceItem] = []
    for item in items:
        source_type = str(item.source_type or "").strip().lower()
        source_url = str(item.source_url or "").strip().lower().rstrip("/")
        metadata = item.metadata_json or {}
        period = str(
            metadata.get("period")
            or metadata.get("report_period")
            or (item.document.report_period if item.document else "")
            or ""
        ).strip().upper()
        if source_type in {"market_api", "market_data", "company_profile", "company_page"} and source_url:
            key = f"snapshot|{source_type}|{source_url}|{period}"
        else:
            key = str(metadata.get("identity_key") or item.evidence_id or item.id)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _evidence_company_matches(item: EvidenceItem, *, task: ReportTask, metadata: dict[str, Any]) -> bool:
    from src.data.company_universe import canonicalize_symbol

    expected_symbol = canonicalize_symbol(str(task.symbol or metadata.get("symbol") or metadata.get("company_symbol") or ""))
    source_identity_symbol = _immutable_source_symbol(item)
    if expected_symbol and source_identity_symbol and expected_symbol != source_identity_symbol:
        return False
    if task.company_id is not None and item.company_id is not None:
        return int(item.company_id) == int(task.company_id)
    company = item.company
    item_symbol = canonicalize_symbol(
        str(
            (company.symbol if company else "")
            or (item.metadata_json or {}).get("symbol")
            or (item.metadata_json or {}).get("company_symbol")
            or ""
        )
    )
    if expected_symbol and item_symbol:
        return expected_symbol == item_symbol
    expected_name = _norm(metadata.get("company_name"))
    item_name = _norm((company.name if company else "") or (item.metadata_json or {}).get("company_name"))
    return bool(expected_name and item_name and expected_name == item_name)


def _immutable_source_symbol(item: EvidenceItem) -> str:
    """Resolve identity from source-controlled labels before mutable DB bindings."""

    from src.data.company_universe import canonicalize_symbol, resolve_company_identifier_with_diagnostics

    text = " ".join([str(item.title or ""), str(item.source_url or "")]).strip()
    resolved = resolve_company_identifier_with_diagnostics(text)
    if bool(resolved.get("resolved")) and float(resolved.get("confidence") or 0.0) >= 0.65:
        return canonicalize_symbol(str(resolved.get("symbol") or ""))
    return ""


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
                "description": "当前任务缺少权威来源：" + "、".join(_source_display_name(source) for source in missing_sources),
                "sources": missing_sources,
            }
        )
    return reasons


def _evidence_gate_summary(
    *,
    coverage: dict[str, Any],
    blocking_reasons: list[dict[str, Any]],
    blocked: bool,
    delivery_ready: bool,
) -> str:
    if blocked:
        return "生成已暂停：证据覆盖不足，请先补充采集或导入权威资料。"
    if delivery_ready:
        return coverage.get("summary") or "证据覆盖已满足正式交付要求。"
    if blocking_reasons:
        return "可生成草稿，但正式交付仍需补齐权威来源和证据覆盖。"
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


def _source_display_name(source_key: str) -> str:
    mapping = {
        "sec_edgar": "美国证监会披露",
        "cninfo": "巨潮资讯",
        "cninfo_announcement": "巨潮资讯披露",
        "cninfo_announcements": "巨潮资讯公告",
        "hkex": "港交所披露",
        "hkex_announcement": "港交所披露",
        "hkex_announcements": "港交所公告",
        "yahoo_finance": "雅虎财经",
        "serper": "公开网页检索",
        "tavily": "公开网页检索",
        "local_evidence": "本地证据库",
    }
    return mapping.get(str(source_key or ""), str(source_key or "未知来源"))


def _artifact_record_from_evidence(item: EvidenceItem, *, task: ReportTask, metadata: dict[str, Any]) -> dict[str, Any]:
    from src.schemas.runtime_contracts import normalize_evidence_record

    item_metadata = dict(item.metadata_json or {})
    source_symbol = str(
        _immutable_source_symbol(item)
        or (item.company.symbol if item.company is not None else "")
        or item_metadata.get("symbol")
        or item_metadata.get("company_symbol")
        or ""
    )
    record = {
        "evidence_id": item.evidence_id,
        "sample_id": item.evidence_id,
        "symbol": source_symbol,
        "period": item_metadata.get("period") or item_metadata.get("report_period") or task.period or metadata.get("period"),
        "source_type": item.source_type or "local_evidence",
        "trust_level": item.trust_level or "medium",
        "title": item.title or item.evidence_id,
        "content": item.content or "",
        "source_url": item.source_url or "",
        "page": item.page_no,
        "metadata": {
            **item_metadata,
            "origin_task_id": item_metadata.get("task_id") or "",
            "task_id": task.task_id,
            "expected_symbol": task.symbol or metadata.get("symbol"),
            "evidence_role": item_metadata.get("evidence_role") or "target",
            "db_evidence_item_id": item.id,
            "source_evidence_id": item.evidence_id,
        },
    }
    grade = grade_source_authority(record)
    source_authority = item_metadata.get("source_authority") or grade.get("source_authority")
    if str(item.trust_level or "").lower() == "official" and source_authority in {"", None, "unknown"}:
        source_authority = "official"
    record.update(
        {
            "source_authority": source_authority,
            "authority_level": item_metadata.get("authority_level") or grade.get("authority_level"),
            "authority_score": item_metadata.get("authority_score") or (1.0 if source_authority == "official" else grade.get("authority_score")),
            "source_document_type": item_metadata.get("source_document_type") or grade.get("source_document_type"),
        }
    )
    cleaned = {key: value for key, value in record.items() if value not in (None, "")}
    return normalize_evidence_record(
        cleaned,
        task_id=task.task_id,
        run_id=str(metadata.get("run_id") or task.task_id),
        target_period=str(task.period or metadata.get("period") or ""),
    )


def _is_official_artifact_evidence(record: dict[str, Any]) -> bool:
    source_type = str(record.get("source_type") or "").lower()
    trust_level = str(record.get("trust_level") or "").lower()
    authority = str(record.get("source_authority") or "").lower()
    return (
        trust_level == "official"
        or authority in {"official", "official_statistics", "company_official"}
        or any(token in source_type for token in ("sec", "edgar", "filing", "10k", "10-q", "cninfo", "hkex", "announcement", "exchange"))
    )


def _patch_claims_with_official_evidence(
    claims: list[dict[str, Any]],
    *,
    official_records: list[dict[str, Any]],
    task_id: str,
) -> list[dict[str, Any]]:
    official_ids = [str(record.get("evidence_id") or "") for record in official_records if record.get("evidence_id")]
    if not official_ids:
        return claims

    patched: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        row = dict(claim)
        section = str(row.get("section_name") or row.get("section") or "").lower()
        text = str(row.get("claim_text") or row.get("text") or row.get("claim") or "").lower()
        if _claim_should_bind_official(section + " " + text):
            existing = [str(item) for item in row.get("evidence_ids") or row.get("citations") or [] if str(item).strip()]
            row["evidence_ids"] = _dedupe(existing + official_ids[:2])
            row["confidence"] = max(float(row.get("confidence") or 0.0), 0.82)
            row["review_status"] = row.get("review_status") or "pending"
        patched.append(row)

    bound_ids = {
        evidence_id
        for claim in patched
        if isinstance(claim, dict)
        for evidence_id in [str(item) for item in claim.get("evidence_ids") or []]
    }
    if not any(evidence_id in bound_ids for evidence_id in official_ids):
        primary = official_records[0]
        patched.append(
            {
                "claim_id": f"cl_{task_id}_official_evidence",
                "section_name": "执行摘要",
                "claim_type": "official_evidence_summary",
                "claim_text": _official_summary_sentence(primary),
                "evidence_ids": official_ids[:2],
                "is_critical": True,
                "critical_claim_type": "official_source",
                "confidence": 0.86,
                "review_status": "pending",
            }
        )
    return patched


def _claim_should_bind_official(text: str) -> bool:
    return any(
        token in text
        for token in (
            "executive",
            "summary",
            "执行摘要",
            "financial",
            "revenue",
            "income",
            "cash",
            "财务",
            "收入",
            "利润",
            "现金流",
            "risk",
            "风险",
            "valuation",
            "估值",
            "conclusion",
            "recommendation",
            "投资",
            "结论",
            "评级",
        )
    )


def _patch_report_markdown_with_official_evidence(
    markdown: str,
    *,
    official_records: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> str:
    title_text = _report_title_from_markdown(markdown) or f"{metadata.get('symbol') or '公司'} {metadata.get('period') or ''} 研报"
    title = f"# {title_text}"
    body = _strip_report_title(markdown).strip()
    primary = official_records[0]
    secondary = official_records[1] if len(official_records) > 1 else primary
    ev1 = str(primary.get("evidence_id") or "")
    ev2 = str(secondary.get("evidence_id") or ev1)
    company = str(metadata.get("company_name") or metadata.get("symbol") or "公司")
    symbol = str(metadata.get("symbol") or "")
    period = str(metadata.get("period") or "")
    source_names = "、".join(_dedupe([_source_label(record) for record in official_records])[:3])
    meta = _report_meta_tags(symbol=symbol, official_records=official_records)
    claim_count = len([claim for claim in claims if isinstance(claim, dict)])

    sections = {
        "执行摘要": _render_meta_summary_section(company, symbol, period, source_names, claim_count, ev1, meta),
        "财务分析": _render_meta_financial_section(ev1, meta),
        "估值观察": _render_meta_valuation_section(ev1, meta),
        "风险评估": _render_meta_risk_section(ev2, meta),
        "投资结论": _render_meta_conclusion_section(source_names, ev1, meta),
    }
    for heading, replacement in sections.items():
        body = _replace_or_insert_section(body, heading, replacement, preserve_substantive=True)
    return f"{title}\n\n{body.strip()}\n"


def _replace_or_insert_section(markdown: str, heading: str, content: str, *, preserve_substantive: bool = False) -> str:
    pattern = re.compile(rf"(?ms)^##\s+{re.escape(heading)}\s*\n.*?(?=^##\s+|\Z)")
    replacement = f"## {heading}\n{content.strip()}\n\n"
    match = pattern.search(markdown)
    if match and preserve_substantive and _is_substantive_report_section(match.group(0)):
        return markdown
    if match:
        return pattern.sub(replacement, markdown, count=1)

    aliases = {
        "财务分析": ("财务分析与三表摘要", "财务分析与经营表现"),
        "估值观察": ("估值与敏感性", "估值分析", "估值"),
        "风险评估": ("风险提示", "风险因素"),
        "投资结论": ("投资建议", "投资观点"),
    }
    for alias in aliases.get(heading, ()):
        alias_pattern = re.compile(rf"(?ms)^##\s+{re.escape(alias)}\s*\n.*?(?=^##\s+|\Z)")
        alias_match = alias_pattern.search(markdown)
        if alias_match and preserve_substantive and _is_substantive_report_section(alias_match.group(0)):
            return markdown
        if alias_match:
            return alias_pattern.sub(replacement, markdown, count=1)
    return markdown.rstrip() + "\n\n" + replacement


def _is_substantive_report_section(section: str) -> bool:
    body = re.sub(r"(?m)^##\s+.*$", "", section).strip()
    # This post-processing step may fill missing sections, but it must never
    # replace a Writer-owned section merely because the prose states a data gap.
    return len(re.findall(r"[\u4e00-\u9fff]", body)) >= 80


def _report_meta_tags(symbol: str, official_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a controlled, market-aware tag set for report section drafting."""

    market_meta = infer_market_from_symbol(symbol)
    joined = " ".join(
        " ".join(
            [
                str(record.get("title") or ""),
                str(record.get("content") or record.get("snippet") or ""),
                str(record.get("source_type") or ""),
            ]
        )
        for record in official_records
        if isinstance(record, dict)
    ).lower()

    financial_tags = _matched_report_tags(
        joined,
        {
            "收入表现": ("revenue", "sales", "收入", "营收"),
            "利润质量": ("gross margin", "margin", "profit", "net income", "净利润", "毛利", "利润"),
            "现金流": ("cash flow", "operating cash", "free cash", "现金流"),
            "资产负债": ("debt", "liabilit", "asset", "资产", "负债"),
            "分部/业务结构": ("segment", "business", "gaming", "cloud", "业务", "分部"),
        },
        fallback=["收入表现", "利润质量", "现金流"],
    )
    risk_tags = _matched_report_tags(
        joined,
        {
            "风险披露": ("risk", "风险"),
            "竞争风险": ("competition", "competitive", "竞争"),
            "监管风险": ("regulatory", "regulation", "policy", "监管", "政策"),
            "供应链风险": ("supply", "manufacturing", "供应链", "产能"),
            "需求波动": ("demand", "inventory", "channel", "需求", "库存", "渠道"),
            "客户集中": ("customer concentration", "major customer", "客户集中"),
        },
        fallback=["风险披露", "竞争风险", "经营波动"],
    )
    valuation_tags = ["估值输入不足", "盈利预测待补", "同业比较待补", "敏感性待补"]
    source_label = _market_report_source_label(market_meta.get("market", ""), official_records)

    return {
        "market": market_meta.get("market") or "unknown",
        "exchange": market_meta.get("exchange") or "",
        "currency": market_meta.get("currency") or "",
        "source_label": source_label,
        "financial_tags": financial_tags,
        "risk_tags": risk_tags,
        "valuation_tags": valuation_tags,
        "all_tags": _dedupe([*financial_tags, *risk_tags, *valuation_tags]),
    }


def _matched_report_tags(text: str, rules: dict[str, tuple[str, ...]], *, fallback: list[str]) -> list[str]:
    matched = [tag for tag, keywords in rules.items() if any(keyword.lower() in text for keyword in keywords)]
    return _dedupe(matched or fallback)[:4]


def _market_report_source_label(market: str, official_records: list[dict[str, Any]]) -> str:
    source_types = {str(record.get("source_type") or "").lower() for record in official_records if isinstance(record, dict)}
    if market == "us" or "sec_edgar" in source_types:
        return "美国证监会披露"
    if market == "hk" or source_types & {"hkex", "hkex_announcement", "hkex_announcements", "hkex_annual_report"}:
        return "港交所披露"
    if market == "cn_a" or source_types & {"cninfo", "cninfo_announcement", "cninfo_announcements", "exchange_announcement"}:
        return "巨潮资讯披露"
    labels = [_source_label(record) for record in official_records if isinstance(record, dict)]
    return _dedupe(labels)[0] if labels else "权威来源披露"


def _render_meta_summary_section(
    company: str,
    symbol: str,
    period: str,
    source_names: str,
    claim_count: int,
    evidence_id: str,
    meta: dict[str, Any],
) -> str:
    source_label = str(meta.get("source_label") or source_names or "权威来源披露")
    return "\n".join(
        [
            f"- 事实边界：本报告以{source_label}为核心事实来源，覆盖公司为{company}（{symbol}），期间为{period or '最近完整披露期'}。[{evidence_id}]",
            f"- 证据基础：当前形成{claim_count}条可追溯主张，核心判断均应回溯至财务披露、经营事实和市场数据，不以缺少证据的推测替代分析。[{evidence_id}]",
            f"- 投资判断：结合盈利能力、现金流、估值水平与主要风险形成方向性观点，并以关键经营指标变化作为后续跟踪依据。[{evidence_id}]",
        ]
    )


def _render_meta_financial_section(evidence_id: str, meta: dict[str, Any]) -> str:
    source_label = str(meta.get("source_label") or "权威来源披露")
    financial_tags = meta.get("financial_tags") or ["收入表现", "利润质量", "现金流"]
    lines = [f"- {financial_tags[0]}：{source_label}已支持对收入规模、业务增长和披露口径进行复核；同比拆分、分部贡献和一次性因素仍需结构化表格确认。[{evidence_id}]"]
    lines.append(f"- 利润质量：当前证据可用于检查毛利率、费用率和净利变化方向，但不应替代完整三表模型。[{evidence_id}]")
    lines.append(f"- 现金流：需要把经营现金流、资本开支和分红回购与利润表现交叉验证，避免只依据单一收入指标得出结论。[{evidence_id}]")
    return "\n".join(lines)


def _render_meta_valuation_section(evidence_id: str, meta: dict[str, Any]) -> str:
    currency = str(meta.get("currency") or "对应市场货币")
    return "\n".join(
        [
            f"- 估值口径：估值应区分历史财务期间与当前市场时点，统一采用{currency}口径，并明确市盈率等倍数对应的盈利期间。[{evidence_id}]",
            f"- 敏感性：围绕收入增速、利润率和估值倍数设置基准、乐观与审慎情景，量化关键假设变化对估值判断的影响。[{evidence_id}]",
            f"- 判断约束：估值结论必须与盈利质量、现金流和风险事实交叉验证，证据覆盖本身不等同于买卖评级。[{evidence_id}]",
        ]
    )


def _render_meta_risk_section(evidence_id: str, meta: dict[str, Any]) -> str:
    source_label = str(meta.get("source_label") or "权威来源披露")
    risk_tags = meta.get("risk_tags") or ["风险披露", "竞争风险", "经营波动"]
    return "\n".join(
        [
            f"- 风险披露：{source_label}提示需要持续跟踪{risk_tags[0]}、{risk_tags[1] if len(risk_tags) > 1 else '经营波动'}等事项，本节采用中文归纳，不直接搬运英文原文。[{evidence_id}]",
            f"- 传导路径：风险需要从披露事实、业务环节、财务指标和投资结论逐层验证；目前适合作为风险清单，尚不能替代人工复核。[{evidence_id}]",
            f"- 监控动作：后续应补充公告更新、管理层口径和行业数据，确认风险是否已经反映到收入、利润率或现金流。[{evidence_id}]",
        ]
    )


def _render_meta_conclusion_section(source_names: str, evidence_id: str, meta: dict[str, Any]) -> str:
    source_label = str(meta.get("source_label") or source_names or "权威来源披露")
    return "\n".join(
        [
            f"- 综合判断：基于{source_label}和当前证据链，从盈利能力、现金创造、估值与风险四个维度形成方向性结论。[{evidence_id}]",
            f"- 决策依据：投资观点必须由前文章节的量化指标和风险事实共同支撑，不使用脱离证据的模板化表述。[{evidence_id}]",
            f"- 跟踪动作：重点监控收入增速、利润率、自由现金流和估值倍数的变化，任一核心假设恶化时重新评估观点。[{evidence_id}]",
        ]
    )


def _official_summary_sentence(record: dict[str, Any]) -> str:
    return f"官方来源《{record.get('title') or record.get('evidence_id')}》提供了本任务的核心事实边界：{_content_preview(record)}"


def _source_label(record: dict[str, Any]) -> str:
    source_type = str(record.get("source_type") or "")
    authority = str(record.get("source_authority") or "")
    if source_type:
        return _source_display_name(source_type)
    if authority:
        return authority
    return "权威来源"


def _content_preview(record: dict[str, Any], *, limit: int = 140) -> str:
    content = re.sub(r"\s+", " ", str(record.get("content") or record.get("snippet") or record.get("title") or "")).strip()
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "..."


def _merge_records_by_id(existing: list[dict[str, Any]], additions: list[dict[str, Any]], *, id_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_id: dict[str, int] = {}
    for record in [*existing, *additions]:
        if not isinstance(record, dict):
            continue
        record_id = ""
        for key in id_keys:
            record_id = str(record.get(key) or "").strip()
            if record_id:
                break
        if not record_id:
            record_id = f"record_{len(merged) + 1}"
        if record_id in index_by_id:
            current = dict(merged[index_by_id[record_id]])
            current.update({key: value for key, value in record.items() if value not in (None, "", [])})
            merged[index_by_id[record_id]] = current
            continue
        index_by_id[record_id] = len(merged)
        merged.append(dict(record))
    return merged


def _sync_task_retrieval_curated_dir(output_dir: Path) -> None:
    target_dir = output_dir / "retrieval_curated"
    target_dir.mkdir(parents=True, exist_ok=True)
    source = output_dir / "official_backfill_curated.jsonl"
    if source.is_file():
        (target_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    task_records = _read_json_list(output_dir / "evidence.json")
    if task_records:
        payload = "\n".join(json.dumps(item, ensure_ascii=False) for item in task_records) + "\n"
        (target_dir / "task_evidence.jsonl").write_text(payload, encoding="utf-8")


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = _read_json_any(path, default=[])
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("evidence", "claims", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = _read_json_any(path, default={})
    return dict(payload) if isinstance(payload, dict) else {}


def _read_json_any(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_list(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_canonical_metrics_manifest(output_dir: Path) -> dict[str, Any]:
    existing = _read_json_object(output_dir / "canonical_metrics.json")
    if existing:
        return _canonical_metrics_summary(output_dir=output_dir, artifact=existing)
    metrics_payload = _read_json_any(output_dir / "financial_metrics.json", default={})
    tables = _read_json_list(output_dir / "tables.json")
    metric_rows: list[dict[str, Any]] = []
    if isinstance(metrics_payload, dict):
        raw_metrics = metrics_payload.get("metrics")
        if isinstance(raw_metrics, list):
            metric_rows = [dict(item) for item in raw_metrics if isinstance(item, dict)]
        else:
            for key, value in metrics_payload.items():
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault("metric_name", key)
                    metric_rows.append(row)
    statements = sorted(
        {
            str(table.get("table_type") or table.get("statement") or "")
            for table in tables
            if str(table.get("table_type") or table.get("statement") or "")
        }
    )
    metric_names = sorted(
        {
            str(row.get("metric_name") or row.get("metric_key") or row.get("line_item") or "")
            for row in metric_rows
            if str(row.get("metric_name") or row.get("metric_key") or row.get("line_item") or "")
        }
    )
    official_metric_count = sum(
        1
        for row in metric_rows
        if str(row.get("source_type") or "").lower()
        in {"sec_companyfacts", "sec_filing", "cninfo_announcement", "hkex_announcement", "pdf_statement_table"}
    )
    return {
        "schema_version": "canonical_metrics_runtime.v1",
        "status": "ready" if metric_rows or tables else "missing",
        "metric_count": len(metric_rows),
        "table_count": len(tables),
        "statement_types": statements,
        "metric_names": metric_names[:40],
        "official_metric_count": official_metric_count,
        "source_files": {
            "financial_metrics": str(output_dir / "financial_metrics.json"),
            "tables": str(output_dir / "tables.json"),
        },
    }


def _canonical_metrics_summary(*, output_dir: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    coverage = artifact.get("coverage") if isinstance(artifact.get("coverage"), dict) else {}
    metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), list) else []
    canonical = artifact.get("canonical_metrics") if isinstance(artifact.get("canonical_metrics"), dict) else {}
    metric_names = sorted(canonical) if canonical else sorted(
        str(item.get("metric_name") or "") for item in metrics if isinstance(item, dict) and item.get("metric_name")
    )
    return {
        "schema_version": "canonical_metrics_runtime.v1",
        "status": "ready" if metric_names else "missing",
        "metric_count": int(artifact.get("metric_count") or len(metric_names)),
        "candidate_count": int(artifact.get("candidate_count") or 0),
        "metric_names": metric_names[:40],
        "missing_core_metrics": list(coverage.get("missing_core_metrics") or []),
        "conflict_count": int(artifact.get("conflict_count") or 0),
        "source_files": {
            "canonical_metrics": str(output_dir / "canonical_metrics.json"),
            "financial_metrics": str(output_dir / "financial_metrics.json"),
            "tables": str(output_dir / "tables.json"),
        },
    }


def _build_section_pack_manifest(output_dir: Path, *, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    artifact = artifact if isinstance(artifact, dict) else build_section_evidence_packs(output_dir)
    contracts = _read_json_object(output_dir / "report_section_contracts.json")
    section_dossiers = _read_json_object(output_dir / "section_dossiers.json")
    contract_map = contracts.get("contracts") if isinstance(contracts.get("contracts"), dict) else {}
    packs = artifact.get("packs") if isinstance(artifact.get("packs"), dict) else {}
    pack_keys = sorted(packs or set(contract_map) | set(section_dossiers))
    blocked_sections = sorted(
        key
        for key, value in contract_map.items()
        if isinstance(value, dict) and (value.get("blocked_reasons") or value.get("status") == "gap")
    )
    citation_ready = sum(
        1
        for value in contract_map.values()
        if isinstance(value, dict) and value.get("citation_evidence_ids")
    )
    return {
        "schema_version": "section_evidence_pack_runtime.v1",
        "status": "ready" if pack_keys else "missing",
        "section_count": len(pack_keys),
        "sections": pack_keys,
        "blocked_sections": blocked_sections,
        "citation_ready_section_count": citation_ready,
        "must_use_evidence_count": sum(len(row.get("must_use_evidence_ids") or []) for row in packs.values() if isinstance(row, dict)),
        "unsupported_claim_count": sum(len(row.get("unsupported_claim_ids") or []) for row in packs.values() if isinstance(row, dict)),
        "missing_evidence_count": sum(len(row.get("missing_evidence_ids") or []) for row in packs.values() if isinstance(row, dict)),
        "source_files": {
            "section_evidence_packs": str(output_dir / "section_evidence_packs.json"),
            "report_section_contracts": str(output_dir / "report_section_contracts.json"),
            "section_dossiers": str(output_dir / "section_dossiers.json"),
        },
    }


def _run_manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    stale = manifest.get("stale_artifacts") if isinstance(manifest.get("stale_artifacts"), dict) else {}
    return {
        "schema_version": "report_run_manifest_runtime.v1",
        "status": str(manifest.get("status") or "missing"),
        "artifact_count": len(artifacts),
        "artifact_versions": {
            name: str(payload.get("version") or "")
            for name, payload in artifacts.items()
            if isinstance(payload, dict)
        },
        "stale_artifacts": stale,
        "missing_artifacts": list(manifest.get("missing_artifacts") or []),
    }


def _build_generation_execution_summary(output_dir: Path) -> dict[str, Any]:
    run_summary = _read_json_object(output_dir / "run_summary.json")
    collaboration = _read_json_object(output_dir / "agent_collaboration_trace.json")
    tool_trace = _read_json_object(output_dir / "tool_trace.json")
    agents = [item for item in collaboration.get("agents", []) if isinstance(item, dict)]
    failed_agents = [
        {
            "agent": str(item.get("agent") or "unknown"),
            "task_type": str(item.get("task_type") or ""),
            "status": str(item.get("status") or "unknown"),
            "error": str(item.get("error") or ""),
        }
        for item in agents
        if str(item.get("status") or "").lower() not in {"success", "completed", "skipped"}
        or bool(item.get("error"))
    ]
    calls = [item for item in tool_trace.get("calls", []) if isinstance(item, dict)]
    failed_tools = [
        {
            "caller_agent": str(item.get("caller_agent") or ""),
            "tool_name": str(item.get("tool_name") or "unknown"),
            "failure_reason": str(item.get("failure_reason") or ""),
        }
        for item in calls
        if item.get("success") is False
    ]
    executed_agents = [str(item) for item in run_summary.get("executed_agents", []) if str(item)]
    model_usage = run_summary.get("model_usage_by_agent")
    model_usage = model_usage if isinstance(model_usage, dict) else {}
    missing_artifacts = [
        name
        for name in ("evidence.json", "claims.json")
        if not (output_dir / name).exists()
    ]
    trace_available = bool(agents or executed_agents)
    if failed_agents or missing_artifacts:
        status = "failed"
        root_cause = "agent_execution_failed" if failed_agents else "generation_artifact_missing"
    elif not trace_available:
        status = "trace_missing"
        root_cause = "generation_trace_missing"
    elif failed_tools:
        status = "degraded"
        root_cause = "tool_execution_degraded"
    else:
        status = "ready"
        root_cause = "none"
    return {
        "schema_version": "generation_execution_runtime.v1",
        "status": status,
        "root_cause": root_cause,
        "trace_available": trace_available,
        "agent_count": len(agents) or len(executed_agents),
        "executed_agents": executed_agents or [str(item.get("agent") or "") for item in agents],
        "failed_agent_count": len(failed_agents),
        "failed_agents": failed_agents,
        "tool_call_count": len(calls),
        "failed_tool_count": len(failed_tools),
        "failed_tools": failed_tools[:20],
        "model_usage_by_agent": model_usage,
        "missing_artifacts": missing_artifacts,
        "source_files": {
            "run_summary": str(output_dir / "run_summary.json"),
            "agent_collaboration_trace": str(output_dir / "agent_collaboration_trace.json"),
            "tool_trace": str(output_dir / "tool_trace.json"),
        },
    }


def _build_section_verification_manifest(*, output_dir: Path, report_dir: Path) -> dict[str, Any]:
    contracts = _read_json_object(output_dir / "report_section_contracts.json")
    remediation = _read_json_object(output_dir / "quality_remediation_plan.json")
    packs = _read_json_object(output_dir / "section_evidence_packs.json")
    markdown = ""
    report_md = report_dir / "report.md"
    if report_md.exists():
        markdown = report_md.read_text(encoding="utf-8")
    artifact = write_section_verification(
        output_dir,
        markdown=markdown,
        report_section_contracts=contracts,
        quality_remediation_plan=remediation,
        section_evidence_packs=packs,
    )
    return {
        "schema_version": "section_verification_runtime.v1",
        "artifact_schema_version": artifact.get("schema_version"),
        "status": artifact.get("status", "failed"),
        "formal_delivery_allowed": bool(artifact.get("formal_delivery_allowed", False)),
        "contract_count": len(contracts.get("contracts") if isinstance(contracts.get("contracts"), dict) else {}),
        "failed_section_count": len(artifact.get("failed_sections") or []),
        "failed_sections": list(artifact.get("failed_sections") or []),
        "issue_count": int(artifact.get("issue_count") or 0),
        "report_markdown_chars": len(markdown),
        "source_files": {
            "report_section_contracts": str(output_dir / "report_section_contracts.json"),
            "quality_remediation_plan": str(output_dir / "quality_remediation_plan.json"),
            "section_evidence_packs": str(output_dir / "section_evidence_packs.json"),
            "section_verification": str(output_dir / "section_verification.json"),
            "report_md": str(report_md),
        },
    }


def _report_title_from_markdown(markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _strip_report_title(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:])
    return str(markdown or "")


def _mark_report_html_as_delivery_blocked(report_dir: Path, quality_result: dict[str, Any]) -> None:
    report_dir = Path(report_dir)
    html_path = report_dir / "report.html"
    markdown_path = report_dir / "report.md"
    if not html_path.exists() and not markdown_path.exists():
        return
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else html_path.read_text(encoding="utf-8")
    title = _report_title_from_markdown(markdown) or "研报草稿"
    blockers = [str(item.get("message") or item.get("category") or item) for item in _top_quality_issues(quality_result)[:5]]
    html = render_professional_html_report(
        markdown=markdown,
        title=title,
        delivery_status="blocked_quality_gate_failed",
        top_blockers=blockers,
        quality_blocked=True,
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
    return output


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


def build_runtime_observability(task: ReportTask, llm_runs: list[LLMRun], tool_runs: list[ToolRun] | None = None) -> dict[str, Any]:
    """Aggregate request tracing, node latency, and LLM usage for one task."""

    metadata = task.metadata_json or {}
    runtime = metadata.get("report_runtime") if isinstance(metadata.get("report_runtime"), dict) else {}
    events = runtime.get("events") if isinstance(runtime.get("events"), list) else []
    node_latency = runtime.get("node_latency_ms") if isinstance(runtime.get("node_latency_ms"), dict) else {}
    prompt_tokens = sum(int(item.prompt_tokens or 0) for item in llm_runs)
    completion_tokens = sum(int(item.completion_tokens or 0) for item in llm_runs)
    total_tokens = sum(int(item.total_tokens or 0) for item in llm_runs)
    cost_raw = sum(float(item.cost_usd or 0.0) for item in llm_runs)
    cost_usd = round(cost_raw, 8)
    run_count_sum = len(llm_runs)
    pricing_status = "not_configured" if cost_raw == 0.0 and run_count_sum > 0 else "available" if cost_raw > 0 else "no_runs"
    llm_latency_ms = sum(int(item.latency_ms or 0) for item in llm_runs)
    tool_runs = tool_runs or []
    tool_latency_ms = sum(int(item.duration_ms or 0) for item in tool_runs)
    latest_tool = tool_runs[0] if tool_runs else None
    failed_tools = [item for item in tool_runs if item.status == "failed"]
    latest_failed_tool = failed_tools[0] if failed_tools else None
    retry_count = sum(max(0, int(item.attempt_count or 1) - 1) for item in tool_runs)
    last_node = events[-1].get("node") if events and isinstance(events[-1], dict) else None
    current_node = None if runtime.get("checkpoint_status") == "completed" else (last_node or task.current_stage)
    runtime_failure = metadata.get("runtime_failure") if isinstance(metadata.get("runtime_failure"), dict) else {}
    failure_root_cause = None
    if latest_failed_tool is not None:
        failure_root_cause = {
            "type": latest_failed_tool.error_type or "tool_execution_failed",
            "message": latest_failed_tool.error_message,
            "tool_name": latest_failed_tool.tool_name,
            "langgraph_node": latest_failed_tool.langgraph_node,
        }
    elif runtime_failure:
        failure_root_cause = {
            "type": runtime_failure.get("error_type") or "runtime_failed",
            "message": runtime_failure.get("message"),
            "tool_name": None,
            "langgraph_node": current_node,
        }
    elapsed_ms = None
    if task.started_at and task.finished_at:
        elapsed_ms = round((task.finished_at - task.started_at).total_seconds() * 1000, 3)
    return {
        "schema_version": "report_runtime_observability.v1",
        "trace_context": {
            "request_id": str(metadata.get("request_id") or task.task_id),
            "run_id": str(metadata.get("run_id") or task.task_id),
            "task_id": task.task_id,
        },
        "checkpoint_status": runtime.get("checkpoint_status", "not_started"),
        "last_node": last_node,
        "current_node": current_node,
        "node_latency_ms": node_latency,
        "total_node_latency_ms": round(sum(float(value or 0.0) for value in node_latency.values()), 3),
        "task_elapsed_ms": elapsed_ms,
        "llm": {
            "run_count": run_count_sum,
            "failed_run_count": sum(1 for item in llm_runs if item.status == "failed"),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "pricing_status": pricing_status,
            "latency_ms": llm_latency_ms,
        },
        "tools": {
            "run_count": len(tool_runs),
            "failed_run_count": sum(1 for item in tool_runs if item.status == "failed"),
            "latency_ms": tool_latency_ms,
            "retry_count": retry_count,
            "current_tool": serialize_tool_run(latest_tool) if latest_tool is not None else None,
            "failure_root_cause": failure_root_cause,
            "by_agent": _tool_run_counts(tool_runs, key="agent_name"),
            "by_tool": _tool_run_counts(tool_runs, key="tool_name"),
        },
    }


def serialize_tool_run(item: ToolRun) -> dict[str, Any]:
    return {
        "run_id": item.run_id,
        "task_id": item.task_id,
        "langgraph_node": item.langgraph_node,
        "agent_name": item.agent_name,
        "tool_name": item.tool_name,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "duration_ms": item.duration_ms,
        "input": item.input_json or {},
        "output_summary": item.output_summary_json or {},
        "evidence_ids": item.evidence_ids or [],
        "artifact_paths": item.artifact_paths or [],
        "error_type": item.error_type,
        "error_message": item.error_message,
        "source": item.source,
        "metadata": item.metadata_json or {},
        "created_at": _dt(item.created_at),
    }


def _tool_run_counts(tool_runs: list[ToolRun], *, key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in tool_runs:
        value = str(getattr(item, key, None) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def _supports_agent_stage_callback(factory: Callable[..., Any]) -> bool:
    try:
        return isinstance(factory, type) and issubclass(factory, MultiAgentOrchestrator)
    except TypeError:
        return False


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


def _resolve_task_bindings(session: Session, *, payload: dict[str, Any], symbol: str) -> tuple[int | None, int | None]:
    """Bind queued tasks to real workspace/company rows when the UI omits IDs."""

    workspace_id = _optional_int(payload.get("workspace_id"))
    if workspace_id is None:
        workspace_id = session.scalar(
            select(Workspace.id).where(Workspace.is_active.is_(True)).order_by(Workspace.id.asc()).limit(1)
        )
    if workspace_id is None:
        workspace = Workspace(
            name="默认投研空间",
            slug="default-research",
            description="工作台自动创建的默认投研空间",
            is_active=True,
        )
        session.add(workspace)
        session.flush()
        workspace_id = workspace.id

    company_id = _optional_int(payload.get("company_id"))
    if company_id is not None:
        company = session.get(Company, company_id)
        if company is not None and _symbols_refer_to_same_listing(company.symbol, symbol):
            canonical_company = _find_company_by_symbol(session, symbol)
            if canonical_company is not None and canonical_company.id != company.id:
                return workspace_id, canonical_company.id
            _apply_company_identity(company, payload=payload, symbol=symbol)
            return workspace_id, company.id

    market = str(payload.get("market") or infer_market_from_symbol(symbol).get("market") or "").strip().lower()
    company = _find_company_by_symbol(session, symbol)
    if company is None:
        aliases = [item for item in _legacy_symbol_aliases(symbol) if item != symbol.upper()]
        company = session.scalar(select(Company).where(func.upper(Company.symbol).in_(aliases)).order_by(Company.id.asc()).limit(1)) if aliases else None
    if company is None:
        company = Company(
            name=str(payload.get("company_name") or symbol).strip(),
            symbol=symbol,
            market=market or None,
            aliases=[symbol],
        )
        session.add(company)
        session.flush()
    else:
        _apply_company_identity(company, payload=payload, symbol=symbol)
    return workspace_id, company.id


def _normalize_task_identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    requested = str(normalized.get("symbol") or normalized.get("company_name") or "AAPL").strip()
    identity = resolve_company_identity(requested, default=requested.upper())
    if not identity.is_listed and normalized.get("company_name"):
        identity = resolve_company_identity(str(normalized["company_name"]), default=requested.upper())
    if not identity.is_listed or not identity.canonical_symbol:
        return normalized

    original_name = str(normalized.get("company_name") or "").strip()
    normalized.update(
        {
            "symbol": identity.canonical_symbol,
            "company_name": original_name if original_name and original_name.upper() != requested.upper() else (identity.company_name or identity.canonical_symbol),
            "market": identity.market,
            "exchange": identity.exchange,
            "currency": identity.currency,
            "country_region": identity.country_region,
        }
    )
    return normalized


def _repair_persisted_task_identity(session: Session, task: ReportTask) -> None:
    metadata = dict(task.metadata_json or {})
    normalized = _normalize_task_identity_payload(
        {
            "symbol": task.symbol,
            "company_name": metadata.get("company_name"),
            "workspace_id": task.workspace_id,
            "company_id": task.company_id,
        }
    )
    canonical_symbol = str(normalized.get("symbol") or task.symbol).upper()
    if canonical_symbol == str(task.symbol or "").upper() and str(metadata.get("market") or "").lower() not in {"", "unknown"}:
        return

    task.symbol = canonical_symbol
    metadata.update({key: normalized.get(key) for key in ("symbol", "company_name", "market", "exchange", "currency", "country_region")})
    task.metadata_json = metadata
    workspace_id, company_id = _resolve_task_bindings(session, payload=normalized, symbol=canonical_symbol)
    task.workspace_id = task.workspace_id or workspace_id
    task.company_id = company_id
    request_state_path = Path(str(metadata.get("output_dir") or "")) / "request_state.json"
    if request_state_path.exists():
        request_state = _read_json_object(request_state_path)
        request_state["symbol"] = canonical_symbol
        request_state_path.write_text(json.dumps(request_state, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_company_identity(company: Company, *, payload: dict[str, Any], symbol: str) -> None:
    company.symbol = symbol
    company.name = str(payload.get("company_name") or company.name or symbol).strip()
    company.market = str(payload.get("market") or infer_market_from_symbol(symbol).get("market") or company.market or "").strip().lower() or None
    company.aliases = sorted({str(item) for item in [*(company.aliases or []), *_legacy_symbol_aliases(symbol)] if str(item).strip()})


def _find_company_by_symbol(session: Session, symbol: str) -> Company | None:
    return session.scalar(
        select(Company).where(func.upper(Company.symbol) == str(symbol or "").upper()).order_by(Company.id.asc()).limit(1)
    )


def _legacy_symbol_aliases(symbol: str) -> list[str]:
    canonical = str(symbol or "").upper().strip()
    aliases = {canonical}
    if canonical.endswith((".SS", ".SZ", ".HK")):
        aliases.add(canonical.rsplit(".", 1)[0])
    return sorted(aliases)


def _symbols_refer_to_same_listing(left: str | None, right: str | None) -> bool:
    return bool(set(_legacy_symbol_aliases(str(left or ""))) & set(_legacy_symbol_aliases(str(right or ""))))


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


_DEFAULT_SECTION_REPAIR_PROMPT = """Rewrite one failed Chinese equity-research report section.
Return JSON with only section_markdown. Do not include the section heading.
Use the canonical metrics and must-use evidence in the input. Cite evidence IDs in square brackets.
Exceed verification.min_chars by at least 30 Chinese characters; do not satisfy length with lists or repeated filler.
Do not invent facts, use placeholders, expose internal field names, or paste raw English source paragraphs.
Give a concrete analytical conclusion, supporting reasons, risks, and evidence boundaries where relevant.
Only repair the requested section."""


class SectionRepairModelBackend:
    """ModelAdapter bridge used by the observable LLM harness."""

    def __init__(self, adapter: ModelAdapter) -> None:
        self.adapter = adapter
        self.name = f"section-repair:{adapter.model_name}"

    def generate_structured(self, prompt: str, schema: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        del schema
        payload = json.dumps(kwargs, ensure_ascii=False, default=str)
        return self.adapter.generate_json(
            prompt=f"{prompt}\n\nSection repair input:\n{payload}",
            system_prompt=(
                "You are a financial report section repair agent. Return valid JSON only. "
                "The section must be written in Chinese and grounded in the supplied evidence."
            ),
            extra_body={"max_tokens": min(self.adapter.max_tokens, 2400)},
        )


def _build_role_model_adapter(*, config_path: str, role: str, execution_tier: str) -> ModelAdapter:
    config = load_config(config_path)
    routes = config.get("agent_model_routes") if isinstance(config, dict) else {}
    defaults = routes.get("defaults", {}) if isinstance(routes, dict) and isinstance(routes.get("defaults"), dict) else {}
    tier = str(execution_tier or "delivery").lower()
    role_route = routes.get(role) if isinstance(routes, dict) else None
    if isinstance(role_route, dict):
        profile = str(role_route.get(tier) or role_route.get("delivery") or defaults.get(tier) or defaults.get("delivery") or "flash")
    elif isinstance(role_route, str):
        profile = role_route
    else:
        profile = str(defaults.get(tier) or defaults.get("delivery") or "flash")
    try:
        return ModelAdapter.from_profile(profile=profile, config_path=config_path, fallback_section="agent_model")
    except Exception:
        return ModelAdapter.from_config(config_path=config_path)


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
