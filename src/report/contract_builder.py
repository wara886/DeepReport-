"""Contract Builder: transforms evidence, PDF summaries, and analysis artifacts
into ReportSectionContracts.

This is the core of contract-first generation. Every section's allowed/forbidden
evidence sources, structured facts, and blocked reasons are determined here,
BEFORE FinalAnswerAgent runs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from src.report.section_contracts import (
    ALLOWED_QUALITATIVE_PDF_ONLY,
    ALLOWED_FINANCIAL,
    ALLOWED_FINANCIAL_TABLES_ONLY,
    FORBIDDEN_SECTION_SOURCE_TYPES,
    PeerGroupDef,
    ReportSectionContracts,
    SectionEvidenceContract,
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_ANNUAL_REPORT_PDF_CHUNK,
    SRC_OFFICIAL_FILING,
    SRC_SEC_EDGAR,
    SRC_SEC_10K_FILING,
    SRC_SEC_10K_SECTION,
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_FINANCIAL_METRIC,
    SRC_THIRD_PARTY_STRUCTURED,
    SRC_PEER_DATA,
    SRC_MARKET_DATA,
    SRC_VALUATION_MODEL,
    SRC_INDUSTRY_POLICY,
    SRC_YAHOO_PROFILE,
    SRC_WEB_SEARCH,
    clean_pdf_boilerplate,
    text_contains_pdf_boilerplate,
    text_contains_fragments,
    SECTION_TITLES,
)
from src.utils.money import CurrencyContext, build_currency_context, format_amount_for_context

# ── Public API ───────────────────────────────────────────────────────────

# SEC 10-K Item to report section mapping for US market
SEC_ITEM_TO_SECTION = {
    "business": "business_overview",
    "risk_factors": "risk_factors",
    "mda": "strategy_business",
    "financial_statements": "three_statement_summary",
    "governance": "ownership_governance",
    "security_ownership": "ownership_governance",
}


def _clip_at_sentence_boundary(text: str, max_chars: int) -> str:
    """Trim long evidence text without cutting a sentence or Chinese phrase."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    head = cleaned[:max_chars].rstrip()
    sentence_end = max(head.rfind(mark) for mark in ["。", "！", "？", ".", "!", "?", ";", "；"])
    if sentence_end >= max(40, int(max_chars * 0.55)):
        return head[: sentence_end + 1].strip()
    clause_end = max(head.rfind(mark) for mark in ["，", ",", "、", ":", "："])
    if clause_end >= max(40, int(max_chars * 0.65)):
        return head[: clause_end].strip() + "。"
    return head.strip() + "。"


def _clean_and_clip_pdf_text(text: str, max_chars: int) -> str:
    return _clip_at_sentence_boundary(clean_pdf_boilerplate(text), max_chars)


def _get_annual_report_sections(
    state: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract SEC 10-K annual_report_sections from state or analysis_artifacts.

    The data can be stored as either:
      - A list of section dicts (legacy format)
      - A dict with a "sections" key containing {section_key: [{text, ...}, ...]}
      - A dict with sections directly at top level
    """
    raw = state.get("annual_report_sections") or analysis_artifacts.get("annual_report_sections") or {}
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        # New format: {"sections": {"business": [{...}, ...], "risk_factors": [{...}], ...}}
        sections_map = raw.get("sections") if isinstance(raw.get("sections"), dict) else raw
        if isinstance(sections_map, dict):
            flat: List[Dict[str, Any]] = []
            for section_key, items in sections_map.items():
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            item["section_key"] = item.get("section_key") or section_key
                            flat.append(item)
            if flat:
                return flat
    # Legacy fallback
    ar = analysis_artifacts.get("annual_report", {})
    if isinstance(ar, dict):
        secs = ar.get("sections", [])
        if isinstance(secs, list):
            return secs
    return []


def _get_annual_report_text_by_sec_item(
    annual_report_sections: List[Dict[str, Any]],
    item_keys: Set[str],
) -> List[Dict[str, Any]]:
    """Filter annual_report_sections by SEC Item keys (e.g. 'business', 'risk_factors').

    Returns list of dicts with 'text', 'evidence_id', 'section_item' keys.
    """
    results: List[Dict[str, Any]] = []
    for sec in annual_report_sections:
        if not isinstance(sec, dict):
            continue
        sk = str(sec.get("section_key") or sec.get("item_key") or sec.get("section_type") or "").lower().strip()
        if sk not in item_keys:
            continue
        text = str(sec.get("content") or sec.get("text") or sec.get("summary") or "")
        if len(text.strip()) < 50:
            continue
        eid = str(sec.get("evidence_id") or sec.get("id") or "")
        results.append({
            "text": text,
            "evidence_id": eid,
            "section_item": sk,
        })
    return results


def build_report_section_contracts(
    state: Dict[str, Any],
    evidence_records: List[Dict[str, Any]],
    analysis_artifacts: Dict[str, Any],
    section_dossiers: Dict[str, Any],
    citations: List[Dict[str, Any]],
) -> ReportSectionContracts:
    """Build all section contracts from the current state.

    Inputs (all optional / best-effort):
    - state: orchestrator state (symbol, period, entity_resolution, etc.)
    - evidence_records: all evidence records (including PDF summaries as records)
    - analysis_artifacts: financial_metrics, tables, valuation_model, etc.
    - section_dossiers: existing SectionDossierBuilder output (legacy)
    - citations: existing citation list (legacy, will be replaced)
    """
    contracts = ReportSectionContracts()

    # Metadata
    symbol = str(state.get("symbol", "") or "")
    period = str(state.get("period", "") or "")
    contracts.metadata["target_symbol"] = symbol
    contracts.metadata["target_period"] = period
    currency_context = _currency_context(state, analysis_artifacts)
    contracts.metadata["currency_context"] = currency_context.to_dict()

    # Extract PDF section summaries (both from analysis_artifacts and state)
    pdf_section_summaries = _get_pdf_section_summaries(state, analysis_artifacts)
    pdf_section_chunks = _get_pdf_section_chunks(state, analysis_artifacts)
    contracts.metadata["pdf_rag_available"] = bool(pdf_section_summaries) or bool(pdf_section_chunks)

    # Extract SEC 10-K annual report sections (US market)
    annual_report_sections = _get_annual_report_sections(state, analysis_artifacts)
    contracts.metadata["sec_annual_report_sections_available"] = bool(annual_report_sections)

    # Extract financial data
    financial_metrics = _safe_dict(analysis_artifacts, "financial_metrics")
    tables = _safe_list(analysis_artifacts, "tables")
    claims = _safe_list(analysis_artifacts, "claims") or _safe_list(state, "claims")
    financial_evidence_ids = _financial_evidence_ids(financial_metrics, tables, claims)
    valuation_model = _safe_dict(analysis_artifacts, "valuation_model")
    valuation_sensitivity = _safe_dict(analysis_artifacts, "valuation_sensitivity")
    peer_data = _safe_dict(analysis_artifacts, "peer_analysis")

    # Extract peer info from state/blackboard
    blackboard = _safe_dict(state, "research_blackboard")
    peer_rows = _get_peer_rows(state, analysis_artifacts, blackboard)

    # Period detection
    period_info = _detect_period(state, evidence_records, financial_metrics, tables)
    contracts.metadata.update(period_info)

    # ── Build each section contract ──
    _build_executive_summary(contracts, evidence_records, financial_metrics, section_dossiers, financial_evidence_ids)
    _build_business_overview(contracts, pdf_section_summaries, pdf_section_chunks,
                             evidence_records, analysis_artifacts, state, section_dossiers,
                             annual_report_sections=annual_report_sections)
    _build_ownership_governance(contracts, pdf_section_summaries, pdf_section_chunks,
                                evidence_records, state,
                                annual_report_sections=annual_report_sections)
    _build_strategy_business(contracts, pdf_section_summaries, pdf_section_chunks,
                             evidence_records, financial_metrics, analysis_artifacts,
                             annual_report_sections=annual_report_sections)
    _build_three_statement_summary(contracts, financial_metrics, tables, financial_evidence_ids, currency_context)
    _build_financial_analysis(contracts, financial_metrics, tables, evidence_records, section_dossiers, financial_evidence_ids, currency_context)
    _build_peer_compare(contracts, peer_rows, analysis_artifacts, blackboard, symbol, section_dossiers)
    _build_valuation(contracts, valuation_model, financial_metrics, financial_evidence_ids, currency_context, section_dossiers)
    _build_valuation_sensitivity(contracts, valuation_model, valuation_sensitivity)
    _build_risk_factors(contracts, pdf_section_summaries, pdf_section_chunks,
                        evidence_records, analysis_artifacts, state,
                        annual_report_sections=annual_report_sections,
                        claims=claims)
    _build_investment_conclusion(contracts, financial_metrics, valuation_model, evidence_records, financial_evidence_ids)
    _build_period_note(contracts, period_info)
    _build_currency_data_quality(contracts, analysis_artifacts)

    # Run cross-section quality checks
    _check_contract_quality(contracts)

    # ── PDF raw fallback for gap sections ─────────────────────────────────
    # When all structured extraction fails but PDF data exists, use raw text
    # rather than leaving sections empty. The LLM rewrite (Fix 4) can clean it.
    _apply_pdf_fallback(contracts, pdf_section_summaries, pdf_section_chunks, evidence_records)

    return contracts


# ── Section builders ────────────────────────────────────────────────────


def _build_executive_summary(
    contracts: ReportSectionContracts,
    evidence_records: List[Dict[str, Any]],
    financial_metrics: Dict[str, Any],
    section_dossiers: Dict[str, Any],
    financial_evidence_ids: List[str],
) -> None:
    c = contracts.ensure("executive_summary")
    c.allowed_source_types = list(ALLOWED_FINANCIAL)
    c.forbidden_source_types = []
    c.render_policy["allow_llm_rewrite"] = True

    # Extract key metrics
    metrics_text = _format_key_metrics(financial_metrics)
    if metrics_text:
        c.add_fact("key_metrics", metrics_text,
                   evidence_ids=financial_evidence_ids[:6],
                   source_types=[SRC_FINANCIAL_METRIC])
        c.status = "supported"

    # Check for existing dossier content
    dossier = _safe_dict(section_dossiers, "executive_summary")
    if dossier:
        suggested = _safe_list(dossier, "suggested_paragraphs")
        for para in suggested[:1]:
            if isinstance(para, str) and len(para) > 50:
                c.add_fact("executive_synthesis", _clip_at_sentence_boundary(para, 400),
                           source_types=[SRC_OFFICIAL_FILING])
                if c.status == "gap":
                    c.status = "partial"

    if c.status == "gap" and not c.facts:
        c.add_blocked_reason("executive_summary_no_evidence")


def _build_business_overview(
    contracts: ReportSectionContracts,
    pdf_section_summaries: List[Dict[str, Any]],
    pdf_section_chunks: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    analysis_artifacts: Dict[str, Any],
    state: Dict[str, Any],
    section_dossiers: Dict[str, Any] | None = None,
    annual_report_sections: List[Dict[str, Any]] = None,
) -> None:
    c = contracts.ensure("business_overview")
    c.allowed_source_types = list(ALLOWED_QUALITATIVE_PDF_ONLY)
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("business_overview", [])
    c.render_policy["allow_llm_rewrite"] = True

    if annual_report_sections is None:
        annual_report_sections = []
    section_dossiers = section_dossiers or {}

    biz_chunks = _filter_chunks_by_type(pdf_section_chunks, {
        "business_overview", "business", "strategy_business",
    })
    biz_summaries = _filter_summaries_by_type(pdf_section_summaries, {
        "business_overview", "business", "strategy_business",
    })

    candidates: List[Dict[str, Any]] = []

    def _append_candidate(text: str, eid: str, source_type: str) -> None:
        clean = _clean_and_clip_pdf_text(text, 600)
        if not clean or len(clean.strip()) < 30:
            return
        candidates.append({
            "score": _business_overview_priority_score(clean),
            "fact_type": _classify_business_fact(clean),
            "text": clean,
            "evidence_id": eid,
            "source_type": source_type,
        })

    for summary in biz_summaries:
        text = str(summary.get("summary_zh") or summary.get("text") or summary.get("content") or "")
        eid = str(summary.get("evidence_id") or "") or str(summary.get("chunk_id") or "")
        if _is_pdf_gap_summary(text):
            c.add_quality_flag("business_overview_gap_summary_skipped")
            continue
        if text_contains_pdf_boilerplate(text):
            c.add_quality_flag("business_overview_boilerplate_cleaned")
            text = clean_pdf_boilerplate(text)
        _append_candidate(text, eid, SRC_ANNUAL_REPORT_PDF_SUMMARY)

    for chunk in biz_chunks:
        text = str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
        eid = str(chunk.get("evidence_id") or "") or str(chunk.get("chunk_id") or "")
        _append_candidate(text, eid, SRC_ANNUAL_REPORT_PDF_CHUNK)

    if c.status == "gap":
        sec_biz = _get_annual_report_text_by_sec_item(annual_report_sections, {"business"})
        for item in sec_biz:
            text = _clip_at_sentence_boundary(item["text"], 800)
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                candidates.append({
                    "score": _business_overview_priority_score(text),
                    "fact_type": "business_model",
                    "text": _clip_at_sentence_boundary(text, 600),
                    "evidence_id": eid,
                    "source_type": SRC_SEC_10K_SECTION,
                })
                c.add_quality_flag("business_overview_uses_sec_10k")
                break

    if candidates:
        candidates.sort(key=lambda item: (item.get("score", 0), len(str(item.get("text") or ""))), reverse=True)
        chosen_texts: List[str] = []
        for item in candidates:
            text = str(item.get("text") or "").strip()
            eid = str(item.get("evidence_id") or "").strip()
            if not text or text in chosen_texts:
                continue
            c.add_fact(
                str(item.get("fact_type") or "general_business"),
                text,
                evidence_ids=[eid] if eid else [],
                source_types=[str(item.get("source_type") or SRC_ANNUAL_REPORT_PDF_SUMMARY)],
            )
            chosen_texts.append(text)
            if len(chosen_texts) >= 3:
                break
        c.status = "supported" if len(chosen_texts) >= 2 else "partial"
    else:
        _fallback_business_overview_via_text_detector(c, state, evidence_records)
        if c.status == "gap":
            profile_text, profile_eid, profile_source = _business_profile_fallback(state, analysis_artifacts, evidence_records)
            if profile_text:
                c.add_fact(
                    "business_profile_fallback",
                    _clip_at_sentence_boundary(profile_text, 700),
                    evidence_ids=[profile_eid] if profile_eid else [],
                    source_types=[profile_source or "company_profile"],
                )
                c.status = "fallback"
                c.add_blocked_reason("business_overview_used_profile_fallback")
            else:
                c.add_blocked_reason("business_overview_pdf_chunks_not_found")

    if c.status == "gap":
        _apply_dossier_pack_fallback(
            c,
            section_dossiers,
            "business_overview",
            fact_type="business_profile_pack",
            source_type=SRC_YAHOO_PROFILE,
            min_chars=30,
        )

    for fact in c.facts:
        frags = text_contains_fragments(fact.text)
        if frags:
            c.add_quality_flag(f"business_overview_fragment:{','.join(frags)}")


def _build_ownership_governance(
    contracts: ReportSectionContracts,
    pdf_section_summaries: List[Dict[str, Any]],
    pdf_section_chunks: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    state: Dict[str, Any],
    annual_report_sections: List[Dict[str, Any]] = None,
) -> None:
    c = contracts.ensure("ownership_governance")
    c.allowed_source_types = list(ALLOWED_QUALITATIVE_PDF_ONLY)
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("ownership_governance", [])
    c.render_policy["allow_llm_rewrite"] = True

    if annual_report_sections is None:
        annual_report_sections = []

    # Collect governance-related sections
    gov_summaries = _filter_summaries_by_type(pdf_section_summaries, {
        "ownership_governance", "governance", "shareholder_structure",
    })
    gov_chunks = _filter_chunks_by_type(pdf_section_chunks, {
        "ownership_governance", "governance", "shareholder_structure",
        "board", "senior_management",
    })

    # Market-specific section detection
    market = _detect_market(state)
    if market == "cn_a":
        cn_a_governance = _filter_chunks_by_type(pdf_section_chunks, {
            "公司治理", "董事会", "监事会", "股东大会", "独立董事",
            "高级管理人员", "内部控制", "股份变动", "前十名股东", "控股股东", "实际控制人",
        })
        gov_chunks.extend(cn_a_governance)
    elif market == "hk":
        hk_governance = _filter_chunks_by_type(pdf_section_chunks, {
            "corporate_governance", "directors", "substantial_shareholders", "share_capital",
        })
        gov_chunks.extend(hk_governance)
    elif market == "us":
        us_governance = _filter_chunks_by_type(pdf_section_chunks, {
            "item_10", "item_12", "directors", "executive_officers", "security_ownership",
        })
        gov_chunks.extend(us_governance)

    evidence_ids_used: List[str] = []

    for summary in gov_summaries:
        text = str(summary.get("summary_zh") or summary.get("text") or summary.get("content") or "")
        eid = str(summary.get("evidence_id") or "") or str(summary.get("chunk_id") or "")
        st = str(summary.get("section_type") or "")
        if not text or len(text.strip()) < 30:
            continue
        if _is_pdf_gap_summary(text):
            c.add_quality_flag("governance_gap_summary_skipped")
            continue
        c.add_fact("governance_structure", _clip_at_sentence_boundary(text, 500),
                   evidence_ids=[eid] if eid else [],
                   source_types=[SRC_ANNUAL_REPORT_PDF_SUMMARY])
        if eid and eid not in evidence_ids_used:
            evidence_ids_used.append(eid)
        if c.status == "gap":
            c.status = "partial"

    for chunk in gov_chunks:
        text = str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
        eid = str(chunk.get("evidence_id") or "") or str(chunk.get("chunk_id") or "")
        st = str(chunk.get("section_type") or "")
        if not text or len(text.strip()) < 30:
            continue
        if eid in evidence_ids_used:
            continue
        c.add_fact("governance_detail", _clip_at_sentence_boundary(text, 400),
                   evidence_ids=[eid] if eid else [],
                   source_types=[SRC_ANNUAL_REPORT_PDF_CHUNK])
        if eid and eid not in evidence_ids_used:
            evidence_ids_used.append(eid)
        if c.status == "gap":
            c.status = "partial"

    # SEC 10-K Item 10 / Item 12 governance sections (US market)
    if c.status == "gap":
        sec_gov = _get_annual_report_text_by_sec_item(annual_report_sections, {"governance", "security_ownership"})
        for item in sec_gov:
            text = _clip_at_sentence_boundary(item["text"], 800)
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                c.add_fact("governance_structure",
                           _clip_at_sentence_boundary(text, 500),
                           evidence_ids=[eid] if eid else [],
                           source_types=[SRC_SEC_10K_SECTION])
                c.status = "supported"
                c.add_quality_flag("governance_uses_sec_10k")
                break

    if c.status == "gap":
        proxy_records = [
            record
            for record in evidence_records
            if isinstance(record, dict) and str(record.get("source_type") or "").lower() == "sec_proxy_filing"
        ]
        for record in proxy_records:
            text = _clip_at_sentence_boundary(str(record.get("content") or ""), 900)
            evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
            if len(text.strip()) < 80:
                continue
            c.add_fact(
                "governance_proxy_disclosure",
                text,
                evidence_ids=[evidence_id] if evidence_id else [],
                source_types=["sec_proxy_filing"],
            )
            if evidence_id:
                evidence_ids_used.append(evidence_id)
            c.status = "supported"
            c.add_quality_flag("governance_uses_sec_proxy")
            break

    if len(c.facts) >= 1 and c.status == "gap":
        c.status = "partial"
    if len(c.facts) >= 2 and evidence_ids_used:
        c.status = "supported"

    if c.status == "gap":
        # Determine specific gap reason
        found_any_governance = bool(gov_summaries) or bool(gov_chunks) or bool(annual_report_sections)
        if found_any_governance:
            # Had summaries but they were noise or unparseable
            noise_chunks = [s for s in pdf_section_summaries
                           if str(s.get("evidence_quality", "")).lower() == "noise_only"
                           and str(s.get("section_type", "")) in {"ownership_governance", "governance"}]
            if noise_chunks:
                c.add_blocked_reason("governance_chunks_noise_only")
            else:
                c.add_blocked_reason("governance_summary_not_injected")
        else:
            c.add_blocked_reason("governance_section_not_found")
        # Provide a substantive deterministic fallback instead of bare data_gap
        company_name = ""
        identity = _safe_dict(state, "entity_resolution")
        if identity:
            company_name = str(identity.get("company_name", "") or "")
        if not company_name:
            company_name = str(state.get("company_name", "") or "")
        market = _detect_market(state)
        # For non-US markets (cn_a, hk) use generic Chinese reference to avoid
        # exposing English legal names like "Kweichow Moutai Co., Ltd." in a
        # Chinese-language report.
        if market == "us" and company_name:
            fallback_parts = [f"{company_name}作为上市公司"]
        else:
            fallback_parts = ["该公司作为上市公司"]
        if market == "us":
            fallback_parts.append(
                "通常由董事会、审计委员会、薪酬委员会、提名与治理委员会及执行管理层共同构成治理框架。"
                "董事会独立性、高管薪酬安排、股东投票权、关联交易披露和信息披露质量是美股公司治理分析的重点；"
                "具体董事、高管与持股情况需以后续 10-K、10-Q 或 proxy statement 披露为准。"
            )
        else:
            fallback_parts.append("具备规范的公司治理结构，设有董事会、监事会和经营管理层。"
                                  "控股股东与实际控制人信息需以年度报告披露为准，"
                                  "股东构成和持股比例受定期报告约束。"
                                  "公司治理评价需结合独立董事制度、内部控制审计、"
                                  "信息披露合规性和分红政策等维度综合判断。")
        c.deterministic_text = "".join(fallback_parts)


def _build_strategy_business(
    contracts: ReportSectionContracts,
    pdf_section_summaries: List[Dict[str, Any]],
    pdf_section_chunks: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    financial_metrics: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
    annual_report_sections: List[Dict[str, Any]] = None,
) -> None:
    c = contracts.ensure("strategy_business")
    c.allowed_source_types = list(ALLOWED_QUALITATIVE_PDF_ONLY)
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("strategy_business", [])
    c.render_policy["allow_llm_rewrite"] = True

    if annual_report_sections is None:
        annual_report_sections = []

    # Collect strategy / MD&A evidence
    strategy_chunks = _filter_chunks_by_type(pdf_section_chunks, {
        "strategy_business", "management_discussion", "mda", "strategy",
        "segments", "liquidity",
    })
    strategy_summaries = _filter_summaries_by_type(pdf_section_summaries, {
        "strategy_business", "management_discussion", "mda", "strategy",
    })

    evidence_ids_used: List[str] = []

    for summary in strategy_summaries:
        text = str(summary.get("summary_zh") or summary.get("text") or summary.get("content") or "")
        eid = str(summary.get("evidence_id") or "") or str(summary.get("chunk_id") or "")
        st = str(summary.get("section_type") or "")
        if not text or len(text.strip()) < 30:
            continue
        # Skip gap summaries — PDF noise placeholders, not actual content
        if _is_pdf_gap_summary(text):
            c.add_quality_flag("strategy_gap_summary_skipped")
            continue
        # Check for fragments
        if text_contains_fragments(text):
            c.add_quality_flag("strategy_fragments_in_summary")
        clean = _clean_and_clip_pdf_text(text, 600)
        if clean:
            c.add_fact("strategy_discussion", clean,
                       evidence_ids=[eid] if eid else [],
                       source_types=[SRC_ANNUAL_REPORT_PDF_SUMMARY])
            if eid and eid not in evidence_ids_used:
                evidence_ids_used.append(eid)
            if c.status == "gap":
                c.status = "partial"

    # SEC 10-K Item 7 MD&A section (US market)
    if c.status == "gap":
        sec_mda = _get_annual_report_text_by_sec_item(annual_report_sections, {"mda", "strategy"})
        for item in sec_mda:
            text = _clip_at_sentence_boundary(item["text"], 800)
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                c.add_fact("strategy_discussion",
                           _clip_at_sentence_boundary(text, 600),
                           evidence_ids=[eid] if eid else [],
                           source_types=[SRC_SEC_10K_SECTION])
                c.status = "supported"
                c.add_quality_flag("strategy_uses_sec_10k_mda")
                break

    for chunk in strategy_chunks:
        text = str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
        eid = str(chunk.get("evidence_id") or "") or str(chunk.get("chunk_id") or "")
        st = str(chunk.get("section_type") or "")
        if not text or len(text.strip()) < 30:
            continue
        if eid in evidence_ids_used:
            continue
        if text_contains_fragments(text):
            continue  # skip fragment chunks - they pollute rather than inform
        clean = _clean_and_clip_pdf_text(text, 500)
        if clean:
            c.add_fact("strategy_detail", clean,
                       evidence_ids=[eid] if eid else [],
                       source_types=[SRC_ANNUAL_REPORT_PDF_CHUNK])
            if eid and eid not in evidence_ids_used:
                evidence_ids_used.append(eid)
            if c.status == "gap":
                c.status = "partial"

    if len(c.facts) >= 2 and evidence_ids_used:
        c.status = "supported"
    elif len(c.facts) >= 1:
        c.status = "partial"
    else:
        c.status = "gap"
        c.add_blocked_reason("strategy_pdf_sections_not_found")
        # Provide a complete deterministic sentence rather than a fragment
        c.deterministic_text = (
            "公司战略分析聚焦品牌力、渠道效率、产品结构、定价能力、"
            "现金流稳定性与分红能力等维度；行业竞争格局和公司战略执行将共同影响"
            "收入增长、利润率稳定性和估值弹性。"
        )


def _build_three_statement_summary(
    contracts: ReportSectionContracts,
    financial_metrics: Dict[str, Any],
    tables: List[Dict[str, Any]],
    financial_evidence_ids: List[str],
    currency_context: CurrencyContext,
) -> None:
    c = contracts.ensure("three_statement_summary")
    c.allowed_source_types = list(ALLOWED_FINANCIAL_TABLES_ONLY)
    c.forbidden_source_types = []
    c.render_policy["allow_llm_rewrite"] = True

    # Add financial metrics as facts (normalise flat or array format)
    flat_metrics = _normalize_metrics_flat(financial_metrics)
    key_metrics = ["revenue", "net_income", "total_assets", "total_liabilities",
                   "operating_cash_flow", "free_cash_flow"]
    facts_added = 0
    for km in key_metrics:
        val = flat_metrics.get(km)
        if val is not None:
            c.add_fact("financial_line_item", f"{km}: {val}",
                       evidence_ids=_metric_evidence_ids(financial_metrics, km, financial_evidence_ids),
                       source_types=[SRC_FINANCIAL_METRIC])
            facts_added += 1

    if facts_added >= 3:
        c.status = "supported"
    elif facts_added >= 1:
        c.status = "partial"
    else:
        c.add_blocked_reason("three_statement_insufficient_metrics")

    table_md = _render_three_statement_table_markdown(tables, currency_context)
    if table_md:
        c.deterministic_text = table_md
        for eid in financial_evidence_ids[:6]:
            if eid not in c.citation_evidence_ids:
                c.citation_evidence_ids.append(eid)
    else:
        for table in tables:
            if isinstance(table, dict) and str(table.get("title", "") or ""):
                md = str(table.get("markdown", "") or "")
                if md and len(md) > 30:
                    c.deterministic_text = md
                    break


def _build_financial_analysis(
    contracts: ReportSectionContracts,
    financial_metrics: Dict[str, Any],
    tables: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    section_dossiers: Dict[str, Any],
    financial_evidence_ids: List[str],
    currency_context: CurrencyContext,
) -> None:
    c = contracts.ensure("financial_analysis")
    c.allowed_source_types = list(ALLOWED_FINANCIAL)
    c.forbidden_source_types = []
    c.render_policy["allow_llm_rewrite"] = True

    metrics_text = _format_key_metrics(financial_metrics)
    if metrics_text:
        c.add_fact("financial_metrics_summary", metrics_text,
                   evidence_ids=financial_evidence_ids[:6],
                   source_types=[SRC_FINANCIAL_METRIC])
        c.status = "supported"

    # Check for existing dossier deterministic blocks
    dossier = _safe_dict(section_dossiers, "financial_analysis")
    if dossier:
        blocks = _safe_list(dossier, "deterministic_blocks")
        for block in blocks:
            if isinstance(block, str) and len(block) > 40:
                c.deterministic_text = _clip_at_sentence_boundary(block, 800)
                break

    # Even without flat metrics, deterministic_text from section_dossiers/tables
    # is enough to avoid a bare gap.
    if c.status == "gap":
        if c.deterministic_text and len(c.deterministic_text.strip()) > 30:
            c.status = "partial"
        elif c.facts:
            c.status = "partial"
        else:
            c.add_blocked_reason("financial_analysis_insufficient_metrics")


def _build_peer_compare(
    contracts: ReportSectionContracts,
    peer_rows: List[Dict[str, Any]],
    analysis_artifacts: Dict[str, Any],
    blackboard: Dict[str, Any],
    target_symbol: str,
    section_dossiers: Dict[str, Any] | None = None,
) -> None:
    c = contracts.ensure("peer_compare")
    c.allowed_source_types = [SRC_PEER_DATA, SRC_MARKET_DATA]
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("peer_compare", [])
    c.render_policy["allow_llm_rewrite"] = True

    if not peer_rows:
        _apply_dossier_pack_fallback(
            c,
            section_dossiers=section_dossiers or _safe_dict(analysis_artifacts, "section_dossiers"),
            section_key="peer_compare",
            fact_type="peer_compare_boundary_pack",
            source_type=SRC_PEER_DATA,
            min_chars=30,
        )
        if c.status == "gap":
            c.status = "fallback"
            c.deterministic_text = (
                "本轮未取得足够可比公司量化表，因此同行对比仅作为口径边界："
                "需要按同市场、同业务结构、相近利润率和现金流质量筛选可比公司；"
                "正式交付前应补齐可比公司的收入增速、毛利率、P/E、P/S 或 P/B 等指标。"
                "在统一财年、币种和会计口径前，本报告不输出缺乏证据支持的同行排名或估值折溢价，"
                "以免把业务结构差异误判为经营优劣；当前结论仅用于说明比较方法和数据边界。"
            )
            c.add_quality_flag("peer_compare_boundary_only")
        return

    # Get approved peer symbols
    approved = _get_approved_peer_symbols(analysis_artifacts, blackboard)

    # Filter and classify peers
    target_market = _infer_market_from_symbol(target_symbol)
    target_industry = _get_target_industry(target_symbol, peer_rows)
    direct_peers: List[str] = []
    cross_market: List[str] = []

    valid_peer_rows: List[Dict[str, Any]] = []
    non_target_rows_seen = False
    target_upper = str(target_symbol or "").strip().upper()
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not sym:
            continue
        if sym == target_upper:
            continue
        non_target_rows_seen = True
        if not _peer_row_has_metrics(row):
            c.add_quality_flag(f"peer_metrics_missing:{sym}")
            continue
        if approved and sym not in approved and sym != target_symbol:
            continue
        row_market = _infer_market_from_symbol(sym)
        if target_market and row_market and row_market != target_market:
            if target_market == "cn_a":
                c.add_quality_flag(f"peer_cross_market_dropped:{sym}")
                continue
            cross_market.append(sym)
        else:
            # Same market: check industry alignment
            row_industry = str(row.get("industry") or row.get("sector") or row.get("peer_group") or "").lower().strip()
            if (target_industry
                    and row_industry
                    and target_industry not in row_industry
                    and row_industry not in target_industry):
                # Industry mismatch: classify as cross-market reference instead
                cross_market.append(sym)
                c.add_quality_flag(f"peer_industry_unmatched:{sym}")
            else:
                direct_peers.append(sym)
                valid_peer_rows.append(row)

    # Build peer groups
    if direct_peers:
        c.peer_groups.append(PeerGroupDef(
            group_label="direct_competitor",
            symbols=direct_peers,
            description="同市场可比公司（业务结构与会计口径一致）",
        ))
    if cross_market:
        c.peer_groups.append(PeerGroupDef(
            group_label="cross_market_reference",
            symbols=cross_market,
            description="海外消费品参考组（非同业直接可比）",
        ))

    if direct_peers and valid_peer_rows:
        c.status = "supported"
    elif cross_market:
        c.status = "partial"
        c.add_blocked_reason("peer_only_cross_market_reference")
    elif non_target_rows_seen:
        c.status = "fallback"
        c.add_blocked_reason("peer_no_metric_rows")
        c.add_quality_flag("peer_compare_boundary_only")
    else:
        c.status = "gap"
        c.add_blocked_reason("peer_only_target_row")
        c.add_quality_flag("peer_compare_boundary_only")
    if not direct_peers and not cross_market:
        if non_target_rows_seen:
            c.add_quality_flag("peer_no_metric_rows")
        else:
            c.add_quality_flag("peer_only_target_row")
    if not valid_peer_rows and direct_peers:
        direct_peers.clear()
        c.status = "fallback"
        c.add_quality_flag("peer_no_metric_rows")

    # Store peer table markdown as deterministic text
    if peer_rows and direct_peers and valid_peer_rows:
        table_md = _render_peer_table_markdown(peer_rows, direct_peers, cross_market, target_symbol)
        if table_md:
            c.deterministic_text = table_md
    elif c.status in {"fallback", "gap"} and not c.deterministic_text:
        c.deterministic_text = (
            "本轮同行对比未取得可验证的非目标公司量化指标，因此不将同业表作为正式估值依据。"
            "正式交付前需要补齐至少两家可比公司的收入增速、毛利率、净利率、ROE 或现金流指标，"
            "并说明业务结构、市场口径和估值倍数差异。"
        )


def _build_valuation(
    contracts: ReportSectionContracts,
    valuation_model: Dict[str, Any],
    financial_metrics: Dict[str, Any],
    financial_evidence_ids: List[str],
    currency_context: CurrencyContext,
    section_dossiers: Dict[str, Any],
) -> None:
    c = contracts.ensure("valuation")
    c.allowed_source_types = [SRC_VALUATION_MODEL, SRC_FINANCIAL_METRIC, SRC_MARKET_DATA]
    c.forbidden_source_types = [SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE]
    c.render_policy["allow_llm_rewrite"] = True

    if not valuation_model:
        metrics_text = _format_key_metrics(financial_metrics)
        if metrics_text:
            c.add_fact(
                "valuation_metric_boundary",
                "估值观察缺少完整目标价模型，但可基于已验证财务指标形成方向性估值边界：" + metrics_text,
                evidence_ids=financial_evidence_ids[:6],
                source_types=[SRC_FINANCIAL_METRIC],
            )
            c.status = "partial"
            c.add_quality_flag("valuation_directional_only")
        else:
            _apply_dossier_pack_fallback(
                c,
                section_dossiers,
                "valuation",
                fact_type="valuation_boundary_pack",
                source_type=SRC_FINANCIAL_METRIC,
                min_chars=30,
            )
        if c.status == "gap":
            c.add_blocked_reason("valuation_model_not_available")
        return

    status = str(valuation_model.get("valuation_status", "") or "")
    if status in ("rough_observation_only", "blocked_due_to_incomplete_inputs"):
        c.add_blocked_reason(f"valuation_model_status:{status}")
        c.status = "fallback"
        c.deterministic_text = (
            "由于财务报表货币与交易货币不一致，且本轮尚未完成官方年报校验与可验证汇率换算，"
            "本报告不输出确定性P/E、P/S、DCF或目标价。"
        )
        return

    # Read from the actual valuation_model structure returned by perform_company_valuation:
    #   valuation_model.relative_valuation.multiples.pe.multiple  → P/E
    #   valuation_model.relative_valuation.multiples.ps.multiple  → P/S
    #   valuation_model.dcf_model.equity_value_billion            → DCF equity value
    rel_val = _safe_dict(valuation_model, "relative_valuation")
    multiples = _safe_dict(rel_val, "multiples")
    pe_info = _safe_dict(multiples, "pe")
    ps_info = _safe_dict(multiples, "ps")
    dcf_info = _safe_dict(valuation_model, "dcf_model")

    pe = pe_info.get("multiple")
    ps = ps_info.get("multiple")
    dcf = dcf_info.get("equity_value_billion")
    pe_value = pe_info.get("equity_value_billion")
    ps_value = ps_info.get("equity_value_billion")
    target_price = valuation_model.get("target_price")

    facts_added = 0
    blended = _safe_number(valuation_model.get("blended_equity_value_billion"))
    dcf_num = _safe_number(dcf)
    suppress_target_price = False
    if blended and dcf_num and max(blended, dcf_num) > 0:
        divergence = abs(blended - dcf_num) / max(blended, dcf_num)
        if divergence > 0.50:
            c.add_quality_flag(f"valuation_method_divergence:{divergence:.2f}")
            suppress_target_price = True
            c.deterministic_text = (
                "估值方法之间存在显著分歧，本报告分别披露相对估值与DCF结果，"
                "不输出单一综合目标价。"
            )
    if pe is not None and pe_value is not None:
        c.add_fact("pe_ratio", f"P/E {pe:.1f}x → 权益价值 {_format_billion_value(pe_value, currency_context)}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1
    if ps is not None and ps_value is not None:
        c.add_fact("ps_ratio", f"P/S {ps:.1f}x → 权益价值 {_format_billion_value(ps_value, currency_context)}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1
    if dcf is not None:
        c.add_fact("dcf_value", f"DCF权益价值 {_format_billion_value(dcf, currency_context)}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1
    if target_price is not None and not suppress_target_price:
        c.add_fact("target_price", f"综合目标价 {target_price:.2f}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1

    if facts_added >= 2:
        c.status = "supported"
    elif facts_added >= 1:
        c.status = "partial"
    else:
        metrics_text = _format_key_metrics(financial_metrics)
        if metrics_text:
            c.add_fact(
                "valuation_metric_boundary",
                "估值观察缺少完整目标价模型，但可基于已验证财务指标形成方向性估值边界：" + metrics_text,
                evidence_ids=financial_evidence_ids[:6],
                source_types=[SRC_FINANCIAL_METRIC],
            )
            c.status = "partial"
            c.add_quality_flag("valuation_directional_only")
        else:
            _apply_dossier_pack_fallback(
                c,
                section_dossiers,
                "valuation",
                fact_type="valuation_boundary_pack",
                source_type=SRC_FINANCIAL_METRIC,
                min_chars=30,
            )
        if c.status == "gap":
            c.add_blocked_reason("valuation_no_metrics_available")


def _build_valuation_sensitivity(
    contracts: ReportSectionContracts,
    valuation_model: Dict[str, Any],
    valuation_sensitivity: Dict[str, Any],
) -> None:
    c = contracts.ensure("valuation_sensitivity")
    c.allowed_source_types = [SRC_VALUATION_MODEL]
    c.forbidden_source_types = [SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE]
    c.render_policy["allow_llm_rewrite"] = True

    if not valuation_sensitivity:
        vm_status = str(valuation_model.get("valuation_status", "") or "") if valuation_model else ""
        if vm_status in ("rough_observation_only", "blocked_due_to_incomplete_inputs"):
            inputs = valuation_model.get("input_summary") if isinstance(valuation_model.get("input_summary"), dict) else {}
            revenue = _safe_number(inputs.get("revenue_billion"))
            net_income = _safe_number(inputs.get("net_income_billion"))
            if revenue and net_income and revenue > 0:
                margin = net_income / revenue
                income_delta = revenue * 0.01 * margin
                c.status = "partial"
                c.deterministic_text = (
                    f"估值敏感性采用盈利桥接而非虚构DCF目标价：基准收入约{revenue:.2f}B、"
                    f"净利润约{net_income:.2f}B，对应净利率约{margin * 100:.1f}%。"
                    f"在净利率保持不变的简化假设下，收入上升或下降1%将使净利润约增加或减少{income_delta:.2f}B；"
                    "若市场估值倍数同时收缩，股权价值的下行幅度可能大于盈利变化。"
                    "该情景用于识别收入与利润弹性，不替代包含折现率、终值增长率和完整预测期的DCF模型。"
                )
                c.add_quality_flag("valuation_sensitivity_earnings_bridge_only")
            else:
                c.status = "fallback"
                c.deterministic_text = (
                    "估值敏感性暂不输出DCF情景数值。本轮只保留变量边界：收入增速、毛利率、"
                    "经营现金流转换率、折现率和终值增长率是后续正式模型必须复核的关键输入。"
                )
                c.add_quality_flag("valuation_sensitivity_boundary_only")
        else:
            c.status = "fallback"
            c.deterministic_text = (
                "估值敏感性数据尚未形成完整表格。本轮先说明敏感性框架：上行情景依赖收入增速、"
                "利润率和现金流改善，下行情景主要来自需求放缓、费用率上升或估值倍数压缩。"
            )
            c.add_quality_flag("valuation_sensitivity_framework_only")
        return

    rows = _normalize_sensitivity_rows(valuation_sensitivity)
    if rows:
        sensitivity_currency = str(
            valuation_sensitivity.get("currency")
            or valuation_model.get("valuation_currency")
            or valuation_model.get("currency")
            or ""
        ).replace("_billion", "").upper()
        c.deterministic_text = _render_sensitivity_text(rows, currency=sensitivity_currency)
        if str(valuation_sensitivity.get("method") or "") == "earnings_bridge":
            c.deterministic_text = "盈利桥接（非DCF目标价）：\n" + c.deterministic_text
            c.status = "partial"
            c.add_quality_flag("valuation_sensitivity_earnings_bridge_only")
        else:
            c.status = "supported"
    else:
        c.add_blocked_reason("valuation_sensitivity_empty")


def _build_risk_factors(
    contracts: ReportSectionContracts,
    pdf_section_summaries: List[Dict[str, Any]],
    pdf_section_chunks: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    analysis_artifacts: Dict[str, Any],
    state: Dict[str, Any],
    annual_report_sections: List[Dict[str, Any]] = None,
    claims: List[Dict[str, Any]] | None = None,
) -> None:
    c = contracts.ensure("risk_factors")
    c.allowed_source_types = list(ALLOWED_QUALITATIVE_PDF_ONLY | {SRC_INDUSTRY_POLICY})
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("risk_factors", [])
    c.render_policy["allow_llm_rewrite"] = True

    if annual_report_sections is None:
        annual_report_sections = []

    # Priority 1: official PDF risk summary
    risk_summaries = _filter_summaries_by_type(pdf_section_summaries, {
        "risk_factors", "risks",
    })
    risk_chunks = _filter_chunks_by_type(pdf_section_chunks, {
        "risk_factors", "risks",
    })

    evidence_ids_used: List[str] = []

    for summary in risk_summaries:
        text = str(summary.get("summary_zh") or summary.get("text") or summary.get("content") or "")
        eid = str(summary.get("evidence_id") or "") or str(summary.get("chunk_id") or "")
        st = str(summary.get("section_type") or "")
        if not text or len(text.strip()) < 30:
            continue
        # Skip gap summaries — known PDF noise markers mean the content is boilerplate
        if _is_pdf_gap_summary(text):
            c.add_quality_flag("risk_gap_summary_skipped")
            continue
        c.add_fact("official_risk_summary", _clip_at_sentence_boundary(text, 600),
                   evidence_ids=[eid] if eid else [],
                   source_types=[SRC_ANNUAL_REPORT_PDF_SUMMARY])
        if eid and eid not in evidence_ids_used:
            evidence_ids_used.append(eid)
        if c.status == "gap":
            c.status = "supported"  # priority-1 found
            c.add_quality_flag("risk_uses_official_pdf")

    if c.status != "supported":
        for chunk in risk_chunks:
            text = str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
            eid = str(chunk.get("evidence_id") or "") or str(chunk.get("chunk_id") or "")
            st = str(chunk.get("section_type") or "")
            if not text or len(text.strip()) < 30:
                continue
            if eid in evidence_ids_used:
                continue
            c.add_fact("official_risk_detail", _clip_at_sentence_boundary(text, 500),
                       evidence_ids=[eid] if eid else [],
                       source_types=[SRC_ANNUAL_REPORT_PDF_CHUNK])
            if eid and eid not in evidence_ids_used:
                evidence_ids_used.append(eid)
            if c.status == "gap":
                c.status = "partial"

    # Some production paths persist official PDF sections directly in the
    # normalized evidence list without duplicating them into the summary/chunk
    # artifacts. Preserve that official risk evidence before using an industry
    # fallback.
    if c.status == "gap":
        for record in evidence_records:
            if not isinstance(record, dict) or str(record.get("source_type") or "").lower() != "pdf_section":
                continue
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            section_type = str(metadata.get("section_type") or record.get("section_type") or "").lower()
            if section_type not in {"risk_factors", "risks"}:
                continue
            document_type = str(record.get("source_document_type") or "").lower()
            authority = str(record.get("source_authority") or "").lower()
            source_url = str(record.get("source_url") or "").lower()
            if authority != "official" and document_type not in {"cninfo_announcement", "exchange_announcement", "hkex_announcement", "official_filing"} and not any(domain in source_url for domain in ("cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk")):
                continue
            text = str(record.get("content") or "").strip()
            if len(text) < 30 or _is_pdf_gap_summary(text):
                continue
            eid = str(record.get("evidence_id") or record.get("sample_id") or "")
            c.add_fact(
                "official_risk_detail",
                _clip_at_sentence_boundary(text, 700),
                evidence_ids=[eid] if eid else [],
                source_types=[SRC_ANNUAL_REPORT_PDF_CHUNK],
            )
            c.status = "supported"
            c.add_quality_flag("risk_uses_official_pdf")
            break

    # SEC 10-K Item 1A Risk Factors (US market)
    if c.status == "gap":
        sec_risk = _get_annual_report_text_by_sec_item(annual_report_sections, {"risk_factors"})
        for item in sec_risk:
            text = _clip_at_sentence_boundary(item["text"], 1200)
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                c.add_fact("official_risk_summary",
                           _clip_at_sentence_boundary(text, 1000),
                           evidence_ids=[eid] if eid else [],
                           source_types=[SRC_SEC_10K_SECTION])
                c.status = "supported"
                c.add_quality_flag("risk_uses_sec_10k_item_1a")
                break

    # Priority 2: industry family fallback (no financial table references)
    if c.status == "gap":
        industry_fallback = _get_industry_risk_fallback(state, analysis_artifacts)
        if industry_fallback:
            c.add_fact("industry_risk_fallback", industry_fallback,
                       source_types=[SRC_INDUSTRY_POLICY])
            c.status = "fallback"
            c.add_blocked_reason("risk_industry_fallback_used")
            c.add_quality_flag("risk_fallback_no_official_pdf")
        else:
            c.status = "fallback"
            c.deterministic_text = (
                "待官方风险章节进一步校验。当前风险分析基于行业一般性公开信息，"
                "尚未获取公司年度报告风险章节的官方披露。"
            )
            c.add_blocked_reason("risk_official_pdf_not_found_and_no_industry_fallback")
            c.add_quality_flag("risk_generic_fallback_no_industry_policy")

    # Risk claims are verified individually, so every available evidence ID
    # attached to a risk claim must be part of the section citation contract.
    # Otherwise the evidence pack can carry the claims as supporting context
    # while CitationBinder has no ownership of their final Markdown citations.
    evidence_by_id = {
        str(record.get("evidence_id") or record.get("sample_id") or ""): record
        for record in evidence_records
        if isinstance(record, dict)
    }
    forbidden = set(c.forbidden_source_types)
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        section_name = str(claim.get("section_name") or claim.get("section_key") or "").strip().lower()
        if section_name not in {"risk", "risks", "risk_factors"}:
            continue
        for raw_evidence_id in claim.get("evidence_ids") or []:
            evidence_id = str(raw_evidence_id or "").strip()
            record = evidence_by_id.get(evidence_id)
            if not evidence_id or record is None:
                continue
            source_type = str(record.get("source_type") or "").strip().lower()
            if source_type in forbidden:
                continue
            if evidence_id not in c.citation_evidence_ids:
                c.citation_evidence_ids.append(evidence_id)


def _build_investment_conclusion(
    contracts: ReportSectionContracts,
    financial_metrics: Dict[str, Any],
    valuation_model: Dict[str, Any],
    evidence_records: List[Dict[str, Any]],
    financial_evidence_ids: List[str],
) -> None:
    c = contracts.ensure("investment_conclusion")
    c.allowed_source_types = list(ALLOWED_FINANCIAL)
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("investment_conclusion", [])
    c.render_policy["allow_llm_rewrite"] = True

    flat_metrics = _normalize_metrics_flat(financial_metrics)
    has_financial = bool(flat_metrics.get("revenue")) or bool(flat_metrics.get("net_income"))
    has_valuation = bool(valuation_model) and valuation_model.get("valuation_available") is not False
    pc = contracts.get("peer_compare")
    has_peers = bool(pc and pc.status not in ("gap",))

    if has_financial or has_valuation or has_peers:
        evidence_ids = financial_evidence_ids[:5]
        direction = _investment_direction(financial_metrics, valuation_model)
        reasons = _investment_reason_text(financial_metrics, valuation_model, has_peers)
        risks = "主要风险包括需求波动、竞争加剧、现金流转换率下降、估值倍数回落，以及官方披露口径尚需持续复核。"
        c.add_fact(
            "conclusion_basis",
            f"投资结论：维持{direction}。{reasons}{risks}",
            evidence_ids=evidence_ids,
            source_types=[SRC_FINANCIAL_METRIC],
        )
        c.deterministic_text = (
            f"维持{direction}，结论基于财务质量、估值约束、同行可比性和风险边界。"
            f"{reasons}{risks}"
            "结论仅基于本报告列示的已验证财务、估值与风险证据，不构成确定性收益承诺。"
        )
        c.status = "partial"
    else:
        c.add_blocked_reason("conclusion_insufficient_evidence")
        c.deterministic_text = (
            "投资结论需要财务、同行、估值和风险证据同时支撑；"
            "当前证据链尚不足以给出强方向评级。"
        )


def _build_period_note(
    contracts: ReportSectionContracts,
    period_info: Dict[str, Any],
) -> None:
    c = contracts.ensure("period_note")
    c.render_policy["allow_llm_rewrite"] = True

    latest = period_info.get("latest_available_period", "")
    target = period_info.get("target_period", "")
    mismatch = period_info.get("period_mismatch", False)
    latest_source_types = {
        str(item or "").strip().lower()
        for item in period_info.get("latest_period_source_types", [])
        if str(item or "").strip()
    }
    profile_only_mismatch = bool(mismatch and latest_source_types) and latest_source_types <= {
        "company_profile",
        "yahoo_profile",
    }

    if latest:
        latest_label = "非目标期公司资料快照" if profile_only_mismatch else "最新可得披露数据期"
        c.add_fact("latest_period", f"{latest_label}：{latest}",
                   source_types=[SRC_FINANCIAL_METRIC])
        c.status = "supported"
    else:
        c.add_blocked_reason("period_metadata_missing")
        c.status = "gap"

    if mismatch:
        c.add_quality_flag("period_mismatch")
        mismatch_scope = (
            f"{latest} 记录仅为公司资料快照，不包含本报告采用的财务数值或目标期事件"
            if profile_only_mismatch
            else f"证据中还包含 {latest} 的非目标期资料"
        )
        c.add_fact(
            "period_mismatch_disclosure",
            (
                f"目标报告期为 {target}；{mismatch_scope}。"
                f"收入、利润、现金流、资产负债、估值输入和投资结论均严格采用 {target} 口径；"
                "非目标期资料不参与跨期比较，也不改变本报告结论。"
            ),
            source_types=[SRC_FINANCIAL_METRIC],
        )
        c.deterministic_text = (
            f"目标报告期：{target}。{mismatch_scope}。"
            f"口径影响：收入、利润、现金流、资产负债、估值输入和投资结论均严格采用 {target} 数据；"
            "非目标期资料不用于替代目标期财务数据、不参与跨期比较，也不改变本报告结论。"
        )


def _investment_direction(financial_metrics: Dict[str, Any], valuation_model: Dict[str, Any]) -> str:
    flat = _normalize_metrics_flat(financial_metrics)
    revenue = _safe_number(flat.get("revenue"))
    net_income = _safe_number(flat.get("net_income"))
    operating_cash_flow = _safe_number(flat.get("operating_cash_flow") or flat.get("cash_flow_operations"))
    valuation_status = str(valuation_model.get("valuation_status") or "") if isinstance(valuation_model, dict) else ""
    if valuation_status in {"blocked_due_to_incomplete_inputs", "rough_observation_only"}:
        return "中性观察评级"
    positives = sum(1 for value in (revenue, net_income, operating_cash_flow) if value is not None and value > 0)
    negatives = sum(1 for value in (net_income, operating_cash_flow) if value is not None and value < 0)
    if positives >= 2 and negatives == 0:
        return "中性偏积极评级"
    if negatives:
        return "偏谨慎评级"
    return "中性观察评级"


def _investment_reason_text(financial_metrics: Dict[str, Any], valuation_model: Dict[str, Any], has_peers: bool) -> str:
    flat = _normalize_metrics_flat(financial_metrics)
    reasons: list[str] = []
    if _safe_number(flat.get("revenue")) is not None:
        reasons.append("收入指标已进入证据链，可用于判断业务规模和增长弹性")
    if _safe_number(flat.get("net_income")) is not None:
        reasons.append("利润指标可用于观察盈利质量和费用压力")
    if _safe_number(flat.get("operating_cash_flow") or flat.get("cash_flow_operations")) is not None:
        reasons.append("经营现金流可用于检验利润含金量")
    if isinstance(valuation_model, dict) and valuation_model:
        reasons.append("估值部分提供了倍数或模型边界，但仍需复核输入假设")
    if has_peers:
        reasons.append("同行对比用于约束估值口径，不能替代公司自身基本面判断")
    if not reasons:
        reasons.append("当前证据只能支持方向性复核，不能支持强评级")
    selected = reasons[:3]
    return "核心理由包括：" + "；".join(selected) + "。"


def _build_currency_data_quality(
    contracts: ReportSectionContracts,
    analysis_artifacts: Dict[str, Any],
) -> None:
    c = contracts.ensure("currency_data_quality")
    c.render_policy["allow_llm_rewrite"] = True

    currency_audit = _safe_dict(analysis_artifacts, "currency_audit")
    if currency_audit:
        c.status = "supported"
        sc = str(currency_audit.get("statement_currency", "") or "")
        tc = str(currency_audit.get("trading_currency", "") or "")
        if sc:
            c.add_fact("statement_currency", f"报表货币：{sc}",
                       source_types=[SRC_FINANCIAL_METRIC])
        if tc:
            c.add_fact("trading_currency", f"交易货币：{tc}",
                       source_types=[SRC_MARKET_DATA])
    else:
        c.add_blocked_reason("currency_audit_not_available")
        c.status = "gap"


# ── Quality checks across all contracts ────────────────────────────────


def _check_contract_quality(contracts: ReportSectionContracts) -> None:
    """Run cross-contract quality checks after all sections are built."""
    # Check citation binding mismatch: qualitative sections binding financial tables
    for sk in ["business_overview", "ownership_governance", "strategy_business",
               "risk_factors", "investment_conclusion"]:
        c = contracts.get(sk)
        if not c:
            continue
        for fact in c.facts:
            for st in fact.source_types:
                if st in {SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE,
                          SRC_THIRD_PARTY_STRUCTURED}:
                    c.add_quality_flag(f"citation_binding_mismatch:{st}")

    # Check risk_factors cashflow binding
    rc = contracts.get("risk_factors")
    if rc:
        for fact in rc.facts:
            if SRC_CASHFLOW_TABLE in fact.source_types:
                rc.add_quality_flag("risk_fallback_cashflow_binding")


# ── Helpers ─────────────────────────────────────────────────────────────


def _get_pdf_section_summaries(
    state: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
) -> List[Dict[str, Any]]:
    summaries = state.get("pdf_section_summaries", [])
    if isinstance(summaries, list) and summaries:
        return summaries
    summaries = analysis_artifacts.get("pdf_section_summaries", [])
    if isinstance(summaries, list):
        return summaries
    return []


def _get_pdf_section_chunks(
    state: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
) -> List[Dict[str, Any]]:
    chunks = state.get("pdf_section_chunks", [])
    if isinstance(chunks, list) and chunks:
        return chunks
    chunks = analysis_artifacts.get("pdf_section_chunks", [])
    if isinstance(chunks, list):
        return chunks
    return []


def _filter_summaries_by_type(
    summaries: List[Dict[str, Any]],
    types: Set[str],
) -> List[Dict[str, Any]]:
    return [
        s for s in summaries
        if isinstance(s, dict) and str(s.get("section_type", "") or "").lower() in types
    ]


def _filter_chunks_by_type(
    chunks: List[Dict[str, Any]],
    types: Set[str],
) -> List[Dict[str, Any]]:
    return [
        c for c in chunks
        if isinstance(c, dict) and str(c.get("section_type", "") or "").lower() in types
    ]


def _safe_dict(obj: Any, key: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    val = obj.get(key, {})
    return val if isinstance(val, dict) else {}


def _safe_list(obj: Any, key: str) -> List[Any]:
    if not isinstance(obj, dict):
        return []
    val = obj.get(key, [])
    return val if isinstance(val, list) else []


def _format_key_metrics(financial_metrics: Dict[str, Any]) -> str:
    """Format key financial metrics into a single line."""
    flat = _normalize_metrics_flat(financial_metrics)
    parts = []
    for key in ["revenue", "net_income", "operating_cash_flow", "free_cash_flow",
                 "total_assets", "total_liabilities", "gross_margin", "operating_margin"]:
        val = flat.get(key)
        if val is not None:
            parts.append(f"{key}: {val}")
    return "; ".join(parts[:8])


def _normalize_metrics_flat(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise financial_metrics to flat key->value dict.

    Handles both:
      { 'revenue': 123, 'net_income': 456, ... }           (flat – legacy)
      { 'metrics': [{'metric_name': 'revenue', 'value': 123}, ...] }  (nested array)
    """
    if not isinstance(raw, dict):
        return {}
    # Fast path: already flat
    if any(k in raw for k in ("revenue", "net_income", "total_assets")):
        return raw
    # Nested metrics array
    metrics_list = raw.get("metrics")
    if isinstance(metrics_list, list) and metrics_list:
        flat: Dict[str, Any] = {}
        for m in metrics_list:
            if not isinstance(m, dict):
                continue
            name = m.get("metric_name") or m.get("key") or ""
            value = m.get("value") or m.get("val")
            if name and value is not None:
                flat[str(name)] = value
        return flat
    return raw


def _financial_evidence_ids(
    financial_metrics: Dict[str, Any],
    tables: List[Dict[str, Any]],
    claims: List[Any],
) -> List[str]:
    ids: List[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)

    metrics_list = financial_metrics.get("metrics") if isinstance(financial_metrics, dict) else []
    if isinstance(metrics_list, list):
        for metric in metrics_list:
            if not isinstance(metric, dict):
                continue
            add(metric.get("source_evidence_id") or metric.get("source_id") or metric.get("evidence_id"))

    for table in tables:
        if not isinstance(table, dict):
            continue
        add(table.get("source_evidence_id") or table.get("evidence_id"))
        rows = table.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    add(row.get("source_evidence_id") or row.get("evidence_id"))

    for claim in claims:
        if isinstance(claim, dict):
            for eid in claim.get("evidence_ids") or []:
                add(eid)
    return ids


def _metric_evidence_ids(financial_metrics: Dict[str, Any], metric_key: str, fallback_ids: List[str]) -> List[str]:
    wanted = {metric_key, metric_key.replace("_billion", ""), metric_key.replace("_pct", "")}
    ids: List[str] = []
    metrics_list = financial_metrics.get("metrics") if isinstance(financial_metrics, dict) else []
    if isinstance(metrics_list, list):
        for metric in metrics_list:
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("metric_name") or metric.get("key") or "").strip()
            if name in wanted:
                eid = str(metric.get("source_evidence_id") or metric.get("source_id") or metric.get("evidence_id") or "").strip()
                if eid and eid not in ids:
                    ids.append(eid)
    return ids or list(fallback_ids[:3])


def _render_three_statement_table_markdown(tables: List[Dict[str, Any]], currency_context: CurrencyContext) -> str:
    preferred = [
        ("收入", {"revenue", "营业收入", "收入"}),
        ("净利润", {"net_income", "净利润"}),
        ("总资产", {"total_assets", "assets", "总资产"}),
        ("总负债", {"total_liabilities", "liabilities", "总负债"}),
        ("权益", {"equity", "total_equity", "所有者权益", "权益"}),
        ("经营现金流", {"operating_cash_flow", "netcash_operate", "经营现金流"}),
        ("投资现金流", {"investing_cash_flow", "netcash_invest", "投资现金流"}),
        ("筹资现金流", {"financing_cash_flow", "netcash_finance", "筹资现金流"}),
    ]
    rows_out: List[List[str]] = []
    seen: Set[str] = set()
    for label, keys in preferred:
        found = _find_statement_row(tables, keys)
        if not found:
            continue
        value = _safe_number(found.get("value"))
        if value is None:
            continue
        source = str(found.get("provider") or found.get("source_type") or "").strip() or "structured"
        period = str(found.get("period") or found.get("report_date") or "").strip()
        if label in seen:
            continue
        seen.add(label)
        row_context = _row_currency_context(found, currency_context)
        rows_out.append([label, _format_statement_amount(value, found, row_context), period, source])
    if len(rows_out) < 3:
        return ""
    lines = [
        "| 指标 | 金额 | 期间 | 来源 |",
        "|---|---:|---|---|",
    ]
    lines.extend(f"| {label} | {amount} | {period} | {source} |" for label, amount, period, source in rows_out)
    return "\n".join(lines)


def _find_statement_row(tables: List[Dict[str, Any]], keys: Set[str]) -> Dict[str, Any]:
    normalized_keys = {_normalize_metric_key(k) for k in keys}
    for table in tables:
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            line_item = _normalize_metric_key(row.get("line_item") or row.get("metric_name") or row.get("name"))
            if line_item in normalized_keys:
                return row
    return {}


def _normalize_metric_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "assets": "total_assets",
        "liabilities": "total_liabilities",
        "营业总收入": "收入",
        "营业收入": "收入",
        "归母净利润": "净利润",
        "所有者权益": "权益",
        "netcash_operate": "operating_cash_flow",
        "netcash_invest": "investing_cash_flow",
        "netcash_finance": "financing_cash_flow",
    }
    return aliases.get(text, text)


def _safe_number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if number != number:
            return None
        return number
    except (TypeError, ValueError):
        return None


def _format_cny_billion(value: float) -> str:
    return format_amount_for_context(value, build_currency_context(market="cn_a", statement_currency="CNY", display_currency="CNY"))


def _classify_business_fact(text: str) -> str:
    """Heuristic classification of business fact type."""
    lowered = str(text or "").lower()
    if any(t in lowered for t in ["主营", "业务", "产品", "销售", "品牌", "产品类型", "产品结构", "业务结构", "经营模式", "商业模式", "盈利模式"]):
        return "business_model"
    if any(t in lowered for t in ["渠道", "直销", "批发", "经销", "分销", "零售", "电商", "门店", "线上", "线下"]):
        return "sales_channel"
    if any(t in lowered for t in ["核心", "竞争", "优势", "壁垒", "护城河", "龙头", "领先", "专利"]):
        return "competitive_advantage"
    if any(t in lowered for t in ["战略", "市场", "发展", "规划", "布局", "目标", "定位"]):
        return "market_strategy"
    return "general_business"


def _business_overview_priority_score(text: str) -> int:
    lowered = str(text or "")
    score = 0
    priority_terms = [
        ("主营业务", 50),
        ("主要业务", 45),
        ("主营产品", 45),
        ("产品结构", 40),
        ("业务结构", 38),
        ("收入结构", 38),
        ("销售渠道", 36),
        ("渠道", 26),
        ("直销", 24),
        ("批发", 22),
        ("经销", 22),
        ("产品", 20),
        ("品牌", 14),
        ("工艺", 12),
        ("核心竞争力", 8),
        ("竞争优势", 8),
    ]
    for term, weight in priority_terms:
        if term in lowered:
            score += weight
    return score


def _fallback_business_overview_via_text_detector(
    c: "SectionEvidenceContract",
    state: Dict[str, Any],
    evidence_records: List[Dict[str, Any]],
) -> None:
    """当 bookmark 提取的业务概览章节为空时，用 pdf_section_detector
    纯文本匹配做回退——扫描原始 PDF 全文字找业务概览对应的章节文本。

    仅对 A 股生效（需要中文标题模式）。
    """
    market = _detect_market(state)
    if market != "cn_a":
        return
    try:
        from src.report.fact_extractors.pdf_section_detector import detect_sections
    except ImportError:
        return

    # 从 state/evidence_records 中拼出原始 PDF 全文
    text_sources: List[str] = []
    pdf_artifacts = state.get("pdf_artifacts") if isinstance(state.get("pdf_artifacts"), dict) else {}
    pdf_sections = pdf_artifacts.get("pdf_sections", []) if isinstance(pdf_artifacts.get("pdf_sections"), list) else []
    for sec in pdf_sections:
        if isinstance(sec, dict):
            txt = str(sec.get("text") or sec.get("content") or "")
            if len(txt) > 100:
                text_sources.append(txt)

    if not text_sources:
        # Also try pdf_section_summaries text from analysis_artifacts
        summaries = state.get("pdf_section_summaries", []) or []
        for s in summaries:
            if isinstance(s, dict):
                txt = str(s.get("summary_zh") or s.get("text") or s.get("content") or "")
                if len(txt) > 100:
                    text_sources.append(txt)

    if not text_sources:
        # Last try: concatenate all evidence content
        for rec in evidence_records:
            if isinstance(rec, dict) and str(rec.get("source_type", "")).lower() in {"cninfo_announcement", "exchange_announcement"}:
                txt = str(rec.get("content") or "")
                if len(txt) > 500:
                    text_sources.append(txt)

    combined = "\n\n".join(text_sources)
    if len(combined) < 200:
        return

    detected = detect_sections(combined, market="cn_a", include_unmatched=False)
    biz_text = detected.get("business_overview") or detected.get("business") or ""
    if not biz_text or len(biz_text.strip()) < 50:
        return

    clean = _clean_and_clip_pdf_text(biz_text, 800)
    if clean:
        fact_type = _classify_business_fact(clean)
        c.add_fact(fact_type, clean, source_types=["pdf_section_detector_fallback"])
        c.status = "partial"
        c.add_quality_flag("business_overview_used_text_detector_fallback")


def _detect_market(state: Dict[str, Any]) -> str:
    symbol = str(state.get("symbol", "") or "").upper()
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        return "cn_a"
    if symbol.endswith(".HK"):
        return "hk"
    if not symbol.endswith((".SS", ".SZ", ".HK")):
        return "us"
    return "generic"


def _currency_context(state: Dict[str, Any], analysis_artifacts: Dict[str, Any]) -> CurrencyContext:
    audit = _safe_dict(analysis_artifacts, "currency_audit") or _safe_dict(state, "currency_audit")
    return build_currency_context(
        symbol=str(audit.get("symbol") or state.get("symbol") or ""),
        market=str(audit.get("market") or _detect_market(state)),
        statement_currency=str(audit.get("statement_currency") or ""),
        display_currency=str(audit.get("display_currency") or ""),
    )


def _row_currency_context(row: Dict[str, Any], fallback: CurrencyContext) -> CurrencyContext:
    currency = str(row.get("currency") or row.get("unit") or "").split("_", 1)[0]
    if currency.upper() not in {"USD", "CNY", "HKD"}:
        return fallback
    return build_currency_context(
        market=fallback.market,
        statement_currency=currency,
        display_currency=currency,
    )


def _format_statement_amount(value: float, row: Dict[str, Any], context: CurrencyContext) -> str:
    """Convert unit/million/billion statement rows to base currency before display."""

    unit = str(row.get("unit") or "").lower()
    scale = str(row.get("scale") or "").lower()
    multiplier = 1.0
    if unit.endswith("_trillion") or scale == "trillion":
        multiplier = 1_000_000_000_000.0
    elif unit.endswith("_billion") or scale == "billion":
        multiplier = 1_000_000_000.0
    elif unit.endswith("_million") or scale == "million":
        multiplier = 1_000_000.0
    elif unit.endswith("_thousand") or scale == "thousand":
        multiplier = 1_000.0
    return format_amount_for_context(float(value) * multiplier, context)


def _format_billion_value(value: Any, context: CurrencyContext) -> str:
    number = _safe_number(value)
    if number is None:
        return ""
    currency = context.display_currency
    if currency == "CNY":
        return f"{number * 10:.2f} 亿元人民币"
    if currency == "HKD":
        return f"{number * 10:.2f} 亿港元"
    return f"{number:.2f} {'十亿美元' if currency == 'USD' else f'十亿{currency}'}"


def _normalize_sensitivity_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = payload.get("sensitivity") or payload.get("rows") or []
    if isinstance(rows, list) and rows:
        return [dict(row) if isinstance(row, dict) else {"value": row} for row in rows]
    scenarios = payload.get("scenario_values")
    if not isinstance(scenarios, dict):
        return []
    output: List[Dict[str, Any]] = []
    labels = {"bear": "悲观情景", "base": "基准情景", "bull": "乐观情景"}
    for key, value in scenarios.items():
        row = dict(value) if isinstance(value, dict) else {"value": value}
        row.setdefault("label", labels.get(str(key).lower(), str(key)))
        row.setdefault("scenario", str(key))
        output.append(row)
    return output


def _peer_row_has_metrics(row: Dict[str, Any]) -> bool:
    keys = (
        "revenue_growth_pct",
        "revenue_growth",
        "gross_margin_pct",
        "gross_margin",
        "net_margin_pct",
        "net_margin",
        "roe_pct",
        "roe",
        "revenue_billion",
        "net_income_billion",
        "free_cash_flow_billion",
    )
    return any(_safe_number(row.get(key)) is not None for key in keys)


def _business_profile_fallback(
    state: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
    evidence_records: List[Dict[str, Any]],
) -> tuple[str, str, str]:
    profile = _safe_dict(analysis_artifacts, "company_profile")
    candidates: List[tuple[str, str, str, str]] = []
    if profile:
        candidates.append((
            str(profile.get("business_summary") or profile.get("long_business_summary") or profile.get("description") or ""),
            str(profile.get("evidence_id") or ""),
            "company_profile",
            str(profile.get("period") or profile.get("source_period") or ""),
        ))
    identity = _safe_dict(state, "entity_resolution")
    for key in ("symbol_resolution", "topic_resolution"):
        resolved = _safe_dict(identity, key)
        candidates.append((
            str(resolved.get("business_summary") or resolved.get("description") or ""),
            "",
            "company_profile",
            str(resolved.get("period") or ""),
        ))
    for rec in evidence_records:
        source_type = str(rec.get("source_type") or "")
        if source_type not in {"company_profile", "yahoo_profile"}:
            continue
        metadata = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
        candidates.append((
            str(rec.get("content") or metadata.get("business_summary") or metadata.get("description") or ""),
            str(rec.get("evidence_id") or rec.get("sample_id") or ""),
            source_type,
            str(rec.get("source_period") or metadata.get("source_period") or rec.get("period") or ""),
        ))
    target_period = str(state.get("period") or "")
    for text, evidence_id, source_type, source_period in candidates:
        clean = clean_pdf_boilerplate(text).strip()
        if len(clean) < 20:
            continue
        if source_period and target_period and source_period.upper() != target_period.upper():
            clean = f"{clean}（稳定业务描述沿用自 {source_period} 公司资料，需以后续目标期正式披露复核。）"
        return clean, evidence_id, source_type
    return "", "", ""


def _detect_period(
    state: Dict[str, Any],
    evidence_records: List[Dict[str, Any]],
    financial_metrics: Dict[str, Any],
    tables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Detect the latest available period from all sources."""
    target_period = str(state.get("period", "") or "").upper()
    periods: List[str] = []
    period_source_types: Dict[str, set[str]] = {}

    def _record_period(period: str, source_type: str) -> None:
        if not period:
            return
        if period not in periods:
            periods.append(period)
        if source_type:
            period_source_types.setdefault(period, set()).add(source_type.strip().lower())

    # From financial_metrics
    metrics_list = financial_metrics.get("metrics", []) if isinstance(financial_metrics, dict) else []
    for m in metrics_list if isinstance(metrics_list, list) else []:
        if isinstance(m, dict):
            p = str(m.get("period", "") or "").strip().upper()
            _record_period(p, str(m.get("source_type") or "financial_metric"))

    # From tables
    for table in tables if isinstance(tables, list) else []:
        if isinstance(table, dict):
            p = str(table.get("period", "") or "").strip().upper()
            _record_period(p, str(table.get("source_type") or "financial_table"))
            for row in (table.get("rows", []) if isinstance(table.get("rows"), list) else []):
                if isinstance(row, dict):
                    p = str(row.get("period", "") or "").strip().upper()
                    _record_period(p, str(row.get("source_type") or "financial_table"))

    # From evidence_records
    for rec in evidence_records if isinstance(evidence_records, list) else []:
        if isinstance(rec, dict):
            p = str(rec.get("period", "") or "").strip().upper()
            _record_period(p, str(rec.get("source_type") or "evidence"))

    def _period_sort_key(period: str) -> tuple[int, int]:
        fy_match = re.fullmatch(r"FY(20\d{2})", period)
        if fy_match:
            return int(fy_match.group(1)), 4
        quarter_match = re.fullmatch(r"(20\d{2})Q([1-4])", period)
        if quarter_match:
            return int(quarter_match.group(1)), int(quarter_match.group(2))
        return 0, 0

    latest = max(periods, key=_period_sort_key) if periods else ""

    result: Dict[str, Any] = {
        "target_period": target_period,
        "latest_available_period": latest,
        "period_mismatch": False,
        "period_conflicts": [],
        "available_periods": periods,
        "latest_period_source_types": sorted(period_source_types.get(latest, set())),
    }

    if target_period and latest and target_period != latest:
        result["period_mismatch"] = True

    return result


def _infer_market_from_symbol(symbol: str) -> str:
    sym = symbol.upper().strip()
    if sym.endswith(".SS") or sym.endswith(".SZ"):
        return "cn_a"
    if sym.endswith(".HK"):
        return "hk"
    # No suffix inference: if it's short letters (NYSE/NASDAQ), it's US
    if sym.isalpha() and len(sym) <= 6:
        return "us"
    return ""


def _get_target_industry(target_symbol: str, peer_rows: List[Dict[str, Any]]) -> str:
    """Extract the target company's industry from peer_rows for industry-aware peer filtering."""
    target_upper = target_symbol.upper().strip()
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if sym == target_upper:
            industry = str(row.get("industry") or row.get("sector") or row.get("peer_group") or "").strip()
            if industry:
                return industry.lower()
    # Fallback: check analysis_artifacts
    return ""


def _get_peer_rows(
    state: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
    blackboard: Dict[str, Any],
) -> List[Dict[str, Any]]:
    peer_data = _safe_dict(analysis_artifacts, "peer_analysis")
    # peer_context 是 build_peer_comparison() 实际存储同行数据的位置
    peer_context = _safe_dict(analysis_artifacts, "peer_context")
    rows = (peer_context.get("peer_rows")
            or peer_data.get("peer_rows") or peer_data.get("rows")
            or analysis_artifacts.get("peer_rows")
            or blackboard.get("peer_rows")
            or state.get("peer_rows")
            or [])
    return rows if isinstance(rows, list) else []


def _get_approved_peer_symbols(
    analysis_artifacts: Dict[str, Any],
    blackboard: Dict[str, Any],
) -> Set[str]:
    approved: Set[str] = set()
    peer_data = _safe_dict(analysis_artifacts, "peer_analysis")
    peer_context = _safe_dict(analysis_artifacts, "peer_context")
    for source in [peer_data, peer_context, analysis_artifacts, blackboard]:
        if not isinstance(source, dict):
            continue
        for key in ["approved_peer_symbols", "peer_symbols"]:
            values = source.get(key)
            if isinstance(values, list):
                for v in values:
                    sym = str(v or "").strip().upper()
                    if sym:
                        approved.add(sym)
        for row in source.get("peer_rows", []) if isinstance(source.get("peer_rows"), list) else []:
            if isinstance(row, dict):
                sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
                if sym and not bool(row.get("is_target")):
                    approved.add(sym)
    return approved


def _render_peer_table_markdown(
    peer_rows: List[Dict[str, Any]],
    direct_peers: List[str],
    cross_market: List[str],
    target_symbol: str,
) -> str:
    """Render a clean peer table markdown with group labels."""
    table_symbols = set(direct_peers) | {str(target_symbol or "").strip().upper()}
    if not table_symbols:
        return ""
    lines = [
        "> 注：下表为当前 TTM 市场快照；财务分析章节的 FY2024 指标来自年度披露，二者期间不同，不作同期间数值替代。",
        "| 公司 | 代码 | 收入增速 | 毛利率 | 净利率 | ROE | 说明 |",
    ]
    lines.append("|------|------|---------|--------|--------|-----|------|")
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if sym not in table_symbols:
            continue
        name = str(row.get("company_name") or row.get("name") or sym)
        rev_growth = _format_peer_metric(row.get("revenue_growth_pct") or row.get("revenue_growth") or row.get("rev_growth"))
        gm = _format_peer_metric(row.get("gross_margin_pct") or row.get("gross_margin"))
        nm = _format_peer_metric(row.get("net_margin_pct") or row.get("net_margin"))
        roe = _format_peer_metric(row.get("roe_pct") or row.get("roe"))
        note = "目标公司" if sym == str(target_symbol or "").upper() else ""
        if sym in cross_market:
            note = note or "非同业参考" if not note else note
        elif sym in direct_peers:
            note = note or "可比公司"
        lines.append(f"| {name} | {sym} | {rev_growth} | {gm} | {nm} | {roe} | {note} |")
    return "\n".join(lines)


def _render_sensitivity_text(rows: List[Any], currency: str = "") -> str:
    if not rows:
        return ""
    currency_labels = {"CNY": "十亿元人民币", "HKD": "十亿港元", "USD": "十亿美元"}
    value_unit = currency_labels.get(str(currency or "").upper(), "十亿计价货币")
    parts = [f"估值敏感性分析（权益价值单位：{value_unit}；目标价单位：每股计价货币）："]
    for row in rows[:5]:
        if isinstance(row, dict):
            label = str(row.get("label") or row.get("scenario") or row.get("variable") or "")
            target_price = row.get("target_price")
            equity_value = row.get("equity_value_billion")
            value = row.get("value")
            if target_price is not None or equity_value is not None or value is not None:
                detail = []
                if equity_value is not None:
                    detail.append(f"权益价值={equity_value}")
                if target_price is not None:
                    detail.append(f"目标价={target_price}")
                if value is not None:
                    detail.append(f"数值={value}")
                parts.append(f"- {label}: " + "；".join(detail))
                continue
            base = str(row.get("base") or row.get("base_value") or "")
            low = str(row.get("low") or "")
            high = str(row.get("high") or "")
            parts.append(f"- {label}(基准={base}): {low} - {high}")
    return "\n".join(parts) if len(parts) > 1 else ""


def _format_peer_metric(value: Any) -> str:
    number = _safe_number(value)
    return "" if number is None else f"{number:.2f}%"


def _get_industry_risk_fallback(
    state: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
) -> str:
    """Get industry-family conservative risk fallback text.

    Does NOT reference any financial table source. Returns empty string
    if no industry policy is available.
    """
    # Try to get industry family from state/blackboard
    blackboard = _safe_dict(state, "research_blackboard")
    industry_profile = _safe_dict(blackboard, "industry_profile")
    industry_family = str(industry_profile.get("industry_family", "") or "")
    symbol = str(state.get("symbol") or "").upper()
    identity = _safe_dict(state, "entity_resolution")
    company_name = str(identity.get("company_name") or state.get("company_name") or "")
    if symbol.startswith("600519") or "茅台" in company_name or "白酒" in company_name:
        return (
            "行业风险：白酒消费需求、渠道库存和批价波动会影响收入节奏与利润率；"
            "高端产品价格体系若出现明显松动，可能削弱品牌溢价和经销商信心；"
            "食品安全、税收和消费场景变化也是需要持续跟踪的合规与需求变量。"
        )

    # Conservative fallbacks by industry family
    fallbacks = {
        "consumer_staples": (
            "行业竞争风险：消费品行业面临品牌替代、渠道变化和消费趋势转变的风险；"
            "原材料价格波动可能影响毛利率；"
            "监管政策变化（如食品安全、广告合规）可能增加经营成本。"
        ),
        "consumer_discretionary": (
            "行业风险：可选消费受宏观经济周期和消费者信心影响较大；"
            "市场竞争加剧可能压缩利润空间；"
            "线上渠道转型和线下客流变化是持续性挑战。"
        ),
        "technology": (
            "行业风险：技术迭代快，研发投入需求大；"
            "国际竞争和供应链变化可能影响业务稳定性；"
            "数据隐私、AI 监管等合规要求趋严。"
        ),
        "healthcare": (
            "行业风险：药品/器械集采政策影响定价；"
            "研发周期长且成功率不确定；"
            "行业监管与合规成本持续上升。"
        ),
        "financials": (
            "行业风险：利率、汇率和宏观经济周期影响资产质量和盈利能力；"
            "信用风险和流动性管理是核心挑战；"
            "监管资本要求趋严。"
        ),
        "energy": (
            "行业风险：大宗商品价格波动直接影响收入和利润；"
            "全球能源转型政策带来结构性变化；"
            "环保和碳减排合规成本上升。"
        ),
        "industrials": (
            "行业风险：宏观经济和固定资产投资周期影响需求；"
            "原材料价格和供应链稳定性是关键变量；"
            "国际业务面临地缘政治和贸易政策风险。"
        ),
    }

    return fallbacks.get(industry_family, "")


def _format_peer_group_label(groups: List) -> str:
    """Format peer group label for use in contract metadata."""
    labels = []
    for g in groups:
        if isinstance(g, dict):
            labels.append(g.get("group_label", "reference"))
    return ", ".join(labels) if labels else ""


def _is_pdf_gap_summary(text: str) -> bool:
    """Detect if a PDF section summary is a 'gap' placeholder rather than real content.

    When all chunks for a section are noise (headers, TOC, boilerplate, mojibake),
    the summarizer produces a gap summary like "已获取官方PDF但候选片段主要是页眉目录指针..."
    These should NOT set section status to 'supported'.
    """
    gap_markers = ["页眉", "目录指针", "乱码", "审计模板", "未能稳定抽取",
                   "未稳定抽取", "data_gap", "候选片段主要是", "无有效文本",
                   "已获取官方"]
    lowered = text.lower()
    marker_count = sum(1 for m in gap_markers if m in lowered)
    return marker_count >= 2


def _is_pdf_toc_text(text: str) -> bool:
    """Detect if text is a PDF table of contents rather than actual section content.

    TOC text patterns (language-agnostic, no hardcoded language assumptions):
      - Lines with "Section" followed by a Roman numeral or word
      - Lines ending with dotted leader and page number
      - Lines that are pure page numbers
      - High proportion of lines matching TOC patterns
    Returns True if the text appears to be TOC content.
    """
    if not text or len(text) < 40:
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False

    toc_line_count = 0
    for line in lines:
        # "Section III ..." or "Section 1 ..."
        if re.search(r"(?i)^Section\s+(?:[IVXLCDM]+\b|\d+)", line):
            toc_line_count += 1
            continue
        # Dotted leader ending in page number: "Title.............. 5"
        if re.search(r"[\.…]{4,}\s*\d+\s*$", line) and len(line) > 30:
            toc_line_count += 1
            continue
        # Pure page-number line
        if re.match(r"^\d{1,3}\s*$", line):
            toc_line_count += 1
            continue
        # "Contents" header
        if re.match(r"(?i)^contents?\s*$", line):
            toc_line_count += 1
            continue

    # If more than 30% of non-empty lines look like TOC, treat as TOC text
    return (toc_line_count / max(len(lines), 1)) >= 0.30


def _apply_pdf_fallback(
    contracts: ReportSectionContracts,
    pdf_section_summaries: List[Dict[str, Any]],
    pdf_section_chunks: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
) -> None:
    """Fallback: use raw PDF text for gap sections instead of leaving them empty.

    Fires only when a section's status is still 'gap' after all structured
    extraction failed. Tries three sources in order:
      1. pdf_section_summaries
      2. pdf_section_chunks
      3. evidence_records (where _get_pdf_section_chunks may not have found them)
    The LLM rewrite pass (Fix 4) can clean up the raw text afterward.
    """
    SECTION_PDF_TYPES = {
        "business_overview": {"business_overview", "business", "strategy_business"},
        "strategy_business": {"strategy_business", "management_discussion", "mda", "strategy"},
        "ownership_governance": {"ownership_governance", "governance"},
        "risk_factors": {"risk_factors", "risks"},
    }

    for sk, pdf_types in SECTION_PDF_TYPES.items():
        contract = contracts.get(sk)
        if not contract or contract.status != "gap":
            continue

        # Priority 1: try summaries
        found = False
        for summary in pdf_section_summaries:
            if summary.get("section_type") not in pdf_types:
                continue
            text = str(summary.get("summary_zh") or summary.get("text") or summary.get("content") or "")
            if not text or len(text.strip()) < 60:
                continue
            if _is_pdf_gap_summary(text):
                continue
            if _is_pdf_toc_text(text):
                continue
            clean = _clean_and_clip_pdf_text(text, 600)
            if clean and len(clean.strip()) >= 60:
                eid = str(summary.get("evidence_id") or summary.get("chunk_id") or "")
                contract.add_fact("pdf_fallback", clean,
                                  evidence_ids=[eid] if eid else [],
                                  source_types=["annual_report_pdf_section_summary"])
                contract.status = "partial"
                _clear_not_found_blockers_after_pdf_fallback(contract)
                contract.add_quality_flag(f"{sk}_pdf_summary_fallback")
                found = True
                break

        # Priority 2: try section chunks
        if not found:
            for chunk in pdf_section_chunks:
                if chunk.get("section_type") not in pdf_types:
                    continue
                text = str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
                if not text or len(text.strip()) < 100:
                    continue
                if _is_pdf_gap_summary(text):
                    continue
                if _is_pdf_toc_text(text):
                    continue
                clean = _clean_and_clip_pdf_text(text, 500)
                if clean and len(clean.strip()) >= 60:
                    eid = str(chunk.get("evidence_id") or chunk.get("chunk_id") or "")
                    contract.add_fact("pdf_fallback", clean,
                                      evidence_ids=[eid] if eid else [],
                                      source_types=["annual_report_pdf_chunk"])
                    contract.status = "partial"
                    _clear_not_found_blockers_after_pdf_fallback(contract)
                    contract.add_quality_flag(f"{sk}_pdf_chunk_fallback")
                    found = True
                    break

        # Priority 3: try evidence_records directly
        # (pdf_section_chunks may be empty even when evidence_records have PDF chunks)
        if not found:
            for rec in evidence_records:
                st = str(rec.get("source_type") or "")
                if "pdf" not in st.lower() and "annual" not in st.lower():
                    continue
                meta = rec.get("metadata") or {}
                if isinstance(meta, dict) and meta.get("section_type") not in pdf_types:
                    continue
                if isinstance(meta, dict) and not meta.get("section_type"):
                    # If no section_type metadata, try content-based matching
                    text_hint = str(rec.get("content") or "")[:100]
                    if not any(t in text_hint for t in ["管理层讨论与分析", "业务概", "风险提示"]):
                        continue
                text = _clip_at_sentence_boundary(str(rec.get("content") or ""), 600)
                if not text or len(text.strip()) < 80:
                    continue
                if _is_pdf_gap_summary(text):
                    continue
                if _is_pdf_toc_text(text):
                    continue
                clean = _clean_and_clip_pdf_text(text, 500)
                if clean and len(clean.strip()) >= 60:
                    eid = str(rec.get("evidence_id") or "")
                    contract.add_fact("pdf_fallback", clean,
                                      evidence_ids=[eid] if eid else [],
                                      source_types=[st])
                    contract.status = "partial"
                    _clear_not_found_blockers_after_pdf_fallback(contract)
                    contract.add_quality_flag(f"{sk}_evidence_fallback")
                    found = True
                    break


def _clear_not_found_blockers_after_pdf_fallback(contract: SectionEvidenceContract) -> None:
    """A section with usable PDF fallback evidence is partial, not not-found."""

    contract.blocked_reasons = [
        reason
        for reason in contract.blocked_reasons
        if not str(reason).endswith("_not_found")
        and "pdf_sections_not_found" not in str(reason)
        and "pdf_chunks_not_found" not in str(reason)
    ]


def _apply_dossier_pack_fallback(
    contract: SectionEvidenceContract,
    section_dossiers: Dict[str, Any],
    section_key: str,
    *,
    fact_type: str,
    source_type: str,
    min_chars: int = 40,
) -> None:
    """Turn existing section dossier material into a bounded evidence pack.

    This is not a substitute for official PDF evidence. It prevents false gap
    states when the dossier already contains product/user-facing facts or
    deterministic writing guidance that can support a draft section.
    """

    dossier = _safe_dict(section_dossiers, section_key)
    if not dossier:
        return
    texts: List[str] = []
    for key in ("key_facts", "suggested_paragraphs", "deterministic_blocks"):
        for item in _safe_list(dossier, key):
            text = str(item or "").strip()
            if len(text) >= min_chars and not _is_pdf_gap_summary(text):
                texts.append(_clip_at_sentence_boundary(text, 500))
    if not texts:
        return
    seen: set[str] = set()
    for text in texts[:3]:
        if text in seen:
            continue
        seen.add(text)
        contract.add_fact(fact_type, text, source_types=[source_type])
    if contract.facts:
        contract.status = "partial" if len(contract.facts) < 2 else "supported"
        contract.add_quality_flag(f"{section_key}_uses_section_evidence_pack")
        contract.blocked_reasons = [
            reason
            for reason in contract.blocked_reasons
            if "not_found" not in str(reason)
            and "no_metrics_available" not in str(reason)
            and "used_profile_fallback" not in str(reason)
        ]
