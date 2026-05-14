"""Peer comparison and valuation helpers for company reports."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd


_VALUATION_PEER_GROUPS: Dict[str, Dict[str, List[str]]] = {
    "Financials": {"core": ["JPM", "BAC", "WFC", "C"], "extended": ["GS", "MS"]},
    "Communication Services": {"core": ["META", "GOOGL"], "extended": ["NFLX", "DIS", "T"]},
    "China Liquor": {"core": ["600519.SS", "000858.SZ", "000568.SZ", "600809.SH"], "extended": ["603369.SH"]},
}


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
    peer_groups = _local_peer_groups(symbol=symbol, sector=target_sector)
    preferred_symbols = set(peer_groups.get("core", []) + peer_groups.get("extended", []))
    if preferred_symbols:
        peers = [
            row
            for row in rows
            if row.get("symbol") != symbol and str(row.get("symbol", "")).upper() in preferred_symbols
        ]
    else:
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
        "peer_groups": peer_groups,
        "peer_rows": peer_rows,
        "peer_count": max(len(peer_rows) - 1, 0),
        "ranking": ranking,
    }


def _local_peer_groups(symbol: str, sector: str) -> Dict[str, List[str]]:
    symbol = str(symbol or "").upper()
    sector_lower = str(sector).lower()
    if symbol in {"600519.SS", "600519.SH", "000858.SZ", "000568.SZ", "600809.SH", "603369.SH"} or "白酒" in sector_lower or "liquor" in sector_lower:
        group = _VALUATION_PEER_GROUPS["China Liquor"]
    elif symbol in {"JPM", "BAC", "WFC", "C", "GS", "MS"} or "financial" in sector_lower:
        group = _VALUATION_PEER_GROUPS["Financials"]
    elif symbol in {"META", "GOOGL", "NFLX", "DIS", "T"} or "communication" in sector_lower:
        group = _VALUATION_PEER_GROUPS["Communication Services"]
    else:
        return {"core": [], "extended": []}
    return {
        "core": [item for item in group["core"] if item != symbol],
        "extended": [item for item in group["extended"] if item != symbol],
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

    currency = _valuation_currency(symbol=symbol, target=target, records=records or [])
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

    # Annualize quarterly income statement figures for P/E and P/S valuation.
    # net_income_billion and revenue_billion from SEC are single-quarter values for 10-Q filings.
    # P/E and P/S multiples are conventionally applied to TTM or annualized figures.
    annualization_factor = int(target.get("annualization_factor") or 1)
    is_quarterly = bool(target.get("is_quarterly", annualization_factor == 4))
    net_income_annualized = net_income * annualization_factor
    revenue_annualized = revenue * annualization_factor
    # FCF for DCF: also annualize if quarterly, but cap at a reasonable level
    free_cash_flow_annualized = (
        _safe_float(target.get("free_cash_flow_billion")) or max(net_income * 0.75, 0.0)
    ) * annualization_factor

    sector = str(target.get("sector") or "")
    industry = str(target.get("industry") or "")
    is_financial = _is_financial_sector(sector, industry) or _is_known_financial_symbol(symbol)
    base_pe_multiple = 12.0 if is_financial else 18.0
    valuation_method_warning = (
        "金融行业估值：已将 P/E 基础倍数调整为 12x；P/S 和 FCF DCF 对银行业适用性有限，结果仅供参考。"
        if is_financial else ""
    )

    peer_rows = [row for row in peer_payload.get("peer_rows", []) if row.get("symbol") != symbol]
    peer_growth = _median_numeric(peer_rows, "revenue_growth_pct", fallback=revenue_growth)
    peer_margin = _median_numeric(peer_rows, "net_margin_pct", fallback=net_margin)
    growth_premium = _bounded(1 + (revenue_growth - peer_growth) / 100, 0.75, 1.35)
    margin_premium = _bounded(1 + (net_margin - peer_margin) / 100, 0.75, 1.35)

    pe_multiple = round(_bounded(base_pe_multiple * growth_premium * margin_premium, 10, 40), 2)
    ps_multiple = round(_bounded(4 * growth_premium * (1 + net_margin / 100), 1.5, 14), 2)
    discount_rate = 0.10
    terminal_growth = 0.025
    fcf_growth = _bounded(revenue_growth / 100, 0.02, 0.20)

    # Use annualized figures for P/E and P/S so multiples apply to full-year equivalents
    pe_value = net_income_annualized * pe_multiple
    ps_value = revenue_annualized * ps_multiple
    dcf_value = _dcf_value(free_cash_flow=free_cash_flow_annualized, growth_rate=fcf_growth, discount_rate=discount_rate, terminal_growth=terminal_growth)

    # Industry-specific valuation models
    bank_valuation: Dict[str, Any] = {}
    if is_financial:
        equity = _safe_float(target.get("shareholder_equity_billion")) or 0.0
        if equity <= 0:
            # Fallback: try to derive equity from total_assets and a typical leverage ratio
            total_assets = _safe_float(target.get("total_assets_billion")) or 0.0
            equity = total_assets * 0.09 if total_assets > 0 else 0.0  # ~9% equity/assets for large banks
        pb_multiple = round(_bounded(1.2 * growth_premium, 0.8, 2.5), 2)
        pb_value = equity * pb_multiple if equity > 0 else 0.0
        pb_available = equity > 0
        payout_ratio = 0.35
        cost_of_equity = 0.10
        ddm_dividend = net_income_annualized * payout_ratio
        ddm_value = (ddm_dividend / (cost_of_equity - terminal_growth)) if cost_of_equity > terminal_growth else 0.0
        bank_valuation = {
            "pb": {
                "multiple": pb_multiple,
                "book_equity_billion": round(equity, 2),
                "value_billion": round(pb_value, 2),
                "equity_source": "SEC XBRL StockholdersEquity" if pb_available else "estimated (9% of total assets)",
            },
            "ddm": {
                "payout_ratio": payout_ratio,
                "cost_of_equity": cost_of_equity,
                "terminal_growth": terminal_growth,
                "dividend_proxy_billion": round(ddm_dividend, 2),
                "value_billion": round(ddm_value, 2),
                "note": (
                    f"Gordon Growth Model: D/(Ke-g) = annualized net income {round(net_income_annualized,2)}B "
                    f"× payout ratio {payout_ratio:.0%} = dividend proxy {round(ddm_dividend,2)}B "
                    f"/ ({cost_of_equity:.0%} - {terminal_growth:.1%})"
                ),
            },
            "note": (
                "银行业主流估值框架：P/B（账面价值倍数）和 DDM（股息折现模型）。"
                "P/E 可作辅助参考；P/S 和 FCF DCF 对银行业适用性有限，权重已降低。"
            ),
        }
        bank_values = [v for v in [pb_value, ddm_value, pe_value] if v > 0]
        blended_value = sum(bank_values) / len(bank_values) if bank_values else 0.0
    else:
        blended_value_components = [value for value in [pe_value, ps_value, dcf_value] if value > 0]
        blended_value = sum(blended_value_components) / len(blended_value_components) if blended_value_components else 0.0
    relative_valuation = _relative_valuation_model(
        symbol=symbol,
        period=period,
        revenue=revenue_annualized,
        net_income=net_income_annualized,
        pe_multiple=pe_multiple,
        ps_multiple=ps_multiple,
        shares_outstanding_billion=shares_outstanding,
    )
    dcf_model = _build_dcf_model(
        symbol=symbol,
        period=period,
        free_cash_flow=free_cash_flow_annualized,
        growth_rate=fcf_growth,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        shares_outstanding_billion=shares_outstanding,
    )
    valuation_sensitivity = _valuation_sensitivity(
        free_cash_flow=free_cash_flow_annualized,
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
        "currency": currency,
        "is_financial_sector": is_financial,
        "methods": {
            "pe": {"multiple": pe_multiple, "value_billion": round(pe_value, 2)},
            "ps": {"multiple": ps_multiple, "value_billion": round(ps_value, 2), "note": "适用性有限（银行业）" if is_financial else ""},
            "dcf": {
                "discount_rate": discount_rate,
                "terminal_growth": terminal_growth,
                "fcf_growth": round(fcf_growth, 4),
                "value_billion": round(dcf_value, 2),
                "note": "适用性有限（银行业）" if is_financial else "",
            },
            **({"bank_specific": bank_valuation} if is_financial else {}),
        },
        "blended_equity_value_billion": round(blended_value, 2),
        "blended_method_note": (
            "综合估值基于 P/B + DDM + P/E（银行业主流框架）" if is_financial
            else "综合估值基于 P/E + P/S + DCF 等权平均"
        ),
        "sensitivity": _build_sensitivity(
            is_financial=is_financial,
            bank_valuation=bank_valuation,
            equity=_safe_float(target.get("shareholder_equity_billion")) or 0.0,
            net_income_annualized=net_income_annualized,
            free_cash_flow_annualized=free_cash_flow_annualized,
            fcf_growth=fcf_growth,
            discount_rate=discount_rate,
            terminal_growth=terminal_growth,
        ),
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
        "valuation_method_warning": valuation_method_warning,
        "assumptions": [
            "估值为规则模型生成的第一版相对估值/DCF 区间，不构成投资建议。",
            "缺少完整股本与实时市值时，输出为企业/股权价值规模估计。",
        ],
    }


def _build_sensitivity(
    is_financial: bool,
    bank_valuation: Dict[str, Any],
    equity: float,
    net_income_annualized: float,
    free_cash_flow_annualized: float,
    fcf_growth: float,
    discount_rate: float,
    terminal_growth: float,
) -> Dict[str, Any]:
    if is_financial and bank_valuation:
        ddm_info = bank_valuation.get("ddm", {})
        payout_ratio = float(ddm_info.get("payout_ratio", 0.35) or 0.35)
        cost_of_equity = float(ddm_info.get("cost_of_equity", 0.10) or 0.10)
        pb_multiple = float((bank_valuation.get("pb") or {}).get("multiple", 1.2) or 1.2)
        dividend = net_income_annualized * payout_ratio

        def _ddm(ke: float, g: float) -> float:
            return round(dividend / (ke - g), 2) if ke > g else 0.0

        def _pb(mult: float) -> float:
            return round(equity * mult, 2) if equity > 0 else 0.0

        return {
            "type": "bank",
            "pb_low": _pb(max(pb_multiple - 0.3, 0.5)),
            "pb_mid": _pb(pb_multiple),
            "pb_high": _pb(pb_multiple + 0.3),
            "pb_multiples": [round(pb_multiple - 0.3, 1), round(pb_multiple, 1), round(pb_multiple + 0.3, 1)],
            "ddm_ke_low": _ddm(max(cost_of_equity - 0.01, 0.06), terminal_growth),
            "ddm_ke_mid": _ddm(cost_of_equity, terminal_growth),
            "ddm_ke_high": _ddm(cost_of_equity + 0.01, terminal_growth),
            "ddm_g_low": _ddm(cost_of_equity, max(terminal_growth - 0.005, 0.01)),
            "ddm_g_mid": _ddm(cost_of_equity, terminal_growth),
            "ddm_g_high": _ddm(cost_of_equity, terminal_growth + 0.005),
            "note": (
                f"银行业敏感性：P/B 倍数 {pb_multiple-0.3:.1f}x / {pb_multiple:.1f}x / {pb_multiple+0.3:.1f}x；"
                f"DDM 权益成本 {cost_of_equity-0.01:.0%} / {cost_of_equity:.0%} / {cost_of_equity+0.01:.0%}；"
                f"DDM 永续增长率 {terminal_growth-0.005:.1%} / {terminal_growth:.1%} / {terminal_growth+0.005:.1%}。"
            ),
        }
    else:
        return {
            "type": "dcf",
            "fcf_growth_minus_2pct": round(_dcf_value(free_cash_flow_annualized, max(fcf_growth - 0.02, 0.0), discount_rate, terminal_growth), 2),
            "fcf_growth_plus_2pct": round(_dcf_value(free_cash_flow_annualized, fcf_growth + 0.02, discount_rate, terminal_growth), 2),
            "discount_rate_plus_1pct": round(_dcf_value(free_cash_flow_annualized, fcf_growth, discount_rate + 0.01, terminal_growth), 2),
        }


def _resolve_period_dir(symbol_dir: Path, period: str) -> Path | None:
    exact = symbol_dir / period
    if exact.exists():
        return exact
    subdirs = sorted(
        [d for d in symbol_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    return subdirs[0] if subdirs else None


def _load_company_financial_rows(raw_data_root: str | Path, period: str) -> List[Dict[str, Any]]:
    root = Path(raw_data_root)
    rows: List[Dict[str, Any]] = []
    if not root.exists():
        return rows
    for symbol_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        period_dir = _resolve_period_dir(symbol_dir, period)
        if period_dir is None:
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
        "shareholder_equity_billion": _safe_float(row.get("shareholder_equity_billion")),
        "total_assets_billion": _safe_float(row.get("total_assets_billion")),
        "currency": str(row.get("currency") or ""),
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
        result = _peer_row(row, target_symbol=symbol)
        # Carry through annualization metadata so valuation can apply correct scaling
    result["is_quarterly"] = bool(metadata.get("is_quarterly", False))
    result["annualization_factor"] = int(metadata.get("annualization_factor") or 1)
    result["currency"] = str(metadata.get("currency") or "")
    return result
    return {}


def _market_context_from_records(records: List[Dict[str, Any]], symbol: str, period: str) -> Dict[str, Any]:
    market_record = None
    for record in records:
        if str(record.get("symbol", "")).upper() != symbol:
            continue
        if str(record.get("source_type", "")).lower() not in {"market", "market_api"}:
            continue
        market_record = record
        break

    if market_record is None:
        return {}

    metadata = market_record.get("metadata") if isinstance(market_record.get("metadata"), dict) else {}
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

    # Fallback: use diluted_shares from SEC financials record to compute market cap
    if not shares:
        for record in records:
            if str(record.get("symbol", "")).upper() != symbol:
                continue
            if str(record.get("source_type", "")).lower() != "financials":
                continue
            fin_meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            shares = _safe_float(fin_meta.get("diluted_shares_billion"))
            if shares:
                break

    if not market_cap and last_close and shares:
        market_cap = round(last_close * shares, 4)

    return {
        "symbol": symbol,
        "period": period,
        "last_close": last_close,
        "market_cap_billion": market_cap,
        "shares_outstanding_billion": shares,
        "snapshot_time_et": str(snapshot.get("snapshot_time_et") or market_record.get("publish_time") or ""),
        "snapshot_time_utc": str(snapshot.get("snapshot_time_utc") or ""),
        "provider": str(metadata.get("provider") or snapshot.get("provider") or "market_data"),
        "source_evidence_id": str(market_record.get("evidence_id") or market_record.get("sample_id") or ""),
        "source_url": str(market_record.get("source_url") or ""),
    }



def _market_gap(blended_value: float, market_context: Dict[str, Any]) -> Dict[str, Any]:
    market_cap = _safe_float(market_context.get("market_cap_billion"))
    if not market_cap:
        return {"available": False}
    gap_pct = ((blended_value - market_cap) / market_cap) * 100 if market_cap else 0.0
    ratio = blended_value / market_cap if market_cap else None
    abs_gap_pct = abs(gap_pct)
    sanity_ok = abs_gap_pct <= 50.0
    sanity_level = None
    sanity_warning = None
    if ratio is not None and not sanity_ok:
        direction = "大幅折价" if ratio < 1.0 else "大幅溢价"
        if abs_gap_pct > 70.0:
            sanity_level = "high"
            sanity_warning = (
                f"估值与市值差异 {gap_pct:+.1f}%（内在价值/市值={ratio:.2f}），{direction}超过 70%。"
                " 请核查：1) 季度/年化/TTM 口径；2) 股本与货币单位；3) 行业估值模型适配性；"
                "4) 倍数或 FCF 基准。银行/保险等金融企业请优先考虑 P/B、P/TBV、RIM 或 DDM。"
            )
        else:
            sanity_level = "medium"
            sanity_warning = (
                f"估值与市值差异 {gap_pct:+.1f}%（内在价值/市值={ratio:.2f}），{direction}超过 50%。"
                " 请复核估值假设与行业适配性。"
            )
    return {
        "available": True,
        "market_cap_billion": round(market_cap, 2),
        "last_close": _safe_float(market_context.get("last_close")),
        "shares_outstanding_billion": _safe_float(market_context.get("shares_outstanding_billion")),
        "valuation_gap_pct": round(gap_pct, 2),
        "valuation_gap_ratio": round(ratio, 3) if ratio is not None else None,
        "snapshot_time_et": str(market_context.get("snapshot_time_et") or ""),
        "snapshot_time_utc": str(market_context.get("snapshot_time_utc") or ""),
        "provider": str(market_context.get("provider") or "market_data"),
        "source_url": str(market_context.get("source_url") or ""),
        "sanity_ok": sanity_ok,
        "sanity_level": sanity_level,
        "sanity_warning": sanity_warning,
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


def _valuation_currency(symbol: str, target: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    explicit = str(target.get("currency") or "").strip()
    if explicit:
        return explicit
    for record in records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        currency = str(metadata.get("currency") or record.get("currency") or "").strip()
        if currency:
            return currency
    text = str(symbol or "").upper()
    if text.endswith((".SS", ".SH", ".SZ", ".BJ")):
        return "CNY_billion"
    if text.endswith(".HK"):
        return "HKD_billion"
    return "USD_billion"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def is_financial_sector(sector: str, industry: str) -> bool:
    """Public wrapper: True if the company is in the financial sector (banks, insurance, etc.)."""
    return _is_financial_sector(sector, industry)


def is_known_financial_symbol(symbol: str) -> bool:
    """Public wrapper: True for well-known financial tickers when sector metadata is unavailable."""
    return _is_known_financial_symbol(symbol)


def _is_financial_sector(sector: str, industry: str) -> bool:
    """Return True if the company is in the financial sector (banks, insurance, etc.)."""
    financial_keywords = {"financial", "bank", "insurance", "diversified financial", "capital markets"}
    sector_lower = sector.lower()
    industry_lower = industry.lower()
    return any(kw in sector_lower or kw in industry_lower for kw in financial_keywords)


def _is_known_financial_symbol(symbol: str) -> bool:
    """Fallback: return True for well-known financial sector tickers when sector metadata is unavailable."""
    known_financials = {
        "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF",
        "BK", "STT", "SCHW", "AXP", "V", "MA", "BRK.A", "BRK.B",
        "MET", "PRU", "AFL", "ALL", "AIG", "CB", "TRV", "HIG",
    }
    return symbol.upper() in known_financials
