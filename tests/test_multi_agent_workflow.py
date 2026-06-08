import json
import re
import sys

from src.agents import AgentStatus, AgentTask, BrowserAgent, DeepAnalyzeAgent, FinalAnswerAgent, VerifierAgent
from src.agents.analysis_role_agents import IdentityAgent, PeerAgent, RiskAgent, StatementAgent, ValuationAgent
from src.agents.browser_agent import enrich_records_with_reader, read_pdf_content, read_url_content
from src.agents.deep_analyze_agent import build_role_outputs, compact_records
from src.agents.final_answer_agent import (
    _claims_to_markdown_bullets,
    _filter_reportable_claims,
    _section_title,
    backfill_role_output_sections,
    enforce_verified_financial_sections,
    ensure_period_disclosure,
    hard_backfill_quality_sections,
    insert_missing_sections_from_claims,
    normalize_report_headings,
)
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator, enrich_task_parameters, prepare_dynamic_tasks
from src.agents.research_blackboard import build_pre_write_critic, initialize_research_blackboard, validate_role_output_write
from src.agents.verifier import Verifier
from src.schemas.claim import ClaimItem
from src.search import SearchManager


class FakeJsonModel:
    model_name = "fake-json-model"

    def generate_json(self, prompt, system_prompt=None, **kwargs):
        if "BrowserAgent" in system_prompt:
            return {
                "records": [
                    {
                        "evidence_id": "ev_fin",
                        "title": "Financials",
                        "content": "Revenue 126.3B.",
                        "source_url": "https://example.com/fin",
                        "source_type": "financials",
                        "key_points": ["Revenue 126.3B"],
                    }
                ]
            }
        if "DeepAnalyzeAgent" in system_prompt:
            evidence_match = re.search(r"'evidence_id': '([^']+)'", prompt)
            evidence_id = evidence_match.group(1) if evidence_match else "ev_fin"
            return {
                "claims": [
                    {
                        "section_name": "financial_analysis",
                        "claim_text": f"AAPL revenue was 126.3B. [{evidence_id}]",
                        "evidence_ids": [evidence_id],
                        "numeric_values": {"revenue_billion": 126.3},
                        "risk_level": "low",
                        "confidence": 0.85,
                        "notes": "fake",
                    }
                ]
            }
        if "FinalAnswerAgent" in system_prompt:
            evidence_ids = re.findall(r"'evidence_ids': \['([^']+)'\]", prompt) or re.findall(r'"evidence_ids": \["([^"]+)"\]', prompt)
            citation_line = " ".join(f"[{item}]" for item in evidence_ids[:8])
            return {
                "markdown": (
                    "# Report\n\n"
                    f"## Executive Summary\n\nAAPL revenue was 126.3B. {citation_line}\n\n"
                    "## Business Overview\n\n- Business overview with citations.\n\n"
                    "## Ownership and Governance\n\n- Governance summary with citations.\n\n"
                    "## Strategy and Business\n\n- Strategy and business mix with citations.\n\n"
                    "## Financial Statements\n\n- Three-statement summary with citations.\n\n"
                    "## Financial Analysis\n\n- AAPL revenue was 126.3B.\n\n"
                    "## Peer Comparison\n\n- Peer comparison with citations.\n\n"
                    "## Valuation\n\n- Valuation observation with citations.\n\n"
                    "## Valuation Sensitivity\n\n- Sensitivity analysis with citations.\n\n"
                    "## Risk Assessment\n\n- No major issue in fake test.\n\n"
                    "## Conclusion\n\n- Initial conclusion.\n"
                ),
                "summary": "ok",
                "citation_count": 1,
            }
        if "VerifierAgent" in system_prompt:
            return {"passed": True, "errors": [], "warnings": [], "fix_recommendations": []}
        if "PlanningAgent" in system_prompt:
            return {
                "overview": "Dynamic fake plan",
                "tasks": [
                    {
                        "task_id": "task_001_research",
                        "task_type": "deep_researcher",
                        "description": "Collect AAPL evidence.",
                        "parameters": {"query": "AAPL 2025Q4 revenue cash flow"},
                        "dependencies": [],
                        "priority": 5,
                        "expected_output": "Evidence candidates.",
                    },
                    {
                        "task_id": "task_002_browser",
                        "task_type": "browser",
                        "description": "Normalize evidence.",
                        "parameters": {},
                        "dependencies": ["task_001_research"],
                        "priority": 4,
                        "expected_output": "Evidence records.",
                    },
                    {
                        "task_id": "task_003_analyze",
                        "task_type": "deep_analyze",
                        "description": "Analyze claims.",
                        "parameters": {},
                        "dependencies": ["task_002_browser"],
                        "priority": 5,
                        "expected_output": "Claims.",
                    },
                    {
                        "task_id": "task_004_final",
                        "task_type": "final_answer",
                        "description": "Write report.",
                        "parameters": {},
                        "dependencies": ["task_003_analyze"],
                        "priority": 4,
                        "expected_output": "Report.",
                    },
                    {
                        "task_id": "task_005_verify",
                        "task_type": "verifier",
                        "description": "Verify report.",
                        "parameters": {},
                        "dependencies": ["task_004_final"],
                        "priority": 3,
                        "expected_output": "Verification.",
                    },
                ],
                "data_sources": ["local_real_data"],
                "citations_required": True,
                "final_outputs": ["report.md", "report.html"],
            }
        return {}


class RevisionFakeModel(FakeJsonModel):
    def __init__(self):
        self.verifier_calls = 0

    def generate_json(self, prompt, system_prompt=None, **kwargs):
        if "FinalAnswerAgent" in system_prompt:
            if "Revision instructions:" in prompt:
                return {
                    "markdown": (
                        "# Report\n\n"
                        "## Executive Summary\n\nAAPL revenue was 126.3B. [ev_fin]\n\n"
                        "## Business Overview\n\n- Business overview with citations. [ev_fin]\n\n"
                        "## Ownership and Governance\n\n- Governance summary with citations. [ev_fin]\n\n"
                        "## Strategy and Business\n\n- Strategy and business mix with citations. [ev_fin]\n\n"
                        "## Financial Statements\n\n- Three-statement summary with citations. [ev_fin]\n\n"
                        "## Financial Analysis\n\n- AAPL revenue was 126.3B. [ev_fin]\n\n"
                        "## Peer Comparison\n\n- Peer comparison with citations. [ev_fin]\n\n"
                        "## Valuation\n\n- Valuation observation with citations. [ev_fin]\n\n"
                        "## Valuation Sensitivity\n\n- Sensitivity analysis with citations. [ev_fin]\n\n"
                        "## Risk Assessment\n\n- Revised risk paragraph. [ev_fin]\n\n"
                        "## Conclusion\n\n- Revised conclusion. [ev_fin]\n"
                    ),
                    "summary": "reworked",
                    "citation_count": 7,
                }
            return {
                "markdown": (
                    "# Report\n\n"
                    "## Executive Summary\n\nAAPL revenue was 126.3B.\n\n"
                    "## Business Overview\n\n- Business overview.\n\n"
                    "## Ownership and Governance\n\n- Governance summary.\n\n"
                    "## Strategy and Business\n\n- Strategy and business mix.\n\n"
                    "## Financial Statements\n\n- Three-statement summary.\n\n"
                    "## Financial Analysis\n\n- AAPL revenue was 126.3B.\n\n"
                    "## Peer Comparison\n\n- Peer comparison.\n\n"
                    "## Valuation\n\n- Valuation observation.\n\n"
                    "## Valuation Sensitivity\n\n- Sensitivity analysis.\n\n"
                    "## Risk Assessment\n\n- Missing citation here.\n\n"
                    "## Conclusion\n\n- Initial conclusion.\n"
                ),
                "summary": "first draft",
                "citation_count": 0,
            }
        if "VerifierAgent" in system_prompt:
            self.verifier_calls += 1
            if self.verifier_calls == 1:
                return {
                    "passed": False,
                    "errors": ["Missing evidence citations for factual claims."],
                    "warnings": [],
                    "fix_recommendations": ["Add [evidence_id] citations to each factual sentence."],
                }
            return {"passed": True, "errors": [], "warnings": [], "fix_recommendations": []}
        return super().generate_json(prompt, system_prompt=system_prompt, **kwargs)


class QualityRemediationFakeModel(FakeJsonModel):
    def __init__(self):
        self.last_prompt = ""

    def generate_json(self, prompt, system_prompt=None, **kwargs):
        if "FinalAnswerAgent" in system_prompt:
            self.last_prompt = prompt
            return {
                "markdown": (
                    "# Report\n\n"
                    "## Peer Comparison\n\n- 同行对比框架待补，缺少可量化同行指标。\n\n"
                    "## Valuation\n\n- 估值分析待补。\n\n"
                    "## Valuation Sensitivity\n\n- 敏感性分析框架待补。\n\n"
                    "## Conclusion\n\n- 维持观察。\n"
                ),
                "summary": "weak draft",
                "citation_count": 0,
            }
        return super().generate_json(prompt, system_prompt=system_prompt, **kwargs)


def _candidate():
    return {
        "result_id": "ev_fin",
        "title": "Financials",
        "snippet": "Revenue 126.3B, gross margin 46.8%, operating cash flow 38.1B.",
        "url": "https://example.com/fin",
        "score": 2.0,
        "source_type": "financials",
        "raw": {
            "evidence_id": "ev_fin",
            "sample_id": "ev_fin",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "financials",
            "title": "Financials",
            "content": "Revenue 126.3B, gross margin 46.8%, operating cash flow 38.1B.",
            "source_url": "https://example.com/fin",
            "publish_time": "2026-01-31",
            "trust_level": "high",
        },
    }


def test_browser_analyze_final_verify_agents_can_share_one_model():
    model = FakeJsonModel()
    browser = BrowserAgent(model=model)
    analyze = DeepAnalyzeAgent(model=model)
    final = FinalAnswerAgent(model=model)
    verifier = VerifierAgent(model=model)

    browser_result = browser.execute_task(
        AgentTask(
            task_id="task_browser",
            task_type="browser",
            description="Normalize",
            parameters={"evidence_candidates": [_candidate()]},
        )
    )
    assert browser_result.status == AgentStatus.COMPLETED

    records = browser_result.output["evidence_records"]
    analyze_result = analyze.execute_task(
        AgentTask(
            task_id="task_analyze",
            task_type="deep_analyze",
            description="Analyze",
            parameters={"evidence_records": records},
        )
    )
    assert analyze_result.metadata["llm_used"] is True
    assert analyze_result.output["analysis_artifacts"]["financial_metrics"]["metric_count"] >= 1
    assert isinstance(analyze_result.output["analysis_artifacts"]["tables"], list)

    claims = analyze_result.output["claims"]
    final_result = final.execute_task(
        AgentTask(
            task_id="task_final",
            task_type="final_answer",
            description="Write",
            parameters={"research_topic": "AAPL", "claims": claims, "evidence_records": records},
        )
    )
    assert "# Report" in final_result.output["markdown"]

    verify_result = verifier.execute_task(
        AgentTask(
            task_id="task_verify",
            task_type="verifier",
            description="Verify",
            parameters={"claims": claims, "markdown": final_result.output["markdown"], "evidence_records": records},
        )
    )
    assert verify_result.output["verification_report"]["llm_used"] is True


def test_deep_analyze_role_outputs_have_required_schema():
    records = [
        {
            "evidence_id": "ev_official",
            "sample_id": "ev_official",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "sec_filing",
            "title": "10-K",
            "content": "Revenue and risk factors.",
        },
        {
            "evidence_id": "ev_market",
            "sample_id": "ev_market",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "market_api",
            "title": "Market data",
            "content": "Market cap data.",
        },
    ]
    claims = [
        {"section_name": "risks", "claim_text": "Risk factor.", "evidence_ids": ["ev_official"]},
        {"section_name": "valuation", "claim_text": "Valuation input.", "evidence_ids": ["ev_market"]},
        {"section_name": "peer_compare", "claim_text": "Peer context.", "evidence_ids": ["ev_official"]},
    ]

    role_outputs = build_role_outputs(
        records=records,
        claims=claims,
        symbol="AAPL",
        period="2025Q4",
        statement_view={"rows": [{"statement": "income_statement"}, {"statement": "balance_sheet"}, {"statement": "cash_flow"}]},
        peer_context={"peer_count": 2, "peer_symbols": ["MSFT", "GOOGL"]},
        valuation={"valuation_available": True, "method": "rule_multiples"},
        financial_metric_lineage={"metric_count": 3, "metrics": [{"metric_name": "revenue", "value": 126.3, "unit": "USD_billion", "source_evidence_id": "ev_official"}]},
        table_artifacts=[],
    )

    assert set(role_outputs) == {
        "identity_profile",
        "three_statement_analysis",
        "peer_analysis",
        "valuation_analysis",
        "risk_analysis",
    }
    for payload in role_outputs.values():
        assert {"status", "confidence", "source", "evidence_ids", "findings", "missing_inputs", "impact_on_report"} <= set(payload)
        assert isinstance(payload["findings"], list)
    statement_text = "\n".join(role_outputs["three_statement_analysis"]["findings"])
    peer_text = "\n".join(role_outputs["peer_analysis"]["findings"])
    valuation_text = "\n".join(role_outputs["valuation_analysis"]["findings"])
    assert "收入" in statement_text or "revenue" in statement_text
    assert "MSFT" in peer_text
    assert "估值" in valuation_text or "Valuation" in valuation_text


def test_analysis_role_agents_write_only_authorized_blackboard_fields():
    records = [
        {
            "evidence_id": "ev_official",
            "sample_id": "ev_official",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "sec_filing",
            "title": "10-K",
            "content": "Revenue, segment, and risk factors.",
        }
    ]
    claims = [{"section_name": "risks", "claim_text": "Risk factor.", "evidence_ids": ["ev_official"]}]
    artifacts = {
        "statement_view": {"rows": [{"statement": "income_statement"}, {"statement": "balance_sheet"}]},
        "peer_context": {"peer_count": 0},
        "valuation": {"valuation_available": False, "missing_inputs": ["market_cap"]},
        "financial_metrics": {"metric_count": 1, "metrics": [{"metric_name": "revenue"}]},
        "tables": [],
    }

    agents = [
        IdentityAgent(),
        StatementAgent(),
        PeerAgent(),
        ValuationAgent(),
        RiskAgent(),
    ]
    expected_keys = {
        "IdentityAgent": "identity_profile",
        "StatementAgent": "three_statement_analysis",
        "PeerAgent": "peer_analysis",
        "ValuationAgent": "valuation_analysis",
        "RiskAgent": "risk_analysis",
    }
    for agent in agents:
        result = agent.execute_task(
            AgentTask(
                task_id=f"task_{agent.name}",
                task_type=expected_keys[agent.name],
                description="role",
                parameters={"evidence_records": records, "claims": claims, "analysis_artifacts": artifacts, "symbol": "AAPL", "period": "2025Q4"},
            )
        )
        payload = result.output["role_outputs"][expected_keys[agent.name]]
        assert payload["owner_agent"] == agent.name
        assert "verified" in payload
        assert {"status", "confidence", "evidence_ids", "findings", "missing_inputs", "impact_on_report", "owner_agent", "verified"} <= set(payload)

    try:
        validate_role_output_write("PeerAgent", "valuation_analysis")
        assert False, "expected unauthorized write to fail"
    except PermissionError:
        pass


def test_pre_write_critic_routes_objections_to_responsible_agents():
    blackboard = initialize_research_blackboard(symbol="AAPL", period="2025Q4")
    blackboard["coverage"]["three_statement"] = {"income": True, "balance": False, "cash_flow": False}
    blackboard["period_state"]["has_data_delay"] = True
    blackboard["role_outputs"]["peer_analysis"] = {
        "status": "missing",
        "confidence": 0.1,
        "source": "",
        "evidence_ids": [],
        "findings": [],
        "missing_inputs": ["peer_universe"],
        "impact_on_report": "Peer comparison must be disclosed as unavailable.",
        "owner_agent": "PeerAgent",
        "verified": False,
    }

    critic = build_pre_write_critic(blackboard)
    objections = critic["objections"]

    assert any(item["category"] == "three_statement" and item["target_agent"] == "StatementAgent" for item in objections)
    period = next(item for item in objections if item["category"] == "period_consistency")
    assert period["target_agent"] == "StatementAgent"
    assert period["blocking"] is True
    for item in objections:
        assert {"field", "target_agent", "blocking", "required_action"} <= set(item)


def test_local_real_data_search_engine_reads_fixture_data():
    manager = SearchManager.with_local_sources()

    payload = manager.search(
        query="AAPL 2025Q4 revenue cash flow news",
        topk=5,
        engines=["local_real_data"],
        symbol="AAPL",
        period="2025Q4",
    )

    assert payload["hits"]
    assert any(hit["source_type"] == "financials" for hit in payload["hits"])
    assert payload["meta"]["engine_meta"]["local_real_data"]["record_count"] >= 1


def test_prepare_dynamic_tasks_adds_implicit_dependencies():
    plan = {
        "tasks": [
            {"task_id": "task_001", "task_type": "deep_researcher", "description": "Research.", "parameters": {}},
            {"task_id": "task_002", "task_type": "browser", "description": "Browse.", "parameters": {}},
            {"task_id": "task_003", "task_type": "deep_analyze", "description": "Analyze.", "parameters": {}},
            {"task_id": "task_004", "task_type": "final_answer", "description": "Write.", "parameters": {}},
            {"task_id": "task_005", "task_type": "verifier", "description": "Verify.", "parameters": {}},
        ]
    }

    tasks = prepare_dynamic_tasks(
        plan=plan,
        research_topic="AAPL",
        symbol="AAPL",
        period="2025Q4",
        raw_data_root="data/raw/real_data",
    )
    deps = {task.task_id: task.dependencies for task in tasks}

    assert deps["task_002"] == ["task_001"]
    assert deps["task_003"] == ["task_002"]
    assert deps["task_004"] == ["task_003"]
    assert deps["task_005"] == ["task_004"]


def test_multi_agent_orchestrator_runs_dynamic_task_graph(tmp_path):
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=FakeJsonModel(),
    )

    result = orchestrator.run(
        research_topic="Analyze AAPL 2025Q4",
        symbol="AAPL",
        period="2025Q4",
        execution_mode="dynamic",
    )

    summary = json.loads((tmp_path / "outputs" / "run_summary.json").read_text(encoding="utf-8"))
    trace_lines = (tmp_path / "outputs" / "task_trace.jsonl").read_text(encoding="utf-8").splitlines()
    first_trace = json.loads(trace_lines[0])

    assert summary["execution_mode"] == "dynamic"
    assert summary["entity_resolution"]["resolved_symbol"] == "AAPL"
    assert summary["verification_passed"] is True
    assert summary["citation_count"] >= 1
    assert summary["chart_count"] >= 1
    assert summary["mcp_tool_count"] >= 1
    assert summary["skill_registry_enabled"] is True
    assert summary["skill_count"] >= 1
    assert len(trace_lines) >= 7
    assert first_trace["model_usage"]["model_name"] == "fake-json-model"
    assert first_trace["model_usage"]["model_enabled"] is True
    assert result["report_md"].endswith("report.md")
    assert result["task_route_context"].endswith("task_route_context.json")
    assert result["citations"].endswith("citations.json")
    assert result["charts"].endswith("charts.json")
    assert result["financial_metrics"].endswith("financial_metrics.json")
    assert result["tables"].endswith("tables.json")
    assert result["valuation_model"].endswith("valuation_model.json")
    assert result["valuation_sensitivity"].endswith("valuation_sensitivity.json")
    assert result["company_report_scorecard"].endswith("company_report_scorecard.json")
    assert result["agent_collaboration_trace"].endswith("agent_collaboration_trace.json")
    assert result["tool_trace"].endswith("tool_trace.json")
    assert result["research_blackboard"].endswith("research_blackboard.json")
    assert result["data_repair_summary"].endswith("data_repair_summary.json")
    assert result["mcp_manifest"].endswith("mcp_manifest.json")
    assert result["conversation_context"].endswith("conversation_context.json")
    assert (tmp_path / "outputs" / "citations.json").exists()
    assert (tmp_path / "outputs" / "charts.json").exists()
    assert (tmp_path / "outputs" / "financial_metrics.json").exists()
    assert (tmp_path / "outputs" / "tables.json").exists()
    assert (tmp_path / "outputs" / "valuation_model.json").exists()
    assert (tmp_path / "outputs" / "valuation_assumptions.json").exists()
    assert (tmp_path / "outputs" / "valuation_sensitivity.json").exists()
    assert (tmp_path / "outputs" / "company_report_scorecard.json").exists()
    assert (tmp_path / "outputs" / "agent_collaboration_trace.json").exists()
    assert (tmp_path / "outputs" / "tool_trace.json").exists()
    assert (tmp_path / "outputs" / "research_blackboard.json").exists()
    assert (tmp_path / "outputs" / "data_repair_summary.json").exists()
    assert (tmp_path / "outputs" / "conversation_context.json").exists()
    assert (tmp_path / "outputs" / "mcp_manifest.json").exists()
    route_context = json.loads((tmp_path / "outputs" / "task_route_context.json").read_text(encoding="utf-8"))
    assert any("financial_statement_analysis" in item["selected_skills"] for item in route_context["tasks"])
    assert "## 参考来源" in (tmp_path / "reports" / "report.md").read_text(encoding="utf-8")
    assert "## 图表" in (tmp_path / "reports" / "report.md").read_text(encoding="utf-8")
    financial_metrics = json.loads((tmp_path / "outputs" / "financial_metrics.json").read_text(encoding="utf-8"))
    assert financial_metrics["metric_count"] >= 1
    valuation_model = json.loads((tmp_path / "outputs" / "valuation_model.json").read_text(encoding="utf-8"))
    assert "dcf_model" not in valuation_model
    scorecard = json.loads((tmp_path / "outputs" / "company_report_scorecard.json").read_text(encoding="utf-8"))
    collaboration = json.loads((tmp_path / "outputs" / "agent_collaboration_trace.json").read_text(encoding="utf-8"))
    blackboard = json.loads((tmp_path / "outputs" / "research_blackboard.json").read_text(encoding="utf-8"))
    tool_trace = json.loads((tmp_path / "outputs" / "tool_trace.json").read_text(encoding="utf-8"))
    repair_summary = json.loads((tmp_path / "outputs" / "data_repair_summary.json").read_text(encoding="utf-8"))
    assert scorecard["scores"]["numeric_lineage_score"] > 0
    assert "valuation_reproducibility_score" in scorecard["scores"]
    assert summary["company_report_overall_score"] == scorecard["overall_score"]
    assert summary["durable_memory_enabled"] is False
    assert not result["durable_memory"]
    assert collaboration["schema_version"] == "agent_collaboration_trace.v1"
    assert collaboration["step_count"] == len(trace_lines)
    assert not any(item["agent"] == "CriticAgent" for item in collaboration["agents"])
    assert blackboard["schema_version"] == "research_blackboard.v1"
    assert blackboard["critic"]["pre_write_passed"] is False
    assert blackboard["company_identity"]["canonical_symbol"] == "AAPL"
    assert set(blackboard["role_outputs"]) == {
        "identity_profile",
        "three_statement_analysis",
        "peer_analysis",
        "valuation_analysis",
        "risk_analysis",
    }
    assert collaboration["research_blackboard"]["role_outputs"]["three_statement_analysis"]["status"] in {"complete", "partial"}
    assert "role_outputs" in next(item for item in collaboration["agents"] if item["agent"] == "DeepAnalyzeAgent")["blackboard_writes"]
    assert any(item["handoff_to"] for item in collaboration["agents"])
    assert collaboration["memory"]["fact_boundary"].startswith("Memory is routing")
    assert tool_trace["schema_version"] == "tool_trace.v1"
    assert tool_trace["tool_call_count"] >= 1
    assert any(call["tool_name"] == "build_three_statement_view" for call in tool_trace["calls"])
    assert "gap_count" in repair_summary


def test_multi_agent_orchestrator_runs_compact_collaborative_by_default(tmp_path):
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=FakeJsonModel(),
    )

    result = orchestrator.run(
        research_topic="Analyze AAPL latest",
        symbol="AAPL",
        period="2025Q4",
        execution_mode="collaborative",
    )

    summary = json.loads((tmp_path / "outputs" / "run_summary.json").read_text(encoding="utf-8"))
    collaboration = json.loads((tmp_path / "outputs" / "agent_collaboration_trace.json").read_text(encoding="utf-8"))
    blackboard = json.loads((tmp_path / "outputs" / "research_blackboard.json").read_text(encoding="utf-8"))
    agent_names = [item["agent"] for item in collaboration["agents"]]

    assert summary["execution_mode"] == "collaborative"
    assert result["research_blackboard"].endswith("research_blackboard.json")
    for agent_name in ["IdentityAgent", "StatementAgent", "PeerAgent", "ValuationAgent", "RiskAgent", "CriticAgent"]:
        assert agent_name not in agent_names
    assert len(agent_names) <= 8
    assert set(blackboard["role_outputs"]) == {
        "identity_profile",
        "three_statement_analysis",
        "peer_analysis",
        "valuation_analysis",
        "risk_analysis",
    }
    for payload in blackboard["role_outputs"].values():
        assert payload["owner_agent"] == "DeepAnalyzeAgent"
        assert "status" in payload


def test_multi_agent_orchestrator_diagnostic_full_runs_role_agents(tmp_path):
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=FakeJsonModel(),
    )

    orchestrator.run(
        research_topic="Analyze AAPL latest",
        symbol="AAPL",
        period="2025Q4",
        execution_mode="diagnostic_full",
    )

    summary = json.loads((tmp_path / "outputs" / "run_summary.json").read_text(encoding="utf-8"))
    collaboration = json.loads((tmp_path / "outputs" / "agent_collaboration_trace.json").read_text(encoding="utf-8"))
    blackboard = json.loads((tmp_path / "outputs" / "research_blackboard.json").read_text(encoding="utf-8"))
    agent_names = [item["agent"] for item in collaboration["agents"]]

    assert summary["execution_mode"] == "diagnostic_full"
    for agent_name in ["IdentityAgent", "StatementAgent", "PeerAgent", "ValuationAgent", "RiskAgent", "CriticAgent"]:
        assert agent_name in agent_names
    for key, owner in {
        "identity_profile": "IdentityAgent",
        "three_statement_analysis": "StatementAgent",
        "peer_analysis": "PeerAgent",
        "valuation_analysis": "ValuationAgent",
        "risk_analysis": "RiskAgent",
    }.items():
        assert blackboard["role_outputs"][key]["owner_agent"] == owner


def test_multi_agent_orchestrator_can_persist_durable_memory_without_quality_regression(tmp_path):
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=FakeJsonModel(),
        memory_enabled=True,
        memory_root=str(tmp_path / "memory"),
    )

    result = orchestrator.run(
        research_topic="Analyze AAPL 2025Q4",
        symbol="AAPL",
        period="2025Q4",
        execution_mode="dynamic",
    )

    summary = json.loads((tmp_path / "outputs" / "run_summary.json").read_text(encoding="utf-8"))
    trace = [
        json.loads(line)
        for line in (tmp_path / "outputs" / "task_trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert summary["verification_passed"] is True
    assert summary["citation_count"] >= 1
    assert summary["durable_memory_enabled"] is True
    assert summary["durable_memory_context_scope"] == "planner_router"
    assert summary["durable_memory"]["working_snapshot"] == result["durable_memory"]
    assert (tmp_path / "memory" / "domain" / "AAPL.json").exists()
    assert "DurableMemory" in next(item for item in trace if item["agent"] == "PlanningAgent")["task"]["parameters"]["conversation_brief"]
    assert "DurableMemory" not in next(item for item in trace if item["agent"] == "FinalAnswerAgent")["task"]["parameters"]["conversation_brief"]
    assert next(item for item in trace if item["agent"] == "DeepAnalyzeAgent")["task"]["metadata"]["selected_skills"]


def test_multi_agent_orchestrator_fast_mode_uses_smaller_context(tmp_path):
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=FakeJsonModel(),
    )

    orchestrator.run(
        research_topic="Analyze AAPL 2025Q4",
        symbol="AAPL",
        period="2025Q4",
        execution_mode="dynamic",
        fast=True,
    )

    summary = json.loads((tmp_path / "outputs" / "run_summary.json").read_text(encoding="utf-8"))
    trace = [
        json.loads(line)
        for line in (tmp_path / "outputs" / "task_trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    research_task = next(item["task"] for item in trace if item["agent"] == "DeepResearcherAgent")
    browser_trace = next(item for item in trace if item["agent"] == "BrowserAgent")
    final_trace = next(item for item in trace if item["agent"] == "FinalAnswerAgent")

    assert summary["performance_profile"] == "fast"
    assert summary["conversation_brief_chars"] > 0
    assert research_task["parameters"]["topk"] == 6
    assert "ConversationMemory" in final_trace["task"]["parameters"]["conversation_brief"]
    assert browser_trace["metadata"]["llm_skipped"] is True


def test_multi_agent_orchestrator_auto_reworks_failed_report(tmp_path):
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        model=RevisionFakeModel(),
    )

    orchestrator.run(
        research_topic="Analyze AAPL 2025Q4",
        symbol="AAPL",
        period="2025Q4",
        execution_mode="dynamic",
    )

    summary = json.loads((tmp_path / "outputs" / "run_summary.json").read_text(encoding="utf-8"))
    revision_history = json.loads((tmp_path / "outputs" / "revision_history.json").read_text(encoding="utf-8"))
    trace = [
        json.loads(line)
        for line in (tmp_path / "outputs" / "task_trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert summary["verification_passed"] is True
    assert summary["revision_rounds"] == 1
    assert len(revision_history) == 1
    assert revision_history[0]["passed_after_round"] is True
    gap_trace = [
        json.loads(line)
        for line in (tmp_path / "outputs" / "gap_resolution_trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert gap_trace
    assert gap_trace[0]["route"] in {"research_browser", "deep_analyze", "final_answer"}
    assert json.loads((tmp_path / "outputs" / "conversation_context.json").read_text(encoding="utf-8"))["verifier_feedback"]
    assert sum(1 for item in trace if item["agent"] == "FinalAnswerAgent") == 2
    assert sum(1 for item in trace if item["agent"] == "VerifierAgent") == 2


def test_final_answer_heading_normalization_demotes_section_h1():
    markdown = "# 执行摘要\n\nText\n\n#### Financial Analysis\n\nText\n\n# 风险评估\n\nText"

    normalized = normalize_report_headings(markdown)

    assert "## 执行摘要" in normalized
    assert "## 财务分析" in normalized
    assert "## 风险评估" in normalized


def test_final_answer_inserts_missing_claim_sections():
    markdown = "# Report\n\n## Executive Summary\n\nText\n"
    claims = [
        {
            "claim_id": "cl_fin_stmt",
            "section_name": "financial_statements",
            "claim_text": "Revenue was 43.7B.",
            "evidence_ids": ["ev_fin"],
            "confidence": 0.8,
        },
        {
            "claim_id": "cl_sens",
            "section_name": "valuation_sensitivity",
            "claim_text": "Sensitivity analysis was generated.",
            "evidence_ids": ["ev_val"],
            "confidence": 0.7,
        },
    ]

    output = insert_missing_sections_from_claims(markdown, claims)

    assert "Revenue was 43.7B." in output
    assert "Sensitivity analysis was generated." in output
    assert "ev_fin" in output
    assert "ev_val" in output


def test_final_answer_hard_backfills_quality_failed_sections():
    model = QualityRemediationFakeModel()
    final = FinalAnswerAgent(model=model)
    claims = [
        {
            "claim_id": "cl_peer",
            "section_name": "peer_compare",
            "claim_text": "AMD 同行对比应落到 NVIDIA、Intel、Broadcom 三组竞争关系，并说明 AI 加速、CPU 和数据中心平台差异。[ev_peer]",
            "evidence_ids": ["ev_peer"],
            "confidence": 0.82,
        },
        {
            "claim_id": "cl_val",
            "section_name": "valuation",
            "claim_text": "AMD 估值观察显示 P/E、P/B、P/S 需要同时受市值、净利润、权益和收入约束，缺口会限制目标价判断。[ev_val]",
            "evidence_ids": ["ev_val"],
            "confidence": 0.8,
        },
        {
            "claim_id": "cl_sens",
            "section_name": "valuation_sensitivity",
            "claim_text": "AMD 敏感性分析应重点跟踪数据中心收入增速、毛利率和研发费用率，变量上行有利于利润弹性。[ev_sens]",
            "evidence_ids": ["ev_sens"],
            "confidence": 0.78,
        },
        {
            "claim_id": "cl_conclusion",
            "section_name": "conclusion",
            "claim_text": "基于增长驱动、竞争压力和估值约束，AMD 维持中性/审慎观察结论，理由是上行弹性仍需现金流和分部收入证据确认。[ev_conclusion]",
            "evidence_ids": ["ev_conclusion"],
            "confidence": 0.8,
        },
    ]
    plan = {
        "quality_feedback_used": True,
        "failed_sections": ["peer_comparison", "valuation", "sensitivity", "investment_conclusion"],
        "required_fixes": ["补充同行对比表和可读结论，避免只输出框架。", "投资结论必须包含方向、理由、关键证据和风险约束。"],
        "forbidden_patterns": ["暂无可验证结论", "框架性结论"],
        "planner_constraints": ["所有事实和数值仍必须绑定 evidence_id/citation，并通过 verifier。"],
    }

    result = final.execute_task(
        AgentTask(
            task_id="task_final",
            task_type="final_answer",
            description="Write",
            parameters={
                "research_topic": "AMD company report",
                "claims": claims,
                "evidence_records": [{"evidence_id": "ev_peer", "title": "SEC filing"}],
                "quality_remediation_plan": plan,
            },
        )
    )

    markdown = result.output["markdown"]
    assert result.metadata["quality_remediation_used"] is True
    assert "Quality remediation constraints" in model.last_prompt
    assert "同行对比框架待补" not in markdown
    assert "估值分析待补" not in markdown
    assert "敏感性分析框架待补" not in markdown
    assert "NVIDIA、Intel、Broadcom" in markdown
    assert "P/E、P/B、P/S" in markdown
    assert "增长驱动、竞争压力和估值约束" in markdown


def test_hard_backfill_quality_sections_replaces_framework_body():
    markdown = """# Report

## 同行对比

- 同行对比框架待补，缺少可量化同行指标。

## 投资结论

- 维持观察。
"""
    claims = [
        {
            "section_name": "peer_compare",
            "claim_text": "同行对比结论：相对 NVIDIA 关注 AI 加速，相对 Intel 关注 CPU 竞争。[ev_peer]",
            "evidence_ids": ["ev_peer"],
        },
        {
            "section_name": "conclusion",
            "claim_text": "基于估值约束和竞争风险，维持中性观察。[ev_conclusion]",
            "evidence_ids": ["ev_conclusion"],
        },
    ]

    updated = hard_backfill_quality_sections(
        markdown,
        claims,
        {"quality_feedback_used": True, "failed_sections": ["peer_comparison", "investment_conclusion"]},
    )

    assert "同行对比框架待补" not in updated
    assert "相对 NVIDIA" in updated
    assert "基于估值约束和竞争风险" in updated


def test_hard_backfill_quality_sections_writes_gap_note_when_claim_missing():
    markdown = "# Report\n\n## 风险评估\n\n暂无结论。\n"

    updated = hard_backfill_quality_sections(
        markdown,
        claims=[],
        quality_remediation_plan={
            "quality_feedback_used": True,
            "failed_sections": ["risk", "investment_conclusion"],
            "required_fixes": ["风险和投资结论必须说明缺口及影响。"],
        },
    )

    assert "## 风险评估" in updated
    assert "## 投资结论" in updated
    assert "数据缺口说明" in updated
    assert "不虚构数值、来源或投资评级" in updated


def test_hard_backfill_quality_sections_replaces_english_hollow_placeholder():
    title = _section_title("valuation")
    markdown = f"""# Report

## {title}

- Framework-only placeholder: to be filled after valuation inputs arrive.
"""
    claims = [
        {
            "section_name": "valuation",
            "claim_text": "Valuation guardrail blocks target-price output until revenue, cash flow, and market inputs pass scale checks.",
            "evidence_ids": ["ev_val"],
        }
    ]

    updated = hard_backfill_quality_sections(markdown, claims)

    assert "Framework-only placeholder" not in updated
    assert "Valuation guardrail blocks target-price output" in updated
    assert "ev_val" in updated


def test_final_answer_filters_diagnostic_and_unlineaged_valuation_claims():
    claims = [
        {
            "section_name": "business_overview",
            "claim_text": "TSLA evidence coverage includes 8 records.",
            "numeric_values": {"evidence_count": 8, "unique_sources": 3},
            "evidence_ids": ["ev_coverage"],
        },
        {
            "section_name": "valuation",
            "claim_text": "Rule valuation model gives a blended equity value.",
            "numeric_values": {"blended_equity_value_billion": 900.0},
            "evidence_ids": ["ev_yahoo"],
        },
        {
            "section_name": "risk_factors",
            "claim_text": "TSLA risk factors include demand and margin pressure.",
            "numeric_values": {},
            "evidence_ids": ["ev_risk"],
        },
    ]

    filtered = _filter_reportable_claims(claims, {"metric_count": 0, "metrics": []})

    assert [item["section_name"] for item in filtered] == ["risk_factors"]


def test_final_answer_overwrites_financial_sections_with_verified_lineage():
    draft = """# Report

## Financial Statements

Operating cash flow was 2,156, investing cash flow was 664, and financing cash flow was -1,492.

## Financial Analysis

The old draft repeats stale cash-flow numbers.
"""
    tables = [
        {
            "table_id": "tbl_cash",
            "table_type": "cash_flow_statement",
            "rows": [
                {"statement": "cash_flow_statement", "line_item": "operating_cash_flow", "value": 937, "unit": "USD_million", "period": "2026Q1", "evidence_id": "ev_cash"},
                {"statement": "cash_flow_statement", "line_item": "investing_cash_flow", "value": 1444, "unit": "USD_million", "period": "2026Q1", "evidence_id": "ev_cash"},
                {"statement": "cash_flow_statement", "line_item": "financing_cash_flow", "value": -2493, "unit": "USD_million", "period": "2026Q1", "evidence_id": "ev_cash"},
            ],
        },
        {
            "table_id": "tbl_income",
            "table_type": "income_statement",
            "rows": [
                {"statement": "income_statement", "line_item": "revenue", "value": 19335, "unit": "USD_million", "period": "2026Q1", "evidence_id": "ev_income"},
                {"statement": "income_statement", "line_item": "net_income", "value": 409, "unit": "USD_million", "period": "2026Q1", "evidence_id": "ev_income"},
            ],
        },
        {
            "table_id": "tbl_balance",
            "table_type": "balance_sheet",
            "rows": [
                {"statement": "balance_sheet", "line_item": "total_assets", "value": 122070, "unit": "USD_million", "period": "2026Q1", "evidence_id": "ev_balance"},
            ],
        },
    ]

    updated = enforce_verified_financial_sections(normalize_report_headings(draft), claims=[], financial_metrics={}, tables=tables)

    assert "2,156" not in updated
    assert "664" not in updated
    assert "-1,492" not in updated
    assert "937 USD_million" in updated
    assert "1,444 USD_million" in updated
    assert "-2,493 USD_million" in updated
    assert "income statement" in updated
    assert "balance sheet" in updated
    assert "cash flow statement" in updated
    assert "[ev_cash]" in updated


def test_final_answer_discloses_three_statement_gap_without_verified_rows():
    draft = normalize_report_headings("# Report\n\n## Financial Statements\n\nPlaceholder.\n")
    claims = [{"claim_id": "cl_gap", "section_name": "risks", "claim_text": "Evidence limited.", "evidence_ids": ["ev_frozen"]}]

    updated = enforce_verified_financial_sections(draft, claims=claims, financial_metrics={}, tables=[])

    assert "三表缺口说明" in updated
    assert "利润表" in updated
    assert "资产负债表" in updated
    assert "现金流量表" in updated
    assert "[ev_frozen]" in updated


def test_final_answer_backfills_thin_role_sections_from_role_findings():
    markdown = normalize_report_headings("# Report\n\n## Peer Comparison\n\nFramework only.\n")
    blackboard = {
        "role_outputs": {
            "peer_analysis": {
                "status": "complete",
                "findings": ["可比公司口径包括 MSFT, GOOGL，同行结论按同一行业口径解释。"],
                "evidence_ids": ["ev_peer"],
                "missing_inputs": [],
                "impact_on_report": "Peer comparison can summarize relative position with cited limits.",
            }
        }
    }

    updated = backfill_role_output_sections(markdown, blackboard)

    assert "MSFT, GOOGL" in updated
    assert "[ev_peer]" in updated


def test_final_answer_replaces_gap_sections_with_identity_and_peer_blackboard():
    business_title = _section_title("business_overview")
    peer_title = _section_title("peer_compare")
    markdown = f"""# Report

## {business_title}

- 数据缺口说明：Use only free public sources; memory is not evidence.

## {peer_title}

- 数据缺口说明：Use only free public sources; memory is not evidence.
"""
    blackboard = {
        "company_identity": {
            "company_name": "Apple Inc.",
            "canonical_symbol": "AAPL",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "business_summary": "Designs and sells consumer devices, software, and services.",
        },
        "role_outputs": {
            "identity_profile": {
                "status": "complete",
                "findings": ["Resolved analysis target as AAPL."],
                "evidence_ids": ["ev_sec"],
            },
            "peer_analysis": {
                "status": "complete",
                "findings": ["可比公司口径包括 MSFT, GOOGL，同行结论按同一行业口径解释。"],
                "evidence_ids": ["ev_peer"],
                "missing_inputs": [],
                "impact_on_report": "Peer comparison can summarize relative position with cited limits.",
            },
        },
    }

    updated = backfill_role_output_sections(markdown, blackboard)

    assert "Use only free public sources" not in updated
    assert "Apple Inc." in updated
    assert "Consumer Electronics" in updated
    assert "MSFT, GOOGL" in updated
    assert "[ev_sec]" in updated
    assert "[ev_peer]" in updated


def test_ensure_period_disclosure_adds_latest_available_data_note():
    markdown = "# Report\n\n## 执行摘要\n\n正文。"

    updated = ensure_period_disclosure(
        markdown,
        "2026Q1",
        evidence_records=[{"period": "2025Q4", "evidence_id": "ev1"}],
    )

    assert "## 数据期间说明" in updated
    assert "目标报告期：2026Q1" in updated
    assert "最新可得披露数据期：2025Q4" in updated
    assert "存在数据期与目标期不一致" in updated


def test_claim_backfill_hides_debug_metadata_from_markdown():
    markdown = _claims_to_markdown_bullets(
        [
            {
                "section_name": "peer_compare",
                "claim_text": "同行对比框架待补，缺少可量化同行指标。",
                "evidence_ids": ["ev_peer"],
                "confidence": 0.32,
            }
        ],
        section="peer_compare",
    )

    assert "证据ID" not in markdown
    assert "置信度" not in markdown
    assert "暂无" not in markdown
    assert "框架" not in markdown
    assert "不可用" not in markdown
    assert "[ev_peer]" in markdown
    assert "数据缺口说明" in markdown


def test_final_answer_consumes_gap_repair_constraints():
    model = QualityRemediationFakeModel()
    final = FinalAnswerAgent(model=model)
    result = final.execute_task(
        AgentTask(
            task_id="task_final",
            task_type="final_answer",
            description="Write",
            parameters={
                "research_topic": "generic company report",
                "claims": [
                    {
                        "claim_id": "cl_val",
                        "section_name": "valuation",
                        "claim_text": "Valuation unavailable because market cap and net income are missing.",
                        "evidence_ids": ["ev1"],
                    }
                ],
                "evidence_records": [{"evidence_id": "ev1", "title": "public source"}],
                "repair_constraints": {
                    "required_backfill_sections": ["valuation"],
                    "must_explain_unresolved_gaps": ["valuation", "cash_flow"],
                    "free_public_source_boundary": "Use only free public sources.",
                },
            },
        )
    )

    assert result.metadata["repair_constraints_used"] is True
    assert "GapResolver repair constraints" in model.last_prompt
    assert "valuation" in model.last_prompt

def test_browser_reader_enriches_web_search_record(monkeypatch, tmp_path):
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
search:
  jina_reader:
    base_url: https://r.jina.ai
    timeout: 2
    max_chars: 50
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"Title: Apple report\\nRevenue and cash flow details from the page."

    monkeypatch.setattr("src.agents.browser_agent.request.urlopen", lambda req, timeout: FakeResponse())
    records, meta = enrich_records_with_reader(
        records=[
            {
                "evidence_id": "web_1",
                "source_type": "web_search",
                "source_url": "https://example.com/aapl",
                "content": "short snippet",
                "metadata": {},
            }
        ],
        max_records=1,
        max_chars=50,
        config_path=str(config_path),
    )

    assert meta["succeeded"] == 1
    assert "Revenue and cash flow" in records[0]["content"]
    assert records[0]["metadata"]["reader"]["engine"] == "jina_reader"


def test_browser_reader_falls_back_when_playwright_fails(monkeypatch):
    def fake_playwright(url, max_chars=4000, config_path="configs/data_sources.yaml"):
        raise RuntimeError("no chromium")

    def fake_jina(url, max_chars=4000, config_path="configs/data_sources.yaml"):
        return {"reader_url": "https://r.jina.ai/http://example.com", "content": "fallback content", "engine": "jina_reader"}

    monkeypatch.setattr("src.agents.browser_agent.read_url_with_playwright", fake_playwright)
    monkeypatch.setattr("src.agents.browser_agent.read_url_with_jina", fake_jina)

    payload = read_url_content("http://example.com", prefer_playwright=True)

    assert payload["engine"] == "jina_reader_after_playwright_error"
    assert payload["content"] == "fallback content"


def test_rule_verifier_checks_evidence_citations_numbers_and_charts(tmp_path):
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(b"png")
    verifier = Verifier()
    claims = [
        ClaimItem(
            claim_id="cl_1",
            section_name="financial_analysis",
            claim_text="AAPL revenue was 126.3B.",
            evidence_ids=["ev_fin"],
            numeric_values={"revenue_billion": 126.3},
            confidence=0.82,
        )
    ]
    report = verifier.verify(
        claims=claims,
        markdown="# Report\n\n## Executive Summary\n\n## Financial Analysis\n\nAAPL revenue [ev_fin]\n\n## Risk Assessment\n\n关键指标\n",
        evidence_records=[
            {
                "evidence_id": "ev_fin",
                "content": "Revenue 126.3B, gross margin 46.8%.",
                "metadata": {"revenue_billion": 126.3},
            }
        ],
        charts=[
            {
                "chart_id": "metrics",
                "chart_type": "bar",
                "title": "关键指标",
                "source_fields": "claims.numeric_values",
                "input_table_ids": ["tbl_fin"],
                "input_claim_ids": ["cl_1"],
                "source_evidence_ids": ["ev_fin"],
                "output_path": str(chart_path),
            }
        ],
        tables=[{"table_id": "tbl_fin", "source_evidence_id": "ev_fin"}],
    )

    assert report["passed"] is True
    assert report["error_count"] == 0


def test_deep_analyze_generates_company_depth_sections():
    records = [
        {
            "evidence_id": "ev_profile",
            "sample_id": "ev_profile",
            "symbol": "NVDA",
            "period": "2025Q4",
            "source_type": "company_profile",
            "title": "NVDA company profile",
            "content": "Designs accelerated computing hardware and software platforms.",
            "source_url": "https://example.com/nvda/profile",
            "publish_time": "2026-01-31",
            "trust_level": "high",
            "metadata": {
                "symbol": "NVDA",
                "company_name": "NVIDIA Corporation",
                "sector": "Technology",
                "industry": "Semiconductors",
                "description": "Designs accelerated computing hardware and software platforms.",
            },
        },
        {
            "evidence_id": "ev_fin",
            "sample_id": "ev_fin",
            "symbol": "NVDA",
            "period": "2025Q4",
            "source_type": "financials",
            "title": "NVDA financials",
            "content": "Revenue 41.8B, gross margin 74.1%, net margin 52.4%, operating cash flow 19.8B, free cash flow 17.3B.",
            "source_url": "https://example.com/nvda/financials",
            "publish_time": "2026-01-31",
            "trust_level": "high",
            "metadata": {
                "symbol": "NVDA",
                "period": "2025Q4",
                "revenue_billion": 41.8,
                "revenue_growth_pct": 38.6,
                "gross_margin_pct": 74.1,
                "net_margin_pct": 52.4,
                "roe_pct": 96.2,
                "roa_pct": 44.1,
                "operating_cash_flow_billion": 19.8,
                "free_cash_flow_billion": 17.3,
            },
        },
    ]
    agent = DeepAnalyzeAgent()

    result = agent.execute_task(
        AgentTask(
            task_id="task_analyze_depth",
            task_type="deep_analyze",
            description="Analyze depth",
            parameters={"evidence_records": records, "symbol": "NVDA", "period": "2025Q4"},
        )
    )

    sections = {claim["section_name"] for claim in result.output["claims"]}
    assert "ownership_governance" in sections
    assert "strategy_business" in sections
    assert "valuation" in sections


def test_compact_records_tolerates_unstructured_items():
    compacted = compact_records(
        [
            {"evidence_id": "ev1", "content": "structured"},
            "raw text evidence",
            None,
        ],
        content_limit=20,
    )

    assert len(compacted) == 2
    assert compacted[1]["source_type"] == "unstructured"
    assert compacted[1]["content"] == "raw text evidence"


def test_prepare_dynamic_tasks_orders_evidence_flow_even_when_planner_outputs_tasks_out_of_order():
    plan = {
        "tasks": [
            {
                "task_id": "task_browser",
                "task_type": "browser",
                "description": "Normalize evidence.",
                "dependencies": [],
            },
            {
                "task_id": "task_analyze",
                "task_type": "deep_analyze",
                "description": "Analyze evidence.",
                "dependencies": ["task_browser"],
            },
            {
                "task_id": "task_research",
                "task_type": "deep_researcher",
                "description": "Research evidence.",
                "dependencies": [],
            },
        ]
    }

    tasks = prepare_dynamic_tasks(
        plan=plan,
        research_topic="总结AAPL 2025Q4",
        symbol="AAPL",
        period="2025Q4",
        raw_data_root="data/raw/real_data",
        search_engines=["local_real_data"],
    )
    by_id = {task.task_id: task for task in tasks}

    assert "task_research" in by_id["task_browser"].dependencies
    assert "task_browser" in by_id["task_analyze"].dependencies


def test_prepare_dynamic_tasks_drops_reverse_dependencies_that_would_cycle_graph():
    plan = {
        "tasks": [
            {
                "task_id": "task_browser",
                "task_type": "browser",
                "description": "Normalize evidence.",
                "dependencies": ["task_analyze"],
            },
            {
                "task_id": "task_analyze",
                "task_type": "deep_analyze",
                "description": "Analyze evidence.",
                "dependencies": ["task_browser"],
            },
            {
                "task_id": "task_research",
                "task_type": "deep_researcher",
                "description": "Research evidence.",
                "dependencies": [],
            },
        ]
    }

    tasks = prepare_dynamic_tasks(
        plan=plan,
        research_topic="总结AAPL 2025Q4",
        symbol="AAPL",
        period="2025Q4",
        raw_data_root="data/raw/real_data",
        search_engines=["local_real_data"],
    )
    by_id = {task.task_id: task for task in tasks}

    assert "task_analyze" not in by_id["task_browser"].dependencies
    assert "task_research" in by_id["task_browser"].dependencies
    assert "task_browser" in by_id["task_analyze"].dependencies


def test_enrich_task_parameters_replaces_model_placeholder_artifact_names():
    task = AgentTask(
        task_id="task_analyze",
        task_type="deep_analyze",
        description="Analyze evidence",
        parameters={"evidence_records": "evidence_records.json"},
    )

    enriched = enrich_task_parameters(
        task=task,
        state={
            "symbol": "AAPL",
            "period": "2025Q4",
            "evidence_records": [{"evidence_id": "ev_1", "content": "Revenue evidence."}],
            "retrieval_ranking_mode": "hybrid_rerank",
        },
        raw_data_root="data/raw/real_data",
    )

    assert enriched.parameters["evidence_records"] == [{"evidence_id": "ev_1", "content": "Revenue evidence."}]


def test_rule_verifier_fails_missing_evidence_id():
    verifier = Verifier()
    claims = [
        ClaimItem(
            claim_id="cl_1",
            section_name="financial_analysis",
            claim_text="AAPL revenue was 126.3B.",
            evidence_ids=["missing_ev"],
            numeric_values={"revenue_billion": 126.3},
            confidence=0.82,
        )
    ]

    report = verifier.verify(
        claims=claims,
        markdown="# Report\n\n## 执行摘要\n\n## 财务分析\n\nAAPL revenue.\n\n## 风险评估\n",
        evidence_records=[],
        charts=[],
    )

    assert report["passed"] is False
    assert any("missing evidence ids" in error for error in report["errors"])


def test_rule_verifier_fails_target_symbol_mismatch():
    verifier = Verifier()
    claims = [
        ClaimItem(
            claim_id="cl_1",
            section_name="financial_analysis",
            claim_text="NADA revenue was 126.3B.",
            evidence_ids=["ev_fin"],
            numeric_values={"revenue_billion": 126.3},
            confidence=0.82,
        )
    ]

    report = verifier.verify(
        claims=claims,
        markdown="# Report\n\n## 执行摘要\n\n## 财务分析\n\nNADA revenue [ev_fin]\n\n## 风险评估\n",
        evidence_records=[
            {
                "evidence_id": "ev_fin",
                "symbol": "NADA",
                "content": "Revenue 126.3B.",
                "metadata": {"symbol": "NADA", "revenue_billion": 126.3},
            }
        ],
        charts=[],
        expected_symbol="NVDA",
    )

    assert report["passed"] is False
    assert any("Target symbol mismatch" in error for error in report["errors"])


def test_final_answer_agent_reports_context_pack_meta():
    final = FinalAnswerAgent()
    claims = [
        {
            "claim_id": f"cl_{idx}",
            "section_name": "financial_analysis",
            "claim_text": f"AAPL revenue claim {idx}.",
            "evidence_ids": [f"ev_{idx}"],
            "numeric_values": {"revenue_billion": float(idx)},
            "confidence": 0.9 - idx * 0.1,
        }
        for idx in range(3)
    ]

    result = final.execute_task(
        AgentTask(
            task_id="task_final_context",
            task_type="final_answer",
            description="Write",
            parameters={
                "research_topic": "AAPL",
                "claims": claims,
                "evidence_records": [{"evidence_id": f"ev_{idx}", "content": "Revenue evidence."} for idx in range(3)],
                "max_claims": 1,
                "max_evidence": 1,
            },
        )
    )

    assert result.metadata["claim_pack_meta"]["dropped_count"] == 2
    assert result.metadata["evidence_pack_meta"]["dropped_count"] == 2
    assert result.metadata["claim_pack_meta"]["packed_ids"] == ["cl_0"]


def test_verifier_agent_reports_context_pack_meta():
    verifier = VerifierAgent()
    claims = [
        ClaimItem(
            claim_id=f"cl_{idx}",
            section_name="financial_analysis",
            claim_text=f"AAPL revenue was {idx}.",
            evidence_ids=[f"ev_{idx}"],
            numeric_values={},
            confidence=0.8,
        )
        for idx in range(3)
    ]
    markdown = "# Report\n\n## 执行摘要\n\n## 财务分析\n\n" + " ".join(f"[ev_{idx}]" for idx in range(3)) + "\n\n## 风险评估\n"

    result = verifier.execute_task(
        AgentTask(
            task_id="task_verify_context",
            task_type="verifier",
            description="Verify",
            parameters={
                "claims": [claim.to_dict() for claim in claims],
                "markdown": markdown,
                "evidence_records": [{"evidence_id": f"ev_{idx}", "symbol": "AAPL", "content": "Revenue evidence."} for idx in range(3)],
                "expected_symbol": "AAPL",
            },
        )
    )

    report = result.output["verification_report"]
    assert report["context_pack_meta"]["claims"]["packed_count"] == 3
    assert report["context_pack_meta"]["evidence"]["packed_ids"] == ["ev_0", "ev_1", "ev_2"]


def test_verifier_agent_emits_structured_evidence_gaps():
    verifier = VerifierAgent()
    claim = ClaimItem(
        claim_id="cl_missing_primary",
        section_name="financial_analysis",
        claim_text="AAPL revenue was 126.3B.",
        evidence_ids=["ev_news"],
        numeric_values={"revenue_billion": 126.3},
        confidence=0.82,
    )

    result = verifier.execute_task(
        AgentTask(
            task_id="task_verify_gap",
            task_type="verifier",
            description="Verify gaps",
            parameters={
                "claims": [claim.to_dict()],
                "markdown": "# Report\n\n## Executive Summary\n\n## Financial Analysis\n\nAAPL revenue [ev_news]\n\n## Risk Assessment\n",
                "evidence_records": [
                    {
                        "evidence_id": "ev_news",
                        "source_type": "news",
                        "source_url": "https://example.com/news",
                        "content": "Revenue 126.3B.",
                    }
                ],
                "expected_symbol": "AAPL",
                "period": "2025Q4",
            },
        )
    )

    gaps = result.output["verification_report"]["evidence_gaps"]
    assert gaps
    assert gaps[0]["gap_type"] == "missing_primary_evidence"
    assert gaps[0]["blocking"] is True


def test_verifier_agent_blocks_cross_symbol_report_body():
    verifier = VerifierAgent()
    claim = ClaimItem(
        claim_id="cl_amd",
        section_name="financial_analysis",
        claim_text="AMD revenue was 10.25B.",
        evidence_ids=["ev_amd"],
        numeric_values={"revenue_billion": 10.25},
        confidence=0.86,
    )

    result = verifier.execute_task(
        AgentTask(
            task_id="task_verify_symbol_mix",
            task_type="verifier",
            description="Verify symbol isolation",
            parameters={
                "claims": [claim.to_dict()],
                "markdown": (
                    "# Report\n\n"
                    "## Executive Summary\n\nApple Inc. report summary discusses AAPL. [ev_amd]\n\n"
                    "## Financial Analysis\n\nAMD revenue was 10.25B. [ev_amd]\n\n"
                    "## Risk Assessment\n\nAMD risk section. [ev_amd]\n"
                ),
                "evidence_records": [
                    {
                        "evidence_id": "ev_amd",
                        "symbol": "AMD",
                        "source_type": "sec_filing",
                        "source_url": "https://www.sec.gov/example",
                        "content": "AMD revenue was 10.25B.",
                    }
                ],
                "expected_symbol": "AMD",
            },
        )
    )

    report = result.output["verification_report"]
    assert report["passed"] is False
    assert any("expected AMD" in item and "AAPL" in item for item in report["errors"])


def test_rule_verifier_blocks_cross_symbol_leak_after_intro():
    verifier = Verifier()
    claim = ClaimItem(
        claim_id="cl_amd",
        section_name="financial_analysis",
        claim_text="AMD revenue was 10.25B.",
        evidence_ids=["ev_amd"],
        numeric_values={"revenue_billion": 10.25},
        confidence=0.86,
    )
    markdown = (
        "# Report\n\n"
        "## Executive Summary\n\nAMD summary. [ev_amd]\n\n"
        + ("x" * 1300)
        + "\nApple Inc. and AAPL leaked into a non-peer section.\n\n"
        "## Financial Analysis\n\nAMD revenue was 10.25B. [ev_amd]\n\n"
        "## Risk Assessment\n\nAMD risk section. [ev_amd]\n"
    )

    report = verifier.verify(
        claims=[claim],
        markdown=markdown,
        evidence_records=[
            {
                "evidence_id": "ev_amd",
                "symbol": "AMD",
                "source_type": "sec_filing",
                "source_url": "https://www.sec.gov/example",
                "content": "AMD revenue was 10.25B.",
            }
        ],
        expected_symbol="AMD",
    )

    assert report["passed"] is False
    assert any("expected AMD" in item and "AAPL" in item for item in report["errors"])


def test_verifier_agent_downgrades_llm_valuation_artifact_objection():
    class ValuationObjectionModel:
        model_name = "fake-valuation-objection"

        def generate_json(self, prompt, system_prompt=None, **kwargs):
            return {
                "passed": False,
                "errors": [
                    "\u4f30\u503c\u6570\u5b57\u7efc\u5408\u80a1\u6743\u4ef7\u503c2252.1B\u7f3a\u4e4f\u8bc1\u636e\u652f\u6301"
                ],
                "warnings": [""],
                "fix_recommendations": [],
            }

    verifier = VerifierAgent(model=ValuationObjectionModel())
    valuation = {
        "valuation_available": True,
        "blended_equity_value_billion": 100.0,
        "relative_valuation": {
            "multiples": {
                "pe": {"denominator_value": 5.0, "multiple": 10.0, "equity_value_billion": 50.0},
                "ps": {"denominator_value": 20.0, "multiple": 5.0, "equity_value_billion": 100.0},
            }
        },
        "dcf_model": {
            "assumptions": {
                "discount_rate": 0.1,
                "terminal_growth": 0.02,
                "net_debt_billion": 0.0,
                "base_free_cash_flow_billion": 5.0,
            },
            "forecast": [{"present_value_billion": 10.0}],
            "pv_terminal_value_billion": 90.0,
            "enterprise_value_billion": 100.0,
            "equity_value_billion": 100.0,
        },
        "valuation_sensitivity": {
            "scenario_values": {
                "bear": {"equity_value_billion": 80.0},
                "base": {"equity_value_billion": 100.0},
                "bull": {"equity_value_billion": 120.0},
            }
        },
    }
    claim = ClaimItem(
        claim_id="cl_valuation",
        section_name="valuation",
        claim_text="AAPL valuation model estimates blended equity value from audited artifacts. [ev_sec]",
        evidence_ids=["ev_sec"],
        numeric_values={"blended_equity_value_billion": 100.0},
        confidence=0.86,
        notes="Derived valuation model output.",
    )

    result = verifier.execute_task(
        AgentTask(
            task_id="task_verify_valuation_override",
            task_type="verifier",
            description="Verify valuation override",
            parameters={
                "claims": [claim.to_dict()],
                "markdown": (
                    "# Report\n\n"
                    "## Executive Summary\n\nAAPL valuation summary. [ev_sec]\n\n"
                    "## Financial Analysis\n\nFinancial context is cited. [ev_sec]\n\n"
                    "## Valuation\n\nAAPL valuation model estimates blended equity value. [ev_sec]\n\n"
                    "## Risk Assessment\n\nValuation risk is model sensitivity. [ev_sec]\n"
                ),
                "evidence_records": [
                    {
                        "evidence_id": "ev_sec",
                        "symbol": "AAPL",
                        "source_type": "sec_filing",
                        "source_url": "https://www.sec.gov/example",
                        "content": "SEC evidence for AAPL filings and valuation inputs.",
                    }
                ],
                "valuation": valuation,
                "expected_symbol": "AAPL",
            },
        )
    )

    report = result.output["verification_report"]
    assert report["passed"] is True
    assert report["llm_override_passed"] is True
    assert report["llm_passed"] is True
    assert report["llm_errors"] == []
    assert any("downgraded" in item for item in report["llm_warnings"])


def test_browser_pdf_reader_extracts_text_and_table(monkeypatch, tmp_path):
    class FakeTable:
        def extract(self):
            return [["Metric", "Value"], ["Revenue", "126.3B"], ["Operating cash flow", "38.1B"]]

    class FakePage:
        def get_text(self):
            return "Revenue 126.3B. Net income and operating cash flow are disclosed."

        def find_tables(self):
            return [FakeTable()]

    class FakeDoc:
        def __len__(self):
            return 1

        def __getitem__(self, index):
            assert index == 0
            return FakePage()

        def close(self):
            return None

    class FakeFitz:
        @staticmethod
        def open(path):
            assert str(path).endswith("annual_report.pdf")
            return FakeDoc()

    monkeypatch.setitem(sys.modules, "fitz", FakeFitz)
    pdf_path = tmp_path / "annual_report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    payload = read_pdf_content(str(pdf_path), max_chars=500)

    assert payload["engine"] == "pymupdf_pdf"
    assert payload["page_count"] == 1
    assert payload["table_count"] == 1
    assert "Revenue 126.3B" in payload["content"]
    assert "Metric | Value" in payload["content"]


def test_browser_reader_enriches_pdf_record(monkeypatch, tmp_path):
    def fake_pdf_reader(pdf_path_or_url, max_chars=4000, max_pages=12, config_path="configs/data_sources.yaml"):
        return {
            "reader_url": pdf_path_or_url,
            "content": "PDF filing content with Revenue 126.3B.",
            "engine": "pymupdf_pdf",
            "page_count": 2,
            "table_count": 1,
            "financial_data_count": 1,
        }

    monkeypatch.setattr("src.agents.browser_agent.read_pdf_content", fake_pdf_reader)
    pdf_path = tmp_path / "annual_report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    records, meta = enrich_records_with_reader(
        records=[
            {
                "evidence_id": "pdf_1",
                "source_type": "web_search",
                "source_url": str(pdf_path),
                "content": "short snippet",
                "metadata": {},
            }
        ],
        max_records=1,
        max_chars=100,
    )

    assert meta["succeeded"] == 1
    assert records[0]["content"].startswith("PDF filing content")
    assert records[0]["metadata"]["reader"]["engine"] == "pymupdf_pdf"
    assert records[0]["metadata"]["pdf"]["table_count"] == 1
