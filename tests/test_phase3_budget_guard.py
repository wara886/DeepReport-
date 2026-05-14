"""Tests for BudgetGuard: execution budget enforcement for dynamic routing."""

from __future__ import annotations

from src.multiagent.router import BudgetGuard, BudgetState


def test_default_budget_state_values():
    b = BudgetState()
    assert b.max_total_rounds == 3
    assert b.max_routed_rework_rounds == 2
    assert b.max_dispatches_per_gap == 2
    assert b.max_total_agent_dispatches == 12
    assert b.max_total_runtime_sec == 300.0
    assert b.current_round == 0
    assert b.current_dispatch_count == 0
    assert b.per_gap_dispatch_count == {}


def test_fast_profile():
    b = BudgetState.from_profile("fast")
    assert b.max_total_rounds == 2
    assert b.max_routed_rework_rounds == 1
    assert b.max_dispatches_per_gap == 1
    assert b.max_total_agent_dispatches == 8
    assert b.max_total_runtime_sec == 180.0


def test_standard_profile():
    b = BudgetState.from_profile("standard")
    assert b.max_total_rounds == 3
    assert b.max_routed_rework_rounds == 2
    assert b.max_dispatches_per_gap == 2
    assert b.max_total_agent_dispatches == 12
    assert b.max_total_runtime_sec == 300.0


def test_default_profile_is_fast():
    b = BudgetState.from_profile()
    assert b.max_total_rounds == 2


def test_record_dispatch_increments_count():
    guard = BudgetGuard(BudgetState(max_dispatches_per_gap=2))
    guard.record_dispatch(gap_id="g1", elapsed_sec=1.5)
    assert guard.budget.current_dispatch_count == 1
    assert guard.budget.per_gap_dispatch_count["g1"] == 1
    assert guard.budget.elapsed_runtime_sec == 1.5


def test_record_dispatch_accumulates():
    guard = BudgetGuard(BudgetState(max_dispatches_per_gap=2))
    guard.record_dispatch(gap_id="g1", elapsed_sec=1.0)
    guard.record_dispatch(gap_id="g1", elapsed_sec=2.0)
    guard.record_dispatch(gap_id="g2", elapsed_sec=3.0)
    assert guard.budget.current_dispatch_count == 3
    assert guard.budget.per_gap_dispatch_count["g1"] == 2
    assert guard.budget.per_gap_dispatch_count["g2"] == 1
    assert guard.budget.elapsed_runtime_sec == 6.0


def test_record_round_increments():
    guard = BudgetGuard()
    assert guard.budget.current_round == 0
    guard.record_round()
    assert guard.budget.current_round == 1
    guard.record_round()
    assert guard.budget.current_round == 2


def test_can_dispatch_gap_within_limit():
    guard = BudgetGuard(BudgetState(max_dispatches_per_gap=2))
    assert guard.can_dispatch_gap("g1") is True
    guard.record_dispatch(gap_id="g1")
    assert guard.can_dispatch_gap("g1") is True
    guard.record_dispatch(gap_id="g1")
    assert guard.can_dispatch_gap("g1") is False


def test_can_dispatch_untracked_gap():
    guard = BudgetGuard(BudgetState(max_dispatches_per_gap=1))
    assert guard.can_dispatch_gap("untracked") is True


def test_stop_when_max_rounds_exceeded():
    guard = BudgetGuard(BudgetState(max_total_rounds=2))
    guard.record_round()
    guard.record_round()
    assert guard.should_stop(has_actionable_gaps=True) is True
    assert "max_total_rounds_exceeded" in guard.stop_reason()


def test_stop_when_max_dispatches_exceeded():
    guard = BudgetGuard(BudgetState(max_total_agent_dispatches=3))
    guard.record_dispatch()
    guard.record_dispatch()
    guard.record_dispatch()
    assert guard.should_stop(has_actionable_gaps=True) is True
    assert "max_total_dispatches_exceeded" in guard.stop_reason()


def test_stop_when_max_runtime_exceeded():
    guard = BudgetGuard(BudgetState(max_total_runtime_sec=10.0))
    guard.record_dispatch(elapsed_sec=10.0)
    assert guard.should_stop(has_actionable_gaps=True) is True
    assert "max_runtime_exceeded" in guard.stop_reason()


def test_stop_when_no_actionable_gaps():
    guard = BudgetGuard()
    assert guard.should_stop(has_actionable_gaps=False) is True
    assert guard.stop_reason() == "no_actionable_gaps"


def test_can_continue_when_within_budget():
    guard = BudgetGuard(BudgetState(max_total_rounds=3))
    assert guard.can_continue(has_actionable_gaps=True) is True


def test_can_continue_chain_all_conditions():
    guard = BudgetGuard(BudgetState(max_total_rounds=2, max_total_agent_dispatches=5, max_total_runtime_sec=100.0))

    # All within limits
    assert guard.can_continue(has_actionable_gaps=True) is True
    assert guard.should_stop(has_actionable_gaps=True) is False
    assert guard.stop_reason() == ""

    # Exceed rounds
    guard.record_round()
    guard.record_round()
    assert guard.can_continue(has_actionable_gaps=True) is False
    assert "max_total_rounds_exceeded" in guard.stop_reason()


def test_budget_snapshot_includes_key_fields():
    guard = BudgetGuard(BudgetState(max_total_rounds=3))
    snap = guard.budget_snapshot(round_index=1, can_continue=True)
    assert snap["round"] == 1
    assert snap["can_continue"] is True
    assert snap["stop_reason"] == ""
    assert snap["current_round"] == 0
    assert snap["current_dispatch_count"] == 0
    assert snap["max_total_rounds"] == 3


def test_budget_snapshot_with_stop():
    guard = BudgetGuard(BudgetState(max_total_rounds=0))
    guard.should_stop(has_actionable_gaps=True)
    snap = guard.budget_snapshot(round_index=0, can_continue=False)
    assert snap["can_continue"] is False
    assert snap["stop_reason"] != ""


def test_repeated_dispatch_gaps_returns_qualified_ids():
    guard = BudgetGuard(BudgetState(max_dispatches_per_gap=2))
    guard.record_dispatch(gap_id="g1")
    guard.record_dispatch(gap_id="g1")
    guard.record_dispatch(gap_id="g2")
    guard.record_dispatch(gap_id="g2")
    guard.record_dispatch(gap_id="g2")  # exceeded
    repeated = guard.repeated_dispatch_gaps()
    assert "g1" in repeated  # at limit (>=)
    assert "g2" in repeated  # exceeded


def test_no_repeated_dispatches_when_empty():
    guard = BudgetGuard()
    assert guard.repeated_dispatch_gaps() == []


def test_budget_state_to_dict():
    b = BudgetState(max_total_rounds=2, max_total_agent_dispatches=5)
    b.current_round = 1
    b.current_dispatch_count = 2
    b.per_gap_dispatch_count["g1"] = 1
    b.elapsed_runtime_sec = 3.5
    d = b.to_dict()
    assert d["max_total_rounds"] == 2
    assert d["current_round"] == 1
    assert d["current_dispatch_count"] == 2
    assert d["per_gap_dispatch_count"] == {"g1": 1}
    assert d["elapsed_runtime_sec"] == 3.5
    assert d["max_total_agent_dispatches"] == 5


def test_dispatch_without_gap_id():
    guard = BudgetGuard()
    guard.record_dispatch(elapsed_sec=1.0)
    assert guard.budget.current_dispatch_count == 1
    assert guard.budget.elapsed_runtime_sec == 1.0
    # No gap_id means per_gap is not incremented
    assert len(guard.budget.per_gap_dispatch_count) == 0


def test_budget_snapshot_sans_optional_params():
    guard = BudgetGuard(BudgetState(max_total_rounds=3))
    snap = guard.budget_snapshot()
    assert "round" not in snap
    assert snap["can_continue"] is True  # no stop reason yet
