"""Three-statement normalization for company research reports."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


def build_three_statement_view(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an income/cash-flow/balance-sheet view from available evidence records.

    The current local data is a financial summary, not full source statements. This
    function keeps every derived balance-sheet line explicitly marked as estimated.
    """

    rows: List[Dict[str, Any]] = []
    source_records = [record for record in records if isinstance(record, dict)]
    financial_records = [record for record in source_records if str(record.get("source_type", "")).lower() == "financials"]
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
        total_assets = net_income / (roa / 100) if net_income is not None and roa not in (None, 0) else None
        shareholder_equity = net_income / (roe / 100) if net_income is not None and roe not in (None, 0) else None
        liabilities = (
            total_assets - shareholder_equity
            if total_assets is not None and shareholder_equity is not None
            else None
        )

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
                    ("total_assets", total_assets, True),
                    ("total_liabilities", liabilities, True),
                    ("shareholder_equity", shareholder_equity, True),
                ],
            )
        )

    return {
        "rows": rows,
        "coverage": _coverage(rows),
        "source_record_count": len(financial_records),
    }


def build_three_statement_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(build_three_statement_view(records)["rows"])


def _financial_metrics_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    metrics = dict(metadata)
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
