"""Evidence intake gates before official evidence is indexed or delivered."""

from __future__ import annotations

import re
from typing import Any

from src.data.company_universe import resolve_company_identifier


IDENTITY_GATED_SOURCE_TYPES = {
    "cninfo_announcement",
    "exchange_announcement",
    "hkex_announcement",
    "hkex_annual_report",
    "pdf_section",
    "pdf_statement_table",
}

PERIOD_GATED_SOURCE_TYPES = IDENTITY_GATED_SOURCE_TYPES | {
    "sec_companyfacts",
    "sec_filing",
    "market_api",
    "yahoo_finance",
    "yahoo_financials",
    "eastmoney_financials",
    "hk_financials",
    "pdf_statement_table",
}

IDENTITY_STOPWORDS = {
    "holding",
    "holdings",
    "limited",
    "ltd",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "group",
    "international",
    "股份有限公司",
    "有限公司",
}


def filter_evidence_records(
    records: list[dict[str, Any]],
    *,
    symbol: str,
    period: str,
    stage: str,
    trusted_parent_evidence_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for record in records:
        reason = evidence_rejection_reason(
            record,
            symbol=symbol,
            period=period,
            trusted_parent_evidence_ids=trusted_parent_evidence_ids or set(),
        )
        if reason:
            rejected.append(rejection_record(record, reason=reason, stage=stage))
            continue
        accepted.append(record)
    return accepted, rejected


def evidence_rejection_reason(
    record: dict[str, Any],
    *,
    symbol: str,
    period: str,
    trusted_parent_evidence_ids: set[str] | None = None,
) -> str:
    source_type = str(record.get("source_type") or "").strip().lower()
    parent_id = source_parent_evidence_id(record)
    inherits_trusted_parent = bool(parent_id and parent_id in (trusted_parent_evidence_ids or set()))
    if (
        source_type in IDENTITY_GATED_SOURCE_TYPES
        and not inherits_trusted_parent
        and not record_mentions_target_company(record, symbol=symbol)
    ):
        return "target_company_mismatch"
    if source_type in PERIOD_GATED_SOURCE_TYPES and record_period_status(record, target_period=period) == "mismatch":
        return "source_period_mismatch"
    return ""


def source_parent_evidence_id(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return str(
        record.get("source_evidence_id")
        or metadata.get("source_evidence_id")
        or record.get("parent_evidence_id")
        or metadata.get("parent_evidence_id")
        or ""
    )


def record_mentions_target_company(record: dict[str, Any], *, symbol: str) -> bool:
    terms = identity_terms(symbol)
    if not terms:
        return True
    text = " ".join(
        [
            str(record.get("title") or ""),
            str(record.get("content") or record.get("snippet") or ""),
            str(record.get("source_url") or ""),
        ]
    ).lower()
    return any(term in text for term in terms)


def identity_terms(symbol: str) -> set[str]:
    symbol_text = str(symbol or "").strip().lower()
    terms: set[str] = set()
    if symbol_text:
        terms.add(symbol_text)
        if "." in symbol_text:
            raw_code = symbol_text.split(".", 1)[0]
            terms.add(raw_code)
            terms.add(raw_code.lstrip("0") or raw_code)
    profile = resolve_company_identifier(symbol) or {}
    _add_company_name_terms(terms, str(profile.get("company_name") or ""))
    try:
        from src.app.company_aliases import RAW_COMPANY_ENTRIES

        for entry in RAW_COMPANY_ENTRIES:
            if str(entry.get("symbol") or "").strip().lower() != symbol_text:
                continue
            _add_company_name_terms(terms, str(entry.get("company_name") or ""))
            for alias in entry.get("aliases", []) if isinstance(entry.get("aliases"), list) else []:
                _add_company_name_terms(terms, str(alias or ""))
    except Exception:
        pass
    return {term for term in terms if _valid_identity_term(term)}


def record_period_status(record: dict[str, Any], *, target_period: str) -> str:
    target = str(target_period or "").strip().upper()
    if not target:
        return "unknown"
    source_periods = record_period_labels(record)
    explicit = [value for value in source_periods if value]
    if explicit and not any(period_labels_match(value, target) for value in explicit):
        return "mismatch"
    explicit_match = any(period_labels_match(value, target) for value in explicit)
    end_date_mismatches = record_end_date_mismatches(record, target_period=target)
    if end_date_mismatches:
        return "mismatch"
    return "match" if explicit_match else "unknown"


def record_period_labels(record: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for source in [record, metadata]:
        for key in ["period", "source_period", "data_cutoff", "fiscal_period", "fiscalPeriod", "fiscal_year_label"]:
            value = str(source.get(key) or "").strip().upper()
            if value:
                labels.append(value)
        fy = str(source.get("fy") or source.get("fiscal_year") or "").strip()
        fp = str(source.get("fp") or "").strip().upper()
        if fy and (fp == "FY" or not fp):
            labels.append(f"FY{fy}")
        elif fy and fp.startswith("Q"):
            labels.append(f"{fy}{fp}")
    return list(dict.fromkeys(labels))


def period_labels_match(source_period: str, target_period: str) -> bool:
    source_key = period_key(source_period)
    target_key = period_key(target_period)
    return bool(source_key and target_key and source_key == target_key)


def period_key(period: str) -> tuple[str, str] | tuple[str, str, str] | None:
    text = str(period or "").strip().upper()
    annual = re.search(r"(?:FY|ANNUAL)\s*(20\d{2})|(20\d{2})\s*(?:FY|ANNUAL)|^(20\d{2})$", text)
    if annual:
        return "fiscal_year", str(annual.group(1) or annual.group(2) or annual.group(3))
    quarter = re.search(r"(20\d{2})\s*Q([1-4])", text)
    if quarter:
        return "quarter", quarter.group(1), f"Q{quarter.group(2)}"
    return None


def record_end_date_mismatches(record: dict[str, Any], *, target_period: str) -> list[str]:
    target_year = _target_fiscal_year(target_period)
    if target_year is None:
        return []
    mismatches: list[str] = []
    for item in iter_period_records(record):
        end_date = record_end_date(item)
        if not end_date:
            continue
        if record_has_explicit_fiscal_year(item, target_year):
            continue
        if int(end_date[:4]) != target_year:
            mismatches.append(end_date)
    return list(dict.fromkeys(mismatches))


def iter_period_records(record: dict[str, Any]):
    yield record
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    yield metadata
    raw = metadata.get("raw") if isinstance(metadata.get("raw"), dict) else {}
    if raw:
        yield raw
    financials = metadata.get("financials") if isinstance(metadata.get("financials"), dict) else {}
    for nested_key in ["income_history", "balance_history", "cashflow_history", "cash_flow_history"]:
        rows = financials.get(nested_key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row


def record_end_date(item: dict[str, Any]) -> str:
    for key in ["end_date", "report_date", "REPORT_DATE", "REPORTDATE", "end", "date"]:
        value = str(item.get(key) or "").strip()[:10]
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
            return value
    return ""


def record_has_explicit_fiscal_year(item: dict[str, Any], target_year: int) -> bool:
    for key in ["fy", "fiscal_year"]:
        try:
            if int(str(item.get(key) or "").strip()) == target_year:
                return True
        except ValueError:
            continue
    fp = str(item.get("fp") or "").strip().upper()
    if fp == "FY":
        for key in ["fy", "fiscal_year"]:
            try:
                if int(str(item.get(key) or "").strip()) == target_year:
                    return True
            except ValueError:
                continue
    return False


def evidence_ids(records: list[dict[str, Any]]) -> set[str]:
    return {
        str(record.get("evidence_id") or record.get("sample_id") or "")
        for record in records
        if str(record.get("evidence_id") or record.get("sample_id") or "")
    }


def rejection_record(record: dict[str, Any], *, reason: str, stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "reason": reason,
        "evidence_id": str(record.get("evidence_id") or record.get("sample_id") or record.get("table_id") or ""),
        "source_type": str(record.get("source_type") or record.get("table_type") or ""),
        "symbol": str(record.get("symbol") or ""),
        "period": str(record.get("period") or record.get("source_period") or ""),
        "title": str(record.get("title") or "")[:160],
        "source_url": str(record.get("source_url") or "")[:240],
    }


def _add_company_name_terms(terms: set[str], raw_name: str) -> None:
    name = str(raw_name or "").strip().lower()
    if not name:
        return
    terms.add(name)
    simplified = re.sub(
        r"\b(holdings|holding|limited|ltd|incorporated|inc|corp|corporation|company|co|股份有限公司|有限公司)\b\.?",
        "",
        name,
        flags=re.I,
    )
    simplified = " ".join(simplified.split())
    if simplified:
        terms.add(simplified)
    for token in re.split(r"[^a-z0-9\u4e00-\u9fff]+", name):
        if token:
            terms.add(token)


def _valid_identity_term(term: str) -> bool:
    value = str(term or "").strip().lower()
    if not value or value in IDENTITY_STOPWORDS:
        return False
    if re.search(r"[\u4e00-\u9fff]", value):
        return len(value) >= 2
    return len(value) >= 3


def _target_fiscal_year(period: str) -> int | None:
    match = re.fullmatch(r"FY(20\d{2})", str(period or "").strip().upper())
    return int(match.group(1)) if match else None
