"""Legacy planner wrapper.

`build_plan()` keeps the original fixed report-section contract used by the
claim-first smoke pipeline. `build_research_plan()` is the bridge into the new
LLM-powered PlanningAgent task-graph contract.
"""

from __future__ import annotations

from typing import List

from src.agents.planning_agent import PlanningAgent, build_default_research_plan


class Planner:
    """Generate legacy section plans or delegate to the new PlanningAgent."""

    DEFAULT_SECTIONS = [
        ("executive_summary", "执行摘要"),
        ("business_overview", "业务概览"),
        ("financial_analysis", "财务分析"),
        ("valuation", "估值观察"),
        ("risks", "风险评估"),
        ("conclusion", "投资结论"),
    ]

    def __init__(
        self,
        use_llm: bool = False,
        planning_agent: PlanningAgent | None = None,
        config_path: str = "configs/model_backends.yaml",
    ):
        self.planning_agent = planning_agent
        if use_llm and self.planning_agent is None:
            self.planning_agent = PlanningAgent.from_config(config_path=config_path)

    def build_plan(self) -> List[dict]:
        return [
            {"section_name": section_name, "section_title": section_title}
            for section_name, section_title in self.DEFAULT_SECTIONS
        ]

    def build_research_plan(
        self,
        research_topic: str,
        requirements: List[str] | None = None,
        output_format: str = "markdown and html report",
    ) -> dict:
        if self.planning_agent:
            return self.planning_agent.build_research_plan(
                research_topic=research_topic,
                requirements=requirements,
                output_format=output_format,
            )
        return build_default_research_plan(
            research_topic=research_topic,
            requirements=requirements,
            output_format=output_format,
        )
