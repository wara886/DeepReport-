from src.agents.base_agent import AgentStatus, AgentTask, TaskResult
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.multiagent.blackboard import Blackboard
from src.multiagent.gaps.schema import GapItem, GapSeverity, GapType
from src.multiagent.taskboard import TaskStatus


class FakeModel:
    model_name = "fake"

    def generate_json(self, *args, **kwargs):
        return {}


class RecordingAgent:
    def __init__(self, name, output):
        self.name = name
        self.model = FakeModel()
        self.output = output
        self.calls = []

    def execute_task(self, task: AgentTask) -> TaskResult:
        self.calls.append(task)
        return TaskResult(task.task_id, self.name, AgentStatus.COMPLETED, self.output)


def _orchestrator(tmp_path):
    return MultiAgentOrchestrator(output_dir=str(tmp_path / "outputs"), report_dir=str(tmp_path / "reports"), model=FakeModel())


def _state(gap):
    return {
        "research_topic": "test report",
        "symbol": "NVDA",
        "period": "latest_quarter",
        "evidence_candidates": [],
        "evidence_records": [],
        "claims": [],
        "analysis_artifacts": {},
        "markdown": "# Report",
        "html": "",
        "report_json": {},
        "citations": [],
        "verification_report": {"passed": False, "gaps": [gap], "evidence_gaps": []},
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
    }


def _gap(gap_type):
    return GapItem(
        gap_id=f"gap_{gap_type.value.lower()}",
        gap_type=gap_type,
        severity=GapSeverity.HIGH,
        detected_by="VerifierAgent",
        description="test gap",
        recommended_action="fix it",
    ).to_dict()


def test_evidence_gap_triggers_research_agent_path(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    research = RecordingAgent("DeepResearcherAgent", {"evidence_candidates": [{"result_id": "ev1", "snippet": "new evidence"}], "search_meta": {}})
    orchestrator.agents["research"] = research
    state = _state(_gap(GapType.EVIDENCE_GAP))
    blackboard = Blackboard(state=state)
    orchestrator._active_blackboard = blackboard

    orchestrator._run_routed_gap_rework(state, round_index=1, blackboard=blackboard)

    assert research.calls
    assert research.calls[0].task_type == "deep_researcher"
    assert state["evidence_candidates"]
    assert state["rework_trace"][0]["actually_executed_agent"] == "DeepResearcherAgent"
    assert state["rework_trace"][0]["before_state_ref"]
    assert state["rework_trace"][0]["after_state_ref"]
    assert state["task_board"]["tasks"][0]["status"] == TaskStatus.RESOLVED.value
    assert any(message["payload"].get("event") == "routed_rework_completed" for message in state["agent_messages"])


def test_numeric_gap_triggers_analyze_agent_path(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    analyze = RecordingAgent("DeepAnalyzeAgent", {"claims": [{"claim_id": "cl1", "claim_text": "numeric fixed"}], "analysis_artifacts": {"tables": []}})
    orchestrator.agents["analyze"] = analyze
    state = _state(_gap(GapType.NUMERIC_GAP))
    state["evidence_records"] = [{"evidence_id": "ev1", "content": "Revenue 10", "source_type": "financials"}]
    blackboard = Blackboard(state=state)
    orchestrator._active_blackboard = blackboard

    orchestrator._run_routed_gap_rework(state, round_index=1, blackboard=blackboard)

    assert analyze.calls
    assert analyze.calls[0].task_type == "deep_analyze"
    assert state["claims"][0]["claim_id"] == "cl1"
    assert state["rework_trace"][0]["actually_executed_agent"] == "DeepAnalyzeAgent"


def test_format_gap_triggers_final_writer_path(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    final = RecordingAgent("FinalAnswerAgent", {"markdown": "# Fixed\n\n## Risk Assessment", "html": "<h1>Fixed</h1>", "report_json": {}})
    orchestrator.agents["final_answer"] = final
    state = _state(_gap(GapType.FORMAT_GAP))
    blackboard = Blackboard(state=state)
    orchestrator._active_blackboard = blackboard

    orchestrator._run_routed_gap_rework(state, round_index=1, blackboard=blackboard)

    assert final.calls
    assert final.calls[0].task_type == "final_answer"
    assert "Fixed" in state["markdown"]
    assert state["rework_trace"][0]["actually_executed_agent"] == "FinalAnswerAgent"


def test_unsupported_gap_type_uses_explicit_fallback(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    state = _state(_gap(GapType.SOURCE_CONFLICT))
    blackboard = Blackboard(state=state)
    orchestrator._active_blackboard = blackboard

    orchestrator._run_routed_gap_rework(state, round_index=1, blackboard=blackboard)

    row = state["rework_trace"][0]
    assert row["actually_executed_agent"] == "fallback_unified_final_answer"
    assert row["fallback_reason"] == "unsupported_gap_type:SOURCE_CONFLICT"
    assert any(message["payload"].get("event") == "routed_rework_fallback" for message in state["agent_messages"])
