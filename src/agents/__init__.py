"""Agent layer exports for local claim-first pipeline."""

__all__ = [
    "AgentStatus",
    "AgentTask",
    "BaseAgent",
    "TaskResult",
    "PlanningAgent",
    "DeepResearcherAgent",
    "BrowserAgent",
    "DeepAnalyzeAgent",
    "FinalAnswerAgent",
    "VerifierAgent",
    "MultiAgentOrchestrator",
    "Planner",
    "Analyst",
    "Writer",
    "Verifier",
    "Orchestrator",
]

_EXPORTS = {
    "AgentStatus": ("src.agents.base_agent", "AgentStatus"),
    "AgentTask": ("src.agents.base_agent", "AgentTask"),
    "BaseAgent": ("src.agents.base_agent", "BaseAgent"),
    "TaskResult": ("src.agents.base_agent", "TaskResult"),
    "PlanningAgent": ("src.agents.planning_agent", "PlanningAgent"),
    "DeepResearcherAgent": ("src.agents.deep_researcher_agent", "DeepResearcherAgent"),
    "BrowserAgent": ("src.agents.browser_agent", "BrowserAgent"),
    "DeepAnalyzeAgent": ("src.agents.deep_analyze_agent", "DeepAnalyzeAgent"),
    "FinalAnswerAgent": ("src.agents.final_answer_agent", "FinalAnswerAgent"),
    "VerifierAgent": ("src.agents.verifier_agent", "VerifierAgent"),
    "MultiAgentOrchestrator": ("src.agents.multi_agent_orchestrator", "MultiAgentOrchestrator"),
    "Planner": ("src.agents.planner", "Planner"),
    "Analyst": ("src.agents.analyst", "Analyst"),
    "Writer": ("src.agents.writer", "Writer"),
    "Verifier": ("src.agents.verifier", "Verifier"),
    "Orchestrator": ("src.agents.orchestrator", "Orchestrator"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    module = __import__(module_name, fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
