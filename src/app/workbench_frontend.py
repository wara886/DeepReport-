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
    .status.completed, .status.supported, .status.approved, .status.official, .status.success, .status.verified, .status.passed { color: var(--good); background: #e9f7ef; }
    .status.failed, .status.rejected, .status.quality_failed { color: var(--bad); background: #fff0ed; }
    .status.running, .status.queued, .status.pending, .status.secondary, .status.regenerate_requested { color: var(--warn); background: #fff6e6; }
    .status.cancelled, .status.archived { color: var(--muted); background: #eef2f5; }
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
      .detail { position: static; max-height: none; }
    }
    @media (max-width: 760px) {
      .topbar { align-items: flex-start; flex-direction: column; padding: 14px 16px; }
      .content { padding: 14px 16px 22px; }
      .nav { grid-template-columns: 1fr; }
      .form-grid { grid-template-columns: 1fr; }
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
        <button data-view="workspace"><span>投研空间</span><span class="tag preview">预览</span></button>
        <button data-view="stockpool"><span>股票池管理</span><span class="tag preview">预览</span></button>
        <button data-view="datasources"><span>数据源管理</span><span class="tag preview">预览</span></button>
        <button data-view="ingestion"><span>采集任务</span><span class="tag preview">预览</span></button>
        <button data-view="manual"><span>手动导入</span><span class="tag preview">预览</span></button>
        <button data-view="documents"><span>文档处理中心</span><span class="tag preview">预览</span></button>
        <button data-view="evidence"><span>证据库</span><span class="tag available">可用</span></button>
        <button data-view="facts"><span>财务事实中心</span><span class="tag preview">预览</span></button>
        <button data-view="signals"><span>投资线索</span><span class="tag enhancing">增强中</span></button>
        <button data-view="tasks"><span>研报任务</span><span class="tag available">可用</span></button>
        <button data-view="claims"><span>主张复核</span><span class="tag available">可用</span></button>
        <button data-view="dictionary"><span>金融词典</span><span class="tag preview">预览</span></button>
        <button data-view="promptops"><span>提示词运营</span><span class="tag preview">预览</span></button>
        <button data-view="entities"><span>实体库</span><span class="tag enhancing">增强中</span></button>
        <button data-view="graph"><span>关系图谱</span><span class="tag enhancing">增强中</span></button>
        <button data-view="evaluation"><span>评测中心</span><span class="tag planned">规划中</span></button>
        <button data-view="export"><span>导出中心</span><span class="tag preview">预览</span></button>
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
          <button class="btn" id="refreshView">刷新</button>
        </div>
      </header>

      <main class="content">
        <section id="dashboard" class="view active">
          <section class="grid cards" id="metricCards"></section>
          <section class="grid dashboard-layout">
            <div class="panel">
              <div class="panel-head">
                <h2>处理漏斗</h2>
                <button class="btn" data-jump="documents">失败步骤</button>
              </div>
              <div class="tab-switch" role="tablist" aria-label="处理漏斗视图">
                <button class="active" data-funnel-tab="funnel">处理漏斗</button>
                <button data-funnel-tab="chain">处理链路</button>
              </div>
              <div class="funnel-view active" id="funnelTab">
                <div id="funnelDemoNote"></div>
                <div class="funnel-visual" id="funnelVisual"></div>
                <div id="funnelLoss"></div>
              </div>
              <div class="funnel-view" id="chainTab">
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
                  <input id="evidenceTask" placeholder="任务编号" />
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
                  <button class="btn" id="refreshEvidence">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>证据</th><th>来源</th><th>可信度</th><th>文档</th><th>主张</th></tr>
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
                  <input id="documentBatch" placeholder="批次编号" />
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
                  <input id="claimTask" placeholder="任务编号" />
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
                <div class="field"><label for="workspaceMarket">市场</label><input id="workspaceMarket" placeholder="US / HK / CN-A" /></div>
                <div class="field full"><label for="workspaceMetrics">关注指标</label><input id="workspaceMetrics" placeholder="收入, 毛利率, 自由现金流" /></div>
                <div class="field full"><label for="workspaceRisks">风险类型</label><input id="workspaceRisks" placeholder="估值风险, 现金流风险, 监管风险" /></div>
                <div class="field full"><label for="workspaceSources">默认数据源</label><input id="workspaceSources" placeholder="sec_edgar, yahoo_finance" /></div>
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
                <div class="field"><label for="stockMarket">市场</label><input id="stockMarket" placeholder="US" /></div>
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
                  <input id="ingestionSource" placeholder="数据源标识，如 sec_edgar" />
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
                <div class="field"><label for="ingestionCreateSource">数据源标识</label><input id="ingestionCreateSource" placeholder="sec_edgar" /></div>
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
                <div class="field"><label for="factEvidenceId">证据编号</label><input id="factEvidenceId" placeholder="可选，evidence_id 或数字 ID" /></div>
                <div class="field full"><label for="factSourceUrl">来源链接</label><input id="factSourceUrl" placeholder="https://..." /></div>
              </div>
              <div class="modal-actions"><button class="btn primary" id="createFinancialFact">导入事实</button></div>
              <div id="factMessage"></div>
            </aside>
          </div>
        </section>
        <section id="signals" class="view"></section>
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
                  <input id="dictionaryMarket" placeholder="US / CN / HK" />
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
                  <input id="promptModule" placeholder="模块，如 verifier / fact_extractor" />
                  <button class="btn" id="refreshPromptOps">刷新</button>
                </div>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr><th>Prompt</th><th>模块</th><th>活动版本</th><th>Schema</th><th>操作</th></tr>
                  </thead>
                  <tbody id="promptRows"></tbody>
                </table>
              </div>
              <div class="detail-section">
                <h3>最近 LLM 调用</h3>
                <div class="table-scroll">
                  <table>
                    <thead><tr><th>运行</th><th>Prompt</th><th>模型</th><th>状态</th><th>耗时/成本</th></tr></thead>
                    <tbody id="llmRunRows"></tbody>
                  </table>
                </div>
              </div>
            </section>
            <aside class="panel detail" id="promptDetail">
              <h2>创建 Prompt</h2>
              <div class="form-grid">
                <div class="field"><label for="promptKey">Prompt 标识</label><input id="promptKey" placeholder="claim_verifier" /></div>
                <div class="field"><label for="promptCreateModule">模块</label><input id="promptCreateModule" placeholder="verifier" /></div>
                <div class="field full"><label for="promptName">名称</label><input id="promptName" placeholder="主张校验 Prompt" /></div>
                <div class="field full"><label for="promptContent">内容</label><textarea id="promptContent" rows="7" placeholder="请判断主张是否有证据支持：{{claim}}"></textarea></div>
                <div class="field full"><label for="promptSchema">输出 Schema JSON</label><textarea id="promptSchema" rows="5" placeholder='{"type":"object","required":["verdict"],"properties":{"verdict":{"type":"string"}}}'></textarea></div>
              </div>
              <div class="modal-actions"><button class="btn primary" id="createPromptTemplate">创建 Prompt</button></div>
              <div id="promptMessage"></div>
            </aside>
          </div>
        </section>
        <section id="entities" class="view"></section>
        <section id="graph" class="view"></section>
        <section id="evaluation" class="view"></section>
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
              <div class="form-note" id="companyResolveNote">支持公司中文名、英文名或股票代码。当前使用内置候选解析，后续接入股票池和实体库。</div>
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
      signals: ["投资线索", "阶段2接入投资线索后启用"],
      tasks: ["研报任务", "按任务编号跟踪研报生成和产物"],
      claims: ["主张复核", "查看证据、校验状态和审计轨迹"],
      dictionary: ["金融词典", "维护公司、指标、行业、风险词和排除词别名"],
      promptops: ["提示词运营", "管理 Prompt 版本、测试运行和 LLM 调用追踪"],
      entities: ["实体库", "阶段2接入实体库后启用"],
      graph: ["关系图谱", "阶段2接入实体关系后启用"],
      evaluation: ["评测中心", "阶段3接入评测运行后启用"],
      export: ["导出中心", "查看产物复核和正式导出状态"],
    };

    const statusMap = {
      queued: "待启动", running: "运行中", completed: "已完成", failed: "失败", timeout: "超时",
      cancelled: "已取消", archived: "已归档", quality_failed: "质量未通过", skipped: "已跳过",
      pending: "待复核", approved: "已通过", rejected: "已驳回", regenerate_requested: "已请求重生成",
      supported: "已支持", verified: "已验证", passed: "通过", success: "成功", parsed: "已解析",
      official: "官方", primary: "一手", secondary: "二手", medium: "中可信", low: "低可信", high: "高可信", unknown: "未知",
      not_required: "无需凭证", required: "需配置", configured: "已配置", expired: "已过期",
      not_run: "未运行",
      company: "公司别名", product: "产品别名", metric: "财务指标", industry: "行业术语", risk: "风险词", exclude: "排除词",
      approve: "通过", reject: "驳回", edit: "保存修改", regenerate: "重生成",
      rejected_claims_present: "存在已驳回主张", pending_claim_review: "存在待复核主张",
      filings: "公告/年报", documents: "文档资料", news: "新闻资料",
    };
    const sourceMap = {
      sec_edgar: "美国证监会年报", cninfo: "巨潮资讯", hkex: "港交所公告",
      eastmoney: "东方财富", yahoo_finance: "雅虎财经", news: "新闻",
      company_profile: "公司画像", market_api: "行情接口", market_data: "行情数据",
      financials: "财务数据", filing: "公告文件", filings: "公告文件", local_pdf: "本地文档",
    };
    const stepMap = {
      ingest: "入库", parse: "解析", table_extract: "表格抽取", chunk: "切分", chunk_vectorize: "切分向量化",
      evidence: "证据化", claim_bind: "绑定主张", verify: "校验",
      orchestrator: "多智能体执行", artifact_import: "产物导入", quality_gate: "质量门禁", completed: "完成",
      queued: "待启动", retry: "重试", failed: "失败", quality_failed: "质量未通过", cancelled: "已取消", archived: "已归档", claim_review: "主张复核",
      manual_import: "手动导入",
    };
    const docTypeMap = {
      report_artifact: "研报任务产物",
      generated_report_artifacts: "研报任务产物",
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
    const stepText = (value) => textOf(stepMap, value);
    const docTypeText = (value) => textOf(docTypeMap, value);
    const artifactText = (value) => textOf(artifactMap, value);

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

    function activateFunnelTab(tab) {
      document.querySelectorAll("[data-funnel-tab]").forEach((item) => item.classList.toggle("active", item.dataset.funnelTab === tab));
      $("funnelTab").classList.toggle("active", tab === "funnel");
      $("chainTab").classList.toggle("active", tab === "chain");
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
      activateView(view);
    }

    function activateView(view) {
      activeState.view = view;
      document.querySelectorAll(".nav button").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
      document.querySelectorAll(".view").forEach((item) => item.classList.toggle("active", item.id === view));
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
      else if (view === "tasks") loadTasks();
      else if (view === "evidence") loadEvidence();
      else if (view === "documents") loadDocuments();
      else if (view === "claims") loadClaims();
      else if (view === "dictionary") loadDictionary();
      else if (view === "promptops") loadPromptOps();
      else if (view === "export") loadExports();
      else renderPlaceholder(view);
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
      $("companyQuickChoices").innerHTML = companyCandidates.slice(0, 6).map((item) => `<button class="choice" type="button" data-company-choice="${esc(item.symbol)}">${esc(item.name)} · ${esc(item.symbol)}</button>`).join("");
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
    }

    function openCreateTaskModal() {
      $("createTaskModal").classList.add("active");
      $("createTaskMessage").innerHTML = "";
      setTimeout(() => $("taskCompanyInput").focus(), 0);
    }

    function closeCreateTaskModal() {
      $("createTaskModal").classList.remove("active");
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
        : "支持公司中文名、英文名或股票代码。当前使用内置候选解析，后续接入股票池和实体库。";
    }

    async function submitCreateTask(event) {
      event.preventDefault();
      const resolved = await resolveCompanyForTask($("taskCompanyInput").value);
      if (!resolved) {
        $("createTaskMessage").innerHTML = `<div class="error">请输入公司名称或股票代码。</div>`;
        return;
      }
      const runMode = $("taskRunModeInput").value;
      const payload = {
        symbol: resolved.symbol,
        period: $("taskPeriodInput").value,
        report_type: $("taskReportTypeInput").value,
        research_topic: $("taskTopicInput").value.trim(),
        data_source_scope: $("taskDataSourceInput").value,
        company_name: resolved.name,
        workspace_id: resolved.workspace_id || undefined,
        company_id: resolved.company_id || undefined,
        run_immediately: runMode === "async",
        run_async: runMode === "async",
      };
      $("createTaskMessage").innerHTML = `<div class="empty">正在创建任务...</div>`;
      try {
        const task = await postJson("/api/report-tasks", payload);
        $("createTaskMessage").innerHTML = `<div class="empty">任务已创建：${esc(task.task_id)}</div>`;
        closeCreateTaskModal();
        activateView("tasks");
        await loadTasks();
        loadTaskDetail(task.task_id);
        loadDashboard();
      } catch (error) {
        $("createTaskMessage").innerHTML = `<div class="error">创建失败，请检查服务配置或稍后重试。</div>`;
      }
    }

    async function resolveCompanyForTask(input) {
      const raw = String(input || "").trim();
      if (!raw) return null;
      try {
        const workspaces = await getJson("/api/workspaces?active_only=true&limit=1");
        const workspace = (workspaces.items || [])[0];
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
        return resolveCompany(raw);
      }
      return resolveCompany(raw);
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
              <td><button class="btn" data-workspace-stockpool="${esc(item.id)}">${esc(item.name)}</button><br><span class="label mono">${esc(item.slug)}</span></td>
              <td>${esc(item.market || "-")}</td>
              <td>${esc(number(item.active_company_count))} / ${esc(number(item.company_count))}</td>
              <td>${renderList(item.focus_metrics)}</td>
              <td>${renderList(item.risk_types)}</td>
              <td>${renderList(item.default_data_sources)}</td>
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
        market: $("workspaceMarket").value.trim(),
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
              <td>${esc(item.market || "-")}</td>
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
        market: $("stockMarket").value.trim(),
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
      if (q) params.set("q", q);
      if (enabled) params.set("enabled", enabled);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/data-sources" + suffix);
        const rows = payload.items || [];
        $("datasourceRows").innerHTML = rows.length
          ? rows.map((item) => `<tr data-selectable="true">
              <td><button class="btn" data-datasource-detail="${esc(item.id)}">${esc(item.name)}</button><br><span class="label mono">${esc(item.source_key)}</span></td>
              <td>${esc(datasourceTypeText(item.source_type))}</td>
              <td>${renderList(item.market_scope)}</td>
              <td><span class="status ${esc(item.trust_level || "secondary")}">${esc(statusText(item.trust_level || "secondary"))}</span></td>
              <td><span class="status ${esc(item.credential_status)}">${esc(statusText(item.credential_status))}</span></td>
              <td><span class="status ${esc(item.last_status || "pending")}">${esc(statusText(item.last_status || "pending"))}</span><br><span class="label">${esc(fmt(item.last_sync_at))}</span></td>
              <td class="links">
                <button class="btn" data-datasource-toggle="${esc(item.id)}" data-enabled="${item.enabled ? "false" : "true"}">${item.enabled ? "停用" : "启用"}</button>
                <button class="btn" data-datasource-health="${esc(item.id)}">标记正常</button>
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
        btn.addEventListener("click", () => markDatasourceHealth(btn.dataset.datasourceHealth));
      });
    }

    async function loadDatasourceDetail(sourceId) {
      try {
        const item = await getJson(`/api/data-sources/${encodeURIComponent(sourceId)}`);
        $("datasourceDetail").innerHTML = `<h2>数据源详情</h2>
          <div class="kv"><span class="label">名称</span><span>${esc(item.name)}</span></div>
          <div class="kv"><span class="label">标识</span><span class="mono">${esc(item.source_key)}</span></div>
          <div class="kv"><span class="label">类型</span><span>${esc(datasourceTypeText(item.source_type))}</span></div>
          <div class="kv"><span class="label">市场</span><span>${renderList(item.market_scope)}</span></div>
          <div class="kv"><span class="label">可信度</span><span><span class="status ${esc(item.trust_level || "secondary")}">${esc(statusText(item.trust_level || "secondary"))}</span></span></div>
          <div class="kv"><span class="label">启用</span><span>${item.enabled ? "是" : "否"}</span></div>
          <div class="kv"><span class="label">凭证</span><span><span class="status ${esc(item.credential_status)}">${esc(statusText(item.credential_status))}</span></span></div>
          <div class="kv"><span class="label">最近状态</span><span><span class="status ${esc(item.last_status || "pending")}">${esc(statusText(item.last_status || "pending"))}</span></span></div>
          <div class="kv"><span class="label">最近同步</span><span>${esc(fmt(item.last_sync_at))}</span></div>
          ${item.last_error ? `<div class="detail-section"><h3>最近错误</h3><div class="text-block">${esc(item.last_error)}</div></div>` : ""}
          <div class="detail-section"><h3>配置</h3><div class="text-block">${esc(JSON.stringify(item.config || {}, null, 2))}</div></div>`;
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
      await postJson(`/api/data-sources/${encodeURIComponent(sourceId)}/enable`, { enabled });
      await loadDatasources();
      await loadDatasourceDetail(sourceId);
    }

    async function markDatasourceHealth(sourceId) {
      await postJson(`/api/data-sources/${encodeURIComponent(sourceId)}/health`, { last_status: "success" });
      await loadDatasources();
      await loadDatasourceDetail(sourceId);
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
          <div class="field"><label for="ingestionCreateSource">数据源标识</label><input id="ingestionCreateSource" placeholder="sec_edgar" /></div>
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
      if (source) params.set("source_key", source);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      try {
        const payload = await getJson("/api/ingestion-batches" + suffix);
        const rows = payload.items || [];
        $("ingestionRows").innerHTML = rows.length
          ? rows.map((batch) => `<tr data-selectable="true">
              <td><button class="btn mono" data-ingestion-detail="${esc(batch.batch_id)}">${esc(shortTaskId(batch.batch_id))}</button><br><span class="label">${esc(batch.name)}</span></td>
              <td>${esc(batch.source_name || sourceText(batch.source_key))}<br><span class="label mono">${esc(fmt(batch.source_key))}</span></td>
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
        btn.addEventListener("click", () => ingestionLifecycleAction(btn.dataset.batchId, btn.dataset.ingestionAction));
      });
      root.querySelectorAll("[data-ingestion-documents]").forEach((btn) => {
        if (btn.dataset.boundIngestionDocuments === "true") return;
        btn.dataset.boundIngestionDocuments = "true";
        btn.addEventListener("click", () => {
          $("documentBatch").value = btn.dataset.ingestionDocuments || "";
          activateView("documents");
          loadDocuments();
        });
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
        source_key: $("ingestionCreateSource").value.trim(),
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
        $("ingestionMessage").innerHTML = `<div class="empty">已创建采集批次：${esc(created.batch_id)}</div>`;
        await loadIngestionBatches();
        await loadIngestionDetail(created.batch_id);
      } catch (error) {
        $("ingestionMessage").innerHTML = `<div class="error">创建失败，请确认数据源标识存在或留空后重试。</div>`;
      }
    }

    async function ingestionLifecycleAction(batchId, action) {
      const labels = { start: "启动", complete: "标记完成", fail: "标记失败", retry: "重试", cancel: "取消" };
      if (!confirm(`确认${labels[action] || "操作"}该采集批次？`)) return;
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
      }
    }

    async function loadIngestionDetail(batchId) {
      try {
        const batch = await getJson(`/api/ingestion-batches/${encodeURIComponent(batchId)}`);
        const events = batch.events || [];
        $("ingestionDetail").innerHTML = `<h2>采集批次详情</h2>
          <div class="kv"><span class="label">批次</span><span class="mono">${esc(batch.batch_id)}</span></div>
          <div class="kv"><span class="label">名称</span><span>${esc(batch.name)}</span></div>
          <div class="kv"><span class="label">数据源</span><span>${esc(batch.source_name || sourceText(batch.source_key))} / <span class="mono">${esc(fmt(batch.source_key))}</span></span></div>
          <div class="kv"><span class="label">目标</span><span>${esc(statusText(batch.target_type))}</span></div>
          <div class="kv"><span class="label">公司期间</span><span>${esc(fmt(batch.symbol))} · ${esc(fmt(batch.period))}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(batch.status)}">${esc(statusText(batch.status))}</span></span></div>
          <div class="kv"><span class="label">结果</span><span>${esc(number(batch.success_count))} 成功 / ${esc(number(batch.failed_count))} 失败 / 共 ${esc(number(batch.item_count))} 项</span></div>
          <div class="kv"><span class="label">时间</span><span>${esc(fmt(batch.started_at))} - ${esc(fmt(batch.finished_at))}</span></div>
          <div class="detail-section"><h3>查询条件</h3><div class="text-block">${esc(batch.query || "-")}</div></div>
          <div class="detail-section"><h3>批次操作</h3>${ingestionActionButtons(batch)}<div class="links"><button class="btn" data-ingestion-documents="${esc(batch.batch_id)}">查看同批次文档</button><button class="btn" data-ingestion-create="true">新建采集批次</button></div></div>
          ${batch.error_message ? `<div class="detail-section"><h3>错误</h3><div class="text-block">${esc(batch.error_message)}</div></div>` : ""}
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
          <div class="kv"><span class="label">批次</span><span class="mono">${esc(result.batch_id || "-")}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(doc.parse_status || "pending")}">${esc(statusText(doc.parse_status || "pending"))}</span></span></div>
          <div class="kv"><span class="label">类型</span><span>${esc(doc.doc_type || "-")}</span></div>
          ${doc.source_url ? `<div class="kv"><span class="label">链接</span><a href="${esc(doc.source_url)}" target="_blank">${esc(doc.source_url)}</a></div>` : ""}
          ${doc.file_path ? `<div class="kv"><span class="label">文件</span><span class="mono">${esc(doc.file_path)}</span></div>` : ""}
          <div class="links" style="margin-top:12px">
            <button class="btn primary" id="manualViewDocument">查看处理路径</button>
            <button class="btn" id="manualViewBatch">查看导入批次</button>
          </div>
          ${result.duplicate ? `<div class="detail-section"><div class="empty">检测到相同内容，未重复创建文档。</div></div>` : ""}`;
        $("manualViewDocument").addEventListener("click", () => {
          if ($("documentBatch")) $("documentBatch").value = result.batch_id || "";
          activateView("documents");
          loadDocuments();
          if (doc.id) loadDocumentDetail(doc.id);
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
        return `<div class="funnel-demo-note">当前暂无真实处理数据，以下为流程示意。创建研报任务或导入文档后将展示真实统计。</div>`;
      }
      if (!hasConsistentFunnel) {
        return `<div class="funnel-demo-note">当前真实统计尚未形成完整累计漏斗，以下展示流程示意；请切换到“处理链路”查看真实阶段计数。</div>`;
      }
      return "";
    }

    function renderFunnel(payload) {
      const rawSteps = payload.steps || [];
      const hasRealCounts = hasRealFunnelCounts(rawSteps);
      const hasConsistentFunnel = isValidFunnelSeries(rawSteps);
      const visualSteps = hasConsistentFunnel ? rawSteps : funnelDemoSteps;
      const chainSteps = hasRealCounts ? rawSteps : funnelDemoSteps;
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
      $("funnel").innerHTML = chainSteps.map((step, index) => {
            const width = Math.max(2, Math.round((Number(step.count || 0) / chainMax) * 100));
            return `<div>
              <div class="funnel-row"><span>${esc(step.label)}</span><div class="bar"><span style="width:${width}%"></span></div><strong>${esc(number(step.count))}</strong></div>
              ${index < chainSteps.length - 1 ? `<div class="funnel-arrow">↓</div>` : ""}
            </div>`;
          }).join("");
      bindJumpHandlers($("funnelVisual"));
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
              <button class="btn" data-task-detail-jump="${esc(task.task_id)}">${esc(task.symbol || task.task_id)}</button>
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
      const displayRows = realRows.length ? realRows : (options.demoRows || []);
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
        demoNote: "暂无真实数据源统计，当前显示示意分布。",
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
        demoNote: "暂无真实主张统计，当前显示示意分布。",
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

    function renderRecentTaskTable(payload) {
      const tasks = (payload.items || []).slice(0, 6);
      $("recentTaskRows").innerHTML = tasks.length
        ? tasks.map((task) => `<tr>
            <td>${esc(task.symbol || "-")}</td>
            <td>${esc(task.period || "-")}</td>
            <td>${esc(reportTypeText(task.report_type))}</td>
            <td><span class="status ${esc(task.status)}">${esc(statusText(task.status))}</span></td>
            <td>${esc(fmt(task.quality_score))}</td>
            <td>${esc(fmt(task.finished_at || task.started_at || task.created_at))}</td>
            <td><button class="btn" data-task-detail-jump="${esc(task.task_id)}">查看</button></td>
          </tr>`).join("")
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
      buttons.push(`<a class="btn" href="/api/report-tasks/${encodeURIComponent(task.task_id)}/artifacts" target="_blank">产物清单</a>`);
      return `<div class="links">${buttons.join("")}</div>`;
    }

    function taskActionButtons(task) {
      const status = String(task.status || "");
      const id = esc(task.task_id);
      const buttons = [];
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
        btn.addEventListener("click", () => taskLifecycleAction(btn.dataset.taskId, btn.dataset.taskAction));
      });
    }

    async function taskLifecycleAction(taskId, action) {
      const labels = { start: "启动", retry: "重试", cancel: "取消", archive: "归档" };
      if (["start", "retry", "cancel", "archive"].includes(action) && !confirm(`确认${labels[action]}该研报任务？`)) return;
      const payloadByAction = {
        start: { run_immediately: true, run_async: true },
        retry: { run_immediately: true, run_async: true },
        cancel: { reason: "用户在工作台取消" },
        archive: { reason: "用户在工作台归档" },
      };
      const endpointByAction = {
        start: "start",
        retry: "retry",
        cancel: "cancel",
        archive: "archive",
      };
      try {
        const endpoint = endpointByAction[action];
        const updated = await postJson(`/api/report-tasks/${encodeURIComponent(taskId)}/${endpoint}`, payloadByAction[action]);
        await loadTasks();
        await loadTaskDetail(updated.task_id || taskId);
        loadDashboard();
        if (action === "start" || action === "retry") scheduleTaskRefresh(updated.task_id || taskId);
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
      const suffix = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
      try {
        const payload = await getJson("/api/report-tasks" + suffix);
        const rows = payload.items || [];
        $("taskRows").innerHTML = rows.length
          ? rows.map((task) => `<tr data-selectable="true" data-task-id="${esc(task.task_id)}">
              <td><button class="btn mono" title="${esc(task.task_id)}" data-task-detail="${esc(task.task_id)}">${esc(shortTaskId(task.task_id))}</button></td>
              <td>${esc(task.symbol)}<br><span class="label">${esc(task.period)}</span></td>
              <td><span class="status ${esc(task.status)}">${esc(statusText(task.status))}</span></td>
              <td class="nowrap">${esc(stepText(task.current_stage))}</td>
              <td>${esc(fmt(task.created_at))}</td>
              <td>${artifactButtons(task)}</td>
              <td>${taskActionButtons(task)}</td>
            </tr>`).join("")
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
        return `<div class="detail-section"><h3>质量诊断</h3><div class="empty">暂无质量门禁和智能体运行诊断。任务完成后会展示 Writer、Verifier 和质量门禁结果。</div></div>`;
      }
      const gateStatus = diag.delivery_pass === true ? "passed" : (diag.delivery_pass === false ? "failed" : "not_run");
      const categories = Object.entries(diag.failure_categories || {});
      const issues = diag.top_issues || [];
      const failedSections = diag.failed_sections || [];
      const fixes = diag.required_fixes || [];
      const runCards = [
        ["Writer", diag.writer],
        ["Verifier", diag.verifier],
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
              <span>LLM复核：${esc(passText(diag.llm_review_pass))}</span>
              <span>LLM运行：${esc(number(diag.llm_run_count || 0))}</span>
              <span>失败运行：${esc(number(diag.failed_llm_run_count || 0))}</span>
            </div>
          </div>
          ${categories.length ? `<div class="diagnostic-card"><strong>失败分类</strong>${categories.map(([key, value]) => `<div class="dist-row"><span>${esc(key)}</span><strong>${esc(number(value))}</strong></div>`).join("")}</div>` : ""}
          ${issues.length ? `<div class="diagnostic-card"><strong>主要问题</strong><div class="diagnostic-list">${issues.map((issue) => `<div class="diagnostic-issue ${esc(issue.severity || "")}"><span class="label">${esc(issue.severity || "warning")}${issue.category ? ` / ${esc(issue.category)}` : ""}</span><br>${esc(issue.message || "")}</div>`).join("")}</div></div>` : ""}
          ${failedSections.length ? `<div class="diagnostic-card"><strong>需修复章节</strong><div class="diagnostic-meta">${failedSections.map((item) => `<span class="status failed">${esc(item)}</span>`).join("")}</div></div>` : ""}
          ${fixes.length ? `<div class="diagnostic-card"><strong>修复建议</strong><div class="diagnostic-list">${fixes.map((item) => `<div class="diagnostic-issue">${esc(item)}</div>`).join("")}</div></div>` : ""}
          <div class="diagnostic-grid">${runCards}</div>
        </div>
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
          <span>${esc(run.model_name || "未知模型")}</span>
          <span>${esc(run.latency_ms ?? "-")} ms</span>
          <span>降级：${esc(run.fallback_used ? "是" : "否")}</span>
          <span>Schema：${esc(passText(run.schema_valid))}</span>
          ${run.metadata?.quality_feedback_used ? `<span>已使用质量反馈</span>` : ""}
        </div>
        ${run.summary ? `<div class="text-block">${esc(run.summary)}</div>` : ""}
        ${run.error_message ? `<div class="error">${esc(run.error_message)}</div>` : ""}
      </div>`;
    }

    function passText(value) {
      if (value === true) return "通过";
      if (value === false) return "未通过";
      if (value === null || value === undefined) return "未记录";
      return String(value);
    }

    async function loadTaskDetail(taskId) {
      try {
        const task = await getJson(`/api/report-tasks/${encodeURIComponent(taskId)}`);
        const events = task.events || [];
        const metadata = task.metadata || {};
        $("taskDetail").innerHTML = `<h2>任务详情</h2>
          <div class="kv"><span class="label">任务</span><span class="mono">${esc(task.task_id)}</span></div>
          <div class="kv"><span class="label">公司</span><span>${esc(metadata.company_name || task.symbol)} / ${esc(task.symbol)}</span></div>
          <div class="kv"><span class="label">查询期间</span><span>${esc(task.period)}</span></div>
          <div class="kv"><span class="label">报告类型</span><span>${esc(reportTypeText(task.report_type))}</span></div>
          <div class="kv"><span class="label">数据源范围</span><span>${esc(dataSourceScopeText(metadata.data_source_scope))}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(task.status)}">${esc(statusText(task.status))}</span></span></div>
          <div class="kv"><span class="label">阶段</span><span>${esc(stepText(task.current_stage))}</span></div>
          <div class="kv"><span class="label">质量分</span><span>${esc(fmt(task.quality_score))}</span></div>
          <div class="detail-section"><h3>研究问题</h3><div class="text-block">${esc(metadata.research_topic || "-")}</div></div>
          <div class="detail-section"><h3>任务操作</h3>${taskActionButtons(task)}</div>
          ${task.error_message ? `<div class="detail-section"><h3>错误</h3><div class="text-block">${esc(task.error_message)}</div></div>` : ""}
          ${renderQualityDiagnostics(task)}
          <div class="detail-section"><h3>产物</h3>${artifactButtons(task)}</div>
          <div class="detail-section"><h3>时间线</h3><div class="timeline">${
            events.length ? events.map((event) => `<div class="event"><strong>${esc(stepText(event.stage))}</strong> <span class="status ${esc(event.status)}">${esc(statusText(event.status))}</span><br><span class="label">${esc(fmt(event.created_at))}</span><br>${esc(fmt(event.message))}</div>`).join("") : `<div class="empty">暂无事件</div>`
          }</div></div>`;
        bindTaskActionButtons($("taskDetail"));
      } catch (error) {
        showLoadError("taskDetail");
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
              <td>${esc(sourceText(item.source_type))}<br><span class="label">${esc(fmt(item.source_url))}</span></td>
              <td><span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span></td>
              <td>${esc(item.document?.title || "-")}<br><span class="label">${esc(item.document?.report_period || "")}</span></td>
              <td>${esc(number(item.claim_count))}</td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">暂无证据</div></td></tr>`;
        document.querySelectorAll("[data-evidence-detail]").forEach((btn) => {
          btn.addEventListener("click", () => loadEvidenceDetail(btn.dataset.evidenceDetail));
        });
      } catch (error) {
        showLoadError("evidenceRows", 5);
      }
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
              <td><button class="btn" data-dictionary-detail="${esc(item.id)}">${esc(item.canonical_name)}</button><br><span class="label mono">${esc(item.normalized_key)}</span></td>
              <td><span class="status ${esc(item.term_type)}">${esc(statusText(item.term_type))}</span></td>
              <td>${esc(item.symbol || "-")}<br><span class="label">${esc(item.market || "-")}</span></td>
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
            <input id="dictionaryMarket" placeholder="US / CN / HK" />
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
        <div class="kv"><span class="label">市场</span><span>${esc(item.market || "-")}</span></div>
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
            <div class="field"><label for="dictionaryResolveMarket">市场</label><input id="dictionaryResolveMarket" value="${esc(item.market || "")}" placeholder="US / CN / HK" /></div>
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
      const market = $("dictionaryResolveMarket").value.trim();
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
        market: $("dictionaryMarket").value.trim(),
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
      const module = $("promptModule").value.trim();
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
              <td><button class="btn" data-prompt-detail="${esc(item.prompt_key)}">${esc(item.name)}</button><br><span class="label mono">${esc(item.prompt_key)}</span></td>
              <td>${esc(item.module || "-")}</td>
              <td>${esc(item.active_version ? "v" + item.active_version : "-")}</td>
              <td>${Object.keys(item.schema || {}).length ? `<span class="status completed">已配置</span>` : `<span class="status pending">未配置</span>`}</td>
              <td><button class="btn primary" data-prompt-test="${esc(item.prompt_key)}">测试运行</button></td>
            </tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">暂无 Prompt 模板</div></td></tr>`;
        document.querySelectorAll("[data-prompt-detail]").forEach((btn) => btn.addEventListener("click", () => loadPromptDetail(btn.dataset.promptDetail)));
        bindPromptTestButtons($("promptRows"));
        renderLlmRuns(runs.items || []);
      } catch (error) {
        showLoadError("promptRows", 5);
      }
    }

    function renderLlmRuns(rows) {
      $("llmRunRows").innerHTML = rows.length
        ? rows.map((item) => `<tr>
            <td><button class="btn mono" data-llm-run="${esc(item.run_id)}">${esc(shortTaskId(item.run_id))}</button></td>
            <td>${esc(item.prompt_key)}</td>
            <td>${esc(item.model_name || "-")}</td>
            <td><span class="status ${esc(item.status)}">${esc(statusText(item.status))}</span><br><span class="label">Schema ${item.schema_valid ? "通过" : "未通过"}</span></td>
            <td>${esc(number(item.latency_ms))} ms<br><span class="label">$${esc(fmt(item.cost_usd))}</span></td>
          </tr>`).join("")
        : `<tr><td colspan="5"><div class="empty">暂无 LLM 调用记录</div></td></tr>`;
      document.querySelectorAll("[data-llm-run]").forEach((btn) => btn.addEventListener("click", () => loadLlmRunDetail(btn.dataset.llmRun)));
    }

    async function loadPromptDetail(promptKey) {
      try {
        const item = await getJson(`/api/promptops/templates/${encodeURIComponent(promptKey)}`);
        const active = (item.versions || []).find((version) => version.id === item.active_version_id) || (item.versions || [])[0];
        $("promptDetail").innerHTML = `<h2>Prompt 详情</h2>
          <div class="kv"><span class="label">标识</span><span class="mono">${esc(item.prompt_key)}</span></div>
          <div class="kv"><span class="label">模块</span><span>${esc(item.module || "-")}</span></div>
          <div class="kv"><span class="label">活动版本</span><span>${esc(item.active_version ? "v" + item.active_version : "-")}</span></div>
          <div class="detail-section"><h3>内容</h3><div class="text-block">${esc(active?.content || "-")}</div></div>
          <div class="detail-section"><h3>Schema</h3><div class="text-block">${esc(JSON.stringify(item.schema || {}, null, 2))}</div></div>
          <div class="detail-section"><h3>版本</h3>${
            (item.versions || []).length ? item.versions.map((version) => `<div class="event"><strong>v${esc(version.version)}</strong> ${version.is_active ? `<span class="status completed">活动</span>` : ""}<br>${esc(version.changelog || "-")}</div>`).join("") : `<div class="empty">暂无版本</div>`
          }</div>
          <div class="links"><button class="btn primary" data-prompt-test="${esc(item.prompt_key)}">测试运行</button></div>`;
        bindPromptTestButtons($("promptDetail"));
      } catch (error) {
        showLoadError("promptDetail");
      }
    }

    function bindPromptTestButtons(root = document) {
      root.querySelectorAll("[data-prompt-test]").forEach((btn) => {
        if (btn.dataset.boundPromptTest === "true") return;
        btn.dataset.boundPromptTest = "true";
        btn.addEventListener("click", () => testPrompt(btn.dataset.promptTest));
      });
    }

    async function createPromptTemplate() {
      let schema = {};
      const rawSchema = $("promptSchema").value.trim();
      if (rawSchema) {
        try { schema = JSON.parse(rawSchema); }
        catch (error) {
          $("promptMessage").innerHTML = `<div class="error">Schema 必须是合法 JSON。</div>`;
          return;
        }
      }
      const payload = {
        prompt_key: $("promptKey").value.trim(),
        name: $("promptName").value.trim(),
        module: $("promptCreateModule").value.trim(),
        content: $("promptContent").value,
        schema,
      };
      if (!payload.prompt_key || !payload.content) {
        $("promptMessage").innerHTML = `<div class="error">请输入 Prompt 标识和内容。</div>`;
        return;
      }
      try {
        const item = await postJson("/api/promptops/templates", payload);
        $("promptMessage").innerHTML = `<div class="empty">已创建 Prompt：${esc(item.prompt_key)}</div>`;
        await loadPromptOps();
        loadPromptDetail(item.prompt_key);
      } catch (error) {
        $("promptMessage").innerHTML = `<div class="error">创建失败，Prompt 标识可能已存在。</div>`;
      }
    }

    async function testPrompt(promptKey) {
      try {
        const result = await postJson(`/api/promptops/templates/${encodeURIComponent(promptKey)}/test-run`, {
          input: { claim: "收入增长是否被证据支持？", text: "revenue increased" },
          model_role: "verifier",
        });
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="empty">测试完成：${esc(result.llm_run_id)}</div>`);
        await loadPromptOps();
      } catch (error) {
        $("promptDetail").insertAdjacentHTML("afterbegin", `<div class="error">测试运行失败，请检查 Schema 和 Prompt。</div>`);
      }
    }

    async function loadLlmRunDetail(runId) {
      try {
        const item = await getJson(`/api/llm-runs/${encodeURIComponent(runId)}`);
        $("promptDetail").innerHTML = `<h2>LLM 调用详情</h2>
          <div class="kv"><span class="label">运行</span><span class="mono">${esc(item.run_id)}</span></div>
          <div class="kv"><span class="label">Prompt</span><span>${esc(item.prompt_key)}</span></div>
          <div class="kv"><span class="label">模型</span><span>${esc(item.model_name || "-")}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(item.status)}">${esc(statusText(item.status))}</span></span></div>
          <div class="kv"><span class="label">耗时</span><span>${esc(number(item.latency_ms))} ms</span></div>
          <div class="detail-section"><h3>输入</h3><div class="text-block">${esc(JSON.stringify(item.input || {}, null, 2))}</div></div>
          <div class="detail-section"><h3>输出</h3><div class="text-block">${esc(JSON.stringify(item.output || {}, null, 2))}</div></div>
          <div class="detail-section"><h3>元数据</h3><div class="text-block">${esc(JSON.stringify(item.metadata || {}, null, 2))}</div></div>
          ${item.error_message ? `<div class="detail-section"><h3>错误</h3><div class="text-block">${esc(item.error_message)}</div></div>` : ""}`;
      } catch (error) {
        showLoadError("promptDetail");
      }
    }

    async function loadEvidenceDetail(evidenceId) {
      try {
        const item = await getJson(`/api/evidence/${encodeURIComponent(evidenceId)}`);
        const claims = item.claims || [];
        $("evidenceDetail").innerHTML = `<h2>证据详情</h2>
          <div class="kv"><span class="label">证据</span><span class="mono">${esc(item.evidence_id)}</span></div>
          <div class="kv"><span class="label">来源</span><span>${esc(sourceText(item.source_type))}</span></div>
          <div class="kv"><span class="label">可信度</span><span><span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span></span></div>
          <div class="kv"><span class="label">页码</span><span>${esc(fmt(item.page_no))}</span></div>
          <div class="kv"><span class="label">文档</span><span>${esc(item.document?.title || "-")}</span></div>
          ${item.source_url ? `<div class="kv"><span class="label">链接</span><a href="${esc(item.source_url)}" target="_blank">${esc(item.source_url)}</a></div>` : ""}
          <div class="detail-section"><h3>来源原文</h3><div class="text-block">${esc(item.content || item.snippet || "")}</div></div>
          <div class="detail-section"><h3>关联主张</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>${esc(claim.section_name || claim.claim_type || "主张")}</strong> <span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span><br>${esc(claim.claim_text)}<br><span class="label mono">${esc(claim.task_id)}</span></div>`).join("") : `<div class="empty">暂无关联主张</div>`
          }</div>`;
      } catch (error) {
        showLoadError("evidenceDetail");
      }
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
              <td><button class="btn" data-fact-detail="${esc(fact.id)}">${esc(fact.metric_name)}</button><br><span class="label">${esc(fact.metric_type || "-")}</span></td>
              <td>${esc(number(fact.value))}<br><span class="label">${esc([fact.currency, fact.unit, fact.scale].filter(Boolean).join(" / ") || "-")}</span></td>
              <td>${esc(fact.period)}</td>
              <td>${fact.evidence ? esc(fact.evidence.evidence_id) : esc(fact.source_url || "-")}</td>
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
            fact.evidence ? `<div class="event"><strong>${esc(fact.evidence.title || fact.evidence.evidence_id)}</strong><br>${esc(fact.evidence.source_url || "-")}</div>` : `<div class="empty">${esc(fact.source_url || "暂无证据绑定")}</div>`
          }</div>
          <div class="detail-section"><h3>元数据</h3><div class="text-block">${esc(JSON.stringify(fact.metadata || {}, null, 2))}</div></div>`;
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
              <td><button class="btn" data-claim-detail="${esc(claim.id)}">#${esc(claim.id)}</button> ${esc(claim.section_name || claim.claim_type || "主张")}<br>${esc(claim.claim_text)}</td>
              <td><span class="mono">${esc(claim.task_id)}</span></td>
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
              <td><span class="mono">${esc(fmt(doc.batch_id))}</span></td>
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
          <div class="kv"><span class="label">批次</span><span class="mono">${esc(fmt(doc.batch_id))}</span></div>
          <div class="kv"><span class="label">状态</span><span><span class="status ${esc(doc.parse_status)}">${esc(statusText(doc.parse_status))}</span></span></div>
          ${doc.source_url ? `<div class="kv"><span class="label">链接</span><a href="${esc(doc.source_url)}" target="_blank">${esc(doc.source_url)}</a></div>` : ""}
          ${doc.file_path ? `<div class="kv"><span class="label">文件</span><span class="mono">${esc(doc.file_path)}</span></div>` : ""}
          <div class="detail-section"><h3>处理步骤</h3><div class="timeline">${
            steps.length ? steps.map((step) => `<div class="event"><strong>${esc(stepText(step.step_name))}</strong> <span class="status ${esc(step.status)}">${esc(statusText(step.status))}</span><br><span class="label">${esc(fmt(step.started_at))} - ${esc(fmt(step.finished_at))}</span>${step.error_message ? `<div class="text-block">${esc(step.error_message)}</div>` : ""}<br><span class="label">${esc(stepMetadataText(step.metadata))}</span></div>`).join("") : `<div class="empty">暂无处理步骤</div>`
          }</div></div>
          <div class="detail-section"><h3>证据</h3>${
            evidence.length ? evidence.map((item) => `<div class="event"><strong>${esc(item.title || item.evidence_id)}</strong> <span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span><br>${esc(item.snippet || "")}</div>`).join("") : `<div class="empty">暂无证据</div>`
          }</div>
          <div class="detail-section"><h3>主张</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>#${esc(claim.id)}</strong> <span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span><br>${esc(claim.claim_text)}<br><span class="label mono">${esc(claim.task_id)}</span></div>`).join("") : `<div class="empty">暂无主张</div>`
          }</div>`;
      } catch (error) {
        showLoadError("documentDetail");
      }
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
              <td><button class="btn" data-export-detail="${esc(item.task_id)}">${esc(item.task_id)}</button><br><span class="label">${esc(item.symbol)} · ${esc(item.period)}</span></td>
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
          <div class="kv"><span class="label">任务</span><span class="mono">${esc(item.task_id)}</span></div>
          <div class="kv"><span class="label">股票代码</span><span>${esc(item.symbol)} / ${esc(item.period)}</span></div>
          <div class="kv"><span class="label">正式导出</span><span>${item.official_export_ready ? `<span class="status completed">可导出</span>` : `<span class="status failed">已阻塞</span>`}</span></div>
          <div class="kv"><span class="label">复核</span><span>${esc(number(item.approved_claim_count))} 个已通过 · ${esc(number(item.pending_claim_count))} 个待复核 · ${esc(number(item.rejected_claim_count))} 个已驳回</span></div>
          <div class="detail-section"><h3>阻塞原因</h3>${
            (item.blocked_reasons || []).length ? `<div class="text-block">${esc((item.blocked_reasons || []).map(statusText).join("\\n"))}</div>` : `<div class="empty">无阻塞项</div>`
          }</div>
          <div class="detail-section"><h3>产物</h3>${
            artifacts.length ? artifacts.map((artifact) => `<div class="event"><strong>${esc(artifactText(artifact.artifact_type))}</strong><br>${artifact.url ? `<a href="${esc(artifact.url)}" target="_blank">${esc(artifact.url)}</a>` : `<span class="mono">${esc(fmt(artifact.path))}</span>`}</div>`).join("") : `<div class="empty">暂无产物</div>`
          }</div>
          <div class="detail-section"><h3>主张</h3>${
            claims.length ? claims.map((claim) => `<div class="event"><strong>#${esc(claim.id)}</strong> <span class="status ${esc(claim.review_status)}">${esc(statusText(claim.review_status))}</span><br>${esc(claim.claim_text)}</div>`).join("") : `<div class="empty">暂无主张</div>`
          }</div>
          <div class="detail-section"><h3>说明</h3><div class="empty">${esc(item.formal_export_note || "正式导出包将在后续阶段接入。")}</div></div>`;
      } catch (error) {
        showLoadError("exportDetail");
      }
    }

    function renderClaimDetail(claim) {
      const evidence = claim.evidence || [];
      const records = claim.review_records || [];
      $("claimDetail").innerHTML = `<h2>主张详情</h2>
        <div class="kv"><span class="label">主张</span><span class="mono">#${esc(claim.id)}</span></div>
        <div class="kv"><span class="label">任务</span><span class="mono">${esc(claim.task_id)}</span></div>
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
          evidence.length ? evidence.map((item) => `<div class="event"><strong>${esc(item.title || item.evidence_id)}</strong> <span class="status ${esc(item.trust_level)}">${esc(statusText(item.trust_level))}</span><br>${esc(item.snippet || "")}<br><span class="label">${esc(sourceText(item.source_type))} · 页 ${esc(fmt(item.page_no))}</span></div>`).join("") : `<div class="empty">暂无关联证据</div>`
        }</div>
        <div class="detail-section"><h3>审计记录</h3>${
          records.length ? records.map((record) => `<div class="event"><strong>${esc(statusText(record.decision))}</strong> <span class="label">${esc(fmt(record.created_at))}</span><br>${esc(fmt(record.comment))}<br><span class="label">${esc(fmt(record.reviewer))}</span></div>`).join("") : `<div class="empty">暂无审计记录</div>`
        }</div>`;
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
    ["evidenceQuery", "evidenceTask"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadEvidence(); });
    });
    $("evidenceSource").addEventListener("change", loadEvidence);
    $("evidenceTrust").addEventListener("change", loadEvidence);
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
    $("refreshFacts").addEventListener("click", loadFinancialFacts);
    ["factCompany", "factMetric", "factPeriodFilter"].forEach((id) => {
      $(id).addEventListener("keydown", (event) => { if (event.key === "Enter") loadFinancialFacts(); });
    });
    $("createFinancialFact").addEventListener("click", createFinancialFact);
    $("refreshExports").addEventListener("click", loadExports);
    $("exportSymbol").addEventListener("keydown", (event) => { if (event.key === "Enter") loadExports(); });
    $("exportStatus").addEventListener("change", loadExports);

    loadDashboard();
    loadTasks();
    updateManualImportFields();
  </script>
</body>
</html>"""
