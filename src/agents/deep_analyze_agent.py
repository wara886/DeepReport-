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
            expected_period=period,
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
                    claims = _merge_claims(_filter_supported_llm_claims(normalize_claims(llm_claims), records), claims)
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
    expected_period: str = "",
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

    pdf_claims, claim_index = _build_pdf_section_claims(records=records, start_index=claim_index, expected_period=expected_period)
    claims.extend(pdf_claims)

    for record in records:
        if str(record.get("source_type") or "") != "sec_companyfacts":
            continue
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        metrics = metadata.get("metrics", {}) if isinstance(metadata.get("metrics"), dict) else {}
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        symbol = str(record.get("symbol") or "Company")
        revenue = _sec_metric(metrics, "RevenueFromContractWithCustomerExcludingAssessedTax") or _sec_metric(metrics, "Revenues")
        net_income = _sec_metric(metrics, "NetIncomeLoss")
        assets = _sec_metric(metrics, "Assets")
        cash = _sec_metric(metrics, "CashAndCashEquivalentsAtCarryingValue")
        if revenue and evidence_id:
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_analysis",
                    claim_text=(
                        f"{symbol} SEC companyfacts 显示，最新可用收入指标约为 "
                        f"{_format_sec_value(revenue)}，期间截止 {revenue.get('end', '未披露')}。"
                    ),
                    evidence_ids=[evidence_id],
                    numeric_values={"revenue": float(revenue["value"])},
                    risk_level="medium",
                    confidence=0.86,
                    notes="由 SEC EDGAR companyfacts 结构化事实生成。",
                )
            )
            claim_index += 1
        if net_income and evidence_id:
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_analysis",
                    claim_text=(
                        f"{symbol} SEC companyfacts 显示，最新可用净利润指标约为 "
                        f"{_format_sec_value(net_income)}，期间截止 {net_income.get('end', '未披露')}。"
                    ),
                    evidence_ids=[evidence_id],
                    numeric_values={"net_income": float(net_income["value"])},
                    risk_level="medium",
                    confidence=0.84,
                    notes="由 SEC EDGAR companyfacts 结构化事实生成。",
                )
            )
            claim_index += 1
        balance_parts = []
        numeric_values: Dict[str, float] = {}
        if assets:
            balance_parts.append(f"资产约为 {_format_sec_value(assets)}")
            numeric_values["assets"] = float(assets["value"])
        if cash:
            balance_parts.append(f"现金及等价物约为 {_format_sec_value(cash)}")
            numeric_values["cash_and_equivalents"] = float(cash["value"])
        if balance_parts and evidence_id:
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_statements",
                    claim_text=f"{symbol} SEC companyfacts 资产负债表指标显示，" + "，".join(balance_parts) + "。",
                    evidence_ids=[evidence_id],
                    numeric_values=numeric_values,
                    risk_level="medium",
                    confidence=0.82,
                    notes="由 SEC EDGAR companyfacts 结构化事实生成。",
                )
            )
            claim_index += 1

    for record in records:
        if str(record.get("source_type") or "") != "eastmoney_financials":
            continue
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        raw = metadata.get("raw", {}) if isinstance(metadata.get("raw"), dict) else {}
        table_type = str(metadata.get("table_type") or "")
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        symbol = str(record.get("symbol") or "Company")
        report_date = str(raw.get("REPORT_DATE") or raw.get("REPORTDATE") or record.get("period") or "未披露")
        if table_type == "income":
            revenue = _first_number(raw, ["OPERATE_INCOME", "TOTAL_OPERATE_INCOME", "营业总收入", "营业收入"])
            net_income = _first_number(raw, ["NETPROFIT", "PARENT_NETPROFIT", "净利润", "归母净利润"])
            parts = []
            numeric_values: Dict[str, float] = {}
            if revenue is not None:
                parts.append(f"营业收入约为 {_format_financial_amount(revenue, 'CNY')}")
                numeric_values["revenue"] = revenue
            if net_income is not None:
                parts.append(f"净利润约为 {_format_financial_amount(net_income, 'CNY')}")
                numeric_values["net_income"] = net_income
            if parts and evidence_id:
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} 东方财富财务表显示，{report_date} " + "，".join(parts) + "。",
                        evidence_ids=[evidence_id],
                        numeric_values=numeric_values,
                        risk_level="medium",
                        confidence=0.8,
                        notes="由东方财富结构化利润表记录生成，仍建议用巨潮/交易所公告 PDF 交叉验证。",
                    )
                )
                claim_index += 1
        if table_type == "balance":
            assets = _first_number(raw, ["TOTAL_ASSETS", "资产总计", "总资产"])
            liabilities = _first_number(raw, ["TOTAL_LIABILITIES", "负债合计", "总负债"])
            equity = _first_number(raw, ["TOTAL_EQUITY", "所有者权益合计", "股东权益合计"])
            parts = []
            numeric_values = {}
            if assets is not None:
                parts.append(f"总资产约为 {_format_financial_amount(assets, 'CNY')}")
                numeric_values["assets"] = assets
            if liabilities is not None:
                parts.append(f"总负债约为 {_format_financial_amount(liabilities, 'CNY')}")
                numeric_values["liabilities"] = liabilities
            if equity is not None:
                parts.append(f"所有者权益约为 {_format_financial_amount(equity, 'CNY')}")
                numeric_values["equity"] = equity
            if parts and evidence_id:
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_statements",
                        claim_text=f"{symbol} 东方财富资产负债表显示，{report_date} " + "，".join(parts) + "。",
                        evidence_ids=[evidence_id],
                        numeric_values=numeric_values,
                        risk_level="medium",
                        confidence=0.78,
                        notes="由东方财富结构化资产负债表记录生成，仍建议用巨潮/交易所公告 PDF 交叉验证。",
                    )
                )
                claim_index += 1
        if table_type == "cashflow":
            ocf = _first_number(raw, ["NETCASH_OPERATE", "经营活动产生的现金流量净额"])
            icf = _first_number(raw, ["NETCASH_INVEST", "投资活动产生的现金流量净额"])
            fcf = _first_number(raw, ["NETCASH_FINANCE", "筹资活动产生的现金流量净额"])
            parts = []
            numeric_values = {}
            if ocf is not None:
                parts.append(f"经营现金流净额约为 {_format_financial_amount(ocf, 'CNY')}")
                numeric_values["operating_cash_flow"] = ocf
            if icf is not None:
                parts.append(f"投资现金流净额约为 {_format_financial_amount(icf, 'CNY')}")
                numeric_values["investing_cash_flow"] = icf
            if fcf is not None:
                parts.append(f"筹资现金流净额约为 {_format_financial_amount(fcf, 'CNY')}")
                numeric_values["financing_cash_flow"] = fcf
            if parts and evidence_id:
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_statements",
                        claim_text=f"{symbol} 东方财富现金流量表显示，{report_date} " + "，".join(parts) + "。",
                        evidence_ids=[evidence_id],
                        numeric_values=numeric_values,
                        risk_level="medium",
                        confidence=0.78,
                        notes="由东方财富结构化现金流量表记录生成，仍建议用巨潮/交易所公告 PDF 交叉验证。",
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
    for summary_claim in _statement_summary_claims(
        rows=statement_rows,
        evidence_ids=financial_evidence_ids,
        start_index=claim_index,
    ):
        claims.append(summary_claim)
        claim_index += 1
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

    for valuation_claim in _minimum_valuation_claims(
        records=records,
        statement_rows=statement_rows,
        financial_evidence_ids=financial_evidence_ids,
        market_evidence_ids=market_evidence_ids,
        start_index=claim_index,
    ):
        claims.append(valuation_claim)
        claim_index += 1

    for row in trend_rows:
        symbol = str(row.get("symbol", "Company") or "Company")
        if symbol == "Company":
            continue
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
    return _add_minimum_company_report_claims(claims=claims, records=records, start_index=claim_index)

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


def _minimum_valuation_claims(
    records: List[Dict[str, Any]],
    statement_rows: Any,
    financial_evidence_ids: List[str],
    market_evidence_ids: List[str],
    start_index: int,
) -> List[ClaimItem]:
    if not financial_evidence_ids:
        return []
    rows = statement_rows if isinstance(statement_rows, list) else []
    symbol = _first_symbol(records) or (str(rows[0].get("symbol") or "Company") if rows and isinstance(rows[0], dict) else "Company")
    period = str(rows[0].get("period") or "") if rows and isinstance(rows[0], dict) else ""
    revenue = _statement_value(rows, "income_statement", "revenue")
    net_income = _statement_value(rows, "income_statement", "net_income")
    equity = _statement_value(rows, "balance_sheet", "total_equity")
    if equity is None:
        equity = _statement_value(rows, "balance_sheet", "shareholders_equity")
    market_cap, market_unit, market_source = _market_cap_from_records(records)
    evidence_ids = list(dict.fromkeys(financial_evidence_ids + market_evidence_ids + ([market_source] if market_source else [])))
    output: List[ClaimItem] = []
    claim_index = start_index

    multiples: List[str] = []
    numeric_values: Dict[str, float] = {}
    if market_cap and net_income and net_income > 0:
        pe = market_cap / _align_market_denominator(net_income)
        multiples.append(f"P/E 约为 {pe:.1f}x")
        numeric_values["pe"] = pe
    if market_cap and equity and equity > 0:
        pb = market_cap / _align_market_denominator(equity)
        multiples.append(f"P/B 约为 {pb:.1f}x")
        numeric_values["pb"] = pb
    if market_cap and revenue and revenue > 0:
        ps = market_cap / _align_market_denominator(revenue)
        multiples.append(f"P/S 约为 {ps:.1f}x")
        numeric_values["ps"] = ps

    if multiples:
        unit_text = "人民币十亿元" if market_unit == "CNY_billion" else "十亿美元"
        output.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="valuation",
                claim_text=(
                    f"{symbol} {period} 最小估值模型以公开行情市值（单位：{unit_text}）和三表数据为输入，"
                    + "、".join(multiples)
                    + "；该结果仅用于相对估值校验，不构成目标价。"
                ),
                evidence_ids=evidence_ids,
                numeric_values=numeric_values,
                risk_level="medium",
                confidence=0.7,
                notes="最小估值模型：market cap + net income/equity/revenue。",
            )
        )
        claim_index += 1
    else:
        missing = []
        if not market_cap:
            missing.append("市值或股本口径")
        if not net_income:
            missing.append("净利润")
        if not equity:
            missing.append("净资产/股东权益")
        if not revenue:
            missing.append("收入")
        output.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="valuation",
                claim_text=(
                    f"{symbol} {period} 估值不可用原因：当前公开证据缺少"
                    + "、".join(missing)
                    + "，因此不能正式计算 P/E、P/B、P/S；报告应把这些缺口列为下一轮检索任务。"
                ),
                evidence_ids=evidence_ids,
                numeric_values={},
                risk_level="medium",
                confidence=0.68,
                notes="最小估值模型缺口披露。",
            )
        )
        claim_index += 1

    if revenue and net_income:
        net_margin = net_income / revenue
        delta = abs(revenue) * 0.01
        output.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="valuation_sensitivity",
                claim_text=(
                    f"{symbol} {period} 敏感性分析显示，当前净利率约为 {net_margin:.1%}；"
                    f"若净利率变动 1pct，净利润方向性影响约为 {_format_statement_number(delta)}。"
                    "??????????????????????????/????????????????????????"
                ),
                evidence_ids=financial_evidence_ids,
                numeric_values={"net_margin": net_margin, "net_income_delta_1pct": delta},
                risk_level="medium",
                confidence=0.7,
                notes="最小敏感性模型：收入 x 净利率变动。",
            )
        )
    return output


def _market_cap_from_records(records: List[Dict[str, Any]]) -> tuple[float | None, str, str]:
    for record in records:
        source_type = str(record.get("source_type") or "").lower()
        if source_type not in {"market", "market_api", "eastmoney_quote"}:
            continue
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        snapshot = metadata.get("snapshot") if isinstance(metadata.get("snapshot"), dict) else metadata
        value = (
            _safe_float(snapshot.get("market_cap_billion"))
            or _safe_float(snapshot.get("market_cap_billion_cny"))
            or _safe_float(snapshot.get("marketCapBillion"))
            or _safe_float(snapshot.get("market_cap"))
            or _safe_float(snapshot.get("marketCap"))
        )
        if value and value > 1_000_000:
            value = value / 1_000_000_000
        unit = "CNY_billion" if snapshot.get("market_cap_billion_cny") else "USD_billion"
        if value:
            return float(value), unit, str(record.get("evidence_id") or record.get("sample_id") or "")
    return None, "", ""


def _align_market_denominator(value: float) -> float:
    if abs(value) >= 1_000_000:
        return value / 1_000_000_000
    return value



def _add_minimum_company_report_claims(
    claims: List[ClaimItem],
    records: List[Dict[str, Any]],
    start_index: int,
) -> List[ClaimItem]:
    """Backfill company-report sections with market/industry rules, not symbol rules."""

    output = list(claims)
    claim_index = start_index
    symbol = _first_symbol(records) or _symbol_from_claims(output) or "Company"
    evidence_ids = _fallback_evidence_ids(records)
    if not evidence_ids:
        return output
    profile = _infer_company_analysis_profile(symbol=symbol, records=records, claims=output)

    def add_claim(section: str, text: str, risk: str = "medium", confidence: float = 0.64, notes: str = "") -> None:
        nonlocal claim_index
        output.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name=section,
                claim_text=text,
                evidence_ids=evidence_ids[:3],
                numeric_values={},
                risk_level=risk,
                confidence=confidence,
                notes=notes,
            )
        )
        claim_index += 1

    if not _has_claim_section(output, "executive_summary"):
        add_claim(
            "executive_summary",
            f"{symbol} ??????????????????????????????????????????????????????? evidence_id?citation ? verifier ???",
            confidence=0.7,
            notes="???????????????????",
        )

    if not _has_claim_section(output, "strategy_business"):
        axes = "?".join(profile["business_axes"])
        add_claim(
            "strategy_business",
            f"{symbol} ???????{profile['label']}??????????{axes}????????/??????????????????????????????????????????????????????????",
            confidence=0.66,
            notes="???/?????????????????????",
        )

    if not _has_claim_section(output, "ownership_governance"):
        add_claim(
            "ownership_governance",
            f"{symbol} ????????????????????????????????????????????SEC filing??????????????????????????????????????????",
            confidence=0.6,
            notes="?????????",
        )

    if not _has_claim_section(output, "peer_compare"):
        peer_axes = "?".join(profile["peer_axes"])
        add_claim(
            "peer_compare",
            f"{symbol} ????????{profile['label']}??????????????????????ROE????????????????????????{peer_axes}??????????????????????????????????????????",
            confidence=0.63,
            notes="??????????????????????",
        )

    if not _has_claim_section(output, "valuation"):
        add_claim(
            "valuation",
            "??????????????????????????????????????????????????????? P/E?P/B?P/S?DCF ???????????????????????????????????",
            confidence=0.68,
            notes="?????????????????",
        )

    if not _has_claim_section(output, "valuation_sensitivity"):
        sens_axes = "?".join(profile["sensitivity_axes"])
        add_claim(
            "valuation_sensitivity",
            f"????????{sens_axes}??????????????????????????????????????????????????????????????????",
            confidence=0.63,
            notes="???????????????",
        )

    if not _has_claim_section(output, "risks"):
        add_claim(
            "risks",
            f"{symbol} ??????????????????????????????????????????????????????????????????????",
            risk="high",
            confidence=0.66,
            notes="?????????",
        )

    if not _has_claim_section(output, "conclusion"):
        add_claim(
            "conclusion",
            f"??????????{symbol} ????????????????{profile['growth_driver']}???????{profile['competition_pressure']}?????????????????????????????????????????????????????????",
            confidence=0.66,
            notes="??????????????????????????",
        )

    return output


def _infer_company_analysis_profile(symbol: str, records: List[Dict[str, Any]], claims: List[ClaimItem]) -> Dict[str, Any]:
    text_parts = [symbol]
    for record in records:
        text_parts.extend([
            str(record.get("title") or ""),
            str(record.get("content") or "")[:800],
            str((record.get("metadata") or {}).get("industry") if isinstance(record.get("metadata"), dict) else ""),
            str((record.get("metadata") or {}).get("sector") if isinstance(record.get("metadata"), dict) else ""),
        ])
    text_parts.extend(str(claim.claim_text) for claim in claims[:20])
    text = " ".join(text_parts).lower()

    profiles = [
        (
            "semiconductor",
            ["semiconductor", "chip", "gpu", "cpu", "accelerator", "data center", "ai", "eda", "foundry", "fabless", "???", "??", "??", "????"],
            "???/????",
            ["?????", "????/????", "????", "??????", "????"],
            ["????", "??/????", "??????", "???", "????"],
            ["????", "???", "?????", "????"],
            "?????????/AI ???????",
            "?????????????????????",
        ),
        (
            "internet_platform",
            ["internet", "platform", "online", "cloud", "advertising", "game", "fintech", "???", "??", "??", "??", "?", "??"],
            "?????",
            ["????", "??/??/??????", "?????", "???????", "????"],
            ["????", "ARPU", "????", "?????", "????"],
            ["????", "?????", "?/????", "?????"],
            "????????????/??/??????",
            "???????????????????/????",
        ),
        (
            "consumer",
            ["consumer", "staples", "retail", "beverage", "food", "spirits", "??", "??", "??", "??", "??", "??", "???"],
            "???",
            ["????", "????", "????", "???", "????"],
            ["????", "????", "?????", "???", "????"],
            ["????", "???", "????", "????"],
            "???????????????",
            "???????????????????",
        ),
        (
            "financial",
            ["bank", "insurance", "broker", "asset management", "??", "??", "??", "??", "???"],
            "??",
            ["????", "???/??", "????", "??", "????"],
            ["?????", "???", "????", "ROE", "????"],
            ["???", "???", "?????", "????"],
            "??????????????????",
            "???????????????????",
        ),
    ]
    for category, keywords, label, business_axes, peer_axes, sensitivity_axes, growth, pressure in profiles:
        if any(keyword in text for keyword in keywords):
            return {
                "category": category,
                "label": label,
                "business_axes": business_axes,
                "peer_axes": peer_axes,
                "sensitivity_axes": sensitivity_axes,
                "growth_driver": growth,
                "competition_pressure": pressure,
            }
    return {
        "category": "general",
        "label": "??????",
        "business_axes": ["????", "????", "??/??", "????", "????"],
        "peer_axes": ["????", "????", "?????", "????", "????"],
        "sensitivity_axes": ["????", "???/???", "??????", "???"],
        "growth_driver": "???????????????????",
        "competition_pressure": "?????????????????????",
    }

def _statement_summary_claims(
    rows: Any,
    evidence_ids: List[str],
    start_index: int,
) -> List[ClaimItem]:
    if not isinstance(rows, list) or not rows or not evidence_ids:
        return []
    symbol = str(rows[0].get("symbol") or "Company") if isinstance(rows[0], dict) else "Company"
    period = str(rows[0].get("period") or "") if isinstance(rows[0], dict) else ""
    output: List[ClaimItem] = []
    claim_index = start_index

    income_parts, income_values = _statement_parts(
        rows,
        "income_statement",
        [("revenue", "收入"), ("net_income", "净利润"), ("gross_profit", "毛利")],
    )
    if income_parts:
        output.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="financial_statements",
                claim_text=f"{symbol} {period} 利润表摘要：" + "，".join(income_parts) + "。",
                evidence_ids=evidence_ids,
                numeric_values=income_values,
                risk_level="medium",
                confidence=0.82,
                notes="由标准化三表行生成，必须写入正文三表摘要。",
            )
        )
        claim_index += 1

    balance_parts, balance_values = _statement_parts(
        rows,
        "balance_sheet",
        [("total_assets", "总资产"), ("total_liabilities", "总负债"), ("total_equity", "股东权益"), ("cash_and_equivalents", "现金及等价物")],
    )
    if balance_parts:
        output.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="financial_statements",
                claim_text=f"{symbol} {period} 资产负债表摘要：" + "，".join(balance_parts) + "。",
                evidence_ids=evidence_ids,
                numeric_values=balance_values,
                risk_level="medium",
                confidence=0.82,
                notes="由标准化三表行生成，必须写入正文三表摘要。",
            )
        )
        claim_index += 1

    cash_parts, cash_values = _statement_parts(
        rows,
        "cash_flow_statement",
        [("operating_cash_flow", "经营现金流"), ("free_cash_flow", "自由现金流"), ("capex", "资本开支")],
    )
    if cash_parts:
        text = f"{symbol} {period} 现金流量表摘要：" + "，".join(cash_parts) + "。"
        confidence = 0.82
    else:
        text = (
            f"{symbol} {period} 现金流量表缺口：当前标准化表格尚未取得经营现金流或自由现金流字段，"
            "报告应明确该缺口会限制现金转化率和估值敏感性判断。"
        )
        confidence = 0.62
    output.append(
        ClaimItem(
            claim_id=f"cl_{claim_index:04d}",
            section_name="financial_statements",
            claim_text=text,
            evidence_ids=evidence_ids,
            numeric_values=cash_values,
            risk_level="medium",
            confidence=confidence,
            notes="现金流量表摘要或缺口说明，必须写入正文三表摘要。",
        )
    )
    return output


def _statement_parts(rows: List[Dict[str, Any]], statement: str, line_items: List[tuple[str, str]]) -> tuple[List[str], Dict[str, float]]:
    parts: List[str] = []
    values: Dict[str, float] = {}
    for line_item, label in line_items:
        value = _statement_value(rows, statement, line_item)
        if _has_number(value):
            values[line_item] = float(value)
            parts.append(f"{label}约为 {_format_statement_number(float(value))}")
    return parts, values


def _format_statement_number(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    return f"{value:.2f}"


def _has_claim_section(claims: List[ClaimItem], section_name: str) -> bool:
    return any(str(claim.section_name or "") == section_name and str(claim.claim_text or "").strip() for claim in claims)


def _claims_text_contains(claims: List[ClaimItem], terms: List[str]) -> bool:
    text = "\n".join(str(claim.claim_text or "") for claim in claims)
    return all(term in text for term in terms)


def _fallback_evidence_ids(records: List[Dict[str, Any]]) -> List[str]:
    preferred = [
        "sec_companyfacts",
        "eastmoney_financials",
        "pdf_section",
        "company_profile",
        "filing",
        "market",
        "market_api",
    ]
    output: List[str] = []
    for source_type in preferred:
        for record in records:
            if str(record.get("source_type") or "") != source_type:
                continue
            evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "").strip()
            if evidence_id and evidence_id not in output:
                output.append(evidence_id)
    if output:
        return output
    for record in records:
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "").strip()
        if evidence_id and evidence_id not in output:
            output.append(evidence_id)
    return output


def _symbol_from_claims(claims: List[ClaimItem]) -> str:
    for claim in claims:
        match = re.search(r"\b[A-Z]{1,6}(?:\.[A-Z]{1,3})?\b", str(claim.claim_text or ""))
        if match:
            return match.group(0)
    return ""


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
        if expected_period and _is_period_sensitive_section(claim.section_name):
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


def _filter_supported_llm_claims(claims: List[ClaimItem], records: List[Dict[str, Any]]) -> List[ClaimItem]:
    evidence_numbers = _numbers_by_evidence_id(records)
    filtered: List[ClaimItem] = []
    for claim in claims:
        supported_numbers = list(claim.numeric_values.values())
        for evidence_id in claim.evidence_ids:
            supported_numbers.extend(evidence_numbers.get(str(evidence_id), []))
        unsupported = [
            number
            for number in _numbers_from_text(claim.claim_text)
            if not _number_is_noise(number) and not _number_is_supported(number, supported_numbers)
        ]
        if unsupported:
            continue
        filtered.append(claim)
    return filtered


def _numbers_by_evidence_id(records: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    output: Dict[str, List[float]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        if not evidence_id:
            continue
        numbers = _numbers_from_text(str(record.get("content", "")))
        numbers.extend(_numbers_from_json(record.get("metadata", {})))
        output[evidence_id] = numbers
    return output


def _numbers_from_text(text: str) -> List[float]:
    values = []
    for match in re.findall(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            values.append(float(match))
        except ValueError:
            continue
    return values


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


def _number_is_noise(value: float) -> bool:
    return value in {0.0, 1.0} or 1900 <= value <= 2100


def _number_is_supported(value: float, supported_numbers: List[float]) -> bool:
    for candidate in supported_numbers:
        tolerance = max(0.05, abs(candidate) * 0.002)
        if abs(value - candidate) <= tolerance:
            return True
    return False


def _sec_metric(metrics: Dict[str, Any], name: str) -> Dict[str, Any]:
    item = metrics.get(name)
    if not isinstance(item, dict):
        return {}
    try:
        value = float(item.get("value"))
    except (TypeError, ValueError):
        return {}
    output = dict(item)
    output["value"] = value
    return output


def _format_sec_value(metric: Dict[str, Any]) -> str:
    value = float(metric.get("value", 0.0) or 0.0)
    unit = str(metric.get("unit") or "")
    return _format_financial_amount(value, unit)


def _format_financial_amount(value: float, unit: str = "") -> str:
    unit_key = str(unit or "").upper()
    if unit_key in {"CNY", "RMB", "人民币", "元"}:
        return f"{float(value) / 100_000_000:.2f}亿元"
    if unit_key in {"USD", "US$"}:
        if abs(value) >= 1_000_000_000:
            return f"{float(value) / 1_000_000_000:.2f} billion USD"
        if abs(value) >= 1_000_000:
            return f"{float(value) / 1_000_000:.2f} million USD"
        return f"{float(value):,.2f} USD"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} billion {unit}".strip()
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f} million {unit}".strip()
    return f"{value:,.2f} {unit}".strip()


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
    return str(section_name or "").strip().lower() in {
        "business_overview",
        "financial_analysis",
        "financial_statements",
        "ownership_governance",
        "strategy_business",
    }


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
        re.compile(r"(\d{4})\s*年\s*(第[一二三四1-4]|一|二|三|四)\s*季度"),
        re.compile(r"(\d{4})\s*年\s*年度报告"),
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
            if pattern is patterns[3]:
                mentions.append((match.group(1), _chinese_quarter(match.group(2))))
            elif pattern is patterns[4]:
                mentions.append((match.group(1), "Q4"))
            else:
                mentions.append((match.group(2), quarter_map.get(match.group(1).lower(), "")))

    deduped: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for year, quarter in mentions:
        key = (year, quarter)
        if quarter and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def _chinese_quarter(value: str) -> str:
    text = str(value or "")
    mapping = {"第一": "Q1", "一": "Q1", "1": "Q1", "第二": "Q2", "二": "Q2", "2": "Q2", "第三": "Q3", "三": "Q3", "3": "Q3", "第四": "Q4", "四": "Q4", "4": "Q4"}
    return mapping.get(text.replace("第", ""), mapping.get(text, ""))


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


def _first_number(row: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = row.get(key)
        if value in {None, ""}:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


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


def _build_pdf_section_claims(records: List[Dict[str, Any]], start_index: int, expected_period: str = "") -> tuple[List[ClaimItem], int]:
    claims: List[ClaimItem] = []
    claim_index = start_index
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        if str(record.get("source_type") or "") != "pdf_section":
            continue
        if expected_period and _record_mentions_other_period(record, expected_period):
            continue
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        section_type = str(metadata.get("section_type") or "")
        if section_type:
            buckets.setdefault(section_type, []).append(record)

    specs = [
        ("business_overview", "strategy_business", "年报/公告 PDF 抽取的主营业务与业务结构片段显示：{snippet}"),
        ("management_discussion", "strategy_business", "管理层讨论与经营情况 PDF 片段显示：{snippet}"),
        ("ownership_governance", "ownership_governance", "股东结构、治理或管理层 PDF 片段显示：{snippet}"),
        ("risk_factors", "risks", "风险提示 PDF 片段显示：{snippet}"),
        ("financial_statements", "financial_statements", "财务报表 PDF 片段显示：{snippet}"),
    ]
    for section_type, section_name, template in specs:
        rows = buckets.get(section_type, [])
        if not rows:
            continue
        snippets = [_compact_snippet(str(row.get("content") or ""), limit=220) for row in rows[:2]]
        snippets = [item for item in snippets if item]
        evidence_ids = [str(row.get("evidence_id") or row.get("sample_id") or "") for row in rows[:2]]
        evidence_ids = [item for item in evidence_ids if item]
        if not snippets or not evidence_ids:
            continue
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name=section_name,
                claim_text=template.format(snippet="；".join(snippets)),
                evidence_ids=evidence_ids,
                numeric_values={},
                risk_level="medium" if section_type == "risk_factors" else "low",
                confidence=0.73,
                notes="由 PDF section artifact 转换为 claim；仍保留原始 section/evidence_id 供审计。",
            )
        )
        claim_index += 1
    for claim in _build_generic_pdf_insight_claims(buckets=buckets, start_index=claim_index):
        claims.append(claim)
        claim_index += 1
    return claims, claim_index



def _build_generic_pdf_insight_claims(buckets: Dict[str, List[Dict[str, Any]]], start_index: int) -> List[ClaimItem]:
    """Create generic PDF-derived insights without company-specific templates."""

    output: List[ClaimItem] = []
    claim_index = start_index
    specs = [
        (
            "strategy_business",
            buckets.get("business_overview", []),
            ["product", "segment", "revenue", "channel", "customer", "region", "??", "??", "??", "??", "??", "??", "??", "??"],
            "PDF ??????????????/?????????????????????????????????????????????????",
        ),
        (
            "ownership_governance",
            buckets.get("ownership_governance", []),
            ["shareholder", "board", "governance", "dividend", "repurchase", "??", "??", "??", "??", "??", "??"],
            "PDF ??????????????????????????????????????????????????",
        ),
        (
            "risks",
            buckets.get("risk_factors", []),
            ["risk", "uncertain", "competition", "demand", "price", "??", "???", "??", "??", "??", "??"],
            "PDF ???????????????????????????????????????????????",
        ),
    ]
    for section_name, rows, keywords, prefix in specs:
        row = _first_row_with_terms(rows, keywords)
        if not row:
            continue
        evidence_id = str(row.get("evidence_id") or row.get("sample_id") or "")
        content = str(row.get("content") or "")
        output.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name=section_name,
                claim_text=f"{prefix} ?????{_compact_snippet(content, 220)}",
                evidence_ids=[evidence_id] if evidence_id else [],
                numeric_values={},
                risk_level="high" if section_name == "risks" else "medium",
                confidence=0.72,
                notes="?? PDF insight?? section type ????????????????",
            )
        )
        claim_index += 1
    return output

def _first_row_with_terms(rows: List[Dict[str, Any]], terms: List[str]) -> Dict[str, Any] | None:
    for row in rows:
        text = str(row.get("content") or "")
        if all(term in text for term in terms):
            return row
    for row in rows:
        text = str(row.get("content") or "")
        if any(term in text for term in terms):
            return row
    return None


def _compact_snippet(text: str, limit: int = 220) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def _financial_evidence_ids(records: List[Dict[str, Any]]) -> List[str]:
    return _source_evidence_ids(records, {"financials", "eastmoney_financials", "sec_companyfacts", "pdf_section"})


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
                value = row.get("value_billion", row.get("value"))
                return float(value)
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
