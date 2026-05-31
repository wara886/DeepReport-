"""Currency audit for financial report artifacts."""

from __future__ import annotations

from typing import Any

from src.data.company_universe import infer_market_from_symbol
from src.market.currency_rules import infer_statement_currency, infer_trading_currency, is_official_financial_source
from src.utils.money import UNKNOWN_CURRENCY, normalize_currency_code


MONEY_METRICS = {
    "revenue",
    "net_income",
    "adjusted_net_income",
    "non_recurring_gain",
    "total_assets",
    "total_liabilities",
    "equity",
    "operating_cash_flow",
    "free_cash_flow",
    "capex",
    "market_cap",
}


def build_currency_audit(
    *,
    symbol: str,
    period: str = "",
    records: list[dict[str, Any]] | None = None,
    financial_metrics: dict[str, Any] | None = None,
    valuation_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    market = infer_market_from_symbol(symbol).get("market", "")
    records = records or []
    financial_metrics = financial_metrics if isinstance(financial_metrics, dict) else {}
    valuation_model = valuation_model if isinstance(valuation_model, dict) else {}
    official_records = [record for record in records if is_official_financial_source(str(record.get("source_type") or ""))]
    currency_meta = infer_statement_currency(symbol=symbol, market=market, source=official_records[0] if official_records else None)
    statement_currency = currency_meta.statement_currency
    trading_currency = infer_trading_currency(symbol, market)
    display_currency = currency_meta.display_currency if currency_meta.display_currency != UNKNOWN_CURRENCY else statement_currency
    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    blockers: list[str] = []
    correction_log: list[dict[str, Any]] = []

    for metric in financial_metrics.get("metrics", []) if isinstance(financial_metrics.get("metrics"), list) else []:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("metric_name") or metric.get("metric_key") or "")
        currency = normalize_currency_code(metric.get("currency") or metric.get("unit"))
        source_type = str(metric.get("source_type") or _source_type_for_metric(metric, records))
        if name in MONEY_METRICS and currency == UNKNOWN_CURRENCY:
            blockers.append("unknown_financial_metric_currency")
            findings.append({"metric": name, "issue": "unknown_currency", "source_type": source_type})
        if market in {"hk", "cn_a"} and name in MONEY_METRICS and currency == "USD" and source_type in {"market_api", "market_data", "yahoo_finance"}:
            blockers.append("currency_unit_mismatch")
            findings.append({"metric": name, "issue": "non_us_statement_metric_marked_usd", "source_type": source_type})
        if name in MONEY_METRICS and statement_currency != UNKNOWN_CURRENCY and currency != statement_currency and currency != UNKNOWN_CURRENCY and source_type in {"market_api", "market_data", "yahoo_finance"}:
            correction_log.append({"metric": name, "from": currency, "to": statement_currency, "reason": "issuer_statement_currency"})

    if market in {"hk", "cn_a"} and str(period or "").upper().startswith("FY") and not official_records:
        blockers.append("official_source_missing_for_non_us_annual")
        warnings.append("non-US annual report has no official annual report/HKEX/IR financial evidence")

    valuation_status = str(valuation_model.get("valuation_status") or valuation_model.get("error") or "")
    model_currency = normalize_currency_code(valuation_model.get("currency"))
    if market in {"hk", "cn_a"} and model_currency == "USD":
        blockers.append("valuation_currency_mismatch")
    if valuation_status == "blocked_due_to_currency_mismatch":
        blockers.append("valuation_currency_mismatch")
    if valuation_status == "missing_fx_rate_for_cross_currency_valuation":
        blockers.append("missing_fx_rate_for_cross_currency_valuation")

    return {
        "symbol": symbol,
        "period": period,
        "market": market,
        "statement_currency": statement_currency,
        "trading_currency": trading_currency,
        "display_currency": display_currency,
        "currency_basis": currency_meta.currency_basis,
        "currency_confidence": currency_meta.confidence,
        "inferred_from": currency_meta.inferred_from,
        "official_financial_source_count": len(official_records),
        "currency_findings": findings,
        "correction_log": correction_log,
        "warnings": _dedupe(warnings),
        "blockers": _dedupe(blockers),
    }


def _source_type_for_metric(metric: dict[str, Any], records: list[dict[str, Any]]) -> str:
    evidence_id = str(metric.get("source_evidence_id") or "")
    for record in records:
        if evidence_id and evidence_id in {str(record.get("evidence_id") or ""), str(record.get("sample_id") or "")}:
            return str(record.get("source_type") or "")
    return ""


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
