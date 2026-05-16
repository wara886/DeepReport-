"""Evidence freshness, cutoff, and scope metadata helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List


MACRO_SOURCE_TYPES = {
    "macro_api",
    "macro_statistic",
    "policy_release",
    "federal_reserve",
    "fred_series",
    "bls_series",
    "bea_series",
}
INDUSTRY_SOURCE_TYPES = {
    "industry_report",
    "industry_statistic",
    "industry_official",
    "industry_search",
}
COMPANY_SOURCE_TYPES = {
    "filing",
    "financials",
    "company_profile",
    "company_page",
    "earnings_release",
    "sec_companyfacts",
}
MARKET_SOURCE_TYPES = {"market", "market_api", "market_data"}


def annotate_evidence_record(record: Dict[str, Any], reference_date: date | None = None) -> Dict[str, Any]:
    """Return a copy with normalized freshness, cutoff, and evidence-scope fields."""

    output = dict(record)
    metadata = dict(output.get("metadata", {})) if isinstance(output.get("metadata"), dict) else {}
    reference = reference_date or date.today()
    timestamp = _first_non_empty(
        output.get("source_timestamp"),
        output.get("publish_time"),
        output.get("as_of_date"),
        metadata.get("source_timestamp"),
        metadata.get("publish_time"),
        metadata.get("as_of_date"),
        metadata.get("fetched_at"),
    )
    data_cutoff = _first_non_empty(
        output.get("data_cutoff"),
        metadata.get("data_cutoff"),
        metadata.get("observation_date"),
        metadata.get("as_of_date"),
        output.get("period"),
        timestamp,
    )
    timestamp_date = parse_date_like(timestamp)
    freshness_days = (reference - timestamp_date).days if timestamp_date else None
    freshness_bucket = freshness_bucket_for_days(freshness_days)

    output["source_timestamp"] = timestamp
    output["data_cutoff"] = data_cutoff
    output["freshness_days"] = freshness_days
    output["freshness_bucket"] = freshness_bucket
    output["evidence_scope"] = output.get("evidence_scope") or infer_evidence_scope(output)
    metadata["freshness"] = {
        "source_timestamp": timestamp,
        "data_cutoff": data_cutoff,
        "freshness_days": freshness_days,
        "freshness_bucket": freshness_bucket,
    }
    metadata["evidence_scope"] = output["evidence_scope"]
    output["metadata"] = metadata
    return output


def annotate_evidence_records(records: Iterable[Dict[str, Any]], reference_date: date | None = None) -> List[Dict[str, Any]]:
    return [annotate_evidence_record(dict(record), reference_date=reference_date) for record in records if isinstance(record, dict)]


def infer_evidence_scope(record: Dict[str, Any]) -> str:
    source_type = str(record.get("source_type") or "").lower()
    if source_type in MACRO_SOURCE_TYPES:
        return "macro"
    if source_type in INDUSTRY_SOURCE_TYPES:
        return "industry"
    if source_type in COMPANY_SOURCE_TYPES:
        return "company"
    if source_type in MARKET_SOURCE_TYPES:
        return "market"
    if source_type in {"news", "web_search"}:
        return "web"
    return "unknown"


def freshness_bucket_for_days(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days < 0:
        return "future_dated"
    if days <= 31:
        return "fresh"
    if days <= 120:
        return "recent"
    return "stale"


def parse_date_like(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for candidate in [text, text[:10]]:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed.date()
        except ValueError:
            pass
    return None


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text
    return ""
