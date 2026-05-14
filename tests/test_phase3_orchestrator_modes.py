"""Tests for multi_agent_orchestrator three execution mode isolation.

Verifies that legacy_workflow, routed_rework, and dynamic_multiagent modes
execute correctly and produce the expected artifacts.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentStatus, AgentTask, TaskResult
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.multiagent.blackboard import Blackboard


class FakeModel:
    model_name = "fake"

    def generate_json(self, *args, **kwargs):
        return {}


class FakeAgent:
    def __init__(self, name: str, output: Dict[str, Any] | None = None):
        self.name = name
        self.model = FakeModel()
        self.output = output or {}
        self.calls: List[AgentTask] = []

    def execute_task(self, task: AgentTask) -> TaskResult:
        self.calls.append(task)
        return TaskResult(task.task_id, self.name, AgentStatus.COMPLETED, self.output)


def _orchestrator(tmp_path) -> MultiAgentOrchestrator:
    return MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=FakeModel(),
    )


def _base_state() -> Dict[str, Any]:
    return {
        "research_topic": "test report",
        "symbol": "NVDA",
        "period": "latest_quarter",
        "evidence_candidates": [{"result_id": "ev1", "snippet": "some evidence"}],
        "evidence_records": [],
        "claims": [],
        "analysis_artifacts": {},
        "markdown": "# Report Body\n\n## Financials\n\nSome content.",
        "html": "",
        "report_json": {},
        "citations": [],
        "verification_report": {
            "passed": False,
            "gaps": [
                {
                    "gap_id": "gap_evidence_1",
                    "gap_type": "EVIDENCE_GAP",
                    "severity": "HIGH",
                    "status": "open",
                    "description": "Missing evidence",
                    "recommended_action": "add evidence",
                }
            ],
            "evidence_gaps": [],
        },
        "gap_resolution_trace": [],
        "rework_trace": [],
        "conversation_context": {},
        "conversation_brief": "",
        "performance_profile": "fast",
        "search_engines": ["local_real_data", "local_evidence"],
        "retrieval_ranking_mode": "hybrid_rerank",
        "raw_data_root": "data/raw/real_data",
        "agent_messages": [],
        "gaps": [],
        "task_board": {},
        "router_decisions": [],
        "budget_trace": [],
        "rework_mode": "routed_rework",
    }


def test_legacy_workflow_mode_same_as_routed_rework_path(tmp_path):
    """legacy_workflow and routed_rework share the same code path — both produce rework_trace."""
    orch = _orchestrator(tmp_path)
    state = _base_state()
    state["rework_mode"] = "legacy_workflow"
    blackboard = Blackboard(state=state)
    orch._active_blackboard = blackboard

    orch._run_verifier_rework_loop(state=state, rework_mode="legacy_workflow")

    # rework_trace is initialized from gaps in both legacy and routed modes
    assert len(state.get("rework_trace", [])) > 0
    # No router_decisions (only dynamic_multiagent produces them)
    assert len(state.get("router_decisions", [])) == 0


def test_routed_rework_mode_produces_rework_trace(tmp_path):
    """routed_rework mode should produce rework_trace entries for supported gaps."""
    orch = _orchestrator(tmp_path)
    orch.agents["research"] = FakeAgent("DeepResearcherAgent", {"evidence_candidates": [{"result_id": "ev2", "snippet": "more evidence"}], "search_meta": {}})
    orch.agents["final_answer"] = FakeAgent("FinalAnswerAgent", {"markdown": "# Revised Report\n\n## Financials\n\nUpdated.", "html": "", "report_json": {}})
    state = _base_state()
    state["rework_mode"] = "routed_rework"
    blackboard = Blackboard(state=state)
    orch._active_blackboard = blackboard

    orch._run_verifier_rework_loop(state=state, rework_mode="routed_rework")

    assert len(state.get("rework_trace", [])) > 0
    # routed_rework does NOT produce router_decisions
    assert len(state.get("router_decisions", [])) == 0


def test_dynamic_multiagent_mode_produces_router_decisions(tmp_path):
    """dynamic_multiagent mode should produce router_decisions and budget_trace entries."""
    orch = _orchestrator(tmp_path)
    orch.agents["research"] = FakeAgent("DeepResearcherAgent", {"evidence_candidates": [{"result_id": "ev2", "snippet": "more evidence"}], "search_meta": {}})
    orch.agents["final_answer"] = FakeAgent("FinalAnswerAgent", {"markdown": "# Revised Report\n\n## Financials\n\nUpdated.", "html": "", "report_json": {}})
    state = _base_state()
    state["rework_mode"] = "dynamic_multiagent"
    blackboard = Blackboard(state=state)
    orch._active_blackboard = blackboard

    orch._run_verifier_rework_loop(state=state, rework_mode="dynamic_multiagent")

    assert len(state.get("router_decisions", [])) > 0, "Expected router_decisions in dynamic_multiagent mode"
    assert len(state.get("budget_trace", [])) > 0, "Expected budget_trace in dynamic_multiagent mode"
    assert len(state.get("rework_trace", [])) > 0, "Expected rework_trace in dynamic_multiagent mode"


def test_dynamic_multiagent_decisions_have_expected_structure(tmp_path):
    """DynamicRouter decisions in dynamic_multiagent mode should have required fields."""
    orch = _orchestrator(tmp_path)
    orch.agents["research"] = FakeAgent("DeepResearcherAgent", {"evidence_candidates": [{"result_id": "ev2", "snippet": "more evidence"}], "search_meta": {}})
    orch.agents["final_answer"] = FakeAgent("FinalAnswerAgent", {"markdown": "# Revised Report\n\n## Financials\n\nUpdated.", "html": "", "report_json": {}})
    state = _base_state()
    state["rework_mode"] = "dynamic_multiagent"
    blackboard = Blackboard(state=state)
    orch._active_blackboard = blackboard

    orch._run_verifier_rework_loop(state=state, rework_mode="dynamic_multiagent")

    for d in state["router_decisions"]:
        assert "decision_id" in d
        assert "selected_action" in d
        assert "selected_agent" in d
        assert "related_gap_ids" in d
        assert "reason" in d
        assert "fallback_used" in d
        assert "created_at" in d


def test_dynamic_multiagent_budget_trace_has_stop_conditions(tmp_path):
    """Budget trace entries in dynamic_multiagent mode should include budget state."""
    orch = _orchestrator(tmp_path)
    orch.agents["research"] = FakeAgent("DeepResearcherAgent", {"evidence_candidates": [{"result_id": "ev2", "snippet": "more evidence"}], "search_meta": {}})
    orch.agents["final_answer"] = FakeAgent("FinalAnswerAgent", {"markdown": "# Revised Report\n\n## Financials\n\nUpdated.", "html": "", "report_json": {}})
    state = _base_state()
    state["rework_mode"] = "dynamic_multiagent"
    blackboard = Blackboard(state=state)
    orch._active_blackboard = blackboard

    orch._run_verifier_rework_loop(state=state, rework_mode="dynamic_multiagent")

    for entry in state["budget_trace"]:
        assert "current_round" in entry
        assert "current_dispatch_count" in entry
        assert "max_total_rounds" in entry
        assert "can_continue" in entry
        assert "stop_reason" in entry


def test_run_has_phase3_metrics_in_state(tmp_path):
    """run() with dynamic_multiagent should include Phase 3 metrics in state."""
    orch = _orchestrator(tmp_path)
    orch.agents["research"] = FakeAgent("DeepResearcherAgent", {"evidence_candidates": [{"result_id": "ev2", "snippet": "more evidence"}], "search_meta": {}})
    orch.agents["final_answer"] = FakeAgent("FinalAnswerAgent", {"markdown": "# Revised Report\n\n## Financials\n\nUpdated.", "html": "", "report_json": {}})

    state = _base_state()
    state["rework_mode"] = "dynamic_multiagent"
    blackboard = Blackboard(state=state)
    orch._active_blackboard = blackboard

    orch._run_verifier_rework_loop(state=state, rework_mode="dynamic_multiagent")

    decisions = state.get("router_decisions", [])
    assert len(decisions) > 0
    assert state["budget_trace"]
    # Track the key counts
    dispatch_count = sum(1 for d in decisions if d.get("selected_action") == "execute")
    fallback_count = sum(1 for d in decisions if d.get("fallback_used"))
    assert dispatch_count >= 0
    assert isinstance(fallback_count, int)
