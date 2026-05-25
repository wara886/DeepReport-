"""Shared research blackboard for company report agents.

The blackboard is a lightweight collaboration artifact: agents publish what
they know, a pre-write critic records objections, and downstream gates can
inspect the same state. It is intentionally deterministic and evidence based.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Dict, Iterable, List

from src.data.company_universe import resolve_company_identity


OFFICIAL_SOURCE_TYPES = {
    "sec_companyfacts",
    "sec_filing",
    "cninfo_announcement",
    "exchange_announcement",
    "eastmoney_financials",
    "company_official",
    "hkex_announcement",
    "pdf_section",
}

ROLE_OUTPUT_KEYS = [
    "identity_profile",
    "three_statement_analysis",
    "peer_analysis",
    "valuation_analysis",
    "risk_analysis",
]

ROLE_OUTPUT_OWNERS = {
    "identity_profile": "IdentityAgent",
    "three_statement_analysis": "StatementAgent",
    "peer_analysis": "PeerAgent",
    "valuation_analysis": "ValuationAgent",
    "risk_analysis": "RiskAgent",
}

AGENT_ROLE_OUTPUTS = {agent: role for role, agent in ROLE_OUTPUT_OWNERS.items()}


def initialize_research_blackboard(
    symbol: str,
    period: str,
    entity_resolution: Dict[str, Any] | None = None,
    search_engines: Any = None,
    raw_data_root: str = "data/raw/real_data",
) -> Dict[str, Any]:
    """Create the run-level collaboration state."""

    identity = resolve_company_identity(symbol, raw_data_root=raw_data_root, default=symbol).to_dict()
    if entity_resolution:
        identity["entity_resolution"] = dict(entity_resolution)
    engines = _engine_list(search_engines) or list(identity.get("data_source_plan", {}).get("engines") or [])
    return {
        "schema_version": "research_blackboard.v1",
        "symbol": str(symbol or "").upper(),
        "target_period": str(period or "").upper(),
        "company_identity": identity,
        "market_route": {
            "market": identity.get("market", "unknown"),
            "exchange": identity.get("exchange", ""),
            "data_source_plan": dict(identity.get("data_source_plan") or {}),
            "primary_sources": list((identity.get("data_source_plan") or {}).get("primary_sources") or []),
            "planned_engines": engines,
            "attempted_engines": [],
            "missing_primary_sources": [],
            "route_coverage": 0.0,
        },
        "industry_profile": {
            "industry": identity.get("industry", ""),
            "sector": identity.get("sector", ""),
            "business_summary": identity.get("business_summary", ""),
            "confidence": 0.0,
            "source_priority": "identity",
            "evidence_ids": [],
        },
        "period_state": {
            "target_period": str(period or "").upper(),
            "latest_available_disclosure_period": "",
            "financial_data_basis": "",
            "market_data_as_of": "",
            "has_data_delay": False,
            "notes": [],
        },
        "coverage": {
            "evidence_count": 0,
            "official_evidence_count": 0,
            "source_types": [],
            "three_statement": {"income": False, "balance": False, "cash_flow": False},
            "peer_compare": {"available": False, "reason": ""},
            "valuation": {"available": False, "method": "", "missing_inputs": []},
            "risk": {"available": False, "evidence_ids": []},
        },
        "role_outputs": {key: _empty_role_output(key) for key in ROLE_OUTPUT_KEYS},
        "agent_writes": [],
        "critic": {"pre_write_passed": False, "objections": [], "recommendations": []},
    }


def update_blackboard_for_task(
    blackboard: Dict[str, Any],
    task_type: str,
    state: Dict[str, Any],
    result_output: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Refresh derived blackboard fields after an agent handoff."""

    bb = dict(blackboard or {})
    if not bb:
        bb = initialize_research_blackboard(
            symbol=str(state.get("symbol", "")),
            period=str(state.get("period", "")),
            entity_resolution=state.get("entity_resolution") if isinstance(state.get("entity_resolution"), dict) else {},
            search_engines=state.get("search_engines"),
        )

    evidence = _as_list(state.get("evidence_records"))
    claims = _as_list(state.get("claims"))
    artifacts = state.get("analysis_artifacts", {}) if isinstance(state.get("analysis_artifacts"), dict) else {}
    if isinstance(result_output, dict) and isinstance(result_output.get("role_outputs"), dict):
        artifacts = dict(artifacts)
        role_outputs = dict(artifacts.get("role_outputs", {})) if isinstance(artifacts.get("role_outputs"), dict) else {}
        for key, value in result_output["role_outputs"].items():
            if key in ROLE_OUTPUT_KEYS and isinstance(value, dict):
                role_outputs[key] = value
        artifacts["role_outputs"] = role_outputs
    search_meta = state.get("search_meta", {}) if isinstance(state.get("search_meta"), dict) else {}
    if not search_meta and isinstance(result_output, dict) and isinstance(result_output.get("search_meta"), dict):
        search_meta = result_output.get("search_meta", {})

    bb["market_route"] = _route_state(bb.get("market_route", {}), search_meta)
    bb["coverage"] = _coverage_state(evidence, claims, artifacts)
    bb["period_state"] = _period_state(bb.get("target_period", ""), evidence, artifacts)
    bb["industry_profile"] = _industry_profile(bb.get("company_identity", {}), evidence, claims)
    bb["role_outputs"] = _role_outputs_state(bb.get("role_outputs", {}), artifacts)
    bb.setdefault("agent_writes", []).append(_agent_write(task_type, state, result_output or {}))
    return bb


def build_pre_write_critic(blackboard: Dict[str, Any], state: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Run deterministic pre-write objections before FinalAnswer."""

    bb = blackboard or {}
    objections: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    identity = bb.get("company_identity", {}) if isinstance(bb.get("company_identity"), dict) else {}
    coverage = bb.get("coverage", {}) if isinstance(bb.get("coverage"), dict) else {}
    period_state = bb.get("period_state", {}) if isinstance(bb.get("period_state"), dict) else {}
    route = bb.get("market_route", {}) if isinstance(bb.get("market_route"), dict) else {}
    industry = bb.get("industry_profile", {}) if isinstance(bb.get("industry_profile"), dict) else {}
    role_outputs = bb.get("role_outputs", {}) if isinstance(bb.get("role_outputs"), dict) else {}

    if not identity.get("is_listed"):
        objections.append(_objection("identity", "blocker", "上市公司身份未确认，不能生成正式公司/个股研报。"))
    if float(industry.get("confidence") or 0.0) < 0.55:
        objections.append(_objection("industry_profile", "warning", "行业画像置信度偏低，FinalAnswer 只能引用已验证主营业务，不得按关键词扩展行业。"))
    if route.get("missing_primary_sources"):
        recommendations.append("正文说明未覆盖的主数据源及其对三表、估值或同行判断的影响。")
    statements = coverage.get("three_statement", {}) if isinstance(coverage.get("three_statement"), dict) else {}
    missing = [name for name, ok in statements.items() if not ok]
    if missing:
        objections.append(_objection("three_statement", "warning", f"三表覆盖不完整：{', '.join(missing)}。"))
        recommendations.append("三表缺项必须写明已尝试来源、缺失项目和对投资判断的影响。")
    if period_state.get("has_data_delay"):
        objections.append(_objection("period_consistency", "blocker", "目标报告期与最新可得披露期不一致，正文必须显式披露。"))
    if period_state.get("market_data_as_of"):
        recommendations.append("行情数据只作为截至日市场输入，不得写成目标报告期财报事实。")
    if not coverage.get("valuation", {}).get("available"):
        recommendations.append("估值不可计算时必须列出缺失输入和判断影响，不能只写暂无结论。")

    identity_role = _role_output_item(role_outputs, "identity_profile")
    if identity_role.get("status") in {"missing", "not_started"}:
        objections.append(_objection("identity_profile", "warning", "Identity role output is missing; FinalAnswer must not infer identity from search keywords."))
    statement_role = _role_output_item(role_outputs, "three_statement_analysis")
    if statement_role.get("status") != "complete":
        recommendations.append("Three-statement role output is incomplete; disclose missing inputs and avoid full coverage claims.")
    peer_role = _role_output_item(role_outputs, "peer_analysis")
    if peer_role.get("status") != "complete":
        recommendations.append("Peer role output is incomplete; frame peer comparison with data-gap limits.")
    valuation_role = _role_output_item(role_outputs, "valuation_analysis")
    if valuation_role.get("status") != "complete":
        recommendations.append("Valuation role output is incomplete; avoid target-price conclusions and list missing inputs.")
    risk_role = _role_output_item(role_outputs, "risk_analysis")
    if risk_role.get("status") not in {"complete", "partial"} or float(risk_role.get("confidence") or 0.0) < 0.4:
        objections.append(_objection("risk_analysis", "warning", "Risk role output has low confidence; disclose risk-evidence limitations."))

    critic = {
        "schema_version": "pre_write_critic.v1",
        "passed": not any(item["severity"] == "blocker" for item in objections),
        "objections": objections,
        "recommendations": _dedupe(recommendations),
    }
    return critic


def apply_pre_write_critic(blackboard: Dict[str, Any], critic: Dict[str, Any]) -> Dict[str, Any]:
    bb = dict(blackboard or {})
    bb["critic"] = {
        "pre_write_passed": bool(critic.get("passed")),
        "objections": _as_list(critic.get("objections")),
        "recommendations": _as_list(critic.get("recommendations")),
    }
    bb.setdefault("agent_writes", []).append(
        {
            "agent": "CriticAgent",
            "task_type": "pre_write_critic",
            "writes": ["critic"],
            "objection_count": len(_as_list(critic.get("objections"))),
        }
    )
    return bb


def role_key_for_agent(agent_name: str) -> str:
    return AGENT_ROLE_OUTPUTS.get(str(agent_name or ""), "")


def validate_role_output_write(agent_name: str, role_key: str) -> None:
    expected = ROLE_OUTPUT_OWNERS.get(str(role_key or ""))
    if not expected:
        raise KeyError(f"unknown role output field: {role_key}")
    if expected != str(agent_name or ""):
        raise PermissionError(f"{agent_name} cannot write {role_key}; owner is {expected}")


def quality_generalization_checks(artifacts: Dict[str, Any]) -> Dict[str, Any]:
    """Expose blackboard-backed checks for objective quality reports."""

    bb = artifacts.get("research_blackboard", {}) if isinstance(artifacts.get("research_blackboard"), dict) else {}
    if not bb:
        return {
            "identity_consistency": {"passed": True, "available": False, "reason": "research_blackboard_missing"},
            "period_consistency": {"passed": True, "available": False, "reason": "research_blackboard_missing"},
            "market_route_coverage": {"passed": True, "available": False, "reason": "research_blackboard_missing"},
            "industry_profile_confidence": {"passed": True, "available": False, "reason": "research_blackboard_missing"},
            "pre_write_critic_passed": {"passed": True, "available": False, "reason": "research_blackboard_missing"},
        }
    text = str(artifacts.get("report_md") or "") + "\n" + str(artifacts.get("report_html") or "")
    identity = bb.get("company_identity", {}) if isinstance(bb.get("company_identity"), dict) else {}
    route = bb.get("market_route", {}) if isinstance(bb.get("market_route"), dict) else {}
    industry = bb.get("industry_profile", {}) if isinstance(bb.get("industry_profile"), dict) else {}
    period_state = bb.get("period_state", {}) if isinstance(bb.get("period_state"), dict) else {}
    critic = bb.get("critic", {}) if isinstance(bb.get("critic"), dict) else {}
    role_outputs = bb.get("role_outputs", {}) if isinstance(bb.get("role_outputs"), dict) else {}
    agent_writes = bb.get("agent_writes", []) if isinstance(bb.get("agent_writes"), list) else []
    critic_available = any(
        isinstance(item, dict)
        and (item.get("agent") == "CriticAgent" or item.get("task_type") == "pre_write_critic")
        for item in agent_writes
    )
    industry_terms = [str(industry.get("industry") or ""), str(industry.get("sector") or ""), str(industry.get("business_summary") or "")]
    identity_ok = bool(identity.get("is_listed")) and bool(identity.get("canonical_symbol") or identity.get("symbol"))
    industry_ok = float(industry.get("confidence") or 0.0) >= 0.55
    period_ok = _period_disclosed(text) if period_state.get("has_data_delay") or period_state.get("market_data_as_of") else True
    route_ok = float(route.get("route_coverage") or 0.0) > 0.0 or bool(route.get("attempted_engines"))
    return {
        "identity_consistency": {
            "passed": identity_ok,
            "market": identity.get("market", ""),
            "exchange": identity.get("exchange", ""),
            "canonical_symbol": identity.get("canonical_symbol") or identity.get("symbol", ""),
        },
        "period_consistency": {
            "passed": period_ok,
            "target_period": period_state.get("target_period", ""),
            "latest_available_disclosure_period": period_state.get("latest_available_disclosure_period", ""),
            "market_data_as_of": period_state.get("market_data_as_of", ""),
        },
        "market_route_coverage": {
            "passed": route_ok,
            "route_coverage": route.get("route_coverage", 0.0),
            "attempted_engines": route.get("attempted_engines", []),
            "missing_primary_sources": route.get("missing_primary_sources", []),
        },
        "industry_profile_confidence": {
            "passed": industry_ok,
            "confidence": round(float(industry.get("confidence") or 0.0), 3),
            "industry": industry.get("industry", ""),
            "sector": industry.get("sector", ""),
            "business_summary": next((item for item in industry_terms if item), ""),
        },
        "pre_write_critic_passed": {
            "passed": bool(critic.get("pre_write_passed")) if critic_available else True,
            "available": critic_available,
            "objection_count": len(_as_list(critic.get("objections"))),
            "reason": "" if critic_available else "pre_write_critic_not_executed",
        },
        "analysis_role_outputs": {
            "passed": _role_outputs_are_reviewable(role_outputs),
            "statuses": {
                key: _role_output_item(role_outputs, key).get("status", "")
                for key in ROLE_OUTPUT_KEYS
            },
        },
    }


def _role_outputs_state(existing: Any, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(existing) if isinstance(existing, dict) else {}
    raw = artifacts.get("role_outputs", {}) if isinstance(artifacts.get("role_outputs"), dict) else {}
    for key in ROLE_OUTPUT_KEYS:
        value = raw.get(key)
        if value is None:
            value = artifacts.get(key)
        if isinstance(value, dict):
            output[key] = _summarize_role_output(value)
        else:
            output.setdefault(key, _empty_role_output(key))
    return output


def _summarize_role_output(value: Dict[str, Any]) -> Dict[str, Any]:
    status = str(value.get("status") or "")
    return {
        "status": status,
        "confidence": round(float(value.get("confidence") or 0.0), 3),
        "source": str(value.get("source") or ""),
        "evidence_ids": _as_list(value.get("evidence_ids"))[:12],
        "findings": [str(item) for item in _as_list(value.get("findings"))[:8]],
        "missing_inputs": [str(item) for item in _as_list(value.get("missing_inputs"))[:8]],
        "impact_on_report": str(value.get("impact_on_report") or ""),
        "owner_agent": str(value.get("owner_agent") or ""),
        "verified": bool(value.get("verified", status == "complete")),
    }


def _empty_role_output(key: str) -> Dict[str, Any]:
    return {
        "status": "not_started",
        "confidence": 0.0,
        "source": "",
        "evidence_ids": [],
        "findings": [],
        "missing_inputs": [key],
        "impact_on_report": "",
        "owner_agent": ROLE_OUTPUT_OWNERS.get(key, ""),
        "verified": False,
    }


def _role_output_item(role_outputs: Any, key: str) -> Dict[str, Any]:
    if not isinstance(role_outputs, dict):
        return _empty_role_output(key)
    value = role_outputs.get(key)
    return value if isinstance(value, dict) else _empty_role_output(key)


def _role_outputs_are_reviewable(role_outputs: Any) -> bool:
    if not isinstance(role_outputs, dict):
        return False
    for key in ROLE_OUTPUT_KEYS:
        item = _role_output_item(role_outputs, key)
        status = str(item.get("status") or "")
        if status in {"", "not_started"}:
            return False
        if status in {"missing", "partial"} and not (item.get("missing_inputs") and item.get("impact_on_report")):
            return False
    return True


def _route_state(route: Dict[str, Any], search_meta: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(route or {})
    planned = _engine_list(output.get("planned_engines"))
    engine_meta = search_meta.get("engine_meta", search_meta) if isinstance(search_meta, dict) else {}
    attempted = list(engine_meta.keys()) if isinstance(engine_meta, dict) else _engine_list(search_meta.get("engines") if isinstance(search_meta, dict) else [])
    if not attempted and isinstance(search_meta, dict):
        attempted = _engine_list(search_meta.get("engines"))
    primary = _engine_list((output.get("primary_sources") or []))
    if not primary:
        identity_plan = output.get("data_source_plan", {}) if isinstance(output.get("data_source_plan"), dict) else {}
        primary = _engine_list(identity_plan.get("primary_sources"))
    if not primary:
        primary = [item for item in planned if item not in {"local_real_data", "local_evidence"}][:3]
    output["planned_engines"] = planned
    output["attempted_engines"] = attempted
    output["missing_primary_sources"] = [item for item in primary if item not in attempted]
    output["route_coverage"] = round(len(set(attempted) & set(planned)) / max(1, len(set(planned))), 4)
    return output


def _coverage_state(evidence: List[Dict[str, Any]], claims: List[Dict[str, Any]], artifacts: Dict[str, Any]) -> Dict[str, Any]:
    source_types = sorted({str(item.get("source_type") or "") for item in evidence if isinstance(item, dict) and item.get("source_type")})
    official = [item for item in evidence if str(item.get("source_type") or "") in OFFICIAL_SOURCE_TYPES or str(item.get("source_authority") or "") == "official"]
    statements = _statement_coverage(artifacts)
    valuation = artifacts.get("valuation", {}) if isinstance(artifacts.get("valuation"), dict) else {}
    peer = artifacts.get("peer_context", {}) if isinstance(artifacts.get("peer_context"), dict) else {}
    risk_evidence_ids = _claim_evidence_ids(claims, sections={"risks", "risk_factors"})
    return {
        "evidence_count": len(evidence),
        "official_evidence_count": len(official),
        "source_types": source_types,
        "three_statement": statements,
        "peer_compare": {"available": bool(peer.get("peer_count") or _has_claim(claims, "peer_compare")), "reason": str(peer.get("failure_reason") or "")},
        "valuation": {
            "available": bool(valuation.get("valuation_available")),
            "method": str(valuation.get("method") or valuation.get("valuation_method") or ""),
            "missing_inputs": _as_list(valuation.get("missing_inputs")),
        },
        "risk": {"available": bool(risk_evidence_ids), "evidence_ids": risk_evidence_ids[:6]},
    }


def _period_state(target_period: str, evidence: List[Dict[str, Any]], artifacts: Dict[str, Any]) -> Dict[str, Any]:
    periods: List[str] = []
    market_dates: List[str] = []
    basis = ""
    for item in evidence:
        if not isinstance(item, dict):
            continue
        period = str(item.get("period") or item.get("data_cutoff") or "").upper()
        if re.fullmatch(r"20\d{2}Q[1-4]", period):
            periods.append(period)
        source_type = str(item.get("source_type") or "")
        publish = str(item.get("publish_time") or item.get("source_timestamp") or "")
        if source_type in {"market_api", "market_data", "eastmoney_quote"} and publish:
            market_dates.append(publish[:10])
    metrics = artifacts.get("financial_metrics", {}) if isinstance(artifacts.get("financial_metrics"), dict) else {}
    for item in metrics.get("metrics", []) if isinstance(metrics.get("metrics"), list) else []:
        if isinstance(item, dict):
            period = str(item.get("period") or "").upper()
            if re.fullmatch(r"20\d{2}Q[1-4]", period):
                periods.append(period)
    latest = sorted(set(periods))[-1] if periods else ""
    target = str(target_period or "").upper()
    if target.endswith("Q4") and latest == target:
        basis = "Q4/FY public disclosure; annual reports may be used as the latest full-year disclosure basis."
    elif latest:
        basis = "quarterly or latest available public disclosure"
    return {
        "target_period": target,
        "latest_available_disclosure_period": latest,
        "financial_data_basis": basis,
        "market_data_as_of": sorted(set(market_dates))[-1] if market_dates else "",
        "has_data_delay": bool(target and latest and target != latest),
        "notes": [],
    }


def _industry_profile(identity: Dict[str, Any], evidence: List[Dict[str, Any]], claims: List[Dict[str, Any]]) -> Dict[str, Any]:
    industry = str(identity.get("industry") or "")
    sector = str(identity.get("sector") or "")
    business = str(identity.get("business_summary") or "")
    evidence_ids: List[str] = []
    official_snippets: List[str] = []
    fallback_snippets: List[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        text = " ".join([str(item.get("title") or ""), str(item.get("content") or "")[:800]])
        source_type = str(item.get("source_type") or "")
        if source_type in OFFICIAL_SOURCE_TYPES:
            official_snippets.append(text)
            evidence_ids.append(str(item.get("evidence_id") or item.get("sample_id") or ""))
        else:
            fallback_snippets.append(text)
    official_text = " ".join(official_snippets)
    fallback_text = " ".join(fallback_snippets)
    inferred = _infer_business_summary(official_text) or _infer_business_summary(fallback_text)
    confidence = 0.45
    source_priority = "identity"
    if industry or sector:
        confidence = 0.72
    if official_text and inferred:
        business = inferred
        confidence = 0.9
        source_priority = "official_disclosure"
    elif fallback_text and inferred and not business:
        business = inferred
        confidence = max(confidence, 0.62)
        source_priority = "market_or_search"
    return {
        "industry": industry,
        "sector": sector,
        "business_summary": business,
        "confidence": round(confidence, 3),
        "source_priority": source_priority,
        "evidence_ids": [item for item in _dedupe(evidence_ids) if item][:8],
    }


def _infer_business_summary(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ["main business", "主营业务", "production and sales", "manufacture and sale"]):
        return _shorten(text, 320)
    if any(term in lowered for term in ["revenue", "segment", "business", "产品", "渠道", "客户"]):
        return _shorten(text, 220)
    return ""


def _statement_coverage(artifacts: Dict[str, Any]) -> Dict[str, bool]:
    tables = _as_list(artifacts.get("tables"))
    names = " ".join(str(row.get("statement") or row.get("table_type") or row.get("title") or "") for row in tables if isinstance(row, dict)).lower()
    metrics = artifacts.get("financial_metrics", {}) if isinstance(artifacts.get("financial_metrics"), dict) else {}
    metric_names = {str(item.get("metric_name") or "").lower() for item in metrics.get("metrics", []) if isinstance(item, dict)}
    return {
        "income": any(term in names for term in ["income", "利润"]) or bool({"revenue", "net_income"} & metric_names),
        "balance": any(term in names for term in ["balance", "资产"]) or bool({"total_assets", "total_liabilities", "cash_and_equivalents"} & metric_names),
        "cash_flow": any(term in names for term in ["cash", "现金"]) or bool({"operating_cash_flow", "free_cash_flow", "capex"} & metric_names),
    }


def _agent_write(task_type: str, state: Dict[str, Any], output: Dict[str, Any]) -> Dict[str, Any]:
    writes_by_task = {
        "deep_researcher": ["evidence_candidates", "search_meta", "market_route"],
        "browser": ["evidence_records", "pdf_artifacts"],
        "deep_analyze": [
            "claims",
            "analysis_artifacts",
            "coverage",
            "role_outputs",
            "identity_profile",
            "three_statement_analysis",
            "peer_analysis",
            "valuation_analysis",
            "risk_analysis",
        ],
        "identity_profile": ["role_outputs", "identity_profile"],
        "three_statement_analysis": ["role_outputs", "three_statement_analysis"],
        "peer_analysis": ["role_outputs", "peer_analysis"],
        "valuation_analysis": ["role_outputs", "valuation_analysis"],
        "risk_analysis": ["role_outputs", "risk_analysis"],
        "final_answer": ["markdown", "report_json"],
        "verifier": ["verification_report", "gap_resolution_trace"],
        "gap_resolver": ["gap_resolution_trace", "data_repair_summary", "repair_constraints"],
    }
    return {
        "agent": _agent_name(task_type),
        "task_type": task_type,
        "writes": writes_by_task.get(task_type, []),
        "evidence_count": len(_as_list(state.get("evidence_records"))),
        "claim_count": len(_as_list(state.get("claims"))),
        "output_keys": sorted(output.keys()) if isinstance(output, dict) else [],
    }


def _claim_evidence_ids(claims: List[Dict[str, Any]], sections: set[str]) -> List[str]:
    ids: List[str] = []
    for claim in claims:
        if not isinstance(claim, dict) or str(claim.get("section_name") or "") not in sections:
            continue
        ids.extend(str(item) for item in _as_list(claim.get("evidence_ids")) if str(item))
    return _dedupe(ids)


def _has_claim(claims: List[Dict[str, Any]], section: str) -> bool:
    return any(isinstance(item, dict) and str(item.get("section_name") or "") == section for item in claims)


def _objection(category: str, severity: str, message: str) -> Dict[str, Any]:
    return {
        "category": category,
        "field": _field_for_category(category),
        "target_agent": _target_agent_for_category(category),
        "severity": severity,
        "blocking": str(severity).lower() in {"fatal", "blocker"},
        "required_action": _required_action_for_category(category),
        "message": message,
    }


def _target_agent_for_category(category: str) -> str:
    mapping = {
        "identity": "IdentityAgent",
        "identity_profile": "IdentityAgent",
        "industry_profile": "IdentityAgent",
        "three_statement": "StatementAgent",
        "period_consistency": "StatementAgent",
        "peer_analysis": "PeerAgent",
        "valuation_analysis": "ValuationAgent",
        "risk_analysis": "RiskAgent",
    }
    return mapping.get(str(category or ""), "FinalAnswerAgent")


def _field_for_category(category: str) -> str:
    mapping = {
        "identity": "company_identity",
        "industry_profile": "industry_profile",
        "three_statement": "role_outputs.three_statement_analysis",
        "period_consistency": "period_state",
        "identity_profile": "role_outputs.identity_profile",
        "peer_analysis": "role_outputs.peer_analysis",
        "valuation_analysis": "role_outputs.valuation_analysis",
        "risk_analysis": "role_outputs.risk_analysis",
    }
    return mapping.get(str(category or ""), str(category or ""))


def _required_action_for_category(category: str) -> str:
    mapping = {
        "identity": "resolve listed-company identity from authoritative sources",
        "industry_profile": "raise industry confidence or constrain report language",
        "three_statement": "complete statement coverage or disclose missing statements",
        "period_consistency": "align financial data basis with target period or downgrade explicitly",
        "identity_profile": "publish identity role output",
        "peer_analysis": "publish peer role output or explicit peer data gap",
        "valuation_analysis": "publish valuation role output or explicit missing-input explanation",
        "risk_analysis": "publish risk role output with sufficient evidence",
    }
    return mapping.get(str(category or ""), "revise the responsible blackboard field")


def _period_disclosed(text: str) -> bool:
    return any(term in text for term in ["数据期间说明", "目标报告期", "最新可得", "行情截至", "data cutoff", "latest available"])


def _engine_list(value: Any) -> List[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _dedupe(items: Iterable[Any]) -> List[Any]:
    output: List[Any] = []
    seen: set[str] = set()
    for item in items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _shorten(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _agent_name(task_type: str) -> str:
    return {
        "deep_researcher": "DeepResearcherAgent",
        "browser": "BrowserAgent",
        "deep_analyze": "DeepAnalyzeAgent",
        "final_answer": "FinalAnswerAgent",
        "verifier": "VerifierAgent",
        "gap_resolver": "GapResolverAgent",
    }.get(task_type, task_type)
