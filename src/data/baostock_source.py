"""Keyless BaoStock financial indicator adapter for China A-shares."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from src.data.source_quality import apply_source_quality


QUERY_TYPES = {
    "profit": "query_profit_data",
    "operation": "query_operation_data",
    "growth": "query_growth_data",
    "balance": "query_balance_data",
    "cashflow": "query_cash_flow_data",
    "dupont": "query_dupont_data",
}


def fetch_baostock_financials(
    *, symbol: str, period: str, topk: int = 6, client: Any = None
) -> dict[str, Any]:
    code = _baostock_code(symbol)
    year = _period_year(period)
    if not code or not year:
        return {"hits": [], "meta": {"mode": "baostock_financials", "failure_reason": "unsupported_symbol_or_period"}}
    try:
        if client is None:
            import baostock as client  # type: ignore
    except Exception as exc:
        return {"hits": [], "meta": {"mode": "baostock_financials", "failure_reason": "dependency_missing", "error": str(exc)}}

    login = client.login()
    if str(getattr(login, "error_code", "0")) != "0":
        return {"hits": [], "meta": {"mode": "baostock_financials", "failure_reason": "login_failed", "error": str(getattr(login, "error_msg", ""))}}
    hits: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    try:
        for table_type, method_name in QUERY_TYPES.items():
            result = getattr(client, method_name)(code=code, year=int(year), quarter=4)
            if str(getattr(result, "error_code", "0")) != "0":
                errors[table_type] = str(getattr(result, "error_msg", "query_failed"))
                continue
            rows = _rows(result)
            if not rows:
                continue
            row = rows[-1]
            digest = hashlib.sha1(f"{code}|{period}|{table_type}|{json.dumps(row, sort_keys=True)}".encode()).hexdigest()[:10]
            evidence_id = f"{code.replace('.', '')}_{period}_baostock_{table_type}_{digest}"
            record = {
                "evidence_id": evidence_id,
                "sample_id": evidence_id,
                "symbol": str(symbol).upper(),
                "period": str(period),
                "source_type": "baostock_financials",
                "title": f"{symbol} BaoStock {table_type} indicators",
                "source_url": "http://www.baostock.com/",
                "publish_time": str(row.get("pubDate") or row.get("statDate") or ""),
                "content": _content(table_type, row),
                "trust_level": "medium",
                "source_authority": "secondary",
                "authority_level": "secondary",
                "authority_score": 0.72,
                "metadata": {"provider": "BaoStock", "table_type": table_type, "raw": row},
            }
            hits.append(apply_source_quality(record))
    except Exception as exc:
        errors["runtime"] = str(exc)
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return {
        "hits": hits[:topk],
        "meta": {
            "mode": "baostock_financials",
            "symbol": str(symbol).upper(),
            "record_count": len(hits),
            "table_types": [item["metadata"]["table_type"] for item in hits],
            "errors": errors,
            "failure_reason": "" if hits else "no_period_matched_rows",
        },
    }


def _rows(result: Any) -> list[dict[str, Any]]:
    fields = [str(item) for item in getattr(result, "fields", [])]
    output = []
    while result.next():
        values = list(result.get_row_data())
        output.append(dict(zip(fields, values)))
    return output


def _content(table_type: str, row: dict[str, Any]) -> str:
    values = [f"{key}={value}" for key, value in row.items() if value not in (None, "")]
    return f"BaoStock {table_type} indicators: " + " | ".join(values)


def _baostock_code(symbol: str) -> str:
    value = str(symbol or "").upper()
    match = re.search(r"(\d{6})", value)
    if not match:
        return ""
    code = match.group(1)
    return f"sh.{code}" if code.startswith(("5", "6", "9")) else f"sz.{code}"


def _period_year(period: str) -> str:
    match = re.search(r"(20\d{2})", str(period or ""))
    return match.group(1) if match else ""
