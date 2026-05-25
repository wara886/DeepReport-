"""Markdown report template renderer."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from src.templates.company_outline import default_company_outline


def render_markdown_report(
    claims: List[dict],
    charts: List[dict] | None = None,
    title: str = "金融研究报告",
) -> str:
    charts = charts or []
    by_section: Dict[str, List[dict]] = defaultdict(list)
    for claim in claims:
        by_section[str(claim.get("section_name", "unknown"))].append(claim)

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("由 FinSight 多智能体金融研报系统生成。")
    lines.append("")

    for section in default_company_outline():
        name = section["section_name"]
        title = section["section_title"]
        lines.append(f"## {title}")
        lines.append("")
        section_claims = by_section.get(name, [])
        if not section_claims:
            lines.append("- 本节暂无可验证结论。")
            lines.append("")
            continue

        for item in section_claims:
            claim_text = str(item.get("claim_text", "")).strip()
            confidence = float(item.get("confidence", 0.0))
            evidence_ids = list(item.get("evidence_ids", []))
            lines.append(f"- {claim_text}")
            if evidence_ids:
                lines.append(f"  - 证据ID: {', '.join(evidence_ids)}")
            lines.append(f"  - 置信度: {confidence:.2f}")
        lines.append("")

    lines.append("## 图表")
    lines.append("")
    if charts:
        for chart in charts:
            lines.append(f"- {chart.get('title', 'Untitled')}: `{chart.get('output_path', '')}`")
    else:
        lines.append("- 暂无图表。")
    lines.append("")

    return "\n".join(lines)
