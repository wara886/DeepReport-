"""LLM-powered planning agent for financial research workflows."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.models import ModelAdapter


ALLOWED_TASK_TYPES = {
    "deep_researcher",
    "browser",
    "deep_analyze",
    "final_answer",
    "verifier",
}


PLANNING_SYSTEM_PROMPT = """You are PlanningAgent in a financial multi-agent research system.
Create an executable task graph for a financial research report.
Return only valid JSON. Do not include markdown.
Keep tasks concrete, dependency-aware, and suitable for routing to specialist agents.
Allowed task_type values: deep_researcher, browser, deep_analyze, final_answer, verifier.
If there is only one verifier task, make it the last task and depend on final_answer.
"""


class PlanningAgent(BaseAgent):
    """Break a financial research request into specialist agent tasks."""

    def __init__(
        self,
        model: ModelAdapter | None = None,
        tools: Dict[str, Any] | None = None,
        fallback_on_error: bool = True,
    ):
        super().__init__(name="PlanningAgent", model=model, tools=tools)
        self.fallback_on_error = fallback_on_error

    @classmethod
    def from_config(
        cls,
        config_path: str = "configs/model_backends.yaml",
        fallback_on_error: bool = True,
    ) -> "PlanningAgent":
        return cls(
            model=ModelAdapter.from_config(config_path=config_path),
            fallback_on_error=fallback_on_error,
        )

    def get_capabilities(self) -> List[str]:
        return [
            "decompose financial research requests into executable task graphs",
            "route tasks to researcher, browser, analyst, final answer, and verifier agents",
            "define task dependencies, priorities, and expected outputs",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        topic = str(task.parameters.get("research_topic") or task.description)
        requirements = task.parameters.get("requirements", [])
        output_format = str(task.parameters.get("output_format", "markdown and html report"))
        conversation_brief = str(task.parameters.get("conversation_brief", "")).strip()
        try:
            if bool(task.parameters.get("force_fallback_plan", False)):
                plan = self._fallback_plan(
                    topic,
                    requirements if isinstance(requirements, list) else [str(requirements)],
                    output_format,
                    reason="forced_fast_mode",
                )
                return self.success(task, {"plan": plan}, metadata={"fallback_used": True, "forced_fast_mode": True})
            plan = self.build_research_plan(
                research_topic=topic,
                requirements=requirements if isinstance(requirements, list) else [str(requirements)],
                output_format=output_format,
                conversation_brief=conversation_brief,
            )
            return self.success(task, {"plan": plan}, metadata={"fallback_used": bool(plan.get("fallback_used"))})
        except Exception as exc:
            return self.failure(task, str(exc))

    def build_research_plan(
        self,
        research_topic: str,
        requirements: List[str] | None = None,
        output_format: str = "markdown and html report",
        conversation_brief: str = "",
    ) -> Dict[str, Any]:
        requirements = requirements or []
        if not self.model:
            return self._fallback_plan(research_topic, requirements, output_format, reason="model_not_configured")

        prompt = _build_planning_prompt(
            research_topic=research_topic,
            requirements=requirements,
            output_format=output_format,
            conversation_brief=conversation_brief,
        )
        try:
            raw_plan = self.model.generate_json(
                prompt=prompt,
                system_prompt=PLANNING_SYSTEM_PROMPT,
                extra_body={"max_tokens": 1600},
            )
            return normalize_research_plan(raw_plan, research_topic, requirements, output_format)
        except Exception as exc:
            if not self.fallback_on_error:
                raise
            return self._fallback_plan(research_topic, requirements, output_format, reason=str(exc))

    def _fallback_plan(
        self,
        research_topic: str,
        requirements: List[str],
        output_format: str,
        reason: str,
    ) -> Dict[str, Any]:
        plan = build_default_research_plan(
            research_topic=research_topic,
            requirements=requirements,
            output_format=output_format,
        )
        plan["fallback_used"] = True
        plan["fallback_reason"] = reason
        return plan


def _build_planning_prompt(
    research_topic: str,
    requirements: List[str],
    output_format: str,
    conversation_brief: str = "",
) -> str:
    memory_block = f"\nConversation memory:\n{conversation_brief}\n" if conversation_brief else ""
    return f"""
Research topic:
{research_topic}

Requirements:
{requirements}
{memory_block}

Output format:
{output_format}

Return a JSON object with exactly these top-level fields:
- overview: string
- tasks: array of task objects
- data_sources: array of strings
- citations_required: boolean
- final_outputs: array of strings

Each task object must contain:
- task_id: stable id like task_001
- task_type: one of deep_researcher, browser, deep_analyze, final_answer, verifier
- description: concrete instruction for the specialist agent
- parameters: object
- dependencies: array of task_id strings
- priority: integer from 1 to 5, where 5 is highest
- expected_output: string

Design a practical first version for a financial multi-agent report system.
""".strip()


def normalize_research_plan(
    raw_plan: Dict[str, Any],
    research_topic: str,
    requirements: List[str],
    output_format: str,
) -> Dict[str, Any]:
    """Normalize an LLM plan into the project contract."""

    tasks = raw_plan.get("tasks", [])
    if not isinstance(tasks, list) or not tasks:
        return build_default_research_plan(
            research_topic=research_topic,
            requirements=requirements,
            output_format=output_format,
        )

    normalized_tasks = []
    known_ids: set[str] = set()
    for index, item in enumerate(tasks, start=1):
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or f"task_{index:03d}")
        task_type = str(item.get("task_type") or "").strip()
        if task_type not in ALLOWED_TASK_TYPES:
            task_type = _infer_task_type(index)
        known_ids.add(task_id)
        normalized_tasks.append(
            {
                "task_id": task_id,
                "task_type": task_type,
                "description": str(item.get("description") or f"Execute {task_type} step."),
                "parameters": item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
                "dependencies": [
                    str(dep)
                    for dep in item.get("dependencies", [])
                    if str(dep) in known_ids or isinstance(dep, str)
                ],
                "priority": _clamp_priority(item.get("priority", 3)),
                "expected_output": str(item.get("expected_output") or ""),
            }
        )

    if not normalized_tasks:
        return build_default_research_plan(research_topic, requirements, output_format)

    normalized_tasks = _make_single_verifier_last(normalized_tasks)
    data_sources = raw_plan.get("data_sources", [])
    final_outputs = raw_plan.get("final_outputs", [])
    return {
        "overview": str(raw_plan.get("overview") or f"Financial research plan for {research_topic}."),
        "research_topic": research_topic,
        "requirements": list(requirements),
        "output_format": output_format,
        "tasks": normalized_tasks,
        "data_sources": data_sources if isinstance(data_sources, list) else [],
        "citations_required": bool(raw_plan.get("citations_required", True)),
        "final_outputs": final_outputs if isinstance(final_outputs, list) else ["report.md", "report.html"],
        "fallback_used": False,
    }


def build_default_research_plan(
    research_topic: str,
    requirements: List[str] | None = None,
    output_format: str = "markdown and html report",
) -> Dict[str, Any]:
    requirements = requirements or []
    return {
        "overview": f"Financial research plan for {research_topic}.",
        "research_topic": research_topic,
        "requirements": list(requirements),
        "output_format": output_format,
        "tasks": [
            {
                "task_id": "task_001",
                "task_type": "deep_researcher",
                "description": "Collect company filings, market data, financial statements, and recent news evidence.",
                "parameters": {"research_topic": research_topic, "requirements": requirements},
                "dependencies": [],
                "priority": 5,
                "expected_output": "Ranked evidence candidates with source metadata.",
            },
            {
                "task_id": "task_002",
                "task_type": "browser",
                "description": "Extract relevant text, tables, and citation snippets from selected sources.",
                "parameters": {"source_types": ["filings", "news", "market_data"]},
                "dependencies": ["task_001"],
                "priority": 4,
                "expected_output": "Structured evidence records with citation anchors.",
            },
            {
                "task_id": "task_003",
                "task_type": "deep_analyze",
                "description": "Analyze financial performance, valuation, risks, trends, and peer context.",
                "parameters": {"analysis_types": ["financials", "valuation", "risk", "trend", "peer_compare"]},
                "dependencies": ["task_001", "task_002"],
                "priority": 5,
                "expected_output": "Evidence-backed claims, metrics, charts, and risk signals.",
            },
            {
                "task_id": "task_004",
                "task_type": "final_answer",
                "description": "Generate the final research report with citations, charts, and structured sections.",
                "parameters": {"output_format": output_format},
                "dependencies": ["task_003"],
                "priority": 4,
                "expected_output": "Markdown, HTML, and JSON report artifacts.",
            },
            {
                "task_id": "task_005",
                "task_type": "verifier",
                "description": "Check claim support, numeric consistency, citation coverage, and report completeness.",
                "parameters": {"checks": ["claim_support", "numeric_consistency", "citation_coverage"]},
                "dependencies": ["task_004"],
                "priority": 3,
                "expected_output": "Verification report and fix recommendations.",
            },
        ],
        "data_sources": ["company_filings", "financial_statements", "market_data", "news", "local_evidence_store"],
        "citations_required": True,
        "final_outputs": ["task_plan.json", "claims.json", "report.md", "report.html", "verification_report.json"],
        "fallback_used": False,
    }


def _infer_task_type(index: int) -> str:
    fallback_order = ["deep_researcher", "browser", "deep_analyze", "final_answer", "verifier"]
    return fallback_order[min(index - 1, len(fallback_order) - 1)]


def _clamp_priority(value: Any) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return 3
    return max(1, min(priority, 5))


def _make_single_verifier_last(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    verifier_indexes = [idx for idx, task in enumerate(tasks) if task.get("task_type") == "verifier"]
    final_indexes = [idx for idx, task in enumerate(tasks) if task.get("task_type") == "final_answer"]
    if len(verifier_indexes) != 1 or not final_indexes:
        return tasks

    verifier = dict(tasks[verifier_indexes[0]])
    final_task = dict(tasks[final_indexes[-1]])
    verifier_id = str(verifier["task_id"])
    final_id = str(final_task["task_id"])
    if verifier_id in final_task.get("dependencies", []):
        final_task["dependencies"] = [dep for dep in final_task["dependencies"] if dep != verifier_id]
        for dep in verifier.get("dependencies", []):
            if dep != final_id and dep not in final_task["dependencies"]:
                final_task["dependencies"].append(dep)
    if final_id not in verifier.get("dependencies", []):
        verifier["dependencies"] = list(verifier.get("dependencies", [])) + [final_id]

    rebuilt = []
    for idx, task in enumerate(tasks):
        if idx == verifier_indexes[0]:
            continue
        if idx == final_indexes[-1]:
            rebuilt.append(final_task)
        else:
            rebuilt.append(task)
    rebuilt.append(verifier)
    return rebuilt
