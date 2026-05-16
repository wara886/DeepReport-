"""DeepAnalyzeAgent for financial claim generation."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.agents.react_loop import run_react_tool_loop
from src.features.financial_metric_lineage import build_financial_metric_lineage, build_financial_metric_tables
from src.models import ModelAdapter
from src.schemas.claim import ClaimItem
from src.tools import ToolRegistry, build_core_tool_registry


ANALYZE_SYSTEM_PROMPT = """You are DeepAnalyzeAgent in a financial multi-agent research system.
Use only provided evidence and metrics. Do not invent facts.
Write every claim_text in Chinese.
Return only valid JSON:
{"claims":[{"section_name":"financial_analysis","claim_text":"...","evidence_ids":["..."],"numeric_values":{},"risk_level":"low|medium|high","confidence":0.8,"notes":"..."}]}
"""


class DeepAnalyzeAgent(BaseAgent):
    """Convert evidence records into evidence-backed financial claims."""

    def __init__(
        self,
        model: ModelAdapter | None = None,
        tool_registry: ToolRegistry | None = None,
        tools: Dict[str, Any] | None = None,
    ):
        self.tool_registry = tool_registry or build_core_tool_registry()
        super().__init__(name="DeepAnalyzeAgent", model=model, tools=tools or self.tool_registry.handlers())

    def get_capabilities(self) -> List[str]:
        return [
            "calculate financial metrics from evidence",
            "generate evidence-backed financial claims",
            "identify risk, trend, valuation, and business overview observations",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        records = task.parameters.get("evidence_records", [])
        if not isinstance(records, list):
            return self.failure(task, "evidence_records must be a list")
        max_records = int(task.parameters.get("max_records", len(records)) or len(records))
        content_limit = int(task.parameters.get("content_limit", 900) or 900)
        records = compact_records(records[:max_records], content_limit=content_limit)
        symbol = str(task.parameters.get("symbol") or _first_symbol(records))
        period = str(task.parameters.get("period") or _first_period(records))
        raw_data_root = str(task.parameters.get("raw_data_root") or "data/raw/real_data")
        react_attempted = bool(task.parameters.get("use_react", False))
        skill_brief = str(task.parameters.get("skill_brief", "")).strip()
        react_payload: Dict[str, Any] = {}
        if react_attempted and self.model and hasattr(self.model, "chat"):
            react_payload = self._run_react_analysis(
                task=task,
                records=records,
                symbol=symbol,
                period=period,
                raw_data_root=raw_data_root,
                skill_brief=skill_brief,
            )

        ratio_rows = _react_tool_result(react_payload, "calculate_financial_ratios", "rows")
        if ratio_rows is None:
            ratio_rows = self.call_tool("calculate_financial_ratios", records=records)["rows"]
        trend_rows = self.call_tool("build_trend_features", records=records)["rows"]
        statement_view = _react_tool_result(react_payload, "build_three_statement_view")
        if statement_view is None:
            statement_view = self.call_tool("build_three_statement_view", records=records)
        peer_context = _react_tool_result(react_payload, "build_peer_comparison")
        if peer_context is None:
            peer_context = self.call_tool("build_peer_comparison", symbol=symbol, period=period, raw_data_root=raw_data_root)
        valuation = _react_tool_result(react_payload, "perform_company_valuation")
        if valuation is None:
            valuation = self.call_tool(
                "perform_company_valuation",
                symbol=symbol,
                period=period,
                records=records,
                raw_data_root=raw_data_root,
            )
        financial_metric_lineage = build_financial_metric_lineage(records)
        table_artifacts = build_financial_metric_tables(records)
        valuation_model = valuation.get("valuation_model", {}) if isinstance(valuation, dict) else {}
        valuation_assumptions = valuation.get("valuation_assumptions", {}) if isinstance(valuation, dict) else {}
        valuation_sensitivity = valuation.get("valuation_sensitivity", {}) if isinstance(valuation, dict) else {}
        claims = build_rule_claims(
            records=records,
            ratio_rows=ratio_rows,
            trend_rows=trend_rows,
            statement_view=statement_view,
            peer_context=peer_context,
            valuation=valuation,
        )
        metadata: Dict[str, Any] = {
            "ratio_row_count": len(ratio_rows),
            "trend_row_count": len(trend_rows),
            "statement_line_item_count": int(statement_view.get("coverage", {}).get("line_item_count", 0)),
            "financial_metric_count": int(financial_metric_lineage.get("metric_count", 0) or 0),
            "table_artifact_count": len(table_artifacts),
            "peer_count": int(peer_context.get("peer_count", 0) or 0),
            "valuation_available": bool(valuation.get("valuation_available", False)),
            "llm_used": False,
            "react_attempted": react_attempted,
            "react_used": bool(react_payload.get("tool_results")),
            "react_trace": react_payload.get("react_trace", []),
            "skill_brief_chars": len(skill_brief),
        }

        if self.model and records:
            try:
                llm_payload = self.model.generate_json(
                    prompt=_build_analyze_prompt(
                        records=records,
                        ratio_rows=ratio_rows,
                        trend_rows=trend_rows,
                        statement_view=statement_view,
                        peer_context=peer_context,
                        valuation=valuation,
                        skill_brief=skill_brief,
                    ),
                    system_prompt=ANALYZE_SYSTEM_PROMPT,
                    extra_body={"max_tokens": int(task.parameters.get("max_tokens", 1800) or 1800)},
                )
                llm_claims = llm_payload.get("claims", [])
                if isinstance(llm_claims, list) and llm_claims:
                    claims = _merge_claims(normalize_claims(llm_claims), claims)
                    metadata["llm_used"] = True
            except Exception as exc:
                metadata["llm_error"] = str(exc)
        claims, gate_report = apply_evidence_gate(
            claims=claims,
            evidence_records=records,
            expected_period=period,
        )
        metadata["evidence_gate"] = gate_report

        return self.success(
            task,
            {
                "claims": [claim.to_dict() for claim in claims],
                "analysis_artifacts": {
                    "ratio_rows": ratio_rows,
                    "trend_rows": trend_rows,
                    "statement_view": statement_view,
                    "financial_metrics": financial_metric_lineage,
                    "tables": table_artifacts,
                    "peer_context": peer_context,
                    "valuation": valuation,
                    "valuation_model": valuation_model,
                    "valuation_assumptions": valuation_assumptions,
                    "valuation_sensitivity": valuation_sensitivity,
                },
            },
            metadata=metadata,
        )

    def _run_react_analysis(
        self,
        task: AgentTask,
        records: List[Dict[str, Any]],
        symbol: str,
        period: str,
        raw_data_root: str,
        skill_brief: str = "",
    ) -> Dict[str, Any]:
        allowed_tools = [
            "calculate_financial_ratios",
            "build_three_statement_view",
            "build_peer_comparison",
            "perform_company_valuation",
        ]
        schemas = [self.tool_registry.get(name).to_tool_schema() for name in allowed_tools]
        handlers = dict(self.tool_registry.handlers())
        handlers["calculate_financial_ratios"] = lambda **kwargs: self.call_tool(
            "calculate_financial_ratios",
            records=kwargs.pop("records", records),
        )
        handlers["build_three_statement_view"] = lambda **kwargs: self.call_tool(
            "build_three_statement_view",
            records=kwargs.pop("records", records),
        )
        handlers["build_peer_comparison"] = lambda **kwargs: self.call_tool(
            "build_peer_comparison",
            symbol=kwargs.pop("symbol", symbol),
            period=kwargs.pop("period", period),
            raw_data_root=kwargs.pop("raw_data_root", raw_data_root),
        )
        handlers["perform_company_valuation"] = lambda **kwargs: self.call_tool(
            "perform_company_valuation",
            symbol=kwargs.pop("symbol", symbol),
            period=kwargs.pop("period", period),
            records=kwargs.pop("records", records),
            raw_data_root=kwargs.pop("raw_data_root", raw_data_root),
        )
        result = run_react_tool_loop(
            model=self.model,
            system_prompt=(
                "You are DeepAnalyzeAgent. Choose financial tools to compute ratios, "
                "three-statement views, peer comparison, and valuation before claims are written."
            ),
            user_prompt=(
                f"Analyze symbol={symbol}, period={period}. "
                f"Evidence records available: {len(records)}. "
                f"{'Relevant skills: ' + skill_brief + ' ' if skill_brief else ''}"
                "Call the tools needed for a company stock research report."
            ),
            tool_schemas=schemas,
            handlers=handlers,
            max_steps=int(task.parameters.get("react_max_steps", 3) or 3),
        )
        tool_results: Dict[str, Any] = {}
        for observation in result.get("observations", []):
            if not isinstance(observation, dict):
                continue
            tool_name = str(observation.get("tool_name", ""))
            if tool_name:
                tool_results[tool_name] = observation.get("result", {})
        return {
            "tool_results": tool_results,
            "react_trace": result.get("trace", []),
            "final_content": result.get("final_content", ""),
            "error": result.get("error", ""),
        }


def build_rule_claims(
    records: List[Dict[str, Any]],
    ratio_rows: List[Dict[str, Any]],
    trend_rows: List[Dict[str, Any]],
    statement_view: Dict[str, Any] | None = None,
    peer_context: Dict[str, Any] | None = None,
    valuation: Dict[str, Any] | None = None,
) -> List[ClaimItem]:
    claims: List[ClaimItem] = []
    claim_index = 1
    statement_view = statement_view or {}
    peer_context = peer_context or {}
    valuation = valuation or {}
    financial_evidence_ids = _financial_evidence_ids(records)
    profile_evidence_ids = _source_evidence_ids(records, {"company_profile"})
    filing_evidence_ids = _source_evidence_ids(records, {"filing"})
    market_evidence_ids = _source_evidence_ids(records, {"market", "market_api"})
    profile_record = _first_record_by_source(records, {"company_profile"})
    profile_meta = profile_record.get("metadata", {}) if isinstance(profile_record.get("metadata"), dict) else {}
    if profile_record and profile_evidence_ids:
        symbol = str(profile_record.get("symbol") or profile_meta.get("symbol") or "Company")
        company_name = str(profile_meta.get("company_name") or symbol)
        sector = str(profile_meta.get("sector") or "未知板块")
        industry = str(profile_meta.get("industry") or "未知行业")
        description = str(profile_meta.get("description") or profile_record.get("content") or "").strip()
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="strategy_business",
                claim_text=f"{company_name}（{symbol}）主营业务位于{sector}板块、{industry}行业；业务描述为：{description or '证据未披露详细业务描述'}。",
                evidence_ids=profile_evidence_ids,
                numeric_values={},
                risk_level="low",
                confidence=0.78,
                notes="由 company_profile 证据生成主营业务与行业定位。",
            )
        )
        claim_index += 1
        governance_fields = [
            str(profile_meta.get("ownership_structure") or ""),
            str(profile_meta.get("governance") or ""),
            str(profile_meta.get("management") or ""),
        ]
        governance_text = "；".join(item for item in governance_fields if item.strip())
        if not governance_text:
            governance_text = "当前本地 company_profile 尚未披露股权结构、董事会或管理层明细，需后续接入年报/DEF14A/公告表格补全。"
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="ownership_governance",
                claim_text=f"{company_name} 的股权结构与公司治理信息：{governance_text}",
                evidence_ids=profile_evidence_ids,
                numeric_values={},
                risk_level="medium",
                confidence=0.66 if "尚未披露" in governance_text else 0.76,
                notes="治理信息由 company_profile 字段生成；缺失时显式标记数据缺口。",
            )
        )
        claim_index += 1

    for row in ratio_rows:
        evidence_id = str(row.get("sample_id", ""))
        symbol = str(row.get("symbol", "Company") or "Company")
        if _has_number(row.get("revenue_billion")):
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_analysis",
                    claim_text=f"{symbol} 在可用证据中披露的营收约为 {float(row['revenue_billion']):.1f}B。",
                    evidence_ids=[evidence_id] if evidence_id else [],
                    numeric_values={"revenue_billion": float(row["revenue_billion"])},
                    risk_level="medium",
                    confidence=0.82,
                    notes="由 DeepAnalyzeAgent 从财务证据提取。",
                )
            )
            claim_index += 1
        if _has_number(row.get("gross_margin_pct")):
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_analysis",
                    claim_text=f"{symbol} 的毛利率约为 {float(row['gross_margin_pct']):.1f}%。",
                    evidence_ids=[evidence_id] if evidence_id else [],
                    numeric_values={"gross_margin_pct": float(row["gross_margin_pct"])},
                    risk_level="low",
                    confidence=0.8,
                    notes="由 DeepAnalyzeAgent 从财务证据提取。",
                )
            )
            claim_index += 1
        if _has_number(row.get("operating_cash_flow_billion")):
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_analysis",
                    claim_text=f"{symbol} 的经营现金流约为 {float(row['operating_cash_flow_billion']):.1f}B。",
                    evidence_ids=[evidence_id] if evidence_id else [],
                    numeric_values={"operating_cash_flow_billion": float(row["operating_cash_flow_billion"])},
                    risk_level="medium",
                    confidence=0.78,
                    notes="由 DeepAnalyzeAgent 从财务证据提取。",
                )
            )
            claim_index += 1

    coverage = statement_view.get("coverage", {}) if isinstance(statement_view, dict) else {}
    if coverage.get("has_three_statement_view") and financial_evidence_ids:
        line_item_count = float(coverage.get("line_item_count", 0) or 0)
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="financial_statements",
                claim_text=f"系统已构建三表视图，覆盖 {int(line_item_count)} 个核心项目。",
                evidence_ids=financial_evidence_ids,
                numeric_values={"statement_line_item_count": line_item_count},
                risk_level="medium",
                confidence=0.74,
                notes="由 build_three_statement_view 生成覆盖结论。",
            )
        )
        claim_index += 1

    statement_rows = statement_view.get("rows", []) if isinstance(statement_view, dict) else []
    net_income = _statement_value(statement_rows, "income_statement", "net_income")
    free_cash_flow = _statement_value(statement_rows, "cash_flow_statement", "free_cash_flow")
    if _has_number(net_income) and _has_number(free_cash_flow) and financial_evidence_ids:
        symbol = str(statement_rows[0].get("symbol") or "Company") if statement_rows else "Company"
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="financial_statements",
                claim_text=f"{symbol} 三表视图显示，估算净利润约为 {float(net_income):.1f}B，自由现金流约为 {float(free_cash_flow):.1f}B。",
                evidence_ids=financial_evidence_ids,
                numeric_values={"net_income_billion": float(net_income), "free_cash_flow_billion": float(free_cash_flow)},
                risk_level="low",
                confidence=0.76,
                notes="由三表视图计算生成。",
            )
        )
        claim_index += 1

    ranking = peer_context.get("ranking", {}) if isinstance(peer_context, dict) else {}
    target_symbol = str(peer_context.get("target_symbol") or "Target company")
    peer_count = int(peer_context.get("peer_count", 0) or 0)
    margin_rank = ranking.get("gross_margin_pct", {}) if isinstance(ranking.get("gross_margin_pct"), dict) else {}
    growth_rank = ranking.get("revenue_growth_pct", {}) if isinstance(ranking.get("revenue_growth_pct"), dict) else {}
    if peer_count and (margin_rank or growth_rank) and financial_evidence_ids:
        parts = []
        numeric_values: Dict[str, float] = {"peer_count": float(peer_count)}
        if margin_rank:
            parts.append(f"毛利率排名 {int(margin_rank.get('rank', 0) or 0)}/{int(margin_rank.get('peer_count', 0) or 0)}")
            numeric_values["gross_margin_rank"] = float(margin_rank.get("rank", 0) or 0)
        if growth_rank:
            parts.append(f"收入增速排名 {int(growth_rank.get('rank', 0) or 0)}/{int(growth_rank.get('peer_count', 0) or 0)}")
            numeric_values["revenue_growth_rank"] = float(growth_rank.get("rank", 0) or 0)
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="peer_compare",
                claim_text=f"{target_symbol} 已完成本地同行对比：" + "；".join(parts) + "。",
                evidence_ids=financial_evidence_ids,
                numeric_values=numeric_values,
                risk_level="low",
                confidence=0.78,
                notes="由同行比较工具生成。",
            )
        )
        claim_index += 1

    if valuation.get("valuation_available") and financial_evidence_ids:
        methods = valuation.get("methods", {}) if isinstance(valuation.get("methods"), dict) else {}
        dcf = methods.get("dcf", {}) if isinstance(methods.get("dcf"), dict) else {}
        market_gap = valuation.get("market_gap", {}) if isinstance(valuation.get("market_gap"), dict) else {}
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="valuation",
                claim_text=(
                    f"规则估值模型基于 P/E、P/S 与 DCF 估算综合股权价值约 "
                    f"{float(valuation.get('blended_equity_value_billion', 0.0) or 0.0):.1f}B，"
                    f"DCF 折现率假设为 {float(dcf.get('discount_rate', 0.0) or 0.0):.1%}。"
                ),
                evidence_ids=financial_evidence_ids + market_evidence_ids,
                numeric_values={
                    "blended_equity_value_billion": float(valuation.get("blended_equity_value_billion", 0.0) or 0.0),
                    "dcf_value_billion": float(dcf.get("value_billion", 0.0) or 0.0),
                },
                risk_level="medium",
                confidence=0.7,
                notes="由规则估值模型生成，依赖财务摘要、同行上下文与可选市场数据。",
            )
        )
        claim_index += 1
        sensitivity = valuation.get("sensitivity", {}) if isinstance(valuation.get("sensitivity"), dict) else {}
        if sensitivity:
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="valuation_sensitivity",
                    claim_text=(
                        "估值敏感性显示：FCF 增速下调 2pct 时 DCF 约为 "
                        f"{float(sensitivity.get('fcf_growth_minus_2pct', 0.0) or 0.0):.1f}B，"
                        "上调 2pct 时约为 "
                        f"{float(sensitivity.get('fcf_growth_plus_2pct', 0.0) or 0.0):.1f}B，"
                        "折现率上调 1pct 时约为 "
                        f"{float(sensitivity.get('discount_rate_plus_1pct', 0.0) or 0.0):.1f}B。"
                    ),
                    evidence_ids=financial_evidence_ids,
                    numeric_values={
                        "dcf_growth_down_billion": float(sensitivity.get("fcf_growth_minus_2pct", 0.0) or 0.0),
                        "dcf_growth_up_billion": float(sensitivity.get("fcf_growth_plus_2pct", 0.0) or 0.0),
                        "dcf_discount_up_billion": float(sensitivity.get("discount_rate_plus_1pct", 0.0) or 0.0),
                    },
                    risk_level="medium",
                    confidence=0.7,
                    notes="由估值模型敏感性表生成。",
                )
            )
            claim_index += 1
        if market_gap.get("available"):
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="valuation",
                    claim_text=(
                        f"市场对照显示，当前市值约为 {float(market_gap.get('market_cap_billion', 0.0) or 0.0):.1f}B，"
                        f"规则估值与市值差异约为 {float(market_gap.get('valuation_gap_pct', 0.0) or 0.0):.1f}%。"
                    ),
                    evidence_ids=market_evidence_ids or financial_evidence_ids,
                    numeric_values={
                        "market_cap_billion": float(market_gap.get("market_cap_billion", 0.0) or 0.0),
                        "valuation_gap_pct": float(market_gap.get("valuation_gap_pct", 0.0) or 0.0),
                    },
                    risk_level="medium",
                    confidence=0.72,
                    notes="由估值模型和市场数据对照生成。",
                )
            )
            claim_index += 1
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="conclusion",
                claim_text=f"基于增长、利润率、ROE 与同行比较，模型给出的初步结论为“{valuation.get('recommendation', '中性观察')}”。",
                evidence_ids=financial_evidence_ids,
                numeric_values={},
                risk_level="medium",
                confidence=0.68,
                notes="由估值模型生成，不构成投资建议。",
            )
        )
        claim_index += 1

    for row in trend_rows:
        symbol = str(row.get("symbol", "Company") or "Company")
        evidence_count = int(row.get("evidence_count", 0) or 0)
        source_count = int(row.get("unique_sources", 0) or 0)
        sample_ids = str(row.get("sample_ids", "")).split("|") if row.get("sample_ids") else []
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="business_overview",
                claim_text=f"{symbol} 的证据覆盖包括 {evidence_count} 条记录，横跨 {source_count} 类来源。",
                evidence_ids=[item for item in sample_ids if item],
                numeric_values={"evidence_count": float(evidence_count), "unique_sources": float(source_count)},
                risk_level="low",
                confidence=0.76,
                notes="由证据覆盖统计生成。",
            )
        )
        claim_index += 1

    for record in records:
        content = str(record.get("content", "")).lower()
        if "risk" in content or "supply" in content or "legal" in content:
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="risks",
                    claim_text=f"{record.get('title', 'Source')} 提示了相关风险或运营关注点。",
                    evidence_ids=[str(record.get("evidence_id") or record.get("sample_id") or "")],
                    numeric_values={},
                    risk_level="medium",
                    confidence=0.68,
                    notes="由来源内容识别风险信号。",
                )
            )
            claim_index += 1
    return claims

def _react_tool_result(payload: Dict[str, Any], tool_name: str, field: str | None = None) -> Any:
    results = payload.get("tool_results", {}) if isinstance(payload, dict) else {}
    if not isinstance(results, dict) or tool_name not in results:
        return None
    result = results.get(tool_name)
    if field is None:
        return result if isinstance(result, dict) else None
    if isinstance(result, dict) and field in result:
        return result[field]
    return None


def apply_evidence_gate(
    claims: List[ClaimItem],
    evidence_records: List[Dict[str, Any]],
    expected_period: str = "",
) -> tuple[List[ClaimItem], Dict[str, Any]]:
    """Keep only claims grounded in currently available evidence records."""

    evidence_by_id = _evidence_by_id(evidence_records)
    accepted: List[ClaimItem] = []
    rejected: List[Dict[str, Any]] = []
    for claim in claims:
        original_ids = list(claim.evidence_ids)
        claim.evidence_ids = [evidence_id for evidence_id in original_ids if evidence_id in evidence_by_id]
        reasons: List[str] = []
        if not claim.evidence_ids:
            reasons.append("missing_or_unknown_evidence_ids")
        if claim.numeric_values and not _is_derived_claim_allowed(claim):
            missing = _unsupported_numeric_keys(claim=claim, evidence_by_id=evidence_by_id)
            if missing:
                reasons.append("unsupported_numeric_values:" + ",".join(missing))
        if expected_period and claim.numeric_values and _is_period_sensitive_section(claim.section_name):
            if _all_evidence_mismatched_period(claim=claim, evidence_by_id=evidence_by_id, expected_period=expected_period):
                reasons.append(f"different_fiscal_period:{expected_period}")
        if reasons:
            rejected.append(
                {
                    "claim_id": claim.claim_id,
                    "section_name": claim.section_name,
                    "reasons": reasons,
                    "evidence_ids": original_ids,
                    "claim_text": claim.claim_text[:220],
                }
            )
            continue
        claim.claim_id = f"cl_{len(accepted) + 1:04d}"
        accepted.append(claim)
    return accepted, {
        "input_claim_count": len(claims),
        "accepted_claim_count": len(accepted),
        "rejected_claim_count": len(rejected),
        "rejected_claims": rejected[:20],
    }


def normalize_claims(items: List[Dict[str, Any]]) -> List[ClaimItem]:
    claims = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        data = {
            "claim_id": str(item.get("claim_id") or f"cl_{index:04d}"),
            "section_name": str(item.get("section_name") or "financial_analysis"),
            "claim_text": str(item.get("claim_text") or ""),
            "evidence_ids": [str(value) for value in item.get("evidence_ids", [])],
            "numeric_values": _numeric_values(item.get("numeric_values", {})),
            "risk_level": str(item.get("risk_level") or "medium"),
            "confidence": float(item.get("confidence", 0.7) or 0.7),
            "notes": str(item.get("notes") or "Generated by DeepAnalyzeAgent."),
        }
        if _looks_conflicted(data):
            continue
        if data["claim_text"]:
            claims.append(ClaimItem.from_dict(data))
    return claims


def _build_analyze_prompt(
    records: List[Dict[str, Any]],
    ratio_rows: List[Dict[str, Any]],
    trend_rows: List[Dict[str, Any]],
    statement_view: Dict[str, Any] | None = None,
    peer_context: Dict[str, Any] | None = None,
    valuation: Dict[str, Any] | None = None,
    skill_brief: str = "",
) -> str:
    compact_records = [
        {
            "evidence_id": item.get("evidence_id"),
            "title": item.get("title"),
            "source_type": item.get("source_type"),
            "content": str(item.get("content", "")),
        }
        for item in records[:10]
    ]
    skill_line = f"Relevant skill brief:\n{skill_brief}\n" if skill_brief else ""
    return (
        "Generate concise, evidence-backed financial report claims. All claim_text values must be Chinese.\n"
        f"{skill_line}"
        f"Evidence records: {compact_records}\n"
        f"Financial ratio rows: {ratio_rows[:10]}\n"
        f"Trend rows: {trend_rows[:10]}\n"
        f"Three-statement view: {statement_view}\n"
        f"Peer context: {peer_context}\n"
        f"Valuation: {valuation}"
    )


def compact_records(records: List[Dict[str, Any]], content_limit: int = 900) -> List[Dict[str, Any]]:
    output = []
    for item in records:
        row = dict(item)
        row["content"] = str(row.get("content", ""))[:content_limit]
        output.append(row)
    return output


def _has_number(value: Any) -> bool:
    try:
        return value is not None and str(value) != "nan" and float(value) == float(value)
    except (TypeError, ValueError):
        return False


def _numeric_values(value: Any) -> Dict[str, float]:
    if not isinstance(value, dict):
        return {}
    output: Dict[str, float] = {}
    for key, raw in value.items():
        try:
            output[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return output


def _looks_conflicted(data: Dict[str, Any]) -> bool:
    text = f"{data.get('claim_text', '')} {data.get('notes', '')}".lower()
    conflict_markers = [
        "discrepancy",
        "conflict",
        "inconsistent",
        "different fiscal period",
    ]
    return any(marker in text for marker in conflict_markers)


def _merge_claims(primary: List[ClaimItem], secondary: List[ClaimItem]) -> List[ClaimItem]:
    output: List[ClaimItem] = []
    seen = set()
    for claim in primary + secondary:
        key = claim.claim_text
        if key in seen:
            continue
        seen.add(key)
        claim.claim_id = f"cl_{len(output) + 1:04d}"
        output.append(claim)
    return output


def _evidence_by_id(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in [record.get("evidence_id"), record.get("sample_id"), record.get("chunk_id"), record.get("parent_sample_id")]:
            evidence_id = str(key or "").strip()
            if evidence_id:
                output.setdefault(evidence_id, record)
    return output


def _unsupported_numeric_keys(claim: ClaimItem, evidence_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    evidence_numbers: List[float] = []
    for evidence_id in claim.evidence_ids:
        record = evidence_by_id.get(evidence_id)
        if record:
            evidence_numbers.extend(_numbers_from_record(record))
    missing = []
    for key, value in claim.numeric_values.items():
        try:
            target = float(value)
        except (TypeError, ValueError):
            continue
        if not _has_close_number(target, evidence_numbers):
            missing.append(str(key))
    return missing


def _is_period_sensitive_section(section_name: str) -> bool:
    return str(section_name or "").strip().lower() in {"financial_analysis", "financial_statements"}


def _all_evidence_mismatched_period(
    claim: ClaimItem,
    evidence_by_id: Dict[str, Dict[str, Any]],
    expected_period: str,
) -> bool:
    relevant_records = [evidence_by_id[evidence_id] for evidence_id in claim.evidence_ids if evidence_id in evidence_by_id]
    if not relevant_records:
        return False
    mismatches = [_record_mentions_other_period(record=record, expected_period=expected_period) for record in relevant_records]
    return all(mismatches)


def _record_mentions_other_period(record: Dict[str, Any], expected_period: str) -> bool:
    expected = _parse_period_label(expected_period)
    if not expected:
        return False
    expected_year, expected_quarter = expected
    record_period = _parse_period_label(str(record.get("period") or ""))
    if record_period:
        return record_period != expected

    text = " ".join(
        [
            str(record.get("title", "")),
            str(record.get("content", "")),
            json.dumps(record.get("metadata", {}), ensure_ascii=False),
        ]
    )
    mentioned_periods = _extract_period_mentions(text)
    if not mentioned_periods:
        return False
    same_year_mentions = [period for period in mentioned_periods if period[0] == expected_year]
    if not same_year_mentions:
        return False
    return all(period[1] != expected_quarter for period in same_year_mentions)


def _numbers_from_record(record: Dict[str, Any]) -> List[float]:
    values: List[float] = []
    values.extend(_numbers_from_text(str(record.get("content", ""))))
    for key in ["numeric_values", "metadata", "key_points"]:
        values.extend(_numbers_from_json(record.get(key)))
    return values


def _parse_period_label(value: str) -> tuple[str, str] | None:
    match = re.search(r"(\d{4})\s*Q([1-4])", str(value or ""), flags=re.I)
    if not match:
        return None
    return match.group(1), f"Q{match.group(2)}"


def _extract_period_mentions(text: str) -> List[tuple[str, str]]:
    content = str(text or "")
    mentions: List[tuple[str, str]] = []
    patterns = [
        re.compile(r"(\d{4})\s*Q([1-4])", flags=re.I),
        re.compile(r"(first|second|third|fourth)\s+quarter\s+of?\s*(\d{4})", flags=re.I),
        re.compile(r"(first|second|third|fourth)\s+quarter\s+(\d{4})", flags=re.I),
    ]
    quarter_map = {
        "first": "Q1",
        "second": "Q2",
        "third": "Q3",
        "fourth": "Q4",
    }

    for match in patterns[0].finditer(content):
        mentions.append((match.group(1), f"Q{match.group(2)}"))
    for pattern in patterns[1:]:
        for match in pattern.finditer(content):
            mentions.append((match.group(2), quarter_map.get(match.group(1).lower(), "")))

    deduped: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for year, quarter in mentions:
        key = (year, quarter)
        if quarter and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def _numbers_from_json(value: Any) -> List[float]:
    values: List[float] = []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_numbers_from_json(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_numbers_from_json(item))
    elif isinstance(value, (int, float)):
        values.append(float(value))
    elif isinstance(value, str):
        values.extend(_numbers_from_text(value))
    return values


def _numbers_from_text(text: str) -> List[float]:
    values: List[float] = []
    for match in re.findall(r"-?\d+(?:\.\d+)?", str(text or "")):
        try:
            values.append(float(match))
        except ValueError:
            continue
    return values


def _has_close_number(target: float, values: List[float]) -> bool:
    for value in values:
        tolerance = max(abs(target) * 0.01, 0.05)
        if abs(value - target) <= tolerance:
            return True
    return False


def _is_derived_claim_allowed(claim: ClaimItem) -> bool:
    text = f"{claim.section_name} {claim.claim_text} {claim.notes}".lower()
    markers = [
        "valuation",
        "peer_compare",
        "business_overview",
        "coverage",
        "source",
        "rank",
        "model",
        "derived",
        "estimated",
    ]
    return any(marker in text for marker in markers)


def _financial_evidence_ids(records: List[Dict[str, Any]]) -> List[str]:
    return _source_evidence_ids(records, {"financials"})


def _source_evidence_ids(records: List[Dict[str, Any]], source_types: set[str]) -> List[str]:
    ids = []
    for record in records:
        if str(record.get("source_type", "")).lower() in source_types:
            evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
            if evidence_id and evidence_id not in ids:
                ids.append(evidence_id)
    return ids


def _first_record_by_source(records: List[Dict[str, Any]], source_types: set[str]) -> Dict[str, Any]:
    for record in records:
        if str(record.get("source_type", "")).lower() in source_types:
            return record
    return {}


def _statement_value(rows: Any, statement: str, line_item: str) -> float | None:
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("statement") == statement and row.get("line_item") == line_item:
            try:
                return float(row.get("value_billion"))
            except (TypeError, ValueError):
                return None
    return None


def _first_symbol(records: List[Dict[str, Any]]) -> str:
    for record in records:
        symbol = str(record.get("symbol") or "").strip()
        if symbol:
            return symbol.upper()
    return ""


def _first_period(records: List[Dict[str, Any]]) -> str:
    for record in records:
        period = str(record.get("period") or "").strip()
        if period:
            return period
    return ""
