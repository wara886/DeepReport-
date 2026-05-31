"""Natural-language task parsing for the chat-first workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Any, Dict

from src.models.model_adapter import ModelAdapter
from src.utils.config import load_config
from src.utils.periods import latest_completed_period as _calendar_latest_completed_period


REPORT_TERMS = (
    "研报",
    "财报",
    "报告",
    "年报",
    "季报",
    "research report",
    "company report",
    "annual report",
    "quarterly report",
)
GENERATION_TERMS = (
    "生成",
    "写",
    "撰写",
    "写一份",
    "做一份",
    "run",
    "create",
    "write",
    "generate",
)
LATEST_TERMS = ("最新", "最近", "latest", "most recent")
KNOWN_COMPANY_ALIASES = {
    "苹果公司": "AAPL",
    "苹果": "AAPL",
    "微软": "MSFT",
    "谷歌": "GOOGL",
    "alphabet": "GOOGL",
    "英伟达公司": "NVDA",
    "英伟达": "NVDA",
    "镁光": "MU",
    "美光": "MU",
    "micron": "MU",
    "micron technology": "MU",
    "台积电": "TSM",
    "台灣積體電路": "TSM",
    "台湾积体电路": "TSM",
    "tsmc": "TSM",
    "礼来": "LLY",
    "礼来公司": "LLY",
    "eli lilly": "LLY",
    "拼多多": "PDD",
    "pinduoduo": "PDD",
    "超微半导体": "AMD",
    "特斯拉": "TSLA",
    "商汤科技": "0020.HK",
    "商汤": "0020.HK",
    "第四范式": "6682.HK",
    "腾讯控股": "0700.HK",
    "腾讯": "0700.HK",
    "小米集团": "1810.HK",
    "小米": "1810.HK",
    "美团": "3690.HK",
    "百度集团": "9888.HK",
    "百度": "9888.HK",
    "贵州茅台": "600519.SS",
    "茅台": "600519.SS",
    "宁德时代": "300750.SZ",
    "比亚迪": "002594.SZ",
    "中国平安": "601318.SS",
    "招商银行": "600036.SS",
    "中芯国际": "688981.SS",
}


@dataclass(frozen=True)
class ParsedChatTask:
    """Parsed report request suitable for routing, not for factual evidence."""

    symbol: str
    period: str
    period_kind: str
    research_topic: str
    confidence: float
    should_run: bool
    needs_confirmation: bool
    reason: str
    source: str = "rule"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "period": self.period,
            "period_kind": self.period_kind,
            "research_topic": self.research_topic,
            "confidence": self.confidence,
            "should_run": self.should_run,
            "needs_confirmation": self.needs_confirmation,
            "reason": self.reason,
            "source": self.source,
        }


def parse_chat_task(
    message: str,
    current_symbol: str = "AAPL",
    current_period: str = "2025Q4",
    today: date | None = None,
) -> ParsedChatTask:
    """Parse a chat message into a company report task."""

    text = str(message or "").strip()
    today = today or date.today()
    symbol, symbol_conf, symbol_reason, symbol_needs_confirmation = _parse_symbol(text, current_symbol)
    period, period_kind, period_conf, period_reason = _parse_period(text, current_period, today, symbol=symbol)
    generation_intent = _has_generation_intent(text)
    report_intent = _has_report_intent(text)
    direct_report_request = _looks_like_direct_report_request(text)
    confidence = round(min(0.99, 0.35 + symbol_conf + period_conf + (0.2 if generation_intent and report_intent else 0.0)), 4)
    should_run = bool(
        report_intent
        and bool(symbol)
        and not symbol_needs_confirmation
        and symbol_conf >= 0.25
        and period_conf >= 0.15
        and confidence >= 0.72
        and (generation_intent or direct_report_request)
    )
    needs_confirmation = bool(report_intent and not should_run)
    topic = f"生成 {symbol or 'UNKNOWN'} {period} 公司财报研报"
    reason_parts = [symbol_reason, period_reason]
    if generation_intent and report_intent:
        reason_parts.append("detected generation intent")
    elif direct_report_request and report_intent:
        reason_parts.append("direct report request")
    elif report_intent:
        reason_parts.append("report intent but parameters are incomplete")
    else:
        reason_parts.append("not a report-generation request")
    return ParsedChatTask(
        symbol=symbol,
        period=period,
        period_kind=period_kind,
        research_topic=topic,
        confidence=confidence,
        should_run=should_run,
        needs_confirmation=needs_confirmation,
        reason="; ".join(part for part in reason_parts if part),
    )


def latest_completed_period(today: date | None = None) -> str:
    return _calendar_latest_completed_period(today)


def latest_available_report_period(
    symbol: str = "",
    today: date | None = None,
    raw_data_root: str = "data/raw/real_data",
) -> str:
    """Best-effort latest report period as of ``today``."""

    calendar_period = latest_completed_period(today)
    try:
        from src.data.company_universe import resolve_company_identity

        identity = resolve_company_identity(symbol, raw_data_root=raw_data_root, default=symbol)
        disclosed = str(identity.latest_disclosure_period or "").strip().upper()
    except Exception:
        disclosed = ""
    if re.match(r"^20\d{2}Q[1-4]$", disclosed) and disclosed > calendar_period:
        return disclosed
    return calendar_period


def _parse_symbol(text: str, fallback: str) -> tuple[str, float, str, bool]:
    explicit_exchange_code = re.search(r"(?<![A-Z0-9])(\d{4,6}\.(?:HK|SS|SH|SZ))(?![A-Z0-9])", text.upper())
    if explicit_exchange_code:
        symbol = _normalize_symbol(explicit_exchange_code.group(1))
        return symbol, 0.38, f"recognized explicit exchange ticker {symbol}", False

    bare_cn_code = re.search(r"(?<!\d)([036]\d{5})(?!\d)", text)
    if bare_cn_code:
        symbol = _normalize_symbol(bare_cn_code.group(1))
        return symbol, 0.34, f"recognized A-share code {symbol}", False

    lowered = text.lower()
    for name, symbol in sorted(KNOWN_COMPANY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if name.lower() in lowered:
            return symbol, 0.36, f"recognized alias {name} -> {symbol}", False

    try:
        from src.data.company_universe import resolve_company_identity

        identity = resolve_company_identity(text, default="")
        resolved_symbol = str(identity.canonical_symbol or identity.symbol or "").strip().upper()
        if resolved_symbol:
            if identity.needs_confirmation:
                confidence = max(0.12, min(0.24, float(identity.resolution_confidence) * 0.35))
                return resolved_symbol, confidence, f"identity needs confirmation: {identity.reason}", True
            confidence = max(0.30, min(0.45, float(identity.resolution_confidence) * 0.5))
            return resolved_symbol, confidence, f"identity resolved: {resolved_symbol}", False
    except Exception:
        pass

    explicit = re.search(r"(?<![A-Z0-9])([A-Z]{1,5}(?:\.[A-Z]{1,3})?)(?![A-Z0-9])", text.upper())
    if explicit:
        token = _normalize_symbol(explicit.group(1))
        if token not in {"Q", "AI", "FY", "ANNUAL", "FULL", "YEAR"}:
            return token, 0.2, f"recognized ambiguous ticker token {token}", True

    fallback_symbol = str(fallback or "").strip().upper()
    if fallback_symbol:
        return "", 0.0, f"company unresolved; current context is {fallback_symbol}", True
    return "", 0.0, "company unresolved", True


def _parse_period(text: str, fallback: str, today: date, symbol: str = "") -> tuple[str, str, float, str]:
    if any(term.lower() in text.lower() for term in LATEST_TERMS):
        period = latest_available_report_period(symbol=symbol, today=today)
        return period, "latest", 0.26, f"resolved latest period {period}"
    explicit_period = _parse_explicit_period(text)
    if explicit_period:
        return explicit_period
    lowered = text.lower()
    if any(term.lower() in lowered for term in REPORT_TERMS) and any(term.lower() in lowered for term in GENERATION_TERMS):
        period = latest_available_report_period(symbol=symbol, today=today)
        return period, "latest", 0.20, f"default latest period {period}"
    fallback_period = str(fallback or latest_completed_period(today)).strip().upper()
    return fallback_period, _infer_period_kind(fallback_period), 0.08, f"fallback period {fallback_period}"


def _parse_explicit_period(text: str) -> tuple[str, str, float, str] | None:
    fiscal_year = re.search(r"(?i)(?<![A-Z0-9])FY\s*[-_/]?\s*(20\d{2})(?!\d)", text)
    if fiscal_year:
        period = f"FY{fiscal_year.group(1)}"
        return period, "fiscal_year", 0.28, f"recognized fiscal year {period}"

    explicit_cn = re.search(r"\b(20\d{2}|\d{2})\s*(?:年)?\s*[Qq]\s*([1-4])\b", text)
    if explicit_cn:
        year = explicit_cn.group(1)
        if len(year) == 2:
            year = f"20{year}"
        period = f"{year}Q{explicit_cn.group(2)}"
        return period, "quarter", 0.28, f"recognized quarter {period}"

    explicit = re.search(r"\b(20\d{2})\s*[Qq季]\s*([1-4])\b", text)
    if explicit:
        period = f"{explicit.group(1)}Q{explicit.group(2)}"
        return period, "quarter", 0.28, f"recognized quarter {period}"

    chinese_quarter = _parse_chinese_quarter(text)
    if chinese_quarter:
        return chinese_quarter, "quarter", 0.28, f"recognized chinese quarter {chinese_quarter}"

    annual = _parse_year_only(text)
    if annual:
        return annual, "fiscal_year", 0.24, f"recognized annual period {annual}"

    english_annual = re.search(r"(?i)(?<!\d)(20\d{2})(?!\d).{0,20}\b(?:annual report|full year|fiscal year)\b", text)
    if english_annual:
        period = f"FY{english_annual.group(1)}"
        return period, "fiscal_year", 0.24, f"recognized annual period {period}"
    return None


def _parse_chinese_quarter(text: str) -> str | None:
    year_match = re.search(r"(?<!\d)(20\d{2}|\d{2})\s*年", text)
    if not year_match:
        return None
    quarter_patterns = [
        (1, r"(Q1|一季度|第一季度|1季度|第1季度)"),
        (2, r"(Q2|二季度|第二季度|2季度|第2季度)"),
        (3, r"(Q3|三季度|第三季度|3季度|第3季度)"),
        (4, r"(Q4|四季度|第四季度|4季度|第4季度)"),
    ]
    quarter = None
    for value, pattern in quarter_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            quarter = value
            break
    if quarter is None:
        return None
    return f"{_normalize_year(year_match.group(1))}Q{quarter}"


def _parse_year_only(text: str) -> str | None:
    lowered = str(text or "").lower()
    annual_terms_cn = ("财报", "年报", "年度", "全年", "财年")
    annual_terms_en = ("annual report", "full year", "fiscal year")
    # Also match standalone 20XX / XX + 年 (e.g. "25年 AMD", "2025年") as probable annual intent
    has_annual_term = any(term in text for term in annual_terms_cn) or any(term in lowered for term in annual_terms_en)
    if not has_annual_term:
        # Check for "XX年" or "XXXX年" pattern which implies annual period intent in Chinese
        if not re.search(r"(?<!\d)(20\d{2}|\d{2})\s*年", text) and not re.search(r"\b(20\d{2})(?:'s| fiscal)", lowered):
            return None
    match = re.search(r"(?<!\d)(20\d{2}|\d{2})\s*年?(?!\d)", text)
    if not match:
        return None
    return f"FY{_normalize_year(match.group(1))}"


def _infer_period_kind(period: str) -> str:
    value = str(period or "").strip().upper()
    if re.match(r"^FY20\d{2}$", value):
        return "fiscal_year"
    if re.match(r"^20\d{2}Q[1-4]$", value):
        return "quarter"
    return "latest"


def _normalize_symbol(raw: str) -> str:
    symbol = str(raw or "").strip().upper()
    hk = re.fullmatch(r"(\d{1,5})\.HK", symbol)
    if hk:
        return f"{hk.group(1).zfill(4)}.HK"
    cn = re.fullmatch(r"([036]\d{5})(?:\.(SS|SH|SZ))?", symbol)
    if cn:
        code = cn.group(1)
        suffix = ".SS" if code.startswith("6") else ".SZ"
        return f"{code}{suffix}"
    return symbol


def _normalize_year(raw: str) -> int:
    year = int(raw)
    if year < 100:
        return 2000 + year
    return year


def _looks_like_direct_report_request(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    if not normalized:
        return False
    question_terms = ("?", "？", "怎么", "如何", "吗", "呢", "是什么")
    if any(term in normalized for term in question_terms):
        return False
    report_terms = ("财报", "研报", "报告", "年报", "季报", "financialreport", "companyreport", "quarterlyreport", "annualreport")
    if not any(term in normalized for term in report_terms):
        return False
    return bool(
        re.search(r"(20\d{2}|\d{2})\s*(?:年)?\s*[qQ]\s*[1-4]", str(text or ""))
        or re.search(r"(20\d{2}|\d{2})\s*(?:年)?\s*(?:第)?[一二三四1234]\s*(?:季|季度)", str(text or ""))
    )


def _has_report_intent(text: str) -> bool:
    lowered = text.lower()
    if any(term.lower() in lowered for term in REPORT_TERMS):
        return True
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    return any(term in normalized for term in ("财报", "研报", "报告", "年报", "季报"))


def _has_generation_intent(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in GENERATION_TERMS)


def llm_parse_chat_task(
    message: str,
    current_symbol: str = "AAPL",
    current_period: str = "2025Q4",
    today: date | None = None,
    config_path: str | Path = "configs/model_backends.yaml",
) -> ParsedChatTask:
    """Use the LLM to parse a chat message into a report task."""

    text = str(message or "").strip()
    if not text:
        return ParsedChatTask(
            symbol=current_symbol,
            period=current_period,
            period_kind=_infer_period_kind(current_period),
            research_topic="",
            confidence=0.0,
            should_run=False,
            needs_confirmation=False,
            reason="empty message",
            source="llm",
        )

    today = today or date.today()
    rule_task = parse_chat_task(message, current_symbol, current_period, today)
    has_report_terms = _has_report_intent(text)
    has_gen_terms = _has_generation_intent(text)
    if not has_report_terms and not has_gen_terms:
        return rule_task

    system_prompt = (
        "You are a precise intent parser for a financial report system. "
        "Extract structured data from user messages about stock research reports.\n\n"
        "Output a JSON object with:\n"
        '- "symbol": stock ticker (e.g., "NVDA", "600519.SS", "0700.HK", "AMD", "AAPL"). Empty string if unknown.\n'
        '- "period": reporting period like "2025Q4", "FY2024", or "2026Q1". Empty string if not specified.\n'
        '- "period_kind": one of "fiscal_year", "quarter", "latest".\n'
        '- "wants_latest": boolean, true if user implies latest/most recent.\n'
        '- "generation_intent": boolean, true if user wants to GENERATE a report.\n'
        '- "report_intent": boolean, true if request is about financial reports.\n'
        '- "confidence": number 0.0-1.0.\n'
        '- "reason": short explanation.'
    )
    user_prompt = (
        f"Context: current_symbol={current_symbol}, current_period={current_period}, today={today.isoformat()}\n"
        f"Message: {text}\n\n"
        "Extract task parameters as JSON."
    )

    try:
        profile = _resolve_task_parser_profile(str(config_path))
        adapter = ModelAdapter.from_profile(profile=profile, config_path=config_path, fallback_section="agent_model")
        adapter.max_tokens = 512
        adapter.temperature = 0.0
        adapter.timeout = 15.0
        result = adapter.generate_json(prompt=user_prompt, system_prompt=system_prompt)
        if not isinstance(result, dict):
            raise RuntimeError(f"expected dict, got {type(result).__name__}")

        routed_symbol, routed_symbol_conf, routed_symbol_note, routed_symbol_needs_confirmation = _parse_symbol(text, current_symbol)
        raw_symbol = str(result.get("symbol") or "").strip().upper()
        if routed_symbol:
            symbol = routed_symbol
            symbol_note = routed_symbol_note
            symbol_needs_confirmation = routed_symbol_needs_confirmation
            symbol_conf = routed_symbol_conf
        elif raw_symbol:
            symbol, symbol_conf, symbol_note, symbol_needs_confirmation = _parse_symbol(raw_symbol, "")
        else:
            symbol = ""
            symbol_conf = 0.0
            symbol_needs_confirmation = True
            symbol_note = "company unresolved"

        raw_period = str(result.get("period") or "").strip().upper()
        raw_period_kind = str(result.get("period_kind") or "").strip().lower()
        wants_latest = bool(result.get("wants_latest", False))
        has_latest_text = any(term.lower() in text.lower() for term in LATEST_TERMS)
        explicit_period = None if has_latest_text else _parse_explicit_period(text)
        if explicit_period:
            period, period_kind, _, period_note = explicit_period
        elif re.match(r"^FY20\d{2}$", raw_period):
            period = raw_period
            period_kind = "fiscal_year"
            period_note = f"LLM period {period}"
        elif re.match(r"^20\d{2}Q[1-4]$", raw_period):
            period = raw_period
            period_kind = "quarter"
            period_note = f"LLM period {period}"
        elif wants_latest or raw_period_kind == "latest":
            period = latest_available_report_period(symbol=symbol or current_symbol, today=today)
            period_kind = "latest"
            period_note = f"LLM latest period {period}"
        else:
            period = rule_task.period
            period_kind = rule_task.period_kind
            period_note = f"rule period {period}"

        direct_report_request = _looks_like_direct_report_request(text)
        generation_intent = bool(result.get("generation_intent", False)) or _has_generation_intent(text)
        report_intent = bool(result.get("report_intent", False)) or _has_report_intent(text) or direct_report_request
        confidence = min(0.99, float(result.get("confidence", 0.0)))
        if direct_report_request:
            confidence = max(confidence, 0.82)
        if rule_task.should_run:
            confidence = max(confidence, rule_task.confidence)
        llm_reason = str(result.get("reason", "")).strip()

        should_run = bool(
            report_intent
            and bool(symbol)
            and not symbol_needs_confirmation
            and symbol_conf >= 0.25
            and confidence >= 0.68
            and (generation_intent or direct_report_request)
        )
        needs_confirmation = bool(report_intent and not should_run)
        topic = f"生成 {symbol or 'UNKNOWN'} {period} 公司财报研报"

        reason_parts = [symbol_note, period_note]
        if should_run:
            reason_parts.append(f"LLM run (confidence={confidence:.2f})")
        elif llm_reason:
            reason_parts.append(llm_reason)
        else:
            reason_parts.append("LLM not confident to run directly")

        return ParsedChatTask(
            symbol=symbol,
            period=period,
            period_kind=period_kind,
            research_topic=topic,
            confidence=round(confidence, 4),
            should_run=should_run,
            needs_confirmation=needs_confirmation,
            reason="; ".join(part for part in reason_parts if part),
            source="llm",
        )

    except Exception as exc:
        parsed = parse_chat_task(message, current_symbol, current_period, today)
        return ParsedChatTask(
            symbol=parsed.symbol,
            period=parsed.period,
            period_kind=parsed.period_kind,
            research_topic=parsed.research_topic,
            confidence=round(parsed.confidence * 0.85, 4),
            should_run=parsed.should_run,
            needs_confirmation=parsed.needs_confirmation,
            reason=f"{parsed.reason}; llm parser exception fallback: {exc}",
            source="rule_fallback",
        )


def _resolve_task_parser_profile(config_path: str) -> str:
    config = load_config(config_path)
    routes = config.get("agent_model_routes") if isinstance(config, dict) else {}
    defaults = routes.get("defaults", {}) if isinstance(routes, dict) and isinstance(routes.get("defaults"), dict) else {}
    route = routes.get("task_parser") if isinstance(routes, dict) else None
    if isinstance(route, dict):
        return str(route.get("delivery") or route.get("preview") or defaults.get("delivery") or "flash")
    if isinstance(route, str):
        return route
    return str(defaults.get("delivery") or "flash")
