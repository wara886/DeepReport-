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
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-2: #f0f3f6;
      --text: #17202a;
      --muted: #667085;
      --line: #d8dee8;
      --accent: #1677ff;
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
    .shell { max-width: 1240px; margin: 0 auto; padding: 24px; }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }
    h1 { margin: 0; font-size: 24px; font-weight: 700; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
    .tabs { display: inline-flex; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 3px; }
    .tab {
      border: 0;
      background: transparent;
      color: var(--muted);
      padding: 8px 12px;
      border-radius: 6px;
      cursor: pointer;
      font: inherit;
      font-size: 14px;
    }
    .tab.active { background: var(--accent); color: white; }
    .view { display: none; }
    .view.active { display: block; }
    .grid { display: grid; gap: 14px; }
    .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 14px; }
    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .card { padding: 14px; min-height: 96px; }
    .label { color: var(--muted); font-size: 12px; }
    .value { font-size: 28px; font-weight: 700; margin-top: 8px; }
    .panel { padding: 16px; }
    .panel h2 { margin: 0 0 12px; font-size: 16px; }
    .dashboard-layout { grid-template-columns: 1.2fr 0.8fr; align-items: start; }
    .funnel { display: grid; gap: 8px; }
    .funnel-row {
      display: grid;
      grid-template-columns: 148px 1fr 56px;
      align-items: center;
      gap: 10px;
      font-size: 13px;
    }
    .bar { height: 10px; background: var(--panel-2); border-radius: 999px; overflow: hidden; }
    .bar span { display: block; height: 100%; background: var(--accent); min-width: 2px; }
    .split { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .dist { display: grid; gap: 8px; }
    .dist-row { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; border-bottom: 1px solid var(--line); padding-bottom: 7px; }
    .toolbar { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 12px; }
    .toolbar input {
      width: 240px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
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
      gap: 6px;
      white-space: nowrap;
    }
    .btn.primary { background: var(--accent); border-color: var(--accent); color: white; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; border-bottom: 1px solid var(--line); padding: 10px 8px; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; background: #fbfcfd; }
    .status { display: inline-block; border-radius: 999px; padding: 3px 8px; font-size: 12px; background: var(--panel-2); }
    .status.completed { color: var(--good); background: #e9f7ef; }
    .status.failed { color: var(--bad); background: #fff0ed; }
    .status.running, .status.queued { color: var(--warn); background: #fff6e6; }
    .links { display: flex; gap: 6px; flex-wrap: wrap; }
    .empty, .error { color: var(--muted); font-size: 13px; padding: 18px; text-align: center; }
    .error { color: var(--bad); }
    @media (max-width: 860px) {
      .shell { padding: 16px; }
      header { align-items: flex-start; flex-direction: column; }
      .cards, .dashboard-layout, .split { grid-template-columns: 1fr; }
      .toolbar { align-items: stretch; flex-direction: column; }
      .toolbar input { width: 100%; }
      table { min-width: 760px; }
      .table-scroll { overflow-x: auto; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>FinSight Research Workbench</h1>
        <div class="sub">Dashboard · Report Tasks · Evidence-backed artifacts</div>
      </div>
      <nav class="tabs" aria-label="Workbench views">
        <button class="tab active" data-view="dashboard">Dashboard</button>
        <button class="tab" data-view="tasks">Report Tasks</button>
      </nav>
    </header>

    <main id="dashboard" class="view active">
      <section class="grid cards" id="metricCards"></section>
      <section class="grid dashboard-layout">
        <div class="panel">
          <h2>Processing Funnel</h2>
          <div class="funnel" id="funnel"></div>
        </div>
        <div class="grid">
          <div class="panel">
            <h2>Task Status</h2>
            <div class="dist" id="taskStatus"></div>
          </div>
          <div class="panel">
            <h2>Data Sources</h2>
            <div class="dist" id="dataSources"></div>
          </div>
        </div>
      </section>
    </main>

    <main id="tasks" class="view">
      <section class="panel">
        <div class="toolbar">
          <h2 style="margin:0">Report Tasks</h2>
          <div>
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
    </main>
  </div>
  <script>
    "use strict";
    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (m) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[m]));
    const fmt = (v) => v == null || v === "" ? "-" : String(v);
    const number = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString() : "0";

    document.querySelectorAll(".tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.view).classList.add("active");
      });
    });

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
        ["Quality Pass Rate", Math.round((summary.quality_pass_rate || 0) * 100) + "%"],
        ["Avg Quality", summary.average_quality_score ?? "-"],
      ];
      $("metricCards").innerHTML = cards.map(([label, value]) => `<div class="card"><div class="label">${esc(label)}</div><div class="value">${esc(number(value))}</div></div>`).join("");
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
      $("funnel").innerHTML = steps.map((step) => {
        const width = Math.max(2, Math.round((Number(step.count || 0) / max) * 100));
        return `<div class="funnel-row"><span>${esc(step.label)}</span><div class="bar"><span style="width:${width}%"></span></div><strong>${esc(number(step.count))}</strong></div>`;
      }).join("");
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
          ? rows.map((task) => `<tr>
              <td><a href="/api/report-tasks/${encodeURIComponent(task.task_id)}" target="_blank">${esc(task.task_id)}</a></td>
              <td>${esc(task.symbol)}<br><span class="label">${esc(task.period)}</span></td>
              <td><span class="status ${esc(task.status)}">${esc(task.status)}</span></td>
              <td>${esc(fmt(task.current_stage))}</td>
              <td>${esc(fmt(task.created_at))}</td>
              <td>${artifactButtons(task)}</td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">No report tasks</div></td></tr>`;
      } catch (error) {
        $("taskRows").innerHTML = `<tr><td colspan="6"><div class="error">${esc(error.message)}</div></td></tr>`;
      }
    }

    $("refreshTasks").addEventListener("click", loadTasks);
    $("symbolFilter").addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadTasks();
    });

    loadDashboard();
    loadTasks();
  </script>
</body>
</html>"""
