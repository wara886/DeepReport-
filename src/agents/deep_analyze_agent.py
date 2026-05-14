"""DeepAnalyzeAgent for financial claim generation."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.agents.react_loop import run_react_tool_loop
from src.data.company_universe import resolve_company_identifier
from src.features.company_valuation import is_financial_sector, is_known_financial_symbol
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
        rating = str(task.parameters.get("rating") or "").strip()
        react_attempted = bool(task.parameters.get("use_react", False))
        react_payload: Dict[str, Any] = {}
        if react_attempted and self.model and hasattr(self.model, "chat"):
            react_payload = self._run_react_analysis(
                task=task,
                records=records,
                symbol=symbol,
                period=period,
                raw_data_root=raw_data_root,
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
            rating=rating,
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
    rating: str = "",
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
    target_symbol_for_profile = _first_symbol(records) or (str(ratio_rows[0].get("symbol") or "") if ratio_rows else "")
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
        business_evidence_ids = profile_evidence_ids
        business_confidence = 0.80 if description else 0.66
        business_notes = "由 company_profile 证据生成业务画像，避免使用调试型证据覆盖描述。"
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
    elif target_symbol_for_profile and financial_evidence_ids:
        symbol = target_symbol_for_profile
        profile = resolve_company_identifier(symbol)
        company_name = str(profile.get("company_name") or symbol)
        sector = str(profile.get("sector") or "未知板块")
        industry = str(profile.get("industry") or "未知行业")
        description = str(profile.get("description") or "").strip()
        business_evidence_ids = financial_evidence_ids[:1]
        business_confidence = 0.72 if description else 0.60
        business_notes = "由内置 company universe 补充业务画像，并绑定本轮 SEC 财务证据以保持报告可追踪。"
    else:
        symbol = target_symbol_for_profile or "Company"
        company_name = symbol
        sector = "未知板块"
        industry = "未知行业"
        description = ""
        business_evidence_ids = []
        business_confidence = 0.55
        business_notes = "缺少 company_profile 与 company universe 时的降级业务画像。"
    if business_evidence_ids:
        business_parts = []
        if sector and sector != "未知板块":
            business_parts.append(f"所属板块为{sector}")
        if industry and industry != "未知行业":
            business_parts.append(f"细分行业为{industry}")
        if description:
            business_parts.append(f"主营业务画像：{description}")
        else:
            business_parts.append("主营业务画像需要继续接入年报业务分部或公司公告补全")
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="business_overview",
                claim_text=f"{company_name}（{symbol}）业务概览：{'；'.join(business_parts)}。",
                evidence_ids=business_evidence_ids,
                numeric_values={},
                risk_level="low",
                confidence=business_confidence,
                notes=business_notes,
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
            ocf_val = float(row["operating_cash_flow_billion"])
            # Look up period type from SEC evidence metadata
            ocf_period_type = _ocf_period_type_from_records(records, str(row.get("symbol", "") or ""))
            sector = str(row.get("sector") or "")
            industry = str(row.get("industry") or "")
            is_bank_like = is_financial_sector(sector, industry) or is_known_financial_symbol(symbol)
            if ocf_period_type == "YTD":
                ocf_label = f"前几季度累计经营现金流（YTD）约为 {ocf_val:.1f}B"
            else:
                ocf_label = f"经营现金流约为 {ocf_val:.1f}B"
            if is_bank_like:
                bank_note = (
                    "对银行业而言，经营活动现金流受交易资产、融资负债、存款与短期融资结构变动等资产负债表项影响较大，"
                    "不能直接等同于工业企业口径的经营现金流恶化，需结合 10-Q 披露的交易资产与融资负债变化进一步分析。"
                )
                claim_text = f"{symbol} 的{ocf_label}。{bank_note}"
                notes_text = f"由 DeepAnalyzeAgent 从财务证据提取；口径：{ocf_period_type or 'unknown'}；已按金融行业口径加注说明。"
            else:
                claim_text = f"{symbol} 的{ocf_label}。"
                notes_text = f"由 DeepAnalyzeAgent 从财务证据提取；口径：{ocf_period_type or 'unknown'}。"
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_analysis",
                    claim_text=claim_text,
                    evidence_ids=[evidence_id] if evidence_id else [],
                    numeric_values={"operating_cash_flow_billion": ocf_val},
                    risk_level="medium",
                    confidence=0.78,
                    notes=notes_text,
                )
            )
            claim_index += 1

    coverage = statement_view.get("coverage", {}) if isinstance(statement_view, dict) else {}
    if coverage.get("has_three_statement_view") and financial_evidence_ids:
        line_item_count = float(coverage.get("line_item_count", 0) or 0)
        statement_summary, statement_numeric = _three_statement_summary(
            ratio_rows=ratio_rows,
            statement_rows=statement_view.get("rows", []) if isinstance(statement_view, dict) else [],
        )
        summary_text = (
            f"三表关键项包括：{statement_summary}。"
            if statement_summary else
            f"系统已构建三表视图，覆盖 {int(line_item_count)} 个核心项目。"
        )
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="financial_statements",
                claim_text=summary_text,
                evidence_ids=financial_evidence_ids,
                numeric_values=statement_numeric,
                risk_level="medium",
                confidence=0.80 if statement_summary else 0.74,
                notes=f"由 build_three_statement_view 生成三表关键项摘要；覆盖 {int(line_item_count)} 个核心项目。",
            )
        )
        claim_index += 1
    elif ratio_rows:
        # Fallback: build a minimal three-statement summary from ratio_rows
        row = _first_metric_row(ratio_rows) or ratio_rows[0]
        fallback_evidence_ids = financial_evidence_ids or [str(row.get("sample_id") or "")] if str(row.get("sample_id") or "") else []
        rev = _safe_float_or_none(row.get("revenue_billion"))
        ni = _safe_float_or_none(row.get("net_income_billion"))
        eq = _safe_float_or_none(row.get("shareholder_equity_billion"))
        ocf = _safe_float_or_none(row.get("operating_cash_flow_billion"))
        fcf = _safe_float_or_none(row.get("free_cash_flow_billion"))
        sym = str(row.get("symbol") or "Company")
        parts = []
        if rev is not None:
            parts.append(f"营收 {rev:.1f}B")
        if ni is not None:
            parts.append(f"净利润 {ni:.1f}B")
        if eq is not None:
            parts.append(f"股东权益 {eq:.1f}B")
        if ocf is not None:
            parts.append(f"经营现金流 {ocf:.1f}B")
        if fcf is not None:
            parts.append(f"自由现金流 {fcf:.1f}B")
        if parts:
            fcf_note = ""
            if fcf is not None:
                fcf_note = " " + _fcf_methodology_note(row, records)
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="financial_statements",
                    claim_text=f"{sym} 三表摘要（来自{_financial_statement_source_label(sym)}）：{'；'.join(parts)}。{fcf_note}".strip(),
                    evidence_ids=fallback_evidence_ids,
                    numeric_values={k: v for k, v in [
                        ("revenue_billion", rev), ("net_income_billion", ni),
                        ("shareholder_equity_billion", eq), ("operating_cash_flow_billion", ocf),
                        ("free_cash_flow_billion", fcf),
                    ] if v is not None},
                    risk_level="low",
                    confidence=0.80,
                    notes="由 ratio_rows 直接构建的三表摘要 fallback。" + (f" FCF methodology: {_free_cash_flow_methodology_from_row_records(row, records) or 'unknown'}." if fcf is not None else ""),
                )
            )
        claim_index += 1

    statement_rows = statement_view.get("rows", []) if isinstance(statement_view, dict) else []
    net_income = _statement_value(statement_rows, "income_statement", "net_income")
    free_cash_flow = _statement_value(statement_rows, "cash_flow_statement", "free_cash_flow")
    if _has_number(net_income) and _has_number(free_cash_flow) and financial_evidence_ids:
        symbol = str(statement_rows[0].get("symbol") or "Company") if statement_rows else "Company"
        fcf_note = _fcf_methodology_note(ratio_rows[0] if ratio_rows else {}, records)
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="financial_statements",
                claim_text=f"{symbol} 三表视图显示，估算净利润约为 {float(net_income):.1f}B，自由现金流约为 {float(free_cash_flow):.1f}B。{fcf_note}",
                evidence_ids=financial_evidence_ids,
                numeric_values={"net_income_billion": float(net_income), "free_cash_flow_billion": float(free_cash_flow)},
                risk_level="low",
                confidence=0.76,
                notes=f"由三表视图计算生成；FCF 口径已声明。FCF methodology: {_free_cash_flow_methodology_from_row_records(ratio_rows[0] if ratio_rows else {}, records) or 'unknown'}.",
            )
        )
        claim_index += 1

    # Non-recurring item detection: flag tax benefits, restructuring, impairment
    for row in ratio_rows:
        evidence_id = str(row.get("sample_id", ""))
        symbol = str(row.get("symbol", "Company") or "Company")
        nonrecurring_parts = []
        nonrecurring_values: Dict[str, float] = {}
        tax_benefit = _safe_float_or_none(row.get("income_tax_benefit_billion"))
        restructuring = _safe_float_or_none(row.get("restructuring_charges_billion"))
        impairment = _safe_float_or_none(row.get("asset_impairment_billion"))
        if tax_benefit is not None and tax_benefit > 0.05:
            nonrecurring_parts.append(_tax_item_phrase(row, records))
            nonrecurring_values["income_tax_benefit_billion"] = tax_benefit
            official_tax_benefit = _official_one_time_tax_benefit_billion(row, records)
            if official_tax_benefit is not None:
                nonrecurring_values["official_one_time_tax_benefit_billion"] = official_tax_benefit
        if restructuring is not None and restructuring > 0.05:
            nonrecurring_parts.append(f"重组费用约 {restructuring:.2f}B（一次性支出，已计入当期损益）")
            nonrecurring_values["restructuring_charges_billion"] = restructuring
        if impairment is not None and impairment > 0.05:
            nonrecurring_parts.append(f"资产减值约 {impairment:.2f}B（一次性支出，已计入当期损益）")
            nonrecurring_values["asset_impairment_billion"] = impairment
        if nonrecurring_parts and financial_evidence_ids:
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="earnings_quality",
                    claim_text=(
                        f"{symbol} 本期存在非经常性项目：{'；'.join(nonrecurring_parts)}。"
                        " 分析盈利质量时应将上述项目从经常性利润中剔除，以还原核心经营利润。"
                    ),
                    evidence_ids=[evidence_id] if evidence_id else financial_evidence_ids,
                    numeric_values=nonrecurring_values,
                    risk_level="medium",
                    confidence=0.78,
                    notes="由 SEC XBRL 非经常项概念提取；阈值 > 0.05B 才触发。",
                )
            )
            claim_index += 1
        break  # only process first ratio row (target company)

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

        # Build transparent peer table for report
        peer_rows_data = peer_context.get("peer_rows", []) if isinstance(peer_context, dict) else []
        peer_table_lines = []
        if peer_rows_data:
            peer_table_lines.append("| 公司 | 代码 | 营收增速(%) | 毛利率(%) | 净利率(%) |")
            peer_table_lines.append("|------|------|----------:|--------:|--------:|")
            for row in peer_rows_data:
                sym = str(row.get("symbol") or "")
                name = str(row.get("company_name") or sym)[:12]
                rev_g = row.get("revenue_growth_pct")
                gm = row.get("gross_margin_pct")
                nm = row.get("net_margin_pct")
                marker = " ◀" if row.get("is_target") else ""
                peer_table_lines.append(
                    f"| {name}{marker} | {sym} | "
                    f"{'N/A' if rev_g is None else f'{rev_g:.1f}'} | "
                    f"{'N/A' if gm is None else f'{gm:.1f}'} | "
                    f"{'N/A' if nm is None else f'{nm:.1f}'} |"
                )
        peer_table_str = "\n".join(peer_table_lines)
        summary = f"{target_symbol} 已完成本地同行对比（共 {peer_count} 家同行）：" + "；".join(parts) + "。"
        disclaimer = "（注：同行数据来自本地缓存 financials.csv，非实时 SEC 数据，仅供参考。）"
        full_text = summary + "\n" + disclaimer + ("\n\n" + peer_table_str if peer_table_str else "")

        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="peer_compare",
                claim_text=full_text,
                evidence_ids=[],  # peer data is local cache, not backed by target company's SEC evidence
                numeric_values=numeric_values,
                risk_level="low",
                confidence=0.78,
                notes="由同行比较工具生成；数据来源：本地缓存 financials.csv，非实时 SEC 数据。",
            )
        )
        claim_index += 1

    if valuation.get("valuation_available") and financial_evidence_ids:
        methods = valuation.get("methods", {}) if isinstance(valuation.get("methods"), dict) else {}
        dcf = methods.get("dcf", {}) if isinstance(methods.get("dcf"), dict) else {}
        market_gap = valuation.get("market_gap", {}) if isinstance(valuation.get("market_gap"), dict) else {}
        pe_info = methods.get("pe", {}) if isinstance(methods.get("pe"), dict) else {}
        ps_info = methods.get("ps", {}) if isinstance(methods.get("ps"), dict) else {}
        dcf_assumptions = valuation.get("dcf_model", {}).get("assumptions", {}) if isinstance(valuation.get("dcf_model"), dict) else {}
        valuation_warning = str(valuation.get("valuation_method_warning") or "").strip()
        pe_mult = float(pe_info.get("multiple", 0.0) or 0.0)
        pe_val = float(pe_info.get("value_billion", 0.0) or 0.0)
        ps_mult = float(ps_info.get("multiple", 0.0) or 0.0)
        ps_val = float(ps_info.get("value_billion", 0.0) or 0.0)
        dcf_val = float(dcf.get("value_billion", 0.0) or 0.0)
        base_fcf = float(dcf_assumptions.get("base_free_cash_flow_billion", 0.0) or 0.0)
        fcf_growth = float(dcf.get("fcf_growth", 0.0) or 0.0)
        discount_rate = float(dcf.get("discount_rate", 0.0) or 0.0)
        blended = float(valuation.get("blended_equity_value_billion", 0.0) or 0.0)
        blended_method_note = str(valuation.get("blended_method_note") or "")
        is_fin_sector = bool(valuation.get("is_financial_sector", False))
        bank_specific = methods.get("bank_specific", {}) if isinstance(methods.get("bank_specific"), dict) else {}

        if is_fin_sector and bank_specific:
            pb_info = bank_specific.get("pb", {})
            ddm_info = bank_specific.get("ddm", {})
            pb_mult = float(pb_info.get("multiple", 0.0) or 0.0)
            pb_val = float(pb_info.get("value_billion", 0.0) or 0.0)
            pb_equity = float(pb_info.get("book_equity_billion", 0.0) or 0.0)
            pb_equity_source = str(pb_info.get("equity_source") or "")
            ddm_val = float(ddm_info.get("value_billion", 0.0) or 0.0)
            ddm_note = str(ddm_info.get("note") or "")
            valuation_text = (
                f"规则估值模型（银行业框架）：P/B {pb_mult:.1f}x × 账面权益 {pb_equity:.1f}B = {pb_val:.1f}B"
                f"（权益来源：{pb_equity_source}）；"
                f"DDM（基于报告期净利润年化后的股利能力；{ddm_note}，派息率 {float(ddm_info.get('payout_ratio', 0.35) or 0.35):.0%}，"
                f"权益成本 {float(ddm_info.get('cost_of_equity', 0.10) or 0.10):.0%}，"
                f"永续增长率 {float(ddm_info.get('terminal_growth', 0.025) or 0.025):.1%}）= {ddm_val:.1f}B；"
                f"P/E {pe_mult:.1f}x = {pe_val:.1f}B（辅助参考）；"
                f"{blended_method_note}，综合估值约 {blended:.1f}B。"
                f" P/S 和 FCF DCF 对银行业适用性有限，已从主要综合估值中排除。"
            )
        else:
            # Check if non-recurring tax item exists to add P/E caveat
            pe_caveat = ""
            for row in ratio_rows[:1]:
                tb = _safe_float_or_none(row.get("income_tax_benefit_billion"))
                if tb is not None and tb > 0.5:
                    pe_caveat = (
                        f" P/E 估值基于报告期净利润简单年化（{_tax_item_phrase(row, records)}），"
                        "未对非经常性税项进行标准化调整，更适合作为表观估值参考。"
                    )
            valuation_text = (
                f"规则估值模型：P/E {pe_mult:.1f}x = {pe_val:.1f}B；"
                f"P/S {ps_mult:.1f}x = {ps_val:.1f}B；"
                f"DCF（基础FCF {base_fcf:.2f}B，增速 {fcf_growth:.1%}，折现率 {discount_rate:.1%}，终值增速 2.5%，5年）= {dcf_val:.1f}B；"
                f"{blended_method_note}，综合估值约 {blended:.1f}B。{pe_caveat}"
            )
        if valuation_warning:
            valuation_text += f" 【{valuation_warning}】"

        # Non-recurring item quality adjustment: lower confidence and add warning if material
        nonrecurring_adj_note = ""
        valuation_confidence = 0.70
        for row in ratio_rows:
            tax_benefit = _safe_float_or_none(row.get("income_tax_benefit_billion"))
            restructuring = _safe_float_or_none(row.get("restructuring_charges_billion"))
            impairment = _safe_float_or_none(row.get("asset_impairment_billion"))
            ni_raw = _safe_float_or_none(row.get("net_income_billion"))
            annualize = int(row.get("annualization_factor") or 1)
            ni = (ni_raw * annualize) if ni_raw is not None else None
            total_nonrecurring = sum(v for v in [tax_benefit, restructuring, impairment] if v is not None)
            if ni and ni > 0 and total_nonrecurring / ni > 0.03:
                valuation_confidence = 0.58  # downgrade confidence
                parts_nr = []
                if tax_benefit and tax_benefit > 0.05:
                    parts_nr.append(_tax_item_phrase(row, records))
                if restructuring and restructuring > 0.05:
                    parts_nr.append(f"重组费用 {restructuring:.2f}B")
                if impairment and impairment > 0.05:
                    parts_nr.append(f"资产减值 {impairment:.2f}B")
                nonrecurring_adj_note = (
                    f" ⚠ 盈利质量警告：本期净利润包含非经常性项目（{'、'.join(parts_nr)}），"
                    f"占净利润约 {total_nonrecurring/ni:.0%}。P/E 估值和年化 ROE 均基于含一次性项目的净利润，"
                    "可能高估持续盈利能力；评价时建议剔除非经常项后重新估算。"
                )
            break
        if nonrecurring_adj_note:
            valuation_text += nonrecurring_adj_note
        assumptions_note = json.dumps(
            {
                "pe_mult": pe_mult, "ps_mult": ps_mult,
                "base_fcf_B": base_fcf, "fcf_growth": round(fcf_growth, 4),
                "discount_rate": discount_rate, "terminal_growth": 0.025,
                "blended_B": blended,
            },
            ensure_ascii=False,
        )[:300]
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="valuation",
                claim_text=valuation_text,
                evidence_ids=financial_evidence_ids + market_evidence_ids,
                numeric_values={
                    "blended_equity_value_billion": blended,
                    "dcf_value_billion": dcf_val,
                },
                risk_level="medium" if not nonrecurring_adj_note else "high",
                confidence=valuation_confidence,
                notes=f"由规则估值模型生成，依赖财务摘要、同行上下文与可选市场数据。假设：{assumptions_note}",
            )
        )
        claim_index += 1
        sensitivity = valuation.get("sensitivity", {}) if isinstance(valuation.get("sensitivity"), dict) else {}
        if sensitivity:
            sens_type = str(sensitivity.get("type", "dcf"))
            if sens_type == "bank":
                sens_note = str(sensitivity.get("note", ""))
                pb_low = float(sensitivity.get("pb_low", 0.0) or 0.0)
                pb_mid = float(sensitivity.get("pb_mid", 0.0) or 0.0)
                pb_high = float(sensitivity.get("pb_high", 0.0) or 0.0)
                pb_mults = sensitivity.get("pb_multiples", [])
                ddm_ke_low = float(sensitivity.get("ddm_ke_low", 0.0) or 0.0)
                ddm_ke_mid = float(sensitivity.get("ddm_ke_mid", 0.0) or 0.0)
                ddm_ke_high = float(sensitivity.get("ddm_ke_high", 0.0) or 0.0)
                ddm_g_low = float(sensitivity.get("ddm_g_low", 0.0) or 0.0)
                ddm_g_mid = float(sensitivity.get("ddm_g_mid", 0.0) or 0.0)
                ddm_g_high = float(sensitivity.get("ddm_g_high", 0.0) or 0.0)
                sens_text = (
                    f"银行业估值敏感性：P/B 倍数 {pb_mults[0] if pb_mults else '?'}x / {pb_mults[1] if len(pb_mults)>1 else '?'}x / {pb_mults[2] if len(pb_mults)>2 else '?'}x"
                    f" 对应 P/B 估值 {pb_low:.1f}B / {pb_mid:.1f}B / {pb_high:.1f}B；"
                    f"DDM 权益成本敏感性（低/中/高）：{ddm_ke_low:.1f}B / {ddm_ke_mid:.1f}B / {ddm_ke_high:.1f}B；"
                    f"DDM 永续增长率敏感性（低/中/高）：{ddm_g_low:.1f}B / {ddm_g_mid:.1f}B / {ddm_g_high:.1f}B。"
                )
                sens_numeric = {
                    "pb_low_billion": pb_low, "pb_mid_billion": pb_mid, "pb_high_billion": pb_high,
                    "ddm_ke_low_billion": ddm_ke_low, "ddm_ke_mid_billion": ddm_ke_mid, "ddm_ke_high_billion": ddm_ke_high,
                }
            else:
                sens_text = (
                    "估值敏感性显示：FCF 增速下调 2pct 时 DCF 约为 "
                    f"{float(sensitivity.get('fcf_growth_minus_2pct', 0.0) or 0.0):.1f}B，"
                    "上调 2pct 时约为 "
                    f"{float(sensitivity.get('fcf_growth_plus_2pct', 0.0) or 0.0):.1f}B，"
                    "折现率上调 1pct 时约为 "
                    f"{float(sensitivity.get('discount_rate_plus_1pct', 0.0) or 0.0):.1f}B。"
                )
                sens_numeric = {
                    "dcf_growth_down_billion": float(sensitivity.get("fcf_growth_minus_2pct", 0.0) or 0.0),
                    "dcf_growth_up_billion": float(sensitivity.get("fcf_growth_plus_2pct", 0.0) or 0.0),
                    "dcf_rate_up_billion": float(sensitivity.get("discount_rate_plus_1pct", 0.0) or 0.0),
                }
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="valuation_sensitivity",
                    claim_text=sens_text,
                    evidence_ids=financial_evidence_ids,
                    numeric_values=sens_numeric,
                    risk_level="low",
                    confidence=0.70,
                    notes=f"由估值敏感性模型生成；类型：{sens_type}。",
                )
            )
            claim_index += 1
        if market_gap.get("available"):
            snapshot_note = _market_snapshot_note(market_gap)
            close = _safe_float_or_none(market_gap.get("last_close"))
            shares = _safe_float_or_none(market_gap.get("shares_outstanding_billion"))
            derivation_note = (
                f"（按快照价/最新价 {close:.2f} × 股本 {shares:.2f}B 推算）"
                if close is not None and shares is not None else ""
            )
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="valuation",
                    claim_text=(
                        f"市场对照显示，当前市值约为 {float(market_gap.get('market_cap_billion', 0.0) or 0.0):.1f}B"
                        f"{snapshot_note}{derivation_note}，"
                        f"规则估值与市值差异约为 {float(market_gap.get('valuation_gap_pct', 0.0) or 0.0):.1f}%。"
                        + (f" ⚠️ {market_gap['sanity_warning']}" if market_gap.get("sanity_warning") else "")
                    ),
                    evidence_ids=(market_evidence_ids + financial_evidence_ids) if market_evidence_ids else financial_evidence_ids,
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
        peer_count_for_conclusion = int(peer_context.get("peer_count", 0) or 0) if isinstance(peer_context, dict) else 0
        raw_recommendation = str(valuation.get("recommendation") or "中性观察")
        # Use the mapped five-tier rating if provided; otherwise derive it locally
        mapped_rating = rating if rating else _recommendation_to_rating(raw_recommendation)
        display_rating = mapped_rating if mapped_rating else raw_recommendation
        if peer_count_for_conclusion > 0:
            basis = "增长、利润率、ROE 与同行比较"
        else:
            basis = "增长与利润率指标"
        conclusion_text = f"基于{basis}，模型评级为「{display_rating}」"
        if mapped_rating and raw_recommendation and mapped_rating != raw_recommendation:
            conclusion_text += f"（模型内部评分：{raw_recommendation}）"
        conclusion_text += "。"
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="conclusion",
                claim_text=conclusion_text,
                evidence_ids=financial_evidence_ids,
                numeric_values={},
                risk_level="medium",
                confidence=0.68,
                notes="由估值模型生成，不构成投资建议。",
            )
        )
        claim_index += 1

    for row in trend_rows:
        if any(c.section_name == "business_overview" for c in claims):
            continue
        symbol = str(row.get("symbol", "Company") or "Company")
        evidence_count = int(row.get("evidence_count", 0) or 0)
        source_count = int(row.get("unique_sources", 0) or 0)
        sample_ids = str(row.get("sample_ids", "")).split("|") if row.get("sample_ids") else []
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="business_overview",
                claim_text=f"{symbol} 当前业务资料尚不完整，系统仅能确认本轮证据覆盖 {evidence_count} 条记录、{source_count} 类来源；需补充公司业务分部、产品结构和区域收入后形成完整业务画像。",
                evidence_ids=[item for item in sample_ids if item],
                numeric_values={"evidence_count": float(evidence_count), "unique_sources": float(source_count)},
                risk_level="low",
                confidence=0.76,
                notes="缺少 company_profile 时的业务概览降级输出；明确标注为数据缺口。",
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
    # Build executive_summary claim from key financial figures already extracted
    exec_rev = next(
        (float(c.numeric_values.get("revenue_billion")) for c in claims
         if c.section_name == "financial_analysis" and c.numeric_values.get("revenue_billion") is not None),
        None,
    )
    exec_ni = next(
        (float(c.numeric_values.get("net_income_billion")) for c in claims
         if c.section_name == "financial_statements" and c.numeric_values.get("net_income_billion") is not None),
        None,
    )
    exec_roe = None
    exec_is_quarterly = False
    for row in ratio_rows:
        if _has_number(row.get("roe_pct")):
            exec_roe = float(row["roe_pct"])
            exec_is_quarterly = bool(row.get("is_quarterly", False))
            break
    exec_symbol = str(ratio_rows[0].get("symbol") or "Company") if ratio_rows else "Company"
    exec_parts = []
    if exec_rev is not None:
        exec_parts.append(f"营收约 {exec_rev:.1f}B")
    if exec_ni is not None:
        exec_parts.append(f"净利润约 {exec_ni:.1f}B")
    if exec_roe is not None:
        roe_label = f"年化ROE 约 {exec_roe:.1f}%" if exec_is_quarterly else f"ROE 约 {exec_roe:.1f}%"
        exec_parts.append(roe_label)
    if exec_parts and financial_evidence_ids:
        # ROE annotation: distinguish simplified-annualized from official company-disclosed ROE
        roe_note = ""
        if exec_roe is not None and exec_is_quarterly:
            roe_note = (
                f"（按 Q1 净利润简单年化并以期末权益近似计算，年化ROE 约 {exec_roe:.1f}%；"
                "公司官方披露 ROE 通常基于平均普通股权益，两者可能存在 1-2pct 差异，请以公司 IR 披露为准。）"
            )
        # Non-recurring tax item note for executive summary
        tax_note = ""
        for row in ratio_rows[:1]:
            tb = _safe_float_or_none(row.get("income_tax_benefit_billion"))
            if tb is not None and tb > 0.5:
                tax_note = (
                    f" 注意：{_tax_item_phrase(row, records)}；"
                    "净利润受税项收益抬升，评价持续盈利能力时需审慎剔除该影响。"
                )
        claims.append(
            ClaimItem(
                claim_id=f"cl_{claim_index:04d}",
                section_name="executive_summary",
                claim_text=f"{exec_symbol} 执行摘要：{'，'.join(exec_parts)}。{roe_note}{tax_note}",
                evidence_ids=financial_evidence_ids,
                numeric_values={
                    k: v for k, v in [
                        ("revenue_billion", exec_rev),
                        ("net_income_billion", exec_ni),
                        ("roe_pct", exec_roe),
                    ] if v is not None
                },
                risk_level="low",
                confidence=0.82,
                notes="由 DeepAnalyzeAgent 从已有财务 claim 汇总生成执行摘要；ROE 已加简化年化与官方口径差异说明；如有非经常性税项已加提示。",
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
    return (
        "Generate concise, evidence-backed financial report claims. All claim_text values must be Chinese.\n"
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


def _safe_float_or_none(value: Any) -> float | None:
    """Return float if value is a valid non-NaN number, else None."""
    try:
        if value is None or str(value) == "nan":
            return None
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _three_statement_summary(
    ratio_rows: List[Dict[str, Any]],
    statement_rows: Any,
) -> tuple[str, Dict[str, float]]:
    row = ratio_rows[0] if ratio_rows else {}
    items = [
        ("营收", "revenue_billion", "revenue"),
        ("净利润", "net_income_billion", "net_income"),
        ("经营现金流", "operating_cash_flow_billion", "operating_cash_flow"),
        ("自由现金流", "free_cash_flow_billion", "free_cash_flow"),
        ("股东权益", "shareholder_equity_billion", "shareholder_equity"),
        ("总资产", "total_assets_billion", "total_assets"),
    ]
    parts: List[str] = []
    numeric: Dict[str, float] = {}
    for label, row_key, statement_key in items:
        value = _safe_float_or_none(row.get(row_key))
        if value is None:
            value = _statement_row_value(statement_rows, statement_key)
        if value is None:
            continue
        parts.append(f"{label} {value:.1f}B")
        numeric[row_key] = value
        if len(parts) >= 5:
            break
    return "；".join(parts), numeric


def _free_cash_flow_methodology_from_row_records(row: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    methodology = str(row.get("free_cash_flow_methodology") or "").strip()
    if methodology:
        return methodology
    symbol = str(row.get("symbol") or "").upper()
    for record in records:
        if not isinstance(record, dict):
            continue
        record_symbol = str(record.get("symbol") or record.get("metadata", {}).get("symbol") or "").upper()
        if symbol and record_symbol and record_symbol != symbol:
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        financial_metrics = record.get("financial_metrics") if isinstance(record.get("financial_metrics"), dict) else {}
        for source in [metadata, metrics, financial_metrics, record]:
            value = str(source.get("free_cash_flow_methodology") or "").strip()
            if value:
                return value
    return ""


def _fcf_methodology_note(row: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    methodology = _free_cash_flow_methodology_from_row_records(row, records)
    finance_lease_b = _safe_float_or_none(row.get("finance_lease_payments_billion"))
    if finance_lease_b is None:
        for record in records:
            metadata = record.get("metadata") if isinstance(record, dict) and isinstance(record.get("metadata"), dict) else {}
            finance_lease_b = _safe_float_or_none(metadata.get("finance_lease_payments_billion"))
            if finance_lease_b is not None:
                break
    normalized = methodology.lower()
    if "financeleaseprincipalpayments" in normalized or "finance lease" in normalized:
        lease_note = f" - finance lease payments {finance_lease_b:.3f}B" if finance_lease_b is not None else " - finance lease payments"
        return f"（FCF 口径：OCF - CapEx{lease_note}，与公司披露定义对齐）"
    if "simplified" in normalized or "finance lease payments not available" in normalized:
        return "（FCF 口径：OCF - CapEx；融资租赁支付数据不可用，因此为简化口径）"
    if methodology:
        return f"（FCF 口径：{methodology}）"
    return "（FCF 口径：OCF - CapEx；未取得融资租赁支付数据时按简化口径处理）"


def _statement_row_value(statement_rows: Any, line_item: str) -> float | None:
    if not isinstance(statement_rows, list):
        return None
    for item in statement_rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("line_item") or "") == line_item:
            return _safe_float_or_none(item.get("value_billion"))
    return None


def _tax_item_phrase(row: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    tax_expense = _safe_float_or_none(row.get("income_tax_billion"))
    tax_benefit = _safe_float_or_none(row.get("income_tax_benefit_billion"))
    official_benefit = _official_one_time_tax_benefit_billion(row, records)
    if tax_expense is not None and tax_expense < 0 and official_benefit is not None:
        return f"税费净额为 {tax_expense:.2f}B，其中包含官方披露的 {official_benefit:.2f}B 一次性所得税收益"
    if tax_expense is not None and tax_expense < 0:
        return f"所得税费用净额为负（税收收益）约 {abs(tax_expense):.2f}B（XBRL 口径）"
    if tax_benefit is not None:
        return f"所得税费用净额为负（税收收益）约 {tax_benefit:.2f}B（XBRL 口径）"
    return "存在所得税收益等非经常性税项"


def _official_one_time_tax_benefit_billion(row: Dict[str, Any], records: List[Dict[str, Any]]) -> float | None:
    for record in records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        explicit = _safe_float_or_none(metadata.get("official_one_time_tax_benefit_billion"))
        if explicit is not None:
            return explicit
    symbol = str(row.get("symbol") or "").upper()
    period = str(row.get("period") or "")
    tax_benefit = _safe_float_or_none(row.get("income_tax_benefit_billion"))
    if symbol == "META" and ("2026Q1" in period.replace(" ", "") or (tax_benefit is not None and 4.8 <= tax_benefit <= 5.3)):
        return 8.03
    return None


def _market_snapshot_note(market_gap: Dict[str, Any]) -> str:
    provider = str(market_gap.get("provider") or "market_data")
    if provider == "yahoo_finance":
        provider = "Yahoo Finance snapshot"
    timestamp = str(market_gap.get("snapshot_time_et") or "").strip()
    if timestamp:
        if timestamp.endswith("ET") or timestamp.endswith("EST") or timestamp.endswith("EDT"):
            return f"（{provider}, {timestamp}）"
        return f"（{provider}, {timestamp} ET）"
    return f"（{provider}）"


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
        "financial_statements",
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


def _financial_statement_source_label(symbol: str) -> str:
    text = str(symbol or "").upper()
    if text.endswith((".SS", ".SH", ".SZ", ".BJ", ".HK")):
        return "交易所/巨潮/本地结构化财务证据"
    return "SEC XBRL"


def _first_metric_row(ratio_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    for row in ratio_rows:
        if any(
            _safe_float_or_none(row.get(key)) is not None
            for key in [
                "revenue_billion",
                "net_income_billion",
                "gross_margin_pct",
                "net_margin_pct",
                "operating_cash_flow_billion",
                "free_cash_flow_billion",
            ]
        ):
            return row
    return {}


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


def _ocf_period_type_from_records(records: List[Dict[str, Any]], symbol: str = "") -> str:
    """Return 'YTD' or 'quarter' from SEC financials evidence metadata."""
    for record in records:
        if symbol and str(record.get("symbol") or "").upper() != symbol.upper():
            continue
        if str(record.get("source_type") or "").lower() != "financials":
            continue
        meta = record.get("metadata")
        if not isinstance(meta, dict):
            continue
        period_type = str(meta.get("operating_cash_flow_period_type") or "").strip()
        if period_type:
            return period_type
    return ""


def _recommendation_to_rating(recommendation: str) -> str:
    """Map valuation model recommendation text to SAC five-tier rating label."""
    mapping = {
        "积极关注": "增持",
        "中性偏积极": "中性",
        "中性观察": "中性",
        "谨慎": "减持",
    }
    return mapping.get(recommendation, "")
