"""Normalize structured statement evidence into canonical financial metrics."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


CORE_METRICS = ("revenue", "net_income", "gross_margin", "free_cash_flow")


def build_standard_financial_metrics(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build canonical metric rows from local summaries and structured filings."""

    metrics: List[Dict[str, Any]] = []
    for record in [item for item in records if isinstance(item, dict)]:
        source_type = str(record.get("source_type", "")).lower()
        if source_type == "eastmoney_financials":
            metrics.extend(_eastmoney_metric_rows(record))
        elif source_type == "sec_companyfacts":
            metrics.extend(_sec_companyfacts_metric_rows(record))
        elif source_type == "financials":
            metrics.extend(_local_financial_metric_rows(record))

    present = {str(item.get("metric_name", "")) for item in metrics}
    return {
        "metrics": metrics,
        "metric_count": len(metrics),
        "coverage": {
            "required_metrics": list(CORE_METRICS),
            "present_metrics": sorted(present),
            "has_core_metric_lineage": set(CORE_METRICS).issubset(present),
        },
    }


def build_standard_statement_rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build normalized income, balance-sheet, and cash-flow rows."""

    rows: List[Dict[str, Any]] = []
    for record in [item for item in records if isinstance(item, dict)]:
        source_type = str(record.get("source_type", "")).lower()
        if source_type == "eastmoney_financials":
            rows.extend(_eastmoney_statement_rows(record))
        elif source_type == "sec_companyfacts":
            rows.extend(_sec_companyfacts_statement_rows(record))
    return rows


def build_standard_table_artifacts(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group normalized rows into table artifacts with source lineage."""

    rows = build_standard_statement_rows(records)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        table_id = str(row.get("source_table_id") or "")
        if table_id:
            grouped.setdefault(table_id, []).append(row)

    tables: List[Dict[str, Any]] = []
    for table_id, table_rows in grouped.items():
        first = table_rows[0] if table_rows else {}
        tables.append(
            {
                "table_id": table_id,
                "table_type": str(first.get("statement", "financial_statement")),
                "rows": table_rows,
                "columns": sorted({key for row in table_rows for key in row.keys()}),
                "source_evidence_id": str(first.get("evidence_id", "")),
                "period": str(first.get("period", "")),
                "currency": "CNY" if str(first.get("source_type", "")) == "eastmoney_financials" else "",
                "unit": "raw",
                "extraction_method": "structured_statement_api_normalization",
                "confidence": 0.86,
                "metadata": {"provider": str(first.get("provider", ""))},
            }
        )
    return tables


def _eastmoney_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    raw = _dict(metadata.get("raw"))
    table_type = str(metadata.get("table_type") or "")
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or raw.get("SECURITY_CODE") or "")
    period = str(record.get("period") or "")
    report_date = str(raw.get("REPORT_DATE") or raw.get("REPORTDATE") or "")
    notice_date = str(raw.get("NOTICE_DATE") or record.get("publish_time") or "")
    table_id = _table_id(symbol, period, evidence_id, table_type or "eastmoney")

    rows: List[Dict[str, Any]] = []
    if table_type == "income":
        revenue = _first_number(raw, ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME"])
        net_income = _first_number(raw, ["PARENT_NETPROFIT", "NETPROFIT"])
        cost = _first_number(raw, ["TOTAL_OPERATE_COST", "OPERATE_COST"])
        if revenue is not None:
            rows.append(_metric_row("revenue", revenue, "CNY", period, table_id, evidence_id, "reported total operating revenue", 0.9, symbol, report_date, notice_date, raw))
        if net_income is not None:
            rows.append(_metric_row("net_income", net_income, "CNY", period, table_id, evidence_id, "reported parent net profit", 0.9, symbol, report_date, notice_date, raw))
        if revenue not in (None, 0) and cost is not None:
            rows.append(_metric_row("gross_margin", (revenue - cost) / revenue * 100.0, "pct", period, table_id, evidence_id, "(revenue - operating cost) / revenue", 0.72, symbol, report_date, notice_date, raw))
    elif table_type == "balance":
        for name, keys in [
            ("total_assets", ["TOTAL_ASSETS"]),
            ("total_liabilities", ["TOTAL_LIABILITIES"]),
            ("equity", ["TOTAL_EQUITY", "TOTAL_PARENT_EQUITY"]),
        ]:
            value = _first_number(raw, keys)
            if value is not None:
                rows.append(_metric_row(name, value, "CNY", period, table_id, evidence_id, f"reported {name}", 0.88, symbol, report_date, notice_date, raw))
    elif table_type == "cashflow":
        ocf = _first_number(raw, ["NETCASH_OPERATE", "NETCASH_OPERATE_ACT"])
        capex = _first_number(raw, ["CONSTRUCT_LONG_ASSET_PAY_CASH", "PURCHASE_FIX_ASSET"])
        if ocf is not None:
            rows.append(_metric_row("operating_cash_flow", ocf, "CNY", period, table_id, evidence_id, "reported net operating cash flow", 0.88, symbol, report_date, notice_date, raw))
        if capex is not None:
            rows.append(_metric_row("capex", capex, "CNY", period, table_id, evidence_id, "reported cash paid for long-term assets", 0.72, symbol, report_date, notice_date, raw))
        if ocf is not None and capex is not None:
            rows.append(_metric_row("free_cash_flow", ocf - capex, "CNY", period, table_id, evidence_id, "operating_cash_flow - capex", 0.68, symbol, report_date, notice_date, raw))
    return rows


def _sec_companyfacts_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    facts = _dict(metadata.get("metrics"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_id = _table_id(symbol, period, evidence_id, "sec_companyfacts")
    rows: List[Dict[str, Any]] = []
    mapping = [
        ("revenue", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"], "reported SEC revenue"),
        ("net_income", ["NetIncomeLoss"], "reported SEC net income"),
        ("total_assets", ["Assets"], "reported SEC assets"),
        ("cash_and_equivalents", ["CashAndCashEquivalentsAtCarryingValue"], "reported SEC cash and equivalents"),
    ]
    for metric_name, keys, formula in mapping:
        fact = _first_fact(facts, keys)
        value = _safe_float(fact.get("value")) if fact else None
        if value is None:
            continue
        rows.append(
            _metric_row(
                metric_name=metric_name,
                value=value,
                unit=str(fact.get("unit") or "USD"),
                period=period,
                source_table_id=table_id,
                source_evidence_id=evidence_id,
                calculation_formula=formula,
                confidence=0.92,
                symbol=symbol,
                report_date=str(fact.get("end") or ""),
                notice_date=str(fact.get("filed") or record.get("publish_time") or ""),
                raw=fact,
            )
        )
    return rows


def _sec_companyfacts_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    facts = _dict(metadata.get("metrics"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_id = _table_id(symbol, period, evidence_id, "sec_companyfacts")
    mapping = [
        ("income_statement", "revenue", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]),
        ("income_statement", "net_income", ["NetIncomeLoss"]),
        ("balance_sheet", "total_assets", ["Assets"]),
        ("balance_sheet", "cash_and_equivalents", ["CashAndCashEquivalentsAtCarryingValue"]),
    ]
    rows: List[Dict[str, Any]] = []
    for statement, line_item, keys in mapping:
        fact = _first_fact(facts, keys)
        value = _safe_float(fact.get("value")) if fact else None
        if value is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": statement,
                "line_item": line_item,
                "value": value,
                "unit": str(fact.get("unit") or "USD"),
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": str(fact.get("end") or ""),
                "source_type": "sec_companyfacts",
                "provider": "SEC EDGAR",
            }
        )
    return rows


def _eastmoney_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    raw = _dict(metadata.get("raw"))
    table_type = str(metadata.get("table_type") or "")
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or raw.get("SECURITY_CODE") or "")
    period = str(record.get("period") or "")
    report_date = str(raw.get("REPORT_DATE") or raw.get("REPORTDATE") or "")
    table_id = _table_id(symbol, period, evidence_id, table_type or "eastmoney")
    mapping = {
        "income": (
            "income_statement",
            [
                ("revenue", ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME"]),
                ("operating_cost", ["TOTAL_OPERATE_COST", "OPERATE_COST"]),
                ("operating_profit", ["OPERATE_PROFIT"]),
                ("total_profit", ["TOTAL_PROFIT"]),
                ("net_income", ["PARENT_NETPROFIT", "NETPROFIT"]),
            ],
        ),
        "balance": (
            "balance_sheet",
            [
                ("total_assets", ["TOTAL_ASSETS"]),
                ("total_liabilities", ["TOTAL_LIABILITIES"]),
                ("equity", ["TOTAL_EQUITY", "TOTAL_PARENT_EQUITY"]),
            ],
        ),
        "cashflow": (
            "cash_flow_statement",
            [
                ("operating_cash_flow", ["NETCASH_OPERATE", "NETCASH_OPERATE_ACT"]),
                ("investing_cash_flow", ["NETCASH_INVEST"]),
                ("financing_cash_flow", ["NETCASH_FINANCE"]),
                ("capex", ["CONSTRUCT_LONG_ASSET_PAY_CASH", "PURCHASE_FIX_ASSET"]),
            ],
        ),
    }
    if table_type not in mapping:
        return []
    statement, items = mapping[table_type]
    rows: List[Dict[str, Any]] = []
    for line_item, keys in items:
        value = _first_number(raw, keys)
        if value is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": statement,
                "line_item": line_item,
                "value": value,
                "unit": "CNY",
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": report_date,
                "source_type": "eastmoney_financials",
                "provider": "Eastmoney",
            }
        )
    return rows


def _local_financial_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or metadata.get("symbol") or "")
    period = str(record.get("period") or metadata.get("period") or "")
    table_id = _table_id(symbol, period, evidence_id, "financial_metrics")
    metric_map = [
        ("revenue", "revenue_billion", "USD_billion", "reported revenue"),
        ("net_income", "net_income_billion", "USD_billion", "reported net income"),
        ("gross_margin", "gross_margin_pct", "pct", "reported gross margin"),
        ("free_cash_flow", "free_cash_flow_billion", "USD_billion", "reported free cash flow"),
    ]
    rows: List[Dict[str, Any]] = []
    for metric_name, key, unit, formula in metric_map:
        value = _first_number({**metadata, **record}, [key])
        if value is not None:
            rows.append(_metric_row(metric_name, value, unit, period, table_id, evidence_id, formula, 0.95, symbol, "", str(record.get("publish_time") or ""), metadata))
    return rows


def _metric_row(
    metric_name: str,
    value: float,
    unit: str,
    period: str,
    source_table_id: str,
    source_evidence_id: str,
    calculation_formula: str,
    confidence: float,
    symbol: str,
    report_date: str,
    notice_date: str,
    raw: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "metric_name": metric_name,
        "value": round(float(value), 6),
        "unit": unit,
        "period": period,
        "source_table_id": source_table_id,
        "source_evidence_id": source_evidence_id,
        "calculation_formula": calculation_formula,
        "confidence": confidence,
        "symbol": symbol,
        "report_date": report_date,
        "notice_date": notice_date,
        "raw_field_keys": sorted(str(key) for key in raw.keys()),
    }


def _first_number(raw: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = raw.get(key)
        number = _safe_float(value)
        if number is not None:
            return number
    return None


def _first_fact(raw: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict) and _safe_float(value.get("value")) is not None:
            return value
    return {}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _evidence_id(record: Dict[str, Any]) -> str:
    return str(record.get("evidence_id") or record.get("sample_id") or "")


def _table_id(symbol: str, period: str, evidence_id: str, table_type: str) -> str:
    parts = [symbol or "unknown", period or "unknown", table_type or "table", evidence_id or "noev"]
    return "_".join(str(part).lower().replace(" ", "_") for part in parts if str(part).strip())
