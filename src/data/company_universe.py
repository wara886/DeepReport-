"""Company universe and ticker normalization helpers."""

from __future__ import annotations

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
    }
]


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


def _resolution_payload(item: Dict[str, Any], query: str, match_type: str, confidence: float) -> Dict[str, Any]:
    return {
        "input": query,
        "resolved": True,
        "symbol": str(item.get("symbol", "")).upper(),
        "company_name": str(item.get("company_name", "")),
        "match_type": match_type,
        "confidence": round(float(confidence), 3),
        "profile_path": str(item.get("profile_path", "")),
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
