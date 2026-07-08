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

    assert created.status_code == 201
    assert facts.status_code == 200
    items = facts.json()["items"]
    assert {item["metric_name"] for item in items} == {"revenue", "net_income"}
    assert all(item["evidence"]["evidence_id"] == "ev_financials" for item in items)
    assert all(item["source_url"] == "https://www.sec.gov/aapl/10-k" for item in items)
    assert dashboard.json()["financial_fact_count"] == 2


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
