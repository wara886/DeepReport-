"""Dedicated analysis role agents for collaborative company reports."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.agents.deep_analyze_agent import build_role_outputs
from src.agents.research_blackboard import ROLE_OUTPUT_OWNERS, role_key_for_agent


class AnalysisRoleAgent(BaseAgent):
    """Base class for one blackboard-owned analysis role."""

    role_key = ""

    def __init__(self, name: str, role_key: str, tools: Dict[str, Any] | None = None):
        super().__init__(name=name, tools=tools)
        self.role_key = role_key

    def get_capabilities(self) -> List[str]:
        return [f"write {self.role_key} to the shared research blackboard"]

    def execute_task(self, task: AgentTask) -> TaskResult:
        params = task.parameters
        artifacts = params.get("analysis_artifacts", {}) if isinstance(params.get("analysis_artifacts"), dict) else {}
        role_outputs = build_role_outputs(
            records=list(params.get("evidence_records", [])) if isinstance(params.get("evidence_records"), list) else [],
            claims=list(params.get("claims", [])) if isinstance(params.get("claims"), list) else [],
            symbol=str(params.get("symbol") or ""),
            period=str(params.get("period") or ""),
            statement_view=artifacts.get("statement_view", {}),
            peer_context=artifacts.get("peer_context", {}),
            valuation=artifacts.get("valuation", {}),
            financial_metric_lineage=artifacts.get("financial_metrics", {}),
            table_artifacts=artifacts.get("tables", []),
        )
        payload = dict(role_outputs.get(self.role_key, {}))
        owner = ROLE_OUTPUT_OWNERS[self.role_key]
        if owner != self.name:
            return self.failure(task, f"{self.name} is not authorized to write {self.role_key}")
        payload["owner_agent"] = self.name
        payload["verified"] = str(payload.get("status") or "") == "complete"
        payload["reviewed_objections"] = [
            item
            for item in params.get("critic_objections", [])
            if isinstance(item, dict) and item.get("target_agent") == self.name
        ][:8]
        return self.success(
            task,
            {
                self.role_key: payload,
                "role_outputs": {self.role_key: payload},
            },
            metadata={
                "role_key": self.role_key,
                "status": payload.get("status", ""),
                "verified": bool(payload.get("verified")),
            },
        )


class IdentityAgent(AnalysisRoleAgent):
    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__("IdentityAgent", "identity_profile", tools=tools)


class StatementAgent(AnalysisRoleAgent):
    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__("StatementAgent", "three_statement_analysis", tools=tools)


class PeerAgent(AnalysisRoleAgent):
    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__("PeerAgent", "peer_analysis", tools=tools)


class ValuationAgent(AnalysisRoleAgent):
    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__("ValuationAgent", "valuation_analysis", tools=tools)


class RiskAgent(AnalysisRoleAgent):
    def __init__(self, tools: Dict[str, Any] | None = None):
        super().__init__("RiskAgent", "risk_analysis", tools=tools)


def role_key_for_task_type(task_type: str) -> str:
    """Map collaborative task types to role-output keys."""

    return role_key_for_agent(
        {
            "identity_profile": "IdentityAgent",
            "three_statement_analysis": "StatementAgent",
            "peer_analysis": "PeerAgent",
            "valuation_analysis": "ValuationAgent",
            "risk_analysis": "RiskAgent",
        }.get(task_type, task_type)
    )
