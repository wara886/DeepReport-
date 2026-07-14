"""Tushare Pro structured financial adapter for China A-shares."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from src.data.source_quality import apply_source_quality
from src.utils.env import load_env_files


ENDPOINTS = {
    "income": "income",
    "balance": "balancesheet",
    "cashflow": "cashflow",
    "indicator": "fina_indicator",
}


def fetch_tushare_financials(
    *, symbol: str, period: str, topk: int = 4, client: Any = None
) -> dict[str, Any]:
    load_env_files(config_path="configs/data_sources.yaml")
    ts_code = _ts_code(symbol)
    year = _period_year(period)
    token = str(os.getenv("TUSHARE_TOKEN") or "").strip()
    if not ts_code or not year:
        return {"hits": [], "meta": {"mode": "tushare_financials", "failure_reason": "unsupported_symbol_or_period"}}
    if client is None and not token:
        return {"hits": [], "meta": {"mode": "tushare_financials", "failure_reason": "missing_api_token"}}
    try:
        if client is None:
            import tushare as ts  # type: ignore

            client = ts.pro_api(token)
    except Exception as exc:
        return {"hits": [], "meta": {"mode": "tushare_financials", "failure_reason": "client_init_failed", "error": str(exc)}}

    hits: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    query_period = f"{year}1231"
    for table_type, method_name in ENDPOINTS.items():
        try:
            frame = getattr(client, method_name)(ts_code=ts_code, period=query_period)
            records = frame.to_dict("records") if frame is not None and not frame.empty else []
        except Exception as exc:
            errors[table_type] = str(exc)
            continue
        if not records:
            errors[table_type] = "no_period_matched_rows"
            continue
        row = dict(records[0])
        digest = hashlib.sha1(f"{ts_code}|{period}|{table_type}|{json.dumps(row, sort_keys=True, default=str)}".encode()).hexdigest()[:10]
        evidence_id = f"{ts_code.replace('.', '')}_{period}_tushare_{table_type}_{digest}"
        record = {
            "evidence_id": evidence_id,
            "sample_id": evidence_id,
            "symbol": str(symbol).upper(),
            "period": str(period),
            "source_type": "tushare_financials",
            "title": f"{symbol} Tushare {table_type} financial data",
            "source_url": "https://tushare.pro/document/2",
            "publish_time": str(row.get("ann_date") or row.get("f_ann_date") or row.get("end_date") or ""),
            "content": _content(table_type, row),
            "trust_level": "medium",
            "metadata": {"provider": "Tushare Pro", "table_type": table_type, "ts_code": ts_code, "raw": row},
        }
        hits.append(apply_source_quality(record))
    return {
        "hits": hits[:topk],
        "meta": {
            "mode": "tushare_financials",
            "symbol": str(symbol).upper(),
            "ts_code": ts_code,
            "record_count": len(hits),
            "table_types": [item["metadata"]["table_type"] for item in hits],
            "errors": errors,
            "failure_reason": "" if hits else ("permission_or_quota_error" if errors else "no_period_matched_rows"),
        },
    }


def _content(table_type: str, row: dict[str, Any]) -> str:
    values = [f"{key}={value}" for key, value in row.items() if value not in (None, "", "nan")]
    return f"Tushare {table_type} financial data: " + " | ".join(values)


def _ts_code(symbol: str) -> str:
    value = str(symbol or "").upper()
    match = re.search(r"(\d{6})", value)
    if not match:
        return ""
    code = match.group(1)
    if value.endswith((".SS", ".SH")) or code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    if value.endswith(".SZ") or code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    return ""


def _period_year(period: str) -> str:
    match = re.search(r"(20\d{2})", str(period or ""))
    return match.group(1) if match else ""
