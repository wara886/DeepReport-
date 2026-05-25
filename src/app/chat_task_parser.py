"""Natural-language task parsing for the chat-first workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from logging import getLogger
from pathlib import Path
import re
from typing import Any, Dict

from src.models.model_adapter import ModelAdapter
from src.utils.periods import latest_completed_period as _calendar_latest_completed_period

logger = getLogger(__name__)


REPORT_TERMS = ("研报", "财报", "报告", "research report", "company report", "annual report", "quarterly report")
GENERATION_TERMS = ("生成", "写", "撰写", "出一份", "做一份", "最新", "run", "create", "write", "generate")
LATEST_TERMS = ("最新财报", "最新", "最近", "latest", "most recent")
KNOWN_COMPANY_ALIASES = {
    "\u82f9\u679c\u516c\u53f8": "AAPL",
    "\u82f9\u679c": "AAPL",
    "\u5fae\u8f6f": "MSFT",
    "\u8c37\u6b4c": "GOOGL",
    "alphabet": "GOOGL",
    "\u82f1\u4f1f\u8fbe\u516c\u53f8": "NVDA",
    "\u82f1\u4f1f\u8fbe": "NVDA",
    "\u8d85\u5fae\u534a\u5bfc\u4f53": "AMD",
    "\u7279\u65af\u62c9": "TSLA",
    "\u5546\u6c64\u79d1\u6280": "0020.HK",
    "\u5546\u6c64": "0020.HK",
    "\u7b2c\u56db\u8303\u5f0f": "6682.HK",
    "\u817e\u8baf\u63a7\u80a1": "0700.HK",
    "\u817e\u8baf": "0700.HK",
    "\u5c0f\u7c73\u96c6\u56e2": "1810.HK",
    "\u5c0f\u7c73": "1810.HK",
    "\u7f8e\u56e2": "3690.HK",
    "\u767e\u5ea6\u96c6\u56e2": "9888.HK",
    "\u767e\u5ea6": "9888.HK",
    "\u8d35\u5dde\u8305\u53f0": "600519.SS",
    "\u8305\u53f0": "600519.SS",
    "\u5b81\u5fb7\u65f6\u4ee3": "300750.SZ",
    "\u6bd4\u4e9a\u8fea": "002594.SZ",
    "\u4e2d\u56fd\u5e73\u5b89": "601318.SS",
    "\u62db\u5546\u94f6\u884c": "600036.SS",
    "\u4e2d\u82af\u56fd\u9645": "688981.SS",
}


@dataclass(frozen=True)
class ParsedChatTask:
    """Parsed report request suitable for routing, not for factual evidence."""

    symbol: str
    period: str
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
    """Parse a chat message into a company report task.

    The parser only infers routing parameters. It must not be used as evidence
    for report facts.
    """

    text = str(message or "").strip()
    today = today or date.today()
    symbol, symbol_conf, symbol_reason = _parse_symbol(text, current_symbol)
    period, period_conf, period_reason = _parse_period(text, current_period, today, symbol=symbol)
    generation_intent = _has_generation_intent(text)
    report_intent = _has_report_intent(text)
    direct_report_request = _looks_like_direct_report_request(text)
    confidence = round(min(0.99, 0.35 + symbol_conf + period_conf + (0.2 if generation_intent and report_intent else 0.0)), 4)
    should_run = bool(
        report_intent
        and symbol_conf >= 0.25
        and period_conf >= 0.15
        and confidence >= 0.72
        and (generation_intent or direct_report_request)
    )
    needs_confirmation = bool(report_intent and not should_run)
    topic = f"生成 {symbol} {period} 公司财报研报"
    reason_parts = [symbol_reason, period_reason]
    if generation_intent and report_intent:
        reason_parts.append("明确生成研报意图")
    elif direct_report_request and report_intent:
        reason_parts.append("完整报告请求，直接生成")
    elif report_intent:
        reason_parts.append("提到研报但参数或生成意图不足")
    else:
        reason_parts.append("未识别为研报生成任务")
    return ParsedChatTask(
        symbol=symbol,
        period=period,
        research_topic=topic,
        confidence=confidence,
        should_run=should_run,
        needs_confirmation=needs_confirmation,
        reason="；".join(part for part in reason_parts if part),
    )


def latest_completed_period(today: date | None = None) -> str:
    return _calendar_latest_completed_period(today)


def latest_available_report_period(
    symbol: str = "",
    today: date | None = None,
    raw_data_root: str = "data/raw/real_data",
) -> str:
    """Best-effort latest report period as of ``today``.

    Without paid APIs this uses the calendar completed quarter as the upper
    bound and lets local company profiles override only when they are newer.
    """

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


def _parse_symbol(text: str, fallback: str) -> tuple[str, float, str]:
    explicit_exchange_code = re.search(r"(?<![A-Z0-9])(\d{4,6}\.(?:HK|SS|SH|SZ))(?![A-Z0-9])", text.upper())
    if explicit_exchange_code:
        symbol = _normalize_symbol(explicit_exchange_code.group(1))
        return symbol, 0.38, f"识别到完整股票代码 {symbol}"

    bare_cn_code = re.search(r"(?<!\d)([036]\d{5})(?!\d)", text)
    if bare_cn_code:
        symbol = _normalize_symbol(bare_cn_code.group(1))
        return symbol, 0.34, f"识别到 A 股代码 {symbol}"

    lowered = text.lower()
    for name, symbol in sorted(KNOWN_COMPANY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if name.lower() in lowered:
            return symbol, 0.36, f"识别到公司名称 {name} -> {symbol}"

    explicit = re.search(r"(?<![A-Z0-9])([A-Z]{1,5}(?:\.[A-Z]{1,3})?)(?![A-Z0-9])", text.upper())
    if explicit:
        token = _normalize_symbol(explicit.group(1))
        if token not in {"Q", "AI", "FY", "ANNUAL", "FULL", "YEAR"}:
            return token, 0.28, f"识别到股票代码 {token}"
    fallback_symbol = str(fallback or "AAPL").strip().upper()
    return fallback_symbol, 0.08, f"沿用当前标的 {fallback_symbol}"


def _parse_period(text: str, fallback: str, today: date, symbol: str = "") -> tuple[str, float, str]:
    explicit_period = _parse_explicit_period(text)
    if explicit_period:
        return explicit_period
    if any(term.lower() in text.lower() for term in LATEST_TERMS):
        period = latest_available_report_period(symbol=symbol, today=today)
        return period, 0.24, f"按当前日期选择最新可生成报告期 {period}"
    # Implicit latest: report+generation intent but no period specified
    lowered = text.lower()
    if any(term.lower() in lowered for term in REPORT_TERMS) and any(
        term.lower() in lowered for term in GENERATION_TERMS
    ):
        period = latest_available_report_period(symbol=symbol, today=today)
        return period, 0.20, f"研报意图但未指定期间，默认最新可生成报告期 {period}"
    fallback_period = str(fallback or latest_completed_period(today)).strip().upper()
    return fallback_period, 0.08, f"沿用当前期间 {fallback_period}"


def _parse_explicit_period(text: str) -> tuple[str, float, str] | None:
    fiscal_year = re.search(r"(?i)(?<![A-Z0-9])FY\s*[-_/]?\s*(20\d{2})(?!\d)", text)
    if fiscal_year:
        period = f"{fiscal_year.group(1)}Q4"
        return period, 0.28, f"识别到财年 FY{fiscal_year.group(1)}，按年度报告期映射为 {period}"
    explicit_cn = re.search(r"\b(20\d{2}|\d{2})\s*(?:\u5e74)?\s*[Qq]\s*([1-4])\b", text)
    if explicit_cn:
        year = explicit_cn.group(1)
        if len(year) == 2:
            year = f"20{year}"
        period = f"{year}Q{explicit_cn.group(2)}"
        return period, 0.28, f"识别到显式期间 {period}"
    explicit = re.search(r"\b(20\d{2})\s*[Qq季]\s*([1-4])\b", text)
    if explicit:
        period = f"{explicit.group(1)}Q{explicit.group(2)}"
        return period, 0.28, f"识别到显式期间 {period}"
    chinese_quarter = _parse_chinese_quarter(text)
    if chinese_quarter:
        return chinese_quarter, 0.28, f"识别到中文期间 {chinese_quarter}"
    annual = _parse_year_only(text)
    if annual:
        return annual, 0.24, f"识别到年度财报口径 {annual}"
    english_annual = re.search(r"(?i)(?<!\d)(20\d{2})(?!\d).{0,20}\b(?:annual report|full year|fiscal year)\b", text)
    if english_annual:
        period = f"{english_annual.group(1)}Q4"
        return period, 0.24, f"识别到年度报告口径 {period}"
    return None


def _parse_chinese_quarter(text: str) -> str | None:
    year_match = re.search(r"(?<!\d)(20\d{2}|\d{2})\s*年", text)
    if not year_match:
        return None
    quarter_patterns = [
        (1, r"(Q1|一季度|第一季度|1季度|第1季度)"),
        (2, r"(Q2|二季度|第二季度|2季度|第2季度)"),
        (3, r"(Q3|三季度|第三季度|3季度|第3季度)"),
        (4, r"(Q4|四季度|第四季度|4季度|第4季度|年报|全年|年度|财报)"),
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
    if not any(term in text for term in ("财报", "年报", "年度", "全年")):
        return None
    match = re.search(r"(?<!\d)(20\d{2}|\d{2})\s*年", text)
    if not match:
        return None
    return f"{_normalize_year(match.group(1))}Q4"


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
    question_terms = (
        "?",
        "\uff1f",
        "\u600e\u4e48",
        "\u5982\u4f55",
        "\u5417",
        "\u5462",
        "\u662f\u4ec0\u4e48",
    )
    if any(term in normalized for term in question_terms):
        return False
    report_terms = (
        "\u8d22\u62a5",
        "\u7814\u62a5",
        "\u62a5\u544a",
        "\u5e74\u62a5",
        "\u5b63\u62a5",
        "financialreport",
        "companyreport",
        "quarterlyreport",
        "annualreport",
    )
    if not any(term in normalized for term in report_terms):
        return False
    return bool(
        re.search(r"(20\d{2}|\d{2})\s*(?:\u5e74)?\s*[qQ]\s*[1-4]", str(text or ""))
        or re.search(r"(20\d{2}|\d{2})\s*(?:\u5e74)?\s*(?:\u7b2c)?[一二三四1234]\s*(?:\u5b63|\u5b63\u5ea6)", str(text or ""))
    )


def _has_report_intent(text: str) -> bool:
    lowered = text.lower()
    if any(term.lower() in lowered for term in REPORT_TERMS):
        return True
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    return any(
        term in normalized
        for term in (
            "\u8d22\u62a5",
            "\u7814\u62a5",
            "\u62a5\u544a",
            "\u5e74\u62a5",
            "\u5b63\u62a5",
        )
    )


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
    """Use the LLM to parse a chat message into a report task.

    Falls back to the rule-based ``parse_chat_task`` when the LLM call fails
    or returns incomplete results.
    """
    text = str(message or "").strip()
    if not text:
        return ParsedChatTask(
            symbol=current_symbol,
            period=current_period,
            research_topic="",
            confidence=0.0,
            should_run=False,
            needs_confirmation=False,
            reason="empty message",
            source="llm",
        )

    today = today or date.today()
    rule_task = parse_chat_task(message, current_symbol, current_period, today)

    # Fast path: skip LLM call if message clearly has no report intent at all
    lowered = text.lower()
    has_report_terms = _has_report_intent(text)
    has_gen_terms = _has_generation_intent(text)
    if not has_report_terms and not has_gen_terms:
        return parse_chat_task(message, current_symbol, current_period, today)

    system_prompt = (
        "You are a precise intent parser for a financial report system. "
        "Extract structured data from user messages about stock research reports.\n\n"
        "Output a JSON object with:\n"
        '- "symbol": stock ticker (e.g., "NVDA", "600519.SS", "0700.HK", "AMD", "AAPL"). '
        "For Chinese company names use the correct ticker. Empty string if unknown.\n"
        '- "period": reporting period like "2025Q4" or "2026Q1". Map "FY2024" and a year-only annual report request to "2024Q4". Empty string if not specified.\n'
        '- "wants_latest": boolean, true if user implies latest/most recent\n'
        '- "generation_intent": boolean, true if user wants to GENERATE a report\n'
        '- "report_intent": boolean, true if about financial reports\n'
        '- "confidence": number 0.0-1.0 reflecting your certainty\n'
        '- "reason": short explanation of your parsing'
    )

    user_prompt = (
        f"Context: current_symbol={current_symbol}, current_period={current_period}, today={today.isoformat()}\n"
        f"Message: {text}\n\n"
        "Extract task parameters as JSON."
    )

    try:
        adapter = ModelAdapter.from_config(config_path=config_path, section="agent_model")
        adapter.max_tokens = 512
        adapter.temperature = 0.0
        adapter.timeout = 15.0

        result = adapter.generate_json(prompt=user_prompt, system_prompt=system_prompt)
        if not isinstance(result, dict):
            raise RuntimeError(f"expected dict, got {type(result).__name__}")

        # ── symbol ───────────────────────────────────────────────────────
        routed_symbol, routed_symbol_conf, routed_symbol_note = _parse_symbol(text, current_symbol)
        raw_symbol = str(result.get("symbol") or "").strip().upper()
        if routed_symbol_conf >= 0.25:
            symbol = routed_symbol
            symbol_note = routed_symbol_note
        elif not raw_symbol:
            symbol = _normalize_symbol(current_symbol)
            symbol_note = f"LLM未识别到公司，沿用当前标的 {symbol}"
        else:
            symbol = _normalize_symbol(raw_symbol)
            symbol_note = f"LLM识别标的 {symbol}"

        # ── period ───────────────────────────────────────────────────────
        raw_period = str(result.get("period") or "").strip().upper()
        wants_latest = bool(result.get("wants_latest", False))
        explicit_period = _parse_explicit_period(text)

        if explicit_period:
            period, _, period_note = explicit_period
        elif re.match(r"^20\d{2}Q[1-4]$", raw_period):
            period = raw_period
            period_note = f"LLM识别期间 {period}"
        elif wants_latest:
            period = latest_available_report_period(symbol=symbol, today=today)
            period_note = f"LLM识别到最新意图，使用最新可生成报告期 {period}"
        else:
            explicit = re.search(r"\b(20\d{2})\s*[Qq季]\s*([1-4])\b", text)
            if explicit:
                period = f"{explicit.group(1)}Q{explicit.group(2)}"
                period_note = f"正则补充识别期间 {period}"
            else:
                # Year-only mention: "2025年腾讯的财报" → 2025Q4 (annual)
                year_only = re.search(r"(20\d{2})\s*[年年内]", text)
                if year_only:
                    period = f"{year_only.group(1)}Q4"
                    period_note = f"识别到年份{year_only.group(1)}年，默认完整财年Q4"
                else:
                    period = latest_available_report_period(symbol=symbol, today=today)
                    period_note = f"LLM未指定期间，默认最新可生成报告期 {period}"

        # ── intent & confidence ──────────────────────────────────────────
        direct_report_request = _looks_like_direct_report_request(text)
        generation_intent = bool(result.get("generation_intent", False)) or _has_generation_intent(text)
        report_intent = bool(result.get("report_intent", False)) or _has_report_intent(text) or direct_report_request
        confidence = min(0.99, float(result.get("confidence", 0.0)))
        if direct_report_request:
            confidence = max(confidence, 0.82)
        if rule_task.should_run:
            confidence = max(confidence, rule_task.confidence)
        llm_reason = str(result.get("reason", "")).strip()

        should_run = bool(report_intent and confidence >= 0.68 and (generation_intent or direct_report_request))
        needs_confirmation = bool(report_intent and not should_run and confidence >= 0.3)
        topic = f"生成 {symbol} {period} 公司财报研报"

        reason_parts = [symbol_note, period_note]
        if should_run:
            reason_parts.append(f"LLM意图识别为生成研报（置信度{confidence}）")
        elif llm_reason:
            reason_parts.append(llm_reason)
        else:
            reason_parts.append("LLM未识别到生成研报意图")

        return ParsedChatTask(
            symbol=symbol,
            period=period,
            research_topic=topic,
            confidence=round(confidence, 4),
            should_run=should_run,
            needs_confirmation=needs_confirmation,
            reason="；".join(reason_parts),
            source="llm",
        )

    except Exception as exc:
        parsed = parse_chat_task(message, current_symbol, current_period, today)
        return ParsedChatTask(
            symbol=parsed.symbol,
            period=parsed.period,
            research_topic=parsed.research_topic,
            confidence=round(parsed.confidence * 0.85, 4),
            should_run=parsed.should_run,
            needs_confirmation=parsed.needs_confirmation,
            reason=f"{parsed.reason}（LLM解析异常，规则兜底：{exc}）",
            source="rule_fallback",
        )
