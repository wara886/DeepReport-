import json

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
    _attach_citation_artifacts(service, tmp_path, used=True)

    with client:
        extracted = client.post("/api/entities/extract-from-task", json={"task_id": "task-analysis"})
        response = client.get("/api/report-tasks/task-analysis/analysis")

    assert extracted.status_code == 201
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
    assert checks["source_coverage"]["passed"] is True
    assert body["retrieval_coverage"]["quality_ready"] is True
    assert body["retrieval_coverage"]["required_sources"] == ["sec_edgar"]
    assert body["retrieval_coverage"]["returned_sources"] == ["sec_edgar"]
    assert body["retrieval_diagnostics"]["stage"] == "ready"
    assert body["retrieval_diagnostics"]["failure_reason"] == ""
    assert body["retrieval_diagnostics"]["query"]["period"] == "FY2024"
    assert body["retrieval_diagnostics"]["candidate_count"] == 1
    assert body["retrieval_diagnostics"]["returned_count"] == 1
    assert body["retrieval_diagnostics"]["returned_examples"][0]["source_type"] == "sec_edgar"
    assert body["citation_usage"]["status"] == "ready"
    assert body["citation_usage"]["used_claim_count"] == 1
    assert body["citation_usage"]["traceable_claim_count"] == 1
    assert body["citation_usage"]["claims_with_used_citation"][0]["claim_text"] == "NVIDIA FY2024 毛利率存在下滑压力。"
    assert body["citation_usage"]["claims_with_used_citation"][0]["evidence_ids"] == ["ev-analysis-margin"]
    assert body["entity_memory"]["ready"] is True
    assert body["entity_memory"]["source_evidence_count"] == 1
    assert body["entity_memory"]["entity_count"] >= 4
    assert body["entity_memory"]["relation_count"] >= 4
    assert any(item["name"] == "metric" for item in body["entity_memory"]["type_distribution"])
    assert any(item["name"] == "HAS_METRIC" for item in body["entity_memory"]["relation_distribution"])
    assert body["signal_summary"]["ready"] is True
    assert body["signal_summary"]["signal_count"] == 1
    assert body["signal_summary"]["high_priority_count"] == 1
    assert body["signal_summary"]["in_context_count"] == 1
    assert body["signal_summary"]["negative_count"] == 1
    assert body["signal_summary"]["top_signals"][0]["priority_label"] == "已进入研报上下文"
    assert body["signal_summary"]["top_signals"][0]["recommended_action"]
    assert "不构成投资建议" in body["signal_summary"]["top_signals"][0]["decision_use"]
    assert body["quality_proof"]["retrieval_coverage"]["summary"]
    assert {item["key"]: item for item in body["quality_proof"]["checks"]}["citation_usage"]["passed"] is True
    assert body["quality_proof"]["failed_claims"][0]["citation_check_status"] == "failed"
    assert body["argument_chain"]["nodes"]
    assert body["argument_chain"]["edges"]
    assert body["risk_chain"]["risk_count"] == 1
    assert any(action["view"] == "claims" for action in body["recommended_actions"])


def test_report_task_analysis_detects_report_citation_usage_gap(tmp_path):
    client, service = build_client(tmp_path)
    seed_analysis_package(service)
    _attach_citation_artifacts(service, tmp_path, used=False)

    with client:
        response = client.get("/api/report-tasks/task-analysis/analysis")

    assert response.status_code == 200
    body = response.json()
    usage = body["citation_usage"]
    assert usage["status"] == "citation_gap"
    assert usage["ready"] is False
    assert usage["citation_count"] == 1
    assert usage["used_citation_count"] == 0
    assert usage["unused_citation_count"] == 1
    assert usage["claims_with_used_citation"] == []
    assert usage["claims_without_used_citation"][0]["claim_text"] == "NVIDIA FY2024 毛利率存在下滑压力。"
    checks = {item["key"]: item for item in body["quality_proof"]["checks"]}
    assert checks["citation_usage"]["passed"] is False
    assert checks["citation_usage"]["title"] == "报告引用使用"


def test_report_task_analysis_exposes_official_evidence_delivery_gate(tmp_path):
    client, service = build_client(tmp_path)
    seed_analysis_package(service)
    output_dir = tmp_path / "official_gap_outputs"
    output_dir.mkdir()
    with service.session() as session:
        task = session.query(ReportTask).filter(ReportTask.task_id == "task-analysis").one()
        metadata = dict(task.metadata_json or {})
        metadata["output_dir"] = str(output_dir)
        metadata["pre_generation_evidence_gate"] = {
            "status": "success",
            "blocked": False,
            "draft_ready": True,
            "delivery_ready": True,
            "summary": "生成前证据门禁通过。",
            "coverage": {"candidate_count": 1, "returned_sources": ["sec_edgar"]},
        }
        task.metadata_json = metadata
        session.commit()

    (output_dir / "evidence_coverage.json").write_text(
        json.dumps(
            {
                "symbol": "NVDA",
                "market": "us",
                "period": "FY2024",
                "official_record_count": 0,
                "required_official_sources": ["SEC EDGAR 10-K/10-Q or SEC Company Facts matching the requested fiscal period"],
                "missing_requirements": ["period_matched_official_filing"],
                "blocking_reasons": ["missing period-matched SEC filing or SEC Company Facts"],
                "recommended_actions": ["Fetch the matching SEC EDGAR filing or SEC Company Facts for this fiscal period."],
                "draft_generation_allowed": True,
                "formal_delivery_allowed": False,
                "degrade_required": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with client:
        response = client.get("/api/report-tasks/task-analysis/analysis")

    assert response.status_code == 200
    gate = response.json()["task"]["metadata"]["pre_generation_evidence_gate"]
    assert gate["draft_ready"] is True
    assert gate["delivery_ready"] is False
    assert gate["official_evidence_coverage"]["formal_delivery_allowed"] is False
    assert gate["delivery_blocked_reasons"][0]["label"] == "官方证据不足"
    assert "SEC" in gate["delivery_blocked_reasons"][0]["description"]
    assert gate["recommended_actions"][0]["view"] == "datasources"


def test_report_task_analysis_retrieval_diagnostics_separates_pool_from_period_hits(tmp_path):
    client, service = build_client(tmp_path)
    with service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US", industry="Semiconductors")
        session.add(company)
        session.flush()
        task = ReportTask(
            task_id="task-analysis-period-gap",
            company_id=company.id,
            symbol="NVDA",
            period="FY2024",
            report_type="annual_review",
            status="quality_failed",
            current_stage="evidence_gate_failed",
            metadata_json={"company_name": "NVIDIA", "data_source_scope": "official_first"},
        )
        session.add(task)
        document = Document(
            company_id=company.id,
            batch_id="batch-old",
            title="NVIDIA FY2023 Form 10-K",
            doc_type="10-K",
            report_period="FY2023",
            source_url="https://example.com/nvda-fy2023",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        session.add(
            EvidenceItem(
                evidence_id="ev-old-period",
                company_id=company.id,
                document_id=document.id,
                source_type="sec_edgar",
                trust_level="official",
                title="FY2023 disclosure",
                content="NVIDIA FY2023 filing content.",
                metadata_json={"period": "FY2023"},
            )
        )
        session.commit()

    with client:
        response = client.get("/api/report-tasks/task-analysis-period-gap/analysis")

    assert response.status_code == 200
    body = response.json()
    diagnostics = body["retrieval_diagnostics"]
    assert body["retrieval_coverage"]["candidate_count"] == 1
    assert body["retrieval_coverage"]["returned_count"] == 0
    assert diagnostics["stage"] == "no_hits"
    assert diagnostics["failure_reason"] == "period_or_query_mismatch"
    assert diagnostics["candidate_examples"][0]["report_period"] == "FY2023"
    assert diagnostics["returned_examples"] == []
    assert any(action["view"] == "evidence" for action in diagnostics["recommended_actions"])


def test_report_task_analysis_returns_404_for_missing_task(tmp_path):
    client, _ = build_client(tmp_path)

    with client:
        response = client.get("/api/report-tasks/not-found/analysis")

    assert response.status_code == 404


def _attach_citation_artifacts(service, tmp_path, *, used: bool) -> None:
    output_dir = tmp_path / ("outputs_used" if used else "outputs_gap")
    report_dir = tmp_path / ("reports_used" if used else "reports_gap")
    output_dir.mkdir()
    report_dir.mkdir()
    with service.session() as session:
        task = session.query(ReportTask).filter(ReportTask.task_id == "task-analysis").one()
        claim = session.query(ReportClaim).filter(ReportClaim.task_id == "task-analysis", ReportClaim.citation_check_status == "passed").one()
        metadata = dict(task.metadata_json or {})
        metadata["output_dir"] = str(output_dir)
        metadata["report_dir"] = str(report_dir)
        task.metadata_json = metadata
        session.commit()

    (output_dir / "citations.json").write_text(
        json.dumps(
            [
                {
                    "citation_id": "ref_001",
                    "evidence_id": "ev-analysis-margin",
                    "claim_ids": [str(claim.id)],
                    "used_in_report": used,
                    "title": "Gross margin disclosure",
                    "source_type": "sec_edgar",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report_text = "NVIDIA FY2024 毛利率存在下滑压力。[ev-analysis-margin]" if used else "NVIDIA FY2024 毛利率存在下滑压力。"
    (report_dir / "report.md").write_text(report_text, encoding="utf-8")
