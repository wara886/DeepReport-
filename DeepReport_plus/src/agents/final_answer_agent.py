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
        claims = _claim_dicts(task.parameters.get("claims", []))
        evidence_records = task.parameters.get("evidence_records", [])
        topic = str(task.parameters.get("research_topic", task.description))
        max_claims = int(task.parameters.get("max_claims", 20) or 20)
        max_evidence = int(task.parameters.get("max_evidence", 12) or 12)
        evidence_content_limit = int(task.parameters.get("evidence_content_limit", 600) or 600)
        revision_request = str(task.parameters.get("revision_request", "")).strip()
        verification_report = task.parameters.get("verification_report", {})
        prior_markdown = str(task.parameters.get("prior_markdown", ""))
        conversation_brief = str(task.parameters.get("conversation_brief", "")).strip()

        claims, claim_pack_meta = pack_claims(
            claims,
            max_items=max_claims,
            text_limit=320,
            total_chars=int(task.parameters.get("claim_context_chars", 3200) or 3200),
        )
        prioritized_evidence_ids = _collect_prioritized_evidence_ids(claims)
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
        }

        markdown = render_markdown_report(claims=claims, charts=[])
        summary = f"已为“{topic}”生成包含 {len(claims)} 条核心结论的研究报告。"
        if self.model and claims:
            try:
                payload = self.model.generate_json(
                    prompt=_build_final_prompt(
                        topic=topic,
                        claims=claims,
                        evidence_records=evidence_records,
                        revision_request=revision_request,
                        verification_report=verification_report if isinstance(verification_report, dict) else {},
                        prior_markdown=prior_markdown,
                        conversation_brief=conversation_brief,
                    ),
                    system_prompt=FINAL_ANSWER_SYSTEM_PROMPT,
                    extra_body={"max_tokens": int(task.parameters.get("max_tokens", 2200) or 2200)},
                )
                if isinstance(payload.get("markdown"), str) and payload["markdown"].strip():
                    markdown = normalize_report_headings(payload["markdown"].strip())
                    summary = str(payload.get("summary") or summary)
                    metadata["llm_used"] = True
                    metadata["citation_count"] = int(payload.get("citation_count", 0) or 0)
            except Exception as exc:
                metadata["llm_error"] = str(exc)

        markdown = normalize_report_headings(markdown)
        markdown = enforce_claim_sections(markdown=markdown, claims=claims)
        html = _markdown_to_simple_html(markdown, title=topic)
        report_json = {
            "title": topic,
            "summary": summary,
            "claim_count": len(claims),
            "evidence_count": len(evidence_records) if isinstance(evidence_records, list) else 0,
            "claims": claims,
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
            output.append(item)
    return output


def _build_final_prompt(
    topic: str,
    claims: List[Dict[str, Any]],
    evidence_records: Any,
    revision_request: str = "",
    verification_report: Dict[str, Any] | None = None,
    prior_markdown: str = "",
    conversation_brief: str = "",
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
    prompt = [
        f"Research topic: {topic}",
        f"Claims: {json.dumps(compact_claims, ensure_ascii=False)}",
        f"Evidence: {json.dumps(compact_evidence, ensure_ascii=False)}",
        (
            "Write the report in Chinese. Use exactly these Markdown section headers: "
            "执行摘要, 业务概览, 股权结构与公司治理, 战略与主营业务, 三表摘要, 财务分析, "
            "同行对比, 估值观察, 估值敏感性, 风险评估, 投资结论."
        ),
    ]
    if conversation_brief:
        prompt.insert(1, f"Conversation memory:\n{conversation_brief}")
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
        "风险评估": "风险评估",
        "结论": "投资结论",
        "投资结论": "投资结论",
    }
    output_lines = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            raw_title = match.group(2).strip()
            normalized = heading_map.get(raw_title.lower()) or heading_map.get(raw_title)
            if normalized:
                output_lines.append(f"## {normalized}")
                continue
        output_lines.append(line)
    output = "\n".join(output_lines)
    if not output.lstrip().startswith("# "):
        output = "# 金融研究报告\n\n" + output.lstrip()
    return output


def enforce_claim_sections(markdown: str, claims: List[Dict[str, Any]]) -> str:
    """Make structured claim sections authoritative after optional LLM drafting."""

    claims_by_section: Dict[str, List[Dict[str, Any]]] = {}
    for claim in claims:
        section = str(claim.get("section_name") or "").strip()
        if section:
            claims_by_section.setdefault(section, []).append(claim)
    if not claims_by_section:
        return markdown

    title_by_section = {item["section_name"]: item["section_title"] for item in default_company_outline()}
    section_by_title = {title: section for section, title in title_by_section.items()}
    lines = markdown.splitlines()
    output: List[str] = []
    index = 0
    replaced_sections: set[str] = set()
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if not match:
            output.append(line)
            index += 1
            continue
        title = match.group(1).strip()
        section = section_by_title.get(title)
        if section in claims_by_section:
            output.append(f"## {title}")
            output.append("")
            output.extend(_claim_bullets(claims_by_section[section]))
            replaced_sections.add(section)
            index += 1
            while index < len(lines) and not re.match(r"^##\s+.+?\s*$", lines[index]):
                index += 1
            continue
        output.append(line)
        index += 1

    for section, section_claims in claims_by_section.items():
        if section in replaced_sections:
            continue
        title = title_by_section.get(section)
        if not title:
            continue
        if output and output[-1].strip():
            output.append("")
        output.append(f"## {title}")
        output.append("")
        output.extend(_claim_bullets(section_claims))
    return "\n".join(output).strip() + "\n"


def _claim_bullets(claims: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for item in claims:
        text = str(item.get("claim_text") or "").strip()
        if not text:
            continue
        lines.append(f"- {text}")
        evidence_ids = item.get("evidence_ids", [])
        if isinstance(evidence_ids, list) and evidence_ids:
            lines.append(f"  - 证据ID: {', '.join(str(value) for value in evidence_ids if str(value))}")
        try:
            confidence = float(item.get("confidence", 0.0) or 0.0)
            lines.append(f"  - 置信度: {confidence:.2f}")
        except (TypeError, ValueError):
            pass
    if not lines:
        lines.append("- 本节暂无可验证结论。")
    lines.append("")
    return lines


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
