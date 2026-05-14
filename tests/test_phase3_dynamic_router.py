"""Tests for DynamicRouter: multi-source state-aware routing for gap rework."""

from __future__ import annotations

from typing import Any, Dict, List

from src.multiagent.router import BudgetGuard, BudgetState, DynamicRouter, RouterDecision, RouterInput


def _router_input(
    open_gaps: List[Dict[str, Any]] | None = None,
    executed_agents: List[str] | None = None,
    unresolved_history: Dict[str, List[str]] | None = None,
) -> RouterInput:
    return RouterInput(
        open_gaps=open_gaps or [],
        executed_agents_in_current_round=list(executed_agents or []),
        unresolved_gap_history=dict(unresolved_history or {}),
    )


def _gap(gap_type: str, gap_id: str = "g1", severity: str = "medium") -> Dict[str, Any]:
    return {"gap_id": gap_id, "gap_type": gap_type, "severity": severity, "status": "open", "description": "test"}


def test_no_open_gaps_returns_stop():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[]))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "stop"
    assert d.stop_recommended is True
    assert d.reason == "no_open_gaps"


def test_evidence_gap_routes_to_research():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("EVIDENCE_GAP")]))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "execute"
    assert d.selected_agent == "research"
    assert d.selected_task_type == "deep_researcher"
    assert d.related_gap_ids == ["g1"]
    assert d.fallback_used is False


def test_numeric_gap_routes_to_analyze():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("NUMERIC_GAP")]))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "execute"
    assert d.selected_agent == "analyze"
    assert d.selected_task_type == "deep_analyze"


def test_citation_gap_routes_to_research():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("CITATION_GAP")]))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "execute"
    assert d.selected_agent == "research"


def test_risk_gap_routes_to_risk():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("RISK_GAP")]))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "execute"
    assert d.selected_agent == "risk"
    assert d.selected_task_type == "risk"


def test_peer_gap_routes_to_peer():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("PEER_GAP")]))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "execute"
    assert d.selected_agent == "peer"
    assert d.selected_task_type == "peer"


def test_format_gap_routes_to_final_answer():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("FORMAT_GAP")]))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "execute"
    assert d.selected_agent == "final_answer"
    assert d.selected_task_type == "final_answer"


def test_unsupported_gap_type_uses_fallback():
    """VALUATION_GAP, COMPLIANCE_GAP, SYMBOL_PERIOD_MISMATCH 仍是 unsupported。
    SOURCE_CONFLICT 已在 Phase 4 移入 executable owners，不再 fallback。"""
    router = DynamicRouter()
    for gap_type in ("VALUATION_GAP", "COMPLIANCE_GAP", "SYMBOL_PERIOD_MISMATCH"):
        decisions = router.decide(_router_input(open_gaps=[_gap(gap_type)]))
        fallbacks = [d for d in decisions if d.selected_action == "fallback"]
        assert len(fallbacks) == 1, f"Expected 1 fallback for {gap_type}, got {[d.selected_action for d in decisions]}"
        assert fallbacks[0].fallback_used is True
        assert fallbacks[0].unsupported_gap_type == gap_type


def test_source_conflict_routes_to_adjudicator():
    """Phase 4: SOURCE_CONFLICT 现在有真实执行者 adjudicator。"""
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("SOURCE_CONFLICT")]))
    executes = [d for d in decisions if d.selected_action == "execute"]
    assert len(executes) == 1
    assert executes[0].selected_agent == "adjudicator"
    assert executes[0].selected_task_type == "adjudicator"
    assert executes[0].fallback_used is False


def test_unknown_gap_type_uses_fallback():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("MADE_UP_GAP")]))
    fallbacks = [d for d in decisions if d.selected_action == "fallback"]
    assert len(fallbacks) == 1
    assert fallbacks[0].fallback_used is True


def test_max_dispatches_per_gap_skips():
    budget = BudgetGuard(BudgetState(max_dispatches_per_gap=1))
    budget.record_dispatch(gap_id="g1")
    router = DynamicRouter(budget_guard=budget)
    decisions = router.decide(_router_input(open_gaps=[_gap("EVIDENCE_GAP", gap_id="g1")]))
    skips = [d for d in decisions if d.selected_action == "skip"]
    assert len(skips) == 1
    assert "max_dispatches_per_gap_reached" in skips[0].reason


def test_skip_when_owner_already_dispatched_for_gap():
    router = DynamicRouter()
    decisions = router.decide(_router_input(
        open_gaps=[_gap("EVIDENCE_GAP", gap_id="g1")],
        executed_agents=["research"],
        unresolved_history={"g1": ["research"]},
    ))
    skips = [d for d in decisions if d.selected_action == "skip"]
    assert len(skips) == 1
    assert "owner_already_dispatched_for_gap" in skips[0].reason


def test_allow_dispatch_when_same_owner_different_gap():
    """Same owner executed for a different gap should NOT block this gap."""
    router = DynamicRouter()
    decisions = router.decide(_router_input(
        open_gaps=[_gap("EVIDENCE_GAP", gap_id="g2")],
        executed_agents=["research"],
        unresolved_history={"g1": ["research"]},  # different gap
    ))
    assert len(decisions) == 1
    d = decisions[0]
    assert d.selected_action == "execute"
    assert d.selected_agent == "research"


def test_multiple_gaps_produce_multiple_decisions():
    router = DynamicRouter()
    gaps = [_gap("EVIDENCE_GAP", gap_id="g1"), _gap("NUMERIC_GAP", gap_id="g2")]
    decisions = router.decide(_router_input(open_gaps=gaps))
    assert len(decisions) == 2
    assert decisions[0].selected_agent == "research"
    assert decisions[1].selected_agent == "analyze"


def test_no_executable_actions_triggers_stop():
    """When all gaps are skipped or fallback, should add a stop decision."""
    budget = BudgetGuard(BudgetState(max_dispatches_per_gap=0))
    router = DynamicRouter(budget_guard=budget)
    decisions = router.decide(_router_input(open_gaps=[_gap("EVIDENCE_GAP", gap_id="g1")]))
    # Should have skip (budget exhausted) + stop (no executable actions)
    assert len(decisions) == 2
    assert decisions[0].selected_action == "skip"
    assert decisions[1].selected_action == "stop"
    assert decisions[1].stop_recommended is True


def test_should_stop_true_when_budget_exhausted():
    budget = BudgetGuard(BudgetState(max_total_rounds=3))
    budget.record_round()
    budget.record_round()
    budget.record_round()
    assert budget.budget.current_round >= budget.budget.max_total_rounds
    router = DynamicRouter(budget_guard=budget)
    assert router.should_stop(_router_input(open_gaps=[_gap("EVIDENCE_GAP")])) is True


def test_should_stop_false_when_actionable_and_within_budget():
    router = DynamicRouter()
    assert router.should_stop(_router_input(open_gaps=[_gap("EVIDENCE_GAP")])) is False


def test_decision_has_decision_id():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("EVIDENCE_GAP")]))
    assert decisions[0].decision_id.startswith("rd_")


def test_decision_has_reason_with_gap_type_and_severity():
    router = DynamicRouter()
    decisions = router.decide(_router_input(open_gaps=[_gap("NUMERIC_GAP", gap_id="g2", severity="high")]))
    d = decisions[0]
    assert "NUMERIC_GAP" in d.reason
    assert "high" in d.reason
    assert "g2" in d.reason


def test_expected_effect_maps_correctly():
    router = DynamicRouter()
    cases = [
        ("EVIDENCE_GAP", "increase_evidence_candidates_and_records"),
        ("NUMERIC_GAP", "repair_numeric_claims_and_analysis_artifacts"),
        ("CITATION_GAP", "supplement_evidence_for_citation_repair"),
        ("RISK_GAP", "add_risk_claims_from_risk_agent"),
        ("PEER_GAP", "add_peer_comparison_claims_and_evidence"),
        ("FORMAT_GAP", "repair_report_format_and_required_sections"),
    ]
    for gap_type, expected_effect in cases:
        decisions = router.decide(_router_input(open_gaps=[_gap(gap_type, gap_id="gx")]))
        assert decisions[0].expected_effect == expected_effect, f"{gap_type}: expected {expected_effect}, got {decisions[0].expected_effect}"


def test_stop_reason_delegates_to_budget_guard():
    budget = BudgetGuard(BudgetState(max_total_rounds=0))
    router = DynamicRouter(budget_guard=budget)
    router.should_stop(_router_input(open_gaps=[_gap("EVIDENCE_GAP")]))
    reason = router.stop_reason()
    assert "max_total_rounds_exceeded" in reason


def test_router_input_from_state_filter_resolved_gaps():
    state = {
        "verification_report": {
            "gaps": [
                {"gap_id": "g1", "gap_type": "EVIDENCE_GAP", "status": "open"},
                {"gap_id": "g2", "gap_type": "NUMERIC_GAP", "status": "resolved"},
                {"gap_id": "g3", "gap_type": "RISK_GAP", "status": "open"},
            ],
        },
        "task_board": {},
        "agent_messages": [],
    }
    rinput = RouterInput.from_state(state, budget_state={})
    assert len(rinput.open_gaps) == 2
    assert rinput.open_gaps[0]["gap_id"] == "g1"
    assert rinput.open_gaps[1]["gap_id"] == "g3"


def test_router_input_from_state_creates_summary():
    state = {
        "symbol": "AAPL",
        "period": "Q1",
        "claims": [{"id": "c1"}],
        "evidence_records": [{"id": "e1"}],
        "citations": [{"id": "ct1"}],
        "markdown": "# Report text",
        "verification_report": {"passed": False, "gaps": [{"gap_id": "g1", "gap_type": "EVIDENCE_GAP", "status": "open"}]},
        "task_board": {},
        "agent_messages": [],
    }
    rinput = RouterInput.from_state(state, budget_state={})
    summary = rinput.current_state_summary
    assert summary["symbol"] == "AAPL"
    assert summary["claim_count"] == 1
    assert summary["evidence_count"] == 1
    assert summary["citation_count"] == 1
    assert summary["markdown_chars"] > 0
    assert summary["verification_passed"] is False
    assert summary["open_gap_count"] == 1


def test_router_decision_to_dict():
    d = RouterDecision(
        selected_action="execute",
        selected_agent="research",
        selected_task_type="deep_researcher",
        related_gap_ids=["g1"],
        reason="gap_type=EVIDENCE_GAP",
        expected_effect="increase_evidence_candidates_and_records",
    )
    dd = d.to_dict()
    assert dd["selected_action"] == "execute"
    assert dd["selected_agent"] == "research"
    assert dd["selected_task_type"] == "deep_researcher"
    assert dd["related_gap_ids"] == ["g1"]
    assert dd["reason"] == "gap_type=EVIDENCE_GAP"
    assert dd["fallback_used"] is False
    assert dd["stop_recommended"] is False
    assert dd["unsupported_gap_type"] == ""
    assert "decision_id" in dd
    assert "created_at" in dd
