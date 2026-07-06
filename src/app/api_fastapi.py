"""ASGI deployment surface for the existing FinSight workbench."""

from __future__ import annotations

from contextlib import asynccontextmanager
import threading
from typing import Any, Optional
from urllib import error, request as urlrequest

from fastapi import BackgroundTasks
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from src.app.web_ui import DEFAULT_OUTPUT_DIR, DEFAULT_REPORT_DIR, run_ui_server
from src.app.workbench_frontend import render_workbench_html
from src.services.claim_review_service import ClaimNotFound, ClaimReviewService
from src.services.dashboard_service import DashboardService
from src.services.document_service import DocumentNotFound, DocumentService
from src.services.evidence_service import EvidenceNotFound, EvidenceService
from src.services.report_task_service import (
    ReportTaskConflict,
    ReportTaskNotFound,
    ReportTaskService,
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
    frontend_port: Optional[int] = None,
    database_url: Optional[str] = None,
    report_task_service: Optional[ReportTaskService] = None,
    orchestrator_factory: Any = None,
) -> FastAPI:
    """Expose the legacy-stable UI contract behind a deployable ASGI server."""

    # Apply mode-aware defaults
    if output_dir is None:
        output_dir = USER_OUTPUT_DIR if mode == "user" else DEV_OUTPUT_DIR
    if report_dir is None:
        report_dir = USER_REPORT_DIR if mode == "user" else DEV_REPORT_DIR

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        server, base_url = run_ui_server(
            host="127.0.0.1",
            port=0,
            mode=mode,
            output_dir=output_dir,
            report_dir=report_dir,
            config_path=config_path,
            memory_root=memory_root,
            frontend_port=frontend_port,
        )
        thread = threading.Thread(target=server.serve_forever, name="finsight-legacy-http", daemon=True)
        thread.start()
        app.state.legacy_base_url = base_url
        try:
            yield
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

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
    app.state.evidence_service = EvidenceService(session_factory=app.state.report_task_service.session)
    app.state.claim_review_service = ClaimReviewService(session_factory=app.state.report_task_service.session)
    app.state.document_service = DocumentService(session_factory=app.state.report_task_service.session)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "finsight-deepreport"}

    @app.get("/")
    def index() -> Response:
        return _forward(app, "/", method="GET")

    @app.get("/workbench")
    def workbench() -> Response:
        return Response(content=render_workbench_html(), media_type="text/html")

    @app.get("/api/latest")
    def latest(incoming: Request) -> Response:
        suffix = f"?{incoming.url.query}" if incoming.url.query else ""
        return _forward(app, f"/api/latest{suffix}", method="GET")

    @app.post("/api/chat")
    async def chat(incoming: Request) -> Response:
        return _forward(app, "/api/chat", method="POST", body=await incoming.body())

    @app.post("/api/run")
    async def run(incoming: Request) -> Response:
        return _forward(app, "/api/run", method="POST", body=await incoming.body())

    @app.post("/api/report-tasks")
    async def create_report_task(incoming: Request, background_tasks: BackgroundTasks) -> Response:
        payload = await _json_payload(incoming)
        run_async = bool(payload.pop("run_async", payload.pop("async_report_run", False)))
        run_immediately = bool(payload.pop("run_immediately", True))
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

    @app.get("/api/evidence")
    def list_evidence(
        company: str | None = None,
        period: str | None = None,
        source_type: str | None = None,
        trust_level: str | None = None,
        task_id: str | None = None,
        q: str | None = None,
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

    @app.get("/artifacts/{artifact_path:path}")
    def artifacts(artifact_path: str, incoming: Request) -> Response:
        suffix = f"?{incoming.url.query}" if incoming.url.query else ""
        return _forward(app, f"/artifacts/{artifact_path}{suffix}", method="GET")

    @app.get("/api/job_status")
    def job_status(incoming: Request) -> Response:
        suffix = f"?{incoming.url.query}" if incoming.url.query else ""
        return _forward(app, f"/api/job_status{suffix}", method="GET")

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


def _evidence_service(app: FastAPI) -> EvidenceService:
    return app.state.evidence_service


def _claim_review_service(app: FastAPI) -> ClaimReviewService:
    return app.state.claim_review_service


def _document_service(app: FastAPI) -> DocumentService:
    return app.state.document_service


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _forward(app: FastAPI, path: str, *, method: str, body: bytes | None = None) -> Response:
    target = f"{app.state.legacy_base_url}{path}"
    headers = {"Content-Type": "application/json"} if body is not None else {}
    outgoing = urlrequest.Request(target, data=body, headers=headers, method=method)
    try:
        with urlrequest.urlopen(outgoing, timeout=120) as response:
            content = response.read()
            status_code = int(response.status)
            content_type = response.headers.get("Content-Type", "application/octet-stream")
    except error.HTTPError as exc:
        content = exc.read()
        status_code = int(exc.code)
        content_type = exc.headers.get("Content-Type", "application/json")
    except Exception as exc:
        return JSONResponse(status_code=502, content={"error": f"upstream request failed: {exc}"})
    return Response(content=content, status_code=status_code, media_type=content_type.split(";", 1)[0])


app = create_fastapi_app()
