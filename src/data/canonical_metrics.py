"""Canonical metric selection for report generation and quality review."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any, Dict, Iterable, List


CORE_CANONICAL_METRICS = {
    "revenue",
    "net_income",
    "gross_margin",
    "total_assets",
    "total_liabilities",
    "operating_cash_flow",
    "free_cash_flow",
    "cash_and_equivalents",
}

SOURCE_PRIORITY = {
    "sec_companyfacts": 10,
    "sec_filing": 12,
    "cninfo_announcement": 20,
    "hkex_announcement": 20,
    "pdf_statement_table": 25,
    "eastmoney_financials": 30,
    "financial_statement_metrics": 35,
    "third_party_structured": 40,
    "hk_financials": 50,
    "market_api": 60,
    "market_data": 60,
}


def build_canonical_metrics_artifact(
    *,
    financial_metrics: Any,
    tables: Any,
    symbol: str = "",
    period: str = "",
) -> Dict[str, Any]:
    """Choose one formal value for each metric from candidate metric/table rows."""

    candidates = _candidate_rows(financial_metrics=financial_metrics, tables=tables)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        metric = str(candidate.get("metric_name") or "").strip()
        if not metric:
            continue
        grouped.setdefault(metric, []).append(candidate)

    canonical: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for metric_name, rows in sorted(grouped.items()):
        ranked = sorted(rows, key=_candidate_sort_key)
        winner = dict(ranked[0])
        winner["canonical"] = True
        winner["selection_reason"] = _selection_reason(winner)
        canonical[metric_name] = winner
        losers = [dict(row) for row in ranked[1:]]
        if _has_value_conflict(winner, losers):
            conflicts.append(
                {
                    "metric_name": metric_name,
                    "winner": _compact_candidate(winner),
                    "losers": [_compact_candidate(row) for row in losers[:5]],
                    "conflict_type": "multi_source_value_mismatch",
                }
            )

    missing_core = sorted(CORE_CANONICAL_METRICS - set(canonical))
    return {
        "schema_version": "canonical_metrics.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "period": period,
        "metric_count": len(canonical),
        "candidate_count": len(candidates),
        "canonical_metrics": canonical,
        "metrics": list(canonical.values()),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "coverage": {
            "required_metrics": sorted(CORE_CANONICAL_METRICS),
            "present_metrics": sorted(canonical),
            "missing_core_metrics": missing_core,
            "has_core_metric_lineage": not missing_core,
        },
    }


def write_canonical_metrics_artifact(
    output_dir: str | Path,
    *,
    financial_metrics: Any,
    tables: Any,
    symbol: str = "",
    period: str = "",
) -> dict[str, Any]:
    artifact = build_canonical_metrics_artifact(
        financial_metrics=financial_metrics,
        tables=tables,
        symbol=symbol,
        period=period,
    )
    path = Path(output_dir) / "canonical_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return artifact


def _candidate_rows(*, financial_metrics: Any, tables: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in _metric_rows(financial_metrics):
        candidate = _normalize_candidate(metric)
        if candidate:
            rows.append(candidate)
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict):
            continue
        table_type = str(table.get("table_type") or table.get("statement") or "")
        for row in table.get("rows", []) if isinstance(table.get("rows"), list) else []:
            if not isinstance(row, dict):
                continue
            merged = dict(row)
            merged.setdefault("metric_name", row.get("metric_name") or row.get("line_item"))
            merged.setdefault("statement", row.get("statement") or table_type)
            merged.setdefault("source_table_id", table.get("table_id") or table.get("source_table_id"))
            merged.setdefault("source_evidence_id", table.get("source_evidence_id") or table.get("evidence_id"))
            merged.setdefault("source_type", row.get("source_type") or table.get("source_type"))
            merged.setdefault("unit", row.get("unit") or table.get("unit"))
            merged.setdefault("currency", row.get("currency") or table.get("currency"))
            candidate = _normalize_candidate(merged)
            if candidate:
                rows.append(candidate)
    return rows


def _metric_rows(financial_metrics: Any) -> list[dict[str, Any]]:
    if isinstance(financial_metrics, dict):
        raw_rows = financial_metrics.get("metrics")
        if isinstance(raw_rows, list):
            return [dict(item) for item in raw_rows if isinstance(item, dict)]
        output: list[dict[str, Any]] = []
        for key, value in financial_metrics.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("metric_name", key)
                output.append(row)
        return output
    if isinstance(financial_metrics, list):
        return [dict(item) for item in financial_metrics if isinstance(item, dict)]
    return []


def _normalize_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    metric_name = str(row.get("metric_name") or row.get("metric_key") or row.get("line_item") or "").strip()
    value = _float_or_none(row.get("value"))
    if not metric_name or value is None:
        return None
    source_type = str(row.get("source_type") or "").lower()
    period_match = row.get("period_match")
    return {
        "metric_name": metric_name,
        "value": value,
        "unit": str(row.get("unit") or ""),
        "currency": str(row.get("currency") or _currency_from_unit(row.get("unit")) or ""),
        "period": str(row.get("period") or ""),
        "source_period": str(row.get("source_period") or row.get("period") or ""),
        "period_match": period_match,
        "source_type": source_type,
        "source_evidence_id": str(row.get("source_evidence_id") or row.get("evidence_id") or row.get("source_id") or ""),
        "source_table_id": str(row.get("source_table_id") or ""),
        "report_date": str(row.get("report_date") or ""),
        "notice_date": str(row.get("notice_date") or ""),
        "confidence": float(row.get("confidence") or 0.0),
        "priority": SOURCE_PRIORITY.get(source_type, 99),
    }


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, int, float, str]:
    period_penalty = 0 if row.get("period_match") is not False else 50
    has_lineage_penalty = 0 if row.get("source_evidence_id") or row.get("source_table_id") else 10
    return (
        int(row.get("priority") or 99) + period_penalty + has_lineage_penalty,
        0 if row.get("period_match") is True else 1,
        -float(row.get("confidence") or 0.0),
        str(row.get("report_date") or row.get("notice_date") or ""),
    )


def _has_value_conflict(winner: dict[str, Any], losers: Iterable[dict[str, Any]]) -> bool:
    winner_value = _float_or_none(winner.get("value"))
    if winner_value is None:
        return False
    for loser in losers:
        loser_value = _float_or_none(loser.get("value"))
        if loser_value is None:
            continue
        tolerance = max(1.0, abs(winner_value) * 0.01)
        if abs(winner_value - loser_value) > tolerance:
            return True
    return False


def _compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": row.get("value"),
        "unit": row.get("unit"),
        "source_type": row.get("source_type"),
        "source_evidence_id": row.get("source_evidence_id"),
        "source_table_id": row.get("source_table_id"),
        "period_match": row.get("period_match"),
        "confidence": row.get("confidence"),
    }


def _selection_reason(row: dict[str, Any]) -> str:
    source = str(row.get("source_type") or "unknown")
    if row.get("period_match") is True:
        return f"selected highest-priority period-matched source: {source}"
    return f"selected highest-priority available source: {source}"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _currency_from_unit(value: Any) -> str:
    text = str(value or "")
    return text.split("_", 1)[0] if "_" in text else text
