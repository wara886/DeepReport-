"""Normalize structured statement evidence into canonical financial metrics."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List

from src.data.company_universe import infer_market_from_symbol
from src.market.currency_rules import infer_statement_currency
from src.utils.money import UNKNOWN_CURRENCY, normalize_currency_code
from src.utils.periods import parse_iso_date, parse_quarter, period_match, period_target_date
from src.data.financial_quality import build_net_income_quality_fields


CORE_METRICS = ("revenue", "net_income", "gross_margin", "free_cash_flow")


def build_standard_financial_metrics(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build canonical metric rows from local summaries and structured filings."""

    metrics: List[Dict[str, Any]] = []
    rejected_metrics: List[Dict[str, Any]] = []
    for record in [item for item in records if isinstance(item, dict)]:
        source_type = str(record.get("source_type", "")).lower()
        if source_type == "eastmoney_financials":
            rows, rejected = _partition_period_rows(_eastmoney_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type == "sec_companyfacts":
            rows, rejected = _partition_period_rows(_sec_companyfacts_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type == "pdf_statement_table":
            rows, rejected = _partition_period_rows(_pdf_statement_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type in {"market_api", "market_data"}:
            rows, rejected = _partition_period_rows(_market_api_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type == "financials":
            rows, rejected = _partition_period_rows(_local_financial_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)

    present = {str(item.get("metric_name", "")) for item in metrics}
    return {
        "metrics": metrics,
        "metric_count": len(metrics),
        "rejected_metrics": rejected_metrics,
        "rejected_metric_count": len(rejected_metrics),
        "coverage": {
            "required_metrics": list(CORE_METRICS),
            "present_metrics": sorted(present),
            "has_core_metric_lineage": set(CORE_METRICS).issubset(present),
            "rejected_metric_count": len(rejected_metrics),
        },
    }


def build_standard_statement_rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build normalized income, balance-sheet, and cash-flow rows."""

    rows: List[Dict[str, Any]] = []
    for record in [item for item in records if isinstance(item, dict)]:
        source_type = str(record.get("source_type", "")).lower()
        if source_type == "eastmoney_financials":
            accepted, _rejected = _partition_period_rows(_eastmoney_statement_rows(record), record)
            rows.extend(accepted)
        elif source_type == "sec_companyfacts":
            accepted, _rejected = _partition_period_rows(_sec_companyfacts_statement_rows(record), record)
            rows.extend(accepted)
        elif source_type == "pdf_statement_table":
            accepted, _rejected = _partition_period_rows(_pdf_statement_rows(record), record)
            rows.extend(accepted)
        elif source_type in {"market_api", "market_data"}:
            accepted, _rejected = _partition_period_rows(_market_api_statement_rows(record), record)
            rows.extend(accepted)
    priority = {"sec_companyfacts": 0, "sec_filing": 1, "pdf_statement_table": 2, "eastmoney_financials": 3, "market_api": 4, "market_data": 4}
    rows.sort(key=lambda row: priority.get(str(row.get("source_type") or "").lower(), 99))
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
                "currency": normalize_currency_code(first.get("currency") or first.get("unit")),
                "unit": str(first.get("scale") or "raw"),
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
        (
            "operating_cash_flow",
            ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
            "reported SEC operating cash flow",
        ),
        (
            "capex",
            ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
            "reported SEC cash paid for capital assets",
        ),
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
    ocf = _first_fact(facts, ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"])
    capex = _first_fact(facts, ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"])
    ocf_value = _safe_float(ocf.get("value")) if ocf else None
    capex_value = _safe_float(capex.get("value")) if capex else None
    if ocf_value is not None and capex_value is not None:
        raw = dict(ocf)
        raw["capex_value"] = capex_value
        rows.append(
            _metric_row(
                metric_name="free_cash_flow",
                value=ocf_value - capex_value,
                unit=str(ocf.get("unit") or "USD"),
                period=period,
                source_table_id=table_id,
                source_evidence_id=evidence_id,
                calculation_formula="operating_cash_flow - capex",
                confidence=0.72,
                symbol=symbol,
                report_date=str(ocf.get("end") or ""),
                notice_date=str(ocf.get("filed") or record.get("publish_time") or ""),
                raw=raw,
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
        ("cash_flow_statement", "operating_cash_flow", ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
        ("cash_flow_statement", "capex", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]),
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
                "notice_date": str(fact.get("filed") or record.get("publish_time") or ""),
                "source_period": str(fact.get("fy") or fact.get("fp") or period),
                "period_match": _period_match(period=period, report_date=str(fact.get("end") or ""), raw=fact),
                "source_type": "sec_companyfacts",
                "provider": "SEC EDGAR",
            }
        )
    ocf = _first_fact(facts, ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"])
    capex = _first_fact(facts, ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"])
    ocf_value = _safe_float(ocf.get("value")) if ocf else None
    capex_value = _safe_float(capex.get("value")) if capex else None
    if ocf_value is not None and capex_value is not None:
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": "cash_flow_statement",
                "line_item": "free_cash_flow",
                "value": ocf_value - capex_value,
                "unit": str(ocf.get("unit") or "USD"),
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": str(ocf.get("end") or ""),
                "notice_date": str(ocf.get("filed") or record.get("publish_time") or ""),
                "source_period": str(ocf.get("fy") or ocf.get("fp") or period),
                "period_match": _period_match(period=period, report_date=str(ocf.get("end") or ""), raw=ocf),
                "source_type": "sec_companyfacts",
                "provider": "SEC EDGAR",
                "calculation_formula": "operating_cash_flow - capex",
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
                "period_match": _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}),
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
        ("adjusted_net_income", "adjusted_net_income_billion", "USD_billion", "adjusted or normalized net income"),
        ("non_recurring_gain", "non_recurring_gain_billion", "USD_billion", "non-recurring gain"),
        ("gross_margin", "gross_margin_pct", "pct", "reported gross margin"),
        ("free_cash_flow", "free_cash_flow_billion", "USD_billion", "reported free cash flow"),
    ]
    rows: List[Dict[str, Any]] = []
    for metric_name, key, unit, formula in metric_map:
        value = _first_number({**metadata, **record}, [key])
        if value is not None:
            rows.append(_metric_row(metric_name, value, unit, period, table_id, evidence_id, formula, 0.95, symbol, "", str(record.get("publish_time") or ""), metadata))
    return rows


def _market_api_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    financials = _dict(metadata.get("financials"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    currency_meta = _currency_meta_for_record(record)
    currency = currency_meta.statement_currency
    confidence = 0.62 if currency != UNKNOWN_CURRENCY else 0.46
    table_id = _table_id(symbol, period, evidence_id, "yahoo_financials")
    income = _latest_statement_row(financials, "income", period)
    balance = _latest_statement_row(financials, "balance", period)
    cashflow = _latest_statement_row(financials, "cashflow", period)
    rows: List[Dict[str, Any]] = []

    revenue = _first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"])
    net_income = _first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"])
    quality = build_net_income_quality_fields(financials, income, net_income=net_income, revenue=revenue)
    adjusted_net_income = quality.get("adjusted_net_income")
    gross_profit = _first_number(income, ["Gross Profit", "grossProfit"])
    total_assets = _first_number(balance, ["Total Assets", "totalAssets"])
    total_liabilities = _first_number(balance, ["Total Liabilities Net Minority Interest", "totalLiabilities", "Total Liabilities"])
    equity = _first_number(balance, ["Total Equity Gross Minority Interest", "Stockholders Equity", "totalStockholderEquity"])
    operating_cash_flow = _first_number(cashflow, ["Operating Cash Flow", "totalCashFromOperatingActivities", "Cash Flow From Continuing Operating Activities"])
    capex = _first_number(cashflow, ["Capital Expenditure", "capitalExpenditures"])
    free_cash_flow = _first_number(cashflow, ["Free Cash Flow", "freeCashFlow"])

    report_date = str(income.get("end_date") or balance.get("end_date") or cashflow.get("end_date") or "")
    raw = {
        "period": period,
        "end": report_date,
        "source_type": str(record.get("source_type") or "market_api"),
        "net_income_quality_flag": quality.get("net_income_quality_flag"),
        "valuation_input_usable": quality.get("valuation_input_usable"),
        "valuation_input_rejection_reason": quality.get("valuation_input_rejection_reason"),
        "non_recurring_gain_ratio": quality.get("non_recurring_gain_ratio"),
    }
    for metric_name, value, formula in [
        ("revenue", revenue, "Yahoo Finance reported revenue"),
        (
            "net_income",
            adjusted_net_income if adjusted_net_income is not None else net_income,
            "Yahoo Finance adjusted/normalized net income"
            if adjusted_net_income is not None and adjusted_net_income != net_income
            else "Yahoo Finance reported net income",
        ),
        ("adjusted_net_income", adjusted_net_income, "Yahoo Finance normalized income or net income less non-recurring gain"),
        ("non_recurring_gain", quality.get("non_recurring_gain"), "Yahoo Finance unusual item or gain on sale of securities"),
        ("total_assets", total_assets, "Yahoo Finance reported total assets"),
        ("total_liabilities", total_liabilities, "Yahoo Finance reported total liabilities"),
        ("equity", equity, "Yahoo Finance reported equity"),
        ("operating_cash_flow", operating_cash_flow, "Yahoo Finance reported operating cash flow"),
        ("capex", abs(capex) if capex is not None else None, "Yahoo Finance reported capital expenditure"),
        ("free_cash_flow", free_cash_flow, "Yahoo Finance reported free cash flow"),
    ]:
        if value is None:
            continue
        rows.append(_metric_row(metric_name, value, currency, period, table_id, evidence_id, formula, confidence, symbol, report_date, str(record.get("publish_time") or ""), {**raw, "currency_basis": currency_meta.currency_basis, "inferred_from": currency_meta.inferred_from}))
    if gross_profit is not None and revenue not in (None, 0):
        rows.append(_metric_row("gross_margin", float(gross_profit) / float(revenue) * 100.0, "pct", period, table_id, evidence_id, "gross_profit / revenue", 0.62, symbol, report_date, str(record.get("publish_time") or ""), raw))
    return rows


def _market_api_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    financials = _dict(metadata.get("financials"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    currency_meta = _currency_meta_for_record(record)
    currency = currency_meta.statement_currency
    table_id = _table_id(symbol, period, evidence_id, "yahoo_financials")
    income = _latest_statement_row(financials, "income", period)
    balance = _latest_statement_row(financials, "balance", period)
    cashflow = _latest_statement_row(financials, "cashflow", period)
    specs = [
        ("income_statement", "revenue", _first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]), income),
        (
            "income_statement",
            "net_income",
            build_net_income_quality_fields(
                financials,
                income,
                net_income=_first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
                revenue=_first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]),
            ).get("adjusted_net_income")
            or _first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
            income,
        ),
        (
            "income_statement",
            "adjusted_net_income",
            build_net_income_quality_fields(
                financials,
                income,
                net_income=_first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
                revenue=_first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]),
            ).get("adjusted_net_income"),
            income,
        ),
        (
            "income_statement",
            "non_recurring_gain",
            build_net_income_quality_fields(
                financials,
                income,
                net_income=_first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
                revenue=_first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]),
            ).get("non_recurring_gain"),
            income,
        ),
        ("balance_sheet", "total_assets", _first_number(balance, ["Total Assets", "totalAssets"]), balance),
        ("balance_sheet", "total_liabilities", _first_number(balance, ["Total Liabilities Net Minority Interest", "totalLiabilities", "Total Liabilities"]), balance),
        ("balance_sheet", "equity", _first_number(balance, ["Total Equity Gross Minority Interest", "Stockholders Equity", "totalStockholderEquity"]), balance),
        ("cash_flow_statement", "operating_cash_flow", _first_number(cashflow, ["Operating Cash Flow", "totalCashFromOperatingActivities", "Cash Flow From Continuing Operating Activities"]), cashflow),
        ("cash_flow_statement", "capex", _abs_or_none(_first_number(cashflow, ["Capital Expenditure", "capitalExpenditures"])), cashflow),
        ("cash_flow_statement", "free_cash_flow", _first_number(cashflow, ["Free Cash Flow", "freeCashFlow"]), cashflow),
    ]
    rows: List[Dict[str, Any]] = []
    for statement, line_item, value, source_row in specs:
        if value is None:
            continue
        report_date = str(source_row.get("end_date") or "")
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": statement,
                "line_item": line_item,
                "value": value,
                "unit": currency,
                "currency": currency,
                "scale": "unit",
                "currency_basis": currency_meta.currency_basis,
                "currency_confidence": currency_meta.confidence,
                "inferred_from": currency_meta.inferred_from,
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": report_date,
                "notice_date": str(record.get("publish_time") or ""),
                "source_period": period,
                "period_match": _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}),
                "source_type": str(record.get("source_type") or "market_api"),
                "provider": "Yahoo Finance",
            }
        )
    return rows


def _pdf_statement_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_type = str(metadata.get("table_type") or "")
    table_id = str(metadata.get("table_id") or _table_id(symbol, period, evidence_id, table_type or "pdf_statement_table"))
    currency = str(metadata.get("currency") or "")
    if not currency:
        currency = _currency_meta_for_record(record).statement_currency
    unit = _pdf_unit(currency, str(metadata.get("unit") or "raw"))
    report_date = str(metadata.get("report_date") or record.get("publish_time") or "")
    notice_date = str(metadata.get("notice_date") or record.get("publish_time") or "")
    rows = metadata.get("rows") if isinstance(metadata.get("rows"), list) else []
    by_item = {
        str(row.get("line_item") or ""): _safe_float(row.get("value"))
        for row in rows
        if isinstance(row, dict) and _safe_float(row.get("value")) is not None
    }
    output: List[Dict[str, Any]] = []
    mapping = {
        "revenue": ("revenue", "reported PDF revenue"),
        "net_income": ("net_income", "reported PDF net income"),
        "gross_profit": ("gross_profit", "reported PDF gross profit"),
        "operating_cash_flow": ("operating_cash_flow", "reported PDF operating cash flow"),
        "free_cash_flow": ("free_cash_flow", "reported PDF free cash flow"),
        "total_assets": ("total_assets", "reported PDF total assets"),
        "total_liabilities": ("total_liabilities", "reported PDF total liabilities"),
        "equity": ("equity", "reported PDF equity"),
    }
    for source_item, (metric_name, formula) in mapping.items():
        value = by_item.get(source_item)
        if value is None:
            continue
        output.append(_metric_row(metric_name, value, unit, period, table_id, evidence_id, formula, 0.86, symbol, report_date, notice_date, {"period": period}))
    if by_item.get("gross_profit") is not None and by_item.get("revenue") not in (None, 0):
        output.append(
            _metric_row(
                "gross_margin",
                float(by_item["gross_profit"]) / float(by_item["revenue"]) * 100.0,
                "pct",
                period,
                table_id,
                evidence_id,
                "gross_profit / revenue",
                0.78,
                symbol,
                report_date,
                notice_date,
                {"period": period},
            )
        )
    return output


def _pdf_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_type = str(metadata.get("table_type") or "financial_statement")
    table_id = str(metadata.get("table_id") or _table_id(symbol, period, evidence_id, table_type))
    currency = str(metadata.get("currency") or "")
    if not currency:
        currency = _currency_meta_for_record(record).statement_currency
    unit = _pdf_unit(currency, str(metadata.get("unit") or "raw"))
    report_date = str(metadata.get("report_date") or record.get("publish_time") or "")
    rows = metadata.get("rows") if isinstance(metadata.get("rows"), list) else []
    output: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _safe_float(row.get("value"))
        line_item = str(row.get("line_item") or "")
        if value is None or not line_item:
            continue
        output.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": table_type,
                "line_item": line_item,
                "value": value,
                "unit": unit,
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": report_date,
                "notice_date": str(record.get("publish_time") or ""),
                "source_period": period,
                "period_match": _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}),
                "source_type": "pdf_statement_table",
                "provider": "PDF",
            }
        )
    return output


def _pdf_unit(currency: str, unit: str) -> str:
    base = normalize_currency_code(currency)
    if unit == "millions":
        return f"{base}_million"
    if unit == "thousands":
        return f"{base}_thousand"
    return base


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
    currency = _currency_from_unit(unit)
    scale = _scale_from_unit(unit)
    return {
        "metric_key": metric_name,
        "metric_lineage_id": _metric_lineage_id(symbol, period, metric_name, source_table_id, source_evidence_id, report_date),
        "metric_name": metric_name,
        "value": round(float(value), 6),
        "unit": unit,
        "currency": currency,
        "scale": scale,
        "source_id": source_evidence_id,
        "source_type": str(raw.get("source_type") or ""),
        "currency_basis": str(raw.get("currency_basis") or ("unknown" if currency == UNKNOWN_CURRENCY else "source_or_rule")),
        "currency_confidence": str(raw.get("currency_confidence") or ("unknown" if currency == UNKNOWN_CURRENCY else "medium")),
        "inferred_from": str(raw.get("inferred_from") or ""),
        "period": period,
        "source_period": str(raw.get("fy") or raw.get("fp") or raw.get("period") or period),
        "period_match": _period_match(period=period, report_date=report_date, raw=raw),
        "source_table_id": source_table_id,
        "source_evidence_id": source_evidence_id,
        "calculation_formula": calculation_formula,
        "confidence": confidence,
        "symbol": symbol,
        "report_date": report_date,
        "notice_date": notice_date,
        "raw_field_keys": sorted(str(key) for key in raw.keys()),
    }


def _currency_meta_for_record(record: Dict[str, Any]):
    symbol = str(record.get("symbol") or "")
    market = infer_market_from_symbol(symbol).get("market", "")
    return infer_statement_currency(symbol=symbol, market=market, source=record)


def _currency_from_unit(unit: Any) -> str:
    text = str(unit or "")
    if "_" in text:
        text = text.split("_", 1)[0]
    return normalize_currency_code(text)


def _scale_from_unit(unit: Any) -> str:
    text = str(unit or "").lower()
    if "billion" in text:
        return "billion"
    if "million" in text:
        return "million"
    if "thousand" in text:
        return "thousand"
    return "unit"


def _partition_period_rows(rows: List[Dict[str, Any]], record: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("period_match") is False:
            rejected.append(
                {
                    "metric_name": row.get("metric_name") or row.get("line_item"),
                    "value": row.get("value"),
                    "unit": row.get("unit"),
                    "target_period": row.get("period") or record.get("period"),
                    "source_period": row.get("source_period", ""),
                    "report_date": row.get("report_date", ""),
                    "notice_date": row.get("notice_date", record.get("publish_time", "")),
                    "source_table_id": row.get("source_table_id", ""),
                    "source_evidence_id": row.get("source_evidence_id") or row.get("evidence_id", ""),
                    "reason": "period_mismatch",
                }
            )
            continue
        accepted.append(row)
    return accepted, rejected


def _period_match(period: str, report_date: str, raw: Dict[str, Any]) -> bool | None:
    return period_match(period=period, report_date=report_date, raw=raw)


def _parse_quarter(value: str) -> tuple[str, str] | None:
    return parse_quarter(value)


def _quarter_from_date(value: str) -> tuple[str, str] | None:
    import re

    match = re.match(r"(\d{4})-(\d{1,2})-\d{1,2}", str(value or ""))
    if not match:
        return None
    month = int(match.group(2))
    quarter = ((month - 1) // 3) + 1
    return match.group(1), f"Q{quarter}"


def _period_target_date(period: str) -> date | None:
    return period_target_date(period)


def _parse_iso_date(raw: Any) -> date | None:
    return parse_iso_date(raw)


def _metric_lineage_id(symbol: str, period: str, metric_name: str, table_id: str, evidence_id: str, report_date: str) -> str:
    parts = [symbol or "unknown", period or "unknown", metric_name, table_id or evidence_id or "noev", report_date or "nodate"]
    return "_".join(str(part).lower().replace(" ", "_").replace("/", "_") for part in parts if str(part).strip())


def _first_number(raw: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = raw.get(key)
        number = _safe_float(value)
        if number is not None:
            return number
    return None


def _latest_statement_row(financials: Dict[str, Any], statement: str, period: str) -> Dict[str, Any]:
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
    prefer_quarter = _parse_quarter(period) is not None
    keys = [quarterly[statement]] if prefer_quarter else [annual[statement], quarterly[statement]]
    for key in keys:
        rows = financials.get(key)
        if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
            continue
        target_row = _statement_row_for_period(rows, period)
        if target_row:
            return target_row
        if not prefer_quarter:
            return rows[0]
    return {}


def _statement_row_for_period(rows: List[Any], period: str) -> Dict[str, Any]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        report_date = str(row.get("end_date") or row.get("report_date") or row.get("date") or row.get("asOfDate") or "")
        if _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}) is True:
            return row
    return {}


def _abs_or_none(value: float | None) -> float | None:
    return abs(float(value)) if value is not None else None


def _first_fact(raw: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict) and _safe_float(value.get("value")) is not None:
            candidates.append(value)
    if not candidates:
        return {}
    candidates.sort(key=lambda item: str(item.get("end") or item.get("filed") or ""), reverse=True)
    return candidates[0]


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
