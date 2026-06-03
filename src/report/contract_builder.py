"""Contract Builder: transforms evidence, PDF summaries, and analysis artifacts
into ReportSectionContracts.

This is the core of contract-first generation. Every section's allowed/forbidden
evidence sources, structured facts, and blocked reasons are determined here,
BEFORE FinalAnswerAgent runs.
"""

from __future__ import annotations

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


def _get_annual_report_sections(
    state: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract SEC 10-K annual_report_sections from state or analysis_artifacts."""
    sections = state.get("annual_report_sections", [])
    if isinstance(sections, list) and sections:
        return sections
    sections = analysis_artifacts.get("annual_report_sections", [])
    if isinstance(sections, list):
        return sections
    # Also check analysis_artifacts.sections
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
    _build_executive_summary(contracts, evidence_records, financial_metrics, section_dossiers)
    _build_business_overview(contracts, pdf_section_summaries, pdf_section_chunks,
                             evidence_records, analysis_artifacts, state,
                             annual_report_sections=annual_report_sections)
    _build_ownership_governance(contracts, pdf_section_summaries, pdf_section_chunks,
                                evidence_records, state,
                                annual_report_sections=annual_report_sections)
    _build_strategy_business(contracts, pdf_section_summaries, pdf_section_chunks,
                             evidence_records, financial_metrics, analysis_artifacts,
                             annual_report_sections=annual_report_sections)
    _build_three_statement_summary(contracts, financial_metrics, tables)
    _build_financial_analysis(contracts, financial_metrics, tables, evidence_records, section_dossiers)
    _build_peer_compare(contracts, peer_rows, analysis_artifacts, blackboard, symbol)
    _build_valuation(contracts, valuation_model, financial_metrics)
    _build_valuation_sensitivity(contracts, valuation_model, valuation_sensitivity)
    _build_risk_factors(contracts, pdf_section_summaries, pdf_section_chunks,
                        evidence_records, analysis_artifacts, state,
                        annual_report_sections=annual_report_sections)
    _build_investment_conclusion(contracts, financial_metrics, valuation_model, evidence_records)
    _build_period_note(contracts, period_info)
    _build_currency_data_quality(contracts, analysis_artifacts)

    # Run cross-section quality checks
    _check_contract_quality(contracts)

    return contracts


# ── Section builders ────────────────────────────────────────────────────


def _build_executive_summary(
    contracts: ReportSectionContracts,
    evidence_records: List[Dict[str, Any]],
    financial_metrics: Dict[str, Any],
    section_dossiers: Dict[str, Any],
) -> None:
    c = contracts.ensure("executive_summary")
    c.allowed_source_types = list(ALLOWED_FINANCIAL)
    c.forbidden_source_types = []
    c.render_policy["allow_llm_rewrite"] = True

    # Extract key metrics
    metrics_text = _format_key_metrics(financial_metrics)
    if metrics_text:
        c.add_fact("key_metrics", metrics_text, source_types=[SRC_FINANCIAL_METRIC])
        c.status = "supported"

    # Check for existing dossier content
    dossier = _safe_dict(section_dossiers, "executive_summary")
    if dossier:
        suggested = _safe_list(dossier, "suggested_paragraphs")
        for para in suggested[:1]:
            if isinstance(para, str) and len(para) > 50:
                c.add_fact("executive_synthesis", para[:400],
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
    annual_report_sections: List[Dict[str, Any]] = None,
) -> None:
    c = contracts.ensure("business_overview")
    c.allowed_source_types = list(ALLOWED_QUALITATIVE_PDF_ONLY)
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("business_overview", [])
    c.render_policy["allow_llm_rewrite"] = False

    if annual_report_sections is None:
        annual_report_sections = []

    # Collect PDF evidence for business overview
    biz_chunks = _filter_chunks_by_type(pdf_section_chunks, {
        "business_overview", "business", "strategy_business",
    })
    biz_summaries = _filter_summaries_by_type(pdf_section_summaries, {
        "business_overview", "business", "strategy_business",
    })

    evidence_ids_used: List[str] = []

    # Extract business model / products from PDF summaries
    for summary in biz_summaries:
        text = str(summary.get("summary_zh") or summary.get("text") or summary.get("content") or "")
        eid = str(summary.get("evidence_id") or "") or str(summary.get("chunk_id") or "")

        has_boilerplate = text_contains_pdf_boilerplate(text)

        if has_boilerplate:
            c.add_quality_flag("business_overview_boilerplate_in_summary")
            text = clean_pdf_boilerplate(text)

        if not text or len(text.strip()) < 30:
            continue

        # Classify fact type
        fact_type = _classify_business_fact(text)
        clean = clean_pdf_boilerplate(text)[:600]
        if clean:
            c.add_fact(fact_type, clean,
                       evidence_ids=[eid] if eid else [],
                       source_types=[SRC_ANNUAL_REPORT_PDF_SUMMARY])
            if eid and eid not in evidence_ids_used:
                evidence_ids_used.append(eid)
            if c.status == "gap":
                c.status = "partial"

    # Also extract from chunks (more granular)
    for chunk in biz_chunks:
        text = str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
        eid = str(chunk.get("evidence_id") or "") or str(chunk.get("chunk_id") or "")
        if not text or len(text.strip()) < 30:
            continue
        if eid in evidence_ids_used:
            continue
        clean = clean_pdf_boilerplate(text)[:600]
        if clean:
            fact_type = _classify_business_fact(clean)
            c.add_fact(fact_type, clean,
                       evidence_ids=[eid] if eid else [],
                       source_types=[SRC_ANNUAL_REPORT_PDF_CHUNK])
            if eid and eid not in evidence_ids_used:
                evidence_ids_used.append(eid)
            if c.status == "gap":
                c.status = "partial"

    # SEC 10-K Item 1 Business section (US market fallback)
    if c.status == "gap":
        sec_biz = _get_annual_report_text_by_sec_item(annual_report_sections, {"business"})
        for item in sec_biz:
            text = item["text"][:800]
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                c.add_fact("business_model",
                           text[:600],
                           evidence_ids=[eid] if eid else [],
                           source_types=[SRC_SEC_10K_SECTION])
                if eid and eid not in evidence_ids_used:
                    evidence_ids_used.append(eid)
                if c.status == "gap":
                    c.status = "supported"
                    c.add_quality_flag("business_overview_uses_sec_10k")
                break

    # Update status based on fact count
    if len(c.facts) >= 2 and evidence_ids_used:
        c.status = "supported"
    elif len(c.facts) >= 1:
        c.status = "partial"
    else:
        # Try yahoo profile fallback
        for rec in evidence_records:
            if str(rec.get("source_type", "") or "") == "yahoo_profile":
                content = str(rec.get("content") or "")[:500]
                if content and len(content) > 50:
                    c.add_fact("business_profile_fallback", content,
                               evidence_ids=[str(rec.get("evidence_id", ""))],
                               source_types=["yahoo_profile"])
                    c.status = "fallback"
                    c.add_blocked_reason("business_overview_used_yahoo_fallback")
                    break
        else:
            c.add_blocked_reason("business_overview_pdf_chunks_not_found")

    # Check for fragments in facts
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
    c.render_policy["allow_llm_rewrite"] = False

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
        c.add_fact("governance_structure", text[:500],
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
        c.add_fact("governance_detail", text[:400],
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
            text = item["text"][:800]
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                c.add_fact("governance_structure",
                           text[:500],
                           evidence_ids=[eid] if eid else [],
                           source_types=[SRC_SEC_10K_SECTION])
                c.status = "supported"
                c.add_quality_flag("governance_uses_sec_10k")
                break

    if len(c.facts) >= 1:
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
    c.render_policy["allow_llm_rewrite"] = False

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
        # Check for fragments
        if text_contains_fragments(text):
            c.add_quality_flag("strategy_fragments_in_summary")
        clean = clean_pdf_boilerplate(text)[:600]
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
            text = item["text"][:800]
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                c.add_fact("strategy_discussion",
                           text[:600],
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
        clean = clean_pdf_boilerplate(text)[:500]
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
            "公司战略分析应围绕品牌力、渠道效率、产品结构、定价能力、"
            "现金流稳定性与分红能力展开；行业竞争格局和公司战略执行将共同影响"
            "收入增长、利润率稳定性和估值弹性。"
        )


def _build_three_statement_summary(
    contracts: ReportSectionContracts,
    financial_metrics: Dict[str, Any],
    tables: List[Dict[str, Any]],
) -> None:
    c = contracts.ensure("three_statement_summary")
    c.allowed_source_types = list(ALLOWED_FINANCIAL_TABLES_ONLY)
    c.forbidden_source_types = []
    c.render_policy["allow_llm_rewrite"] = False

    # Add financial metrics as facts
    key_metrics = ["revenue", "net_income", "total_assets", "total_liabilities",
                   "operating_cash_flow", "free_cash_flow"]
    facts_added = 0
    for km in key_metrics:
        val = financial_metrics.get(km)
        if val is not None:
            c.add_fact("financial_line_item", f"{km}: {val}",
                       source_types=[SRC_FINANCIAL_METRIC])
            facts_added += 1

    if facts_added >= 3:
        c.status = "supported"
    elif facts_added >= 1:
        c.status = "partial"
    else:
        c.add_blocked_reason("three_statement_insufficient_metrics")

    # Add table markdown if available
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
) -> None:
    c = contracts.ensure("financial_analysis")
    c.allowed_source_types = list(ALLOWED_FINANCIAL)
    c.forbidden_source_types = []

    metrics_text = _format_key_metrics(financial_metrics)
    if metrics_text:
        c.add_fact("financial_metrics_summary", metrics_text,
                   source_types=[SRC_FINANCIAL_METRIC])
        c.status = "supported"

    # Check for existing dossier deterministic blocks
    dossier = _safe_dict(section_dossiers, "financial_analysis")
    if dossier:
        blocks = _safe_list(dossier, "deterministic_blocks")
        for block in blocks:
            if isinstance(block, str) and len(block) > 40:
                c.deterministic_text = block[:800]
                break

    if c.status == "gap":
        c.add_blocked_reason("financial_analysis_insufficient_metrics")


def _build_peer_compare(
    contracts: ReportSectionContracts,
    peer_rows: List[Dict[str, Any]],
    analysis_artifacts: Dict[str, Any],
    blackboard: Dict[str, Any],
    target_symbol: str,
) -> None:
    c = contracts.ensure("peer_compare")
    c.allowed_source_types = [SRC_PEER_DATA, SRC_MARKET_DATA]
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("peer_compare", [])

    if not peer_rows:
        c.add_blocked_reason("peer_rows_not_available")
        return

    # Get approved peer symbols
    approved = _get_approved_peer_symbols(analysis_artifacts, blackboard)

    # Filter and classify peers
    target_market = _infer_market_from_symbol(target_symbol)
    target_industry = _get_target_industry(target_symbol, peer_rows)
    direct_peers: List[str] = []
    cross_market: List[str] = []

    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not sym:
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

    if direct_peers:
        c.status = "supported"
    elif cross_market:
        c.status = "partial"
        c.add_blocked_reason("peer_only_cross_market_reference")
    else:
        c.status = "gap"
        c.add_blocked_reason("peer_no_approved_symbols")

    # Store peer table markdown as deterministic text
    if peer_rows:
        table_md = _render_peer_table_markdown(peer_rows, direct_peers, cross_market, target_symbol)
        if table_md:
            c.deterministic_text = table_md


def _build_valuation(
    contracts: ReportSectionContracts,
    valuation_model: Dict[str, Any],
    financial_metrics: Dict[str, Any],
) -> None:
    c = contracts.ensure("valuation")
    c.allowed_source_types = [SRC_VALUATION_MODEL, SRC_FINANCIAL_METRIC, SRC_MARKET_DATA]
    c.forbidden_source_types = [SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE]

    if not valuation_model:
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

    pe = valuation_model.get("pe_ratio")
    pb = valuation_model.get("pb_ratio")
    ps = valuation_model.get("ps_ratio")
    dcf = valuation_model.get("dcf_value")

    facts_added = 0
    if pe is not None:
        c.add_fact("pe_ratio", f"P/E: {pe}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1
    if pb is not None:
        c.add_fact("pb_ratio", f"P/B: {pb}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1
    if ps is not None:
        c.add_fact("ps_ratio", f"P/S: {ps}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1
    if dcf is not None:
        c.add_fact("dcf_value", f"DCF: {dcf}", source_types=[SRC_VALUATION_MODEL])
        facts_added += 1

    if facts_added >= 2:
        c.status = "supported"
    elif facts_added >= 1:
        c.status = "partial"
    else:
        c.add_blocked_reason("valuation_no_metrics_available")


def _build_valuation_sensitivity(
    contracts: ReportSectionContracts,
    valuation_model: Dict[str, Any],
    valuation_sensitivity: Dict[str, Any],
) -> None:
    c = contracts.ensure("valuation_sensitivity")
    c.allowed_source_types = [SRC_VALUATION_MODEL]
    c.forbidden_source_types = [SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE]

    if not valuation_sensitivity:
        vm_status = str(valuation_model.get("valuation_status", "") or "") if valuation_model else ""
        if vm_status in ("rough_observation_only", "blocked_due_to_incomplete_inputs"):
            c.add_blocked_reason(f"valuation_sensitivity_blocked:{vm_status}")
            c.status = "fallback"
        else:
            c.add_blocked_reason("valuation_sensitivity_not_available")
        return

    rows = valuation_sensitivity.get("sensitivity") or valuation_sensitivity.get("rows") or []
    if rows:
        c.deterministic_text = _render_sensitivity_text(rows)
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
) -> None:
    c = contracts.ensure("risk_factors")
    c.allowed_source_types = list(ALLOWED_QUALITATIVE_PDF_ONLY | {SRC_INDUSTRY_POLICY})
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("risk_factors", [])
    c.render_policy["allow_llm_rewrite"] = False

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
        c.add_fact("official_risk_summary", text[:600],
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
            c.add_fact("official_risk_detail", text[:500],
                       evidence_ids=[eid] if eid else [],
                       source_types=[SRC_ANNUAL_REPORT_PDF_CHUNK])
            if eid and eid not in evidence_ids_used:
                evidence_ids_used.append(eid)
            if c.status == "gap":
                c.status = "partial"

    # SEC 10-K Item 1A Risk Factors (US market)
    if c.status == "gap":
        sec_risk = _get_annual_report_text_by_sec_item(annual_report_sections, {"risk_factors"})
        for item in sec_risk:
            text = item["text"][:1200]
            eid = item["evidence_id"]
            if text and len(text.strip()) >= 50:
                c.add_fact("official_risk_summary",
                           text[:1000],
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


def _build_investment_conclusion(
    contracts: ReportSectionContracts,
    financial_metrics: Dict[str, Any],
    valuation_model: Dict[str, Any],
    evidence_records: List[Dict[str, Any]],
) -> None:
    c = contracts.ensure("investment_conclusion")
    c.allowed_source_types = list(ALLOWED_FINANCIAL)
    c.forbidden_source_types = FORBIDDEN_SECTION_SOURCE_TYPES.get("investment_conclusion", [])

    has_financial = bool(financial_metrics.get("revenue")) or bool(financial_metrics.get("net_income"))
    has_valuation = bool(valuation_model) and valuation_model.get("valuation_available") is not False

    if has_financial or has_valuation:
        c.add_fact("conclusion_basis", "综合财务质量、估值、同行与风险证据后形成审慎观察。",
                   source_types=[SRC_FINANCIAL_METRIC])
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
    c.render_policy["allow_llm_rewrite"] = False

    latest = period_info.get("latest_available_period", "")
    target = period_info.get("target_period", "")
    mismatch = period_info.get("period_mismatch", False)

    if latest:
        c.add_fact("latest_period", f"最新可得披露数据期：{latest}",
                   source_types=[SRC_FINANCIAL_METRIC])
        c.status = "supported"
    else:
        c.add_blocked_reason("period_metadata_missing")
        c.status = "gap"

    if mismatch:
        c.add_quality_flag("period_mismatch")


def _build_currency_data_quality(
    contracts: ReportSectionContracts,
    analysis_artifacts: Dict[str, Any],
) -> None:
    c = contracts.ensure("currency_data_quality")
    c.render_policy["allow_llm_rewrite"] = False

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
    parts = []
    for key in ["revenue", "net_income", "operating_cash_flow", "free_cash_flow",
                 "total_assets", "total_liabilities", "gross_margin", "operating_margin"]:
        val = financial_metrics.get(key)
        if val is not None:
            parts.append(f"{key}: {val}")
    return "; ".join(parts[:8])


def _classify_business_fact(text: str) -> str:
    """Heuristic classification of business fact type."""
    lowered = text.lower()
    if any(t in lowered for t in ["主营", "业务", "产品", "销售", "品牌", "茅台", "系列酒"]):
        return "business_model"
    if any(t in lowered for t in ["渠道", "直销", "批发", "i茅台", "经销"]):
        return "sales_channel"
    if any(t in lowered for t in ["核心", "竞争", "优势", "壁垒", "护城河"]):
        return "competitive_advantage"
    if any(t in lowered for t in ["战略", "市场", "发展", "规划", "布局"]):
        return "market_strategy"
    return "general_business"


def _detect_market(state: Dict[str, Any]) -> str:
    symbol = str(state.get("symbol", "") or "").upper()
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        return "cn_a"
    if symbol.endswith(".HK"):
        return "hk"
    if not symbol.endswith((".SS", ".SZ", ".HK")):
        return "us"
    return "generic"


def _detect_period(
    state: Dict[str, Any],
    evidence_records: List[Dict[str, Any]],
    financial_metrics: Dict[str, Any],
    tables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Detect the latest available period from all sources."""
    target_period = str(state.get("period", "") or "").upper()
    periods: List[str] = []

    # From financial_metrics
    metrics_list = financial_metrics.get("metrics", []) if isinstance(financial_metrics, dict) else []
    for m in metrics_list if isinstance(metrics_list, list) else []:
        if isinstance(m, dict):
            p = str(m.get("period", "") or "").strip().upper()
            if p and p not in periods:
                periods.append(p)

    # From tables
    for table in tables if isinstance(tables, list) else []:
        if isinstance(table, dict):
            p = str(table.get("period", "") or "").strip().upper()
            if p and p not in periods:
                periods.append(p)
            for row in (table.get("rows", []) if isinstance(table.get("rows"), list) else []):
                if isinstance(row, dict):
                    p = str(row.get("period", "") or "").strip().upper()
                    if p and p not in periods:
                        periods.append(p)

    # From evidence_records
    for rec in evidence_records if isinstance(evidence_records, list) else []:
        if isinstance(rec, dict):
            p = str(rec.get("period", "") or "").strip().upper()
            if p and p not in periods:
                periods.append(p)

    # Sort: FY periods first (FY2025 > FY2024), then quarterly
    fy_periods = sorted([p for p in periods if p.startswith("FY")], reverse=True)
    q_periods = sorted([p for p in periods if not p.startswith("FY")], reverse=True)
    all_sorted = fy_periods + q_periods
    latest = all_sorted[0] if all_sorted else ""

    result: Dict[str, Any] = {
        "target_period": target_period,
        "latest_available_period": latest,
        "period_mismatch": False,
        "period_conflicts": [],
        "available_periods": periods,
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
    rows = (peer_data.get("peer_rows") or peer_data.get("rows")
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
    for source in [peer_data, analysis_artifacts, blackboard]:
        if not isinstance(source, dict):
            continue
        for key in ["approved_peer_symbols", "peer_symbols"]:
            values = source.get(key)
            if isinstance(values, list):
                for v in values:
                    sym = str(v or "").strip().upper()
                    if sym:
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
    lines = ["| 公司 | 代码 | 收入增速 | 毛利率 | 净利率 | ROE | 说明 |"]
    lines.append("|------|------|---------|--------|--------|-----|------|")
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if sym not in table_symbols:
            continue
        name = str(row.get("company_name") or row.get("name") or sym)
        rev_growth = str(row.get("revenue_growth") or row.get("rev_growth") or "")
        gm = str(row.get("gross_margin") or "")
        nm = str(row.get("net_margin") or "")
        roe = str(row.get("roe") or "")
        note = "目标公司" if sym == target_symbol else ""
        if sym in cross_market:
            note = note or "非同业参考" if not note else note
        elif sym in direct_peers:
            note = note or "可比公司"
        lines.append(f"| {name} | {sym} | {rev_growth} | {gm} | {nm} | {roe} | {note} |")
    return "\n".join(lines)


def _render_sensitivity_text(rows: List[Any]) -> str:
    if not rows:
        return ""
    parts = ["估值敏感性分析："]
    for row in rows[:5]:
        if isinstance(row, dict):
            label = str(row.get("label") or row.get("variable") or "")
            base = str(row.get("base") or row.get("base_value") or "")
            low = str(row.get("low") or "")
            high = str(row.get("high") or "")
            parts.append(f"- {label}(基准={base}): {low} - {high}")
    return "\n".join(parts) if len(parts) > 1 else ""


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
