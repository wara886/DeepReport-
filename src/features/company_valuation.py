"""Peer comparison and valuation helpers for company reports."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd

from src.data.financial_quality import build_net_income_quality_fields


def build_peer_comparison(
    symbol: str,
    period: str,
    raw_data_root: str | Path = "data/raw/real_data",
) -> Dict[str, Any]:
    """Build a local peer table from companies in the same sector when possible."""

    symbol = str(symbol or "").upper()
    rows = _load_company_financial_rows(raw_data_root=raw_data_root, period=period)
    target = next((row for row in rows if row.get("symbol") == symbol), None)
    if not target:
        return {"target_symbol": symbol, "peer_rows": [], "peer_count": 0, "ranking": {}}

    target_sector = str(target.get("sector") or "")
    target_industry = str(target.get("industry") or "")
    peers = [
        row
        for row in rows
        if row.get("symbol") != symbol
        and (row.get("sector") == target_sector or row.get("industry") == target_industry)
    ]
    if not peers:
        peers = [row for row in rows if row.get("symbol") != symbol]

    peer_rows = [_peer_row(row, target_symbol=symbol) for row in [target] + peers]
    ranking = _rank_target(peer_rows, symbol=symbol)
    return {
        "target_symbol": symbol,
        "target_sector": target_sector,
        "target_industry": target_industry,
        "peer_rows": peer_rows,
        "peer_count": max(len(peer_rows) - 1, 0),
        "ranking": ranking,
    }


def perform_company_valuation(
    symbol: str,
    period: str,
    records: List[Dict[str, Any]] | None = None,
    raw_data_root: str | Path = "data/raw/real_data",
) -> Dict[str, Any]:
    """Perform a first-pass company valuation from local financial evidence."""

    symbol = str(symbol or "").upper()
    peer_payload = build_peer_comparison(symbol=symbol, period=period, raw_data_root=raw_data_root)
    target = next((row for row in peer_payload.get("peer_rows", []) if row.get("symbol") == symbol), {})
    if not target and records:
        target = _target_from_records(records=records, symbol=symbol, period=period)
    if not target:
        return {"symbol": symbol, "period": period, "valuation_available": False, "error": "target financials not found"}

    revenue = _safe_float(target.get("revenue_billion")) or 0.0
    net_income = _safe_float(target.get("adjusted_net_income_billion")) or _safe_float(target.get("net_income_billion"))
    if target.get("valuation_input_usable") is False:
        return _valuation_unavailable(
            symbol=symbol,
            period=period,
            error="non_recurring_gain_unadjusted",
            peer_payload=peer_payload,
            input_summary={
                "revenue_billion": revenue,
                "net_income_billion": _safe_float(target.get("net_income_billion")),
                "adjusted_net_income_billion": _safe_float(target.get("adjusted_net_income_billion")),
                "non_recurring_gain_billion": _safe_float(target.get("non_recurring_gain_billion")),
                "net_income_quality_flag": target.get("net_income_quality_flag"),
            },
            missing_inputs=["adjusted_or_normalized_net_income"],
        )
    if net_income is None:
        net_margin = _safe_float(target.get("net_margin_pct")) or 0.0
        net_income = revenue * net_margin / 100
    free_cash_flow = _safe_float(target.get("free_cash_flow_billion"))
    if free_cash_flow is None:
        return _valuation_unavailable(
            symbol=symbol,
            period=period,
            error="valuation_input_invalid",
            peer_payload=peer_payload,
            input_summary={"revenue_billion": revenue, "net_income_billion": net_income, "free_cash_flow_billion": None},
            missing_inputs=["annual_or_ttm_free_cash_flow"],
        )
    if not _fcf_basis_is_usable(target=target, period=period):
        return _valuation_unavailable(
            symbol=symbol,
            period=period,
            error="valuation_input_invalid",
            peer_payload=peer_payload,
            input_summary={
                "revenue_billion": revenue,
                "net_income_billion": net_income,
                "free_cash_flow_billion": free_cash_flow,
                "free_cash_flow_period_basis": target.get("free_cash_flow_period_basis") or target.get("period_basis") or "quarterly",
            },
            missing_inputs=["annual_or_ttm_free_cash_flow"],
        )
    market_context = _market_context_from_records(records=records or [], symbol=symbol, period=period)
    shares_outstanding = _safe_float(market_context.get("shares_outstanding_billion"))
    revenue_growth = _safe_float(target.get("revenue_growth_pct")) or 0.0
    net_margin = _safe_float(target.get("adjusted_net_margin_pct")) or _safe_float(target.get("net_margin_pct")) or 0.0
    roe = _safe_float(target.get("roe_pct")) or 0.0

    peer_rows = [row for row in peer_payload.get("peer_rows", []) if row.get("symbol") != symbol]
    peer_growth = _median_numeric(peer_rows, "revenue_growth_pct", fallback=revenue_growth)
    peer_margin = _median_numeric(peer_rows, "net_margin_pct", fallback=net_margin)
    growth_premium = _bounded(1 + (revenue_growth - peer_growth) / 100, 0.75, 1.35)
    margin_premium = _bounded(1 + (net_margin - peer_margin) / 100, 0.75, 1.35)

    pe_multiple = round(_bounded(18 * growth_premium * margin_premium, 10, 40), 2)
    ps_multiple = round(_bounded(4 * growth_premium * (1 + net_margin / 100), 1.5, 14), 2)
    discount_rate = 0.10
    terminal_growth = 0.025
    fcf_growth = _bounded(revenue_growth / 100, 0.02, 0.20)

    pe_value = net_income * pe_multiple
    ps_value = revenue * ps_multiple
    dcf_value = _dcf_value(free_cash_flow=free_cash_flow, growth_rate=fcf_growth, discount_rate=discount_rate, terminal_growth=terminal_growth)
    values = [value for value in [pe_value, ps_value, dcf_value] if value > 0]
    blended_value = sum(values) / len(values) if values else 0.0
    guardrail = _valuation_guardrail(
        revenue=revenue,
        net_income=net_income,
        free_cash_flow=free_cash_flow,
        pe_value=pe_value,
        ps_value=ps_value,
        dcf_value=dcf_value,
        blended_value=blended_value,
        market_context=market_context,
        shares_outstanding_billion=shares_outstanding,
    )
    if not guardrail["passed"]:
        return {
            "symbol": symbol,
            "period": period,
            "valuation_available": False,
            "error": "valuation_guardrail_failed",
            "guardrail": guardrail,
            "market_context": market_context,
            "peer_context": peer_payload,
            "input_summary": {
                "revenue_billion": revenue,
                "net_income_billion": net_income,
                "free_cash_flow_billion": free_cash_flow,
            },
        }
    relative_valuation = _relative_valuation_model(
        symbol=symbol,
        period=period,
        revenue=revenue,
        net_income=net_income,
        pe_multiple=pe_multiple,
        ps_multiple=ps_multiple,
        shares_outstanding_billion=shares_outstanding,
    )
    dcf_model = _build_dcf_model(
        symbol=symbol,
        period=period,
        free_cash_flow=free_cash_flow,
        growth_rate=fcf_growth,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        shares_outstanding_billion=shares_outstanding,
    )
    valuation_sensitivity = _valuation_sensitivity(
        free_cash_flow=free_cash_flow,
        growth_rate=fcf_growth,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        shares_outstanding_billion=shares_outstanding,
    )

    recommendation = _recommendation(
        revenue_growth=revenue_growth,
        net_margin=net_margin,
        roe=roe,
        peer_growth=peer_growth,
        peer_margin=peer_margin,
    )
    return {
        "symbol": symbol,
        "period": period,
        "valuation_available": True,
        "currency": "USD_billion",
        "methods": {
            "pe": {"multiple": pe_multiple, "value_billion": round(pe_value, 2)},
            "ps": {"multiple": ps_multiple, "value_billion": round(ps_value, 2)},
            "dcf": {
                "discount_rate": discount_rate,
                "terminal_growth": terminal_growth,
                "fcf_growth": round(fcf_growth, 4),
                "value_billion": round(dcf_value, 2),
            },
        },
        "blended_equity_value_billion": round(blended_value, 2),
        "sensitivity": {
            "fcf_growth_minus_2pct": round(_dcf_value(free_cash_flow, max(fcf_growth - 0.02, 0.0), discount_rate, terminal_growth), 2),
            "fcf_growth_plus_2pct": round(_dcf_value(free_cash_flow, fcf_growth + 0.02, discount_rate, terminal_growth), 2),
            "discount_rate_plus_1pct": round(_dcf_value(free_cash_flow, fcf_growth, discount_rate + 0.01, terminal_growth), 2),
        },
        "market_context": market_context,
        "market_gap": _market_gap(blended_value=blended_value, market_context=market_context),
        "peer_context": peer_payload,
        "relative_valuation": relative_valuation,
        "dcf_model": dcf_model,
        "valuation_model": {
            "symbol": symbol,
            "period": period,
            "currency": "USD",
            "unit": "billion",
            "relative_valuation": relative_valuation,
            "dcf_model": dcf_model,
            "blended_equity_value_billion": round(blended_value, 2),
            "target_price": _target_price(blended_value, shares_outstanding),
        },
        "valuation_assumptions": dcf_model["assumptions"],
        "valuation_sensitivity": valuation_sensitivity,
        "recommendation": recommendation,
        "assumptions": [
            "估值为规则模型生成的第一版相对估值/DCF 区间，不构成投资建议。",
            "缺少完整股本与实时市值时，输出为企业/股权价值规模估计。",
        ],
    }


def _load_company_financial_rows(raw_data_root: str | Path, period: str) -> List[Dict[str, Any]]:
    root = Path(raw_data_root)
    rows: List[Dict[str, Any]] = []
    if not root.exists():
        return rows
    for symbol_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        period_dir = symbol_dir / period
        if not period_dir.exists():
            continue
        profile = _read_json(period_dir / "company_profile.json")
        financials_path = period_dir / "financials.csv"
        if not financials_path.exists():
            continue
        for _, item in pd.read_csv(financials_path).iterrows():
            row = item.to_dict()
            row["symbol"] = str(row.get("symbol") or symbol_dir.name).upper()
            row["period"] = str(row.get("period") or period)
            row["company_name"] = profile.get("company_name", "")
            row["sector"] = profile.get("sector", "")
            row["industry"] = profile.get("industry", "")
            revenue = _safe_float(row.get("revenue_billion")) or 0.0
            net_margin = _safe_float(row.get("net_margin_pct")) or 0.0
            if _safe_float(row.get("net_income_billion")) is None:
                row["net_income_billion"] = round(revenue * net_margin / 100, 4)
            if _safe_float(row.get("adjusted_net_income_billion")) is not None:
                adjusted = float(row["adjusted_net_income_billion"])
                row["net_margin_pct"] = (adjusted / revenue * 100.0) if revenue else row.get("net_margin_pct")
            rows.append(row)
    return rows


def _peer_row(row: Dict[str, Any], target_symbol: str) -> Dict[str, Any]:
    metrics = {
        "symbol": str(row.get("symbol", "")).upper(),
        "company_name": str(row.get("company_name", "")),
        "sector": str(row.get("sector", "")),
        "industry": str(row.get("industry", "")),
        "is_target": str(row.get("symbol", "")).upper() == target_symbol,
        "revenue_billion": _safe_float(row.get("revenue_billion")),
        "revenue_growth_pct": _safe_float(row.get("revenue_growth_pct")),
        "gross_margin_pct": _safe_float(row.get("gross_margin_pct")),
        "net_margin_pct": _safe_float(row.get("net_margin_pct")),
        "roe_pct": _safe_float(row.get("roe_pct")),
        "free_cash_flow_billion": _safe_float(row.get("free_cash_flow_billion")),
        "net_income_billion": _safe_float(row.get("net_income_billion")),
        "adjusted_net_income_billion": _safe_float(row.get("adjusted_net_income_billion")),
        "adjusted_net_margin_pct": _safe_float(row.get("adjusted_net_margin_pct")),
        "non_recurring_gain_billion": _safe_float(row.get("non_recurring_gain_billion")),
        "non_recurring_gain_ratio": _safe_float(row.get("non_recurring_gain_ratio")),
        "net_income_quality_flag": str(row.get("net_income_quality_flag") or "reported"),
        "valuation_input_usable": _bool_or_default(row.get("valuation_input_usable"), True),
        "valuation_input_rejection_reason": str(row.get("valuation_input_rejection_reason") or ""),
        "free_cash_flow_period_basis": str(row.get("free_cash_flow_period_basis") or row.get("fcf_period_basis") or row.get("period_basis") or ""),
    }
    return metrics


def _rank_target(peer_rows: List[Dict[str, Any]], symbol: str) -> Dict[str, Any]:
    ranking = {}
    for metric in ["revenue_growth_pct", "gross_margin_pct", "net_margin_pct", "roe_pct"]:
        sorted_rows = sorted(
            [row for row in peer_rows if _safe_float(row.get(metric)) is not None],
            key=lambda row: float(row[metric]),
            reverse=True,
        )
        for index, row in enumerate(sorted_rows, start=1):
            if row.get("symbol") == symbol:
                ranking[metric] = {"rank": index, "peer_count": len(sorted_rows), "value": row.get(metric)}
                break
    return ranking


def _target_from_records(records: List[Dict[str, Any]], symbol: str, period: str) -> Dict[str, Any]:
    priority = {"sec_companyfacts": 0, "sec_filing": 1, "financials": 2, "market_api": 3, "market_data": 3}
    candidates = [
        record
        for record in records
        if str(record.get("symbol", "")).upper() == symbol
        and str(record.get("source_type", "")).lower() in priority
    ]
    candidates.sort(key=lambda item: priority.get(str(item.get("source_type", "")).lower(), 99))
    for record in candidates:
        if str(record.get("symbol", "")).upper() != symbol:
            continue
        if str(record.get("source_type", "")).lower() not in {"financials", "market_api", "market_data", "sec_companyfacts"}:
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        row = _normalize_record_financials(record)
        if not row.get("revenue_billion") and not row.get("net_income_billion"):
            continue
        row["symbol"] = symbol
        row["period"] = period
        return _peer_row(row, target_symbol=symbol)
    return {}


def _market_context_from_records(records: List[Dict[str, Any]], symbol: str, period: str) -> Dict[str, Any]:
    for record in records:
        if str(record.get("symbol", "")).upper() != symbol:
            continue
        if str(record.get("source_type", "")).lower() not in {"market", "market_api"}:
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        snapshot = metadata.get("snapshot") if isinstance(metadata.get("snapshot"), dict) else metadata
        if isinstance(metadata.get("financials"), dict):
            snapshot = {**snapshot, **metadata["financials"]}
        last_close = _safe_float(snapshot.get("last_close") or snapshot.get("close"))
        current_price = _safe_float(snapshot.get("currentPrice") or snapshot.get("regularMarketPrice"))
        market_cap = _safe_float(
            snapshot.get("market_cap_billion")
            or snapshot.get("marketCapBillion")
            or snapshot.get("market_cap")
            or snapshot.get("marketCap")
        )
        shares = _safe_float(snapshot.get("shares_outstanding_billion") or snapshot.get("sharesOutstandingBillion"))
        if market_cap and market_cap > 1_000_000:
            market_cap = market_cap / 1_000_000_000
        if not shares:
            raw_shares = _safe_float(snapshot.get("sharesOutstanding") or snapshot.get("impliedSharesOutstanding"))
            if raw_shares:
                shares = raw_shares / 1_000_000_000 if raw_shares > 1_000_000 else raw_shares
        if not shares and market_cap and current_price:
            shares = market_cap / current_price
        if not market_cap and last_close and shares:
            market_cap = last_close * shares
        return {
            "symbol": symbol,
            "period": period,
            "last_close": last_close or current_price,
            "market_cap_billion": market_cap,
            "shares_outstanding_billion": shares,
            "source_evidence_id": str(record.get("evidence_id") or record.get("sample_id") or ""),
            "source_url": str(record.get("source_url") or ""),
        }
    return {}


def _normalize_record_financials(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source_type = str(record.get("source_type", "")).lower()
    if source_type == "sec_companyfacts":
        metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
        revenue = _first_fact_value(metrics, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"])
        net_income = _first_fact_value(metrics, ["NetIncomeLoss"])
        assets = _first_fact_value(metrics, ["Assets"])
        equity = _first_fact_value(metrics, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
        return {
            "revenue_billion": _to_billion(revenue) if revenue is not None else None,
            "net_income_billion": _to_billion(net_income) if net_income is not None else None,
            "adjusted_net_income_billion": _to_billion(net_income) if net_income is not None else None,
            "net_income_quality_flag": "sec_reported",
            "valuation_input_usable": True,
            "net_margin_pct": (float(net_income) / float(revenue) * 100.0) if revenue not in (None, 0) and net_income is not None else None,
            "roe_pct": (float(net_income) / float(equity) * 100.0) if equity not in (None, 0) and net_income is not None else None,
            "roa_pct": (float(net_income) / float(assets) * 100.0) if assets not in (None, 0) and net_income is not None else None,
        }
    raw = metadata.get("financials") if isinstance(metadata.get("financials"), dict) else metadata
    latest_income = _first_dict(raw.get("income_history")) or _first_dict(raw.get("quarterly_income_history"))
    latest_cashflow = _first_dict(raw.get("cashflow_history")) or _first_dict(raw.get("quarterly_cashflow_history"))
    revenue = _first_number(raw, ["totalRevenue", "revenue", "Total Revenue"])
    if revenue is None:
        revenue = _first_number(latest_income, ["Total Revenue", "Operating Revenue", "revenue"])
    net_income = _first_number(raw, ["netIncome", "Net Income"])
    if net_income is None:
        net_income = _first_number(latest_income, ["Net Income", "Net Income Common Stockholders"])
    quality = build_net_income_quality_fields(raw, latest_income, net_income=net_income, revenue=revenue)
    free_cash_flow = _first_number(raw, ["freeCashflow", "free_cash_flow_billion"])
    if free_cash_flow is None:
        free_cash_flow = _first_number(latest_cashflow, ["Free Cash Flow"])
    adjusted_net_income = quality.get("adjusted_net_income")
    adjusted_net_margin = quality.get("adjusted_net_margin_pct")
    return {
        "revenue_billion": _to_billion(revenue) if revenue is not None else _safe_float(raw.get("revenue_billion")),
        "net_income_billion": _to_billion(net_income) if net_income is not None else _safe_float(raw.get("net_income_billion")),
        "adjusted_net_income_billion": _to_billion(float(adjusted_net_income)) if adjusted_net_income is not None else _safe_float(raw.get("adjusted_net_income_billion")),
        "non_recurring_gain_billion": _to_billion(float(quality["non_recurring_gain"])) if quality.get("non_recurring_gain") is not None else _safe_float(raw.get("non_recurring_gain_billion")),
        "non_recurring_gain_ratio": quality.get("non_recurring_gain_ratio") if quality.get("non_recurring_gain_ratio") is not None else _safe_float(raw.get("non_recurring_gain_ratio")),
        "net_income_quality_flag": quality.get("net_income_quality_flag", raw.get("net_income_quality_flag", "reported")),
        "valuation_input_usable": bool(quality.get("valuation_input_usable", raw.get("valuation_input_usable", True))),
        "valuation_input_rejection_reason": str(quality.get("valuation_input_rejection_reason") or raw.get("valuation_input_rejection_reason") or ""),
        "revenue_growth_pct": _ratio_to_pct(_first_number(raw, ["revenueGrowth", "revenue_growth_pct"]) or 0.0),
        "gross_margin_pct": _ratio_to_pct(_first_number(raw, ["grossMargins", "gross_margin_pct"]) or 0.0),
        "net_margin_pct": float(adjusted_net_margin) if adjusted_net_margin is not None and quality.get("net_income_quality_flag") == "adjusted_for_non_recurring_gain" else _ratio_to_pct(_first_number(raw, ["profitMargins", "net_margin_pct"]) or 0.0),
        "adjusted_net_margin_pct": float(adjusted_net_margin) if adjusted_net_margin is not None else None,
        "roe_pct": _ratio_to_pct(_first_number(raw, ["returnOnEquity", "roe_pct"]) or 0.0),
        "free_cash_flow_billion": _to_billion(free_cash_flow) if free_cash_flow is not None else _safe_float(raw.get("free_cash_flow_billion")),
        "free_cash_flow_period_basis": _period_basis_from_source(raw=raw, latest_cashflow=latest_cashflow),
    }


def _valuation_unavailable(
    *,
    symbol: str,
    period: str,
    error: str,
    peer_payload: Dict[str, Any],
    input_summary: Dict[str, Any],
    missing_inputs: List[str],
) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "period": period,
        "valuation_available": False,
        "error": error,
        "missing_inputs": missing_inputs,
        "peer_context": peer_payload,
        "input_summary": input_summary,
        "valuation_input_usable": False,
        "valuation_input_rejection_reason": error,
    }


def _fcf_basis_is_usable(target: Dict[str, Any], period: str) -> bool:
    basis = str(
        target.get("free_cash_flow_period_basis")
        or target.get("fcf_period_basis")
        or target.get("period_basis")
        or ""
    ).strip().lower()
    if basis in {"annual", "annualized", "ttm", "trailing_twelve_months", "forecast", "projected"}:
        return True
    if _is_quarterly_period(period):
        return False
    return True


def _period_basis_from_source(raw: Dict[str, Any], latest_cashflow: Dict[str, Any]) -> str:
    for source in (raw, latest_cashflow):
        for key in ["free_cash_flow_period_basis", "fcf_period_basis", "period_basis", "timeframe"]:
            value = source.get(key)
            if value:
                return str(value)
    return "quarterly" if latest_cashflow else ""


def _is_quarterly_period(period: str) -> bool:
    return "Q" in str(period or "").upper()


def _bool_or_default(value: Any, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return default


def _first_fact_value(raw: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict):
            parsed = _safe_float(value.get("value"))
            if parsed is not None:
                return parsed
    return None


def _first_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), {})
    return value if isinstance(value, dict) else {}


def _first_number(raw: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = _safe_float(raw.get(key))
        if value is not None:
            return value
    return None


def _to_billion(value: float) -> float:
    return float(value) / 1_000_000_000 if abs(float(value)) > 1_000_000 else float(value)


def _ratio_to_pct(value: float) -> float:
    value = float(value)
    return value * 100.0 if abs(value) <= 1.0 else value


def _market_gap(blended_value: float, market_context: Dict[str, Any]) -> Dict[str, Any]:
    market_cap = _safe_float(market_context.get("market_cap_billion"))
    if not market_cap:
        return {"available": False}
    gap_pct = ((blended_value - market_cap) / market_cap) * 100 if market_cap else 0.0
    return {
        "available": True,
        "market_cap_billion": round(market_cap, 2),
        "valuation_gap_pct": round(gap_pct, 2),
    }


def _dcf_value(free_cash_flow: float, growth_rate: float, discount_rate: float, terminal_growth: float) -> float:
    if discount_rate <= terminal_growth:
        return 0.0
    projected = [free_cash_flow * ((1 + growth_rate) ** year) for year in range(1, 6)]
    discounted = [value / ((1 + discount_rate) ** year) for year, value in enumerate(projected, start=1)]
    terminal = projected[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    discounted_terminal = terminal / ((1 + discount_rate) ** 5)
    return sum(discounted) + discounted_terminal


def _relative_valuation_model(
    symbol: str,
    period: str,
    revenue: float,
    net_income: float,
    pe_multiple: float,
    ps_multiple: float,
    shares_outstanding_billion: float | None,
) -> Dict[str, Any]:
    pe_value = net_income * pe_multiple
    ps_value = revenue * ps_multiple
    return {
        "symbol": symbol,
        "period": period,
        "currency": "USD",
        "unit": "billion",
        "multiples": {
            "pe": {
                "numerator": "equity_value_billion",
                "denominator": "net_income_billion",
                "denominator_value": round(net_income, 6),
                "multiple": pe_multiple,
                "equity_value_billion": round(pe_value, 2),
                "target_price": _target_price(pe_value, shares_outstanding_billion),
            },
            "ps": {
                "numerator": "equity_value_billion",
                "denominator": "revenue_billion",
                "denominator_value": round(revenue, 6),
                "multiple": ps_multiple,
                "equity_value_billion": round(ps_value, 2),
                "target_price": _target_price(ps_value, shares_outstanding_billion),
            },
        },
        "scenario_values": {
            "bear": round(min(pe_value, ps_value) * 0.9, 2),
            "base": round((pe_value + ps_value) / 2, 2),
            "bull": round(max(pe_value, ps_value) * 1.1, 2),
        },
    }


def _build_dcf_model(
    symbol: str,
    period: str,
    free_cash_flow: float,
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
    shares_outstanding_billion: float | None,
) -> Dict[str, Any]:
    forecast = []
    pv_fcf = 0.0
    for year in range(1, 6):
        fcf = free_cash_flow * ((1 + growth_rate) ** year)
        pv = fcf / ((1 + discount_rate) ** year)
        pv_fcf += pv
        forecast.append({"year": year, "free_cash_flow_billion": round(fcf, 6), "present_value_billion": round(pv, 6)})
    terminal_value = forecast[-1]["free_cash_flow_billion"] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** 5)
    enterprise_value = pv_fcf + pv_terminal
    net_debt = 0.0
    equity_value = enterprise_value - net_debt
    return {
        "symbol": symbol,
        "period": period,
        "currency": "USD",
        "unit": "billion",
        "assumptions": {
            "base_free_cash_flow_billion": round(free_cash_flow, 6),
            "fcf_growth": round(growth_rate, 6),
            "discount_rate": round(discount_rate, 6),
            "terminal_growth": round(terminal_growth, 6),
            "forecast_years": 5,
            "net_debt_billion": net_debt,
            "shares_outstanding_billion": shares_outstanding_billion,
        },
        "forecast": forecast,
        "terminal_value_billion": round(terminal_value, 6),
        "pv_terminal_value_billion": round(pv_terminal, 6),
        "enterprise_value_billion": round(enterprise_value, 6),
        "equity_value_billion": round(equity_value, 6),
        "target_price": _target_price(equity_value, shares_outstanding_billion),
    }


def _valuation_sensitivity(
    free_cash_flow: float,
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
    shares_outstanding_billion: float | None,
) -> Dict[str, Any]:
    scenarios = {}
    for name, growth_delta, discount_delta in [
        ("bear", -0.02, 0.01),
        ("base", 0.0, 0.0),
        ("bull", 0.02, -0.01),
    ]:
        value = _dcf_value(
            free_cash_flow=free_cash_flow,
            growth_rate=max(growth_rate + growth_delta, 0.0),
            discount_rate=max(discount_rate + discount_delta, terminal_growth + 0.01),
            terminal_growth=terminal_growth,
        )
        scenarios[name] = {
            "equity_value_billion": round(value, 2),
            "target_price": _target_price(value, shares_outstanding_billion),
        }
    return {
        "scenario_values": scenarios,
        "directional_check": scenarios["bull"]["equity_value_billion"] >= scenarios["base"]["equity_value_billion"] >= scenarios["bear"]["equity_value_billion"],
    }


def _target_price(equity_value_billion: float, shares_outstanding_billion: float | None) -> float | None:
    if not shares_outstanding_billion:
        return None
    return round(equity_value_billion / shares_outstanding_billion, 4)


def _recommendation(revenue_growth: float, net_margin: float, roe: float, peer_growth: float, peer_margin: float) -> str:
    score = 0
    if revenue_growth >= peer_growth:
        score += 1
    if net_margin >= peer_margin:
        score += 1
    if roe >= 20:
        score += 1
    if score >= 3:
        return "积极关注"
    if score == 2:
        return "中性偏积极"
    return "中性观察"


def _median_numeric(rows: List[Dict[str, Any]], key: str, fallback: float) -> float:
    values = [_safe_float(row.get(key)) for row in rows]
    parsed = [value for value in values if value is not None]
    return float(median(parsed)) if parsed else fallback


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _valuation_guardrail(
    revenue: float,
    net_income: float,
    free_cash_flow: float,
    pe_value: float,
    ps_value: float,
    dcf_value: float,
    blended_value: float,
    market_context: Dict[str, Any],
    shares_outstanding_billion: float | None,
) -> Dict[str, Any]:
    """Block obviously unusable valuation outputs before they reach claims."""

    errors: List[str] = []
    warnings: List[str] = []
    method_values = {"pe": pe_value, "ps": ps_value, "dcf": dcf_value, "blended": blended_value}
    for name, value in method_values.items():
        if not _is_finite_positive(value):
            errors.append(f"{name}_value_not_positive_or_finite")

    if revenue <= 0:
        errors.append("revenue_not_positive")
    else:
        value_to_revenue = blended_value / revenue if blended_value > 0 else 0.0
        dcf_to_revenue = dcf_value / revenue if dcf_value > 0 else 0.0
        if value_to_revenue > 80:
            errors.append("blended_value_to_revenue_above_guardrail")
        if dcf_to_revenue > 120:
            errors.append("dcf_value_to_revenue_above_guardrail")

    if net_income < 0 and pe_value > 0:
        errors.append("pe_value_positive_with_negative_net_income")

    if free_cash_flow > 0 and dcf_value / free_cash_flow > 100:
        errors.append("dcf_value_to_fcf_above_guardrail")

    market_cap = _safe_float(market_context.get("market_cap_billion"))
    if market_cap and blended_value > 0:
        market_gap_abs = abs((blended_value - market_cap) / market_cap)
        if market_gap_abs > 10:
            warnings.append("valuation_market_gap_above_1000pct")

    last_close = _safe_float(market_context.get("last_close"))
    if last_close and shares_outstanding_billion and blended_value > 0:
        target_price = blended_value / shares_outstanding_billion
        if target_price / last_close > 10 or target_price / last_close < 0.1:
            warnings.append("target_price_to_last_close_outside_guardrail")

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "limits": {
            "max_blended_value_to_revenue": 80,
            "max_dcf_value_to_revenue": 120,
            "max_dcf_value_to_fcf": 100,
        },
    }


def _is_finite_positive(value: Any) -> bool:
    parsed = _safe_float(value)
    return parsed is not None and parsed > 0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value) == "nan":
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
