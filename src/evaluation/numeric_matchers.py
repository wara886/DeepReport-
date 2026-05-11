"""Numeric matching and error taxonomy for numeric_audit_v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass
class MatchDecision:
    supported: bool
    error_type: str


def _is_close(expected: float, observed: float, abs_tol: float, rel_tol: float) -> bool:
    diff = abs(expected - observed)
    if diff <= abs_tol:
        return True
    base = max(abs(expected), 1e-9)
    return (diff / base) <= rel_tol


def _pick_candidates(metric: str, gold_facts: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    return [item for item in gold_facts if str(item.get("metric", "")) == metric]


def match_numeric_claim(
    claim: Dict[str, object],
    gold_facts: Iterable[Dict[str, object]],
    abs_tol: float = 0.2,
    rel_tol: float = 0.02,
) -> MatchDecision:
    """Classify one numeric claim against gold facts."""

    candidates = _pick_candidates(metric=str(claim.get("metric", "")), gold_facts=gold_facts)
    if not candidates:
        return MatchDecision(supported=False, error_type="hallucinated_number")

    claim_unit = str(claim.get("unit", ""))
    claim_period = str(claim.get("period", ""))
    claim_value = claim.get("value")
    if claim_value is None:
        return MatchDecision(supported=False, error_type="unsupported_number")

    unit_matched = False
    period_matched = False
    for item in candidates:
        expected_unit = str(item.get("unit", ""))
        expected_period = str(item.get("period", ""))
        expected_value = item.get("value")
        if expected_unit == claim_unit:
            unit_matched = True
        if expected_period == claim_period:
            period_matched = True
        if expected_unit != claim_unit:
            continue
        if expected_period != claim_period:
            continue
        if expected_value is None:
            return MatchDecision(supported=False, error_type="unsupported_number")
        if _is_close(float(expected_value), float(claim_value), abs_tol=abs_tol, rel_tol=rel_tol):
            return MatchDecision(supported=True, error_type="none")
        return MatchDecision(supported=False, error_type="value_mismatch")

    if not unit_matched:
        return MatchDecision(supported=False, error_type="unit_mismatch")
    if not period_matched:
        return MatchDecision(supported=False, error_type="period_mismatch")
    return MatchDecision(supported=False, error_type="unsupported_number")

