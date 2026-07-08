from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import (
    ClaimEvidence,
    Company,
    Document,
    EvidenceItem,
    FinancialFact,
    InvestmentSignal,
    ReportClaim,
    ReportTask,
    ReportTaskEvent,
)
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'task_analysis.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app), service


def seed_analysis_package(service):
    with service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US", industry="Semiconductors")
        session.add(company)
        session.flush()
        task = ReportTask(
            task_id="task-analysis",
            company_id=company.id,
            symbol="NVDA",
            period="FY2024",
            report_type="annual_review",
            status="quality_failed",
            current_stage="quality_failed",
            quality_score=0.73,
            metadata_json={
                "company_name": "NVIDIA",
                "research_topic": "分析 NVIDIA FY2024 毛利率和现金流风险",
                "data_source_scope": "official_first",
                "quality_result": {
                    "delivery_gate": {"delivery_pass": False, "objective_pass": False, "llm_review_pass": True},
                    "quality_report": {"objective_pass": False, "total_score": 0.73},
                    "llm_quality_review": {"llm_review_pass": True},
                    "top_quality_issues": [
                        {"severity": "blocker", "category": "citation_missing", "message": "部分风险主张缺少引用。"}
                    ],
                },
            },
        )
        session.add(task)
        session.add(
            ReportTaskEvent(
                task_id="task-analysis",
                stage="quality_gate",
                status="failed",
                message="Delivery quality gate failed",
            )
        )
        document = Document(
            company_id=company.id,
            batch_id="task-analysis",
            title="NVIDIA FY2024 Form 10-K",
            doc_type="10-K",
            report_period="FY2024",
            source_url="https://example.com/nvda-10k",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        evidence = EvidenceItem(
            evidence_id="ev-analysis-margin",
            company_id=company.id,
            document_id=document.id,
            source_type="sec_edgar",
            trust_level="official",
            title="Gross margin disclosure",
            content="Gross margin declined while revenue increased.",
            source_url="https://example.com/nvda-10k#page=42",
            page_no=42,
            metadata_json={"period": "FY2024", "task_id": "task-analysis"},
        )
        session.add(evidence)
        session.flush()
        fact = FinancialFact(
            company_id=company.id,
            evidence_item_id=evidence.id,
            metric_name="毛利率",
            metric_type="ratio",
            value=53.0,
            unit="%",
            period="FY2024",
            confidence=0.91,
            review_status="approved",
        )
        session.add(fact)
        session.flush()
        signal = InvestmentSignal(
            signal_id="sig-analysis-margin",
            task_id="task-analysis",
            company_id=company.id,
            evidence_item_id=evidence.id,
            source_fact_id=fact.id,
            signal_type="margin_decline",
            category="profitability",
            title="毛利率下滑",
            summary="毛利率较前期回落，需要解释产品结构或成本压力。",
            severity="high",
            direction="negative",
            confidence=0.86,
            status="in_context",
            period="FY2024",
            source_rule="margin_decline",
        )
        claim_supported = ReportClaim(
            task_id="task-analysis",
            section_name="盈利能力",
            claim_text="NVIDIA FY2024 毛利率存在下滑压力。",
            claim_type="risk",
            is_critical=True,
            verification_status="supported",
            numeric_check_status="passed",
            citation_check_status="passed",
            confidence=0.82,
            review_status="approved",
        )
        claim_failed = ReportClaim(
            task_id="task-analysis",
            section_name="风险提示",
            claim_text="供应链压力可能继续影响利润率。",
            claim_type="risk",
            verification_status="failed",
            numeric_check_status="passed",
            citation_check_status="failed",
            confidence=0.55,
            review_status="pending",
        )
        session.add_all([signal, claim_supported, claim_failed])
        session.flush()
        session.add(ClaimEvidence(claim_id=claim_supported.id, evidence_item_id=evidence.id, support_type="supporting"))
        session.commit()


def test_report_task_analysis_package_connects_quality_chain_and_risk(tmp_path):
    client, service = build_client(tmp_path)
    seed_analysis_package(service)

    with client:
        response = client.get("/api/report-tasks/task-analysis/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["scope"]["symbol"] == "NVDA"
    assert body["stats"]["evidence_count"] == 1
    assert body["stats"]["financial_fact_count"] == 1
    assert body["stats"]["investment_signal_count"] == 1
    assert body["stats"]["claim_count"] == 2
    assert body["quality_proof"]["delivery_pass"] is False
    checks = {item["key"]: item for item in body["quality_proof"]["checks"]}
    assert checks["evidence_binding"]["passed"] is False
    assert checks["citation_consistency"]["passed"] is False
    assert body["quality_proof"]["failed_claims"][0]["citation_check_status"] == "failed"
    assert body["argument_chain"]["nodes"]
    assert body["argument_chain"]["edges"]
    assert body["risk_chain"]["risk_count"] == 1
    assert any(action["view"] == "claims" for action in body["recommended_actions"])


def test_report_task_analysis_returns_404_for_missing_task(tmp_path):
    client, _ = build_client(tmp_path)

    with client:
        response = client.get("/api/report-tasks/not-found/analysis")

    assert response.status_code == 404
