"""Three-statement normalization for company research reports."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from src.data.financial_quality import build_net_income_quality_fields
from src.data.financial_statement_metrics import build_standard_statement_rows


def build_three_statement_view(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an income/cash-flow/balance-sheet view from available evidence records.

    The current local data is a financial summary, not full source statements. This
    function keeps every derived balance-sheet line explicitly marked as estimated.
    """

    rows: List[Dict[str, Any]] = build_standard_statement_rows(records)
    source_records = [record for record in records if isinstance(record, dict)]
    financial_records = [
        record
        for record in source_records
        if str(record.get("source_type", "")).lower() == "financials"
        and _record_has_structured_financials(record)
    ]
    for record in financial_records:
        metrics = _financial_metrics_from_record(record)
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        symbol = str(record.get("symbol") or metrics.get("symbol") or "")
        period = str(record.get("period") or metrics.get("period") or "")

        revenue = _safe_float(metrics.get("revenue_billion"))
        gross_margin = _safe_float(metrics.get("gross_margin_pct"))
        net_margin = _safe_float(metrics.get("net_margin_pct"))
        roe = _safe_float(metrics.get("roe_pct"))
        roa = _safe_float(metrics.get("roa_pct"))
        operating_cash_flow = _safe_float(metrics.get("operating_cash_flow_billion"))
        free_cash_flow = _safe_float(metrics.get("free_cash_flow_billion"))

        gross_profit = revenue * gross_margin / 100 if revenue is not None and gross_margin is not None else None
        net_income = revenue * net_margin / 100 if revenue is not None and net_margin is not None else None
        capex = operating_cash_flow - free_cash_flow if operating_cash_flow is not None and free_cash_flow is not None else None
        total_assets = _safe_float(metrics.get("total_assets_billion"))
        total_assets_estimated = False
        shareholder_equity = _safe_float(metrics.get("shareholder_equity_billion"))
        shareholder_equity_estimated = False
        liabilities = _safe_float(metrics.get("total_liabilities_billion"))
        cash = _safe_float(metrics.get("cash_and_equivalents_billion"))
        if total_assets is None and net_income is not None and roa not in (None, 0):
            total_assets = net_income / (roa / 100)
            total_assets_estimated = True
        if shareholder_equity is None and net_income is not None and roe not in (None, 0):
            shareholder_equity = net_income / (roe / 100)
            shareholder_equity_estimated = True
        if liabilities is None and total_assets is not None and shareholder_equity is not None:
            liabilities = total_assets - shareholder_equity

        rows.extend(
            _statement_rows(
                symbol=symbol,
                period=period,
                evidence_id=evidence_id,
                statement="income_statement",
                items=[
                    ("revenue", revenue, False),
                    ("gross_profit", gross_profit, True),
                    ("net_income", net_income, True),
                ],
            )
        )
        rows.extend(
            _statement_rows(
                symbol=symbol,
                period=period,
                evidence_id=evidence_id,
                statement="cash_flow_statement",
                items=[
                    ("operating_cash_flow", operating_cash_flow, False),
                    ("capital_expenditure", capex, True),
                    ("free_cash_flow", free_cash_flow, False),
                ],
            )
        )
        rows.extend(
            _statement_rows(
                symbol=symbol,
                period=period,
                evidence_id=evidence_id,
                statement="balance_sheet",
                items=[
                    ("total_assets", total_assets, total_assets_estimated),
                    ("total_liabilities", liabilities, liabilities is None),
                    ("shareholder_equity", shareholder_equity, shareholder_equity_estimated),
                    ("cash_and_equivalents", cash, False),
                ],
            )
        )

    return {
        "rows": rows,
        "coverage": _coverage(rows),
        "source_record_count": len(financial_records)
        + len([record for record in source_records if str(record.get("source_type", "")).lower() == "eastmoney_financials"]),
    }


def build_three_statement_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(build_three_statement_view(records)["rows"])


def _financial_metrics_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    metrics = dict(metadata)
    financials = metadata.get("financials") if isinstance(metadata.get("financials"), dict) else {}
    snapshot = metadata.get("snapshot") if isinstance(metadata.get("snapshot"), dict) else {}
    if financials:
        metrics.update(_normalize_structured_financials(financials))
    if snapshot:
        metrics.update(_normalize_structured_financials(snapshot))
    for key in [
        "symbol",
        "period",
        "revenue_billion",
        "gross_margin_pct",
        "net_margin_pct",
        "roe_pct",
        "roa_pct",
        "operating_cash_flow_billion",
        "free_cash_flow_billion",
    ]:
        if key in record and key not in metrics:
            metrics[key] = record[key]
    if "revenue_billion" not in metrics:
        content = str(record.get("content", ""))
        metrics.update(_parse_content_metrics(content))
    return metrics


def _record_has_structured_financials(record: Dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return str(record.get("source_type", "")).lower() == "financials" or isinstance(metadata.get("financials"), dict)


def _normalize_structured_financials(raw: Dict[str, Any]) -> Dict[str, Any]:
    latest_income = _first_dict(raw.get("income_history")) or _first_dict(raw.get("quarterly_income_history"))
    latest_balance = _first_dict(raw.get("balance_history")) or _first_dict(raw.get("quarterly_balance_history"))
    latest_cashflow = _first_dict(raw.get("cashflow_history")) or _first_dict(raw.get("quarterly_cashflow_history"))
    output: Dict[str, Any] = {}
    revenue = _first_number(raw, ["totalRevenue", "revenue", "Total Revenue"])
    if revenue is None:
        revenue = _first_number(latest_income, ["Total Revenue", "Operating Revenue", "revenue"])
    net_income = _first_number(raw, ["netIncome", "Net Income"])
    if net_income is None:
        net_income = _first_number(latest_income, ["Net Income", "Net Income Common Stockholders"])
    gross_profit = _first_number(latest_income, ["Gross Profit"])
    gross_margin = _first_number(raw, ["grossMargins", "gross_margin_pct"])
    profit_margin = _first_number(raw, ["profitMargins", "net_margin_pct"])
    operating_cash_flow = _first_number(raw, ["operatingCashflow", "operating_cash_flow_billion"])
    if operating_cash_flow is None:
        operating_cash_flow = _first_number(latest_cashflow, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
    free_cash_flow = _first_number(raw, ["freeCashflow", "free_cash_flow_billion"])
    if free_cash_flow is None:
        free_cash_flow = _first_number(latest_cashflow, ["Free Cash Flow"])
    roe = _first_number(raw, ["returnOnEquity", "roe_pct"])
    roa = _first_number(raw, ["returnOnAssets", "roa_pct"])
    total_assets = _first_number(latest_balance, ["Total Assets"])
    total_liabilities = _first_number(latest_balance, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
    shareholder_equity = _first_number(latest_balance, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"])
    cash = _first_number(latest_balance, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])

    if revenue is not None:
        output["revenue_billion"] = _to_billion(revenue)
    if net_income is not None:
        output["net_income_billion"] = _to_billion(net_income)
    quality = build_net_income_quality_fields(raw, latest_income, net_income=net_income, revenue=revenue)
    if quality.get("adjusted_net_income") is not None:
        output["adjusted_net_income_billion"] = _to_billion(float(quality["adjusted_net_income"]))
    if quality.get("non_recurring_gain") is not None:
        output["non_recurring_gain_billion"] = _to_billion(float(quality["non_recurring_gain"]))
    if quality.get("normalized_income") is not None:
        output["normalized_income_billion"] = _to_billion(float(quality["normalized_income"]))
    if quality.get("normalized_ebitda") is not None:
        output["normalized_ebitda_billion"] = _to_billion(float(quality["normalized_ebitda"]))
    if quality.get("non_recurring_gain_ratio") is not None:
        output["non_recurring_gain_ratio"] = float(quality["non_recurring_gain_ratio"])
    output["net_income_quality_flag"] = quality.get("net_income_quality_flag", "reported")
    output["valuation_input_usable"] = bool(quality.get("valuation_input_usable", True))
    output["valuation_input_rejection_reason"] = str(quality.get("valuation_input_rejection_reason") or "")
    if gross_margin is not None:
        output["gross_margin_pct"] = _ratio_to_pct(gross_margin)
    elif gross_profit is not None and revenue not in (None, 0):
        output["gross_margin_pct"] = float(gross_profit) / float(revenue) * 100.0
    if quality.get("adjusted_net_margin_pct") is not None and quality.get("net_income_quality_flag") == "adjusted_for_non_recurring_gain":
        output["net_margin_pct"] = float(quality["adjusted_net_margin_pct"])
    elif profit_margin is not None:
        output["net_margin_pct"] = _ratio_to_pct(profit_margin)
    elif net_income is not None and revenue not in (None, 0):
        output["net_margin_pct"] = float(net_income) / float(revenue) * 100.0
    if operating_cash_flow is not None:
        output["operating_cash_flow_billion"] = _to_billion(operating_cash_flow)
    if free_cash_flow is not None:
        output["free_cash_flow_billion"] = _to_billion(free_cash_flow)
    if roe is not None:
        output["roe_pct"] = _ratio_to_pct(roe)
    if roa is not None:
        output["roa_pct"] = _ratio_to_pct(roa)
    if total_assets is not None:
        output["total_assets_billion"] = _to_billion(total_assets)
    if total_liabilities is not None:
        output["total_liabilities_billion"] = _to_billion(total_liabilities)
    if shareholder_equity is not None:
        output["shareholder_equity_billion"] = _to_billion(shareholder_equity)
    if cash is not None:
        output["cash_and_equivalents_billion"] = _to_billion(cash)
    return output


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


def _parse_content_metrics(content: str) -> Dict[str, float]:
    from src.features.financial_ratios import build_financial_ratios

    df = pd.DataFrame([{"sample_id": "row", "symbol": "", "period": "", "source_type": "financials", "content": content}])
    row = build_financial_ratios(df).iloc[0].to_dict()
    return {key: value for key, value in row.items() if _safe_float(value) is not None}


def _statement_rows(
    symbol: str,
    period: str,
    evidence_id: str,
    statement: str,
    items: List[tuple[str, float | None, bool]],
) -> List[Dict[str, Any]]:
    rows = []
    for line_item, value, estimated in items:
        if value is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": statement,
                "line_item": line_item,
                "value_billion": round(float(value), 4),
                "unit": "USD_billion",
                "estimated": bool(estimated),
                "evidence_id": evidence_id,
            }
        )
    return rows


def _coverage(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    statements = {}
    for row in rows:
        statement = str(row.get("statement", ""))
        statements.setdefault(statement, 0)
        statements[statement] += 1
    required = {"income_statement", "cash_flow_statement", "balance_sheet"}
    return {
        "statements": statements,
        "has_three_statement_view": required.issubset(statements.keys()),
        "line_item_count": len(rows),
    }


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
