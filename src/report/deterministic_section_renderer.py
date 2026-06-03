"""Deterministic markdown-table renderer for report sections."""

from __future__ import annotations

from typing import Any


def render_peer_compare_table(peer_rows: list[dict[str, Any]]) -> str:
    return _render_table(
        headers=["公司", "收入增速", "毛利率", "净利率", "ROE", "P/E", "P/S"],
        rows=[
            [
                _format_text(_first_value(row, ("company_name", "company", "symbol"))),
                _format_percent(_first_value(row, ("revenue_growth_pct", "revenue_growth"))),
                _format_percent(_first_value(row, ("gross_margin_pct", "gross_margin"))),
                _format_percent(_first_value(row, ("net_margin_pct", "net_margin"))),
                _format_percent(_first_value(row, ("roe_pct", "roe"))),
                _format_multiple(_first_value(row, ("forward_pe", "trailing_pe", "pe_ratio"))),
                _format_multiple(_first_value(row, ("price_to_sales", "ps_ratio"))),
            ]
            for row in peer_rows
            if isinstance(row, dict)
        ],
    )


def render_valuation_table(
    valuation_model: dict[str, Any],
    currency_context: dict[str, Any] | None = None,
) -> str:
    if not isinstance(valuation_model, dict) or not valuation_model:
        return ""
    status = str(valuation_model.get("valuation_status") or valuation_model.get("error") or "").lower()
    if status in {"rough_observation_only", "blocked_due_to_incomplete_inputs"}:
        return ""
    if valuation_model.get("valuation_available") is False:
        return ""
    context = currency_context or {}
    statement_currency = str(context.get("statement_currency") or "").upper()
    trading_currency = str(context.get("trading_currency") or "").upper()
    official_status = str(context.get("official_source_status") or "")
    if statement_currency and trading_currency and statement_currency != trading_currency and not context.get("fx_rate"):
        return ""
    if official_status and official_status != "found":
        return ""

    methods = valuation_model.get("methods")
    if not isinstance(methods, list):
        methods = []
    if not methods:
        for key, label in [("dcf_value", "DCF"), ("pe_ratio", "P/E"), ("pb_ratio", "P/B"), ("ps_ratio", "P/S")]:
            if valuation_model.get(key) is None:
                continue
            methods.append(
                {
                    "method": label,
                    "assumption": valuation_model.get(f"{key}_assumption", ""),
                    "equity_value": valuation_model.get(key),
                    "per_share": valuation_model.get(f"{key}_per_share"),
                    "vs_market": valuation_model.get(f"{key}_vs_market", ""),
                }
            )

    return _render_table(
        headers=["估值方法", "核心假设", "权益价值", "每股价值", "相对市场"],
        rows=[
            [
                _format_text(method.get("method")),
                _format_text(method.get("key_assumption") or method.get("assumption"), max_len=90),
                _format_number(method.get("equity_value") or method.get("value")),
                _format_number(method.get("per_share")),
                _format_text(method.get("vs_market") or method.get("market_diff"), max_len=60),
            ]
            for method in methods
            if isinstance(method, dict)
        ],
    )


def render_sensitivity_table(sensitivity: dict[str, Any] | list[dict[str, Any]]) -> str:
    if isinstance(sensitivity, list):
        scenarios = sensitivity
    elif isinstance(sensitivity, dict):
        scenarios = sensitivity.get("scenarios") or sensitivity.get("cases") or sensitivity.get("rows") or []
    else:
        scenarios = []
    return _render_table(
        headers=["情景", "FCF 增长", "折现率", "估值", "变化"],
        rows=[
            [
                _format_text(item.get("name") or item.get("scenario") or item.get("case")),
                _format_percent(item.get("fcf_growth") or item.get("growth")),
                _format_percent(item.get("discount_rate") or item.get("wacc")),
                _format_number(item.get("dcf_value") or item.get("value")),
                _format_text(item.get("change") or item.get("delta") or item.get("change_vs_base"), max_len=40),
            ]
            for item in scenarios
            if isinstance(item, dict)
        ],
    )


def render_risk_table(risk_items: list[dict[str, Any]]) -> str:
    return _render_table(
        headers=["风险类别", "风险描述", "来源", "影响方向"],
        rows=[
            [
                _format_text(_first_value(item, ("category", "risk_title", "name")), max_len=40),
                _format_text(_first_value(item, ("description", "risk_description", "summary")), max_len=120),
                _format_text(_first_value(item, ("source", "evidence_source", "citation_title")), max_len=60),
                _format_text(_first_value(item, ("direction", "impact_level", "impact")), max_len=40),
            ]
            for item in risk_items
            if isinstance(item, dict)
        ],
    )


def render_financial_ratio_table(metrics: dict[str, Any]) -> str:
    if not isinstance(metrics, dict) or not metrics:
        return ""
    rows: list[list[str]] = []
    metric_items = metrics.get("metrics")
    if isinstance(metric_items, list):
        for item in metric_items[:14]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("metric_name") or item.get("name") or "")
            if name.lower() in {"adjusted_net_income", "non_recurring_gain", "revenue_growth_pct", "metric_count", "rejected_metric_count"}:
                continue
            if item.get("value") is None:
                continue
            rows.append([
                _metric_label(name),
                _format_number(item.get("value")),
                _format_text(item.get("period") or item.get("unit") or item.get("currency")),
            ])
    else:
        for key, value in metrics.items():
            lower_key = str(key).lower()
            if lower_key in {"metric_count", "rejected_metric_count", "rejected_metrics"}:
                continue
            if isinstance(value, (int, float)):
                rows.append([_metric_label(str(key)), _format_number(value), _metric_note(str(key))])
            elif isinstance(value, dict) and value.get("value") is not None:
                rows.append([
                    _metric_label(str(key)),
                    _format_number(value.get("value")),
                    _format_text(value.get("period") or value.get("unit") or value.get("currency")),
                ])
    return _render_table(headers=["指标", "数值", "说明"], rows=rows[:14])


def render_all_deterministic_blocks(
    peer_rows: list[dict[str, Any]] | None = None,
    valuation_model: dict[str, Any] | None = None,
    sensitivity: dict[str, Any] | list[dict[str, Any]] | None = None,
    risk_items: list[dict[str, Any]] | None = None,
    financial_metrics: dict[str, Any] | None = None,
) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for key, value in {
        "peer_compare": render_peer_compare_table(peer_rows or []),
        "valuation": render_valuation_table(valuation_model or {}),
        "valuation_sensitivity": render_sensitivity_table(sensitivity or {}),
        "risks": render_risk_table(risk_items or []),
        "financial_analysis": render_financial_ratio_table(financial_metrics or {}),
    }.items():
        if value:
            blocks[key] = value
    return blocks


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    clean_rows = []
    for row in rows:
        normalized = [str(cell or "-").replace("\n", " ").strip() or "-" for cell in row[: len(headers)]]
        if any(cell != "-" for cell in normalized):
            clean_rows.append([cell.replace("|", "\\|") for cell in normalized])
    if not headers or not clean_rows:
        return ""
    lines = [
        f"| {' | '.join(header.replace('|', '/').strip() for header in headers)} |",
        "|" + "|".join([" --- " for _ in headers]) + "|",
    ]
    lines.extend(f"| {' | '.join(row)} |" for row in clean_rows)
    return "\n".join(lines)


def _first_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = row.get(alias)
        if value not in (None, ""):
            return value
    return None


def _format_text(value: Any, max_len: int | None = None) -> str:
    if value in (None, ""):
        return "-"
    text = str(value).replace("\n", " ").strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text or "-"


def _format_number(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _format_text(value)
    if abs(number) >= 1e12:
        return f"{number / 1e12:.2f} 万亿"
    if abs(number) >= 1e8:
        return f"{number / 1e8:.2f} 亿"
    if abs(number) >= 1e4:
        return f"{number / 1e4:.2f} 万"
    return f"{number:.2f}"


def _format_percent(value: Any) -> str:
    if value in (None, ""):
        return "-"
    text = str(value).strip()
    if "%" in text:
        return text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _format_text(value)
    if -1 < number < 1:
        number *= 100
    return f"{number:.1f}%"


def _format_multiple(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return _format_text(value)


def _metric_label(key: str) -> str:
    mapping = {
        "revenue": "收入",
        "net_income": "净利润",
        "gross_profit": "毛利润",
        "gross_margin": "毛利率",
        "operating_income": "营业利润",
        "operating_margin": "营业利润率",
        "net_margin": "净利率",
        "total_assets": "总资产",
        "total_liabilities": "总负债",
        "total_equity": "股东权益",
        "equity": "股东权益",
        "operating_cash_flow": "经营现金流",
        "free_cash_flow": "自由现金流",
        "capex": "资本开支",
        "roe": "ROE",
        "roa": "ROA",
        "eps": "EPS",
        "pe_ratio": "P/E",
        "ps_ratio": "P/S",
        "pb_ratio": "P/B",
        "market_cap": "市值",
    }
    return mapping.get(key, key)


def _metric_note(key: str) -> str:
    notes = {
        "revenue_growth_pct": "收入同比增速",
        "adjusted_net_income": "调整后口径",
        "non_recurring_gain": "非经常性损益",
    }
    return notes.get(key, "-")
