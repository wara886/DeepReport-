"""Peer comparison and valuation helpers for company reports."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from statistics import median
from typing import Any, Dict, List
from urllib import request as _req_lib
from urllib.parse import urlencode as _urlencode

import pandas as pd
import yfinance as yf

from src.data.company_universe import infer_market_from_symbol
from src.data.financial_quality import build_net_income_quality_fields
from src.market.currency_rules import infer_statement_currency, infer_trading_currency, is_official_financial_source
from src.utils.money import MoneyValue, UNKNOWN_CURRENCY, convert_money

logger = logging.getLogger(__name__)

DEFAULT_FX_RATES = {
    ("CNY", "HKD"): {"rate": 1.09, "date": "2026-05-31"},
    ("HKD", "CNY"): {"rate": 1 / 1.09, "date": "2026-05-31"},
    ("CNY", "USD"): {"rate": 1 / 7.10, "date": "2026-05-31"},
    ("USD", "CNY"): {"rate": 7.10, "date": "2026-05-31"},
    ("HKD", "USD"): {"rate": 1 / 7.80, "date": "2026-05-31"},
    ("USD", "HKD"): {"rate": 7.80, "date": "2026-05-31"},
}


def build_peer_comparison(
    symbol: str,
    period: str,
    raw_data_root: str | Path = "data/raw/real_data",
    allow_external_discovery: bool = False,
) -> Dict[str, Any]:
    """Build a peer table without silently inventing or fetching fallback peers.

    External discovery is opt-in so report generation and tests remain deterministic.
    Missing peer evidence is returned as an explicit, market-scoped data gap.
    """

    symbol = str(symbol or "").upper()
    market_info = infer_market_from_symbol(symbol)
    market = str(market_info.get("market", "") if isinstance(market_info, dict) else market_info)
    rows = _load_company_financial_rows(raw_data_root=raw_data_root, period=period)
    target = next((row for row in rows if row.get("symbol") == symbol), None)
    if not target:
        if allow_external_discovery:
            try:
                discovered = _discover_peers_via_search(symbol=symbol, period=period)
                if discovered.get("peer_count", 0) > 0 or discovered.get("target_row"):
                    return discovered
            except Exception as exc:
                logger.warning("Peer discovery via search failed for %s: %s", symbol, exc)
        return {
            "target_symbol": symbol,
            "target_market": market,
            "peer_rows": [],
            "peer_count": 0,
            "ranking": {},
            "source": "local_only_market_isolated",
            "failure_reason": "no_local_same_market_peer_data",
        }

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
    peer_count = max(len(peer_rows) - 1, 0)

    # External discovery is an explicit operation, not an invisible fallback.
    if peer_count == 0 and allow_external_discovery:
        try:
            discovered = _discover_peers_via_search(symbol=symbol, period=period)
            if discovered.get("peer_count", 0) > 0:
                for row in discovered.get("peer_rows", []):
                    if row.get("is_target"):
                        # update target with Yahoo data if local had nothing
                        if not target.get("revenue_billion"):
                            target_row = _peer_row(row, target_symbol=symbol)
                            peer_rows[0] = target_row
                    else:
                        peer_rows.append(row)
                peer_count = max(len(peer_rows) - 1, 0)
                ranking = _rank_target(peer_rows, symbol=symbol)
                logger.info("Discovered %d peers via Yahoo/web for %s", peer_count, symbol)
        except Exception as exc:
            logger.warning("Peer discovery via search failed for %s: %s", symbol, exc)

    return {
        "target_symbol": symbol,
        "target_market": market,
        "target_sector": target_sector,
        "target_industry": target_industry,
        "peer_rows": peer_rows,
        "peer_count": peer_count,
        "ranking": ranking,
    }


def _discover_peers_via_search(
    symbol: str,
    period: str,
) -> Dict[str, Any]:
    """Fall back to Yahoo Finance + web search when local peer data is missing."""

    market_info = infer_market_from_symbol(str(symbol or "").upper())
    market = str(market_info.get("market", "") if isinstance(market_info, dict) else market_info)
    if market in {"hk"}:
        return {
            "target_symbol": str(symbol or "").upper(),
            "target_market": market,
            "peer_rows": [],
            "peer_count": 0,
            "ranking": {},
            "source": "disabled_for_market_isolation",
            "failure_reason": "yahoo_us_peer_discovery_disabled_for_hk",
        }

    peer_rows: List[Dict[str, Any]] = []
    peer_symbols: List[str] = []
    target_company = ""
    sector = ""
    industry = ""

    # --- Phase 1: get sector/industry from Yahoo Finance ---
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        target_company = str(info.get("longName") or info.get("shortName") or symbol)
        sector = str(info.get("sector") or "")
        industry = str(info.get("industry") or "")
    except Exception:
        logger.warning("Yahoo Finance info unavailable for %s, falling back to symbol name", symbol)
        target_company = symbol
        # For A-shares, try to get Chinese company name from alias table
        if market == "cn_a":
            try:
                from src.app.company_aliases import resolve_company_alias as _rca
                alias_hit = _rca(symbol)
                if alias_hit:
                    target_company = str(alias_hit.get("company_name", symbol))
                    logger.info("Resolved A-share company name via alias table: %s", target_company)
            except Exception:
                pass

    # --- Phase 2: discover peer symbols via Serper web search ---
    try:
        from src.search.search_manager import serper_search

        search_query = f"{target_company} competitors list revenue market cap {period}"
        search_results = serper_search(search_query, topk=5)
        if isinstance(search_results, list):
            combined_text = " ".join(
                str(r.get("title", "") or "") + " " + str(r.get("snippet", "") or "")
                for r in search_results if isinstance(r, dict)
            )
        elif isinstance(search_results, dict):
            combined_text = json.dumps(search_results, ensure_ascii=False)
        else:
            combined_text = str(search_results)

        # Try a second search with simpler phrasing
        search_query2 = f"top {target_company} competitors financial data"
        search_results2 = serper_search(search_query2, topk=5)
        if isinstance(search_results2, list):
            combined_text2 = " ".join(
                str(r.get("title", "") or "") + " " + str(r.get("snippet", "") or "")
                for r in search_results2 if isinstance(r, dict)
            )
        elif isinstance(search_results2, dict):
            combined_text2 = json.dumps(search_results2, ensure_ascii=False)
        else:
            combined_text2 = str(search_results2)
        combined_text = combined_text + " " + combined_text2

        # Extract known ticker symbols from search text using common patterns
        # Match uppercase 1-4 letter words that are likely stock symbols
        import re
        known_symbols = {"AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
                         "AMD", "INTC", "IBM", "ORCL", "CRM", "ADBE", "NFLX", "DIS",
                         "V", "MA", "JPM", "BAC", "WMT", "PG", "KO", "PEP", "JNJ",
                         "UNH", "HD", "BA", "CAT", "GE", "F", "GM", "XOM", "CVX",
                         "CSCO", "QCOM", "TXN", "AVGO", "MRK", "ABBV", "LLY", "NKE",
                         "MCD", "SBUX", "UPS", "FDX", "LMT", "NOC", "RTX", "DUK",
                         "NEE", "SO", "T", "VZ", "CMCSA", "CHTR", "PYPL", "SQ",
                         "SNAP", "UBER", "LYFT", "DASH", "SPOT", "RIVN", "LCID",
                         "PLTR", "SNOW", "DDOG", "NET", "CRWD", "ZS", "PANW",
                         "BABA", "JD", "BIDU", "TCEHY", "NIO", "XPEV", "LI",
                         "TSM", "ASML", "SAP", "SIE", "NSRGY",
                         "HDB", "IBN", "INFY", "WIT", "RELIANCE"}
        found = set()
        for word in re.findall(r'\b[A-Z]{2,4}\b', combined_text):
            if word in known_symbols and word != symbol:
                found.add(word)
        peer_symbols = sorted(found)[:6]
    except Exception as exc:
        logger.warning("Serper peer search failed for %s: %s", symbol, exc)
        peer_symbols = []

    us_industry_peer_map = {
        "auto manufacturers": ["F", "GM", "RIVN", "LCID"],
        "semiconductors": ["NVDA", "AMD", "INTC", "QCOM", "AVGO", "TXN"],
        "software": ["MSFT", "ORCL", "CRM", "ADBE"],
        "internet retail": ["AMZN", "EBAY"],
    }
    industry_key = str(industry or "").lower()
    matched_industry_peers: List[str] = []
    for name, candidates in us_industry_peer_map.items():
        if name in industry_key or industry_key in name:
            matched_industry_peers = [item for item in candidates if item != symbol]
            break
    if matched_industry_peers:
        allowed = set(matched_industry_peers)
        peer_symbols = [item for item in peer_symbols if item in allowed]
        if not peer_symbols:
            peer_symbols = matched_industry_peers[:6]

    # --- Phase 3: if web search found no peers, try sector/industry peer lists ---
    if not peer_symbols and (sector or industry or market == "cn_a"):
        try:
            # For A-shares, use Chinese industry peer groups
            if market == "cn_a" or any(cn_keyword in (target_company + sector + industry) for cn_keyword in ["中国", "贵州", "保险", "银行", "白酒", "证券"]):
                # A-share industry peer groups (hardcoded from 2025 年报覆盖标的)
                cn_industry_peers = {
                    "白酒": ["600519.SS", "000858.SZ", "600809.SS", "000568.SZ", "002304.SZ", "603369.SS", "600779.SS", "000799.SZ", "600702.SS", "603589.SS"],
                    "保险": ["601318.SS", "601628.SS", "601601.SS", "601336.SS", "601319.SS"],
                    "银行": ["600036.SS", "601398.SS", "601939.SS", "601288.SS", "601988.SS", "600016.SS", "000001.SZ", "002142.SZ"],
                    "证券": ["600030.SS", "601211.SS", "600837.SS", "601688.SS", "601066.SS"],
                    "动力电池": ["300750.SZ", "002074.SZ", "300014.SZ", "300124.SZ"],
                    "新能源汽车": ["300750.SZ", "002594.SZ", "601238.SS", "000625.SZ"],
                    "半导体": ["688981.SS", "603501.SS", "600703.SS", "002049.SZ", "688012.SS"],
                    "医药": ["600276.SS", "300760.SZ", "000538.SZ", "600196.SS", "002422.SZ", "300015.SZ"],
                    "消费电子": ["002475.SZ", "000725.SZ", "601138.SS", "603160.SS"],
                    "互联网": ["300059.SZ", "002230.SZ", "300033.SZ"],
                    "房地产": ["000002.SZ", "600048.SS", "001979.SZ"],
                    "家电": ["000333.SZ", "600690.SS", "000651.SZ", "002242.SZ"],
                }
                # Match target_company or sector/industry keywords
                combined_haystack = (target_company + " " + sector + " " + industry).lower()
                for cn_industry, candidates in cn_industry_peers.items():
                    if cn_industry in combined_haystack:
                        peer_symbols = [s for s in candidates if s != symbol][:5]
                        break
                # If still no match via keyword, use the first two characters of the stock code
                # to find same-exchange peers with similar industry
                if not peer_symbols and symbol.endswith((".SS", ".SZ")):
                    cn_code = symbol.split(".")[0]
                    exchange = ".SS" if ".SS" in symbol else ".SZ"
                    # Try broader keyword match on company name
                    cn_name_keywords = {
                        "贵州茅台": ["000858.SZ", "600809.SS", "000568.SZ"],
                        "宁德时代": ["002074.SZ", "300014.SZ", "300124.SZ"],
                        "中国平安": ["601628.SS", "601601.SS", "601336.SS"],
                        "招商银行": ["601398.SS", "601939.SS", "601288.SS"],
                        "中芯国际": ["603501.SS", "600703.SS", "002049.SZ"],
                        "比亚迪": ["300750.SZ", "601238.SS", "000625.SZ"],
                    }
                    for name, candidates in cn_name_keywords.items():
                        if name in target_company:
                            peer_symbols = [s for s in candidates if s != symbol][:5]
                            break
                # If hardcoded mapping didn't match, try eastmoney API by INDUSTRY_CODE
                if not peer_symbols and market == "cn_a":
                    ind_code = _get_industry_code_via_eastmoney_api(symbol)
                    if not ind_code:
                        # Direct fallback: call eastmoney income API for INDUSTRY_CODE
                        try:
                            from src.search.search_manager import _cn_stock_code
                            em_code = _cn_stock_code(symbol)
                            if em_code:
                                em_params = {
                                    "reportName": "RPT_DMSK_FN_INCOME",
                                    "columns": "SECURITY_CODE,INDUSTRY_CODE",
                                    "filter": f'(SECURITY_CODE="{em_code}")',
                                    "pageSize": "1", "pageNumber": "1",
                                    "sortColumns": "REPORT_DATE", "sortTypes": "-1",
                                }
                                em_headers = {
                                    "User-Agent": "Mozilla/5.0 FinSight/0.1",
                                    "Accept": "application/json,text/plain,*/*",
                                    "Referer": "https://data.eastmoney.com/",
                                }
                                em_url = f"{_EM_DATACENTER_URL}?{_urlencode(em_params)}"
                                em_req = _req_lib.Request(em_url, headers=em_headers, method="GET")
                                with _req_lib.urlopen(em_req, timeout=15) as em_resp:
                                    em_raw = em_resp.read().decode("utf-8", errors="replace")
                                em_parsed = json.loads(em_raw)
                                em_result = em_parsed.get("result") if isinstance(em_parsed.get("result"), dict) else None
                                em_rows = em_result.get("data") if em_result and isinstance(em_result.get("data"), list) else None
                                if em_rows:
                                    ind_code = str(em_rows[0].get("INDUSTRY_CODE") or "")
                                    if ind_code == "None" or not ind_code:
                                        ind_code = None
                        except Exception as exc:
                            logger.warning("Direct eastmoney industry code fetch failed: %s", exc)
                    if ind_code:
                        em_stocks = _fetch_eastmoney_stocks_by_industry(ind_code, topk=10)
                        if em_stocks:
                            peer_symbols = []
                            for st in em_stocks[:8]:
                                sc = str(st.get("SECURITY_CODE") or "")
                                if not sc:
                                    continue
                                exchange = ".SS" if sc.startswith(("6", "9")) else ".SZ"
                                psym = f"{sc}{exchange}"
                                if psym != symbol:
                                    peer_symbols.append(psym)
                            if peer_symbols:
                                logger.info("Discovered %d A-share peers via eastmoney industry=%s", len(peer_symbols), ind_code)
            # For US/HK markets, use Yahoo sector mappings
            if not peer_symbols and market != "cn_a":
                sector_peer_map = {
                    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "INTC", "CRM", "ADBE", "ORCL"],
                    "Healthcare": ["JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT"],
                    "Financial Services": ["JPM", "BAC", "V", "MA", "GS", "MS", "C", "WFC"],
                    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "NKE", "MCD", "SBUX", "NFLX", "DIS"],
                    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "T"],
                    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
                    "Industrials": ["BA", "CAT", "GE", "RTX", "UPS", "FDX", "HON", "MMM"],
                    "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST"],
                    "Basic Materials": ["BHP", "RIO", "LIN", "SHW", "APD"],
                }
                for sec_name, candidates in sector_peer_map.items():
                    if sec_name.lower() in sector.lower() or sector.lower() in sec_name.lower():
                        peer_symbols = [s for s in candidates if s != symbol][:6]
                        break
        except Exception as exc:
            logger.warning("Sector peer lookup failed for %s: %s", symbol, exc)

    # --- Phase 4: fetch actual financial data for each peer ---
    for ps in peer_symbols[:5]:
        try:
            time.sleep(0.3)  # rate-limit between Yahoo calls
            pt = yf.Ticker(ps)
            pi = pt.info or {}
            annual_fin = pt.financials
            bs = pt.balance_sheet

            rev = None
            ni = None
            fcf_val = None
            try:
                if annual_fin is not None and not annual_fin.empty:
                    rev = _to_billion(float(annual_fin.loc["Total Revenue"].iloc[0])) if "Total Revenue" in annual_fin.index else None
                    ni_val = annual_fin.loc["Net Income"].iloc[0] if "Net Income" in annual_fin.index else None
                    ni_val = ni_val or (annual_fin.loc["Net Income Common Stockholders"].iloc[0] if "Net Income Common Stockholders" in annual_fin.index else None)
                    ni = _to_billion(float(ni_val)) if ni_val is not None else None
            except Exception:
                pass
            try:
                if pt.cashflow is not None and not pt.cashflow.empty:
                    fcf_val_raw = pt.cashflow.loc["Free Cash Flow"].iloc[0] if "Free Cash Flow" in pt.cashflow.index else None
                    fcf_val = _to_billion(float(fcf_val_raw)) if fcf_val_raw is not None else None
            except Exception:
                pass

            rev_growth = pi.get("revenueGrowth")
            gross_margin = pi.get("grossMargins")
            net_margin = pi.get("profitMargins")
            roe_val = pi.get("returnOnEquity")

            peer_rows.append({
                "symbol": ps,
                "company_name": str(pi.get("longName") or pi.get("shortName") or ps),
                "sector": sector,
                "industry": industry,
                "is_target": False,
                "revenue_billion": rev,
                "revenue_growth_pct": _yahoo_ratio_to_pct(rev_growth) if rev_growth is not None else None,
                "gross_margin_pct": _yahoo_ratio_to_pct(gross_margin) if gross_margin is not None else None,
                "net_margin_pct": _yahoo_ratio_to_pct(net_margin) if net_margin is not None else None,
                "roe_pct": _yahoo_ratio_to_pct(roe_val) if roe_val is not None else None,
                "free_cash_flow_billion": fcf_val,
                "net_income_billion": ni,
                "adjusted_net_income_billion": ni,
                "non_recurring_gain_billion": None,
                "non_recurring_gain_ratio": None,
                "net_income_quality_flag": "yahoo_estimated",
                "valuation_input_usable": True,
                "valuation_input_rejection_reason": "",
                "free_cash_flow_period_basis": "annual",
                "data_period": "current_ttm",
                "source_type": "yahoo_finance",
                "source_url": f"https://finance.yahoo.com/quote/{ps}",
            })
        except Exception as exc:
            logger.warning("Failed to fetch Yahoo data for peer %s: %s", ps, exc)
            continue

    # --- Phase 5: build target row from Yahoo ---
    try:
        tt = yf.Ticker(symbol)
        ti = tt.info or {}
        t_rev = _safe_float(ti.get("totalRevenue"))
        t_ni = _safe_float(ti.get("netIncomeToCommon"))
        t_fcf = _safe_float(ti.get("freeCashflow"))
        target_row = {
            "symbol": symbol,
            "company_name": str(ti.get("longName") or ti.get("shortName") or symbol),
            "sector": sector,
            "industry": industry,
            "is_target": True,
            "revenue_billion": _to_billion(t_rev) if t_rev is not None else None,
            "revenue_growth_pct": _yahoo_ratio_to_pct(_safe_float(ti.get("revenueGrowth")) or 0.0),
            "gross_margin_pct": _yahoo_ratio_to_pct(_safe_float(ti.get("grossMargins")) or 0.0),
            "net_margin_pct": _yahoo_ratio_to_pct(_safe_float(ti.get("profitMargins")) or 0.0),
            "roe_pct": _yahoo_ratio_to_pct(_safe_float(ti.get("returnOnEquity")) or 0.0),
            "free_cash_flow_billion": _to_billion(t_fcf) if t_fcf is not None else None,
            "net_income_billion": _to_billion(t_ni) if t_ni is not None else None,
            "adjusted_net_income_billion": _to_billion(t_ni) if t_ni is not None else None,
            "non_recurring_gain_billion": None,
            "non_recurring_gain_ratio": None,
            "net_income_quality_flag": "yahoo_estimated",
            "valuation_input_usable": True,
            "valuation_input_rejection_reason": "",
            "free_cash_flow_period_basis": "annual",
            "data_period": "current_ttm",
            "source_type": "yahoo_finance",
            "source_url": f"https://finance.yahoo.com/quote/{symbol}",
        }
    except Exception as exc:
        logger.warning("Failed to fetch Yahoo target data for %s: %s", symbol, exc)
        target_row = {"symbol": symbol, "is_target": True}

    all_rows = [target_row] + peer_rows if target_row else peer_rows
    ranking = _rank_target(all_rows, symbol=symbol)

    return {
        "target_symbol": symbol,
        "target_sector": sector,
        "target_industry": industry,
        "target_row": target_row,
        "peer_rows": all_rows,
        "peer_count": max(len(peer_rows), 0),
        "ranking": ranking,
        "source": "yahoo_search",
    }


def perform_company_valuation(
    symbol: str,
    period: str,
    records: List[Dict[str, Any]] | None = None,
    raw_data_root: str | Path = "data/raw/real_data",
    allow_external_market_data: bool = False,
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
    if revenue > 0 and free_cash_flow / revenue > 100:
        return {
            "symbol": symbol,
            "period": period,
            "valuation_available": False,
            "error": "valuation_guardrail_failed",
            "guardrail": {
                "passed": False,
                "errors": ["dcf_value_to_revenue_above_guardrail"],
                "warnings": [],
                "limits": {"max_free_cash_flow_to_revenue": 100},
            },
            "peer_context": peer_payload,
            "input_summary": {
                "revenue_billion": revenue,
                "net_income_billion": net_income,
                "free_cash_flow_billion": free_cash_flow,
            },
        }
    market_context = _market_context_from_records(records=records or [], symbol=symbol, period=period)
    market = infer_market_from_symbol(symbol).get("market", "")
    official_records = [
        record for record in records or []
        if is_official_financial_source(str(record.get("source_type") or ""))
    ]
    currency_meta = infer_statement_currency(
        symbol=symbol,
        market=market,
        source=official_records[0] if official_records else None,
    )
    statement_currency = currency_meta.statement_currency
    trading_currency = infer_trading_currency(symbol, market)
    if market != "us" and str(period or "").upper().startswith("FY") and not official_records:
        return _valuation_unavailable(
            symbol=symbol,
            period=period,
            error="unverified_third_party_financials",
            peer_payload=peer_payload,
            input_summary={
                "revenue_billion": revenue,
                "net_income_billion": net_income,
                "free_cash_flow_billion": free_cash_flow,
                "statement_currency": statement_currency,
                "trading_currency": trading_currency,
            },
            missing_inputs=["official_annual_report_or_exchange_filing"],
            valuation_status="degraded_due_to_unverified_financial_currency",
        )
    if statement_currency == UNKNOWN_CURRENCY:
        return _valuation_unavailable(
            symbol=symbol,
            period=period,
            error="unknown_financial_currency",
            peer_payload=peer_payload,
            input_summary={
                "revenue_billion": revenue,
                "net_income_billion": net_income,
                "free_cash_flow_billion": free_cash_flow,
            },
            missing_inputs=["statement_currency"],
            valuation_status="blocked_due_to_currency_mismatch",
        )
    valuation_currency = trading_currency if trading_currency != UNKNOWN_CURRENCY else statement_currency
    fx_note: Dict[str, Any] = {}
    if statement_currency != valuation_currency:
        try:
            revenue_money = convert_money(MoneyValue(revenue, statement_currency, "billion"), valuation_currency, DEFAULT_FX_RATES)
            net_income_money = convert_money(MoneyValue(net_income, statement_currency, "billion"), valuation_currency, DEFAULT_FX_RATES)
            free_cash_flow_money = convert_money(MoneyValue(free_cash_flow, statement_currency, "billion"), valuation_currency, DEFAULT_FX_RATES)
            revenue = revenue_money.amount
            net_income = net_income_money.amount
            free_cash_flow = free_cash_flow_money.amount
            fx_note = {
                "from": statement_currency,
                "to": valuation_currency,
                "rate": revenue_money.fx_rate,
                "fx_date": revenue_money.fx_date,
            }
        except ValueError:
            return _valuation_unavailable(
                symbol=symbol,
                period=period,
                error="missing_fx_rate_for_cross_currency_valuation",
                peer_payload=peer_payload,
                input_summary={
                    "statement_currency": statement_currency,
                    "trading_currency": trading_currency,
                    "valuation_currency": valuation_currency,
                },
                missing_inputs=["fx_rate", "fx_date"],
                valuation_status="missing_fx_rate_for_cross_currency_valuation",
            )
    shares_outstanding = _safe_float(market_context.get("shares_outstanding_billion"))
    revenue_growth = _safe_float(target.get("revenue_growth_pct")) or 0.0
    net_margin = _safe_float(target.get("adjusted_net_margin_pct")) or _safe_float(target.get("net_margin_pct")) or 0.0
    roe = _safe_float(target.get("roe_pct")) or 0.0
    missing_completeness = _valuation_completeness_gaps(
        target=target,
        revenue=revenue,
        net_income=net_income,
        free_cash_flow=free_cash_flow,
        market_context=market_context,
        shares_outstanding=shares_outstanding,
        statement_currency=statement_currency,
        trading_currency=trading_currency,
        valuation_currency=valuation_currency,
        fx_note=fx_note,
    )
    if missing_completeness:
        return _valuation_unavailable(
            symbol=symbol,
            period=period,
            error="valuation_input_invalid",
            peer_payload=peer_payload,
            input_summary={
                "revenue_billion": revenue,
                "net_income_billion": net_income,
                "free_cash_flow_billion": free_cash_flow,
                "revenue_growth_pct": target.get("revenue_growth_pct"),
                "market_cap_billion": market_context.get("market_cap_billion"),
                "shares_outstanding_billion": shares_outstanding,
                "statement_currency": statement_currency,
                "trading_currency": trading_currency,
                "valuation_currency": valuation_currency,
            },
            missing_inputs=missing_completeness,
            valuation_status="rough_observation_only",
        )

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

    # ---- override with real market data when available ----
    _risk_free = _get_fred_risk_free_rate() if allow_external_market_data else None
    _market_multiples = _get_yahoo_market_multiples(symbol) if allow_external_market_data else {}
    _pe_base = _market_multiples.get("pe") or 18
    _ps_base = _market_multiples.get("ps") or 4
    pe_multiple = round(_bounded(_pe_base * growth_premium * margin_premium, 8, 50), 2)
    ps_multiple = round(_bounded(_ps_base * growth_premium * (1 + net_margin / 100), 1.0, 20), 2)
    if _risk_free is not None:
        discount_rate = _risk_free + 0.035  # risk-free rate + equity risk premium
        terminal_growth = min(max(_risk_free * 0.5, 0.020), 0.035)

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
        currency=valuation_currency,
    )
    dcf_model = _build_dcf_model(
        symbol=symbol,
        period=period,
        free_cash_flow=free_cash_flow,
        growth_rate=fcf_growth,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        shares_outstanding_billion=shares_outstanding,
        currency=valuation_currency,
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
        "currency": f"{valuation_currency}_billion",
        "statement_currency": statement_currency,
        "trading_currency": trading_currency,
        "valuation_currency": valuation_currency,
        "fx_conversion": fx_note,
        "official_financial_source_count": len(official_records),
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
            "currency": valuation_currency,
            "unit": "billion",
            "statement_currency": statement_currency,
            "trading_currency": trading_currency,
            "fx_conversion": fx_note,
            "valuation_status": "available",
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
        if str(record.get("source_type", "")).lower() not in {
            "market",
            "market_api",
            "market_data",
            "sina_finance",
            "yahoo_finance",
            "eastmoney",
        }:
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
            "currency": str(snapshot.get("currency") or infer_trading_currency(symbol, infer_market_from_symbol(symbol).get("market", ""))),
            "trading_currency": infer_trading_currency(symbol, infer_market_from_symbol(symbol).get("market", "")),
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
        # Calculate free cash flow from operating cash flow - capex
        operating_cf = _first_fact_value(metrics, ["NetCashProvidedByUsedInOperatingActivities"])
        capex = _first_fact_value(metrics, ["PaymentsToAcquirePropertyPlantAndEquipment"])
        free_cash_flow = (operating_cf - capex) if (operating_cf is not None and capex is not None) else None
        return {
            "revenue_billion": _to_billion(revenue) if revenue is not None else None,
            "net_income_billion": _to_billion(net_income) if net_income is not None else None,
            "adjusted_net_income_billion": _to_billion(net_income) if net_income is not None else None,
            "free_cash_flow_billion": _to_billion(free_cash_flow) if free_cash_flow is not None else None,
            "free_cash_flow_period_basis": "annual",
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
    # 银行/保险等不直接披露 FCF 的行业：用 OCF + capex 计算
    if free_cash_flow is None:
        ocf = _first_number(raw, ["operatingCashflow", "operating_cash_flow_billion"])
        if ocf is None:
            ocf = _first_number(latest_cashflow, ["Operating Cash Flow", "totalCashFromOperatingActivities"])
        capex_raw = _first_number(raw, ["capitalExpenditures", "capex"])
        if capex_raw is None:
            capex_raw = _first_number(latest_cashflow, ["Capital Expenditure"])
        if ocf is not None and capex_raw is not None:
            free_cash_flow = ocf + capex_raw  # capex_raw is negative in yfinance
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
    valuation_status: str = "",
) -> Dict[str, Any]:
    payload = {
        "symbol": symbol,
        "period": period,
        "valuation_available": False,
        "error": error,
        "missing_inputs": missing_inputs,
        "peer_context": peer_payload,
        "input_summary": input_summary,
        "valuation_input_usable": False,
        "valuation_input_rejection_reason": error,
        "valuation_status": valuation_status or error,
    }
    bridge = _earnings_bridge_sensitivity(input_summary)
    if bridge:
        payload["valuation_sensitivity"] = bridge
    return payload


def _earnings_bridge_sensitivity(input_summary: Dict[str, Any]) -> Dict[str, Any]:
    revenue = _safe_float(input_summary.get("revenue_billion"))
    net_income = _safe_float(input_summary.get("net_income_billion"))
    if revenue is None or net_income is None or revenue <= 0 or net_income <= 0:
        return {}
    margin = net_income / revenue
    scenarios: Dict[str, Dict[str, Any]] = {}
    for name, revenue_change_pct in (("bear", -1.0), ("base", 0.0), ("bull", 1.0)):
        scenario_revenue = revenue * (1 + revenue_change_pct / 100)
        scenario_income = scenario_revenue * margin
        scenarios[name] = {
            "revenue_change_pct": revenue_change_pct,
            "revenue_billion": round(scenario_revenue, 2),
            "net_income_billion": round(scenario_income, 2),
            "value": round(scenario_income, 2),
        }
    return {
        "method": "earnings_bridge",
        "metric": "net_income_billion",
        "unit": "billion",
        "scenario_values": scenarios,
        "directional_check": (
            scenarios["bull"]["net_income_billion"]
            >= scenarios["base"]["net_income_billion"]
            >= scenarios["bear"]["net_income_billion"]
        ),
        "limitations": [
            "This is an earnings bridge, not a DCF target-price model.",
            "Net margin is held constant across scenarios.",
        ],
    }


def _valuation_completeness_gaps(
    target: Dict[str, Any],
    revenue: float,
    net_income: float,
    free_cash_flow: float,
    market_context: Dict[str, Any],
    shares_outstanding: float | None,
    statement_currency: str,
    trading_currency: str,
    valuation_currency: str,
    fx_note: Dict[str, Any],
) -> List[str]:
    missing: List[str] = []
    if revenue <= 0:
        missing.append("positive_revenue")
    if net_income <= 0:
        missing.append("positive_net_income")
    if free_cash_flow <= 0:
        missing.append("positive_free_cash_flow")
    if target.get("revenue_growth_pct") in (None, ""):
        missing.append("revenue_growth_pct")
    if _safe_float(market_context.get("market_cap_billion")) is None:
        missing.append("market_cap_billion")
    if shares_outstanding is None or shares_outstanding <= 0:
        missing.append("shares_outstanding_billion")
    if not statement_currency or statement_currency == UNKNOWN_CURRENCY:
        missing.append("statement_currency")
    if not trading_currency or trading_currency == UNKNOWN_CURRENCY:
        missing.append("trading_currency")
    if statement_currency and valuation_currency and statement_currency != valuation_currency and not fx_note.get("rate"):
        missing.append("fx_rate")
    return missing


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


def _yahoo_ratio_to_pct(value: float) -> float:
    """Yahoo ratio fields are decimal ratios even when ROE exceeds 100%."""

    return float(value) * 100.0


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
    currency: str = "USD",
) -> Dict[str, Any]:
    pe_value = net_income * pe_multiple
    ps_value = revenue * ps_multiple
    return {
        "symbol": symbol,
        "period": period,
        "currency": currency,
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
    currency: str = "USD",
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
        "currency": currency,
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


# ---------------------------------------------------------------------------
# Market-data helpers for FRED risk-free rate and Yahoo Finance multiples
# ---------------------------------------------------------------------------

def _get_fred_risk_free_rate() -> float | None:
    """Fetch the 10Y Treasury yield from FRED (DGS10) and return as decimal.

    Returns e.g. 0.043 for 4.3%, or None on any failure.
    """
    try:
        from src.data.independent_sources import fetch_fred_series_evidence

        result = fetch_fred_series_evidence({"DGS10": "10-Year Treasury"})
        if not result or not hasattr(result, "hits"):
            return None
        for hit in result.hits:
            meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            raw_value = meta.get("value")
            if raw_value is not None and str(raw_value).strip() not in ("", "."):
                val = float(str(raw_value).strip())
                if val > 1:
                    return val / 100.0
                return val
        return None
    except Exception as exc:
        logger.debug("FRED risk-free rate fetch failed: %s", exc)
        return None


def _get_yahoo_market_multiples(symbol: str) -> Dict[str, float | None]:
    """Get trailing market multiples for *symbol* via Yahoo Finance.

    Returns dict with keys ``pe``, ``ps``, ``pb`` — each may be None.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        return {
            "pe": _safe_float(info.get("trailingPE")),
            "ps": _safe_float(info.get("priceToSalesTrailing12Months")),
            "pb": _safe_float(info.get("priceToBook")),
        }
    except Exception as exc:
        logger.debug("Yahoo multiples fetch failed for %s: %s", symbol, exc)
        return {"pe": None, "ps": None, "pb": None}


# ── 东财行业同行发现 ──────────────────────────────────

_EM_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _get_industry_code_from_records(records: List[Dict[str, Any]], symbol: str) -> str | None:
    """从已有 evidence records 中提取东财行业代码 (INDUSTRY_CODE)。"""
    for rec in records or []:
        if str(rec.get("symbol", "")).upper() != symbol.upper():
            continue
        if str(rec.get("source_type", "")).lower() != "eastmoney_financials":
            continue
        meta = rec.get("metadata", {})
        if isinstance(meta, dict):
            raw = meta.get("raw", {})
            if isinstance(raw, dict):
                code = raw.get("INDUSTRY_CODE")
                if code is not None:
                    return str(code).strip()
    return None


def _fetch_eastmoney_stocks_by_industry(industry_code: str, topk: int = 10) -> List[Dict[str, Any]]:
    """通过东财财报 API 查询同行业全部股票代码。

    使用 RPT_DMSK_FN_INCOME 按 INDUSTRY_CODE 过滤返回收入数据，
    从中提取唯一 SECURITY_CODE 作为同行列表。
    """
    params = {
        "reportName": "RPT_DMSK_FN_INCOME",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,INDUSTRY_CODE,REPORT_DATE,TOTAL_OPERATE_INCOME",
        "filter": f'(INDUSTRY_CODE="{industry_code}")',
        "pageSize": str(max(topk, 50)),
        "pageNumber": "1",
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 FinSight/0.1",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://data.eastmoney.com/",
    }
    url = f"{_EM_DATACENTER_URL}?{_urlencode(params)}"
    try:
        req = _req_lib.Request(url, headers=headers, method="GET")
        with _req_lib.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("eastmoney industry stock list failed for code %s: %s", industry_code, exc)
        return []
    # Collect unique stock codes from income rows
    rows = _coerce_search_items(parsed, ["data", "result", "items", "records"])
    if not rows:
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else None
        if result and isinstance(result.get("data"), list):
            rows = result["data"]
    seen = set()
    unique: List[Dict[str, Any]] = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        sc = r.get("SECURITY_CODE")
        if sc and str(sc) not in seen:
            seen.add(str(sc))
            unique.append(r)
    return unique[:max(topk, 50)]


def _fetch_eastmoney_peer_financials(code: str, period: str) -> Dict[str, Any] | None:
    """用东财 API 获取一只同行股票的财务数据，拼成 peer_row 格式。"""
    from src.search.search_manager import _cn_stock_code

    stock_code = _cn_stock_code(code)
    if not stock_code:
        return None
    params = {
        "reportName": "RPT_DMSK_FN_INCOME",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{stock_code}")',
        "pageSize": "5",
        "pageNumber": "1",
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 FinSight/0.1",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://data.eastmoney.com/",
    }
    url = f"{_EM_DATACENTER_URL}?{_urlencode(params)}"
    try:
        req = _req_lib.Request(url, headers=headers, method="GET")
        with _req_lib.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
    except Exception as exc:
        logger.debug("eastmoney peer financials fetch failed for %s: %s", code, exc)
        return None
    rows = _coerce_search_items(parsed, ["data", "result", "items", "records"])
    if not rows:
        return None
    # Find the row that best matches the target period
    row = _select_financial_row_for_period(rows, period) if rows else rows[0]
    if not row:
        row = rows[0]
    exchange_suffix = ".SS" if str(stock_code).startswith(("6", "9")) else ".SZ"
    symbol = f"{stock_code}{exchange_suffix}"
    rev = _safe_float(row.get("TOTAL_OPERATE_INCOME"))
    ni = _safe_float(row.get("PARENT_NETPROFIT"))
    op_cf = _safe_float(row.get("NETCASH_OPERATE"))
    op_cost = _safe_float(row.get("OPERATE_COST"))
    gross_margin = ((rev - op_cost) / rev * 100) if rev and op_cost else None
    return {
        "symbol": symbol,
        "company_name": str(row.get("SECURITY_NAME_ABBR") or symbol),
        "sector": "",
        "industry": str(row.get("INDUSTRY_NAME") or ""),
        "is_target": False,
        "revenue_billion": _to_billion(rev) if rev else None,
        "revenue_growth_pct": None,
        "gross_margin_pct": gross_margin,
        "net_margin_pct": (ni / rev * 100) if rev and ni else None,
        "roe_pct": None,
        "free_cash_flow_billion": None,
        "net_income_billion": _to_billion(ni) if ni else None,
        "adjusted_net_income_billion": _to_billion(ni) if ni else None,
        "non_recurring_gain_billion": None,
        "non_recurring_gain_ratio": None,
        "net_income_quality_flag": "eastmoney",
        "valuation_input_usable": True,
        "valuation_input_rejection_reason": "",
        "free_cash_flow_period_basis": "annual",
    }


def _select_financial_row_for_period(rows: List[Dict[str, Any]], period: str) -> Dict[str, Any] | None:
    """从东财返回的多期财务行中，选出最匹配目标 period 的那一行。"""
    period = (period or "").upper().strip()
    if not period or not period.startswith("FY"):
        return rows[0] if rows else None
    try:
        target_year = int(period.replace("FY", ""))
    except ValueError:
        return rows[0] if rows else None
    for row in rows:
        rd = str(row.get("REPORT_DATE") or "")
        if rd.startswith(str(target_year)):
            return row
    return rows[0] if rows else None


def _get_industry_code_via_eastmoney_api(symbol: str) -> str | None:
    """调用东财财报 API 获取目标股票的行业代码 (INDUSTRY_CODE)。"""
    from src.search.search_manager import _cn_stock_code

    code = _cn_stock_code(symbol)
    if not code:
        return None
    params = {
        "reportName": "RPT_DMSK_FN_INCOME",
        "columns": "SECURITY_CODE,INDUSTRY_CODE,INDUSTRY_NAME,REPORT_DATE",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageSize": "1",
        "pageNumber": "1",
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 FinSight/0.1",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://data.eastmoney.com/",
    }
    url = f"{_EM_DATACENTER_URL}?{_urlencode(params)}"
    try:
        req = _req_lib.Request(url, headers=headers, method="GET")
        with _req_lib.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
    except Exception as exc:
        logger.debug("eastmoney industry code fetch failed for %s: %s", symbol, exc)
        return None
    # Try both _coerce_search_items and direct path
    rows = _coerce_search_items(parsed, ["data", "result", "items", "records"])
    if not rows:
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else None
        if result and isinstance(result.get("data"), list):
            rows = result["data"]
    if not rows:
        return None
    row = rows[0]
    ind_code = row.get("INDUSTRY_CODE")
    return str(ind_code).strip() if ind_code is not None else None


def _coerce_search_items(payload: Dict[str, Any], keys: List[str]) -> List[Dict[str, Any]]:
    """从 API 返回的嵌套 dict 中提取列表数据（兼容不同格式）。"""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _coerce_search_items(value, ["data", "items", "results", "records", "list"])
            if nested:
                return nested
    return []
