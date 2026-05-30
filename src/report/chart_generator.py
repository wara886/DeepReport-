"""Chart generation for the multi-agent report path."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.charts.bar_chart import render_bar_chart
from src.charts.table_chart import render_table_chart


def generate_report_charts(
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    output_dir: str | Path,
    tables: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Render simple report charts directly from claims and evidence records."""

    chart_dir = Path(output_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    charts: List[Dict[str, Any]] = []
    table_ids = _table_ids(tables or [])

    metric_points = _metric_points_from_claims(claims)
    if metric_points:
        path = render_bar_chart(
            bars=metric_points[:8],
            output_path=chart_dir / "key_metrics_bar.png",
            title="Key Metrics",
        )
        charts.append(
            {
                "chart_id": "key_metrics_bar",
                "chart_type": "bar",
                "title": "关键指标",
                "section_name": "三表摘要",
                "output_path": str(path),
                "source_fields": "claims.numeric_values",
                "input_table_ids": table_ids,
                "input_claim_ids": _claim_ids_with_numeric_values(claims),
                "source_evidence_ids": _evidence_ids_from_claims(claims),
                "chart_js": _chart_js_payload(chart_type="bar", points=metric_points[:8], label="指标值"),
            }
        )

    confidence_points = _confidence_points_from_claims(claims)
    if confidence_points:
        path = render_bar_chart(
            bars=confidence_points[:10],
            output_path=chart_dir / "claim_confidence_bar.png",
            title="Claim Confidence",
        )
        charts.append(
            {
                "chart_id": "claim_confidence_bar",
                "chart_type": "bar",
                "title": "结论置信度",
                "section_name": "投资结论",
                "output_path": str(path),
                "source_fields": "claims.confidence",
                "input_claim_ids": _claim_ids(claims),
                "source_evidence_ids": _evidence_ids_from_claims(claims),
                "chart_js": _chart_js_payload(chart_type="bar", points=confidence_points[:10], label="置信度"),
            }
        )

    source_rows = _source_rows_from_evidence(evidence_records)
    if source_rows:
        path = render_table_chart(
            headers=["source_type", "count"],
            rows=source_rows,
            output_path=chart_dir / "evidence_source_mix.png",
            title="Evidence Source Mix",
        )
        charts.append(
            {
                "chart_id": "evidence_source_mix",
                "chart_type": "table",
                "title": "证据来源结构",
                "section_name": "执行摘要",
                "output_path": str(path),
                "source_fields": "evidence_records.source_type",
                "source_evidence_ids": _evidence_ids(evidence_records),
                "chart_js": _chart_js_payload(
                    chart_type="doughnut",
                    points=[(row[0], float(row[1])) for row in source_rows],
                    label="证据数量",
                ),
            }
        )

    return charts


def _metric_points_from_claims(claims: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
    points: List[Tuple[str, float]] = []
    for claim in claims:
        numeric_values = claim.get("numeric_values", {}) if isinstance(claim, dict) else {}
        if not isinstance(numeric_values, dict):
            continue
        claim_id = str(claim.get("claim_id") or f"claim_{len(points) + 1}")
        for key, value in numeric_values.items():
            parsed = _safe_float(value)
            if parsed is None:
                continue
            label = f"{claim_id}:{key}"[:28]
            points.append((label, parsed))
    return points


def _confidence_points_from_claims(claims: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
    points: List[Tuple[str, float]] = []
    for index, claim in enumerate(claims, start=1):
        parsed = _safe_float(claim.get("confidence") if isinstance(claim, dict) else None)
        if parsed is None:
            continue
        label = str(claim.get("claim_id") or f"cl_{index:04d}")
        points.append((label, max(0.0, min(parsed, 1.0))))
    return points


def _source_rows_from_evidence(evidence_records: List[Dict[str, Any]]) -> List[List[str]]:
    counter: Counter[str] = Counter()
    for item in evidence_records:
        if not isinstance(item, dict):
            continue
        counter[str(item.get("source_type") or "unknown")] += 1
    return [[source_type, str(count)] for source_type, count in counter.most_common()]


def _claim_ids(claims: List[Dict[str, Any]]) -> List[str]:
    return [str(claim.get("claim_id")) for claim in claims if isinstance(claim, dict) and str(claim.get("claim_id", "")).strip()]


def _claim_ids_with_numeric_values(claims: List[Dict[str, Any]]) -> List[str]:
    return [
        str(claim.get("claim_id"))
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("numeric_values"), dict) and claim.get("numeric_values")
    ]


def _evidence_ids_from_claims(claims: List[Dict[str, Any]]) -> List[str]:
    ids: List[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        ids.extend(str(item) for item in claim.get("evidence_ids", []) if str(item).strip())
    return sorted(set(ids))


def _evidence_ids(evidence_records: List[Dict[str, Any]]) -> List[str]:
    return sorted(
        {
            str(item.get("evidence_id") or item.get("sample_id") or "")
            for item in evidence_records
            if isinstance(item, dict) and str(item.get("evidence_id") or item.get("sample_id") or "").strip()
        }
    )


def _table_ids(tables: List[Dict[str, Any]]) -> List[str]:
    return sorted(
        {
            str(item.get("table_id", ""))
            for item in tables
            if isinstance(item, dict) and str(item.get("table_id", "")).strip()
        }
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _chart_js_payload(chart_type: str, points: List[Tuple[str, float]], label: str) -> Dict[str, Any]:
    return {
        "type": chart_type,
        "labels": [label for label, _ in points],
        "data": [value for _, value in points],
        "label": label,
    }
