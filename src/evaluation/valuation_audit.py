"""Formula checks for reproducible valuation artifacts."""

from __future__ import annotations

from typing import Any, Dict, List


def audit_valuation_model(valuation: Dict[str, Any]) -> Dict[str, Any]:
    """Check relative valuation and DCF arithmetic."""

    errors: List[str] = []
    warnings: List[str] = []
    if not valuation or not valuation.get("valuation_available", False):
        return {"passed": True, "errors": [], "warnings": ["valuation_not_available"], "checks": {}}

    model = valuation.get("valuation_model") if isinstance(valuation.get("valuation_model"), dict) else {}
    relative = model.get("relative_valuation") if isinstance(model.get("relative_valuation"), dict) else valuation.get("relative_valuation", {})
    dcf = model.get("dcf_model") if isinstance(model.get("dcf_model"), dict) else valuation.get("dcf_model", {})
    sensitivity = valuation.get("valuation_sensitivity", {})

    _audit_relative(relative if isinstance(relative, dict) else {}, errors)
    _audit_dcf(dcf if isinstance(dcf, dict) else {}, errors, warnings)
    _audit_sensitivity(sensitivity if isinstance(sensitivity, dict) else {}, errors)
    _audit_scale_guardrails(valuation, relative if isinstance(relative, dict) else {}, dcf if isinstance(dcf, dict) else {}, errors, warnings)

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "has_relative_valuation": bool(relative),
            "has_dcf_model": bool(dcf),
            "has_sensitivity": bool(sensitivity),
        },
    }


def _audit_relative(relative: Dict[str, Any], errors: List[str]) -> None:
    multiples = relative.get("multiples") if isinstance(relative.get("multiples"), dict) else {}
    if not multiples:
        errors.append("missing_relative_multiples")
        return
    for name, item in multiples.items():
        if not isinstance(item, dict):
            continue
        denominator = _float(item.get("denominator_value"))
        multiple = _float(item.get("multiple"))
        value = _float(item.get("equity_value_billion"))
        if denominator is None or multiple is None or value is None:
            errors.append(f"{name}_multiple_missing_inputs")
            continue
        if abs(value - denominator * multiple) > max(abs(value) * 0.01, 0.05):
            errors.append(f"{name}_multiple_formula_error")


def _audit_dcf(dcf: Dict[str, Any], errors: List[str], warnings: List[str]) -> None:
    assumptions = dcf.get("assumptions") if isinstance(dcf.get("assumptions"), dict) else {}
    forecast = dcf.get("forecast") if isinstance(dcf.get("forecast"), list) else []
    discount_rate = _float(assumptions.get("discount_rate"))
    terminal_growth = _float(assumptions.get("terminal_growth"))
    if discount_rate is None or terminal_growth is None:
        errors.append("dcf_missing_discount_or_terminal_growth")
        return
    if discount_rate <= terminal_growth:
        errors.append("dcf_discount_rate_not_above_terminal_growth")
    if terminal_growth > 0.05:
        warnings.append("terminal_growth_above_default_guardrail")
    if discount_rate < 0.04:
        warnings.append("discount_rate_below_default_guardrail")
    pv_fcf = sum(_float(row.get("present_value_billion")) or 0.0 for row in forecast if isinstance(row, dict))
    pv_terminal = _float(dcf.get("pv_terminal_value_billion")) or 0.0
    enterprise_value = _float(dcf.get("enterprise_value_billion"))
    net_debt = _float(assumptions.get("net_debt_billion")) or 0.0
    equity_value = _float(dcf.get("equity_value_billion"))
    if enterprise_value is None or abs(enterprise_value - (pv_fcf + pv_terminal)) > max(abs(enterprise_value) * 0.01, 0.05):
        errors.append("dcf_enterprise_value_formula_error")
    if equity_value is None or enterprise_value is None or abs(equity_value - (enterprise_value - net_debt)) > max(abs(equity_value or 0.0) * 0.01, 0.05):
        errors.append("dcf_equity_value_formula_error")
    shares = _float(assumptions.get("shares_outstanding_billion"))
    target_price = _float(dcf.get("target_price"))
    if shares and target_price is not None and equity_value is not None:
        if abs(target_price - equity_value / shares) > max(abs(target_price) * 0.01, 0.05):
            errors.append("dcf_target_price_formula_error")


def _audit_sensitivity(sensitivity: Dict[str, Any], errors: List[str]) -> None:
    scenarios = sensitivity.get("scenario_values") if isinstance(sensitivity.get("scenario_values"), dict) else {}
    if not scenarios:
        errors.append("missing_valuation_sensitivity")
        return
    bear = _float((scenarios.get("bear") or {}).get("equity_value_billion"))
    base = _float((scenarios.get("base") or {}).get("equity_value_billion"))
    bull = _float((scenarios.get("bull") or {}).get("equity_value_billion"))
    if None not in (bear, base, bull) and not (bull >= base >= bear):
        errors.append("valuation_scenario_direction_error")


def _audit_scale_guardrails(
    valuation: Dict[str, Any],
    relative: Dict[str, Any],
    dcf: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> None:
    """Catch reproducible formulas that still produce unusable scales."""

    revenue = _float(
        ((relative.get("multiples") or {}).get("ps") or {}).get("denominator_value")
        if isinstance(relative.get("multiples"), dict)
        else None
    )
    blended = _float(valuation.get("blended_equity_value_billion"))
    dcf_value = _float(dcf.get("equity_value_billion") or dcf.get("enterprise_value_billion"))
    fcf = _float((dcf.get("assumptions") or {}).get("base_free_cash_flow_billion")) if isinstance(dcf.get("assumptions"), dict) else None
    if revenue and blended and blended / revenue > 80:
        errors.append("blended_value_to_revenue_above_guardrail")
    if revenue and dcf_value and dcf_value / revenue > 120:
        errors.append("dcf_value_to_revenue_above_guardrail")
    if fcf and dcf_value and dcf_value / fcf > 100:
        errors.append("dcf_value_to_fcf_above_guardrail")

    market_context = valuation.get("market_context") if isinstance(valuation.get("market_context"), dict) else {}
    market_cap = _float(market_context.get("market_cap_billion"))
    if market_cap and blended and abs((blended - market_cap) / market_cap) > 10:
        warnings.append("valuation_market_gap_above_1000pct")


def _float(value: Any) -> float | None:
    try:
        if value is None or str(value) == "nan":
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None
