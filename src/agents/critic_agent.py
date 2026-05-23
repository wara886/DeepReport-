"""Pre-write critic agent for multi-agent report collaboration."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.agents.research_blackboard import build_pre_write_critic


class CriticAgent(BaseAgent):
    """Review shared research state before the final writer runs."""

    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__(name="CriticAgent", tools=tools)

    def get_capabilities(self) -> List[str]:
        return [
            "review the research blackboard before final writing",
            "raise objections for identity, period, data coverage, and unsupported conclusions",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        blackboard = task.parameters.get("research_blackboard", {})
        state_snapshot = task.parameters.get("state_snapshot", {})
        critic = build_pre_write_critic(
            blackboard if isinstance(blackboard, dict) else {},
            state_snapshot if isinstance(state_snapshot, dict) else {},
        )
        return self.success(task, {"pre_write_critic": critic}, metadata={"objection_count": len(critic.get("objections", []))})
