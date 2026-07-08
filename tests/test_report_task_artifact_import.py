import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


class ArtifactWritingOrchestrator:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)

    def run(self, **kwargs):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir / "report.md").write_text("# Report", encoding="utf-8")
        (self.report_dir / "report.html").write_text("<html><body>Report</body></html>", encoding="utf-8")
        (self.report_dir / "report.json").write_text(json.dumps({"title": "Report"}), encoding="utf-8")
        (self.output_dir / "run_summary.json").write_text(
            json.dumps({"symbol": kwargs["symbol"], "period": kwargs["period"]}),
            encoding="utf-8",
        )
        (self.output_dir / "verification_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
        return {"verification_passed": True}


class FactArtifactWritingOrchestrator(ArtifactWritingOrchestrator):
    def run(self, **kwargs):
        result = super().run(**kwargs)
        (self.output_dir / "evidence.json").write_text(
            json.dumps(
                [
                    {
                        "evidence_id": "ev_financials",
                        "title": "AAPL FY2024 10-K financials",
                        "content": "Revenue 391035000000, net income 93736000000.",
                        "source_type": "sec_edgar",
                        "trust_level": "official",
                        "source_url": "https://www.sec.gov/aapl/10-k",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (self.output_dir / "claims.json").write_text(
            json.dumps(
                [
                    {
                        "claim_id": "cl_financials",
                        "section_name": "financial_analysis",
                        "claim_text": "AAPL FY2024 revenue was 391.04B and net income was 93.74B.",
                        "evidence_ids": ["ev_financials"],
                        "numeric_values": {"revenue": 391035000000, "net_income": 93736000000},
                        "confidence": 0.9,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return result


class AgentTraceWritingOrchestrator(ArtifactWritingOrchestrator):
    def run(self, **kwargs):
        result = super().run(**kwargs)
        (self.output_dir / "run_summary.json").write_text(
            json.dumps(
                {
                    "symbol": kwargs["symbol"],
                    "period": kwargs["period"],
                    "executed_agents": ["planning", "research", "final_answer", "verifier", "gap_resolver"],
                    "model_usage_by_agent": {
                        "planning": {"model_name": "planner-model", "route_profile": "test", "api_key_present": True, "model_enabled": True},
                        "research": {"model_name": "research-model", "route_profile": "test", "api_key_present": True, "model_enabled": True},
                        "final_answer": {"model_name": "writer-model", "route_profile": "test", "api_key_present": True, "model_enabled": True},
                        "verifier": {"model_name": "verifier-model", "route_profile": "test", "api_key_present": True, "model_enabled": True},
                        "gap_resolver": {"model_name": "", "route_profile": "rule_only", "api_key_present": False, "model_enabled": False},
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.output_dir / "agent_collaboration_trace.json").write_text(
            json.dumps(
                {
                    "agents": [
                        {"agent": "PlanningAgent", "task_type": "planning", "status": "completed", "duration_sec": 0.1, "input_summary": {"topic": "x"}, "output_keys": ["plan"]},
                        {"agent": "DeepResearcherAgent", "task_type": "deep_researcher", "status": "completed", "duration_sec": 1.2, "input_summary": {"symbol": "AAPL"}, "output_keys": ["evidence"]},
                        {"agent": "FinalAnswerAgent", "task_type": "final_answer", "status": "completed", "duration_sec": 2.3, "input_summary": {"claims": 3}, "output_keys": ["report_md"]},
                        {"agent": "VerifierAgent", "task_type": "verifier", "status": "completed", "duration_sec": 0.4, "input_summary": {"claims": 3}, "output_keys": ["verification_report"]},
                        {"agent": "GapResolverAgent", "task_type": "gap_resolver", "status": "completed", "duration_sec": 0.0, "input_summary": {}, "output_keys": ["gaps"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return result


def passing_quality_runner(output_dir, report_dir, **kwargs):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quality_report.json").write_text(
        json.dumps({"objective_pass": True, "total_score": 0.93}),
        encoding="utf-8",
    )
    (output_dir / "delivery_gate.json").write_text(
        json.dumps({"delivery_pass": True, "objective_pass": True, "llm_review_pass": True}),
        encoding="utf-8",
    )
    return {
        "quality_report": {"objective_pass": True, "total_score": 0.93},
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.9, "model_status": "test"},
        "delivery_gate": {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True},
        "top_quality_issues": [],
    }


def test_report_task_artifact_import_links_completed_outputs(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=ArtifactWritingOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-artifacts-001", "symbol": "AAPL", "period": "FY2024"},
        )
        artifacts = client.get("/api/report-tasks/task-artifacts-001/artifacts")

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert artifacts.status_code == 200
    artifact_types = {artifact["artifact_type"] for artifact in artifacts.json()["artifacts"]}
    assert {"markdown", "html", "json", "run_summary", "verification_report", "quality_report", "delivery_gate"}.issubset(artifact_types)
    assert artifacts.json()["report_links"]["html_web_url"].endswith("/runs/task-artifacts-001/reports/report.html")
    assert artifacts.json()["report_links"]["markdown_web_url"].endswith("/runs/task-artifacts-001/reports/report.md")


def test_report_task_artifact_import_populates_financial_facts_from_claim_numbers(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=FactArtifactWritingOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-facts-001", "symbol": "AAPL", "period": "FY2024"},
        )
        facts = client.get("/api/financial-facts", params={"company": "AAPL", "period": "FY2024"})
        dashboard = client.get("/api/dashboard/summary")
        documents = client.get("/api/documents", params={"company": "AAPL", "batch_id": "task-facts-001"})

    assert created.status_code == 201
    assert facts.status_code == 200
    items = facts.json()["items"]
    assert {item["metric_name"] for item in items} == {"revenue", "net_income"}
    assert all(item["evidence"]["evidence_id"] == "ev_financials" for item in items)
    assert all(item["source_url"] == "https://www.sec.gov/aapl/10-k" for item in items)
    assert dashboard.json()["financial_fact_count"] == 2
    assert documents.status_code == 200
    document_items = documents.json()["items"]
    assert len(document_items) == 1
    assert document_items[0]["batch_id"] == "task-facts-001"
    assert document_items[0]["evidence_count"] == 1
    assert document_items[0]["claim_count"] == 1
    assert document_items[0]["step_count"] == 7

    with TestClient(app) as client:
        detail = client.get(f"/api/documents/{document_items[0]['id']}")

    assert detail.status_code == 200
    detail_body = detail.json()
    assert {step["step_name"] for step in detail_body["processing_steps"]} == {
        "ingest",
        "parse",
        "table_extract",
        "chunk_vectorize",
        "evidence",
        "claim_bind",
        "verify",
    }
    assert {step["status"] for step in detail_body["processing_steps"]} == {"success"}
    assert detail_body["evidence"][0]["evidence_id"] == "ev_financials"
    assert detail_body["claims"][0]["claim_text"] == "AAPL FY2024 revenue was 391.04B and net income was 93.74B."


def test_report_task_artifact_import_binds_financial_metrics_lineage(tmp_path):
    class FinancialMetricsOrchestrator(ArtifactWritingOrchestrator):
        def run(self, **kwargs):
            result = super().run(**kwargs)
            (self.output_dir / "evidence.json").write_text(
                json.dumps(
                    [
                        {
                            "evidence_id": "ev_yahoo_financials",
                            "title": "AAPL market financials",
                            "content": "Gross margin was 46.91%.",
                            "source_type": "market_api",
                            "trust_level": "medium",
                            "source_url": "https://finance.yahoo.com/quote/AAPL/key-statistics",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (self.output_dir / "financial_metrics.json").write_text(
                json.dumps(
                    {
                        "metrics": [
                            {
                                "metric_key": "gross_margin",
                                "value": 46.905164,
                                "unit": "pct",
                                "currency": "unknown",
                                "period": "FY2024",
                                "source_evidence_id": "ev_yahoo_financials",
                                "confidence": 0.62,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return result

    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=FinancialMetricsOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-metrics-lineage", "symbol": "AAPL", "period": "FY2024"},
        )
        facts = client.get("/api/financial-facts", params={"company": "AAPL", "metric": "gross_margin", "period": "FY2024"})

    assert created.status_code == 201
    item = facts.json()["items"][0]
    assert item["metric_type"] == "ratio"
    assert item["currency"] is None
    assert item["unit"] == "%"
    assert item["evidence"]["evidence_id"] == "ev_yahoo_financials"
    assert item["source_url"] == "https://finance.yahoo.com/quote/AAPL/key-statistics"


def test_report_task_artifact_import_populates_facts_from_tables_and_valuation(tmp_path):
    class TablesAndValuationOrchestrator(ArtifactWritingOrchestrator):
        def run(self, **kwargs):
            result = super().run(**kwargs)
            (self.output_dir / "evidence.json").write_text(
                json.dumps(
                    [
                        {
                            "evidence_id": "ev_income",
                            "title": "AAPL FY2024 income statement",
                            "content": "Revenue was 391035 million USD.",
                            "source_type": "sec_edgar",
                            "trust_level": "official",
                            "source_url": "https://www.sec.gov/aapl/income",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (self.output_dir / "tables.json").write_text(
                json.dumps(
                    [
                        {
                            "table_type": "income_statement",
                            "source_evidence_id": "ev_income",
                            "rows": [
                                {
                                    "line_item": "revenue",
                                    "value": 391035,
                                    "unit": "USD_million",
                                    "period": "FY2024",
                                }
                            ],
                        },
                        {
                            "table_type": "balance_sheet",
                            "rows": [
                                {
                                    "line_item": "total_assets",
                                    "value": 364980,
                                    "unit": "USD_million",
                                    "period": "FY2024",
                                    "evidence_id": "ev_income",
                                }
                            ],
                        },
                    ]
                ),
                encoding="utf-8",
            )
            (self.output_dir / "valuation_model.json").write_text(
                json.dumps(
                    {
                        "period": "FY2024",
                        "currency": "USD",
                        "unit": "million",
                        "confidence": 0.7,
                        "blended_equity_value": 3200000,
                        "relative_valuation": {"pe_ratio": 31.4},
                    }
                ),
                encoding="utf-8",
            )
            return result

    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=TablesAndValuationOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-table-valuation-facts", "symbol": "AAPL", "period": "FY2024"},
        )
        facts = client.get("/api/financial-facts", params={"company": "AAPL", "period": "FY2024"})

    assert created.status_code == 201
    items = facts.json()["items"]
    by_metric = {item["metric_name"]: item for item in items}
    assert {"revenue", "total_assets", "valuation_model.blended_equity_value", "valuation_model.relative_valuation.pe_ratio"}.issubset(by_metric)
    assert by_metric["revenue"]["currency"] == "USD"
    assert by_metric["revenue"]["unit"] == "million"
    assert by_metric["revenue"]["evidence"]["evidence_id"] == "ev_income"
    assert by_metric["revenue"]["metadata"]["table_type"] == "income_statement"
    assert by_metric["valuation_model.blended_equity_value"]["currency"] == "USD"
    assert by_metric["valuation_model.blended_equity_value"]["unit"] == "million"
    assert by_metric["valuation_model.blended_equity_value"]["metadata"]["source"] == "valuation_model"
    assert by_metric["valuation_model.relative_valuation.pe_ratio"]["metric_type"] == "ratio"
    assert by_metric["valuation_model.relative_valuation.pe_ratio"]["currency"] is None


def test_report_task_imports_agent_trace_as_llm_runs(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=AgentTraceWritingOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-agent-trace", "symbol": "AAPL", "period": "FY2024"},
        )
        runs = client.get("/api/llm-runs", params={"task_id": "task-agent-trace", "limit": 20})
        dashboard = client.get("/api/dashboard/summary")
        detail = client.get("/api/report-tasks/task-agent-trace")

    assert created.status_code == 201
    body = runs.json()
    prompt_keys = {item["prompt_key"] for item in body["items"]}
    assert {"agent.planning", "agent.research", "agent.final_answer", "agent.verifier", "agent.gap_resolver", "report_quality_gate"}.issubset(prompt_keys)
    agent_runs = [item for item in body["items"] if item["metadata"].get("source") == "agent_trace_import"]
    assert len(agent_runs) == 5
    verifier = next(item for item in agent_runs if item["model_role"] == "verifier")
    assert verifier["model_name"] == "verifier-model"
    assert verifier["latency_ms"] == 400
    gap = next(item for item in agent_runs if item["model_role"] == "gap_resolver")
    assert gap["status"] == "skipped"
    assert dashboard.json()["llm_run_count"] == 6
    diagnostics = detail.json()["quality_diagnostics"]
    assert diagnostics["delivery_pass"] is True
    assert diagnostics["writer"]["model_role"] == "final_answer"
    assert diagnostics["writer"]["model_name"] == "writer-model"
    assert diagnostics["verifier"]["model_role"] == "verifier"
    assert diagnostics["verifier"]["model_name"] == "verifier-model"
    assert diagnostics["quality_gate"]["prompt_key"] == "report_quality_gate"
    assert diagnostics["failure_categories"]["模型跳过:gap_resolver"] == 1
