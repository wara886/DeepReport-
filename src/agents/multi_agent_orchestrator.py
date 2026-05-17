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
from src.agents.durable_memory import DurableMemoryConfig, DurableMemoryStore
from src.agents.final_answer_agent import FinalAnswerAgent
from src.agents.gap_router import build_gap_resolution_trace
from src.agents.planning_agent import PlanningAgent
from src.agents.verifier_agent import VerifierAgent
from src.data.company_universe import resolve_company_identifier, resolve_company_identifier_with_diagnostics
from src.data.pdf_artifacts import build_pdf_artifacts
from src.evaluation.company_report_scorecard import build_company_report_scorecard
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
from src.tools import SkillRegistry, build_core_tool_registry, build_financial_skill_registry
from src.utils.config import load_config
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
    "analyze_max_records": 10,
    "analyze_content_limit": 450,
    "analyze_max_tokens": 1200,
    "analyze_use_react": False,
    "analyze_react_max_steps": 2,
    "final_max_claims": 10,
    "final_max_evidence": 8,
    "final_evidence_content_limit": 350,
    "final_max_tokens": 1600,
    "verifier_max_rework_rounds": 2,
}

DEFAULT_PROFILE = {
    "research_topk": 12,
    "research_use_react": True,
    "research_react_max_steps": 3,
    "research_use_chunks": True,
    "browser_skip_llm_extract": False,
    "browser_use_reader": True,
    "browser_use_playwright": False,
    "browser_reader_max_records": 6,
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
    "verifier_max_rework_rounds": 2,
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
        app_config_path: str = "configs/app.yaml",
        memory_enabled: bool | None = None,
        memory_root: str | None = None,
        memory_max_context_chars: int | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_registry_config_path: str | None = "configs/skill_registry.yaml",
    ):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)
        self.config_path = config_path
        self.raw_data_root = raw_data_root
        self.app_config_path = app_config_path
        self.memory_config = _load_durable_memory_config(
            app_config_path=app_config_path,
            memory_enabled=memory_enabled,
            memory_root=memory_root,
            memory_max_context_chars=memory_max_context_chars,
        )
        self.durable_memory = DurableMemoryStore(
            root=self.memory_config.root,
            max_domain_items=self.memory_config.max_domain_items,
            max_episodic_items=self.memory_config.max_episodic_items,
        )
        self.model = model or ModelAdapter.from_config(config_path=config_path)
        self.tool_registry = build_core_tool_registry()
        self.skill_registry = skill_registry or build_financial_skill_registry(config_path=skill_registry_config_path)
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
        enable_remote_data: bool = True,
        data_source_config_path: str = "configs/data_sources.yaml",
        quality_remediation_plan: Dict[str, Any] | None = None,
    ) -> Dict[str, str]:
        quality_remediation_plan = quality_remediation_plan or _read_existing_quality_remediation_plan(self.output_dir)
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
                enable_remote_data=enable_remote_data,
                data_source_config_path=data_source_config_path,
                entity_resolution=entity_resolution,
                quality_remediation_plan=quality_remediation_plan,
            )
        if execution_mode == "static":
            return self._run_static(
                research_topic=research_topic,
                symbol=symbol,
                period=period,
                requirements=requirements,
                search_engines=search_engines,
                retrieval_ranking_mode=retrieval_ranking_mode,
                enable_remote_data=enable_remote_data,
                data_source_config_path=data_source_config_path,
                entity_resolution=entity_resolution,
                quality_remediation_plan=quality_remediation_plan,
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
        enable_remote_data: bool = True,
        data_source_config_path: str = "configs/data_sources.yaml",
        entity_resolution: Dict[str, Any] | None = None,
        quality_remediation_plan: Dict[str, Any] | None = None,
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
        durable_memory_brief = self._durable_memory_brief(
            symbol=symbol,
            period=period,
            report_type=conversation.report_type,
        )
        if durable_memory_brief and _share_durable_memory_with_agents(self.memory_config.context_scope):
            conversation.add_turn("system", durable_memory_brief, {"source": "durable_memory"})
            conversation_brief = _join_context_briefs(
                conversation.context_brief(),
                durable_memory_brief,
                max_chars=self.memory_config.max_context_chars,
            )
        planner_memory_brief = (
            durable_memory_brief
            if _use_durable_memory_for_planner_router(self.memory_config.context_scope)
            and not _share_durable_memory_with_agents(self.memory_config.context_scope)
            else ""
        )
        planning_context_brief = _join_context_briefs(
            conversation_brief,
            planner_memory_brief,
            max_chars=self.memory_config.max_context_chars,
        )
        planning_skill_brief = self._skill_brief(
            query=f"{research_topic} {' '.join(requirements)}",
            task_type="planning",
        )

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
                    "conversation_brief": planning_context_brief,
                    "skill_brief": planning_skill_brief,
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
                    "engines": search_engines or ["local_real_data", "tavily", "yahoo_finance", "sec_edgar", "local_evidence"],
                    "raw_data_root": self.raw_data_root,
                    "ranking_mode": retrieval_ranking_mode,
                    "data_source_config_path": data_source_config_path,
                    "enable_remote": bool(enable_remote_data),
                    "skill_brief": self._skill_brief(research_query, "deep_researcher", max_items=2),
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
                parameters={
                    "evidence_records": evidence_records,
                    "symbol": symbol,
                    "period": period,
                    "raw_data_root": self.raw_data_root,
                    "skill_brief": self._skill_brief("financial analysis valuation peer trend", "deep_analyze", max_items=2),
                },
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
        valuation_model_path = self._write_json(
            "valuation_model.json",
            analysis_artifacts.get("valuation_model", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        valuation_assumptions_path = self._write_json(
            "valuation_assumptions.json",
            analysis_artifacts.get("valuation_assumptions", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        valuation_sensitivity_path = self._write_json(
            "valuation_sensitivity.json",
            analysis_artifacts.get("valuation_sensitivity", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        tables = analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else []

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
                    "skill_brief": self._skill_brief("report markdown citations charts", "final_answer", max_items=2),
                    "tables": tables,
                    "financial_metrics": analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
                    "pdf_sections": analysis_artifacts.get("pdf_sections", []) if isinstance(analysis_artifacts, dict) else [],
                    "company_profile": analysis_artifacts.get("company_profile", {}) if isinstance(analysis_artifacts, dict) else {},
                    "quality_remediation_plan": quality_remediation_plan or {},
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
                    "valuation": analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {},
                    "conversation_brief": conversation_brief,
                    "skill_brief": self._skill_brief("verify evidence gaps citations lineage", "verifier", max_items=2),
                    "expected_symbol": symbol,
                    "period": period,
                    "entity_resolution": entity_resolution,
                },
                dependencies=["task_004_final_answer"],
                priority=3,
            ),
        )
        verification_report = verifier_result.output.get("verification_report", {})
        gap_resolution_trace = build_gap_resolution_trace(
            verification_report.get("evidence_gaps", []) if isinstance(verification_report, dict) else []
        )
        self._write_jsonl("gap_resolution_trace.jsonl", gap_resolution_trace)
        scorecard = build_company_report_scorecard(
            evidence_records=evidence_records if isinstance(evidence_records, list) else [],
            financial_metrics=analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
            multimodal_consistency=multimodal_consistency,
            valuation=analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {},
            verification_report=verification_report if isinstance(verification_report, dict) else {},
            gap_resolution_trace=gap_resolution_trace,
        )
        scorecard_path = self._write_json("company_report_scorecard.json", scorecard)
        durable_memory_artifacts: Dict[str, str] = {}
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
            "evidence_gap_count": len(verification_report.get("evidence_gaps", [])) if isinstance(verification_report, dict) else 0,
            "company_report_overall_score": scorecard["overall_score"],
            "entity_resolution": entity_resolution,
            "conversation_brief_chars": len(conversation_brief),
            "durable_memory_enabled": self.memory_config.enabled,
            "durable_memory_context_scope": self.memory_config.context_scope,
            "skill_registry_enabled": bool(self.skill_registry.names()),
            "skill_count": len(self.skill_registry.names()),
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        if self.memory_config.enabled:
            durable_memory_artifacts = self.durable_memory.persist_run(
                state={
                    "symbol": symbol,
                    "period": period,
                    "conversation_context": conversation.to_dict(),
                    "verification_report": verification_report,
                    "company_report_scorecard": scorecard,
                },
                run_summary=summary,
            )
            summary["durable_memory"] = durable_memory_artifacts
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_trace": str(trace_path),
            "evidence": str(self.output_dir / "evidence.json"),
            "claims": str(self.output_dir / "claims.json"),
            "analysis_artifacts": str(self.output_dir / "analysis_artifacts.json"),
            "financial_metrics": str(financial_metrics_path),
            "tables": str(tables_path),
            "valuation_model": str(valuation_model_path),
            "valuation_assumptions": str(valuation_assumptions_path),
            "valuation_sensitivity": str(valuation_sensitivity_path),
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
            "durable_memory": durable_memory_artifacts.get("working_snapshot", ""),
            "gap_resolution_trace": str(self.output_dir / "gap_resolution_trace.jsonl"),
            "company_report_scorecard": str(scorecard_path),
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
        enable_remote_data: bool = True,
        data_source_config_path: str = "configs/data_sources.yaml",
        entity_resolution: Dict[str, Any] | None = None,
        quality_remediation_plan: Dict[str, Any] | None = None,
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
        durable_memory_brief = self._durable_memory_brief(
            symbol=symbol,
            period=period,
            report_type=conversation.report_type,
        )
        if durable_memory_brief and _share_durable_memory_with_agents(self.memory_config.context_scope):
            conversation.add_turn("system", durable_memory_brief, {"source": "durable_memory"})
            conversation_brief = _join_context_briefs(
                conversation.context_brief(),
                durable_memory_brief,
                max_chars=self.memory_config.max_context_chars,
            )
        planner_memory_brief = (
            durable_memory_brief
            if _use_durable_memory_for_planner_router(self.memory_config.context_scope)
            and not _share_durable_memory_with_agents(self.memory_config.context_scope)
            else ""
        )
        planning_context_brief = _join_context_briefs(
            conversation_brief,
            planner_memory_brief,
            max_chars=self.memory_config.max_context_chars,
        )
        planning_skill_brief = self._skill_brief(
            query=f"{research_topic} {' '.join(requirements)}",
            task_type="planning",
        )

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
                    "conversation_brief": planning_context_brief,
                    "skill_brief": planning_skill_brief,
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
            "gap_resolution_trace": [],
            "conversation_context": conversation.to_dict(),
            "conversation_brief": conversation_brief,
            "durable_memory_brief": durable_memory_brief,
            "durable_memory_enabled": self.memory_config.enabled,
            "durable_memory_context_scope": self.memory_config.context_scope,
            "planner_skill_brief": planning_skill_brief,
            "performance_profile": "fast" if fast else "default",
            "search_engines": search_engines or [],
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "enable_remote_data": bool(enable_remote_data),
            "data_source_config_path": data_source_config_path,
            "entity_resolution": entity_resolution,
            "quality_remediation_plan": quality_remediation_plan or {},
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
            enable_remote_data=enable_remote_data,
            data_source_config_path=data_source_config_path,
            skill_registry=self.skill_registry,
            router_memory_brief=durable_memory_brief
            if _use_durable_memory_for_planner_router(self.memory_config.context_scope)
            else "",
            router_context_max_chars=self.memory_config.max_context_chars,
        )
        route_context_path = self._write_json("task_route_context.json", build_task_route_context(tasks))
        results = self._execute_dynamic_tasks(tasks=tasks, state=state)
        self._run_verifier_rework_loop(state=state)

        evidence_records = state["evidence_records"]
        claims = state["claims"]
        self._write_json("search_meta.json", state.get("search_meta", {}))
        self._write_json("evidence.json", evidence_records)
        self._write_json("claims.json", claims)
        self._write_json("analysis_artifacts.json", state.get("analysis_artifacts", {}))
        analysis_artifacts = state.get("analysis_artifacts", {})
        pdf_artifacts = state.get("pdf_artifacts")
        if not isinstance(pdf_artifacts, dict):
            pdf_artifacts = build_pdf_artifacts(
                records=list(evidence_records) if isinstance(evidence_records, list) else [],
                cache_dir=self.output_dir / "pdf_cache",
                max_pdfs=2 if fast else 4,
                max_pages=6 if fast else 12,
            )
        pdf_manifest_path = self._write_json("pdf_manifest.json", pdf_artifacts.get("pdf_manifest", []))
        pdf_sections_path = self._write_json("pdf_sections.json", pdf_artifacts.get("pdf_sections", []))
        company_profile_extracted_path = self._write_json(
            "company_profile_extracted.json",
            pdf_artifacts.get("company_profile_extracted", {}),
        )
        financial_metrics_path = self._write_json(
            "financial_metrics.json",
            analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        tables_path = self._write_json(
            "tables.json",
            analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
        )
        valuation_model_path = self._write_json(
            "valuation_model.json",
            analysis_artifacts.get("valuation_model", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        valuation_assumptions_path = self._write_json(
            "valuation_assumptions.json",
            analysis_artifacts.get("valuation_assumptions", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        valuation_sensitivity_path = self._write_json(
            "valuation_sensitivity.json",
            analysis_artifacts.get("valuation_sensitivity", {}) if isinstance(analysis_artifacts, dict) else {},
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
        self._write_jsonl("gap_resolution_trace.jsonl", state.get("gap_resolution_trace", []))
        scorecard = build_company_report_scorecard(
            evidence_records=list(evidence_records) if isinstance(evidence_records, list) else [],
            financial_metrics=analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
            multimodal_consistency=multimodal_consistency,
            valuation=analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {},
            verification_report=state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {},
            gap_resolution_trace=list(state.get("gap_resolution_trace", [])) if isinstance(state.get("gap_resolution_trace"), list) else [],
        )
        state["company_report_scorecard"] = scorecard
        scorecard_path = self._write_json("company_report_scorecard.json", scorecard)
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
            "pdf_artifact_meta": pdf_artifacts.get("meta", {}),
            "multimodal_consistency_passed": bool(multimodal_consistency.get("passed", False)),
            "mcp_tool_count": len(self.mcp_manager.list_tools()),
            "search_engines": state.get("search_meta", {}).get("engines", []),
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "revision_rounds": len(state.get("revision_history", [])) if isinstance(state.get("revision_history"), list) else 0,
            "verification_passed": bool(state.get("verification_report", {}).get("passed", False)),
            "evidence_gap_count": len(state.get("verification_report", {}).get("evidence_gaps", []))
            if isinstance(state.get("verification_report"), dict)
            else 0,
            "company_report_overall_score": scorecard["overall_score"],
            "entity_resolution": entity_resolution,
            "conversation_brief_chars": len(str(state.get("conversation_brief", ""))),
            "durable_memory_enabled": self.memory_config.enabled,
            "durable_memory_context_scope": self.memory_config.context_scope,
            "skill_registry_enabled": bool(self.skill_registry.names()),
            "skill_count": len(self.skill_registry.names()),
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        durable_memory_artifacts: Dict[str, str] = {}
        if self.memory_config.enabled:
            durable_memory_artifacts = self.durable_memory.persist_run(
                state=state,
                run_summary=summary,
            )
            summary["durable_memory"] = durable_memory_artifacts
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_route_context": str(route_context_path),
            "task_trace": str(trace_path),
            "search_meta": str(self.output_dir / "search_meta.json"),
            "evidence": str(self.output_dir / "evidence.json"),
            "claims": str(self.output_dir / "claims.json"),
            "analysis_artifacts": str(self.output_dir / "analysis_artifacts.json"),
            "financial_metrics": str(financial_metrics_path),
            "pdf_manifest": str(pdf_manifest_path),
            "pdf_sections": str(pdf_sections_path),
            "company_profile_extracted": str(company_profile_extracted_path),
            "tables": str(tables_path),
            "valuation_model": str(valuation_model_path),
            "valuation_assumptions": str(valuation_assumptions_path),
            "valuation_sensitivity": str(valuation_sensitivity_path),
            "citations": str(self.output_dir / "citations.json"),
            "citations_md": str(citations_md_path),
            "charts": str(self.output_dir / "charts.json"),
            "chart_consistency": str(self.output_dir / "chart_consistency.json"),
            "multimodal_consistency": str(self.output_dir / "multimodal_consistency.json"),
            "mcp_manifest": str(mcp_manifest_path),
            "revision_history": str(self.output_dir / "revision_history.json"),
            "gap_resolution_trace": str(self.output_dir / "gap_resolution_trace.jsonl"),
            "company_report_scorecard": str(scorecard_path),
            "conversation_context": str(conversation_path),
            "durable_memory": durable_memory_artifacts.get("working_snapshot", ""),
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
            if enriched.task_type == "browser":
                attach_pdf_artifacts_to_state(state=state)
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

    def _durable_memory_brief(self, symbol: str, period: str, report_type: str = "company_stock_report") -> str:
        if not self.memory_config.enabled:
            return ""
        return self.durable_memory.build_context_brief(
            symbol=symbol,
            period=period,
            report_type=report_type,
            max_chars=self.memory_config.max_context_chars,
        )

    def _skill_brief(self, query: str, task_type: str, max_items: int = 4) -> str:
        if not self.skill_registry:
            return ""
        return self.skill_registry.render_brief(
            query=query,
            task_type=task_type,
            max_items=max_items,
            max_chars=min(1600, self.memory_config.max_context_chars),
        )

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
                        "tables": dict(state.get("analysis_artifacts", {})).get("tables", [])
                        if isinstance(state.get("analysis_artifacts"), dict)
                        else [],
                        "financial_metrics": dict(state.get("analysis_artifacts", {})).get("financial_metrics", {})
                        if isinstance(state.get("analysis_artifacts"), dict)
                        else {},
                        "pdf_sections": dict(state.get("analysis_artifacts", {})).get("pdf_sections", [])
                        if isinstance(state.get("analysis_artifacts"), dict)
                        else [],
                        "company_profile": dict(state.get("analysis_artifacts", {})).get("company_profile", {})
                        if isinstance(state.get("analysis_artifacts"), dict)
                        else {},
                        "quality_remediation_plan": dict(state.get("quality_remediation_plan", {}))
                        if isinstance(state.get("quality_remediation_plan"), dict)
                        else {},
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
                        "valuation": dict(state.get("analysis_artifacts", {})).get("valuation", {}),
                        "conversation_brief": refresh_conversation_brief(state),
                        "expected_symbol": str(state.get("symbol", "")),
                        "period": str(state.get("period", "")),
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
            _update_gap_trace_after_rework(state=state, round_index=round_index)
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

    def _write_jsonl(self, file_name: str, rows: List[Dict[str, Any]]) -> Path:
        path = self.output_dir / file_name
        payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows if isinstance(row, dict))
        path.write_text((payload + "\n") if payload else "", encoding="utf-8")
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
    enable_remote_data: bool = True,
    data_source_config_path: str = "configs/data_sources.yaml",
    skill_registry: SkillRegistry | None = None,
    router_memory_brief: str = "",
    router_context_max_chars: int = 1600,
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
        metadata = dict(task.metadata)
        if skill_registry:
            route_query = f"{research_topic} {symbol} {period} {task.description} {json.dumps(params, ensure_ascii=False, default=str)}"
            selected_skills = skill_registry.select(query=route_query, task_type=task.task_type, max_items=2)
            skill_brief = skill_registry.render_brief(
                query=route_query,
                task_type=task.task_type,
                max_items=2,
                max_chars=min(900, int(router_context_max_chars)),
            )
            if skill_brief:
                params.setdefault("skill_brief", skill_brief)
            metadata["selected_skills"] = [skill.name for skill in selected_skills]
        if router_memory_brief:
            metadata["memory_context_policy"] = {
                "durable_memory_available": True,
                "scope": "planner_router_hint_only",
                "brief_chars": min(len(router_memory_brief), int(router_context_max_chars)),
            }
        if task.task_type == "deep_researcher":
            params.setdefault("query", f"{symbol} {period} {task.description}")
            params["symbol"] = symbol
            params["period"] = period
            params.setdefault("topk", int(profile["research_topk"]))
            params.setdefault("engines", search_engines or ["local_real_data", "tavily", "yahoo_finance", "sec_edgar", "local_evidence"])
            params.setdefault("raw_data_root", raw_data_root)
            params.setdefault("ranking_mode", retrieval_ranking_mode)
            params.setdefault("data_source_config_path", data_source_config_path)
            params.setdefault("enable_remote", bool(enable_remote_data))
        cleaned.append(
            AgentTask(
                task_id=task.task_id,
                task_type=task.task_type,
                description=task.description,
                parameters=params,
                dependencies=[dep for dep in task.dependencies if dep in cleaned_ids],
                priority=task.priority,
                metadata=metadata,
            )
        )
    return cleaned


def build_task_route_context(tasks: List[AgentTask]) -> Dict[str, Any]:
    """Summarize router-selected skills and context policies for traceability."""

    return {
        "tasks": [
            {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "selected_skills": list(task.metadata.get("selected_skills", []))
                if isinstance(task.metadata.get("selected_skills", []), list)
                else [],
                "memory_context_policy": task.metadata.get("memory_context_policy", {}),
                "skill_brief_chars": len(str(task.parameters.get("skill_brief", ""))),
            }
            for task in tasks
        ]
    }


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
    ids_by_type: Dict[str, List[str]] = {}
    for task in tasks:
        ids_by_type.setdefault(task.task_type, []).append(task.task_id)
    type_by_id = {task.task_id: task.task_type for task in tasks}

    output: List[AgentTask] = []
    for task in tasks:
        deps = [
            dep
            for dep in task.dependencies
            if _task_type_order(type_by_id.get(dep, "")) <= _task_type_order(task.task_type)
        ]
        if task.task_type == "browser":
            deps.extend(ids_by_type.get("deep_researcher", []))
        elif task.task_type == "deep_analyze":
            deps.extend(ids_by_type.get("browser", []) or ids_by_type.get("deep_researcher", []))
        elif task.task_type == "final_answer":
            deps.extend(ids_by_type.get("deep_analyze", []))
        elif task.task_type == "verifier":
            deps.extend(ids_by_type.get("final_answer", []))

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
        params.setdefault("engines", ["local_real_data", "tavily", "yahoo_finance", "sec_edgar", "local_evidence"])
        params.setdefault("raw_data_root", raw_data_root)
        params.setdefault("ranking_mode", str(state.get("retrieval_ranking_mode", "hybrid_rerank")))
        params.setdefault("data_source_config_path", str(state.get("data_source_config_path", "configs/data_sources.yaml")))
        params.setdefault("enable_remote", bool(state.get("enable_remote_data", False)))
    elif task.task_type == "browser":
        if not isinstance(params.get("evidence_candidates"), list) or not params.get("evidence_candidates"):
            params["evidence_candidates"] = list(state.get("evidence_candidates", []))
        params.setdefault("skip_llm_extract", bool(profile["browser_skip_llm_extract"]))
        params.setdefault("use_reader", bool(profile["browser_use_reader"]))
        params.setdefault("use_playwright", bool(profile.get("browser_use_playwright", False)))
        params.setdefault("reader_max_records", int(profile["browser_reader_max_records"]))
        params.setdefault("reader_max_chars", int(profile["browser_reader_max_chars"]))
        params.setdefault("max_llm_records", int(profile["browser_max_llm_records"]))
    elif task.task_type == "deep_analyze":
        if not isinstance(params.get("evidence_records"), list) or not params.get("evidence_records"):
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
        if not isinstance(params.get("claims"), list) or not params.get("claims"):
            params["claims"] = list(state.get("claims", []))
        if not isinstance(params.get("evidence_records"), list) or not params.get("evidence_records"):
            params["evidence_records"] = list(state.get("evidence_records", []))
        analysis_artifacts = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        params.setdefault("tables", analysis_artifacts.get("tables", []))
        params.setdefault("financial_metrics", analysis_artifacts.get("financial_metrics", {}))
        params.setdefault("pdf_sections", analysis_artifacts.get("pdf_sections", []))
        params.setdefault("company_profile", analysis_artifacts.get("company_profile", {}))
        params.setdefault("quality_remediation_plan", dict(state.get("quality_remediation_plan", {})) if isinstance(state.get("quality_remediation_plan"), dict) else {})
        params.setdefault("max_claims", int(profile["final_max_claims"]))
        params.setdefault("max_evidence", int(profile["final_max_evidence"]))
        params.setdefault("evidence_content_limit", int(profile["final_evidence_content_limit"]))
        params.setdefault("max_tokens", int(profile["final_max_tokens"]))
        params.setdefault("conversation_brief", str(state.get("conversation_brief", "")))
    elif task.task_type == "verifier":
        if not isinstance(params.get("claims"), list) or not params.get("claims"):
            params["claims"] = list(state.get("claims", []))
        if not params.get("markdown"):
            params["markdown"] = str(state.get("markdown", ""))
        if not isinstance(params.get("evidence_records"), list) or not params.get("evidence_records"):
            params["evidence_records"] = list(state.get("evidence_records", []))
        if not isinstance(params.get("charts"), list) or not params.get("charts"):
            params["charts"] = list(state.get("charts", []))
        if not params.get("tables"):
            params["tables"] = dict(state.get("analysis_artifacts", {})).get("tables", [])
        if not params.get("valuation"):
            params["valuation"] = dict(state.get("analysis_artifacts", {})).get("valuation", {})
        params.setdefault("conversation_brief", str(state.get("conversation_brief", "")))
        params.setdefault("expected_symbol", str(state.get("symbol", "")))
        params.setdefault("period", str(state.get("period", "")))
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
        gaps = state["verification_report"].get("evidence_gaps", []) if isinstance(state["verification_report"], dict) else []
        if gaps or not state.get("gap_resolution_trace"):
            state["gap_resolution_trace"] = build_gap_resolution_trace(gaps)


def attach_pdf_artifacts_to_state(state: Dict[str, Any]) -> None:
    """Extract filing PDF snippets early enough for analysis and writing."""

    if isinstance(state.get("pdf_artifacts"), dict):
        return
    records = list(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else []
    if not records:
        return
    chart_dir = Path(str(state.get("chart_output_dir") or "data/outputs/multi_agent/charts"))
    output_dir = chart_dir.parent
    fast = state.get("performance_profile") == "fast"
    pdf_artifacts = build_pdf_artifacts(
        records=records,
        cache_dir=output_dir / "pdf_cache",
        max_pdfs=2 if fast else 4,
        max_pages=6 if fast else 12,
    )
    state["pdf_artifacts"] = pdf_artifacts
    section_records = _pdf_sections_as_evidence_records(
        sections=pdf_artifacts.get("pdf_sections", []),
        symbol=str(state.get("symbol", "")),
        period=str(state.get("period", "")),
    )
    if section_records:
        state["evidence_records"] = _merge_records(
            records,
            section_records,
            key_names=["evidence_id", "sample_id", "source_url"],
        )


def _pdf_sections_as_evidence_records(sections: Any, symbol: str, period: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    if not isinstance(sections, list):
        return output
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or "")
        source_evidence_id = str(section.get("evidence_id") or "")
        snippet = str(section.get("snippet") or "").strip()
        if not section_id or not snippet:
            continue
        evidence_id = f"pdf_section_{section_id}"
        output.append(
            {
                "evidence_id": evidence_id,
                "sample_id": evidence_id,
                "source_type": "pdf_section",
                "title": f"PDF section: {section.get('section_type') or 'unknown'}",
                "source_url": str(section.get("source_url") or ""),
                "publish_time": "",
                "content": snippet,
                "symbol": symbol,
                "period": period,
                "trust_level": "high",
                "metadata": {
                    "section_id": section_id,
                    "section_type": section.get("section_type", ""),
                    "page": section.get("page", ""),
                    "matched_keyword": section.get("matched_keyword", ""),
                    "source_evidence_id": source_evidence_id,
                    "extraction_method": section.get("extraction_method", ""),
                },
            }
        )
    return output


def _update_gap_trace_after_rework(state: Dict[str, Any], round_index: int) -> None:
    latest_gaps = {
        str(gap.get("gap_id", ""))
        for gap in state.get("verification_report", {}).get("evidence_gaps", [])
        if isinstance(gap, dict)
    } if isinstance(state.get("verification_report"), dict) else set()
    updated = []
    for item in state.get("gap_resolution_trace", []):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["attempt"] = int(row.get("attempt", 0) or 0) + 1
        row["last_round"] = round_index
        row["status"] = "still_open" if row.get("gap_id") in latest_gaps else "resolved_or_downgraded"
        updated.append(row)
    new_gaps = [
        gap
        for gap in state.get("verification_report", {}).get("evidence_gaps", [])
        if isinstance(gap, dict) and str(gap.get("gap_id", "")) not in {str(item.get("gap_id", "")) for item in updated}
    ] if isinstance(state.get("verification_report"), dict) else []
    updated.extend(build_gap_resolution_trace(new_gaps))
    state["gap_resolution_trace"] = updated


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


def _load_durable_memory_config(
    app_config_path: str,
    memory_enabled: bool | None = None,
    memory_root: str | None = None,
    memory_max_context_chars: int | None = None,
) -> DurableMemoryConfig:
    payload: Dict[str, Any] = {}
    try:
        payload = load_config(app_config_path)
    except FileNotFoundError:
        payload = {}
    memory = payload.get("memory", {}) if isinstance(payload.get("memory"), dict) else {}
    durable = memory.get("durable", {}) if isinstance(memory.get("durable"), dict) else {}
    return DurableMemoryConfig(
        enabled=bool(durable.get("enabled", False) if memory_enabled is None else memory_enabled),
        root=str(durable.get("root", "memory") if memory_root is None else memory_root),
        max_context_chars=int(
            durable.get("max_context_chars", 1600)
            if memory_max_context_chars is None
            else memory_max_context_chars
        ),
        max_domain_items=int(durable.get("max_domain_items", 12) or 12),
        max_episodic_items=int(durable.get("max_episodic_items", 6) or 6),
        context_scope=_normalize_memory_context_scope(durable.get("context_scope", "planner_router")),
    )


def _normalize_memory_context_scope(value: Any) -> str:
    scope = str(value or "planner_router").strip().lower()
    aliases = {
        "planner": "planner_router",
        "router": "planner_router",
        "planner-router": "planner_router",
        "all": "all_agents",
        "all_agent": "all_agents",
        "agents": "all_agents",
        "off": "disabled",
        "none": "disabled",
    }
    scope = aliases.get(scope, scope)
    if scope not in {"planner_router", "all_agents", "disabled"}:
        return "planner_router"
    return scope


def _use_durable_memory_for_planner_router(context_scope: str) -> bool:
    return _normalize_memory_context_scope(context_scope) in {"planner_router", "all_agents"}


def _share_durable_memory_with_agents(context_scope: str) -> bool:
    return _normalize_memory_context_scope(context_scope) == "all_agents"


def _read_existing_quality_remediation_plan(output_dir: Path) -> Dict[str, Any]:
    path = Path(output_dir) / "quality_remediation_plan.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _join_context_briefs(primary: str, secondary: str, max_chars: int) -> str:
    if not secondary:
        return primary
    text = f"{primary}\n\n{secondary}" if primary else secondary
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + "\n...[compressed]"
