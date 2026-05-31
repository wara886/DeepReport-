"""Company universe and ticker normalization helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Dict, List


_FALLBACK_COMPANIES: List[Dict[str, Any]] = [
    {
        "symbol": "AMD",
        "company_name": "Advanced Micro Devices, Inc.",
        "sector": "Technology",
        "industry": "Semiconductors",
        "profile_path": "",
        "period": "",
        "catalog_source": "builtin_fallback",
    },
    {
        "symbol": "MU",
        "company_name": "Micron Technology, Inc.",
        "sector": "Technology",
        "industry": "Semiconductors",
        "profile_path": "",
        "period": "",
        "catalog_source": "builtin_fallback",
    },
    {
        "symbol": "TSM",
        "company_name": "Taiwan Semiconductor Manufacturing Company Limited",
        "sector": "Technology",
        "industry": "Semiconductors",
        "profile_path": "",
        "period": "",
        "catalog_source": "builtin_fallback",
    },
    {
        "symbol": "LLY",
        "company_name": "Eli Lilly and Company",
        "sector": "Healthcare",
        "industry": "Drug Manufacturers",
        "profile_path": "",
        "period": "",
        "catalog_source": "builtin_fallback",
    },
    {
        "symbol": "PDD",
        "company_name": "PDD Holdings Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Internet Retail",
        "profile_path": "",
        "period": "",
        "catalog_source": "builtin_fallback",
    },
    {
        "symbol": "0700.HK",
        "company_name": "Tencent Holdings Limited",
        "sector": "Technology",
        "industry": "Internet Services",
        "profile_path": "",
        "period": "",
        "catalog_source": "builtin_fallback",
    },
    {
        "symbol": "600519.SS",
        "company_name": "Kweichow Moutai Co., Ltd.",
        "sector": "Consumer Staples",
        "industry": "Distillers & Vintners",
        "profile_path": "",
        "period": "",
        "catalog_source": "builtin_fallback",
    },
]


@dataclass(frozen=True)
class CompanyIdentity:
    """Normalized listed-company identity used for routing, not evidence."""

    symbol: str
    canonical_symbol: str
    company_name: str
    market: str
    exchange: str
    currency: str
    country_region: str
    is_listed: bool
    resolution_confidence: float
    data_source_plan: Dict[str, Any]
    match_type: str = "none"
    needs_confirmation: bool = False
    reason: str = ""
    sector: str = ""
    industry: str = ""
    business_summary: str = ""
    official_sources: List[str] | None = None
    latest_disclosure_period: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_company_universe(raw_data_root: str | Path = "data/raw/real_data") -> List[Dict[str, Any]]:
    """Load locally available listed-company profiles."""

    root = Path(raw_data_root)
    companies: Dict[str, Dict[str, Any]] = {}

    if root.exists():
        for profile_path in sorted(root.glob("*/**/company_profile.json")):
            try:
                payload = json.loads(profile_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            symbol = str(payload.get("symbol") or profile_path.parents[1].name).upper()
            if not symbol:
                continue
            item = dict(payload)
            item["symbol"] = symbol
            item.setdefault("period", profile_path.parent.name)
            item.setdefault("profile_path", str(profile_path))
            companies.setdefault(symbol, item)

    for item in _FALLBACK_COMPANIES:
        symbol = str(item.get("symbol", "")).upper()
        if symbol and symbol not in companies:
            companies[symbol] = dict(item)
    return sorted(companies.values(), key=lambda item: str(item.get("symbol", "")))


def resolve_company_identifier(
    identifier: str,
    raw_data_root: str | Path = "data/raw/real_data",
) -> Dict[str, Any]:
    """Resolve a ticker, company name, or query fragment into a local company profile."""

    query = str(identifier or "").strip()
    universe = load_company_universe(raw_data_root=raw_data_root)
    if not query:
        return {}

    normalized_query = _normalize_text(query)
    query_tokens = _symbol_tokens(query)

    for item in universe:
        symbol = str(item.get("symbol", "")).upper()
        if symbol and symbol in query_tokens:
            return dict(item)

    for item in universe:
        symbol = str(item.get("symbol", "")).upper()
        if symbol and _normalize_text(symbol) == normalized_query:
            return dict(item)

    scored = []
    for item in universe:
        aliases = _aliases_for_company(item)
        score = 0
        for alias in aliases:
            normalized_alias = _normalize_text(alias)
            if normalized_alias and normalized_alias in normalized_query:
                score = max(score, len(normalized_alias))
            elif normalized_query and normalized_query in normalized_alias:
                score = max(score, len(normalized_query))
        if score:
            scored.append((score, item))
    if scored:
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return dict(scored[0][1])
    return {}


def resolve_company_identifier_with_diagnostics(
    identifier: str,
    raw_data_root: str | Path = "data/raw/real_data",
) -> Dict[str, Any]:
    """Resolve a company identifier and expose enough detail for trace/debug gates."""

    query = str(identifier or "").strip()
    universe = load_company_universe(raw_data_root=raw_data_root)
    diagnostics: Dict[str, Any] = {
        "input": query,
        "resolved": False,
        "symbol": "",
        "company_name": "",
        "match_type": "none",
        "confidence": 0.0,
        "candidate_symbols": [str(item.get("symbol", "")).upper() for item in universe],
    }
    if not query or not universe:
        diagnostics["reason"] = "empty_input" if not query else "empty_universe"
        return diagnostics

    normalized_query = _normalize_text(query)
    query_tokens = _symbol_tokens(query)

    for item in universe:
        symbol = str(item.get("symbol", "")).upper()
        if symbol and symbol in query_tokens:
            return _resolution_payload(item, query, match_type="symbol_token", confidence=1.0)

    for item in universe:
        symbol = str(item.get("symbol", "")).upper()
        if symbol and _normalize_text(symbol) == normalized_query:
            return _resolution_payload(item, query, match_type="symbol_exact", confidence=1.0)

    scored: List[tuple[float, str, Dict[str, Any]]] = []
    for item in universe:
        aliases = _aliases_for_company(item)
        for alias in aliases:
            normalized_alias = _normalize_text(alias)
            if not normalized_alias:
                continue
            if normalized_alias in normalized_query:
                score = min(0.95, 0.65 + (len(normalized_alias) / max(len(normalized_query), 1)) * 0.3)
                scored.append((score, "alias_contains", item))
            elif normalized_query and normalized_query in normalized_alias:
                score = min(0.9, 0.55 + (len(normalized_query) / max(len(normalized_alias), 1)) * 0.3)
                scored.append((score, "query_contains_alias", item))

    if not scored:
        diagnostics["reason"] = "no_match"
        return diagnostics

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, match_type, best_item = scored[0]
    if len(scored) > 1 and best_score - scored[1][0] < 0.05:
        payload = _resolution_payload(best_item, query, match_type="ambiguous", confidence=best_score)
        payload["ambiguous"] = True
        payload["alternatives"] = [
            {"symbol": str(item.get("symbol", "")).upper(), "score": round(score, 3), "match_type": kind}
            for score, kind, item in scored[:3]
        ]
        return payload
    return _resolution_payload(best_item, query, match_type=match_type, confidence=best_score)


def resolve_symbol(
    identifier: str,
    raw_data_root: str | Path = "data/raw/real_data",
    default: str = "",
) -> str:
    resolved = resolve_company_identifier(identifier=identifier, raw_data_root=raw_data_root)
    return str(resolved.get("symbol") or default).upper()


def resolve_company_identity(
    identifier: str,
    raw_data_root: str | Path = "data/raw/real_data",
    default: str = "",
) -> CompanyIdentity:
    """Resolve any listed-company-like input into a market-aware route plan.

    This function is deliberately heuristic. It is a routing aid for the
    multi-agent workflow and must not be cited as factual evidence in reports.
    """

    query = str(identifier or "").strip()
    resolved = resolve_company_identifier_with_diagnostics(query, raw_data_root=raw_data_root)
    symbol = str(resolved.get("symbol") or "").upper()
    company_name = str(resolved.get("company_name") or "")
    sector = str(resolved.get("sector") or "")
    industry = str(resolved.get("industry") or "")
    business_summary = str(resolved.get("business_summary") or resolved.get("description") or "")
    latest_disclosure_period = str(resolved.get("period") or "")
    match_type = str(resolved.get("match_type") or "none")
    confidence = float(resolved.get("confidence") or 0.0)
    reason = str(resolved.get("reason") or "")

    if not symbol:
        inferred = infer_symbol_from_identifier(query)
        symbol = inferred.get("symbol") or str(default or "").upper()
        match_type = inferred.get("match_type", match_type)
        confidence = float(inferred.get("confidence") or confidence)
        reason = inferred.get("reason", reason)

    market_meta = infer_market_from_symbol(symbol)
    is_listed = bool(symbol and market_meta["market"] != "unknown" and confidence >= 0.45)
    needs_confirmation = bool(not is_listed or confidence < 0.65 or resolved.get("ambiguous"))
    plan = build_data_source_plan(symbol=symbol, market=market_meta["market"], exchange=market_meta["exchange"])
    canonical_symbol = canonicalize_symbol(symbol, market=market_meta["market"])

    return CompanyIdentity(
        symbol=symbol,
        canonical_symbol=canonical_symbol,
        company_name=company_name,
        market=market_meta["market"],
        exchange=market_meta["exchange"],
        currency=market_meta["currency"],
        country_region=market_meta["country_region"],
        is_listed=is_listed,
        resolution_confidence=round(confidence, 3),
        data_source_plan=plan,
        match_type=match_type,
        needs_confirmation=needs_confirmation,
        reason=reason or ("resolved" if is_listed else "unable_to_confirm_listed_company"),
        sector=sector,
        industry=industry,
        business_summary=business_summary,
        official_sources=list(plan.get("primary_sources") or []),
        latest_disclosure_period=latest_disclosure_period,
    )


def infer_symbol_from_identifier(identifier: str) -> Dict[str, Any]:
    """Infer a routeable ticker from free text without company-specific rules."""

    text = str(identifier or "").strip()
    compact = text.upper().replace(" ", "")
    if not compact:
        return {"symbol": "", "confidence": 0.0, "match_type": "empty", "reason": "empty_input"}
    hk_match = re.search(r"(?<!\d)(0?\d{4,5})(?:\.HK)?(?!\d)", compact)
    if hk_match and (compact.endswith(".HK") or len(hk_match.group(1)) in {4, 5} and hk_match.group(1).startswith("0")):
        code = hk_match.group(1).zfill(4)
        return {"symbol": f"{code}.HK", "confidence": 0.62, "match_type": "hk_code", "reason": "matched_hk_code"}
    cn_match = re.search(r"(?<!\d)([036]\d{5})(?:\.(?:SS|SZ|SH))?(?!\d)", compact)
    if cn_match:
        code = cn_match.group(1)
        suffix = ".SS" if code.startswith("6") else ".SZ"
        return {"symbol": f"{code}{suffix}", "confidence": 0.72, "match_type": "cn_code", "reason": "matched_cn_code"}
    ticker_match = re.search(r"\b([A-Z]{1,6}(?:\.[A-Z]{1,3})?)\b", text.upper())
    if ticker_match and ticker_match.group(1) not in {"Q", "AI", "GDP", "CPI"}:
        return {"symbol": ticker_match.group(1), "confidence": 0.58, "match_type": "ticker_pattern", "reason": "matched_ticker_pattern"}
    return {"symbol": "", "confidence": 0.0, "match_type": "none", "reason": "no_routeable_symbol"}


def infer_market_from_symbol(symbol: str) -> Dict[str, str]:
    text = str(symbol or "").upper().strip()
    if text.endswith(".SS") or text.endswith(".SH"):
        return {"market": "cn_a", "exchange": "SSE", "currency": "CNY", "country_region": "China"}
    if text.endswith(".SZ"):
        return {"market": "cn_a", "exchange": "SZSE", "currency": "CNY", "country_region": "China"}
    if text.endswith(".HK"):
        return {"market": "hk", "exchange": "HKEX", "currency": "HKD", "country_region": "Hong Kong"}
    if re.fullmatch(r"[A-Z]{1,6}", text):
        return {"market": "us", "exchange": "US", "currency": "USD", "country_region": "United States"}
    if "." in text:
        return {"market": "other", "exchange": text.rsplit(".", 1)[-1], "currency": "", "country_region": ""}
    return {"market": "unknown", "exchange": "", "currency": "", "country_region": ""}


def canonicalize_symbol(symbol: str, market: str = "") -> str:
    text = str(symbol or "").upper().strip()
    if market == "hk":
        code = text.removesuffix(".HK")
        if code.isdigit():
            return f"{code.zfill(4)}.HK"
    if market == "cn_a":
        code = text.split(".", 1)[0]
        suffix = ".SS" if code.startswith("6") else ".SZ"
        return f"{code}{suffix}" if code.isdigit() else text
    return text


def build_data_source_plan(symbol: str, market: str, exchange: str = "") -> Dict[str, Any]:
    """Build free-public-source search routing for a listed company."""

    if market == "cn_a":
        engines = [
            "local_real_data",
            "cninfo_announcements",
            "exchange_announcements",
            "eastmoney_financials",
            "yahoo_finance",
            "eastmoney",
            "local_evidence",
        ]
        primary = ["cninfo_announcements", "exchange_announcements", "eastmoney_financials"]
    elif market == "hk":
        engines = ["local_real_data", "hkex_announcements", "yahoo_finance", "tavily", "serper", "local_evidence"]
        primary = ["hkex_announcements", "yahoo_finance", "tavily", "serper"]
    elif market == "us":
        engines = ["local_real_data", "sec_edgar", "yahoo_finance", "independent_macro", "tavily", "local_evidence"]
        primary = ["sec_edgar", "yahoo_finance"]
    else:
        engines = ["local_real_data", "yahoo_finance", "tavily", "serper", "local_evidence"]
        primary = ["yahoo_finance", "tavily", "serper"]
    return {
        "symbol": str(symbol or "").upper(),
        "market": market,
        "exchange": exchange,
        "engines": engines,
        "primary_sources": primary,
        "free_public_only": True,
        "requires_gap_explanation_when_missing": ["income_statement", "balance_sheet", "cash_flow", "valuation", "peer_compare"],
    }


def _resolution_payload(item: Dict[str, Any], query: str, match_type: str, confidence: float) -> Dict[str, Any]:
    return {
        "input": query,
        "resolved": True,
        "symbol": str(item.get("symbol", "")).upper(),
        "company_name": str(item.get("company_name", "")),
        "match_type": match_type,
        "confidence": round(float(confidence), 3),
        "profile_path": str(item.get("profile_path", "")),
        "sector": str(item.get("sector", "")),
        "industry": str(item.get("industry", "")),
        "business_summary": str(item.get("business_summary") or item.get("description") or ""),
        "period": str(item.get("period", "")),
        "ambiguous": False,
    }


def _aliases_for_company(item: Dict[str, Any]) -> List[str]:
    aliases = [
        str(item.get("symbol", "")),
        str(item.get("company_name", "")),
        str(item.get("industry", "")),
        str(item.get("sector", "")),
    ]
    company_name = str(item.get("company_name", ""))
    aliases.extend(_company_name_variants(company_name))
    return [alias for alias in aliases if alias]


def _company_name_variants(company_name: str) -> List[str]:
    cleaned = re.sub(r"\b(incorporated|inc|corp|corporation|ltd|limited|plc|class a)\b\.?", "", company_name, flags=re.I)
    compact = " ".join(cleaned.replace(",", " ").split())
    return [compact, compact.replace(" ", "")]


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def _symbol_tokens(value: str) -> set[str]:
    return {
        token.upper()
        for token in re.findall(r"[A-Za-z]{1,8}", value)
        if token.upper() not in {"THE", "AND", "FOR", "WITH", "INC", "CORP", "LTD"}
    }
