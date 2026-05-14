"""Schema types for DynamicRouter input and output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RouterInput:
    """All state inputs the DynamicRouter reads before making a decision."""

    open_gaps: List[Dict[str, Any]] = field(default_factory=list)
    task_board_snapshot: Dict[str, Any] = field(default_factory=dict)
    recent_agent_messages: List[Dict[str, Any]] = field(default_factory=list)
    previous_router_decisions: List[Dict[str, Any]] = field(default_factory=list)
    executed_agents_in_current_round: List[str] = field(default_factory=list)
    unresolved_gap_history: Dict[str, List[str]] = field(default_factory=dict)
    budget_state: Dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "dynamic_multiagent"
    current_state_summary: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_state(
        cls,
        state: Dict[str, Any],
        budget_state: Dict[str, Any],
        previous_decisions: List[Dict[str, Any]] | None = None,
        executed_agents: List[str] | None = None,
        unresolved_gap_history: Dict[str, List[str]] | None = None,
    ) -> "RouterInput":
        report = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
        open_gaps = [g for g in report.get("gaps", []) if isinstance(g, dict) and g.get("status") not in ("resolved",)]
        task_board = state.get("task_board", {}) if isinstance(state.get("task_board"), dict) else {}
        messages = state.get("agent_messages", []) if isinstance(state.get("agent_messages"), list) else []
        return cls(
            open_gaps=open_gaps,
            task_board_snapshot=task_board,
            recent_agent_messages=messages[-20:],
            previous_router_decisions=list(previous_decisions or []),
            executed_agents_in_current_round=list(executed_agents or []),
            unresolved_gap_history=dict(unresolved_gap_history or {}),
            budget_state=dict(budget_state),
            current_state_summary={
                "symbol": str(state.get("symbol", "")),
                "period": str(state.get("period", "")),
                "claim_count": len(state.get("claims", [])) if isinstance(state.get("claims"), list) else 0,
                "evidence_count": len(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else 0,
                "citation_count": len(state.get("citations", [])) if isinstance(state.get("citations"), list) else 0,
                "markdown_chars": len(str(state.get("markdown", ""))),
                "verification_passed": bool(report.get("passed", False)),
                "open_gap_count": len(open_gaps),
            },
        )


@dataclass
class RouterDecision:
    """A single routing decision produced by DynamicRouter."""

    decision_id: str = field(default_factory=lambda: f"rd_{uuid4().hex[:10]}")
    selected_action: str = "execute"
    selected_agent: str = ""
    selected_task_type: str = ""
    related_gap_ids: List[str] = field(default_factory=list)
    reason: str = ""
    expected_effect: str = ""
    fallback_used: bool = False
    stop_recommended: bool = False
    unsupported_gap_type: str = ""
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "selected_action": self.selected_action,
            "selected_agent": self.selected_agent,
            "selected_task_type": self.selected_task_type,
            "related_gap_ids": list(self.related_gap_ids),
            "reason": self.reason,
            "expected_effect": self.expected_effect,
            "fallback_used": self.fallback_used,
            "stop_recommended": self.stop_recommended,
            "unsupported_gap_type": self.unsupported_gap_type,
            "created_at": self.created_at,
        }
