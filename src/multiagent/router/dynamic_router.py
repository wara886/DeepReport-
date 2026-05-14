"""DynamicRouter: multi-source state-aware routing for gap rework decisions."""

from __future__ import annotations

from typing import Any, Dict, List

from src.multiagent.router.budget_guard import BudgetGuard, BudgetState
from src.multiagent.router.schema import RouterDecision, RouterInput


# Gap types with real executable owners (mirrors _supported_rework_owner in orchestrator)
_EXECUTABLE_GAP_OWNERS: Dict[str, str] = {
    "EVIDENCE_GAP": "research",
    "NUMERIC_GAP": "analyze",
    "CITATION_GAP": "research",
    "RISK_GAP": "risk",
    "PEER_GAP": "peer",
    "FORMAT_GAP": "final_answer",
    "SOURCE_CONFLICT": "adjudicator",
}

# Gap types that have no executable owner yet — explicit fallback, not silent fail
_UNSUPPORTED_GAP_TYPES = frozenset({"VALUATION_GAP", "COMPLIANCE_GAP", "SYMBOL_PERIOD_MISMATCH"})


class DynamicRouter:
    """
    Decides the next rework action based on open gaps, task board state,
    recent messages, execution history, and budget constraints.

    Reuses existing P1-B executor logic — does not re-implement agent execution.
    """

    def __init__(self, budget_guard: BudgetGuard | None = None):
        self.budget_guard = budget_guard or BudgetGuard()

    def decide(self, router_input: RouterInput) -> List[RouterDecision]:
        """
        Return a list of RouterDecisions for the current round.

        Each decision maps to one gap rework action. The caller executes them
        in order using the existing _execute_one_routed_gap_rework path.
        """
        decisions: List[RouterDecision] = []
        open_gaps = router_input.open_gaps
        if not open_gaps:
            decisions.append(RouterDecision(
                selected_action="stop",
                reason="no_open_gaps",
                stop_recommended=True,
            ))
            return decisions

        for gap in open_gaps:
            gap_id = str(gap.get("gap_id", ""))
            gap_type = str(gap.get("gap_type", ""))
            severity = str(gap.get("severity", "medium"))

            # Skip gaps that have already been dispatched too many times
            if not self.budget_guard.can_dispatch_gap(gap_id):
                decisions.append(RouterDecision(
                    selected_action="skip",
                    related_gap_ids=[gap_id],
                    reason=f"max_dispatches_per_gap_reached:{self.budget_guard.budget.per_gap_dispatch_count.get(gap_id, 0)}",
                    expected_effect="gap_left_unresolved_budget_exhausted",
                    fallback_used=True,
                ))
                continue

            # Skip gaps that were already dispatched to the same owner in this round
            owner_key = _EXECUTABLE_GAP_OWNERS.get(gap_type)
            if owner_key and owner_key in router_input.executed_agents_in_current_round:
                # Allow re-dispatch only if this gap has not been attempted yet
                gap_history = router_input.unresolved_gap_history.get(gap_id, [])
                if owner_key in gap_history:
                    decisions.append(RouterDecision(
                        selected_action="skip",
                        related_gap_ids=[gap_id],
                        reason=f"owner_already_dispatched_for_gap:{owner_key}",
                        expected_effect="avoid_redundant_dispatch",
                        fallback_used=True,
                    ))
                    continue

            if gap_type in _UNSUPPORTED_GAP_TYPES:
                decisions.append(RouterDecision(
                    selected_action="fallback",
                    related_gap_ids=[gap_id],
                    reason=f"unsupported_gap_type:{gap_type}",
                    expected_effect="gap_deferred_to_unified_final_rewrite_or_future_adjudicator",
                    fallback_used=True,
                    unsupported_gap_type=gap_type,
                ))
                continue

            if owner_key is None:
                decisions.append(RouterDecision(
                    selected_action="fallback",
                    related_gap_ids=[gap_id],
                    reason=f"no_executable_owner_for:{gap_type}",
                    expected_effect="gap_deferred_to_unified_final_rewrite",
                    fallback_used=True,
                ))
                continue

            decisions.append(RouterDecision(
                selected_action="execute",
                selected_agent=owner_key,
                selected_task_type=_task_type_for_owner(owner_key),
                related_gap_ids=[gap_id],
                reason=_build_reason(gap_type, gap_id, severity, router_input),
                expected_effect=_expected_effect(gap_type, owner_key),
                fallback_used=False,
            ))

        if not any(d.selected_action == "execute" for d in decisions):
            decisions.append(RouterDecision(
                selected_action="stop",
                reason="no_executable_actions_in_round",
                stop_recommended=True,
            ))

        return decisions

    def should_stop(self, router_input: RouterInput) -> bool:
        has_actionable = any(
            g.get("gap_type") in _EXECUTABLE_GAP_OWNERS
            and self.budget_guard.can_dispatch_gap(str(g.get("gap_id", "")))
            for g in router_input.open_gaps
        )
        return self.budget_guard.should_stop(has_actionable_gaps=has_actionable)

    def stop_reason(self) -> str:
        return self.budget_guard.stop_reason()


def _task_type_for_owner(owner_key: str) -> str:
    return {
        "research": "deep_researcher",
        "analyze": "deep_analyze",
        "risk": "risk",
        "peer": "peer",
        "final_answer": "final_answer",
        "adjudicator": "adjudicator",
    }.get(owner_key, owner_key)


def _build_reason(gap_type: str, gap_id: str, severity: str, router_input: RouterInput) -> str:
    history = router_input.unresolved_gap_history.get(gap_id, [])
    history_note = f" (previously attempted by: {', '.join(history)})" if history else ""
    return f"gap_type={gap_type} severity={severity} gap_id={gap_id}{history_note}"


def _expected_effect(gap_type: str, owner_key: str) -> str:
    effects = {
        "EVIDENCE_GAP": "increase_evidence_candidates_and_records",
        "NUMERIC_GAP": "repair_numeric_claims_and_analysis_artifacts",
        "CITATION_GAP": "supplement_evidence_for_citation_repair",
        "RISK_GAP": "add_risk_claims_from_risk_agent",
        "PEER_GAP": "add_peer_comparison_claims_and_evidence",
        "FORMAT_GAP": "repair_report_format_and_required_sections",
        "SOURCE_CONFLICT": "adjudicate_conflicting_claims_or_evidence",
    }
    return effects.get(gap_type, f"execute_{owner_key}_for_{gap_type}")
