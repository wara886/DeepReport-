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
        for heading, grouped in [
            ("### 研报图表", _charts_by_category(charts, "report")),
            ("### 审计附录图表", _charts_by_category(charts, "audit")),
        ]:
            if not grouped:
                continue
            lines.append(heading)
            lines.append("")
            for chart in grouped:
                title = str(chart.get("title") or chart.get("chart_id") or "图表")
                output_path = str(chart.get("output_path") or "")
                if output_path:
                    lines.append(f"![{title}]({output_path})")
                    lines.append("")
                else:
                    lines.append(f"- {title}")
    return base + "\n\n" + "\n".join(lines).rstrip() + "\n"


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
        for heading, grouped in [
            ("研报图表", _charts_by_category(charts, "report")),
            ("审计附录图表", _charts_by_category(charts, "audit")),
        ]:
            if not grouped:
                continue
            parts.append(f"<h3>{escape(heading)}</h3>")
            for chart in grouped:
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


def _charts_by_category(charts: List[Dict[str, Any]], category: str) -> List[Dict[str, Any]]:
    return [
        chart
        for chart in charts
        if isinstance(chart, dict)
        and str(chart.get("chart_category") or ("audit" if str(chart.get("title", "")).startswith("附录：") else "report")) == category
    ]
