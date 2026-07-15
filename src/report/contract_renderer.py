"""Contract-based section renderer: renders report sections from SectionEvidenceContracts
instead of letting the LLM freely compose from global evidence.

Deterministic sections (business_overview, governance, strategy, risk, etc.) are
rendered from contract facts. The LLM is only used for sections where allow_llm_rewrite=True.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.report.section_contracts import (
    ReportSectionContracts,
    SectionEvidenceContract,
    SECTION_TITLES,
)


def render_section_from_contract(contract: SectionEvidenceContract) -> str:
    """Render a single section from its contract."""
    if contract.status == "gap":
        if contract.deterministic_text and len(contract.deterministic_text.strip()) > 30:
            return contract.deterministic_text.strip()
        return _render_gap_section(contract)

    if contract.status == "fallback":
        return _render_fallback_section(contract)

    parts: List[str] = []
    if contract.deterministic_text:
        parts.append(contract.deterministic_text)

    fact_paragraphs = _render_facts_as_prose(contract)
    if fact_paragraphs:
        parts.append(fact_paragraphs)

    if contract.peer_groups:
        pg_text = _render_peer_groups(contract)
        if pg_text:
            parts.append(pg_text)

    if contract.status == "partial" and contract.blocked_reasons:
        reasons = "；".join(contract.blocked_reasons)
        parts.append(f"注：本节部分内容受限，{reasons}")

    result = "\n\n".join(parts)
    return result.strip() if result else _render_gap_section(contract)


def render_section_to_markdown(contract: SectionEvidenceContract) -> str:
    """Render a full section heading + body as markdown."""
    heading = SECTION_TITLES.get(contract.section_key, contract.section_key)
    body = render_section_from_contract(contract)
    return f"## {heading}\n\n{body}"


def render_sections_to_markdown(contracts: ReportSectionContracts) -> str:
    """Render all non-gap sections to markdown."""
    sections: List[str] = []
    for sk in SECTION_TITLES:
        contract = contracts.get(sk)
        if not contract:
            continue
        sections.append(render_section_to_markdown(contract))
    return "\n\n".join(sections)


def render_diagnostic_contract_inputs(contracts: ReportSectionContracts) -> str:
    """Render a compact form of all contracts for LLM context injection."""
    inputs: List[str] = []
    for contract in contracts.contracts.values():
        if not contract.render_policy.get("allow_llm_rewrite", False):
            continue
        inputs.append(_render_llm_contract_brief(contract))
    return "\n".join(inputs)


def render_section_contract_inputs(contracts: ReportSectionContracts, section_key: str) -> str:
    """Render only the current section and its required deterministic dependencies."""

    dependency_map = {
        "executive_summary": ["executive_summary", "three_statement_summary", "valuation", "risk_factors"],
        "financial_analysis": ["financial_analysis", "three_statement_summary"],
    }
    keys = dependency_map.get(section_key, [section_key])
    return "\n".join(
        _render_llm_contract_brief(contract)
        for key in keys
        for contract in [contracts.get(key)]
        if contract is not None
    )


def _render_llm_contract_brief(contract: SectionEvidenceContract) -> str:
    """Compact contract brief for LLM-rewrite sections."""
    parts = [f"--- {contract.title} ---", f"状态: {contract.status}"]
    for fact in contract.facts:
        parts.append(f"- {fact.fact_type}: {fact.text[:200]}")
    if contract.deterministic_text:
        parts.append(f"[确定性文本]: {contract.deterministic_text[:200]}")
    return "\n".join(parts)


def _render_gap_section(contract: SectionEvidenceContract) -> str:
    """Render a gap section with clear blocked reasons."""
    reasons = contract.blocked_reasons or ["evidence_not_available"]
    reason_text = "；".join(reasons)
    return f"本节暂不展开详细分析（{reason_text}）。"


def _render_fallback_section(contract: SectionEvidenceContract) -> str:
    """Render a fallback section with source disclosure."""
    parts: List[str] = []
    if contract.deterministic_text:
        parts.append(contract.deterministic_text)
    for fact in contract.facts:
        if fact.text:
            parts.append(fact.text[:500])
    if contract.blocked_reasons:
        parts.append(f"（注：本节为补充性说明，受限原因：{'；'.join(contract.blocked_reasons)}。）")
    return "\n\n".join(parts) if parts else "（本节信息暂缺）"


def _render_facts_as_prose(contract: SectionEvidenceContract) -> str:
    """Render facts into readable prose paragraphs by grouping by fact_type."""
    if contract.section_key in {"three_statement_summary", "financial_analysis", "peer_compare"} and contract.deterministic_text:
        return ""
    grouped: Dict[str, List[str]] = {}
    for fact in contract.facts:
        if _is_raw_metric_fact(fact.text):
            continue
        if fact.text and len(fact.text.strip()) > 5:
            grouped.setdefault(fact.fact_type, []).append(fact.text.strip())
    paragraphs: List[str] = []
    for _, texts in grouped.items():
        combined = "；".join(texts[:3])
        if len(combined) > 5:
            paragraphs.append(combined)
    return "\n\n".join(paragraphs) if paragraphs else ""


def _is_raw_metric_fact(text: str) -> bool:
    value = str(text or "").strip()
    raw_keys = ("revenue:", "net_income:", "total_assets:", "total_liabilities:", "operating_cash_flow:", "free_cash_flow:")
    return any(key in value for key in raw_keys) or bool(re.search(r"^[a-z_]+:\\s*[-+]?\\d", value))


def _render_peer_groups(contract: SectionEvidenceContract) -> str:
    """Render peer groups summary."""
    lines: List[str] = []
    for group in contract.peer_groups:
        if hasattr(group, "description") and group.description:
            lines.append(f"- {group.description}：{', '.join(group.symbols[:8])}")
    if not lines:
        for group in contract.peer_groups:
            label = "可比公司" if group.group_label == "direct_competitor" else "跨市场参考组"
            lines.append(f"- {label}：{', '.join(group.symbols[:8])}")
    return "\n".join(lines) if lines else ""


def render_full_report_from_contracts(
    contracts: ReportSectionContracts,
    title: str = "金融研究报告",
    top_blockers: Optional[List[str]] = None,
) -> str:
    """Render a complete report markdown from contracts."""
    sections: List[str] = [f"# {title}"]
    for sk in SECTION_TITLES:
        contract = contracts.get(sk)
        if not contract:
            continue
        sections.append(render_section_to_markdown(contract))
    return "\n\n".join(sections)
