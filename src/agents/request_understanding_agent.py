"""RequestUnderstandingAgent parses natural-language financial research intents."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.models import ModelAdapter
from src.request_understanding.entity_resolver import EntityResolver, EntityResolutionResult
from src.request_understanding.schema import (
    AttachmentSpec,
    OutputPreferences,
    PeriodSpec,
    ResearchRequest,
    ResolvedEntity,
    normalize_structured_request,
)


class RequestUnderstandingAgent(BaseAgent):
    def __init__(
        self,
        model: ModelAdapter | None = None,
        raw_data_root: str | Path = "data/raw/real_data",
        resolver: EntityResolver | None = None,
    ):
        super().__init__(name="RequestUnderstandingAgent", model=model)
        self.resolver = resolver or EntityResolver(raw_data_root=raw_data_root)

    def get_capabilities(self) -> List[str]:
        return [
            "parse natural-language financial research requests",
            "resolve company entity, ticker and market",
            "infer report type, period, focus areas and output preferences",
            "decide whether clarification is required before research",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        try:
            if isinstance(task.parameters.get("structured_request"), dict):
                request = self.parse_structured_request(dict(task.parameters["structured_request"]))
            else:
                query = str(task.parameters.get("natural_language_query") or task.description or "")
                attachments = task.parameters.get("attachments", [])
                request = self.parse(query=query, attachments=attachments if isinstance(attachments, list) else [])
            return self.success(task, {"research_request": request.to_dict()})
        except Exception as exc:
            return self.failure(task, str(exc))

    def parse(self, query: str, attachments: List[Dict[str, Any]] | None = None) -> ResearchRequest:
        text = str(query or "").strip()
        entity = self.resolver.resolve(text)
        period = parse_period(text)
        focus_areas = parse_focus_areas(text)
        report_type = parse_report_type(text)
        output_preferences = parse_output_preferences(text)
        attachment_spec = AttachmentSpec(optional=True, files=list(attachments or []))
        clarification_needed, questions = build_clarification(entity=entity, query=text, period=period)
        return ResearchRequest(
            original_query=text,
            resolved_entity=ResolvedEntity(
                company_name=entity.company_name,
                symbol=entity.symbol,
                market=entity.market,
                confidence=entity.confidence,
                candidates=entity.candidates,
            ),
            report_type=report_type,
            period=period,
            focus_areas=focus_areas,
            output_preferences=output_preferences,
            attachments=attachment_spec,
            clarification_needed=clarification_needed,
            clarification_questions=questions,
        )

    def parse_structured_request(self, payload: Dict[str, Any]) -> ResearchRequest:
        request = normalize_structured_request(payload)
        if not request.resolved_entity.symbol and request.original_query:
            parsed = self.parse(request.original_query, attachments=request.attachments.files)
            return ResearchRequest(
                original_query=request.original_query,
                resolved_entity=parsed.resolved_entity,
                report_type=request.report_type or parsed.report_type,
                period=request.period or parsed.period,
                focus_areas=request.focus_areas or parsed.focus_areas,
                output_preferences=request.output_preferences,
                attachments=request.attachments,
                clarification_needed=parsed.clarification_needed,
                clarification_questions=parsed.clarification_questions,
            )
        return request


def parse_period(query: str) -> PeriodSpec:
    text = str(query or "").lower()
    if "ttm" in text or "过去十二个月" in query or "近十二个月" in query:
        return PeriodSpec(type="ttm", granularity="trailing_12_months")
    if "最新" in query and ("季度" in query or "一季" in query or "季报" in query):
        return PeriodSpec(type="latest_quarter", granularity="quarter")
    if "最近一个季度" in query or "最近一季" in query or "最近季度" in query:
        return PeriodSpec(type="latest_quarter", granularity="quarter")
    if "年报" in query or "全年" in query or re.search(r"\bFY\b", query):
        return PeriodSpec(type="latest_fiscal_year", granularity="year")
    quarter = re.search(r"(20\d{2})\s*[Qq季度-]?\s*([1-4])", query)
    if quarter:
        return PeriodSpec(type=f"{quarter.group(1)}Q{quarter.group(2)}", granularity="quarter")
    year = re.search(r"\b(20\d{2})\b", query)
    if year:
        return PeriodSpec(type=year.group(1), granularity="year")
    return PeriodSpec(type="latest_quarter", granularity="quarter")


def parse_report_type(query: str) -> str:
    text = str(query or "").lower()
    if "深度" in query or "deep" in text:
        return "deep_company_research"
    broader_research_terms = ["研报", "报告", "经营", "财务", "季度", "基本面", "同业", "盈利", "现金流"]
    if "估值" in query and not any(word in query for word in broader_research_terms):
        return "valuation_analysis"
    if "风险" in query and "估值" not in query and not any(word in query for word in broader_research_terms):
        return "risk_review"
    return "company_research"


def parse_focus_areas(query: str) -> List[str]:
    patterns = [
        ("盈利质量", ["盈利质量", "利润质量", "quality of earnings"]),
        ("估值", ["估值", "valuation", "偏贵", "便宜"]),
        ("行业风险", ["行业风险", "行业", "竞争风险"]),
        ("同业对比", ["同业", "可比公司", "peer", "对比"]),
        ("经营情况", ["经营情况", "经营表现", "基本面", "运营"]),
        ("财务表现", ["财务", "收入", "利润", "现金流", "毛利率"]),
        ("主要风险", ["主要风险", "风险"]),
    ]
    focus: List[str] = []
    lowered = query.lower()
    for label, keywords in patterns:
        if any(keyword.lower() in lowered for keyword in keywords):
            focus.append(label)
    if not focus:
        focus = ["基本面", "财务表现", "估值", "主要风险"]
    return _dedupe(focus)


def parse_output_preferences(query: str) -> OutputPreferences:
    text = str(query or "")
    lowered = text.lower()
    language = "en" if "英文" in text or "english" in lowered else "zh"
    fmt = "markdown_html_json"
    if "pdf" in lowered:
        fmt = "pdf"
    elif "markdown" in lowered or "md" in lowered:
        fmt = "markdown"
    depth = "deep" if "深度" in text or "deep" in lowered else "standard"
    if "简短" in text or "摘要" in text or "brief" in lowered:
        depth = "brief"
    return OutputPreferences(language=language, format=fmt, depth=depth)


def build_clarification(entity: EntityResolutionResult, query: str, period: PeriodSpec) -> tuple[bool, List[str]]:
    questions: List[str] = []
    if not entity.symbol:
        if entity.candidates:
            formatted = _format_candidates(entity.candidates)
            questions.append(f"请确认你要研究的是哪一个标的：{formatted}？")
        else:
            questions.append("请确认要研究的上市公司名称或股票代码。")
    if entity.ambiguous:
        questions.append(f"该公司存在多个上市市场或含义，请确认具体标的：{_format_candidates(entity.candidates)}。")
    if entity.confidence and entity.confidence < 0.75:
        questions.append("当前公司实体解析置信度较低，请确认股票代码或上市市场。")
    if _period_requires_clarification(query, period):
        questions.append("请确认研究时间范围，例如 latest_quarter、TTM、某个财年或具体季度。")
    return bool(questions), _dedupe(questions)


def _period_requires_clarification(query: str, period: PeriodSpec) -> bool:
    text = query.strip()
    vague_time_terms = ["近期", "最近", "当前", "现在"]
    has_vague = any(term in text for term in vague_time_terms)
    has_quarter_hint = any(term in text for term in ["季度", "一季", "季报", "quarter"])
    return has_vague and not has_quarter_hint and period.type == "latest_quarter"


def _format_candidates(candidates: List[Dict[str, Any]]) -> str:
    parts = []
    for item in candidates[:4]:
        name = str(item.get("company_name", "") or item.get("symbol", ""))
        symbol = str(item.get("symbol", ""))
        market = str(item.get("market", ""))
        if symbol:
            parts.append(f"{name}（{symbol}, {market}）")
        else:
            parts.append(f"{name}（{market}）")
    return "；".join(parts)


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
