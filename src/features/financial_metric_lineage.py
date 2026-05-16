"""Build source-linked financial metric artifacts."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from src.data.financial_statement_metrics import (
    build_standard_financial_metrics,
    build_standard_table_artifacts,
)
from src.features.financial_ratios import build_financial_ratios
from src.features.financial_statements import build_three_statement_view


CORE_METRICS = ("revenue", "net_income", "gross_margin", "free_cash_flow")


def build_financial_metric_lineage(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract core company-report metrics with table/evidence lineage."""

    standard = build_standard_financial_metrics(records)
    if standard.get("metric_count"):
        return standard

    rows: List[Dict[str, Any]] = []
    for record in [item for item in records if isinstance(item, dict)]:
        if str(record.get("source_type", "")).lower() != "financials":
            continue
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        symbol = str(record.get("symbol", ""))
        period = str(record.get("period", ""))
        metadata = dict(record.get("metadata", {})) if isinstance(record.get("metadata"), dict) else {}
        metrics = _coerce_metrics(record)
        table_id = _table_id(symbol=symbol, period=period, evidence_id=evidence_id, table_type="financial_metrics")

        if metrics.get("revenue_billion") is not None:
            rows.append(
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
                )
            )
        if metrics.get("gross_margin_pct") is not None:
            rows.append(
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
                )
            )
        net_income = metrics.get("net_income_billion")
        formula = "reported net income"
        confidence = 0.95
        if net_income is None and metrics.get("revenue_billion") is not None and metrics.get("net_margin_pct") is not None:
            net_income = float(metrics["revenue_billion"]) * float(metrics["net_margin_pct"]) / 100.0
            formula = "revenue_billion * net_margin_pct / 100"
            confidence = 0.8
        if net_income is not None:
            rows.append(
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
                )
            )
        if metrics.get("free_cash_flow_billion") is not None:
            rows.append(
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
                )
            )

        if metadata.get("source_table_id"):
            for row in rows:
                if row["source_evidence_id"] == evidence_id:
                    row["source_table_id"] = str(metadata["source_table_id"])

    return {
        "metrics": rows,
        "metric_count": len(rows),
        "coverage": {
            "required_metrics": list(CORE_METRICS),
            "present_metrics": sorted({str(item["metric_name"]) for item in rows}),
            "has_core_metric_lineage": set(CORE_METRICS).issubset({str(item["metric_name"]) for item in rows}),
        },
    }


def build_financial_metric_tables(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build minimal table artifacts from existing three-statement rows."""

    standard_tables = build_standard_table_artifacts(records)
    if standard_tables:
        return standard_tables

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
    }


def _coerce_metrics(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(record.get("metadata", {})) if isinstance(record.get("metadata"), dict) else {}
    metrics = dict(metadata)
    for key in (
        "revenue_billion",
        "net_income_billion",
        "net_margin_pct",
        "gross_margin_pct",
        "free_cash_flow_billion",
    ):
        if key in record and key not in metrics:
            metrics[key] = record[key]

    content_metrics = _extract_content_metrics(record)
    for key, value in content_metrics.items():
        if key not in metrics or _safe_float(metrics.get(key)) is None:
            metrics[key] = value
    return {key: _safe_float(value) for key, value in metrics.items()}


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
