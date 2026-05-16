"""Industry research agent for competition deliverables."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult


class IndustryResearchAgent(BaseAgent):
    """Generate an industry report from company-run artifacts."""

    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__(name="IndustryResearchAgent", tools=tools)

    def get_capabilities(self) -> List[str]:
        return [
            "derive industry structure from company evidence and peer context",
            "summarize competitive positioning, demand drivers, and risks",
            "produce competition-ready industry markdown/json deliverables",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        symbol = str(task.parameters.get("symbol") or "").upper()
        period = str(task.parameters.get("period") or "")
        company_summary = _dict(task.parameters.get("company_summary", {}))
        evidence_records = _list_of_dicts(task.parameters.get("evidence_records", []))
        independent_records = _list_of_dicts(task.parameters.get("independent_evidence_records", []))
        all_records = evidence_records + independent_records
        claims = _list_of_dicts(task.parameters.get("claims", []))
        analysis_artifacts = _dict(task.parameters.get("analysis_artifacts", {}))
        independent_source_meta = _dict(task.parameters.get("independent_source_meta", {}))
        peer_context = _dict(analysis_artifacts.get("peer_context", {}))
        profile = _profile_from_evidence(all_records)
        evidence_ids = _top_evidence_ids(all_records)
        independent_ids = _top_evidence_ids(independent_records)
        citation = _citation(evidence_ids)
        sector = str(profile.get("sector") or peer_context.get("sector") or "未披露板块")
        industry = str(profile.get("industry") or peer_context.get("industry") or "未披露行业")
        peer_count = int(peer_context.get("peer_count", 0) or 0)
        claim_count = len(claims) or int(company_summary.get("claim_count", 0) or 0)
        evidence_count = len(all_records) or int(company_summary.get("evidence_count", 0) or 0)
        independent_count = len(independent_records)
        score = company_summary.get("company_report_overall_score", company_summary.get("company_report_score", ""))
        freshness_summary = _freshness_summary(all_records)
        source_boundary = _source_boundary(independent_count=independent_count, independent_source_meta=independent_source_meta)
        markdown = f"""# 行业研究报告

## 执行摘要

- 本报告由 IndustryResearchAgent 基于公司主链 artifacts 生成，参考标的为 {symbol or '目标公司'}，期间为 {period or '未指定期间'}。
- 当前可用证据数为 {evidence_count}，其中独立行业/宏观/公司外部证据数为 {independent_count}；公司报告结论数为 {claim_count}，公司质量评分为 {score}。{citation}

## 行业定位

- 目标公司位于 {sector} / {industry}；该定位来自本地 company profile、财务证据或同行上下文。{citation}
- 独立证据已接入时，本节优先使用 SEC、官方统计、政策或行业权威来源补强行业定位；未命中的行业事实仍保持为公司主链衍生判断。{_citation(independent_ids)}

## 竞争格局

- 当前 peer context 覆盖 {peer_count} 个可比对象；可用于初步观察相对证据质量、估值和财务指标差异。
- 对 {symbol or '目标公司'} 的竞争判断应优先结合同行指标、业务描述、毛利率、现金流质量和风险信号，而不是单一估值倍数。

## 需求与供给驱动

- 需求侧重点关注终端市场增速、客户资本开支、产品替代周期和价格弹性。
- 供给侧重点关注产能、供应链集中度、关键零部件、渠道能力和行业监管变化。

## 数据边界与时效

- 证据 freshness 分布：{freshness_summary}。
- 真实边界：{source_boundary}

## 风险提示

- 当前行业报告会合并公司主链证据与可用独立证据；若独立数据源未返回记录，则不宣称已经具备完整第三方行业数据库能力。
- 行业景气、竞争强度、技术替代、监管政策、汇率和利率变化都可能改变行业结论。

## 结论

- 在现有证据边界内，行业研究已从公司主链中抽取出可追溯行业定位、同行覆盖和风险框架；正式投资研究仍需要补充独立行业数据源。
"""
        report_json = {
            "title": "行业研究报告",
            "symbol": symbol,
            "period": period,
            "sector": sector,
            "industry": industry,
            "peer_count": peer_count,
            "evidence_count": evidence_count,
            "independent_evidence_count": independent_count,
            "claim_count": claim_count,
            "source_evidence_ids": evidence_ids,
            "independent_source_evidence_ids": independent_ids,
            "freshness_summary": freshness_summary,
            "source_boundary": source_boundary,
            "independent_source_meta": independent_source_meta,
            "limitations": [_limitation(independent_count)],
        }
        return self.success(
            task,
            {"markdown": markdown, "report_json": report_json},
            metadata={
                "evidence_count": evidence_count,
                "independent_evidence_count": independent_count,
                "peer_count": peer_count,
                "source_evidence_ids": evidence_ids,
            },
        )


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _profile_from_evidence(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    for record in records:
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        if record.get("source_type") == "company_profile" or metadata.get("sector") or metadata.get("industry"):
            return metadata
    return {}


def _top_evidence_ids(records: List[Dict[str, Any]], limit: int = 4) -> List[str]:
    output: List[str] = []
    for record in records:
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "").strip()
        if evidence_id and evidence_id not in output:
            output.append(evidence_id)
        if len(output) >= limit:
            break
    return output


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
        return "已把可获取的独立 SEC/宏观/政策 evidence 纳入本报告，但每条事实仍以 evidence_id、source_timestamp 和 data_cutoff 为准。"
    reason = str(independent_source_meta.get("failure_reason") or "no_independent_records")
    return f"本报告未取得独立行业数据库记录；行业结论仅能作为公司主链 artifacts 的衍生分析，原因={reason}。"


def _limitation(independent_count: int) -> str:
    if independent_count > 0:
        return "已接入部分独立 SEC/宏观/政策 evidence，但尚未覆盖完整付费行业数据库或全行业 TAM/份额数据。"
    return "未接入完整第三方行业数据库；当前报告基于公司主链 artifacts 与本地证据。"
