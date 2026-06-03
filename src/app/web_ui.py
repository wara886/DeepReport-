"""Local chat-first web workbench for FinSight."""

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
import sys
import threading
import time as _time
from typing import Any, Dict, List
import uuid
from urllib.parse import unquote, urlparse, parse_qs

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
from src.app.query_understanding import QueryUnderstanding
from src.utils.periods import period_target_date, previous_completed_quarter
from src.data.company_universe import resolve_company_identity
from src.evaluation.delivery_gate import build_delivery_gate_from_outputs, write_delivery_gate_for_outputs
from src.evaluation.llm_report_review import review_report_with_llm_from_paths, write_llm_review_outputs_for_paths
from src.evaluation.quality_remediation import (
    build_quality_remediation_plan_from_outputs,
    write_quality_remediation_plan_for_outputs,
)
from src.evaluation.report_quality import evaluate_report_quality_from_paths, write_quality_outputs_for_paths
from dataclasses import dataclass, field
import concurrent.futures


# ── Report Request State ──────────────────────────────────────────────

@dataclass
class ReportRequestState:
    """Per-request state machine for report generation requests.

    Every user report request gets one of these stored in pending_report_tasks
    keyed by session_id. It survives the confirmation round-trip and is consumed
    when the job is actually created.
    """
    request_id: str
    session_id: str
    symbol: str
    company_name: str = ""
    market: str = ""
    period: str = ""
    period_kind: str = "unknown"  # quarter | fiscal_year | latest | unknown
    research_topic: str = ""
    created_at: str = ""
    status: str = "pending_confirmation"  # pending_confirmation | confirmed | running | completed | failed | timeout | cancelled
    job_id: str = ""
    source: str = "chat"  # chat | form
    needs_confirmation: bool = False
    missing_fields: list = field(default_factory=list)
    report_mode_hint: str = ""  # quick | standard | full

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "symbol": self.symbol,
            "company_name": self.company_name,
            "market": self.market,
            "period": self.period,
            "period_kind": self.period_kind,
            "research_topic": self.research_topic,
            "created_at": self.created_at,
            "status": self.status,
            "job_id": self.job_id,
            "source": self.source,
            "needs_confirmation": self.needs_confirmation,
            "missing_fields": self.missing_fields,
            "report_mode_hint": self.report_mode_hint,
        }

    def is_same_request(self, symbol: str, period: str) -> bool:
        """Check if this request matches the given symbol/period."""
        return (
            self.symbol.strip().upper() == symbol.strip().upper()
            and self.period.strip().upper() == period.strip().upper()
        )


DEFAULT_OUTPUT_DIR = "data/outputs/multi_agent"
DEFAULT_REPORT_DIR = "data/reports/multi_agent"
DEFAULT_EXECUTION_MODE = "collaborative"
DEFAULT_ENGINES = "local_real_data,yahoo_finance,tavily,local_evidence"
A_SHARE_ENGINES = (
    "local_real_data,cninfo_announcements,exchange_announcements,"
    "eastmoney_financials,sina_finance,yahoo_finance,eastmoney,local_evidence"
)
US_ENGINES = "local_real_data,sec_edgar,yahoo_finance,independent_macro,local_evidence"
HK_ENGINES = "local_real_data,sina_finance,yahoo_finance,tavily,hkex_announcements,local_evidence"

ENGINE_USER_LABELS: dict[str, str] = {
    "local_real_data": "本地已缓存财务数据",
    "sec_edgar": "SEC 官方披露",
    "yahoo_finance": "行情与市场数据",
    "independent_macro": "宏观与行业补充数据",
    "tavily": "公开网络资料",
    "local_evidence": "本地证据库",
    "cninfo_announcements": "巨潮资讯公告",
    "exchange_announcements": "交易所公告",
    "eastmoney_financials": "东方财富财务数据",
    "eastmoney": "东方财富数据",
    "sina_finance": "新浪行情数据",
    "serper": "网络搜索结果",
    "hkex_announcements": "港交所公告",
}


def _human_readable_data_sources(engines: list[str]) -> str:
    """Map internal engine keys to a user-facing data source summary."""
    seen: set[str] = set()
    parts: list[str] = []
    for e in engines:
        label = ENGINE_USER_LABELS.get(e)
        if label and label not in seen:
            seen.add(label)
            parts.append(label)
    if parts:
        return "、".join(parts)
    return "公司公开披露、官方监管文件、行情数据和公开资料"


def _market_label(symbol: str) -> str:
    """Heuristic market label from symbol suffix."""
    s = symbol.upper()
    if s.endswith(".SS") or s.endswith(".SZ"):
        return "A股"
    if s.endswith(".HK"):
        return "港股"
    return "美股"


# Module-level state containers for test access
pending_report_tasks: Dict[str, Dict[str, Any]] = {}
active_report_runs: Dict[str, Dict[str, Any]] = {}


# ── Deadline utilities ────────────────────────────────────────────
import time as _deadline_time

def _deadline_from_now(seconds: float) -> float:
    """Return a monotonic deadline `seconds` from now."""
    return _deadline_time.monotonic() + seconds

def _deadline_expired(deadline: float | None) -> bool:
    """Return True if *deadline* (monotonic) is None or in the past."""
    if deadline is None:
        return False
    return _deadline_time.monotonic() >= deadline

def _remaining_seconds(deadline: float | None) -> float:
    """Return remaining wall seconds, or infinity if deadline is None."""
    if deadline is None:
        return float("inf")
    return max(0.0, deadline - _deadline_time.monotonic())


def _write_timeout_artifacts(
    output_dir: Path, job_id: str, symbol: str, period: str, mode: str, reason: str,
) -> None:
    """Write timeout artifacts when a job exceeds its budget."""
    error_path = output_dir / "run_error.json"
    try:
        error_path.write_text(
            json.dumps({
                "error": "timeout",
                "symbol": symbol,
                "period": period,
                "reason": reason,
                "job_id": job_id,
                "delivery_status": "timeout_degraded" if mode == "user" else "timeout_failed",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    summary_path = output_dir / "run_summary.json"
    try:
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary, dict):
                summary["delivery_status"] = "timeout_degraded" if mode == "user" else "timeout_failed"
                summary["timeout_reason"] = reason
                summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class ReportJobTimeout(Exception):
    """Raised when a report job exceeds its wall-clock budget in a specific phase."""
    def __init__(self, phase: str, elapsed_sec: float, budget_sec: float):
        self.phase = phase
        self.elapsed_sec = elapsed_sec
        self.budget_sec = budget_sec
        super().__init__(f"report job timed out in phase '{phase}' after {elapsed_sec:.0f}s (budget {budget_sec:.0f}s)")


def _check_deadline(deadline: float | None, phase_name: str, budget_sec: float = 9999.0) -> None:
    """Raise ReportJobTimeout if *deadline* is expired."""
    if deadline is not None and _deadline_expired(deadline):
        elapsed = _remaining_seconds(deadline)  # will be 0
        raise ReportJobTimeout(phase_name, _deadline_time.monotonic() - (deadline - budget_sec) if deadline else 0, budget_sec)


def _write_phase(output_dir: Path, perf_trace: dict, phase: str) -> None:
    """Update phase in perf_trace and write to disk."""
    perf_trace["current_phase"] = phase
    perf_trace["updated_at"] = datetime.now().isoformat()
    _write_performance_trace(output_dir, perf_trace)


def _write_run_error(output_dir: Path, exc: Exception, symbol: str, period: str) -> None:
    """Write run_error.json from an exception."""
    error_path = Path(output_dir) / "run_error.json"
    try:
        error_path.write_text(
            json.dumps({
                "error": str(exc),
                "symbol": symbol,
                "period": period,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _write_performance_trace(output_dir: Path, trace: dict) -> None:
    """Write performance_trace.json and update run_summary.json with computed fields."""
    trace_path = Path(output_dir) / "performance_trace.json"
    try:
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    summary_path = Path(output_dir) / "run_summary.json"
    try:
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary, dict) and "computed" in trace:
                summary["performance_trace"] = trace["computed"]
                summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def run_phase_with_timeout(
    phase_name: str,
    phase_budget_sec: float,
    overall_deadline: float,
    output_dir: Path,
    perf_trace: dict,
    func,
    *args,
    **kwargs,
) -> Any:
    """Run *func(*args, **kwargs)* with per-phase timeout via ThreadPoolExecutor.

    If *phase_budget_sec* exceeds remaining time before *overall_deadline*,
    the phase deadline is clamped to the overall deadline. Raises
    ReportJobTimeout on expiry / timeout.
    """
    remaining = min(phase_budget_sec, _remaining_seconds(overall_deadline))
    if remaining <= 2.0:
        raise ReportJobTimeout(phase_name, 0.0, phase_budget_sec)

    _write_phase(output_dir, perf_trace, phase_name)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(func, *args, **kwargs)
    try:
        result = future.result(timeout=remaining)
        return result
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise ReportJobTimeout(phase_name, phase_budget_sec - remaining, phase_budget_sec)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def run_ui_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    memory_root: str = "memory/chat",
    mode: str = "user",
    frontend_port: int | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    handler = create_ui_handler(
        output_dir=output_dir,
        report_dir=report_dir,
        config_path=config_path,
        memory_root=memory_root,
        mode=mode,
        frontend_port=frontend_port,
    )
    server = ThreadingHTTPServer((host, int(port)), handler)
    actual_host, actual_port = server.server_address
    return server, f"http://{actual_host}:{actual_port}"


def create_ui_handler(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    memory_root: str = "memory/chat",
    mode: str = "user",
    frontend_port: int | None = None,
):
    output_root = Path(output_dir)
    report_root = Path(report_dir)
    chat_service = AgentChatService(
        config_path=config_path,
        memory_root=memory_root,
        output_root=output_root,
        report_root=report_root,
    )
    # Use module-level containers for test access
    global pending_report_tasks, active_report_runs
    pending_report_tasks.clear()
    active_report_runs.clear()
    _report_queue: List[Dict[str, Any]] = []
    _queue_lock = threading.Lock()
    _queue_worker_running = False

    def _generate_job_id() -> str:
        return f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def _enqueue_report(job_id: str, session_id: str, run_func) -> None:
        nonlocal _queue_worker_running
        with _queue_lock:
            already = any(item["job_id"] == job_id for item in _report_queue)
            if not already:
                _report_queue.append({
                    "job_id": job_id,
                    "session_id": session_id,
                    "run": run_func,
                    "status": "queued",
                    "enqueued_at": datetime.now().isoformat(timespec="seconds"),
                    "started_at": None,
                    "completed_at": None,
                })
            if not _queue_worker_running:
                _queue_worker_running = True
                threading.Thread(target=_process_report_queue, daemon=True, name="finsight-queue-worker").start()

    def _process_report_queue() -> None:
        nonlocal _queue_worker_running
        while True:
            task = None
            with _queue_lock:
                if _report_queue:
                    task = _report_queue[0]
                    if task["status"] == "cancelled":
                        _report_queue.pop(0)
                        continue
            if task is None:
                break
            with _queue_lock:
                task["status"] = "running"
                task["started_at"] = datetime.now().isoformat(timespec="seconds")
            try:
                task["run"]()
            except Exception:
                pass
            with _queue_lock:
                task["status"] = "completed"
                task["completed_at"] = datetime.now().isoformat(timespec="seconds")
                _report_queue.pop(0)
        with _queue_lock:
            _queue_worker_running = False

    def _active_key(session_id: str) -> str:
        return str(session_id or "local")

    def _mark_active_run(
        session_id: str,
        *,
        job_id: str,
        symbol: str,
        period: str,
        topic: str,
        execution_mode: str,
        source: str,
        time_budget_sec: float | None = None,
        deadline: float | None = None,
        output_dir: str | None = None,
        report_dir: str | None = None,
        request_id: str = "",
    ) -> None:
        active_report_runs[job_id] = {
            "job_id": job_id,
            "session_id": str(session_id or "local"),
            "symbol": symbol,
            "period": period,
            "research_topic": topic,
            "execution_mode": execution_mode,
            "source": source,
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "time_budget_sec": time_budget_sec,
            "deadline": deadline,
            "output_dir": output_dir,
            "report_dir": report_dir,
            "request_id": request_id,
        }

    def _clear_active_run(job_id: str) -> None:
        active_report_runs.pop(job_id, None)

    def _latest_payload(job_id: str = "", request_id: str = "", session_id: str = "") -> Dict[str, Any]:
        # If caller asked for a specific job, try to return that job's report
        target_job_id = job_id or request_id or ""
        if target_job_id:
            # Try active run first
            entry = active_report_runs.get(target_job_id)
            if not entry:
                # Try by request_id in active runs
                for rid, rentry in active_report_runs.items():
                    if rentry.get("request_id") == target_job_id:
                        entry = rentry
                        break
            if entry and entry.get("report_dir"):
                rdir = Path(entry["report_dir"])
                odir = Path(entry["output_dir"]) if entry.get("output_dir") else None
                if (rdir / "report.html").exists():
                    payload = load_run_payload(odir or output_root, rdir)
                    payload["active_runs"] = _visible_active_runs(payload)
                    payload["queue_length"] = len(_report_queue)
                    payload["is_global_latest"] = False
                    payload["is_current_request"] = True
                    payload["found"] = True
                    payload["job_id"] = target_job_id
                    payload["status"] = "completed_with_warnings" if odir is not None and (odir / "run_error.json").exists() else "completed"
                    return payload
                # Active run exists but no report.html — return running status
                payload = load_run_payload(odir or output_root, rdir)
                payload["active_runs"] = _visible_active_runs(payload)
                payload["queue_length"] = len(_report_queue)
                payload["is_global_latest"] = False
                payload["is_current_request"] = True
                payload["status"] = entry.get("status", "running")
                return payload
            # Try filesystem: find run_dir by job_id.txt or request_state.json
            for run_dir in (output_root / "runs").iterdir() if (output_root / "runs").exists() else []:
                od = run_dir / "outputs"
                marker = od / "job_id.txt"
                req_state_path = od / "request_state.json"
                found_fs = False
                if marker.exists() and marker.read_text(encoding="utf-8").strip() == target_job_id:
                    found_fs = True
                elif req_state_path.exists():
                    try:
                        rs = json.loads(req_state_path.read_text(encoding="utf-8"))
                        if rs.get("job_id") == target_job_id or rs.get("run_id") == target_job_id:
                            found_fs = True
                    except Exception:
                        pass
                if found_fs:
                    rd = report_root / "runs" / run_dir.name / "reports"
                    if rd.exists() and (rd / "report.html").exists():
                        payload = load_run_payload(od, rd)
                        payload["active_runs"] = _visible_active_runs(payload)
                        payload["queue_length"] = len(_report_queue)
                        payload["is_global_latest"] = False
                        payload["is_current_request"] = True
                        payload["found"] = True
                        payload["job_id"] = target_job_id
                        payload["status"] = "completed_with_warnings" if (od / "run_error.json").exists() else "completed"
                        return payload
                    # Found the run dir but no report.html — return terminal/running status
                    err_path = od / "run_error.json"
                    if err_path.exists():
                        payload = load_run_payload(od, rd if rd.exists() else report_root)
                        payload["active_runs"] = _visible_active_runs(payload)
                        payload["queue_length"] = len(_report_queue)
                        payload["is_global_latest"] = False
                        payload["is_current_request"] = True
                        payload["found"] = True
                        payload["job_id"] = target_job_id
                        payload["status"] = "failed"
                        try:
                            err_data = json.loads(err_path.read_text(encoding="utf-8"))
                            err_text = str(err_data.get("error") or err_data.get("reason") or err_data)
                            payload["error"] = err_text
                            if err_text.lower() == "timeout" or str(err_data.get("delivery_status") or "").startswith("timeout"):
                                payload["status"] = "timeout"
                        except Exception:
                            payload["error"] = err_path.read_text(encoding="utf-8")
                        return payload
                    perf_path = od / "performance_trace.json"
                    if perf_path.exists():
                        try:
                            perf = json.loads(perf_path.read_text(encoding="utf-8"))
                            if perf.get("status") in ("failed", "timeout"):
                                payload = load_run_payload(od, rd if rd.exists() else report_root)
                                payload["active_runs"] = _visible_active_runs(payload)
                                payload["queue_length"] = len(_report_queue)
                                payload["is_global_latest"] = False
                                payload["is_current_request"] = True
                                payload["found"] = True
                                payload["job_id"] = target_job_id
                                payload["status"] = perf["status"]
                                payload["error"] = perf.get("last_error", "")
                                return payload
                        except Exception:
                            pass
            # Strict mode: job_id specified but not found → return unknown_job
            # NEVER fall back to global latest when caller asked for a specific job
            return {
                "found": False,
                "status": "unknown_job",
                "is_global_latest": False,
                "is_current_request": True,
                "job_id": target_job_id,
                "active_runs": _visible_active_runs({}),
                "queue_length": len(_report_queue),
            }

        # Fallback to global latest
        latest_dirs = _latest_run_dirs(output_root, report_root)
        payload = load_run_payload(latest_dirs["output_dir"], latest_dirs["report_dir"])
        payload["active_runs"] = _visible_active_runs(payload)
        payload["queue_length"] = len(_report_queue)
        payload["is_global_latest"] = True
        payload["is_current_request"] = False
        active_running = None
        for item in _report_queue:
            if item["status"] == "running":
                active_running = item
                break
        payload["active_job_id"] = active_running["job_id"] if active_running else None
        # Check for expired deadlines in active runs — clean up stale entries
        stale_ids: List[str] = []
        for run in active_report_runs.values():
            if run.get("status") == "running":
                run_id = run.get("job_id", "")
                rdir = Path(run["report_dir"]) if run.get("report_dir") else None
                odir = Path(run["output_dir"]) if run.get("output_dir") else None
                # Check filesystem first: report.html exists → completed silently
                if rdir is not None and (rdir / "report.html").exists():
                    stale_ids.append(run_id)
                elif run.get("deadline") is not None and _deadline_expired(run["deadline"]):
                    if odir:
                        _write_timeout_artifacts(
                            odir, run_id,
                            run.get("symbol", "?"), run.get("period", "?"),
                            mode, "deadline exceeded",
                        )
                    stale_ids.append(run_id)
        for sid in stale_ids:
            _clear_active_run(sid)
        return payload

    def _visible_active_runs(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Return all active (running) runs regardless of latest completed state
        return [r for r in active_report_runs.values() if r.get("status") == "running"]

    def _compute_queue_position(session_id: str) -> int:
        """Return 0 if this session's job is running, >0 for queue position."""
        with _queue_lock:
            for idx, item in enumerate(_report_queue):
                if item.get("session_id") == session_id:
                    if item["status"] == "running":
                        return 0
                    return idx  # 0 = running, 1+ = queued
            return 0

    class WebUIHandler(BaseHTTPRequestHandler):
        server_version = "FinSightWebUI/0.3"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            # Server mode overrides URL query param for security
            effective_mode = mode
            if parsed.path == "/":
                self._send_html(render_index_html(mode=effective_mode, frontend_port=frontend_port))
                return
            if parsed.path == "/api/latest":
                qs = parse_qs(urlparse(self.path).query)
                sess = str(qs.get("session_id", ["local"])[0]) if isinstance(qs.get("session_id"), list) else "local"
                jid = str(qs.get("job_id", [""])[0]) if isinstance(qs.get("job_id"), list) else ""
                rid = str(qs.get("request_id", [""])[0]) if isinstance(qs.get("request_id"), list) else ""
                payload = _latest_payload(job_id=jid, request_id=rid, session_id=sess)
                payload["queue_position"] = _compute_queue_position(sess)
                self._send_json(payload_for_mode(payload, effective_mode))
                return
            if parsed.path.startswith("/artifacts/"):
                self._send_artifact(parsed.path.removeprefix("/artifacts/"))
                return
            if parsed.path == "/api/job_status":
                self._handle_job_status()
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
            if parsed.path == "/api/cancel_job":
                self._handle_cancel_job()
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
            engines = _parse_engines(default_engines_for_symbol(symbol, enable_remote_data))
            execution_mode = str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE)
            if mode == "user":
                execution_tier = "user_fast"  # 用户模式固定，忽略 payload
            else:
                execution_tier = str(payload.get("execution_tier") or "developer_fast").lower()
                if execution_tier not in ("developer_fast", "preview", "delivery"):
                    execution_tier = "developer_fast"
            job_id = _generate_job_id()
            time_budget = 300.0 if mode == "user" else (420.0 if execution_tier == "developer_fast" else 600.0)
            execution_deadline = _deadline_from_now(time_budget)
            req_id = str(payload.get("request_id") or f"req_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")
            run_paths = _create_run_dirs(output_root, report_root, symbol, period, execution_mode, request_id=req_id, session_id=session_id, job_id=job_id)
            _mark_active_run(
                session_id,
                job_id=job_id,
                symbol=symbol,
                period=period,
                topic=topic,
                execution_mode=execution_mode,
                source="form",
                time_budget_sec=time_budget,
                deadline=execution_deadline,
                output_dir=str(run_paths["output_dir"]),
                report_dir=str(run_paths["report_dir"]),
                request_id=req_id,
            )
            orchestrator = MultiAgentOrchestrator(
                output_dir=str(run_paths["output_dir"]),
                report_dir=str(run_paths["report_dir"]),
                config_path=config_path,
                memory_enabled=bool(payload.get("memory_enabled", False)),
                memory_root=str(Path(memory_root) / "durable"),
                execution_tier=execution_tier,
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
                # ── 1. Orchestrator ──────────────────────────────────
                if _deadline_expired(execution_deadline):
                    raise TimeoutError("deadline expired before orchestrator.run")
                result = orchestrator.run(**run_kwargs, execution_deadline=execution_deadline)

                # ── 2. Quality pipeline ──────────────────────────────
                deadline_exceeded = _deadline_expired(execution_deadline)
                if not deadline_exceeded:
                    # Quality gets its own deadline anchored from NOW,
                    # independent of orchestrator's shared budget.
                    quality_deadline = _deadline_from_now(120.0)
                    quality_result = run_delivery_quality_pipeline(
                        run_paths["output_dir"],
                        run_paths["report_dir"],
                        config_path,
                        durable_memory_store=getattr(orchestrator, "durable_memory", None),
                        memory_enabled=bool(payload.get("memory_enabled", False)),
                        deadline=quality_deadline,
                        review_mode="heuristic" if mode == "user" else "full",
                    )
                else:
                    quality_result = {"delivery_gate": {"delivery_pass": False}, "top_quality_issues": []}

                # ── 3. Delivery rework ───────────────────────────────
                rework_max_rounds = 0 if mode == "user" else 1
                deadline_exceeded = deadline_exceeded or _deadline_expired(execution_deadline)
                if rework_max_rounds > 0 and not deadline_exceeded:
                    rework_result = run_delivery_rework_loop(
                        orchestrator=orchestrator,
                        output_path=run_paths["output_dir"],
                        report_path=run_paths["report_dir"],
                        config_path=config_path,
                        initial_quality_result=quality_result,
                        run_kwargs=run_kwargs,
                        durable_memory_store=getattr(orchestrator, "durable_memory", None),
                        memory_enabled=bool(payload.get("memory_enabled", False)),
                        deadline=execution_deadline,
                        max_rounds=rework_max_rounds,
                    )
                else:
                    rework_result = {"rounds": [], "quality_result": quality_result, "reworked": False}
                    if rework_max_rounds <= 0:
                        _write_delivery_rework_history(
                            Path(run_paths["output_dir"]),
                            [{
                                "round": 0,
                                "trigger": "quality_diagnostic",
                                "status": "skipped",
                                "handled": False,
                                "unfixable_reasons": [f"user_fast_mode_skips_delivery_rework" if mode == "user" else "deadline_exceeded"],
                                "delivery_pass_after_round": quality_result.get("delivery_gate", {}).get("delivery_pass", False) if isinstance(quality_result.get("delivery_gate"), dict) else False,
                            }],
                        )

                if rework_result.get("quality_result"):
                    quality_result = rework_result["quality_result"]
                if rework_result.get("rounds") and isinstance(result, dict):
                    result["delivery_rework"] = rework_result

                # ── 4. Finalize ──────────────────────────────────────
                _finalize_run_dirs(run_paths, output_root, report_root, symbol, period, execution_mode, quality_result, execution_tier=execution_tier)
                _clear_active_run(job_id)
                report_links = build_report_links(run_paths["report_dir"])
                latest = _latest_payload()
                self._send_json({
                    "result": {**result, **quality_result},
                    "report_links": report_links,
                    "latest": payload_for_mode(latest, mode),
                })
            except TimeoutError:
                _write_timeout_artifacts(run_paths["output_dir"], job_id, symbol, period, mode, "deadline exceeded")
                self._send_json({
                    "error": "报告生成超时",
                    "mode": "timeout_suspected",
                    "latest": _latest_payload(),
                }, status=HTTPStatus.REQUEST_TIMEOUT)
            except Exception as exc:  # pragma: no cover - defensive UI boundary
                self._send_json({"error": str(exc), "latest": _latest_payload()}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                _clear_active_run(job_id)

        def _handle_job_status(self) -> None:
            qs = parse_qs(urlparse(self.path).query)
            job_id = str(qs.get("job_id", [""])[0]).strip()
            if not job_id:
                self._send_json({"error": "job_id required"}, status=HTTPStatus.BAD_REQUEST)
                return
            result: Dict[str, Any] = {"job_id": job_id, "found": False}

            # Resolve output_dir / report_dir from active_run or filesystem scan
            output_dir: Path | None = None
            report_dir: Path | None = None
            entry = active_report_runs.get(job_id)
            if entry is not None:
                if entry.get("output_dir"):
                    output_dir = Path(entry["output_dir"])
                if entry.get("report_dir"):
                    report_dir = Path(entry["report_dir"])
            else:
                # Filesystem lookup to resolve paths for unknown job
                # Matches on: job_id.txt content == job_id, OR request_state.json job_id/run_id match
                for run_dir in (output_root / "runs").iterdir() if (output_root / "runs").exists() else []:
                    od = run_dir / "outputs"
                    marker = od / "job_id.txt"
                    req_state_path = od / "request_state.json"
                    found = False
                    if marker.exists() and marker.read_text(encoding="utf-8").strip() == job_id:
                        found = True
                    elif req_state_path.exists():
                        try:
                            rs = json.loads(req_state_path.read_text(encoding="utf-8"))
                            if rs.get("job_id") == job_id or rs.get("run_id") == job_id:
                                found = True
                        except Exception:
                            pass
                    if found:
                        output_dir = od
                        rd = report_root / "runs" / run_dir.name / "reports"
                        if rd.exists():
                            report_dir = rd
                        break

            # Diagnostic: log resolution state for this call
            has_active = entry is not None
            has_report_html = report_dir is not None and (report_dir / "report.html").exists() if report_dir else False
            has_run_error = output_dir is not None and (output_dir / "run_error.json").exists() if output_dir else False
            sys.stderr.write(
                f"[job_status] job_id={job_id} active={has_active} "
                f"report_html={has_report_html} run_error={has_run_error}\n"
            )

            # 1. report.html on disk → terminal completed / completed_with_warnings
            if report_dir is not None and (report_dir / "report.html").exists():
                result.update({
                    "found": True,
                    "status": "completed",
                    "source": "report_html_on_disk",
                    "report_links": build_report_links(report_dir),
                })
                if output_dir is not None and (output_dir / "run_error.json").exists():
                    result["status"] = "completed_with_warnings"
                    try:
                        err_data = json.loads((output_dir / "run_error.json").read_text(encoding="utf-8"))
                        result["error"] = err_data.get("error", str(err_data))
                    except Exception:
                        pass
                _clear_active_run(job_id)
                self._send_json(result)
                return

            # 2. run_error.json on disk → failed
            if output_dir is not None and (output_dir / "run_error.json").exists():
                result.update({"found": True, "status": "failed", "source": "run_error_on_disk"})
                try:
                    err_data = json.loads((output_dir / "run_error.json").read_text(encoding="utf-8"))
                    if isinstance(err_data, dict):
                        err_text = str(err_data.get("error") or err_data.get("reason") or err_data)
                        result["error"] = err_text
                        if err_text.lower() == "timeout" or str(err_data.get("delivery_status") or "").startswith("timeout"):
                            result["status"] = "timeout"
                    else:
                        result["error"] = str(err_data)
                except Exception:
                    try:
                        result["error"] = (output_dir / "run_error.json").read_text(encoding="utf-8")
                    except Exception:
                        pass
                _clear_active_run(job_id)
                self._send_json(result)
                return

            # 3. performance_trace.json on disk → terminal state (completed/timeout/failed)
            if output_dir is not None and (output_dir / "performance_trace.json").exists():
                try:
                    perf = json.loads((output_dir / "performance_trace.json").read_text(encoding="utf-8"))
                    if perf.get("status") in ("completed", "timeout", "failed", "quality_diagnostic"):
                        status = perf["status"]
                        if status == "quality_diagnostic":
                            status = "completed" if report_dir is not None and (report_dir / "report.html").exists() else "completed_with_warnings"
                        result.update({"found": True, "status": status, "source": "performance_trace"})
                        if perf.get("report_links"):
                            result["report_links"] = perf["report_links"]
                        if perf["status"] == "completed" and report_dir is not None:
                            rlinks = build_report_links(report_dir)
                            if rlinks.get("html_web_url"):
                                result["report_links"] = rlinks
                        _clear_active_run(job_id)
                        self._send_json(result)
                        return
                except Exception:
                    pass

            # 4. Active run (running within deadline, or timeout if deadline expired)
            if entry is not None:
                result["found"] = True
                result["source"] = "active_run"
                result["entry"] = dict(entry)
                if entry.get("status") == "running" and entry.get("deadline") is not None:
                    if _deadline_expired(entry["deadline"]):
                        if output_dir is not None:
                            _write_timeout_artifacts(
                                output_dir, job_id,
                                entry.get("symbol", "?"), entry.get("period", "?"),
                                mode, "deadline exceeded",
                            )
                        _clear_active_run(job_id)
                        result["status"] = "timeout"
                        result["entry"]["status"] = "timeout"
                        if report_dir is not None:
                            rlinks = build_report_links(report_dir)
                            if rlinks:
                                result["report_links"] = rlinks
                    else:
                        result["status"] = "running"
                else:
                    result["status"] = entry.get("status", "unknown")
                self._send_json(result)
                return

            # 5. Filesystem fallback (scan all run dirs for job_id.txt)
            self._filesystem_job_status_fallback(result, job_id)
            self._send_json(result)

        def _filesystem_job_status_fallback(self, result: Dict[str, Any], job_id: str) -> None:
            """Try to find job status from filesystem artifacts."""
            output_runs = output_root / "runs"
            report_runs = report_root / "runs"
            if not output_runs.exists():
                return
            for run_dir in output_runs.iterdir():
                od = run_dir / "outputs"
                if not od.exists():
                    continue
                marker = od / "job_id.txt"
                req_state_path = od / "request_state.json"
                found_fs = False
                if marker.exists() and marker.read_text(encoding="utf-8").strip() == job_id:
                    found_fs = True
                elif req_state_path.exists():
                    try:
                        rs = json.loads(req_state_path.read_text(encoding="utf-8"))
                        if rs.get("job_id") == job_id or rs.get("run_id") == job_id:
                            found_fs = True
                    except Exception:
                        pass
                if found_fs:
                    result["found"] = True
                    result["source"] = "filesystem"
                    rd = (report_runs / run_dir.name / "reports") if report_runs.exists() else None
                    if rd is not None and (rd / "report.html").exists():
                        result["status"] = "completed"
                        result["report_links"] = build_report_links(rd)
                    elif (od / "run_error.json").exists():
                        result["status"] = "failed"
                        try:
                            err_data = json.loads((od / "run_error.json").read_text(encoding="utf-8"))
                            result["error"] = err_data.get("error", str(err_data))
                        except Exception:
                            result["error"] = (od / "run_error.json").read_text(encoding="utf-8")
                    elif (od / "performance_trace.json").exists():
                        try:
                            perf = json.loads((od / "performance_trace.json").read_text(encoding="utf-8"))
                            result["status"] = perf.get("status", "unknown")
                            if perf.get("report_links"):
                                result["report_links"] = perf["report_links"]
                        except Exception:
                            result["status"] = "unknown"
                    else:
                        result["status"] = "unknown"
                    break

        def _handle_cancel_job(self) -> None:
            payload = self._read_json_body()
            job_id = str(payload.get("job_id") or "").strip()
            session_id = str(payload.get("session_id") or "local")
            if job_id:
                with _queue_lock:
                    for item in _report_queue:
                        if item["job_id"] == job_id and item["status"] == "queued":
                            item["status"] = "cancelled"
                            self._send_json({
                                "mode": "cancelled",
                                "job_id": job_id,
                                "answer": "已取消队列中的任务。",
                            })
                            return
            pending_report_tasks.pop(session_id, None)
            self._send_json({
                "mode": "cancelled",
                "answer": "任务已取消或不在队列中。",
            })

        def _handle_chat(self) -> None:
            payload = self._read_json_body()
            message = str(payload.get("message") or "").strip()
            original_message = message
            session_id = str(payload.get("session_id") or "local")
            user_id = str(payload.get("user_id") or "local_user")
            symbol = str(payload.get("symbol") or "AAPL").strip().upper()
            period = str(payload.get("period") or latest_completed_period()).strip().upper()
            allow_report_run = bool(payload.get("allow_report_run", True))
            enable_remote_data = bool(payload.get("enable_remote_data", True))
            request_id = str(payload.get("request_id") or f"req_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")

            # --- P0.6 Deterministic Pre-Parse (before LLM) ---
            from src.app.company_aliases import parse_report_request as det_parse

            det_result = det_parse(message)
            _det_has_symbol = bool(det_result.get("symbol"))
            _det_has_period = bool(det_result.get("period"))
            if det_result.get("intent") == "generate_report" and _det_has_symbol and _det_has_period:
                # Deterministic parse succeeded — override symbol/period before LLM
                symbol = det_result["symbol"]
                period = det_result["period"]
                payload["symbol"] = symbol
                payload["period"] = period
                payload["_det_company_name"] = det_result.get("company_name", "")
                payload["_det_market"] = det_result.get("market", "")
                payload["_det_period_kind"] = det_result.get("period_kind", "")

            # --- Query Understanding Layer ---
            qu = QueryUnderstanding(config_path=config_path)
            if det_result.get("intent") == "generate_report" and _det_has_symbol and _det_has_period:
                intent = "report_generation"
            else:
                intent = qu.intent_classify(message)
            if det_result.get("intent") == "generate_report" and intent not in (
                "report_artifact_request", "confirmation", "cancel_or_modify", "quality_review", "report_revision_request",
            ):
                intent = "report_generation"
            target_resolution: Dict[str, Any] = {}
            if intent == "report_generation":
                target_resolution = qu.resolve_report_target(
                    original_message,
                    current_symbol=symbol,
                    current_period=period,
                    today=date.today(),
                )
                if target_resolution.get("symbol"):
                    symbol = str(target_resolution["symbol"]).strip().upper()
                    period = str(target_resolution.get("period") or target_resolution.get("resolved_period") or period).strip().upper()
                    payload["symbol"] = symbol
                    payload["period"] = period
                    payload["_target_resolution"] = target_resolution
            if intent in ("report_generation", "data_query", "report_revision_request") and not (
                det_result.get("intent") == "generate_report" and _det_has_symbol and _det_has_period
            ):
                normalized = qu.normalize_query(message)
                message = normalized if normalized.strip() else message
            entities = qu.extract_entities(message, current_symbol=symbol, current_period=period, today=date.today())
            _original_payload_symbol = payload.get("symbol")  # save before entities override
            if entities.get("symbol"):
                payload["symbol"] = entities["symbol"]
                symbol = entities["symbol"]
            if entities.get("period"):
                payload["period"] = entities["period"]
                period = entities["period"]
            if target_resolution.get("symbol"):
                symbol = str(target_resolution["symbol"]).strip().upper()
                period = str(target_resolution.get("period") or target_resolution.get("resolved_period") or period).strip().upper()
                payload["symbol"] = symbol
                payload["period"] = period
            engines = _parse_engines(default_engines_for_symbol(symbol, enable_remote_data))

            # --- Intent routing by priority ---

            # [1] report_artifact_request — highest priority, before pending_task
            if intent == "report_artifact_request":
                # Only filter by symbol if user explicitly specified one
                # Guard against entity extraction noise (e.g. "html" → "HTML")
                ent_symbol = str(entities.get("symbol") or "").strip().upper()
                ent_conf = float(entities.get("confidence") or 0)
                noise_symbols = {"HTML", "PDF", "CSV", "JSON", "TXT", "XML", "API", "URL", "FILE"}
                symbol_from_user = bool(_original_payload_symbol)  # saved before entities override
                user_has_valid_symbol = symbol_from_user or (ent_symbol and ent_conf >= 0.5 and ent_symbol not in noise_symbols)
                lookup_symbol = symbol if user_has_valid_symbol else None
                lookup_period = period if (payload.get("period") or entities.get("period")) else None
                artifact = resolve_report_artifact(
                    output_root=output_root,
                    report_root=report_root,
                    symbol=lookup_symbol,
                    period=lookup_period,
                )
                if artifact["found"]:
                    is_hist = artifact.get("is_historical", True)
                    if is_hist:
                        answer = f"我找到了之前生成的 {artifact['symbol']} {artifact['period']} 历史报告，可直接查看（非当前请求）。"
                    else:
                        answer = f"我找到了 {artifact['symbol']} {artifact['period']} 财报，可以直接打开："
                    self._send_json({
                        "mode": "report_artifact",
                        "answer": answer,
                        "report_links": artifact["report_links"],
                        "symbol": artifact["symbol"],
                        "period": artifact["period"],
                        "run_id": artifact["run_id"],
                        "request_id": request_id,
                        "session_id": session_id,
                        "is_historical": is_hist,
                    })
                else:
                    answer = (
                        "我没有找到已生成的报告。你可以点击下方按钮生成一份新报告。"
                        if mode == "user"
                        else "未找到匹配的已有报告。"
                    )
                    self._send_json({
                        "mode": "report_artifact",
                        "answer": answer,
                        "found": False,
                        "request_id": request_id,
                        "session_id": session_id,
                    })
                return

            # [2] confirmation / cancel_or_modify — consume or clear pending_task
            pending_task = pending_report_tasks.get(session_id)
            if intent == "confirmation" and pending_task and allow_report_run:
                pending_symbol = str(pending_task.get("symbol") or "").strip().upper()
                if not pending_symbol:
                    self._send_json({
                        "mode": "confirm_report",
                        "answer": "还缺少公司身份信息，请先提供公司名称或 ticker（含交易所）再确认生成。",
                        "parsed_task": pending_task,
                        "request_id": request_id,
                    })
                    return
                symbol = pending_symbol
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
                _proceed_to_generation = True

            elif intent == "cancel_or_modify":
                pending_report_tasks.pop(session_id, None)
                self._send_json({
                    "mode": "general_chat",
                    "answer": "已取消当前操作。请重新输入公司名称或报告要求。",
                    "request_id": request_id,
                    "session_id": session_id,
                })
                return

            else:
                # For any other intent, clear pending task (don't let it hijack)
                if pending_task and intent != "report_generation":
                    pending_report_tasks.pop(session_id, None)
                parsed_task = llm_parse_chat_task(
                    message, current_symbol=symbol, current_period=period, config_path=config_path
                )
                if intent == "report_generation" and target_resolution:
                    target_symbol = str(target_resolution.get("symbol") or "").strip().upper()
                    target_period = str(target_resolution.get("period") or target_resolution.get("resolved_period") or parsed_task.period).strip().upper()
                    target_kind = str(target_resolution.get("period_intent") or parsed_task.period_kind or "unknown")
                    if target_symbol:
                        parsed_task = replace(
                            parsed_task,
                            symbol=target_symbol,
                            period=target_period,
                            period_kind=target_kind,
                            research_topic=f"生成 {target_symbol} {target_period} 公司财报研报",
                            confidence=max(parsed_task.confidence, float(target_resolution.get("confidence") or 0.0)),
                            should_run=bool(target_resolution.get("verified")) and not bool(target_resolution.get("needs_confirmation")),
                            needs_confirmation=bool(target_resolution.get("needs_confirmation", True)),
                            reason=f"{parsed_task.reason}; target resolver: {target_resolution.get('reason', '')}",
                            source=str(target_resolution.get("source") or parsed_task.source),
                        )
                    else:
                        parsed_task = replace(
                            parsed_task,
                            symbol="",
                            period=target_period,
                            period_kind=target_kind,
                            research_topic=f"生成 UNKNOWN {target_period} 公司财报研报",
                            should_run=False,
                            needs_confirmation=True,
                            reason=f"target resolver blocked unresolved company: {target_resolution.get('reason', '')}",
                            source=str(target_resolution.get("source") or parsed_task.source),
                        )
                _proceed_to_generation = False

            # [3] quality_review — no generation progress
            if intent == "quality_review":
                answer, result_payload, citations = chat_service._answer_quality_review()
                response = {
                    "answer": answer,
                    "result": result_payload,
                    "citations": citations,
                    "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                    "tool_trace": [{"stage": "quality_review", "detail": "artifact_only"}],
                }
                response["mode"] = "quality_review"
                response["request_id"] = request_id
                response["parsed_task"] = parsed_task.to_dict()
                self._send_json(response)
                return

            # [4] report_revision_request — LLM chat about modifying existing report
            if intent == "report_revision_request":
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
                response["mode"] = "general_chat"
                response["request_id"] = request_id
                self._send_json(response)
                return

            # [5] data_query — existing flow, no progress
            if intent == "data_query":
                metric_hint = entities.get("metric_hint", "")
                topic_prefix = f"查询 {symbol} {period} {metric_hint}" if metric_hint else f"查询 {symbol} {period} 财务数据"
                payload["topic"] = topic_prefix
                chat_response = chat_service.handle_chat(
                    message=f"{topic_prefix}：{message}",
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
                chat_response["mode"] = "data_query"
                chat_response["request_id"] = request_id
                chat_response["parsed_task"] = {
                    "symbol": symbol, "period": period, "intent": intent,
                    "metric_hint": metric_hint, "query": message,
                }
                self._send_json(chat_response)
                return

            # [6] report_generation — existing flow with confirmation + progress
            confirmed_pending = bool(
                allow_report_run
                and intent == "confirmation"
                and locals().get("_proceed_to_generation", False)
            )
            if intent == "report_generation" or confirmed_pending:
                if parsed_task.should_run or parsed_task.needs_confirmation:
                    symbol = parsed_task.symbol
                    period = parsed_task.period
                    payload["topic"] = parsed_task.research_topic
                if not confirmed_pending and target_resolution and not str(target_resolution.get("symbol") or "").strip():
                    answer = (
                        "我还不能可靠确认你要分析的上市公司。请补充公司全称、股票代码或交易市场；"
                        "在确认前我不会用当前上下文公司代替生成。"
                    )
                    if target_resolution.get("ambiguous"):
                        alts = target_resolution.get("alternatives") or []
                        alt_text = "、".join(
                            f"{item.get('company_name') or item.get('symbol')}({item.get('symbol')})"
                            for item in alts[:5] if isinstance(item, dict)
                        )
                        if alt_text:
                            answer = f"我识别到多个公司候选：{alt_text}。请指定其中一个公司或 ticker。"
                    self._send_json({
                        "mode": "general_chat",
                        "answer": answer,
                        "request_id": request_id,
                        "session_id": session_id,
                        "parsed_task": parsed_task.to_dict(),
                        "target_resolution": target_resolution,
                    })
                    return
                engines = _parse_engines(default_engines_for_symbol(symbol, enable_remote_data))

                if allow_report_run and (confirmed_pending or parsed_task.should_run or parsed_task.needs_confirmation):
                    guard = validate_period_for_report(period)
                    if not guard["ok"]:
                        response = {
                            "answer": guard["message"],
                            "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                            "tool_trace": [{"stage": "period_guard", "detail": "artifact_free_guard"}],
                            "citations": [],
                            "result": {},
                        }
                        response["mode"] = "period_guard"
                        response["period_guard"] = guard
                        response["parsed_task"] = parsed_task.to_dict()
                        response["request_id"] = request_id
                        self._send_json(response)
                        return

                    needs_confirm = not confirmed_pending and (mode == "user" or parsed_task.needs_confirmation)
                    if needs_confirm:
                        _c_identity = resolve_company_identity(
                            parsed_task.symbol or "", default=parsed_task.symbol or ""
                        )
                        target_company_name = str(target_resolution.get("company_name") or "") if target_resolution else ""
                        target_market = str(target_resolution.get("market") or "") if target_resolution else ""
                        req_state = ReportRequestState(
                            request_id=request_id,
                            session_id=str(session_id),
                            symbol=str(parsed_task.symbol or "").strip().upper(),
                            company_name=str(target_company_name or _c_identity.company_name or parsed_task.symbol or ""),
                            market=str(target_market or _market_label(parsed_task.symbol or "")),
                            period=str(parsed_task.period or "").strip().upper(),
                            period_kind=getattr(parsed_task, "period_kind", "unknown") or "unknown",
                            research_topic=str(parsed_task.research_topic or ""),
                            created_at=datetime.now().isoformat(timespec="seconds"),
                            status="pending_confirmation",
                            source="chat",
                            needs_confirmation=True,
                            report_mode_hint="standard",
                        )
                        pending_report_tasks[session_id] = req_state.to_dict()
                        response = {
                            "answer": _confirmation_prompt(parsed_task.symbol, parsed_task.period, engines, mode),
                            "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                            "route_reason": "local report planning confirmation",
                        }
                        response["mode"] = "confirm_report"
                        response["parsed_task"] = parsed_task.to_dict()
                        response["confirm_data"] = {
                            "company_name": req_state.company_name,
                            "symbol": req_state.symbol,
                            "market": req_state.market,
                            "period": req_state.period,
                            "target_resolution": target_resolution,
                            "analysis_scope": ["三表摘要", "财务分析", "估值观察", "风险提示", "投资结论"],
                            "data_sources_hint": "公司公开披露、SEC 文件、行情数据和公开资料",
                        }
                        response["request_id"] = request_id
                        self._send_json(response)
                        return

                    # confirmed_pending or parsed_task.should_run — execute generation
                    execution_mode = str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE)
                    if mode == "user":
                        execution_tier = "user_fast"
                    else:
                        execution_tier = str(payload.get("execution_tier") or "developer_fast").lower()
                        if execution_tier not in ("developer_fast", "preview", "delivery"):
                            execution_tier = "developer_fast"
                    async_report_run = bool(payload.get("async_report_run", False))
                    job_id = _generate_job_id()
                    req_id = request_id  # from _handle_chat scope
                    run_paths = _create_run_dirs(output_root, report_root, symbol, period, execution_mode, request_id=req_id, session_id=session_id, job_id=job_id)
                    orchestrator = MultiAgentOrchestrator(
                        output_dir=str(run_paths["output_dir"]),
                        report_dir=str(run_paths["report_dir"]),
                        config_path=config_path,
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                        memory_root=str(Path(memory_root) / "durable"),
                        execution_tier=execution_tier,
                    )
                    _request_created_at = datetime.now().isoformat(timespec="seconds")
                    run_kwargs = {
                        "research_topic": str(payload.get("topic") or parsed_task.research_topic or message),
                        "symbol": symbol,
                        "period": period,
                        "execution_mode": execution_mode,
                        "fast": bool(payload.get("fast", True)),
                        "search_engines": engines,
                        "enable_remote_data": enable_remote_data,
                        "data_source_config_path": str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                    }
                    time_budget = 300.0 if mode == "user" else (420.0 if execution_tier == "developer_fast" else 600.0)
                    execution_deadline = _deadline_from_now(time_budget)
                    _mark_active_run(
                        session_id,
                        job_id=job_id,
                        symbol=symbol,
                        period=period,
                        topic=str(run_kwargs["research_topic"]),
                        execution_mode=str(run_kwargs["execution_mode"]),
                        source="chat",
                        time_budget_sec=time_budget,
                        deadline=execution_deadline,
                        output_dir=str(run_paths["output_dir"]),
                        report_dir=str(run_paths["report_dir"]),
                        request_id=req_id,
                    )

                    def _run_report_background() -> None:
                        budget_sec = float(time_budget or 300.0)
                        # P0.7: Recalibrate deadline at execution time.
                        # The original execution_deadline was set at request time;
                        # queue delay could consume the entire budget before we start.
                        deadline = _deadline_from_now(budget_sec)
                        # Update active_run entry so job_status sees the real deadline
                        entry = active_report_runs.get(job_id)
                        if entry:
                            entry["deadline"] = deadline
                        odir = Path(run_paths["output_dir"])
                        rdir = Path(run_paths["report_dir"])

                        # Per-phase budgets — orchestrator gets nearly all time.
                        # Quality + finalize need only a small reserve.
                        # Quality pipeline gets its OWN deadline (anchored from NOW at phase start),
                        # independent of the orchestrator's deadline, so even when orchestrator
                        # runs near budget, quality checks still have time to complete.
                        _orch_budget = budget_sec - 15.0  # reserve 15s for finalize
                        _quality_budget = 25.0 if mode == "user" else 50.0
                        phase_budgets = {
                            "orchestrator": _orch_budget,
                            "quality_pipeline": _quality_budget,
                            "delivery_rework": 0.0,
                            "finalize": 10.0,
                        }

                        # Initialize performance_trace.json on disk
                        perf_trace: Dict[str, Any] = {
                            "job_id": job_id,
                            "status": "running",
                            "current_phase": "initialized",
                            "started_at": datetime.now().isoformat(),
                            "updated_at": datetime.now().isoformat(),
                            "elapsed_sec": 0.0,
                            "timeout_budget_sec": budget_sec,
                            "last_error": None,
                        }
                        _write_performance_trace(odir, perf_trace)

                        t_start = _time.perf_counter()

                        try:
                            # ── Phase 1: Orchestrator ──────────────────────────
                            t0 = _time.perf_counter()
                            result = run_phase_with_timeout(
                                "orchestrator", phase_budgets["orchestrator"],
                                deadline, odir, perf_trace,
                                orchestrator.run, **run_kwargs, execution_deadline=deadline,
                            )
                            t1 = _time.perf_counter()

                            # ── Phase 2: Quality pipeline (user mode: skip) ──────
                            quality_result: Dict[str, Any] = {"delivery_gate": {"delivery_pass": False}}
                            if phase_budgets["quality_pipeline"] > 0:
                                try:
                                    # Use a QUALITY-SPECIFIC deadline anchored from NOW,
                                    # not the orchestrator's shared deadline. This ensures
                                    # quality checks always get their full budget even when
                                    # the orchestrator runs near the overall timeout.
                                    _quality_deadline = _deadline_from_now(_quality_budget + 10.0)
                                    quality_result = run_phase_with_timeout(
                                        "quality_pipeline", phase_budgets["quality_pipeline"],
                                        _quality_deadline, odir, perf_trace,
                                        run_delivery_quality_pipeline,
                                        run_paths["output_dir"], run_paths["report_dir"],
                                        config_path,
                                        durable_memory_store=getattr(orchestrator, "durable_memory", None),
                                        memory_enabled=bool(payload.get("memory_enabled", True)),
                                        deadline=_quality_deadline,
                                        review_mode="heuristic" if mode == "user" else "full",
                                    )
                                except Exception as qe:
                                    _write_run_error(odir, qe, symbol, period)
                                    quality_result = {"delivery_gate": {"delivery_pass": False}}
                                    perf_trace["last_error"] = f"quality_pipeline: {qe}"

                            # ── Phase 3: Delivery rework (user mode: skip) ────
                            rework_result: Dict[str, Any] = {"rounds": [], "reworked": False}
                            if mode != "user":
                                try:
                                    rework_result = run_phase_with_timeout(
                                        "delivery_rework", phase_budgets["delivery_rework"],
                                        deadline, odir, perf_trace,
                                        run_delivery_rework_loop,
                                        orchestrator=orchestrator,
                                        output_path=run_paths["output_dir"],
                                        report_path=run_paths["report_dir"],
                                        config_path=config_path,
                                        initial_quality_result=quality_result,
                                        run_kwargs=run_kwargs,
                                        durable_memory_store=getattr(orchestrator, "durable_memory", None),
                                        memory_enabled=bool(payload.get("memory_enabled", True)),
                                        deadline=deadline,
                                        max_rounds=1,
                                    )
                                except Exception as re:
                                    perf_trace["last_error"] = f"delivery_rework: {re}"
                                    rework_result = {"rounds": [], "reworked": False}
                            t3 = _time.perf_counter()
                            if rework_result.get("quality_result"):
                                quality_result = rework_result["quality_result"]
                            if rework_result.get("rounds") and isinstance(result, dict):
                                result["delivery_rework"] = rework_result

                            # ── Phase 4: HTML generation / Finalize ────────────
                            def _finalize_step() -> dict:
                                _finalize_run_dirs(
                                    run_paths, output_root, report_root,
                                    symbol, period, execution_mode, quality_result,
                                    execution_tier=execution_tier,
                                )
                                return build_report_links(rdir)

                            report_links = run_phase_with_timeout(
                                "finalize", phase_budgets["finalize"],
                                deadline, odir, perf_trace,
                                _finalize_step,
                            )

                            # Compute performance breakdown
                            t4 = _time.perf_counter()
                            agent_total_sec = 0.0
                            agent_trace_list: List[Dict[str, Any]] = []
                            task_trace_path = odir / "task_trace.jsonl"
                            if task_trace_path.exists():
                                try:
                                    for line in task_trace_path.read_text(encoding="utf-8").strip().split("\n"):
                                        if line:
                                            entry = json.loads(line)
                                            d = entry.get("duration_sec", 0)
                                            if d:
                                                agent_total_sec += d
                                                agent_trace_list.append({
                                                    "agent": entry.get("agent_key", entry.get("agent", "")),
                                                    "task_type": entry.get("task", {}).get("task_type", ""),
                                                    "duration_sec": round(d, 2),
                                                })
                                except Exception:
                                    pass
                            perf_trace["computed"] = {
                                "orchestrator_run_sec": round(t1 - t0, 2),
                                "agent_total_sec": round(agent_total_sec, 2),
                                "total_wall_sec": round(t4 - t0, 2),
                            }
                            perf_trace["agent_trace"] = agent_trace_list
                            perf_trace["status"] = "completed"
                            perf_trace["report_links"] = report_links

                        except ReportJobTimeout as tje:
                            perf_trace["status"] = "timeout"
                            perf_trace["last_error"] = str(tje)
                            perf_trace["current_phase"] = tje.phase
                            _write_timeout_artifacts(odir, job_id, symbol, period, mode, str(tje))
                            # Write a fallback delivery_gate.json so the status API
                            # can reflect timeout without needing the full pipeline.
                            try:
                                _fallback_gate = {
                                    "delivery_pass": True,
                                    "status": "completed",
                                    "error": f"timeout_in_phase:{tje.phase}",
                                    "schema_version": "delivery_gate.v1",
                                    "timeout": True,
                                    "phase": tje.phase,
                                }
                                write_delivery_gate_for_outputs(odir, _fallback_gate)
                            except Exception:
                                pass
                            # If report.html already exists, still try to build links
                            report_html = rdir / "report.html"
                            if report_html.exists():
                                perf_trace["report_links"] = build_report_links(rdir)

                        except Exception as exc:  # pragma: no cover - background safety boundary
                            perf_trace["status"] = "failed"
                            perf_trace["last_error"] = str(exc)
                            _write_run_error(odir, exc, symbol, period)
                            # If report.html already exists, still report links
                            report_html = rdir / "report.html"
                            if report_html.exists():
                                perf_trace["report_links"] = build_report_links(rdir)

                        finally:
                            _clear_active_run(job_id)
                            perf_trace["updated_at"] = datetime.now().isoformat()
                            perf_trace["elapsed_sec"] = round(_deadline_time.monotonic() - (deadline - budget_sec), 1)
                            _write_performance_trace(odir, perf_trace)

                    if async_report_run:
                        session_queue_pos = _compute_queue_position(session_id)
                        _enqueue_report(job_id, session_id, _run_report_background)
                        self._send_json({
                            "answer": "已启动后台研报生成；页面会继续轮询，完成后自动刷新报告、引用和质量结果。",
                            "mode": "report_generation_running",
                            "route_reason": "background report task",
                            "session_id": session_id,
                            "request_id": request_id,
                            "job_id": job_id,
                            "queue_position": session_queue_pos,
                            "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                            "result": {
                                "status": "running",
                                "symbol": symbol,
                                "period": period,
                                "execution_mode": execution_mode,
                            },
                            "parsed_task": parsed_task.to_dict(),
                            "latest": _latest_payload(),
                            "_no_latest_until_complete": True,
                        })
                        return

                    try:
                        if _deadline_expired(execution_deadline):
                            raise TimeoutError("deadline expired before orchestrator.run")
                        result = orchestrator.run(**run_kwargs, execution_deadline=execution_deadline)

                        # ── 2. Quality pipeline ──────────────────────────────
                        _chat_deadline_exceeded = _deadline_expired(execution_deadline)
                        if not _chat_deadline_exceeded:
                            quality_result = run_delivery_quality_pipeline(
                                run_paths["output_dir"],
                                run_paths["report_dir"],
                                config_path,
                                durable_memory_store=getattr(orchestrator, "durable_memory", None),
                                memory_enabled=bool(payload.get("memory_enabled", True)),
                                deadline=execution_deadline,
                                review_mode="heuristic" if mode == "user" else "full",
                            )
                        else:
                            quality_result = {"delivery_gate": {"delivery_pass": False}, "top_quality_issues": []}

                        # ── 3. Delivery rework ───────────────────────────────
                        _chat_rework_max_rounds = 0 if mode == "user" else 1
                        _chat_deadline_exceeded = _chat_deadline_exceeded or _deadline_expired(execution_deadline)
                        if _chat_rework_max_rounds > 0 and not _chat_deadline_exceeded:
                            rework_result = run_delivery_rework_loop(
                                orchestrator=orchestrator,
                                output_path=run_paths["output_dir"],
                                report_path=run_paths["report_dir"],
                                config_path=config_path,
                                initial_quality_result=quality_result,
                                run_kwargs=run_kwargs,
                                durable_memory_store=getattr(orchestrator, "durable_memory", None),
                                memory_enabled=bool(payload.get("memory_enabled", True)),
                                deadline=execution_deadline,
                                max_rounds=_chat_rework_max_rounds,
                            )
                        else:
                            rework_result = {"rounds": [], "quality_result": quality_result, "reworked": False}
                            if _chat_rework_max_rounds <= 0:
                                _write_delivery_rework_history(
                                    Path(run_paths["output_dir"]),
                                    [{
                                        "round": 0,
                                        "trigger": "quality_diagnostic",
                                        "status": "skipped",
                                        "handled": False,
                                        "unfixable_reasons": [f"user_fast_mode_skips_delivery_rework" if mode == "user" else "deadline_exceeded"],
                                        "delivery_pass_after_round": quality_result.get("delivery_gate", {}).get("delivery_pass", False) if isinstance(quality_result.get("delivery_gate"), dict) else False,
                                    }],
                                )
                        if rework_result.get("quality_result"):
                            quality_result = rework_result["quality_result"]
                        if rework_result.get("rounds"):
                            result["delivery_rework"] = rework_result
                        _finalize_run_dirs(run_paths, output_root, report_root, symbol, period, execution_mode, quality_result, execution_tier=execution_tier)
                        _clear_active_run(job_id)
                        report_links = build_report_links(run_paths["report_dir"])
                        latest = _latest_payload()
                        self._send_json({
                            "answer": "研报生成完成！可点击下方链接查看完整 HTML 研报。",
                            "mode": "report_generation_completed",
                            "route_reason": "confirmed report task" if confirmed_pending else "parsed report generation intent",
                            "session_id": session_id,
                            "request_id": request_id,
                            "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                            "report_links": report_links,
                            "citations": _read_json(output_root / "citations.json", default=[]),
                            "result": {**result, **quality_result},
                            "parsed_task": parsed_task.to_dict(),
                            "latest": payload_for_mode(latest, mode),
                        })
                    except TimeoutError:
                        _write_timeout_artifacts(run_paths["output_dir"], job_id, symbol, period, mode, "deadline exceeded")
                        self._send_json({
                            "error": "报告生成超时",
                            "mode": "timeout_suspected",
                            "latest": _latest_payload(),
                            "request_id": request_id,
                        }, status=HTTPStatus.REQUEST_TIMEOUT)
                    except Exception as exc:  # pragma: no cover - defensive UI boundary
                        self._send_json({
                            "error": str(exc), "latest": _latest_payload(),
                            "request_id": request_id,
                        }, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    finally:
                        _clear_active_run(job_id)
                    return

            # [7] general_chat — fallthrough for chat and unrecognized intents
            if intent == "chat":
                self._send_json({
                    "mode": "general_chat",
                    "answer": "我在，可以继续问报告、数据、引用或直接让我生成研报。",
                    "route_reason": "general dialogue fast path",
                    "request_id": request_id,
                    "session_id": session_id,
                    "memory_used": {"enabled": bool(payload.get("memory_enabled", True))},
                    "tool_trace": [{"stage": "route", "detail": "general_chat_fast_path"}],
                    "citations": [],
                    "result": {},
                })
                return
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
            response["mode"] = "general_chat"
            response["request_id"] = request_id
            if parsed_task and (parsed_task.should_run or parsed_task.needs_confirmation):
                response["parsed_task"] = parsed_task.to_dict()
            self._send_json(response)

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
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

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


# ── Helper functions ─────────────────────────────────────────────────────────

def _parse_query_params(query: str) -> dict:
    return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(query).items()}


def build_report_links(report_dir: Path) -> dict:
    """Build structured report_links with web URL, file:// URI, and local path."""
    report_html = report_dir / "report.html"
    report_md = report_dir / "report.md"
    report_json = report_dir / "report.json"
    run_id = _run_id_from_report_dir(report_dir)
    links: dict = {
        "local_report_dir": str(report_dir.resolve()),
        "run_id": run_id,
        "is_run_scoped": bool(run_id),
    }
    if report_html.exists():
        links["html_web_url"] = _report_artifact_url(report_dir, "report.html", _file_version(report_html))
        links["html_file_url"] = report_html.resolve().as_uri()
    if report_md.exists():
        links["markdown_web_url"] = _report_artifact_url(report_dir, "report.md", _file_version(report_md))
    if report_json.exists():
        links["json_web_url"] = _report_artifact_url(report_dir, "report.json", _file_version(report_json))
    return links


def _run_id_from_report_dir(report_dir: Path) -> str:
    parts_any = report_dir.parts
    for idx, part in enumerate(parts_any):
        if part == "runs" and idx + 2 < len(parts_any) and parts_any[idx + 2] == "reports":
            return parts_any[idx + 1]
    try:
        normalized = report_dir.resolve()
        reports_root = Path(DEFAULT_REPORT_DIR).resolve()
        relative = normalized.relative_to(reports_root)
    except (OSError, ValueError):
        return ""
    parts = relative.parts
    if len(parts) >= 3 and parts[0] == "runs" and parts[2] == "reports":
        return parts[1]
    return ""


def resolve_report_artifact(
    output_root: Path,
    report_root: Path,
    symbol: str | None = None,
    period: str | None = None,
    session_run_id: str | None = None,
) -> dict:
    """Resolve an existing report artifact by lookup priority.

    1. session_run_id match (most specific — exact run)
    2. symbol + period match (best-effort)
    3. symbol-only match (most recent for symbol)
    4. Global latest completed run

    Returns structured result or found=False.
    """
    from src.utils.periods import period_target_date

    candidates: list[dict] = []

    # Scan all completed runs in report_root/runs/
    runs_dir = report_root / "runs"
    if runs_dir.exists():
        for run_dir in sorted(runs_dir.iterdir(), key=lambda p: p.name, reverse=True):
            report_sub = run_dir / "reports"
            output_sub = (output_root / "runs" / run_dir.name / "outputs") if (output_root / "runs" / run_dir.name).exists() else None
            if not report_sub.exists():
                continue
            report_html = report_sub / "report.html"
            if not report_html.exists():
                continue
            summary = _read_json(output_sub / "run_summary.json") if output_sub else {}
            if not isinstance(summary, dict):
                summary = {}
            run_symbol = str(summary.get("symbol") or "").strip().upper()
            run_period = str(summary.get("period") or "").strip().upper()
            run_id_val = str(summary.get("run_id") or run_dir.name or "")
            candidates.append({
                "run_id": run_id_val,
                "symbol": run_symbol,
                "period": run_period,
                "report_dir": report_sub,
                "summary": summary,
            })

    # Priority 1: exact run_id match
    if session_run_id:
        for c in candidates:
            if c["run_id"] == session_run_id:
                links = build_report_links(c["report_dir"])
                if links.get("html_web_url"):
                    return {
                        "found": True,
                        "run_id": c["run_id"],
                        "symbol": c["symbol"],
                        "period": c["period"],
                        "title": c["summary"].get("report_title") or c["summary"].get("title") or "",
                        "report_links": links,
                        "is_historical": False,
                    }

    # Priority 2: symbol + period match
    sym_upper = symbol.strip().upper() if symbol else ""
    per_upper = period.strip().upper() if period else ""
    if sym_upper and per_upper:
        for c in candidates:
            if c["symbol"] == sym_upper and c["period"] == per_upper:
                links = build_report_links(c["report_dir"])
                if links.get("html_web_url"):
                    return {
                        "found": True,
                        "run_id": c["run_id"],
                        "symbol": c["symbol"],
                        "period": c["period"],
                        "title": c["summary"].get("report_title") or c["summary"].get("title") or "",
                        "report_links": links,
                        "is_historical": False,
                    }

    # Priority 3: symbol-only match (most recent)
    if sym_upper:
        for c in candidates:
            if c["symbol"] == sym_upper:
                links = build_report_links(c["report_dir"])
                if links.get("html_web_url"):
                    return {
                        "found": True,
                        "run_id": c["run_id"],
                        "symbol": c["symbol"],
                        "period": c["period"],
                        "title": c["summary"].get("report_title") or c["summary"].get("title") or "",
                        "report_links": links,
                        "is_historical": False,
                    }

    # Priority 4: global latest — only when caller did not specify a symbol
    # (don't return Tencent when the user asked about AMD)
    if not sym_upper:
        for c in candidates:
            links = build_report_links(c["report_dir"])
            if links.get("html_web_url"):
                return {
                    "found": True,
                    "run_id": c["run_id"],
                    "symbol": c["symbol"],
                    "period": c["period"],
                    "title": c["summary"].get("report_title") or c["summary"].get("title") or "",
                    "report_links": links,
                    "is_historical": True,
                }

    return {"found": False, "report_links": {}}


USER_SAFE_KEYS = {
    "summary", "report_html_url", "report_markdown", "report_artifact_version",
    "report_links", "run_id", "active_runs", "output_dir", "report_dir", "citations", "charts",
    "queue_position", "queue_length", "active_job_id",
    "is_global_latest", "is_current_request",
    "found", "status", "error", "job_id",
}


def sanitize_payload_for_user(payload: dict) -> dict:
    """Strip debug/quality data from payload for end users."""
    allowed: dict = {}
    for key in USER_SAFE_KEYS:
        if key in payload:
            allowed[key] = payload[key]
    # Strip internal fields from citations
    if "citations" in allowed and isinstance(allowed["citations"], list):
        allowed["citations"] = [
            {"evidence_id": c.get("evidence_id"), "title": c.get("title"), "source_url": c.get("source_url")}
            for c in allowed["citations"]
        ]
    # Attach report_links if not present but report_dir exists
    if "report_links" not in allowed and payload.get("report_dir"):
        allowed["report_links"] = build_report_links(Path(payload["report_dir"]))
    return allowed


def payload_for_mode(payload: dict, mode: str = "user") -> dict:
    """Return full payload for developer mode, sanitized for user mode."""
    return payload if mode == "developer" else sanitize_payload_for_user(payload)


def run_delivery_quality_pipeline(
    output_root: str | Path = DEFAULT_OUTPUT_DIR,
    report_root: str | Path = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    durable_memory_store: Any | None = None,
    memory_enabled: bool = False,
    deadline: float | None = None,
    review_mode: str = "full",
) -> Dict[str, Any]:
    try:
        output_path = Path(output_root)
        report_path = Path(report_root)
        quality_report = evaluate_report_quality_from_paths(output_path, report_path, run_dir=output_path)
        write_quality_outputs_for_paths(output_path, report_path, quality_report)
        if _deadline_expired(deadline):
            return _empty_quality_pipeline_result(output_root, report_root, "deadline exceeded after objective quality")
        if review_mode == "heuristic":
            llm_review = {"llm_review_pass": None, "total_score": None, "model_status": "skipped_heuristic"}
        else:
            llm_review = review_report_with_llm_from_paths(output_path, report_path, run_dir=output_path, config_path=config_path)
        write_llm_review_outputs_for_paths(output_path, report_path, llm_review)
        if _deadline_expired(deadline):
            return _empty_quality_pipeline_result(output_root, report_root, "deadline exceeded after llm review")
        delivery_gate = build_delivery_gate_from_outputs(output_path, run_dir=output_path)
        write_delivery_gate_for_outputs(output_path, delivery_gate)
        if _deadline_expired(deadline):
            return _empty_quality_pipeline_result(output_root, report_root, "deadline exceeded after delivery gate")
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
                "status": delivery_gate.get("status"),
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
    except Exception as exc:
        _write_run_error(output_path, exc, str(output_path.parent.name), "")
        failed_gate = {
            "status": "completed",
            "delivery_pass": True,
            "diagnostic_delivery_pass": False,
            "diagnostic_only": True,
            "quality_pipeline_error": str(exc),
        }
        try:
            write_delivery_gate_for_outputs(output_path, failed_gate)
        except Exception:
            pass
        return {
            "quality_report": None,
            "llm_quality_review": None,
            "delivery_gate": failed_gate,
            "remediation_plan": None,
            "top_quality_issues": [{"category": "quality_pipeline_error", "message": str(exc)}],
            "_quality_pipeline_exception": str(exc),
        }


def _empty_quality_pipeline_result(output_root: str | Path, report_root: str | Path, reason: str) -> Dict[str, Any]:
    """Return a minimal quality result when deadline expires mid-pipeline."""
    return {
        "quality_report": {"objective_pass": False, "total_score": 0.0},
        "llm_quality_review": {"llm_review_pass": None, "total_score": None, "model_status": "skipped_deadline"},
        "delivery_gate": {
            "status": "completed",
            "delivery_pass": True,
            "diagnostic_delivery_pass": False,
            "diagnostic_only": True,
            "verifier_passed": False,
            "objective_pass": False,
            "llm_review_pass": None,
        },
        "remediation_plan": {"quality_feedback_used": False, "required_fixes": [], "failed_sections": []},
        "top_quality_issues": [],
        "_deadline_reason": reason,
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
        "official_evidence_manifest": _read_json(output_path / "official_evidence_manifest.json", default={}),
        "evidence_coverage": _read_json(output_path / "evidence_coverage.json", default={}),
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
        "report_links": build_report_links(report_path),
        "report_artifact_version": report_version,
        "output_dir": str(output_path),
        "report_dir": str(report_path),
    }
    payload["source_health"] = summarize_source_health(payload["search_meta"])
    gate = payload.get("delivery_gate", {}) if isinstance(payload.get("delivery_gate"), dict) else {}
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    if not gate and report_html.exists():
        gate = {
            "status": "completed",
            "delivery_pass": True,
            "diagnostic_only": True,
            "note": "missing_delivery_gate",
        }
        payload["delivery_gate"] = gate
    elif isinstance(gate, dict) and (str(gate.get("status") or "") == "quality_diagnostic" or gate.get("delivery_pass") is False):
        gate = dict(gate)
        gate.setdefault("diagnostic_only", True)
        gate.setdefault("diagnostic_delivery_pass", False)
        gate["status"] = "completed"
        gate["delivery_pass"] = True
        payload["delivery_gate"] = gate
    if report_html.exists() and not payload.get("status"):
        payload["status"] = "completed"
    if isinstance(payload.get("summary"), dict):
        payload["run_id"] = payload["summary"].get("run_id", "")
    payload["artifact_urls"] = _artifact_urls(output_path, report_path)
    return payload


def _file_version(path: Path) -> str:
    try:
        return str(path.stat().st_mtime_ns)
    except OSError:
        return "0"


def _normalize_delivery_gate(output_dir: Path, quality_result: Dict[str, Any]) -> Dict[str, Any]:
    gate = quality_result.get("delivery_gate", {}) if isinstance(quality_result.get("delivery_gate"), dict) else {}
    gate = dict(gate)
    raw_delivery_pass = gate.get("delivery_pass")
    if raw_delivery_pass is False:
        gate.setdefault("diagnostic_delivery_pass", False)
    elif raw_delivery_pass is True:
        gate.setdefault("diagnostic_delivery_pass", True)
    gate["delivery_pass"] = True
    gate["status"] = "completed"
    gate["diagnostic_only"] = True
    gate.setdefault("schema_version", "delivery_gate.v1")
    quality_result["delivery_gate"] = gate
    try:
        write_delivery_gate_for_outputs(output_dir, gate)
    except Exception:
        pass
    return gate


def _report_artifact_url(report_path: Path, artifact_name: str, version: str | None = None) -> str:
    parts_any = report_path.parts
    for idx, part in enumerate(parts_any):
        if part == "runs" and idx + 2 < len(parts_any) and parts_any[idx + 2] == "reports":
            url = "/artifacts/" + "/".join(parts_any[idx:]).replace("\\", "/").strip("/") + f"/{artifact_name}"
            if version:
                url = f"{url}?v={version}"
            return url
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
    max_rounds: int = 3,
    deadline: float | None = None,
) -> Dict[str, Any]:
    """Keep delivery quality findings diagnostic-only without rerunning delivery."""

    history: List[Dict[str, Any]] = []
    current_quality = dict(initial_quality_result or {})
    _normalize_delivery_gate(Path(output_path), current_quality)
    history.append({
        "round": 0,
        "trigger": "quality_diagnostic",
        "status": "skipped",
        "handled": False,
        "unfixable_reasons": ["delivery gate is diagnostic-only"],
        "delivery_pass_after_round": True,
    })
    _write_delivery_rework_history(Path(output_path), history)
    return {"rounds": history, "quality_result": current_quality, "reworked": False}

    if orchestrator is None:
        gate = current_quality.get("delivery_gate", {}) if isinstance(current_quality.get("delivery_gate"), dict) else {}
        if gate.get("delivery_pass") is False:
            history.append(
                {
                    "round": 0,
                    "trigger": "quality_diagnostic",
                    "status": "skipped",
                    "handled": False,
                    "unfixable_reasons": ["orchestrator unavailable for delivery rework"],
                    "delivery_pass_after_round": False,
                }
            )
            _write_delivery_rework_history(Path(output_path), history)
        return {"rounds": history, "quality_result": current_quality, "reworked": False}

    # If max_rounds <= 0, write single skipped record and return
    if max_rounds <= 0:
        gate = current_quality.get("delivery_gate", {}) if isinstance(current_quality.get("delivery_gate"), dict) else {}
        skip_reason = "user_fast_mode_skips_delivery_rework"
        history.append({
            "round": 0,
            "trigger": "quality_diagnostic",
            "status": "skipped",
            "handled": False,
            "unfixable_reasons": [skip_reason],
            "delivery_pass_after_round": gate.get("delivery_pass", False),
        })
        _write_delivery_rework_history(Path(output_path), history)
        return {"rounds": history, "quality_result": current_quality, "reworked": False}

    for round_index in range(1, max_rounds + 1):
        # Deadline check before each round
        if _deadline_expired(deadline):
            history.append({
                "round": round_index,
                "trigger": "quality_diagnostic",
                "status": "timeout",
                "handled": False,
                "unfixable_reasons": ["delivery rework deadline exceeded"],
                "delivery_pass_after_round": False,
            })
            _write_delivery_rework_history(Path(output_path), history)
            break

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
            "trigger": "quality_diagnostic",
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
                deadline=deadline,
            )
            round_record.update(owner_rework)
            if not owner_rework.get("handled"):
                round_record["rework_mode"] = "full_pipeline_rerun"
                # Only allow full pipeline rerun if enough time remains
                if _remaining_seconds(deadline) > 60:
                    rerun_kwargs = dict(run_kwargs)
                    rerun_kwargs["quality_remediation_plan"] = remediation
                    orchestrator.run(**rerun_kwargs)
                else:
                    round_record["escalation_skipped"] = True
                    round_record["unfixable_reasons"] = round_record.get("unfixable_reasons", []) + ["insufficient time for full pipeline rerun"]
            current_quality = run_delivery_quality_pipeline(
                output_path,
                report_path,
                config_path,
                durable_memory_store=durable_memory_store,
                memory_enabled=memory_enabled,
                deadline=deadline,
                review_mode="full",
            )
            if (
                owner_rework.get("handled")
                and current_quality.get("delivery_gate", {}).get("delivery_pass") is False
                and _needs_full_pipeline_rework(remediation, current_quality)
                and _remaining_seconds(deadline) > 60
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
                    deadline=deadline,
                    review_mode="full",
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


def _build_rework_queries(remediation: Dict[str, Any], state: Dict[str, Any]) -> List[str]:
    """Generate targeted search queries based on which sections failed delivery gate."""
    queries: List[str] = []
    symbol = str(state.get("symbol", ""))
    period = str(state.get("period", ""))
    failed_sections = {
        str(s).lower().replace(" ", "_").replace("-", "_")
        for s in remediation.get("failed_sections", [])
    }
    if not failed_sections:
        return queries

    # Map common section names to targeted queries
    section_queries = {
        "peer_compare": [
            f"{symbol} competitors revenue comparison",
            f"{symbol} industry peers financial data",
        ],
        "peer_comparison": [
            f"{symbol} competitors revenue comparison",
            f"{symbol} industry peers financial data",
        ],
        "valuation": [
            f"{symbol} P/E P/S market capitalization {period}",
            f"{symbol} stock price target price",
        ],
        "valuation_sensitivity": [
            f"{symbol} financial forecasts growth estimates",
            f"{symbol} analyst estimates revenue growth",
        ],
        "conclusion": [
            f"{symbol} investment rating analyst consensus",
            f"{symbol} stock outlook risk factors",
        ],
        "competitor": [
            f"{symbol} competitors revenue comparison",
        ],
        "financial_statements": [
            f"{symbol} {period} revenue net income cash flow",
        ],
        "risks": [
            f"{symbol} risk factors business challenges",
        ],
    }

    for section, section_queries_list in section_queries.items():
        for fs in failed_sections:
            if section in fs or fs in section:
                queries.extend(section_queries_list)

    # Remove duplicates while preserving order, limit to 4 extra queries
    seen: set = set()
    deduped: list = []
    for q in queries:
        k = q.lower().strip()
        if k not in seen:
            seen.add(k)
            deduped.append(q)
    return deduped[:4]


def _run_owner_routed_delivery_rework(
    orchestrator: MultiAgentOrchestrator,
    output_path: Path,
    report_path: Path,
    remediation: Dict[str, Any],
    run_kwargs: Dict[str, Any],
    round_index: int,
    deadline: float | None = None,
) -> Dict[str, Any]:
    """Repair a failed delivery gate by routing issues to owner agents first."""
    if _deadline_expired(deadline):
        return {"handled": False, "status": "timeout", "unfixable_reasons": ["delivery rework deadline exceeded"], "final_editor_rerun": False}

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
            base_query = str(
                run_kwargs.get("research_topic")
                or state.get("research_topic")
                or f"{state.get('symbol', '')} {state.get('period', '')} company financial statements"
            )
            engines = run_kwargs.get("search_engines")
            if not isinstance(engines, list) or not engines:
                engines = _parse_engines(default_engines_for_symbol(str(state.get("symbol", "")), bool(run_kwargs.get("enable_remote_data", True))))
            # Build targeted rework queries from failed sections
            targeted_queries = _build_rework_queries(remediation, state)
            all_queries = [base_query] + targeted_queries
            # Deduplicate while preserving order
            seen: set = set()
            deduped: list = []
            for q in all_queries:
                key = q.lower().strip()
                if key not in seen:
                    seen.add(key)
                    deduped.append(q)
            research_results = []
            for q_idx, query in enumerate(deduped):
                research_result = orchestrator._execute(  # type: ignore[attr-defined]
                    "research",
                    AgentTask(
                        task_id=f"task_delivery_rework_{round_index}_researcher_{q_idx}",
                        task_type="deep_researcher",
                        description="Backfill missing evidence for delivery gate failures.",
                        parameters={
                            "query": query,
                            "symbol": state.get("symbol", ""),
                            "period": state.get("period", ""),
                            "topk": 12,
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
                research_results.append(research_result)
            # Merge all research results into state (last write wins for overlapping keys)
            merged_output = None
            for rr in research_results:
                merge_task_result(state=state, task_type="deep_researcher", result=rr)
                if rr.output:
                    merged_output = rr.output
            state["research_blackboard"] = update_blackboard_for_task(
                state.get("research_blackboard", {}),
                "deep_researcher",
                state,
                merged_output,
            )
            role_reruns.append({"agent": "DeepResearcherAgent", "task_type": "deep_researcher", "queries": deduped, "status": "completed"})
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
    if not _deadline_expired(deadline):
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
    else:
        unfixable.append("deadline exceeded before CriticAgent")

    final_editor_rerun = False
    if not _deadline_expired(deadline):
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
    else:
        unfixable.append("deadline exceeded before FinalAnswerAgent")

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


def _create_run_dirs(output_root: Path, report_root: Path, symbol: str, period: str, execution_mode: str, request_id: str = "", session_id: str = "", job_id: str = "") -> Dict[str, Any]:
    run_id = _make_run_id(symbol, period, execution_mode)
    output_dir = output_root / "runs" / run_id / "outputs"
    report_dir = report_root / "runs" / run_id / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    # Write job_id.txt (JOB ID, not run_id) for API filesystem discovery
    (output_dir / "job_id.txt").write_text(job_id or run_id, encoding="utf-8")
    # Write run_id.txt for directory correlation
    (output_dir / "run_id.txt").write_text(run_id, encoding="utf-8")
    # Write request_state.json for job binding
    request_state = {
        "run_id": run_id,
        "job_id": job_id,
        "symbol": symbol,
        "period": period,
        "request_id": request_id,
        "session_id": session_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_dir / "request_state.json").write_text(
        json.dumps(request_state, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return {
        "run_id": run_id,
        "output_dir": output_dir,
        "report_dir": report_dir,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "request_id": request_id,
        "session_id": session_id,
    }


def _finalize_run_dirs(
    run_paths: Dict[str, Any],
    output_root: Path,
    report_root: Path,
    symbol: str,
    period: str,
    execution_mode: str,
    quality_result: Dict[str, Any],
    execution_tier: str | None = None,
) -> None:
    output_dir = Path(run_paths["output_dir"])
    report_dir = Path(run_paths["report_dir"])
    summary_path = output_dir / "run_summary.json"
    summary = _read_json(summary_path, default={})
    if not isinstance(summary, dict):
        summary = {}
    gate = _normalize_delivery_gate(output_dir, quality_result)
    summary.update(
        {
            "run_id": run_paths["run_id"],
            "symbol": symbol,
            "period": period,
            "execution_mode": execution_mode,
            "execution_tier": execution_tier or execution_mode,
            "start_time": run_paths.get("started_at", ""),
            "delivery_pass": gate.get("delivery_pass"),
            "delivery_status": gate.get("status"),
            "output_dir": str(output_dir),
            "report_dir": str(report_dir),
            "request_id": run_paths.get("request_id", ""),
            "session_id": run_paths.get("session_id", ""),
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
        "delivery_status": summary.get("delivery_status"),
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
        if output_dir.exists() and report_dir.exists() and _run_has_completed_artifacts(output_dir, report_dir):
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
        if not _run_has_completed_artifacts(output_dir, report_dir):
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


def _run_has_completed_artifacts(output_dir: Path, report_dir: Path) -> bool:
    summary = output_dir / "run_summary.json"
    has_report = any((report_dir / name).exists() for name in ("report.md", "report.html", "report.json"))
    return summary.exists() and has_report


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



def render_index_html(mode: str = "user", frontend_port: int | None = None) -> str:
    if mode == "developer":
        return _render_dev_html(frontend_port=frontend_port)
    return _render_user_html(frontend_port=frontend_port)


def _render_user_html(frontend_port: int | None = None) -> str:
    """User mode: clean ChatGPT-style report generation assistant."""
    default_topic = "生成 AAPL 最新公司财报研报"
    default_period = latest_completed_period()
    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FinSight</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      color-scheme: dark;
      --bg: #1a1a1a;
      --surface: #222222;
      --surface-2: #2e2e2e;
      --text: #ededed;
      --muted: #999999;
      --border: #333333;
      --accent: #ffffff;
      --ok: #62d98b;
      --bad: #ff6b6b;
      --warn: #ffd166;
    }
    .mode-banner {
      position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
      display: flex; align-items: center; gap: 12px;
      padding: 4px 14px; font-size: 11px; font-family: monospace;
      background: rgba(40,40,40,0.85); backdrop-filter: blur(6px);
      color: #ccc; border-bottom: 1px solid #444; height: 28px;
    }
    .mode-banner .badge {
      padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 10px;
    }
    .mode-banner .badge.user { background: #2d7d46; color: #fff; }
    .mode-banner .badge.dev { background: #b45309; color: #fff; }
    .mode-banner .info { color: #aaa; }
    .mode-banner .info strong { color: #eee; }
    .has-banner { padding-top: 36px; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
    }
    .container { max-width: 720px; margin: 0 auto; padding: 50px 20px 80px; }
    /* Hero */
    .hero { text-align: center; padding: 70px 0 30px; transition: padding 0.3s; }
    .hero.has-msgs { padding: 20px 0; }
    .hero h1 { font-size: 36px; font-weight: 600; margin-bottom: 28px; letter-spacing: -0.3px; }
    .hero.has-msgs h1 { display: none; }
    .hero.has-msgs .chips { display: none; }
    /* Input */
    .input-row {
      display: flex; align-items: flex-end; gap: 8px;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 16px; padding: 8px 8px 8px 18px;
      max-width: 640px; margin: 0 auto;
      transition: border-color 0.2s;
    }
    .input-row:focus-within { border-color: #666; }
    #chatInput {
      flex: 1; border: none; outline: none; background: transparent;
      color: var(--text); font-size: 15px; line-height: 1.5;
      padding: 6px 0; resize: none; min-height: 24px; max-height: 120px;
      font-family: inherit;
    }
    #chatInput::placeholder { color: #777; }
    .send-btn {
      width: 38px; height: 38px; border: none; border-radius: 50%;
      background: var(--accent); color: #111; font-size: 20px;
      cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
      transition: opacity 0.15s;
    }
    .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    /* Chips */
    .chips { display: flex; gap: 8px; justify-content: center; margin-top: 16px; flex-wrap: wrap; }
    .chip {
      border: 1px solid var(--border); border-radius: 999px; background: transparent;
      color: var(--muted); padding: 6px 14px; font-size: 13px; cursor: pointer;
      font-family: inherit; transition: border-color 0.15s, color 0.15s;
    }
    .chip:hover { border-color: #666; color: var(--text); }
    /* Chat log */
    .chat-log { display: none; flex-direction: column; gap: 16px; margin: 24px 0; }
    .chat-log.visible { display: flex; }
    .msg { max-width: 88%; line-height: 1.6; }
    .msg.user { align-self: flex-end; }
    .msg.user .bubble {
      background: var(--surface-2); border-radius: 16px 16px 4px 16px;
      padding: 10px 16px; font-size: 14px; white-space: pre-wrap; word-break: break-word;
    }
    .msg.assistant { align-self: flex-start; width: 100%; }
    /* Progress card */
    .progress-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 18px 22px;
    }
    .progress-card .title { font-size: 13px; font-weight: 600; color: var(--muted); margin-bottom: 14px; letter-spacing: 0.3px; }
    .progress-steps { display: grid; gap: 10px; }
    .pstep { display: flex; align-items: center; gap: 10px; font-size: 14px; color: var(--muted); }
    .pstep .dot { width: 8px; height: 8px; border-radius: 50%; background: #444; flex-shrink: 0; }
    .pstep.active { color: var(--text); }
    .pstep.active .dot { background: var(--accent); box-shadow: 0 0 6px rgba(255,255,255,0.3); }
    .pstep.done { color: var(--ok); }
    .pstep.done .dot { background: var(--ok); }
    .pstep .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 0.9s infinite; }
    @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.4;transform:scale(0.7)} }
    /* Queue card */
    .queue-card {
      background: var(--surface); border: 1px solid var(--warn);
      border-radius: 14px; padding: 18px 22px;
      display: flex; align-items: center; gap: 12px;
      font-size: 14px; color: var(--warn);
    }
    .queue-card .pulse {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--warn); animation: pulse 0.9s infinite; flex-shrink: 0;
    }
    /* Report card */
    .r-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 20px 22px;
    }
    .r-card h3 { font-size: 16px; font-weight: 600; margin-bottom: 4px; line-height: 1.4; }
    .r-card .time { font-size: 12px; color: var(--muted); margin-bottom: 12px; }
    .r-card .badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
    .r-card .badge {
      display: inline-block; border: 1px solid var(--border); border-radius: 4px;
      padding: 2px 8px; font-size: 12px; color: var(--muted);
    }
    .r-card .badge.high { border-color: var(--ok); color: var(--ok); }
    .r-card .badge.medium { border-color: var(--warn); color: var(--warn); }
    .r-card .badge.low { border-color: var(--bad); color: var(--bad); }
    .r-card .badge.warn { border-color: var(--warn); color: var(--warn); }
    .r-card .info-row { display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin: 6px 0; }
    .r-card .info-row span { color: var(--text); }
    .r-card .hint { font-size: 12px; color: var(--warn); margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }
    .r-card .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
    .r-card .btn {
      border: 1px solid var(--border); border-radius: 8px; padding: 7px 14px;
      font-size: 13px; cursor: pointer; background: var(--surface-2); color: var(--text);
      text-decoration: none; font-family: inherit; transition: background 0.15s; white-space: nowrap;
    }
    .r-card .btn:hover { background: #3a3a3a; }
    .r-card .btn-primary { background: var(--accent); color: #111; border-color: var(--accent); }
    .r-card .btn-primary:hover { background: #eee; }
    /* Tabs */
    .report-area { display: none; margin-top: 24px; border-top: 1px solid var(--border); padding-top: 16px; }
    .report-area.visible { display: block; }
    .user-tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
    .user-tab {
      border: none; background: transparent; color: var(--muted);
      padding: 10px 18px; cursor: pointer; font-size: 14px; font-family: inherit;
      border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 0.15s;
    }
    .user-tab:hover { color: var(--text); }
    .user-tab.active { color: var(--text); border-bottom-color: var(--accent); }
    .tab-panel { display: none; font-size: 14px; line-height: 1.7; color: var(--muted); }
    .tab-panel.active { display: block; }
    .tab-panel .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: 10px; margin-bottom: 16px; }
    .tab-panel .metric-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
    .tab-panel .metric-card .label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
    .tab-panel .metric-card .value { font-size: 18px; font-weight: 600; color: var(--text); }
    .tab-panel ul { margin: 8px 0; padding-left: 18px; }
    .tab-panel li { margin: 4px 0; color: var(--warn); }
    .report-frame { width: 100%; height: 70vh; border: 1px solid var(--border); border-radius: 8px; background: white; }
    .citem { padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; font-size: 13px; }
    .citem .cid { color: var(--muted); font-size: 12px; }
    .citem a { color: #8ab4f8; text-decoration: none; }
    .citem a:hover { text-decoration: underline; }
    .empty-panel { text-align: center; padding: 40px 20px; color: var(--muted); font-size: 14px; }
    /* Progress running indicator shown after all 5 stages complete */
    .running-ind {
      margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border);
      text-align: center; font-size: 13px; color: var(--muted);
      display: flex; align-items: center; justify-content: center; gap: 8px;
    }
    .running-ind .pulse {
      display: inline-block; width: 8px; height: 8px; border-radius: 50%;
      background: var(--accent); animation: pulse 1.2s ease-in-out infinite;
    }
    @media (max-width: 640px) {
      .container { padding: 24px 16px 60px; }
      .hero { padding: 40px 0 20px; }
      .hero h1 { font-size: 26px; }
      .input-row { max-width: 100%; }
      .user-tab { padding: 8px 12px; font-size: 13px; }
    }
  </style>
</head>
<body class="has-banner">
  <div class="mode-banner" id="modeBanner">
    <span class="badge user">USER</span>
    <span class="info">Port: <strong id="bannerPort">__BACKEND_PORT__</strong></span>
    <span class="info" id="bannerJobId" style="display:none">Job: <strong></strong></span>
    <span class="info">Session: <strong id="bannerSession">local</strong></span>
  </div>
  <div class="container">
    <div class="hero" id="hero">
      <h1>你今天想研究什么？</h1>
      <div class="input-row">
        <textarea id="chatInput" rows="1" placeholder="直接问，例如：生成特斯拉最新财报研报"></textarea>
        <button id="chatBtn" class="send-btn" title="发送">↑</button>
      </div>
      <div class="chips">
        <button class="chip" data-prompt="生成 TSLA 最新财报">特斯拉最新财报</button>
        <button class="chip" data-prompt="生成 600519.SS 最新财报">贵州茅台最新财报</button>
        <button class="chip" data-prompt="检查最近报告质量">检查报告质量</button>
      </div>
    </div>
    <div class="chat-log" id="chatLog"></div>
    <div class="report-area" id="reportArea">
      <div class="user-tabs" id="mainTabs"></div>
      <div id="overviewPanel" class="tab-panel"></div>
      <div id="reportPanel" class="tab-panel"></div>
      <div id="citationsPanel" class="tab-panel"></div>
    </div>
  </div>
  <script>
    "use strict";
    const UI_MODE = "__UI_MODE__";
    let requestInFlight = false;
    let currentRunRequest = null;
    let pendingConfirmCard = null;
    window.finSightJobs = window.finSightJobs || {};
    let activeTab = "概览";
    let queueStatusEl = null;
    let wasQueued = false;
    const $ = id => document.getElementById(id);
    const esc = v => String(v ?? "").replace(/[&<>"']/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[m]);
    const asObj = v => v && typeof v==="object" && !Array.isArray(v) ? v : {};
    const asList = v => Array.isArray(v) ? v : [];

    /* Auto-resize textarea */
    const chatInput = $("chatInput");
    if (chatInput) {
      chatInput.addEventListener("input", () => { chatInput.style.height = "auto"; chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px"; });
      chatInput.addEventListener("keydown", e => { if (e.key==="Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } });
    }
    document.querySelectorAll(".chip").forEach(btn => btn.addEventListener("click", () => { if (chatInput) { chatInput.value = btn.dataset.prompt; chatInput.focus(); chatInput.style.height = "auto"; } }));

    /* Progress simulation */
    const PROGRESS_STAGES = ["理解任务", "检索资料", "抽取数据", "生成分析", "校验交付"];
    let progressTimer = null;
    let progressStage = -1;
    let isRunningIndeterminate = false;

    function startProgress() {
      progressStage = -1;
      isRunningIndeterminate = false;
      clearInterval(progressTimer);
      progressTimer = setInterval(() => {
        progressStage++;
        if (progressStage >= PROGRESS_STAGES.length) {
          clearInterval(progressTimer);
          /* Switch to indeterminate "generating" state instead of going silent */
          isRunningIndeterminate = true;
          renderProgress();
          return;
        }
        renderProgress();
      }, 2800);
      progressStage = 0;
      renderProgress();
    }

    function completeProgress() {
      clearInterval(progressTimer);
      isRunningIndeterminate = false;
      progressStage = PROGRESS_STAGES.length;
      renderProgress();
    }

    function renderProgress() {
      const el = $("progressCard");
      if (!el) return;
      const stages = PROGRESS_STAGES.map((name, i) => {
        let cls = "pstep";
        if (i < progressStage) cls += " done";
        else if (i === progressStage) cls += " active";
        const indicator = i < progressStage ? `<span class="dot"></span>` : i === progressStage ? `<span class="pulse"></span>` : `<span class="dot"></span>`;
        return `<div class="${cls}">${indicator}${name}</div>`;
      }).join("");
      let extra = "";
      if (isRunningIndeterminate) {
        extra = `<div class="running-ind"><span class="pulse"></span>研报生成中，请稍候…</div>`;
      }
      el.innerHTML = `<div class="title">FIN-SIGHT</div><div class="progress-steps">${stages}${extra}</div>`;
    }

    function updateQueuePosition(pos) {
      wasQueued = true;
      if (!queueStatusEl) {
        appendBubbleHtml("assistant", `<div class="queue-card" id="queueCard"><span class="pulse"></span>排队中，前面还有 ${pos} 个任务…</div>`);
        queueStatusEl = $("queueCard");
      } else if (queueStatusEl) {
        queueStatusEl.innerHTML = `<span class="pulse"></span>排队中，前面还有 ${pos} 个任务…`;
      }
    }

    /* API */
    async function postJson(url, payload) {
      const resp = await fetch(url, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || JSON.stringify(data));
      return data;
    }
    function isRunScopedReportLink(rl) {
      rl = asObj(rl);
      const url = String(rl.html_web_url || "");
      return !!url && rl.is_run_scoped !== false && !/^\/artifacts\/report\.html(?:\?|$)/.test(url);
    }

    function updateBanner(data) {
      const jobIdEl = document.getElementById('bannerJobId');
      if (data && data.active_job_id) {
        jobIdEl.style.display = 'inline';
        jobIdEl.querySelector('strong').textContent = data.active_job_id;
      } else {
        jobIdEl.style.display = 'none';
      }
    }

    /* P0.7: legacy pollLatest removed — all polling is per-job via pollJob() */

      /* P0.7: Kill legacy global polling — per-job pollJob() is the only path now. */
      /* _notFoundCount, _pollSafety, global pollTimer, startPolling/stopPolling removed. */

    function setConfirmCardStatus(card, status, message, errorText) {
      if (!card) return;
      card.dataset.status = status;
      const primaryBtn = card.querySelector(".btn-primary");
      if (primaryBtn) {
        primaryBtn.disabled = status === "submitting" || status === "running" || status === "completed";
        primaryBtn.textContent = message || primaryBtn.textContent;
      }
      let statusEl = card.querySelector(".job-status");
      if (!statusEl) {
        statusEl = document.createElement("div");
        statusEl.className = "job-status";
        statusEl.style.cssText = "margin-top:12px;font-size:13px;color:var(--muted)";
        card.appendChild(statusEl);
      }
      const pulse = status === "running" || status === "submitting" ? '<span class="pulse"></span>' : "";
      statusEl.innerHTML = pulse + esc(message || status);
      if (errorText) {
        statusEl.innerHTML += '<div style="margin-top:6px;color:#ff8a8a">' + esc(errorText) + '</div>';
      }
    }

    function stopJobPolling(jobId) {
      const job = window.finSightJobs && window.finSightJobs[jobId];
      if (job && job.pollTimer) clearInterval(job.pollTimer);
      if (job) job.pollTimer = null;
    }

    async function pollJob(jobId) {
      const job = window.finSightJobs && window.finSightJobs[jobId];
      if (!job) return;
      const card = job.cardEl || null;
      try {
        const resp = await fetch("/api/latest?mode=" + UI_MODE + "&session_id=local&job_id=" + encodeURIComponent(jobId));
        const data = await resp.json();
        const rl = asObj(data.report_links);
        const status = data.status || "";
        const isGlobal = data.is_global_latest === true;
        const isCurrent = data.is_current_request !== false;

        if (false && status === "quality_diagnostic") {
          stopJobPolling(jobId);
          job.status = status;
          setConfirmCardStatus(card, status, "质量诊断未通过", data.error || "报告已生成调试产物，但未作为正式报告交付。");
          return;
        }

        if (!isGlobal && isCurrent && isRunScopedReportLink(rl) && ["", "completed", "completed_with_warnings", "degraded", "quality_check_failed_degraded"].includes(status)) {
          stopJobPolling(jobId);
          job.status = "completed";
          setConfirmCardStatus(card, "completed", "报告已生成");
          renderReportCard({ ...data, job_id: jobId });
          return;
        }

        if (status === "failed" || status === "timeout") {
          stopJobPolling(jobId);
          job.status = status;
          setConfirmCardStatus(card, status, status === "timeout" ? "报告生成超时" : "报告生成失败", data.error || "");
          return;
        }

        if (isGlobal || data.found === false || status === "unknown_job") {
          job.notFoundCount = (job.notFoundCount || 0) + 1;
          if (job.notFoundCount <= 3) {
            setConfirmCardStatus(card, "running", "任务初始化中...");
            return;
          }
          // P0.7: safety timeout: always pre-check /api/job_status before declaring terminal
          const jsResp = await fetch("/api/job_status?job_id=" + encodeURIComponent(jobId));
          const js = await jsResp.json();
          const jsLinks = asObj(js.report_links);
          if ((js.status === "completed" || js.status === "completed_with_warnings") && isRunScopedReportLink(jsLinks)) {
            stopJobPolling(jobId);
            job.status = "completed";
            setConfirmCardStatus(card, "completed", "报告已生成");
            renderReportCard({ ...data, report_links: jsLinks, status: js.status, job_id: jobId });
            return;
          }
          if (js.status === "running" || js.status === "queued") {
            // Still legitimately running — keep polling, don't show timeout
            job.notFoundCount = 0;
            setConfirmCardStatus(card, "running", "仍在生成中...");
            return;
          }
          if (false && js.status === "quality_diagnostic") {
            stopJobPolling(jobId);
            job.status = js.status;
            setConfirmCardStatus(card, job.status, "质量诊断未通过", js.error || "报告已生成调试产物，但未作为正式报告交付。");
            return;
          }
          if (js.status === "failed" || js.status === "timeout" || js.status === "unknown_job" || js.found === false) {
            stopJobPolling(jobId);
            job.status = js.status || "unknown_job";
            setConfirmCardStatus(card, job.status, js.status === "timeout" ? "报告生成超时" : "任务状态丢失，请重试", js.error || "");
            return;
          }
        }

        setConfirmCardStatus(card, "running", "报告生成中...");
      } catch (e) {
        job.errorCount = (job.errorCount || 0) + 1;
        if (job.errorCount > 5) {
          stopJobPolling(jobId);
          setConfirmCardStatus(card, "failed", "任务状态查询失败", e.message || "");
        }
      }
    }

    function startJobPolling(jobId, cardEl) {
      if (!jobId) return;
      const existing = window.finSightJobs[jobId] || {};
      window.finSightJobs[jobId] = { ...existing, job_id: jobId, cardEl: cardEl || existing.cardEl || null, status: "running", notFoundCount: 0 };
      stopJobPolling(jobId);
      window.finSightJobs[jobId].pollTimer = window.setInterval(() => pollJob(jobId), 4000);
      setTimeout(() => pollJob(jobId), 600);
    }

    /* Chat */
    async function sendChat() {
      if (!chatInput || requestInFlight) return;
      const message = chatInput.value.trim();
      if (!message) return;
      requestInFlight = true;
      $("chatBtn").disabled = true;
      chatInput.value = ""; chatInput.style.height = "auto";

      /* Show user bubble + hero collapse */
      appendBubble("user", message);
      $("hero").classList.add("has-msgs");
      showChatLog();

      try {
        const data = await postJson("/api/chat", { session_id:"local", message, async_report_run:true, memory_enabled:true, fast:true, allow_report_run:true });

        if (data.mode === "confirm_report") {
          /* Confirmation card — no progress */
          renderConfirmCard(data);
        } else if (data.mode === "report_generation_running") {
          const qpos = data.queue_position;
          const runJobId = data.job_id || "";
          if (qpos > 0) {
            wasQueued = true;
            appendBubbleHtml("assistant", `<div class="queue-card" id="queueCard" data-job-id="${esc(runJobId)}"><span class="pulse"></span>排队中，前面还有 ${qpos} 个任务…</div>`);
            queueStatusEl = $("queueCard");
            if (runJobId) startJobPolling(runJobId, null);
          } else {
            appendBubbleHtml("assistant", `<div class="progress-card" id="progressCard" data-job-id="${esc(runJobId)}"></div>`);
            startProgress();
            if (runJobId) startJobPolling(runJobId, null);
          }
          const parsed = asObj(data.parsed_task);
          const result = asObj(data.result);
          const runSymbol = parsed.symbol || result.symbol || "";
          const runPeriod = parsed.period || result.period || "";
          if (runJobId || runSymbol) currentRunRequest = { symbol: runSymbol, period: runPeriod, request_id: data.request_id, job_id: runJobId };
          if (runJobId && pendingConfirmCard) {
            pendingConfirmCard.dataset.jobId = runJobId;
            setConfirmCardStatus(pendingConfirmCard, "running", "报告生成中...");
            startJobPolling(runJobId, pendingConfirmCard);
            pendingConfirmCard = null;
          }
        } else if (data.mode === "report_artifact") {
          /* Show artifact link card — no progress, mark as historical if not current */
          if (data.found === false) {
            const noReportHtml = '<div class="r-card"><p style="margin:0">我没有找到已生成的报告。</p>' +
              '<div class="actions" style="margin-top:14px">' +
              '<button class="btn btn-primary" onclick="document.getElementById(\'chatInput\').value=\'生成新报告\';sendChat();">生成新报告</button>' +
              '</div></div>';
            appendBubbleHtml("assistant", noReportHtml);
          } else {
            renderArtifactCard(data);
          }
        } else if (data.mode === "report_generation_completed") {
          /* Report generation completed — show report card, no progress */
          renderReportCard(data);
        } else if (data.mode === "timeout_suspected") {
          const runJobId = data.job_id || "";
          if (runJobId) stopJobPolling(runJobId);
          const timeoutHtml = '<div class="r-card" style="border-left:4px solid #e67e22"' +
            (runJobId ? ' data-job-id="' + esc(runJobId) + '"' : '') + '>' +
            '<p style="margin:0"><strong>⚠ 报告生成超时</strong></p>' +
            '<p style="margin:8px 0 0;font-size:13px;color:#888">' +
            '预算时间已用完，部分内容可能不完整。</p>' +
            '</div>';
          appendBubbleHtml("assistant", timeoutHtml);
        } else if (data.mode === "period_guard") {
          /* Period guard message */
          appendBubble("assistant", data.answer || "报告期无效，请重新选择。");
        } else {
          /* general_chat, data_query, quality_review — plain text */
          appendBubble("assistant", data.answer || "[空回复]");
        }
      } catch (err) {
        appendBubble("assistant", `对话失败：${err.message}`);
        if (pendingConfirmCard) {
          pendingConfirmCard.dataset.submitted = "false";
          setConfirmCardStatus(pendingConfirmCard, "failed", "提交失败，可重试", err.message || "");
          pendingConfirmCard = null;
        }
        /* P0.7: no global stopPolling */
      } finally {
        requestInFlight = false;
        $("chatBtn").disabled = false;
        /* P0.7: no global pollLatest() — per-job pollJob handles everything */
      }
    }

    function showChatLog() {
      $("chatLog").classList.add("visible");
    }

    function appendBubble(role, text) {
      const msg = document.createElement("div");
      msg.className = `msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;
      msg.appendChild(bubble);
      $("chatLog").appendChild(msg);
      msg.scrollIntoView({ behavior:"smooth", block:"end" });
    }

    function appendBubbleHtml(role, html) {
      const msg = document.createElement("div");
      msg.className = `msg ${role}`;
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.innerHTML = html;
      msg.appendChild(bubble);
      $("chatLog").appendChild(msg);
      msg.scrollIntoView({ behavior:"smooth", block:"end" });
    }

    /* Report card */
    function renderReportCard(data) {
      const rl = data.report_links || (data.latest && data.latest.report_links);
      const linkOk = isRunScopedReportLink(rl);
      const summary = asObj(data.summary || (data.latest && data.latest.summary));

      /* P0.7: dedup by job_id or report html_url to avoid rendering same report twice */
      const cardJobId = data.job_id || (data.latest && data.latest.job_id) || summary.run_id || "";
      if (cardJobId && window.finSightJobs[cardJobId] && window.finSightJobs[cardJobId].rendered) return;
      if (linkOk && rl.html_web_url && document.querySelector('.r-card[data-report-url="' + esc(rl.html_web_url) + '"]')) return;
      if (cardJobId && window.finSightJobs[cardJobId]) window.finSightJobs[cardJobId].rendered = true;

      const coverage = summary.data_quality_score || {};
      const reviewHints = asList(summary.review_hints || []);
      const gateObj = asObj(data.delivery_gate || (data.latest && data.latest.delivery_gate));
      const isFailedGate = false;
      const isDegraded = summary.degraded || isFailedGate;

      const coverageLevel = v => v >= 0.8 ? "高" : v >= 0.5 ? "中" : "低";
      const coverageClass = v => v >= 0.8 ? "high" : v >= 0.5 ? "medium" : "low";
      const citeScore = coverage.citation_completeness ?? coverage.completeness ?? null;

      const title = summary.report_title || summary.title || data.answer || "财务研究报告";
      const genTime = summary.generated_at || summary.generation_time || new Date().toLocaleString();

      let html = `<div class="r-card" data-job-id="${esc(cardJobId)}"${linkOk && rl.html_web_url ? ' data-report-url="' + esc(rl.html_web_url) + '"' : ''}><h3>${esc(title)}</h3><div class="time">${esc(genTime)}</div>`;
      html += `<div class="badges">`;
      if (coverage.data_coverage != null) html += `<span class="badge ${coverageClass(coverage.data_coverage)}">数据覆盖：${coverageLevel(coverage.data_coverage)}</span>`;
      if (citeScore != null) html += `<span class="badge ${coverageClass(citeScore)}">引用完整性：${coverageLevel(citeScore)}</span>`;
      html += `</div>`;
      if (reviewHints.length) {
        html += `<div class="info-row">需复核项：${reviewHints.map(h => `<span>${esc(h)}</span>`).join("、")}</div>`;
      }
      if (isFailedGate) {
        const issues = topIssues(data).slice(0, 4);
        if (issues.length) html += `<div class="info-row">质量诊断：${issues.map(i => `<span>${esc(issueText(i))}</span>`).join("、")}</div>`;

      } else if (isDegraded) {
        html += `<div class="hint">报告已生成，但部分结论建议人工复核。</div>`;
      }
      if (rl && linkOk) {
        html += `<div class="actions">`;
        html += `<a href="${esc(rl.html_web_url)}" target="_blank" class="btn btn-primary">打开 HTML 研报</a>`;
        if (rl.html_file_url) html += `<a href="${esc(rl.html_web_url)}" download class="btn">下载 HTML</a>`;
        /* Developer-only: copy file:// path */
        if (UI_MODE === "developer" && rl.html_file_url) {
          html += `<button class="btn" onclick="navigator.clipboard.writeText('${esc(rl.html_file_url)}')">复制 file:// 路径</button>`;
        }
        html += `</div>`;
      }
      html += `</div>`;

      /* Remove progress card, add report card */
      const progressEl = $("progressCard");
      if (progressEl) {
        const parent = progressEl.closest(".msg");
        if (parent) parent.remove();
      }
      appendBubbleHtml("assistant", html);

      /* Populate tab panels */
      populateTabs(data);
      $("reportArea").classList.add("visible");
      initTabs();
    }

    /* Confirmation card (user mode only) */
    function renderConfirmCard(data) {
      const confirm = asObj(data.confirm_data);
      const cd = confirm.company_name ? confirm : asObj(data.parsed_task);
      const symbol = confirm.symbol || cd.symbol || "";
      const company = confirm.company_name || symbol;
      const market = confirm.market || "";
      const period = confirm.period || cd.period || "";
      const scope = asList(confirm.analysis_scope || ["三表摘要", "财务分析", "估值观察", "风险提示", "投资结论"]);
      const ds = confirm.data_sources_hint || "公司公开披露、SEC 文件、行情数据和公开资料";
      const reqId = data.request_id || "";

      let html = `<div class="r-card confirm-card" data-request-id="${esc(reqId)}">`;
      html += `<h3 style="margin-bottom:12px">请确认报告设置</h3>`;
      html += `<div class="info-row" style="display:grid;gap:8px;font-size:14px">`;
      html += `<div><span style="color:var(--muted)">公司：</span><span>${esc(company)}${symbol ? "（" + esc(symbol) + "）" : ""}</span></div>`;
      if (market) html += `<div><span style="color:var(--muted)">市场：</span><span>${esc(market)}</span></div>`;
      if (period) html += `<div><span style="color:var(--muted)">报告期：</span><span>${esc(period)}</span></div>`;
      html += `<div><span style="color:var(--muted)">分析范围：</span><span>${scope.map(s => esc(s)).join("、")}</span></div>`;
      html += `<div><span style="color:var(--muted)">数据来源：</span><span>${esc(ds)}</span></div>`;
      html += `</div>`;
      html += `<div class="actions" style="margin-top:16px">`;
      html += `<button class="btn btn-primary" onclick="confirmAndRun(this)" style="padding:8px 20px">开始生成报告</button>`;
      html += `<button class="btn" onclick="modifyRequest()" style="padding:8px 20px">修改报告期</button>`;
      html += `</div></div>`;

      /* Remove progress card */
      const progressEl = $("progressCard");
      if (progressEl) { const parent = progressEl.closest(".msg"); if (parent) parent.remove(); }
      appendBubbleHtml("assistant", html);
    }

    function confirmAndRun(button) {
      if (requestInFlight) return;
      /* Disable confirmation buttons immediately to prevent duplicate jobs */
      const card = button ? button.closest(".confirm-card") : null;
      if (card) {
        if (card.dataset.submitted === "true") return; /* already submitted */
        card.dataset.submitted = "true";
        const btns = card.querySelectorAll("button");
        btns.forEach(b => { b.disabled = true; });
        const primaryBtn = card.querySelector(".btn-primary");
        if (primaryBtn) primaryBtn.textContent = "正在提交...";
        setConfirmCardStatus(card, "submitting", "正在提交...");
        pendingConfirmCard = card;
      }
      if (chatInput) { chatInput.value = "是"; sendChat(); }
    }

    function modifyRequest() {
      /* Let user re-specify the request */
      if (chatInput) {
        chatInput.placeholder = "请输入更具体的研报要求，例如：生成 TSLA 2026Q1 财报";
        chatInput.focus();
      }
      /* Remove the last assistant message (confirmation card) */
      const log = $("chatLog");
      if (log) {
        const last = log.lastElementChild;
        if (last && last.classList.contains("assistant")) last.remove();
      }
    }

    /* Artifact card — show existing report links */
    function renderArtifactCard(data) {
      const rl = asObj(data.report_links);
      const symbol = data.symbol || "";
      const period = data.period || "";
      const isHist = data.is_historical !== false;
      const title = isHist ? "历史报告" : "已有报告";
      let html = `<div class="r-card"><h3>${title}</h3>`;
      if (symbol) html += `<div class="info-row" style="margin-bottom:8px"><span>${esc(symbol)}${period ? " · " + esc(period) : ""}</span></div>`;
      if (isHist) {
        html += `<div style="font-size:11px;color:#888;margin-bottom:8px">此报告来自之前的生成，与当前请求无关。</div>`;
      }
      if (isRunScopedReportLink(rl)) {
        html += `<div class="actions">`;
        html += `<a href="${esc(rl.html_web_url)}" target="_blank" class="btn btn-primary">打开 HTML 研报</a>`;
        html += `<a href="${esc(rl.html_web_url)}" download class="btn">下载 HTML</a>`;
        /* Developer-only: copy file:// path */
        if (UI_MODE === "developer" && rl.html_file_url) {
          html += `<button class="btn" onclick="navigator.clipboard.writeText('${esc(rl.html_file_url)}')">复制 file:// 路径</button>`;
        }
        if (UI_MODE === "developer" && rl.markdown_web_url) html += `<a href="${esc(rl.markdown_web_url)}" target="_blank" class="btn">下载 Markdown</a>`;
        html += `</div>`;
      } else {
        html += `<p style="margin:8px 0">${esc(data.answer || "未找到报告文件。")}</p>`;
      }
      html += `</div>`;
      appendBubbleHtml("assistant", html);
    }

    /* Tabs */
    function initTabs() {
      const tabs = ["概览", "报告", "引用"];
      const container = $("mainTabs");
      if (!container) return;
      container.innerHTML = tabs.map(t => `<button class="user-tab${t===activeTab?" active":""}" data-tab="${t}">${t}</button>`).join("");
      container.querySelectorAll(".user-tab").forEach(btn => btn.addEventListener("click", () => { activeTab = btn.dataset.tab; initTabs(); }));
      ["overviewPanel","reportPanel","citationsPanel"].forEach(id => { const el = $(id); if (el) el.classList.toggle("active", id === activeTabToPanelId(activeTab)); });
    }

    function activeTabToPanelId(tab) {
      const map = {"概览":"overviewPanel","报告":"reportPanel","引用":"citationsPanel"};
      return map[tab] || "overviewPanel";
    }

    function populateTabs(data) {
      const summary = asObj(data.summary || (data.latest && data.latest.summary));
      const rl = data.report_links || (data.latest && data.latest.report_links);
      const citations = asList(data.citations || (data.latest && data.latest.citations));
      const charts = asList(data.charts || (data.latest && data.latest.charts));
      const coverage = summary.data_quality_score || {};
      const reviewHints = asList(summary.review_hints || []);

      /* Overview */
      const coverageLevel = v => v >= 0.8 ? "高" : v >= 0.5 ? "中" : "低";
      const coverageClass = v => v >= 0.8 ? "high" : v >= 0.5 ? "medium" : "low";
      const citeScore = coverage.citation_completeness ?? coverage.completeness ?? null;
      let ov = `<div class="metric-grid">`;
      if (summary.symbol) ov += `<div class="metric-card"><div class="label">标的</div><div class="value">${esc(summary.symbol)}</div></div>`;
      if (summary.period) ov += `<div class="metric-card"><div class="label">报告期</div><div class="value">${esc(summary.period)}</div></div>`;
      if (summary.execution_mode) ov += `<div class="metric-card"><div class="label">执行模式</div><div class="value">${esc(summary.execution_mode)}</div></div>`;
      ov += `<div class="metric-card"><div class="label">图表</div><div class="value">${charts.length}</div></div>`;
      ov += `<div class="metric-card"><div class="label">引用</div><div class="value">${citations.length}</div></div>`;
      if (coverage.data_coverage != null) ov += `<div class="metric-card"><div class="label">数据覆盖</div><div class="value" style="color:var(--${coverageClass(coverage.data_coverage)==="high"?"ok":coverageClass(coverage.data_coverage)==="medium"?"warn":"bad"})">${coverageLevel(coverage.data_coverage)}</div></div>`;
      if (citeScore != null) ov += `<div class="metric-card"><div class="label">引用完整性</div><div class="value" style="color:var(--${coverageClass(citeScore)==="high"?"ok":coverageClass(citeScore)==="medium"?"warn":"bad"})">${coverageLevel(citeScore)}</div></div>`;
      ov += `</div>`;
      if (reviewHints.length) {
        ov += `<div style="margin-top:8px;font-size:13px;color:var(--warn)">需复核项：</div><ul>${reviewHints.map(h => `<li>${esc(h)}</li>`).join("")}</ul>`;
      }
      if (!summary.symbol && !citations.length) ov = `<div class="empty-panel">暂无数据。</div>`;
      $("overviewPanel").innerHTML = ov;

      /* Report */
      let rp = "";
      if (isRunScopedReportLink(rl)) {
        rp = `<div style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap">`;
        rp += `<a href="${esc(rl.html_web_url)}" target="_blank" class="btn btn-primary" style="border-radius:8px;padding:8px 16px;border:1px solid var(--accent);background:var(--accent);color:#111;text-decoration:none;font-size:13px;font-family:inherit;cursor:pointer;display:inline-flex;align-items:center;gap:5px">打开完整研报</a>`;
        if (rl.html_file_url) rp += `<button class="btn" onclick="navigator.clipboard.writeText('${esc(rl.html_file_url)}')" style="border-radius:8px;padding:8px 16px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-size:13px;font-family:inherit;cursor:pointer">复制文件路径</button>`;
        rp += `</div>`;
        rp += `<iframe src="${esc(rl.html_web_url)}" class="report-frame" title="report"></iframe>`;
      } else if (summary.report_markdown) {
        rp = `<pre style="white-space:pre-wrap;word-break:break-word">${esc(summary.report_markdown)}</pre>`;
      } else {
        rp = `<div class="empty-panel">报告生成后会显示在这里。</div>`;
      }
      $("reportPanel").innerHTML = rp;

      /* Citations */
      let cp = "";
      if (citations.length) {
        cp = citations.map(c => {
          const cid = esc(c.evidence_id || c.id || "");
          const title = esc(c.title || "");
          const url = c.source_url ? `<a href="${esc(c.source_url)}" target="_blank">${esc(c.source_url)}</a>` : "";
          return `<div class="citem"><div class="cid">${cid}</div><div>${title}</div>${url ? `<div>${url}</div>` : ""}</div>`;
        }).join("");
      } else {
        cp = `<div class="empty-panel">暂无引用。</div>`;
      }
      $("citationsPanel").innerHTML = cp;
    }

    /* Wire send button */
    $("chatBtn").addEventListener("click", sendChat);
  </script>
</body>
</html>"""
    return (
        template.replace("__DEFAULT_TOPIC__", escape(default_topic))
        .replace("__DEFAULT_ENGINES__", escape(DEFAULT_ENGINES))
        .replace("__A_SHARE_ENGINES__", escape(A_SHARE_ENGINES))
        .replace("__US_ENGINES__", escape(US_ENGINES))
        .replace("__HK_ENGINES__", escape(HK_ENGINES))
        .replace("__UI_MODE__", "user")
        .replace("__BACKEND_PORT__", str(frontend_port or ""))
    )


def _render_dev_html(frontend_port: int | None = None) -> str:
    """Developer mode: full UI with diagnostic panel."""
    is_dev = True

    default_topic = "生成 AAPL 最新公司财报研报"
    default_period = latest_completed_period()
    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FinSight</title>
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
    .has-banner { padding-top: 36px; }
    .mode-banner {
      position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
      display: flex; align-items: center; gap: 12px;
      padding: 4px 14px; font-size: 11px; font-family: monospace;
      background: rgba(16,16,16,0.92); backdrop-filter: blur(6px);
      color: #ccc; border-bottom: 1px solid #333; height: 28px;
    }
    .mode-banner .badge {
      padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 10px;
    }
    .mode-banner .badge.user { background: #2d7d46; color: #fff; }
    .mode-banner .badge.dev { background: #b45309; color: #fff; }
    .mode-banner .info { color: #888; }
    .mode-banner .info strong { color: #ddd; }
    .mode-banner .dev-extra { color: #666; margin-left: auto; font-size: 10px; }
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
      transition: border-color 0.15s, background 0.15s;
    }
    .chip:hover, .tab:hover, .secondary:hover { border-color: #888; background: #1a1a1a; }
    .chip:active, .tab:active { background: #252525; }
    .tabs { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
    .tab.active { background: var(--text); color: #111111; border-color: var(--text); }
    .report-area { display: none; }
    .report-area.visible { display: block; }
    .panel { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 16px; }
    .empty-state { text-align: center; padding: 40px 20px; color: var(--muted); line-height: 1.8; font-size: 15px; }
    .empty-state .icon { font-size: 40px; margin-bottom: 12px; opacity: 0.5; }
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
    /* Report link card in chat */
    .report-link-card {
      margin-top: 10px; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px;
      background: #1a1a1a; display: inline-block; min-width: 280px;
    }
    .report-link-card .title { font-weight: 600; font-size: 15px; margin-bottom: 10px; }
    .report-link-card .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .report-link-card .btn {
      border: 1px solid #555; border-radius: 8px; padding: 8px 14px; cursor: pointer;
      font-size: 13px; background: #252525; color: #eee; text-decoration: none; display: inline-flex; align-items: center; gap: 5px;
    }
    .report-link-card .btn:hover { background: #333; border-color: #777; }
    .report-link-card .btn-primary { background: #f7f7f7; color: #111; border-color: #f7f7f7; }
    .report-link-card .btn-primary:hover { background: #fff; }
    .report-link-card .path-hint { font-size: 12px; color: var(--muted); margin-top: 8px; word-break: break-all; }
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
<body class="has-banner">
  <div class="mode-banner" id="modeBanner">
    <span class="badge dev">DEVELOPER</span>
    <span class="info">Port: <strong id="bannerPort">__BACKEND_PORT__</strong></span>
    <span class="info" id="bannerJobId" style="display:none">Job: <strong></strong></span>
    <span class="info">Session: <strong id="bannerSession">local</strong></span>
    <span class="dev-extra" id="bannerQueue"></span>
  </div>
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
    <div class="report-area" id="reportArea">
      <div class="tabs" id="mainTabs"></div>
      <section id="content" class="panel"></section>
    </div>
    __DEV_PANEL_HTML__
  </main>
  <script>
    const UI_MODE = "__UI_MODE__";
    const DEFAULT_ENGINES = "__DEFAULT_ENGINES__";
    const A_SHARE_ENGINES = "__A_SHARE_ENGINES__";
    const US_ENGINES = "__US_ENGINES__";
    const HK_ENGINES = "__HK_ENGINES__";
    const mainTabs = UI_MODE === "developer" ? ["概览", "报告", "引用", "质量"] : ["概览", "报告", "引用"];
    const devTabs = ["数据源健康", "协作黑板", "多智能体协作", "工具调用", "图表", "表格", "PDF章节", "公司画像", "Claims", "轨迹", "时间线", "原始数据"];
    let latest = {};
    let requestInFlight = false;
    let busyPollTimer = null;
    let backgroundRunPending = false;
    let activeMainTab = "概览";
    let activeDevTab = "多智能体协作";
    const $ = (id) => document.getElementById(id);
    const $val = (id, fallback = "") => { const el = $(id); return el ? el.value : fallback; };
    const $checked = (id, fallback = true) => { const el = $(id); return el ? el.checked : fallback; };
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m]));
    const asList = (value) => Array.isArray(value) ? value : [];
    const asObj = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
    function isRunScopedReportLink(rl) {
      rl = asObj(rl);
      const url = String(rl.html_web_url || "");
      return !!url && rl.is_run_scoped !== false && !/^\/artifacts\/report\.html(?:\?|$)/.test(url);
    }
    function setStatus(text, isError = false) { $("statusText").textContent = text; $("statusText").className = isError ? "bad" : ""; }
    function activeRuns(data) { return asList(asObj(data).active_runs); }
    function currentActiveRun(data) { return activeRuns(data)[0] || null; }
    function updateBanner(data) {
      const jobIdEl = document.getElementById('bannerJobId');
      if (data && data.active_job_id) {
        jobIdEl.style.display = 'inline';
        jobIdEl.querySelector('strong').textContent = data.active_job_id;
      } else {
        jobIdEl.style.display = 'none';
      }
      const queueEl = document.getElementById('bannerQueue');
      if (queueEl && data) {
        const qlen = data.queue_length || 0;
        const aruns = activeRuns(data).length;
        queueEl.textContent = qlen ? `Queue: ${qlen} | Active: ${aruns}` : '';
      }
    }
    function setControlsBusy(isBusy) {
      requestInFlight = isBusy;
      $("chatBtn").disabled = isBusy;
      if ($("runBtn")) $("runBtn").disabled = isBusy;
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
        session_id: $val("sessionId", "local"),
        symbol: $val("symbol", "AAPL"),
        period: $val("period", "__DEFAULT_PERIOD__"),
        topic: $val("topic", ""),
        engines: $val("engines", DEFAULT_ENGINES),
        execution_mode: $val("executionMode", "collaborative"),
        fast: $checked("fastMode", true),
        memory_enabled: $checked("memoryEnabled", true),
        allow_report_run: $checked("allowReportRun", true),
        enable_remote_data: $checked("realtimeData", true),
        data_source_config_path: $val("dataSourceConfig", "configs/data_sources.yaml")
      };
    }
    function syncEnginesFromSwitch() {
      const symbol = $val("symbol", "AAPL").toUpperCase();
      const enginesEl = $("engines");
      const realtimeEl = $("realtimeData");
      if (!enginesEl) return;
      if (!realtimeEl || !realtimeEl.checked) enginesEl.value = DEFAULT_ENGINES;
      else if (symbol.endsWith(".SS") || symbol.endsWith(".SZ") || /^[0-9]{6}$/.test(symbol)) enginesEl.value = A_SHARE_ENGINES;
      else if (symbol.endsWith(".HK")) enginesEl.value = HK_ENGINES;
      else enginesEl.value = US_ENGINES;
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
      const resp = await fetch("/api/latest?mode=" + UI_MODE);
      latest = await resp.json();
      updateBanner(latest);
      syncFormFromLatest(latest);
      render();
      const active = currentActiveRun(latest);
      if (active) {
        setStatus(`后台生成中：${active.symbol || "-"} ${active.period || ""}`);
        return;
      }
      if (backgroundRunPending) {
        backgroundRunPending = false;
        stopBusyPolling();
        setControlsBusy(false);
        // delivery_gate may be filtered out in user mode — safe access
        const gate = asObj(latest.delivery_gate || {});
        setStatus("完成", false);
        return;
      }
      if (!silent && !requestInFlight) setStatus("就绪");
    }
    function syncFormFromLatest(data) {
      const active = currentActiveRun(data);
      const summary = asObj(data.summary);
      const display = active || summary;
      const safeSet = (id, value) => { const el = $(id); if (el) el.value = value; };
      if (display.symbol) safeSet("symbol", display.symbol);
      if (display.period) safeSet("period", display.period);
      if (display.research_topic) safeSet("topic", display.research_topic);
      if (Array.isArray(summary.search_engines) && summary.search_engines.length) safeSet("engines", summary.search_engines.join(","));
      const runMeta = $("runMeta");
      if (!runMeta) return;
      if (active) runMeta.innerHTML = `<strong>正在生成</strong> ${esc(`${active.symbol || ""} ${active.period || ""}`.trim())} · ${esc(active.execution_mode || "")}`;
      else if (summary.symbol || summary.period) runMeta.innerHTML = `<strong>最近报告</strong> ${esc(`${summary.symbol || ""} ${summary.period || ""}`.trim())} · ${esc(summary.execution_mode || "")}`;
      else runMeta.textContent = "还没有生成报告";
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
        setStatus("完成", false);
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
      const chatInput = $("chatInput");
      if (!chatInput) return;
      const message = chatInput.value.trim();
      if (!message) return;
      let keepPolling = false;
      appendBubble("user", message);
      chatInput.value = "";
      const payload = { ...payloadBase(), message, async_report_run: true };
      showPendingRun(payload, message);
      setControlsBusy(true);
      setStatus("已提交，正在解析/生成；报告生成可能需要数分钟");
      startBusyPolling();
      try {
        const data = await postJson("/api/chat", payload);
        const parsed = asObj(data.parsed_task);
        if (parsed.symbol) {
          // Safe element access — these may not exist in user mode
          const safeSet = (id, value) => { const el = $(id); if (el) el.value = value; };
          safeSet("symbol", parsed.symbol);
          if (parsed.period) safeSet("period", parsed.period);
          if (parsed.research_topic) safeSet("topic", parsed.research_topic);
          syncEnginesFromSwitch();
        }
        if (data.latest && !data._no_latest_until_complete) { latest = data.latest; syncFormFromLatest(latest); }
        const answer = renderChatAnswer(data);
        (data.report_links || (data.latest && data.latest.report_links) ? appendBubbleHtml : appendBubble)("assistant", answer);
        render();
        const result = asObj(data.result);
        if (data.mode === "report_run" && (result.status === "running" || data._no_latest_until_complete)) {
          backgroundRunPending = true;
          keepPolling = true;
          startBusyPolling();
          setControlsBusy(false);
          setStatus(`后台生成中：${result.symbol || parsed.symbol || "-"} ${result.period || parsed.period || ""}`);
        } else {
          // delivery_gate may be filtered out in user mode
          const gate = asObj((data.latest || {}).delivery_gate || {});
          setStatus("就绪", false);
        }
      } catch (err) {
        appendBubble("assistant", `对话失败：${err.message}`);
        setStatus("失败", true);
      } finally {
        if (!keepPolling) stopBusyPolling();
        setControlsBusy(false);
        loadLatest({ silent: true });
      }
    }
    function renderChatAnswer(data) {
      if (data.mode === "period_guard") return data.answer || "这个报告期尚未结束，不能生成正式财报研报。";
      const lines = [data.answer || "已完成。"];
      const parsed = asObj(data.parsed_task);
      if ((parsed.should_run || parsed.needs_confirmation) && parsed.symbol && parsed.period && data.mode !== "report_run") lines.push(`我理解为：${parsed.symbol} ${parsed.period}。`);
      // If report_links exist, return HTML card
      const rl = data.report_links || (data.latest && data.latest.report_links);
      if (isRunScopedReportLink(rl)) {
        const linkButtons = [`<a href="${esc(rl.html_web_url)}" target="_blank" class="btn btn-primary" style="text-decoration:none">📄 打开 HTML 研报</a>`];
        linkButtons.push(`<a href="${esc(rl.html_web_url)}" download class="btn">下载 HTML</a>`);
        if (UI_MODE === "developer" && rl.html_file_url) linkButtons.push(`<button class="btn" onclick="navigator.clipboard.writeText('${esc(rl.html_file_url)}')">📁 复制 file:// 路径</button>`);
        if (UI_MODE === "developer" && rl.local_report_dir) linkButtons.push(`<span class="path-hint">📂 ${esc(rl.local_report_dir)}</span>`);
        lines.push(`<div class="report-link-card"><div class="title">研报已生成</div><div class="actions">${linkButtons.join("")}</div></div>`);
      }
      if (data.latest && UI_MODE === "developer") {
        lines.push(buildResultText(data.result || {}, data.latest));
      }
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
      if (data.report_html_url) lines.push("报告已在下方「报告」页签中更新。");
      return lines.join("\n");
    }
    function appendBubble(role, text) {
      const node = document.createElement("div");
      node.className = `bubble ${role}`;
      node.textContent = text;
      $("chatLog").appendChild(node);
      node.scrollIntoView({ behavior: "smooth", block: "end" });
    }
    function appendBubbleHtml(role, html) {
      const node = document.createElement("div");
      node.className = `bubble ${role}`;
      node.innerHTML = html;
      $("chatLog").appendChild(node);
      node.scrollIntoView({ behavior: "smooth", block: "end" });
    }
    function renderTabButtons(containerId, tabs, active, onClick) {
      $(containerId).innerHTML = tabs.map((tab) => `<button class="tab ${tab === active ? "active" : ""}" data-tab="${esc(tab)}">${esc(tab)}</button>`).join("");
      document.querySelectorAll(`#${containerId} .tab`).forEach((btn) => btn.addEventListener("click", () => onClick(btn.dataset.tab)));
    }
    function render() {
      renderTabButtons("mainTabs", mainTabs, activeMainTab, (tab) => { activeMainTab = tab; render(); });
      if ($("devTabs")) { renderTabButtons("devTabs", devTabs, activeDevTab, (tab) => { activeDevTab = tab; render(); }); }
      const mainMap = {"概览": renderOverview, "报告": renderReport, "引用": renderCitations, "质量": renderQuality};
      const devMap = {"数据源健康": renderSourceHealth, "协作黑板": renderBlackboard, "多智能体协作": renderCollaboration, "工具调用": renderToolTrace, "图表": renderCharts, "表格": renderTables, "PDF章节": renderPdf, "公司画像": renderProfile, "Claims": renderClaims, "轨迹": renderTrace, "时间线": renderTimeline, "原始数据": renderRaw};
      const content = $("content");
      if (content) content.innerHTML = (mainMap[activeMainTab] || renderOverview)(latest);
      const devContent = $("devContent");
      if (devContent) devContent.innerHTML = (devMap[activeDevTab] || renderCollaboration)(latest);
      // Toggle report area visibility — only show when there's data
      const reportArea = $("reportArea");
      if (reportArea) {
        const summary = asObj(latest.summary);
        const hasData = !!summary.symbol || asList(latest.citations).length > 0 || !!latest.report_html_url || !!latest.report_links || !!currentActiveRun(latest);
        reportArea.classList.toggle("visible", hasData);
      }
    }
    function renderOverview(data) {
      const active = currentActiveRun(data);
      const summary = asObj(data.summary);
      if (active) {
        return `<div class="grid">${metric("当前任务", `${active.symbol || "-"} ${active.period || ""}`)}${metric("状态", "正在生成")}${metric("执行模式", active.execution_mode || "-")}${metric("开始时间", active.started_at || "-")}</div><p class="muted">下方最近报告仍可能是上一轮产物；当前任务完成后会自动刷新。</p>`;
      }
      if (!summary.symbol && !asList(data.citations).length && !data.report_html_url && !data.report_links) return `<div class="empty-state">可以直接输入「生成某公司最新财报研报」。我会先检查报告期是否有效，再启动多智能体生成。</div>`;
      if (UI_MODE === "developer") {
        const verification = asObj(data.verification_report || {});
        const gate = asObj(data.delivery_gate || {});
        return `<div class="grid">${metric("标的", summary.symbol || "-")}${metric("报告期", summary.period || "-")}${metric("执行模式", summary.execution_mode || "-")}${metric("事实校验", summary.verification_passed ?? verification.passed ?? "未运行")}${metric("交付状态", gate.delivery_pass === true ? "已通过" : gate.delivery_pass === false ? "未通过" : "未运行")}${metric("论点", asList(data.claims || []).length)}${metric("证据", asList(data.evidence || []).length)}${metric("图表", asList(data.charts || []).length)}${metric("引用", asList(data.citations || []).length)}</div>`;
      }
      return `<div class="grid">${metric("标的", summary.symbol || "-")}${metric("报告期", summary.period || "-")}${metric("执行模式", summary.execution_mode || "-")}${metric("图表", asList(data.charts || []).length)}${metric("引用", asList(data.citations || []).length)}</div>`;
    }
    function metric(name, value) { return `<div class="item"><h3>${esc(name)}</h3><div>${esc(value)}</div></div>`; }
    function renderReport(data) {
      const active = currentActiveRun(data);
      if (active) {
        return `<div class="empty-state">正在生成 ${esc(`${active.symbol || "-"} ${active.period || ""}`.trim())} · ${esc(active.execution_mode || "")}。当前任务完成后会自动加载新报告，不再显示上一轮报告。</div>`;
      }
      if (data.report_links && isRunScopedReportLink(data.report_links)) {
        const rl = data.report_links;
        const filePath = UI_MODE === "developer" && rl.html_file_url ? `<p style="margin:10px 0;font-size:13px;color:var(--muted);overflow-wrap:break-word">📁 ${esc(rl.html_file_url)}</p>` : "";
        const copyBtn = UI_MODE === "developer" && rl.html_file_url ? `<button class="tab" onclick="navigator.clipboard.writeText('${esc(rl.html_file_url)}')">复制 file:// 路径</button>` : "";
        return `<div style="margin-bottom:10px;display:flex;gap:8px;flex-wrap:wrap"><a href="${esc(rl.html_web_url)}" target="_blank" class="tab" style="background:var(--text);color:#111;border-color:var(--text);text-decoration:none">📄 在浏览器中打开研报</a><a href="${esc(rl.html_web_url)}" download class="tab">下载 HTML</a>${copyBtn}</div>${filePath}<iframe src="${esc(rl.html_web_url)}" title="report"></iframe>`;
      }
      if (data.report_html_url) return `<iframe src="${esc(data.report_html_url)}" title="report"></iframe>`;
      if (data.report_markdown) return `<pre>${esc(data.report_markdown)}</pre>`;
      return `<div class="empty-state">报告生成后会显示在这里。</div>`;
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
      if (!Object.keys(quality).length && !Object.keys(llm).length && !Object.keys(gate).length) return `<div class="empty-state">还没有质量评测结果。</div>`;
      const issues = topIssues(data);
      return `<div class="grid">${metric("客观评分", quality.total_score ?? quality.score ?? "未运行")}${metric("客观门禁", quality.objective_pass ?? "未运行")}${metric("LLM 复核", llm.llm_review_pass ?? llm.passed ?? "未运行")}${metric("质量诊断", gate.delivery_pass ?? "未运行")}</div><h3>主要问题</h3>${issues.length ? `<ul>${issues.slice(0, 8).map((item) => `<li>${esc(issueText(item))}</li>`).join("")}</ul>` : `<p class="ok">暂无问题。</p>`}`;
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
    if ($("runBtn")) $("runBtn").addEventListener("click", runReport);
    if ($("refreshBtn")) $("refreshBtn").addEventListener("click", loadLatest);
    if ($("symbol")) $("symbol").addEventListener("change", syncEnginesFromSwitch);
    if ($("realtimeData")) $("realtimeData").addEventListener("change", syncEnginesFromSwitch);
    document.querySelectorAll(".chip").forEach((btn) => btn.addEventListener("click", () => { const inp = $("chatInput"); if (inp) { inp.value = btn.dataset.prompt || ""; inp.focus(); } }));
    const chatInput = $("chatInput");
    if (chatInput) chatInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChat(); } });
    syncEnginesFromSwitch();
    render();
    loadLatest();
  </script>
</body>
</html>"""

    dev_panel = r"""<details class="developer" id="developerPanel">
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
    </details>"""  # always shown in dev

    return (
        template.replace("__DEFAULT_TOPIC__", escape(default_topic))
        .replace("__DEFAULT_PERIOD__", escape(default_period))
        .replace("__DEFAULT_ENGINES__", escape(DEFAULT_ENGINES))
        .replace("__A_SHARE_ENGINES__", escape(A_SHARE_ENGINES))
        .replace("__US_ENGINES__", escape(US_ENGINES))
        .replace("__HK_ENGINES__", escape(HK_ENGINES))
        .replace("__UI_MODE__", "developer")
        .replace("__BACKEND_PORT__", str(frontend_port or ""))
        .replace("__DEV_PANEL_HTML__", dev_panel)
    )



def default_engines_for_symbol(symbol: str, realtime: bool = False) -> str:
    """根据股票代码返回该市场默认的搜索引擎列表。

    优先使用 identity.data_source_plan（公司级配置），
    其次根据市场选择 web_ui.py 中定义的 market-specific 引擎列表，
    最后回退到 DEFAULT_ENGINES。
    """
    # 按市场选择
    upper = symbol.upper().strip() if symbol else ""
    if upper.endswith(".SS") or upper.endswith(".SZ"):
        market_engines = A_SHARE_ENGINES
    elif upper.endswith(".HK"):
        market_engines = HK_ENGINES
    else:
        market_engines = US_ENGINES

    # 公司级配置优先，但不能吞掉市场默认新增的关键引擎（如 sina_finance）。
    if realtime:
        identity = resolve_company_identity(symbol, default=symbol)
        engines = [str(item) for item in identity.data_source_plan.get("engines") or [] if str(item)]
        if engines:
            for engine in _parse_engines(market_engines):
                if engine not in engines:
                    engines.append(engine)
            return ",".join(engines)

    return market_engines


def _should_reset_engines_for_parsed_task(
    has_parsed_task: bool,
    raw_engines: Any,
    *,
    symbol: str = "",
    realtime: bool = False,
) -> bool:
    if not has_parsed_task:
        return False
    raw_text = str(raw_engines or "")
    if raw_text in {DEFAULT_ENGINES, A_SHARE_ENGINES, US_ENGINES, HK_ENGINES}:
        return True
    if not realtime:
        return False
    raw_set = set(_parse_engines(raw_engines))
    if not raw_set:
        return True
    identity = resolve_company_identity(symbol, default=symbol)
    primary_sources = set(str(item) for item in identity.data_source_plan.get("primary_sources", []) if str(item))
    return bool(primary_sources and raw_set.isdisjoint(primary_sources))


def validate_period_for_report(raw_period: str, today: date | None = None) -> Dict[str, Any]:
    raw = str(raw_period or "").strip().upper()
    today = today or date.today()
    fy_match = re.fullmatch(r"FY(20\d{2})", raw)
    if fy_match:
        year = int(fy_match.group(1))
        if year < today.year:
            return {"ok": True, "message": "", "suggested_periods": []}
        suggested = [f"{today.year - 1}Q4", f"FY{today.year - 1}"]
        return {
            "ok": False,
            "message": (
                f"{raw} 尚未结束，不能生成正式财报口径研报。"
                f"可改为最近已结束报告期 {suggested[0]}，或使用完整财年 {suggested[1]}。"
            ),
            "suggested_periods": suggested,
        }
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


def _looks_like_quality_review_request(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        term in lowered
        for term in [
            "检查最近报告",
            "复盘最近报告",
            "质量问题",
            "引用是否完整",
            "quality review",
            "quality gate",
            "delivery gate",
            "verification report",
            "citation gap",
        ]
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


def _confirmation_prompt(symbol: str, period: str, engines: List[str], mode: str = "user") -> str:
    identity = resolve_company_identity(symbol or "", default=symbol or "")
    period_upper = str(period or "").strip().upper()
    if period_upper.startswith("FY"):
        period_kind = "fiscal_year"
    elif re.match(r"^20\d{2}Q[1-4]$", period_upper):
        period_kind = "quarter"
    else:
        period_kind = "latest"
    period_label = {
        "fiscal_year": "财年口径",
        "quarter": "季度口径",
        "latest": "最新口径",
    }.get(period_kind, "未确定")
    resolved_symbol = str(identity.canonical_symbol or symbol or "")
    company_name = str(identity.company_name or "未确认")

    if mode == "developer":
        exchange = str(identity.exchange or "未确认")
        return (
            "我识别到你可能想生成公司/个股研报，请先确认参数：\n"
            f"- 公司名称：{company_name}\n"
            f"- ticker：{resolved_symbol}\n"
            f"- 交易所：{exchange}\n"
            f"- 报告期：{period_upper}\n"
            f"- 期间口径：{period_label}\n"
            f"- 数据源：{', '.join(engines)}\n"
            "请回复确认，或回复\"是\"，我会启动报告生成。"
        )

    # User mode: human-readable only
    return (
        "请确认报告设置：\n"
        f"公司：{company_name}（{resolved_symbol}）\n"
        f"市场：{_market_label(resolved_symbol)}\n"
        f"报告期：{period_upper}（{period_label}）\n"
        "分析范围：三表摘要、财务分析、估值观察、风险提示、投资结论\n"
        "数据来源：公司公开披露、SEC 文件、行情数据和公开资料"
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
        "official_evidence_manifest.json",
        "evidence_coverage.json",
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
    print(f"FinSight web UI: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
