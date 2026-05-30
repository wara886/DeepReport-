"""Report post-processing for charts and richer HTML."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List


CHARTS_HEADER = "## 图表"


def attach_charts_to_markdown(markdown: str, charts: List[Dict[str, Any]]) -> str:
    base = _strip_markdown_charts(markdown).rstrip()
    lines = [CHARTS_HEADER, ""]
    if not charts:
        lines.append("- 暂无图表。")
    else:
        for chart in charts:
            title = str(chart.get("title") or chart.get("chart_id") or "图表")
            output_path = str(chart.get("output_path") or "")
            if output_path:
                lines.append(f"![{title}]({output_path})")
                lines.append("")
            else:
                lines.append(f"- {title}")
    return base + "\n\n" + "\n".join(lines).rstrip() + "\n"


def inject_chart_references(markdown: str, charts: List[Dict[str, Any]], charts_header: str = CHARTS_HEADER) -> str:
    """Inject ``> 参考图表：[title]`` lines at the end of relevant sections.

    Each chart's ``section_name`` (or ``chart_type``) is matched against markdown
    section headers.  If a section already contains a chart reference, it is
    skipped to avoid duplication.
    """
    if not charts:
        return markdown

    _reference_marker = "参考图表"

    # Group charts by their target section
    section_charts: Dict[str, List[str]] = {}
    for chart in charts:
        target = str(chart.get("section_name") or chart.get("chart_type") or "")
        title = str(chart.get("title") or chart.get("chart_id") or "图表")
        if not target or not title:
            continue
        section_charts.setdefault(target, []).append(title)

    if not section_charts:
        return markdown

    lines = markdown.split("\n")
    result: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        result.append(line)

        # Detect section headers
        stripped = line.strip()
        if not stripped.startswith("## "):
            i += 1
            continue

        current_section = stripped[len("## "):].strip().lower().replace(" ", "_")

        # Check if this section has charts
        matched_titles: List[str] = []
        for section_key, titles in section_charts.items():
            sec_lower = section_key.lower().replace(" ", "_")
            if sec_lower == current_section or sec_lower in current_section or current_section in sec_lower:
                matched_titles.extend(titles)

        if not matched_titles:
            i += 1
            continue

        # Collect all lines of this section
        j = i + 1
        section_body: List[str] = []
        while j < len(lines):
            if lines[j].strip().startswith("## ") or lines[j].strip().startswith(charts_header):
                break
            section_body.append(lines[j])
            j += 1

        # Check if this section already has a chart reference
        body_text = "\n".join(section_body)
        if _reference_marker in body_text:
            i = j
            result.extend(section_body)
            continue

        # Inject chart reference before the last blank line of the section
        # Find the trailing blank lines
        ref_line = f"\n> {_reference_marker}：{'、'.join(matched_titles)}"
        # Insert ref_line before the trailing blank lines at end of section
        k = len(section_body) - 1
        while k >= 0 and section_body[k].strip() == "":
            k -= 1
        # Insert at k+1 (after last non-blank line)
        section_body.insert(k + 1, ref_line)

        result.extend(section_body)
        i = j

    return "\n".join(result)


def attach_charts_to_html(html: str, charts: List[Dict[str, Any]]) -> str:
    block = render_chart_html(charts)
    if "</body>" in html:
        return html.replace("</body>", block + "\n</body>")
    return html.rstrip() + "\n" + block + "\n"


def render_chart_html(charts: List[Dict[str, Any]]) -> str:
    parts = ['<section class="report-charts"><h2>图表</h2>']
    if not charts:
        parts.append("<p>暂无图表。</p>")
    else:
        for chart in charts:
            title = escape(str(chart.get("title") or chart.get("chart_id") or "图表"))
            output_path = str(chart.get("output_path") or "")
            safe_path = escape(output_path, quote=True)
            parts.append('<figure class="chart-card">')
            if output_path:
                parts.append(f'<img src="{safe_path}" alt="{title}">')
            parts.append(f"<figcaption>{title}</figcaption>")
            parts.append("</figure>")
    parts.append("</section>")
    return "\n".join(parts)


def polish_report_html(html: str) -> str:
    """Add a compact report stylesheet if the HTML came from the simple renderer."""

    extra_css = """
    .report-charts { margin: 28px 0; }
    .chart-card { margin: 18px 0; padding: 12px; border: 1px solid #d7dfda; border-radius: 8px; background: #ffffff; }
    .chart-card img { max-width: 100%; height: auto; display: block; }
    .chart-card figcaption { margin-top: 8px; color: #66736d; font-size: 0.92rem; }
    section { margin: 22px 0; }
    a { color: #0f766e; }
    """
    if ".chart-card img" in html:
        return html
    if "</style>" in html:
        return html.replace("</style>", extra_css + "\n  </style>")
    if "</head>" in html:
        return html.replace("</head>", f"<style>{extra_css}</style>\n</head>")
    return html


def _strip_markdown_charts(markdown: str) -> str:
    marker = f"\n{CHARTS_HEADER}"
    start = markdown.find(marker)
    prefix_offset = 1
    if start < 0 and markdown.startswith(CHARTS_HEADER):
        start = 0
        prefix_offset = 0
    if start < 0:
        legacy_marker = "\n## Charts"
        start = markdown.find(legacy_marker)
        prefix_offset = 1
        if start < 0 and markdown.startswith("## Charts"):
            start = 0
            prefix_offset = 0
    if start < 0:
        return markdown

    section_start = start + prefix_offset
    next_header = markdown.find("\n## ", section_start + len(CHARTS_HEADER))
    if next_header < 0:
        return markdown[:start]
    return markdown[:start] + markdown[next_header:]
