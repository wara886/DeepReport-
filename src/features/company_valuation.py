"""Peer comparison and valuation helpers for company reports."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd


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
    net_income = _safe_float(target.get("net_income_billion"))
    if net_income is None:
        net_margin = _safe_float(target.get("net_margin_pct")) or 0.0
        net_income = revenue * net_margin / 100
    free_cash_flow = _safe_float(target.get("free_cash_flow_billion")) or max(net_income * 0.75, 0.0)
    market_context = _market_context_from_records(records=records or [], symbol=symbol, period=period)
    shares_outstanding = _safe_float(market_context.get("shares_outstanding_billion"))
    revenue_growth = _safe_float(target.get("revenue_growth_pct")) or 0.0
    net_margin = _safe_float(target.get("net_margin_pct")) or 0.0
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
            row["net_income_billion"] = round(revenue * net_margin / 100, 4)
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
    for record in records:
        if str(record.get("symbol", "")).upper() != symbol:
            continue
        if str(record.get("source_type", "")).lower() != "financials":
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        row = dict(metadata)
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
        last_close = _safe_float(snapshot.get("last_close") or snapshot.get("close"))
        market_cap = _safe_float(
            snapshot.get("market_cap_billion")
            or snapshot.get("marketCapBillion")
            or snapshot.get("market_cap")
            or snapshot.get("marketCap")
        )
        shares = _safe_float(snapshot.get("shares_outstanding_billion") or snapshot.get("sharesOutstandingBillion"))
        if market_cap and market_cap > 1_000_000:
            market_cap = market_cap / 1_000_000_000
        if not market_cap and last_close and shares:
            market_cap = last_close * shares
        return {
            "symbol": symbol,
            "period": period,
            "last_close": last_close,
            "market_cap_billion": market_cap,
            "shares_outstanding_billion": shares,
            "source_evidence_id": str(record.get("evidence_id") or record.get("sample_id") or ""),
            "source_url": str(record.get("source_url") or ""),
        }
    return {}


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
