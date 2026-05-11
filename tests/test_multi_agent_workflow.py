import json
import re
import sys

from src.agents import AgentStatus, AgentTask, BrowserAgent, DeepAnalyzeAgent, FinalAnswerAgent, VerifierAgent
from src.agents.browser_agent import enrich_records_with_reader, read_pdf_content, read_url_content
from src.agents.final_answer_agent import normalize_report_headings
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator, prepare_dynamic_tasks
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

    assert summary["execution_mode"] == "dynamic"
    assert summary["entity_resolution"]["resolved_symbol"] == "AAPL"
    assert summary["verification_passed"] is True
    assert summary["citation_count"] >= 1
    assert summary["chart_count"] >= 1
    assert summary["mcp_tool_count"] >= 1
    assert len(trace_lines) == 6
    assert result["report_md"].endswith("report.md")
    assert result["citations"].endswith("citations.json")
    assert result["charts"].endswith("charts.json")
    assert result["financial_metrics"].endswith("financial_metrics.json")
    assert result["tables"].endswith("tables.json")
    assert result["mcp_manifest"].endswith("mcp_manifest.json")
    assert result["conversation_context"].endswith("conversation_context.json")
    assert (tmp_path / "outputs" / "citations.json").exists()
    assert (tmp_path / "outputs" / "charts.json").exists()
    assert (tmp_path / "outputs" / "financial_metrics.json").exists()
    assert (tmp_path / "outputs" / "tables.json").exists()
    assert (tmp_path / "outputs" / "conversation_context.json").exists()
    assert (tmp_path / "outputs" / "mcp_manifest.json").exists()
    assert "## 参考来源" in (tmp_path / "reports" / "report.md").read_text(encoding="utf-8")
    assert "## 图表" in (tmp_path / "reports" / "report.md").read_text(encoding="utf-8")
    financial_metrics = json.loads((tmp_path / "outputs" / "financial_metrics.json").read_text(encoding="utf-8"))
    assert financial_metrics["metric_count"] >= 1


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
    assert json.loads((tmp_path / "outputs" / "conversation_context.json").read_text(encoding="utf-8"))["verifier_feedback"]
    assert sum(1 for item in trace if item["agent"] == "FinalAnswerAgent") == 2
    assert sum(1 for item in trace if item["agent"] == "VerifierAgent") == 2


def test_final_answer_heading_normalization_demotes_section_h1():
    markdown = "# 执行摘要\n\nText\n\n#### Financial Analysis\n\nText\n\n# 风险评估\n\nText"

    normalized = normalize_report_headings(markdown)

    assert "## 执行摘要" in normalized
    assert "## 财务分析" in normalized
    assert "## 风险评估" in normalized


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
        markdown="# Report\n\n## 执行摘要\n\n## 财务分析\n\nAAPL revenue [ev_fin]\n\n## 风险评估\n",
        evidence_records=[
            {
                "evidence_id": "ev_fin",
                "content": "Revenue 126.3B, gross margin 46.8%.",
                "metadata": {"revenue_billion": 126.3},
            }
        ],
        charts=[{"chart_id": "metrics", "source_fields": "claims.numeric_values", "output_path": str(chart_path)}],
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
    assert "valuation_sensitivity" in sections


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
