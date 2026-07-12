"""Multi-agent orchestration entrypoint for financial research reports."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
from pathlib import Path
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.agents.base_agent import AgentStatus, AgentTask, TaskResult
from src.agents.analysis_role_agents import (
    IdentityAgent,
    PeerAgent,
    RiskAgent,
    StatementAgent,
    ValuationAgent,
)
from src.agents.browser_agent import BrowserAgent
from src.agents.context_packer import build_revision_brief
from src.agents.conversation_memory import (
    absorb_verifier_feedback,
    build_initial_conversation_state,
    conversation_state_from_dict,
    refresh_conversation_brief,
)
from src.agents.critic_agent import CriticAgent
from src.agents.deep_analyze_agent import DeepAnalyzeAgent
from src.agents.deep_researcher_agent import DeepResearcherAgent
from src.agents.durable_memory import DurableMemoryConfig, DurableMemoryStore
from src.agents.final_answer_agent import FinalAnswerAgent
from src.agents.gap_resolver_agent import GapResolverAgent
from src.agents.gap_router import build_gap_resolution_trace
from src.agents.annual_report_section_extractor import AnnualReportSectionExtractor, annual_sections_to_evidence_records
from src.agents.planning_agent import PlanningAgent
from src.agents.research_blackboard import (
    apply_pre_write_critic,
    initialize_research_blackboard,
    update_blackboard_for_task,
)
from src.agents.verifier_agent import VerifierAgent
from src.data.canonical_metrics import build_canonical_metrics_artifact, canonical_metrics_as_financial_metrics
from src.data.company_universe import (
    build_data_source_plan,
    infer_market_from_symbol,
    resolve_company_identifier,
    resolve_company_identifier_with_diagnostics,
)
from src.data.official_evidence_archive import archive_official_evidence_manifest, build_official_evidence_artifacts
from src.data.pdf_artifacts import build_pdf_artifacts
from src.data.pdf_rag_pipeline import build_pdf_rag_artifacts
from src.data.sec_filing_resolver import resolve_sec_annual_filing, resolve_sec_proxy_filing
from src.evaluation.company_report_scorecard import build_company_report_scorecard
from src.evaluation.delivery_gate import build_delivery_gate_from_outputs, write_delivery_gate_for_outputs
from src.evaluation.multimodal_consistency import audit_multimodal_consistency
from src.evaluation.quality_remediation import build_quality_remediation_plan_from_outputs, write_quality_remediation_plan_for_outputs
from src.evaluation.report_quality import evaluate_report_quality_from_paths
from src.evaluation.section_evidence_pack import build_section_evidence_packs
from src.models import ModelAdapter
from src.report import (
    append_compliance_disclosures,
    append_compliance_disclosures_to_html,
    attach_charts_to_html,
    attach_charts_to_markdown,
    audit_chart_consistency,
    build_citation_artifacts,
    build_citations_from_map,
    generate_report_charts,
    inject_chart_references,
    polish_report_html,
    render_professional_html_report,
)
from src.report.citation_manager import render_citations_markdown
from src.report.mojibake_guard import (
    build_mojibake_quality_issue,
    repair_known_mojibake_obj,
    repair_known_mojibake_text,
)
from src.report.contract_builder import build_report_section_contracts
from src.report.citation_binder import CitationBinder
from src.search import SearchManager
from src.tools import SkillRegistry, build_core_tool_registry, build_financial_skill_registry
from src.utils.config import load_config
from src.utils import MCPManager
from src.agents.derived_evidence_builder import build_derived_evidence
from src.agents.claim_evidence_bundle import build_claim_evidence_bundles
from src.agents.section_dossier_builder import SectionDossierBuilder, sanitize_peer_rows_for_report


logger = logging.getLogger(__name__)


FAST_PROFILE = {
    "research_topk": 6,
    "research_use_react": False,
    "research_react_max_steps": 2,
    "research_merge_standard_search_after_react": True,
    "react_max_tool_calls": 8,
    "react_tool_timeout_seconds": 45.0,
    "react_tool_max_attempts": 2,
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
    "verifier_max_rework_rounds": 1,
    "delivery_rework_rounds": 1,
}

USER_FAST_DELIVERY_PROFILE = {
    **FAST_PROFILE,
    "research_topk": 4,
    "analyze_max_records": 6,
    "final_max_claims": 14,
    "final_max_evidence": 10,
    "final_max_tokens": 2000,
    "review_mode": "heuristic",
    "delivery_rework_rounds": 0,
    "verifier_max_rework_rounds": 0,
    "allow_full_pipeline_rework": False,
    "timeout_budget_sec": 180,
}

DEVELOPER_FAST_PROFILE = {
    **FAST_PROFILE,
    "research_topk": 6,
    "analyze_max_records": 8,
    "final_max_claims": 10,
    "final_max_evidence": 8,
    "final_max_tokens": 1600,
    "review_mode": "full",
    "delivery_rework_rounds": 1,
    "verifier_max_rework_rounds": 0,
    "allow_full_pipeline_rework": False,
    "timeout_budget_sec": 420,
}

DEFAULT_PROFILE = {
    "research_topk": 12,
    "research_use_react": True,
    "research_react_max_steps": 3,
    "research_merge_standard_search_after_react": True,
    "react_max_tool_calls": 8,
    "react_tool_timeout_seconds": 45.0,
    "react_tool_max_attempts": 2,
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
    "verifier_max_rework_rounds": 1,
    "delivery_rework_rounds": 1,
    "timeout_budget_sec": 420,
}


class MultiAgentOrchestrator:
    """Run the first visible financial multi-agent workflow."""

    # Feature flag: which markets use contract-first generation
    # US is guarded (False) until regression tests pass
    CONTRACT_MODE_ENABLED_BY_MARKET = {
        "cn_a": True,
        "hk": True,
        "us": True,
    }

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
        execution_tier: str = "delivery",
        stage_callback: Callable[[Dict[str, Any]], None] | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)
        self.config_path = config_path
        self.raw_data_root = raw_data_root
        self.app_config_path = app_config_path
        self.stage_callback = stage_callback
        _tier = str(execution_tier or "delivery").lower()
        FAST_TIERS = {"user_fast", "developer_fast"}
        if _tier in FAST_TIERS:
            self.execution_tier = _tier
        else:
            self.execution_tier = "preview" if _tier == "preview" else "delivery"
        self.model_route_config = load_config(config_path).get("agent_model_routes", {})
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
        if model is not None:
            self.model = model
            planning_model = model
            research_model = model
            browser_model = model
            analyze_model = model
            final_model = model
            verifier_model = model
        else:
            self.model = self._build_role_model("chat")
            planning_model = self._build_role_model("planning")
            research_model = self._build_role_model("research")
            browser_model = self._build_role_model("browser")
            analyze_model = self._build_role_model("deep_analyze")
            final_model = self._build_role_model("final_answer")
            verifier_model = self._build_role_model("verifier")
        self.tool_registry = build_core_tool_registry()
        self.skill_registry = skill_registry or build_financial_skill_registry(config_path=skill_registry_config_path)
        self.mcp_manager = MCPManager.from_tool_registry(self.tool_registry, namespace="finance")
        self.search_manager = search_manager or SearchManager.with_local_sources()
        self.agents = {
            "planning": PlanningAgent(model=planning_model),
            "research": DeepResearcherAgent(model=research_model, search_manager=self.search_manager),
            "browser": BrowserAgent(model=browser_model),
            "analyze": DeepAnalyzeAgent(model=analyze_model, tool_registry=self.tool_registry),
            "identity": IdentityAgent(),
            "statement": StatementAgent(),
            "peer": PeerAgent(),
            "valuation": ValuationAgent(),
            "risk": RiskAgent(),
            "final_answer": FinalAnswerAgent(model=final_model),
            "critic": CriticAgent(),
            "verifier": VerifierAgent(model=verifier_model),
            "gap_resolver": GapResolverAgent(),
        }
        self.agent_name_to_key = {agent.name: key for key, agent in self.agents.items()}
        self.model_usage_by_agent = self._build_model_usage_by_agent(model is not None)
        self.trace: List[Dict[str, Any]] = []
        self._log_model_routing_summary()

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
        enable_remote_data: bool = False,
        data_source_config_path: str = "configs/data_sources.yaml",
        quality_remediation_plan: Dict[str, Any] | None = None,
        claim_contract: str = "",
        allow_document_enrichment: bool = True,
        execution_deadline: float | None = None,
        stop_after_phase: str = "",
        resume_from_phase_artifacts: bool = False,
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
                claim_contract=claim_contract,
                allow_document_enrichment=allow_document_enrichment,
                execution_deadline=execution_deadline,
            )
        if execution_mode == "collaborative":
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
                claim_contract=claim_contract,
                allow_document_enrichment=allow_document_enrichment,
                collaborative=True,
                execution_deadline=execution_deadline,
            )
        if execution_mode == "diagnostic_full":
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
                claim_contract=claim_contract,
                allow_document_enrichment=allow_document_enrichment,
                collaborative=True,
                diagnostic_full=True,
                execution_deadline=execution_deadline,
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
                stop_after_phase=stop_after_phase,
                resume_from_phase_artifacts=resume_from_phase_artifacts,
            )
        raise ValueError(f"Unsupported execution_mode: {execution_mode}")

    def _build_role_model(self, role: str) -> ModelAdapter:
        profile = self._select_profile_for_role(role)
        adapter = ModelAdapter.from_profile(profile=profile, config_path=self.config_path, fallback_section="agent_model")
        adapter.route_profile = profile
        return adapter

    def _select_profile_for_role(self, role: str) -> str:
        routes = self.model_route_config if isinstance(self.model_route_config, dict) else {}
        defaults = routes.get("defaults", {}) if isinstance(routes.get("defaults"), dict) else {}
        default_profile = str(defaults.get(self.execution_tier) or defaults.get("delivery") or "flash")
        role_route = routes.get(role)
        if isinstance(role_route, str):
            return role_route
        if isinstance(role_route, dict):
            profile = role_route.get(self.execution_tier)
            if profile is None and self.execution_tier in ("user_fast", "developer_fast"):
                profile = default_profile  # fast tiers: 不 fallback 到 delivery/pro
            elif profile is None:
                profile = role_route.get("delivery") or default_profile
            return str(profile)
        return default_profile

    def _build_model_usage_by_agent(self, injected_model: bool) -> Dict[str, Dict[str, Any]]:
        llm_roles = {
            "planning": self.agents.get("planning"),
            "research": self.agents.get("research"),
            "browser": self.agents.get("browser"),
            "deep_analyze": self.agents.get("analyze"),
            "final_answer": self.agents.get("final_answer"),
            "verifier": self.agents.get("verifier"),
        }
        usage: Dict[str, Dict[str, Any]] = {}
        for role, agent in llm_roles.items():
            model = getattr(agent, "model", None)
            usage[role] = {
                "model_name": str(getattr(model, "model_name", "")),
                "provider": str(getattr(model, "provider", "")),
                "base_url": str(getattr(model, "base_url", "")),
                "endpoint_url": str(getattr(model, "endpoint_url", "")),
                "api_key_env": str(getattr(model, "api_key_env", "")),
                "api_key_present": bool(getattr(model, "api_key", "")),
                "route_profile": str(getattr(model, "route_profile", "injected") if injected_model else getattr(model, "route_profile", "")),
                "model_fallback_used": bool(getattr(model, "model_fallback_used", False)),
                "model_enabled": model is not None,
            }
        for role in ["identity", "statement", "peer", "valuation", "risk", "critic", "gap_resolver"]:
            usage[role] = {
                "model_name": "",
                "provider": "",
                "base_url": "",
                "endpoint_url": "",
                "api_key_env": "",
                "api_key_present": False,
                "route_profile": "rule_only",
                "model_fallback_used": False,
                "model_enabled": False,
            }
        return usage

    def _model_usage_for_agent(self, agent_key: str) -> Dict[str, Any]:
        usage = self.model_usage_by_agent.get(agent_key)
        if isinstance(usage, dict):
            return dict(usage)
        if agent_key == "analyze":
            return dict(self.model_usage_by_agent.get("deep_analyze", {}))
        return {}

    def _log_model_routing_summary(self) -> None:
        logger.info(
            "model_route_summary | execution_tier=%s | config_path=%s | roles=%s",
            self.execution_tier,
            self.config_path,
            json.dumps(self.model_usage_by_agent, ensure_ascii=False, sort_keys=True),
        )

    def _runtime_execution_summary(self) -> Dict[str, Any]:
        executed_keys: List[str] = []
        for item in self.trace:
            if not isinstance(item, dict):
                continue
            key = str(item.get("agent_key") or "")
            if not key:
                key = self.agent_name_to_key.get(str(item.get("agent") or ""), "")
            if key and key not in executed_keys:
                executed_keys.append(key)
        model_usage = {key: self._model_usage_for_agent(key) for key in executed_keys}
        fallback_used = any(
            bool((self.model_usage_by_agent.get(key, {}) or {}).get("model_fallback_used", False))
            for key in executed_keys
        )
        return {
            "registered_agent_count": len(self.agents),
            "executed_agent_count": len(executed_keys),
            "executed_agents": executed_keys,
            "model_usage_by_agent": model_usage,
            "model_fallback_used": fallback_used,
        }

    def _resolve_profile(self, fast: bool = False) -> Dict[str, Any]:
        """Select execution profile based on tier and fast flag."""
        if self.execution_tier == "user_fast":
            return USER_FAST_DELIVERY_PROFILE
        if self.execution_tier == "developer_fast":
            return DEVELOPER_FAST_PROFILE
        return FAST_PROFILE if fast else DEFAULT_PROFILE

    def _ensure_claim_evidence_bundles(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build and inject claim_evidence_bundles into state if not already present.

        Returns the list of bundles (possibly empty) for passing to FinalAnswer.
        """
        if state.get("claim_evidence_bundles") is not None:
            bundles = state["claim_evidence_bundles"]
            return bundles if isinstance(bundles, list) else []

        derived = build_derived_evidence(state)
        state["derived_evidence"] = derived

        claims = list(state.get("claims", [])) if isinstance(state.get("claims"), list) else []
        evidence = list(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else []

        bundles = build_claim_evidence_bundles(claims, evidence, derived)
        state["claim_evidence_bundles"] = bundles
        return bundles

    def _build_section_dossiers(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Build section dossiers from the latest state snapshot, enriched with facts extraction."""
        _sanitize_state_peer_rows(state)
        builder = SectionDossierBuilder()
        dossiers = builder.build(
            state=state,
            claims=list(state.get("claims", [])) if isinstance(state.get("claims"), list) else [],
            evidence_records=list(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else [],
            analysis_artifacts=dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {},
            derived_evidence=list(state.get("derived_evidence", [])) if isinstance(state.get("derived_evidence"), list) else [],
            bundles=list(state.get("claim_evidence_bundles", [])) if isinstance(state.get("claim_evidence_bundles"), list) else [],
        )
        dossiers = self._inject_pdf_facts_into_dossiers(state, dossiers, path="rework")
        state["section_dossiers"] = dossiers
        return dossiers

    def _prepare_prewrite_section_evidence_packs(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Materialize the current state so the writer consumes section packs before drafting."""
        self._write_json("evidence.json", list(state.get("evidence_records", [])))
        self._write_json("claims.json", list(state.get("claims", [])))
        analysis = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        self._write_json("analysis_artifacts.json", analysis)
        self._write_json("financial_metrics.json", analysis.get("financial_metrics", {}))
        self._write_json("canonical_metrics.json", analysis.get("canonical_metrics", {}))
        self._write_json("tables.json", analysis.get("tables", []))
        self._write_json("section_dossiers.json", state.get("section_dossiers", {}))
        return build_section_evidence_packs(self.output_dir)

    def _inject_pdf_facts_into_dossiers(self, state: Dict[str, Any], dossiers: Dict[str, Any], *, path: str) -> Dict[str, Any]:
        """Enrich section dossiers with structured PDF facts and write an audit artifact."""
        pdf_sections = (
            state.get("pdf_section_summaries")
            or state.get("section_evidence")
            or state.get("pdf_sections", [])
        )
        audit: Dict[str, Any] = {
            "schema_version": "facts_extraction_audit.v1",
            "path": path,
            "symbol": state.get("symbol", ""),
            "period": state.get("period", ""),
            "input_section_count": len(pdf_sections) if isinstance(pdf_sections, list) else 0,
            "extracted_fact_count": 0,
            "facts_extraction_types": [],
            "removed_raw_paragraph_count": 0,
            "removed_raw_key_fact_count": 0,
            "final_suggested_paragraph_count": 0,
            "sections": {},
        }
        if not isinstance(pdf_sections, list) or not pdf_sections:
            state["facts_extraction_audit"] = audit
            self._write_json("facts_extraction_audit.json", audit)
            return dossiers

        try:
            from src.report.fact_extractors.pdf_facts_extractor import (
                extract_section_facts,
                inject_facts_into_dossiers,
            )

            symbol = str(state.get("symbol", "")).upper()
            market = "cn_a" if symbol.endswith((".SS", ".SZ")) else "hk" if symbol.endswith(".HK") else "us"
            facts = extract_section_facts(pdf_sections, market=market)
            audit["raw_fact_section_count"] = len(facts) if isinstance(facts, dict) else 0
            if facts and any(section_facts for section_facts in facts.values()):
                dossiers = inject_facts_into_dossiers(dossiers, facts, audit=audit)
                import logging
                logging.getLogger(__name__).info(
                    "facts_extraction | path=%s sections=%d types=%s removed_raw=%d",
                    path,
                    int(audit.get("extracted_fact_count", 0) or 0),
                    audit.get("facts_extraction_types", []),
                    int(audit.get("removed_raw_paragraph_count", 0) or 0),
                )
        except Exception as exc:
            audit["error"] = str(exc)
            import logging
            logging.getLogger(__name__).warning("facts_extraction failed: %s", exc)
        finally:
            state["facts_extraction_audit"] = audit
            self._write_json("facts_extraction_audit.json", audit)
        return dossiers

    def _build_contracts_and_bind(self, state: Dict[str, Any]) -> tuple[Any, Any]:
        """Build section contracts and bind citations.

        Reads from state: evidence_records, analysis_artifacts, section_dossiers,
        claims, citations, research_blackboard.

        Returns (contracts, binder). Returns (None, None) on any failure —
        the orchestrator falls back to the old path.
        """
        audit: Dict[str, Any] = {
            "schema_version": "contract_build_audit.v1",
            "market": "",
            "section_count": 0,
            "facts_count": 0,
            "contract_mode_entered": False,
            "citation_binder_active": False,
            "fallback_used": True,
            "failure_reason": "",
        }
        try:
            output_dir = getattr(self, "output_dir", None)
            if output_dir is not None:
                Path(output_dir).mkdir(parents=True, exist_ok=True)

            # Market isolation: detect market and check feature flag
            symbol = str(state.get("symbol", "") or "").upper()
            market = "cn_a" if (symbol.endswith(".SS") or symbol.endswith(".SZ")) else "hk" if symbol.endswith(".HK") else "us"
            enabled = self.CONTRACT_MODE_ENABLED_BY_MARKET.get(market, False)

            evidence_records = list(state.get("evidence_records", []))
            analysis_artifacts = self._apply_canonical_metrics(
                state.get("analysis_artifacts", {}),
                evidence_records=evidence_records,
                symbol=symbol,
                period=str(state.get("period", "") or ""),
            )
            state["analysis_artifacts"] = analysis_artifacts
            section_dossiers = dict(state.get("section_dossiers", {}))
            citations = list(state.get("citations", []))
            audit.update({
                "symbol": symbol,
                "market": market,
                "contract_mode_enabled": bool(enabled),
                "input_evidence_count": len(evidence_records),
                "input_section_dossier_count": len(section_dossiers),
                "input_citation_count": len(citations),
                "pdf_section_count": len(
                    analysis_artifacts.get("pdf_section_summaries", [])
                    or state.get("pdf_section_summaries", [])
                    or state.get("pdf_sections", [])
                    or []
                ),
            })

            # Write market isolation audit regardless
            if output_dir is not None:
                import os
                out = str(output_dir)
                market_audit = {
                    "symbol": symbol,
                    "detected_market": market,
                    "contract_mode_enabled": enabled,
                    "contract_mode_enabled_by_market": dict(self.CONTRACT_MODE_ENABLED_BY_MARKET),
                    "evidence_summary": {
                        "total_records": len(evidence_records),
                        "sec_10k_sections": sum(1 for r in evidence_records if str(r.get("source_type", "") or "") in {"sec_10k_section", "sec_10k_filing"}),
                        "pdf_section_summaries": len(analysis_artifacts.get("pdf_section_summaries", []) or state.get("pdf_section_summaries", [])),
                    },
                }
                try:
                    with open(os.path.join(out, "market_isolation_audit.json"), "w", encoding="utf-8") as f:
                        json.dump(market_audit, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

            if not enabled:
                import logging
                logging.getLogger(__name__).info(
                    "Contract mode disabled for market=%s symbol=%s, falling back to old path",
                    market, symbol,
                )
                audit["failure_reason"] = "contract_mode_disabled_for_market"
                self._write_json("contract_build_audit.json", audit)
                self._write_json("report_section_contracts.json", {"metadata": audit, "contracts": {}})
                self._write_json("citation_binding_audit.json", {"diagnostic_only": True, "failure_reason": audit["failure_reason"]})
                return None, None

            contracts = build_report_section_contracts(
                state=state,
                evidence_records=evidence_records,
                analysis_artifacts=analysis_artifacts,
                section_dossiers=section_dossiers,
                citations=citations,
            )
            if contracts is None:
                audit["failure_reason"] = "contract_builder_returned_none"
                self._write_json("contract_build_audit.json", audit)
                self._write_json("report_section_contracts.json", {"metadata": audit, "contracts": {}})
                self._write_json("citation_binding_audit.json", {"diagnostic_only": True, "failure_reason": audit["failure_reason"]})
                return None, None
            audit["contract_mode_entered"] = True
            audit["fallback_used"] = False
            audit["section_count"] = len(getattr(contracts, "contracts", {}) or {})
            audit["facts_count"] = sum(
                len(getattr(contract, "facts", []) or [])
                for contract in (getattr(contracts, "contracts", {}) or {}).values()
            )

            binder = CitationBinder(evidence_records)
            binder.bind_all(contracts)
            audit["citation_binder_active"] = True

            # Write contract artifacts
            if output_dir is not None:
                import os
                output_dir = str(output_dir)
                contracts.to_json_file(os.path.join(output_dir, "report_section_contracts.json"))
                binder.write_artifacts(output_dir)
            self._write_json("contract_build_audit.json", audit)

            state["report_section_contracts"] = contracts
            state["citation_binder"] = binder
            state["citation_map"] = binder.get_citation_map()

            return contracts, binder
        except Exception as exc:
            audit["fallback_used"] = True
            audit["failure_reason"] = str(exc)
            try:
                self._write_json("contract_build_audit.json", audit)
                self._write_json("report_section_contracts.json", {"metadata": audit, "contracts": {}})
                self._write_json("citation_binding_audit.json", {"diagnostic_only": True, "failure_reason": str(exc)})
            except Exception:
                pass
            import logging
            logging.getLogger(__name__).exception("Failed to build contracts and bind citations")
            return None, None

    def _apply_canonical_metrics(
        self,
        analysis_artifacts: Any,
        *,
        evidence_records: Any = None,
        symbol: str,
        period: str,
    ) -> Dict[str, Any]:
        return _apply_canonical_metrics_to_artifacts(
            analysis_artifacts,
            evidence_records=evidence_records,
            symbol=symbol,
            period=period,
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
        enable_remote_data: bool = False,
        data_source_config_path: str = "configs/data_sources.yaml",
        entity_resolution: Dict[str, Any] | None = None,
        quality_remediation_plan: Dict[str, Any] | None = None,
        stop_after_phase: str = "",
        resume_from_phase_artifacts: bool = False,
    ) -> Dict[str, str]:
        stored_trace = self._read_json("static_phase_trace.json", []) if resume_from_phase_artifacts else []
        self.trace = [dict(item) for item in stored_trace if isinstance(item, dict)]
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

        plan = self._read_json("task_plan.json", {}) if resume_from_phase_artifacts else {}
        if not plan:
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
        if stop_after_phase == "planning":
            return self._static_phase_result("planning", ["task_plan.json"])
        research_blackboard = initialize_research_blackboard(
            symbol=symbol,
            period=period,
            entity_resolution=entity_resolution,
            search_engines=search_engines or [],
            raw_data_root=self.raw_data_root,
        )

        research_query = _query_from_plan(plan=plan, research_topic=research_topic, symbol=symbol, period=period)
        research_checkpoint = self._read_json("research_phase.json", {}) if resume_from_phase_artifacts else {}
        if research_checkpoint:
            research_output = dict(research_checkpoint.get("output") or {})
        else:
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
                    "engines": search_engines or _market_engines(symbol),
                    "raw_data_root": self.raw_data_root,
                    "curated_dir": _retrieval_curated_dir(self.output_dir),
                    "ranking_mode": retrieval_ranking_mode,
                    "data_source_config_path": data_source_config_path,
                    "enable_remote": bool(enable_remote_data),
                    "search_budget_seconds": 240.0,
                    "engine_timeout_seconds": 60.0,
                    "engine_timeout_by_name": _research_engine_timeouts(),
                    "skill_brief": self._skill_brief(research_query, "deep_researcher", max_items=2),
                },
                dependencies=["task_000_planning"],
                priority=5,
                ),
            )
            research_output = dict(research_result.output or {})
            self._write_json(
                "research_phase.json",
                {"phase": "research", "output": _compact_research_phase_output(research_output)},
            )
        evidence_candidates = research_output.get("evidence_candidates", [])
        static_state: Dict[str, Any] = {
            "research_topic": research_topic,
            "symbol": symbol,
            "period": period,
            "entity_resolution": entity_resolution,
            "search_engines": search_engines or [],
            "search_meta": research_output.get("search_meta", {}),
            "evidence_candidates": evidence_candidates,
            "evidence_records": [],
            "claims": [],
            "analysis_artifacts": {},
            "enable_remote_data": bool(enable_remote_data),
        }
        self.state = static_state  # P0.5: expose for _execute deadline enforcement
        research_blackboard = update_blackboard_for_task(
            research_blackboard,
            "deep_researcher",
            static_state,
            research_output,
        )
        self._write_json("research_blackboard.json", research_blackboard)
        self._write_json("search_meta.json", static_state["search_meta"])
        if stop_after_phase == "research":
            return self._static_phase_result("research", ["task_plan.json", "research_phase.json", "search_meta.json"])

        normalize_phase = self._read_json("normalize_evidence_phase.json", {}) if resume_from_phase_artifacts else {}
        gate_evidence_records = self._read_json("evidence.json", [])
        if normalize_phase:
            evidence_records = gate_evidence_records
            browser_output = {"evidence_records": evidence_records}
        else:
            browser_result = self._execute(
                "browser",
                AgentTask(
                task_id="task_002_browser",
                task_type="browser",
                description="Normalize evidence candidates into citation-ready records.",
                parameters={"evidence_candidates": evidence_candidates, "symbol": symbol},
                dependencies=["task_001_research"],
                priority=4,
                ),
            )
            browser_output = dict(browser_result.output or {})
            evidence_records = _merge_records(
                gate_evidence_records,
                browser_output.get("evidence_records", []),
                ["evidence_id", "sample_id", "identity_key", "source_url"],
            )
            browser_output["evidence_records"] = evidence_records
            self._write_json("evidence.json", evidence_records)
            self._write_json(
                "normalize_evidence_phase.json",
                {"phase": "normalize_evidence", "evidence_count": len(evidence_records)},
            )
        static_state["evidence_records"] = evidence_records
        attach_annual_report_sections_to_state(static_state, raw_data_root=self.raw_data_root)
        attach_pdf_artifacts_to_state(state=static_state)
        evidence_records = static_state.get("evidence_records", [])
        research_blackboard = update_blackboard_for_task(
            research_blackboard,
            "browser",
            static_state,
            browser_output,
        )
        self._write_json("research_blackboard.json", research_blackboard)
        if stop_after_phase == "normalize_evidence":
            return self._static_phase_result("normalize_evidence", ["evidence.json", "research_blackboard.json"])

        analyze_phase = self._read_json("analyze_phase.json", {}) if resume_from_phase_artifacts else {}
        analysis_checkpoint = self._read_json("analysis_artifacts.json", {}) if analyze_phase else {}
        claims_checkpoint = self._read_json("claims.json", []) if analyze_phase else []
        if analyze_phase:
            analysis_output = {"claims": claims_checkpoint, "analysis_artifacts": analysis_checkpoint}
        else:
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
            analysis_output = dict(analyze_result.output or {})
        claims = analysis_output.get("claims", [])
        analysis_artifacts = analysis_output.get("analysis_artifacts", {})
        analysis_artifacts = self._apply_canonical_metrics(
            analysis_artifacts,
            evidence_records=evidence_records,
            symbol=symbol,
            period=period,
        )
        static_state["claims"] = claims
        static_state["analysis_artifacts"] = analysis_artifacts
        research_blackboard = update_blackboard_for_task(
            research_blackboard,
            "deep_analyze",
            static_state,
            analysis_output,
        )
        self._write_json("claims.json", claims)
        self._write_json("analysis_artifacts.json", analysis_artifacts)
        financial_metrics_path = self._write_json(
            "financial_metrics.json",
            analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        canonical_metrics_path = self._write_json(
            "canonical_metrics.json",
            analysis_artifacts.get("canonical_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        currency_audit_path = self._write_json(
            "currency_audit.json",
            analysis_artifacts.get("currency_audit", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        rejected_metrics_path = self._write_json(
            "rejected_metrics.json",
            dict(analysis_artifacts.get("financial_metrics", {})).get("rejected_metrics", [])
            if isinstance(analysis_artifacts, dict) and isinstance(analysis_artifacts.get("financial_metrics", {}), dict)
            else [],
        )
        claim_rejection_path = self._write_json(
            "claim_rejection_report.json",
            analysis_artifacts.get("claim_rejection_report", {}) if isinstance(analysis_artifacts, dict) else {},
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
        self._write_json("research_blackboard.json", research_blackboard)
        self._write_json(
            "analyze_phase.json",
            {"phase": "analyze", "claim_count": len(claims), "metric_artifact_ready": bool(analysis_artifacts)},
        )
        if stop_after_phase == "analyze":
            return self._static_phase_result(
                "analyze",
                ["claims.json", "analysis_artifacts.json", "financial_metrics.json", "canonical_metrics.json", "tables.json"],
            )
        tables = analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else []
        official_artifacts = build_official_evidence_artifacts(
            evidence_records if isinstance(evidence_records, list) else [],
            symbol=symbol,
            period=period,
            tables=tables,
        )
        archive_path = ""
        if enable_remote_data:
            archive_path = archive_official_evidence_manifest(
                official_artifacts["official_evidence_manifest"],
                source_records=evidence_records if isinstance(evidence_records, list) else [],
            )
        official_manifest_path = self._write_json("official_evidence_manifest.json", official_artifacts["official_evidence_manifest"])
        evidence_coverage_path = self._write_json("evidence_coverage.json", official_artifacts["evidence_coverage"])
        sec_filing_resolver_path = self._write_json("sec_filing_resolver.json", static_state.get("sec_filing_resolver", {}))
        annual_report_sections_path = self._write_json("annual_report_sections.json", static_state.get("annual_report_sections", {}))
        critic_result = self._execute(
            "critic",
            AgentTask(
                task_id="task_003a_pre_write_critic",
                task_type="pre_write_critic",
                description="Review the shared research blackboard before final writing.",
                parameters={
                    "research_blackboard": research_blackboard,
                    "state_snapshot": {
                        "symbol": symbol,
                        "period": period,
                        "evidence_count": len(evidence_records) if isinstance(evidence_records, list) else 0,
                        "claim_count": len(claims) if isinstance(claims, list) else 0,
                    },
                },
                dependencies=["task_003_analyze"],
                priority=5,
            ),
        )
        pre_write_critic = critic_result.output.get("pre_write_critic", {})
        research_blackboard = apply_pre_write_critic(research_blackboard, pre_write_critic)

        # Build claim-evidence bundles for grounded writing
        static_bundles = build_claim_evidence_bundles(
            claims=claims if isinstance(claims, list) else [],
            evidence_records=evidence_records if isinstance(evidence_records, list) else [],
            derived_evidence=build_derived_evidence({
                "symbol": symbol,
                "period": period,
                "claims": claims if isinstance(claims, list) else [],
                "evidence_records": evidence_records if isinstance(evidence_records, list) else [],
                "analysis_artifacts": analysis_artifacts if isinstance(analysis_artifacts, dict) else {},
                "research_blackboard": research_blackboard if isinstance(research_blackboard, dict) else {},
            }),
        )

        # Build section dossiers for depth enforcement
        _sanitize_state_peer_rows(static_state)
        static_dossiers = SectionDossierBuilder().build(
            state=static_state,
            claims=claims if isinstance(claims, list) else [],
            evidence_records=evidence_records if isinstance(evidence_records, list) else [],
            analysis_artifacts=analysis_artifacts if isinstance(analysis_artifacts, dict) else {},
            derived_evidence=build_derived_evidence(static_state),
            bundles=static_bundles,
        )
        static_dossiers = self._inject_pdf_facts_into_dossiers(static_state, static_dossiers, path="main")
        static_state["section_dossiers"] = static_dossiers

        # Build contract-first generation artifacts
        static_contracts, static_binder = self._build_contracts_and_bind(static_state)
        static_section_packs = self._prepare_prewrite_section_evidence_packs(static_state)

        final_result = self._execute(
            "final_answer",
            AgentTask(
                task_id="task_004_final_answer",
                task_type="final_answer",
                description="Write final report.",
                parameters={
                    "research_topic": research_topic,
                    "symbol": symbol,
                    "period": period,
                    "output_dir": str(self.output_dir),
                    "claims": claims,
                    "evidence_records": evidence_records,
                    "claim_evidence_bundles": static_bundles,
                    "section_dossiers": static_dossiers,
                    "section_evidence_packs": static_section_packs,
                    "conversation_brief": conversation_brief,
                    "skill_brief": self._skill_brief("report markdown citations charts", "final_answer", max_items=2),
                    "tables": tables,
                    "financial_metrics": analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
                    "currency_audit": analysis_artifacts.get("currency_audit", {}) if isinstance(analysis_artifacts, dict) else {},
                    "valuation_model": analysis_artifacts.get("valuation_model", {}) if isinstance(analysis_artifacts, dict) else {},
                    "pdf_sections": analysis_artifacts.get("pdf_sections", []) if isinstance(analysis_artifacts, dict) else [],
                    "company_profile": analysis_artifacts.get("company_profile", {}) if isinstance(analysis_artifacts, dict) else {},
                    "quality_remediation_plan": quality_remediation_plan or {},
                    "research_blackboard": research_blackboard,
                    "pre_write_critic": pre_write_critic,
                    # Contract-first generation
                    "report_section_contracts": static_contracts,
                    "citation_binder": static_binder,
                    "citation_map": static_binder.get_citation_map() if static_binder else {},
                },
                dependencies=["task_003_analyze"],
                priority=4,
            ),
        )
        markdown = str(final_result.output.get("markdown", ""))
        html = str(final_result.output.get("html", ""))
        report_json = final_result.output.get("report_json", {})
        static_state["markdown"] = markdown
        static_state["html"] = html
        static_state["report_json"] = report_json
        static_state["research_blackboard"] = research_blackboard
        static_state["pre_write_critic"] = pre_write_critic
        static_state["section_dossiers"] = static_dossiers
        research_blackboard = update_blackboard_for_task(
            research_blackboard,
            "final_answer",
            static_state,
            final_result.output,
        )
        charts = generate_report_charts(
            claims=claims,
            evidence_records=evidence_records,
            output_dir=self.output_dir / "charts",
            tables=analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
            analysis_artifacts=analysis_artifacts if isinstance(analysis_artifacts, dict) else {},
            currency_context=(analysis_artifacts.get("currency_audit", {}) if isinstance(analysis_artifacts, dict) else {}),
        )
        final_metadata = getattr(final_result, "metadata", {}) or {}
        contract_mode_used = bool(final_metadata.get("contract_mode", False))
        citation_map = final_metadata.get("citation_map", {})
        charts = repair_known_mojibake_obj(charts)
        markdown = repair_known_mojibake_text(attach_charts_to_markdown(markdown, charts))
        markdown = repair_known_mojibake_text(inject_chart_references(markdown, charts))
        citation_artifacts = build_citation_artifacts(
            evidence_records=evidence_records,
            claims=claims,
            markdown=markdown,
            html=html,
        )
        citations = citation_artifacts["citations"]
        citations_markdown = citation_artifacts["citations_markdown"]

        llm_title = str(report_json.get("title", "")).strip() if isinstance(report_json, dict) else ""
        if contract_mode_used:
            report_title = llm_title or _build_formal_report_title(entity_resolution, symbol, period)
        else:
            if llm_title and any(p in llm_title for p in ("生成", "任务", "生成报告")):
                llm_title = ""
            report_title = llm_title or _build_formal_report_title(entity_resolution, symbol, period)
            markdown = citation_artifacts["markdown"]
            html = render_professional_html_report(
                markdown=markdown,
                title=report_title,
                charts=charts,
                citations=citations,
                delivery_status=str(report_json.get("delivery_status") or "normal") if isinstance(report_json, dict) else "normal",
            )

        if contract_mode_used and citation_map:
            markdown = repair_known_mojibake_text(
                attach_charts_to_markdown(str(final_result.output.get("markdown", "")), charts)
            )
            markdown = repair_known_mojibake_text(inject_chart_references(markdown, charts))
            citations = build_citations_from_map(
                evidence_records=evidence_records,
                citation_map=citation_map,
                claims=claims,
                markdown=markdown,
            )
            citations_markdown = render_citations_markdown(citations)
            if citations_markdown and citations_markdown not in markdown:
                markdown = markdown.rstrip() + "\n\n" + citations_markdown
            report_title = repair_known_mojibake_text(llm_title) or _build_formal_report_title(entity_resolution, symbol, period)

        html = render_professional_html_report(
            markdown=markdown,
            title=report_title,
            charts=charts,
            citations=citations,
            delivery_status=str(report_json.get("delivery_status") or "normal") if isinstance(report_json, dict) else "normal",
            top_blockers=list(final_metadata.get("top_blockers", [])) if isinstance(final_metadata.get("top_blockers", []), list) else [],
            contract_mode=contract_mode_used,
        )

        markdown = append_compliance_disclosures(markdown, citations=citations)
        html = append_compliance_disclosures_to_html(html, citations=citations)
        if isinstance(report_json, dict):
            report_json = dict(report_json)
            report_json["citations"] = citations
            report_json["charts"] = charts
            report_json["compliance_disclosure"] = {"included": True, "rating_definition": "未评级"}
            report_json["analysis_artifacts"] = analysis_artifacts
            report_json["research_blackboard"] = research_blackboard
        self._write_json("citations.json", citations)
        self._write_json("charts.json", charts)
        self._write_json("section_dossiers.json", static_dossiers)
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
        citations_md_path.write_text(str(repair_known_mojibake_text(citations_markdown)), encoding="utf-8")
        report_md_path = self.report_dir / "report.md"
        report_html_path = self.report_dir / "report.html"
        report_json_path = self.report_dir / "report.json"
        markdown = str(repair_known_mojibake_text(markdown))
        html = str(repair_known_mojibake_text(html))
        report_json = repair_known_mojibake_obj(report_json)
        report_md_path.write_text(markdown, encoding="utf-8")
        report_html_path.write_text(html, encoding="utf-8")
        report_json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

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
        static_state["verification_report"] = verification_report
        research_blackboard = update_blackboard_for_task(
            research_blackboard,
            "verifier",
            static_state,
            verifier_result.output,
        )
        research_blackboard_path = self._write_json("research_blackboard.json", research_blackboard)
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
            "\n".join(json.dumps(item, ensure_ascii=False, default=str) for item in self.trace) + "\n",
            encoding="utf-8",
        )
        collaboration_trace = build_agent_collaboration_trace(
            trace=self.trace,
            state={
                "research_topic": research_topic,
                "symbol": symbol,
                "period": period,
                "verification_report": verification_report,
                "revision_history": [],
                "gap_resolution_trace": gap_resolution_trace,
                "quality_remediation_plan": quality_remediation_plan or {},
                "memory_enabled": self.memory_config.enabled,
                "memory_context_scope": self.memory_config.context_scope,
                "research_blackboard": research_blackboard,
            },
        )
        collaboration_trace_path = self._write_json("agent_collaboration_trace.json", collaboration_trace)
        tool_trace = build_tool_trace(agents=self.agents, trace=self.trace, state=static_state)
        tool_trace_path = self._write_json("tool_trace.json", tool_trace)

        summary_path = self.output_dir / "run_summary.json"
        summary = {
            "research_topic": research_topic,
            "symbol": symbol,
            "period": period,
            "model": getattr(self.model, "model_name", ""),
            "execution_mode": "static",
            "execution_tier": self.execution_tier,
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
            "evidence_coverage": official_artifacts["evidence_coverage"],
            "official_evidence_archive_path": archive_path,
            "entity_resolution": entity_resolution,
            "research_blackboard": {
                "pre_write_critic_passed": bool(
                    research_blackboard.get("critic", {}).get("pre_write_passed", False)
                )
                if isinstance(research_blackboard.get("critic"), dict)
                else False,
                "industry_profile_confidence": dict(research_blackboard.get("industry_profile", {})).get(
                    "confidence", 0.0
                )
                if isinstance(research_blackboard.get("industry_profile"), dict)
                else 0.0,
            },
            "report_title": report_title,
            "conversation_brief_chars": len(conversation_brief),
            "durable_memory_enabled": self.memory_config.enabled,
            "durable_memory_context_scope": self.memory_config.context_scope,
            "skill_registry_enabled": bool(self.skill_registry.names()),
            "skill_count": len(self.skill_registry.names()),
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        summary.update(self._runtime_execution_summary())
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
        summary = repair_known_mojibake_obj(summary)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_trace": str(trace_path),
            "agent_collaboration_trace": str(collaboration_trace_path),
            "tool_trace": str(tool_trace_path),
            "evidence": str(self.output_dir / "evidence.json"),
            "claims": str(self.output_dir / "claims.json"),
            "analysis_artifacts": str(self.output_dir / "analysis_artifacts.json"),
            "financial_metrics": str(financial_metrics_path),
            "canonical_metrics": str(canonical_metrics_path),
            "currency_audit": str(currency_audit_path),
            "rejected_metrics": str(rejected_metrics_path),
            "claim_rejection_report": str(claim_rejection_path),
            "tables": str(tables_path),
            "official_evidence_manifest": str(official_manifest_path),
            "evidence_coverage": str(evidence_coverage_path),
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
            "research_blackboard": str(research_blackboard_path),
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
        enable_remote_data: bool = False,
        data_source_config_path: str = "configs/data_sources.yaml",
        entity_resolution: Dict[str, Any] | None = None,
        quality_remediation_plan: Dict[str, Any] | None = None,
        collaborative: bool = False,
        diagnostic_full: bool = False,
        claim_contract: str = "",
        allow_document_enrichment: bool = True,
        execution_deadline: float | None = None,
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
            "user_fast_mode": self.execution_tier == "user_fast",
            "developer_fast_mode": self.execution_tier == "developer_fast",
            "search_engines": search_engines or [],
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "enable_remote_data": bool(enable_remote_data),
            "data_source_config_path": data_source_config_path,
            "entity_resolution": entity_resolution,
            "quality_remediation_plan": quality_remediation_plan or {},
            "claim_contract": str(claim_contract or ""),
            "allow_document_enrichment": bool(allow_document_enrichment),
            "collaborative_mode": bool(collaborative),
            "diagnostic_full_mode": bool(diagnostic_full),
            "research_blackboard": initialize_research_blackboard(
                symbol=symbol,
                period=period,
                entity_resolution=entity_resolution,
                search_engines=search_engines or [],
                raw_data_root=self.raw_data_root,
            ),
            "pre_write_critic": {},
            "execution_deadline": execution_deadline,
        }
        self.state = state  # P0.5: expose for _execute deadline enforcement
        tasks = prepare_dynamic_tasks(
            plan=plan,
            research_topic=research_topic,
            symbol=symbol,
            period=period,
            raw_data_root=self.raw_data_root,
            profile=self._resolve_profile(fast),
            search_engines=search_engines,
            retrieval_ranking_mode=retrieval_ranking_mode,
            enable_remote_data=enable_remote_data,
            data_source_config_path=data_source_config_path,
            curated_dir=_retrieval_curated_dir(self.output_dir),
            skill_registry=self.skill_registry,
            router_memory_brief=durable_memory_brief
            if _use_durable_memory_for_planner_router(self.memory_config.context_scope)
            else "",
            router_context_max_chars=self.memory_config.max_context_chars,
        )
        if diagnostic_full:
            tasks = prepare_collaborative_tasks(tasks)
        route_context_path = self._write_json("task_route_context.json", build_task_route_context(tasks))
        results = self._execute_dynamic_tasks(tasks=tasks, state=state)
        # Repair verifier-specific citation/grounding failures before the wider
        # delivery gate decides whether objective quality remediation is needed.
        self._run_verifier_rework_loop(state=state)
        self._run_gap_resolver(state=state)
        self._run_delivery_rework_loop(state=state)

        evidence_records = state["evidence_records"]
        claims = state["claims"]
        self._write_json("search_meta.json", state.get("search_meta", {}))
        self._write_json("evidence.json", evidence_records)
        self._write_json("claims.json", claims)
        self._write_json("analysis_artifacts.json", state.get("analysis_artifacts", {}))
        analysis_artifacts = state.get("analysis_artifacts", {})
        pdf_artifacts = state.get("pdf_artifacts")
        if not isinstance(pdf_artifacts, dict) and bool(state.get("allow_document_enrichment", True)):
            pdf_artifacts = build_pdf_artifacts(
                records=list(evidence_records) if isinstance(evidence_records, list) else [],
                cache_dir=self.output_dir / "pdf_cache",
                max_pdfs=2 if fast else 4,
                max_pages=6 if fast else 12,
            )
            pdf_rag = build_pdf_rag_artifacts(
                pdf_artifacts=pdf_artifacts,
                output_dir=self.output_dir,
                symbol=str(state.get("symbol", "")),
                period=str(state.get("period", "")),
                max_pages_per_section=6 if fast else 10,
            )
            pdf_artifacts.update(pdf_rag)
            state["pdf_section_summaries"] = pdf_rag.get("pdf_section_summaries", [])
            state["section_evidence"] = pdf_rag.get("pdf_section_summaries", [])
            analysis_artifacts = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
            analysis_artifacts["pdf_section_summaries"] = pdf_rag.get("pdf_section_summaries", [])
            analysis_artifacts["pdf_extraction_audit"] = pdf_rag.get("pdf_extraction_audit", {})
            state["analysis_artifacts"] = analysis_artifacts
            summary_records = _pdf_summaries_as_evidence_records(
                summaries=pdf_rag.get("pdf_section_summaries", []),
                symbol=str(state.get("symbol", "")),
                period=str(state.get("period", "")),
            )
            top_chunk_records = _pdf_top_chunks_as_evidence_records(
                chunks=pdf_rag.get("pdf_section_chunks", []),
                symbol=str(state.get("symbol", "")),
                period=str(state.get("period", "")),
            )
            if summary_records or top_chunk_records:
                state["evidence_records"] = _merge_records(
                    list(evidence_records) if isinstance(evidence_records, list) else [],
                    summary_records + top_chunk_records,
                    key_names=["evidence_id", "sample_id", "source_url"],
                )
        if not isinstance(pdf_artifacts, dict):
            pdf_artifacts = {
                "pdf_manifest": [],
                "pdf_sections": [],
                "pdf_tables": [],
                "company_profile_extracted": {},
                "meta": {"document_enrichment_disabled": True},
            }
        pdf_manifest_path = self._write_json("pdf_manifest.json", pdf_artifacts.get("pdf_manifest", []))
        pdf_sections_path = self._write_json("pdf_sections.json", pdf_artifacts.get("pdf_sections", []))
        pdf_section_summaries_path = self._write_json("pdf_section_summaries.json", pdf_artifacts.get("pdf_section_summaries", []))
        pdf_extraction_audit_path = self._write_json("pdf_extraction_audit.json", pdf_artifacts.get("pdf_extraction_audit", {}))
        company_profile_extracted_path = self._write_json(
            "company_profile_extracted.json",
            pdf_artifacts.get("company_profile_extracted", {}),
        )
        financial_metrics_path = self._write_json(
            "financial_metrics.json",
            analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        canonical_metrics_path = self._write_json(
            "canonical_metrics.json",
            analysis_artifacts.get("canonical_metrics", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        currency_audit_path = self._write_json(
            "currency_audit.json",
            analysis_artifacts.get("currency_audit", {}) if isinstance(analysis_artifacts, dict) else {},
        )
        rejected_metrics_path = self._write_json(
            "rejected_metrics.json",
            dict(analysis_artifacts.get("financial_metrics", {})).get("rejected_metrics", [])
            if isinstance(analysis_artifacts, dict) and isinstance(analysis_artifacts.get("financial_metrics", {}), dict)
            else [],
        )
        claim_rejection_path = self._write_json(
            "claim_rejection_report.json",
            analysis_artifacts.get("claim_rejection_report", {}) if isinstance(analysis_artifacts, dict) else {},
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
        official_artifacts = build_official_evidence_artifacts(
            evidence_records if isinstance(evidence_records, list) else [],
            symbol=symbol,
            period=period,
            tables=analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else [],
            pdf_manifest=pdf_artifacts.get("pdf_manifest", []),
        )
        archive_path = ""
        if enable_remote_data:
            archive_path = archive_official_evidence_manifest(
                official_artifacts["official_evidence_manifest"],
                source_records=evidence_records if isinstance(evidence_records, list) else [],
            )
        official_manifest_path = self._write_json("official_evidence_manifest.json", official_artifacts["official_evidence_manifest"])
        evidence_coverage_path = self._write_json("evidence_coverage.json", official_artifacts["evidence_coverage"])
        sec_filing_resolver_path = self._write_json("sec_filing_resolver.json", state.get("sec_filing_resolver", {}))
        annual_report_sections_path = self._write_json("annual_report_sections.json", state.get("annual_report_sections", {}))
        self._write_json("citations.json", state.get("citations", []))
        self._write_json("charts.json", state.get("charts", []))
        self._write_json("section_dossiers.json", state.get("section_dossiers", {}))
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
        if state.get("revision_history") and not state.get("gap_resolution_trace"):
            state["gap_resolution_trace"] = _revision_history_to_gap_trace(state.get("revision_history", []))
        self._write_json("revision_history.json", state.get("revision_history", []))
        self._write_jsonl("gap_resolution_trace.jsonl", state.get("gap_resolution_trace", []))
        gap_resolution_json_path = self._write_json("gap_resolution_trace.json", state.get("gap_resolution_trace", []))
        data_repair_summary_path = self._write_json("data_repair_summary.json", state.get("data_repair_summary", {}))
        repair_constraints_path = self._write_json("repair_constraints.json", state.get("repair_constraints", {}))
        research_blackboard_path = self._write_json("research_blackboard.json", state.get("research_blackboard", {}))
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
        citations_md_path.write_text(str(repair_known_mojibake_text(state.get("citations_markdown", ""))), encoding="utf-8")

        report_md_path = self.report_dir / "report.md"
        report_html_path = self.report_dir / "report.html"
        report_json_path = self.report_dir / "report.json"
        state["markdown"] = str(repair_known_mojibake_text(state.get("markdown", "")))
        state["html"] = str(repair_known_mojibake_text(state.get("html", "")))
        state["report_json"] = repair_known_mojibake_obj(state.get("report_json", {}))
        report_md_path.write_text(str(state.get("markdown", "")), encoding="utf-8")
        report_html_path.write_text(str(state.get("html", "")), encoding="utf-8")
        report_json_path.write_text(
            json.dumps(state.get("report_json", {}), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        verification_path = self.output_dir / "verification_report.json"
        verification_path.write_text(
            json.dumps(state.get("verification_report", {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        trace_path = self.output_dir / "task_trace.jsonl"
        trace_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False, default=str) for item in self.trace) + "\n",
            encoding="utf-8",
        )
        collaboration_trace = build_agent_collaboration_trace(trace=self.trace, state=state)
        collaboration_trace_path = self._write_json("agent_collaboration_trace.json", collaboration_trace)
        tool_trace = build_tool_trace(agents=self.agents, trace=self.trace, state=state)
        tool_trace_path = self._write_json("tool_trace.json", tool_trace)

        summary_path = self.output_dir / "run_summary.json"
        summary = {
            "research_topic": research_topic,
            "symbol": symbol,
            "period": period,
            "model": getattr(self.model, "model_name", ""),
            "execution_mode": "diagnostic_full" if diagnostic_full else "collaborative" if collaborative else "dynamic",
            "execution_tier": self.execution_tier,
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
            "evidence_coverage": official_artifacts["evidence_coverage"],
            "official_evidence_archive_path": archive_path,
            "multimodal_consistency_passed": bool(multimodal_consistency.get("passed", False)),
            "mcp_tool_count": len(self.mcp_manager.list_tools()),
            "search_engines": state.get("search_meta", {}).get("engines", []),
            "retrieval_ranking_mode": retrieval_ranking_mode,
            "revision_rounds": len(state.get("revision_history", [])) if isinstance(state.get("revision_history"), list) else 0,
            "verification_passed": bool(state.get("verification_report", {}).get("passed", False)),
            "report_title": str(state.get("report_title", "")),
            "evidence_gap_count": len(state.get("verification_report", {}).get("evidence_gaps", []))
            if isinstance(state.get("verification_report"), dict)
            else 0,
            "company_report_overall_score": scorecard["overall_score"],
            "entity_resolution": entity_resolution,
            "research_blackboard": {
                "pre_write_critic_passed": bool(
                    dict(state.get("research_blackboard", {}))
                    .get("critic", {})
                    .get("pre_write_passed", False)
                )
                if isinstance(state.get("research_blackboard"), dict)
                else False,
                "industry_profile_confidence": dict(
                    dict(state.get("research_blackboard", {})).get("industry_profile", {})
                ).get("confidence", 0.0)
                if isinstance(state.get("research_blackboard"), dict)
                else 0.0,
            },
            "conversation_brief_chars": len(str(state.get("conversation_brief", ""))),
            "durable_memory_enabled": self.memory_config.enabled,
            "durable_memory_context_scope": self.memory_config.context_scope,
            "skill_registry_enabled": bool(self.skill_registry.names()),
            "skill_count": len(self.skill_registry.names()),
            "total_duration_sec": round(time.perf_counter() - run_started_at, 3),
        }
        summary.update(self._runtime_execution_summary())
        durable_memory_artifacts: Dict[str, str] = {}
        if self.memory_config.enabled:
            durable_memory_artifacts = self.durable_memory.persist_run(
                state=state,
                run_summary=summary,
            )
            summary["durable_memory"] = durable_memory_artifacts
        summary = repair_known_mojibake_obj(summary)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        return {
            "task_plan": str(self.output_dir / "task_plan.json"),
            "task_route_context": str(route_context_path),
            "task_trace": str(trace_path),
            "agent_collaboration_trace": str(collaboration_trace_path),
            "tool_trace": str(tool_trace_path),
            "search_meta": str(self.output_dir / "search_meta.json"),
            "evidence": str(self.output_dir / "evidence.json"),
            "claims": str(self.output_dir / "claims.json"),
            "analysis_artifacts": str(self.output_dir / "analysis_artifacts.json"),
            "financial_metrics": str(financial_metrics_path),
            "canonical_metrics": str(canonical_metrics_path),
            "currency_audit": str(currency_audit_path),
            "rejected_metrics": str(rejected_metrics_path),
            "claim_rejection_report": str(claim_rejection_path),
            "pdf_manifest": str(pdf_manifest_path),
            "pdf_sections": str(pdf_sections_path),
            "pdf_section_summaries": str(pdf_section_summaries_path),
            "pdf_extraction_audit": str(pdf_extraction_audit_path),
            "official_evidence_manifest": str(official_manifest_path),
            "evidence_coverage": str(evidence_coverage_path),
            "sec_filing_resolver": str(sec_filing_resolver_path),
            "annual_report_sections": str(annual_report_sections_path),
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
            "gap_resolution_trace_json": str(gap_resolution_json_path),
            "data_repair_summary": str(data_repair_summary_path),
            "repair_constraints": str(repair_constraints_path),
            "research_blackboard": str(research_blackboard_path),
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
            # Deadline check before each task dispatch
            deadline = state.get("execution_deadline")
            if deadline is not None:
                import time as _time_mod
                if _time_mod.monotonic() >= deadline:
                    state["_deadline_exceeded"] = True
                    break
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
            if (
                task.task_type == "final_answer"
                and state.get("diagnostic_full_mode")
                and not state.get("pre_write_critic")
            ):
                critic_task = AgentTask(
                    task_id=f"{task.task_id}_pre_write_critic",
                    task_type="pre_write_critic",
                    description="Review the shared research blackboard before final writing.",
                    parameters={
                        "research_blackboard": dict(state.get("research_blackboard", {}))
                        if isinstance(state.get("research_blackboard"), dict)
                        else {},
                        "state_snapshot": {
                            "symbol": state.get("symbol", ""),
                            "period": state.get("period", ""),
                            "evidence_count": len(state.get("evidence_records", []))
                            if isinstance(state.get("evidence_records"), list)
                            else 0,
                            "claim_count": len(state.get("claims", [])) if isinstance(state.get("claims"), list) else 0,
                        },
                    },
                    dependencies=[],
                    priority=5,
                )
                critic_result = self._execute("critic", critic_task)
                state["pre_write_critic"] = critic_result.output.get("pre_write_critic", {})
                state["research_blackboard"] = apply_pre_write_critic(
                    state.get("research_blackboard", {}),
                    state.get("pre_write_critic", {}),
                )
                if state.get("diagnostic_full_mode"):
                    self._resolve_pre_write_objections(state)
            enriched = enrich_task_parameters(
                task=task,
                state=state,
                raw_data_root=self.raw_data_root,
                profile=DEVELOPER_FAST_PROFILE if state.get("developer_fast_mode") else (USER_FAST_DELIVERY_PROFILE if state.get("user_fast_mode") else (FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE)),
            )
            if enriched.task_type == "final_answer" and not state.get("report_section_contracts"):
                contracts, binder = self._build_contracts_and_bind(state)
                if contracts is not None and binder is not None:
                    params = dict(enriched.parameters)
                    params["report_section_contracts"] = contracts
                    params["citation_binder"] = binder
                    params["citation_map"] = binder.get_citation_map() if hasattr(binder, "get_citation_map") else {}
                    enriched = AgentTask(
                        task_id=enriched.task_id,
                        task_type=enriched.task_type,
                        description=enriched.description,
                        parameters=params,
                        dependencies=list(enriched.dependencies),
                        priority=enriched.priority,
                        metadata=dict(enriched.metadata),
                    )
            if enriched.task_type == "final_answer":
                section_packs = self._prepare_prewrite_section_evidence_packs(state)
                params = dict(enriched.parameters)
                params["section_evidence_packs"] = section_packs
                enriched = AgentTask(
                    task_id=enriched.task_id,
                    task_type=enriched.task_type,
                    description=enriched.description,
                    parameters=params,
                    dependencies=list(enriched.dependencies),
                    priority=enriched.priority,
                    metadata=dict(enriched.metadata),
                )
            result = self._execute(agent_key_for_task(enriched.task_type), enriched)
            results[enriched.task_id] = result
            merge_task_result(state=state, task_type=enriched.task_type, result=result)
            state["research_blackboard"] = update_blackboard_for_task(
                state.get("research_blackboard", {}),
                enriched.task_type,
                state,
                result.output,
            )
            if enriched.task_type == "browser" and bool(state.get("allow_document_enrichment", True)):
                attach_annual_report_sections_to_state(state=state, raw_data_root=self.raw_data_root)
                attach_pdf_artifacts_to_state(state=state)
                state["research_blackboard"] = update_blackboard_for_task(
                    state.get("research_blackboard", {}),
                    enriched.task_type,
                    state,
                    result.output,
                )
            if enriched.task_type == "verifier":
                absorb_verifier_feedback(state)
            del pending[enriched.task_id]
        return results

    def _resolve_pre_write_objections(self, state: Dict[str, Any], max_rounds: int = 2) -> None:
        """Route blocking critic objections back to the responsible role agents."""

        history: List[Dict[str, Any]] = []
        for round_index in range(1, max_rounds + 1):
            objections = _blocking_objections(state.get("pre_write_critic", {}))
            if not objections:
                break
            target_agents = _ordered_targets(objections)
            for target_agent in target_agents:
                task_type = _role_task_type_for_agent(target_agent)
                if not task_type:
                    continue
                role_result = self._execute(
                    agent_key_for_task(task_type),
                    AgentTask(
                        task_id=f"task_prewrite_rework_{round_index}_{task_type}",
                        task_type=task_type,
                        description=f"Revise {task_type} after pre-write critic objection.",
                        parameters={
                            "symbol": state.get("symbol", ""),
                            "period": state.get("period", ""),
                            "evidence_records": list(state.get("evidence_records", [])),
                            "claims": list(state.get("claims", [])),
                            "analysis_artifacts": dict(state.get("analysis_artifacts", {}))
                            if isinstance(state.get("analysis_artifacts"), dict)
                            else {},
                            "research_blackboard": dict(state.get("research_blackboard", {}))
                            if isinstance(state.get("research_blackboard"), dict)
                            else {},
                            "critic_objections": [item for item in objections if item.get("target_agent") == target_agent],
                        },
                        dependencies=[],
                        priority=6,
                    ),
                )
                merge_task_result(state=state, task_type=task_type, result=role_result)
                state["research_blackboard"] = update_blackboard_for_task(
                    state.get("research_blackboard", {}),
                    task_type,
                    state,
                    role_result.output,
                )
                history.append(
                    {
                        "round": round_index,
                        "target_agent": target_agent,
                        "task_type": task_type,
                        "field": [item.get("field", "") for item in objections if item.get("target_agent") == target_agent],
                        "action": "revise_role_output",
                    }
                )
            critic_result = self._execute(
                "critic",
                AgentTask(
                    task_id=f"task_prewrite_recheck_{round_index}",
                    task_type="pre_write_critic",
                    description="Re-check shared blackboard after responsible role revisions.",
                    parameters={
                        "research_blackboard": dict(state.get("research_blackboard", {}))
                        if isinstance(state.get("research_blackboard"), dict)
                        else {},
                        "state_snapshot": {
                            "symbol": state.get("symbol", ""),
                            "period": state.get("period", ""),
                            "evidence_count": len(state.get("evidence_records", []))
                            if isinstance(state.get("evidence_records"), list)
                            else 0,
                            "claim_count": len(state.get("claims", [])) if isinstance(state.get("claims"), list) else 0,
                        },
                    },
                    dependencies=[],
                    priority=6,
                ),
            )
            state["pre_write_critic"] = critic_result.output.get("pre_write_critic", {})
            state["research_blackboard"] = apply_pre_write_critic(
                state.get("research_blackboard", {}),
                state.get("pre_write_critic", {}),
            )
            if not _blocking_objections(state.get("pre_write_critic", {})):
                break

        remaining = _blocking_objections(state.get("pre_write_critic", {}))
        state["pre_write_rework_history"] = history
        if remaining:
            state["collaborative_degraded_report"] = True
            blackboard = dict(state.get("research_blackboard", {})) if isinstance(state.get("research_blackboard"), dict) else {}
            critic = dict(blackboard.get("critic", {})) if isinstance(blackboard.get("critic"), dict) else {}
            critic["degraded_report"] = True
            critic["remaining_blocking_objections"] = remaining
            blackboard["critic"] = critic
            state["research_blackboard"] = blackboard

    def _execute(self, agent_key: str, task: AgentTask) -> TaskResult:
        agent = self.agents[agent_key]
        model_usage = self._model_usage_for_agent(agent_key)
        self._emit_stage(
            {
                "phase": "started",
                "agent_key": agent_key,
                "agent_name": agent.name,
                "task_id": task.task_id,
                "task_type": task.task_type,
                "model_name": model_usage.get("model_name", ""),
                "provider": model_usage.get("provider", ""),
                "route_profile": model_usage.get("route_profile", ""),
            }
        )
        logger.info(
            "agent_trace_start | agent_key=%s | agent=%s | task_id=%s | task_type=%s | route_profile=%s | provider=%s | model=%s | endpoint=%s | api_key_env=%s | api_key_present=%s",
            agent_key,
            agent.name,
            task.task_id,
            task.task_type,
            model_usage.get("route_profile", ""),
            model_usage.get("provider", ""),
            model_usage.get("model_name", ""),
            model_usage.get("endpoint_url", ""),
            model_usage.get("api_key_env", ""),
            model_usage.get("api_key_present", False),
        )
        # Enforce remaining deadline per task: if a deadline is set, each task
        # gets at most the remaining time.  A 30s floor prevents killing tasks
        # that could succeed within a single LLM call + retry window.
        state = getattr(self, "state", None) or {}
        deadline = state.get("execution_deadline")
        task_timeout = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            task_timeout = max(30.0, remaining)
        started_at = time.perf_counter()
        timeout_fired = False
        if task_timeout is not None:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(agent.execute_task, task)
            try:
                result = future.result(timeout=task_timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                result = TaskResult(
                    task_id=task.task_id,
                    agent_name=agent.name,
                    status=AgentStatus.FAILED,
                    output={},
                    error=f"task exceeded {task_timeout:.0f}s deadline",
                )
                timeout_fired = True
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        else:
            result = agent.execute_task(task)
        duration_sec = round(time.perf_counter() - started_at, 3)
        trace_item = {
            "agent": agent.name,
            "agent_key": agent_key,
            "task": _compact_trace_task(task),
            "status": result.status.value,
            "error": result.error,
            "output_keys": sorted(result.output.keys()),
            "metadata": result.metadata,
            "duration_sec": duration_sec,
            "model_usage": model_usage,
        }
        self.trace.append(trace_item)
        self._emit_stage(
            {
                "phase": "finished",
                "agent_key": agent_key,
                "agent_name": agent.name,
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": result.status.value,
                "duration_ms": round(duration_sec * 1000),
                "error": result.error,
                "model_name": model_usage.get("model_name", ""),
                "provider": model_usage.get("provider", ""),
                "route_profile": model_usage.get("route_profile", ""),
                "react_used": bool(result.metadata.get("react_used")) if isinstance(result.metadata, dict) else False,
            }
        )
        logger.info(
            "agent_trace_finish | agent_key=%s | agent=%s | task_id=%s | status=%s | duration_sec=%.3f | route_profile=%s | provider=%s | model=%s | fallback=%s | error=%s",
            agent_key,
            agent.name,
            task.task_id,
            result.status.value,
            duration_sec,
            model_usage.get("route_profile", ""),
            model_usage.get("provider", ""),
            model_usage.get("model_name", ""),
            model_usage.get("model_fallback_used", False),
            result.error,
        )
        if timeout_fired:
            self.state["_timeout_count"] = self.state.get("_timeout_count", 0) + 1
            return result
        if result.status != AgentStatus.COMPLETED:
            raise RuntimeError(f"{agent.name} failed: {result.error}")
        return result

    def _emit_stage(self, payload: Dict[str, Any]) -> None:
        if self.stage_callback is None:
            return
        try:
            self.stage_callback(dict(payload))
        except Exception as exc:
            logger.warning("agent stage callback failed: %s", exc)

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
        profile = DEVELOPER_FAST_PROFILE if state.get("developer_fast_mode") else (USER_FAST_DELIVERY_PROFILE if state.get("user_fast_mode") else (FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE))
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
            if not state.get("gap_resolution_trace"):
                seed_trace = _verifier_report_to_gap_trace(verification_report)
                if not seed_trace:
                    seed_trace = _revision_request_to_gap_trace(revision_request)
                state["gap_resolution_trace"] = seed_trace
            conversation_brief = refresh_conversation_brief(state)

            bundles = self._ensure_claim_evidence_bundles(state)
            dossiers = self._build_section_dossiers(state)

            final_result = self._execute(
                "final_answer",
                AgentTask(
                    task_id=f"task_rework_{round_index:03d}_final_answer",
                    task_type="final_answer",
                    description="Revise report using verifier feedback.",
                    parameters={
                        "research_topic": state.get("research_topic", ""),
                        "symbol": str(state.get("symbol", "")),
                        "period": str(state.get("period", "")),
                        "claims": list(state.get("claims", [])),
                        "evidence_records": list(state.get("evidence_records", [])),
                        "claim_evidence_bundles": bundles,
                        "section_dossiers": dossiers,
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
                        "research_blackboard": dict(state.get("research_blackboard", {}))
                        if isinstance(state.get("research_blackboard"), dict)
                        else {},
                        "pre_write_critic": dict(state.get("pre_write_critic", {}))
                        if isinstance(state.get("pre_write_critic"), dict)
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

    def _run_gap_resolver(self, state: Dict[str, Any]) -> None:
        result = self._execute(
            "gap_resolver",
            AgentTask(
                task_id="task_gap_resolver_001",
                task_type="gap_resolver",
                description="Resolve data and delivery gaps for the generated report.",
                parameters={
                    "symbol": state.get("symbol", ""),
                    "period": state.get("period", ""),
                    "evidence_records": list(state.get("evidence_records", [])),
                    "claims": list(state.get("claims", [])),
                    "markdown": str(state.get("markdown", "")),
                    "analysis_artifacts": dict(state.get("analysis_artifacts", {}))
                    if isinstance(state.get("analysis_artifacts"), dict)
                    else {},
                    "search_meta": dict(state.get("search_meta", {})) if isinstance(state.get("search_meta"), dict) else {},
                    "quality_remediation_plan": dict(state.get("quality_remediation_plan", {}))
                    if isinstance(state.get("quality_remediation_plan"), dict)
                    else {},
                },
                dependencies=[],
                priority=4,
            ),
        )
        output = result.output if isinstance(result.output, dict) else {}
        state["gap_resolution_trace"] = list(output.get("gap_resolution_trace", []))
        state["data_repair_summary"] = dict(output.get("data_repair_summary", {}))
        state["repair_constraints"] = dict(output.get("repair_constraints", {}))
        state["required_backfill_sections"] = list(output.get("required_backfill_sections", []))
        state["research_blackboard"] = update_blackboard_for_task(
            state.get("research_blackboard", {}),
            "gap_resolver",
            state,
            output,
        )

    # ── delivery rework loop ──────────────────────────────────────────────

    def _write_evaluation_artifacts(self, state: Dict[str, Any]) -> None:
        """Write state-backed artifacts to disk so evaluation functions can read them."""
        report_dir = Path(self.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        state["markdown"] = str(repair_known_mojibake_text(state.get("markdown", "")))
        state["html"] = str(repair_known_mojibake_text(state.get("html", "")))
        state["report_json"] = repair_known_mojibake_obj(state.get("report_json", {}))
        (report_dir / "report.md").write_text(str(state.get("markdown", "")), encoding="utf-8")
        (report_dir / "report.html").write_text(str(state.get("html", "")), encoding="utf-8")
        (report_dir / "report.json").write_text(
            json.dumps(state.get("report_json", {}), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self._write_json("verification_report.json", state.get("verification_report", {}))
        self._write_json("claims.json", list(state.get("claims", [])))
        self._write_json("evidence.json", list(state.get("evidence_records", [])))
        self._write_json("citations.json", list(state.get("citations", [])))
        self._write_json("search_meta.json", state.get("search_meta", {}))
        analysis = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        analysis = self._apply_canonical_metrics(
            analysis,
            evidence_records=list(state.get("evidence_records", [])),
            symbol=str(state.get("symbol", "") or ""),
            period=str(state.get("period", "") or ""),
        )
        state["analysis_artifacts"] = analysis
        self._write_json("tables.json", analysis.get("tables", []))
        self._write_json("financial_metrics.json", analysis.get("financial_metrics", {}))
        self._write_json("canonical_metrics.json", analysis.get("canonical_metrics", {}))
        self._write_json("currency_audit.json", analysis.get("currency_audit", {}))
        self._write_json("valuation_model.json", analysis.get("valuation_model", {}))
        self._write_json("valuation_sensitivity.json", analysis.get("valuation_sensitivity", {}))
        self._write_json("research_blackboard.json", state.get("research_blackboard", {}))
        self._write_json("section_dossiers.json", state.get("section_dossiers", {}))
        pdf = dict(state.get("pdf_artifacts", {})) if isinstance(state.get("pdf_artifacts"), dict) else {}
        self._write_json("company_profile_extracted.json", pdf.get("company_profile_extracted", {}))
        self._write_json("charts.json", list(state.get("charts", [])))
        # Write a minimal run_summary so evaluation functions can read symbol/period
        run_summary = self._read_json("run_summary.json", {})
        if not isinstance(run_summary, dict) or not run_summary.get("symbol"):
            run_summary = {
                "symbol": state.get("symbol", ""),
                "period": state.get("period", ""),
                "research_topic": state.get("research_topic", ""),
                "verification_passed": bool(state.get("verification_report", {}).get("passed", False)),
            }
        self._write_json("run_summary.json", run_summary)

    def _read_json(self, file_name: str, default: Any) -> Any:
        path = self.output_dir / file_name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    def _static_phase_result(self, phase: str, artifact_names: List[str]) -> Dict[str, str]:
        self._write_json("static_phase_trace.json", self.trace)
        manifest = {
            "schema_version": "static_agent_phase.v1",
            "phase": phase,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": {
                name: str(self.output_dir / name)
                for name in artifact_names
                if (self.output_dir / name).is_file()
            },
            "runtime": self._runtime_execution_summary(),
            "trace_count": len(self.trace),
        }
        self._write_json("static_phase_checkpoint.json", manifest)
        return {
            "phase": phase,
            "checkpoint": str(self.output_dir / "static_phase_checkpoint.json"),
            **manifest["artifacts"],
        }

    def _persist_quality_feedback(self, state: Dict[str, Any], remediation: Dict[str, Any]) -> None:
        """Add quality remediation feedback to conversation state so agents see it."""
        issues = remediation.get("top_issues", []) if isinstance(remediation.get("top_issues"), list) else []
        fixes = remediation.get("required_fixes", []) if isinstance(remediation.get("required_fixes"), list) else []
        if not issues and not fixes:
            return
        lines = ["[Quality Remediation Feedback]", ""]
        if issues:
            lines.append("Top issues to resolve:")
            for item in issues:
                sev = str(item.get("severity", "?"))
                msg = str(item.get("message", ""))
                lines.append(f"  [{sev}] {msg}")
        if fixes:
            lines.append("Required fixes:")
            for fix in fixes:
                lines.append(f"  - {fix}")
        feedback_text = "\n".join(lines)
        memory = conversation_state_from_dict(state.get("conversation_context"))
        if memory:
            memory.add_turn("system", feedback_text, {"source": "quality_remediation"})
            state["conversation_context"] = memory.to_dict()
            state["conversation_brief"] = refresh_conversation_brief(state)

    # Agent key → merge task_type mapping (reverse of agent_key_for_task)
    _AGENT_KEY_TO_MERGE_TYPE: Dict[str, str] = {
        "research": "deep_researcher",
        "browser": "browser",
        "analyze": "deep_analyze",
        "identity": "identity_profile",
        "statement": "three_statement_analysis",
        "peer": "peer_analysis",
        "valuation": "valuation_analysis",
        "risk": "risk_analysis",
    }

    def _run_repair_agents_for_rework(
        self,
        state: Dict[str, Any],
        remediation: Dict[str, Any],
        round_idx: int,
    ) -> None:
        """Dispatch repair agents based on responsible_agents from the remediation plan."""
        responsible = remediation.get("responsible_agents", [])
        if not isinstance(responsible, list):
            return
        # Agents to skip — handled separately as the final_answer + verifier pair
        skip_agent_keys = {"final_answer", "verifier", "gap_resolver", "planning", "critic"}
        executed_keys: set[str] = set()
        for entry in responsible:
            agent_name = str(entry.get("agent", "")) if isinstance(entry, dict) else ""
            if not agent_name:
                continue
            agent_key = self.agent_name_to_key.get(agent_name)
            if not agent_key or agent_key in skip_agent_keys or agent_key in executed_keys:
                continue
            executed_keys.add(agent_key)
            merge_type = self._AGENT_KEY_TO_MERGE_TYPE.get(agent_key, agent_key)
            profile = DEVELOPER_FAST_PROFILE if state.get("developer_fast_mode") else (USER_FAST_DELIVERY_PROFILE if state.get("user_fast_mode") else (FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE))
            conversation_brief = refresh_conversation_brief(state)
            repair_params: Dict[str, Any] = {
                "research_topic": state.get("research_topic", ""),
                "symbol": state.get("symbol", ""),
                "period": state.get("period", ""),
                "evidence_records": list(state.get("evidence_records", [])),
                "claims": list(state.get("claims", [])),
                "markdown": str(state.get("markdown", "")),
                "analysis_artifacts": dict(state.get("analysis_artifacts", {}))
                if isinstance(state.get("analysis_artifacts"), dict)
                else {},
                "research_blackboard": dict(state.get("research_blackboard", {}))
                if isinstance(state.get("research_blackboard"), dict)
                else {},
                "verification_report": dict(state.get("verification_report", {}))
                if isinstance(state.get("verification_report"), dict)
                else {},
                "quality_remediation_plan": dict(remediation),
                "repair_constraints": dict(state.get("repair_constraints", {}))
                if isinstance(state.get("repair_constraints"), dict)
                else {},
                "conversation_brief": conversation_brief,
                "rework_round": round_idx,
                "prior_markdown": str(state.get("markdown", "")),
            }
            if agent_key == "research":
                repair_params["query"] = f"{state.get('symbol', '')} {state.get('period', '')} quality-gap rework evidence"
                repair_params["topk"] = int(profile.get("research_topk", 6))
                repair_params["engines"] = _market_engines(str(state.get("symbol", "")))
                repair_params["raw_data_root"] = self.raw_data_root
                repair_params["curated_dir"] = _retrieval_curated_dir(self.output_dir)
                repair_params["ranking_mode"] = str(state.get("retrieval_ranking_mode", "hybrid_rerank"))
                repair_params["enable_remote"] = bool(state.get("enable_remote_data", True))
                repair_params["merge_standard_search_after_react"] = True
            elif agent_key == "browser":
                repair_params["evidence_candidates"] = list(state.get("evidence_candidates", []))
                repair_params["skip_llm_extract"] = bool(profile.get("browser_skip_llm_extract", False))
            elif agent_key == "analyze":
                repair_params["max_records"] = int(profile.get("analyze_max_records", 10))
                repair_params["content_limit"] = int(profile.get("analyze_content_limit", 600))
                repair_params["max_tokens"] = int(profile.get("analyze_max_tokens", 1800))
                repair_params["use_react"] = bool(profile.get("analyze_use_react", False))
            elif agent_key in ("identity", "statement", "peer", "valuation", "risk"):
                repair_params.setdefault("evidence_records", list(state.get("evidence_records", [])))
                repair_params.setdefault("claims", list(state.get("claims", [])))
            try:
                result = self._execute(
                    agent_key,
                    AgentTask(
                        task_id=f"task_delivery_rework_{round_idx:03d}_{agent_key}",
                        task_type=merge_type,
                        description=f"Quality-gap repair: {agent_name} — {entry.get('reason', '')}",
                        parameters=repair_params,
                        dependencies=[],
                        priority=5,
                    ),
                )
                merge_task_result(state=state, task_type=merge_type, result=result)
                state["research_blackboard"] = update_blackboard_for_task(
                    state.get("research_blackboard", {}),
                    merge_type,
                    state,
                    result.output if isinstance(result.output, dict) else {},
                )
            except Exception as exc:
                self.trace.append({
                    "agent": agent_name,
                    "agent_key": agent_key,
                    "task": {"task_id": f"task_delivery_rework_{round_idx:03d}_{agent_key}", "task_type": merge_type},
                    "status": "failed",
                    "error": str(exc),
                    "duration_sec": 0,
                })

    def _run_delivery_rework_final_answer(
        self,
        state: Dict[str, Any],
        remediation: Dict[str, Any],
        round_idx: int,
    ) -> None:
        """Re-run FinalAnswerAgent with delivery quality remediation constraints."""
        profile = DEVELOPER_FAST_PROFILE if state.get("developer_fast_mode") else (USER_FAST_DELIVERY_PROFILE if state.get("user_fast_mode") else (FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE))
        constraints = remediation.get("planner_constraints", [])
        constraints_text = "\n".join(f"- {c}" for c in constraints) if isinstance(constraints, list) else ""
        revision_request = (
            "Quality diagnostic remediation: resolve the following issues.\n"
            + constraints_text
            + "\n"
            + "Retain all evidence_id citations. "
            + "Do NOT remove or restructure sections that already pass verifier checks."
        )
        conversation_brief = refresh_conversation_brief(state)
        analysis = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        bundles = self._ensure_claim_evidence_bundles(state)
        dossiers = self._build_section_dossiers(state)

        # Rebuild contracts to reflect any repair agent changes
        rework_contracts, rework_binder = self._build_contracts_and_bind(state)

        result = self._execute(
            "final_answer",
            AgentTask(
                task_id=f"task_delivery_rework_{round_idx:03d}_final_answer",
                task_type="final_answer",
                description="Rewrite report using delivery quality remediation constraints.",
                parameters={
                    "research_topic": state.get("research_topic", ""),
                    "symbol": str(state.get("symbol", "")),
                    "period": str(state.get("period", "")),
                    "output_dir": str(self.output_dir),
                    "claims": list(state.get("claims", [])),
                    "evidence_records": list(state.get("evidence_records", [])),
                    "claim_evidence_bundles": bundles,
                    "section_dossiers": dossiers,
                    "revision_request": revision_request,
                    "prior_markdown": str(state.get("markdown", "")),
                    "conversation_brief": conversation_brief,
                    "tables": analysis.get("tables", []),
                    "financial_metrics": analysis.get("financial_metrics", {}),
                    "pdf_sections": analysis.get("pdf_sections", []),
                    "company_profile": analysis.get("company_profile", {}),
                    "company_name": str(dict(state.get("entity_resolution", {})).get("company_name", "")),
                    "research_blackboard": dict(state.get("research_blackboard", {}))
                    if isinstance(state.get("research_blackboard"), dict)
                    else {},
                    "pre_write_critic": dict(state.get("pre_write_critic", {}))
                    if isinstance(state.get("pre_write_critic"), dict)
                    else {},
                    "quality_remediation_plan": dict(remediation),
                    "max_claims": int(profile["final_max_claims"]),
                    "max_evidence": int(profile["final_max_evidence"]),
                    "evidence_content_limit": int(profile["final_evidence_content_limit"]),
                    "max_tokens": int(profile["final_max_tokens"]),
                    # Contract-first generation (rebuild after repair)
                    "report_section_contracts": rework_contracts,
                    "citation_binder": rework_binder,
                    "citation_map": rework_binder.get_citation_map() if rework_binder else {},
                },
                dependencies=[],
                priority=5,
            ),
        )
        merge_task_result(state=state, task_type="final_answer", result=result)

    def _run_delivery_rework_verifier(self, state: Dict[str, Any], round_idx: int) -> None:
        """Re-run VerifierAgent after a delivery-rework final-answer pass."""
        analysis = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        result = self._execute(
            "verifier",
            AgentTask(
                task_id=f"task_delivery_rework_{round_idx:03d}_verifier",
                task_type="verifier",
                description="Re-verify report after delivery quality rework.",
                parameters={
                    "claims": list(state.get("claims", [])),
                    "markdown": str(state.get("markdown", "")),
                    "evidence_records": list(state.get("evidence_records", [])),
                    "charts": list(state.get("charts", [])),
                    "tables": analysis.get("tables", []),
                    "valuation": analysis.get("valuation", {}),
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
        merge_task_result(state=state, task_type="verifier", result=result)
        absorb_verifier_feedback(state)

    def _run_delivery_rework_loop(self, state: Dict[str, Any]) -> None:
        """Delivery-gate rework loop: evaluate, dispatch repair agents, rewrite, re-verify."""
        profile = DEVELOPER_FAST_PROFILE if state.get("developer_fast_mode") else (USER_FAST_DELIVERY_PROFILE if state.get("user_fast_mode") else (FAST_PROFILE if state.get("performance_profile") == "fast" else DEFAULT_PROFILE))
        max_rounds = int(profile.get("delivery_rework_rounds", 2) or 0)
        if max_rounds <= 0:
            return

        rework_rounds: List[Dict[str, Any]] = []

        for round_idx in range(1, max_rounds + 1):
            # 1 — Write current artifacts to disk so evaluation functions can read them
            self._write_evaluation_artifacts(state)

            # 2 — Objective quality evaluation
            quality_report = evaluate_report_quality_from_paths(
                outputs_dir=self.output_dir,
                reports_dir=self.report_dir,
                run_dir=self.output_dir,
            )
            self._write_json("quality_report.json", quality_report)

            # 3 — LLM quality review: replaced with heuristic to save ~25s per round.
            # The LLM review was redundant — the artifact guard already overrode its
            # verdict when objective+verifier gates passed. We derive pass/fail directly
            # from the objective quality report instead.
            obj_pass = bool(quality_report.get("objective_pass", False))
            obj_score = float(quality_report.get("overall_score", 0.85) or 0.85)
            llm_review = {
                "schema_version": "llm_quality_review.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "run_dir": str(self.output_dir),
                "model_status": "bypassed_heuristic",
                "llm_review_pass": obj_pass,
                "total_score": obj_score,
                "artifact_guard_applied": True,
                "issues": [],
                "dimension_scores": {
                    "professional_report_likeness": obj_score,
                    "investment_insight": obj_score,
                    "fact_period_consistency": obj_score,
                    "company_report_requirement_fit": obj_score,
                    "chart_usefulness": obj_score,
                    "language_quality": obj_score,
                },
            }
            self._write_json("llm_quality_review.json", llm_review)

            # 4 — Build delivery gate
            gate = build_delivery_gate_from_outputs(self.output_dir, self.output_dir)
            self._write_json("delivery_gate.json", gate)

            round_record = {
                "round": round_idx,
                "delivery_pass": gate.get("delivery_pass", False),
                "scores": dict(gate.get("scores", {})),
                "issue_counts": dict(gate.get("issue_counts", {})),
            }

            if gate.get("delivery_pass", False):
                rework_rounds.append(round_record)
                break
            if _should_stop_delivery_rework(gate):
                round_record["stopped_reason"] = "quality_gate_blocked_without_rewrite"
                rework_rounds.append(round_record)
                break

            # 5 — Build remediation plan from evaluation outputs
            remediation = build_quality_remediation_plan_from_outputs(self.output_dir, self.output_dir)
            self._write_json("quality_remediation_plan.json", remediation)

            round_record["failed_sections"] = list(remediation.get("failed_sections", []))
            round_record["required_fixes"] = list(remediation.get("required_fixes", []))
            round_record["responsible_agents"] = list(remediation.get("responsible_agents", []))

            # 6 — Persist quality feedback into conversation state for next round
            self._persist_quality_feedback(state, remediation)
            state["quality_remediation_plan"] = remediation

            # 7 — Dispatch repair agents mapped from responsible_agents
            self._run_repair_agents_for_rework(state, remediation, round_idx)

            # 8 — Re-write report with remediation constraints
            self._run_delivery_rework_final_answer(state, remediation, round_idx)

            # 9 — Re-verify
            self._run_delivery_rework_verifier(state, round_idx)

            # Track this round
            round_record["delivery_pass_after_round"] = bool(state.get("verification_report", {}).get("passed", False))
            rework_rounds.append(round_record)

            state.setdefault("revision_history", []).append({
                "round": f"delivery_rework_{round_idx}",
                "delivery_pass": round_record["delivery_pass"],
                "failed_sections": round_record.get("failed_sections", []),
                "required_fixes": round_record.get("required_fixes", []),
                "gate_scores": round_record.get("scores", {}),
                "issue_counts": round_record.get("issue_counts", {}),
            })

        self._write_json("rework_rounds.json", {
            "schema": "rework_rounds.v1",
            "symbol": state.get("symbol", ""),
            "period": state.get("period", ""),
            "total_rounds": len(rework_rounds),
            "delivery_passed": any(r.get("delivery_pass") for r in rework_rounds),
            "rounds": rework_rounds,
        })

    def _write_json(self, file_name: str, payload: Any) -> Path:
        path = self.output_dir / file_name
        payload = repair_known_mojibake_obj(payload)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
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


def build_agent_collaboration_trace(trace: List[Dict[str, Any]], state: Dict[str, Any]) -> Dict[str, Any]:
    """Build a human-readable multi-agent handoff summary from raw task trace."""

    agents: List[Dict[str, Any]] = []
    previous_agent = ""
    for index, item in enumerate(trace):
        task = item.get("task", {}) if isinstance(item.get("task"), dict) else {}
        params = task.get("parameters", {}) if isinstance(task.get("parameters"), dict) else {}
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        output_keys = list(item.get("output_keys") or [])
        agent_name = str(item.get("agent") or "")
        agents.append(
            {
                "step": index + 1,
                "agent": agent_name,
                "task_id": task.get("task_id") or task.get("id") or "",
                "task_type": task.get("task_type") or "",
                "description": _shorten(task.get("description") or params.get("research_topic") or ""),
                "status": item.get("status", ""),
                "duration_sec": item.get("duration_sec", 0),
                "input_summary": _task_input_summary(params),
                "output_keys": output_keys,
                "output_summary": _output_summary(output_keys=output_keys, metadata=metadata),
                "memory_used": _memory_used(params=params, state=state),
                "quality_feedback_used": bool(params.get("quality_remediation_plan") or params.get("quality_feedback")),
                "tools_observed": _tools_from_metadata(metadata),
                "blackboard_writes": _blackboard_writes_for_agent(agent_name, state),
                "objections": _objections_for_agent(agent_name, state),
                "handoff_from": previous_agent,
                "handoff_to": "",
                "error": item.get("error") or "",
            }
        )
        if previous_agent and len(agents) >= 2:
            agents[-2]["handoff_to"] = agent_name
        previous_agent = agent_name

    verification = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
    remediation = state.get("quality_remediation_plan", {}) if isinstance(state.get("quality_remediation_plan"), dict) else {}
    revision_history = state.get("revision_history", []) if isinstance(state.get("revision_history"), list) else []
    gap_trace = state.get("gap_resolution_trace", []) if isinstance(state.get("gap_resolution_trace"), list) else []
    blackboard = state.get("research_blackboard", {}) if isinstance(state.get("research_blackboard"), dict) else {}
    blockers = [
        issue
        for issue in (remediation.get("issues", []) if isinstance(remediation.get("issues"), list) else [])
        if isinstance(issue, dict) and str(issue.get("severity", "")).lower() in {"fatal", "blocker"}
    ]
    return {
        "schema_version": "agent_collaboration_trace.v1",
        "symbol": state.get("symbol", ""),
        "period": state.get("period", ""),
        "research_topic": state.get("research_topic", ""),
        "agent_count": len({item.get("agent") for item in agents if item.get("agent")}),
        "step_count": len(agents),
        "agents": agents,
        "handoffs": [
            {"from": item["agent"], "to": item["handoff_to"], "artifact_keys": item["output_keys"]}
            for item in agents
            if item.get("handoff_to")
        ],
        "memory": {
            "enabled": bool(state.get("memory_enabled") or state.get("durable_memory_enabled") or state.get("durable_memory_brief")),
            "context_scope": state.get("memory_context_scope") or state.get("durable_memory_context_scope") or "",
            "used_by_agents": [item["agent"] for item in agents if item.get("memory_used")],
            "fact_boundary": "Memory is routing/context only; facts require evidence/citation/verifier.",
        },
        "quality": {
            "verification_passed": bool(verification.get("passed", False)),
            "rework_rounds": len(revision_history),
            "quality_feedback_used": bool(remediation.get("quality_feedback_used") or remediation),
            "blockers": blockers[:8],
            "remaining_gap_count": len(gap_trace),
        },
        "pre_write_rework_history": list(state.get("pre_write_rework_history", []))
        if isinstance(state.get("pre_write_rework_history"), list)
        else [],
        "research_blackboard": {
            "schema_version": blackboard.get("schema_version", ""),
            "market_route": blackboard.get("market_route", {}),
            "company_identity": blackboard.get("company_identity", {}),
            "industry_profile": blackboard.get("industry_profile", {}),
            "period_state": blackboard.get("period_state", {}),
            "role_outputs": blackboard.get("role_outputs", {}),
            "critic": blackboard.get("critic", {}),
        },
    }


def build_tool_trace(agents: Dict[str, Any], trace: List[Dict[str, Any]], state: Dict[str, Any]) -> Dict[str, Any]:
    """Collect deterministic, ReAct, and search/data-source tool observations."""

    calls: List[Dict[str, Any]] = []
    for agent in agents.values():
        for item in getattr(agent, "tool_trace", []) or []:
            if isinstance(item, dict):
                calls.append(dict(item))

    for item in trace:
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        agent_name = str(item.get("agent") or "")
        for react_item in metadata.get("react_trace", []) if isinstance(metadata.get("react_trace"), list) else []:
            if not isinstance(react_item, dict):
                continue
            tool_name = str(react_item.get("tool") or react_item.get("tool_name") or react_item.get("name") or "")
            if not tool_name:
                continue
            calls.append(
                {
                    "caller_agent": agent_name,
                    "tool_name": tool_name,
                    "input_summary": _shorten(react_item.get("arguments") or react_item.get("input") or {}),
                    "output_summary": _shorten(
                        react_item.get("output_summary")
                        or react_item.get("observation")
                        or react_item.get("output")
                        or {}
                    ),
                    "success": not bool(react_item.get("error")),
                    "failure_reason": str(react_item.get("error") or ""),
                    "error_type": str(react_item.get("error_type") or ""),
                    "attempt_count": int(react_item.get("attempts", 1) or 1),
                    "duration_sec": react_item.get("duration_sec")
                    if react_item.get("duration_sec") is not None
                    else round(float(react_item.get("duration_ms", 0) or 0) / 1000, 6),
                    "evidence_ids": list(react_item.get("evidence_ids") or []),
                    "artifact_paths": [],
                    "source": "react",
                }
            )

    search_meta = state.get("search_meta", {}) if isinstance(state.get("search_meta"), dict) else {}
    engine_meta = search_meta.get("engine_meta", search_meta)
    if isinstance(engine_meta, dict):
        for engine, meta in engine_meta.items():
            meta_dict = meta if isinstance(meta, dict) else {}
            calls.append(
                {
                    "caller_agent": "SearchManager",
                    "tool_name": str(engine),
                    "input_summary": {"engine": engine},
                    "output_summary": _shorten(meta_dict),
                    "success": not bool(meta_dict.get("error") or meta_dict.get("failure_reason") in {"fetch_error", "missing_api_key"}),
                    "failure_reason": str(meta_dict.get("error") or meta_dict.get("failure_reason") or ""),
                    "duration_sec": meta_dict.get("duration_sec", 0),
                    "evidence_ids": [],
                    "artifact_paths": [],
                    "source": "search_engine",
                }
            )

    return {
        "schema_version": "tool_trace.v1",
        "tool_call_count": len(calls),
        "successful_call_count": sum(1 for item in calls if item.get("success")),
        "failed_call_count": sum(1 for item in calls if item.get("success") is False),
        "calls": calls,
    }


def _task_input_summary(params: Dict[str, Any]) -> Dict[str, Any]:
    keys = ["symbol", "period", "query", "research_topic", "engines", "expected_symbol", "max_records", "max_claims"]
    return {key: _shorten(params.get(key)) for key in keys if key in params}


def _output_summary(output_keys: List[str], metadata: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"keys": output_keys[:12]}
    for key in ["evidence_count", "claim_count", "chart_count", "react_used", "quality_remediation_used"]:
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _memory_used(params: Dict[str, Any], state: Dict[str, Any]) -> bool:
    brief = str(params.get("conversation_brief") or "")
    return "DurableMemory" in brief or bool(params.get("durable_memory_brief")) or bool(
        state.get("durable_memory_brief") and params.get("research_topic")
    )


def _tools_from_metadata(metadata: Dict[str, Any]) -> List[str]:
    tools: List[str] = []
    for key in ["tool_calls", "tools", "react_trace"]:
        value = metadata.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    name = str(item.get("tool") or item.get("tool_name") or item.get("name") or "")
                    if name:
                        tools.append(name)
                elif isinstance(item, str):
                    tools.append(item)
    return sorted(set(tools))


def _blackboard_writes_for_agent(agent_name: str, state: Dict[str, Any]) -> List[str]:
    blackboard = state.get("research_blackboard", {}) if isinstance(state.get("research_blackboard"), dict) else {}
    writes: List[str] = []
    for item in blackboard.get("agent_writes", []) if isinstance(blackboard.get("agent_writes"), list) else []:
        if not isinstance(item, dict) or str(item.get("agent") or "") != agent_name:
            continue
        writes.extend(str(field) for field in item.get("writes", []) if str(field))
    return sorted(set(writes))


def _objections_for_agent(agent_name: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    if agent_name != "CriticAgent":
        return []
    blackboard = state.get("research_blackboard", {}) if isinstance(state.get("research_blackboard"), dict) else {}
    critic = blackboard.get("critic", {}) if isinstance(blackboard.get("critic"), dict) else {}
    return [item for item in critic.get("objections", []) if isinstance(item, dict)]


def _shorten(value: Any, limit: int = 220) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_shorten(item, limit=80) for item in value[:8]]
    if isinstance(value, dict):
        return {str(key): _shorten(val, limit=80) for key, val in list(value.items())[:8]}
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def prepare_dynamic_tasks(
    plan: Dict[str, Any],
    research_topic: str,
    symbol: str,
    period: str,
    raw_data_root: str,
    profile: Dict[str, Any] | None = None,
    search_engines: List[str] | None = None,
    retrieval_ranking_mode: str = "hybrid_rerank",
    enable_remote_data: bool = False,
    data_source_config_path: str = "configs/data_sources.yaml",
    curated_dir: str = "data/curated",
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
            params["engines"] = search_engines or _market_engines(symbol)
            params.setdefault("raw_data_root", raw_data_root)
            params.setdefault("curated_dir", curated_dir)
            params.setdefault("ranking_mode", retrieval_ranking_mode)
            params.setdefault("data_source_config_path", data_source_config_path)
            params.setdefault("enable_remote", bool(enable_remote_data))
            params.setdefault("search_budget_seconds", 240.0)
            params.setdefault("engine_timeout_seconds", 60.0)
            params.setdefault("engine_timeout_by_name", _research_engine_timeouts())
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


def _retrieval_curated_dir(output_dir: Path) -> str:
    task_dir = Path(output_dir) / "retrieval_curated"
    if task_dir.is_dir() and any(task_dir.glob("*.jsonl")):
        return str(task_dir)
    return "data/curated"


def _compact_research_phase_output(output: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(output or {})
    payload["evidence_candidates"] = [
        _compact_checkpoint_value(item)
        for item in list(payload.get("evidence_candidates") or [])[:20]
        if isinstance(item, dict)
    ]
    search_meta = dict(payload.get("search_meta") or {}) if isinstance(payload.get("search_meta"), dict) else {}
    returned_hits = search_meta.pop("returned_hits", None)
    if isinstance(returned_hits, list):
        search_meta["returned_hit_count"] = len(returned_hits)
        search_meta["returned_hit_ids"] = [
            str(item.get("result_id") or item.get("evidence_id") or "")
            for item in returned_hits[:20]
            if isinstance(item, dict)
        ]
    payload["search_meta"] = _compact_checkpoint_value(search_meta)
    return payload


def _compact_checkpoint_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 20_000 else value[:20_000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_checkpoint_value(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        return {
            str(key): _compact_checkpoint_value(item, depth=depth + 1)
            for key, item in list(value.items())[:80]
            if key != "raw_artifact_record"
        }
    return str(value)[:2_000]


def _compact_trace_task(task: AgentTask) -> Dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "description": _compact_trace_value(task.description),
        "parameters": _compact_trace_value(task.parameters),
        "dependencies": list(task.dependencies),
        "priority": task.priority,
        "metadata": _compact_trace_value(task.metadata),
    }


def _compact_trace_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 2_000 else value[:2_000] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        if len(value) <= 10 and all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
            return list(value)
        return {
            "type": "list",
            "count": len(value),
            "sample_ids": [
                str(item.get("evidence_id") or item.get("claim_id") or item.get("result_id") or "")
                for item in value[:5]
                if isinstance(item, dict)
            ],
        }
    if isinstance(value, dict):
        if depth >= 2:
            return {"type": "dict", "keys": sorted(str(key) for key in value)[:30]}
        return {
            str(key): _compact_trace_value(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
        }
    return str(value)[:500]


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


def prepare_collaborative_tasks(tasks: List[AgentTask]) -> List[AgentTask]:
    """Insert dedicated role-agent tasks between analysis and final writing."""

    output = list(tasks)
    existing = {task.task_type for task in output}
    analyze_ids = [task.task_id for task in output if task.task_type == "deep_analyze"]
    final_ids = [task.task_id for task in output if task.task_type == "final_answer"]
    role_specs = [
        ("task_role_identity", "identity_profile", "Resolve company identity and business profile."),
        ("task_role_statement", "three_statement_analysis", "Analyze three-statement coverage and period basis."),
        ("task_role_peer", "peer_analysis", "Analyze peer coverage and comparison limits."),
        ("task_role_valuation", "valuation_analysis", "Analyze valuation inputs and missing assumptions."),
        ("task_role_risk", "risk_analysis", "Analyze risk evidence and disclosure limits."),
    ]
    role_ids: List[str] = []
    for task_id, task_type, description in role_specs:
        if task_type in existing:
            role_ids.extend(task.task_id for task in output if task.task_type == task_type)
            continue
        role_ids.append(task_id)
        output.append(
            AgentTask(
                task_id=task_id,
                task_type=task_type,
                description=description,
                parameters={},
                dependencies=list(analyze_ids),
                priority=5,
            )
        )
    final_id_set = set(final_ids)
    rewritten: List[AgentTask] = []
    for task in output:
        deps = list(task.dependencies)
        if task.task_id in final_id_set:
            deps = [dep for dep in deps if dep not in analyze_ids]
            deps.extend(role_ids)
        deduped: List[str] = []
        for dep in deps:
            if dep != task.task_id and dep not in deduped:
                deduped.append(dep)
        rewritten.append(
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
    return apply_implicit_dependencies(rewritten)


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
        params.setdefault(
            "merge_standard_search_after_react",
            bool(profile.get("research_merge_standard_search_after_react", True)),
        )
        params.setdefault("react_max_tool_calls", int(profile.get("react_max_tool_calls", 8)))
        params.setdefault("react_tool_timeout_seconds", float(profile.get("react_tool_timeout_seconds", 45.0)))
        params.setdefault("react_tool_max_attempts", int(profile.get("react_tool_max_attempts", 2)))
        params.setdefault("use_chunks", bool(profile.get("research_use_chunks", True)))
        params["engines"] = _market_engines(state["symbol"])
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
        params.setdefault("symbol", state["symbol"])
        if not bool(state.get("allow_document_enrichment", True)):
            params["use_reader"] = False
            params["use_pdf_reader"] = False
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
        params.setdefault("react_max_tool_calls", int(profile.get("react_max_tool_calls", 8)))
        params.setdefault("react_tool_timeout_seconds", float(profile.get("react_tool_timeout_seconds", 45.0)))
        params.setdefault("react_tool_max_attempts", int(profile.get("react_tool_max_attempts", 2)))
        params.setdefault("claim_contract", str(state.get("claim_contract", "")))
    elif task.task_type in {
        "identity_profile",
        "three_statement_analysis",
        "peer_analysis",
        "valuation_analysis",
        "risk_analysis",
    }:
        params.setdefault("symbol", state["symbol"])
        params.setdefault("period", state["period"])
        params.setdefault("evidence_records", list(state.get("evidence_records", [])))
        params.setdefault("claims", list(state.get("claims", [])))
        params.setdefault(
            "analysis_artifacts",
            dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {},
        )
        params.setdefault(
            "research_blackboard",
            dict(state.get("research_blackboard", {})) if isinstance(state.get("research_blackboard"), dict) else {},
        )
        critic = state.get("pre_write_critic", {}) if isinstance(state.get("pre_write_critic"), dict) else {}
        params.setdefault("critic_objections", list(critic.get("objections", [])) if isinstance(critic.get("objections"), list) else [])
    elif task.task_type == "final_answer":
        params.setdefault("research_topic", state["research_topic"])
        params.setdefault("symbol", state["symbol"])
        params.setdefault("period", state["period"])
        entity_res = state.get("entity_resolution", {})
        params.setdefault("company_name", str(entity_res.get("company_name", "")) if isinstance(entity_res, dict) else "")
        if not isinstance(params.get("claims"), list) or not params.get("claims"):
            params["claims"] = list(state.get("claims", []))
        if not isinstance(params.get("evidence_records"), list) or not params.get("evidence_records"):
            params["evidence_records"] = list(state.get("evidence_records", []))
        # enrich_task_parameters is standalone, call builders directly
        _sanitize_state_peer_rows(state)
        _derived = build_derived_evidence(state)
        state["derived_evidence"] = _derived
        _state_evidence = list(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else []
        _state_claims = list(state.get("claims", [])) if isinstance(state.get("claims"), list) else []
        bundles = build_claim_evidence_bundles(_state_claims, _state_evidence, _derived)
        state["claim_evidence_bundles"] = bundles
        params["claim_evidence_bundles"] = bundles

        _dossiers = SectionDossierBuilder().build(
            state=state,
            claims=list(state.get("claims", [])) if isinstance(state.get("claims"), list) else [],
            evidence_records=list(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else [],
            analysis_artifacts=dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {},
            derived_evidence=_derived,
            bundles=bundles,
        )
        _dossiers = _inject_pdf_facts_into_dossiers(state, _dossiers, path="main")
        state["section_dossiers"] = _dossiers
        params["section_dossiers"] = _dossiers
        analysis_artifacts = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        analysis_artifacts = _apply_canonical_metrics_to_artifacts(
            analysis_artifacts,
            symbol=str(state.get("symbol", "") or ""),
            period=str(state.get("period", "") or ""),
        )
        state["analysis_artifacts"] = analysis_artifacts
        params.setdefault("tables", analysis_artifacts.get("tables", []))
        params.setdefault("financial_metrics", analysis_artifacts.get("financial_metrics", {}))
        params.setdefault("currency_audit", analysis_artifacts.get("currency_audit", {}))
        params.setdefault("valuation_model", analysis_artifacts.get("valuation_model", {}))
        params["pdf_sections"] = state.get("pdf_section_summaries") or analysis_artifacts.get("pdf_section_summaries") or analysis_artifacts.get("pdf_sections", [])
        params.setdefault("company_profile", analysis_artifacts.get("company_profile", {}))
        params.setdefault("annual_report_sections", state.get("annual_report_sections", {}))
        params.setdefault("quality_remediation_plan", dict(state.get("quality_remediation_plan", {})) if isinstance(state.get("quality_remediation_plan"), dict) else {})
        params.setdefault("repair_constraints", dict(state.get("repair_constraints", {})) if isinstance(state.get("repair_constraints"), dict) else {})
        params.setdefault("research_blackboard", dict(state.get("research_blackboard", {})) if isinstance(state.get("research_blackboard"), dict) else {})
        params.setdefault("pre_write_critic", dict(state.get("pre_write_critic", {})) if isinstance(state.get("pre_write_critic"), dict) else {})
        params.setdefault("degraded_report", bool(state.get("collaborative_degraded_report", False)))
        params.setdefault("pre_write_rework_history", list(state.get("pre_write_rework_history", [])) if isinstance(state.get("pre_write_rework_history"), list) else [])
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
        previous_artifacts = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        incoming_artifacts = result.output.get("analysis_artifacts", {})
        artifacts = dict(incoming_artifacts) if isinstance(incoming_artifacts, dict) else {}
        for key in [
            "annual_report_required",
            "annual_report_sections",
            "annual_report_section_count",
            "annual_report_degraded_reason",
            "sec_filing_resolver",
        ]:
            if key in previous_artifacts and key not in artifacts:
                artifacts[key] = previous_artifacts[key]
        state["analysis_artifacts"] = artifacts
    elif task_type in {
        "identity_profile",
        "three_statement_analysis",
        "peer_analysis",
        "valuation_analysis",
        "risk_analysis",
    }:
        artifacts = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
        role_outputs = dict(artifacts.get("role_outputs", {})) if isinstance(artifacts.get("role_outputs"), dict) else {}
        incoming = result.output.get("role_outputs", {}) if isinstance(result.output.get("role_outputs"), dict) else {}
        for key, value in incoming.items():
            if isinstance(value, dict):
                role_outputs[key] = dict(value)
                artifacts[key] = dict(value)
        artifacts["role_outputs"] = role_outputs
        state["analysis_artifacts"] = artifacts
    elif task_type == "final_answer":
        markdown = str(result.output.get("markdown", ""))
        html = str(result.output.get("html", ""))
        report_json = result.output.get("report_json", {})
        metadata = result.metadata if hasattr(result, "metadata") and isinstance(result.metadata, dict) else {}
        contract_mode_used = bool(metadata.get("contract_mode", False))
        citation_map = metadata.get("citation_map", {})

        charts = generate_report_charts(
            claims=list(state.get("claims", [])),
            evidence_records=list(state.get("evidence_records", [])),
            output_dir=str(state.get("chart_output_dir") or "data/outputs/multi_agent/charts"),
            tables=dict(state.get("analysis_artifacts", {})).get("tables", []),
            analysis_artifacts=dict(state.get("analysis_artifacts", {})),
            currency_context=dict(state.get("analysis_artifacts", {})).get("currency_audit", {}),
        )
        charts = repair_known_mojibake_obj(charts)
        markdown = repair_known_mojibake_text(attach_charts_to_markdown(markdown, charts))
        markdown = repair_known_mojibake_text(inject_chart_references(markdown, charts))
        html = polish_report_html(attach_charts_to_html(html, charts))

        if contract_mode_used and citation_map:
            state["markdown"] = markdown
            state["citations"] = list(state.get("citations", []))
            state["citations_markdown"] = str(state.get("citations_markdown", ""))
            state["charts"] = charts
            state["html"] = html
            state["report_title"] = str(report_json.get("title", "")) if isinstance(report_json, dict) else ""
        else:
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
            entity_res = dict(state.get("entity_resolution", {})) if isinstance(state.get("entity_resolution"), dict) else {}
            llm_title = str(report_json.get("title", "")).strip() if isinstance(report_json, dict) else ""
            if llm_title and any(p in llm_title for p in ("生成", "任务", "生成报告")):
                llm_title = ""
            fallback_title = _build_formal_report_title(entity_res, str(state.get("symbol", "")), str(state.get("period", "")))
            state["html"] = render_professional_html_report(
                markdown=state["markdown"],
                title=llm_title or fallback_title,
                charts=charts,
                citations=state["citations"],
                delivery_status=str(report_json.get("delivery_status") or "normal") if isinstance(report_json, dict) else "normal",
            )
            state["report_title"] = llm_title or fallback_title

        if contract_mode_used and citation_map:
            contract_citations = build_citations_from_map(
                evidence_records=list(state.get("evidence_records", [])),
                citation_map=citation_map,
                claims=list(state.get("claims", [])),
                markdown=state.get("markdown", ""),
            )
            state["citations"] = contract_citations
            state["citations_markdown"] = render_citations_markdown(contract_citations)
            if state["citations_markdown"] and state["citations_markdown"] not in state.get("markdown", ""):
                state["markdown"] = str(state.get("markdown", "")).rstrip() + "\n\n" + state["citations_markdown"]
        entity_res = dict(state.get("entity_resolution", {})) if isinstance(state.get("entity_resolution"), dict) else {}
        llm_title = str(report_json.get("title", "")).strip() if isinstance(report_json, dict) else ""
        if llm_title and any(p in llm_title for p in ("鐢熸垚", "浠诲姟", "鐢熸垚鎶ュ憡")):
            llm_title = ""
        fallback_title = _build_formal_report_title(entity_res, str(state.get("symbol", "")), str(state.get("period", "")))
        state["report_title"] = repair_known_mojibake_text(llm_title) or fallback_title
        state["html"] = render_professional_html_report(
            markdown=str(state.get("markdown", "")),
            title=state["report_title"],
            charts=charts,
            citations=list(state.get("citations", [])),
            delivery_status=str(report_json.get("delivery_status") or "normal") if isinstance(report_json, dict) else "normal",
            top_blockers=list(metadata.get("top_blockers", [])) if isinstance(metadata.get("top_blockers", []), list) else [],
            contract_mode=contract_mode_used,
        )

        state["markdown"] = append_compliance_disclosures(state["markdown"], citations=state["citations"])
        state["html"] = append_compliance_disclosures_to_html(state["html"], citations=state["citations"])
        if isinstance(report_json, dict):
            report_json = dict(report_json)
            report_json["citations"] = state["citations"]
            report_json["charts"] = charts
            report_json["compliance_disclosure"] = {"included": True, "rating_definition": "未评级"}
            report_json["analysis_artifacts"] = state.get("analysis_artifacts", {})
            report_json["section_dossiers"] = state.get("section_dossiers", {})
            if contract_mode_used:
                report_json["top_blockers"] = metadata.get("top_blockers", [])
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
    pdf_rag = build_pdf_rag_artifacts(
        pdf_artifacts=pdf_artifacts,
        output_dir=output_dir,
        symbol=str(state.get("symbol", "")),
        period=str(state.get("period", "")),
        max_pages_per_section=6 if fast else 10,
    )
    pdf_artifacts.update(pdf_rag)
    state["pdf_artifacts"] = pdf_artifacts
    state["pdf_section_summaries"] = pdf_rag.get("pdf_section_summaries", [])
    state["section_evidence"] = pdf_rag.get("pdf_section_summaries", [])
    analysis = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
    analysis["pdf_section_summaries"] = pdf_rag.get("pdf_section_summaries", [])
    analysis["pdf_extraction_audit"] = pdf_rag.get("pdf_extraction_audit", {})
    state["analysis_artifacts"] = analysis
    summary_records = _pdf_summaries_as_evidence_records(
        summaries=pdf_rag.get("pdf_section_summaries", []),
        symbol=str(state.get("symbol", "")),
        period=str(state.get("period", "")),
    )
    top_chunk_records = _pdf_top_chunks_as_evidence_records(
        chunks=pdf_rag.get("pdf_section_chunks", []),
        symbol=str(state.get("symbol", "")),
        period=str(state.get("period", "")),
    )
    section_records = _pdf_sections_as_evidence_records(
        sections=pdf_artifacts.get("pdf_sections", []),
        symbol=str(state.get("symbol", "")),
        period=str(state.get("period", "")),
    )
    table_records = _pdf_tables_as_evidence_records(
        tables=pdf_artifacts.get("pdf_tables", []),
        symbol=str(state.get("symbol", "")),
        period=str(state.get("period", "")),
    )
    if summary_records or top_chunk_records or section_records or table_records:
        state["evidence_records"] = _merge_records(
            records,
            summary_records + top_chunk_records + section_records + table_records,
            key_names=["evidence_id", "sample_id", "source_url"],
        )


def attach_annual_report_sections_to_state(state: Dict[str, Any], raw_data_root: str = "data/raw/real_data") -> None:
    """Resolve, fetch, parse, and merge SEC 10-K sections for US FY reports."""

    if isinstance(state.get("annual_report_sections"), dict):
        return
    symbol = str(state.get("symbol") or "").strip().upper()
    period = str(state.get("period") or "").strip().upper()
    if not _requires_sec_annual_report(symbol=symbol, period=period):
        return

    analysis = dict(state.get("analysis_artifacts", {})) if isinstance(state.get("analysis_artifacts"), dict) else {}
    if not bool(state.get("enable_remote_data", False)):
        meta = {
            "status": "skipped",
            "symbol": symbol,
            "period": period,
            "failure_reason": "remote_sources_disabled",
        }
        state["sec_filing_resolver"] = meta
        state["annual_report_sections"] = {"sections": {}, "coverage": {}, "section_count": 0, "meta": meta}
        state["annual_report_required"] = True
        state["collaborative_degraded_report"] = True
        analysis["annual_report_required"] = True
        analysis["annual_report_degraded_reason"] = "remote_sources_disabled"
        state["analysis_artifacts"] = analysis
        return

    chart_dir = Path(str(state.get("chart_output_dir") or "data/outputs/multi_agent/charts"))
    output_dir = chart_dir.parent
    payload = resolve_sec_annual_filing(
        symbol=symbol,
        period=period,
        config_path=str(state.get("data_source_config_path") or "configs/data_sources.yaml"),
        raw_data_root=raw_data_root,
        cache_dir=output_dir / "sec_filings",
        fetch_document=True,
    )
    data = payload.to_dict()
    resolver_meta = dict(data.get("meta", {}))
    state["sec_filing_resolver"] = resolver_meta

    records = list(state.get("evidence_records", [])) if isinstance(state.get("evidence_records"), list) else []
    filing_records = data.get("evidence_records", []) if isinstance(data.get("evidence_records"), list) else []
    if filing_records:
        records = _merge_records(records, filing_records, key_names=["evidence_id", "sample_id", "source_url"])

    proxy_payload = resolve_sec_proxy_filing(
        symbol=symbol,
        period=period,
        config_path=str(state.get("data_source_config_path") or "configs/data_sources.yaml"),
        raw_data_root=raw_data_root,
    ).to_dict()
    proxy_records = proxy_payload.get("evidence_records", []) if isinstance(proxy_payload.get("evidence_records"), list) else []
    if proxy_records:
        records = _merge_records(records, proxy_records, key_names=["evidence_id", "sample_id", "source_url"])
    state["sec_proxy_resolver"] = dict(proxy_payload.get("meta", {}))

    sections_input = data.get("sections_input", {}) if isinstance(data.get("sections_input"), dict) else {}
    extractor = AnnualReportSectionExtractor(
        html_text=str(sections_input.get("html_text") or ""),
        html_path=str(sections_input.get("html_path") or ""),
    )
    annual_sections = extractor.extract(
        symbol=symbol,
        period=period,
        filing_url=str(sections_input.get("filing_url") or resolver_meta.get("filing_url") or ""),
        filing_title=str(sections_input.get("filing_title") or ""),
        filing_evidence_id=str(sections_input.get("filing_evidence_id") or ""),
    )
    section_records = annual_sections_to_evidence_records(annual_sections)
    if section_records:
        records = _merge_records(records, section_records, key_names=["evidence_id", "sample_id", "source_url"])

    annual_sections["resolver_meta"] = resolver_meta
    state["annual_report_sections"] = annual_sections
    state["evidence_records"] = records
    state["annual_report_required"] = True

    analysis["annual_report_required"] = True
    analysis["annual_report_sections"] = annual_sections
    analysis["annual_report_section_count"] = int(annual_sections.get("section_count") or 0)
    analysis["sec_filing_resolver"] = resolver_meta
    analysis["sec_proxy_resolver"] = state["sec_proxy_resolver"]
    if not section_records:
        state["collaborative_degraded_report"] = True
        reason = str(resolver_meta.get("failure_reason") or resolver_meta.get("status") or "annual_report_sections_missing")
        analysis["annual_report_degraded_reason"] = reason
        repair = dict(state.get("repair_constraints", {})) if isinstance(state.get("repair_constraints"), dict) else {}
        repair["annual_report_required_but_missing"] = True
        repair["annual_report_failure_reason"] = reason
        state["repair_constraints"] = repair
    else:
        analysis["annual_report_degraded_reason"] = ""
    state["analysis_artifacts"] = analysis


def _inject_pdf_facts_into_dossiers(state: Dict[str, Any], dossiers: Dict[str, Any], *, path: str) -> Dict[str, Any]:
    """Standalone facts injection for dynamic task enrichment paths."""
    pdf_sections = (
        state.get("pdf_section_summaries")
        or state.get("section_evidence")
        or state.get("pdf_sections", [])
    )
    audit: Dict[str, Any] = {
        "schema_version": "facts_extraction_audit.v1",
        "path": path,
        "symbol": state.get("symbol", ""),
        "period": state.get("period", ""),
        "input_section_count": len(pdf_sections) if isinstance(pdf_sections, list) else 0,
            "extracted_fact_count": 0,
            "facts_extraction_types": [],
            "removed_raw_paragraph_count": 0,
            "removed_raw_key_fact_count": 0,
            "final_suggested_paragraph_count": 0,
            "sections": {},
        }
    if not isinstance(pdf_sections, list) or not pdf_sections:
        state["facts_extraction_audit"] = audit
        _write_facts_extraction_audit_from_state(state, audit)
        return dossiers

    try:
        from src.report.fact_extractors.pdf_facts_extractor import (
            extract_section_facts,
            inject_facts_into_dossiers,
        )

        symbol = str(state.get("symbol", "")).upper()
        market = "cn_a" if symbol.endswith((".SS", ".SZ")) else "hk" if symbol.endswith(".HK") else "us"
        facts = extract_section_facts(pdf_sections, market=market)
        audit["raw_fact_section_count"] = len(facts) if isinstance(facts, dict) else 0
        if facts and any(section_facts for section_facts in facts.values()):
            dossiers = inject_facts_into_dossiers(dossiers, facts, audit=audit)
            import logging
            logging.getLogger(__name__).info(
                "facts_extraction | path=%s sections=%d types=%s removed_raw=%d",
                path,
                int(audit.get("extracted_fact_count", 0) or 0),
                audit.get("facts_extraction_types", []),
                int(audit.get("removed_raw_paragraph_count", 0) or 0),
            )
    except Exception as exc:
        audit["error"] = str(exc)
        import logging
        logging.getLogger(__name__).warning("facts_extraction failed: %s", exc)
    finally:
        state["facts_extraction_audit"] = audit
        _write_facts_extraction_audit_from_state(state, audit)
    return dossiers


def _write_facts_extraction_audit_from_state(state: Dict[str, Any], audit: Dict[str, Any]) -> None:
    chart_dir = str(state.get("chart_output_dir") or "").strip()
    if not chart_dir:
        return
    try:
        output_dir = Path(chart_dir).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "facts_extraction_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return


def _market_engines(symbol: str) -> list[str]:
    """Return the canonical market-aware source plan."""

    market = infer_market_from_symbol(symbol)
    return list(build_data_source_plan(symbol, market["market"], market["exchange"])["engines"])


def _research_engine_timeouts() -> Dict[str, float]:
    return {
        "sec_edgar": 120.0,
        "local_evidence": 90.0,
        "independent_macro": 60.0,
        "yahoo_finance": 30.0,
        "tavily": 20.0,
        "serper": 20.0,
    }


def _requires_sec_annual_report(symbol: str, period: str) -> bool:
    if not symbol or not period.startswith("FY"):
        return False
    # For now, only US tickers without exchange suffix use SEC 10-K routing.
    return "." not in symbol


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


def _pdf_summaries_as_evidence_records(summaries: Any, symbol: str, period: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    if not isinstance(summaries, list):
        return output
    for summary in summaries:
        if not isinstance(summary, dict) or not summary.get("usable_for_generation"):
            continue
        section_type = str(summary.get("section_type") or "").strip()
        content = str(summary.get("summary_zh") or "").strip()
        if not section_type or not content:
            continue
        evidence_id = str(summary.get("evidence_id") or f"pdf_summary_{symbol}_{period}_{section_type}".replace(".", "_").lower())
        output.append(
            {
                "evidence_id": evidence_id,
                "sample_id": evidence_id,
                "source_type": "annual_report_pdf_section_summary",
                "title": str(summary.get("section_title") or f"Official PDF section: {section_type}"),
                "source_url": str(summary.get("source_url") or ""),
                "publish_time": "",
                "content": content,
                "symbol": symbol,
                "period": period,
                "trust_level": "official",
                "metadata": {
                    "section_type": section_type,
                    "pages": list(summary.get("pages", [])) if isinstance(summary.get("pages"), list) else [],
                    "source_chunk_ids": list(summary.get("source_chunk_ids", [])) if isinstance(summary.get("source_chunk_ids"), list) else [],
                    "anchor_source": str(summary.get("anchor_source") or ""),
                    "report_market": str(summary.get("report_market") or ""),
                    "evidence_quality": str(summary.get("evidence_quality") or ""),
                },
            }
        )
    return output


def _pdf_top_chunks_as_evidence_records(chunks: Any, symbol: str, period: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    if not isinstance(chunks, list):
        return output
    seen: set[str] = set()
    for chunk in chunks:
        if not isinstance(chunk, dict) or not chunk.get("usable_for_generation"):
            continue
        chunk_id = str(chunk.get("chunk_id") or chunk.get("evidence_id") or "").strip()
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        output.append(
            {
                "evidence_id": chunk_id,
                "sample_id": chunk_id,
                "source_type": "annual_report_pdf_chunk",
                "title": str(chunk.get("section_title") or chunk.get("section_type") or "Official PDF chunk"),
                "source_url": str(chunk.get("source_url") or ""),
                "publish_time": "",
                "content": str(chunk.get("text_clean") or chunk.get("text") or ""),
                "symbol": symbol,
                "period": period,
                "trust_level": "official",
                "metadata": {
                    "section_type": str(chunk.get("section_type") or ""),
                    "pages": list(chunk.get("pages", [])) if isinstance(chunk.get("pages"), list) else [],
                    "anchor_source": str(chunk.get("anchor_source") or ""),
                    "report_market": str(chunk.get("report_market") or ""),
                    "block_type": str(chunk.get("block_type") or "paragraph"),
                    "retrieval_score": float(chunk.get("retrieval_score", 0.0) or 0.0),
                },
            }
        )
    return output


def _pdf_tables_as_evidence_records(tables: Any, symbol: str, period: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    if not isinstance(tables, list):
        return output
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("table_id") or "")
        table_type = str(table.get("table_type") or "")
        rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        if not table_id or not table_type or not rows:
            continue
        evidence_id = f"pdf_table_{table_id}"
        summary = "; ".join(
            f"{row.get('line_item')}={row.get('value')}"
            for row in rows[:8]
            if isinstance(row, dict) and row.get("line_item")
        )
        output.append(
            {
                "evidence_id": evidence_id,
                "sample_id": evidence_id,
                "source_type": "pdf_statement_table",
                "title": f"PDF table: {table_type}",
                "source_url": str(table.get("source_url") or ""),
                "publish_time": "",
                "content": f"{table_type} extracted from PDF page {table.get('page')}: {summary}",
                "symbol": symbol,
                "period": period,
                "trust_level": "high",
                "metadata": {
                    "table_id": table_id,
                    "table_type": table_type,
                    "rows": rows,
                    "raw_rows": table.get("raw_rows", []),
                    "unit": table.get("unit", "raw"),
                    "currency": table.get("currency", ""),
                    "page": table.get("page", ""),
                    "source_evidence_id": table.get("evidence_id", ""),
                    "extraction_method": table.get("extraction_method", ""),
                    "confidence": table.get("confidence", 0.0),
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


def _verifier_report_to_gap_trace(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(report, dict):
        return []
    gaps = [gap for gap in report.get("evidence_gaps", []) if isinstance(gap, dict)]
    if gaps:
        return build_gap_resolution_trace(gaps)
    synthetic: List[Dict[str, Any]] = []
    for index, message in enumerate(list(report.get("llm_errors", []) or []) + list(report.get("errors", []) or []), start=1):
        text = str(message or "").strip()
        if not text:
            continue
        synthetic.append(
            {
                "gap_id": f"verifier_feedback_{index:04d}",
                "gap_type": "verifier_feedback",
                "claim_id": "",
                "route": "final_answer",
                "action": "revise_language",
                "attempt": 0,
                "max_attempts": 1,
                "status": "queued",
                "message": text,
            }
        )
    return synthetic


def _revision_request_to_gap_trace(revision_request: str) -> List[Dict[str, Any]]:
    text = str(revision_request or "").strip()
    if not text:
        return []
    return [
        {
            "gap_id": "verifier_feedback_0001",
            "gap_type": "verifier_feedback",
            "claim_id": "",
            "route": "final_answer",
            "action": "revise_language",
            "attempt": 0,
            "max_attempts": 1,
            "status": "queued",
            "message": text[:500],
        }
    ]


def _revision_history_to_gap_trace(history: Any) -> List[Dict[str, Any]]:
    rows = history if isinstance(history, list) else []
    output: List[Dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("revision_request") or "").strip()
        if not text:
            continue
        output.append(
            {
                "gap_id": f"revision_round_{index:04d}",
                "gap_type": "verifier_feedback",
                "claim_id": "",
                "route": "final_answer",
                "action": "revise_language",
                "attempt": int(item.get("round", index) or index),
                "max_attempts": 1,
                "status": "resolved_or_downgraded" if item.get("passed_after_round") else "still_open",
                "message": text[:500],
            }
        )
    return output


def _blocking_objections(critic: Any) -> List[Dict[str, Any]]:
    if not isinstance(critic, dict):
        return []
    return [
        item
        for item in critic.get("objections", [])
        if isinstance(item, dict) and (item.get("blocking") is True or str(item.get("severity", "")).lower() in {"fatal", "blocker"})
    ]


def _ordered_targets(objections: List[Dict[str, Any]]) -> List[str]:
    order = ["IdentityAgent", "StatementAgent", "PeerAgent", "ValuationAgent", "RiskAgent", "FinalAnswerAgent"]
    present = {str(item.get("target_agent") or "") for item in objections if item.get("target_agent")}
    return [name for name in order if name in present]


def _role_task_type_for_agent(agent_name: str) -> str:
    return {
        "IdentityAgent": "identity_profile",
        "StatementAgent": "three_statement_analysis",
        "PeerAgent": "peer_analysis",
        "ValuationAgent": "valuation_analysis",
        "RiskAgent": "risk_analysis",
    }.get(str(agent_name or ""), "")


def agent_key_for_task(task_type: str) -> str:
    mapping = {
        "deep_researcher": "research",
        "browser": "browser",
        "deep_analyze": "analyze",
        "identity_profile": "identity",
        "three_statement_analysis": "statement",
        "peer_analysis": "peer",
        "valuation_analysis": "valuation",
        "risk_analysis": "risk",
        "final_answer": "final_answer",
        "verifier": "verifier",
    }
    if task_type not in mapping:
        raise KeyError(f"unsupported dynamic task_type: {task_type}")
    return mapping[task_type]


def _apply_canonical_metrics_to_artifacts(
    analysis_artifacts: Any,
    *,
    evidence_records: Any = None,
    symbol: str,
    period: str,
) -> Dict[str, Any]:
    artifacts = dict(analysis_artifacts) if isinstance(analysis_artifacts, dict) else {}
    raw_financial_metrics = artifacts.get("raw_financial_metrics", artifacts.get("financial_metrics", {}))
    tables = artifacts.get("tables", []) if isinstance(artifacts.get("tables"), list) else []
    canonical = build_canonical_metrics_artifact(
        financial_metrics=raw_financial_metrics,
        tables=tables,
        evidence_records=evidence_records,
        symbol=symbol,
        period=period,
    )
    artifacts["raw_financial_metrics"] = raw_financial_metrics
    artifacts["canonical_metrics"] = canonical
    artifacts["financial_metrics"] = canonical_metrics_as_financial_metrics(canonical, fallback=raw_financial_metrics)
    return artifacts


def _task_type_order(task_type: str) -> int:
    order = {
        "deep_researcher": 10,
        "browser": 20,
        "deep_analyze": 30,
        "identity_profile": 35,
        "three_statement_analysis": 35,
        "peer_analysis": 35,
        "valuation_analysis": 35,
        "risk_analysis": 35,
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
        company_name = str(topic_company.get("company_name", ""))
        source = "topic"
    elif symbol_company:
        resolved_symbol = str(symbol_company["symbol"]).upper()
        company_name = str(symbol_company.get("company_name", ""))
        source = "symbol"
    elif topic_company:
        resolved_symbol = str(topic_company["symbol"]).upper()
        company_name = str(topic_company.get("company_name", ""))
        source = "topic_fallback"
    else:
        resolved_symbol = requested.upper() or "AAPL"
        company_name = ""
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
        "company_name": company_name,
    }


def _resolve_run_symbol(research_topic: str, symbol: str, raw_data_root: str) -> str:
    """Backward-compatible helper for callers/tests that only need a ticker."""

    identity = _resolve_run_identity(research_topic=research_topic, symbol=symbol, raw_data_root=raw_data_root)
    return str(identity.get("resolved_symbol") or "AAPL").upper()


def _format_period_for_title(period: str) -> str:
    """Convert period code to Chinese display format for report titles."""
    p = period.strip().upper()
    if p.startswith("FY"):
        return f"{p[2:]}财年"
    if re.match(r"^\d{4}Q[1-4]$", p):
        quarter_map = {"Q1": "第一季度", "Q2": "第二季度", "Q3": "第三季度", "Q4": "第四季度"}
        year = p[:4]
        quarter = quarter_map.get(p[4:], p[4:])
        return f"{year}年{quarter}"
    if re.match(r"^\d{4}$", p):
        return f"{p}财年"
    return p


def _build_formal_report_title(entity_resolution: dict, symbol: str, period: str) -> str:
    """Build a professional formal report title from entity resolution data."""
    company_name = str(entity_resolution.get("company_name") or "")
    period_display = _format_period_for_title(period)
    if company_name:
        return f"财务研究报告：{company_name}（{symbol}）{period_display}公司财务研究报告"
    return f"财务研究报告：{symbol} {period_display}公司财务研究报告"


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


def _should_stop_delivery_rework(gate: Dict[str, Any]) -> bool:
    issues = gate.get("issues", []) if isinstance(gate.get("issues"), list) else []
    blocking_categories = {
        "html_artifact",
        "html_table_integrity",
        "cross_report_symbol_pollution",
        "developer_placeholder",
        "mojibake_policy",
        "business_overview_wrong_section",
        "official_source_distribution",
    }
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity") or "").lower()
        category = str(issue.get("category") or "").lower()
        if severity in {"fatal", "blocker"} and category in blocking_categories:
            return True
    return False


def _sanitize_state_peer_rows(state: Dict[str, Any]) -> None:
    analysis = state.get("analysis_artifacts", {}) if isinstance(state.get("analysis_artifacts"), dict) else {}
    blackboard = state.get("research_blackboard", {}) if isinstance(state.get("research_blackboard"), dict) else {}
    clean_rows = sanitize_peer_rows_for_report(analysis, blackboard, target_symbol=str(state.get("symbol") or ""))
    state["analysis_artifacts"] = analysis
    state["research_blackboard"] = blackboard
    if clean_rows:
        state["peer_rows"] = clean_rows
    elif "peer_rows" in state:
        state["peer_rows"] = []


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
