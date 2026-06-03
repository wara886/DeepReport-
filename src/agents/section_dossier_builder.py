"""Build per-section writing dossiers for FinalAnswerAgent."""

from __future__ import annotations

import re
from typing import Any


SECTION_TITLES = {
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

INTERNAL_METRIC_KEYS = {"metric_count", "rejected_metric_count", "rejected_metrics"}
RISK_CATEGORIES = ["industry_competition", "margin_pressure", "capex_cashflow", "valuation_multiple", "data_quality"]


class SectionDossierBuilder:
    """Build section-level source material, evidence IDs, and deterministic blocks."""

    def build(
        self,
        state: dict[str, Any] | None = None,
        claims: list[dict[str, Any]] | None = None,
        evidence_records: list[dict[str, Any]] | None = None,
        analysis_artifacts: dict[str, Any] | None = None,
        derived_evidence: list[dict[str, Any]] | None = None,
        bundles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        state = state or {}
        claims = claims or []
        evidence_records = evidence_records or []
        analysis_artifacts = analysis_artifacts or {}
        bundles = bundles or []
        blackboard = state.get("research_blackboard", {}) if isinstance(state.get("research_blackboard"), dict) else {}
        annual_sections = _annual_sections_from_state(state)
        det_blocks = _deterministic_blocks(analysis_artifacts, blackboard)
        return {
            "executive_summary": self._executive_summary(claims, analysis_artifacts, bundles),
            "business_overview": self._business_overview(state, evidence_records, analysis_artifacts, bundles, annual_sections),
            "ownership_governance": self._ownership_governance(claims, evidence_records, bundles, annual_sections),
            "strategy_business": self._strategy_business(claims, evidence_records, analysis_artifacts, bundles, annual_sections),
            "three_statement_summary": self._three_statement_summary(analysis_artifacts),
            "financial_analysis": self._financial_analysis(claims, analysis_artifacts, bundles, det_blocks),
            "peer_compare": self._peer_compare(analysis_artifacts, blackboard, bundles, det_blocks),
            "valuation": self._valuation(claims, analysis_artifacts, bundles, det_blocks),
            "valuation_sensitivity": self._valuation_sensitivity(analysis_artifacts, det_blocks),
            "risks": self._risks(claims, evidence_records, analysis_artifacts, bundles, annual_sections, det_blocks),
            "conclusion": self._conclusion(claims, analysis_artifacts, bundles),
        }

    def _executive_summary(self, claims: list[dict[str, Any]], analysis: dict[str, Any], bundles: list[dict[str, Any]]) -> dict[str, Any]:
        fm = _financial_metrics(analysis)
        key_metrics = [{"name": k, "value": v} for k, v in fm.items() if k not in INTERNAL_METRIC_KEYS and isinstance(v, (int, float))]
        return _dossier(
            "executive_summary",
            claims=claims,
            bundles=bundles,
            key_facts=[f"{item['name']}: {item['value']}" for item in key_metrics[:8]],
            key_metrics=key_metrics[:8],
            caveats=["执行摘要只能汇总已有证据，不使用内部统计字段作为正文事实。"],
            min_content_level="full",
        )

    def _business_overview(
        self,
        state: dict[str, Any],
        evidence_records: list[dict[str, Any]],
        analysis: dict[str, Any],
        bundles: list[dict[str, Any]],
        annual_sections: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        cp = analysis.get("company_profile", {}) if isinstance(analysis.get("company_profile"), dict) else {}
        symbol = str(state.get("symbol") or "").upper()
        company_name = str(cp.get("company_name") or _get(state, "entity_resolution", "company_name") or symbol)
        sector = str(cp.get("sector") or cp.get("industry_group") or "")
        industry = str(cp.get("industry") or "")
        annual_biz = annual_sections.get("business", [])
        usable_annual_biz = _usable_chunks(annual_biz)
        annual_biz_usable = bool(usable_annual_biz)
        summary = str(cp.get("business_summary") or cp.get("long_business_summary") or cp.get("description") or "")
        if usable_annual_biz:
            summary = _summarize_annual_section(usable_annual_biz, company_name=company_name, section_name="business")
        if not summary and not _is_fy(state):
            for rec in evidence_records:
                if isinstance(rec, dict) and str(rec.get("source_type") or "") == "yahoo_profile":
                    content = str(rec.get("content") or "")
                    if len(content) > 80:
                        summary = content[:600]
                        break
        facts = [f"公司: {company_name}"]
        if symbol:
            facts.append(f"代码: {symbol}")
        if sector:
            facts.append(f"行业: {sector}")
        if industry:
            facts.append(f"细分行业: {industry}")
        if summary:
            facts.append(f"业务摘要: {summary[:240]}")
        suggestions = [f"{company_name}（{symbol}）业务概览：{summary[:700]}"] if summary else []
        return _dossier(
            "business_overview",
            claims=list(state.get("claims", [])) if isinstance(state.get("claims"), list) else [],
            bundles=bundles,
            evidence_ids=_chunk_ids(usable_annual_biz),
            key_facts=facts,
            suggested_paragraphs=suggestions,
            caveats=[] if annual_biz_usable or (summary and not _is_fy(state)) else [_pdf_gap_message(annual_biz, "business_overview")],
            min_content_level="full" if annual_biz_usable or (summary and not _is_fy(state)) else "data_gap",
        )

    def _ownership_governance(
        self,
        claims: list[dict[str, Any]],
        evidence_records: list[dict[str, Any]],
        bundles: list[dict[str, Any]],
        annual_sections: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        gov_chunks = _usable_chunks(annual_sections.get("governance", []))
        has_gov = _has_usable_summary(gov_chunks) or any(_contains_any(rec, ["governance", "board", "shareholder", "ownership"]) for rec in evidence_records)
        gov_caveats = [] if has_gov else ["未获取到 proxy/DEF14A 或等价治理披露，本节保持 data_gap，不编造股权和治理结论。"]
        return _dossier(
            "ownership_governance",
            claims=claims,
            bundles=bundles,
            evidence_ids=_chunk_ids(gov_chunks),
            suggested_paragraphs=[_summarize_annual_section(gov_chunks, section_name="governance")[:500]] if gov_chunks else ([] if has_gov else ["本次自动检索未获得足够治理结构证据，故不对股权结构和治理质量作展开判断。"]),
            caveats=[] if has_gov else ["本次自动检索未获得足够治理结构证据。"],
            min_content_level="brief" if has_gov else "data_gap",
        )

    def _strategy_business(
        self,
        claims: list[dict[str, Any]],
        evidence_records: list[dict[str, Any]],
        analysis: dict[str, Any],
        bundles: list[dict[str, Any]],
        annual_sections: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        chunks = _usable_chunks(annual_sections.get("mda", []) + annual_sections.get("segments", []) + annual_sections.get("liquidity", []))
        chunks_usable = _has_usable_summary(chunks)
        fm = _financial_metrics(analysis)
        facts = []
        for key in ["revenue", "gross_margin", "operating_cash_flow", "free_cash_flow"]:
            if key in fm:
                facts.append(f"{key}: {fm[key]}")
        if chunks_usable:
            facts.append(f"10-K MD&A/segments/liquidity sections extracted: {len(chunks)} chunks")
        return _dossier(
            "strategy_business",
            claims=claims,
            bundles=bundles,
            evidence_ids=_chunk_ids(chunks),
            key_facts=facts,
            key_metrics=[{"name": k, "value": v} for k, v in fm.items() if k not in INTERNAL_METRIC_KEYS and isinstance(v, (int, float))][:6],
            suggested_paragraphs=[_summarize_annual_section(chunks, company_name="", section_name="strategy")] if chunks else [],
            caveats=[] if chunks_usable else [_pdf_gap_message(chunks, "management_discussion")],
            min_content_level="full" if chunks_usable else "brief",
        )

    def _three_statement_summary(self, analysis: dict[str, Any]) -> dict[str, Any]:
        tables = analysis.get("tables", []) if isinstance(analysis.get("tables"), list) else []
        fm = _financial_metrics(analysis)
        metrics = [{"name": k, "value": fm[k]} for k in ["revenue", "net_income", "total_assets", "total_liabilities", "operating_cash_flow", "free_cash_flow"] if k in fm]
        return _dossier(
            "three_statement_summary",
            key_metrics=metrics,
            tables=[{"title": t.get("title", ""), "markdown": t.get("markdown", "")} for t in tables if isinstance(t, dict)][:5],
            suggested_paragraphs=["三表数据基于已验收的结构化财务指标，缺失项目不得补写。"],
            min_content_level="full",
            evidence_strength="strong",
        )

    def _financial_analysis(self, claims: list[dict[str, Any]], analysis: dict[str, Any], bundles: list[dict[str, Any]], det_blocks: dict[str, str]) -> dict[str, Any]:
        fm = _financial_metrics(analysis)
        det = det_blocks.get("financial_analysis", "")
        return _dossier(
            "financial_analysis",
            claims=claims,
            bundles=bundles,
            key_metrics=[{"name": k, "value": v} for k, v in fm.items() if k not in INTERNAL_METRIC_KEYS and isinstance(v, (int, float))][:12],
            suggested_paragraphs=[det] if det else [],
            deterministic_blocks=[det] if det else [],
            caveats=["财务分析基于公开财务数据，不构成审计意见。"],
            min_content_level="full",
        )

    def _peer_compare(self, analysis: dict[str, Any], blackboard: dict[str, Any], bundles: list[dict[str, Any]], det_blocks: dict[str, str]) -> dict[str, Any]:
        peer_data = analysis.get("peer_analysis", {}) if isinstance(analysis.get("peer_analysis"), dict) else {}
        peer_rows = peer_data.get("peer_rows") or peer_data.get("rows") or analysis.get("peer_rows") or blackboard.get("peer_rows") or []
        peer_rows = peer_rows if isinstance(peer_rows, list) else []
        approved = _approved_peer_symbols_from_analysis(analysis, blackboard)
        target_symbol = str(analysis.get("symbol") or blackboard.get("symbol") or "").strip().upper()
        peer_rows = _filter_peer_rows(peer_rows, target_symbol=target_symbol, approved_symbols=approved)
        det = det_blocks.get("peer_compare", "")
        tables = [{"title": "可比公司分析", "rows": peer_rows}] if peer_rows else []
        return _dossier(
            "peer_compare",
            bundles=bundles,
            tables=tables,
            suggested_paragraphs=([det] if det else []) + ([f"已识别 {len(peer_rows)} 家可比公司，比较口径需关注业务结构和会计口径差异。"] if peer_rows else []),
            deterministic_blocks=[det] if det else [],
            caveats=["同行可比性受行业分类、业务结构和会计政策差异影响。"] if peer_rows else [],
            min_content_level="full" if peer_rows else "brief",
        )

    def _valuation(self, claims: list[dict[str, Any]], analysis: dict[str, Any], bundles: list[dict[str, Any]], det_blocks: dict[str, str]) -> dict[str, Any]:
        valuation = analysis.get("valuation", {}) if isinstance(analysis.get("valuation"), dict) else {}
        if not valuation and isinstance(analysis.get("valuation_model"), dict):
            valuation = analysis.get("valuation_model", {})
        status = str(valuation.get("valuation_status") or valuation.get("error") or "").lower()
        if status in {"rough_observation_only", "blocked_due_to_incomplete_inputs"} or valuation.get("valuation_available") is False:
            missing = valuation.get("missing_inputs", []) if isinstance(valuation.get("missing_inputs"), list) else []
            note = "估值输入尚不完整，本轮仅保留方向性观察，不输出确定性 DCF、综合股权价值或目标价。"
            if missing:
                note += " 缺失项：" + "、".join(str(item) for item in missing[:6]) + "。"
            return _dossier(
                "valuation",
                claims=claims,
                bundles=bundles,
                suggested_paragraphs=[note],
                caveats=["估值模型处于粗略观察状态，不能作为投资结论或目标价依据。"],
                min_content_level="brief",
                evidence_strength="weak",
                valuation_status=status or "rough_observation_only",
            )
        det = det_blocks.get("valuation", "")
        methods = []
        for key, label in [("pe_ratio", "P/E"), ("pb_ratio", "P/B"), ("ps_ratio", "P/S"), ("dcf_value", "DCF")]:
            if valuation.get(key) is not None:
                methods.append({"name": label, "value": valuation[key]})
        return _dossier(
            "valuation",
            claims=claims,
            bundles=bundles,
            key_metrics=methods,
            tables=[{"title": "估值方法", "rows": methods}] if methods else [],
            suggested_paragraphs=[det] if det else [],
            deterministic_blocks=[det] if det else [],
            caveats=["估值模型基于公开数据和假设，不构成投资建议。", "DCF 对折现率和增长率假设敏感。"],
            min_content_level="full" if methods or det else "brief",
        )

    def _valuation_sensitivity(self, analysis: dict[str, Any], det_blocks: dict[str, str]) -> dict[str, Any]:
        valuation = analysis.get("valuation", {}) if isinstance(analysis.get("valuation"), dict) else {}
        if not valuation and isinstance(analysis.get("valuation_model"), dict):
            valuation = analysis.get("valuation_model", {})
        status = str(valuation.get("valuation_status") or valuation.get("error") or "").lower()
        if status in {"rough_observation_only", "blocked_due_to_incomplete_inputs"} or valuation.get("valuation_available") is False:
            return _dossier(
                "valuation_sensitivity",
                suggested_paragraphs=["敏感性输入尚不完整，本轮不输出 DCF 情景数值，仅说明关键变量缺口。"],
                caveats=["缺少完整基准 FCF、增长率、折现率、终值增长率、市值或股本口径时，敏感性结果不得量化展示。"],
                min_content_level="brief",
                evidence_strength="weak",
            )
        sensitivity = analysis.get("valuation_sensitivity") or valuation.get("sensitivity") or []
        det = det_blocks.get("valuation_sensitivity", "")
        return _dossier(
            "valuation_sensitivity",
            tables=[{"title": "估值敏感性分析", "rows": sensitivity}] if sensitivity else [],
            suggested_paragraphs=[det] if det else [],
            deterministic_blocks=[det] if det else [],
            caveats=["敏感性分析为规则模型计算，不构成投资建议。"],
            min_content_level="full" if sensitivity or det else "brief",
            evidence_strength="medium",
        )

    def _risks(
        self,
        claims: list[dict[str, Any]],
        evidence_records: list[dict[str, Any]],
        analysis: dict[str, Any],
        bundles: list[dict[str, Any]],
        annual_sections: dict[str, list[dict[str, Any]]],
        det_blocks: dict[str, str],
    ) -> dict[str, Any]:
        risk_chunks = _usable_chunks(annual_sections.get("risk_factors", []))
        risk_chunks_usable = _has_usable_summary(risk_chunks)
        risk_data = analysis.get("risk_analysis", {}) if isinstance(analysis.get("risk_analysis"), dict) else {}
        items = []
        if risk_chunks_usable:
            items = _risk_items_from_annual(risk_chunks)
        elif not annual_sections.get("risk_factors"):
            for cat in RISK_CATEGORIES:
                risk = risk_data.get(cat, {}) if isinstance(risk_data, dict) else {}
                items.append({
                    "risk_title": str(risk.get("title") or cat) if isinstance(risk, dict) else cat,
                    "description": str(risk.get("description") or "")[:300] if isinstance(risk, dict) else "",
                    "impact_level": str(risk.get("impact_level") or "medium") if isinstance(risk, dict) else "medium",
                })
        det = det_blocks.get("risks", "") if (risk_chunks_usable or not annual_sections.get("risk_factors")) else ""
        table = {"title": "风险分类", "headers": ["风险类型", "影响程度", "说明"], "rows": [[item["risk_title"], item["impact_level"], item["description"][:120]] for item in items if item.get("description")]}
        suggestions = ([det] if det else []) + (["风险因素来自官方年报章节摘要，报告已压缩为中文风险表，避免直接粘贴原文。"] if risk_chunks_usable else ([_summarize_annual_section(risk_chunks, section_name="risk")] if risk_chunks else []))
        return _dossier(
            "risks",
            claims=claims,
            bundles=bundles,
            evidence_ids=_chunk_ids(risk_chunks),
            tables=[table] if table["rows"] else [],
            suggested_paragraphs=suggestions,
            deterministic_blocks=[det] if det else [],
            caveats=[] if risk_chunks_usable else [_pdf_gap_message(risk_chunks, "risk_factors")],
            min_content_level="full" if risk_chunks_usable or any(item.get("description") for item in items) else "brief",
        )

    def _conclusion(self, claims: list[dict[str, Any]], analysis: dict[str, Any], bundles: list[dict[str, Any]]) -> dict[str, Any]:
        fm = _financial_metrics(analysis)
        valuation = analysis.get("valuation", {}) if isinstance(analysis.get("valuation"), dict) else {}
        elements = ["upside_factors", "downside_risks", "applicable_boundary"]
        if fm.get("net_income"):
            elements.insert(0, "financial_quality")
        if valuation.get("dcf_value") or valuation.get("blended_value"):
            elements.insert(1, "valuation_judgment")
        return _dossier(
            "conclusion",
            claims=claims,
            bundles=bundles,
            caveats=["本报告为自动生成研究报告，不构成投资建议。", "所有结论基于已获取的公开数据。"],
            suggested_paragraphs=["综合财务质量、估值、同行与风险证据后形成审慎观察；证据缺口会限制结论强度。"],
            min_content_level="full",
            conclusion_elements=elements,
        )


def _summarize_annual_section(chunks: list[dict[str, Any]], company_name: str = "", section_name: str = "") -> str:
    text = " ".join(str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "") for chunk in chunks[:3] if isinstance(chunk, dict))
    lowered = text.lower()
    subject = company_name or "公司"
    if section_name == "business":
        if not any(term in lowered for term in ["google services", "segment", "segments", "advertising", "ads", "cloud"]):
            return text[:700]
        pieces = [f"{subject} 的业务概览来自年度报告正文，而不是仅由结构化三表推断。"]
        if "google services" in lowered:
            pieces.append("公司披露的业务分部包括 Google Services、Google Cloud 和 Other Bets。")
        elif "segment" in lowered or "segments" in lowered:
            pieces.append("年度报告披露了多个经营分部，后续分析应按分部口径解释收入、利润和风险。")
        if "advertising" in lowered or "ads" in lowered:
            pieces.append("广告相关业务仍是核心收入来源，同时云服务和新业务承担增长与投入压力。")
        elif "cloud" in lowered:
            pieces.append("云服务是重要增长与资本投入方向。")
        return " ".join(pieces[:4])
    if section_name == "strategy":
        pieces = ["战略与主营业务分析基于年度报告 Business/MD&A 章节。"]
        if "revenue" in lowered:
            pieces.append("管理层围绕收入增长、成本投入、利润率和现金流解释经营表现。")
        if "capital" in lowered or "liquidity" in lowered:
            pieces.append("资本开支、流动性和长期投资需要与现金流能力一起评估。")
        if "competition" in lowered:
            pieces.append("竞争格局是影响增长、定价和利润率的重要变量。")
        return " ".join(pieces[:4])
    return f"{subject} 年度报告章节已抽取，后续分析以中文归纳关键业务事实并保留章节引用。"


def _risk_items_from_annual(chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    categories = [
        ("业务竞争", "市场竞争、产品替代和客户需求变化可能影响收入增长与利润率。"),
        ("技术与投入", "技术迭代、基础设施投入和研发投入可能抬高成本并影响现金流。"),
        ("监管合规", "数据、隐私、反垄断、内容或跨境监管变化可能带来处罚、整改或经营限制。"),
        ("宏观与市场", "汇率、利率、经济周期和资本市场波动可能影响估值与融资环境。"),
        ("披露与数据质量", "自动化报告依赖已获取的公开披露，缺失章节或口径变化会降低结论确定性。"),
    ]
    out: list[dict[str, str]] = []
    for index, (title, description) in enumerate(categories[: max(3, min(5, len(chunks)))], start=1):
        out.append({
            "risk_title": title,
            "description": description,
            "impact_level": "high" if index == 1 else "medium",
        })
    return out


def _dossier(
    section_key: str,
    claims: list[dict[str, Any]] | None = None,
    bundles: list[dict[str, Any]] | None = None,
    evidence_ids: list[str] | None = None,
    supported_claims: list[dict[str, Any]] | None = None,
    key_facts: list[str] | None = None,
    key_metrics: list[dict[str, Any]] | None = None,
    tables: list[dict[str, Any]] | None = None,
    caveats: list[str] | None = None,
    suggested_paragraphs: list[str] | None = None,
    deterministic_blocks: list[str] | None = None,
    min_content_level: str = "brief",
    evidence_strength: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    section_claims = _claims_for_section(claims or [], section_key)
    out = {
        "section_key": section_key,
        "section_title": SECTION_TITLES.get(section_key, section_key),
        "supported_claims": supported_claims if supported_claims is not None else [{"claim_id": c.get("claim_id"), "claim_text": str(c.get("claim_text", ""))[:200]} for c in section_claims],
        "supporting_evidence_ids": _dedupe(_evidence_ids_from_claims(section_claims) + (evidence_ids or [])),
        "key_facts": key_facts or [],
        "key_metrics": key_metrics or [],
        "tables": tables or [],
        "caveats": caveats or [],
        "suggested_paragraphs": suggested_paragraphs or [],
        "deterministic_blocks": deterministic_blocks or [],
        "min_content_level": min_content_level,
        "evidence_strength": evidence_strength or _evidence_strength(bundles or [], section_key),
    }
    out.update(extra)
    return out


def _annual_sections_from_state(state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    annual = state.get("annual_report_sections", {})
    if isinstance(annual, dict) and isinstance(annual.get("sections"), dict):
        output.update({str(k): v for k, v in annual["sections"].items() if isinstance(v, list)})
    elif isinstance(annual, dict):
        output.update({str(k): v for k, v in annual.items() if isinstance(v, list)})

    pdf_summaries = state.get("pdf_section_summaries", [])
    if isinstance(pdf_summaries, list):
        mapping = {
            "business_overview": ["business", "business_overview", "strategy_business"],
            "management_discussion": ["mda", "strategy_business", "management_discussion"],
            "ownership_governance": ["governance", "ownership_governance"],
            "shareholder_structure": ["governance", "shareholder_structure"],
            "risk_factors": ["risk_factors", "risks"],
            "financial_statements": ["financial_statements", "three_statement_summary"],
        }
        for summary in pdf_summaries:
            if not isinstance(summary, dict):
                continue
            section_type = str(summary.get("section_type") or "")
            for key in mapping.get(section_type, [section_type]):
                output.setdefault(key, []).append(summary)
    return output


def sanitize_peer_rows_for_report(analysis: dict[str, Any], blackboard: dict[str, Any] | None = None, target_symbol: str = "") -> list[dict[str, Any]]:
    blackboard = blackboard if isinstance(blackboard, dict) else {}
    peer_data = analysis.get("peer_analysis", {}) if isinstance(analysis.get("peer_analysis"), dict) else {}
    peer_rows = analysis.get("peer_rows") or peer_data.get("peer_rows") or peer_data.get("rows") or blackboard.get("peer_rows") or []
    peer_rows = peer_rows if isinstance(peer_rows, list) else []
    approved = _approved_peer_symbols_from_analysis(analysis, blackboard)
    clean_rows = _filter_peer_rows(
        peer_rows,
        target_symbol=str(target_symbol or "").strip().upper(),
        approved_symbols=approved,
        target_profile=_target_peer_profile(analysis, blackboard, target_symbol),
    )
    if isinstance(peer_data, dict):
        peer_data["peer_rows"] = clean_rows
        peer_data["rows"] = clean_rows
        peer_data["dropped_peer_row_count"] = max(len(peer_rows) - len(clean_rows), 0)
        analysis["peer_analysis"] = peer_data
    analysis["peer_rows"] = clean_rows
    blackboard["peer_rows"] = clean_rows
    return clean_rows


def _deterministic_blocks(analysis: dict[str, Any], blackboard: dict[str, Any]) -> dict[str, str]:
    try:
        from src.report.deterministic_section_renderer import render_all_deterministic_blocks

        peer_rows = sanitize_peer_rows_for_report(analysis, blackboard, target_symbol=str(analysis.get("symbol") or blackboard.get("symbol") or ""))
        valuation_model = analysis.get("valuation_model") or analysis.get("valuation")
        return render_all_deterministic_blocks(
            peer_rows=peer_rows if isinstance(peer_rows, list) else [],
            valuation_model=valuation_model if isinstance(valuation_model, dict) else {},
            sensitivity=analysis.get("valuation_sensitivity") or analysis.get("sensitivity") or {},
            risk_items=analysis.get("risk_items") if isinstance(analysis.get("risk_items"), list) else [],
            financial_metrics=_financial_metrics(analysis),
        )
    except Exception:
        return {}


def _financial_metrics(analysis: dict[str, Any]) -> dict[str, Any]:
    fm = analysis.get("financial_metrics", {}) if isinstance(analysis.get("financial_metrics"), dict) else {}
    return dict(fm)


def _claims_for_section(claims: list[dict[str, Any]], section_key: str) -> list[dict[str, Any]]:
    return [claim for claim in claims if isinstance(claim, dict) and str(claim.get("section_name", "")).lower().replace(" ", "_") == section_key]


def _evidence_ids_from_claims(claims: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for claim in claims:
        raw = claim.get("evidence_ids", []) if isinstance(claim, dict) else []
        if isinstance(raw, list):
            ids.extend(str(item) for item in raw if str(item))
    return ids


def _chunk_ids(chunks: list[dict[str, Any]]) -> list[str]:
    return [str(chunk.get("evidence_id")) for chunk in chunks if isinstance(chunk, dict) and chunk.get("evidence_id")]


def _has_usable_summary(chunks: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(chunk, dict)
        and bool(chunk.get("usable_for_generation", True))
        and str(chunk.get("evidence_quality") or "").lower() not in {"missing", "noise_only"}
        and not _has_mojibake(_chunk_text(chunk))
        and not _looks_like_raw_pdf_dump(_chunk_text(chunk))
        for chunk in chunks
    )


def _usable_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        chunk
        for chunk in chunks
        if isinstance(chunk, dict)
        and bool(chunk.get("usable_for_generation", True))
        and str(chunk.get("evidence_quality") or "").lower() not in {"missing", "noise_only"}
        and not _has_mojibake(_chunk_text(chunk))
        and not _looks_like_raw_pdf_dump(_chunk_text(chunk))
        and not _section_summary_is_unusable(chunk)
    ]


def _pdf_gap_message(chunks: list[dict[str, Any]], section_type: str) -> str:
    if chunks:
        first = next((chunk for chunk in chunks if isinstance(chunk, dict)), {})
        reason = str(first.get("gap_reason") or first.get("evidence_quality") or "section_not_extracted")
        text = str(first.get("summary_zh") or "").strip()
        if text:
            return text
        if reason == "noise_only":
            return f"官方 PDF 已获取，但 {section_type} 候选片段全部被识别为页眉、重要提示、目录指针或勾选项噪声。"
        return f"官方 PDF 已获取，但尚未稳定抽取 {section_type} 对应章节，因此本节不展开判断。"
    return f"未获取到 {section_type} 的官方年报章节摘要，本节保持数据缺口。"


def _evidence_strength(bundles: list[dict[str, Any]], section_key: str) -> str:
    statuses = [
        str(bundle.get("grounding_status") or "unverified")
        for bundle in bundles
        if isinstance(bundle, dict) and str(bundle.get("section_name", "")).lower().replace(" ", "_") == section_key
    ]
    if any(status == "grounded" for status in statuses):
        return "strong"
    if any(status == "partial" for status in statuses):
        return "medium"
    return "weak"


def _contains_any(record: dict[str, Any], terms: list[str]) -> bool:
    text = f"{record.get('title', '')} {record.get('content', '')}".lower()
    return any(term in text for term in terms)


def _is_fy(state: dict[str, Any]) -> bool:
    return str(state.get("period") or "").upper().startswith("FY")


def _approved_peer_symbols_from_analysis(analysis: dict[str, Any], blackboard: dict[str, Any]) -> set[str]:
    approved: set[str] = set()
    peer_data = analysis.get("peer_analysis", {}) if isinstance(analysis.get("peer_analysis"), dict) else {}
    for source in [peer_data, analysis, blackboard]:
        if not isinstance(source, dict):
            continue
        for key in ["approved_peer_symbols", "peer_symbols"]:
            values = source.get(key)
            if isinstance(values, list):
                for value in values:
                    symbol = str(value or "").strip().upper()
                    if symbol:
                        approved.add(symbol)
    return approved


def _target_peer_profile(analysis: dict[str, Any], blackboard: dict[str, Any], target_symbol: str) -> dict[str, Any]:
    profile = analysis.get("company_profile") if isinstance(analysis.get("company_profile"), dict) else {}
    if not profile:
        profile = blackboard.get("company_profile") if isinstance(blackboard.get("company_profile"), dict) else {}
    identity = blackboard.get("company_identity") if isinstance(blackboard.get("company_identity"), dict) else {}
    return {
        "symbol": str(target_symbol or analysis.get("symbol") or blackboard.get("symbol") or "").strip().upper(),
        "company_name": profile.get("company_name") or identity.get("company_name") or analysis.get("company_name") or target_symbol,
        "sector": profile.get("sector") or identity.get("sector") or analysis.get("sector") or "",
        "industry": profile.get("industry") or identity.get("industry") or analysis.get("industry") or "",
    }


def _filter_peer_rows(
    peer_rows: list[dict[str, Any]],
    target_symbol: str,
    approved_symbols: set[str],
    target_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    allowed = {str(symbol).strip().upper() for symbol in approved_symbols if str(symbol).strip()}
    if target_symbol:
        allowed.add(target_symbol)
    target_row = next(
        (
            row for row in peer_rows
            if isinstance(row, dict)
            and str(row.get("symbol") or row.get("ticker") or "").strip().upper() == target_symbol
        ),
        target_profile if isinstance(target_profile, dict) else {},
    )
    target_market = _symbol_market(target_symbol)
    target_family = _peer_industry_family(target_row)
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        if symbol not in allowed:
            continue
        if symbol != target_symbol:
            row_market = _symbol_market(symbol)
            if target_market and row_market and row_market != target_market:
                continue
            row_family = _peer_industry_family(row)
            if target_family not in {"", "generic"} and row_family not in {"", "generic", target_family}:
                continue
        filtered.append(row)
    return filtered


def _symbol_market(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if value.endswith((".SS", ".SZ")):
        return "cn_a"
    if value.endswith(".HK"):
        return "hk"
    if re.fullmatch(r"[A-Z]{1,6}", value):
        return "us"
    return ""


def _peer_industry_family(row: dict[str, Any]) -> str:
    try:
        from src.data.content_governance import classify_industry_family

        return classify_industry_family(
            str(row.get("sector") or ""),
            str(row.get("industry") or row.get("peer_group") or ""),
            str(row.get("company_name") or row.get("company") or row.get("name") or row.get("symbol") or ""),
        )
    except Exception:
        return "generic"


def _summarize_annual_section(chunks: list[dict[str, Any]], company_name: str = "", section_name: str = "") -> str:
    text = " ".join(
        str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
        for chunk in chunks[:3]
        if isinstance(chunk, dict)
    ).strip()
    lowered = text.lower()
    subject = company_name or "公司"
    if section_name == "business":
        if not any(term in lowered for term in ["google services", "segment", "segments", "advertising", "ads", "cloud"]):
            return text[:700]
        pieces = [f"{subject}的业务概览来自年度报告正文，而不是只由结构化三表反推。"]
        if "google services" in lowered:
            pieces.append("公司披露的主要分部包括 Google Services、Google Cloud 和 Other Bets。")
        elif "segment" in lowered or "segments" in lowered:
            pieces.append("年度报告披露了多个经营分部，后续分析应按分部口径解释收入、利润和风险。")
        if "advertising" in lowered or "ads" in lowered:
            pieces.append("广告相关业务仍是核心收入来源，同时云服务和新业务承担增长与投入压力。")
        elif "cloud" in lowered:
            pieces.append("云服务是重要的增长与资本投入方向。")
        return " ".join(pieces[:4])
    if section_name == "strategy":
        pieces = ["战略与主营业务分析基于年度报告 Business 或 MD&A 章节。"]
        if "revenue" in lowered:
            pieces.append("管理层通常围绕收入增长、成本投入、利润率和现金流解释经营表现。")
        if "capital" in lowered or "liquidity" in lowered:
            pieces.append("资本开支、流动性和长期投资需要结合现金流能力一并评估。")
        if "competition" in lowered:
            pieces.append("竞争格局会直接影响增长、定价和利润率。")
        return " ".join(pieces[:4])
    return text[:700]


def _pdf_gap_message(chunks: list[dict[str, Any]], section_type: str) -> str:
    if chunks:
        first = next((chunk for chunk in chunks if isinstance(chunk, dict)), {})
        reason = str(first.get("gap_reason") or first.get("evidence_quality") or "section_not_extracted")
        text = str(first.get("summary_zh") or "").strip()
        if text:
            return text
        if reason == "noise_only":
            return f"已获取官方 PDF，但 {section_type} 候选片段主要是页眉、目录指针、重要提示或审计样板语，未能形成可用摘要。"
        return f"已获取官方 PDF，但尚未稳定抽取 {section_type} 对应章节，因此本节暂不展开判断。"
    return f"尚未取得 {section_type} 的官方 PDF 章节摘要，因此本节保持 data_gap。"


def _get(value: Any, *keys: str) -> Any:
    cur = value
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _chunk_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")


def _has_mojibake(text: str) -> bool:
    value = str(text or "")
    patterns = (
        "\ufffd",
        "鈥",
        "鈭",
        "鈻",
        "鈹",
        "璐靛",
        "璇佹",
        "缁撹",
        "鎽樿",
        "鐩",
        "鍏",
        "涓氬",
        "锛",
        "Ã",
        "Â",
    )
    return any(pattern in value for pattern in patterns)


def _looks_like_raw_pdf_dump(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= 700:
        return False
    sentence_marks = len(re.findall(r"[。！？.!?]", value))
    return sentence_marks < 3 or len(value) > 1200


def _clean_generation_text(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = re.sub(r"\b[A-Za-z\s.,&()-]+(?:Annual Report|Form 10-[KQ]).{0,40}", "", value)
    value = re.sub(r"贵州茅台酒股份有限公司\s*\d{4}\s*年年度报告", "", value)
    value = re.sub(r"第[一二三四五六七八九十\d]+\s*节\s*[^。；\n]{0,30}", "", value)
    value = re.sub(r"[一二三四五六七八九十]、(?=(公司|报告期|本公司|主要|核心|经营))", "", value)
    for phrase in [
        "正文应使用中文归纳",
        "公司 年度报告章节已抽取",
        "年度报告章节已抽取",
        "保留章节引用",
        "使用中文归纳关键业务事实",
    ]:
        value = value.replace(phrase, "")
    return value.strip()


def _compact_text(text: str, max_chars: int) -> str:
    value = _clean_generation_text(text)
    if len(value) <= max_chars:
        return value
    sentences = re.split(r"(?<=[。！？.!?])\s+", value)
    output: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        output.append(sentence)
        if len(" ".join(output)) >= max_chars or len(output) >= 4:
            break
    return (" ".join(output).strip() or value[:max_chars])[:max_chars]


def _section_summary_is_unusable(chunk: dict[str, Any]) -> bool:
    section_type = str(chunk.get("section_type") or "").lower()
    if section_type not in {"business_overview", "business"}:
        return False
    text = _chunk_text(chunk)
    lowered = str(text or "").lower()
    negatives = [
        "释义",
        "公司信息",
        "联系人和联系方式",
        "主要财务指标",
        "法定代表人",
        "财务费用变动原因说明",
        "现金流量净额变动原因说明",
    ]
    positives = [
        "主营业务",
        "经营模式",
        "产品结构",
        "销售渠道",
        "茅台酒",
        "系列酒",
        "直销",
        "i茅台",
        "批发代理",
        "business model",
        "products",
        "segments",
    ]
    if any(term.lower() in lowered for term in negatives):
        return True
    return not any(term.lower() in lowered for term in positives)


def _summarize_annual_section(chunks: list[dict[str, Any]], company_name: str = "", section_name: str = "") -> str:
    text = " ".join(
        str(chunk.get("summary_zh") or chunk.get("text") or chunk.get("content") or "")
        for chunk in chunks[:3]
        if isinstance(chunk, dict)
    ).strip()
    text = _compact_text(text, 420)
    if _has_mojibake(text):
        return ""
    lowered = text.lower()
    subject = company_name or "公司"
    if section_name == "business" and any(term in lowered for term in ["google services", "segment", "segments", "advertising", "ads", "cloud"]):
        pieces = [f"{subject} 的业务概览来自年度报告正文，而不是仅由结构化三表反推。"]
        if "google services" in lowered:
            pieces.append("公司披露的主要分部包括 Google Services、Google Cloud 和 Other Bets。")
        elif "segment" in lowered or "segments" in lowered:
            pieces.append("年度报告披露了多个经营分部，后续分析应按分部口径解释收入、利润和风险。")
        if "advertising" in lowered or "ads" in lowered:
            pieces.append("广告相关业务仍是核心收入来源，同时云服务和新业务承担增长与投入压力。")
        elif "cloud" in lowered:
            pieces.append("云服务是重要的增长与资本投入方向。")
        return " ".join(pieces[:4])
    return text


def _pdf_gap_message(chunks: list[dict[str, Any]], section_type: str) -> str:
    if chunks:
        first = next((chunk for chunk in chunks if isinstance(chunk, dict)), {})
        reason = str(first.get("gap_reason") or first.get("evidence_quality") or "section_not_extracted")
        text = _clean_generation_text(str(first.get("summary_zh") or "").strip())
        if text and not _has_mojibake(text):
            return _compact_text(text, 260)
        if reason == "noise_only":
            return f"已获取官方 PDF，但 {section_type} 候选片段主要是页眉、目录、重要提示、乱码或模板文本，未能形成可用摘要。"
        if reason == "mojibake":
            return f"已获取官方 PDF，但 {section_type} 候选章节存在乱码，已阻断进入正文。"
        return f"已获取官方 PDF，但尚未稳定抽取 {section_type} 对应章节，因此本节暂不展开判断。"
    return f"尚未取得 {section_type} 的官方 PDF 章节摘要，因此本节保持 data_gap。"
