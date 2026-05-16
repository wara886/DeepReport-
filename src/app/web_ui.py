"""Local web UI for running and inspecting the financial multi-agent workflow."""

from __future__ import annotations

from datetime import date
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import unquote, urlparse

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.app.agent_chat import AgentChatService


DEFAULT_OUTPUT_DIR = "data/outputs/multi_agent"
DEFAULT_REPORT_DIR = "data/reports/multi_agent"
DEFAULT_ENGINES = "local_real_data,yahoo_finance,tavily,local_evidence"
A_SHARE_ENGINES = "local_real_data,cninfo_announcements,exchange_announcements,eastmoney_financials,yahoo_finance,eastmoney,local_evidence"
US_ENGINES = "local_real_data,sec_edgar,yahoo_finance,independent_macro,local_evidence"


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
        server_version = "DeepReportPlusUI/0.2"

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
                guard = validate_period_for_report(period)
                if not guard["ok"]:
                    self._send_json({"error": guard["message"], "period_guard": guard}, status=HTTPStatus.BAD_REQUEST)
                    return
                enable_remote_data = bool(payload.get("enable_remote_data", False))
                data_source_config_path = str(payload.get("data_source_config_path") or "configs/data_sources.yaml").strip()
                engines = _parse_engines(payload.get("engines") or default_engines_for_symbol(symbol, enable_remote_data))
                orchestrator = MultiAgentOrchestrator(
                    output_dir=str(output_root),
                    report_dir=str(report_root),
                    config_path=config_path,
                    raw_data_root=raw_data_root,
                    memory_enabled=bool(payload.get("memory_enabled", False)),
                )
                result = orchestrator.run(
                    research_topic=str(payload.get("topic") or f"分析 {symbol} {period} 财务表现，并生成带引用的研究报告").strip(),
                    symbol=symbol,
                    period=period,
                    execution_mode=str(payload.get("execution_mode") or "dynamic"),
                    fast=bool(payload.get("fast", True)),
                    search_engines=engines,
                    enable_remote_data=enable_remote_data,
                    data_source_config_path=data_source_config_path,
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
                allow_report_run = bool(payload.get("allow_report_run", False))
                guard = validate_period_for_report(period)
                if allow_report_run and not guard["ok"]:
                    self._send_json({"error": guard["message"], "period_guard": guard}, status=HTTPStatus.BAD_REQUEST)
                    return
                enable_remote_data = bool(payload.get("enable_remote_data", False))
                data_source_config_path = str(payload.get("data_source_config_path") or "configs/data_sources.yaml").strip()
                memory_enabled = bool(payload.get("memory_enabled", False))
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
                    engines=_parse_engines(payload.get("engines") or default_engines_for_symbol(symbol, enable_remote_data)),
                    fast=bool(payload.get("fast", True)),
                    execution_mode=str(payload.get("execution_mode") or "dynamic"),
                    enable_remote_data=enable_remote_data,
                    data_source_config_path=data_source_config_path,
                )
                if response.get("result"):
                    response["latest"] = load_run_payload(output_root=output_root, report_root=report_root)
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
            candidates = [(output_root / relative).resolve(), (report_root / relative).resolve()]
            allowed_roots = [output_root.resolve(), report_root.resolve()]
            for candidate in candidates:
                if not candidate.exists() or not candidate.is_file():
                    continue
                if not any(_is_relative_to(candidate, root) for root in allowed_roots):
                    continue
                body = candidate.read_bytes()
                self.send_response(int(HTTPStatus.OK))
                self.send_header("Content-Type", mimetypes.guess_type(str(candidate))[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json({"error": f"artifact not found: {raw_path}"}, status=HTTPStatus.NOT_FOUND)

    return FinancialAgentUIHandler


def load_run_payload(output_root: Path, report_root: Path) -> Dict[str, Any]:
    summary = _read_json(output_root / "run_summary.json", default={})
    report_html_path = report_root / "report.html"
    return {
        "summary": summary,
        "search_meta": _read_json(output_root / "search_meta.json", default={}),
        "citations": _read_json(output_root / "citations.json", default=[]),
        "charts": _read_json(output_root / "charts.json", default=[]),
        "claims": _read_json(output_root / "claims.json", default=[]),
        "evidence": _read_json(output_root / "evidence.json", default=[]),
        "tables": _read_json(output_root / "tables.json", default=[]),
        "financial_metrics": _read_json(output_root / "financial_metrics.json", default={}),
        "pdf_manifest": _read_json(output_root / "pdf_manifest.json", default=[]),
        "pdf_sections": _read_json(output_root / "pdf_sections.json", default=[]),
        "company_profile_extracted": _read_json(output_root / "company_profile_extracted.json", default={}),
        "mcp_manifest": _read_json(output_root / "mcp_manifest.json", default={}),
        "revision_history": _read_json(output_root / "revision_history.json", default=[]),
        "verification_report": _read_json(output_root / "verification_report.json", default={}),
        "trace": _read_jsonl(output_root / "task_trace.jsonl"),
        "report_markdown": _read_text(report_root / "report.md"),
        "report_html_url": "/artifacts/report.html" if report_html_path.exists() else "",
        "output_dir": str(output_root),
        "report_dir": str(report_root),
        "artifact_urls": _artifact_urls(output_root),
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


def _artifact_urls(output_root: Path) -> Dict[str, str]:
    names = [
        "run_summary",
        "search_meta",
        "citations",
        "charts",
        "claims",
        "evidence",
        "tables",
        "financial_metrics",
        "pdf_manifest",
        "pdf_sections",
        "company_profile_extracted",
        "mcp_manifest",
        "revision_history",
    ]
    return {name.replace("run_", "") if name == "run_summary" else name: f"/artifacts/{name}.json" for name in names if (output_root / f"{name}.json").exists()}


def _parse_engines(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def default_engines_for_symbol(symbol: str, realtime: bool = False) -> str:
    if not realtime:
        return DEFAULT_ENGINES
    normalized = str(symbol or "").upper()
    if normalized.endswith((".SS", ".SZ")) or (normalized[:1] in {"0", "3", "6"} and normalized[:6].isdigit()):
        return A_SHARE_ENGINES
    return US_ENGINES


def validate_period_for_report(period: str, today: date | None = None) -> Dict[str, Any]:
    today = today or date.today()
    raw = str(period or "").strip().upper()
    if len(raw) != 6 or raw[4] != "Q" or not raw[:4].isdigit() or raw[5] not in "1234":
        return {"ok": True, "period": raw, "message": ""}
    year = int(raw[:4])
    quarter = int(raw[5])
    quarter_end = {1: date(year, 3, 31), 2: date(year, 6, 30), 3: date(year, 9, 30), 4: date(year, 12, 31)}[quarter]
    if today <= quarter_end:
        prior_q = 4 if quarter == 1 else quarter - 1
        prior_y = year - 1 if quarter == 1 else year
        return {
            "ok": False,
            "period": raw,
            "quarter_end": quarter_end.isoformat(),
            "today": today.isoformat(),
            "suggested_periods": [f"{prior_y}Q{prior_q}", f"{year - 1}Q4"],
            "message": f"{raw} 尚未结束，不能生成正式财报口径研报；可选 {prior_y}Q{prior_q} 或 {year - 1}Q4。",
        }
    return {"ok": True, "period": raw, "quarter_end": quarter_end.isoformat(), "today": today.isoformat(), "message": ""}


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
    return path.read_text(encoding="utf-8") if path.exists() else ""


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
  <title>DeepReport+ 金融研究工作台</title>
  <style>
    :root {{ --ink:#17201d; --muted:#65736d; --line:#d7dfda; --panel:#fff; --soft:#f5f7f3; --accent:#0f766e; --accent-dark:#115e59; --bad:#b91c1c; --shadow:0 18px 50px rgba(23,32,29,.08); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; color:var(--ink); background:var(--soft); }}
    header {{ padding:16px 22px; border-bottom:1px solid var(--line); background:rgba(255,255,255,.94); display:flex; justify-content:space-between; gap:16px; position:sticky; top:0; z-index:4; }}
    h1 {{ font-size:20px; margin:0; letter-spacing:0; }} h2 {{ font-size:16px; margin:20px 0 10px; }}
    main {{ display:grid; grid-template-columns:minmax(360px,430px) 1fr; gap:16px; padding:16px; min-height:calc(100vh - 70px); }}
    aside,.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); }}
    aside {{ padding:16px; align-self:start; position:sticky; top:86px; max-height:calc(100vh - 100px); overflow:auto; }}
    label {{ display:block; font-size:13px; color:var(--muted); margin:12px 0 6px; }}
    input,textarea,select {{ width:100%; border:1px solid var(--line); border-radius:7px; padding:10px 11px; font-size:14px; background:#fff; color:var(--ink); }}
    textarea {{ min-height:108px; resize:vertical; line-height:1.5; }}
    button {{ width:100%; border:0; border-radius:7px; background:var(--accent); color:#fff; padding:11px 12px; font-weight:750; cursor:pointer; }}
    button.secondary {{ background:#eef2ef; color:var(--ink); border:1px solid var(--line); }}
    button.tab {{ width:auto; background:#fff; color:var(--ink); border:1px solid var(--line); padding:8px 11px; }}
    button.tab.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    button:disabled {{ opacity:.6; cursor:wait; }}
    .row {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }} .actions {{ display:grid; gap:9px; margin-top:14px; }}
    .check {{ display:flex; align-items:center; gap:8px; margin-top:11px; font-size:14px; }} .check input {{ width:auto; }}
    .pill {{ display:inline-flex; border:1px solid #b7d8d2; color:var(--accent-dark); background:#eef9f6; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700; }}
    .side-title {{ display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px; }}
    .chat-first {{ border:1px solid #b7d8d2; background:#fbfffd; padding:12px; border-radius:8px; margin-bottom:14px; }}
    .chat-log {{ display:grid; gap:8px; max-height:240px; overflow:auto; padding:8px; border:1px solid var(--line); border-radius:8px; background:#fbfcfb; }}
    .msg {{ padding:8px 10px; border-radius:8px; font-size:13px; line-height:1.45; background:#eef2ef; }} .msg.user {{ margin-left:28px; background:#e0f2f1; }} .msg.assistant {{ margin-right:28px; background:#fff; border:1px solid var(--line); }}
    .tabs {{ display:flex; gap:6px; padding:10px; border-bottom:1px solid var(--line); background:#fff; border-radius:8px 8px 0 0; flex-wrap:wrap; position:sticky; top:69px; z-index:3; }}
    .content {{ padding:18px; }} .grid {{ display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)); gap:12px; }}
    .metric {{ border:1px solid var(--line); border-radius:8px; padding:13px; background:#fff; min-height:78px; }} .metric b {{ display:block; font-size:22px; color:var(--accent-dark); }} .metric span,.hint,.status {{ color:var(--muted); font-size:12px; line-height:1.5; }}
    .status {{ font-size:13px; min-height:20px; }} .error {{ color:var(--bad); }}
    table {{ border-collapse:collapse; width:100%; font-size:13px; }} th,td {{ border-bottom:1px solid var(--line); padding:8px; text-align:left; vertical-align:top; }} th {{ color:var(--muted); }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:#111827; color:#e5e7eb; padding:14px; border-radius:8px; overflow:auto; }}
    iframe {{ width:100%; height:720px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
    .charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }} figure {{ margin:0; border:1px solid var(--line); border-radius:8px; padding:10px; background:#fff; }} figure img {{ width:100%; height:auto; display:block; }}
    .links a {{ display:inline-block; margin:0 8px 8px 0; color:var(--accent); font-weight:650; }} .timeline {{ display:grid; gap:10px; }} .event {{ border:1px solid var(--line); border-radius:8px; padding:10px 12px; background:#fff; }}
    @media (max-width:900px) {{ main {{ grid-template-columns:1fr; }} aside {{ position:static; max-height:none; }} .grid {{ grid-template-columns:repeat(2,1fr); }} }}
  </style>
</head>
<body>
  <header><div><div class="pill">Financial Multi-Agent</div><h1>DeepReport+ 对话式多模态研究工作台</h1></div><div id="headerStatus" class="status">就绪</div></header>
  <main>
    <aside>
      <div class="chat-first">
        <div class="side-title"><b>研究助手</b><span class="pill">Chat first</span></div>
        <label for="sessionId">会话</label><input id="sessionId" value="local-session">
        <label for="chatInput">对话</label><textarea id="chatInput" placeholder="例如：帮我生成 600519.SS 2025Q4 研报，使用 A 股正式源。"></textarea>
        <div class="check"><input id="allowReportRun" type="checkbox" checked><span>允许 Chat 在确认参数后启动研报</span></div>
        <div class="actions"><button id="chatBtn" type="button">发送给研究助手</button></div>
        <div id="chatLog" class="chat-log"></div>
      </div>
      <div class="side-title"><b>任务配置</b><span class="pill">端到端</span></div>
      <label for="topic">研究任务</label><textarea id="topic">{escape(default_topic)}</textarea>
      <div class="row"><div><label for="symbol">股票代码</label><input id="symbol" value="AAPL"></div><div><label for="period">期间</label><input id="period" value="2025Q4"></div></div>
      <label for="engines">搜索/数据源</label><input id="engines" value="{DEFAULT_ENGINES}">
      <label for="mode">执行模式</label><select id="mode"><option value="dynamic">dynamic</option><option value="static">static</option></select>
      <div class="check"><input id="fast" type="checkbox" checked><span>快速模式</span></div>
      <div class="check"><input id="realtimeData" type="checkbox"><span>实时数据 / A 股正式源</span></div>
      <div class="check"><input id="memoryEnabled" type="checkbox"><span>启用三层记忆</span></div>
      <div class="actions"><button id="runBtn">生成多智能体研究报告</button><button class="secondary" id="refreshBtn" type="button">读取最近一次结果</button></div>
      <div id="status" class="status"></div>
      <div id="runMeta" class="hint"></div>
    </aside>
    <section class="panel">
      <div class="tabs">
        <button class="tab active" data-tab="overview">总览</button><button class="tab" data-tab="report">报告</button><button class="tab" data-tab="charts">图表</button><button class="tab" data-tab="citations">引用</button><button class="tab" data-tab="tables">表格</button><button class="tab" data-tab="pdf">PDF章节</button><button class="tab" data-tab="profile">公司画像</button><button class="tab" data-tab="claims">Claims</button><button class="tab" data-tab="trace">轨迹</button><button class="tab" data-tab="timeline">时间线</button><button class="tab" data-tab="raw">原始数据</button>
      </div>
      <div class="content" id="content"></div>
    </section>
  </main>
  <script>
    let latest = null, activeTab = 'overview', chatMessages = [], chatTrace = [];
    const $ = id => document.getElementById(id);
    const aShareEngines = '{A_SHARE_ENGINES}';
    const usEngines = '{US_ENGINES}';
    const defaultEngines = '{DEFAULT_ENGINES}';
    function setStatus(text, isError=false) {{ $('status').textContent=text; $('headerStatus').textContent=text||'就绪'; $('status').className=isError?'status error':'status'; }}
    function isAShare(symbol) {{ const s=String(symbol||'').toUpperCase(); return s.endsWith('.SS')||s.endsWith('.SZ')||/^[036]\\d{{5}}$/.test(s); }}
    function syncEnginesFromSwitch() {{ if (!$('realtimeData').checked) $('engines').value=defaultEngines; else $('engines').value=isAShare($('symbol').value)?aShareEngines:usEngines; }}
    function localPeriodGuard() {{
      const p=String($('period').value||'').toUpperCase(), m=p.match(/^(\\d{{4}})Q([1-4])$/); if(!m) return '';
      const y=Number(m[1]), q=Number(m[2]), end=new Date(y, [2,5,8,11][q-1], [31,30,30,31][q-1]);
      const now=new Date(); if(now<=end) {{ const pq=q===1?4:q-1, py=q===1?y-1:y; return `${{p}} 尚未结束，不能生成正式财报口径研报；可选 ${{py}}Q${{pq}} 或 ${{y-1}}Q4。`; }} return '';
    }}
    async function runReport() {{
      const guard=localPeriodGuard(); if(guard) {{ setStatus(guard,true); return; }}
      $('runBtn').disabled=true; setStatus('多智能体正在协作生成报告，通常需要 40-120 秒...');
      try {{
        const res=await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{topic:$('topic').value,symbol:$('symbol').value,period:$('period').value,engines:$('engines').value,execution_mode:$('mode').value,fast:$('fast').checked,memory_enabled:$('memoryEnabled').checked,enable_remote_data:$('realtimeData').checked,data_source_config_path:'configs/data_sources.yaml'}})}});
        latest=await res.json(); if(!res.ok||latest.error) throw new Error(latest.error||'运行失败'); syncFormFromLatest(); setStatus('报告生成完成'); render();
      }} catch(err) {{ setStatus(err.message,true); }} finally {{ $('runBtn').disabled=false; }}
    }}
    async function loadLatest() {{ setStatus('正在读取最近一次输出...'); const res=await fetch('/api/latest'); latest=await res.json(); syncFormFromLatest(); setStatus('已读取最近一次输出'); render(); }}
    function syncFormFromLatest() {{
      const s=(latest&&latest.summary)||{{}}; if(s.symbol) $('symbol').value=s.symbol; if(s.period) $('period').value=s.period; if(s.research_topic) $('topic').value=s.research_topic;
      if(Array.isArray(s.search_engines)&&s.search_engines.length) $('engines').value=s.search_engines.join(',');
      $('realtimeData').checked = Array.isArray(s.search_engines) && s.search_engines.some(x=>['cninfo_announcements','exchange_announcements','eastmoney_financials','sec_edgar','independent_macro'].includes(x));
      $('runMeta').innerHTML = latest ? `当前输出：${{escapeHtml(latest.output_dir||'')}}<br>报告目录：${{escapeHtml(latest.report_dir||'')}}<br>标的/期间：${{escapeHtml(s.symbol||'-')}} / ${{escapeHtml(s.period||'-')}}，模式：${{escapeHtml(s.execution_mode||'-')}}，实时源：${{$('realtimeData').checked?'是':'否'}}` : '';
    }}
    async function sendChat() {{
      const text=$('chatInput').value.trim(); if(!text) return; const guard=$('allowReportRun').checked?localPeriodGuard():''; if(guard) {{ setStatus(guard,true); return; }}
      $('chatBtn').disabled=true; chatMessages.push({{role:'user',content:text}}); renderChatLog(); setStatus('研究助手正在处理...');
      try {{
        const res=await fetch('/api/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:text,session_id:$('sessionId').value||'local-session',symbol:$('symbol').value,period:$('period').value,engines:$('engines').value,execution_mode:$('mode').value,fast:$('fast').checked,memory_enabled:$('memoryEnabled').checked,allow_report_run:$('allowReportRun').checked,enable_remote_data:$('realtimeData').checked,data_source_config_path:'configs/data_sources.yaml'}})}});
        const payload=await res.json(); if(!res.ok||payload.error) throw new Error(payload.error||'Chat 失败'); chatMessages.push({{role:'assistant',content:payload.answer||''}}); chatTrace=payload.tool_trace||[]; if(payload.latest) latest=payload.latest; syncFormFromLatest(); renderChatLog(); render(); setStatus('研究助手已回复');
      }} catch(err) {{ chatMessages.push({{role:'assistant',content:err.message}}); renderChatLog(); setStatus(err.message,true); }} finally {{ $('chatBtn').disabled=false; $('chatInput').value=''; }}
    }}
    function render() {{
      const c=$('content'); if(!latest) {{ c.innerHTML='<p>还没有加载运行结果。</p>'; return; }}
      const map={{overview:renderOverview,report:renderReport,charts:renderCharts,citations:renderCitations,tables:renderTables,pdf:renderPdf,profile:renderProfile,claims:renderClaims,trace:renderTrace,timeline:renderTimeline,raw:d=>'<pre>'+escapeHtml(JSON.stringify(d,null,2))+'</pre>'}};
      c.innerHTML=(map[activeTab]||map.overview)(latest);
    }}
    function renderOverview(d) {{ const s=d.summary||{{}}, engines=(s.search_engines||[]).join(', '), passed=s.verification_passed===true?'通过':'未通过'; return `<div class="grid">${{metric('智能体',s.agent_count)}}${{metric('证据',s.evidence_count)}}${{metric('结论',s.claim_count)}}${{metric('引用',s.citation_count)}}${{metric('图表',s.chart_count)}}${{metric('PDF章节',((d.pdf_sections||[]).length))}}${{metric('验证',passed)}}${{metric('耗时秒',s.total_duration_sec)}}</div><h2>搜索与数据源</h2><p>${{escapeHtml(engines||'暂无搜索元数据。')}}</p><h2>产物文件</h2><div class="links">${{artifactLinks(d.artifact_urls||{{}})}}${{d.report_html_url?`<a href="${{d.report_html_url}}" target="_blank">report.html</a>`:''}}</div>`; }}
    function renderReport(d) {{ return d.report_html_url?`<iframe src="${{d.report_html_url}}"></iframe>`:`<pre>${{escapeHtml(d.report_markdown||'暂无报告。')}}</pre>`; }}
    function renderCharts(d) {{ const rows=d.charts||[]; if(!rows.length) return '<p>暂无图表。</p>'; return '<div class="charts">'+rows.map(ch=>{{ const path=String(ch.output_path||'').replace('data/outputs/multi_agent/',''); return `<figure><img src="/artifacts/${{escapeAttr(path)}}" alt="${{escapeAttr(ch.title||ch.chart_id)}}"><figcaption>${{escapeHtml(ch.title||ch.chart_id)}}</figcaption></figure>`; }}).join('')+'</div>'; }}
    function renderCitations(d) {{ const rows=d.citations||[]; if(!rows.length) return '<p>暂无引用。</p>'; return table(['证据ID','标题','类型','支持结论','来源'],rows.map(r=>[r.evidence_id,r.title,r.source_type,(r.claim_ids||[]).join(', ')||'未关联',r.source_url?`<a href="${{escapeAttr(r.source_url)}}" target="_blank">打开</a>`:''])); }}
    function renderTables(d) {{ const rows=d.tables||[]; if(!rows.length) return '<p>暂无三表标准化表格。</p>'; return table(['表','指标','值','单位','期间','来源证据'],rows.slice(0,240).map(r=>[r.statement||r.table_type,r.metric_name||r.field_name,r.value,r.unit,r.period,r.source_evidence_id||r.evidence_id])); }}
    function renderPdf(d) {{ const rows=d.pdf_sections||[]; if(!rows.length) return '<p>暂无 PDF 章节抽取结果。</p>'; return table(['章节','页码','来源证据','关键词','片段'],rows.map(r=>[r.section_type,r.page,r.evidence_id,r.matched_keyword,r.snippet])); }}
    function renderProfile(d) {{ return '<pre>'+escapeHtml(JSON.stringify(d.company_profile_extracted||{{}},null,2))+'</pre>'; }}
    function renderClaims(d) {{ const rows=d.claims||[]; if(!rows.length) return '<p>暂无 claims。</p>'; return table(['Claim ID','章节','结论','证据','置信度'],rows.map(r=>[r.claim_id,r.section_name,r.claim_text,(r.evidence_ids||[]).join(', '),r.confidence])); }}
    function renderTrace(d) {{ const rows=d.trace||[]; if(!rows.length) return '<p>暂无执行轨迹。</p>'; return table(['智能体','任务','状态','秒','输出字段'],rows.map(r=>[r.agent,(r.task||{{}}).task_type,r.status,r.duration_sec,(r.output_keys||[]).join(', ')])); }}
    function renderTimeline(d) {{ const events=[]; (chatTrace||[]).forEach(x=>events.push({{stage:x.stage||'chat',detail:x.detail||''}})); (d.trace||[]).forEach(r=>events.push({{stage:r.agent||'agent',detail:`${{(r.task||{{}}).task_type||''}} | ${{r.status||''}} | ${{r.duration_sec||''}}s`}})); if(!events.length) return '<p>暂无时间线。</p>'; return '<div class="timeline">'+events.map(e=>`<div class="event"><b>${{escapeHtml(e.stage)}}</b><span>${{escapeHtml(e.detail)}}</span></div>`).join('')+'</div>'; }}
    function renderChatLog() {{ const log=$('chatLog'); log.innerHTML=chatMessages.length?chatMessages.map(m=>`<div class="msg ${{escapeAttr(m.role)}}"><b>${{escapeHtml(m.role)}}:</b> ${{escapeHtml(m.content)}}</div>`).join(''):'<div class="hint">暂无对话。</div>'; log.scrollTop=log.scrollHeight; }}
    function metric(label,value) {{ return `<div class="metric"><b>${{escapeHtml(value??'-')}}</b><span>${{escapeHtml(label)}}</span></div>`; }}
    function table(headers,rows) {{ return `<table><thead><tr>${{headers.map(h=>`<th>${{escapeHtml(h)}}</th>`).join('')}}</tr></thead><tbody>${{rows.map(row=>`<tr>${{row.map(cell=>`<td>${{String(cell??'').startsWith('<a ')?cell:escapeHtml(cell)}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>`; }}
    function artifactLinks(urls) {{ const names={{summary:'运行摘要',search_meta:'搜索记录',citations:'引用表',charts:'图表索引',claims:'Claims',evidence:'Evidence',tables:'三表',financial_metrics:'指标',pdf_manifest:'PDF缓存',pdf_sections:'PDF章节',company_profile_extracted:'公司画像',mcp_manifest:'MCP工具',revision_history:'改写历史'}}; return Object.entries(urls).filter(([k,v])=>v).map(([k,v])=>`<a href="${{v}}" target="_blank">${{escapeHtml(names[k]||k)}}</a>`).join(''); }}
    function escapeHtml(v) {{ return String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
    function escapeAttr(v) {{ return encodeURI(String(v??'')); }}
    document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{{ document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); btn.classList.add('active'); activeTab=btn.dataset.tab; render(); }}));
    $('runBtn').addEventListener('click',runReport); $('refreshBtn').addEventListener('click',loadLatest); $('chatBtn').addEventListener('click',sendChat); $('realtimeData').addEventListener('change',syncEnginesFromSwitch); $('symbol').addEventListener('change',()=>{{ if($('realtimeData').checked) syncEnginesFromSwitch(); }});
    renderChatLog(); loadLatest();
  </script>
</body>
</html>"""
