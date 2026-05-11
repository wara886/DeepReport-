"""Multi-agent orchestration entrypoint for financial research reports."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Dict, List

from src.agents.base_agent import AgentStatus, AgentTask, TaskResult
from src.agents.browser_agent import BrowserAgent
from src.agents.context_packer import build_revision_brief
from src.agents.conversation_memory import (
    absorb_verifier_feedback,
    build_initial_conversation_state,
    refresh_conversation_brief,
)
from src.agents.deep_analyze_agent import DeepAnalyzeAgent
from src.agents.deep_researcher_agent import DeepResearcherAgent
from src.agents.final_answer_agent import FinalAnswerAgent
from src.agents.planning_agent import PlanningAgent
from src.agents.verifier_agent import VerifierAgent
from src.data.company_universe import resolve_company_identifier, resolve_company_identifier_with_diagnostics
from src.evaluation.multimodal_consistency import audit_multimodal_consistency
from src.models import ModelAdapter
from src.report import (
    append_compliance_disclosures,
    append_compliance_disclosures_to_html,
    attach_charts_to_html,
    attach_charts_to_markdown,
    audit_chart_consistency,
    build_citation_artifacts,
    generate_report_charts,
    polish_report_html,
    render_professional_html_report,
)
from src.search import SearchManager
from src.tools import build_core_tool_registry
from src.utils import MCPManager


FAST_PROFILE = {
    "research_topk": 6,
    "research_use_react": False,
    "research_react_max_steps": 2,
    "research_use_chunks": True,
    "browser_skip_llm_extract": True,
    "browser_use_reader": False,
    "browser_use_playwright": False,
    "browser_reader_max_records": 1,
    "browser_reader_max_chars": 1200,
    "browser_max_llm_records": 4,
    "analyze_max_records": 8,
    "analyze_content_limit": 450,
    "analyze_max_tokens": 1200,
    "analyze_use_react": False,
    "analyze_react_max_steps": 2,
    "final_max_claims": 10,
    "final_max_evidence": 8,
    "final_evidence_content_limit": 350,
    "final_max_tokens": 1600,
    "verifier_max_rework_rounds": 1,
}

DEFAULT_PROFILE = {
    "research_topk": 12,
    "research_use_react": True,
    "research_react_max_steps": 3,
    "research_use_chunks": True,
    "browser_skip_llm_extract": False,
    "browser_use_reader": True,
    "browser_use_playwright": False,
    "browser_reader_max_records": 3,
    "browser_reader_max_chars": 2500,
    "browser_max_llm_records": 6,
    "analyze_max_records": 12,
    "analyze_content_limit": 900,
    "analyze_max_tokens": 1800,
    "analyze_use_react": True,
    "analyze_react_max_steps": 3,
    "final_max_claims": 20,
    "final_max_evidence": 12,
    "final_evidence_content_limit": 600,
    "final_max_tokens": 2200,
    "verifier_max_rework_rounds": 1,
}


class MultiAgentOrchestrator:
    """Run the first visible financial multi-agent workflow."""

    def __init__(
        self,
        output_dir: str = "data/outputs/multi_agent",
        report_dir: str = "data/reports/multi_agent",
        config_path: str = "configs/model_backends.yaml",
        raw_data_root: str = "data/raw/real_data",
        model: ModelAdapter | None = None,
        search_manager: SearchManager | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)
        self.config_path = config_path
        self.raw_data_root = raw_data_root
        self.model = model or ModelAdapter.from_config(config_path=config_path)
        self.tool_registry = build_core_tool_registry()
        self.mcp_manager = MCPManager.from_tool_registry(self.tool_registry, namespace="finance")
        self.search_manager = search_manager or SearchManager.with_local_sources()
        self.agents = {
            "planning": PlanningAgent(model=self.model),
            "research": DeepResearcherAgent(model=self.model, search_manager=self.search_manager),
            "browser": BrowserAgent(model=self.model),
            "analyze": DeepAnalyzeAgent(model=self.model, tool_registry=self.tool_registry),
            "final_answer": FinalAnswerAgent(model=self.model),
            "verifier": VerifierAgent(model=self.model),
        }
        self.trace: List[Dict[str, Any]] = []

    def run(
        self,
        research_topic: str,
        symbol: str = "AAPL",
        period: str = "2025Q4",
        requirements: List[str] | None = None,
        execution_mode: str = "dynamic",
        fast: bool = False,
        search_engines: List[str] | None = None,
        retrieval_ranking_mode: str = "hybrid_rerank",
    ) -> Dict[str, str]:
        entity_resolution = _resolve_run_identity(research_topic=research_topic, symbol=symbol, raw_data_root=self.raw_data_root)
        symbol = str(entity_resolution.get("resolved_symbol") or symbol).upper()
        if execution_mode == "dynamic":
            return self._run_dynamic(
                research_topic=research_topic,
                symbol=symbol,
                period=period,
                requirements=requirements,
                fast=fast,
                search_engines=search_engines,
                retrieval_ranking_mode=retrieval_ranking_mode,
                entity_resolution=entity_resolution,
            )
        if execution_mode == "static":
            return self._run_static(
                research_topic=research_topic,
                symbol=symbol,
                period=period,
                requirements=requirements,
                search_engines=search_engines,
                retrieval_ranking_mode=retrieval_ranking_mode,
                entity_resolution=entity_resolution,
            )
        raise ValueError(f"Unsupported execution_mode: {execution_mode}")

    def _run_static(
        self,
        research_topic: str,
        symbol: str = "AAPL",
        period: str = "2025Q4",
        requirements: List[str] | None = None,
        fast: bool = False,
        search_engines: List[str] | None = None,
        retrieval_ranking_mode: str = "hybrid_rerank",
        entity_resolution: Dict[str, Any] | None = None,
    ) -> Dict[str, str]:
        self.trace = []
        run_started_at = time.perf_counter()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        entity_resolution = entity_resolution or _resolve_run_identity(
            research_topic=research_topic,
            symbol=symbol,
            raw_data_root=self.raw_data_root,
        )
        requirements = requirements or [
            "覆盖收入、利润率、现金流、风险、市场表现和近期新闻",
            "所有关键结论必须绑定 evidence_id",
            "输出 Markdown、HTML、JSON、trace 和验证报告",
        ]
        conversation = build_initial_conversation_state(
            research_topic=research_topic,
            requirements=requirements,
            symbol=symbol,
            period=period,
        )
        conversation_brief = conversation.context_brief()

        planning_result = self._execute(
            "planning",
            AgentTask(
                task_id="task_000_planning",
                task_type="planning",
                description=research_topic,
                parameters={
                    "research_topic": research_topic,
                    "requirements": requirements,
                    "output_format": "markdown, html, json with citations",
                    "force_fallback_plan": bool(fast),
                    "conversation_brief": conversation_brief,
                },
                priority=5,
            ),
        )
        plan = planning_result.output.get("plan", {})
        self._write_json("task_plan.json", plan)

        research_query = _query_from_plan(plan=plan, research_topic=research_topic, symbol=symbol, period=period)
        research_result = self._execute(
            "research",
            AgentTask(
                task_id="task_001_research",
                task_type="deep_researcher",
                description="Collect local and searchable evidence for the report.",
                parameters={
                    "query": research_query,
                    "symbol": symbol,
                    "period": period,
                    "topk": 12,
                    "engines": search_engines or ["local_real_data", "tavily", "local_evidence"],
                    "raw_data_root": self.raw_data_root,
                    "ranking_mode": retrieval_ranking_mode,
                },
                dependencies=["task_000_planning"],
                priority=5,
            ),
        )
        evidence_candidates = research_result.output.get("evidence_candidates", [])

        browser_result = self._execute(
            "browser",
            AgentTask(
                task_id="task_002_browser",
                task_type="browser",
                description="Normalize evidence candidates into citation-ready records.",
                parameters={"evidence_candidates": evidence_candidates},
                dependencies=["task_001_research"],
                priority=4,
            ),
        )
        evidence_records = browser_result.output.get("evidence_records", [])
        self._write_json("evidence.json", evidence_records)

        analyze_result = self._execute(
            "analyze",
            AgentTask(
                task_id="task_003_analyze",
                task_type="deep_analyze",
                description="Generate financial claims from evidence records.",
                parameters={"evidence_records": evidence_records, "symbol": symbol, "period": period, "raw_data_root": self.raw_data_root},
                dependencies=["task_002_browser"],
                priority=5,
            ),
        )
        claims = analyze_result.output.get("claims", [])
        analysis_artifacts = analyze_result.output.get("analysis_artifacts", {})
        self._write_json("claims.json", claims)
        self._write_json("analysis_artifacts.json", analysis_artifacts)
        financial_metrics_path = self._write_json(
            "financial_metrics.json",
            analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        tables_path = self._write_json(
            "tables.json",
            analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
        )

        final_result = self._execute(
            "final_answer",
            AgentTask(
                task_id="task_004_final_answer",
                task_type="final_answer",
                description="Write final report.",
                parameters={
                    "research_topic": research_topic,
                    "claims": claims,
                    "evidence_records": evidence_records,
                    "conversation_brief": conversation_brief,
                },
                dependencies=["task_003_analyze"],
                priority=4,
            ),
        )
        markdown = str(final_result.output.get("markdown", ""))
        html = str(final_result.output.get("html", ""))
        report_json = final_result.output.get("report_json", {})
        charts = generate_report_charts(
            claims=claims,
            evidence_records=evidence_records,
            output_dir=self.output_dir / "charts",
            tables=analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
        )
        markdown = attach_charts_to_markdown(markdown, charts)
        html = polish_report_html(attach_charts_to_html(html, charts))
        citation_artifacts = build_citation_artifacts(
            evidence_records=evidence_records,
            claims=claims,
            markdown=markdown,
            html=html,
        )
        markdown = citation_artifacts["markdown"]
        citations = citation_artifacts["citations"]
        html = render_professional_html_report(
            markdown=markdown,
            title=research_topic,
            charts=charts,
            citations=citations,
        )
        markdown = append_compliance_disclosures(markdown, citations=citations)
        html = append_compliance_disclosures_to_html(html, citations=citations)
        if isinstance(report_json, dict):
            report_json = dict(report_json)
            report_json["citations"] = citations
            report_json["charts"] = charts
            report_json["compliance_disclosure"] = {"included": True, "rating_definition": "未评级"}
            report_json["analysis_artifacts"] = analysis_artifacts
        self._write_json("citations.json", citations)
        self._write_json("charts.json", charts)
        chart_consistency = audit_chart_consistency(
            charts=charts,
            claims=claims,
            evidence_records=evidence_records,
            markdown=markdown,
            require_files=True,
        )
        self._write_json("chart_consistency.json", chart_consistency)
        multimodal_consistency = audit_multimodal_consistency(
            charts=charts,
            tables=analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
            claims=claims,
            evidence_records=evidence_records,
            markdown=markdown,
            require_files=True,
        )
        self._write_json("multimodal_consistency.json", multimodal_consistency)
        mcp_manifest_path = self.mcp_manager.export_manifest(self.output_dir / "mcp_manifest.json")
        citations_md_path = self.output_dir / "citations.md"
        citations_md_path.write_text(citation_artifacts["citations_markdown"], encoding="utf-8")
        report_md_path = self.report_dir / "report.md"
        report_html_path = self.report_dir / "report.html"
        report_json_path = self.report_dir / "report.json"
        report_md_path.write_text(markdown, encoding="utf-8")
        report_html_path.write_text(html, encoding="utf-8")
        report_json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")

        verifier_result = self._execute(
            "verifier",
            AgentTask(
                task_id="task_005_verifier",
                task_type="verifier",
                description="Verify the final report.",
                parameters={
                    "claims": claims,
                    "markdown": markdown,
                    "evidence_records": evidence_records,
                    "charts": charts,
                    "tables": analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
                    "conversation_brief": conversation_brief,
                    "expected_symbol": symbol,
                    "entity_resolution": entity_resolution,
                },
                dependencies=["task_004_final_answer"],
                priority=3,
            ),
        )
        verification_report = verifier_result.output.get("verification_report", {})
        conversation.add_verifier_feedback(verification_report)
        conversation_brief = conversation.context_brief()
        conversation_path = self._write_json("conversation_context.json", conversation.to_dict())
        verification_path = self.output_dir / "verification_report.json"
        verification_path.write_text(json.dumps(verification_report, ensure_ascii=False, indent=2), encoding="utf-8")

        trace_path = self.output_dir / "task_trace.jsonl"
        trace_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in self.trace) + "\n",
            encoding="utf-8",
        )

        summary_path = self.output_dir / "run_summary.json"
        summary = {
            "research_topic": research_topic,
            "symbol": symbol,
            "period": period,
            "model": self.model.model_name,
            "execution_mode": "static",
            "agent_count": len(self.agents),
            "trace_count": len(self.trace),
            "evidence_count": len(evidence_records) if isinstance(evidence_records, list) else 0,
            "claim_count": len(claims) if isinstance(claims, list) else 0,
            "citation_count": len(citations) if isinstance(citations, list) else 0,
            "chart_count": len(charts) if isinstance(charts, list) else 0,
            "multimodal_consistency_passed": bool(multimodal_consistency.get("passed", False)),
            "mcp_tool_count": len(self.mcp_manager.list_tools()),
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "verification_passed": bool(verification_report.get("passed", False)),
            "entity_resolution": entity_resolution,
            "conversation_brief_chars": len(conversation_brief),
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_trace": str(trace_path),
            "evidence": str(self.output_dir / "evidence.json"),
            "claims": str(self.output_dir / "claims.json"),
            "analysis_artifacts": str(self.output_dir / "analysis_artifacts.json"),
            "financial_metrics": str(financial_metrics_path),
            "tables": str(tables_path),
            "citations": str(self.output_dir / "citations.json"),
            "citations_md": str(citations_md_path),
            "charts": str(self.output_dir / "charts.json"),
            "chart_consistency": str(self.output_dir / "chart_consistency.json"),
            "multimodal_consistency": str(self.output_dir / "multimodal_consistency.json"),
            "mcp_manifest": str(mcp_manifest_path),
            "report_md": str(report_md_path),
            "report_html": str(report_html_path),
            "report_json": str(report_json_path),
            "verification_report": str(verification_path),
            "conversation_context": str(conversation_path),
            "run_summary": str(summary_path),
        }

    def _run_dynamic(
        self,
        research_topic: str,
        symbol: str = "AAPL",
        period: str = "2025Q4",
        requirements: List[str] | None = None,
        fast: bool = False,
        search_engines: List[str] | None = None,
        retrieval_ranking_mode: str = "hybrid_rerank",
        entity_resolution: Dict[str, Any] | None = None,
    ) -> Dict[str, str]:
        self.trace = []
        run_started_at = time.perf_counter()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        entity_resolution = entity_resolution or _resolve_run_identity(
            research_topic=research_topic,
            symbol=symbol,
            raw_data_root=self.raw_data_root,
        )
        requirements = requirements or [
            "覆盖收入、利润率、现金流、风险、市场表现和近期新闻",
            "所有关键结论必须绑定 evidence_id",
            "输出 Markdown、HTML、JSON、trace 和验证报告",
        ]
        conversation = build_initial_conversation_state(
            research_topic=research_topic,
            requirements=requirements,
            symbol=symbol,
            period=period,
        )
        conversation_brief = conversation.context_brief()

        planning_result = self._execute(
            "planning",
            AgentTask(
                task_id="task_000_planning",
                task_type="planning",
                description=research_topic,
                parameters={
                    "research_topic": research_topic,
                    "requirements": requirements,
                    "output_format": "markdown, html, json with citations",
                    "conversation_brief": conversation_brief,
                },
                priority=5,
            ),
        )
        plan = planning_result.output.get("plan", {})
        self._write_json("task_plan.json", plan)

        state: Dict[str, Any] = {
            "research_topic": research_topic,
            "symbol": symbol,
            "period": period,
            "evidence_candidates": [],
            "evidence_records": [],
            "search_meta": {},
            "claims": [],
            "analysis_artifacts": {},
            "markdown": "",
            "html": "",
            "report_json": {},
            "citations": [],
            "citations_markdown": "",
            "charts": [],
            "chart_output_dir": str(self.output_dir / "charts"),
            "verification_report": {},
            "revision_history": [],
            "conversation_context": conversation.to_dict(),
            "conversation_brief": conversation_brief,
            "performance_profile": "fast" if fast else "default",
            "search_engines": search_engines or [],
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "entity_resolution": entity_resolution,
        }
        tasks = prepare_dynamic_tasks(
            plan=plan,
            research_topic=research_topic,
            symbol=symbol,
            period=period,
            raw_data_root=self.raw_data_root,
            profile=FAST_PROFILE if fast else DEFAULT_PROFILE,
            search_engines=search_engines,
            retrieval_ranking_mode=retrieval_ranking_mode,
        )
        results = self._execute_dynamic_tasks(tasks=tasks, state=state)
        self._run_verifier_rework_loop(state=state)

        evidence_records = state["evidence_records"]
        claims = state["claims"]
        self._write_json("search_meta.json", state.get("search_meta", {}))
        self._write_json("evidence.json", evidence_records)
        self._write_json("claims.json", claims)
        self._write_json("analysis_artifacts.json", state.get("analysis_artifacts", {}))
        analysis_artifacts = state.get("analysis_artifacts", {})
        financial_metrics_path = self._write_json(
            "financial_metrics.json",
            analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        tables_path = self._write_json(
            "tables.json",
            analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
        )
        self._write_json("citations.json", state.get("citations", []))
        self._write_json("charts.json", state.get("charts", []))
        chart_consistency = audit_chart_consistency(
            charts=list(state.get("charts", [])),
            claims=list(claims),
            evidence_records=list(evidence_records),
            markdown=str(state.get("markdown", "")),
            require_files=True,
        )
        self._write_json("chart_consistency.json", chart_consistency)
        multimodal_consistency = audit_multimodal_consistency(
            charts=list(state.get("charts", [])),
            tables=analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
            claims=list(claims),
            evidence_records=list(evidence_records),
            markdown=str(state.get("markdown", "")),
            require_files=True,
        )
        self._write_json("multimodal_consistency.json", multimodal_consistency)
        self._write_json("revision_history.json", state.get("revision_history", []))
        conversation_path = self._write_json("conversation_context.json", state.get("conversation_context", {}))
        mcp_manifest_path = self.mcp_manager.export_manifest(self.output_dir / "mcp_manifest.json")
        citations_md_path = self.output_dir / "citations.md"
        citations_md_path.write_text(str(state.get("citations_markdown", "")), encoding="utf-8")

        report_md_path = self.report_dir / "report.md"
        report_html_path = self.report_dir / "report.html"
        report_json_path = self.report_dir / "report.json"
        report_md_path.write_text(str(state.get("markdown", "")), encoding="utf-8")
        report_html_path.write_text(str(state.get("html", "")), encoding="utf-8")
        report_json_path.write_text(
            json.dumps(state.get("report_json", {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        verification_path = self.output_dir / "verification_report.json"
        verification_path.write_text(
            json.dumps(state.get("verification_report", {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        trace_path = self.output_dir / "task_trace.jsonl"
        trace_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in self.trace) + "\n",
            encoding="utf-8",
        )

        summary_path = self.output_dir / "run_summary.json"
        summary = {
            "research_topic": research_topic,
            "symbol": symbol,
            "period": period,
            "model": self.model.model_name,
            "execution_mode": "dynamic",
            "performance_profile": "fast" if fast else "default",
            "agent_count": len(self.agents),
            "planned_task_count": len(tasks),
            "completed_task_count": len(results),
            "trace_count": len(self.trace),
            "evidence_count": len(evidence_records) if isinstance(evidence_records, list) else 0,
            "claim_count": len(claims) if isinstance(claims, list) else 0,
            "citation_count": len(state.get("citations", [])) if isinstance(state.get("citations"), list) else 0,
            "chart_count": len(state.get("charts", [])) if isinstance(state.get("charts"), list) else 0,
            "multimodal_consistency_passed": bool(multimodal_consistency.get("passed", False)),
            "mcp_tool_count": len(self.mcp_manager.list_tools()),
            "search_engines": state.get("search_meta", {}).get("engines", []),
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "revision_rounds": len(state.get("revision_history", [])) if isinstance(state.get("revision_history"), list) else 0,
            "verification_passed": bool(state.get("verification_report", {}).get("passed", False)),
            "entity_resolution": entity_resolution,
            "conversation_brief_chars": len(str(state.get("conversation_brief", ""))),
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_trace": str(trace_path),
            "search_meta": str(self.output_dir / "search_meta.json"),
            "evidence": str(self.output_dir / "evidence.json"),
            "claims": str(self.output_dir / "claims.json"),
            "analysis_artifacts": str(self.output_dir / "analysis_artifacts.json"),
            "financial_metrics": str(financial_metrics_path),
            "tables": str(tables_path),
            "citations": str(self.output_dir / "citations.json"),
            "citations_md": str(citations_md_path),
            "charts": str(self.output_dir / "charts.json"),
            "chart_consistency": str(self.output_dir / "chart_consistency.json"),
            "multimodal_consistency": str(self.output_dir / "multimodal_consistency.json"),
            "mcp_manifest": str(mcp_manifest_path),
            "revision_history": str(self.output_dir / "revision_history.json"),
            "conversation_context": str(conversation_path),
            "report_md": str(report_md_path),
            "report_html": str(report_html_path),
            "report_json": str(report_json_path),
            "verification_report": str(verification_path),
            "run_summary": str(summary_path),
        }

    def _execute_dynamic_tasks(self, tasks: List[AgentTask], state: Dict[str, Any]) -> Dict[str, TaskResult]:
        pending = {task.task_id: task for task in tasks}
        results: Dict[str, TaskResult] = {}
        while pending:
            ready = [
                task
                for task in pending.values()
                if all(dep in results for dep in task.dependencies)
            ]
            if not ready:
                blocked = {task_id: task.dependencies for task_id, task in pending.items()}
                raise RuntimeError(f"dynamic task graph is blocked by unresolved dependencies: {blocked}")

            ready.sort(key=lambda task: (_task_type_order(task.task_type), -task.priority, task.task_id))
            task = ready[0]
            enriched = enrich_task_parameters(
                task=task,
                state=state,
                raw_data_root=self.raw_data_root,
                profile=FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE,
            )
            result = self._execute(agent_key_for_task(enriched.task_type), enriched)
            results[enriched.task_id] = result
            merge_task_result(state=state, task_type=enriched.task_type, result=result)
            if enriched.task_type == "verifier":
                absorb_verifier_feedback(state)
            del pending[enriched.task_id]
        return results

    def _execute(self, agent_key: str, task: AgentTask) -> TaskResult:
        agent = self.agents[agent_key]
        started_at = time.perf_counter()
        result = agent.execute_task(task)
        duration_sec = round(time.perf_counter() - started_at, 3)
        self.trace.append(
            {
                "agent": agent.name,
                "task": task.to_dict(),
                "status": result.status.value,
                "error": result.error,
                "output_keys": sorted(result.output.keys()),
                "metadata": result.metadata,
                "duration_sec": duration_sec,
            }
        )
        if result.status != AgentStatus.COMPLETED:
            raise RuntimeError(f"{agent.name} failed: {result.error}")
        return result

    def _run_verifier_rework_loop(self, state: Dict[str, Any]) -> None:
        profile = FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE
        max_rounds = int(profile.get("verifier_max_rework_rounds", 1) or 0)
        verification_report = state.get("verification_report", {})
        if max_rounds <= 0 or not isinstance(verification_report, dict):
            return

        for round_index in range(1, max_rounds + 1):
            verification_report = state.get("verification_report", {})
            if not isinstance(verification_report, dict) or verification_report.get("passed", False):
                break

            revision_request = build_revision_brief(verification_report)
            if not revision_request:
                break
            conversation_brief = refresh_conversation_brief(state)

            final_result = self._execute(
                "final_answer",
                AgentTask(
                    task_id=f"task_rework_{round_index:03d}_final_answer",
                    task_type="final_answer",
                    description="Revise report using verifier feedback.",
                    parameters={
                        "research_topic": state.get("research_topic", ""),
                        "claims": list(state.get("claims", [])),
                        "evidence_records": list(state.get("evidence_records", [])),
                        "revision_request": revision_request,
                        "verification_report": verification_report,
                        "prior_markdown": str(state.get("markdown", "")),
                        "conversation_brief": conversation_brief,
                        "max_claims": int(profile["final_max_claims"]),
                        "max_evidence": int(profile["final_max_evidence"]),
                        "evidence_content_limit": int(profile["final_evidence_content_limit"]),
                        "max_tokens": int(profile["final_max_tokens"]),
                    },
                    dependencies=[],
                    priority=5,
                ),
            )
            merge_task_result(state=state, task_type="final_answer", result=final_result)

            verify_result = self._execute(
                "verifier",
                AgentTask(
                    task_id=f"task_rework_{round_index:03d}_verifier",
                    task_type="verifier",
                    description="Re-verify revised report.",
                    parameters={
                        "claims": list(state.get("claims", [])),
                        "markdown": str(state.get("markdown", "")),
                        "evidence_records": list(state.get("evidence_records", [])),
                        "charts": list(state.get("charts", [])),
                        "tables": dict(state.get("analysis_artifacts", {})).get("tables", []),
                        "conversation_brief": refresh_conversation_brief(state),
                        "expected_symbol": str(state.get("symbol", "")),
                        "entity_resolution": dict(state.get("entity_resolution", {}))
                        if isinstance(state.get("entity_resolution"), dict)
                        else {},
                    },
                    dependencies=[],
                    priority=5,
                ),
            )
            merge_task_result(state=state, task_type="verifier", result=verify_result)
            absorb_verifier_feedback(state)
            state.setdefault("revision_history", []).append(
                {
                    "round": round_index,
                    "revision_request": revision_request,
                    "passed_after_round": bool(state.get("verification_report", {}).get("passed", False)),
                }
            )

    def _write_json(self, file_name: str, payload: Any) -> Path:
        path = self.output_dir / file_name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def _query_from_plan(plan: Dict[str, Any], research_topic: str, symbol: str, period: str) -> str:
    tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
    descriptions = []
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict) and task.get("task_type") == "deep_researcher":
                descriptions.append(str(task.get("description", "")))
    base = " ".join(descriptions[:2]).strip() or research_topic
    return f"{symbol} {period} {base}"


def prepare_dynamic_tasks(
    plan: Dict[str, Any],
    research_topic: str,
    symbol: str,
    period: str,
    raw_data_root: str,
    profile: Dict[str, Any] | None = None,
    search_engines: List[str] | None = None,
    retrieval_ranking_mode: str = "hybrid_rerank",
) -> List[AgentTask]:
    profile = profile or DEFAULT_PROFILE
    raw_tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
    tasks: List[AgentTask] = []
    for index, item in enumerate(raw_tasks, start=1):
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or f"task_{index:03d}")
        task_type = str(item.get("task_type") or "").strip()
        if task_type not in {"deep_researcher", "browser", "deep_analyze", "final_answer", "verifier"}:
            continue
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        tasks.append(
            AgentTask(
                task_id=task_id,
                task_type=task_type,
                description=str(item.get("description") or f"Execute {task_type}."),
                parameters=dict(params),
                dependencies=[str(dep) for dep in item.get("dependencies", [])],
                priority=int(item.get("priority", 3) or 3),
                metadata={"expected_output": str(item.get("expected_output", ""))},
            )
        )

    tasks = ensure_minimum_task_graph(tasks, research_topic=research_topic, symbol=symbol, period=period)
    tasks = apply_implicit_dependencies(tasks)

    cleaned_ids = {task.task_id for task in tasks}
    cleaned = []
    for task in tasks:
        params = dict(task.parameters)
        if task.task_type == "deep_researcher":
            params.setdefault("query", f"{symbol} {period} {task.description}")
            params["symbol"] = symbol
            params["period"] = period
            params.setdefault("topk", int(profile["research_topk"]))
            params.setdefault("engines", search_engines or ["local_real_data", "tavily", "local_evidence"])
            params.setdefault("raw_data_root", raw_data_root)
            params.setdefault("ranking_mode", retrieval_ranking_mode)
        cleaned.append(
            AgentTask(
                task_id=task.task_id,
                task_type=task.task_type,
                description=task.description,
                parameters=params,
                dependencies=[dep for dep in task.dependencies if dep in cleaned_ids],
                priority=task.priority,
                metadata=dict(task.metadata),
            )
        )
    return cleaned


def ensure_minimum_task_graph(
    tasks: List[AgentTask],
    research_topic: str,
    symbol: str,
    period: str,
) -> List[AgentTask]:
    output = list(tasks)
    existing_types = {task.task_type for task in output}

    if "deep_researcher" not in existing_types:
        output.append(
            AgentTask(
                task_id=_new_task_id(output, "research"),
                task_type="deep_researcher",
                description=f"Collect financial evidence for {symbol} {period}: {research_topic}",
                parameters={"query": f"{symbol} {period} {research_topic}"},
                priority=5,
            )
        )
    if "browser" not in existing_types:
        output.append(
            AgentTask(
                task_id=_new_task_id(output, "browser"),
                task_type="browser",
                description="Normalize collected evidence into citation-ready records.",
                priority=4,
            )
        )
    if "deep_analyze" not in existing_types:
        output.append(
            AgentTask(
                task_id=_new_task_id(output, "analyze"),
                task_type="deep_analyze",
                description="Generate evidence-backed financial claims.",
                priority=5,
            )
        )
    if "final_answer" not in existing_types:
        output.append(
            AgentTask(
                task_id=_new_task_id(output, "final"),
                task_type="final_answer",
                description="Generate final financial research report.",
                priority=4,
            )
        )
    if "verifier" not in existing_types:
        output.append(
            AgentTask(
                task_id=_new_task_id(output, "verify"),
                task_type="verifier",
                description="Verify claim support, citations, and report structure.",
                priority=3,
            )
        )
    return output


def apply_implicit_dependencies(tasks: List[AgentTask]) -> List[AgentTask]:
    by_type: Dict[str, List[str]] = {}
    output: List[AgentTask] = []
    for task in tasks:
        deps = list(task.dependencies)
        if task.task_type == "browser":
            deps.extend(by_type.get("deep_researcher", []))
        elif task.task_type == "deep_analyze":
            deps.extend(by_type.get("browser", []) or by_type.get("deep_researcher", []))
        elif task.task_type == "final_answer":
            deps.extend(by_type.get("deep_analyze", []))
        elif task.task_type == "verifier":
            deps.extend(by_type.get("final_answer", []))

        deduped = []
        for dep in deps:
            if dep != task.task_id and dep not in deduped:
                deduped.append(dep)
        output.append(
            AgentTask(
                task_id=task.task_id,
                task_type=task.task_type,
                description=task.description,
                parameters=dict(task.parameters),
                dependencies=deduped,
                priority=task.priority,
                metadata=dict(task.metadata),
            )
        )
        by_type.setdefault(task.task_type, []).append(task.task_id)
    return output


def enrich_task_parameters(
    task: AgentTask,
    state: Dict[str, Any],
    raw_data_root: str,
    profile: Dict[str, Any] | None = None,
) -> AgentTask:
    profile = profile or DEFAULT_PROFILE
    params = dict(task.parameters)
    if task.task_type == "deep_researcher":
        params.setdefault("query", f"{state['symbol']} {state['period']} {task.description}")
        params["symbol"] = state["symbol"]
        params["period"] = state["period"]
        params.setdefault("topk", int(profile["research_topk"]))
        params.setdefault("use_react", bool(profile.get("research_use_react", False)))
        params.setdefault("react_max_steps", int(profile.get("research_react_max_steps", 3)))
        params.setdefault("use_chunks", bool(profile.get("research_use_chunks", True)))
        params.setdefault("engines", ["local_real_data", "tavily", "local_evidence"])
        params.setdefault("raw_data_root", raw_data_root)
        params.setdefault("ranking_mode", str(state.get("retrieval_ranking_mode", "hybrid_rerank")))
    elif task.task_type == "browser":
        if not params.get("evidence_candidates"):
            params["evidence_candidates"] = list(state.get("evidence_candidates", []))
        params.setdefault("skip_llm_extract", bool(profile["browser_skip_llm_extract"]))
        params.setdefault("use_reader", bool(profile["browser_use_reader"]))
        params.setdefault("use_playwright", bool(profile.get("browser_use_playwright", False)))
        params.setdefault("reader_max_records", int(profile["browser_reader_max_records"]))
        params.setdefault("reader_max_chars", int(profile["browser_reader_max_chars"]))
        params.setdefault("max_llm_records", int(profile["browser_max_llm_records"]))
    elif task.task_type == "deep_analyze":
        if not params.get("evidence_records"):
            params["evidence_records"] = list(state.get("evidence_records", []))
        params.setdefault("symbol", state["symbol"])
        params.setdefault("period", state["period"])
        params.setdefault("raw_data_root", raw_data_root)
        params.setdefault("max_records", int(profile["analyze_max_records"]))
        params.setdefault("content_limit", int(profile["analyze_content_limit"]))
        params.setdefault("max_tokens", int(profile["analyze_max_tokens"]))
        params.setdefault("use_react", bool(profile.get("analyze_use_react", False)))
        params.setdefault("react_max_steps", int(profile.get("analyze_react_max_steps", 3)))
    elif task.task_type == "final_answer":
        params.setdefault("research_topic", state["research_topic"])
        if not params.get("claims"):
            params["claims"] = list(state.get("claims", []))
        if not params.get("evidence_records"):
            params["evidence_records"] = list(state.get("evidence_records", []))
        params.setdefault("max_claims", int(profile["final_max_claims"]))
        params.setdefault("max_evidence", int(profile["final_max_evidence"]))
        params.setdefault("evidence_content_limit", int(profile["final_evidence_content_limit"]))
        params.setdefault("max_tokens", int(profile["final_max_tokens"]))
        params.setdefault("conversation_brief", str(state.get("conversation_brief", "")))
    elif task.task_type == "verifier":
        if not params.get("claims"):
            params["claims"] = list(state.get("claims", []))
        if not params.get("markdown"):
            params["markdown"] = str(state.get("markdown", ""))
        if not params.get("evidence_records"):
            params["evidence_records"] = list(state.get("evidence_records", []))
        if not params.get("charts"):
            params["charts"] = list(state.get("charts", []))
        if not params.get("tables"):
            params["tables"] = dict(state.get("analysis_artifacts", {})).get("tables", [])
        params.setdefault("conversation_brief", str(state.get("conversation_brief", "")))
        params.setdefault("expected_symbol", str(state.get("symbol", "")))
        params.setdefault("entity_resolution", dict(state.get("entity_resolution", {})) if isinstance(state.get("entity_resolution"), dict) else {})

    return AgentTask(
        task_id=task.task_id,
        task_type=task.task_type,
        description=task.description,
        parameters=params,
        dependencies=list(task.dependencies),
        priority=task.priority,
        metadata=dict(task.metadata),
    )


def merge_task_result(state: Dict[str, Any], task_type: str, result: TaskResult) -> None:
    if task_type == "deep_researcher":
        state["evidence_candidates"] = _merge_records(
            state.get("evidence_candidates", []),
            result.output.get("evidence_candidates", []),
            key_names=["result_id", "evidence_id", "sample_id", "url"],
        )
        state["search_meta"] = result.output.get("search_meta", {})
    elif task_type == "browser":
        state["evidence_records"] = _merge_records(
            state.get("evidence_records", []),
            result.output.get("evidence_records", []),
            key_names=["evidence_id", "sample_id", "source_url"],
        )
    elif task_type == "deep_analyze":
        state["claims"] = _merge_records(
            state.get("claims", []),
            result.output.get("claims", []),
            key_names=["claim_id", "claim_text"],
        )
        state["analysis_artifacts"] = result.output.get("analysis_artifacts", {})
    elif task_type == "final_answer":
        markdown = str(result.output.get("markdown", ""))
        html = str(result.output.get("html", ""))
        report_json = result.output.get("report_json", {})
        charts = generate_report_charts(
            claims=list(state.get("claims", [])),
            evidence_records=list(state.get("evidence_records", [])),
            output_dir=str(state.get("chart_output_dir") or "data/outputs/multi_agent/charts"),
            tables=dict(state.get("analysis_artifacts", {})).get("tables", []),
        )
        markdown = attach_charts_to_markdown(markdown, charts)
        html = polish_report_html(attach_charts_to_html(html, charts))
        citation_artifacts = build_citation_artifacts(
            evidence_records=list(state.get("evidence_records", [])),
            claims=list(state.get("claims", [])),
            markdown=markdown,
            html=html,
        )
        state["markdown"] = citation_artifacts["markdown"]
        state["citations"] = citation_artifacts["citations"]
        state["citations_markdown"] = citation_artifacts["citations_markdown"]
        state["charts"] = charts
        state["html"] = render_professional_html_report(
            markdown=state["markdown"],
            title=str(state.get("research_topic") or "金融研究报告"),
            charts=charts,
            citations=state["citations"],
        )
        state["markdown"] = append_compliance_disclosures(state["markdown"], citations=state["citations"])
        state["html"] = append_compliance_disclosures_to_html(state["html"], citations=state["citations"])
        if isinstance(report_json, dict):
            report_json = dict(report_json)
            report_json["citations"] = state["citations"]
            report_json["charts"] = charts
            report_json["compliance_disclosure"] = {"included": True, "rating_definition": "未评级"}
            report_json["analysis_artifacts"] = state.get("analysis_artifacts", {})
        state["report_json"] = report_json
    elif task_type == "verifier":
        state["verification_report"] = result.output.get("verification_report", {})


def agent_key_for_task(task_type: str) -> str:
    mapping = {
        "deep_researcher": "research",
        "browser": "browser",
        "deep_analyze": "analyze",
        "final_answer": "final_answer",
        "verifier": "verifier",
    }
    if task_type not in mapping:
        raise KeyError(f"unsupported dynamic task_type: {task_type}")
    return mapping[task_type]


def _task_type_order(task_type: str) -> int:
    order = {
        "deep_researcher": 10,
        "browser": 20,
        "deep_analyze": 30,
        "final_answer": 40,
        "verifier": 50,
    }
    return order.get(task_type, 99)


def _merge_records(
    existing: Any,
    incoming: Any,
    key_names: List[str],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for collection in [existing, incoming]:
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            key = _record_key(item, key_names)
            if key in seen:
                continue
            seen.add(key)
            records.append(dict(item))
    return records


def _record_key(item: Dict[str, Any], key_names: List[str]) -> str:
    for key in key_names:
        value = item.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def _new_task_id(tasks: List[AgentTask], suffix: str) -> str:
    existing = {task.task_id for task in tasks}
    index = len(tasks) + 1
    while True:
        task_id = f"task_{index:03d}_{suffix}"
        if task_id not in existing:
            return task_id
        index += 1


def _resolve_run_identity(research_topic: str, symbol: str, raw_data_root: str) -> Dict[str, Any]:
    """Resolve default/user-provided company identifiers and keep diagnostics for gates."""

    requested = str(symbol or "").strip()
    topic_resolution = resolve_company_identifier_with_diagnostics(research_topic, raw_data_root=raw_data_root)
    symbol_resolution = resolve_company_identifier_with_diagnostics(requested, raw_data_root=raw_data_root)
    topic_company = resolve_company_identifier(research_topic, raw_data_root=raw_data_root)
    symbol_company = resolve_company_identifier(requested, raw_data_root=raw_data_root)

    use_topic = bool(topic_company) and (not requested or requested.upper() == "AAPL")
    if use_topic:
        resolved_symbol = str(topic_company["symbol"]).upper()
        source = "topic"
    elif symbol_company:
        resolved_symbol = str(symbol_company["symbol"]).upper()
        source = "symbol"
    elif topic_company:
        resolved_symbol = str(topic_company["symbol"]).upper()
        source = "topic_fallback"
    else:
        resolved_symbol = requested.upper() or "AAPL"
        source = "fallback"

    conflict = bool(topic_company and symbol_company and str(topic_company.get("symbol", "")).upper() != str(symbol_company.get("symbol", "")).upper())
    return {
        "requested_symbol": requested,
        "research_topic": research_topic,
        "resolved_symbol": resolved_symbol,
        "resolution_source": source,
        "topic_resolution": topic_resolution,
        "symbol_resolution": symbol_resolution,
        "conflict": conflict,
    }


def _resolve_run_symbol(research_topic: str, symbol: str, raw_data_root: str) -> str:
    """Backward-compatible helper for callers/tests that only need a ticker."""

    identity = _resolve_run_identity(research_topic=research_topic, symbol=symbol, raw_data_root=raw_data_root)
    return str(identity.get("resolved_symbol") or "AAPL").upper()
