"""FinalAnswerAgent for report generation."""

from __future__ import annotations

from html import escape
import json
import re
from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.agents.context_packer import build_revision_brief, pack_claims, pack_evidence_records, pack_markdown_excerpt
from src.models import ModelAdapter
from src.schemas.claim import ClaimItem
from src.templates.company_outline import default_company_outline
from src.templates.markdown_template import render_markdown_report


FINAL_ANSWER_SYSTEM_PROMPT = """You are FinalAnswerAgent in a financial research multi-agent system.
Write a concise Chinese investment research report from provided claims and evidence.
Use citations like [evidence_id] after factual claims.
Do not invent numbers, sources, or unsupported conclusions.
Return only valid JSON:
{"markdown":"# ...","summary":"...","citation_count":3}
"""


class FinalAnswerAgent(BaseAgent):
    """Generate final Markdown/HTML/JSON report payloads."""

    def __init__(self, model: ModelAdapter | None = None, tools: Dict[str, Any] | None = None):
        super().__init__(name="FinalAnswerAgent", model=model, tools=tools)

    def get_capabilities(self) -> List[str]:
        return [
            "write citation-backed financial research reports",
            "produce markdown, html, and report json artifacts",
            "summarize multi-agent outputs into a final answer",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        all_claims = _claim_dicts(task.parameters.get("claims", []))
        evidence_records = task.parameters.get("evidence_records", [])
        topic = str(task.parameters.get("research_topic", task.description))
        max_claims = int(task.parameters.get("max_claims", 30) or 30)
        max_evidence = int(task.parameters.get("max_evidence", 12) or 12)
        evidence_content_limit = int(task.parameters.get("evidence_content_limit", 600) or 600)
        revision_request = str(task.parameters.get("revision_request", "")).strip()
        verification_report = task.parameters.get("verification_report", {})
        prior_markdown = str(task.parameters.get("prior_markdown", ""))
        conversation_brief = str(task.parameters.get("conversation_brief", "")).strip()
        skill_brief = str(task.parameters.get("skill_brief", "")).strip()
        rating = str(task.parameters.get("rating", "")).strip()
        symbol = str(task.parameters.get("symbol", "")).strip().upper()

        prompt_claims, claim_pack_meta = pack_claims(
            all_claims,
            max_items=max_claims,
            text_limit=400,
            total_chars=int(task.parameters.get("claim_context_chars", 6000) or 6000),
        )
        prioritized_evidence_ids = _collect_prioritized_evidence_ids(prompt_claims)
        evidence_records, evidence_pack_meta = pack_evidence_records(
            evidence_records if isinstance(evidence_records, list) else [],
            prioritized_evidence_ids=prioritized_evidence_ids,
            max_items=max_evidence,
            content_limit=evidence_content_limit,
            total_chars=int(task.parameters.get("evidence_context_chars", 5600) or 5600),
        )
        metadata: Dict[str, Any] = {
            "llm_used": False,
            "claim_pack_meta": claim_pack_meta,
            "evidence_pack_meta": evidence_pack_meta,
            "revision_requested": bool(revision_request),
            "conversation_brief_chars": len(conversation_brief),
            "skill_brief_chars": len(skill_brief),
        }

        markdown = render_markdown_report(claims=all_claims, charts=[])
        summary = f"已为“{topic}”生成包含 {len(all_claims)} 条核心结论的研究报告。"
        if self.model and prompt_claims:
            try:
                payload = self.model.generate_json(
                    prompt=_build_final_prompt(
                        topic=topic,
                        claims=prompt_claims,
                        evidence_records=evidence_records,
                        revision_request=revision_request,
                        verification_report=verification_report if isinstance(verification_report, dict) else {},
                        prior_markdown=prior_markdown,
                        conversation_brief=conversation_brief,
                        skill_brief=skill_brief,
                        rating=rating,
                        symbol=symbol,
                    ),
                    system_prompt=FINAL_ANSWER_SYSTEM_PROMPT,
                    extra_body={"max_tokens": int(task.parameters.get("max_tokens", 4000) or 4000)},
                )
                if isinstance(payload.get("markdown"), str) and payload["markdown"].strip():
                    markdown = normalize_report_headings(payload["markdown"].strip())
                    summary = str(payload.get("summary") or summary)
                    metadata["llm_used"] = True
                    metadata["citation_count"] = int(payload.get("citation_count", 0) or 0)
            except Exception as exc:
                metadata["llm_error"] = str(exc)

        markdown = normalize_report_headings(markdown)
        markdown = backfill_empty_sections_from_claims(markdown, all_claims)
        markdown = insert_missing_sections_from_claims(markdown, all_claims)
        markdown = normalize_report_headings(markdown)
        html = _markdown_to_simple_html(markdown, title=topic)
        report_json = {
            "title": topic,
            "summary": summary,
            "claim_count": len(all_claims),
            "evidence_count": len(evidence_records) if isinstance(evidence_records, list) else 0,
            "claims": all_claims,
            "evidence_records": evidence_records if isinstance(evidence_records, list) else [],
        }

        return self.success(
            task,
            {"markdown": markdown, "html": html, "report_json": report_json, "summary": summary},
            metadata=metadata,
        )


def _claim_dicts(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    output = []
    for item in raw:
        if isinstance(item, ClaimItem):
            output.append(item.to_dict())
        elif isinstance(item, dict):
            output.append(dict(item))
    return output


def _build_final_prompt(
    topic: str,
    claims: List[Dict[str, Any]],
    evidence_records: Any,
    revision_request: str = "",
    verification_report: Dict[str, Any] | None = None,
    prior_markdown: str = "",
    conversation_brief: str = "",
    skill_brief: str = "",
    rating: str = "",
    symbol: str = "",
) -> str:
    evidence = evidence_records if isinstance(evidence_records, list) else []
    compact_evidence = [
        {
            "evidence_id": item.get("evidence_id"),
            "title": item.get("title"),
            "source_url": item.get("source_url"),
            "source_type": item.get("source_type"),
            "trust_level": item.get("trust_level"),
            "content": str(item.get("content", "")),
            "key_points": item.get("key_points", []),
        }
        for item in evidence
        if isinstance(item, dict)
    ]
    compact_claims = [
        {
            "claim_id": item.get("claim_id"),
            "section_name": item.get("section_name"),
            "claim_text": item.get("claim_text"),
            "evidence_ids": item.get("evidence_ids", []),
            "numeric_values": item.get("numeric_values", {}),
            "confidence": item.get("confidence"),
            "notes": item.get("notes", ""),
        }
        for item in claims
    ]
    revision_brief = revision_request or build_revision_brief(verification_report or {})
    # Extract conclusion claim text to force it into the 投资结论 section
    conclusion_texts = [
        item.get("claim_text", "")
        for item in compact_claims
        if item.get("section_name") == "conclusion" and item.get("claim_text")
    ]
    # Extract valuation claim texts to force them into 估值观察
    valuation_texts = [
        item.get("claim_text", "")
        for item in compact_claims
        if item.get("section_name") in {"valuation", "company_valuation", "valuation_summary"}
        and item.get("claim_text")
    ]
    valuation_sensitivity_texts = [
        item.get("claim_text", "")
        for item in compact_claims
        if item.get("section_name") == "valuation_sensitivity" and item.get("claim_text")
    ]
    earnings_quality_texts = [
        item.get("claim_text", "")
        for item in compact_claims
        if item.get("section_name") == "earnings_quality" and item.get("claim_text")
    ]
    risk_texts = [
        item.get("claim_text", "")
        for item in compact_claims
        if item.get("section_name") == "risks" and item.get("claim_text")
    ]
    peer_texts = [
        item.get("claim_text", "")
        for item in compact_claims
        if item.get("section_name") == "peer_compare" and item.get("claim_text")
    ]
    prompt = [
        f"Research topic: {topic}",
        f"Claims: {json.dumps(compact_claims, ensure_ascii=False)}",
        f"Evidence: {json.dumps(compact_evidence, ensure_ascii=False)}",
        (
            "Write the report in Chinese. Use exactly these Markdown section headers: "
            "执行摘要, 业务概览, 股权结构与公司治理, 战略与主营业务, 三表摘要, 财务分析, "
            "同行对比, 估值观察, 估值敏感性, 风险评估, 投资结论. "
            "IMPORTANT: Use ALL claims provided. Map claim section_names to headers: "
            "valuation→估值观察, valuation_sensitivity→估值敏感性, conclusion→投资结论, "
            "peer_compare→同行对比, financial_statements→三表摘要, financial_analysis→财务分析, "
            "executive_summary→执行摘要, earnings_quality→财务分析. "
            "Never write '本节暂无可验证结论' if a claim exists for that section. "
            "业务概览 must describe the company's actual business profile, sector, industry, products/services, and business model; "
            "do not use debug wording such as '证据覆盖 X 条' as the main business overview. "
            "三表摘要 must include available key line items such as revenue, net income, operating cash flow, free cash flow, assets/equity; "
            "do not leave it empty when these metrics are present in claims. "
            "CRITICAL: The 投资结论 section must ONLY cite evidence from sections that have actual claims. "
            "If the 同行对比 section has no verifiable claims, do NOT say '基于同行比较' in 投资结论. "
            "Only reference dimensions (growth, margin, ROE, peer comparison) that are actually supported by claims in the report. "
            "VALUATION SECTION REQUIREMENTS: "
            "1) In 估值观察, explicitly state the valuation methodology used (e.g. P/B + DDM + P/E for banks, or P/E + P/S + DCF for tech). "
            "2) If the company is a bank or financial institution, explain that P/S and FCF DCF have limited applicability and P/B / DDM are the primary methods. "
            "3) Include the FCF methodology note (e.g. OCF - CapEx - finance lease payments) if present in claims. "
            "4) If non-recurring items (tax benefits, restructuring, impairment) are present in claims, mention them in 财务分析 and note their impact on earnings quality. "
            "5) For ROE, always note whether it is simplified-annualized or official company-disclosed, and that the two may differ by 1-2pct."
        ),
    ]
    if conclusion_texts:
        prompt.append(
            f"The 投资结论 section MUST include this conclusion: {conclusion_texts[0]}"
        )
    if valuation_texts:
        prompt.append(
            f"CRITICAL: The 估值观察 section MUST include ALL of the following valuation claims verbatim: "
            + " | ".join(valuation_texts)
        )
    if valuation_sensitivity_texts:
        prompt.append(
            f"CRITICAL: The 估值敏感性 section MUST include: {valuation_sensitivity_texts[0]}"
        )
    if risk_texts:
        prompt.append(
            f"CRITICAL: The 风险评估 section MUST include ALL of the following risk claims verbatim: "
            + " | ".join(risk_texts)
        )
    if peer_texts:
        prompt.append(
            f"CRITICAL: The 同行对比 section MUST include ALL of the following peer comparison claims verbatim: "
            + " | ".join(peer_texts)
        )
    if earnings_quality_texts:
        prompt.append(
            f"CRITICAL: The 财务分析 section MUST include this earnings quality note: {earnings_quality_texts[0]}"
        )
    if conversation_brief:
        prompt.insert(1, f"Conversation memory:\n{conversation_brief}")
    if skill_brief:
        prompt.insert(1, f"Relevant skill brief:\n{skill_brief}")
    if rating and symbol:
        prompt.append(
            f"Investment rating determined: {rating}. "
            f"In the 投资结论 section, you MUST end with an explicit sentence: "
            f"基于以上分析，维持/给予 {symbol}「{rating}」评级。"
        )
    elif rating:
        prompt.append(
            f"Investment rating determined: {rating}. "
            f"In the 投资结论 section, you MUST end with an explicit sentence stating the {rating} rating."
        )
    if revision_brief:
        prompt.append(f"Revision instructions:\n{revision_brief}")
    if prior_markdown.strip():
        prompt.append(f"Previous draft excerpt:\n{pack_markdown_excerpt(prior_markdown, max_chars=1800)}")
    return "\n".join(prompt)


def _collect_prioritized_evidence_ids(claims: List[Dict[str, Any]]) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()
    for item in claims:
        evidence_ids = item.get("evidence_ids", [])
        if not isinstance(evidence_ids, list):
            continue
        for evidence_id in evidence_ids:
            key = str(evidence_id)
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def normalize_report_headings(markdown: str) -> str:
    heading_map = {
        "executive summary": "执行摘要",
        "business overview": "业务概览",
        "business overview / company context": "业务概览",
        "ownership governance": "股权结构与公司治理",
        "ownership and governance": "股权结构与公司治理",
        "corporate governance": "股权结构与公司治理",
        "strategy business": "战略与主营业务",
        "strategy and business": "战略与主营业务",
        "business strategy": "战略与主营业务",
        "financial statements": "三表摘要",
        "three statement summary": "三表摘要",
        "financial analysis": "财务分析",
        "peer comparison": "同行对比",
        "peer compare": "同行对比",
        "valuation": "估值观察",
        "valuation analysis": "估值观察",
        "valuation sensitivity": "估值敏感性",
        "sensitivity analysis": "估值敏感性",
        "risk assessment": "风险评估",
        "risks": "风险评估",
        "risk": "风险评估",
        "risk factors": "风险评估",
        "conclusion": "投资结论",
        "执行摘要": "执行摘要",
        "业务概述": "业务概览",
        "业务概览": "业务概览",
        "股权结构": "股权结构与公司治理",
        "公司治理": "股权结构与公司治理",
        "股权结构与公司治理": "股权结构与公司治理",
        "战略": "战略与主营业务",
        "主营业务": "战略与主营业务",
        "战略与主营业务": "战略与主营业务",
        "三表摘要": "三表摘要",
        "三表分析": "三表摘要",
        "财务分析": "财务分析",
        "同行对比": "同行对比",
        "估值": "估值观察",
        "估值观察": "估值观察",
        "估值分析": "估值观察",
        "估值敏感性": "估值敏感性",
        "敏感性分析": "估值敏感性",
        "估值敏感性分析": "估值敏感性",
        "风险评估": "风险评估",
        "风险因素": "风险评估",
        "风险分析": "风险评估",
        "结论": "投资结论",
        "投资结论": "投资结论",
        "投资建议": "投资结论",
        "投资评级": "投资结论",
        "同行业对比": "同行对比",
        "同行比较": "同行对比",
        "财务报表摘要": "三表摘要",
        "财务摘要": "三表摘要",
        "主营业务与战略": "战略与主营业务",
        "公司概况": "业务概览",
        "投资摘要": "执行摘要",
    }
    output_lines = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            raw_title = match.group(2).strip()
            # Strip Chinese numbering prefix like "一、", "二、", "十一、" etc.
            clean_title = re.sub(r"^[一二三四五六七八九十百]+[、．.]\s*", "", raw_title).strip()
            normalized = (
                heading_map.get(raw_title.lower())
                or heading_map.get(raw_title)
                or heading_map.get(clean_title.lower())
                or heading_map.get(clean_title)
            )
            if normalized:
                output_lines.append(f"## {normalized}")
                continue
        output_lines.append(line)
    output = "\n".join(output_lines)
    if not output.lstrip().startswith("# "):
        output = "# 金融研究报告\n\n" + output.lstrip()
    return output


def backfill_empty_sections_from_claims(markdown: str, claims: List[Dict[str, Any]]) -> str:
    """Replace empty placeholder sections with structured claims the model omitted."""
    if not claims:
        return markdown
    outline_titles = {item["section_name"]: item["section_title"] for item in default_company_outline()}
    title_aliases = {
        "executive_summary": "执行摘要",
        "business_overview": "业务概览",
        "ownership_governance": "股权结构与公司治理",
        "strategy_business": "战略与主营业务",
        "financial_statements": "三表摘要",
        "financial_analysis": "财务分析",
        "peer_compare": "同行对比",
        "valuation": "估值观察",
        "valuation_sensitivity": "估值敏感性",
        "risks": "风险评估",
        "conclusion": "投资结论",
    }
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for claim in claims:
        if isinstance(claim, dict):
            section = str(claim.get("section_name") or "")
            if section:
                by_section.setdefault(section, []).append(claim)
    output = markdown
    for section, section_claims in by_section.items():
        replacement = _claims_to_markdown_bullets(section_claims)
        if not replacement:
            continue
        for title in [title_aliases.get(section, ""), outline_titles.get(section, "")]:
            if not title:
                continue
            output = _replace_empty_section(output, title=title, replacement=replacement)
    return output


def insert_missing_sections_from_claims(markdown: str, claims: List[Dict[str, Any]]) -> str:
    """Insert deterministic section blocks when the model omits required claim headers."""
    if not claims:
        return markdown
    outline_titles = {item["section_name"]: item["section_title"] for item in default_company_outline()}
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        section = str(claim.get("section_name") or "").strip()
        if section and section in outline_titles:
            by_section.setdefault(section, []).append(claim)

    missing_blocks: List[str] = []
    for item in default_company_outline():
        section = item["section_name"]
        title = outline_titles.get(section, "")
        section_claims = by_section.get(section, [])
        if not title or not section_claims:
            continue
        if re.search(rf"(?m)^##\s+{re.escape(title)}\s*$", markdown):
            continue
        replacement = _claims_to_markdown_bullets(section_claims)
        if replacement:
            missing_blocks.append(f"## {title}\n\n{replacement.rstrip()}")

    if not missing_blocks:
        return markdown
    insertion = "\n\n".join(missing_blocks).rstrip()
    return markdown.rstrip() + "\n\n" + insertion + "\n"


def _replace_empty_section(markdown: str, title: str, replacement: str) -> str:
    header_pattern = re.compile(rf"(?m)^##\s+{re.escape(title)}\s*$")
    match = header_pattern.search(markdown)
    if not match:
        return markdown
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    section_end = match.end() + next_header.start() if next_header else len(markdown)
    section_body = markdown[match.end():section_end]
    if not _section_is_empty_placeholder(section_body):
        return markdown
    new_body = "\n\n" + replacement.rstrip() + "\n\n"
    return markdown[:match.end()] + new_body + markdown[section_end:].lstrip("\n")


def _section_is_empty_placeholder(section_body: str) -> bool:
    cleaned = "\n".join(line.strip() for line in section_body.strip().splitlines() if line.strip())
    if not cleaned:
        return True
    placeholder_markers = [
        "本节暂无可验证结论",
        "暂无可验证结论",
        "no verifiable conclusion",
        "no verifiable claims",
    ]
    lowered = cleaned.lower()
    return any(marker in lowered for marker in placeholder_markers)


def _claims_to_markdown_bullets(claims: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for claim in claims:
        text = str(claim.get("claim_text") or "").strip()
        if not text:
            continue
        lines.append(f"- {text}")
        evidence_ids = [str(item) for item in claim.get("evidence_ids", []) if str(item)]
        if evidence_ids:
            lines.append(f"  - 证据ID: {', '.join(evidence_ids)}")
        try:
            confidence = float(claim.get("confidence", 0.0) or 0.0)
            lines.append(f"  - 置信度: {confidence:.2f}")
        except (TypeError, ValueError):
            pass
    return "\n".join(lines)


def _markdown_to_simple_html(markdown: str, title: str) -> str:
    lines = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            lines.append(f"<h1>{escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{escape(line[3:].strip())}</h2>")
        elif line.startswith("- "):
            lines.append(f"<li>{escape(line[2:].strip())}</li>")
        elif line.strip():
            lines.append(f"<p>{escape(line)}</p>")
        else:
            lines.append("")
    body = "\n".join(lines)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Arial, "PingFang SC", "Microsoft YaHei", sans-serif; margin: 28px; line-height: 1.65; color: #172026; }}
    h1, h2 {{ margin: 18px 0 8px; }}
    li {{ margin: 6px 0; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""
