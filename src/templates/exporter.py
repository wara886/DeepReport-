"""Final report exporter for Stage 10 outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from src.templates.html_template import render_html_report
from src.templates.markdown_template import render_markdown_report


def _read_json(path: str | Path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def export_reports(
    claim_path: str | Path = "data/outputs/claim_table.json",
    chart_meta_path: str | Path = "data/outputs/chart_metadata.json",
    report_dir: str | Path = "data/reports",
) -> Dict[str, str]:
    claims: List[dict] = list(_read_json(claim_path))
    charts: List[dict] = []
    cm = Path(chart_meta_path)
    if cm.exists():
        charts = list(_read_json(cm))

    markdown = render_markdown_report(claims=claims, charts=charts)
    html = render_html_report(claims=claims, charts=charts)
    report_json = {
        "title": "Company Research Report",
        "claim_count": len(claims),
        "chart_count": len(charts),
        "claims": claims,
        "charts": charts,
    }

    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "report.md"
    html_path = out_dir / "report.html"
    json_path = out_dir / "report.json"

    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps(report_json, indent=2), encoding="utf-8")

    return {
        "report_md": str(md_path),
        "report_html": str(html_path),
        "report_json": str(json_path),
    }

