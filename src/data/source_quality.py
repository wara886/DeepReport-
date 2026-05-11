"""Source authority grading for financial evidence records."""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import urlparse


OFFICIAL_SOURCE_TYPES = {"filing", "financials", "company_profile", "company_page"}
MARKET_SOURCE_TYPES = {"market", "market_api"}
NEWS_SOURCE_TYPES = {"news", "web_search"}

OFFICIAL_DOMAINS = (
    "sec.gov",
    "nasdaq.com",
    "nyse.com",
    "hkexnews.hk",
    "sse.com.cn",
    "szse.cn",
)
COMPANY_DOMAINS = (
    "apple.com",
    "microsoft.com",
    "alphabet.com",
    "abc.xyz",
    "nvidia.com",
    "tesla.com",
)
MARKET_DOMAINS = (
    "finance.yahoo.com",
    "query1.finance.yahoo.com",
)
NEWSWIRE_DOMAINS = (
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
)
MEDIA_DOMAINS = (
    "reuters.com",
    "bloomberg.com",
    "cnbc.com",
    "wsj.com",
)


def apply_source_quality(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of an evidence/search record with authority metadata."""

    output = dict(record)
    grade = grade_source(record)
    output["source_authority"] = grade["source_authority"]
    output["authority_score"] = grade["authority_score"]
    output.setdefault("metadata", {})
    if isinstance(output["metadata"], dict):
        output["metadata"]["source_quality"] = grade
    if not str(output.get("trust_level", "")).strip():
        output["trust_level"] = grade["trust_level"]
    return output


def grade_source(record: Dict[str, Any]) -> Dict[str, Any]:
    source_type = str(record.get("source_type") or record.get("source") or "").lower()
    url = str(record.get("source_url") or record.get("url") or "")
    domain = _domain(url)

    if source_type in OFFICIAL_SOURCE_TYPES or _matches(domain, OFFICIAL_DOMAINS):
        return _grade("official", 1.0, "high", "official filing or company financial source")
    if _matches(domain, COMPANY_DOMAINS):
        return _grade("company_official", 0.9, "high", "company-owned source")
    if source_type in MARKET_SOURCE_TYPES or _matches(domain, MARKET_DOMAINS):
        return _grade("market_data", 0.75, "medium", "market data provider")
    if _matches(domain, NEWSWIRE_DOMAINS):
        return _grade("newswire", 0.7, "medium", "press release or newswire source")
    if _matches(domain, MEDIA_DOMAINS):
        return _grade("financial_media", 0.65, "medium", "financial media source")
    if source_type in NEWS_SOURCE_TYPES:
        return _grade("web_or_news", 0.5, "medium", "general web or news source")
    return _grade("unknown", 0.35, "low", "unclassified source")


def _grade(source_authority: str, authority_score: float, trust_level: str, reason: str) -> Dict[str, Any]:
    return {
        "source_authority": source_authority,
        "authority_score": authority_score,
        "trust_level": trust_level,
        "reason": reason,
    }


def _domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _matches(domain: str, candidates: tuple[str, ...]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)
