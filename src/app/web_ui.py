"""Local Chat-first web workbench for DeepReport++."""

from __future__ import annotations

from datetime import date
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import unquote, urlparse

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.app.agent_chat import AgentChatService
from src.app.chat_task_parser import llm_parse_chat_task
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

    class WebUIHandler(BaseHTTPRequestHandler):
        server_version = "DeepReportWebUI/0.3"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(render_index_html())
                return
            if parsed.path == "/api/latest":
                self._send_json(load_run_payload(output_root, report_root))
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
            symbol = str(payload.get("symbol") or "AAPL").strip().upper()
            period = str(payload.get("period") or "2025Q4").strip().upper()
            guard = validate_period_for_report(period)
            if not guard["ok"]:
                self._send_json({"error": guard["message"], "period_guard": guard}, status=HTTPStatus.BAD_REQUEST)
                return
            topic = str(payload.get("topic") or f"生成 {symbol} {period} 公司财报研报")
            enable_remote_data = bool(payload.get("enable_remote_data", False))
            engines = _parse_engines(payload.get("engines") or default_engines_for_symbol(symbol, enable_remote_data))
            orchestrator = MultiAgentOrchestrator(
                output_dir=str(output_root),
                report_dir=str(report_root),
                config_path=config_path,
                memory_enabled=bool(payload.get("memory_enabled", False)),
                memory_root=str(Path(memory_root) / "durable"),
            )
            result = orchestrator.run(
                research_topic=topic,
                symbol=symbol,
                period=period,
                execution_mode=str(payload.get("execution_mode") or "dynamic"),
                fast=bool(payload.get("fast", True)),
                search_engines=engines,
                enable_remote_data=enable_remote_data,
                data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
            )
            quality_result = run_delivery_quality_pipeline(
                output_root,
                report_root,
                config_path,
                durable_memory_store=getattr(orchestrator, "durable_memory", None),
                memory_enabled=bool(payload.get("memory_enabled", False)),
            )
            latest = load_run_payload(output_root, report_root)
            self._send_json({"result": {**result, **quality_result}, "latest": latest})

        def _handle_chat(self) -> None:
            payload = self._read_json_body()
            message = str(payload.get("message") or "").strip()
            symbol = str(payload.get("symbol") or "AAPL").strip().upper()
            period = str(payload.get("period") or "2025Q4").strip().upper()
            allow_report_run = bool(payload.get("allow_report_run", True))
            enable_remote_data = bool(payload.get("enable_remote_data", True))
            parsed_task = llm_parse_chat_task(message, current_symbol=symbol, current_period=period, config_path=config_path)
            if parsed_task.should_run:
                symbol = parsed_task.symbol
                period = parsed_task.period
                payload["topic"] = parsed_task.research_topic
            raw_engines = payload.get("engines")
            if parsed_task.should_run and str(raw_engines or "") in {DEFAULT_ENGINES, A_SHARE_ENGINES, US_ENGINES}:
                raw_engines = default_engines_for_symbol(symbol, enable_remote_data)
            engines = _parse_engines(raw_engines or default_engines_for_symbol(symbol, enable_remote_data))
            if allow_report_run and _looks_like_report_request(message):
                guard = validate_period_for_report(period)
                if not guard["ok"]:
                    self._send_json({"error": guard["message"], "period_guard": guard}, status=HTTPStatus.BAD_REQUEST)
                    return
                if parsed_task.needs_confirmation:
                    response = chat_service.handle_chat(
                        message=message,
                        session_id=str(payload.get("session_id") or "local"),
                        user_id=str(payload.get("user_id") or "local_user"),
                        symbol=symbol,
                        period=period,
                        memory_enabled=bool(payload.get("memory_enabled", True)),
                        allow_report_run=False,
                        orchestrator=None,
                        engines=engines,
                        fast=bool(payload.get("fast", True)),
                        execution_mode=str(payload.get("execution_mode") or "dynamic"),
                        enable_remote_data=enable_remote_data,
                        data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
                    )
                    response["mode"] = "confirm_report"
                    response["parsed_task"] = parsed_task.to_dict()
                    response["answer"] = (
                        "我识别到你可能想生成研报，但还需要确认参数：\n"
                        f"- 标的：{parsed_task.symbol}\n"
                        f"- 期间：{parsed_task.period}\n"
                        f"- 数据源：{default_engines_for_symbol(parsed_task.symbol, enable_remote_data)}\n"
                        "请回复确认后我再启动多智能体生成。"
                    )
                    self._send_json(response)
                    return
            orchestrator = None
            if allow_report_run:
                orchestrator = MultiAgentOrchestrator(
                    output_dir=str(output_root),
                    report_dir=str(report_root),
                    config_path=config_path,
                    memory_enabled=bool(payload.get("memory_enabled", True)),
                    memory_root=str(Path(memory_root) / "durable"),
                )
            response = chat_service.handle_chat(
                message=message,
                session_id=str(payload.get("session_id") or "local"),
                user_id=str(payload.get("user_id") or "local_user"),
                symbol=symbol,
                period=period,
                memory_enabled=bool(payload.get("memory_enabled", True)),
                allow_report_run=allow_report_run,
                orchestrator=orchestrator,
                engines=engines,
                fast=bool(payload.get("fast", True)),
                execution_mode=str(payload.get("execution_mode") or "dynamic"),
                enable_remote_data=enable_remote_data,
                data_source_config_path=str(payload.get("data_source_config_path") or "configs/data_sources.yaml"),
            )
            if parsed_task.should_run or parsed_task.needs_confirmation:
                response["parsed_task"] = parsed_task.to_dict()
            if response.get("mode") == "report_run":
                quality_result = run_delivery_quality_pipeline(
                    output_root,
                    report_root,
                    config_path,
                    durable_memory_store=getattr(orchestrator, "durable_memory", None),
                    memory_enabled=bool(payload.get("memory_enabled", True)),
                )
                if isinstance(response.get("result"), dict):
                    response["result"].update(quality_result)
                response["latest"] = load_run_payload(output_root, report_root)
            self._send_json(response)

        def _send_artifact(self, relative_name: str) -> None:
            name = unquote(relative_name)
            candidates = {
                "report.html": report_root / "report.html",
                "report.md": report_root / "report.md",
                "report.json": report_root / "report.json",
            }
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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
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
    payload = {
        "summary": _read_json(output_path / "run_summary.json"),
        "search_meta": _read_json(output_path / "search_meta.json"),
        "citations": _read_json(output_path / "citations.json", default=[]),
        "charts": _read_json(output_path / "charts.json", default=[]),
        "claims": _read_json(output_path / "claims.json", default=[]),
        "evidence": _read_json(output_path / "evidence.json", default=[]),
        "tables": _read_json(output_path / "tables.json", default=[]),
        "financial_metrics": _read_json(output_path / "financial_metrics.json", default={}),
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
        "trace": _read_jsonl(output_path / "task_trace.jsonl"),
        "report_markdown": _read_text(report_path / "report.md"),
        "report_html_url": "/artifacts/report.html" if report_html.exists() else "",
        "output_dir": str(output_path),
        "report_dir": str(report_path),
    }
    payload["artifact_urls"] = _artifact_urls(output_path, report_path)
    return payload


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
      min-height: 48vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 28px 18px 16px;
      gap: 28px;
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
      min-height: 74px;
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
      font-size: 20px;
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
      padding: 0 4px 14px;
      flex-wrap: wrap;
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
      .hero { min-height: 42vh; }
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
      <div id="thinkingLabel" class="thinking">Thinking</div>
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
        <label>执行模式<select id="executionMode"><option value="dynamic">dynamic</option><option value="static">static</option></select></label>
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
    const tabs = ["总览", "报告", "图表", "引用", "表格", "PDF章节", "公司画像", "Claims", "质量评测", "轨迹", "时间线", "原始数据"];
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
        "图表": renderCharts,
        "引用": renderCitations,
        "表格": renderTables,
        "PDF章节": renderPdf,
        "公司画像": renderProfile,
        "Claims": renderClaims,
        "质量评测": renderQuality,
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


def default_engines_for_symbol(symbol: str, realtime: bool = False) -> str:
    if not realtime:
        return DEFAULT_ENGINES
    identity = resolve_company_identity(symbol, default=symbol)
    engines = list(identity.data_source_plan.get("engines") or [])
    return ",".join(engines or _parse_engines(DEFAULT_ENGINES))


def validate_period_for_report(raw_period: str, today: date | None = None) -> Dict[str, Any]:
    raw = str(raw_period or "").strip().upper()
    today = today or date.today()
    if len(raw) != 6 or raw[4] != "Q" or not raw[:4].isdigit() or raw[-1] not in "1234":
        return {"ok": True, "message": "", "suggested_periods": []}
    year = int(raw[:4])
    quarter = int(raw[-1])
    quarter_end_month = {1: 3, 2: 6, 3: 9, 4: 12}[quarter]
    quarter_end_day = {1: 31, 2: 30, 3: 30, 4: 31}[quarter]
    quarter_end = date(year, quarter_end_month, quarter_end_day)
    if quarter_end < today:
        return {"ok": True, "message": "", "suggested_periods": []}
    prior_year, prior_quarter = _previous_completed_quarter(today)
    suggested = [f"{prior_year}Q{prior_quarter}", f"{today.year - 1}Q4"]
    return {
        "ok": False,
        "message": f"{raw} 尚未结束，不能生成正式财报口径研报；可选 {suggested[0]} 或 {suggested[1]}。",
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
    return any(term in lowered for term in ["研报", "财报", "报告", "research report", "company report"])


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
        urls["report.md"] = "/artifacts/report.md"
    if (report_path / "report.html").exists():
        urls["report.html"] = "/artifacts/report.html"
    if (report_path / "report.json").exists():
        urls["report.json"] = "/artifacts/report.json"
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
