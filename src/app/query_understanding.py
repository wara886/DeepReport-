"""Query understanding layer for the chat-first workbench.

Performs intent classification, query normalization, and entity extraction
before routing to the appropriate pipeline (report generation, data query,
quality review, or general chat).
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Dict

from src.app.chat_task_parser import _parse_period, _parse_symbol
from src.models.model_adapter import ModelAdapter
from src.utils.config import load_config


_INTENT_SYSTEM_PROMPT = (
    "You are a precise intent classifier for a financial research system. "
    "Classify the user's message into exactly one of these intents. "
    "Priority order: report_artifact_request > confirmation > cancel_or_modify "
    "> quality_review > report_revision_request > report_generation > data_query > chat.\n\n"
    '- "report_artifact_request": user wants to OPEN / GET a previously generated report HTML, link, or file path.\n'
    '  Examples: "给我html", "打开刚才的报告", "发我报告链接", "把之前生成的报告给我", "直接给我特斯拉财报的html", "打开之前生成的TSLA报告"\n'
    '- "confirmation": user explicitly CONFIRMS a pending report generation.\n'
    '  Examples: "是", "确认", "开始生成", "确认生成", "生成吧", "没问题", "好的", "yes", "ok"\n'
    '- "cancel_or_modify": user wants to CHANGE company/period or CANCEL the pending request.\n'
    '  Examples: "修改报告期", "换公司", "取消", "改成AAPL", "不要了", "换个股票"\n'
    '- "report_revision_request": user wants to MODIFY/SUPPLEMENT an existing report.\n'
    '  Examples: "在刚才的报告上加一段竞争分析", "补充现金流分析", "帮我修改上一份报告的估值部分"\n'
    '- "report_generation": user wants to GENERATE a NEW research report.\n'
    '  Examples: "写一份TSLA研报", "生成茅台财报分析", "帮我做一份NVDA 2025的分析", "生成最新财报"\n'
    '- "quality_review": user wants to REVIEW the quality of a past report.\n'
    '  Examples: "检查最近报告质量", "复盘引用是否完整", "delivery gate结果", "为什么报告没通过校验"\n'
    '- "data_query": user wants to ASK a question about financial data.\n'
    '  Examples: "TSLA去年营收多少", "NVDA PE多少", "AMD和NVDA对比估值", "特斯拉交付量"\n'
    '- "chat": general conversation, greetings, explanations, help requests.\n'
    '  Examples: "你好", "解释一下DCF", "什么是EBITDA"\n\n'
    "IMPORTANT: If the user asks for a previously generated report HTML/link/file, classify as report_artifact_request, "
    "NOT report_generation. If the user says things like '给我' + '报告'/'html'/'链接', it is report_artifact_request.\n\n"
    "Output JSON with:\n"
    '- "intent": one of the above\n'
    '- "confidence": 0.0-1.0\n'
    '- "reason": short explanation'
)

_NORMALIZE_SYSTEM_PROMPT = (
    "You are a query normalizer for a financial research system. "
    "Rewrite the user's colloquial input into clear keyword form suitable for parsing. "
    "Rules:\n"
    "- Expand abbreviations: '25年' -> '2025年', '去年' -> use current year context\n"
    "- Keep all entity names (company names, tickers, metric names) unchanged\n"
    "- Remove filler words (帮我, 看一下, 请问, 能不能, 我想)\n"
    "- Output ONLY the rewritten query text, no explanation"
)


def _resolve_profile(config_path: str) -> str:
    config = load_config(config_path)
    routes = config.get("agent_model_routes") if isinstance(config, dict) else {}
    defaults = routes.get("defaults", {}) if isinstance(routes, dict) and isinstance(routes.get("defaults"), dict) else {}
    route = routes.get("task_parser") if isinstance(routes, dict) else None
    if isinstance(route, dict):
        return str(route.get("delivery") or route.get("preview") or defaults.get("delivery") or "flash")
    if isinstance(route, str):
        return route
    return str(defaults.get("delivery") or "flash")


def _call_llm_json(prompt: str, system_prompt: str, config_path: str) -> Dict[str, Any] | None:
    """Make a lightweight LLM call returning JSON. Returns None on failure."""
    try:
        profile = _resolve_profile(config_path)
        adapter = ModelAdapter.from_profile(profile=profile, config_path=config_path, fallback_section="agent_model")
        adapter.max_tokens = 256
        adapter.temperature = 0.0
        adapter.timeout = 10.0
        result = adapter.generate_json(prompt=prompt, system_prompt=system_prompt)
        return result if isinstance(result, dict) else None
    except Exception:
        return None


def _call_llm_text(prompt: str, system_prompt: str, config_path: str) -> str | None:
    """Make a lightweight LLM call returning text. Returns None on failure."""
    try:
        profile = _resolve_profile(config_path)
        adapter = ModelAdapter.from_profile(profile=profile, config_path=config_path, fallback_section="agent_model")
        adapter.max_tokens = 256
        adapter.temperature = 0.0
        adapter.timeout = 10.0
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        response = adapter.chat(messages=messages)
        if response.success:
            return response.content.strip()
        return None
    except Exception:
        return None


class QueryUnderstanding:
    """Chat-level query understanding: intent classification, normalization, entity extraction."""

    def __init__(self, config_path: str = "configs/model_backends.yaml"):
        self.config_path = config_path

    def intent_classify(self, message: str) -> str:
        """Classify user intent into one of 8 categories.

        Priority: report_artifact_request > confirmation > cancel_or_modify
        > quality_review > report_revision_request > report_generation > data_query > chat.

        Returns:
            One of: "report_artifact_request", "confirmation", "cancel_or_modify",
            "quality_review", "report_revision_request", "report_generation",
            "data_query", "chat"
        """
        text = str(message or "").strip()
        if not text:
            return "chat"

        result = _call_llm_json(text, _INTENT_SYSTEM_PROMPT, self.config_path)
        if result is None:
            return self._fallback_intent(text)
        intent = str(result.get("intent", "chat")).strip().lower()
        confidence = float(result.get("confidence", 0.0))
        valid_intents = {
            "report_artifact_request", "confirmation", "cancel_or_modify",
            "quality_review", "report_revision_request", "report_generation",
            "data_query", "chat",
        }
        if intent not in valid_intents:
            intent = "chat"
        if confidence < 0.3:
            intent = self._fallback_intent(text)
        return intent

    def _fallback_intent(self, text: str) -> str:
        """Rule-based intent fallback when LLM is unavailable.

        Priority order matches intent_classify.
        """
        lowered = text.lower()
        artifact_terms = ("html", "链接", "link", "给我", "打开", "发我", "之前生成", "已生成")
        report_terms = ("研报", "财报", "报告", "年报", "季报", "research report", "company report")
        generation_terms = ("生成", "写", "撰写", "写一份", "做一份", "generate", "write", "create")
        quality_terms = ("检查", "复盘", "质量问题", "引用是否完整", "quality review", "delivery gate")
        confirmation_terms = ("是", "确认", "开始生成", "确认生成", "生成吧", "没问题", "yes", "ok", "好的")
        cancel_terms = ("修改报告期", "换公司", "取消", "不要了", "换")
        question_terms = ("多少", "怎么", "如何", "吗", "呢", "是什么", "对比", "哪个")

        # 1. report_artifact_request
        is_artifact = any(term in lowered for term in artifact_terms) and any(term in lowered for term in report_terms)
        if is_artifact:
            return "report_artifact_request"
        if any(term in lowered for term in ("html", "链接", "link")) and any(t in text for t in ("报告", "研报", "财报")):
            return "report_artifact_request"

        # 2. confirmation
        confirm_normalized = re.sub(r"\s+", "", text.strip().lower())
        if confirm_normalized in ("是", "是的", "确认", "确认生成", "开始生成", "生成吧", "没问题", "好的", "好", "行", "yes", "ok", "okay"):
            return "confirmation"

        # 3. cancel_or_modify
        if any(term in lowered for term in cancel_terms):
            return "cancel_or_modify"

        # 4. quality_review
        if any(term in lowered for term in quality_terms):
            return "quality_review"

        has_question = any(term and term in lowered for term in question_terms)
        has_report = any(term in lowered for term in report_terms)
        has_generation = any(term in lowered for term in generation_terms)

        # 5. report_revision_request (modify existing report)
        revision_terms = ("补充", "修改", "加一段", "改一下", "补充分析", "revise", "supplement")
        if any(term in lowered for term in revision_terms) and has_report:
            return "report_revision_request"

        # 6. report_generation
        if has_report and has_generation:
            return "report_generation"

        # 7. data_query
        if has_question and (has_report or any(t in text for t in ("营收", "利润", "估值", "PE", "交付", "收入"))):
            return "data_query"

        # 8. Default to chat
        return "chat"

    def normalize_query(self, message: str) -> str:
        """Rewrite colloquial input into clear keyword form for downstream parsing.

        Only call this for non-chat intents (report_generation, data_query).
        Falls back to original text on failure.
        """
        text = str(message or "").strip()
        if not text:
            return text

        result = _call_llm_text(text, _NORMALIZE_SYSTEM_PROMPT, self.config_path)
        if result and result.strip():
            normalized = result.strip().strip("\"'")
            if normalized:
                return normalized
        return text

    def extract_entities(self, message: str, current_symbol: str = "AAPL", current_period: str = "2025Q4", today: date | None = None) -> Dict[str, Any]:
        """Extract symbol, period, and metric hints from the message.

        Reuses _parse_symbol and _parse_period from chat_task_parser for
        consistency. Metric hint is extracted via a simple keyword scan.
        """
        text = str(message or "").strip()
        symbol, symbol_conf, _, _ = _parse_symbol(text, current_symbol)
        period, period_kind, _, _ = _parse_period(text, current_period, symbol=symbol, today=today or date.today())

        metric_hint = self._extract_metric_hint(text)

        return {
            "symbol": symbol,
            "period": period,
            "period_kind": period_kind,
            "metric_hint": metric_hint,
            "confidence": round(min(0.99, symbol_conf + 0.1), 4),
        }

    def _extract_metric_hint(self, text: str) -> str:
        """Extract a financial metric hint from the query text."""
        lowered = text.lower()
        metrics = [
            ("营收", "revenue"),
            ("收入", "revenue"),
            ("利润", "profit"),
            ("净利润", "net_income"),
            ("毛利率", "gross_margin"),
            ("现金流", "cash_flow"),
            ("资产", "assets"),
            ("负债", "liabilities"),
            ("估值", "valuation"),
            ("市盈率", "pe"),
            ("PE", "pe"),
            ("市净率", "pb"),
            ("PB", "pb"),
            ("交付量", "delivery"),
            ("交付", "delivery"),
            ("销量", "sales_volume"),
            ("产能", "capacity"),
            ("市占率", "market_share"),
            ("对比", "comparison"),
            ("竞争", "competition"),
        ]
        for keyword, metric in metrics:
            if keyword in lowered:
                return metric
        return ""
