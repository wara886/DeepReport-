"""P0 投研工作台静态页面。"""

from __future__ import annotations


def render_workbench_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>慧研投研工作台</title>
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
    .app { min-height: 100vh; display: grid; grid-template-columns: 236px minmax(0, 1fr); }
    .sidebar {
      background: var(--nav);
      color: #d7e0ea;
      padding: 18px 12px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
    }
    .brand { padding: 10px 10px 18px; border-bottom: 1px solid rgba(255,255,255,.1); margin-bottom: 10px; }
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
    .nav .tag { border-radius: 999px; color: #9fb3c7; font-size: 11px; padding: 2px 7px; background: rgba(255,255,255,.06); }
    .nav .tag.available { color: #bcebd1; background: rgba(22,128,60,.18); }
    .nav .tag.preview { color: #cce0ff; background: rgba(22,119,255,.18); }
    .nav .tag.planned { color: #d3dee8; background: rgba(146,164,183,.16); }
    .nav .tag.enhancing { color: #ffe0a8; background: rgba(181,106,0,.18); }
    .main { min-width: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); }
    .topbar {
      min-height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 12px 22px;
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
    .btn.ghost { background: #f7f9fb; }
    .btn.danger { color: var(--bad); }
    .content { padding: 18px 22px 28px; min-width: 0; }
    .view { display: none; }
    .view.active { display: block; }
    .grid { display: grid; gap: 14px; }
    .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 14px; }
    .card, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
    .card { padding: 14px; min-height: 92px; }
    button.card { cursor: pointer; font: inherit; text-align: left; color: inherit; }
    button.card:hover { border-color: var(--accent); box-shadow: 0 8px 22px rgba(16,24,32,.08); }
    .metric-card { display: grid; align-content: space-between; width: 100%; }
    .metric-card .label { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
    .metric-card .hint { color: var(--accent); font-size: 12px; }
    .label { color: var(--muted); font-size: 12px; }
    .value { font-size: 26px; font-weight: 700; margin-top: 8px; }
    .panel { padding: 16px; }
    .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .panel h2 { margin: 0; font-size: 16px; }
    .panel h3 { margin: 0 0 8px; font-size: 14px; }
    .dashboard-layout { grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr); align-items: start; }
    .dashboard-charts { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 14px; }
    .dashboard-bottom { margin-top: 14px; }
    .work-layout { grid-template-columns: minmax(0, 1fr) 380px; align-items: start; }
    .tab-switch { display: inline-flex; gap: 4px; padding: 3px; border: 1px solid var(--line); border-radius: 8px; background: #f7f9fb; }
    .tab-switch button { border: 0; border-radius: 6px; background: transparent; color: var(--muted); cursor: pointer; font: inherit; font-size: 13px; padding: 6px 10px; }
    .tab-switch button.active { background: #fff; color: var(--text); box-shadow: 0 1px 4px rgba(16,24,32,.08); }
    .funnel-view { display: none; }
    .funnel-view.active { display: block; }
    .funnel-demo-note { border: 1px solid #f4d39b; background: #fff8ea; color: #8a5300; border-radius: 8px; padding: 10px 12px; font-size: 13px; margin-bottom: 12px; line-height: 1.5; }
    .funnel-visual { display: grid; gap: 8px; margin-bottom: 14px; }
    .funnel-layer {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      align-items: center;
      gap: 12px;
      min-height: 48px;
      margin: 0 auto;
      padding: 0 16px;
      border: 1px solid #b8d5ee;
      background: linear-gradient(90deg, #e9f6ff 0%, #f7fbff 100%);
      border-radius: 10px;
      clip-path: polygon(4% 0, 96% 0, 100% 100%, 0% 100%);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      text-align: left;
      width: 100%;
    }
    .funnel-layer:hover { border-color: var(--accent); background: #eef8ff; }
    .funnel-layer span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
    .funnel-layer strong { font-size: 16px; }
    .funnel-layer .rate { color: var(--muted); min-width: 58px; text-align: right; white-space: nowrap; }
    .funnel-loss-card { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; padding: 12px; margin-top: 12px; display: grid; gap: 7px; font-size: 13px; }
    .funnel-loss-card h3 { margin: 0; font-size: 14px; }
    .funnel-stage {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 92px;
      align-items: center;
      gap: 12px;
      min-height: 42px;
      margin: 0 auto;
      padding: 9px 12px;
      border: 1px solid #cfe2f3;
      background: linear-gradient(90deg, #eef8ff 0%, #f8fbfd 100%);
      border-radius: 8px;
      font-size: 13px;
    }
    .funnel-stage strong { text-align: right; font-size: 15px; }
    .funnel-arrow { color: var(--muted); text-align: center; font-size: 12px; margin-top: -2px; }
    .funnel { display: grid; gap: 8px; }
    .funnel-row { display: grid; grid-template-columns: 150px 1fr 56px; align-items: center; gap: 10px; font-size: 13px; }
    .bar { height: 10px; background: var(--panel-2); border-radius: 999px; overflow: hidden; }
    .bar span { display: block; height: 100%; background: var(--accent-2); min-width: 2px; }
    .dist { display: grid; gap: 8px; }
    .dist-row { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; border-bottom: 1px solid var(--line); padding-bottom: 7px; }
    .chart-card { display: grid; grid-template-columns: 168px minmax(0, 1fr); align-items: center; gap: 16px; }
    .donut {
      width: 148px;
      height: 148px;
      border-radius: 50%;
      background: conic-gradient(var(--line) 0deg 360deg);
      position: relative;
      margin: 0 auto;
      box-shadow: inset 0 0 0 1px rgba(16,24,32,.05);
    }
    .donut::after {
      content: "";
      position: absolute;
      inset: 28px;
      border-radius: 50%;
      background: #fff;
      border: 1px solid var(--line);
    }
    .donut-center { position: absolute; inset: 42px; display: grid; place-items: center; text-align: center; z-index: 1; font-size: 12px; color: var(--muted); }
    .donut-center strong { display: block; color: var(--text); font-size: 20px; line-height: 1.1; }
    .legend { display: grid; gap: 8px; }
    .legend-row { display: grid; grid-template-columns: 12px minmax(0, 1fr) auto; align-items: center; gap: 8px; font-size: 13px; }
    .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
    .chart-note { color: var(--muted); font-size: 12px; margin-top: 10px; }
    .mini-list { display: grid; gap: 8px; }
    .mini-item { border-bottom: 1px solid var(--line); padding-bottom: 8px; font-size: 13px; }
    .mini-item:last-child, .dist-row:last-child { border-bottom: 0; padding-bottom: 0; }
    .mini-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .mini-meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
    .health-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 8px; font-size: 13px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }
    .health-row:last-child { border-bottom: 0; padding-bottom: 0; }
    .empty-actions { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .toolbar { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
    .filters { display: flex; gap: 8px; flex-wrap: wrap; }
    .filters input { width: 210px; }
    .filters select { width: 150px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; border-bottom: 1px solid var(--line); padding: 10px 8px; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; background: #fbfcfd; }
    tr[data-selectable="true"] { cursor: pointer; }
    tr[data-selectable="true"]:hover td { background: #f8fbff; }
    .status { display: inline-block; border-radius: 999px; padding: 3px 8px; font-size: 12px; background: var(--panel-2); color: var(--muted); white-space: nowrap; }
    .status.completed, .status.supported, .status.approved, .status.official, .status.success, .status.verified, .status.passed, .status.positive { color: var(--good); background: #e9f7ef; }
    .status.covered { color: var(--good); background: #e9f7ef; }
    .status.failed, .status.rejected, .status.quality_failed, .status.negative, .status.high, .status.credential_required { color: var(--bad); background: #fff0ed; }
    .status.running, .status.queued, .status.pending, .status.secondary, .status.regenerate_requested, .status.medium, .status.not_collected { color: var(--warn); background: #fff6e6; }
    .status.neutral, .status.low, .status.in_context, .status.ready { color: var(--muted); background: #eef2f5; }
    .status.cancelled, .status.archived, .status.disabled, .status.not_configured, .status.market_mismatch { color: var(--muted); background: #eef2f5; }
    .links { display: flex; gap: 6px; flex-wrap: wrap; }
    .detail { position: sticky; top: 82px; max-height: calc(100vh - 104px); overflow-y: auto; }
    .detail-section { border-top: 1px solid var(--line); padding-top: 12px; margin-top: 12px; }
    .kv { display: grid; grid-template-columns: 108px minmax(0, 1fr); gap: 8px; font-size: 13px; margin: 7px 0; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; word-break: break-all; }
    .nowrap { white-space: nowrap; }
    .text-block { border: 1px solid var(--line); background: #fbfcfd; border-radius: 8px; padding: 10px; font-size: 13px; line-height: 1.55; white-space: pre-wrap; }
    .diagnostic-grid { display: grid; gap: 8px; }
    .diagnostic-card { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; padding: 10px; display: grid; gap: 6px; font-size: 13px; }
    .diagnostic-head { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
    .diagnostic-meta { display: flex; flex-wrap: wrap; gap: 6px; color: var(--muted); font-size: 12px; }
    .diagnostic-list { display: grid; gap: 6px; }
    .diagnostic-issue { border-left: 3px solid var(--warn); padding-left: 8px; font-size: 13px; line-height: 1.45; }
    .diagnostic-issue.blocker, .diagnostic-issue.fatal, .diagnostic-issue.error { border-left-color: var(--bad); }
    .diagnostic-empty { color: var(--muted); font-size: 13px; }
    .analysis-stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .analysis-stat { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; padding: 10px; min-height: 72px; }
    .analysis-stat strong { display: block; font-size: 18px; margin-top: 5px; }
    .check-grid { display: grid; gap: 8px; }
    .check-item { border: 1px solid var(--line); border-left: 4px solid var(--warn); border-radius: 8px; background: #fbfcfd; padding: 10px; font-size: 13px; }
    .check-item.passed { border-left-color: var(--good); }
    .check-item.failed { border-left-color: var(--bad); }
    .chain-list { display: grid; gap: 8px; }
    .chain-node { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; padding: 10px; font-size: 13px; }
    .chain-node-head { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
    .chain-edge { margin: 6px 0 6px 14px; color: var(--muted); font-size: 12px; }
    .chain-summary { border: 1px solid #cfe2f3; background: #f4f9ff; color: #18436b; border-radius: 8px; padding: 10px; font-size: 13px; line-height: 1.5; margin-bottom: 10px; }
    .logic-flow { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; margin: 10px 0; }
    .logic-stage { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; padding: 10px; min-height: 118px; font-size: 12px; display: grid; align-content: start; gap: 6px; }
    .logic-stage.done { border-color: rgba(22,128,60,.32); background: #f5fbf7; }
    .logic-stage.missing { border-color: rgba(181,106,0,.34); background: #fffaf0; }
    .logic-stage strong { font-size: 13px; overflow-wrap: anywhere; }
    .logic-stage .count { font-size: 18px; font-weight: 700; }
    .risk-path { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; padding: 10px; display: grid; gap: 8px; }
    .transmission { display: flex; flex-wrap: wrap; gap: 6px; color: var(--muted); font-size: 12px; }
    .transmission span { border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; background: #fff; }
    .action-list { display: grid; gap: 7px; }
    .action-item { border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #fbfcfd; display: grid; gap: 6px; font-size: 13px; }
    .reason-list { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 6px; }
    .reason-pill { display: inline-block; border-radius: 999px; background: #eef6ff; color: #175cd3; padding: 3px 7px; font-size: 12px; }
    .score-note { color: var(--muted); font-size: 12px; line-height: 1.45; }
    .timeline { display: grid; gap: 8px; }
    .event { border-left: 3px solid var(--line); padding-left: 10px; font-size: 13px; }
    .empty, .error { color: var(--muted); font-size: 13px; padding: 18px; text-align: center; border: 1px dashed var(--line); border-radius: 8px; background: #fbfcfd; }
    .error { color: var(--bad); }
    .modal-backdrop { position: fixed; inset: 0; background: rgba(16,24,32,.48); display: none; place-items: center; padding: 18px; z-index: 20; }
    .modal-backdrop.active { display: grid; }
    .modal { width: min(720px, 100%); max-height: calc(100vh - 36px); overflow-y: auto; background: #fff; border-radius: 8px; border: 1px solid var(--line); box-shadow: 0 24px 70px rgba(16,24,32,.22); }
    .modal-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--line); }
    .modal-head h2 { margin: 0; font-size: 16px; }
    .modal-body { padding: 18px; display: grid; gap: 14px; }
    .form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .field { display: grid; gap: 6px; }
    .field label { color: var(--muted); font-size: 12px; }
    .field.full { grid-column: 1 / -1; }
    .choice-row { display: flex; flex-wrap: wrap; gap: 8px; }
    .choice { border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 6px 10px; cursor: pointer; font: inherit; font-size: 12px; }
    .choice:hover { border-color: var(--accent); color: var(--accent); }
    .modal-actions { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 18px; border-top: 1px solid var(--line); background: #fbfcfd; }
    .form-note { color: var(--muted); font-size: 12px; line-height: 1.5; }
    .placeholder-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .placeholder { min-height: 136px; display: grid; align-content: center; gap: 8px; }
    @media (max-width: 1100px) {
      .app { grid-template-columns: 1fr; }
      .sidebar { position: static; height: auto; display: block; }
      .nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .work-layout, .dashboard-layout, .dashboard-charts, .cards, .placeholder-grid { grid-template-columns: 1fr; }
      .logic-flow { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .detail { position: static; max-height: none; }
    }
    @media (max-width: 760px) {
      .topbar { align-items: flex-start; flex-direction: column; padding: 14px 16px; }
      .content { padding: 14px 16px 22px; }
      .nav { grid-template-columns: 1fr; }
      .form-grid { grid-template-columns: 1fr; }
      .logic-flow { grid-template-columns: 1fr; }
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
        <div class="brand-title">慧研投研工作台</div>
        <div class="brand-sub">证据驱动的投研控制台</div>
      </div>
      <nav class="nav" aria-label="工作台导航">
        <button class="active" data-view="dashboard"><span>投研首页</span><span class="tag available">可用</span></button>
	        <button data-view="workspace"><span>投研空间</span><span class="tag available">可用</span></button>
	        <button data-view="stockpool"><span>股票池管理</span><span class="tag available">可用</span></button>
	        <button data-view="datasources"><span>数据源管理</span><span class="tag available">可用</span></button>
	        <button data-view="ingestion"><span>采集任务</span><span class="tag available">可用</span></button>
	        <button data-view="manual"><span>手动导入</span><span class="tag available">可用</span></button>
	        <button data-view="documents"><span>文档处理中心</span><span class="tag available">可用</span></button>
        <button data-view="evidence"><span>证据库</span><span class="tag available">可用</span></button>
	        <button data-view="facts"><span>财务事实中心</span><span class="tag available">可用</span></button>
        <button data-view="signals"><span>投资线索</span><span class="tag enhancing">增强中</span></button>
        <button data-view="tasks"><span>研报任务</span><span class="tag available">可用</span></button>
        <button data-view="claims"><span>主张复核</span><span class="tag available">可用</span></button>
	        <button data-view="dictionary"><span>金融词典</span><span class="tag available">可用</span></button>
	        <button data-view="promptops"><span>提示词运营</span><span class="tag available">可用</span></button>
        <button data-view="entities"><span>实体库</span><span class="tag enhancing">增强中</span></button>
        <button data-view="graph"><span>关系图谱</span><span class="tag enhancing">增强中</span></button>
	        <button data-view="evaluation"><span>评测中心</span><span class="tag available">可用</span></button>
	        <button data-view="export"><span>导出中心</span><span class="tag available">可用</span></button>
      </nav>
    </aside>

    <section class="main">
      <header class="topbar">
        <div class="title">
          <h1 id="viewTitle">投研首页</h1>
          <div class="sub" id="viewSubtitle">任务、证据、主张与处理漏斗</div>
        </div>
        <div class="top-actions">
          <select class="select" aria-label="投研空间">
            <option>默认投研空间</option>
          </select>
          <button class="btn primary" data-open-create-task>创建研报任务</button>
          <button class="btn ghost" data-jump="manual">导入文档</button>
          <button class="btn ghost" data-jump="export">查看最新报告</button>
          <a class="btn ghost" href="/">返回对话首页</a>
          <button class="btn" id="refreshView">刷新</button>
        </div>
      </header>

      <main class="content">
        <div id="workbenchNotice"></div>
        <section id="dashboard" class="view active">
          <section class="grid cards" id="metricCards"></section>
          <section class="grid dashboard-layout">
            <div class="panel">
              <div class="panel-head">
                <h2>处理漏斗</h2>
                <button class="btn" data-jump="documents">失败步骤</button>
              </div>
	              <div class="tab-switch" role="tablist" aria-label="处理漏斗视图">
	                <button class="active" data-funnel-tab="chain">真实处理链路</button>
	                <button data-funnel-tab="funnel">示意漏斗</button>
	              </div>
	              <div class="funnel-view" id="funnelTab">
	                <div id="funnelDemoNote"></div>
	                <div class="funnel-visual" id="funnelVisual"></div>
	                <div id="funnelLoss"></div>
	              </div>
	              <div class="funnel-view active" id="chainTab">
	                <div class="funnel" id="funnel"></div>
	              </div>
            </div>
            <div class="grid">
              <div class="panel">
                <div class="panel-head">
                  <h2>最近任务</h2>
                  <button class="btn" data-jump="tasks">查看任务</button>
                </div>
                <div class="mini-list" id="recentTasks"></div>
              </div>
              <div class="panel">
                <div class="panel-head">
                  <h2>数据源健康</h2>
                  <button class="btn" data-jump="datasources">来源配置</button>
                </div>
                <div class="dist" id="dataSourceHealth"></div>
              </div>
              <div class="panel">
                <div class="panel-head">
                  <h2>复核异常</h2>
                  <button class="btn" data-jump="claims">查看主张</button>
                </div>
                <div class="dist" id="reviewExceptions"></div>
              </div>
            </div>
          </section>
          <section class="grid dashboard-charts">
            <div class="panel">
              <div class="panel-head">
                <h2>数据源分布</h2>
                <button class="btn" data-jump="datasources">配置数据源</button>
              </div>
              <div id="dataSourceChart"></div>
            </div>
            <div class="panel">
              <div class="panel-head">
                <h2>主张状态分布</h2>
                <button class="btn" data-jump="claims">查看主张</button>
              </div>
              <div id="claimStatusChart"></div>
            </div>
          </section>
          <section class="panel dashboard-bottom">
            <div class="panel-head">
              <h2>最近研报任务</h2>
              <button class="btn primary" data-open-create-task>创建研报任务</button>
            </div>
            <div class="table-scroll">
              <table>
                <thead>
                  <tr><th>公司</th><th>期间</th><th>类型</th><th>状态</th><th>质量分</th><th>更新时间</th><th>操作</th></tr>
                </thead>
                <tbody id="recentTaskRows"></tbody>
              </table>
            </div>
          </section>
        </section>

        <section id="tasks" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">研报任务</h2>
                <div class="filters">
                  <input id="symbolFilter" placeholder="筛选股票代码，如 600519" />
                  <button class="btn" id="refreshTasks">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>任务</th><th>公司</th><th>状态</th><th>阶段</th><th>创建时间</th><th>产物</th><th>操作</th></tr>
                  </thead>
                  <tbody id="taskRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="taskDetail">
              <h2>任务详情</h2>
              <div class="empty">选择一个任务查看时间线和产物。</div>
            </aside>
          </div>
        </section>

        <section id="evidence" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">证据库</h2>
                <div class="filters">
                  <input id="evidenceQuery" placeholder="搜索证据" />
                  <input id="evidenceCompany" placeholder="公司或代码" />
                  <input id="evidencePeriod" placeholder="期间，如 FY2024" />
                  <input id="evidenceTask" placeholder="按研报任务筛选" />
                  <select id="evidenceSource">
                    <option value="">全部来源</option>
                    <option value="sec_edgar">美国证监会年报</option>
                    <option value="cninfo">巨潮资讯</option>
                    <option value="hkex">港交所公告</option>
                    <option value="eastmoney">东方财富</option>
                    <option value="yahoo_finance">雅虎财经</option>
                    <option value="news">新闻</option>
                  </select>
                  <select id="evidenceTrust">
                    <option value="">全部可信度</option>
                    <option value="official">官方</option>
                    <option value="primary">一手</option>
                    <option value="secondary">二手</option>
                  </select>
                  <select id="evidenceMode">
                    <option value="">普通筛选</option>
                    <option value="hybrid">智能检索</option>
                  </select>
                  <button class="btn" id="refreshEvidence">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>证据</th><th>匹配原因</th><th>来源</th><th>可信度</th><th>文档</th><th>主张</th></tr>
                  </thead>
                  <tbody id="evidenceRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="evidenceDetail">
              <h2>证据详情</h2>
              <div class="empty">选择一条证据查看原文和关联主张。</div>
            </aside>
          </div>
        </section>

        <section id="documents" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">文档处理中心</h2>
                <div class="filters">
                  <input id="documentQuery" placeholder="搜索文档" />
                  <input id="documentBatch" placeholder="按采集批次筛选" />
                  <select id="documentStep">
                    <option value="">全部步骤</option>
                    <option value="ingest">入库</option>
                    <option value="parse">解析</option>
                    <option value="table_extract">表格抽取</option>
                    <option value="chunk">切分</option>
                    <option value="evidence">证据化</option>
                    <option value="claim_bind">绑定主张</option>
                    <option value="verify">校验</option>
                  </select>
                  <button class="btn" id="refreshDocuments">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>文档</th><th>批次</th><th>状态</th><th>最新步骤</th><th>证据</th><th>主张</th></tr>
                  </thead>
                  <tbody id="documentRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="documentDetail">
              <h2>处理路径</h2>
              <div class="empty">选择一个文档查看处理步骤和关联证据。</div>
            </aside>
          </div>
        </section>

        <section id="claims" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">主张复核</h2>
                <div class="filters">
                  <input id="claimQuery" placeholder="搜索主张" />
                  <input id="claimTask" placeholder="按研报任务筛选" />
                  <select id="claimStatus">
                    <option value="">全部复核状态</option>
                    <option value="pending">待复核</option>
                    <option value="approved">已通过</option>
                    <option value="rejected">已驳回</option>
                    <option value="regenerate_requested">已请求重生成</option>
                  </select>
                  <select id="claimVerification">
                    <option value="">全部校验状态</option>
                    <option value="supported">已支持</option>
                    <option value="failed">失败</option>
                    <option value="pending">待处理</option>
                  </select>
                  <button class="btn" id="refreshClaims">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>主张</th><th>任务</th><th>复核</th><th>校验</th><th>证据</th></tr>
                  </thead>
                  <tbody id="claimRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="claimDetail">
              <h2>主张详情</h2>
              <div class="empty">选择一个主张查看证据、校验和审计记录。</div>
            </aside>
          </div>
        </section>

        <section id="export" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">导出中心</h2>
                <div class="filters">
                  <input id="exportSymbol" placeholder="筛选股票代码" />
                  <select id="exportStatus">
                    <option value="">全部任务状态</option>
                    <option value="completed">已完成</option>
                    <option value="failed">失败</option>
                    <option value="running">运行中</option>
                    <option value="queued">排队中</option>
                  </select>
                  <button class="btn" id="refreshExports">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>任务</th><th>状态</th><th>产物</th><th>复核</th><th>正式导出</th></tr>
                  </thead>
                  <tbody id="exportRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="exportDetail">
              <h2>产物复核</h2>
              <div class="empty">选择一个任务查看产物和导出状态。</div>
            </aside>
          </div>
        </section>

        <section id="workspace" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">投研空间</h2>
                <div class="filters">
                  <button class="btn" id="refreshWorkspaces">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>空间</th><th>市场</th><th>股票池</th><th>关注指标</th><th>风险类型</th><th>数据源</th></tr>
                  </thead>
                  <tbody id="workspaceRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail">
              <h2>创建投研空间</h2>
              <div class="form-grid">
                <div class="field full"><label for="workspaceName">空间名称</label><input id="workspaceName" placeholder="例如：AI 美股投研空间" /></div>
                <div class="field"><label for="workspaceSlug">空间标识</label><input id="workspaceSlug" placeholder="ai-us" /></div>
                <div class="field"><label for="workspaceMarket">市场</label><input id="workspaceMarket" placeholder="美股 / A 股 / 港股" /></div>
                <div class="field full"><label for="workspaceMetrics">关注指标</label><input id="workspaceMetrics" placeholder="收入, 毛利率, 自由现金流" /></div>
                <div class="field full"><label for="workspaceRisks">风险类型</label><input id="workspaceRisks" placeholder="估值风险, 现金流风险, 监管风险" /></div>
                <div class="field full"><label for="workspaceSources">默认数据源</label><input id="workspaceSources" placeholder="美国证监会年报、雅虎财经、本地证据库" /></div>
              </div>
              <div class="modal-actions"><button class="btn primary" id="createWorkspace">创建空间</button></div>
              <div id="workspaceMessage"></div>
            </aside>
          </div>
        </section>
        <section id="stockpool" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">股票池管理</h2>
                <div class="filters">
                  <select id="stockpoolWorkspace"></select>
                  <input id="stockpoolQuery" placeholder="搜索公司、代码或行业" />
                  <button class="btn" id="refreshStockpool">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>公司</th><th>市场</th><th>行业</th><th>别名</th><th>关注指标</th><th>风险类型</th></tr>
                  </thead>
                  <tbody id="stockpoolRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail">
              <h2>添加股票池公司</h2>
              <div class="form-grid">
                <div class="field full"><label for="stockCompanyName">公司名称</label><input id="stockCompanyName" placeholder="例如：NVIDIA Corporation" /></div>
                <div class="field"><label for="stockSymbol">股票代码</label><input id="stockSymbol" placeholder="NVDA" /></div>
                <div class="field"><label for="stockMarket">市场</label><input id="stockMarket" placeholder="美股 / A 股 / 港股" /></div>
                <div class="field full"><label for="stockIndustry">行业</label><input id="stockIndustry" placeholder="Semiconductors" /></div>
                <div class="field full"><label for="stockAliases">公司别名</label><input id="stockAliases" placeholder="英伟达, NVIDIA, NVDA" /></div>
              </div>
              <div class="modal-actions"><button class="btn primary" id="addStockCompany">添加公司</button></div>
              <div id="stockpoolMessage"></div>
            </aside>
          </div>
        </section>
        <section id="datasources" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">数据源管理</h2>
                <div class="filters">
                  <input id="datasourceQuery" placeholder="搜索数据源或类型" />
                  <select id="datasourceEnabled">
                    <option value="">全部状态</option>
                    <option value="true">已启用</option>
                    <option value="false">已停用</option>
                  </select>
                  <button class="btn" id="seedDatasources">同步注册源</button>
                  <button class="btn" id="refreshDatasources">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>数据源</th><th>类型</th><th>市场</th><th>可信度</th><th>凭证</th><th>最近状态</th><th>操作</th></tr>
                  </thead>
                  <tbody id="datasourceRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="datasourceDetail">
              <h2>数据源详情</h2>
              <div class="empty">选择一个数据源查看配置、健康状态和最近错误。</div>
            </aside>
          </div>
        </section>
        <section id="ingestion" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">采集任务</h2>
                <div class="filters">
                  <input id="ingestionQuery" placeholder="搜索批次、公司、期间或查询词" />
                  <select id="ingestionStatus">
                    <option value="">全部状态</option>
                    <option value="queued">待启动</option>
                    <option value="running">运行中</option>
                    <option value="completed">已完成</option>
                    <option value="failed">失败</option>
                    <option value="cancelled">已取消</option>
                  </select>
                  <input id="ingestionSource" placeholder="按数据源筛选，如美国证监会年报" />
                  <button class="btn" id="refreshIngestion">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>批次</th><th>数据源</th><th>目标</th><th>状态</th><th>结果</th><th>操作</th></tr>
                  </thead>
                  <tbody id="ingestionRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="ingestionDetail">
              <h2>创建采集批次</h2>
              <div class="form-grid">
                <div class="field full"><label for="ingestionName">批次名称</label><input id="ingestionName" placeholder="例如：NVDA FY2024 年报采集" /></div>
                <div class="field"><label for="ingestionCreateSource">数据源</label><input id="ingestionCreateSource" placeholder="例如：美国证监会年报" /></div>
                <div class="field"><label for="ingestionTargetType">采集目标</label><select id="ingestionTargetType"><option value="filings">公告/年报</option><option value="market_data">行情数据</option><option value="news">新闻资料</option><option value="documents">文档资料</option></select></div>
                <div class="field"><label for="ingestionSymbol">股票代码</label><input id="ingestionSymbol" placeholder="NVDA" /></div>
                <div class="field"><label for="ingestionPeriod">期间</label><input id="ingestionPeriod" placeholder="FY2024" /></div>
                <div class="field full"><label for="ingestionCreateQuery">查询条件</label><textarea id="ingestionCreateQuery" rows="3" placeholder="例如：NVDA 10-K FY2024"></textarea></div>
              </div>
              <div class="modal-actions"><button class="btn primary" id="createIngestionBatch">创建批次</button></div>
              <div id="ingestionMessage"></div>
            </aside>
          </div>
        </section>
        <section id="manual" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">手动导入</h2>
                <div class="filters">
                  <button class="btn" data-jump="documents">查看文档处理中心</button>
                  <button class="btn" data-jump="ingestion">查看采集批次</button>
                </div>
              </div>
              <div class="form-grid">
                <div class="field">
                  <label for="manualImportType">导入类型</label>
                  <select id="manualImportType">
                    <option value="text">文本摘录</option>
                    <option value="url">来源链接</option>
                    <option value="pdf">PDF 文件</option>
                  </select>
                </div>
                <div class="field">
                  <label for="manualSymbol">股票代码</label>
                  <input id="manualSymbol" placeholder="NVDA / 600519 / 0700.HK" />
                </div>
                <div class="field">
                  <label for="manualCompanyName">公司名称</label>
                  <input id="manualCompanyName" placeholder="NVIDIA Corporation" />
                </div>
                <div class="field">
                  <label for="manualPeriod">期间</label>
                  <input id="manualPeriod" placeholder="FY2024 / 2025Q1" />
                </div>
                <div class="field full">
                  <label for="manualTitle">资料标题</label>
                  <input id="manualTitle" placeholder="例如：NVDA FY2024 年报摘录" />
                </div>
                <div class="field full" data-manual-field="content">
                  <label for="manualContent">文本内容</label>
                  <textarea id="manualContent" rows="8" placeholder="粘贴公告、财报摘录、新闻或券商研报片段。"></textarea>
                </div>
                <div class="field full" data-manual-field="source">
                  <label for="manualSourceUrl">来源链接</label>
                  <input id="manualSourceUrl" placeholder="https://www.sec.gov/..." />
                </div>
                <div class="field full" data-manual-field="file">
                  <label for="manualFilePath">PDF 文件路径</label>
                  <input id="manualFilePath" placeholder="/Users/.../annual_report.pdf" />
                </div>
              </div>
              <div class="modal-actions">
                <button class="btn primary" id="submitManualImport">导入到文档处理中心</button>
              </div>
              <div id="manualImportMessage"></div>
            </section>
            <aside class="panel detail" id="manualImportResult">
              <h2>导入结果</h2>
              <div class="empty">导入后会生成批次和文档记录，后续解析、切分、向量化都从文档处理中心接续。</div>
            </aside>
          </div>
        </section>
        <section id="facts" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">财务事实中心</h2>
                <div class="filters">
                  <input id="factCompany" placeholder="公司或代码" />
                  <input id="factMetric" placeholder="指标" />
                  <input id="factPeriodFilter" placeholder="期间，如 FY2024" />
                  <button class="btn" id="refreshFacts">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>公司</th><th>指标</th><th>数值</th><th>期间</th><th>来源</th><th>状态</th></tr>
                  </thead>
                  <tbody id="factRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="factDetail">
              <h2>导入财务事实</h2>
              <div class="form-grid">
                <div class="field"><label for="factSymbol">股票代码</label><input id="factSymbol" placeholder="AAPL" /></div>
                <div class="field"><label for="factCompanyName">公司名称</label><input id="factCompanyName" placeholder="苹果公司" /></div>
                <div class="field full"><label for="factMetricName">指标</label><input id="factMetricName" placeholder="营业收入 / 毛利率" /></div>
                <div class="field"><label for="factValue">数值</label><input id="factValue" placeholder="391035" /></div>
                <div class="field"><label for="factPeriod">期间</label><input id="factPeriod" placeholder="FY2024" /></div>
                <div class="field"><label for="factCurrency">币种</label><input id="factCurrency" placeholder="USD / CNY / HKD" /></div>
                <div class="field"><label for="factUnit">单位</label><input id="factUnit" placeholder="million / %" /></div>
                <div class="field"><label for="factEvidenceId">关联证据</label><input id="factEvidenceId" placeholder="可选，填写证据编号或记录 ID" /></div>
                <div class="field full"><label for="factSourceUrl">来源链接</label><input id="factSourceUrl" placeholder="https://..." /></div>
              </div>
              <div class="form-note">手工事实默认仅作研究草稿输入。只有绑定可追溯证据、通过期间校验并确认来源权威等级后，才可进入正式研报口径。</div>
              <div class="modal-actions"><button class="btn primary" id="createFinancialFact">导入事实</button></div>
              <div id="factMessage"></div>
            </aside>
          </div>
        </section>
        <section id="signals" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">投资线索</h2>
                <div class="filters">
                  <input id="signalCompany" placeholder="公司或代码" />
                  <input id="signalPeriod" placeholder="期间，如 FY2024" />
                  <select id="signalType">
                    <option value="">全部线索</option>
                    <option value="margin_decline">利润率下滑</option>
                    <option value="cashflow_gap">利润与现金流背离</option>
                    <option value="official_source_missing">官方来源缺口</option>
                    <option value="currency_mismatch">币种口径不一致</option>
                    <option value="valuation_blocked">估值资料不足</option>
                    <option value="revenue_growth_acceleration">收入增速改善</option>
                  </select>
                  <select id="signalStatus">
                    <option value="">全部状态</option>
                    <option value="pending">待复核</option>
                    <option value="in_context">已加入任务</option>
                    <option value="dismissed">已忽略</option>
                  </select>
                  <button class="btn primary" id="generateSignals">生成规则线索</button>
                  <button class="btn" id="refreshSignals">刷新</button>
                </div>
              </div>
              <div class="form-note">增强能力：线索必须绑定证据并经人工复核后，才可进入正式研报。</div>
              <div id="signalScopeNotice"></div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>线索</th><th>公司</th><th>期间</th><th>方向</th><th>强度</th><th>证据</th><th>状态</th></tr>
                  </thead>
                  <tbody id="signalRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="signalDetail">
              <h2>线索详情</h2>
              <div class="empty">选择线索查看证据、来源事实和加入研报任务入口。</div>
            </aside>
          </div>
        </section>
        <section id="dictionary" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">金融词典</h2>
                <div class="filters">
                  <input id="dictionaryQuery" placeholder="搜索标准词、别名、代码" />
                  <select id="dictionaryType">
                    <option value="">全部类型</option>
                    <option value="company">公司别名</option>
                    <option value="product">产品别名</option>
                    <option value="metric">财务指标</option>
                    <option value="industry">行业术语</option>
                    <option value="risk">风险词</option>
                    <option value="exclude">排除词</option>
                  </select>
                  <button class="btn" id="refreshDictionary">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>标准词</th><th>类型</th><th>代码/市场</th><th>别名</th><th>说明</th></tr>
                  </thead>
                  <tbody id="dictionaryRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="dictionaryDetail">
              <h2>添加词条</h2>
              <div class="form-grid">
                <div class="field">
                  <label for="dictionaryCreateType">类型</label>
                  <select id="dictionaryCreateType">
                    <option value="company">公司别名</option>
                    <option value="metric">财务指标</option>
                    <option value="product">产品别名</option>
                    <option value="industry">行业术语</option>
                    <option value="risk">风险词</option>
                    <option value="exclude">排除词</option>
                  </select>
                </div>
                <div class="field">
                  <label for="dictionaryMarket">市场</label>
                  <input id="dictionaryMarket" placeholder="美股 / A 股 / 港股" />
                </div>
                <div class="field full">
                  <label for="dictionaryCanonical">标准词</label>
                  <input id="dictionaryCanonical" placeholder="例如：苹果公司 / 营业收入 / 毛利率" />
                </div>
                <div class="field">
                  <label for="dictionarySymbol">股票代码</label>
                  <input id="dictionarySymbol" placeholder="公司词条可填，如 AAPL" />
                </div>
                <div class="field">
                  <label for="dictionaryAliases">别名</label>
                  <input id="dictionaryAliases" placeholder="苹果, Apple, Apple Inc." />
                </div>
                <div class="field full">
                  <label for="dictionaryDescription">说明</label>
                  <textarea id="dictionaryDescription" rows="3" placeholder="口径、用途或排除原因。"></textarea>
                </div>
              </div>
              <div class="modal-actions"><button class="btn primary" id="createDictionaryTerm">添加词条</button></div>
              <div id="dictionaryMessage"></div>
            </aside>
          </div>
        </section>
        <section id="promptops" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">提示词运营</h2>
                <div class="filters">
                  <input id="promptModule" placeholder="按运行模块筛选，如主张校验 / 事实抽取" />
                  <button class="btn" id="refreshPromptOps">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>提示词</th><th>模块</th><th>状态</th><th>活动版本</th><th>结构化输出</th><th>操作</th></tr>
                  </thead>
                  <tbody id="promptRows"></tbody>
                </table>
              </div>
              <div class="detail-section">
                <h3>最近智能体运行</h3>
                <div class="table-scroll">
                  <table>
                    <thead><tr><th>运行</th><th>提示词</th><th>模型</th><th>状态</th><th>耗时/成本</th></tr></thead>
                    <tbody id="llmRunRows"></tbody>
                  </table>
                </div>
              </div>
            </section>
            <aside class="panel detail" id="promptDetail">
              <h2>创建提示词</h2>
              <div class="form-grid">
                <div class="field"><label for="promptKey">模板标识</label><input id="promptKey" placeholder="例如：主张校验模板" /></div>
                <div class="field"><label for="promptCreateModule">运行模块</label><input id="promptCreateModule" placeholder="例如：主张校验" /></div>
                <div class="field full"><label for="promptName">名称</label><input id="promptName" placeholder="主张校验提示词" /></div>
                <div class="field full"><label for="promptContent">内容</label><textarea id="promptContent" rows="7" placeholder="请判断主张是否有证据支持：{{claim}}"></textarea></div>
                <div class="field full"><label for="promptSchema">结构化输出要求</label><textarea id="promptSchema" rows="5" placeholder='{"type":"object","required":["verdict"],"properties":{"verdict":{"type":"string"}}}'></textarea></div>
              </div>
              <div class="modal-actions"><button class="btn primary" id="createPromptTemplate">创建提示词</button></div>
              <div id="promptMessage"></div>
            </aside>
          </div>
        </section>
        <section id="entities" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">实体库</h2>
                <div class="filters">
                  <input id="entityQuery" placeholder="搜索公司、指标、产品或风险" />
                  <select id="entityType">
                    <option value="">全部实体</option>
                    <option value="company">公司</option>
                    <option value="ticker">股票代码</option>
                    <option value="industry">行业</option>
                    <option value="product">产品</option>
                    <option value="customer">客户</option>
                    <option value="supplier">供应商</option>
                    <option value="executive">高管</option>
                    <option value="metric">财务指标</option>
                    <option value="document">文档</option>
                    <option value="risk_event">风险事件</option>
                    <option value="news_event">新闻事件</option>
                    <option value="peer_company">同行公司</option>
                  </select>
                  <button class="btn" id="refreshEntities">刷新</button>
                </div>
              </div>
              <div class="form-note">增强能力：实体仅用于辅助组织证据，不代表已核验的正式结论。</div>
              <div class="table-scroll">
                <table>
                  <thead><tr><th>实体</th><th>类型</th><th>市场/代码</th><th>来源证据</th><th>置信度</th></tr></thead>
                  <tbody id="entityRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="entityDetail">
              <h2>实体详情</h2>
              <div class="empty">选择一个实体查看来源、说明和后续关系。</div>
            </aside>
          </div>
        </section>
        <section id="graph" class="view">
          <div class="grid work-layout">
            <section class="panel">
              <div class="toolbar">
                <h2 style="margin:0">关系图谱</h2>
                <div class="filters">
                  <input id="relationQuery" placeholder="搜索关系两端实体" />
                  <select id="relationType">
                    <option value="">全部关系</option>
                    <option value="BELONGS_TO">属于行业</option>
                    <option value="PUBLISHED">发布文档</option>
                    <option value="HAS_PRODUCT">拥有产品</option>
                    <option value="HAS_METRIC">关联指标</option>
                    <option value="HAS_EVENT">关联事件</option>
                    <option value="PEER_OF">同行对比</option>
                    <option value="SUPPLIES_TO">供应关系</option>
                    <option value="MENTIONED_IN">出现在文档</option>
                  </select>
                  <button class="btn" id="refreshRelations">刷新</button>
                </div>
              </div>
              <div class="form-note">增强能力：关系图谱仅展示已沉淀关系，不能替代主张与引用校验。</div>
              <div id="graphStats" class="dist" style="margin-bottom:12px"></div>
              <div class="table-scroll">
                <table>
                  <thead><tr><th>关系</th><th>来源</th><th>置信度</th></tr></thead>
                  <tbody id="relationRows"></tbody>
                </table>
              </div>
            </section>
            <aside class="panel detail" id="relationDetail">
              <h2>关系详情</h2>
              <div class="empty">选择一条关系查看两端实体和证据来源。</div>
            </aside>
          </div>
        </section>
        <section id="evaluation" class="view">
          <section class="grid cards" id="evaluationCards"></section>
          <section class="grid dashboard-layout">
            <div class="grid">
              <section class="panel">
                <div class="panel-head">
                  <h2>质量门禁</h2>
                  <button class="btn" data-jump="tasks">查看研报任务</button>
                </div>
                <div id="evaluationGates" class="check-grid"></div>
              </section>
              <section class="panel">
                <div class="panel-head">
                  <h2>最近研报质量</h2>
                  <button class="btn" data-jump="tasks">任务列表</button>
                </div>
                <div class="detail-section" style="border-top:0;margin-top:0;padding-top:0">
                  <h3>基准集结果</h3>
                  <div id="evaluationBenchmarkSuites"></div>
                </div>
                <div class="detail-section" style="border-top:0;margin-top:0;padding-top:0">
                  <h3>回归矩阵</h3>
                  <div id="evaluationRegressionMatrix"></div>
                </div>
                <div class="table-scroll">
                  <table>
                    <thead><tr><th>研报</th><th>状态</th><th>质量分</th><th>证据覆盖</th><th>校验通过</th><th>风险项</th><th>操作</th></tr></thead>
                    <tbody id="evaluationTaskRows"></tbody>
                  </table>
                </div>
              </section>
            </div>
            <div class="grid">
              <section class="panel">
                <div class="panel-head">
                  <h2>主张与证据质量</h2>
                  <button class="btn" data-jump="claims">进入复核</button>
                </div>
                <div id="evaluationClaimQuality" class="diagnostic-grid"></div>
              </section>
              <section class="panel">
                <div class="panel-head">
                  <h2>证据召回质量</h2>
                  <button class="btn" data-jump="evidence">查看证据库</button>
                </div>
                <div id="evaluationRetrievalQuality" class="mini-list"></div>
              </section>
              <section class="panel">
                <div class="panel-head">
                  <h2>模型运行健康</h2>
                  <button class="btn" data-jump="promptops">查看调用</button>
                </div>
                <div id="evaluationModelHealth" class="dist"></div>
              </section>
              <section class="panel">
                <div class="panel-head">
                  <h2>待处理问题</h2>
                  <button class="btn" data-jump="claims">处理问题</button>
                </div>
                <div id="evaluationFailures" class="mini-list"></div>
              </section>
            </div>
          </section>
          <section class="panel dashboard-bottom" id="evaluationDiagnosticPanel">
            <div class="panel-head">
              <h2>单任务诊断</h2>
              <button class="btn" data-jump="tasks">查看任务详情</button>
            </div>
            <div id="evaluationTaskDiagnostic"><div class="empty">从“最近研报质量”选择一个任务，查看质量问题、主张阻塞和处理入口。</div></div>
          </section>
          <section class="panel dashboard-bottom">
            <div class="panel-head">
              <h2>最近模型与智能体运行</h2>
              <button class="btn" data-jump="promptops">提示词运营</button>
            </div>
            <div id="evaluationRuns" class="mini-list"></div>
          </section>
          <section class="panel dashboard-bottom">
            <div class="panel-head">
              <h2>下一步接入</h2>
              <span class="status pending">质量闭环待加强</span>
            </div>
            <div id="evaluationNotes" class="diagnostic-grid"></div>
          </section>
        </section>
      </main>
    </section>
  </div>

  <div class="modal-backdrop" id="createTaskModal" role="dialog" aria-modal="true" aria-labelledby="createTaskTitle">
    <div class="modal">
      <div class="modal-head">
        <h2 id="createTaskTitle">创建研报任务</h2>
        <button class="btn" data-close-create-task>关闭</button>
      </div>
      <form id="createTaskForm">
        <div class="modal-body">
          <div class="form-grid">
            <div class="field full">
              <label for="taskCompanyInput">公司或股票代码</label>
              <input id="taskCompanyInput" list="companyCandidates" placeholder="输入苹果、腾讯、贵州茅台、AAPL、0700.HK、600519" required />
              <datalist id="companyCandidates"></datalist>
              <div class="form-note" id="companyResolveNote">支持公司中文名、英文名或股票代码；优先解析当前投研空间股票池，未命中时使用本地公司候选。</div>
            </div>
            <div class="field">
              <label for="taskPeriodInput">查询期间</label>
              <select id="taskPeriodInput">
                <option value="FY2024">FY2024</option>
                <option value="FY2023">FY2023</option>
                <option value="2025Q1">2025Q1</option>
                <option value="2024Q4">2024Q4</option>
                <option value="2024Q3">2024Q3</option>
                <option value="最近一年">最近一年</option>
              </select>
            </div>
            <div class="field">
              <label for="taskReportTypeInput">报告类型</label>
              <select id="taskReportTypeInput">
                <option value="equity_research">股票研报</option>
                <option value="annual_review">年报深度</option>
                <option value="earnings_review">财报点评</option>
              </select>
            </div>
            <div class="field">
              <label for="taskDataSourceInput">数据源范围</label>
              <select id="taskDataSourceInput">
                <option value="official_first">官方公告优先</option>
                <option value="all_available">全部可用来源</option>
                <option value="local_only">仅本地文档</option>
              </select>
            </div>
            <div class="field">
              <label for="taskEvidenceGateInput">生成前证据门禁</label>
              <select id="taskEvidenceGateInput">
                <option value="enforce">证据不足时暂停生成</option>
                <option value="allow_weak">证据不足时继续并标记风险</option>
                <option value="skip">跳过生成前证据检查</option>
              </select>
              <div class="form-note">正式研报建议先补齐权威来源，再进入生成。</div>
            </div>
            <div class="field">
              <label for="taskRunModeInput">运行方式</label>
              <select id="taskRunModeInput">
                <option value="queue">只创建任务</option>
                <option value="async">后台异步运行</option>
              </select>
            </div>
            <div class="field full">
              <label for="taskTopicInput">研究问题</label>
              <textarea id="taskTopicInput" placeholder="例如：分析收入增长、利润率变化、主要风险和估值线索。" rows="3"></textarea>
            </div>
          </div>
          <div class="choice-row" id="companyQuickChoices"></div>
          <div id="createTaskMessage"></div>
        </div>
        <div class="modal-actions">
          <button class="btn" type="button" data-close-create-task>取消</button>
          <button class="btn primary" type="submit">创建并进入任务</button>
        </div>
      </form>
    </div>
  </div>

  <script>
    "use strict";
    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (m) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[m]));
    const fmt = (v) => v == null || v === "" ? "-" : String(v);
    const number = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString() : "0";
    const pct = (v) => Math.round((Number(v) || 0) * 100) + "%";
    const activeState = { view: "dashboard" };
    const terminalTaskStatuses = new Set(["completed", "failed", "timeout", "cancelled", "archived", "quality_failed"]);
    let taskPoller = null;
    let evidenceSearchContext = new Map();
    let entityContext = new Map();
    let relationContext = new Map();
    let activeSignalTaskScope = null;

    const viewMeta = {
      dashboard: ["投研首页", "任务、证据、主张与处理漏斗"],
      workspace: ["投研空间", "市场、股票池、指标、风险和默认数据源配置"],
      stockpool: ["股票池管理", "维护空间内公司、代码、市场、行业和别名"],
      datasources: ["数据源管理", "配置来源启停、凭证状态、最近同步与错误"],
      ingestion: ["采集任务", "创建采集批次、查看运行日志、失败重试和取消"],
      manual: ["手动导入", "文本、PDF、URL 入库并进入文档处理中心"],
      documents: ["文档处理中心", "查看文档处理路径、失败步骤和关联证据"],
      evidence: ["证据库", "证据、文档、主张关联查询"],
      facts: ["财务事实中心", "指标、单位、币种、期间和证据来源"],
      signals: ["投资线索", "经营变化、财务异常、估值缺口和证据缺口"],
      tasks: ["研报任务", "按公司、期间和状态跟踪研报生成与产物"],
      claims: ["主张复核", "查看证据、校验状态和审计轨迹"],
      dictionary: ["金融词典", "维护公司、指标、行业、风险词和排除词别名"],
      promptops: ["提示词运营", "管理提示词版本、测试运行和智能体调用追踪"],
      entities: ["实体库", "公司、文档、指标、产品和风险事件沉淀"],
      graph: ["关系图谱", "查看实体之间的证据化关系链"],
      evaluation: ["评测中心", "研报质量、证据覆盖、模型运行和失败原因"],
      export: ["导出中心", "查看产物复核和正式导出状态"],
    };

    const evaluationMetricMap = {
      delivery_pass_rate: "交付通过率",
      average_quality_score: "平均质量分",
      traceable_claim_rate: "可追溯主张率",
      evidence_coverage_rate: "证据覆盖率",
      evidence_ready_task_rate: "证据召回可用率",
      source_quality_ready_task_rate: "关键来源覆盖率",
      verified_claim_rate: "主张校验通过率",
      numeric_consistency_rate: "数值一致性",
      citation_support_rate: "引用支持率",
      schema_valid_rate: "结构化输出有效率",
      llm_success_rate: "模型运行成功率",
      llm_cost_usd: "模型成本",
      average_llm_latency_ms: "平均耗时",
    };

    const statusMap = {
      queued: "待启动", running: "运行中", completed: "已完成", failed: "失败", timeout: "超时",
      cancelled: "已取消", archived: "已归档", quality_failed: "质量未通过", skipped: "已跳过",
      pending: "待复核", approved: "已通过", rejected: "已驳回", regenerate_requested: "已请求重生成",
      in_context: "已加入任务", dismissed: "已忽略",
      supported: "已支持", verified: "已验证", passed: "通过", success: "成功", done: "已完成", parsed: "已解析",
      warning: "需关注",
      blocked: "已阻断",
      official: "官方", primary: "一手", secondary: "二手", medium: "中可信", low: "低可信", high: "高可信", unknown: "未知",
      not_required: "无需凭证", required: "需配置", configured: "已配置", expired: "已过期",
      not_run: "未运行",
      company: "公司别名", product: "产品别名", metric: "财务指标", industry: "行业术语", risk: "风险词", exclude: "排除词",
      approve: "通过", reject: "驳回", edit: "保存修改", regenerate: "重生成",
      rejected_claims_present: "存在已驳回主张", pending_claim_review: "存在待复核主张",
      report_task_not_completed: "研报生成尚未完成", evidence_check_pending: "尚未完成证据检查",
      evidence_not_delivery_ready: "证据未达到正式交付要求", quality_check_pending: "尚未完成质量检查",
      quality_gate_failed: "质量门禁未通过", unsupported_claims_present: "存在未获证据支持的主张",
      claims_missing: "尚未生成主张", approved_claims_missing: "尚无审核通过的主张",
      report_artifact_missing: "缺少报告产物", export_ready: "可正式交付", review_required: "需要人工复核", remediation_required: "需要补证据或修复质量问题",
      in_progress: "处理中", complete_report_generation: "完成研报生成", resolve_rejected_claims: "处理已驳回主张",
      review_pending_claims: "复核待处理主张", run_evidence_gate: "执行证据检查",
      supplement_authoritative_evidence: "补充权威来源证据", run_quality_gate: "执行质量检查",
      resolve_quality_blockers: "处理质量阻塞", resolve_unsupported_claims: "处理未支持主张",
      import_or_generate_claims: "生成或导入主张", approve_supported_claims: "审核通过有证据支持的主张",
      generate_report_artifact: "生成报告产物",
      interrupted: "等待人工复核", resumed: "已从断点继续", checkpoint_retry: "断点重试",
	      filings: "公告/年报", documents: "文档资料", news: "新闻资料",
	      content_depth: "正文完整度不足", llm_review: "智能复核问题", verifier: "主张校验问题",
	      model_run_failure: "模型运行失败", claim_not_supported: "主张未获证据支持",
	      numeric_mismatch: "数字不一致", retrieval_gap: "证据召回缺口",
	    };
    const entityTypeMap = {
      company: "公司", ticker: "股票代码", industry: "行业", product: "产品", customer: "客户",
      supplier: "供应商", executive: "高管", metric: "财务指标", document: "文档",
      risk_event: "风险事件", news_event: "新闻事件", peer_company: "同行公司",
    };
    const relationTypeMap = {
      BELONGS_TO: "属于行业", PUBLISHED: "发布文档", HAS_PRODUCT: "拥有产品", HAS_METRIC: "关联指标",
      HAS_EVENT: "关联事件", PEER_OF: "同行对比", SUPPLIES_TO: "供应关系", MENTIONED_IN: "出现在文档",
    };
    const sourceMap = {
      local_real_data: "本地真实数据", local_evidence: "本地证据库", independent_macro: "宏观独立来源",
      sec_edgar: "美国证监会年报", cninfo: "巨潮资讯", cninfo_announcements: "巨潮资讯公告",
      exchange_announcements: "交易所公告", hkex: "港交所公告", hkex_announcements: "港交所公告",
      eastmoney: "东方财富行情", eastmoney_financials: "东方财富财务", sina_finance: "新浪财经行情",
      hk_financials: "港股财务数据", baostock_financials: "BaoStock 财务指标", tushare_financials: "Tushare Pro 财务", serper: "Serper 搜索", tavily: "Tavily 搜索",
      yahoo_finance: "雅虎财经",
      sec_filing: "SEC 披露文件", cninfo_announcement: "巨潮公告", hkex_announcement: "港交所公告",
      hkex_annual_report: "港交所年报", yahoo_profile: "雅虎公司画像", yahoo_financials: "雅虎财务数据",
      eastmoney_quote: "东方财富行情", news: "新闻",
      company_profile: "公司画像", market_api: "行情接口", market_data: "行情数据",
      financials: "财务数据", filing: "公告文件", filings: "公告文件", local_pdf: "本地文档",
      annual_report: "年报资料", quarterly_report: "季报资料", earnings_release: "业绩公告",
    };
    const stepMap = {
      ingest: "入库", parse: "解析", table_extract: "表格抽取", chunk: "切分", chunk_vectorize: "切分向量化",
      evidence: "证据化", claim_bind: "绑定主张", verify: "校验",
      evidence_gate: "生成前证据检查", evidence_gate_failed: "证据不足，已暂停生成",
      orchestrator: "多智能体执行", write_report: "撰写并保存研报", verify_report: "独立校验研报",
      inspect_agent_execution: "检查智能体执行", verify_sections: "校验章节合同",
      repair_failed_sections: "返工未通过章节", build_canonical_metrics: "统一正式指标",
      build_section_evidence_packs: "构建章节证据包", normalize_evidence: "清洗并统一证据",
      official_evidence_backfill: "补齐官方证据", finalize: "汇总交付状态", human_review: "人工复核",
      artifact_import: "产物导入", quality_gate: "质量门禁", quality: "质量门禁", completed: "完成",
      agent_planning: "规划研究任务", "agent.planning": "规划研究任务",
      agent_research: "检索研究资料", "agent.research": "检索研究资料",
      agent_browser: "读取与整理资料", "agent.browser": "读取与整理资料",
      agent_analyze: "财务与估值分析", "agent.analyze": "财务与估值分析",
      agent_final_answer: "撰写研报章节", "agent.final_answer": "撰写研报章节",
      agent_verifier: "校验主张与引用", "agent.verifier": "校验主张与引用",
      agent_gap_resolver: "补齐交付缺口", "agent.gap_resolver": "补齐交付缺口",
      agent_identity: "核对公司身份", "agent.identity": "核对公司身份",
      agent_peer: "分析同行公司", "agent.peer": "分析同行公司",
      agent_critic: "检查研究完整性", "agent.critic": "检查研究完整性",
      queued: "待启动", retry: "重试", failed: "失败", quality_failed: "质量未通过", cancelled: "已取消", archived: "已归档", claim_review: "主张复核",
      manual_import: "手动导入",
    };
    const docTypeMap = {
      report_artifact: "研报任务产物",
      generated_report_artifacts: "研报任务产物",
      annual_report: "年报",
      quarterly_report: "季报",
      earnings_release: "业绩公告",
      manual_text: "手动文本",
      manual_pdf: "手动 PDF",
      manual_url: "手动链接",
    };
    const artifactMap = {
      html: "网页报告", markdown: "文稿", json: "结构化数据",
      claims: "主张数据", evidence: "证据数据", verification_report: "校验报告",
      run_summary: "运行摘要", delivery_gate: "交付门禁", quality_report: "质量报告",
      llm_quality_review: "大模型质检", quality_remediation_plan: "修复计划",
    };
    const dataSourceScopeMap = {
      official_first: "官方公告优先",
      all_available: "全部可用来源",
      local_only: "仅本地文档",
    };
    const chartColors = ["#1677ff", "#0f8f7a", "#b56a00", "#7c3aed", "#d92d20", "#475467"];
    const funnelDemoSteps = [
      { key: "raw_document_ingested", label: "原始资料入库", count: 1280 },
      { key: "parsed_success", label: "解析成功", count: 1146 },
      { key: "table_extracted", label: "表格抽取成功", count: 823 },
      { key: "chunk_vectorized", label: "切分向量化", count: 790 },
      { key: "financial_fact_extracted", label: "财务事实提取", count: 356 },
      { key: "investment_signal_generated", label: "投资线索生成", count: 126 },
      { key: "report_claim_generated", label: "研报主张生成", count: 72 },
      { key: "claim_verified", label: "主张校验通过", count: 58 },
      { key: "manual_review_pending", label: "待人工复核", count: 14 },
    ];
    const funnelTargets = {
      document_ingested: { view: "documents", documentStep: "ingest" },
      raw_document_ingested: { view: "documents", documentStep: "ingest" },
      parse_success: { view: "documents", documentStep: "parse" },
      parsed_success: { view: "documents", documentStep: "parse" },
      table_extract_success: { view: "documents", documentStep: "table_extract" },
      table_extracted: { view: "documents", documentStep: "table_extract" },
      chunk_vectorized: { view: "documents", documentStep: "chunk" },
      financial_fact_extracted: { view: "facts" },
      investment_signal_generated: { view: "signals" },
      report_claim_generated: { view: "claims" },
      claim_verified: { view: "claims", claimVerification: "supported" },
      pending_review: { view: "claims", claimStatus: "pending" },
      manual_review_pending: { view: "claims", claimStatus: "pending" },
    };
    const companyCandidates = [
      { name: "苹果", aliases: ["苹果", "苹果公司", "Apple", "AAPL"], symbol: "AAPL" },
      { name: "英伟达", aliases: ["英伟达", "NVIDIA", "NVDA"], symbol: "NVDA" },
      { name: "特斯拉", aliases: ["特斯拉", "Tesla", "TSLA"], symbol: "TSLA" },
      { name: "微软", aliases: ["微软", "Microsoft", "MSFT"], symbol: "MSFT" },
      { name: "腾讯控股", aliases: ["腾讯", "腾讯控股", "Tencent", "0700.HK"], symbol: "0700.HK" },
      { name: "阿里巴巴", aliases: ["阿里", "阿里巴巴", "Alibaba", "BABA", "9988.HK"], symbol: "BABA" },
      { name: "贵州茅台", aliases: ["贵州茅台", "茅台", "600519"], symbol: "600519" },
      { name: "宁德时代", aliases: ["宁德时代", "CATL", "300750"], symbol: "300750" },
      { name: "比亚迪", aliases: ["比亚迪", "BYD", "002594", "1211.HK"], symbol: "002594" },
    ];
    const textOf = (map, value) => map[String(value || "")] || fmt(value);
    const statusText = (value) => textOf(statusMap, value);
    const sourceText = (value) => textOf(sourceMap, value);
	    function productText(value) {
	      const mappedValue = statusMap[String(value || "")] || "";
	      let text = mappedValue || fmt(value);
      const replacements = [
	        [/\bcontent_depth\b/g, "正文完整度"],
	        [/\bllm_review\b/g, "智能复核"],
	        [/\bverifier\b/g, "主张校验"],
	        [/\bagent\.planning\b/g, "任务规划智能体"],
	        [/\bagent\.research\b/g, "资料检索智能体"],
	        [/\bagent\.browser\b/g, "网页读取智能体"],
	        [/\bagent\.analyze\b/g, "分析智能体"],
	        [/\bagent\.risk\b/g, "风险分析智能体"],
	        [/\bagent\.peer\b/g, "同行分析智能体"],
	        [/\bagent\.gap_resolver\b/g, "证据补齐智能体"],
	        [/\bclaim_verifier\b/g, "主张校验"],
        [/\bsec_edgar\b/g, "美国证监会披露"],
        [/\bevidence_ids\b/g, "证据绑定"],
        [/\bevidence_id\b/g, "证据追踪号"],
        [/\bquality_failed\b/g, "质量未通过"],
        [/\bevidence_gate_failed\b/g, "证据不足，已暂停生成"],
        [/\bcitation_gap\b/g, "正文引用待补齐"],
        [/\bsource_gap\b/g, "来源缺口"],
        [/\bdelivery_pass\b/g, "正式交付状态"],
      ];
      replacements.forEach(([pattern, label]) => { text = text.replace(pattern, label); });
      return text;
    }
    function sourceDisplayText(value) {
      const raw = String(value || "").trim();
      if (!raw) return "未知来源";
      const mapped = sourceText(raw);
      if (mapped !== raw) return mapped;
      if (/official|filing|announcement/i.test(raw)) return "官方披露资料";
      if (/market|quote|price/i.test(raw)) return "行情与估值数据";
      if (/news|web|search/i.test(raw)) return "公开网页资料";
      return productText(raw);
    }
    const stepText = (value) => textOf(stepMap, value);
    const docTypeText = (value) => textOf(docTypeMap, value);
    const artifactText = (value) => textOf(artifactMap, value);
    const entityTypeText = (value) => textOf(entityTypeMap, value);
    const relationTypeText = (value) => textOf(relationTypeMap, value);
    const signalTypeMap = {
      margin_decline: "利润率下滑",
      cashflow_gap: "利润与现金流背离",
      official_source_missing: "官方来源缺口",
      currency_mismatch: "币种口径不一致",
      valuation_blocked: "估值资料不足",
      revenue_growth_acceleration: "收入增速改善",
    };
    const signalCategoryMap = {
      profitability: "盈利能力",
      cashflow: "现金流",
      source_gap: "证据缺口",
      data_quality: "数据质量",
      valuation: "估值口径",
      growth: "成长变化",
      research: "研究线索",
    };
    const signalDirectionMap = { positive: "正向", negative: "负向", neutral: "中性" };
    const signalSeverityMap = { high: "高", medium: "中", low: "低" };
    const signalTypeText = (value) => textOf(signalTypeMap, value);
    const signalCategoryText = (value) => textOf(signalCategoryMap, value);
    const signalDirectionText = (value) => textOf(signalDirectionMap, value);
    const signalSeverityText = (value) => textOf(signalSeverityMap, value);

    function marketText(value) {
      const map = { US: "美股", CN: "A 股", HK: "港股" };
      return textOf(map, value);
    }

    function marketValue(value) {
      const text = String(value || "").trim();
      const map = {
        美股: "US",
        "A股": "CN",
        "A 股": "CN",
        港股: "HK",
      };
      return map[text] || text;
    }

    function sourceKeyValue(value) {
      const text = String(value || "").trim();
      if (!text) return "";
      const sourceInput = $("ingestionSource");
      if (sourceInput && sourceInput.value.trim() === text && sourceInput.dataset.sourceKey) return sourceInput.dataset.sourceKey;
      const direct = Object.entries(sourceMap).find(([, label]) => label === text);
      return direct ? direct[0] : text;
    }

    function promptModuleText(value) {
      const map = {
        verifier: "主张校验",
        fact_extractor: "事实抽取",
        writer: "研报撰写",
        researcher: "资料检索",
        planner: "任务规划",
        "claim_verifier": "主张校验",
        "agent.writer": "研报撰写",
        "agent.verifier": "报告校验",
        "agent.planner": "任务规划",
        "agent.researcher": "资料检索",
        "agent.research": "资料研究",
        "agent.browser": "网页检索",
        "agent.analyze": "深度分析",
        "agent.final_answer": "最终研报",
        "agent.gap_resolver": "证据缺口修复",
        "agent.planning": "任务规划",
      };
      return textOf(map, value);
    }

    function promptModuleValue(value) {
      const text = String(value || "").trim();
      const map = {
        主张校验: "verifier",
        报告校验: "verifier",
        事实抽取: "fact_extractor",
        研报撰写: "writer",
        资料检索: "researcher",
        任务规划: "planner",
      };
      return map[text] || text;
    }

    function metricTypeText(value) {
      const map = {
        money: "金额",
        ratio: "比例",
        percent: "百分比",
        count: "数量",
        per_share: "每股指标",
        valuation: "估值指标",
        growth: "增长率",
      };
      return textOf(map, value);
    }

    function modelDisplayText(value) {
      const map = {
        unknown: "未记录",
        "claim-verifier-rules": "规则校验",
        "rule-verifier": "规则校验",
        "local-rules": "本地规则",
      };
      return textOf(map, value);
    }

    function severityText(value) {
      const map = {
        fatal: "致命",
        blocker: "阻塞",
        warning: "提醒",
        info: "信息",
        error: "错误",
      };
      return textOf(map, value);
    }

    function qualityCategoryText(value) {
      const map = {
        blocker: "阻塞问题",
        warning: "提醒问题",
        info: "信息提示",
        citation_missing: "引用缺失",
        citation_or_evidence_gap: "证据链缺口",
        evidence: "证据不足",
        quality_gate_blocker: "质量门禁阻塞",
        runtime_or_model_failure: "运行或模型失败",
        chart_text_mismatch: "图表文字不一致",
        source_access_or_fetch: "来源访问失败",
        valuation: "估值口径",
        period: "期间错配",
	        llm_review: "智能复核",
	        content_depth: "正文完整度",
	        verifier: "主张校验",
	        numeric: "数字核验",
        structure: "结构完整性",
        freshness: "时效性",
      };
      return textOf(map, value);
    }

    function marketScopeText(values) {
      const items = Array.isArray(values) ? values : [];
      return items.length ? items.map(marketText).join("、") : "未限定";
    }

    function renderSourceList(values) {
      const items = Array.isArray(values) ? values : [];
      return items.length ? items.map(sourceDisplayText).map(esc).join("、") : "-";
    }

    function sourcePurposeText(item) {
      const key = String(item?.source_key || "");
      const type = String(item?.source_type || "");
      const map = {
        local_real_data: "离线回归和样例演示",
        local_evidence: "本地资料补充检索",
        independent_macro: "利率、通胀、就业等宏观背景",
        sec_edgar: "美股公司年报、季报和 XBRL 财务事实",
        cninfo_announcements: "A 股公告和年报 PDF",
        exchange_announcements: "交易所公告补充",
        hkex_announcements: "港股公告和年报",
        eastmoney_financials: "A 股结构化三表和关键财务指标",
        eastmoney: "A 股实时行情和估值倍数",
        sina_finance: "行情数据补充",
        yahoo_finance: "海外与港股行情、公司画像和财务摘要",
        hk_financials: "港股结构化财务补充",
        serper: "公开网页搜索补充",
        tavily: "公开网页搜索和新闻补充",
      };
      if (map[key]) return map[key];
      if (type === "official_filing" || type === "official_announcement") return "官方披露和公告核验";
      if (type === "financial_statement") return "结构化财务事实提取";
      if (type === "market_data") return "行情、估值和交易数据补充";
      if (type === "web_search") return "公开网页和新闻搜索补充";
      if (type === "macro_data") return "宏观环境和政策背景补充";
      if (type === "local_dataset" || type === "local_index") return "本地资料和回归样例";
      return "外部资料补充";
    }

    function credentialText(value) {
      const map = {
        not_required: "无需配置",
        required: "需要配置密钥",
        missing: "缺少凭证",
        configured: "已配置",
        expired: "已过期",
      };
      return textOf(map, value);
    }

    function systemInfoBlock(title, rows) {
      const validRows = rows.filter(([, value]) => value != null && value !== "");
      if (!validRows.length) return "";
      return `<details class="detail-section"><summary>${esc(systemInfoTitle(title))}</summary>${
        validRows.map(([label, value]) => `<div class="kv"><span class="label">${esc(systemLabelText(label))}</span><span class="mono">${esc(systemValueText(label, value))}</span></div>`).join("")
      }</details>`;
    }

    function systemInfoTitle(title) {
      return title === "文件信息" ? "文件追踪信息" : "技术追踪信息";
    }

    function systemLabelText(label) {
      const map = {
        任务编号: "任务追踪号",
        数据源标识: "来源追踪号",
        空间编号: "投研空间号",
        批次编号: "采集批次号",
        文件路径: "本地文件位置",
        提示词标识: "提示词追踪号",
        运行编号: "运行追踪号",
        证据编号: "证据追踪号",
        实体编号: "实体追踪号",
        实体键: "实体索引键",
        来源证据: "来源证据号",
        关系编号: "关系追踪号",
        关系键: "关系索引键",
        事实编号: "事实追踪号",
        线索编号: "线索追踪号",
        规则: "线索类型",
        来源规则: "触发规则",
        主张编号: "主张追踪号",
      };
      return map[label] || label;
    }

    function systemValueText(label, value) {
      if (label === "数据源标识") return `${sourceDisplayText(value)} (${fmt(value)})`;
      if (label === "规则" || label === "来源规则") return signalTypeText(value);
      return fmt(value);
    }

    function evidenceDisplayTitle(item) {
      return item?.title || sourceDisplayText(item?.source_type) || "证据片段";
    }

    function renderEvidenceSearchSummary(item) {
      const info = item?.search;
      if (!info) return `<span class="score-note">按筛选条件展示</span>`;
      const reasons = (info.reasons || []).slice(0, 3);
      const rank = info.rank ? `第 ${esc(info.rank)} 位` : "智能排序";
      return `<div><strong>${rank}</strong><div class="reason-list">${
        reasons.length ? reasons.map((reason) => `<span class="reason-pill">${esc(reason)}</span>`).join("") : `<span class="reason-pill">相关证据</span>`
      }</div></div>`;
    }

    function renderEvidenceSearchDetail(info) {
      if (!info) return "";
      const reasons = info.reasons || [];
      const terms = info.matched_terms || [];
      return `<div class="detail-section"><h3>检索说明</h3>
        <div class="kv"><span class="label">排序</span><span>${esc(info.rank ? "第 " + info.rank + " 位" : "智能排序")}</span></div>
        <div class="kv"><span class="label">来源</span><span>${esc((info.rank_sources || []).map(searchSourceText).join(" / ") || "证据质量排序")}</span></div>
        <div class="reason-list">${reasons.length ? reasons.map((reason) => `<span class="reason-pill">${esc(reason)}</span>`).join("") : `<span class="reason-pill">相关证据</span>`}</div>
        ${terms.length ? `<div class="score-note">命中关键词：${esc(terms.join("、"))}</div>` : ""}
        <div class="score-note">检索排序仅用于辅助定位资料，研报事实仍以原文证据、主张校验和人工复核为准。</div>
      </div>`;
    }

    function searchSourceText(value) {
      const map = {
        keyword: "关键词召回",
        evidence_quality: "证据质量排序",
      };
      return textOf(map, value);
    }

    function entityTitle(entity) {
      const name = entity?.canonical_name || "实体";
      const symbol = entity?.symbol ? ` / ${entity.symbol}` : "";
      return `${name}${symbol}`;
    }

    function entityMarketSymbolText(entity) {
      const parts = [];
      if (entity?.market) parts.push(marketText(entity.market));
      if (entity?.symbol) parts.push(entity.symbol);
      return parts.length ? parts.join(" · ") : "-";
    }

    function entityDescriptionText(entity) {
      const value = String(entity?.description || "");
      const map = {
        revenue: "收入相关指标",
        gross_margin: "毛利率相关指标",
        net_income: "净利润相关指标",
        free_cash_flow: "自由现金流指标",
        operating_cash_flow: "经营现金流指标",
        valuation: "估值相关指标",
        supply_chain_risk: "供应链相关风险",
        margin_pressure: "利润率压力风险",
        demand_risk: "需求相关风险",
        regulatory_risk: "监管或政策风险",
      };
      if (entity?.entity_type === "document" && value) return docTypeText(value);
      return map[value] || value || "结构化业务记忆";
    }

    function evidenceSourceButton(evidenceId) {
      return evidenceId
        ? `<button class="btn" data-entity-evidence="${esc(evidenceId)}">查看证据来源</button>`
        : `<span class="label">暂无证据来源</span>`;
    }

    function relationTitle(relation) {
      const source = relation?.source?.canonical_name || "来源实体";
      const target = relation?.target?.canonical_name || "目标实体";
      return `${source} → ${relationTypeText(relation?.relation_type)} → ${target}`;
    }

    function batchDisplayTitle(batch) {
      if (batch?.name) return batch.name;
      const symbolPeriod = [batch?.symbol, batch?.period].filter(Boolean).join(" · ");
      return symbolPeriod || "采集批次";
    }

    function exportDisplayTitle(item) {
      const company = item?.company_name || item?.symbol || "研报";
      return `${company} · ${item?.period || "-"}`;
    }

    function exportFormatText(value) {
      const map = { json: "JSON", markdown: "Markdown", html: "HTML", pdf: "PDF", docx: "DOCX", manifest: "导出清单", claims_csv: "主张 CSV", evidence_csv: "证据 CSV", facts_csv: "财务事实 CSV", review_csv: "复核记录 CSV" };
      return textOf(map, value);
    }

    function exportCsvText(value) {
      const map = { claims: "主张表", evidence: "证据表", financial_facts: "财务事实表", review_records: "复核记录表" };
      return textOf(map, value);
    }

    function claimTaskText(claim) {
      const task = claim?.task || claim?.report_task || {};
      const company = task.metadata?.company_name || task.company_name || task.symbol || claim?.symbol;
      const period = task.period || claim?.period;
      if (company || period) return [company || "研报任务", period].filter(Boolean).join(" · ");
      return "研报任务";
    }

    function stepMetadataText(metadata) {
      const data = metadata || {};
      const items = [];
      if (data.artifact_count != null) items.push(`产物 ${number(data.artifact_count)} 个`);
      if (Array.isArray(data.artifact_types) && data.artifact_types.length) {
        items.push(`产物类型：${data.artifact_types.map(artifactText).join("、")}`);
      }
      if (Array.isArray(data.report_files) && data.report_files.length) {
        items.push(`报告文件：${data.report_files.join("、")}`);
      }
      if (data.financial_fact_count != null) items.push(`财务事实 ${number(data.financial_fact_count)} 条`);
      if (data.evidence_count != null) items.push(`证据 ${number(data.evidence_count)} 条`);
      if (data.claim_count != null) items.push(`主张 ${number(data.claim_count)} 条`);
      if (data.claim_evidence_count != null) items.push(`证据绑定 ${number(data.claim_evidence_count)} 条`);
      if (data.verification_exists != null) items.push(`校验文件：${data.verification_exists ? "已生成" : "未生成"}`);
      if (data.verification_passed != null) items.push(`校验结果：${data.verification_passed ? "通过" : "未通过"}`);
      return items.length ? items.join("；") : "无附加信息";
    }
    const dataSourceScopeText = (value) => textOf(dataSourceScopeMap, value);
    const shortTaskId = (value) => {
      const text = String(value || "");
      return text.length > 18 ? `${text.slice(0, 10)}...${text.slice(-5)}` : text;
    };

    document.querySelectorAll(".nav button").forEach((btn) => {
      btn.addEventListener("click", () => activateView(btn.dataset.view));
    });
    bindJumpHandlers();
    document.querySelectorAll("[data-funnel-tab]").forEach((btn) => {
      btn.addEventListener("click", () => activateFunnelTab(btn.dataset.funnelTab));
    });
    initCreateTaskModal();
    activateFunnelTab("chain");

    function activateFunnelTab(tab) {
      document.querySelectorAll("[data-funnel-tab]").forEach((item) => item.classList.toggle("active", item.dataset.funnelTab === tab));
      $("funnelTab").classList.toggle("active", tab === "funnel");
      $("chainTab").classList.toggle("active", tab === "chain");
      $("funnelDemoNote").hidden = tab !== "funnel";
    }

    function bindJumpHandlers(root = document) {
      root.querySelectorAll("[data-jump]").forEach((btn) => {
        if (btn.dataset.boundJump === "true") return;
        btn.dataset.boundJump = "true";
        btn.addEventListener("click", () => jumpTo(btn.dataset.jump, btn.dataset));
      });
    }

    function bindCreateTaskButtons(root = document) {
      root.querySelectorAll("[data-open-create-task]").forEach((btn) => {
        if (btn.dataset.boundCreateTask === "true") return;
        btn.dataset.boundCreateTask = "true";
        btn.addEventListener("click", openCreateTaskModal);
      });
    }

    function jumpTo(view, options = {}) {
      if (view === "claims") {
        if (options.claimStatus && $("claimStatus")) $("claimStatus").value = options.claimStatus;
        if (options.claimVerification && $("claimVerification")) $("claimVerification").value = options.claimVerification;
      }
      if (view === "documents" && options.documentStep && $("documentStep")) $("documentStep").value = options.documentStep;
      if (view === "datasources" && options.datasourceQuery && $("datasourceQuery")) $("datasourceQuery").value = sourceText(options.datasourceQuery);
      if (view === "ingestion") {
        if (options.ingestionSource && $("ingestionSource")) {
          $("ingestionSource").value = sourceText(options.ingestionSource);
          $("ingestionSource").dataset.sourceKey = options.ingestionSource;
        }
        if (options.ingestionQuery && $("ingestionQuery")) $("ingestionQuery").value = options.ingestionQuery;
      }
      if (view === "signals") {
        if (options.signalTaskId) {
          activeSignalTaskScope = {
            taskId: options.signalTaskId,
            company: options.signalCompany || "",
            period: options.signalPeriod || "",
          };
          if ($("signalCompany")) $("signalCompany").value = activeSignalTaskScope.company;
          if ($("signalPeriod")) $("signalPeriod").value = activeSignalTaskScope.period;
        } else {
          activeSignalTaskScope = null;
        }
      }
      activateView(view);
    }

    function showNotice(message, type = "empty") {
      const notice = $("workbenchNotice");
      if (!notice) return;
      notice.innerHTML = message ? `<div class="${esc(type)}">${esc(message)}</div>` : "";
    }

    function activateView(view) {
      activeState.view = view;
      document.querySelectorAll(".nav button").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
      document.querySelectorAll(".view").forEach((item) => {
        const active = item.id === view;
        item.classList.toggle("active", active);
        item.hidden = !active;
        item.setAttribute("aria-hidden", active ? "false" : "true");
        if (active) item.removeAttribute("inert");
        else item.setAttribute("inert", "");
        setFormLabelsActive(item, active);
      });
      const meta = viewMeta[view] || [view, ""];
      $("viewTitle").textContent = meta[0];
      $("viewSubtitle").textContent = meta[1];
      if (view === "dashboard") loadDashboard();
      else if (view === "workspace") loadWorkspaces();
      else if (view === "stockpool") loadStockpool();
      else if (view === "datasources") loadDatasources();
      else if (view === "ingestion") loadIngestionBatches();
      else if (view === "manual") updateManualImportFields();
      else if (view === "facts") loadFinancialFacts();
      else if (view === "signals") loadSignals();
      else if (view === "tasks") loadTasks();
      else if (view === "evidence") loadEvidence();
      else if (view === "documents") loadDocuments();
      else if (view === "claims") loadClaims();
      else if (view === "dictionary") loadDictionary();
      else if (view === "promptops") loadPromptOps();
      else if (view === "entities") loadEntities();
      else if (view === "graph") loadRelations();
      else if (view === "evaluation") loadEvaluation();
      else if (view === "export") loadExports();
      else renderPlaceholder(view);
    }

    function setFormLabelsActive(container, active) {
      container.querySelectorAll("label").forEach((label) => {
        if (active && label.dataset.labelFor) {
          label.setAttribute("for", label.dataset.labelFor);
        } else if (!active && label.hasAttribute("for")) {
          label.dataset.labelFor = label.getAttribute("for");
          label.removeAttribute("for");
        }
      });
    }

    async function openDocumentsForBatch(batchId, documentId = null) {
      activateView("documents");
      if ($("documentBatch")) $("documentBatch").value = batchId || "";
      await loadDocuments();
      if (documentId) await loadDocumentDetail(documentId);
    }

    async function getJson(url) {
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || JSON.stringify(data));
      return data;
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

    function showLoadError(targetId, colspan) {
      const text = "数据加载失败，请检查服务和数据库配置。";
      if (colspan) $(targetId).innerHTML = `<tr><td colspan="${colspan}"><div class="error">${text}</div></td></tr>`;
      else $(targetId).innerHTML = `<div class="error">${text}</div>`;
    }

    function emptyBox(text, actions = []) {
      const buttons = actions.length
        ? `<div class="empty-actions">${actions.map((item) => `<button class="btn ${esc(item.className || "")}" data-jump="${esc(item.view)}"${item.claimStatus ? ` data-claim-status="${esc(item.claimStatus)}"` : ""}${item.claimVerification ? ` data-claim-verification="${esc(item.claimVerification)}"` : ""}${item.documentStep ? ` data-document-step="${esc(item.documentStep)}"` : ""}>${esc(item.label)}</button>`).join("")}</div>`
        : "";
      return `<div class="empty"><div>${esc(text)}</div>${buttons}</div>`;
    }

    function initCreateTaskModal() {
      bindCreateTaskButtons();
      $("companyCandidates").innerHTML = companyCandidates.flatMap((item) => item.aliases.map((alias) => `<option value="${esc(alias)}">${esc(item.name)} · ${esc(item.symbol)}</option>`)).join("");
      const quickSymbols = ["AAPL", "0700.HK", "600519", "NVDA", "9988.HK", "300750"];
      const quickCandidates = quickSymbols.map((symbol) => companyCandidates.find((item) => item.symbol === symbol || item.aliases.includes(symbol))).filter(Boolean);
      $("companyQuickChoices").innerHTML = quickCandidates.map((item) => `<button class="choice" type="button" data-company-choice="${esc(item.symbol)}">${esc(item.name)} · ${esc(item.symbol)}</button>`).join("");
      document.querySelectorAll("[data-company-choice]").forEach((btn) => {
        btn.addEventListener("click", () => {
          $("taskCompanyInput").value = btn.dataset.companyChoice;
          updateCompanyResolveNote();
        });
      });
      document.querySelectorAll("[data-close-create-task]").forEach((btn) => btn.addEventListener("click", closeCreateTaskModal));
      $("createTaskModal").addEventListener("click", (event) => {
        if (event.target === $("createTaskModal")) closeCreateTaskModal();
      });
      $("taskCompanyInput").addEventListener("input", updateCompanyResolveNote);
      $("createTaskForm").addEventListener("submit", submitCreateTask);
      updateCompanyResolveNote();
      setFormLabelsActive($("createTaskModal"), false);
    }

    function openCreateTaskModal() {
      $("createTaskModal").classList.add("active");
      setFormLabelsActive($("createTaskModal"), true);
      $("createTaskMessage").innerHTML = "";
      setTimeout(() => $("taskCompanyInput").focus(), 0);
    }

    function closeCreateTaskModal() {
      $("createTaskModal").classList.remove("active");
      setFormLabelsActive($("createTaskModal"), false);
    }

    function resolveCompany(input) {
      const raw = String(input || "").trim();
      if (!raw) return null;
      const lower = raw.toLowerCase();
      const matched = companyCandidates.find((item) => item.aliases.some((alias) => String(alias).toLowerCase() === lower));
      if (matched) return matched;
      return { name: raw, aliases: [raw], symbol: raw.toUpperCase() };
    }

    function updateCompanyResolveNote() {
      const resolved = resolveCompany($("taskCompanyInput").value);
      $("companyResolveNote").textContent = resolved
        ? `将按 ${resolved.name} · ${resolved.symbol} 创建任务。`
        : "支持公司中文名、英文名或股票代码；优先解析当前投研空间股票池，未命中时使用本地公司候选。";
    }

    async function submitCreateTask(event) {
      event.preventDefault();
      const resolved = await resolveCompanyForTask($("taskCompanyInput").value);
      if (!resolved) {
        $("createTaskMessage").innerHTML = `<div class="error">请输入公司名称或股票代码。</div>`;
        return;
      }
      const runMode = $("taskRunModeInput").value;
      const evidenceGateMode = $("taskEvidenceGateInput").value;
      const payload = {
        symbol: resolved.symbol,
        period: $("taskPeriodInput").value,
        report_type: $("taskReportTypeInput").value,
        research_topic: $("taskTopicInput").value.trim(),
        data_source_scope: $("taskDataSourceInput").value,
        enforce_evidence_gate: evidenceGateMode === "enforce",
        allow_weak_evidence: evidenceGateMode === "allow_weak",
        skip_evidence_gate: evidenceGateMode === "skip",
        company_name: resolved.name,
        workspace_id: resolved.workspace_id || undefined,
        company_id: resolved.company_id || undefined,
        run_immediately: runMode === "async",
        run_async: runMode === "async",
      };
      $("createTaskMessage").innerHTML = `<div class="empty">正在创建任务...</div>`;
      try {
        const task = await postJson("/api/report-tasks", payload);
        $("createTaskMessage").innerHTML = `<div class="empty">任务已创建，已进入研报任务列表。</div>`;
        closeCreateTaskModal();
        activateView("tasks");
        await loadTasks();
        loadTaskDetail(task.task_id);
        showNotice(`研报任务已创建：${task.company_name || task.symbol || "新任务"} · ${task.period || ""}`);
        loadDashboard();
      } catch (error) {
        $("createTaskMessage").innerHTML = `<div class="error">创建失败，请检查服务配置或稍后重试。</div>`;
      }
    }

    async function resolveCompanyForTask(input) {
      const raw = String(input || "").trim();
      if (!raw) return null;
      let workspace = null;
      try {
        const workspaces = await getJson("/api/workspaces?active_only=true&limit=1");
        workspace = (workspaces.items || [])[0];
        if (workspace) {
          const item = await getJson(`/api/workspaces/${encodeURIComponent(workspace.id)}/resolve-company?q=${encodeURIComponent(raw)}`);
          return {
            name: item.name,
            symbol: item.symbol,
            workspace_id: item.workspace_id,
            company_id: item.company_id,
          };
        }
      } catch (error) {
        const fallback = resolveCompany(raw);
        return fallback ? { ...fallback, workspace_id: workspace?.id || null } : null;
      }
      const fallback = resolveCompany(raw);
      return fallback ? { ...fallback, workspace_id: workspace?.id || null } : null;
    }

    function csvList(value) {
      return String(value || "").split(/[,，\\n]/).map((item) => item.trim()).filter(Boolean);
    }

    function renderList(values) {
      const items = Array.isArray(values) ? values : [];
      return items.length ? items.map((item) => esc(item)).join("、") : "-";
    }

    async function loadWorkspaces() {
      try {
        const payload = await getJson("/api/workspaces");
        const rows = payload.items || [];
        $("workspaceRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-workspace-stockpool="${esc(item.id)}">${esc(item.name)}</button><br><span class="label">${esc(item.description || "投研空间")}</span></td>
              <td>${esc(marketText(item.market))}</td>
              <td>${esc(number(item.active_company_count))} / ${esc(number(item.company_count))}</td>
              <td>${renderList(item.focus_metrics)}</td>
              <td>${renderList(item.risk_types)}</td>
              <td>${renderSourceList(item.default_data_sources)}</td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">暂无投研空间</div></td></tr>`;
        bindWorkspaceButtons($("workspaceRows"));
        await populateWorkspaceSelect(rows, $("stockpoolWorkspace").value);
      } catch (error) {
        showLoadError("workspaceRows", 6);
      }
    }

    function bindWorkspaceButtons(root = document) {
      root.querySelectorAll("[data-workspace-stockpool]").forEach((btn) => {
        if (btn.dataset.boundWorkspaceStockpool === "true") return;
        btn.dataset.boundWorkspaceStockpool = "true";
        btn.addEventListener("click", () => {
          activateView("stockpool");
          $("stockpoolWorkspace").value = btn.dataset.workspaceStockpool;
          loadStockpool();
        });
      });
    }

    async function createWorkspace() {
      const payload = {
        name: $("workspaceName").value.trim(),
        slug: $("workspaceSlug").value.trim(),
        market: marketValue($("workspaceMarket").value),
        focus_metrics: csvList($("workspaceMetrics").value),
        risk_types: csvList($("workspaceRisks").value),
        default_data_sources: csvList($("workspaceSources").value),
      };
      if (!payload.name) {
        $("workspaceMessage").innerHTML = `<div class="error">请输入空间名称。</div>`;
        return;
      }
      try {
        const created = await postJson("/api/workspaces", payload);
        $("workspaceMessage").innerHTML = `<div class="empty">已创建投研空间：${esc(created.name)}</div>`;
        await loadWorkspaces();
      } catch (error) {
        $("workspaceMessage").innerHTML = `<div class="error">创建失败，空间标识可能已存在。</div>`;
      }
    }

    async function populateWorkspaceSelect(existingRows = null, preferredValue = "") {
      const rows = existingRows || (await getJson("/api/workspaces")).items || [];
      $("stockpoolWorkspace").innerHTML = rows.length
        ? rows.map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")
        : `<option value="">暂无投研空间</option>`;
      if (preferredValue && rows.some((item) => String(item.id) === String(preferredValue))) {
        $("stockpoolWorkspace").value = preferredValue;
      }
    }

    async function loadStockpool() {
      try {
        const workspaces = await getJson("/api/workspaces");
        const previousSelection = $("stockpoolWorkspace").value;
        await populateWorkspaceSelect(workspaces.items || [], previousSelection);
        const selected = $("stockpoolWorkspace").value || ((workspaces.items || [])[0]?.id ?? "");
        if (!selected) {
          $("stockpoolRows").innerHTML = `<tr><td colspan="6"><div class="empty">请先创建投研空间</div></td></tr>`;
          return;
        }
        $("stockpoolWorkspace").value = selected;
        const query = $("stockpoolQuery").value.trim();
        const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
        const payload = await getJson(`/api/workspaces/${encodeURIComponent(selected)}/companies${suffix}`);
        const rows = payload.items || [];
        $("stockpoolRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><strong>${esc(item.name)}</strong><br><span class="label mono">${esc(item.symbol)}</span></td>
              <td>${esc(marketText(item.market))}</td>
              <td>${esc(item.industry || "-")}</td>
              <td>${renderList(item.aliases)}</td>
              <td>${renderList(item.focus_metrics)}</td>
              <td>${renderList(item.risk_types)}</td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">暂无股票池公司</div></td></tr>`;
      } catch (error) {
        showLoadError("stockpoolRows", 6);
      }
    }

    async function addStockCompany() {
      const workspaceId = $("stockpoolWorkspace").value;
      if (!workspaceId) {
        $("stockpoolMessage").innerHTML = `<div class="error">请先创建或选择投研空间。</div>`;
        return;
      }
      const payload = {
        name: $("stockCompanyName").value.trim(),
        symbol: $("stockSymbol").value.trim(),
        market: marketValue($("stockMarket").value),
        industry: $("stockIndustry").value.trim(),
        aliases: csvList($("stockAliases").value),
      };
      if (!payload.name || !payload.symbol) {
        $("stockpoolMessage").innerHTML = `<div class="error">请输入公司名称和股票代码。</div>`;
        return;
      }
      try {
        const item = await postJson(`/api/workspaces/${encodeURIComponent(workspaceId)}/companies`, payload);
        $("stockpoolMessage").innerHTML = `<div class="empty">已添加：${esc(item.name)} / ${esc(item.symbol)}</div>`;
        await loadStockpool();
      } catch (error) {
        $("stockpoolMessage").innerHTML = `<div class="error">添加失败，该公司可能已在当前股票池。</div>`;
      }
    }

    function datasourceTypeText(value) {
      const map = {
        official_filing: "官方年报",
        official_announcement: "官方公告",
        financial_statement: "财务报表",
        market_data: "行情数据",
        web_search: "网页搜索",
        local_dataset: "本地数据",
        local_index: "本地索引",
        macro_data: "宏观数据",
        external: "外部来源",
      };
      return textOf(map, value);
    }

    async function loadDatasources() {
      const params = new URLSearchParams();
      const q = $("datasourceQuery").value.trim();
      const enabled = $("datasourceEnabled").value;
      if (q) params.set("q", sourceKeyValue(q));
      if (enabled) params.set("enabled", enabled);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/data-sources" + suffix);
        const rows = payload.items || [];
        $("datasourceRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-datasource-detail="${esc(item.id)}">${esc(item.name || sourceText(item.source_key))}</button><br><span class="label">${esc(sourcePurposeText(item))}</span></td>
              <td>${esc(datasourceTypeText(item.source_type))}</td>
              <td>${esc(marketScopeText(item.market_scope))}</td>
              <td><span class="status ${esc(item.trust_level || "secondary")}">${esc(statusText(item.trust_level || "secondary"))}</span></td>
              <td><span class="status ${esc(item.credential_status)}">${esc(credentialText(item.credential_status))}</span></td>
              <td><span class="status ${esc(item.last_status || "pending")}">${esc(statusText(item.last_status || "pending"))}</span><br><span class="label">${esc(fmt(item.last_sync_at))}</span></td>
              <td class="links">
                <button class="btn" data-datasource-toggle="${esc(item.id)}" data-enabled="${item.enabled ? "false" : "true"}" ${!item.enabled && item.configured === false ? 'disabled title="请先配置凭证"' : ""}>${item.enabled ? "停用" : "启用"}</button>
                <button class="btn" data-datasource-health="${esc(item.id)}">查看状态说明</button>
              </td>
            </tr>`).join("")
          : `<tr><td colspan="7"><div class="empty"><div>暂无数据源</div><div class="empty-actions"><button class="btn primary" id="seedDatasourcesInline">同步注册源</button></div></div></td></tr>`;
        bindDatasourceButtons($("datasourceRows"));
        const inline = $("seedDatasourcesInline");
        if (inline) inline.addEventListener("click", seedDatasources);
      } catch (error) {
        showLoadError("datasourceRows", 7);
      }
    }

    function bindDatasourceButtons(root = document) {
      root.querySelectorAll("[data-datasource-detail]").forEach((btn) => {
        if (btn.dataset.boundDatasourceDetail === "true") return;
        btn.dataset.boundDatasourceDetail = "true";
        btn.addEventListener("click", () => loadDatasourceDetail(btn.dataset.datasourceDetail));
      });
      root.querySelectorAll("[data-datasource-toggle]").forEach((btn) => {
        if (btn.dataset.boundDatasourceToggle === "true") return;
        btn.dataset.boundDatasourceToggle = "true";
        btn.addEventListener("click", () => toggleDatasource(btn.dataset.datasourceToggle, btn.dataset.enabled === "true"));
      });
      root.querySelectorAll("[data-datasource-health]").forEach((btn) => {
        if (btn.dataset.boundDatasourceHealth === "true") return;
        btn.dataset.boundDatasourceHealth = "true";
        btn.textContent = "查看状态说明";
        btn.addEventListener("click", () => markDatasourceHealth(btn.dataset.datasourceHealth));
      });
    }

    async function loadDatasourceDetail(sourceId) {
      try {
        const item = await getJson(`/api/data-sources/${encodeURIComponent(sourceId)}`);
        $("datasourceDetail").innerHTML = `<h2>数据源详情</h2>
          <div class="kv"><span class="label">名称</span><span>${esc(item.name || sourceText(item.source_key))}</span></div>
          <div class="kv"><span class="label">用途</span><span>${esc(sourcePurposeText(item))}</span></div>
          <div class="kv"><span class="label">类型</span><span>${esc(datasourceTypeText(item.source_type))}</span></div>
          <div class="kv"><span class="label">覆盖市场</span><span>${esc(marketScopeText(item.market_scope))}</span></div>
          <div class="kv"><span class="label">可信度</span><span><span class="status ${esc(item.trust_level || "secondary")}">${esc(statusText(item.trust_level || "secondary"))}</span></span></div>
          <div class="kv"><span class="label">启用</span><span>${item.enabled ? "是" : "否"}</span></div>
          <div class="kv"><span class="label">凭证</span><span><span class="status ${esc(item.credential_status)}">${esc(credentialText(item.credential_status))}</span></span></div>
          <div class="kv"><span class="label">最近状态</span><span><span class="status ${esc(item.last_status || "pending")}">${esc(statusText(item.last_status || "pending"))}</span></span></div>
          <div class="kv"><span class="label">最近同步</span><span>${esc(fmt(item.last_sync_at))}</span></div>
          ${item.last_error ? `<div class="detail-section"><h3>最近错误</h3><div class="text-block">${esc(item.last_error)}</div></div>` : ""}
          ${systemInfoBlock("系统信息", [["数据源标识", item.source_key], ["空间编号", item.workspace_id]])}
          <details class="detail-section"><summary>接入配置</summary><div class="text-block">${esc(JSON.stringify(item.config || {}, null, 2))}</div></details>`;
      } catch (error) {
        showLoadError("datasourceDetail");
      }
    }

    async function seedDatasources() {
      try {
        const result = await postJson("/api/data-sources/seed", {});
        $("datasourceDetail").innerHTML = `<h2>同步注册源</h2><div class="empty">已同步 ${esc(number(result.created))} 个新数据源。</div>`;
        await loadDatasources();
      } catch (error) {
        $("datasourceDetail").innerHTML = `<div class="error">同步失败，请检查 SearchManager 配置。</div>`;
      }
    }

    async function toggleDatasource(sourceId, enabled) {
      try {
        await postJson(`/api/data-sources/${encodeURIComponent(sourceId)}/enable`, { enabled });
        await loadDatasources();
        await loadDatasourceDetail(sourceId);
      } catch (error) {
        showNotice("数据源未配置凭证，不能启用。请先在环境变量或配置中心填写密钥。", "error");
      }
    }

    async function markDatasourceHealth(sourceId) {
      await loadDatasourceDetail(sourceId);
      showNotice("健康状态只能由真实采集或同步任务更新，不能手工标记正常。", "empty");
    }

    function ingestionActionButtons(batch) {
      const status = String(batch.status || "");
      const id = esc(batch.batch_id);
      const buttons = [];
      if (status === "queued") {
        buttons.push(`<button class="btn primary" data-ingestion-action="start" data-batch-id="${id}">启动</button>`);
        buttons.push(`<button class="btn danger" data-ingestion-action="cancel" data-batch-id="${id}">取消</button>`);
      }
      if (status === "running") {
        buttons.push(`<button class="btn" data-ingestion-action="complete" data-batch-id="${id}">标记完成</button>`);
        buttons.push(`<button class="btn danger" data-ingestion-action="fail" data-batch-id="${id}">标记失败</button>`);
        buttons.push(`<button class="btn danger" data-ingestion-action="cancel" data-batch-id="${id}">取消</button>`);
      }
      if (status === "failed" || status === "cancelled") {
        buttons.push(`<button class="btn primary" data-ingestion-action="retry" data-batch-id="${id}">重试</button>`);
      }
      return buttons.length ? `<div class="links">${buttons.join("")}</div>` : `<span class="label">无可用操作</span>`;
    }

    function renderIngestionCreatePanel(message = "") {
      $("ingestionDetail").innerHTML = `<h2>创建采集批次</h2>
        <div class="form-grid">
          <div class="field full"><label for="ingestionName">批次名称</label><input id="ingestionName" placeholder="例如：NVDA FY2024 年报采集" /></div>
          <div class="field"><label for="ingestionCreateSource">数据源</label><input id="ingestionCreateSource" placeholder="例如：美国证监会年报" /></div>
          <div class="field"><label for="ingestionTargetType">采集目标</label><select id="ingestionTargetType"><option value="filings">公告/年报</option><option value="market_data">行情数据</option><option value="news">新闻资料</option><option value="documents">文档资料</option></select></div>
          <div class="field"><label for="ingestionSymbol">股票代码</label><input id="ingestionSymbol" placeholder="NVDA" /></div>
          <div class="field"><label for="ingestionPeriod">期间</label><input id="ingestionPeriod" placeholder="FY2024" /></div>
          <div class="field full"><label for="ingestionCreateQuery">查询条件</label><textarea id="ingestionCreateQuery" rows="3" placeholder="例如：NVDA 10-K FY2024"></textarea></div>
        </div>
        <div class="modal-actions"><button class="btn primary" id="createIngestionBatch">创建批次</button></div>
        <div id="ingestionMessage">${message}</div>`;
      bindCreateIngestionButton();
      $("ingestionName").focus();
    }

    function bindCreateIngestionButton() {
      const button = $("createIngestionBatch");
      if (!button || button.dataset.boundCreateIngestion === "true") return;
      button.dataset.boundCreateIngestion = "true";
      button.addEventListener("click", createIngestionBatch);
    }

    async function loadIngestionBatches() {
      const params = new URLSearchParams();
      const q = $("ingestionQuery").value.trim();
      const status = $("ingestionStatus").value;
      const source = $("ingestionSource").value.trim();
      if (q) params.set("q", q);
      if (status) params.set("status", status);
      if (source) params.set("source_key", sourceKeyValue(source));
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/ingestion-batches" + suffix);
        const rows = payload.items || [];
        $("ingestionRows").innerHTML = rows.length
          ? rows.map((batch) => `<tr data-selectable="true">
              <td><button class="btn" data-ingestion-detail="${esc(batch.batch_id)}">${esc(batchDisplayTitle(batch))}</button><br><span class="label">${esc(fmt(batch.symbol))} ${esc(fmt(batch.period))}</span></td>
              <td>${esc(batch.source_name || sourceText(batch.source_key))}<br><span class="label">${esc(sourcePurposeText(batch))}</span></td>
              <td>${esc(statusText(batch.target_type))}<br><span class="label">${esc(fmt(batch.symbol))} · ${esc(fmt(batch.period))}</span></td>
              <td><span class="status ${esc(batch.status)}">${esc(statusText(batch.status))}</span><br><span class="label">重试 ${esc(number(batch.retry_count))} 次</span></td>
              <td>${esc(number(batch.success_count))} 成功 / ${esc(number(batch.failed_count))} 失败<br><span class="label">共 ${esc(number(batch.item_count))} 项</span></td>
              <td>${ingestionActionButtons(batch)}</td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty"><div>暂无采集批次</div><div class="empty-actions"><button class="btn primary" id="focusCreateIngestion">创建采集批次</button><button class="btn" data-jump="datasources">配置数据源</button></div></div></td></tr>`;
        bindIngestionButtons($("ingestionRows"));
        bindJumpHandlers($("ingestionRows"));
        const focus = $("focusCreateIngestion");
        if (focus) focus.addEventListener("click", () => $("ingestionName").focus());
      } catch (error) {
        showLoadError("ingestionRows", 6);
      }
    }

    function bindIngestionButtons(root = document) {
      root.querySelectorAll("[data-ingestion-detail]").forEach((btn) => {
        if (btn.dataset.boundIngestionDetail === "true") return;
        btn.dataset.boundIngestionDetail = "true";
        btn.addEventListener("click", () => loadIngestionDetail(btn.dataset.ingestionDetail));
      });
      root.querySelectorAll("[data-ingestion-action]").forEach((btn) => {
        if (btn.dataset.boundIngestionAction === "true") return;
        btn.dataset.boundIngestionAction = "true";
        btn.addEventListener("click", () => ingestionLifecycleAction(btn.dataset.batchId, btn.dataset.ingestionAction, btn));
      });
      root.querySelectorAll("[data-ingestion-documents]").forEach((btn) => {
        if (btn.dataset.boundIngestionDocuments === "true") return;
        btn.dataset.boundIngestionDocuments = "true";
        btn.addEventListener("click", () => openDocumentsForBatch(btn.dataset.ingestionDocuments || ""));
      });
      root.querySelectorAll("[data-ingestion-create]").forEach((btn) => {
        if (btn.dataset.boundIngestionCreate === "true") return;
        btn.dataset.boundIngestionCreate = "true";
        btn.addEventListener("click", () => renderIngestionCreatePanel());
      });
    }

    async function createIngestionBatch() {
      const payload = {
        name: $("ingestionName").value.trim(),
        source_key: sourceKeyValue($("ingestionCreateSource").value.trim()),
        target_type: $("ingestionTargetType").value,
        symbol: $("ingestionSymbol").value.trim(),
        period: $("ingestionPeriod").value.trim(),
        query: $("ingestionCreateQuery").value.trim(),
      };
      if (!payload.name) {
        $("ingestionMessage").innerHTML = `<div class="error">请输入批次名称。</div>`;
        return;
      }
      try {
        const created = await postJson("/api/ingestion-batches", payload);
        $("ingestionMessage").innerHTML = `<div class="empty">采集批次已创建，可在下方启动或查看处理文档。</div>`;
        await loadIngestionBatches();
        await loadIngestionDetail(created.batch_id);
      } catch (error) {
        $("ingestionMessage").innerHTML = `<div class="error">创建失败，请确认数据源已配置或留空后重试。</div>`;
      }
    }

    async function ingestionLifecycleAction(batchId, action, button = null) {
      const labels = { start: "启动", complete: "标记完成", fail: "标记失败", retry: "重试", cancel: "取消" };
      if (button && button.dataset.confirmAction !== action) {
        button.dataset.confirmAction = action;
        button.dataset.originalText = button.textContent;
        button.textContent = "再次点击确认操作";
        window.setTimeout(() => {
          if (button.dataset.confirmAction === action) {
            button.textContent = button.dataset.originalText || "操作";
            delete button.dataset.confirmAction;
          }
        }, 6000);
        return;
      }
      if (button) {
        delete button.dataset.confirmAction;
        button.disabled = true;
        button.textContent = "处理中…";
      }
      const payloadByAction = {
        complete: { message: "用户在工作台标记完成" },
        fail: { error_message: "用户在工作台标记失败" },
        cancel: { reason: "用户在工作台取消" },
      };
      try {
        const updated = await postJson(`/api/ingestion-batches/${encodeURIComponent(batchId)}/${encodeURIComponent(action)}`, payloadByAction[action] || {});
        await loadIngestionBatches();
        await loadIngestionDetail(updated.batch_id || batchId);
        loadDashboard();
      } catch (error) {
        $("ingestionDetail").insertAdjacentHTML("afterbegin", `<div class="error">${esc(labels[action] || "操作")}失败，请刷新后重试。</div>`);
      } finally {
        if (button?.isConnected) {
          button.disabled = false;
          button.textContent = button.dataset.originalText || labels[action] || "操作";
        }
      }
    }

    async function loadIngestionDetail(batchId) {
      try {
        const batch = await getJson(`/api/ingestion-batches/${encodeURIComponent(batchId)}`);
        const events = batch.events || [];
        $("ingestionDetail").innerHTML = `<h2>采集批次详情</h2>
          <div class="kv"><span class="label">名称</span><span>${esc(batch.name)}</span></div>
          <div class="kv"><span class="label">数据源</span><span>${esc(batch.source_name || sourceText(batch.source_key))}</span></div>
          <div class="kv"><span class="label">目标</span><span>${esc(statusText(batch.target_type))}</span></div>
          <div class="kv"><span class="label">公司期间</span><span>${esc(fmt(batch.symbol))} · ${esc(fmt(batch.period))}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(batch.status)}">${esc(statusText(batch.status))}</span></span></div>
          <div class="kv"><span class="label">结果</span><span>${esc(number(batch.success_count))} 成功 / ${esc(number(batch.failed_count))} 失败 / 共 ${esc(number(batch.item_count))} 项</span></div>
          <div class="kv"><span class="label">时间</span><span>${esc(fmt(batch.started_at))} - ${esc(fmt(batch.finished_at))}</span></div>
          <div class="detail-section"><h3>查询条件</h3><div class="text-block">${esc(batch.query || "-")}</div></div>
          <div class="detail-section"><h3>批次操作</h3>${ingestionActionButtons(batch)}<div class="links"><button class="btn" data-ingestion-documents="${esc(batch.batch_id)}">查看同批次文档</button><button class="btn" data-ingestion-create="true">新建采集批次</button></div></div>
          ${batch.error_message ? `<div class="detail-section"><h3>错误</h3><div class="text-block">${esc(batch.error_message)}</div></div>` : ""}
          ${systemInfoBlock("系统信息", [["批次编号", batch.batch_id], ["数据源标识", batch.source_key]])}
          <div class="detail-section"><h3>运行日志</h3><div class="timeline">${
            events.length ? events.map((event) => `<div class="event"><strong>${esc(stepText(event.stage))}</strong> <span class="status ${esc(event.status)}">${esc(statusText(event.status))}</span><br><span class="label">${esc(fmt(event.created_at))}</span><br>${esc(fmt(event.message))}</div>`).join("") : `<div class="empty">暂无日志</div>`
          }</div></div>`;
        bindIngestionButtons($("ingestionDetail"));
      } catch (error) {
        showLoadError("ingestionDetail");
      }
    }

    function updateManualImportFields() {
      const type = $("manualImportType").value;
      document.querySelectorAll("[data-manual-field]").forEach((field) => {
        const key = field.dataset.manualField;
        const visible = (type === "text" && key === "content") || (type === "url" && key === "source") || (type === "pdf" && key === "file") || (type === "pdf" && key === "source");
        field.style.display = visible ? "grid" : "none";
      });
      const title = $("manualTitle");
      if (!title.value.trim()) {
        title.placeholder = type === "text" ? "例如：NVDA FY2024 年报摘录" : (type === "url" ? "例如：AAPL SEC 年报链接" : "例如：AAPL FY2024 年报 PDF");
      }
    }

    async function submitManualImport() {
      const type = $("manualImportType").value;
      const payload = {
        import_type: type,
        title: $("manualTitle").value.trim(),
        symbol: $("manualSymbol").value.trim(),
        company_name: $("manualCompanyName").value.trim(),
        period: $("manualPeriod").value.trim(),
        content: $("manualContent").value.trim(),
        source_url: $("manualSourceUrl").value.trim(),
        file_path: $("manualFilePath").value.trim(),
      };
      if (type === "text" && !payload.content) {
        $("manualImportMessage").innerHTML = `<div class="error">请输入文本内容。</div>`;
        return;
      }
      if (type === "url" && !payload.source_url) {
        $("manualImportMessage").innerHTML = `<div class="error">请输入来源链接。</div>`;
        return;
      }
      if (type === "pdf" && !payload.file_path && !payload.source_url) {
        $("manualImportMessage").innerHTML = `<div class="error">请输入 PDF 文件路径或来源链接。</div>`;
        return;
      }
      $("manualImportMessage").innerHTML = `<div class="empty">正在导入...</div>`;
      try {
        const result = await postJson("/api/manual-import", payload);
        const doc = result.document || {};
        $("manualImportMessage").innerHTML = `<div class="empty">${esc(result.message || "导入完成")}</div>`;
        $("manualImportResult").innerHTML = `<h2>导入结果</h2>
          <div class="kv"><span class="label">文档</span><span>${esc(doc.title || "-")}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(doc.parse_status || "pending")}">${esc(statusText(doc.parse_status || "pending"))}</span></span></div>
          <div class="kv"><span class="label">类型</span><span>${esc(docTypeText(doc.doc_type))}</span></div>
          <div class="kv"><span class="label">证据化状态</span><span>${result.processing_status === "evidence_ready" ? `已生成 ${esc(number(doc.evidence_count || 0))} 条证据` : "等待可解析正文"}</span></div>
          ${doc.source_url ? `<div class="kv"><span class="label">链接</span><a href="${esc(doc.source_url)}" target="_blank">${esc(doc.source_url)}</a></div>` : ""}
          ${systemInfoBlock("系统信息", [["批次编号", result.batch_id], ["文件路径", doc.file_path]])}
          <div class="links" style="margin-top:12px">
            <button class="btn primary" id="manualViewDocument">查看处理路径</button>
            <button class="btn" id="manualViewBatch">查看导入批次</button>
          </div>
          ${result.duplicate ? `<div class="detail-section"><div class="empty">检测到相同内容，未重复创建文档。</div></div>` : ""}`;
        $("manualViewDocument").addEventListener("click", () => {
          openDocumentsForBatch(result.batch_id || "", doc.id || null);
        });
        $("manualViewBatch").addEventListener("click", () => {
          activateView("ingestion");
          if (result.batch_id) loadIngestionDetail(result.batch_id);
        });
        loadDashboard();
      } catch (error) {
        $("manualImportMessage").innerHTML = `<div class="error">导入失败，请检查必填项或是否与已有文档冲突。</div>`;
      }
    }

    function renderCards(summary) {
      const cards = [
        { label: "公司数", value: summary.company_count, view: "stockpool" },
        { label: "文档数", value: summary.document_count, view: "documents" },
        { label: "证据数", value: summary.evidence_count, view: "evidence" },
        { label: "主张数", value: summary.claim_count, view: "claims" },
        { label: "待复核", value: summary.review_pending_claim_count, view: "claims", claimStatus: "pending" },
        { label: "已校验主张", value: summary.verified_claim_count, view: "claims", claimVerification: "supported" },
        { label: "质量通过率", value: pct(summary.quality_pass_rate), view: "evaluation" },
        { label: "平均质量分", value: summary.average_quality_score ?? "-", view: "evaluation" },
      ];
      $("metricCards").innerHTML = cards.map((card) => `<button class="card metric-card" data-jump="${esc(card.view)}"${card.claimStatus ? ` data-claim-status="${esc(card.claimStatus)}"` : ""}${card.claimVerification ? ` data-claim-verification="${esc(card.claimVerification)}"` : ""}>
        <div class="label"><span>${esc(card.label)}</span><span class="hint">查看</span></div>
        <div class="value">${esc(card.value)}</div>
      </button>`).join("");
      bindJumpHandlers($("metricCards"));
      bindCreateTaskButtons($("metricCards"));
    }

    function renderDistribution(id, values, mapper) {
      const entries = Object.entries(values || {}).sort((a, b) => b[1] - a[1]);
      $(id).innerHTML = entries.length
        ? entries.map(([key, value]) => `<div class="dist-row"><span>${esc(mapper ? mapper(key) : key)}</span><strong>${esc(number(value))}</strong></div>`).join("")
        : `<div class="empty">暂无数据</div>`;
    }

    function hasRealFunnelCounts(steps) {
      return steps.some((step) => Number(step.count || 0) > 0);
    }

    function isValidFunnelSeries(steps) {
      if (!hasRealFunnelCounts(steps)) return false;
      for (let index = 1; index < steps.length; index += 1) {
        const prev = Number(steps[index - 1].count || 0);
        const current = Number(steps[index].count || 0);
        if (current > prev) return false;
      }
      return true;
    }

    function funnelNoteHtml(hasRealCounts, hasConsistentFunnel) {
      if (!hasRealCounts) {
        return `<div class="funnel-demo-note">当前暂无真实处理数据，以下为流程示意。创建研报任务或导入文档后将展示真实统计；带有黄色提示的图表不计入真实 KPI。</div>`;
      }
      if (!hasConsistentFunnel) {
        return `<div class="funnel-demo-note">当前真实统计尚未形成完整累计漏斗，以下展示流程示意；请切换到“处理链路”查看真实阶段计数。带有黄色提示的图表不计入真实 KPI。</div>`;
      }
      return "";
    }

    function renderFunnel(payload) {
      const rawSteps = payload.steps || [];
      const hasRealCounts = hasRealFunnelCounts(rawSteps);
      const hasConsistentFunnel = isValidFunnelSeries(rawSteps);
      const visualSteps = hasConsistentFunnel ? rawSteps : funnelDemoSteps;
      const chainSteps = hasRealCounts ? rawSteps : [];
      const visualMax = Math.max(1, ...visualSteps.map((step) => Number(step.count || 0)));
      const chainMax = Math.max(1, ...chainSteps.map((step) => Number(step.count || 0)));
      $("funnelDemoNote").innerHTML = funnelNoteHtml(hasRealCounts, hasConsistentFunnel);
      $("funnelVisual").innerHTML = visualSteps.map((step, index) => {
        const count = Number(step.count || 0);
        const prev = index === 0 ? count : Number(visualSteps[index - 1].count || 0);
        const width = Math.max(40, Math.round((count / visualMax) * 100));
        const rate = index === 0 ? "基准" : (prev > 0 ? `${Math.round((count / prev) * 1000) / 10}%` : "-");
        const target = funnelTargets[step.key] || { view: "documents" };
        return `<button class="funnel-layer" style="width:${width}%" data-jump="${esc(target.view)}"${target.documentStep ? ` data-document-step="${esc(target.documentStep)}"` : ""}${target.claimStatus ? ` data-claim-status="${esc(target.claimStatus)}"` : ""}${target.claimVerification ? ` data-claim-verification="${esc(target.claimVerification)}"` : ""}>
          <span>${esc(step.label)}</span>
          <strong>${esc(number(count))}</strong>
          <span class="rate">${esc(rate)}</span>
        </button>`;
      }).join("");
      $("funnelLoss").innerHTML = renderFunnelLoss(visualSteps);
      $("funnel").innerHTML = chainSteps.length ? chainSteps.map((step, index) => {
            const width = Math.max(2, Math.round((Number(step.count || 0) / chainMax) * 100));
            return `<div>
              <div class="funnel-row"><span>${esc(step.label)}</span><div class="bar"><span style="width:${width}%"></span></div><strong>${esc(number(step.count))}</strong></div>
              ${index < chainSteps.length - 1 ? `<div class="funnel-arrow">↓</div>` : ""}
            </div>`;
          }).join("") : emptyBox("暂无真实处理链路数据。导入文档或运行研报任务后显示。", [
            { label: "手动导入", view: "manual", className: "primary" },
            { label: "创建研报任务", view: "tasks" },
          ]);
      bindJumpHandlers($("funnelVisual"));
      bindJumpHandlers($("funnel"));
    }

    function renderFunnelLoss(steps) {
      if (steps.length < 2) return "";
      let maxLoss = null;
      for (let index = 1; index < steps.length; index += 1) {
        const prev = Number(steps[index - 1].count || 0);
        const current = Number(steps[index].count || 0);
        const loss = Math.max(0, prev - current);
        const rate = prev > 0 ? current / prev : 0;
        if (!maxLoss || loss > maxLoss.loss) {
          maxLoss = { from: steps[index - 1], to: steps[index], loss, rate };
        }
      }
      if (!maxLoss) return "";
      return `<div class="funnel-loss-card">
        <h3>最大流失步骤</h3>
        <div><strong>${esc(maxLoss.from.label)} → ${esc(maxLoss.to.label)}</strong></div>
        <div class="dist-row"><span>流失数量</span><strong>${esc(number(maxLoss.loss))}</strong></div>
        <div class="dist-row"><span>阶段转化率</span><strong>${esc(Math.round(maxLoss.rate * 1000) / 10)}%</strong></div>
      </div>`;
    }

    function renderRecentTaskPanel(payload) {
      const tasks = (payload.items || []).slice(0, 5);
      $("recentTasks").innerHTML = tasks.length
        ? tasks.map((task) => `<div class="mini-item">
            <div class="mini-title">
              <button class="btn" data-task-detail-jump="${esc(task.task_id)}">${esc(metadataName(task))}</button>
              <span class="status ${esc(task.status)}">${esc(statusText(task.status))}</span>
            </div>
            <div class="mini-meta">${esc(task.period || "-")} · ${esc(stepText(task.current_stage))} · ${esc(fmt(task.created_at))}</div>
          </div>`).join("")
        : `<div class="empty"><div>暂无任务</div><div class="empty-actions"><button class="btn primary" data-open-create-task>创建研报任务</button></div></div>`;
      bindJumpHandlers($("recentTasks"));
      bindCreateTaskButtons($("recentTasks"));
      bindRecentTaskButtons($("recentTasks"));
    }

    function renderDataSourceHealth(summary) {
      const values = summary.data_source_distribution || {};
      const sources = [
        ["sec_edgar", "美国证监会年报"],
        ["cninfo", "巨潮资讯"],
        ["hkex", "港交所公告"],
        ["yahoo_finance", "雅虎财经"],
        ["company_profile", "公司画像"],
        ["market_api", "行情接口"],
        ["local_pdf", "本地文档"],
      ];
      const hasAny = Object.values(values).some((value) => Number(value || 0) > 0);
      $("dataSourceHealth").innerHTML = sources.map(([key, label]) => {
        const count = Number(values[key] || 0);
        const state = count > 0 ? "已入库" : "待配置";
        const cls = count > 0 ? "completed" : "pending";
        return `<div class="health-row"><span>${esc(label)}</span><strong>${esc(number(count))}</strong><span class="status ${cls}">${state}</span></div>`;
      }).join("") + (hasAny ? "" : `<div class="empty-actions"><button class="btn primary" data-jump="datasources">配置数据源</button></div>`);
      bindJumpHandlers($("dataSourceHealth"));
    }

    function renderDonutChart(targetId, rows, options = {}) {
      const realRows = rows.filter((row) => Number(row.value || 0) > 0);
      const displayRows = realRows;
      const total = displayRows.reduce((sum, row) => sum + Number(row.value || 0), 0);
      if (!displayRows.length || total <= 0) {
        $(targetId).innerHTML = emptyBox(options.emptyText || "暂无统计数据", options.actions || []);
        bindJumpHandlers($(targetId));
        return;
      }
      let start = 0;
      const gradient = displayRows.map((row, index) => {
        const value = Number(row.value || 0);
        const end = start + (value / total) * 360;
        const color = row.color || chartColors[index % chartColors.length];
        const segment = `${color} ${start}deg ${end}deg`;
        start = end;
        return segment;
      }).join(", ");
      const legend = displayRows.map((row, index) => {
        const color = row.color || chartColors[index % chartColors.length];
        const ratio = total > 0 ? Math.round((Number(row.value || 0) / total) * 1000) / 10 : 0;
        return `<div class="legend-row"><span class="legend-dot" style="background:${esc(color)}"></span><span>${esc(row.label)}</span><strong>${esc(number(row.value))} · ${esc(ratio)}%</strong></div>`;
      }).join("");
      $(targetId).innerHTML = `<div class="chart-card">
        <div class="donut" style="background: conic-gradient(${gradient})">
          <div class="donut-center"><div><strong>${esc(number(total))}</strong>${esc(options.centerLabel || "合计")}</div></div>
        </div>
        <div>
          <div class="legend">${legend}</div>
          ${realRows.length ? "" : `<div class="chart-note">${esc(options.demoNote || "暂无真实统计，当前显示流程示意。")}</div>`}
        </div>
      </div>`;
    }

    function renderDashboardCharts(summary) {
      const sourceRows = Object.entries(summary.data_source_distribution || {}).map(([key, value], index) => ({
        label: sourceText(key),
        value,
        color: chartColors[index % chartColors.length],
      }));
      renderDonutChart("dataSourceChart", sourceRows, {
        centerLabel: "来源",
        emptyText: "暂无数据源统计",
        demoNote: "暂无真实数据源统计，当前显示示意分布；示意分布不代表当前空间真实数据。",
        actions: [{ label: "配置数据源", view: "datasources", className: "primary" }],
        demoRows: [
          { label: "美国证监会年报", value: 35, color: chartColors[0] },
          { label: "雅虎财经", value: 20, color: chartColors[1] },
          { label: "巨潮资讯", value: 18, color: chartColors[2] },
          { label: "港交所公告", value: 12, color: chartColors[3] },
          { label: "本地文档", value: 15, color: chartColors[4] },
        ],
      });

      const totalClaims = Number(summary.claim_count || 0);
      const pending = Number(summary.review_pending_claim_count || 0);
      const verified = Number(summary.verified_claim_count || 0);
      const other = Math.max(0, totalClaims - pending - verified);
      renderDonutChart("claimStatusChart", [
        { label: "已校验", value: verified, color: chartColors[1] },
        { label: "待复核", value: pending, color: chartColors[2] },
        { label: "其他主张", value: other, color: chartColors[5] },
      ], {
        centerLabel: "主张",
        emptyText: "暂无主张统计",
        demoNote: "暂无真实主张统计，当前显示示意分布；示意分布不代表当前空间真实数据。",
        actions: [{ label: "生成新研报", view: "tasks", className: "primary" }],
        demoRows: [
          { label: "已校验", value: 58, color: chartColors[1] },
          { label: "待复核", value: 14, color: chartColors[2] },
          { label: "引用缺失", value: 7, color: chartColors[3] },
          { label: "数字冲突", value: 5, color: chartColors[4] },
        ],
      });
    }

    function renderReviewExceptions(summary) {
      const pending = Number(summary.review_pending_claim_count || 0);
      const verified = Number(summary.verified_claim_count || 0);
      const total = Number(summary.claim_count || 0);
      const unchecked = Math.max(0, total - verified);
      $("reviewExceptions").innerHTML = [
        ["待复核主张", summary.review_pending_claim_count],
        ["待校验证据", unchecked],
        ["数字冲突", "待接入"],
        ["引用缺失", "待接入"],
        ["过度推断", "待接入"],
      ].map(([key, value]) => `<div class="dist-row"><span>${esc(key)}</span><strong>${Number.isFinite(Number(value)) ? esc(number(value)) : esc(value)}</strong></div>`).join("")
        + (pending || total ? "" : `<div class="empty-actions"><button class="btn primary" data-jump="tasks">生成新研报</button><button class="btn" data-jump="manual">导入报告产物</button></div>`);
      bindJumpHandlers($("reviewExceptions"));
    }

    function reportTypeText(value) {
      const map = { equity_research: "股票研报", annual_review: "年报深度", earnings_review: "财报点评" };
      return textOf(map, value);
    }

    function taskDeliveryStatus(task) {
      const readiness = task?.delivery_readiness || {};
      const lifecycleStatus = String(task?.status || "unknown");
      if (["failed", "timeout", "cancelled", "archived"].includes(lifecycleStatus)) {
        return { key: lifecycleStatus, label: statusText(lifecycleStatus) };
      }
      if (readiness.machine_status === "passed" && readiness.review_status === "pending") {
        return { key: "pending", label: "机器质检通过，待人工复核" };
      }
      if (readiness.machine_status === "failed") {
        return { key: "failed", label: "机器质检未通过" };
      }
      if (readiness.formal_status === "ready") {
        return { key: "completed", label: "可正式交付" };
      }
      const status = String(readiness.status || "");
      if (status) {
        const classMap = { export_ready: "completed", review_required: "pending", remediation_required: "failed", in_progress: "running", queued: "queued", blocked: "failed" };
        return { key: classMap[status] || status, label: statusText(status) };
      }
      return { key: String(task?.status || "unknown"), label: statusText(task?.status || "unknown") };
    }

    function renderDeliveryReadiness(task) {
      let readiness = task?.delivery_readiness || {};
      if (!Object.keys(readiness).length) return "";
      if (["queued", "pending"].includes(String(task?.status || ""))) {
        readiness = {
          ...readiness,
          can_generate_draft: "可启动",
          draft_generated: "尚未生成",
          can_enter_human_review: "待运行检查",
          can_deliver_formal_report: "待运行检查",
          can_export_formal_package: "待运行检查",
        };
      }
      const blockers = readiness.blocking_reasons || [];
      const actions = readiness.required_actions || [];
      return `<div class="detail-section"><h3>统一交付状态</h3>
        <div class="analysis-stats">
          <div class="analysis-stat"><span class="label">草稿产物</span><strong>${esc(readiness.draft_generated === true ? "已生成" : "尚未生成")}</strong></div>
          <div class="analysis-stat"><span class="label">可重新生成</span><strong>${esc(readiness.can_generate_draft === true ? "是" : "否")}</strong></div>
          <div class="analysis-stat"><span class="label">人工复核</span><strong>${esc(humanReviewText(readiness.human_review_status, readiness.can_enter_human_review))}</strong></div>
          <div class="analysis-stat"><span class="label">正式交付</span><strong>${esc(passText(readiness.can_deliver_formal_report))}</strong></div>
          <div class="analysis-stat"><span class="label">正式导出</span><strong>${esc(passText(readiness.can_export_formal_package))}</strong></div>
        </div>
        ${blockers.length ? `<div class="text-block">${esc(blockers.map(statusText).join("\\n"))}</div>` : `<div class="empty">当前没有正式交付阻塞项。</div>`}
        ${actions.length ? `<div class="score-note">下一步：${esc(actions.map(statusText).join("、"))}</div>` : ""}
      </div>`;
    }

    function renderRecentTaskTable(payload) {
      const tasks = (payload.items || []).slice(0, 6);
      $("recentTaskRows").innerHTML = tasks.length
        ? tasks.map((task) => { const delivery = taskDeliveryStatus(task); return `<tr>
            <td>${esc(task.symbol || "-")}</td>
            <td>${esc(task.period || "-")}</td>
            <td>${esc(reportTypeText(task.report_type))}</td>
            <td><span class="status ${esc(delivery.key)}">${esc(delivery.label)}</span></td>
            <td>${esc(fmt(task.quality_score))}</td>
            <td>${esc(fmt(task.finished_at || task.started_at || task.created_at))}</td>
            <td><button class="btn" data-task-detail-jump="${esc(task.task_id)}">查看</button></td>
          </tr>`; }).join("")
        : `<tr><td colspan="7"><div class="empty"><div>暂无研报任务</div><div class="empty-actions"><button class="btn primary" data-open-create-task>创建研报任务</button></div></div></td></tr>`;
      bindJumpHandlers($("recentTaskRows"));
      bindCreateTaskButtons($("recentTaskRows"));
      bindRecentTaskButtons($("recentTaskRows"));
    }

    function bindRecentTaskButtons(root = document) {
      root.querySelectorAll("[data-task-detail-jump]").forEach((btn) => {
        if (btn.dataset.boundTaskJump === "true") return;
        btn.dataset.boundTaskJump = "true";
        btn.addEventListener("click", () => {
          activateView("tasks");
          loadTaskDetail(btn.dataset.taskDetailJump);
        });
      });
    }

    function artifactButtons(task) {
      const links = task.report_links || {};
      const buttons = [];
      if (links.html_web_url) buttons.push(`<a class="btn primary" href="${esc(links.html_web_url)}" target="_blank">网页报告</a>`);
      if (links.markdown_web_url) buttons.push(`<a class="btn" href="${esc(links.markdown_web_url)}" target="_blank">文稿</a>`);
      if (links.json_web_url) buttons.push(`<a class="btn" href="${esc(links.json_web_url)}" target="_blank">数据</a>`);
      buttons.push(`<a class="btn" href="/api/report-tasks/${encodeURIComponent(task.task_id)}/artifacts" target="_blank">全部产物</a>`);
      return `<div class="links">${buttons.join("")}</div>`;
    }

    function taskActionButtons(task) {
      const status = String(task.status || "");
      const runtime = task?.metadata?.report_runtime || {};
      const runtimeFailure = task?.metadata?.runtime_failure || {};
      const id = esc(task.task_id);
      const buttons = [];
      if (runtime.checkpoint_status === "interrupted") {
        buttons.push(`<button class="btn primary" data-task-action="resume_runtime" data-task-id="${id}">复核完成，继续工作流</button>`);
      }
      if (status === "failed" && runtimeFailure.checkpoint_available) {
        buttons.push(`<button class="btn primary" data-task-action="retry_checkpoint" data-task-id="${id}">从失败节点继续</button>`);
      }
      if (status === "queued") {
        buttons.push(`<button class="btn primary" data-task-action="start" data-task-id="${id}">启动</button>`);
        buttons.push(`<button class="btn danger" data-task-action="cancel" data-task-id="${id}">取消</button>`);
      }
      if (status === "failed" || status === "timeout" || status === "cancelled" || status === "quality_failed") {
        buttons.push(`<button class="btn primary" data-task-action="retry" data-task-id="${id}">重试</button>`);
      }
      if (status !== "running" && status !== "archived") {
        buttons.push(`<button class="btn" data-task-action="archive" data-task-id="${id}">归档</button>`);
      }
      if (status === "running") {
        buttons.push(`<span class="label">运行中任务暂不支持强制停止</span>`);
      }
      return buttons.length ? `<div class="links">${buttons.join("")}</div>` : `<span class="label">无可用操作</span>`;
    }

    function bindTaskActionButtons(root = document) {
      root.querySelectorAll("[data-task-action]").forEach((btn) => {
        if (btn.dataset.boundTaskAction === "true") return;
        btn.dataset.boundTaskAction = "true";
        btn.addEventListener("click", () => taskLifecycleAction(btn.dataset.taskId, btn.dataset.taskAction, btn));
      });
    }

    async function taskLifecycleAction(taskId, action, button = null) {
      if (button && button.dataset.confirmAction !== action) {
        button.dataset.confirmAction = action;
        button.dataset.originalText = button.textContent;
        button.textContent = "再次点击确认操作";
        window.setTimeout(() => {
          if (button.dataset.confirmAction === action) {
            button.textContent = button.dataset.originalText || "操作";
            delete button.dataset.confirmAction;
          }
        }, 6000);
        return;
      }
      if (button) {
        delete button.dataset.confirmAction;
        button.disabled = true;
        button.textContent = "处理中…";
      }
      const labels = { start: "启动", retry: "完整重试", cancel: "取消", archive: "归档", resume_runtime: "从人工复核断点继续", retry_checkpoint: "从失败节点继续" };
      const payloadByAction = {
        start: { run_immediately: true, run_async: true },
        retry: { run_immediately: true, run_async: true },
        cancel: { reason: "用户在工作台取消" },
        archive: { reason: "用户在工作台归档" },
        resume_runtime: { decision: { approved: true, reviewer: "workbench_user" } },
        retry_checkpoint: {},
      };
      const endpointByAction = {
        start: "start",
        retry: "retry",
        cancel: "cancel",
        archive: "archive",
        resume_runtime: "runtime/resume",
        retry_checkpoint: "runtime/retry",
      };
      try {
        const endpoint = endpointByAction[action];
        const response = await postJson(`/api/report-tasks/${encodeURIComponent(taskId)}/${endpoint}`, payloadByAction[action]);
        const updated = response.task || response;
        await loadTasks();
        await loadTaskDetail(updated.task_id || taskId);
        loadDashboard();
        if (["start", "retry", "retry_checkpoint"].includes(action)) scheduleTaskRefresh(updated.task_id || taskId);
      } catch (error) {
        $("taskDetail").insertAdjacentHTML("afterbegin", `<div class="error">${esc(labels[action] || "操作")}失败，请刷新后重试。</div>`);
      }
    }

    function scheduleTaskRefresh(taskId) {
      if (taskPoller) {
        clearInterval(taskPoller.timer);
        taskPoller = null;
      }
      let attempts = 0;
      taskPoller = {
        taskId,
        timer: setInterval(async () => {
          attempts += 1;
          try {
            const task = await getJson(`/api/report-tasks/${encodeURIComponent(taskId)}`);
            if (activeState.view === "tasks") await loadTaskDetail(task.task_id);
            await loadTasks();
            loadDashboard();
            if (terminalTaskStatuses.has(String(task.status || "")) || attempts >= 30) {
              clearInterval(taskPoller.timer);
              taskPoller = null;
            }
          } catch (error) {
            if (taskPoller) {
              clearInterval(taskPoller.timer);
              taskPoller = null;
            }
          }
        }, 2000),
      };
    }

    async function loadEvaluation() {
      try {
        const payload = await getJson("/api/evaluation/summary");
        renderEvaluation(payload);
      } catch (error) {
        showLoadError("evaluationCards");
      }
    }

    function renderEvaluation(payload) {
      const metrics = { ...(payload.metrics || {}) };
      const sampleRequirements = {
        delivery_pass_rate: "quality_evaluated_task_count",
        evidence_ready_task_rate: "quality_evaluated_task_count",
        source_quality_ready_task_rate: "quality_evaluated_task_count",
        traceable_claim_rate: "claim_count",
        citation_support_rate: "claim_count",
        numeric_consistency_rate: "numeric_checked_count",
        llm_success_rate: "llm_run_count",
        schema_valid_rate: "schema_checked_count",
      };
      Object.entries(sampleRequirements).forEach(([valueKey, countKey]) => {
        if (Number(metrics[countKey] || 0) <= 0) metrics[valueKey] = null;
      });
      const cards = [
        { label: "机器质检通过率", value: percentText(metrics.machine_quality_pass_rate), note: `${number(metrics.machine_quality_pass_count)} / ${number(metrics.quality_evaluated_task_count)} 个已质检任务`, view: "tasks" },
        { label: "正式交付通过率", value: percentText(metrics.formal_delivery_pass_rate ?? metrics.delivery_pass_rate), note: `${number(metrics.formal_delivery_pass_count ?? metrics.delivery_pass_count)} / ${number(metrics.quality_evaluated_task_count)} 个已质检任务；需完成人工复核`, view: "tasks" },
        { label: "内容完整度评分", value: scoreText(metrics.average_quality_score), note: "仅衡量报告内容完整程度，不等同于正式交付状态", view: "tasks" },
        { label: "可追溯主张率", value: percentText(metrics.traceable_claim_rate), note: `${number(metrics.traceable_claim_count)} / ${number(metrics.claim_count)} 条主张`, view: "claims" },
        { label: "证据召回可用率", value: percentText(metrics.evidence_ready_task_rate), note: `${number(metrics.evidence_ready_task_count)} / ${number(metrics.quality_evaluated_task_count)} 个已质检任务`, view: "evidence" },
        { label: "关键来源覆盖率", value: percentText(metrics.source_quality_ready_task_rate), note: `${number(metrics.source_quality_ready_task_count)} 个任务来源充分`, view: "datasources" },
        { label: "引用支持率", value: percentText(metrics.citation_support_rate), note: `${number(metrics.citation_supported_count)} 条有证据或引用`, view: "claims" },
        { label: "数值一致性", value: percentText(metrics.numeric_consistency_rate), note: `${number(metrics.numeric_checked_count)} 条已检查`, view: "facts" },
        { label: "模型运行成功率", value: percentText(metrics.llm_success_rate), note: `${number(metrics.llm_success_count)} / ${number(metrics.llm_run_count)} 次运行`, view: "promptops" },
        { label: "结构化输出有效率", value: percentText(metrics.schema_valid_rate), note: `${number(metrics.schema_valid_count)} / ${number(metrics.schema_checked_count)} 次校验`, view: "promptops" },
        { label: "平均耗时", value: metrics.average_llm_latency_ms == null ? "-" : `${number(metrics.average_llm_latency_ms)} ms`, note: `成本 ${costText(metrics.llm_cost_usd, metrics.llm_run_count)}`, view: "promptops" },
      ];
      $("evaluationCards").innerHTML = cards.map((card) => `<button class="card metric-card" data-jump="${esc(card.view)}">
        <div class="label"><span>${esc(card.label)}</span><span class="hint">查看</span></div>
        <div class="value">${esc(card.value)}</div>
        <div class="score-note">${esc(card.note)}</div>
      </button>`).join("");
      renderEvaluationGates(payload.quality_gates || []);
      renderEvaluationClaimQuality(payload.claim_quality || {});
      renderEvaluationRetrievalQuality(payload.retrieval_quality || {});
      renderEvaluationModelHealth(payload.model_health || {});
      renderEvaluationFailures(payload.failure_categories || [], metrics);
      renderEvaluationBenchmarkSuites(payload.benchmark_suites || []);
      renderEvaluationRegressionMatrix(payload.regression_matrix || {});
      renderEvaluationTaskRows(payload.recent_tasks || []);
      renderEvaluationRuns(payload.recent_llm_runs || []);
      renderEvaluationNotes(payload);
      bindJumpHandlers($("evaluation"));
      bindRecentTaskButtons($("evaluation"));
      bindEvaluationDiagnosticButtons($("evaluation"));
    }

    function renderEvaluationGates(gates) {
      $("evaluationGates").innerHTML = gates.length
        ? gates.map((gate) => `<div class="check-item ${esc(gate.status === "passed" ? "passed" : (gate.status === "failed" ? "failed" : ""))}">
            <div class="diagnostic-head">
              <strong>${esc(gate.label)}</strong>
              <span class="status ${esc(gate.status)}">${esc(evaluationGateStatusText(gate.status))}</span>
            </div>
            <div class="diagnostic-meta">
              <span>当前：${esc(metricValueText(gate.key, gate.value))}</span>
              <span>目标：${esc(percentText(gate.target))}</span>
            </div>
            <div class="score-note">${esc(gate.description || "")}</div>
          </div>`).join("")
        : emptyBox("暂无质量门禁数据", [{ label: "创建研报任务", view: "tasks", className: "primary" }]);
    }

    function renderEvaluationClaimQuality(quality) {
      const cards = quality.cards || [];
      $("evaluationClaimQuality").innerHTML = cards.length
        ? cards.map((card) => `<button class="diagnostic-card" data-jump="claims">
            <div class="diagnostic-head"><strong>${esc(card.label)}</strong><span>${esc(percentText(card.value))}</span></div>
            <div class="score-note">相关主张：${esc(number(card.count))} 条</div>
          </button>`).join("")
          + `<div class="dist">
              <div class="dist-row"><span>待人工复核</span><strong>${esc(number(quality.pending_review))}</strong></div>
              <div class="dist-row"><span>数字冲突</span><strong>${esc(number(quality.numeric_failed))}</strong></div>
              <div class="dist-row"><span>引用缺失</span><strong>${esc(number(quality.citation_failed))}</strong></div>
            </div>`
        : emptyBox("暂无主张质量数据", [
            { label: "生成新研报", view: "tasks", className: "primary" },
            { label: "导入报告产物", view: "manual" },
          ]);
    }

    function renderEvaluationRetrievalQuality(quality) {
      const returnedSources = quality.returned_sources || [];
      const missingSources = quality.missing_sources || [];
      const gapTypes = quality.gap_types || [];
      const rows = [
        ["证据可用任务", `${number(quality.evidence_ready_task_count)} / ${number(quality.task_count)}`, percentText(quality.evidence_ready_task_rate)],
        ["关键来源充分", `${number(quality.source_quality_ready_task_count)} / ${number(quality.task_count)}`, percentText(quality.source_quality_ready_task_rate)],
        ["无证据任务", number(quality.retrieval_gap_task_count), "需补采集或导入"],
        ["来源缺口任务", number(quality.source_gap_task_count), "需补官方或一手来源"],
      ];
      const sourceHtml = returnedSources.length
        ? `<div class="dist-list">${returnedSources.slice(0, 5).map((item) => `<div class="dist-row"><span>${esc(item.label || sourceText(item.source_key))}</span><strong>${esc(number(item.count))}</strong></div>`).join("")}</div>`
        : `<div class="empty">暂无命中来源统计。</div>`;
      const missingHtml = missingSources.length
        ? `<div class="dist-list">${missingSources.slice(0, 5).map((item) => `<div class="dist-row"><span>${esc(item.label || sourceText(item.source_key))}</span><strong>${esc(number(item.count))}</strong></div>`).join("")}</div>`
        : `<div class="empty">暂无关键来源缺口。</div>`;
      const gapHtml = gapTypes.length
        ? `<div class="mini-list">${gapTypes.slice(0, 5).map((item) => `<div class="mini-item"><strong>${esc(item.label || item.type)}</strong><br><span class="label">影响任务：${esc(number(item.count))}</span></div>`).join("")}</div>`
        : `<div class="empty">暂无召回缺口。</div>`;
      $("evaluationRetrievalQuality").innerHTML = Number(quality.task_count || 0)
        ? `<div class="chain-summary">${esc(quality.summary || "")}</div>
          <div class="dist">${rows.map(([label, value, note]) => `<div class="dist-row"><span>${esc(label)}</span><strong>${esc(value)}</strong><span class="label">${esc(note)}</span></div>`).join("")}</div>
          <div class="detail-section"><h3>命中来源</h3>${sourceHtml}</div>
          <div class="detail-section"><h3>来源缺口</h3>${missingHtml}</div>
          <div class="detail-section"><h3>召回缺口类型</h3>${gapHtml}</div>`
        : emptyBox("暂无召回质量数据", [{ label: "创建研报任务", view: "tasks", className: "primary" }]);
    }

    function renderEvaluationModelHealth(health) {
      const rows = [
        ["模型运行", `${number(health.success_count)} 成功 / ${number(health.run_count)} 总计`],
        ["失败运行", number(health.failed_count)],
        ["降级运行", number(health.fallback_count)],
        ["结构化输出", percentText(health.schema_valid_rate)],
        ["平均耗时", health.average_latency_ms == null ? "-" : `${number(health.average_latency_ms)} ms`],
        ["累计成本", costText(health.cost_usd, health.run_count)],
      ];
      $("evaluationModelHealth").innerHTML = rows.map(([label, value]) => `<div class="dist-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("")
        + ((health.recent_roles || []).length ? `<div class="detail-section"><h3>最近运行角色</h3>${health.recent_roles.map((item) => `<div class="dist-row"><span>${esc(modelRoleText(item.role))}</span><strong>${esc(number(item.count))}</strong></div>`).join("")}</div>` : "");
    }

    function renderEvaluationFailures(items, metrics = {}) {
	      if (!items.length && Number(metrics.quality_evaluated_task_count || 0) <= 0) {
	        $("evaluationFailures").innerHTML = emptyBox("尚无可评测样本；请先完成至少一个研报任务。", [{ label: "查看研报任务", view: "tasks", className: "primary" }]);
	        return;
	      }
	      $("evaluationFailures").innerHTML = items.length
	        ? items.map((item) => `<div class="mini-item">
	            <div class="mini-title">
	              <strong>${esc(productText(item.key || item.label))}</strong>
	              <span class="status ${esc(item.severity)}">${esc(signalSeverityText(item.severity))}</span>
	            </div>
            <div class="mini-meta">${esc(number(item.count))} 项需要处理</div>
            <div style="margin-top:8px"><button class="btn" data-jump="${esc(item.next_view || "evaluation")}">查看处理入口</button></div>
          </div>`).join("")
        : emptyBox("当前没有明显阻塞问题", [{ label: "查看研报任务", view: "tasks", className: "primary" }]);
    }

    function renderEvaluationRegressionMatrix(matrix) {
      const rows = matrix.rows || [];
      if (!rows.length) {
        $("evaluationRegressionMatrix").innerHTML = emptyBox("暂无回归矩阵数据", [{ label: "创建研报任务", view: "tasks", className: "primary" }]);
        return;
      }
      $("evaluationRegressionMatrix").innerHTML = `<div class="chain-summary">${esc(matrix.description || "按任务检查交付门禁、证据覆盖、引用支持和数字一致性。")}</div>
        <div class="dist" style="margin:10px 0">
          <div class="dist-row"><span>纳入回归</span><strong>${esc(number(matrix.evaluated_count))}</strong></div>
          <div class="dist-row"><span>通过率</span><strong>${esc(percentText(matrix.pass_rate))}</strong></div>
          <div class="dist-row"><span>阻塞任务</span><strong>${esc(number(matrix.blocked_count))}</strong></div>
        </div>
        <div class="table-scroll"><table>
          <thead><tr><th>任务</th><th>回归状态</th><th>失败门禁</th><th>下一步</th><th>操作</th></tr></thead>
          <tbody>${rows.map((row) => `<tr>
            <td>${esc(row.company_name || row.symbol)}<br><span class="label">${esc(row.symbol)} · ${esc(row.period)}</span></td>
            <td><span class="status ${esc(row.status)}">${esc(regressionStatusText(row.status))}</span><br><span class="label">质量分 ${esc(scoreText(row.quality_score))}</span></td>
            <td>${(row.failed_gate_labels || []).length ? esc((row.failed_gate_labels || []).join("、")) : "-"}</td>
            <td>${esc(row.recommended_action || "查看任务诊断。")}</td>
            <td><button class="btn" data-evaluation-diagnostic="${esc(row.task_id)}">诊断</button></td>
          </tr>`).join("")}</tbody>
        </table></div>`;
    }

    function renderEvaluationBenchmarkSuites(suites) {
      if (!suites.length) {
        $("evaluationBenchmarkSuites").innerHTML = emptyBox("暂无基准集跑批结果。运行 Formal-18、Quick-9 或回归集后，这里会自动读取产物。", [{ label: "查看提示词运营", view: "promptops", className: "primary" }]);
        return;
      }
      $("evaluationBenchmarkSuites").innerHTML = `<div class="diagnostic-grid">${suites.slice(0, 6).map((suite) => {
        const metrics = suite.metrics || {};
        const markets = (suite.market_breakdown || []).filter((row) => row.market && row.market !== "Overall").map((row) => row.market).join("、") || "未记录";
        const evaluatedCount = suite.evaluated_count ?? suite.case_count;
        return `<div class="diagnostic-card">
          <div class="diagnostic-head"><strong>${esc(suite.suite_name || "基准评测")}</strong><span class="status ${esc(suite.suite_type || "benchmark")}">${esc(benchmarkSuiteTypeText(suite.suite_type))}</span></div>
          <div class="dist" style="margin-top:10px">
            <div class="dist-row"><span>交付通过率</span><strong>${esc(percentText(metrics.delivery_pass_rate))}</strong></div>
            <div class="dist-row"><span>客观质量分</span><strong>${esc(scoreText(metrics.objective_quality_score))}</strong></div>
            <div class="dist-row"><span>可追溯主张率</span><strong>${esc(percentText(metrics.traceable_claim_rate))}</strong></div>
          </div>
          <div class="mini-meta">样例 ${esc(countText(evaluatedCount))} / ${esc(countText(suite.case_count))} · 覆盖市场：${esc(markets)}</div>
          <div class="score-note">最近产物：${esc(suite.last_updated_at ? fmt(new Date(Number(suite.last_updated_at) * 1000).toISOString()) : "未记录")}</div>
        </div>`;
      }).join("")}</div>`;
    }

    function renderEvaluationTaskRows(tasks) {
      $("evaluationTaskRows").innerHTML = tasks.length
        ? tasks.map((task) => { const delivery = taskDeliveryStatus(task); return `<tr>
            <td>${esc(task.company_name || task.symbol)}<br><span class="label">${esc(task.symbol)} · ${esc(task.period)} · ${esc(reportTypeText(task.report_type))}</span></td>
            <td><span class="status ${esc(delivery.key)}">${esc(delivery.label)}</span><br><span class="label">正式交付：${esc(passText(task.delivery_pass))}</span></td>
            <td>${esc(scoreText(task.quality_score))}</td>
            <td>${esc(percentText(task.traceable_claim_rate))}</td>
            <td>${esc(percentText(task.verified_claim_rate))}</td>
            <td>${esc(number(Number(task.issue_count || 0) + Number(task.citation_failed_count || 0) + Number(task.numeric_failed_count || 0) + Number(task.pending_review_count || 0)))}</td>
            <td><div class="links"><button class="btn primary" data-evaluation-diagnostic="${esc(task.task_id)}">诊断</button><button class="btn" data-task-detail-jump="${esc(task.task_id)}">分析包</button></div></td>
          </tr>`; }).join("")
        : `<tr><td colspan="7">${emptyBox("暂无研报质量记录", [{ label: "创建研报任务", view: "tasks", className: "primary" }])}</td></tr>`;
    }

    function bindEvaluationDiagnosticButtons(root = document) {
      root.querySelectorAll("[data-evaluation-diagnostic]").forEach((btn) => {
        if (btn.dataset.boundEvaluationDiagnostic === "true") return;
        btn.dataset.boundEvaluationDiagnostic = "true";
        btn.addEventListener("click", () => loadEvaluationTaskDiagnostic(btn.dataset.evaluationDiagnostic));
      });
    }

    async function loadEvaluationTaskDiagnostic(taskId) {
      $("evaluationTaskDiagnostic").innerHTML = `<div class="empty">正在生成单任务诊断...</div>`;
      try {
        const [payload, analysis] = await Promise.all([
          getJson(`/api/evaluation/report-tasks/${encodeURIComponent(taskId)}/diagnostics`),
          getJson(`/api/report-tasks/${encodeURIComponent(taskId)}/analysis`).catch(() => null),
        ]);
        renderEvaluationTaskDiagnostic(payload, analysis);
        $("evaluationDiagnosticPanel").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        $("evaluationTaskDiagnostic").innerHTML = `<div class="error">诊断加载失败，请刷新后重试。</div>`;
      }
    }

    function renderEvaluationTaskDiagnostic(payload, analysis = null) {
      const task = payload.task || {};
      const delivery = taskDeliveryStatus({ status: task.status, delivery_readiness: payload.delivery_readiness || {} });
      const summary = payload.summary || {};
      const blockers = payload.blockers || [];
      const actions = payload.recommended_actions || [];
      const claimIssues = payload.claim_issues || {};
      const modelIssues = payload.model_issues || [];
      const qualityIssues = payload.quality_issues || [];
      const dataSourceHealth = payload.data_source_health || {};
      $("evaluationTaskDiagnostic").innerHTML = `<div class="detail-section" style="border-top:0;margin-top:0;padding-top:0">
          <div class="diagnostic-head">
            <div>
              <h3>${esc(task.company_name || task.symbol || "研报任务")} · ${esc(task.period || "-")}</h3>
              <div class="score-note">${esc(task.symbol || "-")} · ${esc(reportTypeText(task.report_type))} · ${esc(fmt(task.updated_at))}</div>
            </div>
            <span class="status ${esc(delivery.key)}">${esc(delivery.label)}</span>
          </div>
          <div class="analysis-stats" style="margin-top:10px">
            <div class="analysis-stat"><span class="label">质量分</span><strong>${esc(scoreText(summary.quality_score))}</strong><span class="score-note">门禁：${esc(passText(summary.delivery_pass))}</span></div>
            <div class="analysis-stat"><span class="label">证据覆盖</span><strong>${esc(percentText(summary.traceable_claim_rate))}</strong><span class="score-note">缺证据 ${esc(number(summary.missing_evidence_count))} 条</span></div>
            <div class="analysis-stat"><span class="label">主张校验</span><strong>${esc(percentText(summary.verified_claim_rate))}</strong><span class="score-note">未支持 ${esc(number(summary.unsupported_claim_count))} 条</span></div>
            <div class="analysis-stat"><span class="label">模型问题</span><strong>${esc(number(summary.model_issue_count))}</strong><span class="score-note">结构化、降级或失败运行</span></div>
          </div>
        </div>
        <div class="detail-section"><h3>诊断结论</h3>${renderDiagnosticBlockers(blockers)}</div>
        <div class="detail-section"><h3>数据源与采集健康</h3>${renderDiagnosticDataSourceHealth(dataSourceHealth)}</div>
        <div class="detail-section"><h3>建议动作</h3>${renderDiagnosticActions(actions)}</div>
        <div class="detail-section"><h3>主张问题</h3>${renderDiagnosticClaimGroups(claimIssues)}</div>
        <div class="detail-section"><h3>模型运行问题</h3>${renderDiagnosticModelIssues(modelIssues)}</div>
        <div class="detail-section"><h3>分析链路摘要</h3>${renderEvaluationAnalysisLinkage(analysis)}</div>
        <div class="detail-section"><h3>质量检查原始问题</h3>${renderDiagnosticQualityIssues(qualityIssues)}</div>
        ${systemInfoBlock("系统信息", [["任务编号", task.task_id]])}`;
      bindJumpHandlers($("evaluationTaskDiagnostic"));
      bindRecentTaskButtons($("evaluationTaskDiagnostic"));
      bindRemediationBatchButtons($("evaluationTaskDiagnostic"));
    }

    function renderDiagnosticBlockers(blockers) {
      return blockers.length
        ? `<div class="diagnostic-list">${blockers.map((item) => `<div class="diagnostic-issue ${esc(item.severity)}">
            <div class="diagnostic-head"><strong>${esc(item.label)}</strong><span class="status ${esc(item.severity)}">${esc(signalSeverityText(item.severity))}</span></div>
            <div>${esc(item.description || "")}</div>
            <div class="score-note">${esc(number(item.count))} 项 · <button class="btn" data-jump="${esc(item.next_view || "evaluation")}">去处理</button></div>
          </div>`).join("")}</div>`
        : `<div class="empty">当前没有明显质量阻塞。</div>`;
    }

    function renderDiagnosticDataSourceHealth(health) {
      const rows = health.source_rows || [];
      const distribution = health.evidence_source_distribution || [];
      if (!rows.length) return `<div class="empty">暂无数据源诊断。完成任务或补充证据后会展示来源覆盖、采集状态和缺口原因。</div>`;
      const gapCount = (health.gaps || []).length;
      return `<div class="analysis-stats">
          <div class="analysis-stat"><span class="label">覆盖市场</span><strong>${esc(marketText(health.market))}</strong><span class="score-note">按任务公司和股票代码判断</span></div>
          <div class="analysis-stat"><span class="label">需要来源</span><strong>${esc(number(health.required_source_count || rows.length))}</strong><span class="score-note">${esc(renderSourceList(health.required_sources))}</span></div>
          <div class="analysis-stat"><span class="label">健康来源</span><strong>${esc(number(health.healthy_source_count))}</strong><span class="score-note">可用、运行中或已覆盖</span></div>
          <div class="analysis-stat"><span class="label">证据命中来源</span><strong>${esc(number(health.covered_source_count))}</strong><span class="score-note">缺口 ${esc(number(gapCount))} 个</span></div>
        </div>
        <div class="mini-list">${rows.map(renderDiagnosticSourceRow).join("")}</div>
        <div class="detail-section"><h3>证据来源分布</h3>${
          distribution.length
            ? `<div class="dist-list">${distribution.map((item) => `<div class="dist-row"><span>${esc(item.label || sourceText(item.source_key))}</span><strong>${esc(number(item.count))}</strong></div>`).join("")}</div>`
            : `<div class="empty">当前任务尚未命中可追溯证据来源。</div>`
        }</div>`;
    }

    function renderDiagnosticSourceRow(item) {
      const latestBatch = item.latest_batch || null;
      const batchText = latestBatch
        ? `${statusText(latestBatch.status)} · ${latestBatch.symbol || "-"} · ${latestBatch.period || "-"}`
        : "暂无匹配采集批次";
      const errorText = latestBatch?.error_message || item.last_error || "";
      const buttons = [
        `<button class="btn" data-jump="datasources" data-datasource-query="${esc(item.source_key)}">配置来源</button>`,
        `<button class="btn" data-jump="ingestion" data-ingestion-source="${esc(item.source_key)}">查看采集</button>`,
      ];
      if (canCreateRemediationBatch(item)) {
        buttons.unshift(`<button class="btn primary" data-remediation-batch='${esc(JSON.stringify(item.remediation_batch || {}))}'>创建补采集批次</button>`);
      }
      if (item.evidence_count > 0) buttons.push(`<button class="btn" data-jump="evidence">查看证据</button>`);
      return `<div class="mini-item source-health-row">
        <div class="mini-title">
          <strong>${esc(item.name || sourceText(item.source_key))}</strong>
          <span class="status ${esc(item.health_status || "pending")}">${esc(sourceHealthText(item.health_status))}</span>
        </div>
        <div>${esc(item.purpose || sourcePurposeText(item))}</div>
        <div class="mini-meta">
          <span>证据 ${esc(number(item.evidence_count))} 条</span>
          <span>市场：${esc(item.market_supported ? "覆盖" : "不覆盖")}</span>
          <span>凭证：${esc(credentialText(item.credential_status))}</span>
          <span>最近采集：${esc(batchText)}</span>
        </div>
        <div class="score-note">${esc(item.reason || "")}</div>
        ${errorText ? `<div class="error">${esc(errorText)}</div>` : ""}
        <div class="links">${buttons.join("")}</div>
      </div>`;
    }

    function sourceHealthText(value) {
      const map = {
        covered: "已覆盖",
        ready: "可用待命中",
        running: "采集中",
        not_collected: "待采集",
        failed: "采集失败",
        credential_required: "凭证缺失",
        disabled: "已停用",
        not_configured: "未配置",
        market_mismatch: "市场不匹配",
      };
      return textOf(map, value);
    }

    function canCreateRemediationBatch(item) {
      return item?.remediation_batch && ["failed", "not_collected", "ready"].includes(String(item.health_status || ""));
    }

    function bindRemediationBatchButtons(root = document) {
      root.querySelectorAll("[data-remediation-batch]").forEach((btn) => {
        if (btn.dataset.boundRemediationBatch === "true") return;
        btn.dataset.boundRemediationBatch = "true";
        btn.addEventListener("click", () => createRemediationBatch(btn));
      });
    }

    async function createRemediationBatch(btn) {
      let payload = {};
      try { payload = JSON.parse(btn.dataset.remediationBatch || "{}"); }
      catch (error) { payload = {}; }
      if (!payload.name || !payload.source_key) {
        $("evaluationTaskDiagnostic").insertAdjacentHTML("afterbegin", `<div class="error">补采集参数缺失，请先查看采集任务或数据源配置。</div>`);
        return;
      }
      btn.disabled = true;
      btn.textContent = "正在创建...";
      try {
        const created = await postJson("/api/ingestion-batches", payload);
        $("evaluationTaskDiagnostic").insertAdjacentHTML("afterbegin", `<div class="empty">已创建补采集批次：${esc(created.name || created.batch_id)}</div>`);
        showNotice(`已创建补采集批次：${created.name || created.batch_id}`);
        activateView("ingestion");
        $("ingestionSource").value = sourceText(created.source_key);
        $("ingestionSource").dataset.sourceKey = created.source_key || "";
        await loadIngestionBatches();
        await loadIngestionDetail(created.batch_id);
      } catch (error) {
        btn.disabled = false;
        btn.textContent = "创建补采集批次";
        $("evaluationTaskDiagnostic").insertAdjacentHTML("afterbegin", `<div class="error">补采集批次创建失败，请检查数据源配置或稍后重试。</div>`);
      }
    }

    function renderDiagnosticActions(actions) {
      return actions.length
        ? `<div class="action-list">${actions.map((item) => `<div class="action-item">
            <div class="diagnostic-head"><strong>${esc(item.label)}</strong><span class="status ${esc(item.priority || "medium")}">${esc(signalSeverityText(item.priority || "medium"))}</span></div>
            <div class="score-note">${esc(item.reason || "")}</div>
            <div><button class="btn primary" data-jump="${esc(item.view || "tasks")}"${item.datasource_query ? ` data-datasource-query="${esc(item.datasource_query)}"` : ""}${item.ingestion_source ? ` data-ingestion-source="${esc(item.ingestion_source)}"` : ""}${item.ingestion_query ? ` data-ingestion-query="${esc(item.ingestion_query)}"` : ""}>前往处理</button></div>
          </div>`).join("")}</div>`
        : `<div class="empty">暂无建议动作。</div>`;
    }

    function renderDiagnosticClaimGroups(groups) {
      const definitions = [
        ["missing_evidence", "缺少证据"],
        ["unsupported_claims", "未获支持"],
        ["numeric_conflicts", "数字冲突"],
        ["citation_gaps", "引用缺失"],
        ["pending_review", "待人工复核"],
      ];
      const sections = definitions.map(([key, label]) => {
        const items = groups[key] || [];
        if (!items.length) return "";
        return `<details class="detail-section" open><summary>${esc(label)} · ${esc(number(items.length))} 条</summary>
          <div class="mini-list">${items.map((claim) => `<div class="mini-item">
            <strong>主张 ${esc(claim.id)}</strong> <span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span>
            <div>${esc(claim.claim_text || "")}</div>
            <div class="score-note">校验：${esc(statusText(claim.verification_status))} · 数字：${esc(statusText(claim.numeric_check_status))} · 引用：${esc(statusText(claim.citation_check_status))} · 证据 ${esc(number(claim.evidence_count))} 条</div>
          </div>`).join("")}</div>
        </details>`;
      }).filter(Boolean);
      return sections.length ? sections.join("") : `<div class="empty">暂无主张级问题。</div>`;
    }

    function renderDiagnosticModelIssues(items) {
      return items.length
        ? `<div class="mini-list">${items.map((item) => `<div class="mini-item">
            <div class="mini-title"><strong>${esc(item.label)}</strong><span class="status ${esc(item.severity)}">${esc(item.reason)}</span></div>
            <div class="mini-meta">状态：${esc(statusText(item.status))} · 结构化输出：${esc(passText(item.schema_valid))} · ${esc(item.latency_ms == null ? "-" : item.latency_ms + " ms")} · ${esc(fmt(item.created_at))}</div>
            ${item.error_message ? `<div class="text-block">${esc(item.error_message)}</div>` : ""}
          </div>`).join("")}</div>`
        : `<div class="empty">暂无模型运行问题。</div>`;
    }

    function renderDiagnosticQualityIssues(items) {
      return items.length
        ? `<div class="diagnostic-list">${items.map((item) => `<div class="diagnostic-issue ${esc(item.severity)}">
            <span class="label">${esc(item.label)}</span><br>${esc(item.message)}
          </div>`).join("")}</div>`
        : `<div class="empty">暂无额外质量检查问题。</div>`;
    }

    function renderEvaluationAnalysisLinkage(analysis) {
      if (!analysis) {
        return `<div class="empty">分析包暂不可用，可进入研报任务详情查看已有产物。</div>`;
      }
      const task = analysis.task || {};
      const stats = analysis.stats || {};
      const qualityProof = analysis.quality_proof || {};
      const argumentChain = analysis.argument_chain || {};
      const riskChain = analysis.risk_chain || {};
      const narrative = analysis.narrative || [];
      const retrievalCoverage = analysis.retrieval_coverage || qualityProof.retrieval_coverage || {};
      const narrativeHtml = narrative.length
        ? `<div class="timeline">${narrative.slice(0, 5).map((item) => `<div class="event"><strong>${esc(item.stage)}</strong> <span class="status ${esc(item.status || "pending")}">${esc(statusText(item.status || "pending"))}</span><br>${esc(item.description || "")}</div>`).join("")}</div>`
        : `<div class="empty">暂无业务链路。</div>`;
      const proofChecks = qualityProof.checks || [];
      const chainNodes = argumentChain.nodes || [];
      const riskNodes = (riskChain.nodes || []).filter((node) => node.type === "risk");
      return `<div class="analysis-stats">
          <div class="analysis-stat"><span class="label">证据</span><strong>${esc(number(stats.evidence_count))}</strong><span class="score-note">官方/一手 ${esc(number(stats.official_evidence_count))} 条</span></div>
          <div class="analysis-stat"><span class="label">财务事实</span><strong>${esc(number(stats.financial_fact_count))}</strong><span class="score-note">结构化指标和口径</span></div>
          <div class="analysis-stat"><span class="label">投资线索</span><strong>${esc(number(stats.investment_signal_count))}</strong><span class="score-note">高优先级 ${esc(number(stats.high_severity_signal_count))} 条</span></div>
          <div class="analysis-stat"><span class="label">逻辑链节点</span><strong>${esc(number(chainNodes.length))}</strong><span class="score-note">风险节点 ${esc(number(riskNodes.length))} 个</span></div>
        </div>
        <div class="detail-section"><h3>业务链路</h3>${narrativeHtml}</div>
        ${renderRetrievalCoverage(retrievalCoverage)}
        <div class="detail-section"><h3>研报质量证明</h3>
          <div class="chain-summary">${esc(qualityProof.explanation || "暂无质量解释。")}</div>
          <div class="check-grid">${proofChecks.length ? proofChecks.slice(0, 4).map((item) => `<div class="check-item ${item.passed ? "passed" : "failed"}"><div class="diagnostic-head"><strong>${esc(item.title)}</strong><span class="status ${item.passed ? "passed" : "failed"}">${esc(item.passed ? "通过" : "需处理")}</span></div><div class="score-note">${esc(item.description || "")}</div></div>`).join("") : `<div class="empty">暂无质量检查项。</div>`}</div>
        </div>
        <div class="detail-section"><h3>投资逻辑链</h3>
          <div class="chain-summary">${esc(argumentChain.summary || "尚未形成投资逻辑链。")}</div>
          ${renderAnalysisNodeList(chainNodes, argumentChain.edges || [])}
        </div>
        <div class="detail-section"><h3>风险传导链</h3>
          <div class="chain-summary">${esc(riskChain.summary || "尚未识别风险传导节点。")}</div>
          <div class="mini-list">${riskNodes.length ? riskNodes.slice(0, 5).map((node) => `<div class="mini-item"><strong>${esc(node.title || "风险线索")}</strong><br><span class="label">${esc(signalSeverityText(node.payload?.severity || ""))} · ${esc(signalDirectionText(node.payload?.direction || ""))}</span><br>${esc(node.payload?.summary || "")}</div>`).join("") : `<div class="empty">暂无风险节点。</div>`}</div>
        </div>
        <div class="links" style="margin-top:10px">
          <button class="btn primary" data-task-detail-jump="${esc(task.task_id)}">打开完整分析包</button>
          <button class="btn" data-jump="signals" data-signal-task-id="${esc(task.task_id)}" data-signal-company="${esc(task.symbol || "")}" data-signal-period="${esc(task.period || "")}">查看投资线索</button>
          <button class="btn" data-jump="graph">查看关系图谱</button>
        </div>`;
    }

    function renderAnalysisNodeList(nodes, edges) {
      if (!nodes.length) return `<div class="empty">暂无可展示链路。导入证据、财务事实和投资线索后会自动补全。</div>`;
      return `<div class="chain-list">${nodes.slice(0, 6).map((node) => {
        const outgoing = edges.filter((edge) => edge.from === node.id).slice(0, 2);
        return `<div class="chain-node"><div class="chain-node-head"><strong>${esc(node.title || node.id)}</strong><span class="status ${esc(node.type || "neutral")}">${esc(chainNodeTypeText(node.type))}</span></div>${outgoing.map((edge) => `<div class="chain-edge">→ ${esc(edge.label || "关联")} → ${esc(chainTargetTitle(edge.to, nodes))}</div>`).join("")}</div>`;
      }).join("")}</div>`;
    }

    function renderEvaluationRuns(runs) {
      $("evaluationRuns").innerHTML = runs.length
        ? runs.map((run) => `<div class="mini-item">
            <div class="mini-title">
	              <strong>${esc(modelRunLabelText(run))}</strong>
              <span class="status ${esc(run.status)}">${esc(statusText(run.status))}</span>
            </div>
            <div class="mini-meta">${esc(run.task_id || "未绑定任务")} · 结构化输出 ${esc(passText(run.schema_valid))} · ${esc(run.latency_ms == null ? "-" : run.latency_ms + " ms")} · ${esc(fmt(run.created_at))}</div>
            ${run.fallback_used ? `<div class="score-note">已启用降级运行</div>` : ""}
          </div>`).join("")
        : emptyBox("暂无模型运行记录", [{ label: "查看提示词运营", view: "promptops", className: "primary" }]);
    }

    function renderEvaluationNotes(payload) {
      const notes = payload.notes || [];
      const fixedNotes = [
        "当前页面聚合现有任务、主张、证据和模型运行记录，用于证明研报质量。",
        "Formal-18、Quick-9 和回归集跑批仍属于后续评测能力，需要在评测样例和局部诊断接口稳定后接入。",
      ];
      $("evaluationNotes").innerHTML = [...notes, ...fixedNotes].map((note) => `<div class="diagnostic-card">${esc(note)}</div>`).join("");
    }

    function metricValueText(key, value) {
      if (key === "average_quality_score") return scoreText(value);
      if (String(key || "").includes("rate")) return percentText(value);
      return fmt(value);
    }

    function costText(cost, runCount) {
      // Show "成本未配置" when there are LLM runs but no cost data
      const hasRuns = typeof runCount === "number" && runCount > 0;
      const isZero = cost === null || cost === undefined || cost === "" || cost === 0;
      if (hasRuns && isZero) return "成本未配置";
      if (isZero) return "-";
      return `$${fmt(cost)}`;
    }

    function scoreText(value) {
      if (value === null || value === undefined || value === "") return "-";
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return fmt(value);
      return numeric <= 1 ? String(Math.round(numeric * 1000) / 10) : String(Math.round(numeric * 10) / 10);
    }

    function countText(value) {
      if (value === null || value === undefined || value === "") return "未记录";
      return number(value);
    }

    function evaluationGateStatusText(value) {
      const map = { passed: "达标", warning: "需关注", failed: "未达标", pending: "待生成" };
      return textOf(map, value);
    }

    function regressionStatusText(value) {
      const map = { passed: "通过", blocked: "阻塞", warning: "待补充", pending: "待生成" };
      return textOf(map, value);
    }

	    function modelRoleText(value) {
	      const map = {
	        quality_gate: "质量门禁",
	        verifier: "校验智能体",
	        writer: "研报撰写",
	        researcher: "资料检索",
	        planner: "任务规划",
	        final_answer: "最终研报",
	        gap_resolver: "证据补齐",
	        analyze: "综合分析",
	        browser: "网页读取",
	        research: "资料检索",
	        planning: "任务规划",
	        risk: "风险分析",
	        peer: "同行分析",
	        "agent.gap_resolver": "证据补齐智能体",
	        "agent.analyze": "分析智能体",
	        "agent.browser": "网页读取智能体",
	        "agent.research": "资料检索智能体",
	        "agent.planning": "任务规划智能体",
	        "agent.risk": "风险分析智能体",
	        "agent.peer": "同行分析智能体",
	      };
	      return productText(textOf(map, value));
	    }

	    function modelRunLabelText(run) {
	      const raw = String(run?.label || run?.role || run?.model_role || run?.prompt_key || "").trim();
	      if (!raw) return "模型运行";
	      return modelRoleText(raw);
	    }

	    async function loadDashboard() {
      try {
        const [summary, funnel, recentTasksPayload] = await Promise.all([
          getJson("/api/dashboard/summary"),
          getJson("/api/dashboard/funnel"),
          getJson("/api/report-tasks?limit=6"),
        ]);
        renderCards(summary);
        renderRecentTaskPanel(recentTasksPayload);
        renderDataSourceHealth(summary);
        renderReviewExceptions(summary);
        renderDashboardCharts(summary);
        renderRecentTaskTable(recentTasksPayload);
        renderFunnel(funnel);
      } catch (error) {
        showLoadError("metricCards");
      }
    }

    async function loadTasks() {
      const symbol = $("symbolFilter").value.trim();
	      const suffix = symbol ? `?symbol=${encodeURIComponent(symbol)}&limit=20` : "?limit=20";
      try {
        const payload = await getJson("/api/report-tasks" + suffix);
        const rows = payload.items || [];
        $("taskRows").innerHTML = rows.length
          ? rows.map((task) => { const delivery = taskDeliveryStatus(task); return `<tr data-selectable="true" data-task-id="${esc(task.task_id)}">
              <td><button class="btn" data-task-detail="${esc(task.task_id)}">${esc(metadataName(task))}</button></td>
              <td>${esc(task.symbol)}<br><span class="label">${esc(task.period)}</span></td>
              <td><span class="status ${esc(delivery.key)}">${esc(delivery.label)}</span></td>
              <td class="nowrap">${esc(stepText(task.current_stage))}</td>
              <td>${esc(fmt(task.created_at))}</td>
              <td>${artifactButtons(task)}</td>
              <td>${taskActionButtons(task)}</td>
            </tr>`; }).join("")
          : `<tr><td colspan="7"><div class="empty">暂无研报任务</div></td></tr>`;
        document.querySelectorAll("[data-task-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadTaskDetail(btn.dataset.taskDetail));
        });
        bindTaskActionButtons($("taskRows"));
      } catch (error) {
        showLoadError("taskRows", 7);
      }
    }

    function renderQualityDiagnostics(task) {
      const diag = task.quality_diagnostics || {};
      const hasQuality = diag.delivery_pass !== undefined || diag.quality_score !== undefined || Number(diag.llm_run_count || 0) > 0;
      if (!hasQuality) {
        return `<div class="detail-section"><h3>质量诊断</h3><div class="empty">暂无质量门禁和智能体运行诊断。任务完成后会展示撰写智能体、校验智能体和质量门禁结果。</div></div>`;
      }
      const gateStatus = diag.delivery_pass === true ? "passed" : (diag.delivery_pass === false ? "failed" : "not_run");
      const categories = Object.entries(diag.failure_categories || {});
      const issues = diag.top_issues || [];
      const failedSections = diag.failed_sections || [];
      const fixes = diag.required_fixes || [];
      const runCards = [
        ["撰写智能体", diag.writer],
        ["校验智能体", diag.verifier],
        ["质量门禁", diag.quality_gate],
      ].map(([label, run]) => renderDiagnosticRunCard(label, run)).join("");
      return `<div class="detail-section"><h3>质量诊断</h3>
        <div class="diagnostic-grid">
          <div class="diagnostic-card">
            <div class="diagnostic-head">
              <strong>交付门禁</strong>
              <span class="status ${esc(gateStatus)}">${esc(diag.delivery_pass === true ? "通过" : (diag.delivery_pass === false ? "未通过" : "未运行"))}</span>
            </div>
            <div class="diagnostic-meta">
              <span>质量分：${esc(fmt(diag.quality_score))}</span>
              <span>客观规则：${esc(passText(diag.objective_pass))}</span>
              <span>智能复核：${esc(passText(diag.llm_review_pass))}</span>
              <span>智能体运行：${esc(number(diag.llm_run_count || 0))}</span>
              <span>失败运行：${esc(number(diag.failed_llm_run_count || 0))}</span>
            </div>
          </div>
          ${categories.length ? `<div class="diagnostic-card"><strong>失败分类</strong>${categories.map(([key, value]) => `<div class="dist-row"><span>${esc(qualityCategoryText(key))}</span><strong>${esc(number(value))}</strong></div>`).join("")}</div>` : ""}
          ${issues.length ? `<div class="diagnostic-card"><strong>主要问题</strong><div class="diagnostic-list">${issues.map((issue) => `<div class="diagnostic-issue ${esc(issue.severity || "")}"><span class="label">${esc(severityText(issue.severity || "warning"))}${issue.category ? ` / ${esc(qualityCategoryText(issue.category))}` : ""}</span><br>${esc(productText(issue.message || ""))}</div>`).join("")}</div></div>` : ""}
          ${failedSections.length ? `<div class="diagnostic-card"><strong>需修复章节</strong><div class="diagnostic-meta">${failedSections.map((item) => `<span class="status failed">${esc(productText(item))}</span>`).join("")}</div></div>` : ""}
          ${fixes.length ? `<div class="diagnostic-card"><strong>修复建议</strong><div class="diagnostic-list">${fixes.map((item) => `<div class="diagnostic-issue">${esc(productText(item))}</div>`).join("")}</div></div>` : ""}
          <div class="diagnostic-grid">${runCards}</div>
        </div>
      </div>`;
    }

    function renderToolRuns(task) {
      const runtime = task.runtime_observability || {};
      const summary = runtime.tools || {};
      const runs = task.tool_runs || [];
      if (!runs.length) {
        return `<div class="detail-section"><h3>工具调用轨迹</h3><div class="empty">暂无工具调用记录。任务生成完成后会展示检索、数据和分析工具的执行情况。</div></div>`;
      }
      const recent = runs.slice(0, 12);
      return `<div class="detail-section"><h3>工具调用轨迹</h3>
        <div class="diagnostic-meta">
          <span>调用：${esc(number(summary.run_count || runs.length))}</span>
          <span>失败：${esc(number(summary.failed_run_count || 0))}</span>
          <span>总耗时：${esc(number(summary.latency_ms || 0))} ms</span>
        </div>
        <div class="timeline">${recent.map((run) => `<div class="event">
          <strong>${esc(productText(run.tool_name || "工具"))}</strong>
          <span class="status ${esc(run.status || "unknown")}">${esc(statusText(run.status || "unknown"))}</span><br>
          <span class="label">${esc(productText(run.agent_name || "系统"))} · ${esc(number(run.duration_ms || 0))} ms · ${esc(number(run.attempt_count || 1))} 次尝试</span>
          ${run.error_message ? `<br><span class="error">${esc(productText(run.error_message))}</span>` : ""}
        </div>`).join("")}</div>
      </div>`;
    }

    function renderDiagnosticRunCard(label, run) {
      if (!run) {
        return `<div class="diagnostic-card"><div class="diagnostic-head"><strong>${esc(label)}</strong><span class="status not_run">未记录</span></div><div class="diagnostic-empty">暂无可查询的运行记录</div></div>`;
      }
      return `<div class="diagnostic-card">
        <div class="diagnostic-head">
          <strong>${esc(label)}</strong>
          <span class="status ${esc(run.status || "unknown")}">${esc(statusText(run.status || "unknown"))}</span>
        </div>
        <div class="diagnostic-meta">
          <span>${esc(modelDisplayText(run.model_name || "unknown"))}</span>
          <span>${esc(run.latency_ms ?? "-")} ms</span>
          <span>降级：${esc(run.fallback_used ? "是" : "否")}</span>
          <span>结构化校验：${esc(passText(run.schema_valid))}</span>
          ${run.metadata?.quality_feedback_used ? `<span>已使用质量反馈</span>` : ""}
        </div>
        ${run.summary ? `<div class="text-block">${esc(productText(run.summary))}</div>` : ""}
        ${run.error_message ? `<div class="error">${esc(productText(run.error_message))}</div>` : ""}
      </div>`;
    }

    function passText(value) {
      if (value === true) return "通过";
      if (value === false) return "未通过";
      if (value === null || value === undefined) return "未记录";
      return String(value);
    }

    function humanReviewText(status, canEnterReview) {
      const key = String(status || "").toLowerCase();
      if (key === "completed") return "已完成";
      if (key === "pending") return "待复核";
      if (key === "not_required") return "无需复核";
      if (canEnterReview === true) return "可进入复核";
      return "未开始";
    }

    function metadataName(task) {
      const metadata = task?.metadata || {};
      const company = metadata.company_name || task?.symbol || "研报任务";
      return `${company} · ${task?.period || "-"}`;
    }

    async function loadTaskDetail(taskId) {
      try {
        const analysis = await getJson(`/api/report-tasks/${encodeURIComponent(taskId)}/analysis`);
        const task = analysis.task || {};
        const delivery = taskDeliveryStatus(task);
        const events = task.events || [];
        const metadata = task.metadata || {};
        $("taskDetail").innerHTML = `<h2>任务详情</h2>
          <div class="kv"><span class="label">公司</span><span>${esc(metadata.company_name || task.symbol)} / ${esc(task.symbol)}</span></div>
          <div class="kv"><span class="label">查询期间</span><span>${esc(task.period)}</span></div>
          <div class="kv"><span class="label">报告类型</span><span>${esc(reportTypeText(task.report_type))}</span></div>
          <div class="kv"><span class="label">数据源范围</span><span>${esc(dataSourceScopeText(metadata.data_source_scope))}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(delivery.key)}">${esc(delivery.label)}</span></span></div>
          <div class="kv"><span class="label">阶段</span><span>${esc(stepText(task.current_stage))}</span></div>
          <div class="kv"><span class="label">质量分</span><span>${esc(fmt(task.quality_score))}</span></div>
          <div class="detail-section"><h3>研究问题</h3><div class="text-block">${esc(metadata.research_topic || "-")}</div></div>
          <div class="detail-section"><h3>任务操作</h3>${taskActionButtons(task)}</div>
          ${task.error_message ? `<div class="detail-section"><h3>错误</h3><div class="text-block">${esc(task.error_message)}</div></div>` : ""}
          ${renderDeliveryReadiness(task)}
          ${renderPreGenerationEvidenceGate(metadata.pre_generation_evidence_gate || {})}
          ${renderTaskLinkageOverview(analysis)}
          ${renderTaskNarrative(analysis)}
          ${renderTaskAnalysisStats(analysis.stats || {})}
          ${renderTaskEntityMemory(analysis.entity_memory || {}, task)}
          ${renderTaskSignalSummary(analysis.signal_summary || {}, task)}
          ${renderRetrievalCoverage(analysis.retrieval_coverage || analysis.quality_proof?.retrieval_coverage || {})}
          ${renderRetrievalDiagnostics(analysis.retrieval_diagnostics || {})}
          ${renderCitationUsage(analysis.citation_usage || {})}
          ${renderQualityProof(analysis.quality_proof || {}, task)}
          ${renderArgumentChain(analysis.argument_chain || {})}
          ${renderRiskChain(analysis.risk_chain || {})}
          ${renderRecommendedActions(analysis.recommended_actions || [])}
          ${renderQualityDiagnostics(task)}
          ${renderToolRuns(task)}
          <div class="detail-section"><h3>产物</h3>${artifactButtons(task)}</div>
          ${systemInfoBlock("系统信息", [["任务编号", task.task_id]])}
          <div class="detail-section"><h3>时间线</h3><div class="timeline">${
            events.length ? events.map((event) => `<div class="event"><strong>${esc(stepText(event.stage))}</strong> <span class="status ${esc(event.status)}">${esc(statusText(event.status))}</span><br><span class="label">${esc(fmt(event.created_at))}</span><br>${esc(fmt(event.message))}</div>`).join("") : `<div class="empty">暂无事件</div>`
          }</div></div>`;
        {
          const sections = Array.from($("taskDetail").querySelectorAll(":scope > .detail-section"));
          const coreCount = task.error_message ? 5 : 4;
          const advanced = sections.slice(coreCount, Math.max(coreCount, sections.length - 2));
          advanced.forEach((section) => { section.hidden = true; });
          if (advanced.length) {
            const toggle = document.createElement("button");
            toggle.className = "btn";
            toggle.type = "button";
            toggle.textContent = "展开高级分析与诊断";
            toggle.addEventListener("click", () => {
              const showing = advanced.some((section) => section.hidden);
              advanced.forEach((section) => { section.hidden = !showing; });
              toggle.textContent = showing ? "收起高级分析与诊断" : "展开高级分析与诊断";
            });
            sections[Math.max(0, coreCount - 1)]?.insertAdjacentElement("afterend", toggle);
          }
        }
        bindTaskActionButtons($("taskDetail"));
        bindTaskEntityMemoryButtons($("taskDetail"));
        bindTaskSignalButtons($("taskDetail"));
        bindJumpHandlers($("taskDetail"));
        bindCreateTaskButtons($("taskDetail"));
      } catch (error) {
        showLoadError("taskDetail");
      }
    }

    function evidenceGateStatusText(gate) {
      if (gate.blocked) return "未通过，已暂停生成";
      const map = {
        success: "正式交付可用",
        warning: "草稿可生成",
        failed: "未通过",
        skipped: "已跳过",
      };
      return textOf(map, gate.status);
    }

    function evidenceGateStatusClass(gate) {
      if (gate.blocked || gate.status === "failed") return "failed";
      if (gate.status === "success") return "passed";
      if (gate.status === "skipped") return "skipped";
      return "warning";
    }

    function evidenceReasonText(reason) {
      const sources = Array.isArray(reason?.sources) ? reason.sources : [];
      if (sources.length) return `${fmt(reason.description || reason.label || "证据来源缺口").split("：")[0]}：${sources.map(sourceText).join("、")}`;
      return fmt(reason?.description || reason?.label || "证据覆盖不足");
    }

    function renderPreGenerationEvidenceGate(gate) {
      const hasGate = gate && Object.keys(gate).length > 0;
      if (!hasGate) {
        return `<div class="detail-section"><h3>生成前证据门禁</h3><div class="empty">该任务尚未运行生成前证据检查。启动任务后会展示权威来源覆盖、拦截原因和补证据入口。</div></div>`;
      }
      const coverage = gate.coverage || {};
      const blockingReasons = gate.blocking_reasons || [];
      const deliveryBlockedReasons = gate.delivery_blocked_reasons || blockingReasons;
      const actions = gate.recommended_actions || [];
      const requiredSources = coverage.required_sources || [];
      const missingSources = coverage.missing_sources || [];
      const returnedSources = coverage.returned_sources || [];
      const draftReady = gate.draft_ready !== false && !gate.blocked;
      const deliveryReady = gate.delivery_ready === true;
      return `<div class="detail-section"><h3>生成前证据门禁</h3>
        <div class="chain-summary">${esc(gate.summary || "暂无门禁说明。")}</div>
        <div class="analysis-stats">
          <div class="analysis-stat"><span class="label">草稿生成</span><strong><span class="status ${esc(draftReady ? "passed" : "failed")}">${esc(draftReady ? "可运行" : "已暂停")}</span></strong><span class="score-note">${esc(gate.blocked ? "需先补齐证据" : "可继续生成草稿")}</span></div>
          <div class="analysis-stat"><span class="label">正式交付</span><strong><span class="status ${esc(deliveryReady ? "passed" : "failed")}">${esc(deliveryReady ? "可交付" : "待补权威来源")}</span></strong><span class="score-note">${esc(deliveryReady ? "证据覆盖满足要求" : "不应作为正式研报交付")}</span></div>
          <div class="analysis-stat"><span class="label">候选证据</span><strong>${esc(number(coverage.candidate_count || 0))}</strong><span class="score-note">进入生成前检查</span></div>
          <div class="analysis-stat"><span class="label">已命中来源</span><strong>${esc(number(returnedSources.length))}</strong><span class="score-note">${renderSourceList(returnedSources)}</span></div>
          <div class="analysis-stat"><span class="label">缺失来源</span><strong>${esc(number(missingSources.length))}</strong><span class="score-note">${missingSources.length ? renderSourceList(missingSources) : "无关键缺口"}</span></div>
        </div>
        <div class="kv"><span class="label">建议来源</span><span>${requiredSources.length ? renderSourceList(requiredSources) : "未限定"}</span></div>
        ${deliveryBlockedReasons.length ? `<div class="diagnostic-list">${deliveryBlockedReasons.map((reason) => `<div class="diagnostic-issue ${esc(reason.type || "warning")}"><div class="diagnostic-head"><strong>${esc(reason.label || "证据缺口")}</strong><span class="status failed">${esc(gate.blocked ? "阻塞生成" : "阻塞交付")}</span></div><div class="score-note">${esc(evidenceReasonText(reason))}</div></div>`).join("")}</div>` : `<div class="empty">当前没有阻塞正式交付的证据缺口。</div>`}
        <div class="links" style="margin-top:10px">
          ${actions.length ? actions.map((action) => `<button class="btn" data-jump="${esc(action.view || "evidence")}">${esc(action.label || "处理证据")}</button>`).join("") : `<button class="btn" data-jump="evidence">查看证据库</button>`}
          <button class="btn" data-jump="datasources">检查数据源</button>
          <button class="btn" data-jump="ingestion">补采集批次</button>
        </div>
      </div>`;
    }

    function renderTaskLinkageOverview(analysis) {
      const stats = analysis.stats || {};
      const task = analysis.task || {};
      const hasEvidence = Number(stats.evidence_count || 0) > 0;
      const entityMemory = analysis.entity_memory || {};
      const hasMemory = entityMemory.ready === true;
      const hasFacts = Number(stats.financial_fact_count || 0) > 0;
      const hasSignals = Number(stats.investment_signal_count || 0) > 0;
      const claimCount = Number(stats.claim_count || 0);
      const verifiedClaims = Number(stats.verified_claim_count || 0);
      const hasClaims = claimCount > 0;
      const hasReport = ["completed", "done", "exported"].includes(String(task.status || ""));
      const steps = [
        {
          title: "数据进入",
          passed: hasEvidence,
          note: hasEvidence ? `已沉淀 ${number(stats.evidence_count)} 条证据` : "还没有可复用证据",
          action: { label: "查看证据库", view: "evidence" },
        },
        {
          title: "记忆沉淀",
          passed: hasMemory,
          partial: hasEvidence && !hasMemory,
          note: hasMemory ? `已沉淀 ${number(entityMemory.entity_count)} 个实体、${number(entityMemory.relation_count)} 条关系` : "任务证据尚未形成长期结构化记忆",
          action: { label: hasMemory ? "查看关系图谱" : "沉淀任务证据", view: hasMemory ? "graph" : "tasks" },
        },
        {
          title: "结构化处理",
          passed: hasFacts,
          note: hasFacts ? `已提取 ${number(stats.financial_fact_count)} 条财务事实` : "财务事实尚未形成",
          action: { label: "查看事实中心", view: "facts" },
        },
        {
          title: "线索发现",
          passed: hasSignals,
          note: hasSignals ? `已识别 ${number(stats.investment_signal_count)} 条投资线索` : "线索仍需由事实和证据触发",
          action: { label: "查看投资线索", view: "signals" },
        },
        {
          title: "主张复核",
          passed: hasClaims && verifiedClaims === claimCount,
          partial: hasClaims && verifiedClaims < claimCount,
          note: hasClaims ? `${number(verifiedClaims)} / ${number(claimCount)} 条主张已通过` : "研报主张尚未生成",
          action: { label: "进入主张复核", view: "claims" },
        },
        {
          title: "报告输出",
          passed: hasReport || analysis.quality_proof?.delivery_pass === true,
          partial: analysis.quality_proof?.delivery_pass === false,
          note: analysis.quality_proof?.delivery_pass === true ? "质量门禁已通过，可进入导出" : "需要完成质量门禁后再导出",
          action: { label: "查看导出中心", view: "export" },
        },
      ];
      return `<div class="detail-section"><h3>分析链路总览</h3>
        <div class="chain-summary">按视频中的情报后台叙事，这里把当前研报任务串成“数据进入、记忆沉淀、结构化处理、线索发现、主张复核、报告输出”六步，便于判断任务卡在哪一环。</div>
        <div class="check-grid">${steps.map((step) => {
          const cls = step.passed ? "passed" : "failed";
          const status = step.passed ? "已完成" : (step.partial ? "需处理" : "未完成");
          return `<div class="check-item ${cls}"><div class="diagnostic-head"><strong>${esc(step.title)}</strong><span class="status ${cls}">${esc(status)}</span></div><div class="score-note">${esc(step.note)}</div><div style="margin-top:8px"><button class="btn" data-jump="${esc(step.action.view)}">${esc(step.action.label)}</button></div></div>`;
        }).join("")}</div>
      </div>`;
    }

    function renderTaskEntityMemory(memory, task) {
      const hasMemory = memory && Object.keys(memory).length > 0;
      if (!hasMemory) {
        return `<div class="detail-section"><h3>结构化记忆</h3><div class="empty">暂无记忆诊断。任务关联证据后，可以将公司、文档、指标和风险事件沉淀到实体库。</div></div>`;
      }
      const ready = memory.ready === true;
      const typeDist = memory.type_distribution || [];
      const relationDist = memory.relation_distribution || [];
      const sampleEntities = memory.sample_entities || [];
      const sampleRelations = memory.sample_relations || [];
      return `<div class="detail-section"><h3>结构化记忆</h3>
        <div class="chain-summary">${esc(memory.summary || "暂无结构化记忆说明。")}</div>
        <div class="analysis-stats">
          <div class="analysis-stat"><span class="label">记忆状态</span><strong><span class="status ${ready ? "passed" : "pending"}">${esc(ready ? "已形成" : "待沉淀")}</span></strong><span class="score-note">${esc(ready ? "可用于关系分析" : "先沉淀当前任务证据")}</span></div>
          <div class="analysis-stat"><span class="label">来源证据</span><strong>${esc(number(memory.source_evidence_count || 0))}</strong><span class="score-note">当前任务证据池</span></div>
          <div class="analysis-stat"><span class="label">已沉淀实体</span><strong>${esc(number(memory.entity_count || 0))}</strong><span class="score-note">${memoryDistributionText(typeDist, entityTypeText)}</span></div>
          <div class="analysis-stat"><span class="label">已形成关系</span><strong>${esc(number(memory.relation_count || 0))}</strong><span class="score-note">${memoryDistributionText(relationDist, relationTypeText)}</span></div>
        </div>
        <div class="check-grid">
          <div class="check-item ${sampleEntities.length ? "passed" : "failed"}"><div class="diagnostic-head"><strong>实体样例</strong><span class="status ${sampleEntities.length ? "passed" : "pending"}">${esc(sampleEntities.length ? "已有记忆" : "待沉淀")}</span></div>
            ${sampleEntities.length ? `<div class="mini-list">${sampleEntities.slice(0, 5).map((item) => `<div class="mini-item"><strong>${esc(item.canonical_name || "实体")}${item.symbol ? ` / ${esc(item.symbol)}` : ""}</strong><br><span class="label">${esc(entityTypeText(item.entity_type))} · 证据支持</span></div>`).join("")}</div>` : `<div class="empty">还没有从当前任务证据沉淀出实体。</div>`}
          </div>
          <div class="check-item ${sampleRelations.length ? "passed" : "failed"}"><div class="diagnostic-head"><strong>关系样例</strong><span class="status ${sampleRelations.length ? "passed" : "pending"}">${esc(sampleRelations.length ? "已有关系" : "待沉淀")}</span></div>
            ${sampleRelations.length ? `<div class="mini-list">${sampleRelations.slice(0, 5).map((item) => `<div class="mini-item"><strong>${esc(item.source || "实体")} → ${esc(relationTypeText(item.relation_type))} → ${esc(item.target || "实体")}</strong><br><span class="label">证据支持</span></div>`).join("")}</div>` : `<div class="empty">还没有从当前任务证据形成实体关系。</div>`}
          </div>
        </div>
        <div class="links" style="margin-top:10px">
          <button class="btn primary" data-extract-task-entities="${esc(task.task_id)}">沉淀当前任务证据</button>
          <button class="btn" data-jump="entities">查看实体库</button>
          <button class="btn" data-jump="graph">查看关系图谱</button>
        </div>
        <div id="taskEntityExtractResult"></div>
      </div>`;
    }

    function memoryDistributionText(items, labelFn) {
      const rows = Array.isArray(items) ? items : [];
      return rows.length ? rows.slice(0, 3).map((item) => `${labelFn(item.name)} ${number(item.count)}`).join("、") : "暂无分布";
    }

    function renderTaskSignalSummary(summary, task) {
      const hasSummary = summary && Object.keys(summary).length > 0;
      if (!hasSummary) {
        return `<div class="detail-section"><h3>投资线索闭环</h3><div class="empty">暂无线索诊断。导入财务事实和证据后，可以按当前任务生成风险/机会线索。</div></div>`;
      }
      const topSignals = summary.top_signals || [];
      const ready = summary.ready === true;
      return `<div class="detail-section"><h3>投资线索闭环</h3>
        <div class="chain-summary">${esc(summary.brief || "暂无线索研判摘要。")}</div>
        <div class="analysis-stats">
          <div class="analysis-stat"><span class="label">线索状态</span><strong><span class="status ${ready ? "passed" : "pending"}">${esc(ready ? "已识别" : "待生成")}</span></strong><span class="score-note">仅供研究，不构成投资建议</span></div>
          <div class="analysis-stat"><span class="label">线索总数</span><strong>${esc(number(summary.signal_count || 0))}</strong><span class="score-note">高优先级 ${esc(number(summary.high_priority_count || 0))} 条</span></div>
          <div class="analysis-stat"><span class="label">已进上下文</span><strong>${esc(number(summary.in_context_count || 0))}</strong><span class="score-note">可被研报任务引用</span></div>
          <div class="analysis-stat"><span class="label">方向分布</span><strong>${esc(number(summary.negative_count || 0))} / ${esc(number(summary.positive_count || 0))}</strong><span class="score-note">风险 / 机会</span></div>
        </div>
        <div class="check-grid">
          <div class="check-item ${topSignals.length ? "passed" : "failed"}"><div class="diagnostic-head"><strong>重点线索</strong><span class="status ${topSignals.length ? "passed" : "pending"}">${esc(topSignals.length ? "待研判" : "待生成")}</span></div>
            ${topSignals.length ? `<div class="mini-list">${topSignals.slice(0, 4).map((signal) => `<div class="mini-item">
              <strong>${esc(signal.title || "投资线索")}</strong> <span class="status ${esc(signal.severity || "medium")}">${esc(signalSeverityText(signal.severity || "medium"))}</span><br>
              <span class="label">${esc(signalDirectionText(signal.direction || "neutral"))} · ${esc(signal.priority_label || "持续观察")}</span><br>
              ${esc(signal.summary || "")}
              ${signal.recommended_action ? `<div class="score-note">建议：${esc(signal.recommended_action)}</div>` : ""}
            </div>`).join("")}</div>` : `<div class="empty">当前任务还没有线索，可先运行规则生成。</div>`}
          </div>
          <div class="check-item ${Number(summary.evidence_bound_count || 0) ? "passed" : "failed"}"><div class="diagnostic-head"><strong>证据绑定</strong><span class="status ${Number(summary.evidence_bound_count || 0) ? "passed" : "pending"}">${esc(Number(summary.evidence_bound_count || 0) ? "已有证据" : "待补证据")}</span></div>
            <div class="score-note">已有 ${esc(number(summary.evidence_bound_count || 0))} 条线索绑定证据或财务事实。高优先级线索必须可追溯后再进入正式研报。</div>
            <div id="taskSignalGenerateResult"></div>
          </div>
        </div>
        <div class="links" style="margin-top:10px">
          <button class="btn primary" data-generate-task-signals="${esc(task.task_id)}">生成当前任务线索</button>
          <button class="btn" data-jump="signals" data-signal-task-id="${esc(task.task_id)}" data-signal-company="${esc(task.symbol || "")}" data-signal-period="${esc(task.period || "")}">查看投资线索</button>
          <button class="btn" data-jump="facts">查看财务事实</button>
          <button class="btn" data-jump="claims">进入主张复核</button>
        </div>
      </div>`;
    }

    function renderTaskNarrative(analysis) {
      const items = analysis.narrative || [];
      return `<div class="detail-section"><h3>业务链路</h3><div class="timeline">${
        items.length ? items.map((item) => `<div class="event"><strong>${esc(item.stage)}</strong> <span class="status ${esc(item.status || "pending")}">${esc(statusText(item.status || "pending"))}</span><br>${esc(item.description || "")}</div>`).join("") : `<div class="empty">暂无链路数据</div>`
      }</div></div>`;
    }

    function renderTaskAnalysisStats(stats) {
      const cards = [
        ["证据", stats.evidence_count, `官方/一手 ${number(stats.official_evidence_count || 0)} 条`],
        ["财务事实", stats.financial_fact_count, "结构化指标和口径"],
        ["投资线索", stats.investment_signal_count, `高优先级 ${number(stats.high_severity_signal_count || 0)} 条`],
        ["主张校验", `${number(stats.verified_claim_count || 0)} / ${number(stats.claim_count || 0)}`, `待复核 ${number(stats.pending_review_count || 0)} 条`],
      ];
      return `<div class="detail-section"><h3>分析包概览</h3>
        <div class="analysis-stats">${cards.map(([label, value, note]) => `<div class="analysis-stat"><span class="label">${esc(label)}</span><strong>${esc(fmt(value))}</strong><span class="score-note">${esc(note)}</span></div>`).join("")}</div>
        <div class="score-note" style="margin-top:8px">引用覆盖率：${percentText(stats.citation_coverage_rate)}；主张通过率：${percentText(stats.claim_verified_rate)}；官方证据占比：${percentText(stats.official_evidence_rate)}</div>
      </div>`;
    }

    function renderQualityProof(proof, task) {
      if (["queued", "pending"].includes(String(task?.status || ""))) {
        return `<div class="detail-section"><h3>研报质量证明</h3><div class="empty">任务尚未运行。主张、数字和引用检查均为待检查，不能视为通过。</div></div>`;
      }
      const checks = proof.checks || [];
      const issues = proof.top_issues || [];
      const failedClaims = proof.failed_claims || [];
      const failedChecks = checks.filter((item) => !item.passed);
      const passedChecks = checks.filter((item) => item.passed);
      const score = proof.quality_score ?? task.quality_score;
      const reasonText = proof.delivery_pass === true
        ? `质量分 ${fmt(score)} 已满足交付门禁，主要依据是 ${number(passedChecks.length)} 项检查通过。`
        : failedChecks.length
          ? `质量分 ${fmt(score)} 尚未稳定达标，优先处理 ${failedChecks.slice(0, 3).map((item) => item.title).join("、")}。`
          : `质量分 ${fmt(score)} 仍需等待证据、主张和引用检查补齐后再判断。`;
      const gapText = failedClaims.length
        ? `当前还有 ${number(failedClaims.length)} 条主张需要复核，重点检查数字一致性、引用是否可追溯以及是否存在过度推断。`
        : failedChecks.length
          ? "当前主要缺口来自质量检查项，处理后再重新生成或刷新分析包。"
          : "当前没有主张级阻塞项，建议进入评测中心查看回归表现。";
      return `<div class="detail-section"><h3>研报质量证明</h3>
        <div class="chain-summary">${esc(productText(proof.explanation || "暂无质量解释。"))}</div>
        <div class="chain-summary"><strong>为什么是这个质量分</strong><br>${esc(reasonText)}<br><strong>还差什么</strong><br>${esc(gapText)}</div>
        <div class="kv"><span class="label">交付门禁</span><span><span class="status ${esc(proof.delivery_pass === true ? "passed" : (proof.delivery_pass === false ? "failed" : "pending"))}">${esc(passText(proof.delivery_pass))}</span></span></div>
        <div class="kv"><span class="label">质量分</span><span>${esc(fmt(proof.quality_score ?? task.quality_score))}</span></div>
        <div class="check-grid">${checks.length ? checks.map((item) => `<div class="check-item ${item.passed ? "passed" : "failed"}"><div class="diagnostic-head"><strong>${esc(productText(item.title))}</strong><span class="status ${item.passed ? "passed" : "failed"}">${esc(item.passed ? "通过" : "需处理")}</span></div><div class="score-note">${esc(productText(item.description || ""))}</div><div class="mono">${esc(checkValueText(item))}</div></div>`).join("") : `<div class="empty">暂无质量检查项</div>`}</div>
        ${issues.length ? `<div class="detail-section"><h3>主要问题</h3><div class="diagnostic-list">${issues.slice(0, 5).map((issue) => `<div class="diagnostic-issue ${esc(issue.severity || "")}">${esc(productText(issue.message || issue))}</div>`).join("")}</div></div>` : ""}
        ${failedClaims.length ? `<div class="detail-section"><h3>需关注主张</h3><div class="mini-list">${failedClaims.slice(0, 5).map((claim) => `<div class="mini-item"><strong>主张 ${esc(claim.id)}</strong><br>${esc(claim.claim_text || "")}<br><span class="label">校验：${esc(statusText(claim.verification_status))} · 数字：${esc(statusText(claim.numeric_check_status))} · 引用：${esc(statusText(claim.citation_check_status))}</span></div>`).join("")}</div></div>` : ""}
        <div class="links" style="margin-top:10px">
          <button class="btn" data-jump="claims">查看主张复核</button>
          <button class="btn" data-jump="evidence">查看证据库</button>
          <button class="btn" data-jump="evaluation">进入评测中心</button>
        </div>
      </div>`;
    }

    function renderRetrievalCoverage(coverage) {
      const candidateCount = Number(coverage.candidate_count || 0);
      const returnedCount = Number(coverage.returned_count || 0);
      const returnedSources = coverage.returned_sources || [];
      const missingSources = coverage.missing_sources || [];
      const gaps = coverage.gaps || [];
      if (!candidateCount && !returnedCount && !gaps.length) {
        return `<div class="detail-section"><h3>证据召回准备度</h3><div class="empty">暂无召回诊断。完成证据导入或研报任务后会展示来源覆盖和缺口。</div></div>`;
      }
      return `<div class="detail-section"><h3>证据召回准备度</h3>
        <div class="analysis-stats">
          <div class="analysis-stat"><span class="label">候选证据</span><strong>${esc(number(candidateCount))}</strong><span class="score-note">进入任务证据池</span></div>
          <div class="analysis-stat"><span class="label">可用证据</span><strong>${esc(number(returnedCount))}</strong><span class="score-note">${esc(coverage.evidence_ready ? "已可复核" : "需要补证据")}</span></div>
          <div class="analysis-stat"><span class="label">命中来源</span><strong>${esc(number(returnedSources.length))}</strong><span class="score-note">${renderSourceList(returnedSources)}</span></div>
          <div class="analysis-stat"><span class="label">来源缺口</span><strong>${esc(number(missingSources.length))}</strong><span class="score-note">${missingSources.length ? renderSourceList(missingSources) : "无关键缺口"}</span></div>
        </div>
        <div class="chain-summary">${esc(productText(coverage.summary || "暂无召回说明。"))}</div>
        ${gaps.length ? `<div class="diagnostic-list">${gaps.map((gap) => `<div class="diagnostic-issue ${esc(gap.type || "")}">
          <div class="diagnostic-head"><strong>${esc(productText(gap.label || "证据缺口"))}</strong><button class="btn" data-jump="${esc(gap.next_view || "evidence")}">去处理</button></div>
          <div class="score-note">${esc(productText(gap.description || ""))}</div>
        </div>`).join("")}</div>` : `<div class="empty">当前未发现明显召回缺口。</div>`}
      </div>`;
    }

    function retrievalStageText(value) {
      const map = {
        ready: "证据可用",
        source_gap: "来源待补齐",
        no_hits: "资料未命中",
        no_data: "暂无候选资料",
      };
      return textOf(map, value);
    }

    function retrievalReasonText(value) {
      const map = {
        no_candidates: "没有候选证据",
        period_or_query_mismatch: "期间或查询条件未命中",
        missing_required_source: "缺少必要权威来源",
        retrieval_gap: "证据召回缺口",
      };
      return value ? productText(textOf(map, value)) : "无阻塞原因";
    }

    function renderEvidenceExamples(items) {
      const rows = Array.isArray(items) ? items : [];
      if (!rows.length) return `<div class="empty">暂无样例</div>`;
      return `<div class="mini-list">${rows.slice(0, 5).map((item) => `<div class="mini-item"><strong>${esc(productText(item.title || "证据资料"))}</strong><br><span class="label">${esc(sourceDisplayText(item.source_type))} · ${esc(statusText(item.trust_level))} · ${esc(item.report_period || "未标期间")}</span></div>`).join("")}</div>`;
    }

    function renderRetrievalDiagnostics(diagnostics) {
      const hasDiagnostics = diagnostics && Object.keys(diagnostics).length > 0;
      if (!hasDiagnostics) {
        return `<div class="detail-section"><h3>证据召回诊断</h3><div class="empty">暂无召回诊断。完成证据导入或任务运行后会展示候选资料、命中结果和缺口原因。</div></div>`;
      }
      const query = diagnostics.query || {};
      const actions = diagnostics.recommended_actions || [];
      const candidateExamples = diagnostics.candidate_examples || [];
      const returnedExamples = diagnostics.returned_examples || [];
      const missingSources = diagnostics.missing_sources || [];
      const returnedSources = diagnostics.returned_sources || [];
      const stage = diagnostics.stage || "";
      const stageClass = stage === "ready" ? "passed" : (stage === "source_gap" ? "warning" : "failed");
      return `<div class="detail-section"><h3>证据召回诊断</h3>
        <div class="chain-summary">${esc(productText(diagnostics.summary || "暂无诊断说明。"))}</div>
        <div class="analysis-stats">
          <div class="analysis-stat"><span class="label">诊断阶段</span><strong><span class="status ${esc(stageClass)}">${esc(retrievalStageText(stage))}</span></strong><span class="score-note">${esc(retrievalReasonText(diagnostics.failure_reason))}</span></div>
          <div class="analysis-stat"><span class="label">候选资料</span><strong>${esc(number(diagnostics.candidate_count || 0))}</strong><span class="score-note">公司/任务相关资料池</span></div>
          <div class="analysis-stat"><span class="label">命中证据</span><strong>${esc(number(diagnostics.returned_count || 0))}</strong><span class="score-note">${renderSourceList(returnedSources)}</span></div>
          <div class="analysis-stat"><span class="label">来源缺口</span><strong>${esc(number(missingSources.length))}</strong><span class="score-note">${missingSources.length ? renderSourceList(missingSources) : "无关键缺口"}</span></div>
        </div>
        <div class="kv"><span class="label">查询口径</span><span>${esc(query.company_name || query.symbol || "-")} · ${esc(query.period || "-")} · ${esc(dataSourceScopeText(query.data_source_scope))}</span></div>
        <div class="check-grid">
          <div class="check-item ${candidateExamples.length ? "passed" : "failed"}"><div class="diagnostic-head"><strong>候选资料样例</strong><span class="status ${candidateExamples.length ? "passed" : "failed"}">${esc(candidateExamples.length ? "有资料" : "需补资料")}</span></div>${renderEvidenceExamples(candidateExamples)}</div>
          <div class="check-item ${returnedExamples.length ? "passed" : "failed"}"><div class="diagnostic-head"><strong>已命中证据</strong><span class="status ${returnedExamples.length ? "passed" : "failed"}">${esc(returnedExamples.length ? "已命中" : "未命中")}</span></div>${renderEvidenceExamples(returnedExamples)}</div>
        </div>
        <div class="links" style="margin-top:10px">
          ${actions.length ? actions.map((action) => `<button class="btn" data-jump="${esc(action.view || "evidence")}">${esc(action.label || "处理证据")}</button>`).join("") : `<button class="btn" data-jump="evidence">查看证据库</button>`}
        </div>
      </div>`;
    }

    function citationUsageStatusText(value) {
      const map = {
        ready: "引用闭环已形成",
        citation_gap: "正文引用待补齐",
        no_citations: "缺少引用清单",
        no_traceable_claims: "主张未绑定证据",
        no_claims: "缺少研报主张",
      };
      return productText(textOf(map, value));
    }

    function citationUsageStatusClass(value, ready) {
      if (ready) return "passed";
      if (value === "citation_gap" || value === "no_citations" || value === "no_traceable_claims") return "failed";
      return "pending";
    }

    function renderCitationUsage(usage) {
      const hasUsage = usage && Object.keys(usage).length > 0;
      if (!hasUsage) {
        return `<div class="detail-section"><h3>引用覆盖闭环</h3><div class="empty">暂无引用覆盖诊断。任务完成并导入引用产物后，会检查证据引用是否真正进入报告正文。</div></div>`;
      }
      const status = usage.status || "";
      const ready = usage.ready === true;
      const statusClass = citationUsageStatusClass(status, ready);
      const gaps = usage.claims_without_used_citation || [];
      const unused = usage.unused_citations || [];
      const actions = usage.recommended_actions || [];
      const chainRows = gaps.length ? gaps : (usage.claims_with_used_citation || usage.used_claims || []);
      return `<div class="detail-section"><h3>引用覆盖闭环</h3>
        <div class="chain-summary">${esc(productText(usage.summary || "暂无引用覆盖说明。"))}</div>
        <div class="analysis-stats">
          <div class="analysis-stat"><span class="label">闭环状态</span><strong><span class="status ${esc(statusClass)}">${esc(citationUsageStatusText(status))}</span></strong><span class="score-note">${esc(ready ? "可用于质量证明" : "需要处理后再交付")}</span></div>
          <div class="analysis-stat"><span class="label">正文已使用引用</span><strong>${esc(number(usage.used_citation_count || 0))} / ${esc(number(usage.citation_count || 0))}</strong><span class="score-note">${esc(percentText(usage.citation_usage_rate))}</span></div>
          <div class="analysis-stat"><span class="label">可追溯主张</span><strong>${esc(number(usage.used_claim_count || 0))} / ${esc(number(usage.traceable_claim_count || 0))}</strong><span class="score-note">${esc(percentText(usage.claim_usage_rate))}</span></div>
          <div class="analysis-stat"><span class="label">待补齐</span><strong>${esc(number(gaps.length))}</strong><span class="score-note">未在正文找到已使用引用的主张</span></div>
        </div>
        <div class="detail-section"><h3>报告引用证据链</h3>
          ${chainRows.length ? `<div class="mini-list">${chainRows.slice(0, 5).map(renderCitationClaimTrace).join("")}</div>` : `<div class="empty">暂无可展示的主张到证据链路。任务完成并导入主张、引用产物后会自动补全。</div>`}
        </div>
        <div class="check-grid">
          <div class="check-item ${gaps.length ? "failed" : "passed"}"><div class="diagnostic-head"><strong>缺引用主张</strong><span class="status ${gaps.length ? "failed" : "passed"}">${esc(gaps.length ? "需处理" : "无缺口")}</span></div>
            ${gaps.length ? `<div class="mini-list">${gaps.slice(0, 5).map((claim) => `<div class="mini-item"><strong>${esc(productText(claim.section_name || "研报主张"))}</strong><br>${esc(productText(claim.claim_text || ""))}<br><span class="label">关联证据：${esc(number((claim.evidence_ids || []).length))} 条</span></div>`).join("")}</div>` : `<div class="empty">所有可追溯主张都已找到正文引用。</div>`}
          </div>
          <div class="check-item ${unused.length ? "failed" : "passed"}"><div class="diagnostic-head"><strong>未进入正文的引用</strong><span class="status ${unused.length ? "failed" : "passed"}">${esc(unused.length ? "需核对" : "无缺口")}</span></div>
            ${unused.length ? `<div class="mini-list">${unused.slice(0, 5).map((item) => `<div class="mini-item"><strong>${esc(productText(item.title || "证据引用"))}</strong><br><span class="label">${esc(sourceDisplayText(item.source_type))} · ${esc(statusText(item.trust_level || item.source_authority || "unknown"))}</span></div>`).join("")}</div>` : `<div class="empty">引用清单中的证据均已进入报告正文。</div>`}
          </div>
        </div>
        <div class="links" style="margin-top:10px">
          ${actions.length ? actions.map((action) => `<button class="btn" data-jump="${esc(action.view || "claims")}">${esc(action.label || "处理引用")}</button>`).join("") : `<button class="btn" data-jump="claims">进入主张复核</button>`}
          <button class="btn" data-jump="export">查看报告产物</button>
        </div>
      </div>`;
    }

    function renderCitationClaimTrace(claim) {
      const evidenceCount = (claim.evidence_ids || claim.citation_ids || []).length;
      const status = evidenceCount ? "证据已绑定" : "待补证据";
      return `<div class="mini-item">
        <strong>${esc(productText(claim.section_name || claim.section || "研报主张"))}</strong>
        <span class="status ${evidenceCount ? "passed" : "failed"}">${esc(status)}</span><br>
        ${esc(productText(claim.claim_text || claim.text || ""))}<br>
        <span class="label">证据链路：报告结论 → 主张复核 → ${esc(number(evidenceCount))} 条证据 → 正文引用</span>
      </div>`;
    }

    function renderArgumentChain(chain) {
      const nodes = chain.nodes || [];
      const edges = chain.edges || [];
      const flow = chain.flow || [];
      const gaps = chain.gaps || [];
      const readiness = chain.readiness || {};
      const actions = chain.recommended_actions || [];
      return `<div class="detail-section"><h3>投资逻辑链</h3>
        <div class="chain-summary">${esc(chain.summary || "尚未形成投资逻辑链。")}</div>
        ${readiness.summary ? `<div class="diagnostic-meta"><span>闭环进度：${esc(number(readiness.completed_stage_count || 0))} / ${esc(number(readiness.total_stage_count || 0))}</span><span>缺口：${esc(number(readiness.gap_count || 0))}</span></div>` : ""}
        ${renderArgumentFlow(flow)}
        ${renderChainGaps(gaps, actions)}
        <div class="chain-list">${nodes.length ? nodes.slice(0, 8).map((node) => {
          const outgoing = edges.filter((edge) => edge.from === node.id).slice(0, 2);
          const evidenceText = renderEvidenceIds(node.evidence_ids || []);
          return `<div class="chain-node"><div class="chain-node-head"><strong>${esc(node.title || node.id)}</strong><span class="status ${esc(node.type || "neutral")}">${esc(node.stage_label || chainNodeTypeText(node.type))}</span></div><div class="score-note">${esc(node.description || "")}</div>${evidenceText}${outgoing.map((edge) => `<div class="chain-edge">→ ${esc(edge.label || "关联")} → ${esc(chainTargetTitle(edge.to, nodes))}</div>`).join("")}</div>`;
        }).join("") : `<div class="empty">暂无可展示链路。导入证据、财务事实和投资线索后会自动补全。</div>`}</div>
      </div>`;
    }

    function renderRiskChain(chain) {
      const nodes = chain.nodes || [];
      const risks = nodes.filter((node) => node.type === "risk");
      const paths = chain.exposure_paths || [];
      const gaps = chain.gaps || [];
      const readiness = chain.readiness || {};
      const actions = chain.recommended_actions || [];
      return `<div class="detail-section"><h3>风险传导链</h3>
        <div class="chain-summary">${esc(chain.summary || "尚未识别风险传导节点。")}</div>
        ${readiness.summary ? `<div class="diagnostic-meta"><span>支撑绑定 ${esc(number(readiness.support_bound_count ?? readiness.evidence_bound_count ?? 0))} / ${esc(number(readiness.risk_count || 0))}</span><span>缺口 ${esc(number(readiness.gap_count || 0))}</span></div>` : ""}
        ${renderRiskPaths(paths)}
        ${renderChainGaps(gaps, actions)}
        <div class="mini-list">${risks.length ? risks.slice(0, 5).map((node) => `<div class="mini-item"><strong>${esc(node.title || "风险线索")}</strong><br><span class="label">${esc(signalSeverityText(node.payload?.severity || ""))} · ${esc(signalDirectionText(node.payload?.direction || ""))}</span><br>${esc(node.payload?.summary || "")}${renderEvidenceIds(node.evidence_ids || [])}</div>`).join("") : `<div class="empty">暂无风险线索，可先在投资线索页生成。</div>`}</div>
      </div>`;
    }

    function renderArgumentFlow(flow) {
      if (!flow.length) return "";
      return `<div class="logic-flow">${flow.map((stage) => `<div class="logic-stage ${esc(stage.status || "missing")}">
        <span class="label">${esc(stage.label || stage.key)}</span>
        <span class="count">${esc(number(stage.count || 0))}</span>
        <strong>${esc(stage.title || stage.label || "")}</strong>
        <span class="score-note">${esc(stage.description || "")}</span>
        ${renderEvidenceIds(stage.evidence_ids || [])}
      </div>`).join("")}</div>`;
    }

    function renderChainGaps(gaps, actions) {
      if (!gaps.length && !actions.length) return "";
      const gapHtml = gaps.length
        ? `<div class="mini-list">${gaps.slice(0, 4).map((gap) => `<div class="mini-item"><strong>${esc(gap.label || "待补齐")}</strong><br>${esc(gap.description || "")}</div>`).join("")}</div>`
        : `<div class="empty">当前链路没有明显缺口。</div>`;
      const actionHtml = actions.length
        ? `<div class="links" style="margin-top:10px">${actions.slice(0, 4).map((action) => `<button class="btn" data-jump="${esc(action.view || "tasks")}">${esc(action.label || "处理")}</button>`).join("")}</div>`
        : "";
      return `<div class="chain-node"><div class="chain-node-head"><strong>链路缺口</strong><span class="status ${gaps.length ? "pending" : "passed"}">${esc(gaps.length ? "需处理" : "已闭环")}</span></div>${gapHtml}${actionHtml}</div>`;
    }

    function renderRiskPaths(paths) {
      if (!paths.length) return "";
      return `<div class="mini-list">${paths.slice(0, 4).map((path) => {
        const claims = path.affected_claims || [];
        const binding = path.evidence_binding || {};
        const transmission = path.transmission || [];
        return `<div class="risk-path">
          <div class="diagnostic-head"><strong>${esc(path.title || "风险线索")}</strong><span class="status ${binding.ready ? "passed" : "failed"}">${esc(riskBindingText(binding))}</span></div>
          <div class="score-note">${esc(path.summary || "")}</div>
          ${renderEvidenceIds(binding.evidence_ids || [])}
          ${binding.source_fact_id && !(binding.evidence_ids || []).length ? `<div class="reason-list"><span class="reason-pill">财务事实 ${esc(binding.source_fact_id)}</span></div>` : ""}
          <div class="transmission">${transmission.map((item) => `<span>${esc(item.stage || "")}：${esc(item.text || "")}</span>`).join("")}</div>
          ${claims.length ? `<div class="mini-list">${claims.slice(0, 3).map((claim) => `<div class="mini-item"><strong>${esc(claim.section_name || "报告章节")}</strong><br>${esc(claim.claim_text || "")}<br><span class="label">校验：${esc(statusText(claim.verification_status))}</span></div>`).join("")}</div>` : `<div class="empty">该风险还没有承接到研报主张。</div>`}
        </div>`;
      }).join("")}</div>`;
    }

    function renderEvidenceIds(ids) {
      const values = (ids || []).filter(Boolean);
      if (!values.length) return "";
      return `<div class="reason-list"><span class="reason-pill">已绑定 ${esc(number(values.length))} 条证据</span></div>`;
    }

    function riskBindingText(binding) {
      if (!binding?.ready) return "支撑待补齐";
      if (binding.support_type === "financial_fact") return "已绑定财务事实";
      return "证据已绑定";
    }

    function renderRecommendedActions(actions) {
      return `<div class="detail-section"><h3>下一步动作</h3>
        <div class="action-list">${actions.length ? actions.map((item) => `<div class="action-item"><div class="diagnostic-head"><strong>${esc(item.label)}</strong><button class="btn" data-jump="${esc(item.view || "tasks")}">前往</button></div><div class="score-note">${esc(item.reason || "")}</div></div>`).join("") : `<div class="empty">当前任务暂无阻塞动作。</div>`}</div>
      </div>`;
    }

    function percentText(value) {
      if (value === null || value === undefined || value === "") return "未记录";
      return `${Math.round(Number(value) * 1000) / 10}%`;
    }

    function checkValueText(item) {
      if (typeof item.value === "number" && item.value >= 0 && item.value <= 1) return `当前值：${percentText(item.value)}`;
      return `当前值：${fmt(item.value)}`;
    }

    function chainNodeTypeText(value) {
      const map = { evidence: "事件", fact: "财务事实", signal: "投资线索", claim: "主张", company: "实体", risk: "风险线索", report_section: "报告章节" };
      return textOf(map, value);
    }

    function benchmarkSuiteTypeText(value) {
      const map = { quick9: "Quick-9", formal18: "Formal-18", regression: "回归集", benchmark: "基准集" };
      return textOf(map, value);
    }

    function chainTargetTitle(id, nodes) {
      const node = nodes.find((item) => item.id === id);
      return node?.title || id;
    }

    function bindTaskEntityMemoryButtons(root = document) {
      root.querySelectorAll("[data-extract-task-entities]").forEach((btn) => {
        if (btn.dataset.boundExtractTaskEntities === "true") return;
        btn.dataset.boundExtractTaskEntities = "true";
        btn.addEventListener("click", () => extractEntitiesFromTask(btn.dataset.extractTaskEntities));
      });
    }

    function bindTaskSignalButtons(root = document) {
      root.querySelectorAll("[data-generate-task-signals]").forEach((btn) => {
        if (btn.dataset.boundGenerateTaskSignals === "true") return;
        btn.dataset.boundGenerateTaskSignals = "true";
        btn.addEventListener("click", () => generateSignalsForTask(btn.dataset.generateTaskSignals));
      });
    }

    async function extractEntitiesFromTask(taskId) {
      const resultBox = $("taskEntityExtractResult");
      if (resultBox) resultBox.innerHTML = `<div class="empty">正在沉淀当前任务证据...</div>`;
      try {
        const result = await postJson("/api/entities/extract-from-task", { task_id: taskId });
        if (resultBox) {
          resultBox.innerHTML = `<div class="empty">已从 ${esc(number(result.evidence_count))} 条证据沉淀 ${esc(number(result.entity_count))} 个实体、${esc(number(result.relation_count))} 条关系。</div>
            <div class="links"><button class="btn primary" data-jump="entities">查看实体库</button><button class="btn" data-jump="graph">查看关系图谱</button></div>`;
          bindJumpHandlers(resultBox);
        }
        await loadTaskDetail(taskId);
        if (activeState.view === "entities") await loadEntities();
        if (activeState.view === "graph") await loadRelations();
      } catch (error) {
        if (resultBox) resultBox.innerHTML = `<div class="error">沉淀失败，请先确认该任务已经关联证据。</div>`;
      }
    }

    async function generateSignalsForTask(taskId) {
      const resultBox = $("taskSignalGenerateResult");
      if (resultBox) resultBox.innerHTML = `<div class="empty">正在根据当前任务证据和财务事实生成线索...</div>`;
      try {
        const result = await postJson("/api/investment-signals/generate", { task_id: taskId });
        if (resultBox) {
          resultBox.innerHTML = `<div class="empty">已生成或更新 ${esc(number(result.generated))} 条线索。规则线索仅供研究，不构成投资建议。</div>
            <div class="links"><button class="btn primary" data-jump="signals" data-signal-task-id="${esc(taskId)}">查看当前任务线索</button><button class="btn" data-jump="claims">进入主张复核</button></div>`;
          bindJumpHandlers(resultBox);
        }
        await loadTaskDetail(taskId);
        if (activeState.view === "signals") await loadSignals();
        loadDashboard();
      } catch (error) {
        if (resultBox) resultBox.innerHTML = `<div class="error">生成失败，请先确认该任务有公司、期间或可用财务事实。</div>`;
      }
    }

    async function loadEvidence() {
      const params = new URLSearchParams();
      const q = $("evidenceQuery").value.trim();
      const company = $("evidenceCompany").value.trim();
      const period = $("evidencePeriod").value.trim();
      const taskId = $("evidenceTask").value.trim();
      const source = $("evidenceSource").value;
      const trust = $("evidenceTrust").value;
      const mode = $("evidenceMode").value;
      if (q) params.set("q", q);
      if (company) params.set("company", company);
      if (period) params.set("period", period);
      if (taskId) params.set("task_id", taskId);
      if (source) params.set("source_type", source);
      if (trust) params.set("trust_level", trust);
      if (mode) params.set("mode", mode);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/evidence" + suffix);
        const rows = payload.items || [];
        const searchMetaRow = renderEvidenceSearchMetaRow(payload.search_meta || null);
        evidenceSearchContext = new Map(rows.map((item) => [item.evidence_id, item.search]).filter(([, info]) => info));
        $("evidenceRows").innerHTML = rows.length
          ? `${searchMetaRow}${rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-evidence-detail="${esc(item.evidence_id)}">${esc(evidenceDisplayTitle(item))}</button><br>${esc(item.snippet || "")}</td>
              <td>${renderEvidenceSearchSummary(item)}</td>
              <td>${esc(sourceText(item.source_type))}<br><span class="label">${esc(fmt(item.source_url))}</span></td>
              <td><span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span></td>
              <td>${esc(item.document?.title || "-")}<br><span class="label">${esc(item.document?.report_period || "")}</span></td>
              <td>${esc(number(item.claim_count))}</td>
            </tr>`).join("")}`
          : `${searchMetaRow}<tr><td colspan="6"><div class="empty">暂无证据</div></td></tr>`;
        document.querySelectorAll("[data-evidence-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadEvidenceDetail(btn.dataset.evidenceDetail));
        });
      } catch (error) {
        showLoadError("evidenceRows", 6);
      }
    }

    function renderEvidenceSearchMetaRow(meta) {
      if (!meta || meta.mode !== "hybrid") return "";
      const coverage = meta.coverage || {};
      const gaps = coverage.gaps || [];
      const components = (meta.components || []).join("、") || "关键词与证据质量";
      const missingSources = (coverage.missing_sources || []).map(sourceText).join("、");
      return `<tr><td colspan="6">
        <div class="chain-summary" style="margin-bottom:0">
          <strong>证据召回诊断</strong><br>
          ${esc(coverage.summary || "已完成智能检索。")}
          <div class="diagnostic-meta" style="margin-top:6px">
            <span>候选证据：${esc(number(coverage.candidate_count || meta.candidate_count || 0))}</span>
            <span>返回结果：${esc(number(coverage.returned_count || meta.returned_hit_count || 0))}</span>
            <span>检索路径：${esc(components)}</span>
            <span>降级：${esc(meta.fallback_used ? "已启用" : "未启用")}</span>
          </div>
          ${missingSources ? `<div class="score-note">待补来源：${esc(missingSources)}</div>` : ""}
          ${gaps.length ? `<div class="reason-list">${gaps.slice(0, 3).map((gap) => `<span class="reason-pill">${esc(gap.label || gap.type)}</span>`).join("")}</div>` : ""}
        </div>
      </td></tr>`;
    }

    async function loadDictionary() {
      const params = new URLSearchParams();
      const q = $("dictionaryQuery").value.trim();
      const type = $("dictionaryType").value;
      if (q) params.set("q", q);
      if (type) params.set("term_type", type);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/dictionary" + suffix);
        const rows = payload.items || [];
        $("dictionaryRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-dictionary-detail="${esc(item.id)}">${esc(item.canonical_name)}</button><br><span class="label">${esc(item.description || "用于识别别名和口径")}</span></td>
              <td><span class="status ${esc(item.term_type)}">${esc(statusText(item.term_type))}</span></td>
              <td>${esc(item.symbol || "-")}<br><span class="label">${esc(marketText(item.market))}</span></td>
              <td>${renderList(item.aliases)}</td>
              <td>${esc(item.description || "-")}</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty"><div>暂无金融词典词条</div><div class="empty-actions"><button class="btn primary" id="focusDictionaryCreate">添加词条</button></div></div></td></tr>`;
        document.querySelectorAll("[data-dictionary-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadDictionaryDetail(btn.dataset.dictionaryDetail));
        });
        const focus = $("focusDictionaryCreate");
        if (focus) focus.addEventListener("click", () => $("dictionaryCanonical").focus());
      } catch (error) {
        showLoadError("dictionaryRows", 5);
      }
    }

    function renderDictionaryCreatePanel(message = "") {
      $("dictionaryDetail").innerHTML = `<h2>添加词条</h2>
        <div class="form-grid">
          <div class="field">
            <label for="dictionaryCreateType">类型</label>
            <select id="dictionaryCreateType">
              <option value="company">公司别名</option>
              <option value="metric">财务指标</option>
              <option value="product">产品别名</option>
              <option value="industry">行业术语</option>
              <option value="risk">风险词</option>
              <option value="exclude">排除词</option>
            </select>
          </div>
          <div class="field">
            <label for="dictionaryMarket">市场</label>
                  <input id="dictionaryMarket" placeholder="美股 / A 股 / 港股" />
          </div>
          <div class="field full">
            <label for="dictionaryCanonical">标准词</label>
            <input id="dictionaryCanonical" placeholder="例如：苹果公司 / 营业收入 / 毛利率" />
          </div>
          <div class="field">
            <label for="dictionarySymbol">股票代码</label>
            <input id="dictionarySymbol" placeholder="公司词条可填，如 AAPL" />
          </div>
          <div class="field">
            <label for="dictionaryAliases">别名</label>
            <input id="dictionaryAliases" placeholder="苹果, Apple, Apple Inc." />
          </div>
          <div class="field full">
            <label for="dictionaryDescription">说明</label>
            <textarea id="dictionaryDescription" rows="3" placeholder="口径、用途或排除原因。"></textarea>
          </div>
        </div>
        <div class="modal-actions"><button class="btn primary" id="createDictionaryTerm">添加词条</button></div>
        <div id="dictionaryMessage">${message}</div>`;
      bindCreateDictionaryButton();
      $("dictionaryCanonical").focus();
    }

    function bindCreateDictionaryButton() {
      const button = $("createDictionaryTerm");
      if (!button || button.dataset.boundCreateDictionary === "true") return;
      button.dataset.boundCreateDictionary = "true";
      button.addEventListener("click", createDictionaryTerm);
    }

    async function loadDictionaryDetail(termId) {
      try {
        const item = await getJson(`/api/dictionary/terms/${encodeURIComponent(termId)}`);
        renderDictionaryDetail(item);
      } catch (error) {
        $("dictionaryDetail").insertAdjacentHTML("afterbegin", `<div class="error">词条加载失败，请刷新后重试。</div>`);
      }
    }

    function renderDictionaryDetail(item) {
      const defaultAlias = (item.aliases || []).find((alias) => alias !== item.canonical_name) || item.canonical_name || "";
      $("dictionaryDetail").innerHTML = `<h2>词条详情</h2>
        <div class="kv"><span class="label">标准词</span><span>${esc(item.canonical_name)}</span></div>
        <div class="kv"><span class="label">类型</span><span><span class="status ${esc(item.term_type)}">${esc(statusText(item.term_type))}</span></span></div>
        <div class="kv"><span class="label">代码</span><span>${esc(item.symbol || "-")}</span></div>
        <div class="kv"><span class="label">市场</span><span>${esc(marketText(item.market))}</span></div>
        <div class="detail-section"><h3>别名</h3><div class="text-block">${esc((item.aliases || []).join("\\n") || "-")}</div></div>
        <div class="detail-section"><h3>说明</h3><div class="text-block">${esc(item.description || "-")}</div></div>
        <div class="detail-section"><h3>解析测试</h3>
          <div class="form-grid">
            <div class="field"><label for="dictionaryResolveQuery">待解析文本</label><input id="dictionaryResolveQuery" value="${esc(defaultAlias)}" /></div>
            <div class="field"><label for="dictionaryResolveType">类型</label><select id="dictionaryResolveType">
              <option value="">全部类型</option>
              <option value="company"${item.term_type === "company" ? " selected" : ""}>公司别名</option>
              <option value="metric"${item.term_type === "metric" ? " selected" : ""}>财务指标</option>
              <option value="product"${item.term_type === "product" ? " selected" : ""}>产品别名</option>
              <option value="industry"${item.term_type === "industry" ? " selected" : ""}>行业术语</option>
              <option value="risk"${item.term_type === "risk" ? " selected" : ""}>风险词</option>
              <option value="exclude"${item.term_type === "exclude" ? " selected" : ""}>排除词</option>
            </select></div>
            <div class="field"><label for="dictionaryResolveMarket">市场</label><input id="dictionaryResolveMarket" value="${esc(item.market || "")}" placeholder="美股 / A 股 / 港股" /></div>
          </div>
          <div class="links"><button class="btn primary" id="testDictionaryResolve">测试解析</button><button class="btn" data-dictionary-create="true">新增词条</button></div>
          <div id="dictionaryResolveResult"></div>
        </div>
        <div class="detail-section"><h3>用途</h3><div class="empty">用于公司归一、指标归一、查询理解和后续检索扩展；词典记录本身不替代证据。</div></div>`;
      $("testDictionaryResolve").addEventListener("click", testDictionaryResolve);
      document.querySelectorAll("[data-dictionary-create]").forEach((btn) => btn.addEventListener("click", () => renderDictionaryCreatePanel()));
    }

    async function testDictionaryResolve() {
      const params = new URLSearchParams();
      const q = $("dictionaryResolveQuery").value.trim();
      const type = $("dictionaryResolveType").value;
      const market = marketValue($("dictionaryResolveMarket").value);
      if (!q) {
        $("dictionaryResolveResult").innerHTML = `<div class="error">请输入要解析的别名或术语。</div>`;
        return;
      }
      params.set("q", q);
      if (type) params.set("term_type", type);
      if (market) params.set("market", market);
      try {
        const resolved = await getJson(`/api/dictionary/resolve?${params.toString()}`);
        $("dictionaryResolveResult").innerHTML = `<div class="empty">已解析为：${esc(resolved.canonical_name)}${resolved.symbol ? ` / ${esc(resolved.symbol)}` : ""}<br><span class="label">命中别名：${esc(resolved.matched_alias || q)}</span></div>`;
      } catch (error) {
        $("dictionaryResolveResult").innerHTML = `<div class="error">未命中词典，请检查类型、市场或别名。</div>`;
      }
    }

    async function createDictionaryTerm() {
      const payload = {
        term_type: $("dictionaryCreateType").value,
        canonical_name: $("dictionaryCanonical").value.trim(),
        symbol: $("dictionarySymbol").value.trim(),
        market: marketValue($("dictionaryMarket").value),
        aliases: csvList($("dictionaryAliases").value),
        description: $("dictionaryDescription").value.trim(),
      };
      if (!payload.canonical_name) {
        $("dictionaryMessage").innerHTML = `<div class="error">请输入标准词。</div>`;
        return;
      }
      try {
        const item = await postJson("/api/dictionary", payload);
        $("dictionaryMessage").innerHTML = `<div class="empty">已添加词条：${esc(item.canonical_name)}</div>`;
        await loadDictionary();
        renderDictionaryDetail(item);
      } catch (error) {
        $("dictionaryMessage").innerHTML = `<div class="error">添加失败，词条可能已存在。</div>`;
      }
    }

    async function loadPromptOps() {
      const params = new URLSearchParams();
      const module = promptModuleValue($("promptModule").value);
      if (module) params.set("module", module);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const [templates, runs] = await Promise.all([
          getJson("/api/promptops/templates" + suffix),
          getJson("/api/llm-runs?limit=8"),
        ]);
        const rows = templates.items || [];
        $("promptRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-prompt-detail="${esc(item.prompt_key)}">${esc(item.name || promptKeyText(item.prompt_key))}</button><br><span class="label">${esc(item.description || promptKeyText(item.prompt_key))}</span></td>
              <td>${esc(promptModuleText(item.module))}</td>
              <td><span class="status ${item.is_active ? "completed" : "archived"}">${esc(item.is_active ? "启用中" : "已停用")}</span></td>
              <td>${esc(item.active_version ? "v" + item.active_version : "-")}</td>
              <td>${Object.keys(item.schema || {}).length ? `<span class="status completed">已配置</span>` : `<span class="status pending">未配置</span>`}</td>
              <td><button class="btn primary" data-prompt-test="${esc(item.prompt_key)}">测试运行</button></td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">暂无提示词模板</div></td></tr>`;
        document.querySelectorAll("[data-prompt-detail]").forEach((btn) => btn.addEventListener("click", () => loadPromptDetail(btn.dataset.promptDetail)));
        bindPromptTestButtons($("promptRows"));
        renderLlmRuns(runs.items || []);
      } catch (error) {
        showLoadError("promptRows", 6);
      }
    }

    function renderLlmRuns(rows) {
      $("llmRunRows").innerHTML = rows.length
        ? rows.map((item) => `<tr>
            <td><button class="btn" data-llm-run="${esc(item.run_id)}">${esc(promptRunTitle(item))}</button></td>
            <td>${esc(promptKeyText(item.prompt_key))}</td>
            <td>${esc(modelDisplayText(item.model_name || "unknown"))}</td>
            <td><span class="status ${esc(item.status)}">${esc(statusText(item.status))}</span><br><span class="label">结构化校验 ${esc(passText(item.schema_valid))}</span></td>
            <td>${esc(number(item.latency_ms))} ms<br><span class="label">$${esc(fmt(item.cost_usd))}</span></td>
          </tr>`).join("")
        : `<tr><td colspan="5"><div class="empty">暂无智能体运行记录</div></td></tr>`;
      document.querySelectorAll("[data-llm-run]").forEach((btn) => btn.addEventListener("click", () => loadLlmRunDetail(btn.dataset.llmRun)));
    }

    function promptKeyText(value) {
      return promptModuleText(value);
    }

    function promptRunTitle(item) {
      const module = promptKeyText(item.prompt_key);
      const status = statusText(item.status);
      return `${module} · ${status}`;
    }

    async function loadPromptDetail(promptKey) {
      try {
        const item = await getJson(`/api/promptops/templates/${encodeURIComponent(promptKey)}`);
        const active = (item.versions || []).find((version) => version.id === item.active_version_id) || (item.versions || [])[0];
        $("promptDetail").innerHTML = `<h2>提示词详情</h2>
          <div class="kv"><span class="label">名称</span><span>${esc(item.name || promptKeyText(item.prompt_key))}</span></div>
          <div class="kv"><span class="label">模块</span><span>${esc(promptModuleText(item.module))}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${item.is_active ? "completed" : "archived"}">${esc(item.is_active ? "启用中" : "已停用")}</span></span></div>
          <div class="kv"><span class="label">活动版本</span><span>${esc(item.active_version ? "v" + item.active_version : "-")}</span></div>
          <div class="detail-section"><h3>内容</h3><div class="text-block">${esc(active?.content || "-")}</div></div>
          <details class="detail-section"><summary>结构化输出要求</summary><div class="text-block">${esc(JSON.stringify(item.schema || {}, null, 2))}</div></details>
          <div class="detail-section"><h3>版本</h3>${
            (item.versions || []).length ? item.versions.map((version) => `<div class="event"><strong>v${esc(version.version)}</strong> ${version.is_active ? `<span class="status completed">活动</span>` : `<button class="btn" data-prompt-activate-version="${esc(version.id)}" data-prompt-key="${esc(item.prompt_key)}">设为活动</button>`}<br>${esc(version.changelog || "-")}</div>`).join("") : `<div class="empty">暂无版本</div>`
          }</div>
          ${renderPromptTestPanel(item)}
          ${systemInfoBlock("系统信息", [["提示词标识", item.prompt_key]])}
          <div class="links"><button class="btn primary" data-prompt-test="${esc(item.prompt_key)}">测试运行</button><button class="btn" data-prompt-active="${esc(item.prompt_key)}" data-active="${item.is_active ? "false" : "true"}">${item.is_active ? "停用模板" : "启用模板"}</button></div>`;
        bindPromptTestButtons($("promptDetail"));
        bindPromptManagementButtons($("promptDetail"));
      } catch (error) {
        showLoadError("promptDetail");
      }
    }

    function renderPromptTestPanel(item) {
      const promptKey = String(item?.prompt_key || "");
      const defaultClaim = promptKey.includes("verifier") ? "公司收入增长是否被证据支持？" : "请基于证据提取关键事实。";
      const defaultEvidence = promptKey.includes("verifier") ? "公司披露收入同比增长，来源为官方公告。" : "公司公告显示收入、利润和现金流数据。";
      return `<div class="detail-section">
        <h3>测试输入</h3>
        <div class="form-grid">
          <div class="field"><label for="promptTestTaskId">任务追踪号</label><input id="promptTestTaskId" placeholder="可选，如 task-xxx" /></div>
          <div class="field"><label for="promptTestSymbol">公司代码</label><input id="promptTestSymbol" placeholder="NVDA" value="NVDA" /></div>
          <div class="field"><label for="promptTestPeriod">分析期间</label><input id="promptTestPeriod" placeholder="FY2024" value="FY2024" /></div>
          <div class="field"><label for="promptTestRole">运行角色</label><input id="promptTestRole" placeholder="主张校验 / 事实抽取" value="${esc(promptModuleText(item?.module || item?.prompt_key))}" /></div>
          <div class="field full"><label for="promptTestClaim">测试主张</label><textarea id="promptTestClaim" rows="3">${esc(defaultClaim)}</textarea></div>
          <div class="field full"><label for="promptTestEvidence">证据文本</label><textarea id="promptTestEvidence" rows="3">${esc(defaultEvidence)}</textarea></div>
        </div>
      </div>`;
    }

    function bindPromptTestButtons(root = document) {
      root.querySelectorAll("[data-prompt-test]").forEach((btn) => {
        if (btn.dataset.boundPromptTest === "true") return;
        btn.dataset.boundPromptTest = "true";
        btn.addEventListener("click", () => testPrompt(btn.dataset.promptTest));
      });
    }

    function bindPromptManagementButtons(root = document) {
      root.querySelectorAll("[data-prompt-activate-version]").forEach((btn) => {
        if (btn.dataset.boundPromptActivateVersion === "true") return;
        btn.dataset.boundPromptActivateVersion = "true";
        btn.addEventListener("click", () => activatePromptVersion(btn.dataset.promptKey, btn.dataset.promptActivateVersion));
      });
      root.querySelectorAll("[data-prompt-active]").forEach((btn) => {
        if (btn.dataset.boundPromptActive === "true") return;
        btn.dataset.boundPromptActive = "true";
        btn.addEventListener("click", () => setPromptTemplateActive(btn.dataset.promptActive, btn.dataset.active === "true"));
      });
    }

    async function createPromptTemplate() {
      let schema = {};
      const rawSchema = $("promptSchema").value.trim();
      if (rawSchema) {
        try { schema = JSON.parse(rawSchema); }
        catch (error) {
          $("promptMessage").innerHTML = `<div class="error">结构化输出要求必须是合法 JSON。</div>`;
          return;
        }
      }
      const payload = {
        prompt_key: $("promptKey").value.trim(),
        name: $("promptName").value.trim(),
        module: promptModuleValue($("promptCreateModule").value),
        content: $("promptContent").value,
        schema,
      };
      if (!payload.prompt_key || !payload.content) {
        $("promptMessage").innerHTML = `<div class="error">请输入模板标识和提示词内容。</div>`;
        return;
      }
      try {
        const item = await postJson("/api/promptops/templates", payload);
        $("promptMessage").innerHTML = `<div class="empty">提示词已创建，可立即测试运行。</div>`;
        await loadPromptOps();
        loadPromptDetail(item.prompt_key);
      } catch (error) {
        $("promptMessage").innerHTML = `<div class="error">创建失败，模板标识可能已存在。</div>`;
      }
    }

    async function activatePromptVersion(promptKey, versionId) {
      try {
        await postJson(`/api/promptops/templates/${encodeURIComponent(promptKey)}/versions/${encodeURIComponent(versionId)}/activate`, {});
        await loadPromptOps();
        await loadPromptDetail(promptKey);
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="empty">活动版本已切换。</div>`);
      } catch (error) {
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="error">活动版本切换失败，请刷新后重试。</div>`);
      }
    }

    async function setPromptTemplateActive(promptKey, active) {
      try {
        await postJson(`/api/promptops/templates/${encodeURIComponent(promptKey)}/active`, { active });
        await loadPromptOps();
        await loadPromptDetail(promptKey);
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="empty">${active ? "模板已启用。" : "模板已停用。"}</div>`);
      } catch (error) {
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="error">模板状态更新失败，请刷新后重试。</div>`);
      }
    }

    async function testPrompt(promptKey) {
      try {
        const symbol = $("promptTestSymbol")?.value.trim() || "NVDA";
        const period = $("promptTestPeriod")?.value.trim() || "FY2024";
        const claim = $("promptTestClaim")?.value.trim() || "收入增长是否被证据支持？";
        const evidenceText = $("promptTestEvidence")?.value.trim() || "revenue increased";
        const roleText = $("promptTestRole")?.value.trim() || "verifier";
        const taskId = $("promptTestTaskId")?.value.trim() || `promptops-${String(promptKey || "test").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
        const result = await postJson(`/api/promptops/templates/${encodeURIComponent(promptKey)}/test-run`, {
          input: promptTestInput({ symbol, period, claim, evidenceText }),
          model_role: promptModuleValue(roleText) || "verifier",
          task_id: taskId,
        });
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="empty">测试完成，已记录一条智能体运行。</div>`);
        await loadPromptOps();
      } catch (error) {
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="error">测试运行失败，请检查结构化输出要求和提示词内容。</div>`);
      }
    }

    function promptTestInput({ symbol, period, claim, evidenceText }) {
      return {
        expected_symbol: symbol,
        claim,
        text: evidenceText,
        claims: [{
          claim_id: "manual_test_claim",
          section_name: "promptops_test",
          claim_text: `${claim} [manual_test_evidence]`,
          evidence_ids: ["manual_test_evidence"],
          confidence: 0.8,
        }],
        markdown: `# PromptOps 测试\\n\\n${claim} [manual_test_evidence]`,
        evidence_records: [{
          evidence_id: "manual_test_evidence",
          source_type: "manual_text",
          content: evidenceText,
          metadata: { symbol, period },
        }],
      };
    }

    async function loadLlmRunDetail(runId) {
      try {
        const item = await getJson(`/api/llm-runs/${encodeURIComponent(runId)}`);
        $("promptDetail").innerHTML = `<h2>智能体运行详情</h2>
          <div class="kv"><span class="label">模块</span><span>${esc(promptKeyText(item.prompt_key))}</span></div>
          <div class="kv"><span class="label">模型</span><span>${esc(modelDisplayText(item.model_name || "unknown"))}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(item.status)}">${esc(statusText(item.status))}</span></span></div>
          <div class="kv"><span class="label">耗时</span><span>${esc(number(item.latency_ms))} ms</span></div>
          <div class="kv"><span class="label">结构化校验</span><span>${esc(passText(item.schema_valid))}</span></div>
          <div class="kv"><span class="label">重试与降级</span><span>${esc(number(item.attempt_count))} 次尝试 · ${esc(item.fallback_used ? "已启用降级模型" : "未降级")}</span></div>
          <div class="kv"><span class="label">Token / 成本</span><span>${esc(number(item.total_tokens))} tokens · ${costText(item.cost_usd, item.run_count)}</span></div>
          <details class="detail-section" open><summary>运行输入</summary><div class="text-block">${esc(JSON.stringify(item.input || {}, null, 2))}</div></details>
          <details class="detail-section" open><summary>运行输出</summary><div class="text-block">${esc(JSON.stringify(item.output || {}, null, 2))}</div></details>
          <details class="detail-section"><summary>运行诊断</summary><div class="text-block">${esc(JSON.stringify(item.metadata || {}, null, 2))}</div></details>
          ${systemInfoBlock("系统信息", [["运行编号", item.run_id], ["提示词标识", item.prompt_key], ["任务编号", item.task_id]])}
          ${item.error_message ? `<div class="detail-section"><h3>错误</h3><div class="text-block">${esc(item.error_message)}</div></div>` : ""}`;
      } catch (error) {
        showLoadError("promptDetail");
      }
    }

    async function loadEvidenceDetail(evidenceId) {
      try {
        const item = await getJson(`/api/evidence/${encodeURIComponent(evidenceId)}`);
        const claims = item.claims || [];
        const searchInfo = evidenceSearchContext.get(item.evidence_id);
        $("evidenceDetail").innerHTML = `<h2>证据详情</h2>
          <div class="kv"><span class="label">来源</span><span>${esc(sourceText(item.source_type))}</span></div>
          <div class="kv"><span class="label">可信度</span><span><span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span></span></div>
          <div class="kv"><span class="label">页码</span><span>${esc(fmt(item.page_no))}</span></div>
          <div class="kv"><span class="label">文档</span><span>${esc(item.document?.title || "-")}</span></div>
          ${item.source_url ? `<div class="kv"><span class="label">链接</span><a href="${esc(item.source_url)}" target="_blank">${esc(item.source_url)}</a></div>` : ""}
          ${renderEvidenceSearchDetail(searchInfo)}
          <div class="detail-section"><h3>来源原文</h3><div class="text-block">${esc(item.content || item.snippet || "")}</div></div>
          <div class="detail-section"><h3>关联主张</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>${esc(claim.section_name || claim.claim_type || "主张")}</strong> <span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span><br>${esc(claim.claim_text)}</div>`).join("") : `<div class="empty">暂无关联主张</div>`
          }</div>
          <div class="detail-section"><h3>结构化记忆</h3>
            <div class="empty">将公司、文档、财务指标和风险事件沉淀到实体库，并生成可追溯关系。</div>
            <div class="links" style="margin-top:10px">
              <button class="btn primary" data-extract-evidence-entities="${esc(item.evidence_id)}">沉淀到实体库</button>
              <button class="btn" data-jump="entities">查看实体库</button>
              <button class="btn" data-jump="graph">查看关系图谱</button>
            </div>
            <div id="entityExtractResult"></div>
          </div>
          ${systemInfoBlock("系统信息", [["证据编号", item.evidence_id]])}`;
        bindEntityExtractionButtons($("evidenceDetail"));
        bindJumpHandlers($("evidenceDetail"));
      } catch (error) {
        showLoadError("evidenceDetail");
      }
    }

    function bindEntityExtractionButtons(root = document) {
      root.querySelectorAll("[data-extract-evidence-entities]").forEach((btn) => {
        if (btn.dataset.boundExtractEntities === "true") return;
        btn.dataset.boundExtractEntities = "true";
        btn.addEventListener("click", () => extractEntitiesFromEvidence(btn.dataset.extractEvidenceEntities));
      });
    }

    async function extractEntitiesFromEvidence(evidenceId) {
      const resultBox = $("entityExtractResult");
      if (resultBox) resultBox.innerHTML = `<div class="empty">正在沉淀实体和关系...</div>`;
      try {
        const result = await postJson("/api/entities/extract-from-evidence", { evidence_id: evidenceId });
        if (resultBox) {
          resultBox.innerHTML = `<div class="empty">已沉淀 ${esc(number(result.entity_count))} 个实体、${esc(number(result.relation_count))} 条关系。</div>
            <div class="links"><button class="btn primary" data-jump="entities">查看实体库</button><button class="btn" data-jump="graph">查看关系图谱</button></div>`;
          bindJumpHandlers(resultBox);
        }
        if (activeState.view === "entities") await loadEntities();
        if (activeState.view === "graph") await loadRelations();
      } catch (error) {
        if (resultBox) resultBox.innerHTML = `<div class="error">沉淀失败，请确认该证据已绑定公司或文档。</div>`;
      }
    }

    async function loadEntities() {
      const params = new URLSearchParams();
      const q = $("entityQuery").value.trim();
      const type = $("entityType").value;
      if (q) params.set("q", q);
      if (type) params.set("entity_type", type);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/entities" + suffix);
        const rows = payload.items || [];
        entityContext = new Map(rows.map((item) => [String(item.id), item]));
        $("entityRows").innerHTML = rows.length
          ? rows.map((entity) => `<tr data-selectable="true">
              <td><button class="btn" data-entity-detail="${esc(entity.id)}">${esc(entityTitle(entity))}</button><br><span class="label">${esc(entityDescriptionText(entity))}</span></td>
              <td><span class="status ${esc(entity.entity_type)}">${esc(entityTypeText(entity.entity_type))}</span></td>
              <td>${esc(entityMarketSymbolText(entity))}</td>
              <td>${evidenceSourceButton(entity.source_evidence_id)}</td>
              <td>${esc(Math.round(Number(entity.confidence || 0) * 1000) / 10)}%</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty"><div>暂无实体记忆</div><div class="empty-actions"><button class="btn primary" data-jump="evidence">从证据库沉淀</button><button class="btn" data-jump="manual">导入资料</button></div></div></td></tr>`;
        bindEntityButtons($("entityRows"));
        bindJumpHandlers($("entityRows"));
      } catch (error) {
        showLoadError("entityRows", 5);
      }
    }

    function bindEntityButtons(root = document) {
      root.querySelectorAll("[data-entity-detail]").forEach((btn) => {
        if (btn.dataset.boundEntityDetail === "true") return;
        btn.dataset.boundEntityDetail = "true";
        btn.addEventListener("click", () => loadEntityDetail(btn.dataset.entityDetail));
      });
      root.querySelectorAll("[data-entity-evidence]").forEach((btn) => {
        if (btn.dataset.boundEntityEvidence === "true") return;
        btn.dataset.boundEntityEvidence = "true";
        btn.addEventListener("click", () => {
          activateView("evidence");
          loadEvidenceDetail(btn.dataset.entityEvidence);
        });
      });
      root.querySelectorAll("[data-entity-relations]").forEach((btn) => {
        if (btn.dataset.boundEntityRelations === "true") return;
        btn.dataset.boundEntityRelations = "true";
        btn.addEventListener("click", () => {
          $("relationQuery").value = btn.dataset.entityName || "";
          activateView("graph");
          loadRelations();
        });
      });
    }

    async function loadEntityDetail(entityId) {
      try {
        const entity = await getJson(`/api/entities/${encodeURIComponent(entityId)}`);
        const relations = await getJson(`/api/entity-relations?entity_id=${encodeURIComponent(entity.id)}&limit=20`);
        const relationRows = relations.items || [];
        $("entityDetail").innerHTML = `<h2>实体详情</h2>
          <div class="kv"><span class="label">实体</span><span>${esc(entityTitle(entity))}</span></div>
          <div class="kv"><span class="label">类型</span><span><span class="status ${esc(entity.entity_type)}">${esc(entityTypeText(entity.entity_type))}</span></span></div>
          <div class="kv"><span class="label">市场代码</span><span>${esc(entityMarketSymbolText(entity))}</span></div>
          <div class="kv"><span class="label">置信度</span><span>${esc(Math.round(Number(entity.confidence || 0) * 1000) / 10)}%</span></div>
          <div class="detail-section"><h3>说明</h3><div class="text-block">${esc(entityDescriptionText(entity))}</div></div>
          <div class="detail-section"><h3>来源</h3>${evidenceSourceButton(entity.source_evidence_id)}</div>
          <div class="detail-section"><h3>相关关系</h3>${
            relationRows.length ? relationRows.map((relation) => `<div class="event"><strong>${esc(relationTitle(relation))}</strong><br><span class="label">${esc(relation.source_evidence_id ? "证据支持" : "手工维护")} · ${esc(Math.round(Number(relation.confidence || 0) * 1000) / 10)}%</span></div>`).join("") : `<div class="empty">暂无关系记录</div>`
          }</div>
          <div class="links"><button class="btn primary" data-entity-relations="${esc(entity.id)}" data-entity-name="${esc(entity.canonical_name)}">查看关系图谱</button></div>
          ${systemInfoBlock("系统信息", [["实体编号", entity.id], ["实体键", entity.entity_key], ["来源证据", entity.source_evidence_id]])}`;
        bindEntityButtons($("entityDetail"));
      } catch (error) {
        showLoadError("entityDetail");
      }
    }

    async function loadRelations() {
      const params = new URLSearchParams();
      const q = $("relationQuery").value.trim();
      const type = $("relationType").value;
      if (q) params.set("q", q);
      if (type) params.set("relation_type", type);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const [payload, summary] = await Promise.all([
          getJson("/api/entity-relations" + suffix),
          getJson("/api/graph/summary?limit=120"),
        ]);
        renderGraphStats(summary);
        const rows = payload.items || [];
        relationContext = new Map(rows.map((item) => [String(item.id), item]));
        $("relationRows").innerHTML = rows.length
          ? rows.map((relation) => `<tr data-selectable="true">
              <td><button class="btn" data-relation-detail="${esc(relation.id)}">${esc(relationTitle(relation))}</button><br><span class="label">${esc(relationTypeText(relation.relation_type))}</span></td>
              <td>${relation.source_evidence_id ? `<span class="status completed">证据支持</span>` : `<span class="status pending">手工维护</span>`}</td>
              <td>${esc(Math.round(Number(relation.confidence || 0) * 1000) / 10)}%</td>
            </tr>`).join("")
          : `<tr><td colspan="3"><div class="empty"><div>暂无实体关系</div><div class="empty-actions"><button class="btn primary" data-jump="evidence">从证据库沉淀</button><button class="btn" data-jump="entities">查看实体库</button></div></div></td></tr>`;
        bindRelationButtons($("relationRows"));
        bindJumpHandlers($("relationRows"));
      } catch (error) {
        showLoadError("relationRows", 3);
        showLoadError("graphStats");
      }
    }

    function renderGraphStats(summary) {
      const nodes = summary.nodes || [];
      const edges = summary.edges || [];
      const typeCounts = nodes.reduce((acc, node) => {
        const label = entityTypeText(node.entity_type);
        acc[label] = (acc[label] || 0) + 1;
        return acc;
      }, {});
      const relationCounts = edges.reduce((acc, edge) => {
        const label = relationTypeText(edge.relation_type);
        acc[label] = (acc[label] || 0) + 1;
        return acc;
      }, {});
      const typeRows = Object.entries(typeCounts).slice(0, 4);
      const relationRows = Object.entries(relationCounts).slice(0, 4);
      $("graphStats").innerHTML = `<div class="dist-row"><span>实体总数</span><strong>${esc(number(summary.node_count || 0))}</strong></div>
        <div class="dist-row"><span>关系总数</span><strong>${esc(number(summary.edge_count || 0))}</strong></div>
        ${typeRows.map(([label, value]) => `<div class="dist-row"><span>${esc(label)}</span><strong>${esc(number(value))}</strong></div>`).join("")}
        ${relationRows.map(([label, value]) => `<div class="dist-row"><span>${esc(label)}</span><strong>${esc(number(value))}</strong></div>`).join("")}`;
    }

    function bindRelationButtons(root = document) {
      root.querySelectorAll("[data-relation-detail]").forEach((btn) => {
        if (btn.dataset.boundRelationDetail === "true") return;
        btn.dataset.boundRelationDetail = "true";
        btn.addEventListener("click", () => loadRelationDetail(btn.dataset.relationDetail));
      });
      root.querySelectorAll("[data-relation-entity]").forEach((btn) => {
        if (btn.dataset.boundRelationEntity === "true") return;
        btn.dataset.boundRelationEntity = "true";
        btn.addEventListener("click", () => {
          activateView("entities");
          loadEntityDetail(btn.dataset.relationEntity);
        });
      });
      root.querySelectorAll("[data-relation-evidence]").forEach((btn) => {
        if (btn.dataset.boundRelationEvidence === "true") return;
        btn.dataset.boundRelationEvidence = "true";
        btn.addEventListener("click", () => {
          activateView("evidence");
          loadEvidenceDetail(btn.dataset.relationEvidence);
        });
      });
    }

    function loadRelationDetail(relationId) {
      const relation = relationContext.get(String(relationId));
      if (!relation) {
        $("relationDetail").innerHTML = `<div class="error">关系详情已过期，请刷新关系图谱。</div>`;
        return;
      }
      $("relationDetail").innerHTML = `<h2>关系详情</h2>
        <div class="kv"><span class="label">关系</span><span>${esc(relationTypeText(relation.relation_type))}</span></div>
        <div class="kv"><span class="label">来源实体</span><span>${esc(entityTitle(relation.source))}</span></div>
        <div class="kv"><span class="label">目标实体</span><span>${esc(entityTitle(relation.target))}</span></div>
        <div class="kv"><span class="label">置信度</span><span>${esc(Math.round(Number(relation.confidence || 0) * 1000) / 10)}%</span></div>
        <div class="detail-section"><h3>业务含义</h3><div class="text-block">${esc(relationTitle(relation))}</div></div>
        <div class="detail-section"><h3>来源</h3>${relation.source_evidence_id ? `<button class="btn" data-relation-evidence="${esc(relation.source_evidence_id)}">查看证据来源</button>` : `<div class="empty">暂无证据来源</div>`}</div>
        <div class="links">
          <button class="btn" data-relation-entity="${esc(relation.source_entity_id)}">查看来源实体</button>
          <button class="btn" data-relation-entity="${esc(relation.target_entity_id)}">查看目标实体</button>
        </div>
        ${systemInfoBlock("系统信息", [["关系编号", relation.id], ["关系键", relation.relation_key], ["来源证据", relation.source_evidence_id]])}`;
      bindRelationButtons($("relationDetail"));
    }

    async function loadFinancialFacts() {
      const params = new URLSearchParams();
      const company = $("factCompany").value.trim();
      const metric = $("factMetric").value.trim();
      const period = $("factPeriodFilter").value.trim();
      if (company) params.set("company", company);
      if (metric) params.set("metric", metric);
      if (period) params.set("period", period);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/financial-facts" + suffix);
        const rows = payload.items || [];
        $("factRows").innerHTML = rows.length
          ? rows.map((fact) => `<tr data-selectable="true">
              <td>${esc(fact.company?.name || "-")}<br><span class="label mono">${esc(fact.company?.symbol || "")}</span></td>
              <td><button class="btn" data-fact-detail="${esc(fact.id)}">${esc(fact.metric_name)}</button><br><span class="label">${esc(metricTypeText(fact.metric_type))}</span></td>
              <td>${esc(number(fact.value))}<br><span class="label">${esc([fact.currency, fact.unit, fact.scale].filter(Boolean).join(" / ") || "-")}</span></td>
              <td>${esc(fact.period)}</td>
              <td>${fact.evidence ? esc(evidenceDisplayTitle(fact.evidence)) : (fact.source_url ? `<a href="${esc(fact.source_url)}" target="_blank">打开来源</a>` : "-")}</td>
              <td><span class="status ${esc(fact.review_status)}">${esc(statusText(fact.review_status))}</span></td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">暂无财务事实</div></td></tr>`;
        document.querySelectorAll("[data-fact-detail]").forEach((btn) => btn.addEventListener("click", () => loadFinancialFactDetail(btn.dataset.factDetail)));
      } catch (error) {
        showLoadError("factRows", 6);
      }
    }

    async function loadFinancialFactDetail(factId) {
      try {
        const fact = await getJson(`/api/financial-facts/${encodeURIComponent(factId)}`);
        $("factDetail").innerHTML = `<h2>财务事实详情</h2>
          <div class="kv"><span class="label">公司</span><span>${esc(fact.company?.name || "-")} / ${esc(fact.company?.symbol || "-")}</span></div>
          <div class="kv"><span class="label">指标</span><span>${esc(fact.metric_name)}</span></div>
          <div class="kv"><span class="label">数值</span><span>${esc(number(fact.value))} ${esc([fact.currency, fact.unit, fact.scale].filter(Boolean).join(" / "))}</span></div>
          <div class="kv"><span class="label">期间</span><span>${esc(fact.period)}</span></div>
          <div class="kv"><span class="label">置信度</span><span>${esc(fmt(fact.confidence))}</span></div>
          <div class="kv"><span class="label">审核</span><span><span class="status ${esc(fact.review_status)}">${esc(statusText(fact.review_status))}</span></span></div>
          <div class="detail-section"><h3>证据来源</h3>${
            fact.evidence ? `<div class="event"><strong>${esc(evidenceDisplayTitle(fact.evidence))}</strong><br>${fact.evidence.source_url ? `<a href="${esc(fact.evidence.source_url)}" target="_blank">打开来源</a>` : `<span class="label">暂无在线链接</span>`}</div>` : `<div class="empty">${fact.source_url ? `<a href="${esc(fact.source_url)}" target="_blank">打开来源</a>` : "暂无证据绑定"}</div>`
          }</div>
          <details class="detail-section"><summary>运行诊断</summary><div class="text-block">${esc(JSON.stringify(fact.metadata || {}, null, 2))}</div></details>
          ${systemInfoBlock("系统信息", [["事实编号", fact.id], ["证据编号", fact.evidence?.evidence_id]])}`;
      } catch (error) {
        showLoadError("factDetail");
      }
    }

    async function createFinancialFact() {
      const payload = {
        symbol: $("factSymbol").value.trim(),
        company_name: $("factCompanyName").value.trim(),
        metric_name: $("factMetricName").value.trim(),
        value: $("factValue").value.trim(),
        period: $("factPeriod").value.trim(),
        currency: $("factCurrency").value.trim(),
        unit: $("factUnit").value.trim(),
        evidence_id: $("factEvidenceId").value.trim(),
        source_url: $("factSourceUrl").value.trim(),
      };
      if (!payload.metric_name || !payload.value || !payload.period) {
        $("factMessage").innerHTML = `<div class="error">请输入指标、数值和期间。</div>`;
        return;
      }
      try {
        const fact = await postJson("/api/financial-facts", payload);
        $("factMessage").innerHTML = `<div class="empty">已导入事实：${esc(fact.metric_name)}</div>`;
        await loadFinancialFacts();
        loadFinancialFactDetail(fact.id);
      } catch (error) {
        $("factMessage").innerHTML = `<div class="error">导入失败，金额类指标需要币种和单位。</div>`;
      }
    }

    function signalEvidenceText(signal) {
      if (signal?.evidence?.evidence_id) return evidenceDisplayTitle(signal.evidence);
      if (signal?.source_fact?.id) return signal.source_fact.metric_name || "财务事实";
      return "待补证据";
    }

    function signalStatusClass(signal) {
      if (signal.status === "in_context") return "completed";
      if (signal.severity === "high") return "failed";
      return signal.status || "pending";
    }

    function signalSubtitle(signal) {
      const typeText = signalTypeText(signal.signal_type);
      const categoryText = signalCategoryText(signal.category);
      if (!typeText || typeText === signal.title) return categoryText;
      return `${typeText} · ${categoryText}`;
    }

    async function loadSignals() {
      const params = new URLSearchParams();
      const company = $("signalCompany").value.trim();
      const period = $("signalPeriod").value.trim();
      const type = $("signalType").value;
      const status = $("signalStatus").value;
      renderSignalScopeNotice();
      if (activeSignalTaskScope?.taskId) params.set("task_id", activeSignalTaskScope.taskId);
      if (company) params.set("company", company);
      if (period) params.set("period", period);
      if (type) params.set("signal_type", type);
      if (status) params.set("status", status);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/investment-signals" + suffix);
        const rows = payload.items || [];
        $("signalRows").innerHTML = rows.length
          ? rows.map((signal) => `<tr data-selectable="true">
              <td><button class="btn" data-signal-detail="${esc(signal.id)}">${esc(signal.title)}</button><br><span class="label">${esc(signalSubtitle(signal))}</span></td>
              <td>${esc(signal.company?.name || "-")}<br><span class="label mono">${esc(signal.company?.symbol || "")}</span></td>
              <td>${esc(fmt(signal.period))}</td>
              <td><span class="status ${esc(signal.direction)}">${esc(signalDirectionText(signal.direction))}</span></td>
              <td><span class="status ${esc(signal.severity)}">${esc(signal.priority_label || signalSeverityText(signal.severity))}</span><br><span class="label">置信度 ${esc(fmt(signal.confidence))}</span></td>
              <td>${esc(signalEvidenceText(signal))}</td>
              <td><span class="status ${esc(signalStatusClass(signal))}">${esc(statusText(signal.status))}</span></td>
            </tr>`).join("")
          : `<tr><td colspan="7"><div class="empty"><div>暂无投资线索</div><div class="empty-actions"><button class="btn primary" id="generateSignalsInline">生成规则线索</button><button class="btn" data-jump="facts">导入财务事实</button></div></div></td></tr>`;
        bindSignalButtons($("signalRows"));
        bindJumpHandlers($("signalRows"));
        const inline = $("generateSignalsInline");
        if (inline) inline.addEventListener("click", generateSignals);
      } catch (error) {
        showLoadError("signalRows", 7);
      }
    }

    function renderSignalScopeNotice() {
      const box = $("signalScopeNotice");
      if (!box) return;
      if (!activeSignalTaskScope?.taskId) {
        box.innerHTML = "";
        return;
      }
      box.innerHTML = `<div class="chain-summary" style="margin-bottom:10px">
        <strong>当前仅查看该研报任务的线索</strong><br>
        ${esc(activeSignalTaskScope.company || "当前任务")} · ${esc(activeSignalTaskScope.period || "-")} · ${esc(activeSignalTaskScope.taskId)}
        <div class="links" style="margin-top:8px"><button class="btn" id="clearSignalTaskScope">查看全部线索</button></div>
      </div>`;
      const clear = $("clearSignalTaskScope");
      if (clear) clear.addEventListener("click", () => {
        activeSignalTaskScope = null;
        if ($("signalCompany")) $("signalCompany").value = "";
        if ($("signalPeriod")) $("signalPeriod").value = "";
        loadSignals();
      });
    }

    function bindSignalButtons(root = document) {
      root.querySelectorAll("[data-signal-detail]").forEach((btn) => {
        if (btn.dataset.boundSignalDetail === "true") return;
        btn.dataset.boundSignalDetail = "true";
        btn.addEventListener("click", () => loadSignalDetail(btn.dataset.signalDetail));
      });
    }

    async function generateSignals() {
      const payload = {
        company: $("signalCompany").value.trim(),
        period: $("signalPeriod").value.trim(),
      };
      if (activeSignalTaskScope?.taskId) payload.task_id = activeSignalTaskScope.taskId;
      $("signalDetail").innerHTML = `<h2>生成规则线索</h2><div class="empty">正在根据财务事实、证据来源和任务上下文生成线索...</div>`;
      try {
        const result = await postJson("/api/investment-signals/generate", payload);
        $("signalDetail").innerHTML = `<h2>生成规则线索</h2><div class="empty">已生成或更新 ${esc(number(result.generated))} 条线索。规则线索仅供研究，不构成投资建议。</div>`;
        await loadSignals();
        loadDashboard();
      } catch (error) {
        $("signalDetail").innerHTML = `<div class="error">生成失败，请先导入财务事实或检查筛选条件。</div>`;
      }
    }

    async function loadSignalDetail(signalId) {
      try {
        const signal = await getJson(`/api/investment-signals/${encodeURIComponent(signalId)}`);
        renderSignalDetail(signal);
      } catch (error) {
        showLoadError("signalDetail");
      }
    }

    function renderSignalDetail(signal) {
      const evidence = signal.evidence || {};
      const fact = signal.source_fact || {};
      $("signalDetail").innerHTML = `<h2>线索详情</h2>
        <div class="kv"><span class="label">线索</span><span>${esc(signal.title)}</span></div>
        <div class="kv"><span class="label">公司</span><span>${esc(signal.company?.name || "-")} / ${esc(signal.company?.symbol || "-")}</span></div>
        <div class="kv"><span class="label">类型</span><span>${esc(signalTypeText(signal.signal_type))} · ${esc(signalCategoryText(signal.category))}</span></div>
        <div class="kv"><span class="label">期间</span><span>${esc(fmt(signal.period))}</span></div>
        <div class="kv"><span class="label">方向</span><span><span class="status ${esc(signal.direction)}">${esc(signalDirectionText(signal.direction))}</span></span></div>
        <div class="kv"><span class="label">研判优先级</span><span><span class="status ${esc(signal.severity)}">${esc(signal.priority_label || signalSeverityText(signal.severity))}</span> · 置信度 ${esc(fmt(signal.confidence))}</span></div>
        <div class="kv"><span class="label">状态</span><span><span class="status ${esc(signalStatusClass(signal))}">${esc(statusText(signal.status))}</span></span></div>
        <div class="detail-section"><h3>线索研判摘要</h3><div class="text-block">${esc(signal.research_brief || signal.summary)}</div><div class="score-note">仅供研究，不构成投资建议；进入正式研报仍需要证据和主张复核。</div></div>
        <div class="detail-section"><h3>建议动作</h3>
          <div class="chain-summary"><strong>下一步</strong><br>${esc(signal.recommended_action || "补齐证据、复核口径后再写入研报主张。")}<br><strong>研报用途</strong><br>${esc(signal.decision_use || "用于研究流程分流和证据补齐，不构成投资建议。")}</div>
        </div>
        <div class="detail-section"><h3>来源事实</h3>${
          fact.id ? `<div class="event"><strong>${esc(fact.metric_name || "财务事实")}</strong><br>${esc(number(fact.value))} ${esc([fact.currency, fact.unit, fact.scale].filter(Boolean).join(" / "))}<br><span class="label">${esc(fmt(fact.period))} · ${esc(metricTypeText(fact.metric_type))}</span></div>` : `<div class="empty">暂无来源事实绑定</div>`
        }</div>
        <div class="detail-section"><h3>证据来源</h3>${
          evidence.evidence_id ? `<div class="event"><strong>${esc(evidenceDisplayTitle(evidence))}</strong> <span class="status ${esc(evidence.trust_level || "unknown")}">${esc(statusText(evidence.trust_level || "unknown"))}</span><br><span class="label">${esc(sourceText(evidence.source_type))} · 页 ${esc(fmt(evidence.page_no))}</span>${evidence.source_url ? `<br><a href="${esc(evidence.source_url)}" target="_blank">打开来源</a>` : ""}</div>` : `<div class="empty">暂无证据绑定，请回到证据库或手动导入补齐。</div>`
        }</div>
        <div class="detail-section"><h3>加入研报任务</h3>
          <div class="field"><label for="signalTaskInput">任务编号</label><input id="signalTaskInput" placeholder="粘贴研报任务编号" value="${esc(signal.task_id || "")}" /></div>
          <div class="links" style="margin-top:10px">
            <button class="btn primary" data-signal-add-task="${esc(signal.id)}">加入任务上下文</button>
            <button class="btn" data-jump="tasks">查看研报任务</button>
            <button class="btn" data-jump="evidence">查看证据库</button>
          </div>
          <div id="signalContextMessage"></div>
        </div>
        ${systemInfoBlock("系统信息", [["线索编号", signal.signal_id], ["规则", signalTypeText(signal.signal_type)], ["来源规则", signalTypeText(signal.source_rule)]])}`;
      bindJumpHandlers($("signalDetail"));
      $("signalDetail").querySelectorAll("[data-signal-add-task]").forEach((btn) => {
        btn.addEventListener("click", () => addSignalToTask(btn.dataset.signalAddTask));
      });
    }

    async function addSignalToTask(signalId) {
      const taskId = $("signalTaskInput").value.trim();
      if (!taskId) {
        $("signalContextMessage").innerHTML = `<div class="error">请输入研报任务编号。</div>`;
        return;
      }
      try {
        const result = await postJson(`/api/investment-signals/${encodeURIComponent(signalId)}/add-to-task`, { task_id: taskId });
        renderSignalDetail(result.signal);
        $("signalContextMessage").innerHTML = `<div class="empty">已加入 ${esc(result.task?.symbol || "研报任务")} ${esc(result.task?.period || "")} 的任务上下文。</div>`;
        await loadSignals();
        loadDashboard();
      } catch (error) {
        $("signalContextMessage").innerHTML = `<div class="error">加入失败，请确认任务编号存在。</div>`;
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
              <td><button class="btn" data-claim-detail="${esc(claim.id)}">主张 ${esc(claim.id)}</button> ${esc(claim.section_name || claim.claim_type || "主张")}<br>${esc(claim.claim_text)}</td>
              <td>${esc(claimTaskText(claim))}</td>
              <td><span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span></td>
              <td><span class="status ${esc(claim.verification_status)}">${esc(statusText(claim.verification_status))}</span><br><span class="label">数字 ${esc(statusText(claim.numeric_check_status))} / 引用 ${esc(statusText(claim.citation_check_status))}</span></td>
              <td>${esc(number(claim.evidence_count))}</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">暂无主张</div></td></tr>`;
        document.querySelectorAll("[data-claim-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadClaimDetail(btn.dataset.claimDetail));
        });
      } catch (error) {
        showLoadError("claimRows", 5);
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
              <td><button class="btn" data-document-detail="${esc(doc.id)}">${esc(doc.title)}</button><br><span class="label">${esc(docTypeText(doc.doc_type))} · ${esc(doc.report_period || "-")}</span></td>
              <td>${esc(doc.batch_name || "导入批次")}</td>
              <td><span class="status ${esc(doc.parse_status)}">${esc(statusText(doc.parse_status))}</span><br><span class="label">${esc(number(doc.failed_step_count))} 个失败</span></td>
              <td>${esc(stepText(doc.latest_step?.step_name))}<br><span class="status ${esc(doc.latest_step?.status || "")}">${esc(statusText(doc.latest_step?.status))}</span></td>
              <td>${esc(number(doc.evidence_count))}</td>
              <td>${esc(number(doc.claim_count))}</td>
            </tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">暂无文档</div></td></tr>`;
        document.querySelectorAll("[data-document-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadDocumentDetail(btn.dataset.documentDetail));
        });
      } catch (error) {
        showLoadError("documentRows", 6);
      }
    }

    async function loadDocumentDetail(documentId) {
      try {
        const doc = await getJson(`/api/documents/${encodeURIComponent(documentId)}`);
        const steps = doc.processing_steps || [];
        const evidence = doc.evidence || [];
        const claims = doc.claims || [];
        $("documentDetail").innerHTML = `<h2>处理路径</h2>
          <div class="kv"><span class="label">文档</span><span>${esc(doc.title)}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(doc.parse_status)}">${esc(statusText(doc.parse_status))}</span></span></div>
          ${doc.source_url ? `<div class="kv"><span class="label">链接</span><a href="${esc(doc.source_url)}" target="_blank">${esc(doc.source_url)}</a></div>` : ""}
          ${systemInfoBlock("系统信息", [["批次编号", doc.batch_id], ["文件路径", doc.file_path]])}
          <div class="detail-section"><h3>处理步骤</h3><div class="timeline">${
            steps.length ? steps.map((step) => `<div class="event"><strong>${esc(stepText(step.step_name))}</strong> <span class="status ${esc(step.status)}">${esc(statusText(step.status))}</span><br><span class="label">${esc(fmt(step.started_at))} - ${esc(fmt(step.finished_at))}</span>${step.error_message ? `<div class="text-block">${esc(step.error_message)}</div>` : ""}<br><span class="label">${esc(stepMetadataText(step.metadata))}</span></div>`).join("") : `<div class="empty">暂无处理步骤</div>`
          }</div></div>
          <div class="detail-section"><h3>证据</h3>${
            evidence.length ? evidence.map((item) => `<div class="event"><strong>${esc(item.title || sourceText(item.source_type) || "证据")}</strong> <span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span><br>${esc(item.snippet || "")}</div>`).join("") : documentEvidenceEmptyState(doc)
          }</div>
          <div class="detail-section"><h3>主张</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>主张 ${esc(claim.id)}</strong> <span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span><br>${esc(claim.claim_text)}</div>`).join("") : documentClaimEmptyState(doc)
          }</div>`;
        bindJumpHandlers($("documentDetail"));
        bindCreateTaskButtons($("documentDetail"));
      } catch (error) {
        showLoadError("documentDetail");
      }
    }

    function documentEvidenceEmptyState(doc) {
      return `<div class="empty">
        <div>当前文档已入库或已解析，但尚未沉淀证据。可能原因：未完成切分/证据化、内容未命中抽取规则，或需要补充来源。</div>
        <div class="score-note">文档：${esc(doc.title || "未命名文档")}</div>
        <div class="empty-actions">
          <button class="btn" data-jump="ingestion">查看采集任务</button>
          <button class="btn" data-jump="manual">手动导入</button>
          <button class="btn" data-jump="evidence">查看证据库</button>
        </div>
      </div>`;
    }

    function documentClaimEmptyState(doc) {
      return `<div class="empty">
        <div>主张通常来自研报产物导入或 Claim 生成阶段；可先生成研报任务或导入报告产物。</div>
        <div class="score-note">当前文档：${esc(doc.title || "未命名文档")}</div>
        <div class="empty-actions">
          <button class="btn primary" data-open-create-task>创建研报任务</button>
          <button class="btn" data-jump="claims">主张复核</button>
        </div>
      </div>`;
    }

    async function loadClaimDetail(claimId) {
      try {
        const claim = await getJson(`/api/claims/${encodeURIComponent(claimId)}`);
        renderClaimDetail(claim);
      } catch (error) {
        showLoadError("claimDetail");
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
              <td><button class="btn" data-export-detail="${esc(item.task_id)}">${esc(exportDisplayTitle(item))}</button><br><span class="label">${esc(item.symbol)} · ${esc(item.period)}</span></td>
              <td><span class="status ${esc(item.status)}">${esc(statusText(item.status))}</span></td>
              <td>${esc(number(item.artifact_count))}</td>
              <td><span class="status approved">${esc(number(item.approved_claim_count))} 个已通过</span><br><span class="status pending">${esc(number(item.pending_claim_count))} 个待复核</span><br><span class="status rejected">${esc(number(item.rejected_claim_count))} 个已驳回</span></td>
              <td>${item.official_export_ready ? `<span class="status completed">可导出</span>` : `<span class="status failed">已阻塞</span>`}</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">暂无导出记录</div></td></tr>`;
        document.querySelectorAll("[data-export-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadExportDetail(btn.dataset.exportDetail));
        });
      } catch (error) {
        showLoadError("exportRows", 5);
      }
    }

    async function loadExportDetail(taskId) {
      try {
        const item = await getJson(`/api/exports/${encodeURIComponent(taskId)}`);
        const artifacts = item.artifacts || [];
        const claims = item.claims || [];
        $("exportDetail").innerHTML = `<h2>产物复核</h2>
          <div class="kv"><span class="label">股票代码</span><span>${esc(item.symbol)} / ${esc(item.period)}</span></div>
          <div class="kv"><span class="label">正式导出</span><span>${item.official_export_ready ? `<span class="status completed">可导出</span>` : `<span class="status failed">已阻塞</span>`}</span></div>
          <div class="kv"><span class="label">复核</span><span>${esc(number(item.approved_claim_count))} 个已通过 · ${esc(number(item.pending_claim_count))} 个待复核 · ${esc(number(item.rejected_claim_count))} 个已驳回</span></div>
          <div class="detail-section"><h3>阻塞原因</h3>${
            (item.blocked_reasons || []).length ? `<div class="text-block">${esc((item.blocked_reasons || []).map(statusText).join("\\n"))}</div>` : `<div class="empty">无阻塞项</div>`
          }</div>
          <div class="detail-section"><h3>产物</h3>${
            artifacts.length ? artifacts.map((artifact) => `<div class="event"><strong>${esc(artifactText(artifact.artifact_type))}</strong><br>${artifact.url ? `<a href="${esc(artifact.url)}" target="_blank">打开产物</a>` : `<span class="label">已生成，暂无在线链接</span>`}${artifact.path ? systemInfoBlock("文件信息", [["文件路径", artifact.path]]) : ""}</div>`).join("") : `<div class="empty">暂无产物</div>`
          }</div>
          <div class="detail-section"><h3>主张</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>主张 ${esc(claim.id)}</strong> <span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span><br>${esc(claim.claim_text)}</div>`).join("") : `<div class="empty">暂无主张</div>`
          }</div>
          <div class="links" style="margin-top:10px"><button class="btn primary" data-export-package="${esc(item.task_id)}">预览正式导出包</button></div>
          <div id="exportPackagePreview" class="detail-section"><h3>正式导出包</h3><div class="empty">预览后可检查正式包包含的 PDF、DOCX、主张、证据、财务事实和 CSV 表。</div></div>
          ${systemInfoBlock("系统信息", [["任务编号", item.task_id]])}
          <div class="detail-section"><h3>说明</h3><div class="empty">${esc(item.formal_export_note || "正式导出包将在后续阶段接入。")}</div></div>`;
        bindExportPackageButtons($("exportDetail"));
      } catch (error) {
        showLoadError("exportDetail");
      }
    }

    function bindExportPackageButtons(root = document) {
      root.querySelectorAll("[data-export-package]").forEach((btn) => {
        if (btn.dataset.boundExportPackage === "true") return;
        btn.dataset.boundExportPackage = "true";
        btn.addEventListener("click", () => loadExportPackage(btn.dataset.exportPackage));
      });
    }

    async function loadExportPackage(taskId) {
      try {
        const pkg = await getJson(`/api/exports/${encodeURIComponent(taskId)}/package`);
        const payload = pkg.json || {};
        const readiness = payload.readiness || {};
        const csv = pkg.csv || {};
        $("exportPackagePreview").innerHTML = `<h3>正式导出包</h3>
          <div class="kv"><span class="label">导出格式</span><span>${esc((pkg.formats || []).map(exportFormatText).join("、"))}</span></div>
          <div class="kv"><span class="label">正式导出</span><span>${readiness.official_export_ready ? `<span class="status completed">可导出</span>` : `<span class="status failed">存在阻塞</span>`}</span></div>
          <div class="analysis-stats">
            <div class="analysis-stat"><span class="label">纳入主张</span><strong>${esc(number(readiness.approved_claim_count))}</strong><span class="score-note">仅已通过复核</span></div>
            <div class="analysis-stat"><span class="label">排除主张</span><strong>${esc(number(readiness.excluded_claim_count))}</strong><span class="score-note">待复核或已驳回</span></div>
            <div class="analysis-stat"><span class="label">证据</span><strong>${esc(number((payload.evidence || []).length))}</strong><span class="score-note">随主张追溯</span></div>
            <div class="analysis-stat"><span class="label">财务事实</span><strong>${esc(number((payload.financial_facts || []).length))}</strong><span class="score-note">结构化表</span></div>
          </div>
          <div class="detail-section"><h3>CSV 表</h3><div class="mini-list">
            ${Object.entries(csv).map(([key, value]) => `<div class="mini-item"><strong>${esc(exportCsvText(key))}</strong><br><span class="label">${esc(String(value || "").split("\\n").filter(Boolean).length)} 行</span></div>`).join("")}
          </div></div>
          <div class="links" style="margin-top:10px"><button class="btn primary" data-write-export-package="${esc(taskId)}"${readiness.official_export_ready ? "" : " disabled"}>${readiness.official_export_ready ? "生成下载文件" : "正式导出尚未就绪"}</button></div>
          <div id="exportPackageFiles" class="detail-section"><h3>下载文件</h3><div class="empty">生成后会提供 JSON、Markdown、HTML 和 CSV 下载链接。</div></div>
          <div class="detail-section"><h3>Markdown 预览</h3><pre class="text-block">${esc((pkg.markdown || "").slice(0, 1200))}</pre></div>`;
        bindWriteExportPackageButtons($("exportPackagePreview"));
      } catch (error) {
        showLoadError("exportPackagePreview");
      }
    }

    function bindWriteExportPackageButtons(root = document) {
      root.querySelectorAll("[data-write-export-package]").forEach((btn) => {
        if (btn.dataset.boundWriteExportPackage === "true") return;
        btn.dataset.boundWriteExportPackage = "true";
        btn.addEventListener("click", () => writeExportPackageFiles(btn.dataset.writeExportPackage));
      });
    }

    async function writeExportPackageFiles(taskId) {
      try {
        const result = await postJson(`/api/exports/${encodeURIComponent(taskId)}/package/files`, {});
        const files = result.files || [];
        $("exportPackageFiles").innerHTML = `<h3>下载文件</h3>${files.length ? `<div class="mini-list">${files.map((file) => `<div class="mini-item"><strong>${esc(exportFormatText(file.format))}</strong><br><a href="${esc(file.download_url)}" target="_blank">下载 ${esc(file.filename)}</a><br><span class="label">${esc(number(file.size_bytes))} bytes</span></div>`).join("")}</div>` : `<div class="empty">暂无可下载文件。</div>`}`;
      } catch (error) {
        showLoadError("exportPackageFiles");
      }
    }

    function renderClaimDetail(claim) {
      const evidence = claim.evidence || [];
      const records = claim.review_records || [];
      $("claimDetail").innerHTML = `<h2>主张详情</h2>
        <div class="kv"><span class="label">主张</span><span>主张 ${esc(claim.id)}</span></div>
        <div class="kv"><span class="label">研报任务</span><span>${esc(claimTaskText(claim))}</span></div>
        <div class="kv"><span class="label">复核</span><span><span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span></span></div>
        <div class="kv"><span class="label">校验</span><span><span class="status ${esc(claim.verification_status)}">${esc(statusText(claim.verification_status))}</span></span></div>
        <div class="detail-section"><h3>主张文本</h3><textarea id="claimEditText" style="width:100%;min-height:96px">${esc(claim.claim_text)}</textarea></div>
        <div class="links" style="margin-top:10px">
          <button class="btn primary" data-claim-action="approve" data-claim-id="${esc(claim.id)}">通过</button>
          <button class="btn danger" data-claim-action="reject" data-claim-id="${esc(claim.id)}">驳回</button>
          <button class="btn" data-claim-action="edit" data-claim-id="${esc(claim.id)}">保存修改</button>
          <button class="btn" data-claim-action="regenerate" data-claim-id="${esc(claim.id)}">重生成</button>
        </div>
        <div class="detail-section"><h3>证据</h3>${
          evidence.length ? evidence.map((item) => `<div class="event"><strong>${esc(item.title || sourceText(item.source_type) || "证据")}</strong> <span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span><br>${esc(item.snippet || "")}<br><span class="label">${esc(sourceText(item.source_type))} · 页 ${esc(fmt(item.page_no))}</span></div>`).join("") : `<div class="empty">暂无关联证据</div>`
        }</div>
        <div class="detail-section"><h3>审计记录</h3>${
          records.length ? records.map((record) => `<div class="event"><strong>${esc(statusText(record.decision))}</strong> <span class="label">${esc(fmt(record.created_at))}</span><br>${esc(fmt(record.comment))}<br><span class="label">${esc(fmt(record.reviewer))}</span></div>`).join("") : `<div class="empty">暂无审计记录</div>`
        }</div>
        ${systemInfoBlock("系统信息", [["主张编号", claim.id], ["任务编号", claim.task_id]])}`;
      document.querySelectorAll("[data-claim-action]").forEach((btn) => {
        btn.addEventListener("click", () => claimAction(btn.dataset.claimId, btn.dataset.claimAction));
      });
    }

    async function claimAction(claimId, action) {
      const payload = { reviewer: "工作台" };
      if (action === "edit") {
        payload.claim_text = $("claimEditText").value;
        payload.comment = "在工作台修改";
      } else {
        payload.comment = "在工作台执行" + statusText(action);
      }
      try {
        const updated = await postJson(`/api/claims/${encodeURIComponent(claimId)}/${encodeURIComponent(action)}`, payload);
        renderClaimDetail(updated);
        loadClaims();
      } catch (error) {
        $("claimDetail").insertAdjacentHTML("afterbegin", `<div class="error">操作失败，请稍后重试。</div>`);
      }
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
          <h2>数据契约</h2>
          <div class="empty">等待规划中的接口和数据库表接入。</div>
        </div>
        <div class="panel placeholder">
          <h2>追踪链路</h2>
          <div class="empty">该模块后续会回链到稳定的任务、文档、证据、主张或产物编号。</div>
        </div>
      </div>`;
    }

    $("refreshView").addEventListener("click", () => activateView(activeState.view));
    $("refreshWorkspaces").addEventListener("click", loadWorkspaces);
    $("createWorkspace").addEventListener("click", createWorkspace);
    $("refreshStockpool").addEventListener("click", loadStockpool);
    $("addStockCompany").addEventListener("click", addStockCompany);
    $("stockpoolWorkspace").addEventListener("change", loadStockpool);
    $("stockpoolQuery").addEventListener("keydown", (event) => { if (event.key === "Enter") loadStockpool(); });
    $("refreshDatasources").addEventListener("click", loadDatasources);
    $("seedDatasources").addEventListener("click", seedDatasources);
    $("datasourceQuery").addEventListener("keydown", (event) => { if (event.key === "Enter") loadDatasources(); });
    $("datasourceEnabled").addEventListener("change", loadDatasources);
    $("refreshIngestion").addEventListener("click", loadIngestionBatches);
    bindCreateIngestionButton();
    ["ingestionQuery", "ingestionSource"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadIngestionBatches(); });
    });
    $("ingestionStatus").addEventListener("change", loadIngestionBatches);
    $("manualImportType").addEventListener("change", updateManualImportFields);
    $("submitManualImport").addEventListener("click", submitManualImport);
    $("refreshTasks").addEventListener("click", loadTasks);
    $("symbolFilter").addEventListener("keydown", (event) => { if (event.key === "Enter") loadTasks(); });
    $("refreshEvidence").addEventListener("click", loadEvidence);
    ["evidenceQuery", "evidenceCompany", "evidencePeriod", "evidenceTask"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadEvidence(); });
    });
    $("evidenceSource").addEventListener("change", loadEvidence);
    $("evidenceTrust").addEventListener("change", loadEvidence);
    $("evidenceMode").addEventListener("change", loadEvidence);
    $("refreshDocuments").addEventListener("click", loadDocuments);
    ["documentQuery", "documentBatch"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadDocuments(); });
    });
    $("documentStep").addEventListener("change", loadDocuments);
    $("refreshClaims").addEventListener("click", loadClaims);
    ["claimQuery", "claimTask"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadClaims(); });
    });
    $("claimStatus").addEventListener("change", loadClaims);
    $("claimVerification").addEventListener("change", loadClaims);
    $("refreshDictionary").addEventListener("click", loadDictionary);
    $("dictionaryQuery").addEventListener("keydown", (event) => { if (event.key === "Enter") loadDictionary(); });
    $("dictionaryType").addEventListener("change", loadDictionary);
    bindCreateDictionaryButton();
    $("refreshPromptOps").addEventListener("click", loadPromptOps);
    $("promptModule").addEventListener("keydown", (event) => { if (event.key === "Enter") loadPromptOps(); });
    $("createPromptTemplate").addEventListener("click", createPromptTemplate);
    $("refreshEntities").addEventListener("click", loadEntities);
    $("entityQuery").addEventListener("keydown", (event) => { if (event.key === "Enter") loadEntities(); });
    $("entityType").addEventListener("change", loadEntities);
    $("refreshRelations").addEventListener("click", loadRelations);
    $("relationQuery").addEventListener("keydown", (event) => { if (event.key === "Enter") loadRelations(); });
    $("relationType").addEventListener("change", loadRelations);
    $("refreshFacts").addEventListener("click", loadFinancialFacts);
    ["factCompany", "factMetric", "factPeriodFilter"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadFinancialFacts(); });
    });
    $("createFinancialFact").addEventListener("click", createFinancialFact);
    $("refreshSignals").addEventListener("click", loadSignals);
    $("generateSignals").addEventListener("click", generateSignals);
    ["signalCompany", "signalPeriod"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadSignals(); });
    });
    $("signalType").addEventListener("change", loadSignals);
    $("signalStatus").addEventListener("change", loadSignals);
    $("refreshExports").addEventListener("click", loadExports);
    $("exportSymbol").addEventListener("keydown", (event) => { if (event.key === "Enter") loadExports(); });
    $("exportStatus").addEventListener("change", loadExports);

    activateView("dashboard");
    loadTasks();
    updateManualImportFields();
  </script>
</body>
</html>"""
