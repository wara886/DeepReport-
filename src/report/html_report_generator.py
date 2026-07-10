"""Professional standalone HTML report renderer.

This module is intentionally conservative: report quality diagnostics stay in
sidecar artifacts, while the user-facing HTML shows only the report body,
charts, citations, and a plain delivery status.
"""

from __future__ import annotations

from html import escape
import json
import re
from typing import Any, Dict, List

from src.report.chart_generator import FALLBACK_LABEL_MAP, METRIC_LABEL_MAP, sanitize_chart_payloads
from src.report.mojibake_guard import repair_known_mojibake_text


BANNED_PHRASES: List[str] = [
    "insufficient_verifiable_evidence",
    "PDF_section",
    "section_pending",
    "to_be_supplemented",
    "framework_only",
    "risk_operation_concern_reminder",
    "web_search_reminder",
    "data_gap",
    "N/A",
]

QUALITY_DIAGNOSTIC_PATTERNS = [
    r"^\s*质量诊断(?:建议)?[：:][^\n]*$",
    r"^\s*Quality Diagnostics?[：:][^\n]*$",
    r"^\s*[-*]\s*(?:ownership_governance|strategy_business|peer_compare|valuation|risk_factors|business_overview)[^\n]*$",
]

RAW_METRIC_LINE_RE = re.compile(
    r"^\s*(?:revenue|net_income|total_assets|total_liabilities|operating_cash_flow|free_cash_flow)\s*:\s*[-+]?\d",
    re.IGNORECASE,
)


def sanitize_user_markdown(markdown: str) -> str:
    """Remove user-visible debug leakage without changing real report content."""
    text = repair_known_mojibake_text(str(markdown or ""))
    text = _drop_markdown_reference_section(text)
    text = _replace_internal_metric_keys(text)
    text = _strip_valuation_numbers(text)
    text = _format_chinese_amounts(text)

    cleaned_lines: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            continue
        if any(phrase in stripped for phrase in BANNED_PHRASES):
            continue
        if any(re.search(pattern, stripped, flags=re.IGNORECASE) for pattern in QUALITY_DIAGNOSTIC_PATTERNS):
            continue
        if RAW_METRIC_LINE_RE.match(stripped):
            continue
        if re.fullmatch(r"\[\d+(?:,\s*\d+)*\]", stripped):
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_professional_html_report(
    markdown: str,
    title: str,
    charts: List[Dict[str, Any]] | None = None,
    citations: List[Dict[str, Any]] | None = None,
    delivery_status: str = "normal",
    top_blockers: List[str] | None = None,
    quality_blocked: bool = False,
    contract_mode: bool = False,
) -> str:
    """Render a professional standalone HTML report."""
    charts = _visible_user_charts(charts or [])
    citations = citations or []
    markdown = sanitize_user_markdown(markdown)
    title = _clean_report_title(title, markdown)

    body_html = _markdown_to_html(markdown)
    chart_count = len(charts)
    citation_count = len(citations)
    toc_entries = _extract_toc(markdown)
    is_zh = _contains_cjk(title + markdown)

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
  <style>
    :root {{
      --accent: #3b6ea8;
      --accent-2: #8b6f47;
      --ink: #172033;
      --muted: #667085;
      --paper: #ffffff;
      --soft: #f5f7fa;
      --line: #d8dee8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--soft);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
      line-height: 1.75;
    }}
    .report-header {{
      background: linear-gradient(135deg, #203048 0%, #315679 54%, #8b6f47 100%);
      color: #fff;
      padding: 2.7rem 0 2.1rem;
      margin-bottom: 2rem;
    }}
    .report-header h1 {{ font-size: clamp(1.5rem, 3vw, 2.35rem); font-weight: 750; margin: 0 0 .55rem; }}
    .report-header .lead {{ margin: 0; opacity: .92; font-size: 1.03rem; }}
    .report-header .meta {{ margin-top: .7rem; font-size: .9rem; opacity: .88; }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      gap: .4rem;
      border: 1px solid rgba(255,255,255,.35);
      border-radius: 999px;
      padding: .4rem .8rem;
      margin-top: .85rem;
      font-size: .85rem;
      background: rgba(255,255,255,.12);
    }}
    .container {{ max-width: 1120px; }}
    .report-section, .toc {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 1.4rem 1.65rem;
      margin-bottom: 1.45rem;
      box-shadow: 0 1px 5px rgba(16, 24, 40, .045);
    }}
    .report-section h2 {{
      display: flex;
      align-items: center;
      gap: .45rem;
      font-size: 1.28rem;
      font-weight: 750;
      margin: 0 0 1rem;
      padding-bottom: .55rem;
      border-bottom: 2px solid var(--accent);
    }}
    .report-section h3 {{ font-size: 1.06rem; font-weight: 700; margin: 1.15rem 0 .55rem; }}
    .report-section p, .report-section li {{ font-size: .96rem; }}
    .report-table {{ width: 100%; border-collapse: collapse; margin: .8rem 0 1rem; font-size: .92rem; }}
    .report-table th, .report-table td {{ border: 1px solid var(--line); padding: .55rem .75rem; vertical-align: top; }}
    .report-table th {{ background: #eef3f8; font-weight: 700; }}
    .report-table tr:nth-child(even) {{ background: #f8fafc; }}
    .toc h2 {{ font-size: 1.08rem; margin: 0 0 .65rem; }}
    .toc ul {{ list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 1.6rem; }}
    .toc li {{ break-inside: avoid; padding: .16rem 0; }}
    .toc a {{ color: var(--ink); text-decoration: none; font-size: .93rem; }}
    .toc a:hover {{ color: var(--accent); }}
    .chart-tabs {{ display: flex; flex-direction: row; flex-wrap: wrap; gap: .55rem; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid var(--line); padding-bottom: .3rem; }}
    .chart-tabs .nav-link {{ display: inline-flex; width: auto; border: 1px solid var(--line); border-radius: 8px 8px 0 0; padding: .58rem 1.05rem; cursor: pointer; background: #fff; color: var(--accent); font-weight: 600; }}
    .chart-tabs .nav-link.active {{ color: var(--accent-2); border-color: var(--accent-2); border-bottom: 2px solid var(--accent-2); }}
    .chart-container {{ position: relative; height: 400px; margin: 1rem 0; }}
    .citation {{ border-left: 3px solid var(--accent); padding: .55rem 0 .55rem .9rem; margin: .75rem 0; background: #f8fafc; border-radius: 0 6px 6px 0; font-size: .88rem; }}
    .citation .num {{ font-weight: 750; color: var(--accent); }}
    .citation a {{ word-break: break-all; }}
    .degraded-warning {{ background: #fff8e6; border: 1px solid #f5d48b; border-radius: 8px; padding: .95rem 1.15rem; margin-bottom: 1.45rem; color: #6d4c00; }}
    .report-footer {{ background: #182235; color: #d8dee8; padding: 1.35rem 0; margin-top: 2.5rem; text-align: center; font-size: .86rem; }}
    .report-footer strong {{ color: #fff; }}
    @media (max-width: 768px) {{
      .toc ul {{ columns: 1; }}
      .report-section, .toc {{ padding: 1.15rem; }}
      .chart-container {{ height: 340px; }}
    }}
    @media print {{
      body {{ background: #fff; }}
      .report-section, .toc {{ box-shadow: none; break-inside: avoid; }}
      .chart-container {{ height: 300px; }}
    }}
  </style>
</head>
<body>
  {_render_header(title, chart_count, citation_count, delivery_status, top_blockers=top_blockers or [], quality_blocked=quality_blocked)}
  <div class="container">
    {_render_degraded_warning(is_zh) if delivery_status.startswith("degraded") or delivery_status.startswith("blocked") or quality_blocked else ""}
    {_render_toc(toc_entries)}
    <main>{body_html}</main>
    {_render_charts_section(charts, is_zh)}
    {_render_citations_section(citations, is_zh)}
  </div>
  <footer class="report-footer">
    <div class="container">
      <p><strong>{"FinSight 多智能体金融研报系统" if is_zh else "FinSight Multi-Agent Financial Research System"}</strong> &middot; {"AI 生成，仅供参考" if is_zh else "AI-generated, for reference only"}</p>
      <p style="margin:0;font-size:.8rem;opacity:.72">{"报告 ID" if is_zh else "Report ID"}: {escape(title)}</p>
    </div>
  </footer>
  {_render_chart_script(charts)}
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""
    return _strip_html_mojibake(html_doc)


def _render_header(
    title: str,
    chart_count: int,
    citation_count: int,
    delivery_status: str = "normal",
    top_blockers: list[str] | None = None,
    quality_blocked: bool = False,
) -> str:
    blocker_text = " ".join(str(item or "") for item in (top_blockers or []))
    is_zh = _contains_cjk(title + blocker_text)
    blocked = quality_blocked or delivery_status.startswith("blocked") or delivery_status.startswith("degraded")
    subtitle = "草稿研报（正式交付阻塞）" if (is_zh and blocked) else (
        "多智能体深度研究报告" if is_zh else (
            "Draft Report (Formal Delivery Blocked)" if blocked else "Multi-Agent Deep Research Report"
        )
    )
    status = "草稿生成，正式交付阻塞" if (is_zh and blocked) else (
        "正常生成" if is_zh else ("Draft Generated, Formal Delivery Blocked" if blocked else "Generated")
    )
    score = _estimate_confidence(chart_count, citation_count, delivery_status)
    diagnostic_label = "质量诊断" if is_zh else "Quality review"
    blocker_labels = [_user_blocker_label(item, is_zh=is_zh) for item in (top_blockers or [])[:5]]
    blocker_html = ""
    if blocked:
        tags = "".join(f'<span class="blocker-tag">{escape(label)}</span>' for label in blocker_labels)
        blocker_html = f'<div class="quality-diagnostic"><strong>{diagnostic_label}：</strong>{tags or status}</div>'
    return f"""<header class="report-header">
  <div class="container">
    <h1><i class="fas fa-chart-line"></i> {escape(title)}</h1>
    <p class="lead">{subtitle}</p>
    <div class="meta">
      <span><i class="fas fa-robot"></i> FinSight AI</span>
      {f'<span class="ms-3"><i class="fas fa-chart-bar"></i> 图表 {chart_count}</span>' if chart_count else ""}
      {f'<span class="ms-3"><i class="fas fa-bookmark"></i> 参考来源 {citation_count}</span>' if citation_count else ""}
    </div>
    <div class="status-badge"><i class="fas fa-circle-info"></i> {status} · {score}%</div>
    {blocker_html}
  </div>
</header>"""


def _user_blocker_label(value: str, is_zh: bool) -> str:
    key = str(value or "").strip()
    labels_zh = {
        "governance_section_gap": "治理信息证据不足",
        "governance_gap": "治理信息待补充",
        "peer_universe_mismatch": "同行样本口径不一致",
    }
    if is_zh:
        return labels_zh.get(key, key.replace("_", " "))
    return key.replace("_", " ").title()


def _render_degraded_warning(is_zh: bool = False) -> str:
    if is_zh:
        return """<div class="degraded-warning"><i class="fas fa-exclamation-triangle"></i> 当前报告为草稿版本，正式交付仍被证据、章节质量、主张复核或导出门禁阻塞。请先处理质量诊断中的阻塞原因。</div>"""
    return """<div class="degraded-warning"><i class="fas fa-exclamation-triangle"></i> This is a draft report. Formal delivery is still blocked by evidence, section quality, claim review, or export readiness gates.</div>"""


def _render_toc(entries: list[str]) -> str:
    if not entries:
        return ""
    title = "目录" if any(_contains_cjk(e) for e in entries) else "Table of Contents"
    items = "\n".join(
        f'<li><a href="#{_slugify(e)}"><i class="fas fa-chevron-right" style="font-size:.62rem;color:var(--accent);margin-right:.35rem"></i>{escape(e)}</a></li>'
        for e in entries
    )
    return f'<div class="toc"><h2><i class="fas fa-list"></i> {title}</h2><ul>{items}</ul></div>'


def _render_charts_section(charts: List[Dict[str, Any]], is_zh: bool = False) -> str:
    charts = _visible_user_charts(charts)
    if not charts:
        return ""
    tabs: List[str] = []
    panes: List[str] = []
    for i, chart in enumerate(charts):
        chart_id = _safe_id(str(chart.get("chart_id") or f"chart_{i}"))
        title = escape(_sanitize_text_for_user_html(str(chart.get("title") or chart_id), fallback="图表"))
        active = " active" if i == 0 else ""
        display = "block" if i == 0 else "none"
        tabs.append(f'<button class="nav-link{active}" data-chart-tab="{chart_id}" type="button" role="tab">{title}</button>')
        panes.append(f'<div class="tab-pane" data-chart-pane="{chart_id}" style="display:{display}"><div class="chart-container"><canvas id="canvas-{chart_id}" ondblclick="downloadChart(this)"></canvas></div></div>')
    heading = "交互图表" if is_zh else "Interactive Charts"
    hint = "双击图表可保存为 PNG" if is_zh else "Double-click a chart to save as PNG"
    return f"""<section class="report-section">
  <h2><i class="fas fa-chart-pie"></i> {heading}</h2>
  <nav class="chart-tabs" role="tablist">{''.join(tabs)}</nav>
  <div class="tab-content">{''.join(panes)}</div>
  <p class="text-muted" style="font-size:.82rem;margin:.5rem 0 0"><i class="fas fa-info-circle"></i> {hint}</p>
</section>"""


def _render_citations_section(citations: List[Dict[str, Any]], is_zh: bool = False) -> str:
    if not citations:
        return ""
    heading = "参考来源" if is_zh else "References"
    items: List[str] = []
    for i, citation in enumerate(citations, start=1):
        raw_title = str(citation.get("title") or citation.get("evidence_id") or f"source {i}")
        title = escape(_sanitize_citation_title(raw_title))
        url = escape(str(citation.get("source_url") or ""))
        source = escape(str(citation.get("source") or citation.get("source_type") or ""))
        date_str = escape(str(citation.get("access_date") or citation.get("retrieved_at") or citation.get("publish_time") or ""))
        meta = source + ((" · " + date_str) if date_str else "")
        link = f'<a href="{url}" target="_blank" rel="noopener">{url}</a>' if url else ""
        items.append(f'<div class="citation"><span class="num">[{i}]</span> <strong>{title}</strong><br><span>{meta}</span><br>{link}</div>')
    return f'<section class="report-section"><h2><i class="fas fa-quote-left"></i> {heading}</h2>{"".join(items)}</section>'


def _render_chart_script(charts: List[Dict[str, Any]]) -> str:
    charts = _visible_user_charts(charts)
    chart_payloads: List[Dict[str, Any]] = []
    for chart in charts:
        chart_js = chart.get("chart_js") if isinstance(chart.get("chart_js"), dict) else {}
        if not chart_js:
            continue
        chart_id = _safe_id(str(chart.get("chart_id") or "chart"))
        chart_payloads.append(
            {
                "id": f"canvas-{chart_id}",
                "type": chart_js.get("type", "bar"),
                "labels": [
                    _sanitize_text_for_user_html(str(label), fallback=f"指标 {idx}")
                    for idx, label in enumerate(chart_js.get("labels", []), start=1)
                ],
                "data": chart_js.get("data", []),
                "label": _sanitize_text_for_user_html(str(chart_js.get("label") or chart.get("title") or "指标"), fallback="指标"),
                "unit_label": _sanitize_text_for_user_html(str(chart_js.get("unit_label") or ""), fallback=""),
            }
        )
    if not chart_payloads:
        return ""
    payload = json.dumps(chart_payloads, ensure_ascii=False)
    return f"""<script>
  var chartPayloads = {payload};
  var palette = ['#3b6ea8','#8b6f47','#56a3a6','#d88948','#7a89c2','#6ea87a','#b56576','#4a6f8f'];
  if (typeof ChartDataLabels !== 'undefined') {{ Chart.register(ChartDataLabels); }}
  window.finSightCharts = window.finSightCharts || {{}};
  function downloadChart(canvas) {{
    var link = document.createElement('a');
    link.download = canvas.id + '.png';
    link.href = canvas.toDataURL();
    link.click();
  }}
  function chartConfig(item) {{
    var isBar = item.type === 'bar';
    var unit = item.unit_label || '';
    return {{
      type: item.type,
      data: {{
        labels: item.labels,
        datasets: [{{
          label: item.label,
          data: item.data,
          backgroundColor: item.labels.map(function(_, j) {{ return palette[j % palette.length] + '80'; }}),
          borderColor: palette[0],
          borderWidth: 1,
          maxBarThickness: isBar ? 48 : undefined,
          categoryPercentage: isBar ? 0.45 : undefined,
          barPercentage: isBar ? 0.65 : undefined
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        layout: isBar ? {{ padding: {{ top: 24 }} }} : {{}},
        scales: isBar && unit ? {{ y: {{ title: {{ display: true, text: unit }}, ticks: {{ callback: function(v) {{ return v.toLocaleString(); }} }} }} }} : {{}},
        plugins: {{
          legend: {{ display: item.type !== 'bar', position: 'top' }},
          tooltip: isBar && unit ? {{ callbacks: {{ label: function(ctx) {{ return ctx.dataset.label + ': ' + ctx.parsed.y.toLocaleString() + ' ' + unit; }} }} }} : {{ mode: 'nearest' }},
          datalabels: {{ display: isBar ? 'auto' : false, color: '#333', font: {{ weight: 'bold', size: 10 }}, anchor: 'end', align: 'end', offset: 2, formatter: isBar && unit ? function(v) {{ return v.toLocaleString() + ' ' + unit; }} : undefined }}
        }}
      }}
    }};
  }}
  function ensureChartRendered(chartId) {{
    if (window.finSightCharts[chartId]) return;
    var canvas = document.getElementById('canvas-' + chartId);
    if (!canvas) return;
    var payload = chartPayloads.find(function(p) {{ return p.id === 'canvas-' + chartId; }});
    if (!payload || typeof Chart === 'undefined') return;
    window.finSightCharts[chartId] = new Chart(canvas, chartConfig(payload));
  }}
  function initFinSightChartTabs() {{
    var tabs = document.querySelectorAll('[data-chart-tab]');
    var panes = document.querySelectorAll('[data-chart-pane]');
    tabs.forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        var id = this.getAttribute('data-chart-tab');
        tabs.forEach(function(t) {{ t.classList.remove('active'); }});
        panes.forEach(function(p) {{ p.style.display = 'none'; }});
        var target = document.querySelector('[data-chart-pane="' + id + '"]');
        if (target) target.style.display = 'block';
        this.classList.add('active');
        ensureChartRendered(id);
      }});
    }});
    var firstTab = document.querySelector('[data-chart-tab].active');
    if (firstTab) ensureChartRendered(firstTab.getAttribute('data-chart-tab'));
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', initFinSightChartTabs);
  }} else {{
    initFinSightChartTabs();
  }}
</script>"""


def _markdown_to_html(markdown: str) -> str:
    sections: List[str] = []
    current_title: str | None = None
    current_lines: List[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title is None:
            if current_lines:
                sections.append(_render_lines(current_lines))
        else:
            sections.append(
                f'<section class="report-section"><h2 id="{_slugify(current_title)}"><i class="fas fa-angle-right"></i> {escape(current_title)}</h2>{_render_lines(current_lines)}</section>'
            )
        current_title = None
        current_lines = []

    for line in markdown.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            flush()
            current_title = line[3:].strip()
        elif line.strip().startswith("![") and ")" in line:
            continue  # skip markdown image syntax — Chart.js handles charts in HTML mode
        else:
            current_lines.append(line)
    flush()
    return "\n".join(section for section in sections if section.strip())


def _render_lines(lines: List[str]) -> str:
    html_parts: List[str] = []
    paragraph: List[str] = []
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            html_parts.append(f"<p>{_inline_markdown(' '.join(paragraph).strip())}</p>")
            paragraph = []

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            i += 1
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            html_parts.append(f"<h3>{escape(stripped[4:].strip())}</h3>")
            i += 1
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            flush_paragraph()
            table_lines: List[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            html_parts.append(_render_markdown_table(table_lines))
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            items: List[str] = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            html_parts.append("<ul>" + "".join(f"<li>{_inline_markdown(item)}</li>" for item in items) + "</ul>")
            continue
        paragraph.append(stripped)
        i += 1
    flush_paragraph()
    return "\n".join(html_parts)


def _render_markdown_table(lines: List[str]) -> str:
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    if len(rows) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in rows[1]):
        header = rows[0]
        body_rows = rows[2:]
    else:
        header = rows[0]
        body_rows = rows[1:]
    thead = "<thead><tr>" + "".join(f"<th>{_inline_markdown(cell)}</th>" for cell in header) + "</tr></thead>"
    tbody = "<tbody>" + "".join("<tr>" + "".join(f"<td>{_inline_markdown(cell)}</td>" for cell in row) + "</tr>" for row in body_rows) + "</tbody>"
    return f'<table class="report-table">{thead}{tbody}</table>'


def _inline_markdown(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[(\d+)\]", r'<span class="citation-ref">[\1]</span>', escaped)
    return escaped


def _extract_toc(markdown: str) -> list[str]:
    return [line[3:].strip() for line in markdown.splitlines() if line.startswith("## ")]


def _drop_markdown_reference_section(markdown: str) -> str:
    lines = markdown.splitlines()
    output: List[str] = []
    skipping = False
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            skipping = any(token in heading for token in ["参考来源", "references", "citation", "引用"])
            if skipping:
                continue
        if not skipping:
            output.append(line)
    return "\n".join(output)


def _replace_internal_metric_keys(markdown: str) -> str:
    replacements = {
        "adjusted_net_income": "调整后净利润",
        "non_recurring_gain": "非经常性损益",
        "revenue_growth_pct": "收入增长率",
        "gross_margin_pct": "毛利率",
        "net_margin_pct": "净利率",
        "pe_ttm": "市盈率（TTM）",
        "ps_ttm": "市销率（TTM）",
        "market_cap_trillion": "总市值",
        "revenue_billion": "收入",
        "net_income_billion": "净利润",
        "total_assets_billion": "总资产",
        "operating_cash_flow_billion": "经营现金流",
        "free_cash_flow_billion": "自由现金流",
        "total_assets": "总资产",
        "total_liabilities": "总负债",
        "operating_cash_flow": "经营现金流",
        "free_cash_flow": "自由现金流",
    }
    text = markdown
    for raw, label in replacements.items():
        text = text.replace(raw, label)
    return text


def _strip_valuation_numbers(text: str) -> str:
    replacement = "由于关键估值输入尚未完整校验，本报告不输出确定性 P/E、P/S、DCF 或目标价。"
    text = re.sub(r"P/?E\s*(?:约为|倍数)?\s*\d+\.?\d*\s*x?", replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"P/?S\s*(?:约为|倍数)?\s*\d+\.?\d*\s*x?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"DCF\s*[^\n]{0,80}", "", text, flags=re.IGNORECASE)
    text = re.sub(r"目标价[^\n]{0,30}\d+\.?\d*", "", text)
    return text


def _format_chinese_amounts(text: str) -> str:
    if not _contains_cjk(text):
        return text

    def replace_bn(match: re.Match[str]) -> str:
        return f"{float(match.group(1)) * 10:,.2f} 亿元人民币"

    return re.sub(r"(\d+\.?\d*)\s*billion\s*CNY", replace_bn, text)


def _visible_user_charts(charts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    visible = []
    for chart in sanitize_chart_payloads(charts or []):
        if not isinstance(chart, dict):
            continue
        if chart.get("diagnostic_only") is True:
            continue
        if str(chart.get("chart_id") or "") in {"claim_confidence_bar", "evidence_source_mix"}:
            continue
        visible.append(chart)
    return visible


def _sanitize_text_for_user_html(text: str, fallback: str = "指标") -> str:
    text = repair_known_mojibake_text(str(text or "").strip())
    if not text:
        return fallback
    mapped = FALLBACK_LABEL_MAP.get(text) or METRIC_LABEL_MAP.get(text) or FALLBACK_LABEL_MAP.get(text.lower()) or METRIC_LABEL_MAP.get(text.lower())
    if mapped:
        return mapped
    if "\ufffd" in text:
        return fallback
    return text


def _clean_report_title(title: str, markdown: str = "") -> str:
    """Repair or replace unusable report titles without inventing company names."""
    candidate = _sanitize_text_for_user_html(title, fallback="")
    if not _title_is_broken(candidate):
        return candidate
    md_title = ""
    for line in str(markdown or "").splitlines():
        if line.startswith("# "):
            md_title = _sanitize_text_for_user_html(line[2:].strip(), fallback="")
            break
    if md_title and not _title_is_broken(md_title):
        return md_title
    symbol = _extract_symbol(candidate + "\n" + markdown)
    period = _extract_period(candidate + "\n" + markdown)
    if symbol and period:
        return f"财务研究报告：{symbol}（{period}）"
    if symbol:
        return f"财务研究报告：{symbol}"
    return "财务研究报告"


def _title_is_broken(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    question_count = text.count("?") + text.count("\ufffd")
    return question_count >= 3 and question_count >= max(1, len(text) // 4)


def _extract_symbol(text: str) -> str:
    match = re.search(r"\b\d{6}\.(?:SS|SZ)\b|\b\d{4}\.HK\b|\b[A-Z]{1,5}\b", str(text or "").upper())
    return match.group(0) if match else ""


def _extract_period(text: str) -> str:
    match = re.search(r"\bFY20\d{2}\b|\b20\d{2}Q[1-4]\b|\b20\d{2}\b", str(text or "").upper())
    return match.group(0) if match else ""


def _sanitize_citation_title(raw_title: str) -> str:
    cleaned = repair_known_mojibake_text(str(raw_title or ""))
    cleaned = re.sub(r"supported claims:\s*cl_\d+(?:,\s*cl_\d+)*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"claim_id:\s*cl_\d+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bcl_\d{4}\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned[:117] + "...") if len(cleaned) > 120 else (cleaned or "reference")


def _strip_html_mojibake(text: str) -> str:
    cleaned = str(text or "")
    for marker in ["璐㈠姟", "缁撹", "鐮旂┒", "鎵ц", "璇佹嵁", "鏀跺叆", "鍑€"]:
        cleaned = cleaned.replace(marker, repair_known_mojibake_text(marker))
    return cleaned


def _slugify(text: str) -> str:
    slug = re.sub(r"\s+", "-", str(text or "").strip())
    slug = re.sub(r"[^\w\-\u4e00-\u9fff]", "", slug)
    return slug or "section"


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    return safe.strip("-") or "chart"


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _estimate_confidence(chart_count: int, citation_count: int, delivery_status: str = "normal") -> int:
    if delivery_status.startswith("blocked"):
        return 50
    if delivery_status.startswith("degraded"):
        return 68
    return min(95, 70 + min(chart_count, 5) * 4 + min(citation_count, 10) * 2)
