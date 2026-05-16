"""Natural-language task parsing for the chat-first workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any, Dict


REPORT_TERMS = ("研报", "财报", "报告", "research report", "company report")
GENERATION_TERMS = ("生成", "写", "撰写", "出一份", "做一份", "最新", "run", "create", "write")
LATEST_TERMS = ("最新财报", "最新", "最近", "latest")


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
    period, period_conf, period_reason = _parse_period(text, current_period, today)
    generation_intent = _has_generation_intent(text)
    report_intent = _has_report_intent(text)
    confidence = round(min(0.99, 0.35 + symbol_conf + period_conf + (0.2 if generation_intent and report_intent else 0.0)), 4)
    should_run = bool(generation_intent and report_intent and symbol_conf >= 0.25 and period_conf >= 0.15 and confidence >= 0.72)
    needs_confirmation = bool(report_intent and not should_run)
    topic = f"生成 {symbol} {period} 公司财报研报"
    reason_parts = [symbol_reason, period_reason]
    if generation_intent and report_intent:
        reason_parts.append("明确生成研报意图")
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
    today = today or date.today()
    if today.month <= 3:
        return f"{today.year - 1}Q4"
    if today.month <= 6:
        return f"{today.year}Q1"
    if today.month <= 9:
        return f"{today.year}Q2"
    return f"{today.year}Q3"


def _parse_symbol(text: str, fallback: str) -> tuple[str, float, str]:
    compact = text.upper().replace(" ", "")
    if "贵州茅台" in text or "茅台" in text or "600519" in compact:
        return "600519.SS", 0.34, "识别到贵州茅台/600519"
    if re.search(r"\bAMD\b", text, flags=re.IGNORECASE):
        return "AMD", 0.34, "识别到 AMD"
    explicit = re.search(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b", text.upper())
    if explicit:
        token = explicit.group(1)
        if token not in {"Q", "AI"}:
            return token, 0.28, f"识别到股票代码 {token}"
    cn_code = re.search(r"(?<!\d)([036]\d{5})(?!\d)", text)
    if cn_code:
        return f"{cn_code.group(1)}.SS", 0.28, f"识别到 A 股代码 {cn_code.group(1)}"
    fallback_symbol = str(fallback or "AAPL").strip().upper()
    return fallback_symbol, 0.08, f"沿用当前标的 {fallback_symbol}"


def _parse_period(text: str, fallback: str, today: date) -> tuple[str, float, str]:
    explicit = re.search(r"\b(20\d{2})\s*[Qq季]\s*([1-4])\b", text)
    if explicit:
        period = f"{explicit.group(1)}Q{explicit.group(2)}"
        return period, 0.28, f"识别到显式期间 {period}"
    if any(term.lower() in text.lower() for term in LATEST_TERMS):
        period = latest_completed_period(today)
        return period, 0.24, f"按当前日期选择最近已结束期间 {period}"
    fallback_period = str(fallback or latest_completed_period(today)).strip().upper()
    return fallback_period, 0.08, f"沿用当前期间 {fallback_period}"


def _has_report_intent(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in REPORT_TERMS)


def _has_generation_intent(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in GENERATION_TERMS)
