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
    """Render report-facing charts plus a small audit appendix."""

    chart_dir = Path(output_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    charts: List[Dict[str, Any]] = []
    table_ids = _table_ids(tables or [])

    financial_rows, financial_claim_ids, financial_evidence_ids = _financial_statement_rows(claims)
    if financial_rows:
        path = render_table_chart(
            headers=["Metric", "Value", "Unit"],
            rows=financial_rows,
            output_path=chart_dir / "financial_performance_table.png",
            title="Financial Performance",
            width=1180,
        )
        charts.append(
            {
                "chart_id": "financial_performance_table",
                "chart_type": "table",
                "title": "核心财务表现",
                "output_path": str(path),
                "chart_category": "report",
                "source_fields": "claims.numeric_values",
                "input_table_ids": table_ids,
                "input_claim_ids": financial_claim_ids,
                "source_evidence_ids": financial_evidence_ids,
            }
        )

    profitability_points, profitability_claim_ids, profitability_evidence_ids = _profitability_points(claims)
    if profitability_points:
        path = render_bar_chart(
            bars=profitability_points[:5],
            output_path=chart_dir / "profitability_returns_bar.png",
            title="Profitability and Returns (%)",
        )
        charts.append(
            {
                "chart_id": "profitability_returns_bar",
                "chart_type": "bar",
                "title": "盈利能力与资本回报",
                "output_path": str(path),
                "chart_category": "report",
                "source_fields": "claims.numeric_values",
                "input_table_ids": table_ids,
                "input_claim_ids": profitability_claim_ids,
                "source_evidence_ids": profitability_evidence_ids,
                "chart_js": _chart_js_payload(chart_type="bar", points=profitability_points[:5], label="百分比"),
            }
        )

    valuation_points, valuation_claim_ids, valuation_evidence_ids = _valuation_market_points(claims)
    if valuation_points:
        path = render_bar_chart(
            bars=valuation_points,
            output_path=chart_dir / "valuation_market_compare_bar.png",
            title="Valuation vs Market Cap",
        )
        charts.append(
            {
                "chart_id": "valuation_market_compare_bar",
                "chart_type": "bar",
                "title": "估值对照：模型价值与市场市值",
                "output_path": str(path),
                "chart_category": "report",
                "source_fields": "claims.claim_text",
                "input_claim_ids": valuation_claim_ids,
                "source_evidence_ids": valuation_evidence_ids,
                "chart_js": _chart_js_payload(chart_type="bar", points=valuation_points, label="USD billion"),
            }
        )

    peer_rows, peer_claim_ids, peer_evidence_ids = _peer_table_rows(claims)
    if peer_rows:
        path = render_table_chart(
            headers=["Company", "Revenue(B)", "Rev growth(%)", "Net margin(%)", "ROE(%)", "FCF(B)"],
            rows=peer_rows[:8],
            output_path=chart_dir / "peer_comparison_table.png",
            title="Peer Comparison",
            width=1320,
        )
        charts.append(
            {
                "chart_id": "peer_comparison_table",
                "chart_type": "table",
                "title": "同行对比：核心指标",
                "output_path": str(path),
                "chart_category": "report",
                "source_fields": "claims.claim_text",
                "input_claim_ids": peer_claim_ids,
                "source_evidence_ids": peer_evidence_ids,
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
                "title": "附录：结论置信度",
                "output_path": str(path),
                "chart_category": "audit",
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
                "title": "附录：证据来源结构",
                "output_path": str(path),
                "chart_category": "audit",
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


def _financial_statement_rows(claims: List[Dict[str, Any]]) -> Tuple[List[List[str]], List[str], List[str]]:
    wanted = [
        ("revenue_billion", "Revenue"),
        ("net_income_billion", "Net income"),
        ("operating_cash_flow_billion", "Operating cash flow"),
        ("free_cash_flow_billion", "Free cash flow"),
        ("shareholder_equity_billion", "Shareholder equity"),
        ("total_assets_billion", "Total assets"),
    ]
    values, claim_ids, evidence_ids = _first_numeric_values_by_priority(
        claims=claims,
        keys=[key for key, _ in wanted],
        preferred_sections=["financial_statements", "executive_summary", "financial_analysis"],
    )
    rows = [
        [label, f"{values[key]:,.2f}", "USD billion"]
        for key, label in wanted
        if key in values
    ]
    return rows[:6], claim_ids, evidence_ids


def _profitability_points(claims: List[Dict[str, Any]]) -> Tuple[List[Tuple[str, float]], List[str], List[str]]:
    wanted = [
        ("gross_margin_pct", "Gross margin"),
        ("operating_margin_pct", "Operating margin"),
        ("net_margin_pct", "Net margin"),
        ("roe_pct", "ROE"),
        ("roa_pct", "ROA"),
    ]
    values, claim_ids, evidence_ids = _first_numeric_values_by_priority(
        claims=claims,
        keys=[key for key, _ in wanted],
        preferred_sections=["executive_summary", "financial_analysis", "financial_statements"],
    )
    points = [(label, values[key]) for key, label in wanted if key in values and values[key] >= 0]
    return points, claim_ids, evidence_ids


def _valuation_market_points(claims: List[Dict[str, Any]]) -> Tuple[List[Tuple[str, float]], List[str], List[str]]:
    values, claim_ids, evidence_ids = _first_numeric_values_by_priority(
        claims=claims,
        keys=["blended_equity_value_billion", "dcf_value_billion", "market_cap_billion"],
        preferred_sections=["valuation"],
    )
    points: List[Tuple[str, float]] = []
    if "blended_equity_value_billion" in values:
        points.append(("Model valuation", values["blended_equity_value_billion"]))
    if "dcf_value_billion" in values:
        points.append(("DCF valuation", values["dcf_value_billion"]))
    if "market_cap_billion" in values:
        points.append(("Market cap", values["market_cap_billion"]))
    return points, claim_ids, evidence_ids


def _peer_table_rows(claims: List[Dict[str, Any]]) -> Tuple[List[List[str]], List[str], List[str]]:
    for claim in claims:
        if not isinstance(claim, dict) or str(claim.get("section_name") or "") != "peer_compare":
            continue
        text = str(claim.get("claim_text") or "")
        rows: List[List[str]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not (line.startswith("|") and line.endswith("|")):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 6:
                continue
            if cells[0] in {"公司", "------"} or set(cells[0]) <= {"-"}:
                continue
            cells = [_ascii_cell(cell) for cell in cells]
            rows.append(cells[:6])
        if rows:
            return rows, _claim_ids([claim]), _evidence_ids_from_claims([claim])
    return [], [], []


def _first_numeric_values_by_priority(
    claims: List[Dict[str, Any]],
    keys: List[str],
    preferred_sections: List[str],
) -> Tuple[Dict[str, float], List[str], List[str]]:
    values: Dict[str, float] = {}
    claim_ids: List[str] = []
    evidence_ids: List[str] = []
    section_rank = {section: index for index, section in enumerate(preferred_sections)}
    ordered = sorted(
        [claim for claim in claims if isinstance(claim, dict)],
        key=lambda claim: (
            section_rank.get(str(claim.get("section_name") or ""), 999),
            -float(claim.get("confidence", 0.0) or 0.0),
        ),
    )
    for claim in ordered:
        numeric_values = claim.get("numeric_values", {}) if isinstance(claim, dict) else {}
        if not isinstance(numeric_values, dict):
            continue
        used_claim = False
        for key in keys:
            if key in values:
                continue
            value = numeric_values.get(key)
            parsed = _safe_float(value)
            if parsed is None:
                continue
            values[key] = parsed
            used_claim = True
        if used_claim:
            claim_id = str(claim.get("claim_id") or "")
            if claim_id and claim_id not in claim_ids:
                claim_ids.append(claim_id)
            for evidence_id in claim.get("evidence_ids", []):
                evidence_id = str(evidence_id)
                if evidence_id and evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
        if all(key in values for key in keys):
            break
    return values, claim_ids, evidence_ids


def _ascii_cell(value: Any) -> str:
    text = str(value).replace("◀", "<").strip()
    return text.encode("ascii", errors="ignore").decode("ascii") or "N/A"


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


def _metric_label(key: str, claim_id: str) -> str:
    labels = {
        "revenue_billion": "Revenue",
        "gross_margin_pct": "Gross margin",
        "operating_cash_flow_billion": "Operating cash flow",
        "net_income_billion": "Net income",
        "free_cash_flow_billion": "Free cash flow",
        "blended_equity_value_billion": "Blended equity value",
        "dcf_value_billion": "DCF value",
        "dcf_growth_down_billion": "DCF growth -2pct",
        "dcf_growth_up_billion": "DCF growth +2pct",
        "discount_rate_up_billion": "Discount rate +1pct",
    }
    cleaned = labels.get(key)
    if cleaned:
        return cleaned
    return f"{claim_id} {key}".replace("_", " ")
