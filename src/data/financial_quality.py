"""Financial quality guardrails shared by analysis and valuation helpers."""

from __future__ import annotations

from typing import Any, Dict


DEFAULT_NON_RECURRING_THRESHOLD = 0.15

NORMALIZED_INCOME_KEYS = (
    "Normalized Income",
    "NormalizedIncome",
    "normalizedIncome",
    "normalized_income",
)
NORMALIZED_EBITDA_KEYS = (
    "Normalized EBITDA",
    "NormalizedEBITDA",
    "normalizedEbitda",
    "normalized_ebitda",
)
UNUSUAL_ITEM_KEYS = (
    "Total Unusual Items",
    "Total Unusual Items Excluding Goodwill",
    "TotalUnusualItems",
    "totalUnusualItems",
    "total_unusual_items",
)
GAIN_ON_SALE_KEYS = (
    "Gain On Sale Of Security",
    "Gain On Sale Of Securities",
    "GainOnSaleOfSecurity",
    "gainOnSaleOfSecurity",
    "gain_on_sale_of_security",
)


def build_net_income_quality_fields(
    raw: Dict[str, Any] | None = None,
    income_row: Dict[str, Any] | None = None,
    *,
    net_income: float | None = None,
    revenue: float | None = None,
    threshold: float = DEFAULT_NON_RECURRING_THRESHOLD,
) -> Dict[str, Any]:
    """Return adjusted-income fields for recurring-quality guardrails.

    Inputs and outputs use the same numeric unit as the supplied statement
    values. Callers can convert to billions or keep raw currency units.
    """

    merged: Dict[str, Any] = {}
    if isinstance(raw, dict):
        merged.update(raw)
    if isinstance(income_row, dict):
        merged.update(income_row)

    normalized_income = _first_number(merged, NORMALIZED_INCOME_KEYS)
    normalized_ebitda = _first_number(merged, NORMALIZED_EBITDA_KEYS)
    unusual_items = _first_number(merged, UNUSUAL_ITEM_KEYS)
    gain_on_sale = _first_number(merged, GAIN_ON_SALE_KEYS)
    non_recurring_gain = _first_present_number(unusual_items, gain_on_sale)

    adjusted_net_income = normalized_income
    adjustment_source = "normalized_income" if normalized_income is not None else ""
    if adjusted_net_income is None and net_income is not None and non_recurring_gain is not None:
        adjusted_net_income = float(net_income) - float(non_recurring_gain)
        adjustment_source = "net_income_minus_non_recurring_gain"
    if adjusted_net_income is None and net_income is not None and non_recurring_gain in (None, 0):
        adjusted_net_income = float(net_income)
        adjustment_source = "reported_net_income_no_material_adjustment"

    ratio = None
    if net_income not in (None, 0) and non_recurring_gain is not None:
        ratio = abs(float(non_recurring_gain)) / abs(float(net_income))

    requires_adjustment = ratio is not None and ratio >= threshold
    can_adjust = adjusted_net_income is not None
    valuation_usable = not requires_adjustment or can_adjust
    rejection_reason = ""
    if requires_adjustment and not can_adjust:
        rejection_reason = "non_recurring_gain_unadjusted"

    net_margin = None
    if revenue not in (None, 0) and adjusted_net_income is not None:
        net_margin = float(adjusted_net_income) / float(revenue) * 100.0

    quality_flag = "reported"
    if requires_adjustment and can_adjust:
        quality_flag = "adjusted_for_non_recurring_gain"
    elif requires_adjustment:
        quality_flag = "non_recurring_gain_unadjusted"
    elif non_recurring_gain is not None:
        quality_flag = "non_recurring_gain_not_material"

    return {
        "adjusted_net_income": adjusted_net_income,
        "normalized_income": normalized_income,
        "normalized_ebitda": normalized_ebitda,
        "non_recurring_gain": non_recurring_gain,
        "non_recurring_gain_ratio": ratio,
        "net_income_quality_flag": quality_flag,
        "valuation_input_usable": valuation_usable,
        "valuation_input_rejection_reason": rejection_reason,
        "adjustment_source": adjustment_source,
        "adjusted_net_margin_pct": net_margin,
    }


def _first_present_number(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _first_number(raw: Dict[str, Any], keys: tuple[str, ...]) -> float | None:
    lowered = {str(key).lower(): value for key, value in raw.items()}
    for key in keys:
        value = raw.get(key)
        number = _safe_float(value)
        if number is not None:
            return number
        number = _safe_float(lowered.get(key.lower()))
        if number is not None:
            return number
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip().lower() in {"", "nan", "none"}:
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None
