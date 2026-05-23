"""Build source-linked financial metric artifacts."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from src.data.financial_statement_metrics import (
    build_standard_financial_metrics,
    build_standard_table_artifacts,
)
from src.data.financial_quality import build_net_income_quality_fields
from src.features.financial_ratios import build_financial_ratios
from src.features.financial_statements import build_three_statement_view
from src.utils.periods import parse_iso_date, parse_quarter, period_match, period_target_date


CORE_METRICS = ("revenue", "net_income", "gross_margin", "free_cash_flow")


def build_financial_metric_lineage(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract core company-report metrics with table/evidence lineage."""

    standard = build_standard_financial_metrics(records)
    standard_coverage = standard.get("coverage", {}) if isinstance(standard.get("coverage"), dict) else {}
    rows: List[Dict[str, Any]] = list(standard.get("metrics", []) if isinstance(standard.get("metrics"), list) else [])
    rejected_metrics: List[Dict[str, Any]] = list(
        standard.get("rejected_metrics", []) if isinstance(standard.get("rejected_metrics"), list) else []
    )
    for record in [item for item in records if isinstance(item, dict)]:
        if str(record.get("source_type", "")).lower() not in {"financials", "market_api", "market_data"}:
            continue
        if str(record.get("source_type", "")).lower() in {"market_api", "market_data"}:
            rejected_metrics.append(
                {
                    "metric_name": "market_embedded_financials",
                    "target_period": record.get("period", ""),
                    "source_evidence_id": record.get("evidence_id") or record.get("sample_id") or "",
                    "reason": "market_financials_not_allowed_as_statement_primary_evidence",
                }
            )
            continue
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        symbol = str(record.get("symbol", ""))
        period = str(record.get("period", ""))
        metadata = dict(record.get("metadata", {})) if isinstance(record.get("metadata"), dict) else {}
        report_date = str(metadata.get("report_date") or metadata.get("end") or metadata.get("as_of_date") or "")
        notice_date = str(metadata.get("notice_date") or record.get("publish_time") or "")
        metrics = _coerce_metrics(record)
        table_id = _table_id(symbol=symbol, period=period, evidence_id=evidence_id, table_type="financial_metrics")

        if metrics.get("revenue_billion") is not None:
            _append_metric_once(
                rows,
                _metric_row(
                    metric_name="revenue",
                    value=metrics["revenue_billion"],
                    unit="USD_billion",
                    period=period,
                    source_table_id=table_id,
                    source_evidence_id=evidence_id,
                    calculation_formula="reported revenue",
                    confidence=0.95,
                    symbol=symbol,
                    report_date=report_date,
                    notice_date=notice_date,
                    source_period=str(metadata.get("source_period") or period),
                )
            )
        if metrics.get("gross_margin_pct") is not None:
            _append_metric_once(
                rows,
                _metric_row(
                    metric_name="gross_margin",
                    value=metrics["gross_margin_pct"],
                    unit="pct",
                    period=period,
                    source_table_id=table_id,
                    source_evidence_id=evidence_id,
                    calculation_formula="reported gross margin",
                    confidence=0.95,
                    symbol=symbol,
                    report_date=report_date,
                    notice_date=notice_date,
                    source_period=str(metadata.get("source_period") or period),
                )
            )
        net_income = metrics.get("adjusted_net_income_billion") or metrics.get("net_income_billion")
        formula = (
            "adjusted net income excluding non-recurring gain"
            if metrics.get("adjusted_net_income_billion") is not None
            and str(metrics.get("net_income_quality_flag") or "") == "adjusted_for_non_recurring_gain"
            else "reported net income"
        )
        confidence = 0.92 if "adjusted" in formula else 0.95
        if net_income is None and metrics.get("revenue_billion") is not None and metrics.get("net_margin_pct") is not None:
            net_income = float(metrics["revenue_billion"]) * float(metrics["net_margin_pct"]) / 100.0
            formula = "revenue_billion * net_margin_pct / 100"
            confidence = 0.8
        if net_income is not None:
            _append_metric_once(
                rows,
                _metric_row(
                    metric_name="net_income",
                    value=net_income,
                    unit="USD_billion",
                    period=period,
                    source_table_id=table_id,
                    source_evidence_id=evidence_id,
                    calculation_formula=formula,
                    confidence=confidence,
                    symbol=symbol,
                    report_date=report_date,
                    notice_date=notice_date,
                    source_period=str(metadata.get("source_period") or period),
                )
            )
        if metrics.get("adjusted_net_income_billion") is not None:
            _append_metric_once(
                rows,
                _metric_row(
                    metric_name="adjusted_net_income",
                    value=metrics["adjusted_net_income_billion"],
                    unit="USD_billion",
                    period=period,
                    source_table_id=table_id,
                    source_evidence_id=evidence_id,
                    calculation_formula="normalized income or net income less non-recurring gain",
                    confidence=0.92,
                    symbol=symbol,
                    report_date=report_date,
                    notice_date=notice_date,
                    source_period=str(metadata.get("source_period") or period),
                ),
            )
        if metrics.get("non_recurring_gain_billion") is not None:
            _append_metric_once(
                rows,
                _metric_row(
                    metric_name="non_recurring_gain",
                    value=metrics["non_recurring_gain_billion"],
                    unit="USD_billion",
                    period=period,
                    source_table_id=table_id,
                    source_evidence_id=evidence_id,
                    calculation_formula="reported unusual item or gain on sale of securities",
                    confidence=0.9,
                    symbol=symbol,
                    report_date=report_date,
                    notice_date=notice_date,
                    source_period=str(metadata.get("source_period") or period),
                ),
            )
        if metrics.get("free_cash_flow_billion") is not None:
            _append_metric_once(
                rows,
                _metric_row(
                    metric_name="free_cash_flow",
                    value=metrics["free_cash_flow_billion"],
                    unit="USD_billion",
                    period=period,
                    source_table_id=table_id,
                    source_evidence_id=evidence_id,
                    calculation_formula="reported free cash flow",
                    confidence=0.95,
                    symbol=symbol,
                    report_date=report_date,
                    notice_date=notice_date,
                    source_period=str(metadata.get("source_period") or period),
                )
            )

        if metadata.get("source_table_id"):
            for row in rows:
                if row["source_evidence_id"] == evidence_id:
                    row["source_table_id"] = str(metadata["source_table_id"])

    present = {str(item.get("metric_name")) for item in rows}
    return {
        "metrics": rows,
        "metric_count": len(rows),
        "rejected_metrics": rejected_metrics,
        "rejected_metric_count": len(rejected_metrics),
        "coverage": {
            "required_metrics": list(CORE_METRICS),
            "present_metrics": sorted(present),
            "has_core_metric_lineage": set(CORE_METRICS).issubset(present),
            "standard_metric_count": int(standard.get("metric_count", 0) or 0),
            "standard_has_core_metric_lineage": bool(standard_coverage.get("has_core_metric_lineage")),
            "rejected_metric_count": len(rejected_metrics),
        },
    }


def build_financial_metric_tables(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build minimal table artifacts from existing three-statement rows."""

    statement_payload = build_three_statement_view(records)
    rows_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for row in statement_payload.get("rows", []):
        table_id = _table_id(
            symbol=str(row.get("symbol", "")),
            period=str(row.get("period", "")),
            evidence_id=str(row.get("evidence_id", "")),
            table_type=str(row.get("statement", "financial_statement")),
        )
        rows_by_table.setdefault(table_id, []).append(dict(row))

    tables: List[Dict[str, Any]] = []
    for table_id, rows in rows_by_table.items():
        first = rows[0] if rows else {}
        tables.append(
            {
                "table_id": table_id,
                "table_type": str(first.get("statement", "financial_statement")),
                "rows": rows,
                "columns": sorted({key for row in rows for key in row.keys()}),
                "source_evidence_id": str(first.get("evidence_id", "")),
                "period": str(first.get("period", "")),
                "currency": "USD",
                "unit": "billion",
                "extraction_method": "financial_summary_normalization",
                "confidence": 0.8,
                "metadata": {"estimated_rows": [row.get("line_item") for row in rows if row.get("estimated")]},
            }
        )
    return tables


def _metric_row(
    metric_name: str,
    value: Any,
    unit: str,
    period: str,
    source_table_id: str,
    source_evidence_id: str,
    calculation_formula: str,
    confidence: float,
    symbol: str,
    report_date: str = "",
    notice_date: str = "",
    source_period: str = "",
) -> Dict[str, Any]:
    return {
        "metric_lineage_id": _metric_lineage_id(symbol, period, metric_name, source_table_id, source_evidence_id, report_date),
        "metric_name": metric_name,
        "value": round(float(value), 6),
        "unit": unit,
        "period": period,
        "source_period": source_period or period,
        "report_date": report_date,
        "notice_date": notice_date,
        "period_match": _period_match(period=period, report_date=report_date),
        "source_table_id": source_table_id,
        "source_evidence_id": source_evidence_id,
        "calculation_formula": calculation_formula,
        "confidence": confidence,
        "symbol": symbol,
    }


def _coerce_metrics(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(record.get("metadata", {})) if isinstance(record.get("metadata"), dict) else {}
    metrics = dict(metadata)
    financials = metadata.get("financials") if isinstance(metadata.get("financials"), dict) else {}
    snapshot = metadata.get("snapshot") if isinstance(metadata.get("snapshot"), dict) else {}
    if financials:
        metrics.update(_normalize_structured_financials(financials))
    if snapshot:
        metrics.update(_normalize_structured_financials(snapshot))
    for key in (
        "revenue_billion",
        "net_income_billion",
        "net_margin_pct",
        "gross_margin_pct",
        "operating_cash_flow_billion",
        "free_cash_flow_billion",
    ):
        if key in record and key not in metrics:
            metrics[key] = record[key]

    content_metrics = _extract_content_metrics(record)
    for key, value in content_metrics.items():
        if key not in metrics or _safe_float(metrics.get(key)) is None:
            metrics[key] = value
    return {key: _safe_float(value) for key, value in metrics.items()}


def _normalize_structured_financials(raw: Dict[str, Any]) -> Dict[str, Any]:
    latest_income = _first_dict(raw.get("income_history")) or _first_dict(raw.get("quarterly_income_history"))
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
    return output


def _append_metric_once(rows: List[Dict[str, Any]], row: Dict[str, Any]) -> None:
    metric = str(row.get("metric_name") or "")
    evidence_id = str(row.get("source_evidence_id") or "")
    if any(str(item.get("metric_name") or "") == metric and str(item.get("source_evidence_id") or "") == evidence_id for item in rows):
        return
    rows.append(row)


def _period_match(period: str, report_date: str) -> bool | None:
    return period_match(period=period, report_date=report_date)


def _parse_quarter(value: str) -> tuple[str, str] | None:
    return parse_quarter(value)


def _quarter_from_date(value: str) -> tuple[str, str] | None:
    import re

    match = re.match(r"(\d{4})-(\d{1,2})-\d{1,2}", str(value or ""))
    if not match:
        return None
    quarter = ((int(match.group(2)) - 1) // 3) + 1
    return match.group(1), f"Q{quarter}"


def _period_target_date(period: str) -> date | None:
    return period_target_date(period)


def _parse_iso_date(raw: Any) -> date | None:
    return parse_iso_date(raw)


def _metric_lineage_id(symbol: str, period: str, metric_name: str, table_id: str, evidence_id: str, report_date: str) -> str:
    parts = [symbol or "unknown", period or "unknown", metric_name, table_id or evidence_id or "noev", report_date or "nodate"]
    return "_".join(str(part).lower().replace(" ", "_").replace("/", "_") for part in parts if str(part).strip())


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


def _extract_content_metrics(record: Dict[str, Any]) -> Dict[str, Any]:
    content = str(record.get("content", "") or "")
    if not content.strip():
        return {}
    parsed = build_financial_ratios(
        pd.DataFrame(
            [
                {
                    "sample_id": record.get("sample_id") or record.get("evidence_id") or "",
                    "symbol": record.get("symbol", ""),
                    "period": record.get("period", ""),
                    "source_type": record.get("source_type", ""),
                    "content": content,
                }
            ]
        )
    )
    if parsed.empty:
        return {}
    return {
        key: value
        for key, value in parsed.iloc[0].to_dict().items()
        if key.endswith("_billion") or key.endswith("_pct")
    }


def _table_id(symbol: str, period: str, evidence_id: str, table_type: str) -> str:
    parts = [symbol or "unknown", period or "unknown", table_type, evidence_id or "noev"]
    return "_".join(part.lower().replace(" ", "_") for part in parts if part)


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
