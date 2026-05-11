from src.agents import AgentStatus, AgentTask, BaseAgent, PlanningAgent, TaskResult
from src.agents.deep_analyze_agent import normalize_claims
from src.agents.planner import Planner


class DummyAgent(BaseAgent):
    def get_capabilities(self):
        return ["dummy"]

    def execute_task(self, task: AgentTask) -> TaskResult:
        return self.success(task, {"ok": True})


class FakeModel:
    def generate_json(self, prompt, system_prompt=None, **kwargs):
        assert "Return a JSON object" in prompt
        assert "PlanningAgent" in system_prompt
        return {
            "overview": "Plan overview",
            "tasks": [
                {
                    "task_id": "task_001",
                    "task_type": "deep_researcher",
                    "description": "Collect evidence.",
                    "parameters": {"symbol": "AAPL"},
                    "dependencies": [],
                    "priority": 5,
                    "expected_output": "Evidence list.",
                },
                {
                    "task_id": "task_002",
                    "task_type": "deep_analyze",
                    "description": "Analyze claims.",
                    "parameters": {},
                    "dependencies": ["task_001"],
                    "priority": 4,
                    "expected_output": "Claim list.",
                },
            ],
            "data_sources": ["filings"],
            "citations_required": True,
            "final_outputs": ["report.md"],
        }


def test_agent_task_and_result_roundtrip():
    task = AgentTask(
        task_id="task_001",
        task_type="deep_analyze",
        description="Analyze revenue.",
        parameters={"symbol": "AAPL"},
        dependencies=["task_000"],
        priority=4,
    )
    loaded = AgentTask.from_dict(task.to_dict())

    assert loaded == task

    result = TaskResult(
        task_id=task.task_id,
        agent_name="DeepAnalyzeAgent",
        status=AgentStatus.COMPLETED,
        output={"claims": []},
    )

    assert TaskResult.from_dict(result.to_dict()) == result


def test_base_agent_records_success_in_memory():
    agent = DummyAgent(name="DummyAgent", tools={"add": lambda a, b: a + b})
    task = AgentTask(task_id="task_001", task_type="dummy", description="Run dummy.")

    result = agent.execute_task(task)

    assert result.status == AgentStatus.COMPLETED
    assert result.output == {"ok": True}
    assert agent.call_tool("add", a=1, b=2) == 3
    assert len(agent.memory) == 1


def test_planning_agent_builds_normalized_task_graph():
    agent = PlanningAgent(model=FakeModel())

    plan = agent.build_research_plan(
        research_topic="Analyze AAPL 2025Q4",
        requirements=["Use citations"],
    )

    assert plan["fallback_used"] is False
    assert plan["tasks"][0]["task_type"] == "deep_researcher"
    assert plan["tasks"][1]["dependencies"] == ["task_001"]
    assert plan["citations_required"] is True


def test_planner_keeps_legacy_sections_and_can_delegate_to_planning_agent():
    planning_agent = PlanningAgent(model=FakeModel())
    planner = Planner(planning_agent=planning_agent)

    sections = planner.build_plan()
    task_plan = planner.build_research_plan("Analyze AAPL 2025Q4")

    assert {"section_name": "financial_analysis", "section_title": "财务分析"} in sections
    assert task_plan["tasks"][0]["task_type"] == "deep_researcher"


def test_deep_analyze_filters_conflicting_llm_claims():
    claims = normalize_claims(
        [
            {
                "claim_text": "Revenue grew 15.7%.",
                "evidence_ids": ["tavily_1"],
                "numeric_values": {"revenue_growth_pct": 15.7},
                "notes": "discrepancy with official 11.2% growth",
            },
            {
                "claim_text": "Revenue grew 11.2%.",
                "evidence_ids": ["ev_1"],
                "numeric_values": {"revenue_growth_pct": 11.2},
                "notes": "official",
            },
        ]
    )

    assert len(claims) == 1
    assert claims[0].claim_text == "Revenue grew 11.2%."


def test_planning_agent_can_force_fast_fallback_without_model_call():
    class FailingModel:
        def generate_json(self, *args, **kwargs):
            raise AssertionError("model should not be called")

    agent = PlanningAgent(model=FailingModel())
    result = agent.execute_task(
        AgentTask(
            task_id="task_planning",
            task_type="planning",
            description="Analyze AAPL",
            parameters={"research_topic": "Analyze AAPL", "force_fallback_plan": True},
        )
    )

    assert result.status == AgentStatus.COMPLETED
    assert result.metadata["forced_fast_mode"] is True
    assert result.output["plan"]["fallback_reason"] == "forced_fast_mode"
