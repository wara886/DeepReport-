"""Chart generation for the multi-agent report path."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple
import re

from src.charts.bar_chart import render_bar_chart
from src.charts.table_chart import render_table_chart
from src.report.mojibake_guard import looks_like_mojibake
from src.utils.money import CurrencyContext, build_currency_context

# Map internal metric keys to user-readable Chinese labels
METRIC_LABEL_MAP: Dict[str, str] = {
    "revenue_billion": "收入",
    "net_income_billion": "净利润",
    "total_assets_billion": "总资产",
    "total_liabilities_billion": "总负债",
    "cash_and_equivalents_billion": "现金及等价物",
    "operating_cash_flow_billion": "经营现金流",
    "free_cash_flow_billion": "自由现金流",
    "gross_margin_pct": "毛利率",
    "net_margin_pct": "净利率",
    "roe_pct": "ROE",
    "roa_pct": "ROA",
    "debt_to_equity": "资产负债率",
    "pe_ratio": "市盈率(P/E)",
    "pb_ratio": "市净率(P/B)",
    "revenue_growth_pct": "收入增长率",
    "net_income_growth_pct": "净利润增长率",
    "eps_basic": "基本每股收益",
    "eps_diluted": "稀释每股收益",
    "rd_expense_billion": "研发费用",
    "market_cap_billion": "总市值",
    "revenue": "收入",
    "net_income": "净利润",
    "assets": "总资产",
    "liabilities": "总负债",
    "equity": "权益",
    "operating_cash_flow": "经营现金流",
    "investing_cash_flow": "投资现金流",
    "financing_cash_flow": "筹资现金流",
}

# Fallback label map for raw metric keys not in METRIC_LABEL_MAP
FALLBACK_LABEL_MAP: Dict[str, str] = {
    "revenue": "收入",
    "net_income": "净利润",
    "total_assets": "总资产",
    "total_liabilities": "总负债",
    "operating_cash_flow": "经营现金流",
    "free_cash_flow": "自由现金流",
    "capex": "资本开支",
    "pe_ttm": "市盈率",
    "market_cap_trillion": "市值",
    "market_cap_billion": "市值",
    "revenue_growth_pct": "收入增长率",
    "gross_margin_pct": "毛利率",
    "net_margin_pct": "净利率",
    "roe_pct": "ROE",
    "evidence_source_mix": "证据来源结构",
    "financial_scale_bar": "财务规模",
    "profitability_bar": "盈利能力",
    "cash_flow_bar": "现金流",
    "valuation_bar": "估值指标",
    "claim_confidence_bar": "结论置信度",
    "sec_10k_filing": "SEC 10-K",
    "sec_10k_section": "SEC 10-K 章节",
    "sec_companyfacts": "SEC companyfacts",
    "yahoo_finance": "Yahoo Finance",
    "market_data": "行情数据",
    "fred_series": "FRED",
    "policy_release": "公开政策资料",
    "web_search": "公开网页",
    "local_evidence": "本地证据",
}

BANNED_LABEL_PATTERNS = [
    r'statement_line_item_count',
    r'cl_\d+',
    r'ev_\d+',
    r'claim_id',
    r'supported\s*metrics',
    r'pe_ttm',
    r'market_cap_trillion',
    r'revenue_growth_pct',
    r'gross_margin_pct',
    r'net_margin_pct',
    r'[\uFFFD]',
    r'[鐠缂閹锟]',
    r'[\ue000-\uf8ff]',
    r'(缁撹|璇佹嵁|鏉ユ簮|鎽樿)',
    r'[ÃÂÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]',
]

# Category assignment for each metric key 鈥?used to split mixed-unit charts
_METRIC_CATEGORY: Dict[str, str] = {
    "revenue_billion": "financial_scale",
    "net_income_billion": "financial_scale",
    "total_assets_billion": "financial_scale",
    "total_liabilities_billion": "financial_scale",
    "cash_and_equivalents_billion": "financial_scale",
    "operating_cash_flow_billion": "cash_flow",
    "free_cash_flow_billion": "cash_flow",
    "gross_margin_pct": "profitability",
    "net_margin_pct": "profitability",
    "roe_pct": "profitability",
    "roa_pct": "profitability",
    "debt_to_equity": "profitability",
    "pe_ratio": "valuation",
    "pb_ratio": "valuation",
    "revenue_growth_pct": "profitability",
    "net_income_growth_pct": "profitability",
    "eps_basic": "financial_scale",
    "eps_diluted": "financial_scale",
    "rd_expense_billion": "financial_scale",
    "market_cap_billion": "financial_scale",
    "revenue": "financial_scale",
    "net_income": "financial_scale",
    "assets": "financial_scale",
    "liabilities": "financial_scale",
    "equity": "financial_scale",
    "total_assets": "financial_scale",
    "total_liabilities": "financial_scale",
    "operating_cash_flow": "cash_flow",
    "investing_cash_flow": "cash_flow",
    "financing_cash_flow": "cash_flow",
}

CATEGORY_TITLES: Dict[str, str] = {
    "financial_scale": "财务规模",
    "profitability": "盈利能力",
    "cash_flow": "现金流",
    "valuation": "估值指标",
}


def generate_report_charts(
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    output_dir: str | Path,
    tables: List[Dict[str, Any]] | None = None,
    analysis_artifacts: Dict[str, Any] | None = None,
    include_diagnostic_charts: bool = False,
    currency_context: CurrencyContext | Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Render simple report charts directly from claims and evidence records."""

    chart_dir = Path(output_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    charts: List[Dict[str, Any]] = []
    table_ids = _table_ids(tables or [])
    artifacts = analysis_artifacts if isinstance(analysis_artifacts, dict) else {}
    display_context = _resolve_currency_context(currency_context, artifacts)

    # Split metric points by category to avoid mixing units (billions vs percentages)
    category_points = _categorize_metric_points(claims)
    for cat_key in ("financial_scale", "profitability", "cash_flow", "valuation"):
        points = category_points.get(cat_key, [])
        if not points:
            continue
        cat_title = CATEGORY_TITLES.get(cat_key, cat_key)
        chart_id = f"{cat_key}_bar"
        path = render_bar_chart(
            bars=points[:8],
            output_path=chart_dir / f"{chart_id}.png",
            title=cat_title,
        )
        charts.append({
            "chart_id": chart_id,
            "chart_type": "bar",
            "title": cat_title,
            "section_name": "三表摘要",
            "output_path": str(path),
            "source_fields": "claims.numeric_values",
            "input_table_ids": table_ids,
            "input_claim_ids": _claim_ids_with_numeric_values(claims),
            "source_evidence_ids": _evidence_ids_from_claims(claims),
            "chart_js": _chart_js_payload(chart_type="bar", points=points[:8], label=cat_title),
        })

    peer_points = _peer_points_from_artifacts(artifacts)
    if peer_points:
        title = "同业比较"
        path = render_bar_chart(
            bars=peer_points[:8],
            output_path=chart_dir / "peer_compare_bar.png",
            title=title,
        )
        charts.append({
            "chart_id": "peer_compare_bar",
            "chart_type": "bar",
            "title": title,
            "section_name": "同行对比",
            "output_path": str(path),
            "source_fields": "analysis_artifacts.peer_analysis.rows",
            "input_table_ids": table_ids,
            "source_evidence_ids": _evidence_ids_from_claims(claims),
            "chart_js": _chart_js_payload(chart_type="bar", points=peer_points[:8], label="净利率"),
        })

    sensitivity_points = _valuation_sensitivity_points(artifacts)
    if sensitivity_points:
        title = "估值敏感性"
        path = render_bar_chart(
            bars=sensitivity_points[:8],
            output_path=chart_dir / "valuation_sensitivity_bar.png",
            title=title,
        )
        charts.append({
            "chart_id": "valuation_sensitivity_bar",
            "chart_type": "bar",
            "title": title,
            "section_name": "估值敏感性",
            "output_path": str(path),
            "source_fields": "analysis_artifacts.valuation_sensitivity",
            "source_evidence_ids": _evidence_ids_from_claims(claims),
            "chart_js": _chart_js_payload(chart_type="bar", points=sensitivity_points[:8], label=title),
        })

    confidence_points = _confidence_points_from_claims(claims)
    if include_diagnostic_charts and confidence_points:
        path = render_bar_chart(
            bars=confidence_points[:10],
            output_path=chart_dir / "claim_confidence_bar.png",
            title="Claim Confidence",
        )
        charts.append(
            {
                "chart_id": "claim_confidence_bar",
                "diagnostic_only": True,
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
    if include_diagnostic_charts and source_rows:
        path = render_table_chart(
            headers=["source_type", "count"],
            rows=source_rows,
            output_path=chart_dir / "evidence_source_mix.png",
            title="Evidence Source Mix",
        )
        charts.append(
            {
                "chart_id": "evidence_source_mix",
                "diagnostic_only": True,
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

    # Sanitize chart payloads before returning
    charts = sanitize_chart_payloads(charts, currency_context=display_context)
    return charts


def normalize_financial_scale(
    chart: dict[str, Any],
    currency_context: CurrencyContext | None = None,
) -> dict[str, Any]:
    """Scale monetary charts using the report's market currency."""
    chart_id = str(chart.get("chart_id") or "")
    if chart_id not in {"financial_scale_bar", "cash_flow_bar"}:
        return chart
    chart_js = chart.get("chart_js", {}) if isinstance(chart.get("chart_js"), dict) else {}
    data = chart_js.get("data", []) if isinstance(chart_js.get("data"), list) else []
    if not data:
        return chart
    context = currency_context or build_currency_context()
    numeric = [float(v) for v in data if isinstance(v, (int, float))]
    if not numeric:
        return chart
    already_scaled = max(abs(v) for v in numeric) < 1_000_000
    raw_data = list(data)
    scaled = list(data) if already_scaled else [
        v / context.display_scale if isinstance(v, (int, float)) else v for v in data
    ]
    # Idempotent guard: if the chart already has currency metadata, do NOT
    # overwrite it — a second call (e.g. from html_report_generator's
    # _visible_user_charts with a default USD context) would corrupt the
    # unit label originally set with the correct market currency.
    if not already_scaled or not (chart_js.get("raw_currency") or chart_js.get("unit_label")):
        chart["chart_js"] = {
            **chart_js,
            "data": scaled,
            "raw_data": raw_data,
            "raw_currency": context.statement_currency,
            "display_currency": context.display_currency,
            "display_scale": context.display_scale,
            "unit_label": context.unit_label,
        }
    else:
        chart["chart_js"] = {
            **chart_js,
            "data": scaled,
            "raw_data": raw_data,
        }
    if chart_id == "cash_flow_bar":
        chart["title"] = "现金流"
    return chart


def sanitize_chart_payloads(
    charts: List[Dict[str, Any]],
    currency_context: CurrencyContext | None = None,
) -> List[Dict[str, Any]]:
    """Remove internal labels from chart payloads and drop charts with <2 valid points."""
    clean: List[Dict[str, Any]] = []
    for chart in charts:
        if isinstance(chart, dict):
            if chart.get("diagnostic_only") is True:
                clean.append(chart)
                continue
            chart = normalize_financial_scale(chart, currency_context=currency_context)
            chart_id = str(chart.get("chart_id") or "")
            title = _sanitize_chart_label(chart.get("title") or chart_id or "图表", 1)
            if title.startswith("指标 ") and chart_id:
                title = FALLBACK_LABEL_MAP.get(chart_id, title)
            chart["title"] = title
            chart["section_name"] = _sanitize_chart_label(chart.get("section_name") or "", 1)
        chart_js = chart.get("chart_js")
        if not isinstance(chart_js, dict):
            clean.append(chart)
            continue
        labels = chart_js.get("labels", [])
        data = chart_js.get("data", [])
        if not isinstance(labels, list) or not isinstance(data, list):
            clean.append(chart)
            continue
        filtered_labels: list = []
        filtered_data: list = []
        chart_id = str(chart.get("chart_id") or "")
        for index, (label, point) in enumerate(zip(labels, data), start=1):
            label_str = f"结论 {index}" if chart_id == "claim_confidence_bar" else _sanitize_chart_label(label, index)
            if not label_str:
                continue
            if any(re.search(pat, label_str, flags=re.IGNORECASE) for pat in BANNED_LABEL_PATTERNS):
                continue
            filtered_labels.append(label_str)
            filtered_data.append(point)
        # Drop chart if fewer than 2 valid points remain
        if len(filtered_labels) < 2:
            continue
        chart["chart_js"] = {
            **chart_js,
            "labels": filtered_labels,
            "data": filtered_data,
            "label": (
                chart.get("title")
                if _sanitize_chart_label(chart_js.get("label") or chart.get("title") or "指标", 1).startswith("指标 ")
                else _sanitize_chart_label(chart_js.get("label") or chart.get("title") or "指标", 1)
            ),
        }
        unit_label = chart_js.get("unit_label")
        if isinstance(unit_label, str) and unit_label:
            unit_clean = _sanitize_chart_label(unit_label, 1)
            if unit_clean.startswith("指标 ") and chart_id == "financial_scale_bar":
                unit_clean = (currency_context or build_currency_context()).unit_label
            chart["chart_js"]["unit_label"] = unit_clean
        clean.append(chart)
    return clean


def _sanitize_chart_label(label: Any, index: int = 1) -> str:
    text = str(label or "").strip()
    if not text:
        return f"指标 {index}"
    mapped = FALLBACK_LABEL_MAP.get(text) or METRIC_LABEL_MAP.get(text)
    if mapped:
        return mapped
    lowered = text.lower()
    mapped = FALLBACK_LABEL_MAP.get(lowered) or METRIC_LABEL_MAP.get(lowered)
    if mapped:
        return mapped
    if re.search(r'[\uFFFD]', text) or re.search(r'[鐠缂閹锟]', text) or _looks_like_mojibake(text):
        if "evidence" in lowered or "source" in lowered:
            return "证据来源结构"
        if "confidence" in lowered or "claim" in lowered:
            return f"结论 {index}"
        return f"指标 {index}"
    if re.search(r'^(?:cl|claim|ev)_?\d+', lowered):
        return f"结论 {index}"
    if re.search(r'^[a-z][a-z0-9_]+$', lowered):
        return FALLBACK_LABEL_MAP.get(lowered, "")
    return text


def _looks_like_mojibake(text: str) -> bool:
    return bool(
        looks_like_mojibake(text)
        or
        re.search(r'[ÃÂÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]', text)
        or re.search(r'[\ue000-\uf8ff]', text)
        or re.search(r'(缁撹|璇佹嵁|鏉ユ簮|鎽樿)', text)
    )


def _metric_points_from_claims(claims: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
    """Extract metric points with user-readable Chinese labels, aggregated by metric key."""
    # Aggregate values by metric key to avoid duplicate labels from overlapping claims
    aggregated: Dict[str, float] = {}
    for claim in claims:
        numeric_values = claim.get("numeric_values", {}) if isinstance(claim, dict) else {}
        if not isinstance(numeric_values, dict):
            continue
        for key, value in numeric_values.items():
            parsed = _safe_float(value)
            if parsed is None:
                continue
            label = METRIC_LABEL_MAP.get(key)
            if label is None:
                label = FALLBACK_LABEL_MAP.get(key, key)
            # If the same metric appears in multiple claims, take the first encountered value
            if label not in aggregated:
                aggregated[label] = parsed
    return list(aggregated.items())


def _categorize_metric_points(claims: List[Dict[str, Any]]) -> Dict[str, List[Tuple[str, float]]]:
    """Split metric points by category (financial_scale, profitability, cash_flow, valuation)."""
    categories: Dict[str, Dict[str, float]] = defaultdict(dict)
    for claim in claims:
        numeric_values = claim.get("numeric_values", {}) if isinstance(claim, dict) else {}
        if not isinstance(numeric_values, dict):
            continue
        for key, value in numeric_values.items():
            parsed = _safe_float(value)
            if parsed is None:
                continue
            label = METRIC_LABEL_MAP.get(key)
            if label is None:
                label = FALLBACK_LABEL_MAP.get(key, key)
            cat = _METRIC_CATEGORY.get(key, "financial_scale")
            # First-encountered wins per label within each category
            if label not in categories[cat]:
                categories[cat][label] = parsed
    return {cat: list(points.items()) for cat, points in categories.items()}


def _confidence_points_from_claims(claims: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
    points: List[Tuple[str, float]] = []
    for index, claim in enumerate(claims, start=1):
        parsed = _safe_float(claim.get("confidence") if isinstance(claim, dict) else None)
        if parsed is None:
            continue
        # Use claim title or truncated text instead of internal claim_id
        label = str(claim.get("title") or claim.get("claim") or claim.get("claim_text") or f"结论 {index}")[:20]
        label = _sanitize_chart_label(label, index)
        points.append((label, max(0.0, min(parsed, 1.0))))
    return points


def _source_rows_from_evidence(evidence_records: List[Dict[str, Any]]) -> List[List[str]]:
    counter: Counter[str] = Counter()
    for item in evidence_records:
        if not isinstance(item, dict):
            continue
        counter[str(item.get("source_type") or "unknown")] += 1
    return [[source_type, str(count)] for source_type, count in counter.most_common()]


def _peer_points_from_artifacts(artifacts: Dict[str, Any]) -> List[Tuple[str, float]]:
    peer_data = artifacts.get("peer_analysis") if isinstance(artifacts, dict) else {}
    peer_context = artifacts.get("peer_context") if isinstance(artifacts, dict) else {}
    rows = []
    if isinstance(peer_data, dict):
        rows = peer_data.get("rows") or peer_data.get("peer_rows") or []
    if (not rows) and isinstance(peer_context, dict):
        rows = peer_context.get("peer_rows") or []
    if not isinstance(rows, list):
        return []
    points: List[Tuple[str, float]] = []
    has_non_target = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("is_target") is not True:
            has_non_target = True
        label = str(row.get("company_name") or row.get("symbol") or "").strip()
        value = _safe_float(row.get("net_margin_pct") or row.get("gross_margin_pct") or row.get("roe_pct"))
        if label and value is not None:
            points.append((label[:16], value))
    return points if has_non_target and len(points) >= 2 else []


def _valuation_sensitivity_points(artifacts: Dict[str, Any]) -> List[Tuple[str, float]]:
    sensitivity = artifacts.get("valuation_sensitivity") if isinstance(artifacts, dict) else {}
    if not isinstance(sensitivity, dict):
        return []
    rows = sensitivity.get("sensitivity") or sensitivity.get("rows") or []
    if not rows and isinstance(sensitivity.get("scenario_values"), dict):
        rows = [
            {"scenario": key, **(value if isinstance(value, dict) else {"value": value})}
            for key, value in sensitivity["scenario_values"].items()
        ]
    if not isinstance(rows, list):
        return []
    points: List[Tuple[str, float]] = []
    for index, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            label = str(row.get("label") or row.get("scenario") or row.get("assumption") or f"情景 {index}")
            value = _safe_float(row.get("target_price") or row.get("equity_value_billion") or row.get("value"))
        else:
            label = f"情景 {index}"
            value = _safe_float(row)
        if value is not None:
            points.append((_sanitize_chart_label(label, index), value))
    return points if len(points) >= 2 else []


def _resolve_currency_context(
    value: CurrencyContext | Dict[str, Any] | None,
    artifacts: Dict[str, Any],
) -> CurrencyContext:
    if isinstance(value, CurrencyContext):
        return value
    audit = artifacts.get("currency_audit") if isinstance(artifacts.get("currency_audit"), dict) else {}
    source = value if isinstance(value, dict) else audit
    return build_currency_context(
        symbol=str(source.get("symbol") or artifacts.get("symbol") or ""),
        market=str(source.get("market") or ""),
        statement_currency=str(source.get("statement_currency") or ""),
        display_currency=str(source.get("display_currency") or ""),
    )


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
