"""Source authority policy for company stock research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import urlparse


PRIMARY_SOURCE_TYPES = {"filing", "financials", "company_profile", "company_page", "earnings_release"}
MARKET_SOURCE_TYPES = {"market", "market_api", "market_data"}
NEWS_SOURCE_TYPES = {"news", "web_search"}

PRIMARY_DOMAINS = (
    "sec.gov",
    "nasdaq.com",
    "nyse.com",
    "hkexnews.hk",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "cninfo.com.cn",
)
COMPANY_DOMAINS = (
    "amd.com",
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
    "query2.finance.yahoo.com",
    "alphavantage.co",
    "polygon.io",
    "iexcloud.io",
    "tushare.pro",
    "akshare.akfamily.xyz",
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

CORE_FINANCIAL_CLAIMS = {
    "financial_statement",
    "financial_metric",
    "revenue",
    "profit",
    "cash_flow",
    "balance_sheet",
    "guidance",
}
MARKET_CLAIMS = {"market_price", "market_cap", "volume", "valuation_market_input"}
EVENT_CLAIMS = {"event", "risk", "business_context", "management_commentary"}


@dataclass(frozen=True)
class SourceAuthorityGrade:
    source_authority: str
    authority_level: str
    authority_score: float
    trust_level: str
    source_document_type: str
    allowed_claim_types: Tuple[str, ...]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_authority": self.source_authority,
            "authority_level": self.authority_level,
            "authority_score": self.authority_score,
            "trust_level": self.trust_level,
            "source_document_type": self.source_document_type,
            "allowed_claim_types": list(self.allowed_claim_types),
            "reason": self.reason,
        }


class SourceAuthorityPolicy:
    """Classify evidence sources into claim-support tiers."""

    def grade(self, record: Dict[str, Any]) -> SourceAuthorityGrade:
        source_type = str(record.get("source_type") or record.get("source") or "").lower()
        url = str(record.get("source_url") or record.get("url") or "")
        title = str(record.get("title") or "")
        domain = domain_from_url(url)
        doc_type = infer_document_type(source_type=source_type, url=url, title=title)

        if source_type in PRIMARY_SOURCE_TYPES or matches_domain(domain, PRIMARY_DOMAINS):
            return SourceAuthorityGrade(
                source_authority="official",
                authority_level="primary",
                authority_score=1.0,
                trust_level="high",
                source_document_type=doc_type,
                allowed_claim_types=tuple(sorted(CORE_FINANCIAL_CLAIMS | EVENT_CLAIMS)),
                reason="official filing, structured financial record, or exchange disclosure",
            )
        if matches_domain(domain, COMPANY_DOMAINS):
            return SourceAuthorityGrade(
                source_authority="company_official",
                authority_level="primary",
                authority_score=0.92,
                trust_level="high",
                source_document_type=doc_type,
                allowed_claim_types=tuple(sorted(CORE_FINANCIAL_CLAIMS | EVENT_CLAIMS)),
                reason="company-owned investor relations or disclosure source",
            )
        if source_type in MARKET_SOURCE_TYPES or matches_domain(domain, MARKET_DOMAINS):
            return SourceAuthorityGrade(
                source_authority="market_data",
                authority_level="market_data",
                authority_score=0.78,
                trust_level="medium",
                source_document_type=doc_type,
                allowed_claim_types=tuple(sorted(MARKET_CLAIMS)),
                reason="market data provider suitable for price, volume, and market valuation inputs",
            )
        if matches_domain(domain, NEWSWIRE_DOMAINS):
            return SourceAuthorityGrade(
                source_authority="newswire",
                authority_level="secondary",
                authority_score=0.7,
                trust_level="medium",
                source_document_type=doc_type,
                allowed_claim_types=tuple(sorted(EVENT_CLAIMS)),
                reason="press release or newswire source suitable for event context",
            )
        if matches_domain(domain, MEDIA_DOMAINS):
            return SourceAuthorityGrade(
                source_authority="financial_media",
                authority_level="secondary",
                authority_score=0.65,
                trust_level="medium",
                source_document_type=doc_type,
                allowed_claim_types=tuple(sorted(EVENT_CLAIMS)),
                reason="financial media source suitable for background and market commentary",
            )
        if source_type in NEWS_SOURCE_TYPES:
            return SourceAuthorityGrade(
                source_authority="web_or_news",
                authority_level="tertiary",
                authority_score=0.5,
                trust_level="medium",
                source_document_type=doc_type,
                allowed_claim_types=tuple(sorted(EVENT_CLAIMS)),
                reason="general web or news result; must be upgraded before supporting core financial claims",
            )
        return SourceAuthorityGrade(
            source_authority="unknown",
            authority_level="unknown",
            authority_score=0.35,
            trust_level="low",
            source_document_type=doc_type,
            allowed_claim_types=tuple(),
            reason="unclassified source",
        )


DEFAULT_SOURCE_AUTHORITY_POLICY = SourceAuthorityPolicy()


def grade_source_authority(record: Dict[str, Any]) -> Dict[str, Any]:
    return DEFAULT_SOURCE_AUTHORITY_POLICY.grade(record).to_dict()


def can_support_claim(record: Dict[str, Any], claim_type: str) -> bool:
    grade = grade_source_authority(record)
    return str(claim_type) in set(str(item) for item in grade.get("allowed_claim_types", []))


def domain_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    return host[4:] if host.startswith("www.") else host


def matches_domain(domain: str, candidates: Iterable[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def infer_document_type(source_type: str, url: str, title: str = "") -> str:
    text = f"{source_type} {url} {title}".lower()
    if "10-k" in text or "10k" in text:
        return "10-K"
    if "10-q" in text or "10q" in text:
        return "10-Q"
    if "8-k" in text or "8k" in text:
        return "8-K"
    if "earnings" in text or "results" in text:
        return "earnings_release"
    if "presentation" in text:
        return "investor_presentation"
    if "market" in source_type:
        return "market_snapshot"
    if "news" in source_type or source_type == "web_search":
        return "web_or_news"
    return source_type or "unknown"
