"""Macro research agent for competition deliverables."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult


class MacroResearchAgent(BaseAgent):
    """Generate a macro context report from local company-run artifacts."""

    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__(name="MacroResearchAgent", tools=tools)

    def get_capabilities(self) -> List[str]:
        return [
            "summarize macro transmission channels for company valuation and demand",
            "separate evidenced market facts from directional macro reasoning",
            "produce competition-ready macro markdown/json deliverables",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        symbol = str(task.parameters.get("symbol") or "").upper()
        period = str(task.parameters.get("period") or "")
        company_summary = _dict(task.parameters.get("company_summary", {}))
        evidence_records = _list_of_dicts(task.parameters.get("evidence_records", []))
        independent_records = _list_of_dicts(task.parameters.get("independent_evidence_records", []))
        all_records = evidence_records + independent_records
        claims = _list_of_dicts(task.parameters.get("claims", []))
        independent_source_meta = _dict(task.parameters.get("independent_source_meta", {}))
        macro_ids = _macro_evidence_ids(independent_records)
        market_ids = _market_evidence_ids(all_records)
        citation = _citation(macro_ids or market_ids or _top_evidence_ids(all_records))
        verification = bool(company_summary.get("verification_passed", False))
        multimodal = bool(company_summary.get("multimodal_consistency_passed", False))
        evidence_count = len(all_records) or int(company_summary.get("evidence_count", 0) or 0)
        independent_count = len(independent_records)
        claim_count = len(claims) or int(company_summary.get("claim_count", 0) or 0)
        freshness_summary = _freshness_summary(all_records)
        source_boundary = _source_boundary(independent_count=independent_count, independent_source_meta=independent_source_meta)
        markdown = f"""# 宏观研究报告

## 执行摘要

- 本报告由 MacroResearchAgent 基于本地公司主链 artifacts 和可用独立宏观/政策 evidence 生成，覆盖期间为 {period or '未指定期间'}，参考标的为 {symbol or '目标公司'}。
- 公司报告门禁状态：verification={verification}，multimodal={multimodal}；可用证据数为 {evidence_count}，其中独立宏观/政策/SEC 证据数为 {independent_count}，结论数为 {claim_count}。{citation}

## 利率与流动性

- 利率和流动性通过折现率、风险偏好、融资成本和估值倍数影响股票定价。
- 若报告对象属于高久期成长股，折现率变化通常会放大估值敏感性；若属于金融机构，则净息差、资产质量和负债成本更关键。{_citation(macro_ids)}

## 增长、通胀与需求

- 增长预期影响收入增速和终端需求，通胀影响成本、价格传导和利润率。
- 对 {symbol or '目标公司'} 的宏观判断应结合公司主链中的收入、毛利率、现金流和风险结论，避免脱离证据进行方向性判断。

## 汇率、政策与风险偏好

- 跨国收入、供应链和海外成本暴露会放大汇率敏感性；政策变化会影响行业准入、税负、补贴和资本开支周期。
- 只有当 FRED、BLS、BEA、Federal Reserve 等独立 evidence 返回记录时，报告才引用最新 CPI、就业、利率或政策材料；否则仅保留传导框架。

## 对公司研究的传导

- 宏观变量主要通过估值模型假设、同行倍数、现金流折现率、收入场景和风险溢价传导到公司结论。
- 后续若接入权威宏观数据源，可把利率、通胀、汇率、PMI 和政策事件绑定为独立 evidence_id。

## 数据边界与时效

- 证据 freshness 分布：{freshness_summary}。
- 真实边界：{source_boundary}

## 风险提示

- 宏观结论以已返回的权威 evidence 和公司主链事实为边界；缺失的实时指标不会被默认补全或推断。
- 市场风险偏好可能在短期内快速变化，本地模型记忆不能替代实时数据。
"""
        report_json = {
            "title": "宏观研究报告",
            "symbol": symbol,
            "period": period,
            "evidence_count": evidence_count,
            "independent_evidence_count": independent_count,
            "claim_count": claim_count,
            "macro_evidence_ids": macro_ids,
            "market_evidence_ids": market_ids,
            "verification_passed": verification,
            "multimodal_consistency_passed": multimodal,
            "freshness_summary": freshness_summary,
            "source_boundary": source_boundary,
            "independent_source_meta": independent_source_meta,
            "limitations": [_limitation(independent_count)],
        }
        return self.success(
            task,
            {"markdown": markdown, "report_json": report_json},
            metadata={"evidence_count": evidence_count, "independent_evidence_count": independent_count, "market_evidence_ids": market_ids},
        )


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _market_evidence_ids(records: List[Dict[str, Any]]) -> List[str]:
    ids: List[str] = []
    for record in records:
        source_type = str(record.get("source_type") or "").lower()
        if source_type not in {"market", "market_api", "news"}:
            continue
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "").strip()
        if evidence_id and evidence_id not in ids:
            ids.append(evidence_id)
    return ids[:4]


def _macro_evidence_ids(records: List[Dict[str, Any]]) -> List[str]:
    ids: List[str] = []
    for record in records:
        source_type = str(record.get("source_type") or "").lower()
        scope = str(record.get("evidence_scope") or "").lower()
        if source_type not in {"macro_api", "macro_statistic", "policy_release", "federal_reserve", "fred_series", "bls_series", "bea_series"} and scope != "macro":
            continue
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "").strip()
        if evidence_id and evidence_id not in ids:
            ids.append(evidence_id)
    return ids[:6]


def _top_evidence_ids(records: List[Dict[str, Any]], limit: int = 2) -> List[str]:
    ids: List[str] = []
    for record in records:
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "").strip()
        if evidence_id and evidence_id not in ids:
            ids.append(evidence_id)
        if len(ids) >= limit:
            break
    return ids


def _citation(evidence_ids: List[str]) -> str:
    return " ".join(f"[{item}]" for item in evidence_ids[:2]) if evidence_ids else ""


def _freshness_summary(records: List[Dict[str, Any]]) -> str:
    buckets: Dict[str, int] = {}
    for record in records:
        bucket = str(record.get("freshness_bucket") or "unknown")
        buckets[bucket] = buckets.get(bucket, 0) + 1
    if not buckets:
        return "unknown=0"
    return ", ".join(f"{key}={value}" for key, value in sorted(buckets.items()))


def _source_boundary(independent_count: int, independent_source_meta: Dict[str, Any]) -> str:
    if independent_count > 0:
        return "已纳入可获取的 FRED/BLS/BEA/Federal Reserve/SEC 等独立 evidence；每个宏观事实以 evidence_id、source_timestamp 与 data_cutoff 为准。"
    reason = str(independent_source_meta.get("failure_reason") or "no_independent_records")
    return f"本报告未取得实时宏观数据库记录；宏观判断仅作为公司主链 facts 的传导框架，原因={reason}。"


def _limitation(independent_count: int) -> str:
    if independent_count > 0:
        return "已接入部分独立宏观/政策/SEC evidence，但尚未覆盖全部全球宏观数据库或付费行业数据。"
    return "未接入实时宏观数据库；当前报告为公司主链 evidence 驱动的宏观传导框架。"
