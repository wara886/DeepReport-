"""Professional HTML report generator with Bootstrap 5, Chart.js, and Font Awesome.

Inspired by the visual design of DeepReport_official_run reports.
"""

from __future__ import annotations

from html import escape
import json
import re
from typing import Any, Dict, List

from src.report.chart_generator import FALLBACK_LABEL_MAP, METRIC_LABEL_MAP, sanitize_chart_payloads


# 鈹€鈹€ Banned debug phrases 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
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


def _clean_phrases(text: str) -> str:
    """Remove banned debug/generic phrases from text, leaving valid content intact."""
    for phrase in BANNED_PHRASES:
        text = text.replace(phrase, "")
    text = re.sub(r"PDF section:\s*\S*", "", text, flags=re.IGNORECASE)
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
    "Data Gap and Degradation Notes" appendix. Isolated banned phrases in
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
        result.append("## Data Gap and Degradation Notes")
        result.append("")
        result.append("The following sections lacked sufficient verifiable public data and could not be fully analyzed in the current report:")
        result.append("")
        for sec in gap_sections:
            for line in sec:
                if line.startswith("## "):
                    result.append(f"### {line[3:].strip()} (data gap)")
                elif line.strip() and any(p in line for p in BANNED_PHRASES):
                    result.append("> insufficient data to support detailed analysis of this section")
                elif line.strip():
                    result.append(line)
        result.append("")

    return "\n".join(result)


def _render_degraded_warning() -> str:
    """Render a warning card for degraded reports."""
    return """<div class="degraded-warning">
  <i class="fas fa-exclamation-triangle"></i>
  <strong>Data Gap Notice:</strong>
  Some sections have been downgraded to data gap explanations due to a lack of verifiable evidence. Please refer to core sections such as the three-statement summary, valuation analysis, and risk assessment for complete analysis.
</div>"""


def sanitize_user_markdown(markdown: str) -> str:
    """Sanitize user-facing markdown by removing debug leakage, internal IDs, and invalid section content."""
    text = _filter_banned_phrases(markdown)
    text = _drop_markdown_reference_section(text)
    text = _replace_orphan_numeric_summary(text)
    text = _remove_internal_reference_lines(text)
    text = re.sub(r"supported claims:\s*cl_\d+(?:,\s*cl_\d+)*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"支持结论[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"鏀寔缁撹[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"claim_id:\s*cl_\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bclaim_id\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcl_\d{4}\b", "", text)
    text = re.sub(r"\bmetric_count\b", "", text)
    text = re.sub(r"\brejected_metric_count\b", "", text)
    text = re.sub(r"\bRisk-related claim evidence count\b", "", text)
    text = re.sub(r"statement_line_item_count\b", "", text)
    text = re.sub(r"Revenues\d{6,}", "", text)
    text = re.sub(r"NetIncomeLoss\d{6,}", "", text)
    text = re.sub(r"\bev_\d+\b", "", text)
    return text.strip()


def _drop_markdown_reference_section(markdown: str) -> str:
    """Remove markdown reference sections; HTML renders cleaned citations separately."""
    lines = markdown.splitlines()
    output: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip()
            lowered = heading.lower()
            skipping = (
                "参考来源" in heading
                or "references" in lowered
                or "鍙傝" in heading
                or "citation" in lowered
            )
            if skipping:
                continue
        if skipping:
            continue
        output.append(line)
    return "\n".join(output)


def _remove_internal_reference_lines(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        lowered = line.lower()
        if "cl_000" in lowered or "claim_id" in lowered:
            continue
        if "supported claims" in lowered or "支持结论" in line or "鏀寔缁撹" in line:
            continue
        if any(token in line for token in ("metric_count", "rejected_metric_count", "statement_line_item_count")):
            continue
        lines.append(line)
    return "\n".join(lines)


def _replace_orphan_numeric_summary(markdown: str) -> str:
    """Replace executive-summary sections that contain only orphan numeric bullets."""
    lines = markdown.splitlines()
    if not lines:
        return markdown
    output: list[str] = []
    i = 0
    replaced = False
    replacement = (
        "本报告已获取部分财务与市场数据，但当前摘要材料不足以形成完整结论。"
        "以下分析以已验证的三表、估值与来源信息为准，并在相关章节标注数据缺口。"
    )
    while i < len(lines):
        line = lines[i]
        if line.startswith("## ") and not replaced:
            heading = line[3:].strip()
            next_i = i + 1
            body: list[str] = []
            while next_i < len(lines) and not lines[next_i].startswith("## "):
                body.append(lines[next_i])
                next_i += 1
            numeric_bullets = [
                item for item in body
                if re.match(r"^\s*[-*]\s*\d+(?:\.\d+)?\s*$", item.strip())
            ]
            prose = "\n".join(
                item for item in body
                if item.strip() and not re.match(r"^\s*[-*]\s*\d+(?:\.\d+)?\s*$", item.strip())
            )
            prose_chars = re.sub(r"[\s#*\-:：，、。()\[\]0-9a-zA-Z]", "", prose)
            looks_like_exec = "执行摘要" in heading or "摘要" in heading or "鎵ц" in heading or not output
            if looks_like_exec and len(numeric_bullets) >= 2 and len(prose_chars) < 18:
                output.extend([line, "", replacement, ""])
                replaced = True
                i = next_i
                continue
        output.append(line)
        i += 1
    return "\n".join(output)


def render_professional_html_report(
    markdown: str,
    title: str,
    charts: List[Dict[str, Any]] | None = None,
    citations: List[Dict[str, Any]] | None = None,
    delivery_status: str = "normal",
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
    charts = sanitize_chart_payloads(charts or [])
    citations = citations or []
    markdown = sanitize_user_markdown(markdown)
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
  <!-- Chart.js + datalabels; tab controller is self-contained via initFinSightChartTabs -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
  <style>
    /* 鈹€鈹€ Base 鈹€鈹€ */
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

    /* 鈹€鈹€ Header 鈹€鈹€ */
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

    /* 鈹€鈹€ Sections 鈹€鈹€ */
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

    /* 鈹€鈹€ Executive Summary Callout 鈹€鈹€ */
    .exec-summary {{
      background: #eef2ff;
      border-left: 4px solid var(--accent);
      border-radius: 0 10px 10px 0;
      padding: 1.3rem 1.5rem;
      margin-bottom: 1.5rem;
    }}
    .exec-summary h3 {{ margin: 0 0 0.6rem; color: #4338ca; font-size: 1.1rem; }}
    .exec-summary i {{ margin-right: 0.4rem; }}

    /* 鈹€鈹€ Tables 鈹€鈹€ */
    .report-table {{
      width: 100%; border-collapse: collapse; margin: 0.8rem 0; font-size: 0.9rem;
    }}
    .report-table th, .report-table td {{
      border: 1px solid #dee2e6; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top;
    }}
    .report-table th {{ background: #f1f5f9; font-weight: 600; }}
    .report-table tr:nth-child(even) {{ background: #f8fafc; }}

    /* 鈹€鈹€ Metrics / Stat cards 鈹€鈹€ */
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1rem; margin: 1rem 0; }}
    .metric-card {{
      background: linear-gradient(135deg, var(--pink) 0%, var(--pink2) 100%);
      border-radius: 10px; padding: 1.2rem; color: #fff; text-align: center;
    }}
    .metric-card .value {{ font-size: 1.8rem; font-weight: 700; line-height: 1.2; }}
    .metric-card .label {{ font-size: 0.8rem; opacity: 0.9; }}

    /* 鈹€鈹€ Risk Cards 鈹€鈹€ */
    .risk-card {{
      border-radius: 8px; padding: 1rem 1.2rem; margin: 0.6rem 0;
      border-left: 4px solid; font-size: 0.92rem;
    }}
    .risk-high {{ background: #fef2f2; border-color: #ef4444; }}
    .risk-medium {{ background: #fff7ed; border-color: #f97316; }}
    .risk-low {{ background: #f0fdf4; border-color: #22c55e; }}
    .risk-card strong {{ display: block; margin-bottom: 0.3rem; }}

    /* 鈹€鈹€ Charts 鈹€鈹€ */
    .chart-tabs {{ display: flex; flex-direction: row; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid var(--line); padding-bottom: 0.25rem; }}
    .chart-tabs .nav-link {{ display: inline-flex; width: auto; border: 1px solid var(--line); border-radius: 8px 8px 0 0; padding: 0.6rem 1.1rem; cursor: pointer; background: #fff; color: var(--accent); font-weight: 500; }}
    .chart-tabs .nav-link.active {{ color: var(--accent2); font-weight: 600; background: transparent; border-bottom: 2px solid var(--accent2); border-color: var(--accent2); }}
    .chart-container {{ position: relative; height: 400px; margin: 1rem 0; }}

    /* 鈹€鈹€ Citations 鈹€鈹€ */
    .citation {{
      font-size: 0.88em; color: #555; border-left: 3px solid var(--accent);
      padding: 0.5rem 0 0.5rem 1rem; margin: 0.8rem 0;
      background: #fafafa; border-radius: 0 6px 6px 0;
    }}
    .citation .num {{ font-weight: 700; color: var(--accent2); }}
    .citation a {{ word-break: break-all; }}

    /* 鈹€鈹€ Recommendations 鈹€鈹€ */
    .rec-card {{
      background: #faf5ff; border-left: 4px solid #a855f7; border-radius: 0 8px 8px 0;
      padding: 1rem 1.2rem; margin: 0.8rem 0;
    }}
    .rec-card strong {{ display: block; margin-bottom: 0.3rem; color: #6b21a8; }}

    /* 鈹€鈹€ TOC 鈹€鈹€ */
    .toc {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.5rem; margin-bottom: 1.5rem; }}
    .toc h2 {{ font-size: 1.1rem; margin: 0 0 0.6rem; }}
    .toc ul {{ list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 1.5rem; }}
    .toc li {{ padding: 0.2rem 0; }}
    .toc a {{ text-decoration: none; color: var(--ink); font-size: 0.92rem; }}
    .toc a:hover {{ color: var(--accent); }}

    /* 鈹€鈹€ Footer 鈹€鈹€ */
    .report-footer {{
      background: #1e293b; color: #cbd5e1; padding: 1.5rem 0; margin-top: 2.5rem;
      font-size: 0.85rem; text-align: center;
    }}
    .report-footer strong {{ color: #f1f5f9; }}

    /* 鈹€鈹€ Degraded Warning 鈹€鈹€ */
    .degraded-warning {{ background: #fff8e1; border: 1px solid #ffe082; border-radius: 8px; padding: 1rem 1.2rem; margin-bottom: 1.5rem; font-size: 0.92rem; color: #6d4c00; }}
    .degraded-warning i {{ margin-right: 0.5rem; }}

    /* 鈹€鈹€ Print 鈹€鈹€ */
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

  {_render_header(title, chart_count, citation_count, delivery_status)}

  <div class="container">

    {_render_degraded_warning() if delivery_status == "degraded_due_to_content_quality" else ''}

    {_render_toc(toc_entries)}

    <main>
      {body_html}
    </main>

    {_render_charts_section(charts)}

    {_render_citations_section(citations)}

  </div>

  <footer class="report-footer">
    <div class="container">
      <p><strong>FinSight Multi-Agent Financial Research System</strong> &middot; AI-generated, for reference only</p>
      <p style="margin:0;font-size:0.8rem;opacity:0.7">Report ID: {escape(title)} &middot; {_generation_timestamp()}</p>
    </div>
  </footer>

  {_render_chart_script(charts)}
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""


def _render_header(title: str, chart_count: int, citation_count: int, delivery_status: str = "normal") -> str:
    subtitle = "Auto Financial Observation Report (Degraded)" if delivery_status == "degraded_due_to_content_quality" else "Multi-Agent Deep Research Report"
    return f"""<header class="report-header">
  <div class="container">
    <div class="row align-items-center">
      <div class="col-md-8">
        <h1><i class="fas fa-chart-line"></i> {escape(title)}</h1>
        <p class="lead">{subtitle}</p>
        <div class="meta">
          <span><i class="far fa-calendar-alt"></i> {_generation_timestamp()}</span>
          <span class="ms-3"><i class="fas fa-robot"></i> FinSight AI</span>
          {f'<span class="ms-3"><i class="fas fa-chart-bar"></i> Charts {chart_count}</span>' if chart_count else ''}
          {f'<span class="ms-3"><i class="fas fa-bookmark"></i> References {citation_count}</span>' if citation_count else ''}
        </div>
      </div>
      <div class="col-md-4 text-end d-none d-md-block">
        <div class="confidence-card">
          <h4><i class="fas fa-star"></i> Report Confidence</h4>
          <div class="score">{_estimate_confidence(chart_count, citation_count)}%</div>
          <small>Based on data coverage and citation analysis</small>
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
  <h2><i class="fas fa-list"></i> Table of Contents</h2>
  <ul>{items}</ul>
</div>"""


def _render_charts_section(charts: List[Dict[str, Any]]) -> str:
    if not charts:
        return ""
    tabs = []
    panes = []
    for i, chart in enumerate(charts):
        chart_id = _safe_id(str(chart.get("chart_id") or f"chart_{i}"))
        title = escape(_sanitize_text_for_user_html(str(chart.get("title") or chart_id), fallback="图表"))
        active = " active" if i == 0 else ""
        display = "block" if i == 0 else "none"
        tabs.append(f"""<button class="nav-link{active}" data-chart-tab="{chart_id}" type="button" role="tab">{title}</button>""")
        panes.append(f"""<div class="tab-pane" data-chart-pane="{chart_id}" style="display:{display}"><div class="chart-container"><canvas id="canvas-{chart_id}" ondblclick="downloadChart(this)"></canvas></div></div>""")
    return f"""<section class="report-section">
  <h2><i class="fas fa-chart-pie"></i> Interactive Charts</h2>
  <nav class="chart-tabs" role="tablist">{''.join(tabs)}</nav>
  <div class="tab-content">{''.join(panes)}</div>
  <p class="text-muted" style="font-size:0.8rem;margin:0.5rem 0 0"><i class="fas fa-info-circle"></i> Double-click a chart to save as PNG</p>
</section>"""


def _render_citations_section(citations: List[Dict[str, Any]]) -> str:
    if not citations:
        return ""
    items = []
    for i, c in enumerate(citations, 1):
        raw_title = str(c.get("title") or c.get("evidence_id", f"source {i}"))
        title = escape(_sanitize_citation_title(raw_title))
        url = escape(str(c.get("source_url") or ""))
        source = escape(str(c.get("source", "") or ""))
        date_str = escape(str(c.get("access_date") or c.get("retrieved_at", "")))
        items.append(f"""<div class="citation"><span class="num">[{i}]</span> <strong>{title}</strong><br><span style="font-size:0.85em">{source}{' 路 ' + date_str if date_str else ''}</span><br><a href="{url}" target="_blank" rel="noopener">{url}</a></div>""")
    return f"""<section class="report-section">
  <h2><i class="fas fa-quote-left"></i> References</h2>
  {''.join(items)}
</section>"""


def _sanitize_citation_title(raw_title: str) -> str:
    """Strip internal claim IDs from citation titles for user-facing display."""
    cleaned = re.sub(r'supported claims:\s*cl_\d+(?:,\s*cl_\d+)*', '', raw_title, flags=re.IGNORECASE)
    cleaned = re.sub(r'claim_id:\s*cl_\d+', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bcl_\d{4}\b', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > 120:
        cleaned = cleaned[:117] + "..."
    return cleaned or "reference"


def _render_chart_script(charts: List[Dict[str, Any]]) -> str:
    charts = sanitize_chart_payloads(charts)
    chart_payloads = []
    for chart in charts:
        chart_js = chart.get("chart_js") if isinstance(chart.get("chart_js"), dict) else {}
        if not chart_js:
            continue
        chart_id = _safe_id(str(chart.get("chart_id") or "chart"))
        chart_payloads.append({
            "id": f"canvas-{chart_id}",
            "type": chart_js.get("type", "bar"),
            "labels": [_sanitize_text_for_user_html(str(label), fallback=f"指标 {idx}") for idx, label in enumerate(chart_js.get("labels", []), start=1)],
            "data": chart_js.get("data", []),
            "label": _sanitize_text_for_user_html(str(chart_js.get("label") or chart.get("title") or "指标"), fallback="指标"),
        })
    if not chart_payloads:
        return ""
    payload = json.dumps(chart_payloads, ensure_ascii=False)
    return f"""<script>
  var chartPayloads = {payload};
  var palette = ['#667eea','#764ba2','#f093fb','#f5576c','#4facfe','#00f2fe','#43e97b','#fa709a'];
  if (typeof ChartDataLabels !== 'undefined') {{ Chart.register(ChartDataLabels); }}
  window.finSightCharts = window.finSightCharts || {{}};
  function downloadChart(canvas) {{
    var link = document.createElement('a');
    link.download = canvas.id + '.png';
    link.href = canvas.toDataURL();
    link.click();
  }}
  function chartConfig(item) {{
    return {{
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
          tooltip: {{ mode: 'nearest' }},
          datalabels: {{
            display: item.type === 'bar' ? 'auto' : false,
            color: '#333',
            font: {{ weight: 'bold', size: 10 }},
            anchor: 'end',
            align: 'end',
            offset: 2
          }}
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


def _sanitize_text_for_user_html(text: str, fallback: str = "指标") -> str:
    text = str(text or "").strip()
    if not text:
        return fallback
    mapped = METRIC_LABEL_MAP.get(text) or FALLBACK_LABEL_MAP.get(text)
    if mapped:
        return mapped
    lowered = text.lower()
    mapped = METRIC_LABEL_MAP.get(lowered) or FALLBACK_LABEL_MAP.get(lowered)
    if mapped:
        return mapped
    if (
        re.search(r"[\uFFFD]", text)
        or re.search(r"[鐠缂閹锟]", text)
        or re.search(r"[\ue000-\uf8ff]", text)
        or re.search(r"(缁撹|璇佹嵁|鏉ユ簮|鎽樿)", text)
        or re.search(r"[ÃÂÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]", text)
    ):
        if "evidence" in lowered or "source" in lowered:
            return "证据来源结构"
        if "claim" in lowered or "confidence" in lowered:
            return "结论"
        return fallback
    if re.search(r"^[a-z][a-z0-9_]+$", lowered):
        return FALLBACK_LABEL_MAP.get(lowered, fallback)
    return text


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
            klass = "references" if heading == "References" else "report-section"
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
        if line.startswith("## ") and line[3:].strip() not in ("References", "Interactive Charts"):
            entries.append(line[3:].strip())
    return entries


def _slugify(text: str) -> str:
    """Create a URL-safe anchor ID from text."""
    slug = re.sub(r"[^\w-]+", "-", text).strip("-")
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
