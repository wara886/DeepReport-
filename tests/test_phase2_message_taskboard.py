import json
from pathlib import Path

from src.agents.base_agent import AgentStatus, AgentTask, TaskResult
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator, _sync_gap_routes_to_blackboard
from src.eval.metrics import message_count, task_blocked_count, task_resolution_rate
from src.multiagent.blackboard import Blackboard
from src.multiagent.gaps.schema import GapItem, GapSeverity, GapType
from src.multiagent.messages import AgentMessage, MessageStatus, MessageType
from src.multiagent.taskboard import TaskBoard, TaskStatus


class FakeModel:
    model_name = "fake"

    def generate_json(self, *args, **kwargs):
        return {}


class StubAgent:
    def __init__(self, name: str):
        self.name = name
        self.model = FakeModel()

    def execute_task(self, task: AgentTask) -> TaskResult:
        outputs = {
            "deep_researcher": {"evidence_candidates": [], "search_meta": {}},
            "browser": {"evidence_records": []},
            "deep_analyze": {"claims": [], "analysis_artifacts": {}},
            "final_answer": {"markdown": "# Report", "html": "<h1>Report</h1>", "report_json": {}},
            "verifier": {"verification_report": {"passed": True, "errors": [], "warnings": [], "evidence_gaps": [], "gaps": [], "gap_count": 0}},
        }
        return TaskResult(task.task_id, self.name, AgentStatus.COMPLETED, outputs.get(task.task_type, {}))


def test_agent_message_schema_roundtrip_and_priority_clamp():
    message = AgentMessage.create(
        sender_agent="ResearchAgent",
        receiver_agent="AnalyzeAgent",
        message_type=MessageType.REQUEST_RECALCULATION,
        related_task_id="task_1",
        related_gap_id="gap_1",
        related_claim_ids=["cl_1"],
        payload={"x": 1},
        priority=9,
        status=MessageStatus.SENT,
    )

    restored = AgentMessage.from_dict(message.to_dict())

    assert restored.message_type == MessageType.REQUEST_RECALCULATION
    assert restored.status == MessageStatus.SENT
    assert restored.priority == 5
    assert restored.related_claim_ids == ["cl_1"]


def test_task_board_tracks_open_blocked_and_resolution_rate():
    board = TaskBoard.from_plan_tasks(
        [
            AgentTask("task_1", "deep_researcher", "research"),
            AgentTask("task_2", "verifier", "verify", dependencies=["task_1"]),
        ],
        lambda task_type: f"owner:{task_type}",
    )
    board.update_status("task_1", TaskStatus.RESOLVED, result_ref="ResearchAgent")
    board.update_status("task_2", TaskStatus.BLOCKED)

    payload = board.to_dict()

    assert payload["summary"]["task_count"] == 2
    assert payload["summary"]["blocked_count"] == 1
    assert payload["summary"]["resolution_rate"] == 0.5
    assert len(board.open_tasks()) == 1


def test_blackboard_read_write_append_and_open_tasks():
    board = TaskBoard()
    board.upsert({"task_id": "task_1", "task_type": "verify", "owner_agent": "VerifierAgent"})
    blackboard = Blackboard(state={"symbol": "NVDA"}, task_board=board)
    blackboard.write_state("period", "2025Q4")
    blackboard.append_message(AgentMessage.create("A", "B", MessageType.STATUS_UPDATE))
    blackboard.append_gap(GapItem("gap_1", GapType.EVIDENCE_GAP, GapSeverity.HIGH, "VerifierAgent"))

    assert blackboard.read_state("symbol") == "NVDA"
    assert blackboard.read_state("period") == "2025Q4"
    assert len(blackboard.read_state("agent_messages")) == 1
    assert len(blackboard.read_state("gaps")) == 1
    assert blackboard.get_open_tasks()[0]["task_id"] == "task_1"


def test_gap_routes_write_taskboard_and_agent_messages():
    gap = GapItem("gap_ev", GapType.EVIDENCE_GAP, GapSeverity.HIGH, "VerifierAgent", related_claim_ids=["cl_1"]).to_dict()
    state = {"verification_report": {"gaps": [gap]}, "agent_messages": [], "gaps": []}
    blackboard = Blackboard(state=state)

    _sync_gap_routes_to_blackboard(state, blackboard)

    task_board = state["task_board"]
    owners = {task["owner_agent"] for task in task_board["tasks"]}
    assert {"ResearchAgent", "BrowserAgent"}.issubset(owners)
    assert state["gaps"][0]["gap_id"] == "gap_ev"
    assert any(message["message_type"] == MessageType.REQUEST_EVIDENCE.value for message in state["agent_messages"])


def test_dynamic_execution_records_taskboard_and_messages(tmp_path: Path):
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=FakeModel(),
    )
    orchestrator.agents.update(
        {
            "research": StubAgent("ResearchAgent"),
            "browser": StubAgent("BrowserAgent"),
            "analyze": StubAgent("AnalyzeAgent"),
            "final_answer": StubAgent("FinalWriterAgent"),
            "verifier": StubAgent("VerifierAgent"),
        }
    )
    tasks = [
        AgentTask("task_001_research", "deep_researcher", "research"),
        AgentTask("task_002_browser", "browser", "browser", dependencies=["task_001_research"]),
        AgentTask("task_003_analyze", "deep_analyze", "analyze", dependencies=["task_002_browser"]),
        AgentTask("task_004_final", "final_answer", "write", dependencies=["task_003_analyze"]),
        AgentTask("task_005_verify", "verifier", "verify", dependencies=["task_004_final"]),
    ]
    state = {
        "research_topic": "NVDA report",
        "symbol": "NVDA",
        "period": "2025Q4",
        "evidence_candidates": [],
        "evidence_records": [],
        "claims": [],
        "analysis_artifacts": {},
        "verification_report": {},
        "gap_resolution_trace": [],
        "rework_trace": [],
        "conversation_context": {},
        "performance_profile": "fast",
        "agent_messages": [],
        "gaps": [],
        "task_board": {},
    }

    results = orchestrator._execute_dynamic_tasks(tasks, state)

    assert len(results) == 5
    assert state["task_board"]["summary"]["task_count"] == 5
    assert state["task_board"]["summary"]["resolution_rate"] == 1.0
    assert len(state["agent_messages"]) == 10


def test_phase2_eval_process_metrics_from_artifacts(tmp_path: Path):
    messages_path = tmp_path / "agent_messages.jsonl"
    board_path = tmp_path / "task_board.json"
    messages_path.write_text(json.dumps({"message_id": "m1"}) + "\n" + json.dumps({"message_id": "m2"}) + "\n", encoding="utf-8")
    board = {"tasks": [{"status": "resolved"}, {"status": "blocked"}], "summary": {"blocked_count": 1, "resolution_rate": 0.5}}
    board_path.write_text(json.dumps(board), encoding="utf-8")

    assert message_count([{"message_id": "m1"}, {"message_id": "m2"}]) == 2
    assert task_blocked_count(board) == 1
    assert task_resolution_rate(board) == 0.5
