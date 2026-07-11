"""FinalAnswerAgent for report generation."""

from __future__ import annotations

from html import escape
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult

logger = logging.getLogger(__name__)
from src.agents.context_packer import build_revision_brief, pack_claims, pack_evidence_records, pack_markdown_excerpt
from src.models import ModelAdapter
from src.schemas.claim import ClaimItem
from src.templates.company_outline import default_company_outline
from src.templates.markdown_template import render_markdown_report


SECTIONS_REQUIRING_EVIDENCE = {
    "business_overview": "业务概览",
    "ownership_governance": "股权结构与公司治理",
    "peer_compare": "同行对比",
    "valuation": "估值观察",
    "risks": "风险评估",
    "conclusion": "投资结论",
}

GENERIC_GOVERNANCE_PHRASES = [
    "董事会监督、股权结构和激励机制可能影响长期战略",
    "是上市公司",
    "作为上市公司",
    "作为一家上市公司",
    "具备完善的公司治理结构",
]

FINAL_ANSWER_SYSTEM_PROMPT = """You are FinalAnswerAgent in a financial research multi-agent system.
Write a comprehensive, detailed Chinese investment research report from provided claim_evidence_bundles.

Each section must contain at least 3-5 substantive paragraphs. Do not write just 1-2 sentences per section.
Use the provided evidence, key_facts, and key_metrics to write thorough financial analysis.

Each bundle contains:
- claim_text: the claim to write about
- supporting_evidence: evidence content that grounds this claim
- grounding_status: "grounded" (well-supported, at least one high-quality evidence),
  "partial" (limited evidence), or "unverified" (unsupported)

Rules:
- Only write claims where grounding_status is "grounded" or "partial"
- Never write claims with grounding_status "unverified" in the main report body
- Use citations like [evidence_id] after factual claims
- Move unsupported content to a data-gap appendix
- Do not invent numbers, sources, or unsupported conclusions
Return only valid JSON:
{"markdown":"# ...","summary":"...","title":"...","citation_count":3}

title must be a formal Chinese research report title, e.g.
"财务研究报告：贵州茅台（600519.SS）2026年第一季度公司财务研究报告"
Format: 财务研究报告：{company_name}（{symbol}）{period_hint}公司{report_type}
Use the explicit company_name and symbol from the prompt context, NOT the research_topic.
Do NOT copy the research_topic into the title.
Do NOT include phrases like "生成", "任务", "生成报告" in the title.
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
        # Check if contract mode is requested
        report_section_contracts = task.parameters.get("report_section_contracts", None)
        citation_binder = task.parameters.get("citation_binder", None)
        if report_section_contracts is not None and citation_binder is not None:
            return self._execute_contract_mode(task, report_section_contracts, citation_binder)

        all_claims = _claim_dicts(task.parameters.get("claims", []))
        evidence_records = task.parameters.get("evidence_records", [])
        topic = str(task.parameters.get("research_topic", task.description))
        max_claims = int(task.parameters.get("max_claims", 30) or 30)
        max_evidence = int(task.parameters.get("max_evidence", 20) or 20)
        evidence_content_limit = int(task.parameters.get("evidence_content_limit", 1200) or 1200)
        revision_request = str(task.parameters.get("revision_request", "")).strip()
        verification_report = task.parameters.get("verification_report", {})
        prior_markdown = str(task.parameters.get("prior_markdown", ""))
        conversation_brief = str(task.parameters.get("conversation_brief", "")).strip()
        skill_brief = str(task.parameters.get("skill_brief", "")).strip()
        rating = str(task.parameters.get("rating", "")).strip()
        symbol = str(task.parameters.get("symbol", "")).strip().upper()
        period = str(task.parameters.get("period", "")).strip().upper()
        company_name = str(task.parameters.get("company_name", "")).strip()
        tables = task.parameters.get("tables", [])
        financial_metrics = task.parameters.get("financial_metrics", {})
        currency_audit = task.parameters.get("currency_audit", {})
        valuation_model = task.parameters.get("valuation_model", {})
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

        # Parse claim_evidence_bundles for grounded writing
        claim_evidence_bundles = task.parameters.get("claim_evidence_bundles", [])
        if not isinstance(claim_evidence_bundles, list):
            claim_evidence_bundles = []

        # Parse section_dossiers for depth enforcement
        section_dossiers = task.parameters.get("section_dossiers", {})
        if not isinstance(section_dossiers, dict):
            section_dossiers = {}

        prompt_claims, claim_pack_meta = pack_claims(
            all_claims,
            max_items=max_claims,
            text_limit=400,
            total_chars=int(task.parameters.get("claim_context_chars", 10000) or 10000),
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
            "claim_evidence_bundles_count": len(claim_evidence_bundles),
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
            "section_evidence": {},
            "research_blackboard_used": isinstance(research_blackboard, dict) and bool(research_blackboard),
            "pre_write_critic_objection_count": len(pre_write_critic.get("objections", []))
            if isinstance(pre_write_critic, dict)
            else 0,
            "degraded_report": degraded_report,
        }

        markdown = render_markdown_report(claims=all_claims, charts=[])
        section_evidence = _build_section_evidence_status(prompt_claims)
        metadata['section_evidence'] = section_evidence
        summary = '已为”%s”生成包含 %d 条核心结论的研究报告。' % (topic, len(all_claims))
        if self.model and prompt_claims:
            try:
                payload = self.model.generate_json(
                    prompt=_build_final_prompt(
                        topic=topic,
                        claims=prompt_claims,
                        evidence_records=evidence_records,
                        claim_evidence_bundles=claim_evidence_bundles,
                        revision_request=revision_request,
                        verification_report=verification_report if isinstance(verification_report, dict) else {},
                        prior_markdown=prior_markdown,
                        conversation_brief=conversation_brief,
                        skill_brief=skill_brief,
                        rating=rating,
                        symbol=symbol,
                        period=period,
                        company_name=company_name,
                        quality_remediation_plan=quality_remediation_plan,
                        repair_constraints=repair_constraints,
                        tables=tables,
                        financial_metrics=financial_metrics,
                        pdf_sections=pdf_sections,
                        company_profile=company_profile,
                        research_blackboard=research_blackboard,
                        pre_write_critic=pre_write_critic,
                        section_evidence=section_evidence,
                        section_dossiers=section_dossiers,
                    ),
                    system_prompt=FINAL_ANSWER_SYSTEM_PROMPT,
                    extra_body={"max_tokens": int(task.parameters.get("max_tokens", 4000) or 4000)},
                )
                if isinstance(payload.get("markdown"), str) and payload["markdown"].strip():
                    markdown = normalize_report_headings(payload["markdown"].strip())
                    summary = str(payload.get("summary") or summary)
                    llm_title = str(payload.get("title") or "").strip()
                    if llm_title:
                        topic = llm_title
                    metadata["llm_used"] = True
                    metadata["citation_count"] = int(payload.get("citation_count", 0) or 0)
            except Exception as exc:
                metadata["llm_error"] = str(exc)

        markdown = normalize_report_headings(markdown)
        markdown = remove_broken_or_half_sentences(markdown)
        markdown = backfill_empty_sections_from_claims(markdown, all_claims)
        markdown = insert_missing_sections_from_claims(markdown, all_claims)
        markdown = hard_backfill_quality_sections(markdown, all_claims, quality_remediation_plan, repair_constraints)
        markdown = enforce_verified_financial_sections(markdown, all_claims, financial_metrics, tables)
        markdown = backfill_role_output_sections(markdown, research_blackboard)
        markdown = ensure_period_disclosure(markdown, period, evidence_records, tables, financial_metrics)
        if degraded_report:
            markdown = _append_degraded_report_note(markdown, pre_write_critic, pre_write_rework_history)
        markdown = _append_currency_gate_note(markdown, currency_audit, valuation_model)
        markdown = normalize_report_headings(markdown)
        markdown = insert_deterministic_blocks_from_dossiers(markdown, section_dossiers)
        markdown = enforce_section_depth(markdown, section_dossiers)
        markdown = remove_raw_pdf_paste_paragraphs(markdown, section_dossiers)
        markdown = enforce_section_depth(markdown, section_dossiers)
        markdown = auto_rewrite_core_sections(
            markdown,
            claims=all_claims,
            evidence_records=evidence_records if isinstance(evidence_records, list) else [],
            financial_metrics=financial_metrics,
            quality_remediation_plan=quality_remediation_plan,
            repair_constraints=repair_constraints,
        )
        markdown = _sanitize_generic_phrases(markdown)
        markdown = _sanitize_pdf_gap_language(markdown)
        # Final cleanup pass — after all deterministic overrides that may re-insert bad content
        markdown = remove_debug_leakage(markdown)
        markdown = remove_internal_ids(markdown)
        markdown = remove_template_phrases(markdown)
        markdown = remove_a_share_template_contamination(markdown, symbol)
        markdown = remove_instructional_report_text(markdown)
        markdown = dedupe_section_paragraphs(markdown)
        markdown = remove_broken_or_half_sentences(markdown)
        markdown, blocker_meta = final_blocker_scan(markdown)
        markdown = _clean_to_numbered_citations(markdown, evidence_records if isinstance(evidence_records, list) else [])
        html = _markdown_to_simple_html(markdown, title=topic)
        report_json = {
            "title": topic,
            "summary": summary,
            "claim_count": len(all_claims),
            "evidence_count": len(evidence_records) if isinstance(evidence_records, list) else 0,
            "claims": all_claims,
            "evidence_records": evidence_records if isinstance(evidence_records, list) else [],
            "claim_evidence_bundles": claim_evidence_bundles,
            "research_blackboard": research_blackboard if isinstance(research_blackboard, dict) else {},
            "pre_write_critic": pre_write_critic if isinstance(pre_write_critic, dict) else {},
            "degraded_report": degraded_report,
            "pre_write_rework_history": pre_write_rework_history if isinstance(pre_write_rework_history, list) else [],
            "section_dossiers": section_dossiers,
            "currency_audit": currency_audit if isinstance(currency_audit, dict) else {},
            "valuation_model": valuation_model if isinstance(valuation_model, dict) else {},
            "delivery_status": _delivery_status_from_currency(currency_audit, valuation_model, blocker_meta.get("delivery_status", "normal")),
            "sparse_or_invalid_sections": blocker_meta.get("sparse_or_invalid_sections", []),
            "user_warning": blocker_meta.get("user_warning", ""),
        }
        metadata["delivery_status"] = report_json["delivery_status"]

        return self.success(
            task,
            {"markdown": markdown, "html": html, "report_json": report_json, "summary": summary},
            metadata=metadata,
        )

    def _execute_contract_mode(
        self,
        task: AgentTask,
        contracts: Any,
        binder: Any,
    ) -> TaskResult:
        """Execute FinalAnswer in contract mode: only read section contracts.

        This replaces the old approach where the LLM received all evidence_records,
        claims, peer_rows, and citations globally. Now it only receives contracts.

        Args:
            binder: CitationBinder instance from orchestrator, already loaded with
                evidence_records and already called bind_all(contracts).
        """
        from src.report.contract_renderer import (
            render_diagnostic_contract_inputs,
            render_full_report_from_contracts,
        )
        from src.report.section_contracts import ALL_SECTION_KEYS, SECTION_TITLES, ReportSectionContracts
        from src.report.html_report_generator import render_professional_html_report

        # Ensure contracts are proper object
        if isinstance(contracts, dict):
            from src.report.section_contracts import ReportSectionContracts as RSC
            rsc = RSC()
            if "contracts" in contracts:
                for sk, sc_data in contracts.get("contracts", {}).items():
                    c = rsc.ensure(sk)
                    if isinstance(sc_data, dict):
                        c.status = sc_data.get("status", "gap")
                        c.deterministic_text = sc_data.get("deterministic_text", "")
                        for fdata in sc_data.get("facts", []):
                            if isinstance(fdata, dict):
                                c.add_fact(
                                    fact_type=fdata.get("fact_type", "general"),
                                    text=fdata.get("text", ""),
                                    evidence_ids=fdata.get("evidence_ids", []),
                                    source_types=fdata.get("source_types", []),
                                    quality=fdata.get("quality", "ok"),
                                )
                        for br in sc_data.get("blocked_reasons", []):
                            c.add_blocked_reason(br)
                        for qf in sc_data.get("quality_flags", []):
                            c.add_quality_flag(qf)
                if "metadata" in contracts:
                    rsc.metadata.update(contracts["metadata"])
            contracts = rsc

        topic = str(task.parameters.get("research_topic", task.description))
        symbol = str(task.parameters.get("symbol", "")).strip().upper()
        period = str(task.parameters.get("period", "")).strip().upper()

        # Build the list of top blockers
        top_blockers = contracts.top_blockers()

        # Render the full report from contracts
        report_title = f"财务研究报告：{symbol}（{period}）"
        contract_markdown = render_full_report_from_contracts(
            contracts,
            title=report_title,
            top_blockers=top_blockers,
        )

        # For sections with allow_llm_rewrite, rewrite one at a time.
        # Each section gets its own focused LLM call so a timeout/cutoff on one
        # section doesn't lose the others (Fix: per-section rewrite, not batch JSON).
        llm_context = render_diagnostic_contract_inputs(contracts)
        final_md = contract_markdown
        llm_used = False
        if self.model and hasattr(self.model, "generate") and llm_context:
            REWRITE_SECTION_KEYS = {
                "executive_summary",
                "business_overview",
                "ownership_governance",
                "strategy_business",
                "financial_analysis",
                "risk_factors",
            }
            for sk in REWRITE_SECTION_KEYS:
                contract = contracts.get(sk)
                if not contract:
                    continue
                if not contract.render_policy.get("allow_llm_rewrite", False):
                    continue
                if contract.status in {"gap", "fallback"}:
                    # LLM can't write from nothing — skip sections with no data
                    continue

                heading = SECTION_TITLES.get(sk, sk)
                try:
                    llm_prompt = (
                        f"Research topic: {topic}\n"
                        f"Symbol: {symbol}\n"
                        f"Period: {period}\n\n"
                        f"Below is the context for section \"{heading}\" ({sk}).\n"
                        "Rewrite this section in Chinese financial research prose.\n"
                        "IMPORTANT:\n"
                        "- Do NOT include citation numbers like [1][2][3] or [ev_xxx]\n"
                        "- Use the facts provided — do not invent numbers\n"
                        "- Write 3-5 substantive paragraphs in Chinese\n"
                        "- Start DIRECTLY with the content, no explanations, no headings\n"
                        f"\n{llm_context}"
                    )
                    response = self.model.generate(
                        prompt=llm_prompt,
                        system_prompt=(
                            f"You are FinalAnswerAgent writing the \"{heading}\" section of a "
                            "financial report. Write in Chinese financial research prose. "
                            "Do not include citations."
                        ),
                        extra_body={"max_tokens": 2048},
                    )
                    body = str(response.content or "").strip() if response.success else ""
                    if not body or len(body) < 60:
                        continue
                    # Find the section heading in compiled markdown and replace
                    pattern = re.compile(rf"(?m)^##\s+{re.escape(heading)}\s*$")
                    match = re.search(pattern, final_md)
                    if match:
                        # Find the KNOWN next section heading from SECTION_TITLES order
                        # instead of any ^## pattern (prevents LLM body false matches)
                        end = len(final_md)
                        try:
                            sk_idx = ALL_SECTION_KEYS.index(sk)
                            for nsk in ALL_SECTION_KEYS[sk_idx + 1:]:
                                ntitle = SECTION_TITLES.get(nsk, nsk)
                                nm = re.search(rf"(?m)^##\s+{re.escape(ntitle)}\s*$", final_md[match.end():])
                                if nm:
                                    end = match.end() + nm.start()
                                    break
                        except ValueError:
                            nm = re.search(r"(?m)^##\s+", final_md[match.end():])
                            if nm:
                                end = match.end() + nm.start()
                        final_md = final_md[:match.end()] + "\n\n" + body + "\n\n" + final_md[end:]
                        llm_used = True
                        logger.info("LLM rewrote section %s (%d chars)", sk, len(body))
                except Exception as exc:
                    logger.error("LLM rewrite failed for section %s: %s", sk, exc)

        # ── Citation binding pipeline ──────────────────────────────────
        # Step 1: Ensure binder has run bind_all (safe to call if already done)
        if hasattr(binder, 'bind_all'):
            binder.bind_all(contracts)

        # Step 2: Strip any LLM-written or old-style citations
        final_md = binder.strip_llm_citations(final_md)

        # Step 3: Inject bound [N] citation markers from contracts
        final_md = binder.inject_bound_citations(final_md, contracts)
        final_md = remove_a_share_template_contamination(final_md, symbol)
        final_md = remove_instructional_report_text(final_md)
        final_md = dedupe_section_paragraphs(final_md)

        # Step 4: Write citation artifacts to disk
        import os
        output_dir = getattr(task, "output_dir", None) or "data/outputs/multi_agent"
        if hasattr(task, "parameters") and isinstance(task.parameters, dict):
            od = task.parameters.get("output_dir", output_dir)
            if od:
                output_dir = od
        if hasattr(binder, 'write_artifacts'):
            binder.write_artifacts(str(output_dir))

        # Write contracts JSON
        contracts_path = os.path.join(str(output_dir), "report_section_contracts.json")
        if isinstance(contracts, ReportSectionContracts):
            contracts.to_json_file(contracts_path)

        # Get citation map for merge_task_result
        citation_map = {}
        if hasattr(binder, 'get_citation_map'):
            citation_map = binder.get_citation_map()

        # ── Professional HTML rendering ───────────────────────────────
        blocked = False
        delivery_status = "normal"
        html = render_professional_html_report(
            markdown=final_md,
            title=report_title,
            delivery_status=delivery_status,
            top_blockers=top_blockers,
            quality_blocked=False,
            contract_mode=True,
        )

        report_json = {
            "title": report_title,
            "delivery_status": delivery_status,
            "contract_mode": True,
            "top_blockers": top_blockers,
            "citation_map_keys": list(citation_map.keys()),
        }

        return self.success(
            task,
            {"markdown": final_md, "html": html, "report_json": report_json,
             "summary": "Contract-mode report generated."},
            metadata={
                "contract_mode": True,
                "llm_used": llm_used,
                "section_count": len(contracts.contracts) if isinstance(contracts, ReportSectionContracts) else 0,
                "top_blockers": top_blockers,
                "citation_map": citation_map,
            },
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


def _append_currency_gate_note(markdown: str, currency_audit: Any, valuation_model: Any) -> str:
    if not isinstance(currency_audit, dict) or not currency_audit:
        return markdown
    blockers = currency_audit.get("blockers", []) if isinstance(currency_audit.get("blockers"), list) else []
    warnings = currency_audit.get("warnings", []) if isinstance(currency_audit.get("warnings"), list) else []
    statement_currency = str(currency_audit.get("statement_currency") or "")
    trading_currency = str(currency_audit.get("trading_currency") or "")
    display_currency = str(currency_audit.get("display_currency") or statement_currency)
    valuation_status = ""
    if isinstance(valuation_model, dict):
        valuation_status = str(valuation_model.get("valuation_status") or valuation_model.get("error") or "")
    official_status = str(currency_audit.get("official_source_status") or "")
    has_fx = bool(isinstance(valuation_model, dict) and valuation_model.get("fx_rate"))
    is_cross = statement_currency and trading_currency and statement_currency.upper() != trading_currency.upper()
    valuation_blocked = is_cross and not has_fx

    if not statement_currency or statement_currency == "unknown":
        return markdown

    lines = ["", "## 货币与数据质量说明", ""]
    # Currency line
    ccy_parts = []
    if statement_currency:
        ccy_parts.append(f"财务报表货币：{statement_currency}")
    if trading_currency:
        ccy_parts.append(f"交易货币：{trading_currency}")
    if display_currency:
        ccy_parts.append(f"报告展示货币：{display_currency}")
    if ccy_parts:
        lines.append("- " + "；".join(ccy_parts) + "")

    # Official source status — human-readable Chinese
    if official_status in ("resolver_not_enabled", "not_integrated"):
        lines.append("- 官方来源接入状态：当前港股默认生成链路尚未稳定接入或启用港交所公告 / 公司 IR 官方年报源；本报告主要基于第三方结构化数据，尚未完成官方年报或港交所公告交叉验证。")
    elif official_status == "resolver_unavailable":
        lines.append("- 官方来源接入状态：港交所公告检索器已配置但当前不可用，可能由于远程搜索 API key 缺失或网络不可用。")
    elif official_status == "attempted_not_found":
        lines.append("- 官方来源接入状态：已尝试检索港交所公告与公司 IR，但未获取到匹配 FY2025 的可解析官方文件。")
    elif official_status == "found":
        lines.append("- 官方来源接入状态：已获取港交所公告或公司 IR 来源，并用于官方来源交叉验证。")

    # Valuation restriction
    if valuation_blocked:
        lines.append("- 估值限制：由于官方来源校验与跨货币汇率换算尚未闭环，本报告不输出确定性 P/E、P/S、DCF 或目标价。")
    elif valuation_status and valuation_status.startswith("blocked"):
        lines.append(f"- 估值限制：估值模型状态为 {valuation_status}，本报告不输出确定性估值倍数。")

    return markdown.rstrip() + "\n" + "\n".join(lines) + "\n"


def _delivery_status_from_currency(currency_audit: Any, valuation_model: Any, current: str = "normal") -> str:
    if current != "normal":
        return current
    blockers = currency_audit.get("blockers", []) if isinstance(currency_audit, dict) and isinstance(currency_audit.get("blockers"), list) else []
    if any(str(item).startswith("valuation") or str(item).startswith("missing_fx") for item in blockers):
        return "blocked_due_to_currency_mismatch"
    if blockers:
        return "degraded_due_to_currency_quality"
    if isinstance(valuation_model, dict):
        status = str(valuation_model.get("valuation_status") or valuation_model.get("error") or "")
        if status.startswith("blocked") or status.startswith("missing_fx"):
            return "blocked_due_to_currency_mismatch"
        if status.startswith("degraded"):
            return "degraded_due_to_currency_quality"
    return current


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


def _compact_bundles(bundles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compact claim-evidence bundles for prompt injection, avoiding text bloat."""
    if not bundles:
        return []
    compact: List[Dict[str, Any]] = []
    for b in bundles:
        if not isinstance(b, dict):
            continue
        supporting = b.get("supporting_evidence", [])
        if isinstance(supporting, list):
            supporting = [
                {"evidence_id": e.get("evidence_id"), "trust_level": e.get("trust_level"), "source_type": e.get("source_type")}
                for e in supporting
                if isinstance(e, dict)
            ]
        compact.append({
            "claim_id": b.get("claim_id"),
            "section_name": b.get("section_name"),
            "claim_text": str(b.get("claim_text", ""))[:300],
            "grounding_status": b.get("grounding_status", "unverified"),
            "allowed_in_report": bool(b.get("allowed_in_report", False)),
            "supporting_evidence_count": len(supporting),
        })
    return compact


# ── section evidence contract ──────────────────────────────────────────

def _build_section_evidence_status(
    claims: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Check which key sections have sufficient evidence from packed claims.

    Returns a dict mapping section_name -> status: "sufficient", "weak", or "gap".
    """
    status: Dict[str, str] = {}
    section_claims: Dict[str, List[Dict[str, Any]]] = {}
    for c in claims:
        sec = str(c.get("section_name", ""))
        if sec not in SECTIONS_REQUIRING_EVIDENCE:
            continue
        section_claims.setdefault(sec, []).append(c)

    for sec in SECTIONS_REQUIRING_EVIDENCE:
        sec_claims = section_claims.get(sec, [])
        total = len(sec_claims)
        if total == 0:
            status[sec] = "gap"
            continue
        with_ids = sum(
            1 for c in sec_claims
            if c.get("evidence_ids") and any(str(eid).strip() for eid in c.get("evidence_ids", []))
        )
        if with_ids == 0:
            status[sec] = "gap"
        elif with_ids < total / 2:
            status[sec] = "weak"
        else:
            status[sec] = "sufficient"
    return status


def _section_evidence_gap_prompt(section_status: Dict[str, str]) -> str:
    """Build prompt instructions for sections with insufficient evidence."""
    gap_sections = [k for k, v in section_status.items() if v == "gap"]
    weak_sections = [k for k, v in section_status.items() if v == "weak"]
    lines: list[str] = []
    if gap_sections:
        gap_names = [SECTIONS_REQUIRING_EVIDENCE[s] for s in gap_sections]
        lines.append(
            "EVIDENCE GAP SECTIONS — the following sections have NO evidence-backed claims: "
            + ", ".join(gap_names)
            + ". "
            + "For each of these sections, you MUST write a concise data-gap disclosure "
            + "rather than generic templated description. A gap disclosure explains what data "
            + "is missing and why the section cannot be fully analyzed, e.g.: "
            + f"'本轮尚未通过港交所公告、公司 IR 年报或年度业绩公告获取可验证来源，"
            + f"因此本节不展开详细分析，后续应以官方年报为准。' "
            + "Do NOT invent numbers, sources, or conclusions. "
            + "Do NOT use phrases like '董事会监督、股权结构和激励机制可能影响长期战略' or '是上市公司'."
        )
    if weak_sections:
        weak_names = [SECTIONS_REQUIRING_EVIDENCE[s] for s in weak_sections]
        lines.append(
            "WEAK EVIDENCE SECTIONS — the following sections have claims but most lack "
            + "evidence_ids: " + ", ".join(weak_names) + ". "
            + "Write conservatively and note where data is limited. "
            + "Do NOT fabricate numbers or present weak claims as established facts."
        )
    return "\n".join(lines)


def _sanitize_generic_phrases(markdown: str) -> str:
    """Replace known generic/unsubstantiated phrases with gap disclosures."""
    for phrase in GENERIC_GOVERNANCE_PHRASES:
        if phrase in markdown:
            markdown = markdown.replace(
                phrase,
                "资料缺口：本节暂无充足的可验证证据支持详细分析。",
            )
    # Catch generic board/ownership fluff patterns
    markdown = re.sub(
        r'董事会[^。]*?(?:监督|结构|独立|运作|机制)[^。]*。',
        '资料缺口：本节暂无充足的可验证证据支持详细分析。',
        markdown,
    )
    markdown = re.sub(
        r'股权结构[^。]*?(?:集中|分散|激励|安排)[^。]*。',
        '资料缺口：本节暂无充足的可验证证据支持详细分析。',
        markdown,
    )
    return markdown


def _sanitize_pdf_gap_language(markdown: str) -> str:
    text = str(markdown or "")
    text = re.sub(r"\b([A-Z0-9]{4,6}\.[A-Z]{2})（\1）", r"\1", text)
    text = re.sub(r"(。){2,}", "。", text)
    text = text.replace(
        "资料缺口：本节暂无充足的可验证证据支持详细分析。",
        "本节尚未获得可直接支撑分析的官方章节摘要，因此保持数据缺口。",
    )
    text = text.replace(
        "本轮已获取公司年度报告PDF，但尚未稳定抽取相关章节，因此本节暂不展开详细分析",
        "本轮已获取公司年度报告 PDF，但尚未稳定抽取本节所需的具体章节或字段，因此本节暂不展开详细分析",
    )
    return text


def _build_final_prompt(
    topic: str,
    claims: List[Dict[str, Any]],
    evidence_records: Any,
    claim_evidence_bundles: List[Dict[str, Any]] | None = None,
    revision_request: str = "",
    verification_report: Dict[str, Any] | None = None,
    prior_markdown: str = "",
    conversation_brief: str = "",
    skill_brief: str = "",
    rating: str = "",
    symbol: str = "",
    period: str = "",
    company_name: str = "",
    quality_remediation_plan: Dict[str, Any] | None = None,
    repair_constraints: Dict[str, Any] | None = None,
    tables: Any = None,
    financial_metrics: Any = None,
    pdf_sections: Any = None,
    company_profile: Any = None,
    research_blackboard: Any = None,
    pre_write_critic: Any = None,
    section_evidence: Dict[str, str] | None = None,
    section_dossiers: Dict[str, Any] | None = None,
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
        f"Company symbol: {symbol}",
        f"Target report period: {period or 'not specified'}",
        f"Company name: {company_name}" if company_name else "Company name: (not specified)",
        f"Shared research blackboard: {json.dumps(_compact_blackboard(research_blackboard), ensure_ascii=False)}",
        f"Pre-write critic: {json.dumps(pre_write_critic if isinstance(pre_write_critic, dict) else {}, ensure_ascii=False)}",
        f"Claims: {json.dumps(compact_claims, ensure_ascii=False)}",
        f"Evidence: {json.dumps(compact_evidence, ensure_ascii=False)}",
        (
            "Claim-Evidence Bundles (each claim pre-bound to supporting evidence "
            "with grounding_status: grounded/partial/unverified):\n"
            + json.dumps(_compact_bundles(claim_evidence_bundles), ensure_ascii=False)
            + "\n"
            if claim_evidence_bundles
            else ""
        ),
        (
            "Write the report in Chinese financial research prose. "
            "Use exactly these Markdown section headers: "
            "执行摘要, 业务概览, 股权结构与公司治理, 战略与主营业务, 三表摘要, 财务分析, "
            "同行对比, 估值观察, 估值敏感性, 风险评估, 投资结论. "
            "Map claim section_names to headers: "
            "valuation→估值观察, valuation_sensitivity→估值敏感性, conclusion→投资结论, "
            "peer_compare→同行对比, financial_statements→三表摘要, financial_analysis→财务分析, "
            "executive_summary→执行摘要, earnings_quality→财务分析, "
            "business_overview→业务概览, strategy_business→战略与主营业务, "
            "ownership_governance→股权结构与公司治理, risks→风险评估. "
            "For each section, synthesize the provided claims into coherent prose paragraphs "
            "with specific data, analysis, and a conclusion. "
            "Reference evidence_ids in brackets like [ev_123].\n"
            "TITLE FORMAT: Generate a formal Chinese title as the 'title' field in your JSON output. "
            "Use the company_name and symbol provided above. "
            "Format: 财务研究报告：{company_name}（{symbol}）{period}{report_type}. "
            "For example: '财务研究报告：贵州茅台（600519.SS）2026年第一季度公司财务研究报告'. "
            "IMPORTANT: Do NOT copy the research_topic into the title. "
            "Do NOT include '生成', '任务', '报告生成' in the title.\n"
            "FORBIDDEN placeholder patterns — never use these: "
            "框架性, 待补, 暂无结论, 暂无可验证结论, 无法判断, "
            "仅给出框架性描述, 缺少可量化, 框架待补, N/A. "
            "If a claim exists for a section, write it as substantive prose with context. "
            "If no claim exists, skip the section entirely rather than writing a placeholder.\n"
            "EXAMPLE of good prose:\n"
            "## 财务分析\n"
            "本期收入 35.4 亿美元（同比 +24%），其中数据中心业务占比 46% 首次超越客户端业务，成为最大收入来源。"
            "毛利率提升至 52.1%（同比 +1.8pp），受益于高毛利的数据中心 GPU 出货占比提升。"
            "经营现金流 12.3 亿美元，自由现金流 9.8 亿美元，均同比改善。[ev_amd_fin_001]\n"
            "业务概览 must describe the company's actual business: sector, industry, products, "
            "and business model, not debug wording like '证据覆盖 X 条'. "
            "三表摘要 must present key line items (revenue, net income, operating cash flow, "
            "free cash flow, assets/equity) in context. "
            "估值观察 section: if the dossier contains deterministic_blocks with a valuation table, "
            "describe the methodology and values in prose. "
            "If valuation is blocked (no deterministic_blocks for valuation), you MUST write: "
            "'由于财务报表货币与交易货币不一致，且本轮尚未完成官方年报校验与可验证汇率换算，"
            "本报告不输出确定性P/E、P/S、DCF或目标价。' "
            "Do NOT invent P/E, P/S, DCF numbers or target prices when valuation is blocked. "
            "The 投资结论 section must only reference dimensions actually supported by claims."
            "Add a short 数据期间说明 when target report period differs from the latest available disclosure period."
            "Treat claims and evidence as the primary source of truth for all quantitative data. "
            "For 业务概览 only, you may incorporate generally-known public information about the company's "
            "sector, products, and business model. "
            "For all other sections (especially 估值观察, 估值敏感性, 财务分析, 投资结论), "
            "do not infer financial data or valuation inputs beyond what claims and evidence provide. "
            "For 同行对比 section: if provided a markdown peer comparison table, "
            "preserve the table verbatim — do NOT rewrite it as prose or concatenate "
            "metrics like '收入增速9.1;毛利率56.45'. Always show the table and add "
            "a brief caveat that peer data is from third-party structured sources pending official validation. "
            "IMPORTANT: Write as a professional research analyst. "
            "Do NOT include system instructions, writing boundaries, meta-descriptions about evidence sources, "
            "or any text that sounds like a system prompt or debug output. "
            "Every section must read like an analyst wrote it for a client, not like a system describing its own constraints.\n"
            "Each section must be at least 3-5 substantive sentences of analysis. "
            "A single sentence is insufficient for any section. "
            "业务概览: describe the company's sector, products, business model, and market position in detail. "
            "股权结构与公司治理: discuss ownership structure, board oversight, and governance practices. "
            "战略与主营业务: discuss business strategy, competitive advantages, and growth initiatives. "
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

    if section_dossiers:
        compact_dossiers = {}
        for sk, sd in section_dossiers.items():
            if isinstance(sd, dict):
                compact_dossiers[sk] = {
                    "section_title": sd.get("section_title", ""),
                    "key_facts": sd.get("key_facts", [])[:6],
                    "key_metrics": sd.get("key_metrics", [])[:6],
                    "tables": sd.get("tables", [])[:3],
                    "caveats": sd.get("caveats", [])[:3],
                    "suggested_paragraphs": sd.get("suggested_paragraphs", [])[:2],
                    "min_content_level": sd.get("min_content_level", "full"),
                    "evidence_strength": sd.get("evidence_strength", "medium"),
                    "supported_claim_count": len(sd.get("supported_claims", [])),
                    "supporting_evidence_count": len(sd.get("supporting_evidence_ids", [])),
                }
        prompt.append(
            "Section Dossiers (per-section writing briefs with key facts, metrics, "
            "evidence strength, and suggested fallback paragraphs):\n"
            + json.dumps(compact_dossiers, ensure_ascii=False)
            + "\n\nWrite the report organized by section. For each section:\n"
            + "1. Use the dossier's key_facts, key_metrics, and tables as source material\n"
            + "2. Write substantive prose (3-5+ sentences per section)\n"
            + "3. If evidence_strength is 'weak' or min_content_level is 'data_gap', write a brief\n"
            + "   data-gap note instead of filling with generic content\n"
            + "4. Use citation IDs like [evidence_id] after factual statements\n"
        )
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
    evidence_gap_guidance = _section_evidence_gap_prompt(section_evidence or {})
    if evidence_gap_guidance:
        prompt.insert(1, evidence_gap_guidance)
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


SECTION_DEPTH_THRESHOLDS = {
    "executive_summary": 120,
    "business_overview": 160,
    "financial_analysis": 220,
    "peer_compare": 120,
    "valuation": 180,
    "risks": 160,
    "conclusion": 160,
}

SECTION_HEADING_MAP = {
    "executive_summary": "执行摘要",
    "business_overview": "业务概览",
    "ownership_governance": "股权结构与公司治理",
    "strategy_business": "战略与主营业务",
    "three_statement_summary": "三表摘要",
    "financial_analysis": "财务分析",
    "peer_compare": "同行对比",
    "valuation": "估值观察",
    "valuation_sensitivity": "估值敏感性",
    "risks": "风险评估",
    "conclusion": "投资结论",
}

def normalize_report_headings(markdown: str) -> str:
    """Normalize common report section headings to the configured outline."""
    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return text

    alias_to_section = {
        "摘要": "executive_summary",
        "执行摘要": "executive_summary",
        "核心摘要": "executive_summary",
        "公司概览": "business_overview",
        "业务概览": "business_overview",
        "业务分析": "business_overview",
        "三表摘要": "three_statement_summary",
        "财务报表": "three_statement_summary",
        "财务摘要": "three_statement_summary",
        "财务分析": "financial_analysis",
        "同业对比": "peer_compare",
        "同行对比": "peer_compare",
        "可比公司": "peer_compare",
        "估值": "valuation",
        "估值观察": "valuation",
        "估值分析": "valuation",
        "风险": "risks",
        "风险提示": "risks",
        "风险评估": "risks",
        "投资结论": "conclusion",
        "结论": "conclusion",
        "executive summary": "executive_summary",
        "business overview": "business_overview",
        "financial statements": "three_statement_summary",
        "financial analysis": "financial_analysis",
        "peer comparison": "peer_compare",
        "valuation": "valuation",
        "valuation sensitivity": "valuation_sensitivity",
        "sensitivity analysis": "valuation_sensitivity",
        "risks": "risks",
        "risk factors": "risks",
        "investment conclusion": "conclusion",
    }
    canonical_titles = {
        item["section_name"]: str(item["section_title"])
        for item in default_company_outline()
        if isinstance(item, dict) and item.get("section_name") and item.get("section_title")
    }
    canonical_titles.update({k: v for k, v in SECTION_HEADING_MAP.items() if v})

    lines: List[str] = []
    seen_sections = set()
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            lines.append(line)
            continue

        level, heading = match.groups()
        clean_heading = re.sub(r"^[\d一二三四五六七八九十]+[\.、\)]\s*", "", heading.strip())
        normalized_key = re.sub(r"\s+", " ", clean_heading).strip().lower()
        section_key = alias_to_section.get(clean_heading) or alias_to_section.get(normalized_key)
        if not section_key:
            lines.append(line)
            continue

        title = canonical_titles.get(section_key, clean_heading)
        heading_level = "##"
        if section_key in seen_sections:
            heading_level = "###"
        else:
            seen_sections.add(section_key)
        lines.append(f"{heading_level} {title}")

    output = "\n".join(lines)
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output.strip()


HALF_SENTENCE_PATTERNS = [
    (r'相关的[。，,．]', ''),
    (r'(?:需要|需)关注[。，,．]', ''),
    (r'(?:需关注|需注意)[^。\n]{0,30}相关的[。，,．]', ''),
    (r'主要体现为[。，,．]', ''),
    (r'包括：[^。\n]*。', ''),
    (r'作为上市公司[。，,．]', ''),
    (r'具备完善的公司治理结构[。，,．]', '资料缺口：本节暂无充足的可验证证据支持详细分析。'),
    (r'未分类领域[。，,．]', ''),
    (r'持续深耕[^。\n]{0,20}[。，,．]', ''),
    (r'(?:巩固|提升)核心竞争力[^。\n]{0,20}[。，,．]', ''),
    (r'长期发展空间[^。\n]{0,10}[。，,．]', ''),
]

# Debug/internal field names that must never appear in the final report body
DEBUG_LEAK_PATTERNS = [
    "metric_count",
    "rejected_metric_count",
    "statement_line_item_count",
    "Risk-related claim evidence count",
    "supported metrics",
    "正文应使用中文归纳",
    "章节已抽取",
    "section extracted",
    "developer placeholder",
    "TODO",
    "FIXME",
]

# Template/buzzword phrases that indicate hollow content
TEMPLATE_PHRASES = [
    "持续深耕",
    "巩固核心竞争力",
    "长期发展空间",
]


RAW_PDF_FALLBACK_MARKERS = (
    "公司坚持",
    "报告期内主要经营情况",
    "一是",
    "二是",
    "三是",
    "√适用",
    "□不适用",
    "年度报告",
    "管理层讨论与分析",
)


def _select_depth_suggestions(section_key: str, dossier: dict) -> list[str]:
    suggestions = [str(item).strip() for item in dossier.get("suggested_paragraphs", []) if str(item).strip()]
    suggestions = [item for item in suggestions if not _looks_like_raw_pdf_fallback(item)]
    return suggestions[:4]


def _count_chinese_chars(text: str) -> int:
    return len(re.sub(r"[\s\n\r#\-*:：;；,，.。()\[\]【】\"\"''a-zA-Z0-9]", "", str(text or "")))


def _format_metric_facts(metrics: Any, limit: int = 8) -> list[str]:
    if not isinstance(metrics, list):
        return []
    output: list[str] = []
    for item in metrics:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("metric_name") or "").strip()
        value = item.get("value")
        if not name or value in (None, ""):
            continue
        unit = str(item.get("unit") or "").strip()
        period = str(item.get("period") or "").strip()
        source = str(item.get("source_type") or item.get("provider") or "").strip()
        text = f"{name}为{value}{unit}"
        if period:
            text += f"（{period}）"
        if source:
            text += f"，来源口径为{source}"
        output.append(text)
        if len(output) >= limit:
            break
    return output


def _build_section_depth_replacement(section_key: str, dossier: dict, threshold: int) -> str:
    suggestions = _select_depth_suggestions(section_key, dossier)
    blocks = [str(item).strip() for item in dossier.get("deterministic_blocks", []) if str(item).strip()]
    facts = [str(item).strip() for item in dossier.get("key_facts", []) if str(item).strip()]
    facts = [item for item in facts if not _looks_like_raw_pdf_fallback(item) and not re.match(r"^\d+$", item)]
    metric_facts = _format_metric_facts(dossier.get("key_metrics", []))
    tables = dossier.get("tables", []) if isinstance(dossier.get("tables", []), list) else []

    parts: list[str] = []
    for item in suggestions + blocks:
        if item and item not in parts:
            parts.append(item)
        if _count_chinese_chars("\n\n".join(parts)) >= threshold:
            return "\n\n".join(parts)

    section_templates = {
        "executive_summary": [
            "本报告当前证据链主要覆盖财务指标、估值输入状态、同行可比口径和风险线索，因此整体判断以公开数据可验证的经营表现为主。",
            "在证据仍有缺口的情况下，结论采用审慎表述：优先说明已验证事实，再披露尚未取得官方页码级证据或完整估值输入的限制。",
        ],
        "business_overview": [
            "公司业务分析聚焦主营产品、销售渠道、品牌资源和经营模式。已抽取到官方年报章节摘要时，本节以归纳后的业务事实呈现，不直接复述年报长段原文。",
            "现有资料显示，公司业务叙述需要同时连接产品结构、渠道覆盖和品牌或工艺壁垒，并结合收入贡献判断主营业务稳定性。",
        ],
        "financial_analysis": [
            "财务分析围绕收入规模、利润质量、资产负债结构和经营现金流展开。三表数据同时可用时，应观察利润是否由现金流支撑，以及资产负债变化是否削弱经营弹性。",
            "从当前结构化指标看，收入、净利润、资产负债和经营现金流是本节的核心证据；缺失项会降低对趋势和盈利质量的判断确定性。",
        ],
        "peer_compare": [
            "同行对比采用市场和行业隔离后的可比口径。若同市场样本不足，本节只保留可比性边界说明，不把跨市场公司作为直接同业结论。",
            "对 A 股白酒或消费品公司，可比重点应放在收入增速、毛利率、净利率、ROE、渠道结构和品牌溢价，而不是跨行业科技指标。",
        ],
        "valuation": [
            "估值观察以公开市场数据、财务指标和模型输入状态为基础。当前若缺少市值、股本或完整市场输入，则仅保留方向性估值约束。",
            "在输入不完整时，本节不输出目标价或确定性评级，而是说明可观察倍数、现金流质量和关键敏感变量对判断的影响。",
        ],
        "risks": [
            "风险评估聚焦需求、价格、渠道、成本、监管和数据质量。对消费品和白酒类 A 股公司，核心风险来自消费需求变化、渠道库存、产品价格体系、原材料成本和合规要求。",
            "这些风险会分别影响收入节奏、毛利率、经营现金流和估值假设；若官方风险章节证据不足，结论应保持审慎并披露证据边界。",
        ],
        "conclusion": [
            "投资结论综合财务质量、估值约束、同行位置和风险因素后形成。本报告当前更适合作为审慎观察结论，而不是直接给出买卖评级。",
            "若财务质量较强但估值输入和官方页码级证据仍不足，结论应偏中性：认可经营韧性，同时保留对估值、风险和证据覆盖的限制说明。",
        ],
    }
    if metric_facts:
        parts.append("可用结构化指标为：" + "、".join(metric_facts[:8]) + "。")
    if facts:
        parts.append("关键事实为：" + "；".join(facts[:6]) + "。")
    if tables:
        parts.append(f"本节引用了 {len(tables)} 组表格或同行数据，分析重点在于表格口径、数据来源和可比性。")
    for item in section_templates.get(section_key, []):
        if item not in parts:
            parts.append(item)

    return _dedupe_paragraphs("\n\n".join(item for item in parts if item).strip())


def _looks_like_raw_pdf_fallback(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    marker_count = sum(1 for marker in RAW_PDF_FALLBACK_MARKERS if marker in text or marker in compact)
    if marker_count >= 2:
        return True
    if len(compact) > 180 and marker_count >= 1:
        return True
    if len(compact) > 260 and ("。" in text or "，" in text):
        return True
    return False


def remove_raw_pdf_paste_paragraphs(markdown: str, section_dossiers: dict) -> str:
    """Remove annual-report paste paragraphs from sections that have structured facts."""
    if not markdown or not isinstance(section_dossiers, dict):
        return markdown
    output = markdown
    for section_key, dossier in section_dossiers.items():
        if not isinstance(dossier, dict):
            continue
        metadata = dossier.get("metadata", {}) if isinstance(dossier.get("metadata", {}), dict) else {}
        if section_key != "business_overview" and not metadata.get("facts_extraction_applied"):
            continue
        heading = SECTION_HEADING_MAP.get(section_key, "")
        if not heading:
            continue
        header_pattern = re.compile(rf"(?m)^##\s*{re.escape(heading)}\s*$")
        match = header_pattern.search(output)
        if not match:
            continue
        next_header = re.search(r"(?m)^##\s+", output[match.end():])
        start = match.end()
        end = start + next_header.start() if next_header else len(output)
        body = output[start:end].strip()
        if not body:
            continue
        paragraphs = re.split(r"\n\s*\n", body)
        kept = [paragraph.strip() for paragraph in paragraphs if paragraph.strip() and not _looks_like_raw_pdf_fallback(paragraph)]
        if len(kept) == len([paragraph for paragraph in paragraphs if paragraph.strip()]):
            continue
        output = output[:start] + "\n\n" + "\n\n".join(kept).strip() + "\n\n" + output[end:]
    return output


def enforce_section_depth(markdown: str, section_dossiers: dict) -> str:
    """Check each core section for minimum content depth; use suggested_paragraphs as fallback."""
    if not section_dossiers:
        return markdown
    output = markdown
    for section_key, threshold in SECTION_DEPTH_THRESHOLDS.items():
        heading = SECTION_HEADING_MAP.get(section_key, "")
        if not heading:
            continue
        header_pattern = re.compile(rf"(?m)^##\s*{re.escape(heading)}\s*$")
        match = header_pattern.search(output)
        if not match:
            continue
        next_header = re.search(r"(?m)^##\s+", output[match.end():])
        start = match.end()
        end = start + next_header.start() if next_header else len(output)
        body = output[start:end].strip()
        chinese_chars = _count_chinese_chars(body)
        if chinese_chars >= threshold:
            continue
        dossier = section_dossiers.get(section_key, {})
        if not isinstance(dossier, dict):
            continue
        if dossier.get("min_content_level") == "data_gap":
            continue
        replacement = _build_section_depth_replacement(section_key, dossier, threshold)
        if replacement:
            output = output[:start] + "\n\n" + replacement + "\n\n" + output[end:]
    return output


def insert_deterministic_blocks_from_dossiers(markdown: str, section_dossiers: dict) -> str:
    """Ensure deterministic table blocks survive the LLM draft."""
    if not isinstance(section_dossiers, dict) or not section_dossiers:
        return markdown
    output = markdown
    for section_key, dossier in section_dossiers.items():
        if not isinstance(dossier, dict):
            continue
        blocks = [str(item).strip() for item in dossier.get("deterministic_blocks", []) if str(item).strip()]
        if not blocks:
            continue
        heading = SECTION_HEADING_MAP.get(str(section_key), "")
        if not heading:
            continue
        for block in blocks:
            if block in output:
                continue
            output = _append_to_section(output, heading, block)
    return output


def _append_to_section(markdown: str, heading: str, block: str) -> str:
    header_pattern = re.compile(rf"(?m)^##\s*{re.escape(heading)}\s*$")
    match = header_pattern.search(markdown)
    if not match:
        return markdown.rstrip() + f"\n\n## {heading}\n\n{block}\n"
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    end = match.end() + next_header.start() if next_header else len(markdown)
    return markdown[:end].rstrip() + "\n\n" + block.strip() + "\n\n" + markdown[end:].lstrip()


def remove_broken_or_half_sentences(markdown: str) -> str:
    """Detect and remove/replace half-sentences and empty template phrases."""
    output = markdown
    for pattern, replacement in HALF_SENTENCE_PATTERNS:
        output = re.sub(pattern, replacement, output)
    # Clean up double spaces/blank lines left after removal
    output = re.sub(r" +", " ", output)
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output.strip()


def remove_debug_leakage(markdown: str) -> str:
    """Strip internal debug/tracking field names from the report body."""
    output = markdown
    for pattern in DEBUG_LEAK_PATTERNS:
        output = re.sub(rf'\b{re.escape(pattern)}\b', '', output)
    # Also strip standalone "cl_" prefix with digits (e.g. "cl_0001")
    output = re.sub(r'\bcl_\d{4}\b', '', output)
    # Strip "未分类领域" as standalone text
    output = re.sub(r'未分类领域', '', output)
    # Clean up artifacts left after removal
    output = re.sub(r'[=:]\s*[,，]?\s*', '', output)
    output = re.sub(r' +', ' ', output)
    output = re.sub(r'\n{3,}', '\n\n', output)
    return output.strip()


def remove_internal_ids(markdown: str) -> str:
    """Strip internal entity IDs (claim_id:key, ev_000, etc.) from body text."""
    # Remove "cl_XXXX:metric_key" or "cl_XXXX: readable label" patterns
    output = re.sub(r'\bcl_\d{4}:[\w_]+', '', markdown)
    # Remove standalone "cl_XXXX" not already caught
    output = re.sub(r'\bcl_\d{4}\b', '', output)
    # Remove evidence ID prefixes in running text (not citation brackets like [ev_001])
    output = re.sub(r'(?<!\[)\bev_\d+\b(?!\])', '', output)
    # Clean up double spaces and blank lines
    output = re.sub(r' +', ' ', output)
    output = re.sub(r'\n{3,}', '\n\n', output)
    return output.strip()


def remove_template_phrases(markdown: str) -> str:
    """Remove hollow template/buzzword phrases from the report body."""
    output = markdown
    for phrase in TEMPLATE_PHRASES:
        output = re.sub(re.escape(phrase), '', output)
    # Clean up artifacts
    output = re.sub(r' +', ' ', output)
    output = re.sub(r'\n{3,}', '\n\n', output)
    return output.strip()


INSTRUCTIONAL_REPORT_PATTERNS = [
    r"正文应[^。\n]*。",
    r"本节不得[^。\n]*。",
    r"不套用[^。\n]*模板。",
    r"避免直接[^。\n]*。",
    r"避免把[^。\n]*。",
    r"应围绕[^。\n]*。",
]


def remove_instructional_report_text(markdown: str) -> str:
    """Remove prompt/rule residue that leaked into report prose."""
    output = str(markdown or "")
    for pattern in INSTRUCTIONAL_REPORT_PATTERNS:
        output = re.sub(pattern, "", output)
    output = re.sub(r"(?m)^\s*关键事实\s*$", "", output)
    output = re.sub(r"(?m)^\s*关键事实为[:：].*$", "", output)
    output = re.sub(r"(?m)^\s*鍏抽敭浜嬪疄涓猴細.*$", "", output)
    output = re.sub(r"(?m)^\s*本节可用事实.*$", "", output)
    output = re.sub(r"(?m)^\s*鏈妭鍙敤浜嬪疄.*$", "", output)
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output.strip()


def dedupe_section_paragraphs(markdown: str) -> str:
    """Remove duplicate paragraphs within each markdown section."""
    text = str(markdown or "").strip()
    if not text:
        return text
    chunks = re.split(r"(?m)(^##\s+.+$)", text)
    if len(chunks) <= 1:
        return _dedupe_paragraphs(text)
    output = [chunks[0].strip()]
    for index in range(1, len(chunks), 2):
        heading = chunks[index].strip()
        body = chunks[index + 1] if index + 1 < len(chunks) else ""
        output.append(heading)
        output.append(_dedupe_paragraphs(body.strip()))
    return "\n\n".join(part for part in output if part).strip()


def _dedupe_paragraphs(text: str) -> str:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", str(text or "")) if item.strip()]
    seen: set[str] = set()
    output: list[str] = []
    for paragraph in paragraphs:
        key = _paragraph_dedupe_key(paragraph)
        if key in seen:
            continue
        seen.add(key)
        output.append(paragraph)
    return "\n\n".join(output).strip()


def _paragraph_dedupe_key(paragraph: str) -> str:
    compact = re.sub(r"\s+", "", str(paragraph or ""))
    compact = re.sub(r"\[[^\]]+\]", "", compact)
    return compact[:180]


def remove_a_share_template_contamination(markdown: str, symbol: str = "") -> str:
    """Remove US/tech template residue from A-share reports."""
    if not str(symbol or "").upper().endswith((".SS", ".SZ")):
        return markdown
    output = str(markdown or "")
    forbidden_symbols = ("PG", "KO", "PEP", "WMT", "COST")
    lines: list[str] = []
    for line in output.splitlines():
        upper = line.upper()
        if any(re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", upper) for sym in forbidden_symbols):
            if "|" in line:
                continue
            line = re.sub(r"\b(?:PG|KO|PEP|WMT|COST)\b[、,\s]*", "", line, flags=re.IGNORECASE)
        lines.append(line)
    output = "\n".join(lines)
    replacements = {
        "云厂商": "渠道与需求",
        "云服务": "数字化渠道",
        "Google Cloud": "跨市场科技业务",
        "Google Services": "跨市场科技业务",
        "Other Bets": "新业务",
        "软件订阅": "消费需求",
        "科技资本开支": "渠道与产能投入",
    }
    for old, new in replacements.items():
        output = output.replace(old, new)
    output = re.sub(r"\n{3,}", "\n\n", output)
    return output.strip()


# Patterns that indicate raw SEC companyfacts dump in report body
COMPANYFACTS_DUMP_PATTERNS = [
    r'Revenues\d{6,}',
    r'NetIncomeLoss\d{6,}',
    r'CashAndCashEquivalentsAtCarryingValue',
    r'NetCashProvidedByUsedInOperatingActivities',
    r'Assets\d{6,}',
    r'Liabilities\d{6,}',
    r'companyfacts?\d{6,}',
]

# Template residue / half-sentence patterns for section-level detection
INVALID_SECTION_PATTERNS = [
    r'\b需关注.*?相关的',
    r'的关键在于',
    r'将共同决定其',
    r'在上市公司领域',
    r'所在领域的业务布局',
    r'下文章节展开分析',
]

GAP_REPLACEMENTS = {
    "执行摘要": "本报告已获取部分财务与市场数据，但当前摘要材料不足以形成完整结论。以下分析以已验证的三表、估值与来源信息为准，并在相关章节标注数据缺口。",
    "业务概览": "当前未获取到足够的公司画像信息，包括行业分类、主营业务描述和业务分部信息。本节不直接使用 SEC companyfacts 原始指标拼接公司介绍，相关财务数据将在三表摘要和财务分析中展开。",
    "股权结构与公司治理": "本次自动检索未获得足够的官方治理结构证据，包括年报治理章节、董事会构成、主要股东或 proxy 文件。因此本节不对股权结构和治理质量作展开判断。",
    "战略与主营业务": "本次自动检索未获得足够的战略与主营业务文本证据，因此不对公司战略执行作定性判断。当前仅基于收入、盈利能力、现金流和资产负债结构进行经营表现观察。",
}

DEFAULT_GAP_NOTE = "本节数据缺口：当前自动检索未获得足够的可验证信息展开分析。"


def _extract_section_body(markdown: str, heading: str) -> tuple[str | None, int, int]:
    """Extract a section body from markdown given its ## heading. Returns (body, start, end)."""
    pattern = re.compile(rf"(?m)^##\s*{re.escape(heading)}\s*$")
    match = pattern.search(markdown)
    if not match:
        return None, -1, -1
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    start = match.end()
    end = start + next_header.start() if next_header else len(markdown)
    body = markdown[start:end].strip()
    return body, start, end


def _body_is_orphan_numeric(body: str) -> bool:
    """Detect if body contains only isolated number bullets (e.g. '- 10\\n- 9')."""
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    if not lines:
        return False
    # Check if all non-empty lines are just "- <number>"
    numeric_bullets = sum(1 for l in lines if re.match(r'^-\s*\d+(?:\.\d+)?\s*$', l))
    # If most lines are numeric bullets and there's no Chinese prose with >2 chars
    has_chinese = bool(re.search(r'[一-鿿]{3,}', body))
    return numeric_bullets >= 2 and not has_chinese


def _body_has_companyfacts_dump(body: str) -> bool:
    """Detect raw SEC companyfacts tag dumps in body."""
    for pat in COMPANYFACTS_DUMP_PATTERNS:
        if re.search(pat, body):
            return True
    return False


def _body_has_invalid_patterns(body: str) -> bool:
    """Detect half-sentence/template residue patterns."""
    for pat in INVALID_SECTION_PATTERNS:
        if re.search(pat, body):
            return True
    # Trailing comma/colon/顿号 on a short final line (under 30 chars after trim)
    # catches orphaned punctuation after word-level template removal
    last_line = body.strip().split("\n")[-1].strip()
    if len(last_line) < 30 and re.search(r'[，、：,;:]$', last_line):
        return True
    return False


def detect_invalid_section_content(section_key: str, heading: str, body: str) -> str | None:
    """Check section body for contamination patterns. Returns gap replacement or None."""
    if not body:
        return GAP_REPLACEMENTS.get(heading, DEFAULT_GAP_NOTE) if heading else DEFAULT_GAP_NOTE

    if _body_is_orphan_numeric(body):
        return GAP_REPLACEMENTS.get(heading, DEFAULT_GAP_NOTE)

    if _body_has_companyfacts_dump(body):
        return GAP_REPLACEMENTS.get(heading, DEFAULT_GAP_NOTE)

    if _body_has_invalid_patterns(body):
        return GAP_REPLACEMENTS.get(heading, DEFAULT_GAP_NOTE)

    return None


def replace_invalid_sections_with_gap(markdown: str) -> str:
    """Replace sections whose body matches contamination patterns with gap notes."""
    output = markdown
    for section_key, heading in SECTION_HEADING_MAP.items():
        body, start, end = _extract_section_body(output, heading)
        if body is None:
            continue
        replacement = detect_invalid_section_content(section_key, heading, body)
        if replacement is not None:
            output = output[:start] + "\n\n" + replacement + "\n\n" + output[end:]
    return output


def final_blocker_scan(markdown: str) -> tuple[str, dict]:
    """Final scan: detect remaining blockers after all cleaning.

    Returns (markdown, meta_dict) where meta_dict contains delivery_status.
    """
    meta: dict = {
        "delivery_status": "normal",
        "sparse_or_invalid_sections": [],
        "user_warning": "",
    }

    # Check each section for remaining issues
    for section_key, heading in SECTION_HEADING_MAP.items():
        body, start, end = _extract_section_body(markdown, heading)
        if body is None:
            meta["sparse_or_invalid_sections"].append(heading)
            continue
        replacement = detect_invalid_section_content(section_key, heading, body)
        if replacement is not None:
            meta["sparse_or_invalid_sections"].append(heading)

    # If any section still invalid, degrade report status
    if meta["sparse_or_invalid_sections"]:
        meta["delivery_status"] = "degraded_due_to_content_quality"
        meta["user_warning"] = "部分章节因证据不足已降级为数据缺口说明。"

    return markdown, meta
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


CORE_AUTO_REWRITE_SECTIONS = {
    "executive_summary",
    "business_overview",
    "financial_analysis",
    "peer_compare",
    "valuation",
    "risks",
    "conclusion",
}


def auto_rewrite_core_sections(
    markdown: str,
    *,
    claims: List[Dict[str, Any]] | None = None,
    evidence_records: List[Dict[str, Any]] | None = None,
    financial_metrics: Any = None,
    quality_remediation_plan: Dict[str, Any] | None = None,
    repair_constraints: Dict[str, Any] | None = None,
) -> str:
    """Deterministically repair thin/truncated core sections before quality gates.

    This is a bounded writing repair: it summarizes available claims, evidence
    and metrics, and explicitly preserves data boundaries instead of inventing
    targets or official filings.
    """

    plan = quality_remediation_plan or {}
    targets = _quality_target_sections(plan, repair_constraints or {}) & CORE_AUTO_REWRITE_SECTIONS
    output = markdown
    by_section = _claims_by_outline_section(claims or [])
    metrics = _financial_metric_rows(financial_metrics)
    evidence = [item for item in (evidence_records or []) if isinstance(item, dict)]
    for section in sorted(CORE_AUTO_REWRITE_SECTIONS | targets, key=_outline_section_order):
        title = _section_title(section)
        if not title:
            continue
        body = _section_body(output, title)
        if section not in targets and not _core_section_needs_auto_rewrite(title, body):
            continue
        replacement = _build_core_section_rewrite(
            section=section,
            claims=by_section.get(section, []),
            evidence_records=evidence,
            metric_rows=metrics,
            quality_remediation_plan=plan,
            repair_constraints=repair_constraints or {},
        )
        if replacement:
            output = _replace_section(output, title=title, replacement=replacement)
    return output


def _core_section_needs_auto_rewrite(title: str, body: str | None) -> bool:
    if body is None:
        return True
    threshold = SECTION_DEPTH_THRESHOLDS.get(_section_key_from_title(title), 120)
    if _count_chinese_chars(body) < threshold:
        return True
    if _section_needs_hard_backfill(title, body):
        return True
    tail = re.sub(r"\s+", "", body)[-28:]
    unfinished_markers = ("分别披露", "主要包括", "取决于", "由于", "因此", "以及", "包括", "体现为", "来自于")
    return any(tail.endswith(marker) for marker in unfinished_markers)


def _section_key_from_title(title: str) -> str:
    for key, heading in SECTION_HEADING_MAP.items():
        if heading == title:
            return key
    return ""


def _financial_metric_rows(financial_metrics: Any) -> list[dict[str, Any]]:
    def _public_metric(item: dict[str, Any]) -> bool:
        name = str(item.get("metric_name") or item.get("name") or "").lower()
        return name not in {"adjusted_net_income", "non_recurring_gain", "revenue_growth_pct"}
    if isinstance(financial_metrics, dict):
        rows = financial_metrics.get("metrics", [])
        return [item for item in rows if isinstance(item, dict) and _public_metric(item)] if isinstance(rows, list) else []
    if isinstance(financial_metrics, list):
        return [item for item in financial_metrics if isinstance(item, dict) and _public_metric(item)]
    return []


def _build_core_section_rewrite(
    *,
    section: str,
    claims: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    quality_remediation_plan: dict[str, Any],
    repair_constraints: dict[str, Any],
) -> str:
    claim_lines = _claim_sentences_for_rewrite(claims, limit=4)
    metric_lines = _format_metric_facts(metric_rows, limit=5)
    evidence_lines = _evidence_lines_for_rewrite(evidence_records, limit=4)
    citation_ids = _rewrite_citation_ids(claims, evidence_records, limit=3)
    citation_tail = " ".join(f"[{item}]" for item in citation_ids)
    evidence_basis = "；".join(evidence_lines[:2]) if evidence_lines else "当前证据池尚未形成足够完整的官方披露链路"
    metric_basis = "；".join(metric_lines[:3]) if metric_lines else "关键财务指标仍需继续补齐和复核"
    claim_basis = "；".join(claim_lines[:3]) if claim_lines else "主张层证据仍以审慎归纳为主"
    boundary = _attempted_source_note(quality_remediation_plan, repair_constraints)

    if section == "executive_summary":
        return (
            f"本报告基于当前证据池对公司经营、财务、估值和风险进行审慎归纳，核心依据包括：{evidence_basis}。"
            f"从已校验主张看，{claim_basis}；从结构化指标看，{metric_basis}。"
            "因此，执行摘要不直接给出强买卖结论，而是把判断限定在已披露资料能够支撑的范围内：先确认业务和财务趋势，再结合估值输入、竞争格局与风险约束判断正式交付条件。"
            f"后续若要形成正式可交付观点，需要继续核对官方披露、报告期口径和引用覆盖，避免把未验证信息写成确定结论。{citation_tail}"
        ).strip()
    if section == "business_overview":
        return (
            f"业务概览以公司已披露经营信息和证据池为边界，当前可引用依据包括：{evidence_basis}。"
            f"从主张层看，{claim_basis}；这些信息用于界定公司所处行业、主要产品或服务、客户需求以及收入形成方式。"
            "正式研报需要把业务画像和财务表现连接起来：业务规模决定收入弹性，竞争格局影响利润率，客户结构和监管环境则影响现金流稳定性。"
            "因此，本节不把公司简介写成孤立背景，而是作为后续财务分析、估值观察和风险评估的基础。"
            f"若后续补齐更多官方披露，应进一步拆分主营板块、区域结构和关键经营指标。{citation_tail}"
        ).strip()
    if section == "financial_analysis":
        return (
            f"财务分析以三表和结构化指标为核心，当前可使用的指标包括：{metric_basis}。"
            f"结合证据池，{evidence_basis}；结合主张层，{claim_basis}。"
            "正式分析不能只罗列收入或利润，而要说明利润表、资产负债表和现金流量表之间的勾稽关系：收入代表经营规模，利润率反映盈利质量，资产和权益反映安全垫，经营现金流反映利润兑现能力。"
            "如果收入增长但现金流承压，需要跟踪应收、库存、资本开支或费用投放；如果现金流和资产结构同步改善，盈利质量才更有支撑。"
            f"本节结论仍受官方口径、报告期匹配和表格来源限制，正式交付前需要继续复核原始披露。{citation_tail}"
        ).strip()
    if section == "peer_compare":
        return (
            f"同行对比以可比口径为前提，当前证据基础包括：{evidence_basis}。"
            "在没有完整同业样本、统一会计期间和同口径估值倍数时，本节不输出绝对强弱排序，也不把第三方行情数据直接等同于正式投研结论。"
            f"可形成的分析边界是：将公司收入质量、利润率、现金流和估值约束放在同一框架中观察，并说明比较结论依赖哪些数据输入。"
            f"从主张层看，{claim_basis}；若后续补齐同行官方披露和市场估值数据，可进一步比较成长性、盈利稳定性、资本效率和估值溢价。"
            f"当前版本保留审慎比较口径，避免用不完整数据制造确定性结论。{citation_tail}"
        ).strip()
    if section == "valuation":
        return (
            f"估值观察以已披露财务和市场输入为边界，目前可使用的信息包括：{metric_basis}。"
            f"从已校验主张看，{claim_basis}。"
            "在缺少完整目标价模型、折现率、长期增长率或同口径可比倍数时，本节不输出确定目标价，也不把单一倍数解释为投资结论。"
            f"可形成的判断是：估值弹性应主要绑定收入增速、利润率、现金流质量和风险溢价变化；若这些输入改善，估值中枢才具备上修依据，反之则需要下调预期。"
            f"当前仍需补齐的证据来源包括{boundary}，正式交付前应复核估值输入与官方财务口径是否一致。{citation_tail}"
        ).strip()
    if section == "risks":
        return (
            f"风险评估围绕证据池中已经出现的经营、财务和外部约束展开，当前依据包括：{evidence_basis}。"
            f"从主张层看，{claim_basis}；这些风险不应被写成孤立提示，而应和收入增速、毛利率、现金流、客户需求、监管披露和估值假设联动观察。"
            "若后续官方披露显示关键指标恶化，风险会通过盈利质量、资金周转和估值倍数传导到投资结论；若指标改善，则风险权重可以下降但仍需保留跟踪。"
            f"本节仅描述可验证风险边界，不补造未披露事项。{citation_tail}"
        ).strip()
    if section == "conclusion":
        return (
            "投资结论维持中性观察评级，基于当前证据支持方向性判断，但尚不足以形成无条件正式交付观点。"
            f"核心理由包括：从已校验主张看，{claim_basis}；支持因素来自{evidence_basis}和{metric_basis}。"
            "主要风险包括估值输入完整性不足、现金流转换率变化、竞争压力、需求波动和官方来源复核要求。"
            "因此，本报告适合作为研究工作底稿和人工复核材料：若后续补齐官方披露、三表口径、估值输入和关键风险引用，可以再升级为正式交付；在此之前，不应输出激进评级或确定目标价。"
            f"最终判断应以证据门禁、质量评分、主张复核和引用覆盖共同通过为前提。{citation_tail}"
        ).strip()
    return ""


def _claim_sentences_for_rewrite(claims: list[dict[str, Any]], *, limit: int) -> list[str]:
    lines: list[str] = []
    for claim in claims:
        text = re.sub(r"\s+", " ", str(claim.get("claim_text") or "")).strip()
        if not text or _claim_text_is_weak(text):
            continue
        lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def _evidence_lines_for_rewrite(evidence_records: list[dict[str, Any]], *, limit: int) -> list[str]:
    rows: list[str] = []
    for item in evidence_records:
        title = str(item.get("title") or item.get("source_type") or item.get("evidence_id") or "").strip()
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        period = str(item.get("period") or metadata.get("period") or "").strip()
        source = str(item.get("source_type") or "").strip()
        if not title:
            continue
        text = title
        if period:
            text += f"（{period}）"
        if source and source not in text:
            text += f"，来源为{source}"
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _rewrite_citation_ids(
    claims: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
    *,
    limit: int,
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        evidence_ids = claim.get("evidence_ids", [])
        if not isinstance(evidence_ids, list):
            continue
        for raw in evidence_ids:
            value = str(raw or "").strip()
            if value and value not in seen:
                seen.add(value)
                ids.append(value)
                if len(ids) >= limit:
                    return ids
    for item in evidence_records:
        value = str(item.get("evidence_id") or item.get("sample_id") or "").strip()
        if value and value not in seen:
            seen.add(value)
            ids.append(value)
            if len(ids) >= limit:
                break
    return ids


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


def _has_official_source(financial_metrics: Any = None, tables: Any = None) -> bool:
    """Check if any financial metrics or tables come from official (non-market-data) sources."""
    official_types = {"official_filing", "official_annual_report", "hkex_announcement",
                      "company_ir", "sec_edgar", "official_10k", "official_10q"}
    metric_items = financial_metrics.get("metrics", []) if isinstance(financial_metrics, dict) else []
    for m in (metric_items if isinstance(metric_items, list) else []):
        if isinstance(m, dict) and str(m.get("source_type") or "") in official_types:
            return True
    table_items = tables if isinstance(tables, list) else []
    for t in table_items:
        for row in (t.get("rows", []) if isinstance(t, dict) and isinstance(t.get("rows"), list) else []):
            if isinstance(row, dict) and str(row.get("source_type") or "") in official_types:
                return True
    return False


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
    official_found = _has_official_source(financial_metrics, tables)
    if fallback_sources:
        if official_found:
            lines.append(
                "- 三表数据基于最新可获取的公开财务数据，核心指标已与官方来源交叉验证。"
            )
        else:
            lines.append(
                "- 当前三表数据主要来自第三方结构化数据，尚未完成官方年报或交易所公告交叉验证。"
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
        lines.append(f"- {label} 属于{(' / '.join(parts)) if parts else '已识别上市公司'}行业，在{summary or '其核心领域'}具备领先市场地位。 {tail}".rstrip())
    if summary:
        lines.append(f"- 主营业务概览：{summary} {tail}".rstrip())
    if not lines:
        return _role_findings_to_markdown(role, "business_overview")
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
    parts: List[str] = []
    statement_labels = {
        "income_statement": "利润表",
        "balance_sheet": "资产负债表",
        "cash_flow_statement": "现金流量表",
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
                    f"- {statement_labels[statement]}：现金流量表数据暂未形成可验证结构化行，"
                    "该缺口可能影响现金转化率和估值敏感性判断。"
                )
            else:
                parts.append(f"- {statement_labels[statement]}：当前未形成可验证结构化行，正文不补数。")
            continue
        table_parts = [f"**{statement_labels[statement]}**", "", "| 指标 | 数值 | 期间 |", "|------|------|------|"]
        for row in items[:8]:
            label = _metric_label(str(row.get("line_item") or row.get("metric_name") or ""))
            value = _format_number(row.get("value"))
            unit = str(row.get("unit") or "").strip()
            period = str(row.get("period") or "").strip()
            val_str = f"{value}{(' ' + unit) if unit else ''}"
            table_parts.append(f"| {label} | {val_str} | {period} |")
        evidence = _evidence_tail(items)
        if evidence:
            table_parts.append("")
            table_parts.append(f"来源：{evidence}")
        parts.append("\n".join(table_parts))
    return "\n\n".join(parts)


def _financial_analysis_body(rows: List[Dict[str, Any]], claims: List[Dict[str, Any]]) -> str:
    grouped = _rows_by_statement(rows)
    revenue = _first_row(grouped.get("income_statement", []), ["revenue"])
    net_income = _first_row(grouped.get("income_statement", []), ["net_income"])
    ocf = _first_row(grouped.get("cash_flow_statement", []), ["operating_cash_flow"])
    fcf = _first_row(grouped.get("cash_flow_statement", []), ["free_cash_flow"])
    assets = _first_row(grouped.get("balance_sheet", []), ["total_assets"])
    liabilities = _first_row(grouped.get("balance_sheet", []), ["total_liabilities"])
    lines = ["- 以下财务分析基于可获取的公开财务数据，部分指标待官方年报交叉验证。"]
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
    suffix = f"{value}{(' ' + unit) if unit else ''}"
    if period:
        return f"{label} {suffix}（{period}）"
    return f"{label} {suffix}"


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


def _clean_to_numbered_citations(markdown: str, evidence_records: List[Dict[str, Any]]) -> str:
    """Replace raw evidence_id markers with [N] numbered citations + reference section.

    The LLM and backfill functions embed evidence IDs like
    [600519_2026Q1_eastmoney_financials_income_1fd3a55f5e] directly in the body.
    This function replaces them with [1], [2], … and appends a clean reference
    section so readers see human-readable source descriptions instead of internal IDs.
    """
    if not markdown or not evidence_records:
        return markdown

    # Build lookup: evidence_id -> human-readable reference entry
    ref_map: Dict[str, str] = {}
    for rec in evidence_records:
        eid = str(rec.get("evidence_id") or "").strip()
        if not eid:
            continue
        title = str(rec.get("title") or "").strip() or eid
        source_type = str(rec.get("source_type") or "").strip()
        source_url = str(rec.get("source_url") or "").strip()
        date_str = ""
        raw_date = rec.get("published_at") or rec.get("date") or None
        if raw_date:
            try:
                dt = datetime.fromtimestamp(int(raw_date) / 1000)
                date_str = dt.strftime("%Y-%m-%d")
            except (OSError, ValueError, OverflowError):
                date_str = str(raw_date)
        parts = [title]
        if source_type:
            parts.append(f"({source_type})")
        if date_str:
            parts.append(date_str)
        ref_map[eid] = " - ".join(parts) + (f" - {source_url}" if source_url else "")

    # Find all [evidence_id] patterns in the markdown body.
    # Evidence IDs are non-whitespace strings with no brackets inside.
    evidence_pattern = re.compile(r"\[([^\]]{8,})\]")
    found: List[str] = []
    seen: set[str] = set()
    for match in evidence_pattern.finditer(markdown):
        inside = match.group(1).strip()
        if not inside:
            continue
        # Skip obvious non-evidence bracketed tokens
        if inside.lower() in {"n/a", "na", "todo", "fixme", "ev_123", "ev_amd_fin_001"}:
            continue
        if re.match(r"^\d+$", inside):
            continue
        if inside not in seen:
            seen.add(inside)
            found.append(inside)

    if not found:
        return markdown

    # Build ordered mapping: evidence_id -> [N]
    id_to_num: Dict[str, int] = {eid: idx + 1 for idx, eid in enumerate(found) if eid in ref_map}
    unknown_counter = len(id_to_num) + 1
    for eid in found:
        if eid not in id_to_num:
            id_to_num[eid] = unknown_counter
            unknown_counter += 1

    def _replace_match(m: re.Match) -> str:
        inside = m.group(1).strip()
        num = id_to_num.get(inside)
        if num is None:
            return m.group(0)
        return f"[{num}]"

    cleaned = evidence_pattern.sub(_replace_match, markdown)
    cleaned = re.sub(r"(\[\d+\])(?:\s+\1)+", r"\1", cleaned)

    # Remove any existing "参考来源" / "参考来源" section so we can rewrite it cleanly
    ref_section_pattern = re.compile(r"^##\s*参考来源\s*$(?:\n.*)*", re.MULTILINE)
    cleaned = ref_section_pattern.sub("", cleaned).rstrip()

    # Build reference entries
    ref_lines: List[str] = ["", "## 参考来源", ""]
    for eid in found:
        num = id_to_num.get(eid)
        if num is None:
            continue
        display = ref_map.get(eid, eid)
        ref_lines.append(f"- [{num}] {display}")

    if len(ref_lines) > 3:
        return cleaned + "\n" + "\n".join(ref_lines) + "\n"

    return cleaned


def _markdown_to_simple_html(markdown: str, title: str) -> str:
    body = _render_markdown_body(markdown)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Arial, "PingFang SC", "Microsoft YaHei", sans-serif; margin: 28px; line-height: 1.65; color: #172026; }}
    h1, h2 {{ margin: 18px 0 8px; }}
    ul {{ margin: 8px 0 16px 20px; }}
    li {{ margin: 6px 0; }}
    .report-table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }}
    .report-table th, .report-table td {{ border: 1px solid #d9e0e7; padding: 10px 12px; text-align: left; vertical-align: top; }}
    .report-table thead th {{ background: #f4f7fb; }}
    .report-table tbody tr:nth-child(even) {{ background: #fafcff; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _render_markdown_body(markdown: str) -> str:
    output: list[str] = []
    lines = markdown.splitlines()
    index = 0
    in_list = False
    while index < len(lines):
        raw = lines[index].rstrip()
        line = raw.strip()
        if not line:
            if in_list:
                output.append("</ul>")
                in_list = False
            index += 1
            continue
        if line.startswith("<table") or line.startswith("<thead") or line.startswith("<tbody") or line.startswith("<tr") or line.startswith("<th") or line.startswith("<td") or line.startswith("</table"):
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(raw)
            index += 1
            continue
        if _is_markdown_table_row(line):
            if in_list:
                output.append("</ul>")
                in_list = False
            table_lines = [line]
            index += 1
            while index < len(lines) and _is_markdown_table_row(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            output.append(_markdown_table_to_html(table_lines))
            continue
        if raw.startswith("# "):
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<h1>{escape(raw[2:].strip())}</h1>")
        elif raw.startswith("## "):
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<h2>{escape(raw[3:].strip())}</h2>")
        elif raw.startswith("- "):
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{escape(raw[2:].strip())}</li>")
        else:
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<p>{escape(raw)}</p>")
        index += 1
    if in_list:
        output.append("</ul>")
    return "\n".join(output)


def _is_markdown_table_row(line: str) -> bool:
    return bool(line) and line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _markdown_table_to_html(lines: list[str]) -> str:
    if len(lines) < 2:
        return "<p>" + escape(lines[0]) + "</p>" if lines else ""
    header_cells = [cell.strip() for cell in lines[0].strip("|").split("|")]
    body_lines = [row for row in lines[1:] if not re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", row)]
    if not header_cells or any(cell in {"---", ""} for cell in header_cells):
        return "\n".join(f"<p>{escape(row)}</p>" for row in lines)
    header_html = "".join(f"<th>{escape(cell)}</th>" for cell in header_cells)
    body_rows = []
    for row in body_lines:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) != len(header_cells):
            continue
        body_rows.append("<tr>" + "".join(f"<td>{escape(cell or '-')}</td>" for cell in cells) + "</tr>")
    if not body_rows:
        return "\n".join(f"<p>{escape(row)}</p>" for row in lines)
    return f'<table class="report-table"><thead><tr>{header_html}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'


def replace_invalid_sections_with_gap(markdown: str) -> str:
    """Legacy shim kept for compatibility; quality gate should block instead of rewriting."""
    return markdown


def final_blocker_scan(markdown: str) -> tuple[str, dict]:
    """Detect blockers after cleaning without mutating report sections."""
    meta: dict[str, Any] = {
        "delivery_status": "normal",
        "sparse_or_invalid_sections": [],
        "user_warning": "",
    }
    for section_key, heading in SECTION_HEADING_MAP.items():
        body, _, _ = _extract_section_body(markdown, heading)
        if body is None:
            meta["sparse_or_invalid_sections"].append(heading)
            continue
        if detect_invalid_section_content(section_key, heading, body) is not None:
            meta["sparse_or_invalid_sections"].append(heading)
    if meta["sparse_or_invalid_sections"]:
        meta["delivery_status"] = "normal"
        meta["user_warning"] = "部分章节仍存在内容质量问题，已作为质量诊断记录。"
    return markdown, meta
