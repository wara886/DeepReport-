"""Local Chat-first web workbench for DeepReport++."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List
from urllib.parse import unquote, urlparse

from src.agents.base_agent import AgentTask
from src.agents.multi_agent_orchestrator import (
    MultiAgentOrchestrator,
    attach_pdf_artifacts_to_state,
    build_agent_collaboration_trace,
    merge_task_result,
)
from src.agents.research_blackboard import apply_pre_write_critic, update_blackboard_for_task
from src.app.agent_chat import AgentChatService
from src.app.chat_task_parser import latest_completed_period, llm_parse_chat_task
from src.utils.periods import period_target_date, previous_completed_quarter
from src.data.company_universe import resolve_company_identity
from src.evaluation.delivery_gate import build_delivery_gate_from_outputs, write_delivery_gate_for_outputs
from src.evaluation.llm_report_review import review_report_with_llm_from_paths, write_llm_review_outputs_for_paths
from src.evaluation.quality_remediation import (
    build_quality_remediation_plan_from_outputs,
    write_quality_remediation_plan_for_outputs,
)
from src.evaluation.report_quality import evaluate_report_quality_from_paths, write_quality_outputs_for_paths


DEFAULT_OUTPUT_DIR = "data/outputs/multi_agent"
DEFAULT_REPORT_DIR = "data/reports/multi_agent"
DEFAULT_EXECUTION_MODE = "collaborative"
DEFAULT_ENGINES = "local_real_data,yahoo_finance,tavily,local_evidence"
A_SHARE_ENGINES = (
    "local_real_data,cninfo_announcements,exchange_announcements,"
    "eastmoney_financials,yahoo_finance,eastmoney,local_evidence"
)
US_ENGINES = "local_real_data,sec_edgar,yahoo_finance,independent_macro,local_evidence"
HK_ENGINES = "local_real_data,yahoo_finance,tavily,local_evidence"


def run_ui_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    memory_root: str = "memory/chat",
) -> tuple[ThreadingHTTPServer, str]:
    handler = create_ui_handler(
        output_dir=output_dir,
        report_dir=report_dir,
        config_path=config_path,
        memory_root=memory_root,
    )
    server = ThreadingHTTPServer((host, int(port)), handler)
    actual_host, actual_port = server.server_address
    return server, f"http://{actual_host}:{actual_port}"


def create_ui_handler(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    memory_root: str = "memory/chat",
):
    output_root = Path(output_dir)
    report_root = Path(report_dir)
    chat_service = AgentChatService(
        config_path=config_path,
        memory_root=memory_root,
        output_root=output_root,
        report_root=report_root,
    )
    pending_report_tasks: Dict[str, Dict[str, Any]] = {}
    active_report_runs: Dict[str, Dict[str, Any]] = {}

    def _active_key(session_id: str) -> str:
        return str(session_id or "local")

    def _mark_active_run(
        session_id: str,
        *,
        symbol: str,
        period: str,
        topic: str,
        execution_mode: str,
        source: str,
    ) -> None:
        active_report_runs[_active_key(session_id)] = {
            "session_id": str(session_id or "local"),
            "symbol": symbol,
            "period": period,
            "research_topic": topic,
            "execution_mode": execution_mode,
            "source": source,
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _clear_active_run(session_id: str) -> None:
        active_report_runs.pop(_active_key(session_id), None)

    def _latest_payload() -> Dict[str, Any]:
        latest_dirs = _latest_run_dirs(output_root, report_root)
        payload = load_run_payload(latest_dirs["output_dir"], latest_dirs["report_dir"])
        payload["active_runs"] = _visible_active_runs(payload)
        return payload

    def _visible_active_runs(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        delivery_gate = payload.get("delivery_gate", {}) if isinstance(payload.get("delivery_gate"), dict) else {}
        completed_symbol = str(summary.get("symbol") or "").upper()
        completed_period = str(summary.get("period") or "").upper()
        has_completed_artifacts = bool(summary and delivery_gate)
        visible: List[Dict[str, Any]] = []
        stale_keys: List[str] = []
        for key, run in active_report_runs.items():
            run_symbol = str(run.get("symbol") or "").upper()
            run_period = str(run.get("period") or "").upper()
            if has_completed_artifacts and run_symbol == completed_symbol and run_period == completed_period:
                stale_keys.append(key)
                continue
            visible.append(run)
        for key in stale_keys:
            active_report_runs.pop(key, None)
        return visible

    class WebUIHandler(BaseHTTPRequestHandler):
        server_version = "DeepReportWebUI/0.3"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(render_index_html())
                return
            if parsed.path == "/api/latest":
                self._send_json(_latest_payload())
                return
            if parsed.path.startswith("/artifacts/"):
                self._send_artifact(parsed.path.removeprefix("/artifacts/"))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/run":
                self._handle_run()
                return
            if parsed.path == "/api/chat":
                self._handle_chat()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _handle_run(self) -> None:
            payload = self._read_json_body()
            session_id = str(payload.get("session_id") or "local")
            symbol = str(payload.get("symbol") or "AAPL").strip().upper()
            period = str(payload.get("period") or latest_completed_period()).strip().upper()
            guard = validate_period_for_report(period)
            if not guard["ok"]:
                self._send_json({"error": guard["message"], "period_guard": guard}, status=HTTPStatus.BAD_REQUEST)
                return
            topic = str(payload.get("topic") or f"生成 {symbol} {period} 公司财报研报")
            enable_remote_data = bool(payload.get("enable_remote_data", False))
            engines = _parse_engines(payload.get("engines") or default_engines_for_symbol(symbol, enable_remote_data))
            execution_mode = str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE)
            _mark_active_run(
                session_id,
                symbol=symbol,
                period=period,
                topic=topic,
                execution_mode=execution_mode,
                source="form",
            )
            run_paths = _create_run_dirs(output_root, report_root, symbol, period, execution_mode)
            orchestrator = MultiAgentOrchestrator(
                output_dir=str(run_paths["output_dir"]),
                report_dir=str(run_paths["report_dir"]),
                config_path=config_path,
                memory_enabled=bool(payload.get("memory_enabled", False)),
                memory_root=str(Path(memory_root) / "durable"),
            )
            run_kwargs = {
                    "research_topic": topic,
                    "symbol": symbol,
                    "period": period,
                    "execution_mode": execution_mode,
                    "fast": bool(payload.get("fast", True)),
                    "search_engines": engines,
                    "enable_remote_data": enable_remote_data,
                    "data_source_config_path": str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
            }
            try:
                result = orchestrator.run(**run_kwargs)
                quality_result = run_delivery_quality_pipeline(
                    run_paths["output_dir"],
                    run_paths["report_dir"],
                    config_path,
                    durable_memory_store=getattr(orchestrator, "durable_memory", None),
                    memory_enabled=bool(payload.get("memory_enabled", False)),
                )
                rework_result = run_delivery_rework_loop(
                    orchestrator=orchestrator,
                    output_path=run_paths["output_dir"],
                    report_path=run_paths["report_dir"],
                    config_path=config_path,
                    initial_quality_result=quality_result,
                    run_kwargs=run_kwargs,
                    durable_memory_store=getattr(orchestrator, "durable_memory", None),
                    memory_enabled=bool(payload.get("memory_enabled", False)),
                )
                if rework_result.get("quality_result"):
                    quality_result = rework_result["quality_result"]
                    result["delivery_rework"] = rework_result
                _finalize_run_dirs(run_paths, output_root, report_root, symbol, period, execution_mode, quality_result)
                _clear_active_run(session_id)
                latest = _latest_payload()
                self._send_json({"result": {**result, **quality_result}, "latest": latest})
            except Exception as exc:  # pragma: no cover - defensive UI boundary
                self._send_json({"error": str(exc), "latest": _latest_payload()}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                _clear_active_run(session_id)

        def _handle_chat(self) -> None:
            payload = self._read_json_body()
            message = str(payload.get("message") or "").strip()
            session_id = str(payload.get("session_id") or "local")
            user_id = str(payload.get("user_id") or "local_user")
            symbol = str(payload.get("symbol") or "AAPL").strip().upper()
            period = str(payload.get("period") or latest_completed_period()).strip().upper()
            allow_report_run = bool(payload.get("allow_report_run", True))
            enable_remote_data = bool(payload.get("enable_remote_data", True))
            pending_task = pending_report_tasks.get(session_id)
            confirmed_pending = bool(allow_report_run and pending_task and _is_confirmation_message(message))
            chat_message = message
            if confirmed_pending:
                symbol = str(pending_task.get("symbol") or symbol).strip().upper()
                period = str(pending_task.get("period") or period).strip().upper()
                payload["topic"] = str(pending_task.get("research_topic") or f"生成 {symbol} {period} 公司财报研报")
                chat_message = str(payload["topic"])
                parsed_task = llm_parse_chat_task(
                    chat_message,
                    current_symbol=symbol,
                    current_period=period,
                    config_path=config_path,
                )
                parsed_task = replace(parsed_task, should_run=True, needs_confirmation=False)
                pending_report_tasks.pop(session_id, None)
            else:
                parsed_task = llm_parse_chat_task(message, current_symbol=symbol, current_period=period, config_path=config_path)
            if parsed_task.should_run or parsed_task.needs_confirmation:
                symbol = parsed_task.symbol
                period = parsed_task.period
                payload["topic"] = parsed_task.research_topic
            raw_engines = payload.get("engines")
            if _should_reset_engines_for_parsed_task(parsed_task.should_run or parsed_task.needs_confirmation, raw_engines):
                raw_engines = default_engines_for_symbol(symbol, enable_remote_data)
            engines = _parse_engines(raw_engines or default_engines_for_symbol(symbol, enable_remote_data))
            report_task_requested = bool(
                confirmed_pending
                or parsed_task.should_run
                or parsed_task.needs_confirmation
                or _looks_like_report_request(message)
            )
            if allow_report_run and report_task_requested:
                guard = validate_period_for_report(period)
                if not guard["ok"]:
                    response = chat_service.handle_chat(
                        message=message,
                        session_id=session_id,
                        user_id=user_id,
                        symbol=symbol,
                        period=period,
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                        allow_report_run=False,
                        orchestrator=None,
                        engines=engines,
                        fast=bool(payload.get("fast", True)),
                        execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                        enable_remote_data=enable_remote_data,
                        data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                    )
                    response["mode"] = "period_guard"
                    response["period_guard"] = guard
                    response["parsed_task"] = parsed_task.to_dict()
                    response["answer"] = guard["message"]
                    self._send_json(response)
                    return
                if parsed_task.needs_confirmation:
                    pending_report_tasks[session_id] = parsed_task.to_dict()
                    response = chat_service.handle_chat(
                        message=message,
                        session_id=session_id,
                        user_id=user_id,
                        symbol=symbol,
                        period=period,
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                        allow_report_run=False,
                        orchestrator=None,
                        engines=engines,
                        fast=bool(payload.get("fast", True)),
                        execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                        enable_remote_data=enable_remote_data,
                        data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                    )
                    response["mode"] = "confirm_report"
                    response["parsed_task"] = parsed_task.to_dict()
                    response["answer"] = (
                        "我可以为你生成一份公司/个股研报，请先确认：\n"
                        f"- 公司/标的：{parsed_task.symbol}\n"
                        "- 报告类型：公司/个股跟踪研报\n"
                        f"- 报告期：{parsed_task.period}\n"
                        f"- 当前日期：{date.today().isoformat()}\n"
                        "- 是否可生成：可以，确认后启动检索、分析、写作和质量复核。\n"
                        "请回复确认，我再开始。"
                    )
                    response["answer"] = _confirmation_prompt(parsed_task.symbol, parsed_task.period, engines)
                    self._send_json(response)
                    return
                if confirmed_pending or parsed_task.should_run:
                    execution_mode = str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE)
                    run_paths = _create_run_dirs(output_root, report_root, symbol, period, execution_mode)
                    orchestrator = MultiAgentOrchestrator(
                        output_dir=str(run_paths["output_dir"]),
                        report_dir=str(run_paths["report_dir"]),
                        config_path=config_path,
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                        memory_root=str(Path(memory_root) / "durable"),
                    )
                    run_kwargs = {
                        "research_topic": str(payload.get("topic") or parsed_task.research_topic or chat_message),
                        "symbol": symbol,
                        "period": period,
                        "execution_mode": execution_mode,
                        "fast": bool(payload.get("fast", True)),
                        "search_engines": engines,
                        "enable_remote_data": enable_remote_data,
                        "data_source_config_path": str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                    }
                    _mark_active_run(
                        session_id,
                        symbol=symbol,
                        period=period,
                        topic=str(run_kwargs["research_topic"]),
                        execution_mode=str(run_kwargs["execution_mode"]),
                        source="chat",
                    )
                    try:
                        result = orchestrator.run(**run_kwargs)
                        quality_result = run_delivery_quality_pipeline(
                            run_paths["output_dir"],
                            run_paths["report_dir"],
                            config_path,
                            durable_memory_store=getattr(orchestrator, "durable_memory", None),
                            memory_enabled=bool(payload.get("memory_enabled", True)),
                        )
                        rework_result = run_delivery_rework_loop(
                            orchestrator=orchestrator,
                            output_path=run_paths["output_dir"],
                            report_path=run_paths["report_dir"],
                            config_path=config_path,
                            initial_quality_result=quality_result,
                            run_kwargs=run_kwargs,
                            durable_memory_store=getattr(orchestrator, "durable_memory", None),
                            memory_enabled=bool(payload.get("memory_enabled", True)),
                        )
                        if rework_result.get("quality_result"):
                            quality_result = rework_result["quality_result"]
                        if rework_result.get("rounds"):
                            result["delivery_rework"] = rework_result
                        _finalize_run_dirs(run_paths, output_root, report_root, symbol, period, execution_mode, quality_result)
                        _clear_active_run(session_id)
                        response = {
                            "answer": "已启动并完成多智能体研报生成。右侧报告、引用、图表和轨迹已刷新。",
                            "mode": "report_run",
                            "route_reason": "confirmed report task" if confirmed_pending else "parsed report generation intent",
                            "session_id": session_id,
                            "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                            "tool_trace": [
                                {"stage": "think", "detail": "route=report_run reason=parsed_or_confirmed_report_task"},
                                {"stage": "action", "detail": "start_multi_agent_report_run"},
                                {"stage": "verify", "detail": f"report_run_complete verification={result.get('verification_passed')}"},
                            ],
                            "citations": _read_json(output_root / "citations.json", default=[]),
                            "result": {**result, **quality_result},
                            "parsed_task": parsed_task.to_dict(),
                            "latest": _latest_payload(),
                        }
                        self._send_json(response)
                    except Exception as exc:  # pragma: no cover - defensive UI boundary
                        self._send_json({"error": str(exc), "latest": _latest_payload()}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    finally:
                        _clear_active_run(session_id)
                    return
            orchestrator = None
            run_paths = None
            marked_active = False
            if allow_report_run:
                execution_mode = str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE)
                run_paths = _create_run_dirs(output_root, report_root, symbol, period, execution_mode)
                orchestrator = MultiAgentOrchestrator(
                    output_dir=str(run_paths["output_dir"]),
                    report_dir=str(run_paths["report_dir"]),
                    config_path=config_path,
                    memory_enabled=bool(payload.get("memory_enabled", True)),
                    memory_root=str(Path(memory_root) / "durable"),
                )
                _mark_active_run(
                    session_id,
                    symbol=symbol,
                    period=period,
                    topic=chat_message,
                    execution_mode=execution_mode,
                    source="chat",
                )
                marked_active = True
            try:
                response = chat_service.handle_chat(
                    message=chat_message,
                    session_id=session_id,
                    user_id=user_id,
                    symbol=symbol,
                    period=period,
                    memory_enabled=bool(payload.get("memory_enabled", True)),
                    allow_report_run=allow_report_run,
                    orchestrator=orchestrator,
                    engines=engines,
                    fast=bool(payload.get("fast", True)),
                    execution_mode=str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                    enable_remote_data=enable_remote_data,
                    data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                )
                if parsed_task.should_run or parsed_task.needs_confirmation:
                    response["parsed_task"] = parsed_task.to_dict()
                if response.get("mode") == "report_run":
                    quality_output_root = run_paths["output_dir"] if run_paths else output_root
                    quality_report_root = run_paths["report_dir"] if run_paths else report_root
                    quality_result = run_delivery_quality_pipeline(
                        quality_output_root,
                        quality_report_root,
                        config_path,
                        durable_memory_store=getattr(orchestrator, "durable_memory", None),
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                    )
                    rework_result = run_delivery_rework_loop(
                        orchestrator=orchestrator,
                        output_path=quality_output_root,
                        report_path=quality_report_root,
                        config_path=config_path,
                        initial_quality_result=quality_result,
                        run_kwargs={
                            "research_topic": str(payload.get("topic") or parsed_task.research_topic or message),
                            "symbol": symbol,
                            "period": period,
                            "execution_mode": str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                            "fast": bool(payload.get("fast", True)),
                            "search_engines": engines,
                            "enable_remote_data": enable_remote_data,
                            "data_source_config_path": str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                        },
                        durable_memory_store=getattr(orchestrator, "durable_memory", None) if orchestrator is not None else None,
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                    )
                    if rework_result.get("quality_result"):
                        quality_result = rework_result["quality_result"]
                    if isinstance(response.get("result"), dict):
                        response["result"].update(quality_result)
                        response["result"]["delivery_rework"] = rework_result
                    if run_paths:
                        _finalize_run_dirs(
                            run_paths,
                            output_root,
                            report_root,
                            symbol,
                            period,
                            str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                            quality_result,
                        )
                    if marked_active:
                        _clear_active_run(session_id)
                    response["latest"] = _latest_payload()
                self._send_json(response)
            finally:
                if marked_active:
                    _clear_active_run(session_id)

        def _send_artifact(self, relative_name: str) -> None:
            name = unquote(relative_name)
            candidates = {
                "report.html": report_root / "report.html",
                "report.md": report_root / "report.md",
                "report.json": report_root / "report.json",
            }
            if name.startswith("runs/") and "/reports/" in name:
                path = report_root / name
            else:
                path = candidates.get(name, output_root / name)
            try:
                resolved = path.resolve()
                allowed = any(_is_relative_to(resolved, root.resolve()) for root in [output_root, report_root])
            except OSError:
                allowed = False
            if not allowed or not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                payload = {}
            return payload if isinstance(payload, dict) else {}

        def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return WebUIHandler


def run_delivery_quality_pipeline(
    output_root: str | Path = DEFAULT_OUTPUT_DIR,
    report_root: str | Path = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    durable_memory_store: Any | None = None,
    memory_enabled: bool = False,
) -> Dict[str, Any]:
    output_path = Path(output_root)
    report_path = Path(report_root)
    quality_report = evaluate_report_quality_from_paths(output_path, report_path, run_dir=output_path)
    write_quality_outputs_for_paths(output_path, report_path, quality_report)
    llm_review = review_report_with_llm_from_paths(output_path, report_path, run_dir=output_path, config_path=config_path)
    write_llm_review_outputs_for_paths(output_path, report_path, llm_review)
    delivery_gate = build_delivery_gate_from_outputs(output_path, run_dir=output_path)
    write_delivery_gate_for_outputs(output_path, delivery_gate)
    remediation_plan = build_quality_remediation_plan_from_outputs(output_path, run_dir=output_path)
    write_quality_remediation_plan_for_outputs(output_path, remediation_plan)
    memory_quality_feedback = {}
    if memory_enabled and durable_memory_store is not None and remediation_plan.get("quality_feedback_used"):
        memory_quality_feedback = durable_memory_store.persist_quality_feedback(remediation_plan)
        _update_summary_quality_feedback(output_path / "run_summary.json", memory_quality_feedback)
    return {
        "quality_report": {
            "objective_pass": quality_report.get("objective_pass"),
            "total_score": quality_report.get("total_score"),
        },
        "llm_quality_review": {
            "llm_review_pass": llm_review.get("llm_review_pass"),
            "total_score": llm_review.get("total_score"),
            "model_status": llm_review.get("model_status"),
        },
        "delivery_gate": {
            "delivery_pass": delivery_gate.get("delivery_pass"),
            "verifier_passed": delivery_gate.get("verifier_passed"),
            "objective_pass": delivery_gate.get("objective_pass"),
            "llm_review_pass": delivery_gate.get("llm_review_pass"),
        },
        "remediation_plan": {
            "quality_feedback_used": remediation_plan.get("quality_feedback_used"),
            "required_fixes": remediation_plan.get("required_fixes", [])[:5],
            "failed_sections": remediation_plan.get("failed_sections", []),
            "memory_quality_feedback_used": bool(memory_quality_feedback),
        },
        "top_quality_issues": delivery_gate.get("top_issues", []),
}


def _update_summary_quality_feedback(summary_path: Path, memory_quality_feedback: Dict[str, Any]) -> None:
    summary = _read_json(summary_path, default={})
    if not isinstance(summary, dict):
        return
    summary["memory_quality_feedback_used"] = bool(memory_quality_feedback)
    summary["memory_quality_feedback"] = memory_quality_feedback
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def load_run_payload(
    output_root: str | Path = DEFAULT_OUTPUT_DIR,
    report_root: str | Path = DEFAULT_REPORT_DIR,
) -> Dict[str, Any]:
    output_path = Path(output_root)
    report_path = Path(report_root)
    report_html = report_path / "report.html"
    report_version = _file_version(report_html)
    report_html_url = _report_artifact_url(report_path, "report.html", report_version) if report_html.exists() else ""
    payload = {
        "summary": _read_json(output_path / "run_summary.json"),
        "search_meta": _read_json(output_path / "search_meta.json"),
        "citations": _read_json(output_path / "citations.json", default=[]),
        "charts": _read_json(output_path / "charts.json", default=[]),
        "claims": _read_json(output_path / "claims.json", default=[]),
        "evidence": _read_json(output_path / "evidence.json", default=[]),
        "tables": _read_json(output_path / "tables.json", default=[]),
        "financial_metrics": _read_json(output_path / "financial_metrics.json", default={}),
        "rejected_metrics": _read_json(output_path / "rejected_metrics.json", default=[]),
        "claim_rejection_report": _read_json(output_path / "claim_rejection_report.json", default={}),
        "pdf_manifest": _read_json(output_path / "pdf_manifest.json", default={}),
        "pdf_sections": _read_json(output_path / "pdf_sections.json", default=[]),
        "company_profile_extracted": _read_json(output_path / "company_profile_extracted.json", default={}),
        "mcp_manifest": _read_json(output_path / "mcp_manifest.json", default={}),
        "revision_history": _read_json(output_path / "revision_history.json", default=[]),
        "verification_report": _read_json(output_path / "verification_report.json", default={}),
        "quality_report": _read_json(output_path / "quality_report.json", default={}),
        "llm_quality_review": _read_json(output_path / "llm_quality_review.json", default={}),
        "delivery_gate": _read_json(output_path / "delivery_gate.json", default={}),
        "quality_remediation_plan": _read_json(output_path / "quality_remediation_plan.json", default={}),
        "agent_collaboration_trace": _read_json(output_path / "agent_collaboration_trace.json", default={}),
        "research_blackboard": _read_json(output_path / "research_blackboard.json", default={}),
        "tool_trace": _read_json(output_path / "tool_trace.json", default={}),
        "delivery_rework_history": _read_json(output_path / "delivery_rework_history.json", default=[]),
        "trace": _read_jsonl(output_path / "task_trace.jsonl"),
        "report_markdown": _read_text(report_path / "report.md"),
        "report_html_url": report_html_url,
        "report_artifact_version": report_version,
        "output_dir": str(output_path),
        "report_dir": str(report_path),
    }
    payload["source_health"] = summarize_source_health(payload["search_meta"])
    if isinstance(payload.get("summary"), dict):
        payload["run_id"] = payload["summary"].get("run_id", "")
    payload["artifact_urls"] = _artifact_urls(output_path, report_path)
    return payload


def _file_version(path: Path) -> str:
    try:
        return str(path.stat().st_mtime_ns)
    except OSError:
        return "0"


def _report_artifact_url(report_path: Path, artifact_name: str, version: str | None = None) -> str:
    try:
        normalized = report_path.resolve()
        reports_root = Path(DEFAULT_REPORT_DIR).resolve()
        relative = normalized.relative_to(reports_root)
        url = "/artifacts/" + relative.as_posix().strip("/") + f"/{artifact_name}"
    except (OSError, ValueError):
        url = f"/artifacts/{artifact_name}"
    if version:
        url = f"{url}?v={version}"
    return url


def summarize_source_health(search_meta: Any) -> Dict[str, Any]:
    meta = search_meta.get("engine_meta", search_meta) if isinstance(search_meta, dict) else {}
    if not isinstance(meta, dict):
        return {"status": "unknown", "engines": []}
    engines = []
    for name, item in meta.items():
        row = item if isinstance(item, dict) else {}
        error = str(row.get("error") or "")
        failure = str(row.get("failure_reason") or "")
        skipped = row.get("skipped_files", []) if isinstance(row.get("skipped_files"), list) else []
        optional_degraded = name in {"metaso", "sogou"} and (error or failure)
        engines.append(
            {
                "engine": str(name),
                "status": "degraded_optional" if optional_degraded else "failed" if error else "empty" if failure else "ok",
                "record_count": row.get("record_count", row.get("result_count", "")),
                "returned_hit_count": row.get("returned_hit_count", ""),
                "failure_reason": failure,
                "error": error,
                "skipped_files": skipped,
            }
        )
    failed = [item for item in engines if item["status"] == "failed"]
    degraded = [item for item in engines if item["status"] in {"degraded_optional", "empty"}]
    status = "failed" if failed else "degraded" if degraded else "ok" if engines else "unknown"
    return {"status": status, "engines": engines}


def run_delivery_rework_loop(
    orchestrator: MultiAgentOrchestrator | None,
    output_path: Path,
    report_path: Path,
    config_path: str,
    initial_quality_result: Dict[str, Any],
    run_kwargs: Dict[str, Any],
    durable_memory_store: Any = None,
    memory_enabled: bool = False,
    max_rounds: int = 1,
) -> Dict[str, Any]:
    """Rerun the report in the same request when delivery gate fails."""

    history: List[Dict[str, Any]] = []
    current_quality = dict(initial_quality_result or {})
    if orchestrator is None:
        gate = current_quality.get("delivery_gate", {}) if isinstance(current_quality.get("delivery_gate"), dict) else {}
        if gate.get("delivery_pass") is False:
            history.append(
                {
                    "round": 0,
                    "trigger": "delivery_gate_failed",
                    "status": "skipped",
                    "handled": False,
                    "unfixable_reasons": ["orchestrator unavailable for delivery rework"],
                    "delivery_pass_after_round": False,
                }
            )
            _write_delivery_rework_history(Path(output_path), history)
        return {"rounds": history, "quality_result": current_quality, "reworked": False}
    for round_index in range(1, max_rounds + 1):
        gate = current_quality.get("delivery_gate", {}) if isinstance(current_quality.get("delivery_gate"), dict) else {}
        if gate.get("delivery_pass") is True:
            break
        remediation = _read_json(Path(output_path) / "quality_remediation_plan.json", default={})
        if not remediation:
            break
        repair_constraints = _read_json(Path(output_path) / "repair_constraints.json", default={})
        if isinstance(repair_constraints, dict) and repair_constraints:
            remediation["repair_constraints"] = repair_constraints
        round_record = {
            "round": round_index,
            "trigger": "delivery_gate_failed",
            "status": "running",
            "top_quality_issues": current_quality.get("top_quality_issues", []),
            "responsible_agents": remediation.get("responsible_agents", []),
            "required_fixes": remediation.get("required_fixes", []),
            "rework_mode": "owner_routed",
            "repair_type": _delivery_repair_type(remediation),
        }
        history.append(round_record)
        _write_delivery_rework_history(Path(output_path), history)
        try:
            owner_rework = _run_owner_routed_delivery_rework(
                orchestrator=orchestrator,
                output_path=Path(output_path),
                report_path=Path(report_path),
                remediation=remediation,
                run_kwargs=run_kwargs,
                round_index=round_index,
            )
            round_record.update(owner_rework)
            if not owner_rework.get("handled"):
                round_record["rework_mode"] = "full_pipeline_rerun"
                rerun_kwargs = dict(run_kwargs)
                rerun_kwargs["quality_remediation_plan"] = remediation
                orchestrator.run(**rerun_kwargs)
            current_quality = run_delivery_quality_pipeline(
                output_path,
                report_path,
                config_path,
                durable_memory_store=durable_memory_store,
                memory_enabled=memory_enabled,
            )
            if (
                owner_rework.get("handled")
                and current_quality.get("delivery_gate", {}).get("delivery_pass") is False
                and _needs_full_pipeline_rework(remediation, current_quality)
            ):
                round_record["rework_mode"] = "owner_routed_plus_full_pipeline_rerun"
                round_record["escalated_full_pipeline_rerun"] = True
                rerun_kwargs = dict(run_kwargs)
                rerun_kwargs["quality_remediation_plan"] = remediation
                orchestrator.run(**rerun_kwargs)
                current_quality = run_delivery_quality_pipeline(
                    output_path,
                    report_path,
                    config_path,
                    durable_memory_store=durable_memory_store,
                    memory_enabled=memory_enabled,
                )
            round_record["status"] = "completed"
            round_record["delivery_pass_after_round"] = current_quality.get("delivery_gate", {}).get("delivery_pass")
            if round_record["delivery_pass_after_round"] is False and not round_record.get("target_agents_rerun"):
                round_record["repair_type"] = "unresolved_gap"
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            round_record["status"] = "failed"
            round_record["handled"] = False
            round_record["error"] = str(exc)
            round_record["delivery_pass_after_round"] = False
            round_record["repair_type"] = "unresolved_gap"
            _write_delivery_rework_history(Path(output_path), history)
            break
        _write_delivery_rework_history(Path(output_path), history)
        if current_quality.get("delivery_gate", {}).get("delivery_pass") is True:
            break
    return {"rounds": history, "quality_result": current_quality, "reworked": bool(history)}


def _needs_full_pipeline_rework(remediation: Dict[str, Any], quality_result: Dict[str, Any]) -> bool:
    """Escalate data-layer failures beyond final-answer-only repairs."""

    agents = {
        str(item.get("agent") or "")
        for item in remediation.get("responsible_agents", [])
        if isinstance(item, dict)
    }
    data_agents = {"DeepResearcherAgent", "BrowserAgent", "DeepAnalyzeAgent", "StatementAgent"}
    issue_text = " ".join(
        [
            json.dumps(remediation, ensure_ascii=False),
            json.dumps(quality_result.get("top_quality_issues", []), ensure_ascii=False),
            json.dumps(quality_result.get("delivery_gate", {}).get("issues", []), ensure_ascii=False)
            if isinstance(quality_result.get("delivery_gate"), dict)
            else "",
        ]
    ).lower()
    data_terms = (
        "three_statement",
        "statement",
        "cash flow",
        "balance sheet",
        "income statement",
        "period",
        "fact_period_consistency",
        "financial",
        "metric_lineage",
        "数据",
        "三表",
        "期间",
        "财务",
        "现金流",
    )
    return bool(agents & data_agents) or any(term in issue_text for term in data_terms)


def _delivery_repair_type(remediation: Dict[str, Any]) -> str:
    agents = {
        str(item.get("agent") or "")
        for item in remediation.get("responsible_agents", [])
        if isinstance(item, dict)
    }
    text = json.dumps(remediation, ensure_ascii=False).lower()
    if agents & {"DeepResearcherAgent", "BrowserAgent"}:
        return "data_repair"
    if agents & {"DeepAnalyzeAgent", "StatementAgent", "PeerAgent", "ValuationAgent"}:
        return "analysis_repair"
    if agents == {"FinalAnswerAgent"} or "finalansweragent" in text:
        return "writing_repair"
    if any(term in text for term in ("fact_period_consistency", "non_recurring_gain", "valuation_input_invalid", "dcf", "financial")):
        return "analysis_repair"
    return "writing_repair"


def _run_owner_routed_delivery_rework(
    orchestrator: MultiAgentOrchestrator,
    output_path: Path,
    report_path: Path,
    remediation: Dict[str, Any],
    run_kwargs: Dict[str, Any],
    round_index: int,
) -> Dict[str, Any]:
    """Repair a failed delivery gate by routing issues to owner agents first."""

    if not hasattr(orchestrator, "_execute"):
        return {"handled": False, "unfixable_reasons": ["orchestrator does not expose agent execution"]}
    state = _load_delivery_rework_state(output_path, report_path, remediation, run_kwargs)
    target_agents = _delivery_target_agents(remediation)
    if not target_agents:
        target_agents = ["FinalAnswerAgent"]
    objections = _delivery_objections(remediation, target_agents)
    trace_start = len(getattr(orchestrator, "trace", []) or [])
    role_reruns: List[Dict[str, Any]] = []
    unfixable: List[str] = []
    claim_rebuild_attempted = False
    rejected_claim_count = 0

    if "DeepResearcherAgent" in target_agents:
        try:
            query = str(
                run_kwargs.get("research_topic")
                or state.get("research_topic")
                or f"{state.get('symbol', '')} {state.get('period', '')} company financial statements"
            )
            engines = run_kwargs.get("search_engines")
            if not isinstance(engines, list) or not engines:
                engines = _parse_engines(default_engines_for_symbol(str(state.get("symbol", "")), bool(run_kwargs.get("enable_remote_data", True))))
            research_result = orchestrator._execute(  # type: ignore[attr-defined]
                "research",
                AgentTask(
                    task_id=f"task_delivery_rework_{round_index}_deep_researcher",
                    task_type="deep_researcher",
                    description="Backfill missing primary financial statement evidence for delivery gate failures.",
                    parameters={
                        "query": query,
                        "symbol": state.get("symbol", ""),
                        "period": state.get("period", ""),
                        "topk": 16,
                        "engines": engines,
                        "raw_data_root": str(run_kwargs.get("raw_data_root") or "data/raw/real_data"),
                        "ranking_mode": str(run_kwargs.get("retrieval_ranking_mode") or "hybrid_rerank"),
                        "data_source_config_path": str(run_kwargs.get("data_source_config_path") or "configs/data_sources.yaml"),
                        "enable_remote": bool(run_kwargs.get("enable_remote_data", True)),
                        "quality_remediation_plan": remediation,
                    },
                    dependencies=[],
                    priority=9,
                ),
            )
            merge_task_result(state=state, task_type="deep_researcher", result=research_result)
            state["research_blackboard"] = update_blackboard_for_task(
                state.get("research_blackboard", {}),
                "deep_researcher",
                state,
                research_result.output,
            )
            role_reruns.append({"agent": "DeepResearcherAgent", "task_type": "deep_researcher", "status": research_result.status.value})
        except Exception as exc:  # pragma: no cover - defensive UI path
            unfixable.append(f"DeepResearcherAgent data backfill failed: {exc}")

    if "BrowserAgent" in target_agents or "DeepResearcherAgent" in target_agents:
        try:
            browser_result = orchestrator._execute(  # type: ignore[attr-defined]
                "browser",
                AgentTask(
                    task_id=f"task_delivery_rework_{round_index}_browser",
                    task_type="browser",
                    description="Normalize newly collected evidence before claim rebuild.",
                    parameters={
                        "evidence_candidates": list(state.get("evidence_candidates", [])),
                        "quality_remediation_plan": remediation,
                    },
                    dependencies=[],
                    priority=8,
                ),
            )
            merge_task_result(state=state, task_type="browser", result=browser_result)
            attach_pdf_artifacts_to_state(state)
            state["research_blackboard"] = update_blackboard_for_task(
                state.get("research_blackboard", {}),
                "browser",
                state,
                browser_result.output,
            )
            role_reruns.append({"agent": "BrowserAgent", "task_type": "browser", "status": browser_result.status.value})
        except Exception as exc:  # pragma: no cover - defensive UI path
            unfixable.append(f"BrowserAgent evidence normalization failed: {exc}")

    if "DeepAnalyzeAgent" in target_agents:
        claim_rebuild_attempted = True
        try:
            analyze_result = orchestrator._execute(  # type: ignore[attr-defined]
                "analyze",
                AgentTask(
                    task_id=f"task_delivery_rework_{round_index}_deep_analyze",
                    task_type="deep_analyze",
                    description="Rebuild metrics and claims for delivery gate period/numeric failures.",
                    parameters={
                        "symbol": state.get("symbol", ""),
                        "period": state.get("period", ""),
                        "evidence_records": list(state.get("evidence_records", [])),
                        "raw_data_root": str(run_kwargs.get("raw_data_root") or "data/raw/real_data"),
                        "quality_remediation_plan": remediation,
                    },
                    dependencies=[],
                    priority=8,
                ),
            )
            merge_task_result(state=state, task_type="deep_analyze", result=analyze_result)
            gate = analyze_result.metadata.get("evidence_gate", {}) if isinstance(analyze_result.metadata, dict) else {}
            rejected_claim_count = int(gate.get("rejected_claim_count", 0) or 0) if isinstance(gate, dict) else 0
            role_reruns.append({"agent": "DeepAnalyzeAgent", "task_type": "deep_analyze", "status": analyze_result.status.value})
        except Exception as exc:  # pragma: no cover - defensive UI path
            unfixable.append(f"DeepAnalyzeAgent claim rebuild failed: {exc}")

    for agent_name in target_agents:
        task_type = _delivery_role_task_type(agent_name)
        agent_key = _delivery_agent_key(agent_name)
        if not task_type or not agent_key:
            continue
        try:
            result = orchestrator._execute(  # type: ignore[attr-defined]
                agent_key,
                AgentTask(
                    task_id=f"task_delivery_rework_{round_index}_{task_type}",
                    task_type=task_type,
                    description=f"Repair delivery gate issue assigned to {agent_name}.",
                    parameters={
                        "symbol": state.get("symbol", ""),
                        "period": state.get("period", ""),
                        "evidence_records": list(state.get("evidence_records", [])),
                        "claims": list(state.get("claims", [])),
                        "analysis_artifacts": dict(state.get("analysis_artifacts", {}))
                        if isinstance(state.get("analysis_artifacts"), dict)
                        else {},
                        "research_blackboard": dict(state.get("research_blackboard", {}))
                        if isinstance(state.get("research_blackboard"), dict)
                        else {},
                        "critic_objections": [item for item in objections if item.get("target_agent") == agent_name],
                        "quality_remediation_plan": remediation,
                    },
                    dependencies=[],
                    priority=7,
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive UI path
            unfixable.append(f"{agent_name} rework failed: {exc}")
            continue
        merge_task_result(state=state, task_type=task_type, result=result)
        state["research_blackboard"] = update_blackboard_for_task(
            state.get("research_blackboard", {}),
            task_type,
            state,
            result.output,
        )
        role_reruns.append({"agent": agent_name, "task_type": task_type, "status": result.status.value})

    critic_result = None
    try:
        critic_result = orchestrator._execute(  # type: ignore[attr-defined]
            "critic",
            AgentTask(
                task_id=f"task_delivery_rework_{round_index}_critic",
                task_type="pre_write_critic",
                description="Re-check blackboard after delivery owner repairs.",
                parameters={
                    "research_blackboard": dict(state.get("research_blackboard", {}))
                    if isinstance(state.get("research_blackboard"), dict)
                    else {},
                    "state_snapshot": {
                        "symbol": state.get("symbol", ""),
                        "period": state.get("period", ""),
                        "evidence_count": len(state.get("evidence_records", []))
                        if isinstance(state.get("evidence_records"), list)
                        else 0,
                        "claim_count": len(state.get("claims", [])) if isinstance(state.get("claims"), list) else 0,
                    },
                },
                dependencies=[],
                priority=6,
            ),
        )
        state["pre_write_critic"] = critic_result.output.get("pre_write_critic", {})
        state["research_blackboard"] = apply_pre_write_critic(
            state.get("research_blackboard", {}),
            state.get("pre_write_critic", {}),
        )
    except Exception as exc:  # pragma: no cover - defensive UI path
        unfixable.append(f"CriticAgent recheck failed: {exc}")

    final_editor_rerun = False
    try:
        final_result = orchestrator._execute(  # type: ignore[attr-defined]
            "final_answer",
            AgentTask(
                task_id=f"task_delivery_rework_{round_index}_final_answer",
                task_type="final_answer",
                description="Rewrite report after delivery gate owner-routed repairs.",
                parameters={
                    "research_topic": state.get("research_topic", ""),
                    "symbol": state.get("symbol", ""),
                    "period": state.get("period", ""),
                    "claims": list(state.get("claims", [])),
                    "evidence_records": list(state.get("evidence_records", [])),
                    "revision_request": _delivery_revision_request(remediation, objections),
                    "verification_report": dict(state.get("verification_report", {}))
                    if isinstance(state.get("verification_report"), dict)
                    else {},
                    "prior_markdown": str(state.get("markdown", "")),
                    "conversation_brief": str(state.get("conversation_brief", "")),
                    "tables": dict(state.get("analysis_artifacts", {})).get("tables", [])
                    if isinstance(state.get("analysis_artifacts"), dict)
                    else [],
                    "financial_metrics": dict(state.get("analysis_artifacts", {})).get("financial_metrics", {})
                    if isinstance(state.get("analysis_artifacts"), dict)
                    else {},
                    "pdf_sections": _read_json(output_path / "pdf_sections.json", default=[]),
                    "company_profile": _read_json(output_path / "company_profile_extracted.json", default={}),
                    "research_blackboard": dict(state.get("research_blackboard", {}))
                    if isinstance(state.get("research_blackboard"), dict)
                    else {},
                    "pre_write_critic": dict(state.get("pre_write_critic", {}))
                    if isinstance(state.get("pre_write_critic"), dict)
                    else {},
                    "quality_remediation_plan": remediation,
                    "repair_constraints": dict(state.get("repair_constraints", {}))
                    if isinstance(state.get("repair_constraints"), dict)
                    else {},
                    "degraded_report": True,
                    "pre_write_rework_history": list(state.get("pre_write_rework_history", []))
                    if isinstance(state.get("pre_write_rework_history"), list)
                    else [],
                    "max_claims": 24,
                    "max_evidence": 14,
                    "evidence_content_limit": 700,
                    "max_tokens": 2600,
                },
                dependencies=[],
                priority=7,
            ),
        )
        merge_task_result(state=state, task_type="final_answer", result=final_result)
        final_editor_rerun = True
    except Exception as exc:  # pragma: no cover - defensive UI path
        unfixable.append(f"FinalAnswerAgent delivery repair failed: {exc}")

    new_trace = list(getattr(orchestrator, "trace", []) or [])[trace_start:]
    if final_editor_rerun or role_reruns:
        _write_owner_repair_artifacts(output_path, report_path, state, new_trace)
    return {
        "handled": bool(final_editor_rerun or role_reruns),
        "target_agents": target_agents,
        "target_agents_rerun": role_reruns,
        "critic_rechecked": critic_result is not None,
        "final_editor_rerun": final_editor_rerun,
        "llm_repair_attempted": final_editor_rerun,
        "claim_rebuild_attempted": claim_rebuild_attempted,
        "rejected_claim_count": rejected_claim_count,
        "remaining_unfixable_gaps": unfixable,
        "unfixable_reasons": unfixable,
    }


def _create_run_dirs(output_root: Path, report_root: Path, symbol: str, period: str, execution_mode: str) -> Dict[str, Any]:
    run_id = _make_run_id(symbol, period, execution_mode)
    output_dir = output_root / "runs" / run_id / "outputs"
    report_dir = report_root / "runs" / run_id / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    return {
        "run_id": run_id,
        "output_dir": output_dir,
        "report_dir": report_dir,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }


def _finalize_run_dirs(
    run_paths: Dict[str, Any],
    output_root: Path,
    report_root: Path,
    symbol: str,
    period: str,
    execution_mode: str,
    quality_result: Dict[str, Any],
) -> None:
    output_dir = Path(run_paths["output_dir"])
    report_dir = Path(run_paths["report_dir"])
    summary_path = output_dir / "run_summary.json"
    summary = _read_json(summary_path, default={})
    if not isinstance(summary, dict):
        summary = {}
    summary.update(
        {
            "run_id": run_paths["run_id"],
            "symbol": symbol,
            "period": period,
            "execution_mode": execution_mode,
            "start_time": run_paths.get("started_at", ""),
            "delivery_pass": (quality_result.get("delivery_gate", {}) if isinstance(quality_result.get("delivery_gate"), dict) else {}).get("delivery_pass"),
            "output_dir": str(output_dir),
            "report_dir": str(report_dir),
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = {
        "run_id": run_paths["run_id"],
        "symbol": symbol,
        "period": period,
        "execution_mode": execution_mode,
        "start_time": run_paths.get("started_at", ""),
        "output_dir": str(output_dir),
        "report_dir": str(report_dir),
        "delivery_pass": summary.get("delivery_pass"),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "latest_run.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    _mirror_latest(output_dir, output_root, skip_names={"runs"})
    _mirror_latest(report_dir, report_root, skip_names={"runs"})


def _latest_run_dirs(output_root: Path, report_root: Path) -> Dict[str, Path]:
    newest = _newest_run_dirs(output_root, report_root)
    latest = _read_json(output_root / "latest_run.json", default={})
    if isinstance(latest, dict):
        output_dir = Path(str(latest.get("output_dir") or ""))
        report_dir = Path(str(latest.get("report_dir") or ""))
        if output_dir.exists() and report_dir.exists():
            if newest:
                try:
                    latest_key = _run_id_time_key(output_dir.parent.name)
                    newest_key = _run_id_time_key(newest["output_dir"].parent.name)
                    if newest_key and latest_key and newest_key > latest_key:
                        return newest
                    latest_mtime = max(output_dir.stat().st_mtime, report_dir.stat().st_mtime)
                    newest_mtime = max(newest["output_dir"].stat().st_mtime, newest["report_dir"].stat().st_mtime)
                    if newest_mtime > latest_mtime + 0.001:
                        return newest
                except OSError:
                    return newest
            return {"output_dir": output_dir, "report_dir": report_dir}
    if newest:
        return newest
    return {"output_dir": output_root, "report_dir": report_root}


def _newest_run_dirs(output_root: Path, report_root: Path) -> Dict[str, Path] | None:
    output_runs = output_root / "runs"
    report_runs = report_root / "runs"
    if not output_runs.exists() or not report_runs.exists():
        return None
    candidates: List[tuple[str, float, Path, Path]] = []
    for output_run in output_runs.iterdir():
        output_dir = output_run / "outputs"
        report_dir = report_runs / output_run.name / "reports"
        if not output_dir.exists() or not report_dir.exists():
            continue
        try:
            candidates.append((_run_id_time_key(output_run.name), max(output_dir.stat().st_mtime, report_dir.stat().st_mtime), output_dir, report_dir))
        except OSError:
            continue
    if not candidates:
        return None
    _time_key, _mtime, output_dir, report_dir = max(candidates, key=lambda item: (item[0], item[1]))
    return {"output_dir": output_dir, "report_dir": report_dir}


def _run_id_time_key(run_id: str) -> str:
    match = re.match(r"(\d{8}_\d{6})", str(run_id or ""))
    return match.group(1) if match else ""


def _make_run_id(symbol: str, period: str, execution_mode: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{symbol}_{period}_{execution_mode}").strip("_").lower()
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}"


def _mirror_latest(source: Path, target: Path, skip_names: set[str] | None = None) -> None:
    skip_names = skip_names or set()
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in skip_names:
            continue
        dest = target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, dest)


def _load_delivery_rework_state(
    output_path: Path,
    report_path: Path,
    remediation: Dict[str, Any],
    run_kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    summary = _read_json(output_path / "run_summary.json", default={})
    symbol = str(run_kwargs.get("symbol") or summary.get("symbol") or "").upper()
    period = str(run_kwargs.get("period") or summary.get("period") or "").upper()
    return {
        "research_topic": run_kwargs.get("research_topic") or summary.get("research_topic") or f"{symbol} {period} company report",
        "symbol": symbol,
        "period": period,
        "evidence_records": _read_json(output_path / "evidence.json", default=[]),
        "claims": _read_json(output_path / "claims.json", default=[]),
        "analysis_artifacts": _read_json(output_path / "analysis_artifacts.json", default={}),
        "markdown": _read_text(report_path / "report.md"),
        "html": _read_text(report_path / "report.html"),
        "report_json": _read_json(report_path / "report.json", default={}),
        "citations": _read_json(output_path / "citations.json", default=[]),
        "charts": _read_json(output_path / "charts.json", default=[]),
        "verification_report": _read_json(output_path / "verification_report.json", default={}),
        "search_meta": _read_json(output_path / "search_meta.json", default={}),
        "repair_constraints": _read_json(output_path / "repair_constraints.json", default={}),
        "research_blackboard": _read_json(output_path / "research_blackboard.json", default={}),
        "pre_write_critic": {},
        "quality_remediation_plan": remediation,
        "conversation_brief": "",
        "chart_output_dir": str(output_path / "charts"),
        "collaborative_degraded_report": True,
    }


def _delivery_target_agents(remediation: Dict[str, Any]) -> List[str]:
    rows = remediation.get("responsible_agents", []) if isinstance(remediation.get("responsible_agents"), list) else []
    ordered = ["DeepResearcherAgent", "BrowserAgent", "DeepAnalyzeAgent", "IdentityAgent", "StatementAgent", "PeerAgent", "ValuationAgent", "RiskAgent", "FinalAnswerAgent"]
    found = {str(item.get("agent") or "") for item in rows if isinstance(item, dict)}
    return [agent for agent in ordered if agent in found]


def _delivery_role_task_type(agent_name: str) -> str:
    return {
        "IdentityAgent": "identity_profile",
        "StatementAgent": "three_statement_analysis",
        "PeerAgent": "peer_analysis",
        "ValuationAgent": "valuation_analysis",
        "RiskAgent": "risk_analysis",
    }.get(agent_name, "")


def _delivery_agent_key(agent_name: str) -> str:
    return {
        "IdentityAgent": "identity",
        "StatementAgent": "statement",
        "PeerAgent": "peer",
        "ValuationAgent": "valuation",
        "RiskAgent": "risk",
    }.get(agent_name, "")


def _delivery_objections(remediation: Dict[str, Any], target_agents: List[str]) -> List[Dict[str, Any]]:
    fixes = [str(item) for item in remediation.get("required_fixes", []) if str(item).strip()]
    issues = remediation.get("issues")
    if not isinstance(issues, list) or not issues:
        issues = remediation.get("top_issues", []) if isinstance(remediation.get("top_issues"), list) else []
    top_message = "; ".join(str(item.get("message") or item) for item in issues[:4] if item) or "; ".join(fixes[:4])
    output: List[Dict[str, Any]] = []
    for agent in target_agents:
        output.append(
            {
                "category": "delivery_gate",
                "field": _delivery_field_for_agent(agent),
                "target_agent": agent,
                "severity": "blocker",
                "blocking": True,
                "required_action": "Address delivery quality failure using existing evidence; do not invent missing facts.",
                "message": top_message,
                "required_fixes": fixes[:6],
            }
        )
    return output


def _delivery_field_for_agent(agent_name: str) -> str:
    return {
        "IdentityAgent": "role_outputs.identity_profile",
        "StatementAgent": "role_outputs.three_statement_analysis",
        "PeerAgent": "role_outputs.peer_analysis",
        "ValuationAgent": "role_outputs.valuation_analysis",
        "RiskAgent": "role_outputs.risk_analysis",
        "FinalAnswerAgent": "report.markdown",
    }.get(agent_name, "report")


def _delivery_revision_request(remediation: Dict[str, Any], objections: List[Dict[str, Any]]) -> str:
    failed = [str(item) for item in remediation.get("failed_sections", []) if str(item).strip()]
    fixes = [str(item) for item in remediation.get("required_fixes", []) if str(item).strip()]
    messages = [str(item.get("message") or "") for item in objections if isinstance(item, dict) and item.get("message")]
    lines = [
        "Delivery gate failed. Rewrite only with verified claims/evidence/blackboard facts.",
        "If inputs are missing, write a concrete data-gap impact note instead of placeholders.",
    ]
    if failed:
        lines.append("Failed sections: " + ", ".join(failed[:10]))
    if fixes:
        lines.append("Required fixes: " + " | ".join(fixes[:10]))
    if messages:
        lines.append("Blocking objections: " + " | ".join(messages[:4]))
    return "\n".join(lines)


def _write_owner_repair_artifacts(
    output_path: Path,
    report_path: Path,
    state: Dict[str, Any],
    new_trace: List[Dict[str, Any]],
) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    report_path.mkdir(parents=True, exist_ok=True)
    (output_path / "analysis_artifacts.json").write_text(
        json.dumps(state.get("analysis_artifacts", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "claims.json").write_text(
        json.dumps(state.get("claims", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    artifacts = state.get("analysis_artifacts", {}) if isinstance(state.get("analysis_artifacts"), dict) else {}
    financial_metrics = artifacts.get("financial_metrics", {}) if isinstance(artifacts.get("financial_metrics"), dict) else {}
    (output_path / "financial_metrics.json").write_text(
        json.dumps(financial_metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "rejected_metrics.json").write_text(
        json.dumps(financial_metrics.get("rejected_metrics", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "claim_rejection_report.json").write_text(
        json.dumps(artifacts.get("claim_rejection_report", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "tables.json").write_text(
        json.dumps(artifacts.get("tables", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "pdf_sections.json").write_text(
        json.dumps(artifacts.get("pdf_sections", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "evidence.json").write_text(
        json.dumps(state.get("evidence_records", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "search_meta.json").write_text(
        json.dumps(state.get("search_meta", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "research_blackboard.json").write_text(
        json.dumps(state.get("research_blackboard", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "citations.json").write_text(
        json.dumps(state.get("citations", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "charts.json").write_text(
        json.dumps(state.get("charts", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_path / "report.md").write_text(str(state.get("markdown", "")), encoding="utf-8")
    (report_path / "report.html").write_text(str(state.get("html", "")), encoding="utf-8")
    (report_path / "report.json").write_text(
        json.dumps(state.get("report_json", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if new_trace:
        trace_path = output_path / "task_trace.jsonl"
        previous = _read_jsonl(trace_path)
        combined = previous + [item for item in new_trace if isinstance(item, dict)]
        trace_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in combined) + "\n", encoding="utf-8")
        collaboration_trace = build_agent_collaboration_trace(trace=combined, state=state)
        (output_path / "agent_collaboration_trace.json").write_text(
            json.dumps(collaboration_trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _write_delivery_rework_history(output_path: Path, history: List[Dict[str, Any]]) -> None:
    path = output_path / "delivery_rework_history.json"
    path.write_text(json.dumps(_json_safe_for_artifact(history), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _json_safe_for_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(_json_safe_for_artifact(key)): _json_safe_for_artifact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_for_artifact(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_for_artifact(item) for item in value]
    if isinstance(value, str):
        return "".join(ch if (ord(ch) >= 32 or ch in "\n\r\t") else " " for ch in value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
    return value


def render_index_html() -> str:
    default_topic = "生成 AAPL 2025Q4 公司财报研报"
    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DeepReport++ Chat Workbench</title>
  <style>
    :root {
      --bg: #080808;
      --panel: #141414;
      --panel-2: #202020;
      --text: #f6f6f6;
      --muted: #a7a7a7;
      --line: #333333;
      --accent: #ffffff;
      --ok: #62d98b;
      --warn: #ffd166;
      --bad: #ff6b6b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      letter-spacing: 0;
    }
    button, input, textarea, select { font: inherit; }
    button { cursor: pointer; }
    .hero {
      min-height: 210px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-end;
      padding: 28px 18px 14px;
      gap: 18px;
    }
    .hero h1 {
      margin: 0;
      font-size: clamp(26px, 4vw, 38px);
      font-weight: 760;
    }
    .chat-shell {
      width: min(1000px, calc(100vw - 34px));
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel-2);
      display: grid;
      grid-template-columns: 1fr auto auto;
      align-items: center;
      min-height: 60px;
      padding: 8px 8px 8px 28px;
      gap: 14px;
    }
    #chatInput {
      width: 100%;
      min-height: 34px;
      max-height: 92px;
      resize: vertical;
      border: 0;
      outline: 0;
      background: transparent;
      color: var(--text);
      font-size: 17px;
      line-height: 1.4;
      padding: 6px 0;
    }
    #chatInput::placeholder { color: #b7b7b7; }
    .thinking {
      color: #d8d8d8;
      min-width: 118px;
      text-align: center;
      font-size: 17px;
    }
    .send {
      width: 46px;
      height: 46px;
      border-radius: 999px;
      border: 0;
      background: var(--accent);
      color: #111111;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      font-weight: 800;
    }
    main {
      width: min(1220px, calc(100vw - 32px));
      margin: 0 auto 40px;
    }
    .status-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 14px;
      padding: 10px 12px;
      flex-wrap: wrap;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #101010;
      margin-bottom: 12px;
    }
    .chat-log {
      display: grid;
      gap: 12px;
      margin-bottom: 18px;
    }
    .bubble {
      border: 1px solid var(--line);
      background: #121212;
      border-radius: 8px;
      padding: 14px 16px;
      line-height: 1.65;
      white-space: pre-wrap;
    }
    .bubble.user { justify-self: end; max-width: 82%; background: #1f1f1f; }
    .bubble.assistant { justify-self: start; max-width: 88%; }
    details {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #111111;
      margin: 14px 0;
    }
    summary {
      padding: 12px 14px;
      color: var(--text);
      cursor: pointer;
      font-weight: 650;
    }
    .settings {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 0 14px 14px;
    }
    label { color: var(--muted); font-size: 13px; display: grid; gap: 6px; }
    input, select, textarea {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #090909;
      color: var(--text);
      padding: 9px 10px;
      min-width: 0;
    }
    .span-2 { grid-column: span 2; }
    .checks {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      grid-column: 1 / -1;
    }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      color: var(--text);
    }
    .check input { width: auto; }
    .actions { grid-column: 1 / -1; display: flex; gap: 10px; flex-wrap: wrap; }
    .secondary {
      border: 1px solid var(--line);
      background: #191919;
      color: var(--text);
      border-radius: 6px;
      padding: 9px 12px;
    }
    .tabs { display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0 12px; }
    .tab {
      border: 1px solid var(--line);
      background: #121212;
      color: var(--muted);
      border-radius: 999px;
      padding: 8px 12px;
    }
    .tab.active { background: var(--text); color: #111111; border-color: var(--text); }
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #101010;
      padding: 16px;
      min-height: 240px;
    }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #151515;
    }
    .item h3 { margin: 0 0 8px; font-size: 15px; }
    .timeline { display: grid; gap: 10px; }
    .timeline-step { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #151515; }
    .timeline-step header { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; color: var(--muted); font-size: 12px; }
    .muted { color: var(--muted); }
    .ok { color: var(--ok); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    iframe {
      width: 100%;
      height: 78vh;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }
    pre { overflow: auto; white-space: pre-wrap; word-break: break-word; }
    a { color: #ffffff; }
    @media (max-width: 760px) {
      .hero { min-height: 180px; }
      .chat-shell { grid-template-columns: 1fr auto; border-radius: 28px; padding-left: 18px; }
      .thinking { grid-column: 1 / -1; order: 3; text-align: left; padding-left: 2px; }
      .settings, .checks, .grid { grid-template-columns: 1fr; }
      .span-2 { grid-column: span 1; }
    }
  </style>
</head>
<body>
  <section class="hero">
    <h1>你今天在想些什么？</h1>
    <div class="chat-shell">
      <textarea id="chatInput" rows="1" placeholder="有问题，尽管问"></textarea>
      <div id="thinkingLabel" class="thinking">Ready</div>
      <button id="chatBtn" class="send" title="发送">↑</button>
    </div>
  </section>
  <main>
    <div class="status-line">
      <div id="statusText">Ready</div>
      <div id="runMeta">尚未读取报告</div>
    </div>
    <div id="chatLog" class="chat-log"></div>

    <details id="advancedSettings">
      <summary>高级设置</summary>
      <div class="settings">
        <label>Session ID<input id="sessionId" value="local"></label>
        <label>股票代码<input id="symbol" value="AAPL"></label>
        <label>报告期<input id="period" value="2025Q4"></label>
        <label>执行模式<select id="executionMode"><option value="collaborative">collaborative</option><option value="diagnostic_full">diagnostic_full</option><option value="dynamic">dynamic</option><option value="static">static</option></select></label>
        <label class="span-2">研究主题<input id="topic" value="__DEFAULT_TOPIC__"></label>
        <label class="span-2">搜索/数据源<input id="engines" value="__US_ENGINES__"></label>
        <label class="span-2">数据源配置<input id="dataSourceConfig" value="configs/data_sources.yaml"></label>
        <div class="checks">
          <label class="check"><input type="checkbox" id="allowReportRun" checked>允许 Chat 启动研报</label>
          <label class="check"><input type="checkbox" id="memoryEnabled" checked>启用 memory</label>
          <label class="check"><input type="checkbox" id="realtimeData" checked>实时数据/A股正式源</label>
          <label class="check"><input type="checkbox" id="fastMode" checked>快速模式</label>
        </div>
        <div class="actions">
          <button id="runBtn" class="secondary">按表单生成报告</button>
          <button id="refreshBtn" class="secondary">读取最近输出</button>
        </div>
      </div>
    </details>

    <div class="tabs" id="tabs"></div>
    <section id="content" class="panel"></section>
  </main>

  <script>
    const DEFAULT_ENGINES = "__DEFAULT_ENGINES__";
    const A_SHARE_ENGINES = "__A_SHARE_ENGINES__";
    const US_ENGINES = "__US_ENGINES__";
    const HK_ENGINES = "__HK_ENGINES__";
    const tabs = ["总览", "报告", "多智能体协作", "工具调用", "质量评测", "图表", "引用", "表格", "PDF章节", "公司画像", "Claims", "轨迹", "时间线", "原始数据"];
    let latest = {};
    let activeTab = "总览";

    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m]));
    const asList = (value) => Array.isArray(value) ? value : [];
    const asObj = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};

    function setStatus(text, isError = false) {
      $("statusText").textContent = text;
      $("statusText").className = isError ? "bad" : "";
      $("thinkingLabel").textContent = text.includes("Error") ? "Error" : text.split(" ")[0] || "Thinking";
    }

    function payloadBase() {
      return {
        session_id: $("sessionId").value || "local",
        symbol: $("symbol").value || "AAPL",
        period: $("period").value || "2025Q4",
        topic: $("topic").value,
        engines: $("engines").value,
        execution_mode: $("executionMode").value,
        fast: $("fastMode").checked,
        memory_enabled: $("memoryEnabled").checked,
        allow_report_run: $("allowReportRun").checked,
        enable_remote_data: $("realtimeData").checked,
        data_source_config_path: $("dataSourceConfig").value || "configs/data_sources.yaml"
      };
    }

    function syncEnginesFromSwitch() {
      const symbol = ($("symbol").value || "").toUpperCase();
      if (!$("realtimeData").checked) {
        $("engines").value = DEFAULT_ENGINES;
      } else if (symbol.endsWith(".SS") || symbol.endsWith(".SZ") || /^[0-9]{6}$/.test(symbol)) {
        $("engines").value = A_SHARE_ENGINES;
      } else if (symbol.endsWith(".HK")) {
        $("engines").value = HK_ENGINES;
      } else {
        $("engines").value = US_ENGINES;
      }
    }

    async function postJson(url, payload) {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || JSON.stringify(data));
      return data;
    }

    async function loadLatest() {
      setStatus("Loading");
      const resp = await fetch("/api/latest");
      latest = await resp.json();
      syncFormFromLatest(latest);
      render();
      setStatus("Ready");
    }

    function syncFormFromLatest(data) {
      const summary = asObj(data.summary);
      if (summary.symbol) $("symbol").value = summary.symbol;
      if (summary.period) $("period").value = summary.period;
      if (summary.research_topic) $("topic").value = summary.research_topic;
      if (Array.isArray(summary.search_engines) && summary.search_engines.length) $("engines").value = summary.search_engines.join(",");
      const bits = [];
      if (data.output_dir) bits.push(`输出：${data.output_dir}`);
      if (summary.symbol || summary.period) bits.push(`${summary.symbol || ""} ${summary.period || ""}`.trim());
      if (summary.generated_at) bits.push(summary.generated_at);
      $("runMeta").textContent = bits.length ? bits.join(" | ") : "尚未读取报告";
    }

    async function runReport() {
      setStatus("Planning");
      $("runBtn").disabled = true;
      try {
        const data = await postJson("/api/run", payloadBase());
        latest = data.latest || {};
        syncFormFromLatest(latest);
        appendBubble("assistant", buildResultText(data.result || {}, latest));
        render();
        setStatus("Done");
      } catch (err) {
        appendBubble("assistant", `运行失败：${err.message}`);
        setStatus("Error", true);
      } finally {
        $("runBtn").disabled = false;
      }
    }

    async function sendChat() {
      const message = $("chatInput").value.trim();
      if (!message) return;
      appendBubble("user", message);
      $("chatInput").value = "";
      $("chatBtn").disabled = true;
      setStatus("Thinking");
      try {
        const payload = { ...payloadBase(), message };
        const data = await postJson("/api/chat", payload);
        if (data.mode === "report_run") setStatus("Evaluating");
        const parsed = asObj(data.parsed_task);
        if (parsed.symbol) {
          $("symbol").value = parsed.symbol;
          if (parsed.period) $("period").value = parsed.period;
          if (parsed.research_topic) $("topic").value = parsed.research_topic;
          syncEnginesFromSwitch();
        }
        if (data.latest) {
          latest = data.latest;
          syncFormFromLatest(latest);
        }
        appendBubble("assistant", renderChatAnswer(data));
        render();
        setStatus("Ready");
      } catch (err) {
        appendBubble("assistant", `对话失败：${err.message}`);
        setStatus("Error", true);
      } finally {
        $("chatBtn").disabled = false;
      }
    }

    function renderChatAnswer(data) {
      const lines = [data.answer || "已完成。"];
      const memory = asObj(data.memory_used);
      if (memory.enabled) {
        const prefs = asList(memory.preference_updates).map((x) => `${x.key}=${x.value}`).join("，") || "已启用";
        lines.push(`已使用记忆偏好：${prefs}`);
        lines.push("事实仍以 evidence_id/citation/verifier 为准。");
      }
      const parsed = asObj(data.parsed_task);
      if ((parsed.should_run || parsed.needs_confirmation) && parsed.symbol && parsed.period) {
        lines.push(`识别任务：${parsed.symbol} ${parsed.period}，置信度 ${parsed.confidence ?? "-"}`);
      }
      const remediation = asObj(data.result && data.result.remediation_plan);
      if (remediation.quality_feedback_used) {
        lines.push("已读取上一轮质量反馈，并生成本轮修复约束。");
        lines.push("事实仍以 evidence_id/citation/verifier 为准。");
      }
      if (data.latest) lines.push(buildResultText(data.result || {}, data.latest));
      return lines.join("\n");
    }

    function buildResultText(result, data) {
      const gate = asObj(data.delivery_gate);
      const quality = asObj(data.quality_report);
      const llm = asObj(data.llm_quality_review);
      const verification = asObj(data.verification_report);
      const link = data.report_html_url ? `${location.origin}${data.report_html_url}` : "";
      const lines = [];
      if (link) lines.push(`报告链接：${link}`);
      lines.push(`Verifier：${result.verification_passed ?? verification.passed ?? "未运行"}`);
      lines.push(`本地测评分：${quality.total_score ?? quality.score ?? "未运行"}`);
      lines.push(`LLM/Codex 复核：${llm.llm_review_pass ?? llm.passed ?? "未运行"}`);
      lines.push(`交付门禁：${gate.delivery_pass ?? "未运行"}`);
      const issues = topIssues(data).slice(0, 5);
      if (issues.length) lines.push(`主要待修问题：\n- ${issues.map((item) => issueText(item)).join("\n- ")}`);
      return lines.join("\n");
    }

    function appendBubble(role, text) {
      const node = document.createElement("div");
      node.className = `bubble ${role}`;
      node.textContent = text;
      $("chatLog").appendChild(node);
      node.scrollIntoView({ behavior: "smooth", block: "end" });
    }

    function renderTabs() {
      $("tabs").innerHTML = tabs.map((tab) => `<button class="tab ${tab === activeTab ? "active" : ""}" data-tab="${esc(tab)}">${esc(tab)}</button>`).join("");
      document.querySelectorAll(".tab").forEach((btn) => btn.addEventListener("click", () => {
        activeTab = btn.dataset.tab;
        render();
      }));
    }

    function render() {
      renderTabs();
      const map = {
        "总览": renderOverview,
        "报告": renderReport,
        "多智能体协作": renderCollaboration,
        "工具调用": renderToolTrace,
        "质量评测": renderQuality,
        "图表": renderCharts,
        "引用": renderCitations,
        "表格": renderTables,
        "PDF章节": renderPdf,
        "公司画像": renderProfile,
        "Claims": renderClaims,
        "轨迹": renderTrace,
        "时间线": renderTimeline,
        "原始数据": renderRaw
      };
      $("content").innerHTML = (map[activeTab] || renderOverview)(latest);
    }

    function renderOverview(data) {
      const summary = asObj(data.summary);
      const verification = asObj(data.verification_report);
      const gate = asObj(data.delivery_gate);
      return `<div class="grid">
        ${metric("标的", summary.symbol || "-")}
        ${metric("期间", summary.period || "-")}
        ${metric("Verifier", summary.verification_passed ?? verification.passed ?? "未运行")}
        ${metric("交付门禁", gate.delivery_pass ?? "未运行")}
        ${metric("Claims", asList(data.claims).length)}
        ${metric("Evidence", asList(data.evidence).length)}
        ${metric("Charts", asList(data.charts).length)}
        ${metric("PDF Sections", asList(data.pdf_sections).length)}
      </div>`;
    }

    function metric(name, value) {
      return `<div class="item"><h3>${esc(name)}</h3><div>${esc(value)}</div></div>`;
    }

    function renderReport(data) {
      const active = currentActiveRun(data);
      if (active) {
        return `<p class="muted">正在生成 ${esc(`${active.symbol || "-"} ${active.period || ""}`.trim())} · ${esc(active.execution_mode || "")}。当前任务完成后会自动加载新报告，不再显示上一轮报告。</p>`;
      }
      if (data.report_html_url) return `<iframe src="${esc(data.report_html_url)}" title="report"></iframe>`;
      if (data.report_markdown) return `<pre>${esc(data.report_markdown)}</pre>`;
      return `<p class="muted">尚未生成报告。</p>`;
    }

    function renderCharts(data) {
      const rows = asList(data.charts);
      if (!rows.length) return `<p class="muted">暂无图表。</p>`;
      return `<div class="grid">${rows.map((c) => `<div class="item"><h3>${esc(c.title || c.chart_id || "chart")}</h3><pre>${esc(JSON.stringify(c, null, 2))}</pre></div>`).join("")}</div>`;
    }

    function renderCitations(data) {
      return table(asList(data.citations), ["evidence_id", "title", "source_url", "trust_level"]);
    }

    function renderTables(data) {
      const tables = asList(data.tables);
      if (!tables.length) return `<p class="muted">暂无三表标准化数据。</p><pre>${esc(JSON.stringify(data.financial_metrics || {}, null, 2))}</pre>`;
      return `<div class="grid">${tables.map((t) => `<div class="item"><h3>${esc(t.statement || t.title || "table")}</h3><pre>${esc(JSON.stringify(t, null, 2))}</pre></div>`).join("")}</div>`;
    }

    function renderPdf(data) {
      const rows = asList(data.pdf_sections);
      if (!rows.length) return `<p class="muted">暂无 PDF 抽取章节。</p><pre>${esc(JSON.stringify(data.pdf_manifest || {}, null, 2))}</pre>`;
      return `<div class="grid">${rows.map((s) => `<div class="item"><h3>${esc(s.heading || s.section_id || "section")}</h3><p>${esc(s.text || s.content || "")}</p><pre>${esc(JSON.stringify(s.metadata || {}, null, 2))}</pre></div>`).join("")}</div>`;
    }

    function renderProfile(data) {
      return `<pre>${esc(JSON.stringify(data.company_profile_extracted || {}, null, 2))}</pre>`;
    }

    function renderClaims(data) {
      return table(asList(data.claims), ["claim_id", "section_name", "claim_text", "evidence_ids", "confidence"]);
    }

    function renderQuality(data) {
      const quality = asObj(data.quality_report);
      const llm = asObj(data.llm_quality_review);
      const gate = asObj(data.delivery_gate);
      const remediation = asObj(data.quality_remediation_plan);
      if (!Object.keys(quality).length && !Object.keys(llm).length && !Object.keys(gate).length) {
        return `<p class="muted">尚未运行质量评测。</p>`;
      }
      const issues = topIssues(data);
      return `<div class="grid">
        ${metric("Objective Score", quality.total_score ?? quality.score ?? "未运行")}
        ${metric("Objective Pass", quality.objective_pass ?? "未运行")}
        ${metric("LLM Review Score", llm.total_score ?? llm.score ?? "未运行")}
        ${metric("LLM Review Pass", llm.llm_review_pass ?? llm.passed ?? "未运行")}
        ${metric("Delivery Pass", gate.delivery_pass ?? "未运行")}
        ${metric("质量反馈", remediation.quality_feedback_used ?? "未运行")}
      </div>
      <h3>质量问题</h3>
      ${issues.length ? `<ul>${issues.map((item) => `<li>${esc(issueText(item))}</li>`).join("")}</ul>` : `<p class="ok">暂无问题。</p>`}
      <h3>修复计划</h3><pre>${esc(JSON.stringify(remediation, null, 2))}</pre>
      <h3>Objective</h3><pre>${esc(JSON.stringify(quality, null, 2))}</pre>
      <h3>LLM/Codex Review</h3><pre>${esc(JSON.stringify(llm, null, 2))}</pre>`;
    }

    function topIssues(data) {
      const quality = asObj(data.quality_report);
      const llm = asObj(data.llm_quality_review);
      const gate = asObj(data.delivery_gate);
      return [
        ...asList(gate.issues),
        ...asList(quality.issues),
        ...asList(quality.top_issues),
        ...asList(llm.issues),
        ...asList(llm.top_issues)
      ];
    }

    function issueText(item) {
      if (typeof item === "string") return item;
      return [item.severity, item.category, item.message || item.detail || item.issue].filter(Boolean).join(" | ") || JSON.stringify(item);
    }

    function renderCollaboration(data) {
      const trace = asObj(data.agent_collaboration_trace);
      const agents = asList(trace.agents);
      const rework = asList(data.delivery_rework_history);
      if (!agents.length && !rework.length) return `<p class="muted">暂无多智能体协作记录。</p>`;
      const steps = agents.map((item) => `<div class="timeline-step">
        <header><strong>${esc(item.step || "")}. ${esc(item.agent || "")}</strong><span class="pill">${esc(item.status || "")}</span></header>
        <div class="muted">${esc(item.task_type || "")} · ${esc(item.duration_sec ?? "-")}s</div>
        <p>${esc(item.description || "")}</p>
        <div>输入：<code>${esc(JSON.stringify(item.input_summary || {}))}</code></div>
        <div>输出：${esc(asList(item.output_keys).join(", ") || "-")}</div>
        <div>Memory：${esc(item.memory_used ? "used" : "no")} · Quality feedback：${esc(item.quality_feedback_used ? "used" : "no")}</div>
        <div>Handoff：${esc(item.handoff_from || "start")} → ${esc(item.handoff_to || "end")}</div>
      </div>`).join("");
      const reworkHtml = rework.length ? `<h3>Delivery Rework</h3>${table(rework, ["round", "repair_type", "trigger", "delivery_pass_after_round"])}` : "";
      const memory = asObj(trace.memory);
      return `<div class="grid">
        ${metric("Agent Steps", trace.step_count ?? agents.length)}
        ${metric("Rework Rounds", rework.length)}
        ${metric("Memory Scope", memory.context_scope || "-")}
        ${metric("Fact Boundary", memory.fact_boundary || "facts require evidence")}
      </div><h3>Agent Timeline</h3><div class="timeline">${steps}</div>${reworkHtml}`;
    }

    function renderToolTrace(data) {
      const trace = asObj(data.tool_trace);
      const calls = asList(trace.calls);
      if (!calls.length) return `<p class="muted">暂无工具调用记录。</p>`;
      return `<div class="grid">
        ${metric("Tool Calls", trace.tool_call_count ?? calls.length)}
        ${metric("Success", trace.successful_call_count ?? "-")}
        ${metric("Failed", trace.failed_call_count ?? "-")}
      </div>${table(calls, ["caller_agent", "tool_name", "success", "failure_reason", "duration_sec"])}`;
    }

    function renderTrace(data) {
      return table(asList(data.trace), ["agent", "stage", "status", "detail"]);
    }

    function renderTimeline(data) {
      const rows = asList(data.trace).map((row, idx) => ({ idx, ...row }));
      return table(rows, ["idx", "agent", "stage", "status", "started_at", "finished_at"]);
    }

    function renderRaw(data) {
      return `<pre>${esc(JSON.stringify(data, null, 2))}</pre>`;
    }

    function table(rows, columns) {
      if (!rows.length) return `<p class="muted">暂无数据。</p>`;
      return `<table><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((c) => `<td>${esc(Array.isArray(row[c]) ? row[c].join(", ") : row[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    }

    $("chatBtn").addEventListener("click", sendChat);
    $("runBtn").addEventListener("click", runReport);
    $("refreshBtn").addEventListener("click", loadLatest);
    $("symbol").addEventListener("change", syncEnginesFromSwitch);
    $("realtimeData").addEventListener("change", syncEnginesFromSwitch);
    $("chatInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChat();
      }
    });

    syncEnginesFromSwitch();
    render();
    loadLatest();
  </script>
</body>
</html>"""
    return (
        template.replace("__DEFAULT_TOPIC__", escape(default_topic))
        .replace("__DEFAULT_ENGINES__", escape(DEFAULT_ENGINES))
        .replace("__A_SHARE_ENGINES__", escape(A_SHARE_ENGINES))
        .replace("__US_ENGINES__", escape(US_ENGINES))
        .replace("__HK_ENGINES__", escape(HK_ENGINES))
    )


def render_index_html() -> str:
    """Render the user-facing chat UI with diagnostics hidden by default."""

    default_topic = "生成 AAPL 最新公司财报研报"
    default_period = latest_completed_period()
    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Open DeepReport++</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #080808;
      --panel: #101010;
      --panel-2: #171717;
      --line: #2b2b2b;
      --text: #f7f7f7;
      --muted: #ababab;
      --ok: #7bd88f;
      --bad: #ff7b7b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .wrap { width: min(980px, calc(100vw - 32px)); margin: 0 auto; padding: 44px 0 56px; }
    .hero { min-height: 190px; display: grid; align-content: center; gap: 22px; text-align: center; }
    h1 { margin: 0; font-size: clamp(32px, 5vw, 52px); line-height: 1.04; letter-spacing: 0; }
    .chat-shell {
      width: min(760px, 100%);
      margin: 0 auto;
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      gap: 10px;
      min-height: 64px;
      border: 1px solid var(--line);
      border-radius: 32px;
      background: #202020;
      padding: 8px 10px 8px 22px;
      box-shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
    }
    #chatInput {
      width: 100%;
      min-height: 28px;
      max-height: 150px;
      resize: none;
      border: 0;
      outline: none;
      background: transparent;
      color: var(--text);
      font-size: 17px;
      line-height: 1.45;
      padding: 8px 0;
    }
    #chatInput::placeholder { color: #b9b9b9; }
    .send {
      width: 48px;
      height: 48px;
      border: 0;
      border-radius: 999px;
      background: #f7f7f7;
      color: #111111;
      font-size: 25px;
      cursor: pointer;
      display: grid;
      place-items: center;
    }
    .send:disabled { opacity: 0.55; cursor: wait; }
    .status-line {
      min-height: 42px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #0f0f0f;
      padding: 10px 14px;
      color: var(--muted);
      font-size: 14px;
    }
    .status-line strong { color: #dedede; font-weight: 600; }
    .chat-log { display: grid; gap: 14px; margin: 18px 0; }
    .bubble {
      max-width: min(760px, 88%);
      white-space: pre-wrap;
      word-break: break-word;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 15px 17px;
      line-height: 1.65;
      font-size: 15px;
      background: #151515;
    }
    .bubble.user { justify-self: end; background: #222222; border-color: #333333; }
    .bubble.assistant { justify-self: start; }
    .quick-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 20px; }
    .chip, .tab, .secondary {
      border: 1px solid var(--line);
      background: #121212;
      color: #dddddd;
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
      font-size: 14px;
    }
    .chip:hover, .tab:hover, .secondary:hover { border-color: #555555; }
    .tabs { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
    .tab.active { background: var(--text); color: #111111; border-color: var(--text); }
    .panel { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 16px; min-height: 150px; }
    .empty { min-height: 150px; display: grid; align-content: center; color: var(--muted); line-height: 1.7; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .item { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel-2); min-width: 0; }
    .item h3 { margin: 0 0 8px; font-size: 13px; color: var(--muted); font-weight: 500; }
    .item div { overflow-wrap: anywhere; }
    .developer { margin-top: 18px; border: 1px solid var(--line); border-radius: 8px; background: #0f0f0f; }
    .developer > summary { cursor: pointer; padding: 12px 14px; color: var(--muted); font-weight: 600; }
    .developer-body { padding: 0 14px 14px; }
    .settings { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
    label { display: grid; gap: 6px; color: var(--muted); font-size: 13px; }
    input, select { width: 100%; border: 1px solid var(--line); border-radius: 8px; background: #161616; color: var(--text); padding: 9px 10px; font: inherit; min-width: 0; }
    .span-3 { grid-column: span 3; }
    .checks { grid-column: span 3; display: flex; gap: 12px; flex-wrap: wrap; }
    .check { display: flex; align-items: center; gap: 7px; }
    .check input { width: auto; }
    .actions { grid-column: span 3; display: flex; gap: 10px; }
    .timeline { display: grid; gap: 10px; }
    .timeline-step { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel-2); }
    .timeline-step header { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; color: var(--muted); font-size: 12px; }
    .muted { color: var(--muted); }
    .ok { color: var(--ok); }
    .bad { color: var(--bad); }
    iframe { width: 100%; height: 76vh; border: 1px solid var(--line); border-radius: 8px; background: white; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }
    pre { overflow: auto; white-space: pre-wrap; word-break: break-word; }
    a { color: #ffffff; }
    @media (max-width: 760px) {
      .wrap { width: min(100% - 20px, 980px); padding-top: 26px; }
      .hero { min-height: 150px; }
      .chat-shell { min-height: 58px; border-radius: 28px; padding-left: 16px; }
      .grid, .settings { grid-template-columns: 1fr; }
      .span-3, .checks, .actions { grid-column: span 1; }
      .status-line { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <h1>你今天想研究什么？</h1>
      <div class="chat-shell">
        <textarea id="chatInput" rows="1" placeholder="直接问，例如：生成特斯拉最新财报研报"></textarea>
        <button id="chatBtn" class="send" title="发送" aria-label="发送">↑</button>
      </div>
    </section>
    <div class="status-line">
      <div id="statusText">就绪</div>
      <div id="runMeta">还没有生成报告</div>
    </div>
    <div id="chatLog" class="chat-log"></div>
    <div class="quick-actions">
      <button class="chip" data-prompt="生成特斯拉最新财报研报">特斯拉最新财报</button>
      <button class="chip" data-prompt="生成贵州茅台最新财报研报">贵州茅台最新财报</button>
      <button class="chip" data-prompt="帮我检查最近一份报告有哪些质量问题">检查报告质量</button>
    </div>
    <div class="tabs" id="mainTabs"></div>
    <section id="content" class="panel"></section>
    <details class="developer" id="developerPanel">
      <summary>开发者诊断</summary>
      <div class="developer-body">
        <div class="settings">
          <label>Session ID<input id="sessionId" value="local"></label>
          <label>股票代码<input id="symbol" value="AAPL"></label>
          <label>报告期<input id="period" value="__DEFAULT_PERIOD__"></label>
          <label>执行模式<select id="executionMode"><option value="collaborative">collaborative</option><option value="diagnostic_full">diagnostic_full</option><option value="dynamic">dynamic</option><option value="static">static</option></select></label>
          <label class="span-3">研究主题<input id="topic" value="__DEFAULT_TOPIC__"></label>
          <label class="span-3">搜索/数据源<input id="engines" value="__US_ENGINES__"></label>
          <label class="span-3">数据源配置<input id="dataSourceConfig" value="configs/data_sources.yaml"></label>
          <div class="checks">
            <label class="check"><input type="checkbox" id="allowReportRun" checked>允许生成报告</label>
            <label class="check"><input type="checkbox" id="memoryEnabled" checked>启用记忆</label>
            <label class="check"><input type="checkbox" id="realtimeData" checked>使用公开实时数据源</label>
            <label class="check"><input type="checkbox" id="fastMode" checked>快速模式</label>
          </div>
          <div class="actions">
            <button id="runBtn" class="secondary">按表单生成</button>
            <button id="refreshBtn" class="secondary">刷新最近输出</button>
          </div>
        </div>
        <div class="tabs" id="devTabs"></div>
        <section id="devContent" class="panel"></section>
      </div>
    </details>
  </main>
  <script>
    const DEFAULT_ENGINES = "__DEFAULT_ENGINES__";
    const A_SHARE_ENGINES = "__A_SHARE_ENGINES__";
    const US_ENGINES = "__US_ENGINES__";
    const HK_ENGINES = "__HK_ENGINES__";
    const mainTabs = ["概览", "报告", "引用", "质量"];
    const devTabs = ["数据源健康", "协作黑板", "多智能体协作", "工具调用", "图表", "表格", "PDF章节", "公司画像", "Claims", "轨迹", "时间线", "原始数据"];
    let latest = {};
    let requestInFlight = false;
    let busyPollTimer = null;
    let activeMainTab = "概览";
    let activeDevTab = "多智能体协作";
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m]));
    const asList = (value) => Array.isArray(value) ? value : [];
    const asObj = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
    function setStatus(text, isError = false) { $("statusText").textContent = text; $("statusText").className = isError ? "bad" : ""; }
    function activeRuns(data) { return asList(asObj(data).active_runs); }
    function currentActiveRun(data) { return activeRuns(data)[0] || null; }
    function setControlsBusy(isBusy) {
      requestInFlight = isBusy;
      $("chatBtn").disabled = isBusy;
      $("runBtn").disabled = isBusy;
    }
    function startBusyPolling() {
      stopBusyPolling();
      busyPollTimer = window.setInterval(() => loadLatest({ silent: true }), 8000);
    }
    function stopBusyPolling() {
      if (busyPollTimer) window.clearInterval(busyPollTimer);
      busyPollTimer = null;
    }
    function showPendingRun(payload, message = "") {
      const pending = {
        session_id: payload.session_id || "local",
        symbol: payload.symbol || "",
        period: payload.period || "",
        research_topic: payload.topic || message || "",
        execution_mode: payload.execution_mode || "collaborative",
        status: "submitted",
        started_at: new Date().toLocaleString()
      };
      latest = { ...latest, active_runs: [pending] };
      syncFormFromLatest(latest);
      render();
    }
    function payloadBase() {
      return {
        session_id: $("sessionId").value || "local",
        symbol: $("symbol").value || "AAPL",
        period: $("period").value || "__DEFAULT_PERIOD__",
        topic: $("topic").value,
        engines: $("engines").value,
        execution_mode: $("executionMode").value,
        fast: $("fastMode").checked,
        memory_enabled: $("memoryEnabled").checked,
        allow_report_run: $("allowReportRun").checked,
        enable_remote_data: $("realtimeData").checked,
        data_source_config_path: $("dataSourceConfig").value || "configs/data_sources.yaml"
      };
    }
    function syncEnginesFromSwitch() {
      const symbol = ($("symbol").value || "").toUpperCase();
      if (!$("realtimeData").checked) $("engines").value = DEFAULT_ENGINES;
      else if (symbol.endsWith(".SS") || symbol.endsWith(".SZ") || /^[0-9]{6}$/.test(symbol)) $("engines").value = A_SHARE_ENGINES;
      else if (symbol.endsWith(".HK")) $("engines").value = HK_ENGINES;
      else $("engines").value = US_ENGINES;
    }
    async function postJson(url, payload) {
      const resp = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || JSON.stringify(data));
      return data;
    }
    async function loadLatest(options = {}) {
      const silent = Boolean(options.silent);
      if (!silent && !requestInFlight) setStatus("读取最近报告");
      const resp = await fetch("/api/latest");
      latest = await resp.json();
      syncFormFromLatest(latest);
      render();
      const active = currentActiveRun(latest);
      if (active) setStatus(`后台生成中：${active.symbol || "-"} ${active.period || ""}`);
      else if (!silent && !requestInFlight) setStatus("就绪");
    }
    function syncFormFromLatest(data) {
      const active = currentActiveRun(data);
      const summary = asObj(data.summary);
      const display = active || summary;
      if (display.symbol) $("symbol").value = display.symbol;
      if (display.period) $("period").value = display.period;
      if (display.research_topic) $("topic").value = display.research_topic;
      if (Array.isArray(summary.search_engines) && summary.search_engines.length) $("engines").value = summary.search_engines.join(",");
      if (active) $("runMeta").innerHTML = `<strong>正在生成</strong> ${esc(`${active.symbol || ""} ${active.period || ""}`.trim())} · ${esc(active.execution_mode || "")}`;
      else if (summary.symbol || summary.period) $("runMeta").innerHTML = `<strong>最近报告</strong> ${esc(`${summary.symbol || ""} ${summary.period || ""}`.trim())} · ${esc(summary.execution_mode || "")}`;
      else $("runMeta").textContent = "还没有生成报告";
    }
    async function runReport() {
      const payload = payloadBase();
      showPendingRun(payload);
      setStatus(`正在生成报告：${payload.symbol} ${payload.period}`);
      setControlsBusy(true);
      startBusyPolling();
      try {
        const data = await postJson("/api/run", payload);
        latest = data.latest || {};
        syncFormFromLatest(latest);
        appendBubble("assistant", buildResultText(data.result || {}, latest));
        render();
        setStatus(latest.delivery_gate && latest.delivery_gate.delivery_pass === false ? "报告未通过质量门禁" : "完成", latest.delivery_gate && latest.delivery_gate.delivery_pass === false);
      } catch (err) {
        appendBubble("assistant", `生成失败：${err.message}`);
        setStatus("失败", true);
      } finally {
        stopBusyPolling();
        setControlsBusy(false);
        loadLatest({ silent: true });
      }
    }
    async function sendChat() {
      const message = $("chatInput").value.trim();
      if (!message) return;
      appendBubble("user", message);
      $("chatInput").value = "";
      const payload = { ...payloadBase(), message };
      showPendingRun(payload, message);
      setControlsBusy(true);
      setStatus("已提交，正在解析/生成；报告生成可能需要数分钟");
      startBusyPolling();
      try {
        const data = await postJson("/api/chat", payload);
        const parsed = asObj(data.parsed_task);
        if (parsed.symbol) {
          $("symbol").value = parsed.symbol;
          if (parsed.period) $("period").value = parsed.period;
          if (parsed.research_topic) $("topic").value = parsed.research_topic;
          syncEnginesFromSwitch();
        }
        if (data.latest) { latest = data.latest; syncFormFromLatest(latest); }
        appendBubble("assistant", renderChatAnswer(data));
        render();
        const gate = asObj(asObj(data.latest).delivery_gate);
        setStatus(gate.delivery_pass === false ? "报告未通过质量门禁" : "就绪", gate.delivery_pass === false);
      } catch (err) {
        appendBubble("assistant", `对话失败：${err.message}`);
        setStatus("失败", true);
      } finally {
        stopBusyPolling();
        setControlsBusy(false);
        loadLatest({ silent: true });
      }
    }
    function renderChatAnswer(data) {
      if (data.mode === "period_guard") return data.answer || "这个报告期尚未结束，不能生成正式财报研报。";
      const lines = [data.answer || "已完成。"];
      const parsed = asObj(data.parsed_task);
      if ((parsed.should_run || parsed.needs_confirmation) && parsed.symbol && parsed.period && data.mode !== "report_run") lines.push(`我理解为：${parsed.symbol} ${parsed.period}。`);
      if (data.latest) lines.push(buildResultText(data.result || {}, data.latest));
      return lines.filter(Boolean).join("\n");
    }
    function buildResultText(result, data) {
      const gate = asObj(data.delivery_gate);
      const quality = asObj(data.quality_report);
      const llm = asObj(data.llm_quality_review);
      const verification = asObj(data.verification_report);
      const summary = asObj(data.summary);
      const lines = [];
      if (summary.symbol || summary.period) lines.push(`报告对象：${[summary.symbol, summary.period].filter(Boolean).join(" ")}`);
      lines.push(`事实校验：${result.verification_passed ?? verification.passed ?? "未运行"}`);
      lines.push(`客观评分：${quality.total_score ?? quality.score ?? "未运行"}`);
      lines.push(`LLM 复核：${llm.llm_review_pass ?? llm.passed ?? "未运行"}`);
      lines.push(`交付状态：${gate.delivery_pass === true ? "已通过" : gate.delivery_pass === false ? "未通过" : "未运行"}`);
      const issues = topIssues(data).slice(0, 4);
      if (issues.length) lines.push(`需要关注：\n- ${issues.map((item) => issueText(item)).join("\n- ")}`);
      if (data.report_html_url) lines.push("报告已在下方“报告”页签中更新。");
      return lines.join("\n");
    }
    function appendBubble(role, text) {
      const node = document.createElement("div");
      node.className = `bubble ${role}`;
      node.textContent = text;
      $("chatLog").appendChild(node);
      node.scrollIntoView({ behavior: "smooth", block: "end" });
    }
    function renderTabButtons(containerId, tabs, active, onClick) {
      $(containerId).innerHTML = tabs.map((tab) => `<button class="tab ${tab === active ? "active" : ""}" data-tab="${esc(tab)}">${esc(tab)}</button>`).join("");
      document.querySelectorAll(`#${containerId} .tab`).forEach((btn) => btn.addEventListener("click", () => onClick(btn.dataset.tab)));
    }
    function render() {
      renderTabButtons("mainTabs", mainTabs, activeMainTab, (tab) => { activeMainTab = tab; render(); });
      renderTabButtons("devTabs", devTabs, activeDevTab, (tab) => { activeDevTab = tab; render(); });
      const mainMap = {"概览": renderOverview, "报告": renderReport, "引用": renderCitations, "质量": renderQuality};
      const devMap = {"数据源健康": renderSourceHealth, "协作黑板": renderBlackboard, "多智能体协作": renderCollaboration, "工具调用": renderToolTrace, "图表": renderCharts, "表格": renderTables, "PDF章节": renderPdf, "公司画像": renderProfile, "Claims": renderClaims, "轨迹": renderTrace, "时间线": renderTimeline, "原始数据": renderRaw};
      $("content").innerHTML = (mainMap[activeMainTab] || renderOverview)(latest);
      $("devContent").innerHTML = (devMap[activeDevTab] || renderCollaboration)(latest);
    }
    function renderOverview(data) {
      const active = currentActiveRun(data);
      const summary = asObj(data.summary);
      const verification = asObj(data.verification_report);
      const gate = asObj(data.delivery_gate);
      if (active) {
        return `<div class="grid">${metric("当前任务", `${active.symbol || "-"} ${active.period || ""}`)}${metric("状态", "正在生成")}${metric("执行模式", active.execution_mode || "-")}${metric("开始时间", active.started_at || "-")}</div><p class="muted">下方最近报告仍可能是上一轮产物；当前任务完成后会自动刷新。</p>`;
      }
      if (!summary.symbol && !asList(data.evidence).length && !data.report_html_url) return `<div class="empty">可以直接输入“生成某公司最新财报研报”。我会先检查报告期是否有效，再启动多智能体生成。</div>`;
      return `<div class="grid">${metric("标的", summary.symbol || "-")}${metric("报告期", summary.period || "-")}${metric("执行模式", summary.execution_mode || "-")}${metric("事实校验", summary.verification_passed ?? verification.passed ?? "未运行")}${metric("交付状态", gate.delivery_pass === true ? "已通过" : gate.delivery_pass === false ? "未通过" : "未运行")}${metric("论点", asList(data.claims).length)}${metric("证据", asList(data.evidence).length)}${metric("图表", asList(data.charts).length)}${metric("引用", asList(data.citations).length)}</div>`;
    }
    function metric(name, value) { return `<div class="item"><h3>${esc(name)}</h3><div>${esc(value)}</div></div>`; }
    function renderReport(data) {
      const active = currentActiveRun(data);
      if (active) {
        return `<div class="empty">正在生成 ${esc(`${active.symbol || "-"} ${active.period || ""}`.trim())} · ${esc(active.execution_mode || "")}。当前任务完成后会自动加载新报告，不再显示上一轮报告。</div>`;
      }
      if (data.report_html_url) return `<iframe src="${esc(data.report_html_url)}" title="report"></iframe>`;
      if (data.report_markdown) return `<pre>${esc(data.report_markdown)}</pre>`;
      return `<div class="empty">报告生成后会显示在这里。</div>`;
    }
    function renderCharts(data) {
      const rows = asList(data.charts);
      if (!rows.length) return `<p class="muted">暂无图表。</p>`;
      return `<div class="grid">${rows.map((c) => `<div class="item"><h3>${esc(c.title || c.chart_id || "chart")}</h3><pre>${esc(JSON.stringify(c, null, 2))}</pre></div>`).join("")}</div>`;
    }
    function renderCitations(data) { return table(asList(data.citations), ["evidence_id", "title", "source_url", "trust_level"]); }
    function renderTables(data) {
      const tables = asList(data.tables);
      if (!tables.length) return `<p class="muted">暂无三表标准化数据。</p><pre>${esc(JSON.stringify(data.financial_metrics || {}, null, 2))}</pre>`;
      return `<div class="grid">${tables.map((t) => `<div class="item"><h3>${esc(t.statement || t.title || "table")}</h3><pre>${esc(JSON.stringify(t, null, 2))}</pre></div>`).join("")}</div>`;
    }
    function renderPdf(data) {
      const rows = asList(data.pdf_sections);
      if (!rows.length) return `<p class="muted">暂无 PDF 抽取章节。</p><pre>${esc(JSON.stringify(data.pdf_manifest || {}, null, 2))}</pre>`;
      return `<div class="grid">${rows.map((s) => `<div class="item"><h3>${esc(s.heading || s.section_id || "section")}</h3><p>${esc(s.text || s.content || "")}</p><pre>${esc(JSON.stringify(s.metadata || {}, null, 2))}</pre></div>`).join("")}</div>`;
    }
    function renderProfile(data) { return `<pre>${esc(JSON.stringify(data.company_profile_extracted || {}, null, 2))}</pre>`; }
    function renderClaims(data) { return table(asList(data.claims), ["claim_id", "section_name", "claim_text", "evidence_ids", "confidence"]); }
    function renderQuality(data) {
      const quality = asObj(data.quality_report);
      const llm = asObj(data.llm_quality_review);
      const gate = asObj(data.delivery_gate);
      if (!Object.keys(quality).length && !Object.keys(llm).length && !Object.keys(gate).length) return `<div class="empty">还没有质量评测结果。</div>`;
      const issues = topIssues(data);
      return `<div class="grid">${metric("客观评分", quality.total_score ?? quality.score ?? "未运行")}${metric("客观门禁", quality.objective_pass ?? "未运行")}${metric("LLM 复核", llm.llm_review_pass ?? llm.passed ?? "未运行")}${metric("交付门禁", gate.delivery_pass ?? "未运行")}</div><h3>主要问题</h3>${issues.length ? `<ul>${issues.slice(0, 8).map((item) => `<li>${esc(issueText(item))}</li>`).join("")}</ul>` : `<p class="ok">暂无问题。</p>`}`;
    }
    function renderSourceHealth(data) {
      const health = asObj(data.source_health);
      const rows = asList(health.engines);
      if (!rows.length) return `<p class="muted">暂无数据源健康信息。生成报告后会显示各搜索/数据源状态。</p>`;
      return `<div class="grid">${metric("总体状态", health.status || "unknown")}${metric("数据源数量", rows.length)}${metric("失败", rows.filter((r) => r.status === "failed").length)}${metric("可选降级", rows.filter((r) => r.status === "degraded_optional").length)}</div>${table(rows, ["engine", "status", "record_count", "returned_hit_count", "failure_reason", "error"])}`;
    }
    function topIssues(data) {
      const quality = asObj(data.quality_report);
      const llm = asObj(data.llm_quality_review);
      const gate = asObj(data.delivery_gate);
      return [...asList(gate.issues), ...asList(gate.top_issues), ...asList(quality.issues), ...asList(quality.top_issues), ...asList(llm.issues), ...asList(llm.top_issues)];
    }
    function issueText(item) {
      if (typeof item === "string") return item;
      return [item.severity, item.category, item.message || item.detail || item.issue].filter(Boolean).join(" | ") || JSON.stringify(item);
    }
    function renderBlackboard(data) {
      const board = asObj(data.research_blackboard);
      if (!Object.keys(board).length) return `<p class="muted">暂无协作黑板。生成报告后会显示市场路由、公司身份、披露期和写作前质询。</p>`;
      const identity = asObj(board.company_identity);
      const route = asObj(board.market_route);
      const period = asObj(board.period_state);
      const critic = asObj(board.critic);
      const objections = asList(critic.objections);
      return `<div class="grid">${metric("市场", identity.market || route.market || "-")}${metric("交易所", identity.exchange || route.exchange || "-")}${metric("最新披露期", period.latest_available_disclosure_period || "-")}${metric("写作前审议", critic.pre_write_passed === true ? "通过" : "需关注")}${metric("质询数", objections.length)}</div>${objections.length ? `<h3>Objections</h3><ul>${objections.map((item) => `<li>${esc(issueText(item))}</li>`).join("")}</ul>` : ""}<pre>${esc(JSON.stringify(board, null, 2))}</pre>`;
    }
    function renderCollaboration(data) {
      const trace = asObj(data.agent_collaboration_trace);
      const agents = asList(trace.agents);
      const rework = asList(data.delivery_rework_history);
      if (!agents.length && !rework.length) return `<p class="muted">暂无多智能体协作记录。</p>`;
      const steps = agents.map((item) => `<div class="timeline-step"><header><strong>${esc(item.step || "")}. ${esc(item.agent || "")}</strong><span class="pill">${esc(item.status || "")}</span></header><div class="muted">${esc(item.task_type || "")} · ${esc(item.duration_sec ?? "-")}s</div><p>${esc(item.description || "")}</p><div>输入：<code>${esc(JSON.stringify(item.input_summary || {}))}</code></div><div>产物键：${esc(asList(item.output_keys).join(", ") || "-")}</div><div>Memory：${esc(item.memory_used ? "used" : "no")} · Quality feedback：${esc(item.quality_feedback_used ? "used" : "no")}</div></div>`).join("");
      const reworkHtml = rework.length ? `<h3>Delivery Rework</h3>${table(rework, ["round", "repair_type", "trigger", "delivery_pass_after_round"])}` : "";
      return `<div class="grid">${metric("Agent Steps", trace.step_count ?? agents.length)}${metric("Rework Rounds", rework.length)}</div><h3>Agent Timeline</h3><div class="timeline">${steps}</div>${reworkHtml}`;
    }
    function renderToolTrace(data) {
      const trace = asObj(data.tool_trace);
      const calls = asList(trace.calls);
      if (!calls.length) return `<p class="muted">暂无工具调用记录。</p>`;
      return `<div class="grid">${metric("Tool Calls", trace.tool_call_count ?? calls.length)}${metric("Success", trace.successful_call_count ?? "-")}${metric("Failed", trace.failed_call_count ?? "-")}</div>${table(calls, ["caller_agent", "tool_name", "success", "failure_reason", "duration_sec"])}`;
    }
    function renderTrace(data) { return table(asList(data.trace), ["agent", "stage", "status", "detail"]); }
    function renderTimeline(data) {
      const rows = asList(data.trace).map((row, idx) => ({ idx, ...row }));
      return table(rows, ["idx", "agent", "stage", "status", "started_at", "finished_at"]);
    }
    function renderRaw(data) { return `<pre>${esc(JSON.stringify(data, null, 2))}</pre>`; }
    function table(rows, columns) {
      if (!rows.length) return `<p class="muted">暂无数据。</p>`;
      return `<table><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((c) => `<td>${esc(Array.isArray(row[c]) ? row[c].join(", ") : row[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    }
    $("chatBtn").addEventListener("click", sendChat);
    $("runBtn").addEventListener("click", runReport);
    $("refreshBtn").addEventListener("click", loadLatest);
    $("symbol").addEventListener("change", syncEnginesFromSwitch);
    $("realtimeData").addEventListener("change", syncEnginesFromSwitch);
    document.querySelectorAll(".chip").forEach((btn) => btn.addEventListener("click", () => { $("chatInput").value = btn.dataset.prompt || ""; $("chatInput").focus(); }));
    $("chatInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChat(); } });
    syncEnginesFromSwitch();
    render();
    loadLatest();
  </script>
</body>
</html>"""
    return (
        template.replace("__DEFAULT_TOPIC__", escape(default_topic))
        .replace("__DEFAULT_PERIOD__", escape(default_period))
        .replace("__DEFAULT_ENGINES__", escape(DEFAULT_ENGINES))
        .replace("__A_SHARE_ENGINES__", escape(A_SHARE_ENGINES))
        .replace("__US_ENGINES__", escape(US_ENGINES))
        .replace("__HK_ENGINES__", escape(HK_ENGINES))
    )


def default_engines_for_symbol(symbol: str, realtime: bool = False) -> str:
    if not realtime:
        return DEFAULT_ENGINES
    identity = resolve_company_identity(symbol, default=symbol)
    engines = list(identity.data_source_plan.get("engines") or [])
    return ",".join(engines or _parse_engines(DEFAULT_ENGINES))


def _should_reset_engines_for_parsed_task(has_parsed_task: bool, raw_engines: Any) -> bool:
    if not has_parsed_task:
        return False
    return str(raw_engines or "") in {DEFAULT_ENGINES, A_SHARE_ENGINES, US_ENGINES, HK_ENGINES}


def validate_period_for_report(raw_period: str, today: date | None = None) -> Dict[str, Any]:
    raw = str(raw_period or "").strip().upper()
    today = today or date.today()
    if len(raw) != 6 or raw[4] != "Q" or not raw[:4].isdigit() or raw[-1] not in "1234":
        return {"ok": True, "message": "", "suggested_periods": []}
    quarter_end = period_target_date(raw)
    if quarter_end is None:
        return {"ok": True, "message": "", "suggested_periods": []}
    if quarter_end < today:
        return {"ok": True, "message": "", "suggested_periods": []}
    prior_year, prior_quarter = previous_completed_quarter(today)
    suggested = [f"{prior_year}Q{prior_quarter}", f"{today.year - 1}Q4"]
    return {
        "ok": False,
        "message": (
            f"{raw} 尚未结束，不能生成正式财报口径研报。"
            f"可改为最近已结束报告期 {suggested[0]}，或使用完整财年 {suggested[1]}。"
        ),
        "suggested_periods": suggested,
    }


def _previous_completed_quarter(today: date) -> tuple[int, int]:
    month = today.month
    if month <= 3:
        return today.year - 1, 4
    if month <= 6:
        return today.year, 1
    if month <= 9:
        return today.year, 2
    return today.year, 3


def _looks_like_report_request(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        term in lowered
        for term in ["研报", "财报", "报告", "年报", "季报", "research report", "company report", "annual report", "quarterly report"]
    )


def _is_confirmation_message(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    if normalized in {
        "\u662f",
        "\u662f\u7684",
        "\u786e\u8ba4",
        "\u5bf9",
        "\u5bf9\u7684",
        "\u53ef\u4ee5",
        "\u5f00\u59cb",
        "\u5f00\u59cb\u751f\u6210",
        "\u751f\u6210",
        "\u597d",
        "\u597d\u7684",
        "\u884c",
        "\u6ca1\u95ee\u9898",
    }:
        return True
    return normalized in {
        "确认",
        "是",
        "是的",
        "对",
        "对的",
        "可以",
        "开始",
        "开始生成",
        "生成",
        "好的",
        "好",
        "行",
        "没问题",
        "yes",
        "y",
        "ok",
        "okay",
        "confirm",
        "曲儿",
    }


def _confirmation_prompt(symbol: str, period: str, engines: List[str]) -> str:
    return (
        "我识别到你可能想生成研报，但还需要确认参数：\n"
        f"- 标的：{symbol}\n"
        f"- 期间：{period}\n"
        f"- 数据源：{', '.join(engines)}\n"
        "请回复确认，或回复“是”，我会直接启动多智能体生成。"
    )


def _parse_engines(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _read_json(path: Path, default: Any | None = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _artifact_urls(output_path: Path, report_path: Path) -> Dict[str, str]:
    names = [
        "run_summary.json",
        "search_meta.json",
        "citations.json",
        "charts.json",
        "claims.json",
        "evidence.json",
        "tables.json",
        "financial_metrics.json",
        "rejected_metrics.json",
        "claim_rejection_report.json",
        "pdf_manifest.json",
        "pdf_sections.json",
        "company_profile_extracted.json",
        "mcp_manifest.json",
        "revision_history.json",
        "verification_report.json",
        "quality_report.json",
        "llm_quality_review.json",
        "delivery_gate.json",
        "quality_remediation_plan.json",
        "task_trace.jsonl",
    ]
    urls: Dict[str, str] = {}
    for name in names:
        if (output_path / name).exists():
            urls[name] = f"/artifacts/{name}"
    if (report_path / "report.md").exists():
        urls["report.md"] = _report_artifact_url(report_path, "report.md")
    if (report_path / "report.html").exists():
        urls["report.html"] = _report_artifact_url(report_path, "report.html")
    if (report_path / "report.json").exists():
        urls["report.json"] = _report_artifact_url(report_path, "report.json")
    return urls


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    server, url = run_ui_server()
    print(f"DeepReport++ web UI: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
