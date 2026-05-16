"""Local web UI for running and inspecting the financial multi-agent workflow."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
import json
from pathlib import Path
import mimetypes
from typing import Any, Dict, List, Tuple
from urllib.parse import unquote, urlparse

from src.app.agent_chat import AgentChatService
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator


DEFAULT_OUTPUT_DIR = "data/outputs/multi_agent"
DEFAULT_REPORT_DIR = "data/reports/multi_agent"
DEFAULT_ENGINES = "local_real_data,yahoo_finance,tavily,local_evidence"


def create_ui_handler(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    raw_data_root: str = "data/raw/real_data",
    memory_root: str = "memory/chat",
) -> type[BaseHTTPRequestHandler]:
    output_root = Path(output_dir)
    report_root = Path(report_dir)
    chat_service = AgentChatService(
        config_path=config_path,
        memory_root=memory_root,
        output_root=output_root,
        report_root=report_root,
    )

    class FinancialAgentUIHandler(BaseHTTPRequestHandler):
        server_version = "DeepReportPlusUI/0.1"

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._send_html(render_index_html())
            elif path == "/api/latest":
                self._send_json(load_run_payload(output_root=output_root, report_root=report_root))
            elif path.startswith("/artifacts/"):
                self._serve_artifact(path.removeprefix("/artifacts/"), output_root=output_root, report_root=report_root)
            else:
                self._send_json({"error": f"not found: {path}"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/chat":
                self._handle_chat()
                return
            if path != "/api/run":
                self._send_json({"error": f"not found: {path}"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                payload = self._read_json()
                symbol = str(payload.get("symbol") or "AAPL").strip().upper()
                period = str(payload.get("period") or "2025Q4").strip()
                topic = str(payload.get("topic") or f"分析 {symbol} {period} 财务表现，并生成带引用的研究报告").strip()
                engines = _parse_engines(payload.get("engines") or DEFAULT_ENGINES)
                fast = bool(payload.get("fast", True))
                execution_mode = str(payload.get("execution_mode") or "dynamic")
                memory_enabled = bool(payload.get("memory_enabled", False))
                orchestrator = MultiAgentOrchestrator(
                    output_dir=str(output_root),
                    report_dir=str(report_root),
                    config_path=config_path,
                    raw_data_root=raw_data_root,
                    memory_enabled=memory_enabled,
                )
                result = orchestrator.run(
                    research_topic=topic,
                    symbol=symbol,
                    period=period,
                    execution_mode=execution_mode,
                    fast=fast,
                    search_engines=engines,
                )
                response = load_run_payload(output_root=output_root, report_root=report_root)
                response["result"] = result
                self._send_json(response)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def _handle_chat(self) -> None:
            try:
                payload = self._read_json()
                symbol = str(payload.get("symbol") or "AAPL").strip().upper()
                period = str(payload.get("period") or "2025Q4").strip()
                memory_enabled = bool(payload.get("memory_enabled", False))
                allow_report_run = bool(payload.get("allow_report_run", False))
                orchestrator = None
                if allow_report_run:
                    orchestrator = MultiAgentOrchestrator(
                        output_dir=str(output_root),
                        report_dir=str(report_root),
                        config_path=config_path,
                        raw_data_root=raw_data_root,
                        memory_enabled=memory_enabled,
                    )
                response = chat_service.handle_chat(
                    message=str(payload.get("message") or ""),
                    session_id=str(payload.get("session_id") or "default"),
                    user_id=str(payload.get("user_id") or "local_user"),
                    symbol=symbol,
                    period=period,
                    memory_enabled=memory_enabled,
                    allow_report_run=allow_report_run,
                    orchestrator=orchestrator,
                    engines=_parse_engines(payload.get("engines") or DEFAULT_ENGINES),
                    fast=bool(payload.get("fast", True)),
                    execution_mode=str(payload.get("execution_mode") or "dynamic"),
                )
                if response.get("result"):
                    latest = load_run_payload(output_root=output_root, report_root=report_root)
                    response["latest"] = latest
                self._send_json(response)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("JSON payload must be an object")
            return payload

        def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_artifact(self, raw_path: str, output_root: Path, report_root: Path) -> None:
            relative = Path(unquote(raw_path))
            candidates = [
                (output_root / relative).resolve(),
                (report_root / relative).resolve(),
            ]
            allowed_roots = [output_root.resolve(), report_root.resolve()]
            for candidate in candidates:
                if not candidate.exists() or not candidate.is_file():
                    continue
                if not any(_is_relative_to(candidate, root) for root in allowed_roots):
                    continue
                content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
                body = candidate.read_bytes()
                self.send_response(int(HTTPStatus.OK))
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json({"error": f"artifact not found: {raw_path}"}, status=HTTPStatus.NOT_FOUND)

    return FinancialAgentUIHandler


def load_run_payload(output_root: Path, report_root: Path) -> Dict[str, Any]:
    summary = _read_json(output_root / "run_summary.json", default={})
    search_meta = _read_json(output_root / "search_meta.json", default={})
    citations = _read_json(output_root / "citations.json", default=[])
    charts = _read_json(output_root / "charts.json", default=[])
    mcp_manifest = _read_json(output_root / "mcp_manifest.json", default={})
    revision_history = _read_json(output_root / "revision_history.json", default=[])
    verification = _read_json(output_root / "verification_report.json", default={})
    trace = _read_jsonl(output_root / "task_trace.jsonl")
    report_markdown = _read_text(report_root / "report.md")
    report_html_path = report_root / "report.html"

    return {
        "summary": summary,
        "search_meta": search_meta,
        "citations": citations,
        "charts": charts,
        "mcp_manifest": mcp_manifest,
        "revision_history": revision_history,
        "verification_report": verification,
        "trace": trace,
        "report_markdown": report_markdown,
        "report_html_url": "/artifacts/report.html" if report_html_path.exists() else "",
        "artifact_urls": {
            "summary": "/artifacts/run_summary.json" if (output_root / "run_summary.json").exists() else "",
            "search_meta": "/artifacts/search_meta.json" if (output_root / "search_meta.json").exists() else "",
            "citations": "/artifacts/citations.json" if (output_root / "citations.json").exists() else "",
            "charts": "/artifacts/charts.json" if (output_root / "charts.json").exists() else "",
            "mcp_manifest": "/artifacts/mcp_manifest.json" if (output_root / "mcp_manifest.json").exists() else "",
            "revision_history": "/artifacts/revision_history.json" if (output_root / "revision_history.json").exists() else "",
        },
    }


def run_ui_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    report_dir: str = DEFAULT_REPORT_DIR,
    config_path: str = "configs/model_backends.yaml",
    raw_data_root: str = "data/raw/real_data",
    memory_root: str = "memory/chat",
) -> Tuple[ThreadingHTTPServer, str]:
    handler = create_ui_handler(
        output_dir=output_dir,
        report_dir=report_dir,
        config_path=config_path,
        raw_data_root=raw_data_root,
        memory_root=memory_root,
    )
    server = ThreadingHTTPServer((host, port), handler)
    return server, f"http://{host}:{server.server_address[1]}"


def _parse_engines(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def render_index_html() -> str:
    default_topic = "分析 AAPL 2025Q4 财务表现，并生成带引用、图表和验证报告的研究报告"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DeepReport+ 金融多智能体工作台</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #18201d;
      --muted: #66736d;
      --line: #d7dfda;
      --panel: #ffffff;
      --soft: #f5f7f3;
      --accent: #0f766e;
      --accent-dark: #115e59;
      --accent-2: #9a3412;
      --ok: #15803d;
      --bad: #b91c1c;
      --shadow: 0 18px 50px rgba(23, 32, 29, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; color: var(--ink); background: linear-gradient(180deg, #f9faf7 0%, var(--soft) 100%); }}
    header {{ padding: 18px 24px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,.92); backdrop-filter: blur(12px); display: flex; align-items: center; justify-content: space-between; gap: 16px; position: sticky; top: 0; z-index: 3; }}
    h1 {{ font-size: 20px; margin: 0; font-weight: 750; letter-spacing: 0; }}
    h2 {{ margin: 22px 0 10px; font-size: 16px; }}
    .brand {{ display: flex; flex-direction: column; gap: 2px; }}
    .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 750; text-transform: uppercase; }}
    .subtitle {{ color: var(--muted); font-size: 13px; }}
    main {{ display: grid; grid-template-columns: 388px 1fr; gap: 18px; padding: 18px; min-height: calc(100vh - 74px); }}
    aside, section.panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); }}
    aside {{ padding: 18px; align-self: start; position: sticky; top: 92px; }}
    .side-title {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }}
    .side-title b {{ font-size: 16px; }}
    .pill {{ display: inline-flex; align-items: center; border: 1px solid #b7d8d2; color: var(--accent-dark); background: #eef9f6; padding: 4px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    label {{ display: block; font-size: 13px; color: var(--muted); margin: 13px 0 6px; }}
    input, textarea, select {{ width: 100%; border: 1px solid var(--line); border-radius: 7px; padding: 10px 11px; font-size: 14px; background: #fff; color: var(--ink); outline: none; transition: border-color .16s, box-shadow .16s; }}
    input:focus, textarea:focus, select:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15, 118, 110, .12); }}
    textarea {{ min-height: 116px; resize: vertical; line-height: 1.5; }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .check {{ display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 14px; }}
    .check input {{ width: auto; }}
    .actions {{ display: grid; grid-template-columns: 1fr; gap: 9px; margin-top: 14px; }}
    button {{ width: 100%; margin-top: 0; border: 0; border-radius: 7px; background: var(--accent); color: #fff; padding: 11px 12px; font-weight: 750; cursor: pointer; transition: transform .12s, background .12s; }}
    button:hover {{ background: var(--accent-dark); transform: translateY(-1px); }}
    button.secondary {{ background: #eef2ef; color: var(--ink); border: 1px solid var(--line); }}
    button.secondary:hover {{ background: #e3ebe6; }}
    button:disabled {{ opacity: .6; cursor: wait; }}
    .tabs {{ display: flex; gap: 6px; padding: 10px; border-bottom: 1px solid var(--line); background: #fff; border-radius: 8px 8px 0 0; flex-wrap: wrap; position: sticky; top: 75px; z-index: 2; }}
    .tab {{ width: auto; margin: 0; padding: 8px 11px; background: transparent; color: var(--ink); border: 1px solid var(--line); }}
    .tab.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .content {{ padding: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 12px; }}
    .metric {{ border: 1px solid var(--line); border-radius: 8px; padding: 13px; background: linear-gradient(180deg, #fff 0%, #fbfcfb 100%); min-height: 78px; }}
    .metric b {{ display: block; font-size: 22px; color: var(--accent-dark); }}
    .metric span {{ color: var(--muted); font-size: 12px; }}
    .hint {{ color: var(--muted); font-size: 12px; line-height: 1.5; margin-top: 10px; }}
    .status {{ color: var(--muted); font-size: 13px; margin-top: 10px; min-height: 20px; }}
    .error {{ color: var(--bad); }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #111827; color: #e5e7eb; padding: 14px; border-radius: 8px; overflow: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    figure {{ margin: 0; border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fff; }}
    figure img {{ width: 100%; height: auto; display: block; }}
    figcaption {{ color: var(--muted); margin-top: 8px; font-size: 13px; }}
    iframe {{ width: 100%; height: 720px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .links a {{ display: inline-block; margin: 0 8px 8px 0; color: var(--accent); font-weight: 650; }}
    .chat-box {{ margin-top: 18px; border-top: 1px solid var(--line); padding-top: 14px; }}
    .chat-log {{ display: grid; gap: 8px; max-height: 260px; overflow: auto; padding: 8px; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfb; }}
    .msg {{ padding: 8px 10px; border-radius: 8px; font-size: 13px; line-height: 1.45; background: #eef2ef; }}
    .msg.user {{ margin-left: 28px; background: #e0f2f1; }}
    .msg.assistant {{ margin-right: 28px; background: #fff; border: 1px solid var(--line); }}
    .timeline {{ display: grid; gap: 10px; }}
    .event {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fff; }}
    .event b {{ color: var(--accent-dark); display: block; margin-bottom: 4px; }}
    @media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; }} aside {{ position: static; }} .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="eyebrow">Financial Multi-Agent</div>
      <h1>DeepReport+ 金融研究工作台</h1>
      <div class="subtitle">规划、检索、分析、写作、引用、图表和验证的一体化演示</div>
    </div>
    <div id="headerStatus" class="status">就绪</div>
  </header>
  <main>
    <aside>
      <div class="side-title"><b>任务配置</b><span class="pill">端到端</span></div>
      <label for="topic">研究任务</label>
      <textarea id="topic">{escape(default_topic)}</textarea>
      <div class="row">
        <div>
          <label for="symbol">股票代码</label>
          <input id="symbol" value="AAPL">
        </div>
        <div>
          <label for="period">期间</label>
          <input id="period" value="2025Q4">
        </div>
      </div>
      <label for="engines">搜索/数据源</label>
      <input id="engines" value="{DEFAULT_ENGINES}">
      <label for="mode">执行模式</label>
      <select id="mode"><option value="dynamic">dynamic</option><option value="static">static</option></select>
      <div class="check"><input id="fast" type="checkbox" checked><span>快速模式</span></div>
      <div class="check"><input id="memoryEnabled" type="checkbox"><span>启用三层记忆</span></div>
      <div class="actions">
        <button id="runBtn">生成多智能体研究报告</button>
        <button class="secondary" id="refreshBtn" type="button">读取最近一次结果</button>
      </div>
      <div class="hint">建议先保持默认参数运行。生成完成后，在右侧查看报告、图表、引用、执行轨迹和原始 JSON。</div>
      <div id="status" class="status"></div>
      <div class="chat-box">
        <div class="side-title"><b>研究助手</b><span class="pill">Chat</span></div>
        <label for="sessionId">会话</label>
        <input id="sessionId" value="local-session">
        <label for="chatInput">对话</label>
        <textarea id="chatInput" placeholder="直接提问，或让助手根据当前标的启动研报任务"></textarea>
        <div class="check"><input id="allowReportRun" type="checkbox"><span>允许 Chat 启动研报</span></div>
        <div class="actions">
          <button id="chatBtn" type="button">发送给研究助手</button>
        </div>
        <div id="chatLog" class="chat-log"></div>
        <div class="hint">Memory 只作为上下文与偏好，不作为报告证据；事实仍需 citation 和 verifier。</div>
      </div>
    </aside>
    <section class="panel">
      <div class="tabs">
        <button class="tab active" data-tab="overview">总览</button>
        <button class="tab" data-tab="report">报告</button>
        <button class="tab" data-tab="charts">图表</button>
        <button class="tab" data-tab="citations">引用</button>
        <button class="tab" data-tab="trace">轨迹</button>
        <button class="tab" data-tab="timeline">时间线</button>
        <button class="tab" data-tab="raw">原始数据</button>
      </div>
      <div class="content" id="content"></div>
    </section>
  </main>
  <script>
    let latest = null;
    let activeTab = 'overview';
    let chatMessages = [];
    let chatTrace = [];
    const $ = id => document.getElementById(id);

    function setStatus(text, isError=false) {{
      $('status').textContent = text;
      $('headerStatus').textContent = text || '就绪';
      $('status').className = isError ? 'status error' : 'status';
    }}

    async function runReport() {{
      $('runBtn').disabled = true;
      setStatus('多智能体正在协作生成报告，通常需要 40-120 秒...');
      try {{
        const res = await fetch('/api/run', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            topic: $('topic').value,
            symbol: $('symbol').value,
            period: $('period').value,
            engines: $('engines').value,
            execution_mode: $('mode').value,
            fast: $('fast').checked,
            memory_enabled: $('memoryEnabled').checked
          }})
        }});
        latest = await res.json();
        if (!res.ok || latest.error) throw new Error(latest.error || '运行失败');
        setStatus('报告生成完成');
        render();
      }} catch (err) {{
        setStatus(err.message, true);
      }} finally {{
        $('runBtn').disabled = false;
      }}
    }}

    async function loadLatest() {{
      setStatus('正在读取最近一次输出...');
      const res = await fetch('/api/latest');
      latest = await res.json();
      setStatus('已读取最近一次输出');
      render();
    }}

    function render() {{
      const c = $('content');
      if (!latest) {{ c.innerHTML = '<p>还没有加载运行结果。</p>'; return; }}
      if (activeTab === 'overview') c.innerHTML = renderOverview(latest);
      if (activeTab === 'report') c.innerHTML = renderReport(latest);
      if (activeTab === 'charts') c.innerHTML = renderCharts(latest);
      if (activeTab === 'citations') c.innerHTML = renderCitations(latest);
      if (activeTab === 'trace') c.innerHTML = renderTrace(latest);
      if (activeTab === 'timeline') c.innerHTML = renderTimeline(latest);
      if (activeTab === 'raw') c.innerHTML = '<pre>' + escapeHtml(JSON.stringify(latest, null, 2)) + '</pre>';
    }}

    async function sendChat() {{
      const text = $('chatInput').value.trim();
      if (!text) return;
      $('chatBtn').disabled = true;
      chatMessages.push({{role:'user', content:text}});
      renderChatLog();
      setStatus('研究助手正在处理...');
      try {{
        const res = await fetch('/api/chat', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            message: text,
            session_id: $('sessionId').value || 'local-session',
            symbol: $('symbol').value,
            period: $('period').value,
            engines: $('engines').value,
            execution_mode: $('mode').value,
            fast: $('fast').checked,
            memory_enabled: $('memoryEnabled').checked,
            allow_report_run: $('allowReportRun').checked
          }})
        }});
        const payload = await res.json();
        if (!res.ok || payload.error) throw new Error(payload.error || 'Chat 失败');
        chatMessages.push({{role:'assistant', content:payload.answer || ''}});
        chatTrace = payload.tool_trace || [];
        if (payload.latest) latest = payload.latest;
        renderChatLog();
        render();
        setStatus('研究助手已回复');
      }} catch (err) {{
        chatMessages.push({{role:'assistant', content:err.message}});
        renderChatLog();
        setStatus(err.message, true);
      }} finally {{
        $('chatBtn').disabled = false;
        $('chatInput').value = '';
      }}
    }}

    function renderChatLog() {{
      const log = $('chatLog');
      log.innerHTML = chatMessages.length ? chatMessages.map(m => `<div class="msg ${{escapeAttr(m.role)}}"><b>${{escapeHtml(m.role)}}:</b> ${{escapeHtml(m.content)}}</div>`).join('') : '<div class="hint">暂无对话。</div>';
      log.scrollTop = log.scrollHeight;
    }}

    function renderOverview(data) {{
      const s = data.summary || {{}};
      const engines = (s.search_engines || []).join(', ');
      const passed = s.verification_passed === true ? '通过' : '未通过';
      return `
        <div class="grid">
          ${{metric('智能体', s.agent_count)}}
          ${{metric('证据', s.evidence_count)}}
          ${{metric('结论', s.claim_count)}}
          ${{metric('引用', s.citation_count)}}
          ${{metric('图表', s.chart_count)}}
          ${{metric('MCP 工具', s.mcp_tool_count)}}
          ${{metric('验证', passed)}}
          ${{metric('耗时秒', s.total_duration_sec)}}
        </div>
        <h2>搜索与数据源</h2>
        <p>${{escapeHtml(engines || '暂无搜索元数据。')}}</p>
        <h2>产物文件</h2>
        <div class="links">${{artifactLinks(data.artifact_urls || {{}})}}${{data.report_html_url ? `<a href="${{data.report_html_url}}" target="_blank">report.html</a>` : ''}}</div>
      `;
    }}

    function metric(label, value) {{ return `<div class="metric"><b>${{escapeHtml(value ?? '-')}}</b><span>${{escapeHtml(label)}}</span></div>`; }}

    function renderReport(data) {{
      if (data.report_html_url) return `<iframe src="${{data.report_html_url}}"></iframe>`;
      return `<pre>${{escapeHtml(data.report_markdown || '暂无报告。')}}</pre>`;
    }}

    function renderCharts(data) {{
      const charts = data.charts || [];
      if (!charts.length) return '<p>暂无图表。</p>';
      return '<div class="charts">' + charts.map(ch => {{
        const path = String(ch.output_path || '').replace('data/outputs/multi_agent/', '');
        return `<figure><img src="/artifacts/${{escapeAttr(path)}}" alt="${{escapeAttr(ch.title || ch.chart_id)}}"><figcaption>${{escapeHtml(ch.title || ch.chart_id)}}</figcaption></figure>`;
      }}).join('') + '</div>';
    }}

    function renderCitations(data) {{
      const rows = data.citations || [];
      if (!rows.length) return '<p>暂无引用。</p>';
      return `<table><thead><tr><th>证据ID</th><th>标题</th><th>类型</th><th>支持结论</th><th>来源</th></tr></thead><tbody>${{rows.map(r => `
        <tr><td>${{escapeHtml(r.evidence_id)}}</td><td>${{escapeHtml(r.title)}}</td><td>${{escapeHtml(r.source_type)}}</td><td>${{escapeHtml((r.claim_ids || []).join(', ') || '未关联')}}</td><td>${{r.source_url ? `<a href="${{escapeAttr(r.source_url)}}" target="_blank">打开</a>` : ''}}</td></tr>
      `).join('')}}</tbody></table>`;
    }}

    function renderTrace(data) {{
      const rows = data.trace || [];
      if (!rows.length) return '<p>暂无执行轨迹。</p>';
      return `<table><thead><tr><th>智能体</th><th>任务</th><th>状态</th><th>秒</th><th>输出字段</th></tr></thead><tbody>${{rows.map(r => `
        <tr><td>${{escapeHtml(r.agent)}}</td><td>${{escapeHtml((r.task || {{}}).task_type || '')}}</td><td>${{escapeHtml(r.status)}}</td><td>${{escapeHtml(r.duration_sec)}}</td><td>${{escapeHtml((r.output_keys || []).join(', '))}}</td></tr>
      `).join('')}}</tbody></table>`;
    }}

    function renderTimeline(data) {{
      const events = [];
      (chatTrace || []).forEach(item => events.push({{stage:item.stage || 'chat', detail:item.detail || ''}}));
      (data.trace || []).forEach(r => events.push({{stage:r.agent || 'agent', detail:`${{(r.task || {{}}).task_type || ''}} · ${{r.status || ''}} · ${{r.duration_sec || ''}}s`}}));
      if (!events.length) return '<p>暂无思考/动作/观察/验证时间线。</p>';
      return '<div class="timeline">' + events.map(e => `<div class="event"><b>${{escapeHtml(e.stage)}}</b><span>${{escapeHtml(e.detail)}}</span></div>`).join('') + '</div>';
    }}

    function artifactLinks(urls) {{
      const names = {{summary:'运行摘要', search_meta:'搜索记录', citations:'引用表', charts:'图表索引', mcp_manifest:'MCP工具清单'}};
      return Object.entries(urls).filter(([k,v]) => v).map(([k,v]) => `<a href="${{v}}" target="_blank">${{escapeHtml(names[k] || k)}}</a>`).join('');
    }}

    function escapeHtml(v) {{ return String(v ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
    function escapeAttr(v) {{ return encodeURI(String(v ?? '')); }}

    document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => {{
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      activeTab = btn.dataset.tab;
      render();
    }}));
    $('runBtn').addEventListener('click', runReport);
    $('refreshBtn').addEventListener('click', loadLatest);
    $('chatBtn').addEventListener('click', sendChat);
    renderChatLog();
    loadLatest();
  </script>
</body>
</html>"""
