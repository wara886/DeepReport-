"""Market-level currency inference rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.data.company_universe import infer_market_from_symbol
from src.utils.money import CurrencyMetadata, UNKNOWN_CURRENCY, normalize_currency_code


OFFICIAL_SOURCE_TYPES = {
    "sec_companyfacts",
    "sec_filing",
    "sec_10k_filing",
    "sec_10k_section",
    "hkex_announcement",
    "company_official",
    "company_ir",
    "exchange_announcement",
    "cninfo_announcement",
    "eastmoney_financials",
    "pdf_statement_table",
}


def infer_trading_currency(symbol: str, market: str = "") -> str:
    market_key = (market or infer_market_from_symbol(symbol).get("market") or "").lower()
    if market_key == "us":
        return "USD"
    if market_key == "hk":
        return "HKD"
    if market_key == "cn_a":
        return "CNY"
    return normalize_currency_code(infer_market_from_symbol(symbol).get("currency"))


def infer_statement_currency(
    symbol: str,
    market: str = "",
    company_name: str = "",
    source: dict[str, Any] | None = None,
    overrides_path: str | Path = "configs/issuer_currency_overrides.yaml",
) -> CurrencyMetadata:
    source = source if isinstance(source, dict) else {}
    source_currency = _currency_from_source(source)
    if source_currency != UNKNOWN_CURRENCY:
        return CurrencyMetadata(
            statement_currency=source_currency,
            trading_currency=infer_trading_currency(symbol, market),
            display_currency=source_currency,
            currency_basis="source_metadata",
            confidence="high",
            inferred_from="source_metadata",
        )

    override = issuer_currency_override(symbol, overrides_path=overrides_path)
    if override:
        statement = normalize_currency_code(override.get("statement_currency"))
        trading = normalize_currency_code(override.get("trading_currency")) or infer_trading_currency(symbol, market)
        if statement != UNKNOWN_CURRENCY:
            return CurrencyMetadata(
                statement_currency=statement,
                trading_currency=trading,
                display_currency=normalize_currency_code(override.get("display_currency")) if override.get("display_currency") else statement,
                currency_basis="issuer_currency_rules",
                confidence=str(override.get("confidence") or "inferred"),
                inferred_from="issuer_currency_overrides",
            )

    market_key = (market or infer_market_from_symbol(symbol).get("market") or "").lower()
    if market_key == "us":
        return CurrencyMetadata("USD", "USD", "USD", "market_default", "medium", "us_market_default")
    if market_key == "cn_a":
        return CurrencyMetadata("CNY", "CNY", "CNY", "market_default", "medium", "cn_a_market_default")
    if market_key == "hk":
        return CurrencyMetadata(UNKNOWN_CURRENCY, "HKD", UNKNOWN_CURRENCY, "unknown", "unknown", "hk_requires_statement_source")
    return CurrencyMetadata(UNKNOWN_CURRENCY, infer_trading_currency(symbol, market), UNKNOWN_CURRENCY, "unknown", "unknown", "no_rule")


def issuer_currency_override(symbol: str, overrides_path: str | Path = "configs/issuer_currency_overrides.yaml") -> dict[str, Any]:
    path = Path(overrides_path)
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    issuers = payload.get("issuers") if isinstance(payload, dict) else {}
    if not isinstance(issuers, dict):
        return {}
    return dict(issuers.get(str(symbol or "").upper()) or {})


def is_official_financial_source(source_type: str) -> bool:
    return str(source_type or "").lower() in OFFICIAL_SOURCE_TYPES


def _currency_from_source(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    candidates = [
        source.get("currency"),
        source.get("statement_currency"),
        source.get("reporting_currency"),
        source.get("unit"),
        metadata.get("currency"),
        metadata.get("statement_currency"),
        metadata.get("reporting_currency"),
    ]
    for candidate in candidates:
        normalized = normalize_currency_code(candidate)
        if normalized != UNKNOWN_CURRENCY:
            return normalized
    return UNKNOWN_CURRENCY
