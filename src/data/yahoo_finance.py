"""Small Yahoo Finance market-data adapter.

Yahoo's chart endpoint is keyless and useful for a first real-market-data
tool. It should be treated as a best-effort public data source, not as an
audited filings source.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict
from urllib import error, parse, request
from zoneinfo import ZoneInfo


YAHOO_CHART_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


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
            "User-Agent": "OpenDeepReportPlus/0.1",
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
    # previousClose = prior trading day close; chartPreviousClose = range start price (not prior day)
    previous_close = _safe_float(meta.get("previousClose"))
    range_start_price = _safe_float(meta.get("chartPreviousClose"))
    change_pct = None
    if first_close not in (None, 0) and last_close is not None:
        change_pct = ((last_close - first_close) / first_close) * 100

    latest_timestamp = timestamps[-1] if timestamps else None
    first_timestamp = timestamps[0] if timestamps else None
    latest_date = _date_from_timestamp(latest_timestamp)
    latest_time_utc = _iso_from_timestamp(latest_timestamp, timezone.utc)
    latest_time_et = _iso_from_timestamp(latest_timestamp, ZoneInfo("America/New_York"))
    range_start_date = _date_from_timestamp(first_timestamp)
    # Extract market cap and shares if available in meta
    market_cap_raw = _safe_float(meta.get("marketCap"))
    market_cap_billion = round(market_cap_raw / 1_000_000_000, 4) if market_cap_raw and market_cap_raw > 1_000_000 else market_cap_raw
    shares_raw = _safe_float(meta.get("sharesOutstanding"))
    shares_billion = round(shares_raw / 1_000_000_000, 6) if shares_raw and shares_raw > 1_000_000 else shares_raw
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
        "range_start_price": range_start_price,
        "range_start_date": range_start_date,
        "change_pct": change_pct,
        "latest_volume": volumes[-1] if volumes else None,
        "latest_date": latest_date,
        "snapshot_time_utc": latest_time_utc,
        "snapshot_time_et": latest_time_et,
        "market_cap_billion": market_cap_billion,
        "shares_outstanding_billion": shares_billion,
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
    prior_day_part = (
        f", prior day close {snapshot['previous_close']}"
        if snapshot.get("previous_close") is not None
        else ""
    )
    cap_part = ""
    if snapshot.get("market_cap_billion") is not None:
        cap_part += f"market cap {snapshot.get('market_cap_billion')}B, "
    if snapshot.get("shares_outstanding_billion") is not None:
        cap_part += f"shares outstanding {snapshot.get('shares_outstanding_billion')}B, "
    content = (
        f"{snapshot['symbol']} Yahoo Finance market snapshot: latest close {snapshot.get('last_close')} "
        f"{snapshot.get('currency')}{prior_day_part}, "
        f"{range_} price change {change_text} (from {snapshot.get('range_start_date')} to {snapshot.get('latest_date')}), "
        f"latest volume {snapshot.get('latest_volume')}, "
        f"{cap_part}"
        f"snapshot time {snapshot.get('snapshot_time_et') or snapshot.get('latest_date')} ET."
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
        "publish_time": str(snapshot.get("snapshot_time_utc") or snapshot.get("latest_date") or ""),
        "trust_level": "medium",
        "score": 6.0,
        "metadata": {"provider": "yahoo_finance", "snapshot": snapshot},
    }


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


def _iso_from_timestamp(value: Any, tz: timezone | ZoneInfo) -> str:
    try:
        if value is None:
            return ""
        return datetime.fromtimestamp(float(value), tz=tz).strftime("%Y-%m-%d %H:%M %Z")
    except (TypeError, ValueError, OSError):
        return ""
