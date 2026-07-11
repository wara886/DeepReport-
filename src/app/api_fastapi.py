"""ASGI deployment surface for the existing FinSight workbench."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
from typing import Any, Optional
import uuid

from fastapi import BackgroundTasks
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from src.app.workbench_frontend import render_workbench_html
from src.services.claim_review_service import ClaimNotFound, ClaimReviewService
from src.services.dashboard_service import DashboardService
from src.services.datasource_service import DataSourceConflict, DataSourceNotFound, DataSourceService
from src.services.dictionary_service import DictionaryConflict, DictionaryService, DictionaryTermNotFound
from src.services.document_service import DocumentNotFound, DocumentService
from src.services.entity_service import EntityConflict, EntityNotFound, EntityService
from src.services.evidence_service import EvidenceNotFound, EvidenceService
from src.services.evaluation_service import EvaluationService
from src.services.export_service import ExportNotReady, ExportService, ExportTaskNotFound
from src.services.financial_fact_service import FinancialFactConflict, FinancialFactNotFound, FinancialFactService
from src.services.ingestion_service import IngestionBatchConflict, IngestionBatchNotFound, IngestionService
from src.services.investment_signal_service import (
    InvestmentSignalConflict,
    InvestmentSignalNotFound,
    InvestmentSignalService,
)
from src.services.llm_run_service import LLMRunNotFound, LLMRunService
from src.services.manual_import_service import ManualImportConflict, ManualImportService
from src.services.promptops_service import PromptOpsConflict, PromptOpsService, PromptTemplateNotFound
from src.services.report_task_service import (
    ReportTaskConflict,
    ReportTaskNotFound,
    ReportTaskService,
)
from src.services.task_analysis_service import TaskAnalysisService
from src.services.workspace_service import (
    WorkspaceCompanyNotFound,
    WorkspaceConflict,
    WorkspaceNotFound,
    WorkspaceService,
)

# Mode-aware default roots
USER_OUTPUT_DIR = "data/outputs_user"
USER_REPORT_DIR = "data/reports_user"
DEV_OUTPUT_DIR = "data/outputs_dev"
DEV_REPORT_DIR = "data/reports_dev"


def create_fastapi_app(
    *,
    output_dir: Optional[str] = None,
    report_dir: Optional[str] = None,
    config_path: str = "configs/model_backends.yaml",
    memory_root: str = "memory/chat",
    mode: str = "user",
    database_url: Optional[str] = None,
    report_task_service: Optional[ReportTaskService] = None,
    orchestrator_factory: Any = None,
) -> FastAPI:
    """Expose the FinSight workbench and API as one ASGI application."""

    # Apply mode-aware defaults
    if output_dir is None:
        output_dir = USER_OUTPUT_DIR if mode == "user" else DEV_OUTPUT_DIR
    if report_dir is None:
        report_dir = USER_REPORT_DIR if mode == "user" else DEV_REPORT_DIR

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            task_service = getattr(app.state, "report_task_service", None)
            if task_service is not None:
                task_service.close()

    app = FastAPI(
        title="FinSight DeepReport++ API",
        version="0.1.0",
        description="Evidence-driven financial research report workbench.",
        lifespan=lifespan,
    )
    app.state.report_task_service = report_task_service or ReportTaskService(
        database_url=database_url,
        output_root=output_dir,
        report_root=report_dir,
        config_path=config_path,
        memory_root=memory_root,
        mode=mode,
        orchestrator_factory=orchestrator_factory,
    )
    app.state.dashboard_service = DashboardService(session_factory=app.state.report_task_service.session)
    app.state.evaluation_service = EvaluationService(session_factory=app.state.report_task_service.session)
    app.state.datasource_service = DataSourceService(session_factory=app.state.report_task_service.session)
    app.state.dictionary_service = DictionaryService(session_factory=app.state.report_task_service.session)
    app.state.evidence_service = EvidenceService(session_factory=app.state.report_task_service.session)
    app.state.claim_review_service = ClaimReviewService(session_factory=app.state.report_task_service.session)
    app.state.document_service = DocumentService(session_factory=app.state.report_task_service.session)
    app.state.entity_service = EntityService(session_factory=app.state.report_task_service.session)
    app.state.export_service = ExportService(session_factory=app.state.report_task_service.session)
    app.state.financial_fact_service = FinancialFactService(session_factory=app.state.report_task_service.session)
    app.state.workspace_service = WorkspaceService(session_factory=app.state.report_task_service.session)
    app.state.ingestion_service = IngestionService(session_factory=app.state.report_task_service.session)
    app.state.manual_import_service = ManualImportService(session_factory=app.state.report_task_service.session)
    app.state.llm_run_service = LLMRunService(session_factory=app.state.report_task_service.session)
    app.state.promptops_service = PromptOpsService(session_factory=app.state.report_task_service.session)
    app.state.investment_signal_service = InvestmentSignalService(session_factory=app.state.report_task_service.session)
    app.state.task_analysis_service = TaskAnalysisService(
        session_factory=app.state.report_task_service.session,
        report_task_service=app.state.report_task_service,
    )
    app.state.artifact_roots = _artifact_roots(
        output_dir=output_dir,
        report_dir=report_dir,
        report_task_service=app.state.report_task_service,
    )

    @app.middleware("http")
    async def attach_request_trace(incoming: Request, call_next: Any) -> Response:
        request_id = str(incoming.headers.get("x-request-id") or f"req_{uuid.uuid4().hex}")
        incoming.state.request_id = request_id
        response = await call_next(incoming)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/health")
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "finsight-deepreport"}

    @app.get("/")
    def index() -> Response:
        return Response(content=render_workbench_html(), media_type="text/html")

    @app.get("/workbench")
    def workbench() -> Response:
        return Response(content=render_workbench_html(), media_type="text/html")

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return Response(status_code=204)

    @app.post("/api/report-tasks")
    async def create_report_task(incoming: Request, background_tasks: BackgroundTasks) -> Response:
        payload = await _json_payload(incoming)
        payload.setdefault("request_id", str(incoming.state.request_id))
        run_async = bool(payload.pop("run_async", payload.pop("async_report_run", False)))
        run_immediately = bool(payload.pop("run_immediately", payload.pop("auto_run", payload.pop("run", False))))
        payload["run_mode"] = "async_generation" if run_immediately and run_async else ("sync_generation" if run_immediately else "queue_only")
        try:
            task = _report_task_service(app).create_task(payload)
            if run_immediately:
                if run_async:
                    background_tasks.add_task(_report_task_service(app).run_task, task["task_id"])
                    task = _report_task_service(app).get_task(task["task_id"])
                else:
                    task = _report_task_service(app).run_task(task["task_id"])
            status_code = 202 if run_immediately and run_async else 201
            return JSONResponse(status_code=status_code, content=task)
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/report-tasks")
    def list_report_tasks(status: str | None = None, symbol: str | None = None, limit: int = 50) -> Response:
        try:
            return JSONResponse(content=_report_task_service(app).list_tasks(status=status, symbol=symbol, limit=limit))
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/report-tasks/{task_id}")
    def get_report_task(task_id: str) -> Response:
        try:
            return JSONResponse(content=_report_task_service(app).get_task(task_id))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/report-tasks/{task_id}/artifacts")
    def get_report_task_artifacts(task_id: str) -> Response:
        try:
            return JSONResponse(content=_report_task_service(app).get_artifacts(task_id))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/report-tasks/{task_id}/runtime")
    def get_report_task_runtime(task_id: str) -> Response:
        try:
            return JSONResponse(content=_report_task_service(app).get_runtime_checkpoint(task_id))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/report-tasks/{task_id}/runtime/resume")
    async def resume_report_task_runtime(task_id: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        decision = payload.get("decision", payload)
        try:
            return JSONResponse(content=_report_task_service(app).resume_runtime(task_id, decision=decision))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/report-tasks/{task_id}/runtime/retry")
    def retry_report_task_runtime_checkpoint(task_id: str) -> Response:
        try:
            return JSONResponse(content=_report_task_service(app).retry_runtime_checkpoint(task_id))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/dashboard/summary")
    def dashboard_summary() -> Response:
        try:
            return JSONResponse(content=_dashboard_service(app).summary())
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/dashboard/funnel")
    def dashboard_funnel() -> Response:
        try:
            return JSONResponse(content=_dashboard_service(app).funnel())
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/evaluation/summary")
    def evaluation_summary(limit: int = 50) -> Response:
        try:
            return JSONResponse(content=_evaluation_service(app).summary(limit=limit))
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/evaluation/report-tasks/{task_id}/diagnostics")
    def evaluation_task_diagnostics(task_id: str) -> Response:
        try:
            return JSONResponse(content=_evaluation_service(app).task_diagnostics(task_id))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/workspaces")
    def list_workspaces(market: str | None = None, active_only: bool = False, limit: int = 50) -> Response:
        try:
            return JSONResponse(
                content=_workspace_service(app).list_workspaces(market=market, active_only=active_only, limit=limit)
            )
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/workspaces")
    async def create_workspace(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_workspace_service(app).create_workspace(payload))
        except WorkspaceConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/workspaces/{workspace_ref}")
    def get_workspace(workspace_ref: str) -> Response:
        try:
            return JSONResponse(content=_workspace_service(app).get_workspace(workspace_ref))
        except WorkspaceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Workspace not found: {workspace_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/workspaces/{workspace_ref}/companies")
    def list_workspace_companies(
        workspace_ref: str,
        q: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(
                content=_workspace_service(app).list_companies(
                    workspace_ref,
                    q=q,
                    active_only=active_only,
                    limit=limit,
                )
            )
        except WorkspaceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Workspace not found: {workspace_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/workspaces/{workspace_ref}/companies")
    async def add_workspace_company(workspace_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_workspace_service(app).add_company(workspace_ref, payload))
        except WorkspaceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Workspace not found: {workspace_ref}"})
        except WorkspaceConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/workspaces/{workspace_ref}/resolve-company")
    def resolve_workspace_company(workspace_ref: str, q: str) -> Response:
        try:
            return JSONResponse(content=_workspace_service(app).resolve_company(workspace_ref, q))
        except WorkspaceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Workspace not found: {workspace_ref}"})
        except WorkspaceCompanyNotFound:
            return JSONResponse(status_code=404, content={"error": f"Company not found in workspace: {q}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/data-sources/seed")
    async def seed_data_sources(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_datasource_service(app).seed_registered_sources(workspace_ref=payload.get("workspace_id") or payload.get("workspace")))
        except DataSourceNotFound as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/data-sources")
    def list_data_sources(
        workspace_id: str | None = None,
        enabled: bool | None = None,
        q: str | None = None,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(
                content=_datasource_service(app).list_sources(
                    workspace_ref=workspace_id,
                    enabled=enabled,
                    q=q,
                    limit=limit,
                )
            )
        except DataSourceNotFound as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/data-sources")
    async def create_data_source(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_datasource_service(app).create_source(payload))
        except DataSourceConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except DataSourceNotFound as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/data-sources/{source_ref}")
    def get_data_source(source_ref: str) -> Response:
        try:
            return JSONResponse(content=_datasource_service(app).get_source(source_ref))
        except DataSourceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Datasource not found: {source_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/dictionary")
    def list_dictionary_terms(
        term_type: str | None = None,
        q: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(
                content=_dictionary_service(app).list_terms(
                    term_type=term_type,
                    q=q,
                    workspace_ref=workspace_id,
                    active_only=active_only,
                    limit=limit,
                )
            )
        except DictionaryConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/dictionary")
    async def create_dictionary_term(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_dictionary_service(app).create_term(payload))
        except DictionaryConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/dictionary/terms/{term_ref}")
    def get_dictionary_term(term_ref: str) -> Response:
        try:
            return JSONResponse(content=_dictionary_service(app).get_term(term_ref))
        except DictionaryTermNotFound:
            return JSONResponse(status_code=404, content={"error": f"Dictionary term not found: {term_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/dictionary/resolve")
    def resolve_dictionary_alias(
        q: str,
        term_type: str | None = None,
        workspace_id: str | None = None,
        market: str | None = None,
    ) -> Response:
        try:
            return JSONResponse(
                content=_dictionary_service(app).resolve_alias(
                    query=q,
                    term_type=term_type,
                    workspace_ref=workspace_id,
                    market=market,
                )
            )
        except DictionaryTermNotFound:
            return JSONResponse(status_code=404, content={"error": f"Dictionary alias not found: {q}"})
        except DictionaryConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/dictionary/resolve-company")
    def resolve_dictionary_company(q: str, workspace_id: str | None = None, market: str | None = None) -> Response:
        try:
            return JSONResponse(content=_dictionary_service(app).resolve_company(q, workspace_ref=workspace_id, market=market))
        except DictionaryTermNotFound:
            return JSONResponse(status_code=404, content={"error": f"Company alias not found: {q}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/dictionary/resolve-metric")
    def resolve_dictionary_metric(q: str, workspace_id: str | None = None) -> Response:
        try:
            return JSONResponse(content=_dictionary_service(app).resolve_metric(q, workspace_ref=workspace_id))
        except DictionaryTermNotFound:
            return JSONResponse(status_code=404, content={"error": f"Metric alias not found: {q}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/data-sources/{source_ref}/enable")
    async def enable_data_source(source_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_datasource_service(app).set_enabled(source_ref, bool(payload.get("enabled", True))))
        except DataSourceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Datasource not found: {source_ref}"})
        except DataSourceConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/data-sources/{source_ref}/health")
    async def mark_data_source_health(source_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_datasource_service(app).mark_health(source_ref, payload))
        except DataSourceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Datasource not found: {source_ref}"})
        except DataSourceConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/ingestion-batches")
    async def create_ingestion_batch(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_ingestion_service(app).create_batch(payload))
        except IngestionBatchConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except IngestionBatchNotFound as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/ingestion-batches")
    def list_ingestion_batches(
        workspace_id: str | None = None,
        status: str | None = None,
        source_key: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> Response:
        try:
            return JSONResponse(
                content=_ingestion_service(app).list_batches(
                    workspace_id=workspace_id,
                    status=status,
                    source_key=source_key,
                    q=q,
                    limit=limit,
                )
            )
        except IngestionBatchNotFound as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/ingestion-batches/{batch_ref}")
    def get_ingestion_batch(batch_ref: str) -> Response:
        try:
            return JSONResponse(content=_ingestion_service(app).get_batch(batch_ref))
        except IngestionBatchNotFound:
            return JSONResponse(status_code=404, content={"error": f"Ingestion batch not found: {batch_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/ingestion-batches/{batch_ref}/start")
    async def start_ingestion_batch(batch_ref: str) -> Response:
        try:
            return JSONResponse(content=_ingestion_service(app).start_batch(batch_ref))
        except IngestionBatchNotFound:
            return JSONResponse(status_code=404, content={"error": f"Ingestion batch not found: {batch_ref}"})
        except IngestionBatchConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/ingestion-batches/{batch_ref}/complete")
    async def complete_ingestion_batch(batch_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_ingestion_service(app).complete_batch(batch_ref, payload))
        except IngestionBatchNotFound:
            return JSONResponse(status_code=404, content={"error": f"Ingestion batch not found: {batch_ref}"})
        except IngestionBatchConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/ingestion-batches/{batch_ref}/fail")
    async def fail_ingestion_batch(batch_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_ingestion_service(app).fail_batch(batch_ref, payload))
        except IngestionBatchNotFound:
            return JSONResponse(status_code=404, content={"error": f"Ingestion batch not found: {batch_ref}"})
        except IngestionBatchConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/ingestion-batches/{batch_ref}/retry")
    async def retry_ingestion_batch(batch_ref: str) -> Response:
        try:
            return JSONResponse(content=_ingestion_service(app).retry_batch(batch_ref))
        except IngestionBatchNotFound:
            return JSONResponse(status_code=404, content={"error": f"Ingestion batch not found: {batch_ref}"})
        except IngestionBatchConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/ingestion-batches/{batch_ref}/cancel")
    async def cancel_ingestion_batch(batch_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_ingestion_service(app).cancel_batch(batch_ref, reason=_optional_string(payload.get("reason"))))
        except IngestionBatchNotFound:
            return JSONResponse(status_code=404, content={"error": f"Ingestion batch not found: {batch_ref}"})
        except IngestionBatchConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/manual-import")
    async def manual_import(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            result = _manual_import_service(app).import_document(payload)
            document = result.get("document") if isinstance(result.get("document"), dict) else {}
            document_id = document.get("id")
            if document_id and document.get("parse_status") == "parsed":
                processed = _document_service(app).process_document(int(document_id))
                result["document"] = processed
                result["processing_status"] = "evidence_ready"
                result["message"] = "文档已解析、切分并进入证据库。"
            else:
                result["processing_status"] = "awaiting_content"
                result["message"] = "文档记录已创建，补充可解析内容后才能进入证据库。"
            return JSONResponse(status_code=200 if result.get("duplicate") else 201, content=result)
        except ManualImportConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/llm-runs")
    def list_llm_runs(
        task_id: str | None = None,
        prompt_key: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(content=_llm_run_service(app).list_runs(task_id=task_id, prompt_key=prompt_key, status=status, limit=limit))
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/llm-runs/{run_ref}")
    def get_llm_run(run_ref: str) -> Response:
        try:
            return JSONResponse(content=_llm_run_service(app).get_run(run_ref))
        except LLMRunNotFound:
            return JSONResponse(status_code=404, content={"error": f"LLM run not found: {run_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/promptops/templates")
    def list_prompt_templates(module: str | None = None, active_only: bool = False, limit: int = 100) -> Response:
        try:
            return JSONResponse(content=_promptops_service(app).list_templates(module=module, active_only=active_only, limit=limit))
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/promptops/templates")
    async def create_prompt_template(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_promptops_service(app).create_template(payload))
        except PromptOpsConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/promptops/templates/{template_ref}/versions")
    async def create_prompt_version(template_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_promptops_service(app).add_version(template_ref, payload))
        except PromptTemplateNotFound:
            return JSONResponse(status_code=404, content={"error": f"Prompt template not found: {template_ref}"})
        except PromptOpsConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/promptops/templates/{template_ref}/versions/{version_ref}/activate")
    async def activate_prompt_version(template_ref: str, version_ref: str) -> Response:
        try:
            return JSONResponse(content=_promptops_service(app).set_active_version(template_ref, version_ref))
        except PromptTemplateNotFound:
            return JSONResponse(status_code=404, content={"error": f"Prompt version not found: {version_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/promptops/templates/{template_ref}/active")
    async def set_prompt_template_active(template_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_promptops_service(app).set_template_active(template_ref, bool(payload.get("active", True))))
        except PromptTemplateNotFound:
            return JSONResponse(status_code=404, content={"error": f"Prompt template not found: {template_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/promptops/templates/{prompt_key}/active")
    def resolve_prompt_active_version(prompt_key: str) -> Response:
        try:
            return JSONResponse(content=_promptops_service(app).resolve_active_version(prompt_key))
        except PromptTemplateNotFound:
            return JSONResponse(status_code=404, content={"error": f"Active prompt version not found: {prompt_key}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/promptops/templates/{prompt_key}/test-run")
    async def test_prompt_template(prompt_key: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_promptops_service(app).test_prompt(prompt_key, payload))
        except PromptTemplateNotFound:
            return JSONResponse(status_code=404, content={"error": f"Prompt template not found: {prompt_key}"})
        except PromptOpsConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/promptops/templates/{template_ref}")
    def get_prompt_template(template_ref: str) -> Response:
        try:
            return JSONResponse(content=_promptops_service(app).get_template(template_ref))
        except PromptTemplateNotFound:
            return JSONResponse(status_code=404, content={"error": f"Prompt template not found: {template_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/evidence")
    def list_evidence(
        company: str | None = None,
        period: str | None = None,
        source_type: str | None = None,
        trust_level: str | None = None,
        task_id: str | None = None,
        q: str | None = None,
        mode: str | None = None,
        limit: int = 50,
    ) -> Response:
        try:
            return JSONResponse(
                content=_evidence_service(app).list_evidence(
                    company=company,
                    period=period,
                    source_type=source_type,
                    trust_level=trust_level,
                    task_id=task_id,
                    q=q,
                    mode=mode,
                    limit=limit,
                )
            )
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/evidence/{evidence_ref}")
    def get_evidence(evidence_ref: str) -> Response:
        try:
            return JSONResponse(content=_evidence_service(app).get_evidence(evidence_ref))
        except EvidenceNotFound:
            return JSONResponse(status_code=404, content={"error": f"Evidence not found: {evidence_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/entities")
    def list_entities(
        entity_type: str | None = None,
        q: str | None = None,
        market: str | None = None,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(
                content=_entity_service(app).list_entities(
                    entity_type=entity_type,
                    q=q,
                    market=market,
                    limit=limit,
                )
            )
        except EntityConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/entities")
    async def upsert_entity(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_entity_service(app).upsert_entity(payload))
        except EntityConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/entities/{entity_ref}")
    def get_entity(entity_ref: str) -> Response:
        try:
            return JSONResponse(content=_entity_service(app).get_entity(entity_ref))
        except EntityNotFound:
            return JSONResponse(status_code=404, content={"error": f"Entity not found: {entity_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/entities/extract-from-evidence")
    async def extract_entities_from_evidence(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        evidence_ref = payload.get("evidence_id") or payload.get("evidence_ref") or payload.get("id")
        try:
            return JSONResponse(status_code=201, content=_entity_service(app).extract_from_evidence(evidence_ref))
        except EntityConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/entities/extract-from-task")
    async def extract_entities_from_task(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        task_id = payload.get("task_id") or payload.get("id")
        try:
            return JSONResponse(status_code=201, content=_entity_service(app).extract_from_task(task_id))
        except EntityConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/entity-relations")
    def list_entity_relations(
        relation_type: str | None = None,
        entity_id: int | None = None,
        q: str | None = None,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(
                content=_entity_service(app).list_relations(
                    relation_type=relation_type,
                    entity_id=entity_id,
                    q=q,
                    limit=limit,
                )
            )
        except EntityConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/entity-relations")
    async def upsert_entity_relation(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_entity_service(app).upsert_relation(payload))
        except (EntityConflict, EntityNotFound) as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/graph/summary")
    def entity_graph_summary(limit: int = 100) -> Response:
        try:
            return JSONResponse(content=_entity_service(app).graph_summary(limit=limit))
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/financial-facts")
    def list_financial_facts(
        company: str | None = None,
        metric: str | None = None,
        period: str | None = None,
        review_status: str | None = None,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(
                content=_financial_fact_service(app).list_facts(
                    company=company,
                    metric=metric,
                    period=period,
                    review_status=review_status,
                    limit=limit,
                )
            )
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/financial-facts")
    async def import_financial_fact(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(status_code=201, content=_financial_fact_service(app).import_fact(payload))
        except FinancialFactConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/financial-facts/{fact_id}")
    def get_financial_fact(fact_id: int) -> Response:
        try:
            return JSONResponse(content=_financial_fact_service(app).get_fact(fact_id))
        except FinancialFactNotFound:
            return JSONResponse(status_code=404, content={"error": f"Financial fact not found: {fact_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/investment-signals")
    def list_investment_signals(
        company: str | None = None,
        period: str | None = None,
        signal_type: str | None = None,
        status: str | None = None,
        task_id: str | None = None,
        q: str | None = None,
        limit: int = 100,
    ) -> Response:
        try:
            return JSONResponse(
                content=_investment_signal_service(app).list_signals(
                    company=company,
                    period=period,
                    signal_type=signal_type,
                    status=status,
                    task_id=task_id,
                    q=q,
                    limit=limit,
                )
            )
        except InvestmentSignalConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/investment-signals/generate")
    async def generate_investment_signals(incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(
                status_code=201,
                content=_investment_signal_service(app).generate_signals(
                    company=_optional_string(payload.get("company") or payload.get("symbol")),
                    period=_optional_string(payload.get("period")),
                    task_id=_optional_string(payload.get("task_id")),
                ),
            )
        except InvestmentSignalConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/investment-signals/{signal_ref}")
    def get_investment_signal(signal_ref: str) -> Response:
        try:
            return JSONResponse(content=_investment_signal_service(app).get_signal(signal_ref))
        except InvestmentSignalNotFound:
            return JSONResponse(status_code=404, content={"error": f"Investment signal not found: {signal_ref}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/report-tasks/{task_id}/analysis")
    def get_report_task_analysis(task_id: str) -> Response:
        try:
            return JSONResponse(content=_task_analysis_service(app).get_analysis_package(task_id))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/investment-signals/{signal_ref}/add-to-task")
    async def add_investment_signal_to_task(signal_ref: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        task_id = _optional_string(payload.get("task_id"))
        if not task_id:
            return JSONResponse(status_code=409, content={"error": "task_id is required"})
        try:
            return JSONResponse(content=_investment_signal_service(app).add_to_report_context(signal_ref, task_id))
        except InvestmentSignalNotFound:
            return JSONResponse(status_code=404, content={"error": f"Investment signal not found: {signal_ref}"})
        except InvestmentSignalConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/claims")
    def list_claims(
        task_id: str | None = None,
        status: str | None = None,
        verification_status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> Response:
        try:
            return JSONResponse(
                content=_claim_review_service(app).list_claims(
                    task_id=task_id,
                    status=status,
                    verification_status=verification_status,
                    q=q,
                    limit=limit,
                )
            )
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/claims/{claim_id}")
    def get_claim(claim_id: int) -> Response:
        try:
            return JSONResponse(content=_claim_review_service(app).get_claim(claim_id))
        except ClaimNotFound:
            return JSONResponse(status_code=404, content={"error": f"Claim not found: {claim_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/documents")
    def list_documents(
        company: str | None = None,
        batch_id: str | None = None,
        status: str | None = None,
        step: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> Response:
        try:
            return JSONResponse(
                content=_document_service(app).list_documents(
                    company=company,
                    batch_id=batch_id,
                    status=status,
                    step=step,
                    q=q,
                    limit=limit,
                )
            )
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/documents/{document_id}")
    def get_document(document_id: int) -> Response:
        try:
            return JSONResponse(content=_document_service(app).get_document(document_id))
        except DocumentNotFound:
            return JSONResponse(status_code=404, content={"error": f"Document not found: {document_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/documents/{document_id}/process")
    def process_document(document_id: int) -> Response:
        """Chunk document content into searchable evidence items.
        Idempotent: already-processed documents skip chunking."""
        try:
            result = _document_service(app).process_document(document_id)
            return JSONResponse(content=result)
        except DocumentNotFound as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/exports")
    def list_export_entries(status: str | None = None, symbol: str | None = None, limit: int = 50) -> Response:
        try:
            return JSONResponse(content=_export_service(app).list_export_entries(status=status, symbol=symbol, limit=limit))
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/exports/{task_id}")
    def get_export_entry(task_id: str) -> Response:
        try:
            return JSONResponse(content=_export_service(app).get_export_entry(task_id))
        except ExportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Export entry not found: {task_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/exports/{task_id}/package")
    def get_export_package(task_id: str) -> Response:
        try:
            return JSONResponse(content=_export_service(app).build_export_package(task_id))
        except ExportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Export entry not found: {task_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/exports/{task_id}/package/files")
    def write_export_package_files(task_id: str) -> Response:
        try:
            return JSONResponse(content=_export_service(app).write_export_package(task_id))
        except ExportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Export entry not found: {task_id}"})
        except ExportNotReady as exc:
            return JSONResponse(status_code=409, content={"error": str(exc), "blocked_reasons": exc.blocked_reasons})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/api/exports/{task_id}/package/files/{filename}")
    def download_export_package_file(task_id: str, filename: str) -> Response:
        try:
            path = _export_service(app).get_package_file(task_id, filename)
            return FileResponse(path)
        except ExportNotReady as exc:
            return JSONResponse(status_code=409, content={"error": str(exc), "blocked_reasons": exc.blocked_reasons})
        except ExportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Export entry not found: {task_id}"})
        except FileNotFoundError:
            return JSONResponse(status_code=404, content={"error": f"Export package file not found: {filename}"})

    @app.post("/api/claims/{claim_id}/approve")
    async def approve_claim(claim_id: int, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(
                content=_claim_review_service(app).approve(
                    claim_id,
                    reviewer=_optional_string(payload.get("reviewer")),
                    comment=_optional_string(payload.get("comment")),
                )
            )
        except ClaimNotFound:
            return JSONResponse(status_code=404, content={"error": f"Claim not found: {claim_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/claims/{claim_id}/reject")
    async def reject_claim(claim_id: int, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(
                content=_claim_review_service(app).reject(
                    claim_id,
                    reviewer=_optional_string(payload.get("reviewer")),
                    comment=_optional_string(payload.get("comment")),
                )
            )
        except ClaimNotFound:
            return JSONResponse(status_code=404, content={"error": f"Claim not found: {claim_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/claims/{claim_id}/edit")
    async def edit_claim(claim_id: int, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(
                content=_claim_review_service(app).edit(
                    claim_id,
                    claim_text=_optional_string(payload.get("claim_text")),
                    review_status=_optional_string(payload.get("review_status")),
                    reviewer=_optional_string(payload.get("reviewer")),
                    comment=_optional_string(payload.get("comment")),
                )
            )
        except ClaimNotFound:
            return JSONResponse(status_code=404, content={"error": f"Claim not found: {claim_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/claims/{claim_id}/regenerate")
    async def regenerate_claim(claim_id: int, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(
                content=_claim_review_service(app).regenerate(
                    claim_id,
                    reviewer=_optional_string(payload.get("reviewer")),
                    comment=_optional_string(payload.get("comment")),
                )
            )
        except ClaimNotFound:
            return JSONResponse(status_code=404, content={"error": f"Claim not found: {claim_id}"})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/report-tasks/{task_id}/retry")
    async def retry_report_task(task_id: str, incoming: Request, background_tasks: BackgroundTasks) -> Response:
        payload = await _json_payload(incoming)
        run_async = bool(payload.get("run_async", payload.get("async_report_run", False)))
        run_immediately = bool(payload.get("run_immediately", True))
        try:
            if run_immediately and run_async:
                task = _report_task_service(app).retry_task(task_id, run_immediately=False)
                background_tasks.add_task(_report_task_service(app).run_task, task_id)
                return JSONResponse(status_code=202, content=task)
            task = _report_task_service(app).retry_task(task_id, run_immediately=run_immediately)
            return JSONResponse(content=task)
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/report-tasks/{task_id}/start")
    async def start_report_task(task_id: str, incoming: Request, background_tasks: BackgroundTasks) -> Response:
        payload = await _json_payload(incoming)
        run_async = bool(payload.get("run_async", payload.get("async_report_run", True))
        )
        try:
            if run_async:
                task = _report_task_service(app).start_task(task_id, run_immediately=False)
                background_tasks.add_task(_report_task_service(app).run_task, task_id)
                return JSONResponse(status_code=202, content=task)
            return JSONResponse(content=_report_task_service(app).start_task(task_id, run_immediately=True))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/report-tasks/{task_id}/cancel")
    async def cancel_report_task(task_id: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_report_task_service(app).cancel_task(task_id, reason=_optional_string(payload.get("reason"))))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/report-tasks/{task_id}/archive")
    async def archive_report_task(task_id: str, incoming: Request) -> Response:
        payload = await _json_payload(incoming)
        try:
            return JSONResponse(content=_report_task_service(app).archive_task(task_id, reason=_optional_string(payload.get("reason"))))
        except ReportTaskNotFound:
            return JSONResponse(status_code=404, content={"error": f"Report task not found: {task_id}"})
        except ReportTaskConflict as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/artifacts/{artifact_path:path}")
    def artifacts(artifact_path: str) -> Response:
        local_artifact = _resolve_artifact_path(app, artifact_path)
        if local_artifact is not None:
            guarded = _guard_report_html_delivery_label(app, local_artifact)
            if guarded is not None:
                return guarded
            return FileResponse(local_artifact)
        return JSONResponse(status_code=404, content={"error": f"Artifact not found: {artifact_path}"})

    return app


async def _json_payload(incoming: Request) -> dict[str, Any]:
    try:
        payload = await incoming.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _report_task_service(app: FastAPI) -> ReportTaskService:
    return app.state.report_task_service


def _dashboard_service(app: FastAPI) -> DashboardService:
    return app.state.dashboard_service


def _evaluation_service(app: FastAPI) -> EvaluationService:
    return app.state.evaluation_service


def _datasource_service(app: FastAPI) -> DataSourceService:
    return app.state.datasource_service


def _dictionary_service(app: FastAPI) -> DictionaryService:
    return app.state.dictionary_service


def _evidence_service(app: FastAPI) -> EvidenceService:
    return app.state.evidence_service


def _claim_review_service(app: FastAPI) -> ClaimReviewService:
    return app.state.claim_review_service


def _document_service(app: FastAPI) -> DocumentService:
    return app.state.document_service


def _entity_service(app: FastAPI) -> EntityService:
    return app.state.entity_service


def _export_service(app: FastAPI) -> ExportService:
    return app.state.export_service


def _financial_fact_service(app: FastAPI) -> FinancialFactService:
    return app.state.financial_fact_service


def _workspace_service(app: FastAPI) -> WorkspaceService:
    return app.state.workspace_service


def _ingestion_service(app: FastAPI) -> IngestionService:
    return app.state.ingestion_service


def _manual_import_service(app: FastAPI) -> ManualImportService:
    return app.state.manual_import_service


def _llm_run_service(app: FastAPI) -> LLMRunService:
    return app.state.llm_run_service


def _promptops_service(app: FastAPI) -> PromptOpsService:
    return app.state.promptops_service


def _investment_signal_service(app: FastAPI) -> InvestmentSignalService:
    return app.state.investment_signal_service


def _task_analysis_service(app: FastAPI) -> TaskAnalysisService:
    return app.state.task_analysis_service


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _artifact_roots(
    *,
    output_dir: str | Path,
    report_dir: str | Path,
    report_task_service: ReportTaskService,
) -> list[Path]:
    candidates = [
        Path(report_dir),
        Path(output_dir),
        getattr(report_task_service, "report_root", None),
        getattr(report_task_service, "output_root", None),
        Path(USER_REPORT_DIR),
        Path(USER_OUTPUT_DIR),
        Path(DEV_REPORT_DIR),
        Path(DEV_OUTPUT_DIR),
        Path("data/export_packages"),
    ]
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        root = Path(candidate).resolve()
        if root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


def _resolve_artifact_path(app: FastAPI, artifact_path: str) -> Path | None:
    normalized = artifact_path.split("?", 1)[0].strip().lstrip("/")
    if not normalized or "\x00" in normalized:
        return None
    relative = Path(normalized)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        return None

    roots = list(getattr(app.state, "artifact_roots", []) or [])
    if relative.parts and relative.parts[0] == "runs":
        candidates = [root / relative for root in roots]
    else:
        candidates = [root / relative for root in roots]
        if relative.parts and relative.parts[0] not in {"runs", "export_packages"}:
            candidates.extend(root / "runs" / relative for root in roots)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not _is_within_any_root(resolved, roots):
            continue
        if resolved.is_file():
            return resolved
    return None


def _guard_report_html_delivery_label(app: FastAPI, artifact_path: Path) -> Response | None:
    if artifact_path.name != "report.html":
        return None
    if "runs" not in artifact_path.parts or "reports" not in artifact_path.parts:
        return None

    gate = _find_delivery_gate_for_report(app, artifact_path)
    if not isinstance(gate, dict) or gate.get("delivery_pass") is not False:
        return None

    try:
        html = artifact_path.read_text(encoding="utf-8")
    except OSError:
        return None

    blocked_label = "草稿生成，正式交付阻塞"
    if blocked_label not in html:
        html = re.sub(r"正常(?:生成|交付)\s*·\s*\d{1,3}%", blocked_label, html)
        html = re.sub(r"需复核\s*·\s*\d{1,3}%", blocked_label, html)
        html = html.replace("正常生成", blocked_label)
        html = html.replace("正常交付", blocked_label)
        html = html.replace("需复核", blocked_label)
        if "正式交付阻塞" not in html:
            warning = (
                '<div class="degraded-warning">'
                "<strong>草稿版本：</strong>当前报告未通过正式交付门禁，请先处理质量、证据或复核阻塞原因。"
                "</div>"
            )
            html = html.replace("</header>", f"{warning}</header>", 1)
    return Response(content=html, media_type="text/html")


def _find_delivery_gate_for_report(app: FastAPI, report_html: Path) -> dict[str, Any] | None:
    try:
        parts = report_html.resolve().parts
    except OSError:
        return None
    for idx, part in enumerate(parts):
        if part != "runs" or idx + 2 >= len(parts):
            continue
        run_id = parts[idx + 1]
        if parts[idx + 2] != "reports":
            continue
        for root in list(getattr(app.state, "artifact_roots", []) or []):
            candidate = Path(root) / "runs" / run_id / "outputs" / "delivery_gate.json"
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not _is_within_any_root(resolved, list(getattr(app.state, "artifact_roots", []) or [])):
                continue
            if resolved.is_file():
                try:
                    payload = json.loads(resolved.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return None
                return payload if isinstance(payload, dict) else None
    return None


def _is_within_any_root(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


app = create_fastapi_app()
