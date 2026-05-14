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
    refresh_conversation_memory_from_state,
)
from src.agents.deep_analyze_agent import DeepAnalyzeAgent
from src.agents.risk_agent import RiskAgent
from src.agents.peer_comparison_agent import PeerComparisonAgent
from src.agents.adjudicator_agent import AdjudicatorAgent
from src.agents.deep_researcher_agent import DeepResearcherAgent
from src.agents.final_answer_agent import FinalAnswerAgent
from src.agents.gap_router import build_gap_resolution_trace
from src.multiagent.blackboard import Blackboard
from src.multiagent.gaps.router import GapRouter
from src.multiagent.gaps.schema import now_iso
from src.multiagent.messages import AgentMessage, MessageStatus, MessageType
from src.multiagent.router import BudgetGuard, BudgetState, DynamicRouter, RouterInput
from src.multiagent.taskboard import TaskBoard, TaskBoardItem, TaskStatus
from src.agents.planning_agent import PlanningAgent
from src.agents.request_understanding_agent import RequestUnderstandingAgent
from src.agents.verifier_agent import VerifierAgent
from src.data.company_universe import resolve_company_identifier, resolve_company_identifier_with_diagnostics
from src.request_understanding.schema import ResearchRequest, normalize_structured_request
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
from src.tools import build_core_tool_registry
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
        self.flash_long_model = self.model if model else (_load_optional_model(config_path=config_path, section="flash_long_model") or self.model)
        self.pro_judge_model = None if model else _load_optional_model(config_path=config_path, section="pro_judge_model")
        self.pro_refiner_model = None if model else _load_optional_model(config_path=config_path, section="pro_refiner_model")
        self.pro_model = self.pro_refiner_model or self.pro_judge_model
        self.model_routing = _load_model_routing(config_path=config_path)
        self.tool_registry = build_core_tool_registry()
        self.mcp_manager = MCPManager.from_tool_registry(self.tool_registry, namespace="finance")
        self.search_manager = search_manager or SearchManager.with_local_sources()
        self.agents = {
            "request_understanding": RequestUnderstandingAgent(model=self.model, raw_data_root=raw_data_root),
            "planning": PlanningAgent(model=self.model),
            "research": DeepResearcherAgent(model=self.model, search_manager=self.search_manager),
            "browser": BrowserAgent(model=self.model),
            "analyze": DeepAnalyzeAgent(model=self.model, tool_registry=self.tool_registry),
            "final_answer": FinalAnswerAgent(model=self.flash_long_model),
            "verifier": VerifierAgent(model=self.model),
            "risk": RiskAgent(model=self.model),
            "peer": PeerComparisonAgent(model=self.model),
            "adjudicator": AdjudicatorAgent(model=self.model),
        }
        self.trace: List[Dict[str, Any]] = []
        self._active_blackboard: Blackboard | None = None

    def run(
        self,
        research_topic: str = "",
        symbol: str = "AAPL",
        period: str = "2025Q4",
        requirements: List[str] | None = None,
        execution_mode: str = "dynamic",
        fast: bool = False,
        search_engines: List[str] | None = None,
        retrieval_ranking_mode: str = "hybrid_rerank",
        natural_language_query: str | None = None,
        structured_request: Dict[str, Any] | ResearchRequest | None = None,
        attachments: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, str]:
        request = self._build_research_request(
            research_topic=research_topic,
            symbol=symbol,
            period=period,
            natural_language_query=natural_language_query,
            structured_request=structured_request,
            attachments=attachments,
        )
        if request.clarification_needed:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            clarification_path = self.output_dir / "request_understanding.json"
            clarification_path.write_text(json.dumps(request.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            return {"request_understanding": str(clarification_path), "status": "clarification_needed"}

        research_topic = request.planner_topic()
        symbol = request.symbol or symbol
        period = request.period_label or period
        requirements = list(requirements or []) + request.planner_requirements()
        entity_resolution = _resolve_run_identity(research_topic=research_topic, symbol=symbol, raw_data_root=self.raw_data_root)
        entity_resolution["request_understanding"] = request.to_dict()
        symbol = str(entity_resolution.get("resolved_symbol") or symbol).upper()
        if execution_mode in ("dynamic", "routed_rework"):
            return self._run_dynamic(
                research_topic=research_topic,
                symbol=symbol,
                period=period,
                requirements=requirements,
                fast=fast,
                search_engines=search_engines,
                retrieval_ranking_mode=retrieval_ranking_mode,
                entity_resolution=entity_resolution,
                rework_mode=execution_mode,
            )
        if execution_mode == "legacy_workflow":
            return self._run_dynamic(
                research_topic=research_topic,
                symbol=symbol,
                period=period,
                requirements=requirements,
                fast=fast,
                search_engines=search_engines,
                retrieval_ranking_mode=retrieval_ranking_mode,
                entity_resolution=entity_resolution,
                rework_mode="legacy_workflow",
            )
        if execution_mode == "dynamic_multiagent":
            return self._run_dynamic(
                research_topic=research_topic,
                symbol=symbol,
                period=period,
                requirements=requirements,
                fast=fast,
                search_engines=search_engines,
                retrieval_ranking_mode=retrieval_ranking_mode,
                entity_resolution=entity_resolution,
                rework_mode="dynamic_multiagent",
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

    def _write_request_understanding_artifact(self, entity_resolution: Dict[str, Any] | None) -> Path:
        payload = dict((entity_resolution or {}).get("request_understanding", {}) or {})
        path = self.output_dir / "request_understanding.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        research_request_path = self.output_dir / "research_request.json"
        research_request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _build_research_request(
        self,
        research_topic: str,
        symbol: str,
        period: str,
        natural_language_query: str | None,
        structured_request: Dict[str, Any] | ResearchRequest | None,
        attachments: List[Dict[str, Any]] | None,
    ) -> ResearchRequest:
        if isinstance(structured_request, ResearchRequest):
            return structured_request
        if isinstance(structured_request, dict):
            return normalize_structured_request(structured_request)
        if natural_language_query:
            agent = self.agents["request_understanding"]
            assert isinstance(agent, RequestUnderstandingAgent)
            return agent.parse(query=natural_language_query, attachments=attachments or [])
        return normalize_structured_request(
            {
                "original_query": research_topic,
                "company_name": symbol,
                "symbol": symbol,
                "market": "",
                "period": {"type": period, "granularity": _period_granularity(period)},
                "report_type": "company_research",
                "focus_areas": [],
                "attachments": {"optional": True, "files": attachments or []},
            }
        )

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
        request_understanding_path = self._write_request_understanding_artifact(entity_resolution)
        research_request_path = request_understanding_path
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

        _rating = _derive_rating(analysis_artifacts)

        # Run RiskAgent and PeerComparisonAgent to fill P2 sections
        valuation_for_agents = analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {}
        ratio_rows_for_agents = analysis_artifacts.get("ratio_rows", []) if isinstance(analysis_artifacts, dict) else []
        financial_evidence_ids = [
            str(r.get("evidence_id") or r.get("sample_id") or "")
            for r in evidence_records
            if str(r.get("source_type", "")).lower() == "financials"
        ]
        market_evidence_ids = [
            str(r.get("evidence_id") or r.get("sample_id") or "")
            for r in evidence_records
            if str(r.get("source_type", "")).lower() in {"market", "market_api"}
        ]
        target_metrics = _select_target_metric_row(ratio_rows_for_agents)

        risk_result = self._execute(
            "risk",
            AgentTask(
                task_id="task_005_risk",
                task_type="risk",
                description="Generate risk assessment claims.",
                parameters={
                    "symbol": symbol,
                    "evidence_records": evidence_records,
                    "valuation": valuation_for_agents,
                    "ratio_rows": ratio_rows_for_agents,
                    "financial_evidence_ids": financial_evidence_ids,
                    "market_evidence_ids": market_evidence_ids,
                },
                dependencies=["task_003_analyze"],
                priority=5,
            ),
        )
        peer_result = self._execute(
            "peer",
            AgentTask(
                task_id="task_006_peer",
                task_type="peer",
                description="Generate peer comparison claims.",
                parameters={
                    "symbol": symbol,
                    "period": period,
                    "sector": str(target_metrics.get("sector", "")),
                    "industry": str(target_metrics.get("industry", "")),
                    "target_metrics": target_metrics,
                    "financial_evidence_ids": financial_evidence_ids,
                    "raw_data_root": self.raw_data_root,
                },
                dependencies=["task_003_analyze"],
                priority=5,
            ),
        )
        risk_claims = risk_result.output.get("claims", []) if risk_result.status == AgentStatus.COMPLETED else []
        peer_claims = peer_result.output.get("claims", []) if peer_result.status == AgentStatus.COMPLETED else []
        peer_evidence_records = peer_result.output.get("evidence_records", []) if peer_result.status == AgentStatus.COMPLETED else []
        if peer_evidence_records:
            evidence_records = _merge_records(
                evidence_records,
                peer_evidence_records,
                key_names=["evidence_id", "sample_id", "source_url"],
            )
            self._write_json("evidence.json", evidence_records)
        # Merge new claims, replacing any existing peer_compare / risks claims from deep_analyze
        existing_sections = {str(c.get("section_name", "")) for c in claims if isinstance(c, dict)}
        claims = [c for c in claims if str(c.get("section_name", "")) not in {"risks", "peer_compare"}]
        claims = claims + risk_claims + peer_claims
        self._write_json("claims.json", claims)

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
                    "rating": _rating,
                    "symbol": symbol,
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
        resolved_period = _resolve_display_period(evidence_records=evidence_records, requested_period=period)
        html = render_professional_html_report(
            markdown=markdown,
            title=research_topic,
            charts=charts,
            citations=citations,
            symbol=symbol,
            company_name=str(entity_resolution.get("company_name") or symbol),
            period=resolved_period,
            rating=_rating,
        )
        markdown = append_compliance_disclosures(markdown, citations=citations, rating=_rating)
        html = append_compliance_disclosures_to_html(html, citations=citations, rating=_rating)
        if isinstance(report_json, dict):
            report_json = dict(report_json)
            report_json["citations"] = citations
            report_json["charts"] = charts
            report_json["compliance_disclosure"] = {"included": True, "rating": _rating}
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
        rework_trace = build_rework_trace(
            gaps=verification_report.get("gaps", []) if isinstance(verification_report, dict) else [],
            gap_resolution_trace=gap_resolution_trace,
        )
        self._write_jsonl("gap_resolution_trace.jsonl", gap_resolution_trace)
        self._write_json("rework_trace.json", rework_trace)
        scorecard = build_company_report_scorecard(
            evidence_records=evidence_records if isinstance(evidence_records, list) else [],
            financial_metrics=analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
            multimodal_consistency=multimodal_consistency,
            valuation=analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {},
            verification_report=verification_report if isinstance(verification_report, dict) else {},
            gap_resolution_trace=gap_resolution_trace,
        )
        scorecard_path = self._write_json("company_report_scorecard.json", scorecard)
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
            "main_model": self.model.model_name,
            "flash_long_model": getattr(self.flash_long_model, "model_name", ""),
            "pro_judge_model": getattr(self.pro_judge_model, "model_name", ""),
            "pro_refiner_model": getattr(self.pro_refiner_model, "model_name", ""),
            "model_routing": self.model_routing,
            "pro_route_trace_count": _count_pro_route_trace(self.trace),
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
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_trace": str(trace_path),
            "request_understanding": str(request_understanding_path),
            "research_request": str(research_request_path),
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
            "gap_resolution_trace": str(self.output_dir / "gap_resolution_trace.jsonl"),
            "rework_trace": str(self.output_dir / "rework_trace.json"),
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
        entity_resolution: Dict[str, Any] | None = None,
        rework_mode: str = "routed_rework",
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
        request_understanding_path = self._write_request_understanding_artifact(entity_resolution)
        research_request_path = request_understanding_path
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
            "gap_resolution_trace": [],
            "rework_trace": [],
            "agent_messages": [],
            "gaps": [],
            "task_board": {"tasks": [], "summary": {"task_count": 0, "blocked_count": 0, "resolution_rate": 0.0}},
            "router_decisions": [],
            "budget_trace": [],
            "rework_mode": rework_mode,
            "conversation_context": conversation.to_dict(),
            "conversation_brief": conversation_brief,
            "performance_profile": "fast" if fast else "default",
            "search_engines": search_engines or [],
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "entity_resolution": entity_resolution,
            "raw_data_root": self.raw_data_root,
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

        self._run_verifier_rework_loop(state=state, rework_mode=rework_mode)

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
        self._write_json("rework_trace.json", state.get("rework_trace", []))
        task_board_path = self._write_json("task_board.json", state.get("task_board", {}))
        agent_messages_path = self._write_jsonl("agent_messages.jsonl", state.get("agent_messages", []))
        router_decisions_path = self._write_jsonl("router_decisions.jsonl", state.get("router_decisions", []))
        budget_trace_path = self._write_jsonl("budget_trace.jsonl", state.get("budget_trace", []))
        scorecard = build_company_report_scorecard(
            evidence_records=list(evidence_records) if isinstance(evidence_records, list) else [],
            financial_metrics=analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
            multimodal_consistency=multimodal_consistency,
            valuation=analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {},
            verification_report=state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {},
            gap_resolution_trace=list(state.get("gap_resolution_trace", [])) if isinstance(state.get("gap_resolution_trace"), list) else [],
        )
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
            "main_model": self.model.model_name,
            "flash_long_model": getattr(self.flash_long_model, "model_name", ""),
            "pro_judge_model": getattr(self.pro_judge_model, "model_name", ""),
            "pro_refiner_model": getattr(self.pro_refiner_model, "model_name", ""),
            "model_routing": self.model_routing,
            "pro_route_trace_count": _count_pro_route_trace(self.trace),
            "execution_mode": "dynamic",
            "performance_profile": "fast" if fast else "default",
            "agent_count": len(self.agents),
            "planned_task_count": len(tasks),
            "completed_task_count": len(results),
            "trace_count": len(self.trace),
            "message_count": len(state.get("agent_messages", [])) if isinstance(state.get("agent_messages"), list) else 0,
            "task_blocked_count": _task_board_blocked_count(state.get("task_board", {})),
            "task_resolution_rate": _task_board_resolution_rate(state.get("task_board", {})),
            "router_decision_count": len(state.get("router_decisions", [])) if isinstance(state.get("router_decisions"), list) else 0,
            "dynamic_dispatch_count": _count_dynamic_dispatches(state.get("router_decisions", [])),
            "fallback_decision_count": _count_fallback_decisions(state.get("router_decisions", [])),
            "budget_exceeded_count": _count_budget_exceeded(state.get("budget_trace", [])),
            "router_stop_reason": _last_stop_reason(state.get("budget_trace", [])),
            "rework_mode": rework_mode,
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
            "evidence_gap_count": len(state.get("verification_report", {}).get("evidence_gaps", []))
            if isinstance(state.get("verification_report"), dict)
            else 0,
            "gap_detection_count": len(state.get("verification_report", {}).get("gaps", []))
            if isinstance(state.get("verification_report"), dict)
            else 0,
            "gap_resolution_rate": _gap_resolution_rate(state.get("rework_trace", [])),
            "adjudication_decisions": list(state.get("adjudication_decisions", [])) if isinstance(state.get("adjudication_decisions"), list) else [],
            "conflict_resolution_count": _count_resolved_adjudications(state.get("adjudication_decisions", [])),
            "adjudication_decision_distribution": _adjudication_decision_distribution(state.get("adjudication_decisions", [])),
            "company_report_overall_score": scorecard["overall_score"],
            "entity_resolution": entity_resolution,
            "conversation_brief_chars": len(str(state.get("conversation_brief", ""))),
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_trace": str(trace_path),
            "task_board": str(task_board_path),
            "agent_messages": str(agent_messages_path),
            "router_decisions": str(router_decisions_path),
            "budget_trace": str(budget_trace_path),
            "request_understanding": str(request_understanding_path),
            "research_request": str(research_request_path),
            "search_meta": str(self.output_dir / "search_meta.json"),
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
            "revision_history": str(self.output_dir / "revision_history.json"),
            "gap_resolution_trace": str(self.output_dir / "gap_resolution_trace.jsonl"),
            "rework_trace": str(self.output_dir / "rework_trace.json"),
            "company_report_scorecard": str(scorecard_path),
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
        blackboard = Blackboard(state=state, task_board=TaskBoard.from_plan_tasks(tasks, agent_key_for_task))
        self._active_blackboard = blackboard
        blackboard.sync_task_board()
        while pending:
            ready = [
                task
                for task in pending.values()
                if all(dep in results for dep in task.dependencies)
            ]
            if not ready:
                blocked = {task_id: task.dependencies for task_id, task in pending.items()}
                for task_id in blocked:
                    blackboard.task_board.update_status(task_id, TaskStatus.BLOCKED)
                blackboard.sync_task_board()
                raise RuntimeError(f"dynamic task graph is blocked by unresolved dependencies: {blocked}")

            ready.sort(key=lambda task: (_task_type_order(task.task_type), -task.priority, task.task_id))
            task = ready[0]
            enriched = enrich_task_parameters(
                task=task,
                state=state,
                raw_data_root=self.raw_data_root,
                profile=FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE,
            )
            # Pre-flight: block final_answer if resolved symbol doesn't match evidence
            if enriched.task_type == "final_answer":
                _preflight_symbol_check(state)
            blackboard.task_board.update_status(enriched.task_id, TaskStatus.RUNNING)
            blackboard.sync_task_board()
            try:
                result = self._execute(agent_key_for_task(enriched.task_type), enriched)
            except Exception as exc:
                blackboard.task_board.update_status(enriched.task_id, TaskStatus.FAILED, result_ref=str(exc))
                blackboard.sync_task_board()
                raise
            blackboard.task_board.update_status(enriched.task_id, TaskStatus.RESOLVED, result_ref=result.agent_name)
            blackboard.sync_task_board()
            results[enriched.task_id] = result
            merge_task_result(state=state, task_type=enriched.task_type, result=result)
            if enriched.task_type == "verifier":
                absorb_verifier_feedback(state)
                _sync_gap_routes_to_blackboard(state, blackboard)
            else:
                refresh_conversation_memory_from_state(state)
            del pending[enriched.task_id]
        self._active_blackboard = None
        return results

    def _execute(self, agent_key: str, task: AgentTask) -> TaskResult:
        return self._execute_agent(agent=self.agents[agent_key], task=task, model_route="flash_main")

    def _execute_agent(self, agent: Any, task: AgentTask, model_route: str = "flash_main") -> TaskResult:
        blackboard = self._active_blackboard
        if blackboard is not None:
            blackboard.append_message(
                AgentMessage.create(
                    sender_agent="Orchestrator",
                    receiver_agent=agent.name,
                    message_type=MessageType.STATUS_UPDATE,
                    related_task_id=task.task_id,
                    payload={"event": "task_started", "task": task.to_dict(), "model_route": model_route},
                    status=MessageStatus.SENT,
                )
            )
        started_at = time.perf_counter()
        result = agent.execute_task(task)
        duration_sec = round(time.perf_counter() - started_at, 3)
        model_name = getattr(getattr(agent, "model", None), "model_name", "")
        if blackboard is not None:
            blackboard.append_message(
                AgentMessage.create(
                    sender_agent=agent.name,
                    receiver_agent="Orchestrator",
                    message_type=MessageType.STATUS_UPDATE,
                    related_task_id=task.task_id,
                    payload={"event": "task_finished", "result": result.to_dict(), "duration_sec": duration_sec},
                    status=MessageStatus.HANDLED if result.status == AgentStatus.COMPLETED else MessageStatus.FAILED,
                )
            )
        self.trace.append(
            {
                "agent": agent.name,
                "model": model_name,
                "model_route": model_route,
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

    def _run_verifier_rework_loop(self, state: Dict[str, Any], rework_mode: str = "routed_rework") -> None:
        if isinstance(state.get("verification_report"), dict):
            state["rework_trace"] = build_rework_trace(
                gaps=state["verification_report"].get("gaps", []),
                gap_resolution_trace=state.get("gap_resolution_trace", []),
            )
        profile = FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE
        max_rounds = int(profile.get("verifier_max_rework_rounds", 1) or 0)
        verification_report = state.get("verification_report", {})
        if max_rounds <= 0 or not isinstance(verification_report, dict):
            return

        if rework_mode == "dynamic_multiagent":
            self._run_dynamic_multiagent_rework_loop(state=state, max_rounds=max_rounds, profile=profile)
            return

        for round_index in range(1, max_rounds + 1):
            verification_report = state.get("verification_report", {})
            if not isinstance(verification_report, dict) or verification_report.get("passed", False):
                break

            revision_request = build_revision_brief(verification_report)
            if not revision_request:
                break
            conversation_brief = refresh_conversation_brief(state)
            blackboard = self._active_blackboard or Blackboard(state=state)
            self._active_blackboard = blackboard
            self._run_routed_gap_rework(state=state, round_index=round_index, blackboard=blackboard)
            verification_report = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else verification_report
            use_pro = self._should_use_pro_for_rework(verification_report)
            final_agent = (
                FinalAnswerAgent(model=self.pro_refiner_model)
                if use_pro and self._pro_role_enabled("final_answer_rework")
                else self.agents["final_answer"]
            )

            rework_task = TaskBoardItem(
                task_id=f"task_rework_{round_index:03d}_final_answer",
                task_type="final_answer_rework",
                owner_agent="final_answer",
                dependencies=[],
                related_gap_ids=_current_gap_ids(state),
                status=TaskStatus.QUEUED,
            )
            blackboard.upsert_task(rework_task)
            blackboard.task_board.update_status(rework_task.task_id, TaskStatus.RUNNING)
            blackboard.sync_task_board()
            final_result = self._execute_agent(
                agent=final_agent,
                task=AgentTask(
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
                model_route="pro_refiner" if final_agent is not self.agents["final_answer"] else "flash_rework",
            )
            blackboard.task_board.update_status(final_result.task_id, TaskStatus.RESOLVED, result_ref=final_result.agent_name)
            blackboard.sync_task_board()
            merge_task_result(state=state, task_type="final_answer", result=final_result)
            verifier_agent = (
                VerifierAgent(model=self.pro_judge_model)
                if use_pro and self._pro_role_enabled("verifier_recheck")
                else self.agents["verifier"]
            )

            verify_task = TaskBoardItem(
                task_id=f"task_rework_{round_index:03d}_verifier",
                task_type="verifier_recheck",
                owner_agent="verifier",
                dependencies=[final_result.task_id],
                related_gap_ids=_current_gap_ids(state),
                status=TaskStatus.QUEUED,
            )
            blackboard.upsert_task(verify_task)
            blackboard.task_board.update_status(verify_task.task_id, TaskStatus.RUNNING)
            blackboard.sync_task_board()
            verify_result = self._execute_agent(
                agent=verifier_agent,
                task=AgentTask(
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
                model_route="pro_judge" if verifier_agent is not self.agents["verifier"] else "flash_recheck",
            )
            blackboard.task_board.update_status(verify_result.task_id, TaskStatus.RESOLVED, result_ref=verify_result.agent_name)
            blackboard.sync_task_board()
            merge_task_result(state=state, task_type="verifier", result=verify_result)
            absorb_verifier_feedback(state)
            _update_gap_trace_after_rework(state=state, round_index=round_index)
            _sync_gap_routes_to_blackboard(state, blackboard)
            state.setdefault("revision_history", []).append(
                {
                    "round": round_index,
                    "revision_request": revision_request,
                    "model_route": "pro_conditional" if use_pro else "flash_rework",
                    "passed_after_round": bool(state.get("verification_report", {}).get("passed", False)),
                }
            )

    def _run_dynamic_multiagent_rework_loop(self, state: Dict[str, Any], max_rounds: int, profile: Dict[str, Any]) -> None:
        budget = BudgetState.from_profile(state.get("performance_profile", "fast"))
        guard = BudgetGuard(budget)
        router = DynamicRouter(budget_guard=guard)
        blackboard = self._active_blackboard or Blackboard(state=state)
        self._active_blackboard = blackboard
        unresolved_gap_history: Dict[str, List[str]] = {}
        previous_decisions: List[Dict[str, Any]] = []

        for round_index in range(1, max_rounds + 1):
            verification_report = state.get("verification_report", {})
            if not isinstance(verification_report, dict) or verification_report.get("passed", False):
                break

            guard.record_round()
            router_input = RouterInput.from_state(
                state=state,
                budget_state=guard.budget_snapshot(round_index=round_index),
                previous_decisions=previous_decisions,
                executed_agents=[],
                unresolved_gap_history=unresolved_gap_history,
            )

            if router.should_stop(router_input):
                state.setdefault("budget_trace", []).append(
                    guard.budget_snapshot(round_index=round_index, can_continue=False)
                )
                break

            state.setdefault("budget_trace", []).append(
                guard.budget_snapshot(round_index=round_index, can_continue=True)
            )

            decisions = router.decide(router_input)
            executed_agents_this_round: List[str] = []

            for decision in decisions:
                state.setdefault("router_decisions", []).append(decision.to_dict())
                previous_decisions.append(decision.to_dict())

                if decision.stop_recommended or decision.selected_action in ("stop", "skip"):
                    continue

                if decision.selected_action == "fallback":
                    for gap_id in decision.related_gap_ids:
                        unresolved_gap_history.setdefault(gap_id, []).append("fallback")
                    continue

                if decision.selected_action == "execute" and decision.selected_agent:
                    gap_id = decision.related_gap_ids[0] if decision.related_gap_ids else ""
                    report = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
                    gap = next((g for g in report.get("gaps", []) if isinstance(g, dict) and str(g.get("gap_id", "")) == gap_id), None)
                    if gap is None:
                        continue
                    dispatch_start = time.perf_counter()
                    self._execute_one_routed_gap_rework(state=state, gap=gap, round_index=round_index, blackboard=blackboard)
                    dispatch_elapsed = time.perf_counter() - dispatch_start
                    guard.record_dispatch(gap_id=gap_id, elapsed_sec=dispatch_elapsed)
                    executed_agents_this_round.append(decision.selected_agent)
                    unresolved_gap_history.setdefault(gap_id, []).append(decision.selected_agent)

            blackboard.sync_task_board()

            revision_request = build_revision_brief(state.get("verification_report", {}))
            if not revision_request:
                break
            conversation_brief = refresh_conversation_brief(state)
            use_pro = self._should_use_pro_for_rework(state.get("verification_report", {}))
            final_agent = (
                FinalAnswerAgent(model=self.pro_refiner_model)
                if use_pro and self._pro_role_enabled("final_answer_rework")
                else self.agents["final_answer"]
            )
            rework_task = TaskBoardItem(
                task_id=f"task_dyn_{round_index:03d}_final_answer",
                task_type="final_answer_rework",
                owner_agent="final_answer",
                dependencies=[],
                related_gap_ids=_current_gap_ids(state),
                status=TaskStatus.QUEUED,
            )
            blackboard.upsert_task(rework_task)
            blackboard.task_board.update_status(rework_task.task_id, TaskStatus.RUNNING)
            blackboard.sync_task_board()
            final_result = self._execute_agent(
                agent=final_agent,
                task=AgentTask(
                    task_id=f"task_dyn_{round_index:03d}_final_answer",
                    task_type="final_answer",
                    description="Revise report using dynamic router feedback.",
                    parameters={
                        "research_topic": state.get("research_topic", ""),
                        "claims": list(state.get("claims", [])),
                        "evidence_records": list(state.get("evidence_records", [])),
                        "revision_request": revision_request,
                        "verification_report": state.get("verification_report", {}),
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
                model_route="pro_refiner" if final_agent is not self.agents["final_answer"] else "flash_rework",
            )
            blackboard.task_board.update_status(final_result.task_id, TaskStatus.RESOLVED, result_ref=final_result.agent_name)
            blackboard.sync_task_board()
            merge_task_result(state=state, task_type="final_answer", result=final_result)

            verifier_agent = (
                VerifierAgent(model=self.pro_judge_model)
                if use_pro and self._pro_role_enabled("verifier_recheck")
                else self.agents["verifier"]
            )
            verify_task = TaskBoardItem(
                task_id=f"task_dyn_{round_index:03d}_verifier",
                task_type="verifier_recheck",
                owner_agent="verifier",
                dependencies=[final_result.task_id],
                related_gap_ids=_current_gap_ids(state),
                status=TaskStatus.QUEUED,
            )
            blackboard.upsert_task(verify_task)
            blackboard.task_board.update_status(verify_task.task_id, TaskStatus.RUNNING)
            blackboard.sync_task_board()
            verify_result = self._execute_agent(
                agent=verifier_agent,
                task=AgentTask(
                    task_id=f"task_dyn_{round_index:03d}_verifier",
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
                model_route="pro_judge" if verifier_agent is not self.agents["verifier"] else "flash_recheck",
            )
            blackboard.task_board.update_status(verify_result.task_id, TaskStatus.RESOLVED, result_ref=verify_result.agent_name)
            blackboard.sync_task_board()
            merge_task_result(state=state, task_type="verifier", result=verify_result)
            absorb_verifier_feedback(state)
            _update_gap_trace_after_rework(state=state, round_index=round_index)
            _sync_gap_routes_to_blackboard(state, blackboard)
            state.setdefault("revision_history", []).append(
                {
                    "round": round_index,
                    "revision_request": revision_request,
                    "model_route": "pro_conditional" if use_pro else "flash_rework",
                    "passed_after_round": bool(state.get("verification_report", {}).get("passed", False)),
                    "router_decisions_this_round": len(decisions),
                    "executed_agents_this_round": executed_agents_this_round,
                }
            )

    def _run_routed_gap_rework(self, state: Dict[str, Any], round_index: int, blackboard: Blackboard) -> None:
        report = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
        gaps = [gap for gap in report.get("gaps", []) if isinstance(gap, dict)]
        if not gaps:
            return
        for gap in gaps:
            self._execute_one_routed_gap_rework(state=state, gap=gap, round_index=round_index, blackboard=blackboard)
        blackboard.sync_task_board()

    def _execute_one_routed_gap_rework(self, state: Dict[str, Any], gap: Dict[str, Any], round_index: int, blackboard: Blackboard) -> None:
        gap_id = str(gap.get("gap_id", ""))
        gap_type = str(gap.get("gap_type", ""))
        route = GapRouter().route(gap)
        owner_key = _supported_rework_owner(gap_type, route.routed_to)
        task_id = f"task_rework_{round_index:03d}_{gap_id}_{owner_key or 'fallback'}".replace(" ", "_")
        before_ref = _state_snapshot_ref(state)
        row = _ensure_rework_row(state, gap, route.to_dict())
        row["before_state_ref"] = before_ref
        row["routed_to"] = route.routed_to
        row["actually_executed_agent"] = ""
        if owner_key is None:
            row["actually_executed_agent"] = "fallback_unified_final_answer"
            row["fallback_reason"] = f"unsupported_gap_type:{gap_type}"
            row["after_state_ref"] = before_ref
            row["latency"] = 0.0
            blackboard.task_board.add_gap_task(gap_id=gap_id, gap_type=gap_type, owner_agent="fallback_unified_final_answer")
            blackboard.task_board.update_status(f"gap_task_{gap_id}_fallback_unified_final_answer", TaskStatus.WAITING_REVIEW, result_ref=row["fallback_reason"])
            blackboard.append_message(
                AgentMessage.create(
                    sender_agent="GapRouter",
                    receiver_agent="Orchestrator",
                    message_type=MessageType.STATUS_UPDATE,
                    related_task_id=task_id,
                    related_gap_id=gap_id,
                    payload={"event": "routed_rework_fallback", "gap": gap, "route": route.to_dict(), "reason": row["fallback_reason"]},
                    status=MessageStatus.HANDLED,
                )
            )
            return

        task = _routed_rework_task(task_id=task_id, owner_key=owner_key, gap=gap, state=state)
        blackboard.upsert_task(
            TaskBoardItem(
                task_id=task.task_id,
                task_type=f"gap_rework:{gap_type}",
                owner_agent=owner_key,
                dependencies=[],
                related_gap_ids=[gap_id] if gap_id else [],
                status=TaskStatus.QUEUED,
            )
        )
        blackboard.append_message(
            AgentMessage.create(
                sender_agent="VerifierAgent",
                receiver_agent="GapRouter",
                message_type=_message_type_for_gap(gap_type),
                related_task_id=task.task_id,
                related_gap_id=gap_id,
                related_claim_ids=[str(item) for item in gap.get("related_claim_ids", [])] if isinstance(gap.get("related_claim_ids"), list) else [],
                payload={"event": "routed_rework_requested", "gap": gap},
                status=MessageStatus.SENT,
            )
        )
        blackboard.append_message(
            AgentMessage.create(
                sender_agent="GapRouter",
                receiver_agent=owner_key,
                message_type=_message_type_for_gap(gap_type),
                related_task_id=task.task_id,
                related_gap_id=gap_id,
                payload={"event": "routed_rework_assigned", "route": route.to_dict()},
                status=MessageStatus.SENT,
            )
        )
        blackboard.task_board.update_status(task.task_id, TaskStatus.RUNNING)
        blackboard.sync_task_board()
        started = time.perf_counter()
        try:
            result = self._execute_agent(self.agents[owner_key], task, model_route="routed_gap_rework")
            merge_task_result(state=state, task_type=task.task_type, result=result)
            if task.task_type == "deep_analyze":
                refresh_conversation_memory_from_state(state)
            elif task.task_type == "final_answer":
                refresh_conversation_memory_from_state(state)
            latency = round(time.perf_counter() - started, 4)
            blackboard.task_board.update_status(task.task_id, TaskStatus.RESOLVED, result_ref=result.agent_name)
            row["actually_executed_agent"] = result.agent_name
            row["after_state_ref"] = _state_snapshot_ref(state)
            row["latency"] = latency
            row["resolved"] = False
            row["status"] = "executed_pending_verification"
            blackboard.append_message(
                AgentMessage.create(
                    sender_agent=result.agent_name,
                    receiver_agent="VerifierAgent",
                    message_type=MessageType.STATUS_UPDATE,
                    related_task_id=task.task_id,
                    related_gap_id=gap_id,
                    payload={"event": "routed_rework_completed", "output_keys": sorted(result.output.keys()), "latency": latency},
                    status=MessageStatus.HANDLED,
                )
            )
        except Exception as exc:
            latency = round(time.perf_counter() - started, 4)
            blackboard.task_board.update_status(task.task_id, TaskStatus.FAILED, result_ref=str(exc))
            row["actually_executed_agent"] = owner_key
            row["after_state_ref"] = _state_snapshot_ref(state)
            row["latency"] = latency
            row["resolved"] = False
            row["status"] = "execution_failed"
            row["error"] = str(exc)
            blackboard.append_message(
                AgentMessage.create(
                    sender_agent=owner_key,
                    receiver_agent="VerifierAgent",
                    message_type=MessageType.STATUS_UPDATE,
                    related_task_id=task.task_id,
                    related_gap_id=gap_id,
                    payload={"event": "routed_rework_failed", "error": str(exc), "latency": latency},
                    status=MessageStatus.FAILED,
                )
            )

    def _should_use_pro_for_rework(self, verification_report: Dict[str, Any]) -> bool:
        if self.pro_model is None:
            return False
        routing = self.model_routing if isinstance(self.model_routing, dict) else {}
        if str(routing.get("pro_policy", "conditional")) != "conditional":
            return False
        triggers = {str(item) for item in routing.get("pro_triggers", []) if str(item)}
        if not verification_report.get("passed", False) and "verifier_fail" in triggers:
            return True
        gaps = verification_report.get("evidence_gaps", [])
        if isinstance(gaps, list) and gaps:
            if "evidence_gap" in triggers:
                return True
            gap_types = {str(gap.get("gap_type", "")) for gap in gaps if isinstance(gap, dict)}
            if gap_types.intersection(triggers):
                return True
        messages = " ".join(
            str(item)
            for key in ("errors", "warnings", "llm_errors", "llm_warnings")
            for item in verification_report.get(key, [])
            if isinstance(verification_report.get(key, []), list)
        ).lower()
        if "valuation" in messages and "valuation_formula_error" in triggers:
            return True
        if ("period" in messages or "symbol mismatch" in messages) and "entity_or_period_mismatch" in triggers:
            return True
        if "chart" in messages and "multimodal_conflict" in triggers:
            return True
        return False

    def _pro_role_enabled(self, role: str) -> bool:
        roles = self.model_routing.get("pro_roles", []) if isinstance(self.model_routing, dict) else []
        return role in {str(item) for item in roles}

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
        params.setdefault("symbol", str(state.get("symbol", "")))
        if not params.get("rating"):
            params["rating"] = _derive_rating(state.get("analysis_artifacts", {}))
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
        browser_records = result.output.get("evidence_records", [])
        if not browser_records:
            # BrowserAgent returned nothing (local-data mode or network unavailable).
            # Promote evidence_candidates to evidence_records so downstream agents
            # (DeepAnalyzeAgent, RiskAgent, PeerComparisonAgent) can attach evidence_ids to claims.
            browser_records = _promote_candidates_to_records(state.get("evidence_candidates", []))
        state["evidence_records"] = _merge_records(
            state.get("evidence_records", []),
            browser_records,
            key_names=["evidence_id", "sample_id", "source_url"],
        )
    elif task_type == "deep_analyze":
        state["claims"] = _merge_records(
            state.get("claims", []),
            result.output.get("claims", []),
            key_names=["claim_id", "claim_text"],
        )
        state["analysis_artifacts"] = result.output.get("analysis_artifacts", {})
        # Immediately run RiskAgent and PeerComparisonAgent and merge their claims
        _run_risk_and_peer_agents(state)
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
        _rating2 = _derive_rating(state.get("analysis_artifacts", {}))
        _resolved_period2 = _resolve_display_period(
            evidence_records=list(state.get("evidence_records", [])),
            requested_period=str(state.get("period") or ""),
        )
        state["html"] = render_professional_html_report(
            markdown=state["markdown"],
            title=str(state.get("research_topic") or "金融研究报告"),
            charts=charts,
            citations=state["citations"],
            symbol=str(state.get("symbol") or ""),
            company_name=str((state.get("entity_resolution") or {}).get("company_name") or state.get("symbol") or ""),
            period=_resolved_period2,
            rating=_rating2,
        )
        state["markdown"] = append_compliance_disclosures(state["markdown"], citations=state["citations"], rating=_rating2)
        state["html"] = append_compliance_disclosures_to_html(state["html"], citations=state["citations"], rating=_rating2)
        if isinstance(report_json, dict):
            report_json = dict(report_json)
            report_json["citations"] = state["citations"]
            report_json["charts"] = charts
            report_json["compliance_disclosure"] = {"included": True, "rating": _rating2}
            report_json["analysis_artifacts"] = state.get("analysis_artifacts", {})
        state["report_json"] = report_json
    elif task_type == "verifier":
        state["verification_report"] = result.output.get("verification_report", {})
        gaps = state["verification_report"].get("evidence_gaps", []) if isinstance(state["verification_report"], dict) else []
        if gaps or not state.get("gap_resolution_trace"):
            state["gap_resolution_trace"] = build_gap_resolution_trace(gaps)
        structured_gaps = state["verification_report"].get("gaps", []) if isinstance(state["verification_report"], dict) else []
        if structured_gaps or not state.get("rework_trace"):
            state["rework_trace"] = build_rework_trace(structured_gaps, state.get("gap_resolution_trace", []))
    elif task_type == "risk":
        state["claims"] = _merge_records(
            state.get("claims", []),
            result.output.get("claims", []),
            key_names=["claim_id", "claim_text"],
        )
    elif task_type == "peer":
        state["claims"] = _merge_records(
            state.get("claims", []),
            result.output.get("claims", []),
            key_names=["claim_id", "claim_text"],
        )
        state["evidence_records"] = _merge_records(
            state.get("evidence_records", []),
            result.output.get("evidence_records", []),
            key_names=["evidence_id", "sample_id", "source_url"],
        )
    elif task_type == "adjudicator":
        # Accumulate adjudication decisions into state for artifact writing and metrics
        decisions = result.output.get("adjudication_decisions", [])
        existing = state.setdefault("adjudication_decisions", [])
        existing.extend(decisions)


def _rerun_final_answer_with_risk_peer(orchestrator: Any, state: Dict[str, Any], fast: bool = True) -> None:
    """Re-run FinalAnswerAgent with risk + peer claims merged into state."""
    from src.agents.final_answer_agent import FinalAnswerAgent
    profile = FAST_PROFILE if fast else DEFAULT_PROFILE
    agent = orchestrator.agents.get("final_answer")
    if agent is None:
        return
    params: Dict[str, Any] = {
        "research_topic": state.get("research_topic", ""),
        "claims": list(state.get("claims", [])),
        "evidence_records": list(state.get("evidence_records", [])),
        "conversation_brief": str(state.get("conversation_brief", "")),
        "symbol": str(state.get("symbol", "")),
        "rating": _derive_rating(state.get("analysis_artifacts", {})),
        "max_claims": int(profile.get("final_max_claims", 30)),
        "max_evidence": int(profile.get("final_max_evidence", 12)),
        "evidence_content_limit": int(profile.get("final_evidence_content_limit", 400)),
        "max_tokens": int(profile.get("final_max_tokens", 4000)),
    }
    task = AgentTask(
        task_id="task_final_answer_with_risk_peer",
        task_type="final_answer",
        description="Re-run final answer with risk and peer comparison claims.",
        parameters=params,
    )
    result = agent.execute_task(task)
    if result.status == AgentStatus.COMPLETED:
        merge_task_result(state=state, task_type="final_answer", result=result)


def _run_risk_and_peer_agents(state: Dict[str, Any]) -> None:
    """Run RiskAgent and PeerComparisonAgent after deep_analyze and merge their claims into state."""
    analysis_artifacts = state.get("analysis_artifacts", {})
    evidence_records = list(state.get("evidence_records", []))
    symbol = str(state.get("symbol", ""))
    period = str(state.get("period", "latest"))
    valuation = analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {}
    ratio_rows = analysis_artifacts.get("ratio_rows", []) if isinstance(analysis_artifacts, dict) else []
    financial_evidence_ids = [
        str(r.get("evidence_id") or r.get("sample_id") or "")
        for r in evidence_records
        if str(r.get("source_type", "")).lower() == "financials"
    ]
    market_evidence_ids = [
        str(r.get("evidence_id") or r.get("sample_id") or "")
        for r in evidence_records
        if str(r.get("source_type", "")).lower() in {"market", "market_api"}
    ]
    target_metrics = _select_target_metric_row(ratio_rows)

    try:
        risk_agent = RiskAgent(model=None)
        risk_result = risk_agent.run(AgentTask(
            task_id="task_risk_inline",
            task_type="risk",
            description="Generate risk assessment claims.",
            parameters={
                "symbol": symbol,
                "evidence_records": evidence_records,
                "valuation": valuation,
                "ratio_rows": ratio_rows,
                "financial_evidence_ids": financial_evidence_ids,
                "market_evidence_ids": market_evidence_ids,
            },
        ))
        risk_claims = risk_result.output.get("claims", []) if risk_result.status == AgentStatus.COMPLETED else []
    except Exception:
        risk_claims = []

    try:
        peer_agent = PeerComparisonAgent(model=None)
        peer_result = peer_agent.run(AgentTask(
            task_id="task_peer_inline",
            task_type="peer",
            description="Generate peer comparison claims.",
            parameters={
                "symbol": symbol,
                "period": period,
                "sector": str(target_metrics.get("sector", "")),
                "industry": str(target_metrics.get("industry", "")),
                "target_metrics": target_metrics,
                "financial_evidence_ids": financial_evidence_ids,
                "raw_data_root": str(state.get("raw_data_root") or "data/raw/real_data"),
                "use_sec_fetch": "sec_companyfacts" in set(state.get("search_engines") or []),
            },
        ))
        peer_claims = peer_result.output.get("claims", []) if peer_result.status == AgentStatus.COMPLETED else []
        peer_evidence_records = peer_result.output.get("evidence_records", []) if peer_result.status == AgentStatus.COMPLETED else []
        if peer_evidence_records:
            state["evidence_records"] = _merge_records(
                list(state.get("evidence_records", [])),
                peer_evidence_records,
                key_names=["evidence_id", "sample_id", "source_url"],
            )
    except Exception:
        peer_claims = []

    def _to_dict(c: Any) -> Dict[str, Any]:
        if isinstance(c, dict):
            return c
        if hasattr(c, "__dict__"):
            return c.__dict__
        return {}

    risk_claims_dicts = [_to_dict(c) for c in risk_claims if c]
    peer_claims_dicts = [_to_dict(c) for c in peer_claims if c]

    # Replace any existing risks/peer_compare claims from deep_analyze
    state["claims"] = [
        c for c in state.get("claims", [])
        if isinstance(c, dict) and str(c.get("section_name", "")) not in {"risks", "peer_compare"}
    ] + risk_claims_dicts + peer_claims_dicts


def build_rework_trace(gaps: List[Dict[str, Any]], gap_resolution_trace: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    router = GapRouter()
    legacy_by_id = {
        str(item.get("gap_id", "")): item
        for item in (gap_resolution_trace or [])
        if isinstance(item, dict)
    }
    rows: List[Dict[str, Any]] = []
    for gap in gaps if isinstance(gaps, list) else []:
        if not isinstance(gap, dict):
            continue
        route = router.route(gap).to_dict()
        legacy = legacy_by_id.get(str(gap.get("gap_id", "")), {})
        rows.append(
            {
                "gap_id": str(gap.get("gap_id", "")),
                "gap_type": str(gap.get("gap_type", "")),
                "routed_to": route["routed_to"],
                "before_revision": gap,
                "after_revision": {},
                "resolved": False,
                "rounds": int(legacy.get("attempt", 0) or 0),
                "latency": 0.0,
                "status": str(gap.get("status", "open")),
                "created_at": str(gap.get("created_at", "")),
                "resolved_at": str(gap.get("resolved_at", "")),
            }
        )
    return rows


def _gap_resolution_rate(rework_trace: Any) -> float:
    if not isinstance(rework_trace, list) or not rework_trace:
        return 0.0
    resolved = sum(1 for item in rework_trace if isinstance(item, dict) and bool(item.get("resolved")))
    return round(resolved / float(len(rework_trace)), 4)


def _update_gap_trace_after_rework(state: Dict[str, Any], round_index: int) -> None:
    report = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
    latest_legacy_gaps = {
        str(gap.get("gap_id", ""))
        for gap in report.get("evidence_gaps", [])
        if isinstance(gap, dict)
    }
    latest_structured_gaps = {
        str(gap.get("gap_id", "")): gap
        for gap in report.get("gaps", [])
        if isinstance(gap, dict)
    }
    updated = []
    for item in state.get("gap_resolution_trace", []):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["attempt"] = int(row.get("attempt", 0) or 0) + 1
        row["last_round"] = round_index
        row["status"] = "still_open" if row.get("gap_id") in latest_legacy_gaps else "resolved_or_downgraded"
        updated.append(row)
    new_gaps = [
        gap
        for gap in report.get("evidence_gaps", [])
        if isinstance(gap, dict) and str(gap.get("gap_id", "")) not in {str(item.get("gap_id", "")) for item in updated}
    ]
    updated.extend(build_gap_resolution_trace(new_gaps))
    state["gap_resolution_trace"] = updated

    rework_rows = []
    for row in state.get("rework_trace", []):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        gap_id = str(item.get("gap_id", ""))
        still_open = gap_id in latest_structured_gaps
        item["after_revision"] = latest_structured_gaps.get(gap_id, {})
        item["resolved"] = not still_open
        item["rounds"] = int(item.get("rounds", 0) or 0) + 1
        item["status"] = "unresolved" if still_open else "resolved"
        item["resolved_at"] = "" if still_open else now_iso()
        rework_rows.append(item)
    known = {str(item.get("gap_id", "")) for item in rework_rows if isinstance(item, dict)}
    for gap_id, gap in latest_structured_gaps.items():
        if gap_id not in known:
            rework_rows.extend(build_rework_trace([gap], state.get("gap_resolution_trace", [])))
    state["rework_trace"] = rework_rows


def _supported_rework_owner(gap_type: str, routed_to: List[str]) -> str | None:
    candidates = {
        "EVIDENCE_GAP": [("ResearchAgent", "research"), ("BrowserAgent", "browser")],
        "NUMERIC_GAP": [("AnalyzeAgent", "analyze")],
        "CITATION_GAP": [("ResearchAgent", "research")],
        "RISK_GAP": [("RiskAgent", "risk")],
        "PEER_GAP": [("PeerComparisonAgent", "peer")],
        "FORMAT_GAP": [("FinalWriterAgent", "final_answer")],
        "SOURCE_CONFLICT": [("AdjudicatorAgent", "adjudicator")],
    }
    for route_agent, owner_key in candidates.get(gap_type, []):
        if route_agent in routed_to:
            return owner_key
    return None


def _routed_rework_task(task_id: str, owner_key: str, gap: Dict[str, Any], state: Dict[str, Any]) -> AgentTask:
    gap_type = str(gap.get("gap_type", ""))
    description = f"Routed rework for {gap_type}: {gap.get('description', '')}"
    if owner_key == "research":
        return AgentTask(
            task_id=task_id,
            task_type="deep_researcher",
            description=description,
            parameters={
                "query": f"{state.get('symbol', '')} {state.get('period', '')} {gap.get('description', '')} {gap.get('recommended_action', '')}",
                "symbol": str(state.get("symbol", "")),
                "period": str(state.get("period", "")),
                "topk": 6,
                "engines": list(state.get("search_engines", [])) or ["local_real_data", "local_evidence"],
                "raw_data_root": str(state.get("raw_data_root") or "data/raw/real_data"),
                "ranking_mode": str(state.get("retrieval_ranking_mode", "hybrid_rerank")),
            },
            priority=5,
        )
    if owner_key == "browser":
        return AgentTask(task_id=task_id, task_type="browser", description=description, parameters={"evidence_candidates": list(state.get("evidence_candidates", [])), "skip_llm_extract": True}, priority=5)
    if owner_key == "analyze":
        return AgentTask(
            task_id=task_id,
            task_type="deep_analyze",
            description=description,
            parameters={
                "evidence_records": list(state.get("evidence_records", [])),
                "symbol": str(state.get("symbol", "")),
                "period": str(state.get("period", "")),
                "raw_data_root": str(state.get("raw_data_root") or "data/raw/real_data"),
                "max_records": 12,
                "content_limit": 900,
                "use_react": False,
            },
            priority=5,
        )
    if owner_key == "final_answer":
        return AgentTask(
            task_id=task_id,
            task_type="final_answer",
            description=description,
            parameters={
                "research_topic": str(state.get("research_topic", "")),
                "claims": list(state.get("claims", [])),
                "evidence_records": list(state.get("evidence_records", [])),
                "revision_request": f"Repair format gap {gap.get('gap_id', '')}: {gap.get('recommended_action') or gap.get('description', '')}",
                "verification_report": dict(state.get("verification_report", {})) if isinstance(state.get("verification_report"), dict) else {},
                "prior_markdown": str(state.get("markdown", "")),
                "conversation_brief": str(state.get("conversation_brief", "")),
                "max_claims": 20,
                "max_evidence": 12,
                "evidence_content_limit": 600,
                "symbol": str(state.get("symbol", "")),
            },
            priority=5,
        )
    if owner_key == "risk":
        return AgentTask(task_id=task_id, task_type="risk", description=description, parameters={"symbol": str(state.get("symbol", "")), "evidence_records": list(state.get("evidence_records", [])), "valuation": dict(state.get("analysis_artifacts", {})).get("valuation", {})}, priority=5)
    if owner_key == "peer":
        return AgentTask(task_id=task_id, task_type="peer", description=description, parameters={"symbol": str(state.get("symbol", "")), "period": str(state.get("period", "")), "raw_data_root": str(state.get("raw_data_root") or "data/raw/real_data")}, priority=5)
    if owner_key == "adjudicator":
        # Pass conflicting claims and evidence from the gap's context
        conflicting_claims = list(gap.get("conflicting_claims", []))
        conflicting_evidence = list(gap.get("conflicting_evidence", []))
        # If gap doesn't carry structured conflicts, try to find them from state claims
        if not conflicting_claims:
            all_claims = list(state.get("claims", []))
            conflicting_claims = [c for c in all_claims if isinstance(c, dict) and str(c.get("gap_id", "")) == str(gap.get("gap_id", ""))]
        return AgentTask(
            task_id=task_id,
            task_type="adjudicator",
            description=description,
            parameters={
                "gap_id": str(gap.get("gap_id", "")),
                "gap_description": str(gap.get("description", "")),
                "conflicting_claims": conflicting_claims,
                "conflicting_evidence": conflicting_evidence,
                "symbol": str(state.get("symbol", "")),
            },
            priority=5,
        )
    raise KeyError(f"unsupported routed rework owner: {owner_key}")


def _ensure_rework_row(state: Dict[str, Any], gap: Dict[str, Any], route: Dict[str, Any]) -> Dict[str, Any]:
    gap_id = str(gap.get("gap_id", ""))
    rows = state.setdefault("rework_trace", [])
    for row in rows:
        if isinstance(row, dict) and str(row.get("gap_id", "")) == gap_id:
            return row
    row = {
        "gap_id": gap_id,
        "gap_type": str(gap.get("gap_type", "")),
        "routed_to": list(route.get("routed_to", [])),
        "before_revision": gap,
        "after_revision": {},
        "resolved": False,
        "rounds": 0,
        "latency": 0.0,
        "status": "routed",
        "created_at": str(gap.get("created_at", "")),
        "resolved_at": str(gap.get("resolved_at", "")),
    }
    rows.append(row)
    return row


def _state_snapshot_ref(state: Dict[str, Any]) -> str:
    return "claims={};evidence={};citations={};markdown_chars={}".format(
        len(state.get("claims", [])) if isinstance(state.get("claims"), list) else 0,
        len(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else 0,
        len(state.get("citations", [])) if isinstance(state.get("citations"), list) else 0,
        len(str(state.get("markdown", ""))),
    )


def _count_resolved_adjudications(adjudication_decisions: Any) -> int:
    if not isinstance(adjudication_decisions, list):
        return 0
    return sum(
        1
        for decision in adjudication_decisions
        if isinstance(decision, dict) and str(decision.get("decision", "")) not in ("", "uncertain")
    )


def _adjudication_decision_distribution(adjudication_decisions: Any) -> Dict[str, int]:
    distribution: Dict[str, int] = {}
    if not isinstance(adjudication_decisions, list):
        return distribution
    for decision in adjudication_decisions:
        if not isinstance(decision, dict):
            continue
        verdict = str(decision.get("decision", "unknown") or "unknown")
        distribution[verdict] = distribution.get(verdict, 0) + 1
    return distribution


def _count_dynamic_dispatches(router_decisions: Any) -> int:
    if not isinstance(router_decisions, list):
        return 0
    return sum(1 for d in router_decisions if isinstance(d, dict) and d.get("selected_action") == "execute")


def _count_fallback_decisions(router_decisions: Any) -> int:
    if not isinstance(router_decisions, list):
        return 0
    return sum(1 for d in router_decisions if isinstance(d, dict) and d.get("fallback_used"))


def _count_budget_exceeded(budget_trace: Any) -> int:
    if not isinstance(budget_trace, list):
        return 0
    return sum(1 for b in budget_trace if isinstance(b, dict) and not b.get("can_continue", True))


def _last_stop_reason(budget_trace: Any) -> str:
    if not isinstance(budget_trace, list):
        return ""
    for b in reversed(budget_trace):
        if isinstance(b, dict) and b.get("stop_reason"):
            return str(b["stop_reason"])
    return ""


def _sync_gap_routes_to_blackboard(state: Dict[str, Any], blackboard: Blackboard) -> None:
    report = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
    gaps = [gap for gap in report.get("gaps", []) if isinstance(gap, dict)]
    if not gaps:
        blackboard.sync_task_board()
        return
    existing_gap_ids = {
        str(item.get("gap_id", ""))
        for item in state.get("gaps", [])
        if isinstance(item, dict)
    }
    for gap in gaps:
        gap_id = str(gap.get("gap_id", ""))
        gap_type = str(gap.get("gap_type", ""))
        if gap_id and gap_id not in existing_gap_ids:
            blackboard.append_gap(gap)
            existing_gap_ids.add(gap_id)
        route = GapRouter().route(gap)
        for owner_agent in route.routed_to:
            task = blackboard.task_board.add_gap_task(
                gap_id=gap_id,
                gap_type=gap_type,
                owner_agent=owner_agent,
            )
            blackboard.append_message(
                AgentMessage.create(
                    sender_agent="GapRouter",
                    receiver_agent=owner_agent,
                    message_type=_message_type_for_gap(gap_type),
                    related_task_id=task.task_id,
                    related_gap_id=gap_id,
                    related_claim_ids=[str(item) for item in gap.get("related_claim_ids", [])] if isinstance(gap.get("related_claim_ids"), list) else [],
                    payload={"gap": gap, "route": route.to_dict()},
                    status=MessageStatus.SENT,
                )
            )
    blackboard.sync_task_board()


def _message_type_for_gap(gap_type: str) -> MessageType:
    mapping = {
        "EVIDENCE_GAP": MessageType.REQUEST_EVIDENCE,
        "CITATION_GAP": MessageType.REQUEST_EVIDENCE,
        "NUMERIC_GAP": MessageType.REQUEST_RECALCULATION,
        "VALUATION_GAP": MessageType.REQUEST_RECALCULATION,
        "SOURCE_CONFLICT": MessageType.ESCALATE_CONFLICT,
    }
    return mapping.get(gap_type, MessageType.PROPOSE_REVISION)


def _current_gap_ids(state: Dict[str, Any]) -> List[str]:
    report = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
    return [str(gap.get("gap_id", "")) for gap in report.get("gaps", []) if isinstance(gap, dict) and str(gap.get("gap_id", ""))]


def _task_board_blocked_count(task_board: Any) -> int:
    if not isinstance(task_board, dict):
        return 0
    summary = task_board.get("summary", {})
    if isinstance(summary, dict):
        try:
            return int(summary.get("blocked_count", 0) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _task_board_resolution_rate(task_board: Any) -> float:
    if not isinstance(task_board, dict):
        return 0.0
    summary = task_board.get("summary", {})
    if isinstance(summary, dict):
        try:
            return round(float(summary.get("resolution_rate", 0.0) or 0.0), 4)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def agent_key_for_task(task_type: str) -> str:
    mapping = {
        "deep_researcher": "research",
        "browser": "browser",
        "deep_analyze": "analyze",
        "final_answer": "final_answer",
        "verifier": "verifier",
        "risk": "risk",
        "peer": "peer",
    }
    if task_type not in mapping:
        raise KeyError(f"unsupported dynamic task_type: {task_type}")
    return mapping[task_type]


def _task_type_order(task_type: str) -> int:
    order = {
        "deep_researcher": 10,
        "browser": 20,
        "deep_analyze": 30,
        "risk": 36,
        "peer": 37,
        "final_answer": 40,
        "verifier": 50,
    }
    return order.get(task_type, 99)


def _promote_candidates_to_records(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert evidence_candidates (search hits) to evidence_records format.

    Used when BrowserAgent returns nothing (local-data or offline mode) so that
    downstream agents can still attach evidence_ids to claims.
    """
    records = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        evidence_id = str(c.get("result_id") or c.get("evidence_id") or c.get("sample_id") or "")
        if not evidence_id:
            continue
        records.append({
            "evidence_id": evidence_id,
            "title": str(c.get("title", "")),
            "content": str(c.get("snippet", c.get("content", ""))),
            "source_url": str(c.get("url", c.get("source_url", ""))),
            "source_type": str(c.get("source_type", "search_candidate")),
            "score": float(c.get("score", 1.0)),
        })
    return records


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


def _preflight_symbol_check(state: Dict[str, Any]) -> None:
    """Abort report generation if resolved symbol doesn't match evidence records."""
    resolved = str(state.get("symbol") or "").upper()
    if not resolved:
        return
    evidence_records = state.get("evidence_records") or []
    if not evidence_records:
        return
    evidence_symbols = {
        str(r.get("symbol") or "").upper()
        for r in evidence_records
        if isinstance(r, dict) and r.get("symbol")
    }
    # Allow if resolved symbol appears in evidence, or evidence has no symbol tags
    if not evidence_symbols or resolved in evidence_symbols:
        return
    # Mismatch: evidence is for different tickers
    raise RuntimeError(
        f"Symbol mismatch: requested '{resolved}' but evidence records contain {sorted(evidence_symbols)}. "
        "Report generation aborted to prevent entity confusion."
    )


def _derive_rating(analysis_artifacts: Dict[str, Any]) -> str:
    """Map model recommendation text to SAC five-tier rating."""
    if not isinstance(analysis_artifacts, dict):
        return "未评级"
    valuation = analysis_artifacts.get("valuation") or {}
    recommendation = str(valuation.get("recommendation") or "").strip()
    mapping = {
        "积极关注": "增持",
        "中性偏积极": "中性",
        "中性观察": "中性",
        "谨慎": "减持",
    }
    return mapping.get(recommendation, "未评级")


def _resolve_display_period(evidence_records: List[Dict[str, Any]], requested_period: str) -> str:
    """Return the actual financial period from SEC evidence, replacing 'latest' with the real period label."""
    if requested_period and requested_period.lower() != "latest":
        return requested_period
    for record in evidence_records:
        if not isinstance(record, dict):
            continue
        if str(record.get("source_type") or "").lower() != "financials":
            continue
        period = str(record.get("period") or "").strip()
        if period and period.lower() != "latest":
            return period
    return requested_period


def _period_granularity(period: str) -> str:
    value = str(period or "").lower()
    if "ttm" in value:
        return "trailing_12_months"
    if "q" in value or "quarter" in value or "季度" in value:
        return "quarter"
    return "year" if value[:4].isdigit() else "quarter"


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


def _load_optional_model(config_path: str, section: str) -> ModelAdapter | None:
    try:
        return ModelAdapter.from_config(config_path=config_path, section=section)
    except Exception:
        return None


def _load_model_routing(config_path: str) -> Dict[str, Any]:
    defaults = {
        "default_chain": "flash",
        "pro_policy": "conditional",
        "timeout_policy": {
            "flash_default_timeout_sec": 30,
            "flash_long_timeout_sec": 60,
            "pro_judge_timeout_sec": 90,
            "pro_refiner_timeout_sec": 120,
            "external_api_timeout_isolated": True,
        },
        "pro_triggers": ["verifier_fail", "evidence_gap", "valuation_formula_error", "multimodal_conflict", "entity_or_period_mismatch"],
        "pro_roles": ["final_answer_rework", "verifier_recheck"],
    }
    try:
        config = load_config(config_path)
    except Exception:
        return defaults
    routing = config.get("model_routing", {})
    if not isinstance(routing, dict):
        return defaults
    merged = dict(defaults)
    merged.update(routing)
    if isinstance(defaults.get("timeout_policy"), dict) and isinstance(routing.get("timeout_policy"), dict):
        timeout_policy = dict(defaults["timeout_policy"])
        timeout_policy.update(routing["timeout_policy"])
        merged["timeout_policy"] = timeout_policy
    return merged


def _count_pro_route_trace(trace: List[Dict[str, Any]]) -> int:
    return sum(1 for item in trace if str(item.get("model_route", "")).startswith("pro_"))


def _select_target_metric_row(ratio_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    for row in ratio_rows:
        if not isinstance(row, dict):
            continue
        if any(
            _metric_value_present(row.get(key))
            for key in [
                "revenue_billion",
                "net_income_billion",
                "gross_margin_pct",
                "net_margin_pct",
                "operating_cash_flow_billion",
                "free_cash_flow_billion",
            ]
        ):
            return row
    return ratio_rows[0] if ratio_rows else {}


def _metric_value_present(value: Any) -> bool:
    try:
        if value is None or str(value) == "nan":
            return False
        parsed = float(value)
        return parsed == parsed
    except (TypeError, ValueError):
        return False
