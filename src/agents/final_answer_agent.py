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
        period = str(task.parameters.get("period", "")).strip().upper()
        tables = task.parameters.get("tables", [])
        financial_metrics = task.parameters.get("financial_metrics", {})
        pdf_sections = task.parameters.get("pdf_sections", [])
        company_profile = task.parameters.get("company_profile", {})
        research_blackboard = task.parameters.get("research_blackboard", {})
        pre_write_critic = task.parameters.get("pre_write_critic", {})
        degraded_report = bool(task.parameters.get("degraded_report", False))
        pre_write_rework_history = task.parameters.get("pre_write_rework_history", [])
        quality_remediation_plan = _normalize_quality_remediation_plan(
            task.parameters.get("quality_remediation_plan")
            or task.parameters.get("remediation_plan")
            or task.parameters.get("quality_feedback")
        )
        repair_constraints = _normalize_repair_constraints(
            task.parameters.get("repair_constraints")
            or task.parameters.get("gap_repair_constraints")
            or quality_remediation_plan.get("repair_constraints")
        )
        all_claims = _filter_reportable_claims(all_claims, financial_metrics)

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
            "quality_remediation_used": bool(quality_remediation_plan.get("quality_feedback_used")),
            "repair_constraints_used": bool(repair_constraints),
            "table_context_count": len(tables) if isinstance(tables, list) else 0,
            "financial_metric_context_count": len(financial_metrics) if isinstance(financial_metrics, dict) else 0,
            "pdf_section_context_count": len(pdf_sections) if isinstance(pdf_sections, list) else 0,
            "company_profile_context_used": bool(company_profile),
            "research_blackboard_used": isinstance(research_blackboard, dict) and bool(research_blackboard),
            "pre_write_critic_objection_count": len(pre_write_critic.get("objections", []))
            if isinstance(pre_write_critic, dict)
            else 0,
            "degraded_report": degraded_report,
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
                        period=period,
                        quality_remediation_plan=quality_remediation_plan,
                        repair_constraints=repair_constraints,
                        tables=tables,
                        financial_metrics=financial_metrics,
                        pdf_sections=pdf_sections,
                        company_profile=company_profile,
                        research_blackboard=research_blackboard,
                        pre_write_critic=pre_write_critic,
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
        markdown = hard_backfill_quality_sections(markdown, all_claims, quality_remediation_plan, repair_constraints)
        markdown = enforce_verified_financial_sections(markdown, all_claims, financial_metrics, tables)
        markdown = backfill_role_output_sections(markdown, research_blackboard)
        markdown = ensure_period_disclosure(markdown, period, evidence_records, tables, financial_metrics)
        if degraded_report:
            markdown = _append_degraded_report_note(markdown, pre_write_critic, pre_write_rework_history)
        markdown = normalize_report_headings(markdown)
        html = _markdown_to_simple_html(markdown, title=topic)
        report_json = {
            "title": topic,
            "summary": summary,
            "claim_count": len(all_claims),
            "evidence_count": len(evidence_records) if isinstance(evidence_records, list) else 0,
            "claims": all_claims,
            "evidence_records": evidence_records if isinstance(evidence_records, list) else [],
            "research_blackboard": research_blackboard if isinstance(research_blackboard, dict) else {},
            "pre_write_critic": pre_write_critic if isinstance(pre_write_critic, dict) else {},
            "degraded_report": degraded_report,
            "pre_write_rework_history": pre_write_rework_history if isinstance(pre_write_rework_history, list) else [],
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


def _filter_reportable_claims(claims: List[Dict[str, Any]], financial_metrics: Any = None) -> List[Dict[str, Any]]:
    """Remove diagnostic or unsupported fallback claims before final writing."""

    metrics = financial_metrics if isinstance(financial_metrics, dict) else {}
    has_metric_lineage = int(metrics.get("metric_count", 0) or 0) > 0
    output: List[Dict[str, Any]] = []
    for claim in claims:
        section = str(claim.get("section_name") or "")
        text = str(claim.get("claim_text") or "")
        notes = str(claim.get("notes") or "")
        numeric_values = claim.get("numeric_values", {}) if isinstance(claim.get("numeric_values"), dict) else {}
        combined = f"{text} {notes}".lower()
        if set(numeric_values.keys()).issubset({"evidence_count", "unique_sources"}) and numeric_values:
            continue
        if any(marker in combined for marker in ["evidence coverage", "coverage statistics"]):
            continue
        if "证据覆盖" in text or "璇佹嵁瑕嗙洊" in text:
            continue
        if not has_metric_lineage and section in {"valuation", "valuation_sensitivity"}:
            unsupported_numeric = bool(numeric_values)
            if unsupported_numeric:
                continue
        if not has_metric_lineage and section == "conclusion" and any(
            marker in combined
            for marker in [
                "valuation",
                "recommendation",
                "model conclusion",
                "中性观察",
                "涓€ц瀵",
            ]
        ):
            continue
        output.append(claim)
    return output


def _append_degraded_report_note(markdown: str, critic: Any, rework_history: Any) -> str:
    objections = critic.get("objections", []) if isinstance(critic, dict) and isinstance(critic.get("objections"), list) else []
    blocking = [
        item
        for item in objections
        if isinstance(item, dict) and (item.get("blocking") is True or str(item.get("severity", "")).lower() in {"fatal", "blocker"})
    ]
    lines = ["", "## 数据缺口与降级说明"]
    if blocking:
        for item in blocking[:6]:
            lines.append(
                f"- {item.get('field', item.get('category', 'unknown'))}: {item.get('message', '')} "
                f"(责任 Agent: {item.get('target_agent', 'unknown')})"
            )
    else:
        lines.append("- 写作前审议存在未完全消除的限制，正文仅使用已验证事实和已披露缺口。")
    if isinstance(rework_history, list) and rework_history:
        lines.append(f"- 已执行责任 Agent 返工轮次：{len(rework_history)}。")
    return markdown.rstrip() + "\n" + "\n".join(lines) + "\n"


def _compact_blackboard(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    keys = [
        "company_identity",
        "market_route",
        "industry_profile",
        "period_state",
        "coverage",
        "role_outputs",
        "critic",
    ]
    compact: Dict[str, Any] = {}
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict):
            compact[key] = value
    return compact


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
    period: str = "",
    quality_remediation_plan: Dict[str, Any] | None = None,
    repair_constraints: Dict[str, Any] | None = None,
    tables: Any = None,
    financial_metrics: Any = None,
    pdf_sections: Any = None,
    company_profile: Any = None,
    research_blackboard: Any = None,
    pre_write_critic: Any = None,
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
        f"Target report period: {period or 'not specified'}",
        f"Shared research blackboard: {json.dumps(_compact_blackboard(research_blackboard), ensure_ascii=False)}",
        f"Pre-write critic: {json.dumps(pre_write_critic if isinstance(pre_write_critic, dict) else {}, ensure_ascii=False)}",
        f"Claims: {json.dumps(compact_claims, ensure_ascii=False)}",
        f"Evidence: {json.dumps(compact_evidence, ensure_ascii=False)}",
        (
            "Write the report in Chinese financial research prose. "
            "Use exactly these Markdown section headers: "
            "执行摘要, 业务概览, 股权结构与公司治理, 战略与主营业务, 三表摘要, 财务分析, "
            "同行对比, 估值观察, 估值敏感性, 风险评估, 投资结论. "
            "Map claim section_names to headers: "
            "valuation→估值观察, valuation_sensitivity→估值敏感性, conclusion→投资结论, "
            "peer_compare→同行对比, financial_statements→三表摘要, financial_analysis→财务分析, "
            "executive_summary→执行摘要, earnings_quality→财务分析. "
            "For each section, synthesize the provided claims into coherent prose paragraphs "
            "with specific data, analysis, and a conclusion. "
            "Reference evidence_ids in brackets like [ev_123].\n"
            "FORBIDDEN placeholder patterns — never use these: "
            "框架性, 待补, 暂无结论, 暂无可验证结论, 无法判断, "
            "仅给出框架性描述, 缺少可量化, 框架待补, N/A. "
            "If a claim exists for a section, write it as substantive prose with context. "
            "If no claim exists, skip the section entirely rather than writing a placeholder.\n"
            "EXAMPLE of good prose:\n"
            "## 财务分析\n"
            "???????????????????????????????????????? evidence_id?"
            "数据中心业务收入 35.4 亿美元（占比 46%）首次超越客户端业务，成为最大收入来源。"
            "毛利率提升至 52.1%（同比 +1.8pp），受益于高毛利的数据中心 GPU 出货占比提升。"
            "经营现金流 12.3 亿美元，自由现金流 9.8 亿美元，均同比改善。[ev_amd_fin_001]\n"
            "业务概览 must describe the company's actual business: sector, industry, products, "
            "and business model, not debug wording like '证据覆盖 X 条'. "
            "三表摘要 must present key line items (revenue, net income, operating cash flow, "
            "free cash flow, assets/equity) in context. "
            "估值观察 must state the methodology (e.g. P/E + P/S + DCF for tech) "
            "and provide the computed valuation range. "
            "The 投资结论 section must only reference dimensions actually supported by claims."
            "Add a short 数据期间说明 when target report period differs from the latest available disclosure period."
            "Treat the shared research blackboard and pre-write critic as binding constraints: "
            "do not infer industry, business scope, financial data basis, or valuation inputs outside the blackboard/claims/evidence. "
            "If the critic raises an objection, address it in prose using available evidence or clearly state the evidence boundary."
        ),
    ]
    artifact_context = _artifact_context_prompt(
        tables=tables,
        financial_metrics=financial_metrics,
        pdf_sections=pdf_sections,
        company_profile=company_profile,
    )
    if artifact_context:
        prompt.append(artifact_context)
    section_claim_map = {
        "投资结论": conclusion_texts,
        "估值观察": valuation_texts,
        "估值敏感性": valuation_sensitivity_texts,
        "风险评估": risk_texts,
        "同行对比": peer_texts,
        "财务分析": earnings_quality_texts,
    }
    for section_name, texts in section_claim_map.items():
        if texts:
            excerpts = [t[:200] for t in texts if t]
            if excerpts:
                prompt.append(
                    f"Reference material for {section_name}: {' | '.join(excerpts)}"
                )
    if conversation_brief:
        prompt.insert(1, f"Conversation memory:\n{conversation_brief}")
    if skill_brief:
        prompt.insert(1, f"Relevant skill brief:\n{skill_brief}")
    quality_guidance = _quality_remediation_prompt(quality_remediation_plan or {})
    if quality_guidance:
        prompt.insert(1, quality_guidance)
    repair_guidance = _repair_constraints_prompt(repair_constraints or {})
    if repair_guidance:
        prompt.insert(1, repair_guidance)
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


def _artifact_context_prompt(
    tables: Any = None,
    financial_metrics: Any = None,
    pdf_sections: Any = None,
    company_profile: Any = None,
) -> str:
    parts = []
    compact_tables = _compact_list(tables, max_items=8)
    compact_pdf = _compact_list(pdf_sections, max_items=6)
    compact_metrics = _compact_mapping(financial_metrics, max_items=20)
    compact_profile = _compact_mapping(company_profile, max_items=20)
    if compact_tables:
        parts.append(f"Structured table artifacts: {json.dumps(compact_tables, ensure_ascii=False)}")
    if compact_metrics:
        parts.append(f"Financial metrics artifact: {json.dumps(compact_metrics, ensure_ascii=False)}")
    if compact_pdf:
        parts.append(f"PDF-derived sections/artifacts: {json.dumps(compact_pdf, ensure_ascii=False)}")
    if compact_profile:
        parts.append(f"Company profile artifact: {json.dumps(compact_profile, ensure_ascii=False)}")
    if not parts:
        return ""
    parts.append(
        "Use these artifacts to decide which sections need concrete prose, but cite only evidence_id-backed claims or evidence records."
    )
    return "\n".join(parts)


def _compact_list(raw: Any, max_items: int = 8) -> List[Any]:
    if not isinstance(raw, list):
        return []
    return [_truncate_nested(item) for item in raw[:max_items]]


def _compact_mapping(raw: Any, max_items: int = 20) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    output: Dict[str, Any] = {}
    for index, (key, value) in enumerate(raw.items()):
        if index >= max_items:
            break
        output[str(key)] = _truncate_nested(value)
    return output


def _truncate_nested(value: Any, limit: int = 360) -> Any:
    if isinstance(value, dict):
        return {str(key): _truncate_nested(item, limit=limit) for key, item in list(value.items())[:16]}
    if isinstance(value, list):
        return [_truncate_nested(item, limit=limit) for item in value[:8]]
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _normalize_quality_remediation_plan(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "quality_feedback_used": True,
                "planner_constraints": [raw.strip()],
                "boundary": "Quality feedback is planning context only; report facts still require evidence_id citations and verifier gates.",
            }
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def _normalize_repair_constraints(raw: Any) -> Dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _quality_remediation_prompt(plan: Dict[str, Any]) -> str:
    if not plan or not plan.get("quality_feedback_used"):
        return ""
    required_fixes = [str(item) for item in plan.get("required_fixes", []) if str(item).strip()]
    failed_sections = [str(item) for item in plan.get("failed_sections", []) if str(item).strip()]
    forbidden_patterns = [str(item) for item in plan.get("forbidden_patterns", []) if str(item).strip()]
    constraints = [str(item) for item in plan.get("planner_constraints", []) if str(item).strip()]
    parts = [
        "Quality remediation constraints from the previous delivery gate:",
        "These constraints are planning/writing guidance only; never cite them as evidence.",
    ]
    if failed_sections:
        parts.append("Failed sections: " + ", ".join(failed_sections[:8]))
    if required_fixes:
        parts.append("Required fixes: " + " | ".join(required_fixes[:8]))
    if forbidden_patterns:
        parts.append("Forbidden weak wording: " + "、".join(forbidden_patterns[:8]))
    if constraints:
        parts.append("Planner constraints: " + " | ".join(constraints[:8]))
    parts.append(
        "Hard rule: if a claim exists for a failed section, write the claim into the corresponding report section instead of leaving a framework, placeholder, or weak conclusion."
    )
    return "\n".join(parts)


def _repair_constraints_prompt(plan: Dict[str, Any]) -> str:
    if not plan:
        return ""
    sections = [str(item) for item in plan.get("required_backfill_sections", []) if str(item).strip()]
    unresolved = [str(item) for item in plan.get("must_explain_unresolved_gaps", []) if str(item).strip()]
    parts = [
        "GapResolver repair constraints:",
        "These are writing constraints only; never cite them as evidence.",
    ]
    if sections:
        parts.append("Required backfill sections: " + ", ".join(sections[:10]))
    if unresolved:
        parts.append("Unresolved gaps that must be explained in body: " + ", ".join(unresolved[:12]))
    if plan.get("free_public_source_boundary"):
        parts.append("Source boundary: " + str(plan.get("free_public_source_boundary")))
    parts.append(
        "For unresolved gaps, state what is missing, which free public source classes were attempted, why the item cannot be confirmed, and how it affects the investment view."
    )
    return "\n".join(parts)


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
        replacement = _claims_to_markdown_bullets(section_claims, section=section)
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
        replacement = _claims_to_markdown_bullets(section_claims, section=section)
        if replacement:
            missing_blocks.append(f"## {title}\n\n{replacement.rstrip()}")

    if not missing_blocks:
        return markdown
    insertion = "\n\n".join(missing_blocks).rstrip()
    return markdown.rstrip() + "\n\n" + insertion + "\n"


def hard_backfill_quality_sections(
    markdown: str,
    claims: List[Dict[str, Any]],
    quality_remediation_plan: Dict[str, Any] | None = None,
    repair_constraints: Dict[str, Any] | None = None,
) -> str:
    """Replace weak framework sections with deterministic claim-backed prose."""
    plan = quality_remediation_plan or {}
    target_sections = _quality_target_sections(plan, repair_constraints or {})
    by_section = _claims_by_outline_section(claims)
    output = markdown

    weak_sections = _weak_sections_in_markdown(output)
    for section in sorted(set(by_section) | target_sections | weak_sections, key=_outline_section_order):
        section_claims = by_section.get(section, [])
        title = _section_title(section)
        if not title:
            continue
        body = _section_body(output, title)
        should_replace = body is None or section in target_sections or _section_needs_hard_backfill(title, body)
        if not should_replace:
            continue
        replacement = _claims_to_markdown_bullets(section_claims, section=section) if section_claims else _gap_section_note(section, plan, repair_constraints or {})
        if replacement:
            output = _replace_section(output, title=title, replacement=replacement)
    return output


def _outline_section_order(section: str) -> int:
    for index, item in enumerate(default_company_outline()):
        if item["section_name"] == section:
            return index
    return 999


def _weak_sections_in_markdown(markdown: str) -> set[str]:
    weak: set[str] = set()
    for item in default_company_outline():
        section = str(item["section_name"])
        title = str(item["section_title"])
        body = _section_body(markdown, title)
        if body is not None and _section_needs_hard_backfill(title, body):
            weak.add(section)
    return weak


def _quality_target_sections(plan: Dict[str, Any], repair_constraints: Dict[str, Any] | None = None) -> set[str]:
    failed = {str(item) for item in plan.get("failed_sections", []) if str(item)}
    text = " ".join(
        [str(item) for item in plan.get("required_fixes", [])]
        + [str(item) for item in plan.get("planner_constraints", [])]
        + [str(item) for item in plan.get("forbidden_patterns", [])]
    )
    mapping = {
        "three_statement_analysis": "financial_statements",
        "business_profile": "business_overview",
        "peer_comparison": "peer_compare",
        "peer_compare": "peer_compare",
        "valuation": "valuation",
        "sensitivity": "valuation_sensitivity",
        "valuation_sensitivity": "valuation_sensitivity",
        "risk": "risks",
        "risks": "risks",
        "investment_conclusion": "conclusion",
        "conclusion": "conclusion",
        "executive_summary": "executive_summary",
    }
    targets = {mapping[item] for item in failed if item in mapping}
    for item in (repair_constraints or {}).get("required_backfill_sections", []):
        key = str(item)
        targets.add(mapping.get(key, key))
    if any(term in text for term in ["三表", "利润表", "资产负债表", "现金流量表"]):
        targets.add("financial_statements")
    if any(term in text for term in ["同行", "对比"]):
        targets.add("peer_compare")
    if any(term in text for term in ["估值", "P/E", "P/B", "P/S"]):
        targets.add("valuation")
    if any(term in text for term in ["敏感性", "情景"]):
        targets.add("valuation_sensitivity")
    if any(term in text for term in ["投资建议", "投资结论", "方向", "理由"]):
        targets.add("conclusion")
    if any(term in text for term in ["内容空洞", "暂无结论", "暂无可验证结论"]):
        targets.update({"executive_summary", "business_overview", "risks", "conclusion"})
    return targets


def _claims_by_outline_section(claims: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    section_aliases = {
        "company_valuation": "valuation",
        "valuation_summary": "valuation",
        "risk": "risks",
        "risk_assessment": "risks",
        "business_profile": "business_overview",
        "business": "business_overview",
        "strategy": "strategy_business",
        "financial": "financial_analysis",
        "financial_summary": "financial_analysis",
        "investment_conclusion": "conclusion",
    }
    outline_sections = {item["section_name"] for item in default_company_outline()}
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        section = str(claim.get("section_name") or "").strip()
        section = section_aliases.get(section, section)
        if section in outline_sections:
            by_section.setdefault(section, []).append(claim)
    return by_section


def _section_title(section: str) -> str:
    for item in default_company_outline():
        if item["section_name"] == section:
            return str(item["section_title"])
    return ""


def _gap_section_note(
    section: str,
    quality_remediation_plan: Dict[str, Any] | None = None,
    repair_constraints: Dict[str, Any] | None = None,
) -> str:
    title = _section_title(section) or section
    attempted = _attempted_source_note(quality_remediation_plan or {}, repair_constraints or {})
    impact_map = {
        "executive_summary": "执行摘要暂不能给出高置信度结论，因为该章节缺少可直接引用的核心论点。报告应先补齐关键事实后再形成摘要。",
        "peer_compare": "同行对比暂不可用，主要缺口是可比公司口径、估值倍数或经营指标尚未形成可引用证据。该缺口会降低横向竞争判断的可靠性。",
        "valuation": "估值暂不可用，主要缺口是市值、股本、净利润、自由现金流或可比倍数等输入未形成可引用证据。该缺口会限制目标价和估值区间判断。",
        "valuation_sensitivity": "敏感性分析暂不可用，主要缺口是关键变量及其基准值未形成可引用证据。该缺口会限制对收入、毛利率、成本或汇率变化的情景判断。",
        "risks": "风险评估暂不可用，主要缺口是风险事项缺少可验证证据。该缺口会影响投资结论的风险约束。",
        "conclusion": "投资结论暂不宜给出强方向，主要缺口是估值、同行、风险或财务数据未同时形成可引用证据。当前只能保留审慎观察口径。",
        "financial_statements": "三表摘要暂不可用，主要缺口是利润表、资产负债表或现金流量表未完整形成可引用证据。该缺口会影响盈利质量和现金流匹配判断。",
    }
    note = impact_map.get(section, f"{title}暂不可用，原因是该章节缺少可引用证据。")
    return (
        f"- 数据缺口说明：{note}\n"
        f"  - 已尝试来源：{attempted}\n"
        "  - 处理边界：本段仅说明缺口，不作为事实证据引用，也不伪造数值、来源或投资结论。"
    )


def _attempted_source_note(plan: Dict[str, Any], repair_constraints: Dict[str, Any]) -> str:
    source_boundary = str(repair_constraints.get("free_public_source_boundary") or plan.get("source_boundary") or "").strip()
    if source_boundary:
        return source_boundary
    return "免费公开披露、交易所/监管公告、行情源、宏观数据源和本地证据库。"


def _section_body(markdown: str, title: str) -> str | None:
    header_pattern = re.compile(rf"(?m)^##\s+{re.escape(title)}\s*$")
    match = header_pattern.search(markdown)
    if not match:
        return None
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    section_end = match.end() + next_header.start() if next_header else len(markdown)
    return markdown[match.end():section_end]


def _collect_available_periods(evidence_records: Any = None, tables: Any = None, financial_metrics: Any = None) -> set[str]:
    periods: set[str] = set()
    for collection in [evidence_records, tables]:
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, dict):
                    _add_period(periods, item.get("period"))
    if isinstance(financial_metrics, dict):
        for item in financial_metrics.get("metrics", []) if isinstance(financial_metrics.get("metrics"), list) else []:
            if isinstance(item, dict):
                _add_period(periods, item.get("period"))
    elif isinstance(financial_metrics, list):
        for item in financial_metrics:
            if isinstance(item, dict):
                _add_period(periods, item.get("period"))
    return periods


def _collect_structured_fallback_sources(tables: Any = None, financial_metrics: Any = None) -> List[str]:
    sources: set[str] = set()
    fallback_types = {"market_api", "market_data", "pdf_statement_table"}
    table_items = tables if isinstance(tables, list) else []
    for table in table_items:
        rows = table.get("rows", []) if isinstance(table, dict) and isinstance(table.get("rows"), list) else []
        for row in rows:
            if not isinstance(row, dict) or row.get("period_match") is False:
                continue
            source_type = str(row.get("source_type") or "").strip()
            if source_type in fallback_types:
                provider = str(row.get("provider") or source_type).strip()
                if provider:
                    sources.add(provider)
    metric_items = financial_metrics.get("metrics", []) if isinstance(financial_metrics, dict) else []
    for metric in metric_items if isinstance(metric_items, list) else []:
        if not isinstance(metric, dict) or metric.get("period_match") is False:
            continue
        source_type = str(metric.get("source_type") or "").strip()
        if source_type in fallback_types:
            provider = str(metric.get("provider") or source_type).strip()
            if provider:
                sources.add(provider)
    return sorted(sources)


def _add_period(periods: set[str], raw: Any) -> None:
    period = str(raw or "").strip().upper()
    if re.match(r"^20\d{2}Q[1-4]$", period):
        periods.add(period)


def _section_needs_hard_backfill(title: str, body: str) -> bool:
    cleaned = re.sub(r"\s+", "", body)
    weak_markers = [
        "暂无结论",
        "暂无可验证结论",
        "待补",
        "框架待补",
        "框架性",
        "缺少可量化",
        "缺少实质",
        "无法判断",
        "N/A",
    ]
    if any(marker in cleaned for marker in weak_markers):
        return True
    if title == "投资结论":
        has_direction = any(term in cleaned for term in ["中性", "审慎", "买入", "增持", "持有", "卖出", "评级", "观察"])
        has_reason = any(term in cleaned for term in ["因为", "基于", "理由", "驱动", "约束", "风险", "估值", "增长"])
        return not (has_direction and has_reason)
    return False


def _replace_section(markdown: str, title: str, replacement: str) -> str:
    header_pattern = re.compile(rf"(?m)^##\s+{re.escape(title)}\s*$")
    match = header_pattern.search(markdown)
    if not match:
        return markdown.rstrip() + f"\n\n## {title}\n\n{replacement.rstrip()}\n"
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    section_end = match.end() + next_header.start() if next_header else len(markdown)
    new_body = "\n\n" + replacement.rstrip() + "\n\n"
    return markdown[:match.end()] + new_body + markdown[section_end:].lstrip("\n")


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


def _claims_to_markdown_bullets(claims: List[Dict[str, Any]], section: str = "") -> str:
    lines: List[str] = []
    for claim in claims:
        text = str(claim.get("claim_text") or "").strip()
        if not text:
            continue
        if _claim_text_is_weak(text):
            text = _rewrite_weak_claim_as_gap_note(section or str(claim.get("section_name") or ""), text)
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


def _claim_text_is_weak(text: str) -> bool:
    weak_markers = ("暂无", "待补", "框架", "尚未覆盖完整", "证据不足以量化", "初步判断")
    return any(marker in text for marker in weak_markers)


def _rewrite_weak_claim_as_gap_note(section: str, original: str) -> str:
    section_key = {
        "risk": "risks",
        "investment_conclusion": "conclusion",
        "sensitivity": "valuation_sensitivity",
        "peer_comparison": "peer_compare",
    }.get(section, section)
    note = _gap_section_note(section_key, {}, {})
    first_line = next((line[2:] for line in note.splitlines() if line.startswith("- ")), note)
    if section_key == "peer_compare":
        return first_line + " 当前只能说明同行维度仍需补齐，不能据此判断公司相对强弱。"
    if section_key == "conclusion":
        return first_line + " 因此投资结论维持审慎观察，并以补齐财务、同行和估值证据作为后续判断前提。"
    if section_key == "valuation_sensitivity":
        return first_line + " 因此当前只能说明变量方向，不能量化目标价或利润弹性。"
    return first_line


# The definitions above may contain legacy mojibake text from earlier generated
# code. Keep the helper names stable, but override their wording here with clean
# Chinese so the final report does not expose debugging-style prose.
def _gap_section_note(
    section: str,
    quality_remediation_plan: Dict[str, Any] | None = None,
    repair_constraints: Dict[str, Any] | None = None,
) -> str:
    title = _section_title(section) or section
    attempted = _attempted_source_note(quality_remediation_plan or {}, repair_constraints or {})
    impact_map = {
        "executive_summary": "执行摘要需要依赖已验证的核心财务、经营和风险判断；当前证据尚未形成足够集中的摘要依据。报告在本节只说明证据边界，避免把零散事实包装成确定结论。",
        "peer_compare": "同行对比需要可比公司、经营指标和估值口径保持一致；当前证据未形成完整横向口径。该限制会削弱对相对竞争地位的判断力度。",
        "valuation": "估值判断需要市值、股本、盈利、现金流或可比倍数等输入相互印证；当前证据未形成完整估值输入。该限制会影响目标价和估值区间判断。",
        "valuation_sensitivity": "敏感性分析需要关键变量、基准值和变动幅度具备可引用依据；当前证据未形成可量化情景输入。该限制会影响对收入、毛利率、成本或汇率变化的弹性判断。",
        "risks": "风险评估需要风险事项与公开证据逐项对应；当前证据对部分风险约束覆盖不足。该限制会影响投资结论的风险边界。",
        "conclusion": "投资结论需要财务、同行、估值和风险证据同时支撑；当前证据链尚不足以给出强方向评级。结论应保持审慎观察，并明确后续需要补强的证据。",
        "financial_statements": "三表摘要需要利润表、资产负债表和现金流量表口径完整；当前证据对部分报表项目覆盖不足。该限制会影响盈利质量和现金流匹配判断。",
    }
    note = impact_map.get(section, f"{title}需要更多可引用证据支撑，当前只说明证据边界和对判断的影响。")
    return (
        f"- 数据缺口说明：{note}\n"
        f"  - 已尝试来源：{attempted}\n"
        "  - 处理边界：本段只描述公开证据覆盖范围，不虚构数值、来源或投资评级。"
    )


def _attempted_source_note(plan: Dict[str, Any], repair_constraints: Dict[str, Any]) -> str:
    source_boundary = str(repair_constraints.get("free_public_source_boundary") or plan.get("source_boundary") or "").strip()
    if source_boundary:
        return source_boundary
    return "免费公开披露、交易所或监管公告、行情源、宏观数据源和本地证据库。"


def ensure_period_disclosure(
    markdown: str,
    target_period: str,
    evidence_records: Any = None,
    tables: Any = None,
    financial_metrics: Any = None,
) -> str:
    target = str(target_period or "").strip().upper()
    data_periods = _collect_available_periods(evidence_records, tables, financial_metrics)
    if not target and not data_periods:
        return markdown
    latest = sorted(data_periods)[-1] if data_periods else ""
    has_delay = bool(target and latest and target != latest)
    disclosure_terms = ("数据期间说明", "最新可得", "数据延迟", "披露数据期", "data cutoff", "latest available")
    if any(term in markdown for term in disclosure_terms):
        return markdown
    lines = [
        "## 数据期间说明",
        "",
        f"- 目标报告期：{target or '未指定'}。",
        f"- 最新可得披露数据期：{latest or '未从结构化证据中识别'}。",
        f"- 数据延迟判断：{'存在数据期与目标期不一致，正文结论需按最新可得公开披露解释。' if has_delay else '未识别到目标期与可得数据期错配。'}",
    ]
    fallback_sources = _collect_structured_fallback_sources(tables, financial_metrics)
    if fallback_sources:
        lines.append(
            "- 三表来源说明：目标期官方 10-Q/交易所原始三表尚未进入可用证据时，本文仅使用已通过 period_match 的结构化降级来源"
            f"（{', '.join(fallback_sources)}）生成三表项目；正式发布前仍需用一手公告复核。"
        )
    return markdown.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def _section_needs_hard_backfill(title: str, body: str) -> bool:
    cleaned = re.sub(r"\s+", "", body)
    lowered = cleaned.lower()
    weak_markers = [
        "暂无结论",
        "暂无可验证结论",
        "待补",
        "框架待补",
        "框架性",
        "缺少可量化",
        "缺少实质",
        "无法判断",
        "N/A",
        "证据ID",
        "置信度",
    ]
    weak_markers.extend(
        [
            "no conclusion",
            "no verifiable conclusion",
            "no verifiable claims",
            "unable to judge",
            "to be filled",
            "framework-only",
            "framework only",
            "placeholder",
            "hollow",
            "empty section",
        ]
    )
    if any(marker.lower() in lowered for marker in weak_markers):
        return True
    bullet_like = [line.strip() for line in body.splitlines() if line.strip()]
    prose_chars = re.sub(r"[\s#*\-:：;；,，.。()\[\]【】]", "", body)
    if len(prose_chars) < 24 and len(bullet_like) <= 2:
        return True
    if title == "投资结论":
        has_direction = any(term in cleaned for term in ["中性", "审慎", "买入", "增持", "持有", "卖出", "评级", "观察"])
        has_reason = any(term in cleaned for term in ["因为", "基于", "理由", "驱动", "约束", "风险", "估值", "增长"])
        return not (has_direction and has_reason)
    return False


def _section_is_empty_placeholder(section_body: str) -> bool:
    cleaned = "\n".join(line.strip() for line in section_body.strip().splitlines() if line.strip())
    if not cleaned:
        return True
    placeholder_markers = [
        "本节暂无可验证结论",
        "暂无可验证结论",
        "暂无结论",
        "no verifiable conclusion",
        "no verifiable claims",
    ]
    placeholder_markers.extend(
        [
            "no conclusion",
            "unable to judge",
            "to be filled",
            "framework-only",
            "framework only",
            "placeholder",
            "hollow",
            "empty section",
            "n/a",
        ]
    )
    lowered = cleaned.lower()
    if any(marker.lower() in lowered for marker in placeholder_markers):
        return True
    prose_chars = re.sub(r"[\s#*\-:：;；,，.。()\[\]【】]", "", cleaned)
    return len(prose_chars) < 16


def _claims_to_markdown_bullets(claims: List[Dict[str, Any]], section: str = "") -> str:
    lines: List[str] = []
    for claim in claims:
        text = str(claim.get("claim_text") or "").strip()
        if not text:
            continue
        if _claim_text_is_weak(text):
            text = _rewrite_weak_claim_as_gap_note(section or str(claim.get("section_name") or ""), text)
        evidence_ids = [str(item) for item in claim.get("evidence_ids", []) if str(item)]
        citation_tail = " ".join(f"[{item}]" for item in evidence_ids[:4])
        if citation_tail and citation_tail not in text:
            text = f"{text} {citation_tail}"
        lines.append(f"- {text}")
    return "\n".join(lines)


def _claim_text_is_weak(text: str) -> bool:
    weak_markers = (
        "暂无",
        "待补",
        "框架",
        "尚未覆盖完整",
        "证据不足以量化",
        "初步判断",
        "不可用",
        "暂不宜",
        "当前只能",
    )
    return any(marker in text for marker in weak_markers)


def _rewrite_weak_claim_as_gap_note(section: str, original: str) -> str:
    section_key = {
        "risk": "risks",
        "investment_conclusion": "conclusion",
        "sensitivity": "valuation_sensitivity",
        "peer_comparison": "peer_compare",
    }.get(section, section)
    note = _gap_section_note(section_key, {}, {})
    first_line = next((line[2:] for line in note.splitlines() if line.startswith("- ")), note)
    if section_key == "peer_compare":
        return first_line + " 因此本报告把同行结论限定为证据覆盖范围说明，不据此判断公司相对强弱。"
    if section_key == "conclusion":
        return first_line + " 因此投资结论维持审慎观察，并以补强财务、同行和估值证据作为后续判断前提。"
    if section_key == "valuation_sensitivity":
        return first_line + " 因此本报告只说明变量方向，不量化目标价或利润弹性。"
    return first_line


def enforce_verified_financial_sections(
    markdown: str,
    claims: List[Dict[str, Any]],
    financial_metrics: Any = None,
    tables: Any = None,
) -> str:
    """Overwrite financial prose with accepted metric/table lineage.

    The LLM draft may still contain stale cash-flow or statement numbers.  This
    post-write guard makes the statement and financial-analysis sections a
    deterministic rendering of accepted structured artifacts.
    """

    rows = _verified_statement_rows(financial_metrics, tables)
    if not rows:
        return _replace_section(markdown, _section_title("financial_statements"), _statement_gap_markdown(claims))
    statement_body = _statement_rows_to_markdown(rows)
    output = _replace_section(markdown, _section_title("financial_statements"), statement_body)
    analysis_body = _financial_analysis_body(rows, claims)
    if analysis_body:
        output = _replace_section(output, _section_title("financial_analysis"), analysis_body)
    return output


def _statement_gap_markdown(claims: List[Dict[str, Any]]) -> str:
    evidence_ids = _dedupe_preserve_order(
        str(evidence_id)
        for claim in claims
        if isinstance(claim, dict)
        for evidence_id in claim.get("evidence_ids", [])
        if str(evidence_id)
    )
    citation_tail = " ".join(f"[{evidence_id}]" for evidence_id in evidence_ids[:3])
    return (
        "- 三表缺口说明：当前已验收结构化证据未形成可验证的利润表、资产负债表和现金流量表行；"
        "正文不补写三表数值，该缺口会限制盈利质量、现金转化和估值判断。 "
        + citation_tail
    ).rstrip()


def backfill_role_output_sections(markdown: str, research_blackboard: Any = None) -> str:
    """Use verified role findings when the draft leaves analysis sections hollow."""

    if not isinstance(research_blackboard, dict):
        return markdown
    role_outputs = research_blackboard.get("role_outputs", {})
    if not isinstance(role_outputs, dict):
        return markdown
    mapping = {
        "identity_profile": "business_overview",
        "peer_analysis": "peer_compare",
        "valuation_analysis": "valuation",
        "risk_analysis": "risks",
    }
    output = markdown
    for role_key, section in mapping.items():
        role = role_outputs.get(role_key, {})
        if not isinstance(role, dict):
            continue
        findings = (
            _business_identity_to_markdown(research_blackboard, role)
            if section == "business_overview"
            else _role_findings_to_markdown(role, section)
        )
        if not findings:
            continue
        title = _section_title(section)
        body = _section_body(output, title)
        if (
            body is None
            or _section_needs_hard_backfill(title, body)
            or _role_section_is_thin(body)
            or _role_section_is_gap_note(body)
        ):
            output = _replace_section(output, title, findings)
    return output


def _business_identity_to_markdown(research_blackboard: Dict[str, Any], role: Dict[str, Any]) -> str:
    identity = research_blackboard.get("company_identity", {}) if isinstance(research_blackboard.get("company_identity"), dict) else {}
    industry = research_blackboard.get("industry_profile", {}) if isinstance(research_blackboard.get("industry_profile"), dict) else {}
    company = str(identity.get("company_name") or identity.get("symbol") or "").strip()
    symbol = str(identity.get("canonical_symbol") or identity.get("symbol") or "").strip()
    sector = str(identity.get("sector") or industry.get("sector") or "").strip()
    industry_name = str(identity.get("industry") or industry.get("industry") or "").strip()
    summary = str(identity.get("business_summary") or industry.get("business_summary") or "").strip()
    evidence_ids = [str(item) for item in role.get("evidence_ids", []) if str(item)]
    tail = " ".join(f"[{item}]" for item in evidence_ids[:4])
    lines: List[str] = []
    if company or symbol or sector or industry_name:
        label = f"{company}（{symbol}）" if company and symbol else company or symbol
        parts = [item for item in [sector, industry_name] if item]
        lines.append(f"- {label} 属于{(' / '.join(parts)) if parts else '已识别上市公司'}口径，业务画像以公司身份解析和公开披露为边界。 {tail}".rstrip())
    if summary:
        lines.append(f"- 主营业务概览：{summary} {tail}".rstrip())
    if not lines:
        return _role_findings_to_markdown(role, "business_overview")
    lines.append("- 写作边界：本节仅使用已解析的公司身份、行业分类和公开证据，不把记忆或路由信息当作事实来源。")
    return "\n".join(_dedupe_preserve_order(lines))


def _verified_statement_rows(financial_metrics: Any = None, tables: Any = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        table_type = str(table.get("table_type") or table.get("statement") or "")
        table_rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        if table_rows:
            for row in table_rows:
                if isinstance(row, dict):
                    normalized = dict(row)
                    normalized.setdefault("statement", table_type)
                    rows.append(normalized)
        elif table.get("metric_name") or table.get("line_item"):
            rows.append(dict(table))
    for metric in (financial_metrics.get("metrics", []) if isinstance(financial_metrics, dict) else []):
        if not isinstance(metric, dict):
            continue
        if metric.get("period_match") is False:
            continue
        statement = _statement_for_metric(str(metric.get("metric_name") or ""))
        if not statement:
            continue
        rows.append(
            {
                "statement": statement,
                "line_item": metric.get("metric_name"),
                "metric_name": metric.get("metric_name"),
                "value": metric.get("value"),
                "unit": metric.get("unit"),
                "period": metric.get("period"),
                "evidence_id": metric.get("source_evidence_id"),
                "source_evidence_id": metric.get("source_evidence_id"),
                "source_table_id": metric.get("source_table_id"),
                "report_date": metric.get("report_date"),
            }
        )
    output: List[Dict[str, Any]] = []
    for row in rows:
        line_item = str(row.get("line_item") or row.get("metric_name") or "").strip()
        statement = _normalize_statement_name(row.get("statement") or row.get("table_type") or "")
        value = _safe_number(row.get("value"))
        if not line_item or not statement or value is None:
            continue
        key = (statement, line_item, str(row.get("period") or ""))
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(row)
        normalized["statement"] = statement
        normalized["line_item"] = line_item
        normalized["value"] = value
        output.append(normalized)
    return output


def _statement_rows_to_markdown(rows: List[Dict[str, Any]]) -> str:
    grouped = _rows_by_statement(rows)
    parts = [
        "- 本节仅使用已通过 period_match 和 metric lineage/table artifact 的结构化三表项目；未进入 lineage 的数值不写入正文。",
    ]
    statement_labels = {
        "income_statement": "income statement / 利润表",
        "balance_sheet": "balance sheet / 资产负债表",
        "cash_flow_statement": "cash flow statement / 现金流量表",
    }
    item_order = {
        "income_statement": ["revenue", "gross_profit", "gross_margin", "operating_profit", "net_income"],
        "balance_sheet": ["total_assets", "total_liabilities", "equity", "shareholders_equity", "cash_and_equivalents"],
        "cash_flow_statement": ["operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "capex", "free_cash_flow"],
    }
    for statement in ["income_statement", "balance_sheet", "cash_flow_statement"]:
        items = _ordered_rows(grouped.get(statement, []), item_order[statement])
        if not items:
            if statement == "cash_flow_statement":
                parts.append(
                    f"- {statement_labels[statement]}：cash flow data gap explained; 当前未形成可验证结构化现金流量表行，"
                    "不补写经营现金流或自由现金流数值，该缺口会限制现金转化率和估值敏感性判断。"
                )
            else:
                parts.append(f"- {statement_labels[statement]}：当前未形成可验证结构化行，正文不补数。")
            continue
        rendered = "; ".join(_format_statement_row(row) for row in items[:8])
        evidence = _evidence_tail(items)
        parts.append(f"- {statement_labels[statement]}：{rendered}。{evidence}".rstrip())
    return "\n".join(parts)


def _financial_analysis_body(rows: List[Dict[str, Any]], claims: List[Dict[str, Any]]) -> str:
    grouped = _rows_by_statement(rows)
    revenue = _first_row(grouped.get("income_statement", []), ["revenue"])
    net_income = _first_row(grouped.get("income_statement", []), ["net_income"])
    ocf = _first_row(grouped.get("cash_flow_statement", []), ["operating_cash_flow"])
    fcf = _first_row(grouped.get("cash_flow_statement", []), ["free_cash_flow"])
    assets = _first_row(grouped.get("balance_sheet", []), ["total_assets"])
    liabilities = _first_row(grouped.get("balance_sheet", []), ["total_liabilities"])
    lines = ["- 财务分析采用已验收的三表行项目，避免混用旧期间、行情快照或未绑定 lineage 的数值。"]
    if revenue or net_income:
        bits = [_format_statement_row(row) for row in [revenue, net_income] if row]
        lines.append("- 盈利能力：" + "；".join(bits) + "。")
    if assets or liabilities:
        bits = [_format_statement_row(row) for row in [assets, liabilities] if row]
        lines.append("- 资产负债：" + "；".join(bits) + "。")
    if ocf or fcf:
        bits = [_format_statement_row(row) for row in [ocf, fcf] if row]
        lines.append("- 现金流：" + "；".join(bits) + "。")
    for claim in claims:
        if not isinstance(claim, dict) or str(claim.get("section_name") or "") not in {"earnings_quality", "financial_analysis"}:
            continue
        text = str(claim.get("claim_text") or "").strip()
        if text and not _claim_text_is_weak(text):
            evidence_ids = [str(item) for item in claim.get("evidence_ids", []) if str(item)]
            tail = " ".join(f"[{item}]" for item in evidence_ids[:3])
            lines.append(f"- {text} {tail}".rstrip())
    return "\n".join(_dedupe_preserve_order(lines))


def _role_findings_to_markdown(role: Dict[str, Any], section: str) -> str:
    findings = [str(item).strip() for item in role.get("findings", []) if str(item).strip()]
    findings = [item for item in findings if not _role_finding_is_debug(item)]
    if not findings:
        return ""
    evidence_ids = [str(item) for item in role.get("evidence_ids", []) if str(item)]
    tail = " ".join(f"[{item}]" for item in evidence_ids[:4])
    lines = [f"- {item}{(' ' + tail) if tail and '[' not in item else ''}".rstrip() for item in findings[:6]]
    missing = [str(item) for item in role.get("missing_inputs", []) if str(item)]
    if missing and section in {"peer_compare", "valuation", "risks"}:
        lines.append("- 边界说明：仍缺少 " + ", ".join(missing[:5]) + "，相关结论按证据覆盖范围降级处理。")
    impact = str(role.get("impact_on_report") or "").strip()
    if impact and not _role_finding_is_debug(impact):
        lines.append(f"- 写作边界：{impact}")
    return "\n".join(_dedupe_preserve_order(lines))


def _rows_by_statement(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("statement") or ""), []).append(row)
    return grouped


def _ordered_rows(rows: List[Dict[str, Any]], order: List[str]) -> List[Dict[str, Any]]:
    rank = {name: index for index, name in enumerate(order)}
    return sorted(rows, key=lambda row: rank.get(str(row.get("line_item") or ""), 999))


def _first_row(rows: List[Dict[str, Any]], names: List[str]) -> Dict[str, Any] | None:
    wanted = set(names)
    return next((row for row in rows if str(row.get("line_item") or "") in wanted), None)


def _format_statement_row(row: Dict[str, Any]) -> str:
    label = _metric_label(str(row.get("line_item") or row.get("metric_name") or "metric"))
    value = _format_number(row.get("value"))
    unit = str(row.get("unit") or "").strip()
    period = str(row.get("period") or "").strip()
    report_date = str(row.get("report_date") or "").strip()
    suffix = f"{value}{(' ' + unit) if unit else ''}"
    context = ", ".join(item for item in [period, f"report_date={report_date}" if report_date else ""] if item)
    return f"{label} {suffix}{(' (' + context + ')') if context else ''}"


def _evidence_tail(rows: List[Dict[str, Any]]) -> str:
    evidence_ids = _dedupe_preserve_order(
        str(row.get("source_evidence_id") or row.get("evidence_id") or "")
        for row in rows
        if str(row.get("source_evidence_id") or row.get("evidence_id") or "")
    )
    return " ".join(f"[{item}]" for item in evidence_ids[:4])


def _statement_for_metric(metric_name: str) -> str:
    metric = metric_name.lower()
    if metric in {"revenue", "gross_profit", "gross_margin", "operating_profit", "net_income"}:
        return "income_statement"
    if metric in {"total_assets", "total_liabilities", "equity", "shareholders_equity", "total_equity", "cash_and_equivalents"}:
        return "balance_sheet"
    if metric in {"operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "capex", "free_cash_flow"}:
        return "cash_flow_statement"
    return ""


def _normalize_statement_name(raw: Any) -> str:
    text = str(raw or "").lower()
    if "income" in text or "profit" in text:
        return "income_statement"
    if "balance" in text or "asset" in text or "liabilit" in text:
        return "balance_sheet"
    if "cash" in text:
        return "cash_flow_statement"
    return text if text in {"income_statement", "balance_sheet", "cash_flow_statement"} else ""


def _metric_label(metric_name: str) -> str:
    return {
        "revenue": "收入",
        "gross_profit": "毛利",
        "gross_margin": "毛利率",
        "operating_profit": "经营利润",
        "net_income": "净利润",
        "total_assets": "总资产",
        "total_liabilities": "总负债",
        "equity": "权益",
        "shareholders_equity": "股东权益",
        "total_equity": "总权益",
        "cash_and_equivalents": "现金及等价物",
        "operating_cash_flow": "经营现金流",
        "investing_cash_flow": "投资现金流",
        "financing_cash_flow": "筹资现金流",
        "capex": "资本开支",
        "free_cash_flow": "自由现金流",
    }.get(metric_name, metric_name)


def _format_number(value: Any) -> str:
    number = _safe_number(value)
    if number is None:
        return str(value)
    if abs(number) >= 100:
        return f"{number:,.0f}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _safe_number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
        if number != number:
            return None
        return number
    except (TypeError, ValueError):
        return None


def _role_section_is_thin(body: str) -> bool:
    cleaned = re.sub(r"\s+", "", str(body or ""))
    if len(cleaned) < 80:
        return True
    thin_terms = ("coveragecount", "evidencecount", "仅泛泛", "无实质", "框架", "待补")
    return any(term.lower() in cleaned.lower() for term in thin_terms)


def _role_section_is_gap_note(body: str) -> bool:
    text = str(body or "").lower()
    markers = (
        "数据缺口",
        "僅说明",
        "仅说明",
        "use only free public sources",
        "memory is not evidence",
        "gap explained",
        "缺口",
        "鏁版嵁缂哄彛",
    )
    return any(marker.lower() in text for marker in markers)


def _role_finding_is_debug(text: str) -> bool:
    lowered = text.lower()
    debug_terms = ("coverage income=", "metric lineage count", "evidence records available", "contains 0 comparable")
    return any(term in lowered for term in debug_terms)


def _dedupe_preserve_order(items: Any) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


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
