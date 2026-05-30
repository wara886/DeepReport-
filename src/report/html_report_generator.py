"""Professional HTML report generator with Bootstrap 5, Chart.js, and Font Awesome.

Inspired by the visual design of DeepReport_official_run reports.
"""

from __future__ import annotations

from html import escape
import json
import re
from typing import Any, Dict, List


# ── Banned debug phrases ─────────────────────────────────────────────
BANNED_PHRASES: List[str] = [
    "暂无充足的可验证证据",
    "PDF section:",
    "本节暂无",
    "待补",
    "框架性",
    "提示了相关风险或运营关注点",
    "web_search 提示",
    "资料缺口：",
]


def _clean_phrases(text: str) -> str:
    """Remove banned debug/generic phrases from text, leaving valid content intact."""
    text = re.sub(r"暂无充足的可验证证据[^。]*。?\s*", "", text)
    text = re.sub(r"资料缺口[：:][^。]*。?\s*", "", text)
    text = re.sub(r"提示了相关风险或运营关注点[^。]*。?\s*", "", text)
    text = re.sub(r"PDF section:\s*\S*", "", text)
    text = text.replace("web_search 提示", "").replace("本节暂无", "").replace("待补", "")
    text = re.sub(r"（框架性[^）]*）", "", text)
    return text.strip()


def _section_is_gap(lines: List[str]) -> bool:
    """Return True if most non-header lines in a section are gap/debug content."""
    content = [l for l in lines if l.strip() and not l.startswith("##") and not l.startswith("#")]
    if not content:
        return False
    gap_count = sum(1 for l in content if any(p in l for p in BANNED_PHRASES))
    return gap_count / len(content) > 0.5


def _filter_banned_phrases(markdown: str) -> str:
    """Filter banned debug/generic phrases from report markdown.

    Sections consisting primarily of gap content are moved to a
    "数据缺口与降级说明" appendix. Isolated banned phrases in
    otherwise valid sections are silently removed.
    """
    lines = markdown.splitlines()
    sections: List[List[str]] = []
    current: List[str] = []

    for line in lines:
        if line.startswith("## ") and current and current[0].startswith("## "):
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)

    main_sections: List[List[str]] = []
    gap_sections: List[List[str]] = []

    for sec in sections:
        if _section_is_gap(sec):
            gap_sections.append(sec)
        else:
            cleaned = []
            for line in sec:
                cl = _clean_phrases(line)
                if cl.strip():
                    cleaned.append(cl)
            main_sections.append(cleaned)

    result: List[str] = []
    for sec in main_sections:
        result.extend(sec)

    if gap_sections:
        result.append("")
        result.append("## 数据缺口与降级说明")
        result.append("")
        result.append("以下章节因缺乏可验证的公开数据，当前报告期内未能生成详细分析：")
        result.append("")
        for sec in gap_sections:
            for line in sec:
                if line.startswith("## "):
                    result.append(f"### {line[3:].strip()}（数据缺口）")
                elif line.strip() and any(p in line for p in BANNED_PHRASES):
                    result.append("> 数据不足以支持该章节的详细分析。")
                elif line.strip():
                    result.append(line)
        result.append("")

    return "\n".join(result)


def render_professional_html_report(
    markdown: str,
    title: str,
    charts: List[Dict[str, Any]] | None = None,
    citations: List[Dict[str, Any]] | None = None,
) -> str:
    """Render a professional standalone HTML report.

    Features:
    - Bootstrap 5 responsive layout + Font Awesome icons
    - Gradient header with confidence/score badge
    - Table of contents (auto-generated from h2 headings)
    - Tabbed Chart.js interactive chart navigation
    - Color-coded callout boxes and risk indicators
    - Professional citation blocks
    - Print CSS support
    - Compliance disclosure footer
    """
    charts = charts or []
    citations = citations or []
    markdown = _filter_banned_phrases(markdown)
    body_html = _markdown_to_html(markdown)
    chart_count = len(charts)
    citation_count = len(citations)

    # Extract headings for TOC
    toc_entries = _extract_toc(markdown)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    /* ── Base ── */
    :root {{
      --accent: #667eea;
      --accent2: #764ba2;
      --pink: #f093fb;
      --pink2: #f5576c;
      --ink: #1a1a2e;
      --muted: #6c757d;
      --soft: #f8f9fa;
      --panel: #ffffff;
      --line: #e9ecef;
    }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif; color: var(--ink); background: var(--soft); line-height: 1.7; }}
    a {{ color: #556ee6; }}
    a:hover {{ color: #764ba2; }}

    /* ── Header ── */
    .report-header {{
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: #fff;
      padding: 3rem 0 2rem;
      margin-bottom: 2rem;
    }}
    .report-header h1 {{ font-size: clamp(1.5rem, 3vw, 2.4rem); font-weight: 700; margin: 0 0 0.5rem; }}
    .report-header .lead {{ font-size: 1.05rem; opacity: 0.9; margin: 0; }}
    .report-header .meta {{ font-size: 0.9rem; opacity: 0.85; margin-top: 0.6rem; }}
    .report-header .meta i {{ margin-right: 0.3rem; }}
    .confidence-card {{
      background: linear-gradient(135deg, var(--pink) 0%, var(--pink2) 100%);
      border-radius: 12px;
      padding: 1.2rem 1.8rem;
      text-align: center;
      color: #fff;
    }}
    .confidence-card h4 {{ font-size: 0.85rem; margin: 0 0 0.3rem; opacity: 0.9; }}
    .confidence-card .score {{ font-size: 2.2rem; font-weight: 800; line-height: 1.1; }}
    .confidence-card small {{ opacity: 0.8; }}

    /* ── Sections ── */
    .report-section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 1.5rem 1.8rem;
      margin-bottom: 1.5rem;
      box-shadow: 0 1px 4px rgba(0,0,0,0.04);
      break-inside: avoid;
    }}
    .report-section h2 {{
      font-size: 1.3rem; font-weight: 700; margin: 0 0 1rem; padding-bottom: 0.5rem;
      border-bottom: 2px solid var(--accent);
      color: #333;
    }}
    .report-section h3 {{ font-size: 1.05rem; font-weight: 600; margin: 1.2rem 0 0.6rem; }}
    .report-section p, .report-section li {{ font-size: 0.95rem; }}
    .report-section ul {{ padding-left: 1.2rem; }}
    .report-section li {{ margin: 0.3rem 0; }}

    /* ── Executive Summary Callout ── */
    .exec-summary {{
      background: #eef2ff;
      border-left: 4px solid var(--accent);
      border-radius: 0 10px 10px 0;
      padding: 1.3rem 1.5rem;
      margin-bottom: 1.5rem;
    }}
    .exec-summary h3 {{ margin: 0 0 0.6rem; color: #4338ca; font-size: 1.1rem; }}
    .exec-summary i {{ margin-right: 0.4rem; }}

    /* ── Tables ── */
    .report-table {{
      width: 100%; border-collapse: collapse; margin: 0.8rem 0; font-size: 0.9rem;
    }}
    .report-table th, .report-table td {{
      border: 1px solid #dee2e6; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top;
    }}
    .report-table th {{ background: #f1f5f9; font-weight: 600; }}
    .report-table tr:nth-child(even) {{ background: #f8fafc; }}

    /* ── Metrics / Stat cards ── */
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1rem; margin: 1rem 0; }}
    .metric-card {{
      background: linear-gradient(135deg, var(--pink) 0%, var(--pink2) 100%);
      border-radius: 10px; padding: 1.2rem; color: #fff; text-align: center;
    }}
    .metric-card .value {{ font-size: 1.8rem; font-weight: 700; line-height: 1.2; }}
    .metric-card .label {{ font-size: 0.8rem; opacity: 0.9; }}

    /* ── Risk Cards ── */
    .risk-card {{
      border-radius: 8px; padding: 1rem 1.2rem; margin: 0.6rem 0;
      border-left: 4px solid; font-size: 0.92rem;
    }}
    .risk-high {{ background: #fef2f2; border-color: #ef4444; }}
    .risk-medium {{ background: #fff7ed; border-color: #f97316; }}
    .risk-low {{ background: #f0fdf4; border-color: #22c55e; }}
    .risk-card strong {{ display: block; margin-bottom: 0.3rem; }}

    /* ── Charts ── */
    .chart-tabs {{ margin-bottom: 1rem; }}
    .chart-tabs .nav-link {{ color: var(--accent); font-weight: 500; }}
    .chart-tabs .nav-link.active {{ color: var(--accent2); font-weight: 600; background: transparent; border-bottom: 2px solid var(--accent2); }}
    .chart-container {{ position: relative; height: 380px; margin: 1rem 0; }}

    /* ── Citations ── */
    .citation {{
      font-size: 0.88em; color: #555; border-left: 3px solid var(--accent);
      padding: 0.5rem 0 0.5rem 1rem; margin: 0.8rem 0;
      background: #fafafa; border-radius: 0 6px 6px 0;
    }}
    .citation .num {{ font-weight: 700; color: var(--accent2); }}
    .citation a {{ word-break: break-all; }}

    /* ── Recommendations ── */
    .rec-card {{
      background: #faf5ff; border-left: 4px solid #a855f7; border-radius: 0 8px 8px 0;
      padding: 1rem 1.2rem; margin: 0.8rem 0;
    }}
    .rec-card strong {{ display: block; margin-bottom: 0.3rem; color: #6b21a8; }}

    /* ── TOC ── */
    .toc {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.5rem; margin-bottom: 1.5rem; }}
    .toc h2 {{ font-size: 1.1rem; margin: 0 0 0.6rem; }}
    .toc ul {{ list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 1.5rem; }}
    .toc li {{ padding: 0.2rem 0; }}
    .toc a {{ text-decoration: none; color: var(--ink); font-size: 0.92rem; }}
    .toc a:hover {{ color: var(--accent); }}

    /* ── Footer ── */
    .report-footer {{
      background: #1e293b; color: #cbd5e1; padding: 1.5rem 0; margin-top: 2.5rem;
      font-size: 0.85rem; text-align: center;
    }}
    .report-footer strong {{ color: #f1f5f9; }}

    /* ── Print ── */
    @media print {{
      body {{ background: #fff; }}
      .report-header {{ padding: 1.5rem 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      .report-section {{ box-shadow: none; border: 1px solid #ddd; break-inside: avoid; }}
      .metric-card {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      .confidence-card {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
      .chart-container {{ height: 300px; break-inside: avoid; }}
      .toc ul {{ columns: 1; }}
    }}
    @media (max-width: 768px) {{
      .toc ul {{ columns: 1; }}
      .metric-grid {{ grid-template-columns: repeat(2, 1fr); }}
    }}
  </style>
</head>
<body>

  {_render_header(title, chart_count, citation_count)}

  <div class="container">

    {_render_toc(toc_entries)}

    <main>
      {body_html}
    </main>

    {_render_charts_section(charts)}

    {_render_citations_section(citations)}

  </div>

  <footer class="report-footer">
    <div class="container">
      <p><strong>FinSight 多智能体金融研报系统</strong> · 由 AI 自动生成，仅供参考</p>
      <p style="margin:0;font-size:0.8rem;opacity:0.7">报告 ID: {escape(title)} · {_generation_timestamp()}</p>
    </div>
  </footer>

  {_render_chart_script(charts)}
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""


def _render_header(title: str, chart_count: int, citation_count: int) -> str:
    return f"""<header class="report-header">
  <div class="container">
    <div class="row align-items-center">
      <div class="col-md-8">
        <h1><i class="fas fa-chart-line"></i> {escape(title)}</h1>
        <p class="lead">多智能体深度研究报告</p>
        <div class="meta">
          <span><i class="far fa-calendar-alt"></i> {_generation_timestamp()}</span>
          <span class="ms-3"><i class="fas fa-robot"></i> FinSight AI</span>
          {f'<span class="ms-3"><i class="fas fa-chart-bar"></i> 图表 {chart_count} 个</span>' if chart_count else ''}
          {f'<span class="ms-3"><i class="fas fa-bookmark"></i> 参考来源 {citation_count} 条</span>' if citation_count else ''}
        </div>
      </div>
      <div class="col-md-4 text-end d-none d-md-block">
        <div class="confidence-card">
          <h4><i class="fas fa-star"></i> 报告置信度</h4>
          <div class="score">{_estimate_confidence(chart_count, citation_count)}%</div>
          <small>基于数据覆盖与引用分析</small>
        </div>
      </div>
    </div>
  </div>
</header>"""


def _render_toc(entries: list[str]) -> str:
    if not entries:
        return ""
    items = "\n".join(f'<li><a href="#{_slugify(e)}"><i class="fas fa-chevron-right" style="font-size:0.6rem;color:var(--accent);margin-right:0.4rem"></i>{escape(e)}</a></li>' for e in entries)
    return f"""<div class="toc">
  <h2><i class="fas fa-list"></i> 目录</h2>
  <ul>{items}</ul>
</div>"""


def _render_charts_section(charts: List[Dict[str, Any]]) -> str:
    if not charts:
        return ""
    tabs = []
    panes = []
    for i, chart in enumerate(charts):
        chart_id = _safe_id(str(chart.get("chart_id") or f"chart_{i}"))
        title = escape(str(chart.get("title") or chart_id))
        active = " active" if i == 0 else ""
        tabs.append(f"""<button class="nav-link{active}" id="tab-{chart_id}" data-bs-toggle="tab" data-bs-target="#pane-{chart_id}" type="button" role="tab">{title}</button>""")
        panes.append(f"""<div class="tab-pane fade{' show active' if i == 0 else ''}" id="pane-{chart_id}" role="tabpanel"><div class="chart-container"><canvas id="canvas-{chart_id}" ondblclick="downloadChart(this)"></canvas></div></div>""")
    return f"""<section class="report-section">
  <h2><i class="fas fa-chart-pie"></i> 交互图表</h2>
  <ul class="nav nav-tabs chart-tabs" role="tablist">{''.join(tabs)}</ul>
  <div class="tab-content">{''.join(panes)}</div>
  <p class="text-muted" style="font-size:0.8rem;margin:0.5rem 0 0"><i class="fas fa-info-circle"></i> 双击图表可下载为 PNG</p>
</section>"""


def _render_citations_section(citations: List[Dict[str, Any]]) -> str:
    if not citations:
        return ""
    items = []
    for i, c in enumerate(citations, 1):
        title = escape(str(c.get("title") or c.get("evidence_id", f"来源 {i}")))
        url = escape(str(c.get("source_url") or ""))
        source = escape(str(c.get("source", "") or ""))
        date_str = escape(str(c.get("access_date") or c.get("retrieved_at", "")))
        items.append(f"""<div class="citation"><span class="num">[{i}]</span> <strong>{title}</strong><br><span style="font-size:0.85em">{source}{' · ' + date_str if date_str else ''}</span><br><a href="{url}" target="_blank" rel="noopener">{url}</a></div>""")
    return f"""<section class="report-section">
  <h2><i class="fas fa-quote-left"></i> 参考来源</h2>
  {''.join(items)}
</section>"""


def _render_chart_script(charts: List[Dict[str, Any]]) -> str:
    chart_payloads = []
    for chart in charts:
        chart_js = chart.get("chart_js") if isinstance(chart.get("chart_js"), dict) else {}
        if not chart_js:
            continue
        chart_id = _safe_id(str(chart.get("chart_id") or "chart"))
        chart_payloads.append({
            "id": f"canvas-{chart_id}",
            "type": chart_js.get("type", "bar"),
            "labels": chart_js.get("labels", []),
            "data": chart_js.get("data", []),
            "label": chart_js.get("label", str(chart.get("title") or "数据")),
        })
    if not chart_payloads:
        return ""
    payload = json.dumps(chart_payloads, ensure_ascii=False)
    return f"""<script>
  var chartPayloads = {payload};
  var palette = ['#667eea','#764ba2','#f093fb','#f5576c','#4facfe','#00f2fe','#43e97b','#fa709a'];
  function downloadChart(canvas) {{
    var link = document.createElement('a');
    link.download = canvas.id + '.png';
    link.href = canvas.toDataURL();
    link.click();
  }}
  for (var i = 0; i < chartPayloads.length; i++) {{
    var item = chartPayloads[i];
    var el = document.getElementById(item.id);
    if (!el || typeof Chart === 'undefined') continue;
    new Chart(el, {{
      type: item.type,
      data: {{
        labels: item.labels,
        datasets: [{{
          label: item.label,
          data: item.data,
          backgroundColor: item.type === 'doughnut' || item.type === 'pie'
            ? item.labels.map(function(_, j) {{ return palette[j % palette.length]; }})
            : palette.slice(0, item.labels.length).map(function(c) {{ return c + '80'; }}),
          borderColor: item.type === 'doughnut' || item.type === 'pie'
            ? '#fff' : palette[0],
          borderWidth: item.type === 'doughnut' || item.type === 'pie' ? 2 : 1,
        }}]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ display: item.type !== 'bar', position: 'top' }},
          tooltip: {{ mode: 'nearest' }}
        }}
      }}
    }});
  }}
</script>"""


def _markdown_to_html(markdown: str) -> str:
    """Convert simplified markdown to HTML, preserving table structures."""
    lines = markdown.splitlines()
    html: list[str] = []
    in_list = False
    section_open = False
    in_table = False
    table_header_done = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    def close_section() -> None:
        nonlocal section_open, in_table, table_header_done
        close_list()
        if in_table:
            html.append("</tbody></table>")
            in_table = False
            table_header_done = False
        if section_open:
            html.append("</section>")
            section_open = False

    def close_table() -> None:
        nonlocal in_table, table_header_done
        if in_table:
            html.append("</tbody></table>")
            in_table = False
            table_header_done = False

    for raw in lines:
        line = raw.rstrip()
        if not line:
            close_list()
            if in_table:
                # Empty line ends a table
                close_table()
            continue

        # Skip images
        if re.match(r"!\[(.*?)\]\((.*?)\)", line):
            continue

        # Sections: ## heading
        if line.startswith("## "):
            close_section()
            heading = escape(line[3:].strip())
            klass = "references" if heading == "参考来源" else "report-section"
            anchor = _slugify(heading)
            html.append(f'<section class="{klass}"><h2 id="{anchor}"><i class="fas fa-angle-right" style="color:var(--accent);margin-right:0.4rem"></i>{heading}</h2>')
            section_open = True
            continue

        # Skip h1 (used for title)
        if line.startswith("# "):
            continue

        # h3 subheadings
        if line.startswith("### "):
            close_list()
            close_table()
            html.append(f"<h3>{escape(line[4:].strip())}</h3>")
            continue

        # Detect table rows (pipe-delimited)
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            # Check if this is a separator row (|---|)
            if all(re.match(r"^-{1,}$", c) for c in cells):
                continue  # skip separator
            if not in_table:
                html.append("<table class=\"report-table\"><thead><tr>")
                for c in cells:
                    html.append(f"<th>{_inline_markdown(c)}</th>")
                html.append("</tr></thead><tbody>")
                in_table = True
                table_header_done = True
            else:
                if table_header_done:
                    table_header_done = False
                html.append("<tr>")
                for c in cells:
                    html.append(f"<td>{_inline_markdown(c)}</td>")
                html.append("</tr>")
            continue

        # Blockquote
        if line.startswith("> "):
            close_list()
            close_table()
            html.append(f"<blockquote style=\"border-left:3px solid var(--accent);padding:0.3rem 0 0.3rem 1rem;margin:0.5rem 0;color:var(--muted)\">{_inline_markdown(line[2:].strip())}</blockquote>")
            continue

        # List items
        if line.startswith("- ") or line.startswith("* "):
            close_table()
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_markdown(line[2:].strip())}</li>")
            continue

        # Paragraph
        close_list()
        close_table()
        html.append(f"<p>{_inline_markdown(line.strip())}</p>")

    close_section()
    return "\n".join(html)


def _inline_markdown(text: str) -> str:
    """Convert inline markdown formatting to HTML."""
    escaped = escape(text)
    # Bold **text**
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    # Inline code `text`
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


def _extract_toc(markdown: str) -> list[str]:
    """Extract h2 headings for table of contents."""
    entries: list[str] = []
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("## ") and line[3:].strip() not in ("参考来源", "交互图表"):
            entries.append(line[3:].strip())
    return entries


def _slugify(text: str) -> str:
    """Create a URL-safe anchor ID from text."""
    slug = re.sub(r"[^\w一-鿿]+", "-", text).strip("-")
    return slug or "section"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_") or "chart"


def _generation_timestamp() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _estimate_confidence(chart_count: int, citation_count: int) -> int:
    """Estimate a report confidence score based on data richness."""
    score = 60
    if chart_count >= 1:
        score += 10
    if chart_count >= 3:
        score += 5
    if citation_count >= 5:
        score += 10
    if citation_count >= 15:
        score += 5
    if chart_count >= 1 and citation_count >= 5:
        score += 5
    return min(score, 95)
