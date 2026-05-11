"""Professional HTML report generator with Chart.js support."""

from __future__ import annotations

from html import escape
import json
import re
from typing import Any, Dict, List


def render_professional_html_report(
    markdown: str,
    title: str,
    charts: List[Dict[str, Any]] | None = None,
    citations: List[Dict[str, Any]] | None = None,
) -> str:
    charts = charts or []
    citations = citations or []
    body = _markdown_to_html(markdown)
    chart_blocks = _render_chartjs_blocks(charts)
    citation_count = len(citations)
    chart_count = len(charts)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {{
      --ink: #172026;
      --muted: #66736d;
      --line: #d7dfda;
      --soft: #f5f7f3;
      --accent: #0f766e;
      --panel: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, "PingFang SC", "Microsoft YaHei", sans-serif; color: var(--ink); background: var(--soft); line-height: 1.68; }}
    header {{ padding: 28px 34px 20px; background: #ffffff; border-bottom: 1px solid var(--line); }}
    header h1 {{ margin: 0 0 10px; font-size: 28px; letter-spacing: 0; }}
    .meta {{ display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); font-size: 13px; }}
    .badge {{ border: 1px solid #b7d8d2; color: #115e59; background: #eef9f6; padding: 4px 8px; border-radius: 999px; font-weight: 700; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 22px; }}
    section.report-section, .chart-panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px 20px; margin: 14px 0; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    h3 {{ margin: 16px 0 8px; font-size: 16px; }}
    p {{ margin: 8px 0; }}
    ul {{ padding-left: 22px; margin: 8px 0; }}
    li {{ margin: 6px 0; }}
    a {{ color: var(--accent); }}
    code {{ background: #eef2ef; padding: 2px 5px; border-radius: 4px; }}
    .charts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }}
    .chart-panel canvas {{ width: 100%; min-height: 260px; }}
    .chart-caption {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
    .references li {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <div class="meta">
      <span class="badge">多智能体研究报告</span>
      <span>图表 {chart_count} 个</span>
      <span>参考来源 {citation_count} 条</span>
    </div>
  </header>
  <main>
    {body}
    {chart_blocks}
  </main>
  {_render_chartjs_script(charts)}
</body>
</html>"""


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    html: List[str] = []
    in_list = False
    section_open = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    def close_section() -> None:
        nonlocal section_open
        close_list()
        if section_open:
            html.append("</section>")
            section_open = False

    for raw in lines:
        line = raw.rstrip()
        if not line:
            close_list()
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            close_section()
            title = escape(line[3:].strip())
            klass = "references" if title == "参考来源" else "report-section"
            html.append(f'<section class="{klass}"><h2>{title}</h2>')
            section_open = True
            continue
        if line.startswith("### "):
            close_list()
            html.append(f"<h3>{escape(line[4:].strip())}</h3>")
            continue
        image_match = re.match(r"!\[(.*?)\]\((.*?)\)", line)
        if image_match:
            continue
        if line.startswith("- ") or line.startswith("* "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_markdown(line[2:].strip())}</li>")
            continue
        close_list()
        html.append(f"<p>{_inline_markdown(line.strip())}</p>")
    close_section()
    return "\n".join(html)


def _inline_markdown(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _render_chartjs_blocks(charts: List[Dict[str, Any]]) -> str:
    if not charts:
        return ""
    blocks = ['<section class="report-section"><h2>交互图表</h2><div class="charts-grid">']
    for chart in charts:
        chart_id = _safe_id(str(chart.get("chart_id") or "chart"))
        title = escape(str(chart.get("title") or chart_id))
        blocks.append(
            f'<div class="chart-panel"><h3>{title}</h3><canvas id="canvas_{chart_id}"></canvas>'
            f'<div class="chart-caption">{escape(str(chart.get("source_fields") or ""))}</div></div>'
        )
    blocks.append("</div></section>")
    return "\n".join(blocks)


def _render_chartjs_script(charts: List[Dict[str, Any]]) -> str:
    chart_payloads = []
    for chart in charts:
        chart_js = chart.get("chart_js") if isinstance(chart.get("chart_js"), dict) else {}
        if not chart_js:
            continue
        chart_payloads.append(
            {
                "id": f"canvas_{_safe_id(str(chart.get('chart_id') or 'chart'))}",
                "type": chart_js.get("type", "bar"),
                "labels": chart_js.get("labels", []),
                "data": chart_js.get("data", []),
                "label": chart_js.get("label", str(chart.get("title") or "数据")),
            }
        )
    payload = json.dumps(chart_payloads, ensure_ascii=False)
    return f"""<script>
  const chartPayloads = {payload};
  const palette = ['#0f766e', '#9a3412', '#2563eb', '#7c3aed', '#15803d', '#be123c', '#475569', '#ca8a04'];
  for (const item of chartPayloads) {{
    const el = document.getElementById(item.id);
    if (!el || typeof Chart === 'undefined') continue;
    new Chart(el, {{
      type: item.type,
      data: {{
        labels: item.labels,
        datasets: [{{
          label: item.label,
          data: item.data,
          backgroundColor: item.labels.map((_, i) => palette[i % palette.length]),
          borderColor: '#0f766e',
          borderWidth: 1
        }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: item.type !== 'bar' }} }} }}
    }});
  }}
</script>"""


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_") or "chart"
