"""Market-aware report period options and disclosure readiness."""

from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any

from src.data.company_universe import infer_market_from_symbol
from src.utils.periods import period_target_date, previous_completed_quarter


PERIOD_PATTERN = re.compile(r"^(?:FY\d{4}|\d{4}Q[1-4])$", re.I)


def report_period_options(*, symbol: str = "", period: str = "", as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    normalized_symbol = str(symbol or "").strip().upper()
    market_meta = infer_market_from_symbol(normalized_symbol)
    market = market_meta.get("market", "unknown")
    quarter_year, quarter = previous_completed_quarter(as_of)
    quarters = _recent_quarters(quarter_year, quarter, count=8)
    fiscal_years = [f"FY{as_of.year - offset}" for offset in range(1, 6)]
    values = quarters + fiscal_years
    options = [
        {
            "value": value,
            "label": _period_label(value, latest_quarter=quarters[0], latest_year=fiscal_years[0]),
            "kind": "quarter" if "Q" in value else "fiscal_year",
            "readiness": disclosure_readiness(market=market, period=value, as_of=as_of),
        }
        for value in values
    ]
    target = str(period or quarters[0]).strip().upper()
    return {
        "schema_version": "report_period_options.v1",
        "symbol": normalized_symbol,
        "market": market,
        "exchange": market_meta.get("exchange", ""),
        "as_of_date": as_of.isoformat(),
        "market_data_as_of": as_of.isoformat(),
        "latest_completed_quarter": quarters[0],
        "latest_fiscal_year": fiscal_years[0],
        "custom_period_supported": True,
        "options": options,
        "selected": {
            "period": target,
            "valid": bool(PERIOD_PATTERN.fullmatch(target)),
            "readiness": disclosure_readiness(market=market, period=target, as_of=as_of),
        },
    }


def disclosure_readiness(*, market: str, period: str, as_of: date) -> dict[str, Any]:
    normalized = str(period or "").strip().upper()
    if not PERIOD_PATTERN.fullmatch(normalized):
        return _readiness(False, "invalid", None, "期间格式应为 FY2025 或 2026Q2。", market)
    available_from, reason = _expected_available_date(market=market, period=normalized)
    if available_from is None:
        return _readiness(False, "not_standard", None, reason, market)
    available = as_of >= available_from
    status = "available" if available else "scheduled"
    message = "按市场法定披露窗口，官方披露应已可用。" if available else f"官方披露预计不早于 {available_from.isoformat()}。"
    if reason:
        message = f"{message}{reason}"
    return _readiness(available, status, available_from, message, market)


def _expected_available_date(*, market: str, period: str) -> tuple[date | None, str]:
    annual = re.fullmatch(r"FY(\d{4})", period)
    if annual:
        year = int(annual.group(1))
        delay = 120 if market == "us" else 120
        return date(year, 12, 31) + timedelta(days=delay), " 实际日期仍受发行人财年结束日影响。" if market == "us" else ""
    target = period_target_date(period)
    if target is None:
        return None, "无法识别目标期间。"
    quarter = int(period[-1])
    if market == "cn_a":
        fixed = {1: date(target.year, 4, 30), 2: date(target.year, 8, 31), 3: date(target.year, 10, 31), 4: date(target.year + 1, 4, 30)}
        return fixed[quarter], ""
    if market == "hk":
        if quarter in {1, 3}:
            return None, "港股通常不强制披露第一、第三季度报告，请改用中期或年度期间。"
        return (date(target.year, 9, 30), "") if quarter == 2 else (date(target.year + 1, 4, 30), "")
    delay = 90 if quarter == 4 else 45
    return target + timedelta(days=delay), " 实际日期仍受发行人财年结束日影响。" if market == "us" else ""


def _readiness(available: bool, status: str, available_from: date | None, reason: str, market: str) -> dict[str, Any]:
    source = {"cn_a": "交易所/巨潮公告", "hk": "港交所披露", "us": "SEC EDGAR"}.get(market, "官方披露渠道")
    return {
        "official_disclosure_available": available,
        "status": status,
        "available_from": available_from.isoformat() if available_from else None,
        "reason": reason,
        "expected_official_source": source,
    }


def _recent_quarters(year: int, quarter: int, *, count: int) -> list[str]:
    rows: list[str] = []
    for _ in range(count):
        rows.append(f"{year}Q{quarter}")
        quarter -= 1
        if quarter == 0:
            year -= 1
            quarter = 4
    return rows


def _period_label(value: str, *, latest_quarter: str, latest_year: str) -> str:
    if value == latest_quarter:
        return f"{value}（最近完整季度）"
    if value == latest_year:
        return f"{value}（最近年度）"
    return value
