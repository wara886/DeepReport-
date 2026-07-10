"""Collaborative multi-agent orchestrator entrypoint.

This class keeps the legacy dynamic/static orchestrator intact while exposing a
named entrypoint whose default execution mode uses dedicated role agents,
blackboard ownership, pre-write criticism, and responsibility-aware rework.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator


class CollaborativeOrchestrator(MultiAgentOrchestrator):
    """Run the collaborative company-report workflow by default."""

    def run(
        self,
        research_topic: str,
        symbol: str = "AAPL",
        period: str = "2025Q4",
        requirements: List[str] | None = None,
        execution_mode: str = "collaborative",
        fast: bool = False,
        search_engines: List[str] | None = None,
        retrieval_ranking_mode: str = "hybrid_rerank",
        enable_remote_data: bool = False,
        data_source_config_path: str = "configs/data_sources.yaml",
        quality_remediation_plan: Dict[str, Any] | None = None,
    ) -> Dict[str, str]:
        return super().run(
            research_topic=research_topic,
            symbol=symbol,
            period=period,
            requirements=requirements,
            execution_mode=execution_mode,
            fast=fast,
            search_engines=search_engines,
            retrieval_ranking_mode=retrieval_ranking_mode,
            enable_remote_data=enable_remote_data,
            data_source_config_path=data_source_config_path,
            quality_remediation_plan=quality_remediation_plan,
        )
