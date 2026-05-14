"""BudgetGuard: enforces execution budget limits for dynamic multi-agent routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class BudgetState:
    max_total_rounds: int = 3
    max_routed_rework_rounds: int = 2
    max_dispatches_per_gap: int = 2
    max_total_agent_dispatches: int = 12
    max_total_runtime_sec: float = 300.0
    current_round: int = 0
    current_dispatch_count: int = 0
    per_gap_dispatch_count: Dict[str, int] = field(default_factory=dict)
    elapsed_runtime_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_total_rounds": self.max_total_rounds,
            "max_routed_rework_rounds": self.max_routed_rework_rounds,
            "max_dispatches_per_gap": self.max_dispatches_per_gap,
            "max_total_agent_dispatches": self.max_total_agent_dispatches,
            "max_total_runtime_sec": self.max_total_runtime_sec,
            "current_round": self.current_round,
            "current_dispatch_count": self.current_dispatch_count,
            "per_gap_dispatch_count": dict(self.per_gap_dispatch_count),
            "elapsed_runtime_sec": round(self.elapsed_runtime_sec, 4),
        }

    @classmethod
    def from_profile(cls, profile: str = "fast") -> "BudgetState":
        if profile == "fast":
            return cls(max_total_rounds=2, max_routed_rework_rounds=1, max_dispatches_per_gap=1, max_total_agent_dispatches=8, max_total_runtime_sec=180.0)
        return cls(max_total_rounds=3, max_routed_rework_rounds=2, max_dispatches_per_gap=2, max_total_agent_dispatches=12, max_total_runtime_sec=300.0)


class BudgetGuard:
    def __init__(self, budget: BudgetState | None = None):
        self.budget = budget or BudgetState()
        self._stop_reason: str = ""

    def record_dispatch(self, gap_id: str = "", elapsed_sec: float = 0.0) -> None:
        self.budget.current_dispatch_count += 1
        self.budget.elapsed_runtime_sec += elapsed_sec
        if gap_id:
            self.budget.per_gap_dispatch_count[gap_id] = self.budget.per_gap_dispatch_count.get(gap_id, 0) + 1

    def record_round(self) -> None:
        self.budget.current_round += 1

    def can_dispatch_gap(self, gap_id: str) -> bool:
        count = self.budget.per_gap_dispatch_count.get(gap_id, 0)
        return count < self.budget.max_dispatches_per_gap

    def can_continue(self, has_actionable_gaps: bool = True) -> bool:
        self._stop_reason = self._compute_stop_reason(has_actionable_gaps)
        return not bool(self._stop_reason)

    def should_stop(self, has_actionable_gaps: bool = True) -> bool:
        return not self.can_continue(has_actionable_gaps)

    def stop_reason(self) -> str:
        return self._stop_reason

    def budget_snapshot(self, round_index: int | None = None, can_continue: bool | None = None) -> Dict[str, Any]:
        snap = self.budget.to_dict()
        snap["can_continue"] = can_continue if can_continue is not None else not bool(self._stop_reason)
        snap["stop_reason"] = self._stop_reason
        if round_index is not None:
            snap["round"] = round_index
        return snap

    def _compute_stop_reason(self, has_actionable_gaps: bool) -> str:
        b = self.budget
        if b.current_round >= b.max_total_rounds:
            return f"max_total_rounds_exceeded:{b.current_round}>={b.max_total_rounds}"
        if b.current_dispatch_count >= b.max_total_agent_dispatches:
            return f"max_total_dispatches_exceeded:{b.current_dispatch_count}>={b.max_total_agent_dispatches}"
        if b.elapsed_runtime_sec >= b.max_total_runtime_sec:
            return f"max_runtime_exceeded:{b.elapsed_runtime_sec:.1f}>={b.max_total_runtime_sec}"
        if not has_actionable_gaps:
            return "no_actionable_gaps"
        return ""

    def repeated_dispatch_gaps(self) -> List[str]:
        return [gap_id for gap_id, count in self.budget.per_gap_dispatch_count.items() if count >= self.budget.max_dispatches_per_gap]
