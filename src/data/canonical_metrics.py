"""Canonical metric selection for report generation and quality review."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any, Dict, Iterable, List

from src.utils.periods import period_match
from src.schemas.runtime_contracts import build_company_identity, build_period_spec, normalize_metric_candidate


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
    evidence_records: Any = None,
    symbol: str = "",
    period: str = "",
) -> Dict[str, Any]:
    """Choose one formal value for each metric from candidate metric/table rows."""

    candidates, rejected_candidates = _partition_period_candidates(
        _candidate_rows(
            financial_metrics=financial_metrics,
            tables=tables,
            evidence_records=evidence_records,
            symbol=symbol,
            target_period=period,
        ),
        period=period,
    )
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
        conflicting_losers = _value_conflicts(winner, losers)
        if conflicting_losers:
            resolution_status, resolution_reason = _conflict_resolution(winner, conflicting_losers)
            conflicts.append(
                {
                    "metric_name": metric_name,
                    "winner": _compact_candidate(winner),
                    "losers": [_compact_candidate(row) for row in conflicting_losers[:5]],
                    "conflict_type": "multi_source_value_mismatch",
                    "resolution_status": resolution_status,
                    "resolution_reason": resolution_reason,
                }
            )

    derived_metrics = _build_derived_metrics(canonical)
    missing_core = sorted(CORE_CANONICAL_METRICS - set(canonical))
    unresolved_conflicts = [item for item in conflicts if item.get("resolution_status") == "unresolved"]
    return {
        "schema_version": "canonical_metrics.v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "period": period,
        "company_identity": build_company_identity(symbol),
        "period_spec": build_period_spec(period, source_period=period),
        "metric_count": len(canonical),
        "candidate_count": len(candidates),
        "rejected_candidate_count": len(rejected_candidates),
        "rejected_candidates": rejected_candidates,
        "canonical_metrics": canonical,
        "derived_metrics": derived_metrics,
        "metrics": list(canonical.values()),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "resolved_conflict_count": len(conflicts) - len(unresolved_conflicts),
        "unresolved_conflict_count": len(unresolved_conflicts),
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
    evidence_records: Any = None,
    symbol: str = "",
    period: str = "",
) -> dict[str, Any]:
    artifact = build_canonical_metrics_artifact(
        financial_metrics=financial_metrics,
        tables=tables,
        evidence_records=evidence_records,
        symbol=symbol,
        period=period,
    )
    path = Path(output_dir) / "canonical_metrics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return artifact


def canonical_metrics_as_financial_metrics(artifact: Any, fallback: Any | None = None) -> Any:
    """Return a legacy financial_metrics-shaped payload backed by canonical winners."""

    if not isinstance(artifact, dict):
        return fallback if fallback is not None else {}
    metrics = artifact.get("metrics")
    if not isinstance(metrics, list):
        canonical = artifact.get("canonical_metrics") if isinstance(artifact.get("canonical_metrics"), dict) else {}
        metrics = list(canonical.values())
    if not metrics:
        return fallback if fallback is not None else {"metrics": [], "metric_count": 0}
    output = dict(fallback) if isinstance(fallback, dict) else {}
    output["metrics"] = [dict(item) for item in metrics if isinstance(item, dict)]
    derived = artifact.get("derived_metrics") if isinstance(artifact.get("derived_metrics"), dict) else {}
    output["metrics"].extend(dict(item) for item in derived.values() if isinstance(item, dict))
    output["metric_count"] = len(output["metrics"])
    output["canonical_source"] = "canonical_metrics.json"
    output["canonical_conflicts"] = list(artifact.get("conflicts") or []) if isinstance(artifact.get("conflicts"), list) else []
    output["coverage"] = dict(artifact.get("coverage") or {}) if isinstance(artifact.get("coverage"), dict) else {}
    return output


def _build_derived_metrics(canonical: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    specs = {
        "net_margin": ("net_income", "revenue", "net_income / revenue * 100"),
        "return_on_assets": ("net_income", "total_assets", "net_income / total_assets * 100"),
        "free_cash_flow_conversion": ("free_cash_flow", "net_income", "free_cash_flow / net_income * 100"),
        "liability_to_assets": ("total_liabilities", "total_assets", "total_liabilities / total_assets * 100"),
    }
    output: dict[str, dict[str, Any]] = {}
    for metric_name, (numerator_name, denominator_name, formula) in specs.items():
        numerator = canonical.get(numerator_name)
        denominator = canonical.get(denominator_name)
        if not isinstance(numerator, dict) or not isinstance(denominator, dict):
            continue
        numerator_value = _normalized_metric_value(numerator)
        denominator_value = _normalized_metric_value(denominator)
        if numerator_value is None or denominator_value in (None, 0):
            continue
        input_metric_ids = [
            str(row.get("metric_id") or row.get("metric_name") or name)
            for name, row in ((numerator_name, numerator), (denominator_name, denominator))
        ]
        source_evidence_ids = list(
            dict.fromkeys(
                str(row.get("source_evidence_id") or "")
                for row in (numerator, denominator)
                if str(row.get("source_evidence_id") or "")
            )
        )
        output[metric_name] = {
            "metric_name": metric_name,
            "value": round(numerator_value / denominator_value * 100.0, 4),
            "unit": "pct",
            "period": str(numerator.get("period") or denominator.get("period") or ""),
            "source_type": "derived_metric",
            "calculation_formula": formula,
            "input_metric_names": [numerator_name, denominator_name],
            "input_metric_ids": input_metric_ids,
            "source_evidence_ids": source_evidence_ids,
            "lineage": {
                "formula": formula,
                "inputs": [
                    _derived_input(numerator_name, numerator),
                    _derived_input(denominator_name, denominator),
                ],
            },
        }
    return output


def _derived_input(metric_name: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "metric_id": row.get("metric_id"),
        "value": row.get("value"),
        "unit": row.get("unit"),
        "source_evidence_id": row.get("source_evidence_id"),
        "source_table_id": row.get("source_table_id"),
    }


def _normalized_metric_value(row: dict[str, Any]) -> float | None:
    value = _float_or_none(row.get("value"))
    if value is None:
        return None
    unit = str(row.get("unit") or "").lower()
    if unit.endswith("_trillion"):
        return value * 1_000_000_000_000
    if unit.endswith("_billion"):
        return value * 1_000_000_000
    if unit.endswith("_million"):
        return value * 1_000_000
    if unit.endswith("_thousand"):
        return value * 1_000
    return value


def _candidate_rows(
    *,
    financial_metrics: Any,
    tables: Any,
    evidence_records: Any = None,
    symbol: str = "",
    target_period: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in _metric_rows(financial_metrics):
        candidate = _normalize_candidate(metric, symbol=symbol, target_period=target_period)
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
            candidate = _normalize_candidate(merged, symbol=symbol, target_period=target_period)
            if candidate:
                rows.append(candidate)
    rows.extend(
        _structured_evidence_candidates(
            evidence_records,
            symbol=symbol,
            target_period=target_period,
        )
    )
    return rows


def _structured_evidence_candidates(
    evidence_records: Any,
    *,
    symbol: str,
    target_period: str,
) -> list[dict[str, Any]]:
    """Extract period-matched statement values embedded in evidence metadata."""

    output: list[dict[str, Any]] = []
    for record in evidence_records if isinstance(evidence_records, list) else []:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        financials = metadata.get("financials") if isinstance(metadata.get("financials"), dict) else {}
        if not financials:
            continue
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        source_type = str(record.get("source_type") or "").lower()
        source_quality = metadata.get("source_quality") if isinstance(metadata.get("source_quality"), dict) else {}
        currency = str(metadata.get("currency") or record.get("currency") or _default_currency(symbol))
        common = {
            "symbol": symbol or str(record.get("symbol") or ""),
            "period": str(record.get("period") or target_period),
            "source_period": str(metadata.get("target_period") or record.get("period") or target_period),
            "source_type": source_type,
            "source_url": str(record.get("source_url") or ""),
            "source_evidence_id": evidence_id,
            "source_authority": str(source_quality.get("source_authority") or ""),
            "authority_level": str(source_quality.get("authority_level") or ""),
            "authority_score": float(source_quality.get("authority_score") or 0.0),
            "trust_level": str(source_quality.get("trust_level") or ""),
            "source_document_type": str(source_quality.get("source_document_type") or ""),
            "currency": currency,
            "confidence": 0.82 if source_type in {"market_api", "market_data"} else 0.9,
        }
        income = _period_statement_row(financials, ("income_history", "quarterly_income_history"), target_period)
        balance = _period_statement_row(financials, ("balance_history", "quarterly_balance_history"), target_period)
        cashflow = _period_statement_row(financials, ("cashflow_history", "quarterly_cashflow_history"), target_period)
        revenue = _first_number(income, ("Total Revenue", "Operating Revenue", "revenue"))
        net_income = _first_number(income, ("Net Income", "Net Income Common Stockholders"))
        gross_profit = _first_number(income, ("Gross Profit",))
        values = {
            "revenue": revenue,
            "net_income": net_income,
            "gross_margin": (gross_profit / revenue * 100.0) if gross_profit is not None and revenue not in (None, 0) else None,
            "total_assets": _first_number(balance, ("Total Assets",)),
            "total_liabilities": _first_number(balance, ("Total Liabilities Net Minority Interest", "Total Liabilities")),
            "cash_and_equivalents": _first_number(balance, ("Cash And Cash Equivalents",)),
            "operating_cash_flow": _first_number(
                cashflow,
                ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
            ),
            "free_cash_flow": _first_number(cashflow, ("Free Cash Flow",)),
        }
        report_date = str(income.get("end_date") or balance.get("end_date") or cashflow.get("end_date") or "")
        for metric_name, raw_value in values.items():
            if raw_value is None:
                continue
            is_ratio = metric_name == "gross_margin"
            candidate = _normalize_candidate(
                {
                    **common,
                    "metric_name": metric_name,
                    "value": raw_value if is_ratio else _to_billion(raw_value),
                    "unit": "pct" if is_ratio else f"{currency}_billion",
                    "report_date": report_date,
                },
                symbol=symbol,
                target_period=target_period,
            )
            if candidate:
                output.append(candidate)
    return output


def _period_statement_row(financials: dict[str, Any], keys: tuple[str, ...], target_period: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        value = financials.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    for row in rows:
        if period_match(period=target_period, report_date=str(row.get("end_date") or ""), raw=row) is True:
            return row
    return {}


def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _float_or_none(row.get(key))
        if value is not None:
            return value
    return None


def _to_billion(value: float) -> float:
    number = float(value)
    return number / 1_000_000_000 if abs(number) > 1_000_000 else number


def _default_currency(symbol: str) -> str:
    normalized = str(symbol or "").upper()
    if normalized.endswith(".HK"):
        return "HKD"
    if normalized.endswith((".SS", ".SZ")):
        return "CNY"
    return "USD"


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


def _normalize_candidate(
    row: dict[str, Any],
    *,
    symbol: str = "",
    target_period: str = "",
) -> dict[str, Any] | None:
    metric_name = str(row.get("metric_name") or row.get("metric_key") or row.get("line_item") or "").strip()
    value = _float_or_none(row.get("value"))
    if not metric_name or value is None:
        return None
    source_type = str(row.get("source_type") or "").lower()
    period_match = row.get("period_match")
    candidate = {
        "metric_name": metric_name,
        "value": value,
        "unit": str(row.get("unit") or ""),
        "currency": str(row.get("currency") or _currency_from_unit(row.get("unit")) or ""),
        "period": str(row.get("period") or ""),
        "source_period": str(row.get("source_period") or row.get("period") or ""),
        "period_match": period_match,
        "source_type": source_type,
        "source_url": str(row.get("source_url") or ""),
        "source_authority": str(row.get("source_authority") or ""),
        "authority_level": str(row.get("authority_level") or ""),
        "authority_score": float(row.get("authority_score") or 0.0),
        "source_document_type": str(row.get("source_document_type") or ""),
        "trust_level": str(row.get("trust_level") or ""),
        "source_evidence_id": str(row.get("source_evidence_id") or row.get("evidence_id") or row.get("source_id") or ""),
        "source_table_id": str(row.get("source_table_id") or ""),
        "report_date": str(row.get("report_date") or ""),
        "notice_date": str(row.get("notice_date") or ""),
        "confidence": float(row.get("confidence") or 0.0),
        "priority": SOURCE_PRIORITY.get(source_type, 99),
    }
    return normalize_metric_candidate(
        candidate,
        symbol=symbol or str(row.get("symbol") or ""),
        target_period=target_period or str(row.get("target_period") or row.get("period") or ""),
    )


def _partition_period_candidates(rows: list[dict[str, Any]], *, period: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        candidate = dict(row)
        match = candidate.get("period_match")
        if match is None:
            match = period_match(period=period, report_date=str(candidate.get("report_date") or ""), raw=candidate)
            candidate["period_match"] = match
        if match is False:
            rejected.append(
                {
                    "metric_name": candidate.get("metric_name"),
                    "source_type": candidate.get("source_type"),
                    "source_evidence_id": candidate.get("source_evidence_id"),
                    "source_table_id": candidate.get("source_table_id"),
                    "period": candidate.get("period"),
                    "source_period": candidate.get("source_period"),
                    "report_date": candidate.get("report_date"),
                    "reason": "period_mismatch",
                }
            )
            continue
        accepted.append(candidate)
    return accepted, rejected


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, int, float, str]:
    period_penalty = 0 if row.get("period_match") is not False else 50
    has_lineage_penalty = 0 if row.get("source_evidence_id") or row.get("source_table_id") else 10
    return (
        int(row.get("priority") or 99) + period_penalty + has_lineage_penalty,
        0 if row.get("period_match") is True else 1,
        -float(row.get("confidence") or 0.0),
        str(row.get("report_date") or row.get("notice_date") or ""),
    )


def _value_conflicts(winner: dict[str, Any], losers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    winner_value = _float_or_none(winner.get("value"))
    if winner_value is None:
        return []
    conflicts: list[dict[str, Any]] = []
    for loser in losers:
        loser_value = _float_or_none(loser.get("value"))
        if loser_value is None:
            continue
        tolerance = max(1.0, abs(winner_value) * 0.01)
        if abs(winner_value - loser_value) > tolerance:
            conflicts.append(loser)
    return conflicts


def _conflict_resolution(winner: dict[str, Any], losers: list[dict[str, Any]]) -> tuple[str, str]:
    """Distinguish auditable source differences from unresolved formal conflicts."""

    winner_priority = int(winner.get("priority") or 99)
    winner_currency = str(winner.get("currency") or "").upper()
    winner_unit = str(winner.get("unit") or "").lower()
    for loser in losers:
        loser_priority = int(loser.get("priority") or 99)
        loser_currency = str(loser.get("currency") or "").upper()
        loser_unit = str(loser.get("unit") or "").lower()
        if loser_priority <= winner_priority:
            return "unresolved", "conflicting candidate has equal or higher source authority"
        if winner_currency and loser_currency and winner_currency != loser_currency:
            return "unresolved", "conflicting candidates use different currencies"
        if winner_unit and loser_unit and winner_unit != loser_unit:
            return "unresolved", "conflicting candidates use different units or scales"
    return "resolved", "higher-authority canonical source selected over lower-priority candidates"


def _compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric_id": row.get("metric_id"),
        "value": row.get("value"),
        "unit": row.get("unit"),
        "source_type": row.get("source_type"),
        "source_evidence_id": row.get("source_evidence_id"),
        "source_table_id": row.get("source_table_id"),
        "period_match": row.get("period_match"),
        "confidence": row.get("confidence"),
        "authority": row.get("authority"),
        "period_spec": row.get("period_spec"),
        "lineage": row.get("lineage"),
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
