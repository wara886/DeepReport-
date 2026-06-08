"""Report post-processing for charts and richer HTML."""

from __future__ import annotations

from html import escape
import re
from typing import Any, Dict, List


CHARTS_HEADER = "## 图表"


def attach_charts_to_markdown(markdown: str, charts: List[Dict[str, Any]]) -> str:
    charts = _visible_charts(charts)
    base = _strip_markdown_charts(markdown).rstrip()
    if not charts:
        return base + ("\n" if base else "")

    lines = [CHARTS_HEADER, ""]
    for chart in charts:
        title = str(chart.get("title") or chart.get("chart_id") or "图表")
        output_path = str(chart.get("output_path") or "")
        web_path = _chart_path_to_web_url(output_path)
        if web_path:
            lines.append(f"![{title}]({web_path})")
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
    charts = _visible_charts(charts)
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
    charts = _visible_charts(charts)
    if not charts or _has_interactive_charts(html):
        return html

    block = render_chart_html(charts)
    if not block:
        return html
    if "</body>" in html:
        return html.replace("</body>", block + "\n</body>")
    return html.rstrip() + "\n" + block + "\n"


def render_chart_html(charts: List[Dict[str, Any]]) -> str:
    charts = _visible_charts(charts)
    if not charts:
        return ""

    parts = ['<section class="report-charts"><h2>图表</h2>']
    for chart in charts:
        title = escape(str(chart.get("title") or chart.get("chart_id") or "图表"))
        output_path = str(chart.get("output_path") or "")
        web_path = _chart_path_to_web_url(output_path)
        safe_path = escape(web_path, quote=True)
        parts.append('<figure class="chart-card">')
        if web_path:
            parts.append(f'<img src="{safe_path}" alt="{title}">')
        parts.append(f"<figcaption>{title}</figcaption>")
        parts.append("</figure>")
    parts.append("</section>")
    return "\n".join(parts)


def _visible_charts(charts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        chart
        for chart in charts
        if isinstance(chart, dict)
        and chart.get("diagnostic_only") is not True
        and str(chart.get("chart_id") or "") not in {"claim_confidence_bar", "evidence_source_mix"}
    ]


def _has_interactive_charts(html: str) -> bool:
    return any(
        marker in html
        for marker in (
            "chartPayloads",
            "data-chart-tab=",
            "data-chart-pane=",
            "交互图表",
            "Interactive Charts",
        )
    )


def _chart_path_to_web_url(path: str) -> str:
    """Convert a filesystem chart path to an absolute web artifact URL.

    The web_ui serves artifacts at ``/artifacts/<relative_path>``.  Charts are
    stored under ``data/outputs_user/runs/{run_id}/outputs/charts/`` on disk,
    but the report HTML is served from a different directory tree
    (``data/reports_user/runs/{run_id}/reports/report.html``).  A bare
    filesystem-relative path like ``data\\outputs_user\\runs\\{id}\\outputs\\
    charts\\file.png`` would resolve to the wrong place when the browser
    fetches it relative to the report URL.

    This function produces an absolute artifact URL:
    ``/artifacts/runs/{id}/outputs/charts/<file>``
    so the web_ui's ``_send_artifact`` handler strips ``/artifacts/`` and
    resolves via ``output_root / "runs/{id}/outputs/charts/file.png"``.

    If the path doesn't match the expected ``runs/…/outputs/charts`` pattern
    the original value is returned unchanged.
    """
    posix = path.replace("\\", "/")
    match = re.search(r"runs/[^/]+/outputs/charts/[^/]+\.png$", posix)
    if match:
        return "/artifacts/" + match.group(0)
    return path


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
