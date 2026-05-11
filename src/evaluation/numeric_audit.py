"""numeric_audit_v1 for key financial numbers."""

from __future__ import annotations

from typing import Dict, Iterable, List

from src.evaluation.numeric_extract import extract_gold_numeric_facts, extract_numeric_claims
from src.evaluation.numeric_matchers import match_numeric_claim


ERROR_TYPES = [
    "value_mismatch",
    "unit_mismatch",
    "period_mismatch",
    "unsupported_number",
    "hallucinated_number",
]


def run_numeric_audit_for_case(
    case: Dict[str, object],
    report_claims: Iterable[Dict[str, object]],
    abs_tol: float = 0.2,
    rel_tol: float = 0.02,
) -> Dict[str, object]:
    """Audit one case against canonical metrics: revenue/net_income/yoy/gross_margin."""

    case_id = str(case.get("case_id", ""))
    period = str(case.get("period", ""))
    numeric_claims = [x.to_dict() for x in extract_numeric_claims(case_id=case_id, period=period, claims=report_claims)]
    gold_facts = extract_gold_numeric_facts(case)

    error_breakdown = {k: 0 for k in ERROR_TYPES}
    supported = 0
    detail_rows: List[Dict[str, object]] = []
    for claim in numeric_claims:
        decision = match_numeric_claim(claim=claim, gold_facts=gold_facts, abs_tol=abs_tol, rel_tol=rel_tol)
        if decision.supported:
            supported += 1
        else:
            error_breakdown[decision.error_type] = error_breakdown.get(decision.error_type, 0) + 1
        detail_rows.append(
            {
                **claim,
                "supported": decision.supported,
                "error_type": decision.error_type,
            }
        )

    total = len(numeric_claims)
    unsupported = total - supported
    return {
        "case_id": case_id,
        "numeric_claims": total,
        "supported_numeric_claims": supported,
        "unsupported_numeric_claims": unsupported,
        "error_breakdown": error_breakdown,
        "details": detail_rows,
    }


def summarize_numeric_audit(results: Iterable[Dict[str, object]]) -> Dict[str, object]:
    """Aggregate per-case numeric audit result list."""

    rows = list(results)
    total_claims = sum(int(x.get("numeric_claims", 0)) for x in rows)
    total_supported = sum(int(x.get("supported_numeric_claims", 0)) for x in rows)
    total_unsupported = sum(int(x.get("unsupported_numeric_claims", 0)) for x in rows)
    breakdown = {k: 0 for k in ERROR_TYPES}
    for row in rows:
        data = dict(row.get("error_breakdown", {}))
        for key in breakdown:
            breakdown[key] += int(data.get(key, 0))

    return {
        "case_count": len(rows),
        "numeric_claims": total_claims,
        "supported_numeric_claims": total_supported,
        "unsupported_numeric_claims": total_unsupported,
        "numeric_accuracy": round(float(total_supported) / float(total_claims), 4) if total_claims else 0.0,
        "grounded_rate": round(float(total_supported) / float(total_supported + total_unsupported), 4)
        if (total_supported + total_unsupported)
        else 0.0,
        "error_breakdown": breakdown,
    }

