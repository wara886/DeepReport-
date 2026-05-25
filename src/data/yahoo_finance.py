"""Small Yahoo Finance market-data adapter.

Yahoo's chart endpoint is keyless and useful for a first real-market-data
tool. It should be treated as a best-effort public data source, not as an
audited filings source.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import re
from logging import getLogger
from typing import Any, Dict
from urllib import error, parse, request

import pandas as pd

from src.data.financial_quality import build_net_income_quality_fields
from src.utils.periods import latest_completed_period

logger = getLogger(__name__)


YAHOO_CHART_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_QUOTESUMMARY_BASE_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary"


def fetch_yahoo_chart_snapshot(
    symbol: str,
    range_: str = "1mo",
    interval: str = "1d",
    timeout: int = 12,
) -> Dict[str, Any]:
    """Fetch a compact market snapshot from Yahoo Finance's chart endpoint."""

    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    query = parse.urlencode({"range": range_, "interval": interval})
    url = f"{YAHOO_CHART_BASE_URL}/{parse.quote(symbol)}?{query}"
    req = request.Request(
        url,
        headers={
            "User-Agent": "FinSight/0.1",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Yahoo Finance HTTP {exc.code}: {body[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Yahoo Finance URL error: {exc.reason}") from exc

    parsed = json.loads(raw)
    result = parsed.get("chart", {}).get("result", [])
    if not result:
        chart_error = parsed.get("chart", {}).get("error")
        raise RuntimeError(f"Yahoo Finance returned no chart result: {chart_error}")

    item = result[0]
    meta = item.get("meta", {}) if isinstance(item, dict) else {}
    timestamps = item.get("timestamp", []) if isinstance(item, dict) else []
    quote = {}
    indicators = item.get("indicators", {}) if isinstance(item, dict) else {}
    quotes = indicators.get("quote", []) if isinstance(indicators, dict) else []
    if quotes and isinstance(quotes[0], dict):
        quote = quotes[0]

    closes = [_safe_float(value) for value in quote.get("close", [])]
    closes = [value for value in closes if value is not None]
    volumes = [_safe_float(value) for value in quote.get("volume", [])]
    volumes = [value for value in volumes if value is not None]

    first_close = closes[0] if closes else _safe_float(meta.get("chartPreviousClose"))
    last_close = closes[-1] if closes else _safe_float(meta.get("regularMarketPrice") or meta.get("currentTradingPeriod", {}).get("regular", {}).get("price"))
    previous_close = _safe_float(meta.get("previousClose") or meta.get("chartPreviousClose"))
    change_pct = None
    if first_close not in (None, 0) and last_close is not None:
        change_pct = ((last_close - first_close) / first_close) * 100

    latest_timestamp = timestamps[-1] if timestamps else None
    latest_date = _date_from_timestamp(latest_timestamp)
    return {
        "symbol": symbol,
        "range": range_,
        "interval": interval,
        "currency": str(meta.get("currency", "")),
        "exchange_name": str(meta.get("exchangeName", "")),
        "instrument_type": str(meta.get("instrumentType", "")),
        "first_close": first_close,
        "last_close": last_close,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "latest_volume": volumes[-1] if volumes else None,
        "latest_date": latest_date,
        "source_url": f"https://finance.yahoo.com/quote/{parse.quote(symbol)}",
        "raw_meta": meta,
    }


def yahoo_snapshot_to_evidence(
    symbol: str,
    period: str = "",
    range_: str = "1mo",
    interval: str = "1d",
    timeout: int = 12,
) -> Dict[str, Any]:
    snapshot = fetch_yahoo_chart_snapshot(symbol=symbol, range_=range_, interval=interval, timeout=timeout)
    change_text = "unknown"
    if snapshot.get("change_pct") is not None:
        change_text = f"{float(snapshot['change_pct']):.2f}%"
    target_period = str(period or "").strip().upper()
    current_context_note = ""
    if target_period and target_period != latest_completed_period():
        current_context_note = (
            " This is a current market snapshot used for valuation context, "
            f"not target-period statement evidence for {target_period}."
        )
    content = (
        f"{snapshot['symbol']} Yahoo Finance market snapshot: latest close {snapshot.get('last_close')} "
        f"{snapshot.get('currency')}, previous close {snapshot.get('previous_close')}, "
        f"{range_} price change {change_text}, latest volume {snapshot.get('latest_volume')}."
        f"{current_context_note}"
    )
    digest = hashlib.sha1(f"{symbol}|{period}|{snapshot.get('latest_date')}|{content}".encode("utf-8")).hexdigest()[:10]
    return {
        "evidence_id": f"{snapshot['symbol']}_{period or range_}_yahoo_finance_{digest}",
        "sample_id": f"{snapshot['symbol']}_{period or range_}_yahoo_finance_{digest}",
        "symbol": snapshot["symbol"],
        "period": period,
        "source_type": "market_api",
        "title": f"{snapshot['symbol']} Yahoo Finance market snapshot",
        "content": content,
        "source_url": snapshot["source_url"],
        "publish_time": str(snapshot.get("latest_date") or ""),
        "trust_level": "medium",
        "score": 6.0,
        "metadata": {
            "provider": "yahoo_finance",
            "snapshot": snapshot,
            "context_type": "current_market_snapshot",
            "target_period": target_period,
            "as_of_date": str(snapshot.get("latest_date") or ""),
            "historical_report_context": bool(current_context_note),
        },
    }


def fetch_yahoo_financials(
    symbol: str,
    timeout: int = 12,
) -> Dict[str, Any]:
    """Fetch key financial data from Yahoo Finance.

    Uses yfinance (crumb-based auth) as primary backend for cross-market
    support (US, HK, A-shares), with urllib quoteSummary as fallback.

    Returns a dict with financialData, income_history, balance_history, and/or
    cashflow_history. Returns empty dict on any failure — never raises.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {}

    # ── Primary: yfinance (handles crumb/auth for all markets) ────────
    yf_data = _fetch_via_yfinance(symbol, timeout)
    if yf_data:
        return yf_data

    # ── Fallback: direct quoteSummary (works for US stocks without crumb) ──
    return _fetch_via_urllib(symbol, timeout)


def _fetch_via_yfinance(symbol: str, timeout: int = 12) -> Dict[str, Any]:
    """Fetch financials via yfinance library."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        logger.warning("yfinance not installed, skipping financials fetch for %s", symbol)
        return {}

    try:
        ticker = yf.Ticker(symbol)
    except Exception as exc:
        logger.warning("yfinance Ticker(%s) failed: %s", symbol, exc)
        return {}
    financial_data: Dict[str, Any] = {}

    # ── info (key financial metrics) ──
    try:
        info = ticker.info or {}
        for key in (
            "currentPrice", "totalRevenue", "operatingCashflow", "freeCashflow",
            "grossMargins", "profitMargins", "returnOnEquity", "returnOnAssets",
            "revenueGrowth", "earningsGrowth", "debtToEquity",
            "marketCap", "trailingPE", "forwardPE", "priceToBook",
        ):
            value = info.get(key)
            if value is not None:
                financial_data[key] = value
    except Exception as exc:
        logger.warning("yfinance Ticker(%s).info failed: %s", symbol, exc)

    # ── income statement ──
    try:
        fin = ticker.financials
        if fin is not None and not fin.empty:
            financial_data["income_history"] = _yfinance_df_to_rows(fin, max_rows=2)
    except Exception as exc:
        logger.warning("yfinance Ticker(%s).financials failed: %s", symbol, exc)

    # ── balance sheet ──
    try:
        bs = ticker.balance_sheet
        if bs is not None and not bs.empty:
            financial_data["balance_history"] = _yfinance_df_to_rows(bs, max_rows=2)
    except Exception as exc:
        logger.warning("yfinance Ticker(%s).balance_sheet failed: %s", symbol, exc)

    # ── cash flow statement ──
    try:
        cf = ticker.cashflow
        if cf is not None and not cf.empty:
            financial_data["cashflow_history"] = _yfinance_df_to_rows(cf, max_rows=2)
    except Exception as exc:
        logger.warning("yfinance Ticker(%s).cashflow failed: %s", symbol, exc)

    # ── quarterly financials (more recent data) ──
    try:
        q_fin = ticker.quarterly_financials
        if q_fin is not None and not q_fin.empty:
            financial_data["quarterly_income_history"] = _yfinance_df_to_rows(q_fin, max_rows=2)
    except Exception as exc:
        logger.warning("yfinance Ticker(%s).quarterly_financials failed: %s", symbol, exc)

    try:
        q_bs = ticker.quarterly_balance_sheet
        if q_bs is not None and not q_bs.empty:
            financial_data["quarterly_balance_history"] = _yfinance_df_to_rows(q_bs, max_rows=2)
    except Exception as exc:
        logger.warning("yfinance Ticker(%s).quarterly_balance_sheet failed: %s", symbol, exc)

    try:
        q_cf = ticker.quarterly_cashflow
        if q_cf is not None and not q_cf.empty:
            financial_data["quarterly_cashflow_history"] = _yfinance_df_to_rows(q_cf, max_rows=2)
    except Exception as exc:
        logger.warning("yfinance Ticker(%s).quarterly_cashflow failed: %s", symbol, exc)

    return financial_data


def _yfinance_df_to_rows(df: Any, max_rows: int = 2) -> list[Dict[str, Any]]:
    """Convert a yfinance financials DataFrame to a list of row dicts."""
    rows: list[Dict[str, Any]] = []
    for col_idx in range(min(len(df.columns), max_rows)):
        date_key = str(df.columns[col_idx].date() if hasattr(df.columns[col_idx], "date") else df.columns[col_idx])
        row: Dict[str, Any] = {"end_date": date_key}
        for metric in df.index:
            try:
                val = df.iloc[df.index.get_loc(metric), col_idx]
                if pd.notna(val):
                    row[str(metric)] = float(val) if isinstance(val, (int, float)) else str(val)
            except Exception:
                pass
        rows.append(row)
    return rows


def _fetch_via_urllib(symbol: str, timeout: int = 12) -> Dict[str, Any]:
    """Fallback: fetch financials via direct quoteSummary endpoint."""
    modules = "financialData,incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory"
    query = parse.urlencode({"modules": modules})
    url = f"{YAHOO_QUOTESUMMARY_BASE_URL}/{parse.quote(symbol)}?{query}"
    req = request.Request(
        url,
        headers={
            "User-Agent": "FinSight/0.1",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except Exception:
        return {}

    try:
        parsed = json.loads(raw)
        result = parsed.get("quoteSummary", {}).get("result", [])
        if not result:
            return {}
        data = result[0]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        return {}

    financial_data: Dict[str, Any] = {}

    fin_data = data.get("financialData", {}) if isinstance(data.get("financialData"), dict) else {}
    if fin_data:
        for key in (
            "currentPrice", "totalRevenue", "operatingCashflow", "freeCashflow",
            "grossMargins", "profitMargins", "returnOnEquity", "returnOnAssets",
            "revenueGrowth", "earningsGrowth", "debtToEquity",
        ):
            value = _safe_extract(fin_data, key)
            if value is not None:
                financial_data[key] = value

    income = data.get("incomeStatementHistory", {}) if isinstance(data.get("incomeStatementHistory"), dict) else {}
    income_list = income.get("incomeStatementHistory", [])
    if income_list:
        financial_data["income_history"] = [_extract_financial_row(row) for row in income_list[:2]]

    balance = data.get("balanceSheetHistory", {}) if isinstance(data.get("balanceSheetHistory"), dict) else {}
    balance_list = balance.get("balanceSheetHistory", [])
    if balance_list:
        financial_data["balance_history"] = [_extract_financial_row(row) for row in balance_list[:2]]

    cashflow = data.get("cashflowStatementHistory", {}) if isinstance(data.get("cashflowStatementHistory"), dict) else {}
    cashflow_list = cashflow.get("cashflowStatementHistory", [])
    if cashflow_list:
        financial_data["cashflow_history"] = [_extract_financial_row(row) for row in cashflow_list[:2]]

    return financial_data


def yahoo_financials_to_evidence(
    symbol: str,
    period: str = "",
) -> Dict[str, Any] | None:
    """Generate an evidence record from Yahoo Finance financial data.

    Returns None if the financial data endpoint is unavailable (no API key
    required, but Yahoo may require cookie/crumb for the quoteSummary endpoint).
    """
    financials = fetch_yahoo_financials(symbol=symbol)
    if not financials:
        return None

    content_parts: list[str] = [f"{symbol} Yahoo Finance financial data:"]

    metrics: list[str] = []
    for key in ("totalRevenue", "operatingCashflow", "freeCashflow", "grossMargins", "profitMargins",
                 "currentPrice", "marketCap", "trailingPE", "revenueGrowth"):
        value = financials.get(key)
        if value is not None:
            metrics.append(f"{key}={value}")
    if metrics:
        content_parts.append(" | ".join(metrics))

    income = _yf_statement_rows_for_period(financials, "income", period)
    if income:
        latest = income[0]
        rev = _yf_find_key(latest, ("Total Revenue", "totalRevenue", "Reconciled Cost of Revenue")) or "N/A"
        ni = _yf_find_key(latest, ("Net Income", "netIncome")) or "N/A"
        gp = _yf_find_key(latest, ("Gross Profit", "grossProfit")) or "N/A"
        quality = build_net_income_quality_fields(
            financials,
            latest,
            net_income=_yf_number(ni),
            revenue=_yf_number(rev),
        )
        end_date = latest.get("end_date") or latest.get("report_date") or ""
        label = f"{period} income" if str(period or "").strip() else "Latest income"
        content_parts.append(
            f"{label}: end_date={end_date}, revenue={rev}, netIncome={ni}, "
            f"adjustedNetIncome={quality.get('adjusted_net_income') or 'N/A'}, "
            f"nonRecurringGain={quality.get('non_recurring_gain') or 'N/A'}, "
            f"netIncomeQuality={quality.get('net_income_quality_flag')}, grossProfit={gp}"
        )

    balance = _yf_statement_rows_for_period(financials, "balance", period)
    if balance:
        latest = balance[0]
        ta = _yf_find_key(latest, ("Total Assets", "totalAssets")) or "N/A"
        tl = _yf_find_key(latest, ("Total Liabilities Net Minority Interest", "totalLiabilities", "Total Liabilities")) or "N/A"
        te = _yf_find_key(latest, ("Total Equity Gross Minority Interest", "totalStockholderEquity", "Stockholders Equity")) or "N/A"
        end_date = latest.get("end_date") or latest.get("report_date") or ""
        content_parts.append(f"Balance: end_date={end_date}, assets={ta}, liabilities={tl}, equity={te}")

    cashflow = _yf_statement_rows_for_period(financials, "cashflow", period)
    if cashflow:
        latest = cashflow[0]
        ocf = _yf_find_key(latest, ("Operating Cash Flow", "totalCashFromOperatingActivities", "Cash From Operating Activities")) or "N/A"
        capex = _yf_find_key(latest, ("Capital Expenditure", "capitalExpenditures")) or "N/A"
        fcf = _yf_find_key(latest, ("Free Cash Flow", "freeCashFlow")) or "N/A"
        end_date = latest.get("end_date") or latest.get("report_date") or ""
        content_parts.append(f"Cash flow: end_date={end_date}, operating={ocf}, capex={capex}, freeCashFlow={fcf}")

    content = " | ".join(content_parts)
    digest = hashlib.sha1(f"{symbol}|{period}|financials|{content}".encode("utf-8")).hexdigest()[:10]

    return {
        "evidence_id": f"{symbol}_{period}_yahoo_financials_{digest}",
        "sample_id": f"{symbol}_{period}_yahoo_financials_{digest}",
        "symbol": symbol,
        "period": period,
        "source_type": "market_api",
        "title": f"{symbol} Yahoo Finance financial data",
        "content": content,
        "source_url": f"https://finance.yahoo.com/quote/{parse.quote(symbol)}/key-statistics",
        "publish_time": "",
        "trust_level": "medium",
        "score": 6.5,
        "metadata": {"provider": "yahoo_finance", "financials": financials},
    }


def _yf_find_key(row: Dict[str, Any], candidates: tuple[str, ...]) -> Any:
    """Return the first matching value from a row dict using candidate keys."""
    for key in candidates:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _yf_number(value: Any) -> float | None:
    try:
        if value in (None, "N/A"):
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _yf_statement_rows_for_period(financials: Dict[str, Any], statement: str, period: str) -> list[Dict[str, Any]]:
    quarterly = {
        "income": "quarterly_income_history",
        "balance": "quarterly_balance_history",
        "cashflow": "quarterly_cashflow_history",
    }
    annual = {
        "income": "income_history",
        "balance": "balance_history",
        "cashflow": "cashflow_history",
    }
    prefer_quarter = bool(_yf_parse_quarter(period))
    keys = [quarterly[statement]] if prefer_quarter else [annual[statement], quarterly[statement]]
    for key in keys:
        rows = financials.get(key)
        if not isinstance(rows, list):
            continue
        clean_rows = [row for row in rows if isinstance(row, dict)]
        if not clean_rows:
            continue
        if prefer_quarter:
            matched = _yf_row_for_period(clean_rows, period)
            if matched:
                return [matched]
            continue
        return clean_rows
    return []


def _yf_row_for_period(rows: list[Dict[str, Any]], period: str) -> Dict[str, Any]:
    target = _yf_period_target_date(period)
    if not target:
        return {}
    for row in rows:
        row_date = _yf_parse_date(row.get("end_date") or row.get("report_date") or row.get("date") or row.get("asOfDate"))
        if row_date and abs((row_date - target).days) <= 45:
            return row
    return {}


def _yf_parse_quarter(value: str | None) -> tuple[int, int] | None:
    match = re.search(r"(20\d{2})\s*Q([1-4])", str(value or ""), flags=re.I)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _yf_period_target_date(period: str | None) -> date | None:
    parsed = _yf_parse_quarter(period)
    if not parsed:
        return None
    year, quarter = parsed
    month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[quarter]
    return date(year, month_day[0], month_day[1])


def _yf_parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _safe_extract(container: Dict[str, Any], key: str) -> Any:
    item = container.get(key, {})
    if isinstance(item, dict):
        return item.get("raw", item.get("fmt"))
    return None


def _extract_financial_row(row: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict) and "raw" in value:
            result[key] = value["raw"]
        elif isinstance(value, dict) and "fmt" in value:
            result[key] = value["fmt"]
        else:
            result[key] = value
    return result


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _date_from_timestamp(value: Any) -> str:
    try:
        if value is None:
            return ""
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""
