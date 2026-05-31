"""Query understanding layer for the chat-first workbench.

Performs intent classification, query normalization, and entity extraction
before routing to the appropriate pipeline (report generation, data query,
quality review, or general chat).
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Dict

from src.app.chat_task_parser import (
    _parse_period,
    _parse_symbol,
    latest_available_report_period,
)
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

_TARGET_RESOLUTION_SYSTEM_PROMPT = (
    "You are the planning-stage company and filing-period resolver for a stock research report system. "
    "Understand the user's natural-language request and identify the intended listed company. "
    "You may use your market knowledge, but you must be conservative.\n\n"
    "Return JSON only with these keys:\n"
    '- "company_name": official or commonly used company name, empty if unknown.\n'
    '- "symbol": primary listed ticker, e.g. "MU", "TSM", "LLY", "PDD", "0700.HK", "600519.SS". Empty if unknown.\n'
    '- "market": one of "US", "HK", "CN", "OTHER", or "UNKNOWN".\n'
    '- "period_intent": one of "latest", "quarter", "fiscal_year", or "unknown".\n'
    '- "confidence": number from 0.0 to 1.0.\n'
    '- "needs_confirmation": boolean.\n'
    '- "reason": short explanation.\n\n'
    "Rules:\n"
    "- Never use the current context company as a fallback for an unresolved company.\n"
    "- If the user asks for 最新/latest/most recent, set period_intent to latest even if a year is also mentioned.\n"
    "- If more than one company is requested, leave symbol empty and set needs_confirmation true.\n"
    "- If you are not sure the company is publicly listed or the ticker is correct, set needs_confirmation true.\n"
)

_NOISE_SYMBOLS = {"HTML", "PDF", "CSV", "JSON", "TXT", "XML", "API", "URL", "FILE", "Q", "AI", "FY"}


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


def _normalize_report_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    hk = re.fullmatch(r"(\d{1,5})\.HK", text)
    if hk:
        return f"{hk.group(1).zfill(4)}.HK"
    cn = re.fullmatch(r"([036]\d{5})(?:\.(SS|SH|SZ))?", text)
    if cn:
        code = cn.group(1)
        suffix = ".SS" if code.startswith("6") else ".SZ"
        return f"{code}{suffix}"
    return text


def _normalize_market(market: str) -> str:
    raw = str(market or "").strip().upper()
    if raw in {"US", "NYSE", "NASDAQ", "AMEX"}:
        return "US"
    if raw in {"HK", "HKG", "HKEX"}:
        return "HK"
    if raw in {"CN", "CHINA", "A", "ASHARE", "A_SHARE", "SSE", "SZSE"}:
        return "CN"
    if raw:
        return raw
    return "UNKNOWN"


def _validate_report_symbol(symbol: str, market: str = "", company_name: str = "") -> Dict[str, Any]:
    symbol = _normalize_report_symbol(symbol)
    if not symbol or symbol in _NOISE_SYMBOLS:
        return {"routeable": False, "identity_verified": False, "market": "UNKNOWN", "reason": "missing or noisy ticker"}
    routeable = bool(
        re.fullmatch(r"[A-Z]{1,6}", symbol)
        or re.fullmatch(r"\d{4,5}\.HK", symbol)
        or re.fullmatch(r"[036]\d{5}\.(SS|SH|SZ)", symbol)
    )
    if not routeable:
        return {"routeable": False, "identity_verified": False, "market": "UNKNOWN", "reason": f"ticker {symbol} is not routeable"}

    try:
        from src.data.company_universe import resolve_company_identity

        identity = resolve_company_identity(symbol or company_name, default=symbol)
        identity_verified = bool(identity.is_listed and not identity.needs_confirmation)
        resolved_market = {
            "us": "US",
            "hk": "HK",
            "cn_a": "CN",
        }.get(str(identity.market or "").lower(), _normalize_market(market))
        return {
            "routeable": True,
            "identity_verified": identity_verified,
            "company_name": str(identity.company_name or company_name or ""),
            "market": resolved_market,
            "reason": f"symbol {symbol} routeable; identity_confidence={identity.resolution_confidence}",
        }
    except Exception as exc:
        return {
            "routeable": True,
            "identity_verified": False,
            "company_name": company_name,
            "market": _normalize_market(market),
            "reason": f"symbol {symbol} routeable; identity lookup failed: {exc}",
        }


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

    def resolve_report_target(
        self,
        message: str,
        current_symbol: str = "",
        current_period: str = "",
        today: date | None = None,
    ) -> Dict[str, Any]:
        """Resolve company + period for report planning with validation gates.

        The resolver deliberately does not fall back to ``current_symbol`` when
        the user names an unknown company.  Current context is informational for
        the LLM prompt only.
        """

        today = today or date.today()
        text = str(message or "").strip()
        base = self._empty_target_result(text, today=today, current_period=current_period)
        if not text:
            return base

        local = self._resolve_target_local(text, current_period=current_period, today=today)
        llm = self._resolve_target_llm(text, current_symbol=current_symbol, current_period=current_period, today=today)

        if local.get("ambiguous"):
            return local

        if local.get("symbol"):
            if llm.get("symbol") and llm["symbol"] != local["symbol"] and float(llm.get("confidence") or 0) >= 0.65:
                local["needs_confirmation"] = True
                local["conflict"] = True
                local["reason"] = f"local symbol {local['symbol']} conflicts with LLM symbol {llm['symbol']}"
                local["alternatives"] = [local, llm]
            return local

        if llm.get("symbol"):
            return llm

        if llm.get("company_name"):
            llm["needs_confirmation"] = True
            llm["reason"] = llm.get("reason") or "LLM found a company name but no verified ticker"
            return llm

        return base

    def _empty_target_result(self, text: str, today: date, current_period: str = "") -> Dict[str, Any]:
        period, period_kind, _, period_note = _parse_period(
            text,
            current_period or latest_available_report_period(today=today),
            today=today,
            symbol="",
        )
        return {
            "company_name": "",
            "symbol": "",
            "market": "UNKNOWN",
            "period_intent": period_kind,
            "resolved_period": period,
            "period": period,
            "confidence": 0.0,
            "needs_confirmation": True,
            "verified": False,
            "source": "unresolved",
            "reason": f"company unresolved; {period_note}",
        }

    def _resolve_target_local(self, text: str, current_period: str, today: date) -> Dict[str, Any]:
        try:
            from src.app.company_aliases import resolve_company_alias_all
        except Exception:
            resolve_company_alias_all = None

        matches = resolve_company_alias_all(text) if resolve_company_alias_all else []
        if len(matches) > 1:
            period, period_kind, _, period_note = _parse_period(text, current_period, today=today, symbol="")
            return {
                "company_name": "",
                "symbol": "",
                "market": "UNKNOWN",
                "period_intent": period_kind,
                "resolved_period": period,
                "period": period,
                "confidence": 0.0,
                "needs_confirmation": True,
                "verified": False,
                "ambiguous": True,
                "source": "local_alias",
                "alternatives": matches,
                "reason": f"multiple company aliases matched; {period_note}",
            }
        if matches:
            match = matches[0]
            return self._build_validated_target(
                text=text,
                symbol=str(match.get("symbol") or ""),
                company_name=str(match.get("company_name") or ""),
                market=str(match.get("market") or ""),
                confidence=float(match.get("confidence") or 0.0),
                source="local_alias",
                reason=f"recognized alias {match.get('matched_alias')}",
                current_period=current_period,
                today=today,
            )

        symbol, symbol_conf, symbol_reason, symbol_needs_confirmation = _parse_symbol(text, "")
        if symbol and symbol_conf >= 0.18:
            result = self._build_validated_target(
                text=text,
                symbol=symbol,
                company_name="",
                market="",
                confidence=symbol_conf,
                source="local_symbol",
                reason=symbol_reason,
                current_period=current_period,
                today=today,
            )
            result["needs_confirmation"] = True if symbol_needs_confirmation else result["needs_confirmation"]
            return result

        return {}

    def _resolve_target_llm(
        self,
        text: str,
        current_symbol: str,
        current_period: str,
        today: date,
    ) -> Dict[str, Any]:
        prompt = (
            f"Today: {today.isoformat()}\n"
            f"Current context symbol, for reference only: {current_symbol or '(none)'}\n"
            f"Current context period, for reference only: {current_period or '(none)'}\n"
            f"User message: {text}\n\n"
            "Resolve the report target. Remember: do not copy the current context company when unresolved."
        )
        payload = _call_llm_json(prompt, _TARGET_RESOLUTION_SYSTEM_PROMPT, self.config_path)
        if not isinstance(payload, dict):
            return {}
        symbol = str(payload.get("symbol") or "").strip().upper()
        confidence = float(payload.get("confidence") or 0.0)
        if not symbol and confidence < 0.5:
            return {
                **self._empty_target_result(text, today=today, current_period=current_period),
                "company_name": str(payload.get("company_name") or ""),
                "source": "llm",
                "reason": str(payload.get("reason") or "LLM could not resolve a ticker"),
            }
        result = self._build_validated_target(
            text=text,
            symbol=symbol,
            company_name=str(payload.get("company_name") or ""),
            market=str(payload.get("market") or ""),
            confidence=confidence,
            source="llm",
            reason=str(payload.get("reason") or "LLM resolved report target"),
            current_period=current_period,
            today=today,
            llm_period_intent=str(payload.get("period_intent") or ""),
        )
        if bool(payload.get("needs_confirmation", False)):
            result["needs_confirmation"] = True
        if confidence < 0.65:
            result["needs_confirmation"] = True
            result["verified"] = False
        return result

    def _build_validated_target(
        self,
        text: str,
        symbol: str,
        company_name: str,
        market: str,
        confidence: float,
        source: str,
        reason: str,
        current_period: str,
        today: date,
        llm_period_intent: str = "",
    ) -> Dict[str, Any]:
        normalized_symbol = _normalize_report_symbol(symbol)
        period, period_kind, _, period_note = _parse_period(
            text,
            current_period or latest_available_report_period(symbol=normalized_symbol, today=today),
            today=today,
            symbol=normalized_symbol,
        )
        if llm_period_intent.lower() == "latest" and period_kind != "latest":
            period = latest_available_report_period(symbol=normalized_symbol, today=today)
            period_kind = "latest"
            period_note = f"LLM latest period {period}"

        validation = _validate_report_symbol(normalized_symbol, market=market, company_name=company_name)
        resolved_company = company_name or validation.get("company_name", "")
        resolved_market = validation.get("market") or _normalize_market(market)
        verified = bool(validation.get("routeable")) and confidence >= 0.55
        needs_confirmation = bool(not verified or confidence < 0.78 or not validation.get("identity_verified"))
        return {
            "company_name": resolved_company,
            "symbol": normalized_symbol if validation.get("routeable") else "",
            "market": resolved_market or "UNKNOWN",
            "period_intent": period_kind,
            "resolved_period": period,
            "period": period,
            "confidence": round(float(confidence), 4),
            "needs_confirmation": needs_confirmation,
            "verified": verified,
            "identity_verified": bool(validation.get("identity_verified")),
            "source": source,
            "reason": "; ".join(part for part in [reason, validation.get("reason", ""), period_note] if part),
        }

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
