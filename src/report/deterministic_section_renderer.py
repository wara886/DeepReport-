"""Deterministic markdown table renderer for report sections."""

from __future__ import annotations

import re
from typing import Any


def render_peer_compare_table(peer_rows: list[dict[str, Any]]) -> str:
    if not peer_rows:
        return ""
    headers = ["公司", "营收增长", "毛利率", "净利率", "ROE", "P/E", "P/S"]
    keys = [
        ("company", "company_name", "symbol", "公司"),
        ("revenue_growth", "revenue_growth_pct", "营收增长"),
        ("gross_margin", "gross_margin_pct", "毛利率"),
        ("net_margin", "net_margin_pct", "净利率"),
        ("roe", "roe_pct", "ROE"),
        ("pe_ratio", "forward_pe", "trailing_pe", "P/E"),
        ("ps_ratio", "price_to_sales", "P/S"),
    ]
    rows: list[list[str]] = []
    for row in peer_rows[:8]:
        if not isinstance(row, dict):
            continue
        values = []
        for aliases in keys:
            value = _first_value(row, aliases)
            values.append(_format_cell(value, aliases[0]))
        if any(value != "-" for value in values):
            rows.append(values)
    return _markdown_table(headers, rows)


def render_valuation_table(valuation_model: dict[str, Any], currency_context: dict[str, Any] | None = None) -> str:
    if not isinstance(valuation_model, dict) or not valuation_model:
        return ""
    # P0.8.2: Block valuation output when cross-currency without FX rate
    ctx = currency_context or {}
    stmt_ccy = str(ctx.get("statement_currency") or "").upper()
    trade_ccy = str(ctx.get("trading_currency") or "").upper()
    fx_rate = ctx.get("fx_rate")
    official = str(ctx.get("official_source_status") or "")
    is_cross = stmt_ccy and trade_ccy and stmt_ccy != trade_ccy
    if is_cross and not fx_rate:
        return ""  # block: CNY financials + HKD market cap, no FX → no P/E/P/S
    if official and official != "found":
        return ""  # block: no official source validation → no deterministic valuation
    methods = valuation_model.get("methods")
    if not isinstance(methods, list):
        methods = []
    if not methods:
        for key, label in [("dcf_value", "DCF"), ("pe_ratio", "P/E"), ("pb_ratio", "P/B"), ("ps_ratio", "P/S")]:
            if valuation_model.get(key) is not None:
                methods.append(
                    {
                        "method": label,
                        "key_assumption": valuation_model.get(f"{key}_assumption", ""),
                        "equity_value": valuation_model.get(key),
                        "per_share": valuation_model.get(f"{key}_per_share", ""),
                        "vs_market": valuation_model.get(f"{key}_vs_market", ""),
                    }
                )
    rows = []
    for method in methods[:6]:
        if not isinstance(method, dict):
            continue
        rows.append(
            [
                str(method.get("method") or "-"),
                str(method.get("key_assumption") or method.get("assumption") or "-")[:90],
                _format_number(method.get("equity_value", method.get("value"))),
                _format_number(method.get("per_share")),
                str(method.get("vs_market") or method.get("market_diff") or "-")[:60],
            ]
        )
    return _markdown_table(["估值方法", "核心假设", "股权价值/倍数", "每股价值", "与市场差异"], rows)


def render_sensitivity_table(sensitivity: dict[str, Any] | list[dict[str, Any]]) -> str:
    if isinstance(sensitivity, list):
        scenarios = sensitivity
    elif isinstance(sensitivity, dict):
        scenarios = sensitivity.get("scenarios") or sensitivity.get("cases") or sensitivity.get("rows") or []
    else:
        scenarios = []
    if not isinstance(scenarios, list):
        return ""
    rows = []
    for scenario in scenarios[:8]:
        if not isinstance(scenario, dict):
            continue
        rows.append(
            [
                str(scenario.get("name") or scenario.get("scenario") or scenario.get("case") or "-"),
                _format_percent(scenario.get("fcf_growth", scenario.get("growth"))),
                _format_percent(scenario.get("discount_rate", scenario.get("wacc"))),
                _format_number(scenario.get("dcf_value", scenario.get("value"))),
                str(scenario.get("change") or scenario.get("delta") or scenario.get("change_vs_base") or "-")[:40],
            ]
        )
    return _markdown_table(["情景", "FCF 增长", "折现率", "DCF 价值", "变化"], rows)


def render_risk_table(risk_items: list[dict[str, Any]]) -> str:
    if not risk_items:
        return ""
    rows = []
    for item in risk_items[:8]:
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                str(_first_value(item, ("category", "risk_title", "风险类别")) or "-")[:40],
                str(_first_value(item, ("description", "risk_description", "风险描述")) or "-")[:120],
                str(_first_value(item, ("source", "evidence_source", "证据来源")) or "-")[:60],
                str(_first_value(item, ("direction", "impact_level", "影响方向")) or "-")[:40],
            ]
        )
    return _markdown_table(["风险类别", "风险描述", "证据来源", "影响方向"], rows)


def render_financial_ratio_table(metrics: dict[str, Any]) -> str:
    if not isinstance(metrics, dict) or not metrics:
        return ""
    if isinstance(metrics.get("metrics"), list):
        rows = []
        for item in metrics["metrics"][:14]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("metric_name") or item.get("name") or "")
            if name.lower() in {"adjusted_net_income", "non_recurring_gain", "revenue_growth_pct", "metric_count", "rejected_metric_count"}:
                continue
            value = item.get("value")
            if not name or value is None:
                continue
            rows.append([_metric_label(name), _format_number(value), str(item.get("period") or item.get("unit") or item.get("currency") or "-")])
        return _markdown_table(["指标", "数值", "期间/单位"], rows)

    rows = []
    for key, value in metrics.items():
        if key in {"metric_count", "rejected_metric_count", "rejected_metrics"}:
            continue
        # P0.8.1: Map internal keys to Chinese labels instead of skipping
        if key.lower() in {"adjusted_net_income", "non_recurring_gain", "revenue_growth_pct"}:
            rows.append([_metric_label(str(key)), _format_number(value), _metric_note(str(key))])
            continue
        if isinstance(value, (int, float)):
            rows.append([_metric_label(str(key)), _format_number(value), _metric_note(str(key))])
        elif isinstance(value, dict):
            nested = value.get("value")
            if nested is not None:
                rows.append([_metric_label(str(key)), _format_number(nested), str(value.get("period") or value.get("unit") or "-")])
    return _markdown_table(["指标", "数值", "说明"], rows[:14])


def render_all_deterministic_blocks(
    peer_rows: list[dict[str, Any]] | None = None,
    valuation_model: dict[str, Any] | None = None,
    sensitivity: dict[str, Any] | list[dict[str, Any]] | None = None,
    risk_items: list[dict[str, Any]] | None = None,
    financial_metrics: dict[str, Any] | None = None,
) -> dict[str, str]:
    blocks: dict[str, str] = {}
    peer = render_peer_compare_table(peer_rows or [])
    if peer:
        blocks["peer_compare"] = peer
    valuation = render_valuation_table(valuation_model or {})
    if valuation:
        blocks["valuation"] = valuation
    sens = render_sensitivity_table(sensitivity or {})
    if sens:
        blocks["valuation_sensitivity"] = sens
    risks = render_risk_table(risk_items or [])
    if risks:
        blocks["risks"] = risks
    ratios = render_financial_ratio_table(financial_metrics or {})
    if ratios:
        blocks["financial_analysis"] = ratios
    return blocks


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    rows = [[_escape_cell(cell) for cell in row] for row in rows if any(str(cell).strip() and str(cell).strip() != "-" for cell in row)]
    if not headers or not rows:
        return ""
    lines = [f"| {' | '.join(headers)} |", f"|{'|'.join([' --- ' for _ in headers])}|"]
    lines.extend(f"| {' | '.join(row[: len(headers)])} |" for row in rows)
    return "\n".join(lines)


def _first_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = row.get(alias)
        if value not in (None, ""):
            return value
    return None


def _format_cell(value: Any, key: str) -> str:
    if value in (None, ""):
        return "-"
    if key in {"revenue_growth", "gross_margin", "net_margin", "roe"}:
        return _format_percent(value)
    if key in {"pe_ratio", "ps_ratio"}:
        try:
            return f"{float(value):.2f}x"
        except (TypeError, ValueError):
            return str(value)
    return _format_number(value)


def _format_number(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
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
    text = str(value)
    if "%" in text:
        return text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return text
    if -1 < number < 1:
        return f"{number * 100:.1f}%"
    return f"{number:.1f}%"


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
        # P0.8.1: Internal keys that leak to user reports
        "adjusted_net_income": "调整后净利润",
        "non_recurring_gain": "非经常性收益",
        "revenue_growth_pct": "收入增速",
        "gross_margin_pct": "毛利率",
        "net_margin_pct": "净利率",
        "roe_pct": "ROE",
        "pe_ttm": "市盈率",
        "ps_ttm": "市销率",
    }
    return mapping.get(key.lower(), key)


def _metric_note(key: str) -> str:
    notes = {
        "revenue": "主营业务收入规模",
        "net_income": "归母或可归属净利润",
        "gross_margin": "盈利能力指标",
        "free_cash_flow": "现金转化与资本开支后的结果",
        "operating_cash_flow": "经营活动现金流",
        "roe": "股东权益回报",
    }
    return notes.get(key.lower(), "-")


def _escape_cell(value: Any) -> str:
    text = str(value).replace("\n", " ").replace("|", "\\|").strip()
    text = re.sub(r"\s{2,}", " ", text)
    return text or "-"
