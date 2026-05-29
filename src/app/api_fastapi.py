"""ASGI deployment surface for the existing FinSight workbench."""

from __future__ import annotations

from contextlib import asynccontextmanager
import threading
from typing import Any
from urllib import error, request as urlrequest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from src.app.web_ui import DEFAULT_OUTPUT_DIR, DEFAULT_REPORT_DIR, run_ui_server


def create_fastapi_app(
    *,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    memory_root: str = "memory/chat",
    mode: str = "user",
) -> FastAPI:
    """Expose the legacy-stable UI contract behind a deployable ASGI server."""

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

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "finsight-deepreport"}

    @app.get("/")
    def index() -> Response:
        return _forward(app, "/", method="GET")

    @app.get("/api/latest")
    def latest() -> Response:
        return _forward(app, "/api/latest", method="GET")

    @app.post("/api/chat")
    async def chat(incoming: Request) -> Response:
        return _forward(app, "/api/chat", method="POST", body=await incoming.body())

    @app.post("/api/run")
    async def run(incoming: Request) -> Response:
        return _forward(app, "/api/run", method="POST", body=await incoming.body())

    @app.get("/artifacts/{artifact_path:path}")
    def artifacts(artifact_path: str, incoming: Request) -> Response:
        suffix = f"?{incoming.url.query}" if incoming.url.query else ""
        return _forward(app, f"/artifacts/{artifact_path}{suffix}", method="GET")

    return app


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
