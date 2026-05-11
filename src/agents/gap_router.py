"""Route structured evidence gaps to remediation actions."""

from __future__ import annotations

from typing import Any, Dict, List


def route_evidence_gap(gap: Dict[str, Any]) -> Dict[str, Any]:
    gap_type = str(gap.get("gap_type", ""))
    if gap_type in {"missing_primary_evidence", "missing_evidence"}:
        return {"route": "research_browser", "action": "collect_or_refresh_evidence"}
    if gap_type == "valuation_formula_error":
        return {"route": "deep_analyze", "action": "recompute_valuation"}
    if gap_type == "multimodal_conflict":
        return {"route": "final_answer", "action": "regenerate_chart_table_links"}
    if gap_type == "entity_or_period_mismatch":
        return {"route": "deep_analyze", "action": "realign_entity_period"}
    return {"route": "final_answer", "action": "revise_language"}


def build_gap_resolution_trace(
    gaps: List[Dict[str, Any]],
    max_attempts_per_gap: int = 1,
) -> List[Dict[str, Any]]:
    trace: List[Dict[str, Any]] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        route = route_evidence_gap(gap)
        status = "queued" if gap.get("blocking", True) else "not_blocking"
        trace.append(
            {
                "gap_id": str(gap.get("gap_id", "")),
                "gap_type": str(gap.get("gap_type", "")),
                "claim_id": str(gap.get("claim_id", "")),
                "route": route["route"],
                "action": route["action"],
                "attempt": 0,
                "max_attempts": max_attempts_per_gap,
                "status": status,
            }
        )
    return trace
