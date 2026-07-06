"""Static HTML for the P0 FinSight research workbench."""

from __future__ import annotations


def render_workbench_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FinSight Research Workbench</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --nav: #101820;
      --nav-2: #16222d;
      --panel: #ffffff;
      --panel-2: #eef2f5;
      --text: #17202a;
      --muted: #667085;
      --line: #d8dee8;
      --accent: #1677ff;
      --accent-2: #0f8f7a;
      --good: #16803c;
      --bad: #b42318;
      --warn: #b56a00;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      letter-spacing: 0;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 236px minmax(0, 1fr);
    }
    .sidebar {
      background: var(--nav);
      color: #d7e0ea;
      padding: 18px 12px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
    }
    .brand {
      padding: 10px 10px 18px;
      border-bottom: 1px solid rgba(255,255,255,.1);
      margin-bottom: 10px;
    }
    .brand-title { font-size: 16px; font-weight: 700; color: #fff; }
    .brand-sub { font-size: 12px; color: #92a4b7; margin-top: 4px; }
    .nav { display: grid; gap: 4px; }
    .nav button {
      width: 100%;
      border: 0;
      background: transparent;
      color: #c5d1dd;
      border-radius: 8px;
      min-height: 36px;
      padding: 8px 10px;
      text-align: left;
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .nav button.active { background: var(--nav-2); color: #fff; }
    .nav .tag { color: #88a2b6; font-size: 11px; }
    .main {
      min-width: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .topbar {
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 0 22px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    .title h1 { margin: 0; font-size: 18px; font-weight: 700; }
    .sub { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .select, input, select, textarea {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      font-size: 13px;
      min-height: 36px;
    }
    .btn {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 8px 10px;
      cursor: pointer;
      color: var(--text);
      font: inherit;
      font-size: 13px;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      white-space: nowrap;
      min-height: 36px;
    }
    .btn.primary { background: var(--accent); border-color: var(--accent); color: white; }
    .btn.danger { color: var(--bad); }
    .content { padding: 18px 22px 28px; min-width: 0; }
    .view { display: none; }
    .view.active { display: block; }
    .grid { display: grid; gap: 14px; }
    .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 14px; }
    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .card { padding: 14px; min-height: 92px; }
    .label { color: var(--muted); font-size: 12px; }
    .value { font-size: 26px; font-weight: 700; margin-top: 8px; }
    .panel { padding: 16px; }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .panel h2 { margin: 0; font-size: 16px; }
    .panel h3 { margin: 0 0 8px; font-size: 14px; }
    .dashboard-layout { grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr); align-items: start; }
    .work-layout { grid-template-columns: minmax(0, 1fr) 360px; align-items: start; }
    .funnel { display: grid; gap: 8px; }
    .funnel-row {
      display: grid;
      grid-template-columns: 150px 1fr 56px;
      align-items: center;
      gap: 10px;
      font-size: 13px;
    }
    .bar { height: 10px; background: var(--panel-2); border-radius: 999px; overflow: hidden; }
    .bar span { display: block; height: 100%; background: var(--accent-2); min-width: 2px; }
    .split { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .dist { display: grid; gap: 8px; }
    .dist-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 7px;
    }
    .toolbar {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }
    .filters { display: flex; gap: 8px; flex-wrap: wrap; }
    .filters input { width: 210px; }
    .filters select { width: 150px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; border-bottom: 1px solid var(--line); padding: 10px 8px; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; background: #fbfcfd; }
    tr[data-selectable="true"] { cursor: pointer; }
    tr[data-selectable="true"]:hover td { background: #f8fbff; }
    .status {
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      background: var(--panel-2);
      color: var(--muted);
      white-space: nowrap;
    }
    .status.completed, .status.supported, .status.approved, .status.official { color: var(--good); background: #e9f7ef; }
    .status.failed, .status.rejected { color: var(--bad); background: #fff0ed; }
    .status.running, .status.queued, .status.pending, .status.secondary { color: var(--warn); background: #fff6e6; }
    .links { display: flex; gap: 6px; flex-wrap: wrap; }
    .detail {
      position: sticky;
      top: 82px;
      max-height: calc(100vh - 104px);
      overflow-y: auto;
    }
    .detail-section { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 12px; }
    .kv { display: grid; grid-template-columns: 108px minmax(0, 1fr); gap: 8px; font-size: 13px; margin: 7px 0; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      word-break: break-all;
    }
    .text-block {
      border: 1px solid var(--line);
      background: #fbfcfd;
      border-radius: 8px;
      padding: 10px;
      font-size: 13px;
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .timeline { display: grid; gap: 8px; }
    .event {
      border-left: 3px solid var(--line);
      padding-left: 10px;
      font-size: 13px;
    }
    .empty, .error {
      color: var(--muted);
      font-size: 13px;
      padding: 18px;
      text-align: center;
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }
    .error { color: var(--bad); }
    .placeholder-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .placeholder { min-height: 136px; display: grid; align-content: center; gap: 8px; }
    @media (max-width: 1100px) {
      .app { grid-template-columns: 1fr; }
      .sidebar {
        position: static;
        height: auto;
        display: block;
      }
      .nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .work-layout, .dashboard-layout, .cards, .placeholder-grid { grid-template-columns: 1fr; }
      .detail { position: static; max-height: none; }
    }
    @media (max-width: 760px) {
      .topbar { height: auto; align-items: flex-start; flex-direction: column; padding: 14px 16px; }
      .content { padding: 14px 16px 22px; }
      .nav { grid-template-columns: 1fr; }
      .filters input, .filters select { width: 100%; }
      table { min-width: 820px; }
      .table-scroll { overflow-x: auto; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-title">FinSight Research Workbench</div>
        <div class="brand-sub">Evidence-backed research console</div>
      </div>
      <nav class="nav" aria-label="Workbench navigation">
        <button class="active" data-view="dashboard"><span>投研首页</span><span class="tag">P0</span></button>
        <button data-view="workspace"><span>投研空间</span><span class="tag">P1</span></button>
        <button data-view="stockpool"><span>股票池管理</span><span class="tag">P1</span></button>
        <button data-view="datasources"><span>数据源管理</span><span class="tag">P1</span></button>
        <button data-view="ingestion"><span>采集任务</span><span class="tag">P1</span></button>
        <button data-view="manual"><span>手动导入</span><span class="tag">P1</span></button>
        <button data-view="documents"><span>文档处理中心</span><span class="tag">P0.8</span></button>
        <button data-view="evidence"><span>证据库</span><span class="tag">P0.6</span></button>
        <button data-view="facts"><span>财务事实中心</span><span class="tag">P1</span></button>
        <button data-view="signals"><span>投资线索</span><span class="tag">P2</span></button>
        <button data-view="tasks"><span>研报任务</span><span class="tag">P0</span></button>
        <button data-view="claims"><span>Claim 复核</span><span class="tag">P0.7</span></button>
        <button data-view="dictionary"><span>金融词典</span><span class="tag">P1</span></button>
        <button data-view="promptops"><span>PromptOps</span><span class="tag">P1</span></button>
        <button data-view="entities"><span>实体库</span><span class="tag">P2</span></button>
        <button data-view="graph"><span>关系图谱</span><span class="tag">P2</span></button>
        <button data-view="evaluation"><span>评测中心</span><span class="tag">P3</span></button>
        <button data-view="export"><span>导出中心</span><span class="tag">P0.9</span></button>
      </nav>
    </aside>

    <section class="main">
      <header class="topbar">
        <div class="title">
          <h1 id="viewTitle">投研首页</h1>
          <div class="sub" id="viewSubtitle">任务、证据、Claim 与处理漏斗</div>
        </div>
        <div class="top-actions">
          <select class="select" aria-label="Workspace">
            <option>Default Research Space</option>
          </select>
          <button class="btn" id="refreshView">Refresh</button>
        </div>
      </header>

      <main class="content">
        <section id="dashboard" class="view active">
          <section class="grid cards" id="metricCards"></section>
          <section class="grid dashboard-layout">
            <div class="panel">
              <div class="panel-head">
                <h2>Processing Funnel</h2>
                <button class="btn" data-jump="documents">Failed Steps</button>
              </div>
              <div class="funnel" id="funnel"></div>
            </div>
            <div class="grid">
              <div class="panel">
                <div class="panel-head">
                  <h2>Task Status</h2>
                  <button class="btn" data-jump="tasks">Open Tasks</button>
                </div>
                <div class="dist" id="taskStatus"></div>
              </div>
              <div class="panel">
                <div class="panel-head">
                  <h2>Data Sources</h2>
                  <button class="btn" data-jump="datasources">Sources</button>
                </div>
                <div class="dist" id="dataSources"></div>
              </div>
              <div class="panel">
                <div class="panel-head">
                  <h2>Review Queue</h2>
                  <button class="btn" data-jump="claims">Claims</button>
                </div>
                <div class="dist" id="reviewQueue"></div>
              </div>
            </div>
          </section>
        </section>

        <section id="tasks" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">Report Tasks</h2>
                <div class="filters">
                  <input id="symbolFilter" placeholder="Filter symbol, e.g. NVDA" />
                  <button class="btn" id="refreshTasks">Refresh</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Task</th>
                      <th>Company</th>
                      <th>Status</th>
                      <th>Stage</th>
                      <th>Created</th>
                      <th>Artifacts</th>
                    </tr>
                  </thead>
                  <tbody id="taskRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="taskDetail">
              <h2>Task Detail</h2>
              <div class="empty">Select a task to inspect timeline and artifacts.</div>
            </aside>
          </div>
        </section>

        <section id="evidence" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">Evidence Center</h2>
                <div class="filters">
                  <input id="evidenceQuery" placeholder="Search evidence" />
                  <input id="evidenceTask" placeholder="task_id" />
                  <select id="evidenceSource">
                    <option value="">All sources</option>
                    <option value="sec_edgar">SEC EDGAR</option>
                    <option value="cninfo">CNINFO</option>
                    <option value="hkex">HKEX</option>
                    <option value="eastmoney">EastMoney</option>
                    <option value="yahoo_finance">Yahoo</option>
                    <option value="news">News</option>
                  </select>
                  <select id="evidenceTrust">
                    <option value="">All trust</option>
                    <option value="official">Official</option>
                    <option value="primary">Primary</option>
                    <option value="secondary">Secondary</option>
                  </select>
                  <button class="btn" id="refreshEvidence">Refresh</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Evidence</th>
                      <th>Source</th>
                      <th>Trust</th>
                      <th>Document</th>
                      <th>Claims</th>
                    </tr>
                  </thead>
                  <tbody id="evidenceRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="evidenceDetail">
              <h2>Evidence Detail</h2>
              <div class="empty">Select evidence to inspect source text and linked claims.</div>
            </aside>
          </div>
        </section>

        <section id="documents" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">Document Processing Center</h2>
                <div class="filters">
                  <input id="documentQuery" placeholder="Search documents" />
                  <input id="documentBatch" placeholder="batch_id" />
                  <select id="documentStep">
                    <option value="">All steps</option>
                    <option value="ingest">Ingest</option>
                    <option value="parse">Parse</option>
                    <option value="table_extract">Table extract</option>
                    <option value="chunk">Chunk</option>
                    <option value="evidence">Evidence</option>
                    <option value="claim_bind">Claim bind</option>
                    <option value="verify">Verify</option>
                  </select>
                  <button class="btn" id="refreshDocuments">Refresh</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Batch</th>
                      <th>Status</th>
                      <th>Latest Step</th>
                      <th>Evidence</th>
                      <th>Claims</th>
                    </tr>
                  </thead>
                  <tbody id="documentRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="documentDetail">
              <h2>Processing Path</h2>
              <div class="empty">Select a document to inspect processing steps and linked evidence.</div>
            </aside>
          </div>
        </section>

        <section id="claims" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">Claim Review</h2>
                <div class="filters">
                  <input id="claimQuery" placeholder="Search claims" />
                  <input id="claimTask" placeholder="task_id" />
                  <select id="claimStatus">
                    <option value="">All review status</option>
                    <option value="pending">Pending</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                    <option value="regenerate_requested">Regenerate requested</option>
                  </select>
                  <select id="claimVerification">
                    <option value="">All verification</option>
                    <option value="supported">Supported</option>
                    <option value="failed">Failed</option>
                    <option value="pending">Pending</option>
                  </select>
                  <button class="btn" id="refreshClaims">Refresh</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Claim</th>
                      <th>Task</th>
                      <th>Review</th>
                      <th>Verification</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody id="claimRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="claimDetail">
              <h2>Claim Detail</h2>
              <div class="empty">Select a claim to review evidence, checks, and audit trail.</div>
            </aside>
          </div>
        </section>

        <section id="export" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">Export Center</h2>
                <div class="filters">
                  <input id="exportSymbol" placeholder="Filter symbol" />
                  <select id="exportStatus">
                    <option value="">All task status</option>
                    <option value="completed">Completed</option>
                    <option value="failed">Failed</option>
                    <option value="running">Running</option>
                    <option value="queued">Queued</option>
                  </select>
                  <button class="btn" id="refreshExports">Refresh</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Task</th>
                      <th>Status</th>
                      <th>Artifacts</th>
                      <th>Review</th>
                      <th>Official Export</th>
                    </tr>
                  </thead>
                  <tbody id="exportRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="exportDetail">
              <h2>Artifact Review</h2>
              <div class="empty">Select a task to inspect artifacts and export readiness.</div>
            </aside>
          </div>
        </section>

        <section id="workspace" class="view"></section>
        <section id="stockpool" class="view"></section>
        <section id="datasources" class="view"></section>
        <section id="ingestion" class="view"></section>
        <section id="manual" class="view"></section>
        <section id="facts" class="view"></section>
        <section id="signals" class="view"></section>
        <section id="dictionary" class="view"></section>
        <section id="promptops" class="view"></section>
        <section id="entities" class="view"></section>
        <section id="graph" class="view"></section>
        <section id="evaluation" class="view"></section>
      </main>
    </section>
  </div>

  <script>
    "use strict";
    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (m) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[m]));
    const fmt = (v) => v == null || v === "" ? "-" : String(v);
    const number = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString() : "0";
    const pct = (v) => Math.round((Number(v) || 0) * 100) + "%";
    const activeState = { view: "dashboard" };

    const viewMeta = {
      dashboard: ["投研首页", "任务、证据、Claim 与处理漏斗"],
      workspace: ["投研空间", "P1 接入 workspace 配置后启用"],
      stockpool: ["股票池管理", "P1 接入 workspace companies 后启用"],
      datasources: ["数据源管理", "P1 接入 data_sources 后启用"],
      ingestion: ["采集任务", "P1 接入 ingestion batches 后启用"],
      manual: ["手动导入", "P1 接入 manual import 后启用"],
      documents: ["文档处理中心", "P0.8 接入 document processing steps 后启用"],
      evidence: ["证据库", "Evidence、Document、Claim 关联查询"],
      facts: ["财务事实中心", "P1 接入 financial_facts 后启用"],
      signals: ["投资线索", "P2 接入 investment signals 后启用"],
      tasks: ["研报任务", "按 task_id 跟踪研报生成和 artifacts"],
      claims: ["Claim 复核", "P0.7 接入 review workflow 后启用"],
      dictionary: ["金融词典", "P1 接入 dictionary terms 后启用"],
      promptops: ["PromptOps", "P1 接入 Harness 和 prompt_versions 后启用"],
      entities: ["实体库", "P2 接入 entities 后启用"],
      graph: ["关系图谱", "P2 接入 entity relations 后启用"],
      evaluation: ["评测中心", "P3 接入 eval runs 后启用"],
      export: ["导出中心", "P0.9 接入 artifact review 后启用"],
    };

    document.querySelectorAll(".nav button").forEach((btn) => {
      btn.addEventListener("click", () => activateView(btn.dataset.view));
    });
    document.querySelectorAll("[data-jump]").forEach((btn) => {
      btn.addEventListener("click", () => activateView(btn.dataset.jump));
    });

    function activateView(view) {
      activeState.view = view;
      document.querySelectorAll(".nav button").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
      document.querySelectorAll(".view").forEach((item) => item.classList.toggle("active", item.id === view));
      const meta = viewMeta[view] || [view, ""];
      $("viewTitle").textContent = meta[0];
      $("viewSubtitle").textContent = meta[1];
      if (view === "dashboard") loadDashboard();
      else if (view === "tasks") loadTasks();
      else if (view === "evidence") loadEvidence();
      else if (view === "documents") loadDocuments();
      else if (view === "claims") loadClaims();
      else if (view === "export") loadExports();
      else renderPlaceholder(view);
    }

    async function getJson(url) {
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || JSON.stringify(data));
      return data;
    }

    function renderCards(summary) {
      const cards = [
        ["Companies", summary.company_count],
        ["Documents", summary.document_count],
        ["Evidence", summary.evidence_count],
        ["Claims", summary.claim_count],
        ["Pending Review", summary.review_pending_claim_count],
        ["Verified Claims", summary.verified_claim_count],
        ["Quality Pass Rate", pct(summary.quality_pass_rate)],
        ["Avg Quality", summary.average_quality_score ?? "-"],
      ];
      $("metricCards").innerHTML = cards.map(([label, value]) => `<div class="card"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`).join("");
    }

    function renderDistribution(id, values) {
      const entries = Object.entries(values || {}).sort((a, b) => b[1] - a[1]);
      $(id).innerHTML = entries.length
        ? entries.map(([key, value]) => `<div class="dist-row"><span>${esc(key)}</span><strong>${esc(number(value))}</strong></div>`).join("")
        : `<div class="empty">No data</div>`;
    }

    function renderFunnel(payload) {
      const steps = payload.steps || [];
      const max = Math.max(1, ...steps.map((step) => Number(step.count || 0)));
      $("funnel").innerHTML = steps.length
        ? steps.map((step) => {
            const width = Math.max(2, Math.round((Number(step.count || 0) / max) * 100));
            return `<div class="funnel-row"><span>${esc(step.label)}</span><div class="bar"><span style="width:${width}%"></span></div><strong>${esc(number(step.count))}</strong></div>`;
          }).join("")
        : `<div class="empty">No funnel data</div>`;
    }

    function renderReviewQueue(summary) {
      $("reviewQueue").innerHTML = [
        ["Pending Claims", summary.review_pending_claim_count],
        ["Verified Claims", summary.verified_claim_count],
        ["All Claims", summary.claim_count],
      ].map(([key, value]) => `<div class="dist-row"><span>${esc(key)}</span><strong>${esc(number(value))}</strong></div>`).join("");
    }

    function artifactButtons(task) {
      const links = task.report_links || {};
      const buttons = [];
      if (links.html_web_url) buttons.push(`<a class="btn primary" href="${esc(links.html_web_url)}" target="_blank">HTML</a>`);
      if (links.markdown_web_url) buttons.push(`<a class="btn" href="${esc(links.markdown_web_url)}" target="_blank">MD</a>`);
      if (links.json_web_url) buttons.push(`<a class="btn" href="${esc(links.json_web_url)}" target="_blank">JSON</a>`);
      buttons.push(`<a class="btn" href="/api/report-tasks/${encodeURIComponent(task.task_id)}/artifacts" target="_blank">Artifacts</a>`);
      return `<div class="links">${buttons.join("")}</div>`;
    }

    async function loadDashboard() {
      try {
        const [summary, funnel] = await Promise.all([
          getJson("/api/dashboard/summary"),
          getJson("/api/dashboard/funnel"),
        ]);
        renderCards(summary);
        renderDistribution("taskStatus", summary.report_task_status_distribution);
        renderDistribution("dataSources", summary.data_source_distribution);
        renderReviewQueue(summary);
        renderFunnel(funnel);
      } catch (error) {
        $("metricCards").innerHTML = `<div class="error">${esc(error.message)}</div>`;
      }
    }

    async function loadTasks() {
      const symbol = $("symbolFilter").value.trim();
      const suffix = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
      try {
        const payload = await getJson("/api/report-tasks" + suffix);
        const rows = payload.items || [];
        $("taskRows").innerHTML = rows.length
          ? rows.map((task) => `<tr data-selectable="true" data-task-id="${esc(task.task_id)}">
              <td><button class="btn" data-task-detail="${esc(task.task_id)}">${esc(task.task_id)}</button></td>
              <td>${esc(task.symbol)}<br><span class="label">${esc(task.period)}</span></td>
              <td><span class="status ${esc(task.status)}">${esc(task.status)}</span></td>
              <td>${esc(fmt(task.current_stage))}</td>
              <td>${esc(fmt(task.created_at))}</td>
              <td>${artifactButtons(task)}</td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">No report tasks</div></td></tr>`;
        document.querySelectorAll("[data-task-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadTaskDetail(btn.dataset.taskDetail));
        });
      } catch (error) {
        $("taskRows").innerHTML = `<tr><td colspan="6"><div class="error">${esc(error.message)}</div></td></tr>`;
      }
    }

    async function loadTaskDetail(taskId) {
      try {
        const task = await getJson(`/api/report-tasks/${encodeURIComponent(taskId)}`);
        const events = task.events || [];
        $("taskDetail").innerHTML = `<h2>Task Detail</h2>
          <div class="kv"><span class="label">Task</span><span class="mono">${esc(task.task_id)}</span></div>
          <div class="kv"><span class="label">Symbol</span><span>${esc(task.symbol)} / ${esc(task.period)}</span></div>
          <div class="kv"><span class="label">Status</span><span><span class="status ${esc(task.status)}">${esc(task.status)}</span></span></div>
          <div class="kv"><span class="label">Stage</span><span>${esc(fmt(task.current_stage))}</span></div>
          <div class="kv"><span class="label">Quality</span><span>${esc(fmt(task.quality_score))}</span></div>
          ${task.error_message ? `<div class="detail-section"><h3>Error</h3><div class="text-block">${esc(task.error_message)}</div></div>` : ""}
          <div class="detail-section"><h3>Artifacts</h3>${artifactButtons(task)}</div>
          <div class="detail-section"><h3>Timeline</h3><div class="timeline">${
            events.length ? events.map((event) => `<div class="event"><strong>${esc(event.stage)}</strong> <span class="status ${esc(event.status)}">${esc(event.status)}</span><br><span class="label">${esc(fmt(event.created_at))}</span><br>${esc(fmt(event.message))}</div>`).join("") : `<div class="empty">No events</div>`
          }</div></div>`;
      } catch (error) {
        $("taskDetail").innerHTML = `<h2>Task Detail</h2><div class="error">${esc(error.message)}</div>`;
      }
    }

    async function loadEvidence() {
      const params = new URLSearchParams();
      const q = $("evidenceQuery").value.trim();
      const taskId = $("evidenceTask").value.trim();
      const source = $("evidenceSource").value;
      const trust = $("evidenceTrust").value;
      if (q) params.set("q", q);
      if (taskId) params.set("task_id", taskId);
      if (source) params.set("source_type", source);
      if (trust) params.set("trust_level", trust);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/evidence" + suffix);
        const rows = payload.items || [];
        $("evidenceRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-evidence-detail="${esc(item.evidence_id)}">${esc(item.title || item.evidence_id)}</button><br><span class="label mono">${esc(item.evidence_id)}</span><br>${esc(item.snippet || "")}</td>
              <td>${esc(fmt(item.source_type))}<br><span class="label">${esc(fmt(item.source_url))}</span></td>
              <td><span class="status ${esc(item.trust_level)}">${esc(fmt(item.trust_level))}</span></td>
              <td>${esc(item.document?.title || "-")}<br><span class="label">${esc(item.document?.report_period || "")}</span></td>
              <td>${esc(number(item.claim_count))}</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">No evidence</div></td></tr>`;
        document.querySelectorAll("[data-evidence-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadEvidenceDetail(btn.dataset.evidenceDetail));
        });
      } catch (error) {
        $("evidenceRows").innerHTML = `<tr><td colspan="5"><div class="error">${esc(error.message)}</div></td></tr>`;
      }
    }

    async function loadEvidenceDetail(evidenceId) {
      try {
        const item = await getJson(`/api/evidence/${encodeURIComponent(evidenceId)}`);
        const claims = item.claims || [];
        $("evidenceDetail").innerHTML = `<h2>Evidence Detail</h2>
          <div class="kv"><span class="label">Evidence</span><span class="mono">${esc(item.evidence_id)}</span></div>
          <div class="kv"><span class="label">Source</span><span>${esc(fmt(item.source_type))}</span></div>
          <div class="kv"><span class="label">Trust</span><span><span class="status ${esc(item.trust_level)}">${esc(fmt(item.trust_level))}</span></span></div>
          <div class="kv"><span class="label">Page</span><span>${esc(fmt(item.page_no))}</span></div>
          <div class="kv"><span class="label">Document</span><span>${esc(item.document?.title || "-")}</span></div>
          ${item.source_url ? `<div class="kv"><span class="label">URL</span><a href="${esc(item.source_url)}" target="_blank">${esc(item.source_url)}</a></div>` : ""}
          <div class="detail-section"><h3>Source Text</h3><div class="text-block">${esc(item.content || item.snippet || "")}</div></div>
          <div class="detail-section"><h3>Linked Claims</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>${esc(claim.section_name || claim.claim_type || "Claim")}</strong> <span class="status ${esc(claim.review_status)}">${esc(claim.review_status)}</span><br>${esc(claim.claim_text)}<br><span class="label mono">${esc(claim.task_id)}</span></div>`).join("") : `<div class="empty">No linked claims</div>`
          }</div>`;
      } catch (error) {
        $("evidenceDetail").innerHTML = `<h2>Evidence Detail</h2><div class="error">${esc(error.message)}</div>`;
      }
    }

    async function loadClaims() {
      const params = new URLSearchParams();
      const q = $("claimQuery").value.trim();
      const taskId = $("claimTask").value.trim();
      const status = $("claimStatus").value;
      const verification = $("claimVerification").value;
      if (q) params.set("q", q);
      if (taskId) params.set("task_id", taskId);
      if (status) params.set("status", status);
      if (verification) params.set("verification_status", verification);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/claims" + suffix);
        const rows = payload.items || [];
        $("claimRows").innerHTML = rows.length
          ? rows.map((claim) => `<tr data-selectable="true">
              <td><button class="btn" data-claim-detail="${esc(claim.id)}">#${esc(claim.id)}</button> ${esc(claim.section_name || claim.claim_type || "Claim")}<br>${esc(claim.claim_text)}</td>
              <td><span class="mono">${esc(claim.task_id)}</span></td>
              <td><span class="status ${esc(claim.review_status)}">${esc(claim.review_status)}</span></td>
              <td><span class="status ${esc(claim.verification_status)}">${esc(claim.verification_status)}</span><br><span class="label">num ${esc(fmt(claim.numeric_check_status))} / cite ${esc(fmt(claim.citation_check_status))}</span></td>
              <td>${esc(number(claim.evidence_count))}</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">No claims</div></td></tr>`;
        document.querySelectorAll("[data-claim-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadClaimDetail(btn.dataset.claimDetail));
        });
      } catch (error) {
        $("claimRows").innerHTML = `<tr><td colspan="5"><div class="error">${esc(error.message)}</div></td></tr>`;
      }
    }

    async function loadDocuments() {
      const params = new URLSearchParams();
      const q = $("documentQuery").value.trim();
      const batch = $("documentBatch").value.trim();
      const step = $("documentStep").value;
      if (q) params.set("q", q);
      if (batch) params.set("batch_id", batch);
      if (step) params.set("step", step);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/documents" + suffix);
        const rows = payload.items || [];
        $("documentRows").innerHTML = rows.length
          ? rows.map((doc) => `<tr data-selectable="true">
              <td><button class="btn" data-document-detail="${esc(doc.id)}">${esc(doc.title)}</button><br><span class="label">${esc(doc.doc_type || "-")} · ${esc(doc.report_period || "-")}</span></td>
              <td><span class="mono">${esc(fmt(doc.batch_id))}</span></td>
              <td><span class="status ${esc(doc.parse_status)}">${esc(doc.parse_status)}</span><br><span class="label">${esc(number(doc.failed_step_count))} failed</span></td>
              <td>${esc(doc.latest_step?.step_name || "-")}<br><span class="status ${esc(doc.latest_step?.status || "")}">${esc(doc.latest_step?.status || "-")}</span></td>
              <td>${esc(number(doc.evidence_count))}</td>
              <td>${esc(number(doc.claim_count))}</td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">No documents</div></td></tr>`;
        document.querySelectorAll("[data-document-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadDocumentDetail(btn.dataset.documentDetail));
        });
      } catch (error) {
        $("documentRows").innerHTML = `<tr><td colspan="6"><div class="error">${esc(error.message)}</div></td></tr>`;
      }
    }

    async function loadDocumentDetail(documentId) {
      try {
        const doc = await getJson(`/api/documents/${encodeURIComponent(documentId)}`);
        const steps = doc.processing_steps || [];
        const evidence = doc.evidence || [];
        const claims = doc.claims || [];
        $("documentDetail").innerHTML = `<h2>Processing Path</h2>
          <div class="kv"><span class="label">Document</span><span>${esc(doc.title)}</span></div>
          <div class="kv"><span class="label">Batch</span><span class="mono">${esc(fmt(doc.batch_id))}</span></div>
          <div class="kv"><span class="label">Status</span><span><span class="status ${esc(doc.parse_status)}">${esc(doc.parse_status)}</span></span></div>
          ${doc.source_url ? `<div class="kv"><span class="label">URL</span><a href="${esc(doc.source_url)}" target="_blank">${esc(doc.source_url)}</a></div>` : ""}
          ${doc.file_path ? `<div class="kv"><span class="label">File</span><span class="mono">${esc(doc.file_path)}</span></div>` : ""}
          <div class="detail-section"><h3>Steps</h3><div class="timeline">${
            steps.length ? steps.map((step) => `<div class="event"><strong>${esc(step.step_name)}</strong> <span class="status ${esc(step.status)}">${esc(step.status)}</span><br><span class="label">${esc(fmt(step.started_at))} - ${esc(fmt(step.finished_at))}</span>${step.error_message ? `<div class="text-block">${esc(step.error_message)}</div>` : ""}<br><span class="label mono">${esc(JSON.stringify(step.metadata || {}))}</span></div>`).join("") : `<div class="empty">No processing steps</div>`
          }</div></div>
          <div class="detail-section"><h3>Evidence</h3>${
            evidence.length ? evidence.map((item) => `<div class="event"><strong>${esc(item.title || item.evidence_id)}</strong> <span class="status ${esc(item.trust_level)}">${esc(fmt(item.trust_level))}</span><br>${esc(item.snippet || "")}</div>`).join("") : `<div class="empty">No evidence</div>`
          }</div>
          <div class="detail-section"><h3>Claims</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>#${esc(claim.id)}</strong> <span class="status ${esc(claim.review_status)}">${esc(claim.review_status)}</span><br>${esc(claim.claim_text)}<br><span class="label mono">${esc(claim.task_id)}</span></div>`).join("") : `<div class="empty">No claims</div>`
          }</div>`;
      } catch (error) {
        $("documentDetail").innerHTML = `<h2>Processing Path</h2><div class="error">${esc(error.message)}</div>`;
      }
    }

    async function loadClaimDetail(claimId) {
      try {
        const claim = await getJson(`/api/claims/${encodeURIComponent(claimId)}`);
        renderClaimDetail(claim);
      } catch (error) {
        $("claimDetail").innerHTML = `<h2>Claim Detail</h2><div class="error">${esc(error.message)}</div>`;
      }
    }

    async function loadExports() {
      const params = new URLSearchParams();
      const symbol = $("exportSymbol").value.trim();
      const status = $("exportStatus").value;
      if (symbol) params.set("symbol", symbol);
      if (status) params.set("status", status);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/exports" + suffix);
        const rows = payload.items || [];
        $("exportRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-export-detail="${esc(item.task_id)}">${esc(item.task_id)}</button><br><span class="label">${esc(item.symbol)} · ${esc(item.period)}</span></td>
              <td><span class="status ${esc(item.status)}">${esc(item.status)}</span></td>
              <td>${esc(number(item.artifact_count))}</td>
              <td><span class="status approved">${esc(number(item.approved_claim_count))} approved</span><br><span class="status pending">${esc(number(item.pending_claim_count))} pending</span><br><span class="status rejected">${esc(number(item.rejected_claim_count))} rejected</span></td>
              <td>${item.official_export_ready ? `<span class="status completed">Ready</span>` : `<span class="status failed">Blocked</span>`}</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">No export entries</div></td></tr>`;
        document.querySelectorAll("[data-export-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadExportDetail(btn.dataset.exportDetail));
        });
      } catch (error) {
        $("exportRows").innerHTML = `<tr><td colspan="5"><div class="error">${esc(error.message)}</div></td></tr>`;
      }
    }

    async function loadExportDetail(taskId) {
      try {
        const item = await getJson(`/api/exports/${encodeURIComponent(taskId)}`);
        const artifacts = item.artifacts || [];
        const claims = item.claims || [];
        $("exportDetail").innerHTML = `<h2>Artifact Review</h2>
          <div class="kv"><span class="label">Task</span><span class="mono">${esc(item.task_id)}</span></div>
          <div class="kv"><span class="label">Symbol</span><span>${esc(item.symbol)} / ${esc(item.period)}</span></div>
          <div class="kv"><span class="label">Official Export</span><span>${item.official_export_ready ? `<span class="status completed">Ready</span>` : `<span class="status failed">Blocked</span>`}</span></div>
          <div class="kv"><span class="label">Review</span><span>${esc(number(item.approved_claim_count))} approved · ${esc(number(item.pending_claim_count))} pending · ${esc(number(item.rejected_claim_count))} rejected</span></div>
          <div class="detail-section"><h3>Blocked Reasons</h3>${
            (item.blocked_reasons || []).length ? `<div class="text-block">${esc((item.blocked_reasons || []).join("\\n"))}</div>` : `<div class="empty">No blockers</div>`
          }</div>
          <div class="detail-section"><h3>Artifacts</h3>${
            artifacts.length ? artifacts.map((artifact) => `<div class="event"><strong>${esc(artifact.artifact_type)}</strong><br>${artifact.url ? `<a href="${esc(artifact.url)}" target="_blank">${esc(artifact.url)}</a>` : `<span class="mono">${esc(fmt(artifact.path))}</span>`}</div>`).join("") : `<div class="empty">No artifacts</div>`
          }</div>
          <div class="detail-section"><h3>Claims</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>#${esc(claim.id)}</strong> <span class="status ${esc(claim.review_status)}">${esc(claim.review_status)}</span><br>${esc(claim.claim_text)}</div>`).join("") : `<div class="empty">No claims</div>`
          }</div>
          <div class="detail-section"><h3>Note</h3><div class="empty">${esc(item.formal_export_note || "")}</div></div>`;
      } catch (error) {
        $("exportDetail").innerHTML = `<h2>Artifact Review</h2><div class="error">${esc(error.message)}</div>`;
      }
    }

    function renderClaimDetail(claim) {
      const evidence = claim.evidence || [];
      const records = claim.review_records || [];
      $("claimDetail").innerHTML = `<h2>Claim Detail</h2>
        <div class="kv"><span class="label">Claim</span><span class="mono">#${esc(claim.id)}</span></div>
        <div class="kv"><span class="label">Task</span><span class="mono">${esc(claim.task_id)}</span></div>
        <div class="kv"><span class="label">Review</span><span><span class="status ${esc(claim.review_status)}">${esc(claim.review_status)}</span></span></div>
        <div class="kv"><span class="label">Verify</span><span><span class="status ${esc(claim.verification_status)}">${esc(claim.verification_status)}</span></span></div>
        <div class="detail-section"><h3>Claim Text</h3><textarea id="claimEditText" style="width:100%;min-height:96px">${esc(claim.claim_text)}</textarea></div>
        <div class="links" style="margin-top:10px">
          <button class="btn primary" data-claim-action="approve" data-claim-id="${esc(claim.id)}">Approve</button>
          <button class="btn danger" data-claim-action="reject" data-claim-id="${esc(claim.id)}">Reject</button>
          <button class="btn" data-claim-action="edit" data-claim-id="${esc(claim.id)}">Save Edit</button>
          <button class="btn" data-claim-action="regenerate" data-claim-id="${esc(claim.id)}">Regenerate</button>
        </div>
        <div class="detail-section"><h3>Evidence</h3>${
          evidence.length ? evidence.map((item) => `<div class="event"><strong>${esc(item.title || item.evidence_id)}</strong> <span class="status ${esc(item.trust_level)}">${esc(fmt(item.trust_level))}</span><br>${esc(item.snippet || "")}<br><span class="label">${esc(fmt(item.source_type))} · page ${esc(fmt(item.page_no))}</span></div>`).join("") : `<div class="empty">No linked evidence</div>`
        }</div>
        <div class="detail-section"><h3>Audit Trail</h3>${
          records.length ? records.map((record) => `<div class="event"><strong>${esc(record.decision)}</strong> <span class="label">${esc(fmt(record.created_at))}</span><br>${esc(fmt(record.comment))}<br><span class="label">${esc(fmt(record.reviewer))}</span></div>`).join("") : `<div class="empty">No review records</div>`
        }</div>`;
      document.querySelectorAll("[data-claim-action]").forEach((btn) => {
        btn.addEventListener("click", () => claimAction(btn.dataset.claimId, btn.dataset.claimAction));
      });
    }

    async function claimAction(claimId, action) {
      const payload = { reviewer: "workbench" };
      if (action === "edit") {
        payload.claim_text = $("claimEditText").value;
        payload.comment = "Edited from workbench";
      } else {
        payload.comment = action + " from workbench";
      }
      try {
        const updated = await postJson(`/api/claims/${encodeURIComponent(claimId)}/${encodeURIComponent(action)}`, payload);
        renderClaimDetail(updated);
        loadClaims();
      } catch (error) {
        $("claimDetail").insertAdjacentHTML("afterbegin", `<div class="error">${esc(error.message)}</div>`);
      }
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || JSON.stringify(data));
      return data;
    }

    function renderPlaceholder(view) {
      const meta = viewMeta[view] || [view, "待接入"];
      const target = $(view);
      if (!target || target.dataset.rendered === "true") return;
      target.dataset.rendered = "true";
      target.innerHTML = `<div class="grid placeholder-grid">
        <div class="panel placeholder">
          <h2>${esc(meta[0])}</h2>
          <div class="empty">${esc(meta[1])}</div>
        </div>
        <div class="panel placeholder">
          <h2>Data Contract</h2>
          <div class="empty">Waiting for the planned API and DB tables.</div>
        </div>
        <div class="panel placeholder">
          <h2>Traceability</h2>
          <div class="empty">This section will link back to stable task, document, evidence, claim, or artifact IDs.</div>
        </div>
      </div>`;
    }

    $("refreshView").addEventListener("click", () => activateView(activeState.view));
    $("refreshTasks").addEventListener("click", loadTasks);
    $("symbolFilter").addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadTasks();
    });
    $("refreshEvidence").addEventListener("click", loadEvidence);
    ["evidenceQuery", "evidenceTask"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => {
        if (event.key === "Enter") loadEvidence();
      });
    });
    $("evidenceSource").addEventListener("change", loadEvidence);
    $("evidenceTrust").addEventListener("change", loadEvidence);
    $("refreshDocuments").addEventListener("click", loadDocuments);
    ["documentQuery", "documentBatch"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => {
        if (event.key === "Enter") loadDocuments();
      });
    });
    $("documentStep").addEventListener("change", loadDocuments);
    $("refreshClaims").addEventListener("click", loadClaims);
    ["claimQuery", "claimTask"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => {
        if (event.key === "Enter") loadClaims();
      });
    });
    $("claimStatus").addEventListener("change", loadClaims);
    $("claimVerification").addEventListener("change", loadClaims);
    $("refreshExports").addEventListener("click", loadExports);
    $("exportSymbol").addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadExports();
    });
    $("exportStatus").addEventListener("change", loadExports);

    loadDashboard();
    loadTasks();
  </script>
</body>
</html>"""
