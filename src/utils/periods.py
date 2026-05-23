"""Shared report-period helpers.

These helpers are routing and validation utilities. They are not evidence for
financial facts.
"""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Dict


def parse_quarter(value: str) -> tuple[str, str] | None:
    match = re.search(r"(\d{4})\s*Q([1-4])", str(value or ""), flags=re.I)
    if not match:
        return None
    return match.group(1), f"Q{match.group(2)}"


def period_target_date(period: str) -> date | None:
    parsed = parse_quarter(period)
    if not parsed:
        return None
    year = int(parsed[0])
    return {
        "Q1": date(year, 3, 31),
        "Q2": date(year, 6, 30),
        "Q3": date(year, 9, 30),
        "Q4": date(year, 12, 31),
    }.get(parsed[1])


def parse_iso_date(raw: Any) -> date | None:
    try:
        return datetime.strptime(str(raw or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def period_match(period: str, report_date: str = "", raw: Dict[str, Any] | None = None, max_day_delta: int = 45) -> bool | None:
    """Return whether a source row belongs to a target report period.

    Prefer explicit SEC fiscal year/period fields when available. Otherwise use
    a bounded calendar-quarter date window. This deliberately avoids accepting
    every January-March row as Q1; fiscal-year companies must be matched through
    explicit ``fy``/``fp`` metadata or the date window.
    """

    target = parse_quarter(period)
    if not target:
        return True
    raw = raw or {}
    fy = str(raw.get("fy") or raw.get("fiscal_year") or "").strip()
    fp = str(raw.get("fp") or raw.get("fiscal_period") or "").strip().upper()
    if fy and fp:
        if fp == "FY":
            return target[1] == "Q4" and fy == target[0]
        if fp.startswith("Q") and fp[1:] in {"1", "2", "3", "4"}:
            return (fy, fp) == target

    target_date = period_target_date(period)
    source_date = parse_iso_date(report_date or raw.get("end") or raw.get("report_date") or raw.get("date"))
    if target_date and source_date:
        return abs((source_date - target_date).days) <= max_day_delta
    return None


def latest_completed_period(today: date | None = None) -> str:
    today = today or date.today()
    if today.month <= 3:
        return f"{today.year - 1}Q4"
    if today.month <= 6:
        return f"{today.year}Q1"
    if today.month <= 9:
        return f"{today.year}Q2"
    return f"{today.year}Q3"


def previous_completed_quarter(today: date) -> tuple[int, int]:
    if today.month <= 3:
        return today.year - 1, 4
    if today.month <= 6:
        return today.year, 1
    if today.month <= 9:
        return today.year, 2
    return today.year, 3


def period_is_finished(period: str, today: date | None = None) -> bool | None:
    target_date = period_target_date(period)
    if not target_date:
        return None
    return target_date < (today or date.today())
