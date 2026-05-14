"""RiskAgent: generates risk_assessment section claims from evidence and valuation context."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from src.agents.base_agent import AgentStatus, AgentTask, BaseAgent, TaskResult
from src.agents.deep_analyze_agent import _safe_float_or_none
from src.agents.deep_analyze_agent import _tax_item_phrase
from src.schemas.claim import ClaimItem


_RISK_CATEGORIES = {
    "macro": ["利率", "通胀", "衰退", "宏观", "macro", "interest rate", "recession", "inflation"],
    "regulatory": ["监管", "合规", "诉讼", "罚款", "regulatory", "compliance", "litigation", "fine", "antitrust"],
    "capex": ["资本开支", "CapEx", "capital expenditure", "投资", "guidance"],
    "competition": ["竞争", "市场份额", "competition", "market share"],
    "earnings_quality": ["一次性", "非经常", "税收收益", "减值", "重组", "one-time", "non-recurring", "impairment"],
    "valuation": ["估值偏高", "高估", "overvalued", "premium"],
}


class RiskAgent(BaseAgent):
    """Generates risk_assessment claims from evidence, valuation, and non-recurring item data."""

    def __init__(self, model=None, tools=None):
        super().__init__(name="RiskAgent", model=model, tools=tools or {})

    def get_capabilities(self) -> list:
        return ["risk_assessment", "earnings_quality_risk", "valuation_gap_risk"]

    def execute_task(self, task: AgentTask) -> TaskResult:
        return self.run(task)

    def run(self, task: AgentTask) -> TaskResult:
        params = task.parameters or {}
        symbol: str = str(params.get("symbol", "Company")).upper()
        evidence_records: List[Dict[str, Any]] = params.get("evidence_records", [])
        valuation: Dict[str, Any] = params.get("valuation", {})
        ratio_rows: List[Dict[str, Any]] = params.get("ratio_rows", [])
        financial_evidence_ids: List[str] = params.get("financial_evidence_ids", [])
        market_evidence_ids: List[str] = params.get("market_evidence_ids", [])

        risks: List[str] = []
        risk_evidence_ids: List[str] = list(financial_evidence_ids) + list(market_evidence_ids)

        # 1. Non-recurring item risks
        for row in ratio_rows[:1]:
            tax_benefit = _safe_float_or_none(row.get("income_tax_benefit_billion"))
            restructuring = _safe_float_or_none(row.get("restructuring_charges_billion"))
            impairment = _safe_float_or_none(row.get("asset_impairment_billion"))
            if tax_benefit and tax_benefit > 0.1:
                risks.append(
                    f"盈利质量风险：{_tax_item_phrase(row, evidence_records)}，"
                    "若下期无类似税项，净利润和 ROE 将面临回落压力。"
                )
            if restructuring and restructuring > 0.1:
                risks.append(
                    f"重组风险：本期重组费用 {restructuring:.2f}B，"
                    "需关注重组计划执行进度及后续潜在费用。"
                )
            if impairment and impairment > 0.1:
                risks.append(
                    f"资产减值风险：本期资产减值 {impairment:.2f}B，"
                    "需关注相关资产的持续经营价值。"
                )

        # 2. Valuation gap risk
        market_gap = valuation.get("market_gap", {}) if isinstance(valuation.get("market_gap"), dict) else {}
        gap_pct = _safe_float_or_none(market_gap.get("valuation_gap_pct"))
        if gap_pct is not None:
            if gap_pct > 20:
                risks.append(
                    f"估值回撤风险：规则估值高于当前市值约 {gap_pct:.1f}%，"
                    "若市场预期下修或利率上行，股价存在回调压力。"
                )
            elif gap_pct < -20:
                risks.append(
                    f"估值回撤风险：规则估值低于当前市值约 {abs(gap_pct):.1f}%，"
                    "可能反映市场对增长预期更为乐观，需关注估值假设的合理性。"
                )

        # 3. Evidence-based risks: scan Tavily/web search results for risk keywords
        for record in evidence_records:
            if not isinstance(record, dict):
                continue
            if str(record.get("source_type", "")).lower() not in {"web_search", "tavily", "news"}:
                continue
            content = str(record.get("content") or record.get("snippet") or "").lower()
            title = str(record.get("title") or "").lower()
            combined = content[:500] + " " + title
            eid = str(record.get("evidence_id") or record.get("sample_id") or "")
            for category, keywords in _RISK_CATEGORIES.items():
                if any(kw.lower() in combined for kw in keywords):
                    if eid and eid not in risk_evidence_ids:
                        risk_evidence_ids.append(eid)
                    break

        # 4. CapEx guidance risk (from ratio_rows or evidence)
        for row in ratio_rows[:1]:
            capex = _safe_float_or_none(row.get("capital_expenditure_billion"))
            rev = _safe_float_or_none(row.get("revenue_billion"))
            if capex and rev and capex / rev > 0.25:
                risks.append(
                    f"资本开支强度风险：资本开支约 {capex:.1f}B，占营收比例约 {capex/rev:.0%}，"
                    "高强度投入期自由现金流承压，需关注投资回报周期。"
                )
            elif capex and capex > 5:
                risks.append(
                    f"资本开支风险：本期资本开支约 {capex:.1f}B。"
                    "如公司已上调全年 CapEx 指引，可能进一步压制自由现金流，需关注管理层指引变化。"
                )

        # 5. Financial sector specific risks
        is_financial = bool(valuation.get("is_financial_sector", False))
        if is_financial:
            risks.append(
                "利率与信用风险（银行业）：净息差受利率周期影响显著；"
                "信贷质量在经济下行期面临不良贷款率上升压力；"
                "资本充足率需持续满足监管要求（CET1 等）。"
            )

        # 6. Generic risks if no specific risks found
        if not risks:
            if _is_china_listed_symbol(symbol):
                risks.extend(_china_market_default_risks(symbol=symbol, evidence_records=evidence_records, ratio_rows=ratio_rows))
            else:
                risks.append(
                    f"{symbol} 当前可识别风险包括：宏观经济不确定性、行业竞争加剧、"
                    "监管政策变化及汇率波动。具体风险程度需结合最新年报、季报、公告或 10-Q/10-K 披露评估。"
                )

        risk_text = f"{symbol} 风险评估：\n" + "\n".join(f"• {r}" for r in risks)

        from src.schemas.claim import ClaimItem
        claim = ClaimItem(
            claim_id="cl_risk_0001",
            section_name="risks",
            claim_text=risk_text,
            evidence_ids=risk_evidence_ids[:6],
            numeric_values={},
            risk_level="high",
            confidence=0.65,
            notes="由 RiskAgent 从非经常项、估值差异、证据关键词和行业特征综合生成。",
        )

        return TaskResult(
            task_id=task.task_id,
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            output={"claims": [claim.__dict__ if hasattr(claim, "__dict__") else claim]},
        )


def _is_china_listed_symbol(symbol: str) -> bool:
    text = str(symbol or "").upper()
    return text.endswith((".SS", ".SH", ".SZ", ".BJ", ".HK")) or text[:2] in {"SH", "SZ", "BJ", "HK"}


def _china_market_default_risks(
    symbol: str,
    evidence_records: List[Dict[str, Any]],
    ratio_rows: List[Dict[str, Any]],
) -> List[str]:
    industry_text = " ".join(
        str(value or "")
        for row in ratio_rows[:1]
        for value in [row.get("sector"), row.get("industry")]
    ).lower()
    evidence_text = " ".join(
        (str(record.get("title") or "") + " " + str(record.get("content") or ""))[:300]
        for record in evidence_records[:8]
    ).lower()
    combined = industry_text + " " + evidence_text
    if any(keyword in combined for keyword in ["白酒", "酒", "liquor", "beverage", "consumer staples"]):
        return [
            "消费需求与价格带风险：高端白酒需求受宏观消费、商务宴请和礼赠场景影响，若终端动销走弱，批价和渠道利润可能承压。",
            "渠道库存与回款风险：经销商库存、预收款和现金流变化会影响收入确认节奏，需要结合年报、季报和交易所公告持续跟踪。",
            "食品安全与监管风险：白酒企业受食品安全、广告宣传、税收政策和行业监管影响，突发事件可能放大估值波动。",
        ]
    return [
        f"{symbol} 当前可识别风险包括：宏观经济与市场流动性变化、行业竞争、监管政策和公告披露不完整带来的数据风险。",
        "具体风险程度需结合最新年报、季报、临时公告、交易所问询函和行业政策文件评估。",
    ]
