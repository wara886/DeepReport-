"""Build per-section writing dossiers for FinalAnswerAgent."""

from __future__ import annotations

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
        summary = str(cp.get("business_summary") or cp.get("long_business_summary") or cp.get("description") or "")
        if annual_biz:
            annual_text = " ".join(str(chunk.get("text") or "")[:500] for chunk in annual_biz[:2])
            if len(annual_text) > 80:
                summary = annual_text[:900]
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
            evidence_ids=_chunk_ids(annual_biz),
            key_facts=facts,
            suggested_paragraphs=suggestions,
            caveats=[] if summary else ["未获取到 10-K Item 1 或公司画像证据，本节应保持数据缺口。"],
            min_content_level="full" if summary else "data_gap",
        )

    def _ownership_governance(
        self,
        claims: list[dict[str, Any]],
        evidence_records: list[dict[str, Any]],
        bundles: list[dict[str, Any]],
        annual_sections: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        gov_chunks = annual_sections.get("governance", [])
        has_gov = bool(gov_chunks) or any(_contains_any(rec, ["governance", "board", "shareholder", "ownership"]) for rec in evidence_records)
        return _dossier(
            "ownership_governance",
            claims=claims,
            bundles=bundles,
            evidence_ids=_chunk_ids(gov_chunks),
            suggested_paragraphs=[str(gov_chunks[0].get("text") or "")[:500]] if gov_chunks else ([] if has_gov else ["本次自动检索未获得足够治理结构证据，故不对股权结构和治理质量作展开判断。"]),
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
        chunks = annual_sections.get("mda", []) + annual_sections.get("segments", []) + annual_sections.get("liquidity", [])
        fm = _financial_metrics(analysis)
        facts = []
        for key in ["revenue", "gross_margin", "operating_cash_flow", "free_cash_flow"]:
            if key in fm:
                facts.append(f"{key}: {fm[key]}")
        if chunks:
            facts.append(f"10-K MD&A/segments/liquidity sections extracted: {len(chunks)} chunks")
        return _dossier(
            "strategy_business",
            claims=claims,
            bundles=bundles,
            evidence_ids=_chunk_ids(chunks),
            key_facts=facts,
            key_metrics=[{"name": k, "value": v} for k, v in fm.items() if k not in INTERNAL_METRIC_KEYS and isinstance(v, (int, float))][:6],
            suggested_paragraphs=[str(chunks[0].get("text") or "")[:650]] if chunks else [],
            caveats=[] if chunks else ["未获取到 10-K MD&A/segments/liquidity 证据，本节只能基于财务表现做有限观察。"],
            min_content_level="full" if chunks else "brief",
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
        risk_chunks = annual_sections.get("risk_factors", [])
        risk_data = analysis.get("risk_analysis", {}) if isinstance(analysis.get("risk_analysis"), dict) else {}
        items = []
        if risk_chunks:
            for index, chunk in enumerate(risk_chunks[:5], start=1):
                text = str(chunk.get("text") or "")
                if text:
                    items.append({"risk_title": f"10-K Risk Factor {index}", "description": text[:300], "impact_level": "high" if index == 1 else "medium"})
        else:
            for cat in RISK_CATEGORIES:
                risk = risk_data.get(cat, {}) if isinstance(risk_data, dict) else {}
                items.append({
                    "risk_title": str(risk.get("title") or cat) if isinstance(risk, dict) else cat,
                    "description": str(risk.get("description") or "")[:300] if isinstance(risk, dict) else "",
                    "impact_level": str(risk.get("impact_level") or "medium") if isinstance(risk, dict) else "medium",
                })
        det = det_blocks.get("risks", "")
        table = {"title": "风险分类", "headers": ["风险类型", "影响程度", "说明"], "rows": [[item["risk_title"], item["impact_level"], item["description"][:120]] for item in items if item.get("description")]}
        suggestions = ([det] if det else []) + ([str(risk_chunks[0].get("text") or "")[:650]] if risk_chunks else [])
        return _dossier(
            "risks",
            claims=claims,
            bundles=bundles,
            evidence_ids=_chunk_ids(risk_chunks),
            tables=[table] if table["rows"] else [],
            suggested_paragraphs=suggestions,
            deterministic_blocks=[det] if det else [],
            caveats=[] if risk_chunks else ["风险分析缺少 10-K Item 1A 正文证据时不得伪装为完整年报风险章节。"],
            min_content_level="full" if risk_chunks or any(item.get("description") for item in items) else "brief",
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
    annual = state.get("annual_report_sections", {})
    if isinstance(annual, dict) and isinstance(annual.get("sections"), dict):
        return {str(k): v for k, v in annual["sections"].items() if isinstance(v, list)}
    if isinstance(annual, dict):
        return {str(k): v for k, v in annual.items() if isinstance(v, list)}
    return {}


def _deterministic_blocks(analysis: dict[str, Any], blackboard: dict[str, Any]) -> dict[str, str]:
    try:
        from src.report.deterministic_section_renderer import render_all_deterministic_blocks

        peer_data = analysis.get("peer_analysis", {}) if isinstance(analysis.get("peer_analysis"), dict) else {}
        peer_rows = analysis.get("peer_rows") or peer_data.get("peer_rows") or peer_data.get("rows") or blackboard.get("peer_rows")
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
