from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ClaimEvidence, Company, EvidenceItem, FinancialFact, ReportArtifact, ReportClaim, ReportTask, ReviewRecord
from src.services.export_service import ExportService
from src.services.report_task_service import ReportTaskService


def build_export_client(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
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
    app.state.export_service = ExportService(session_factory=service.session, package_root=tmp_path / "export_packages")
    return service, TestClient(app)


def seed_export_task(service, *, rejected=False, pending=False):
    with service.session() as session:
        company = Company(name="NVIDIA", symbol="NVDA", market="US")
        session.add(company)
        session.flush()
        task = ReportTask(task_id="task-export", symbol="NVDA", period="FY2024", status="completed", quality_score=0.92, company_id=company.id)
        session.add(task)
        session.flush()
        evidence = EvidenceItem(
            evidence_id="ev-export-1",
            company_id=company.id,
            source_type="sec_edgar",
            trust_level="official",
            title="FY2024 10-K",
            content="Revenue and margin evidence.",
            source_url="https://example.com/10-k",
        )
        session.add(evidence)
        fact = FinancialFact(
            company_id=company.id,
            metric_name="Revenue",
            metric_type="income_statement",
            value=100.0,
            currency="USD",
            unit="million",
            period="FY2024",
            review_status="approved",
        )
        session.add(fact)
        session.add_all(
            [
                ReportArtifact(task_id="task-export", artifact_type="html", path="report.html", url="/artifacts/report.html"),
                ReportArtifact(task_id="task-export", artifact_type="markdown", path="report.md", url="/artifacts/report.md"),
                ReportArtifact(task_id="task-export", artifact_type="json", path="report.json", url="/artifacts/report.json"),
                ReportArtifact(task_id="task-export", artifact_type="claims", path="claims.json", url="/artifacts/claims.json"),
                ReportArtifact(task_id="task-export", artifact_type="evidence", path="evidence.json", url="/artifacts/evidence.json"),
                ReportArtifact(
                    task_id="task-export",
                    artifact_type="verification_report",
                    path="verification_report.json",
                    url="/artifacts/verification_report.json",
                ),
            ]
        )
        session.flush()
        approved_claim = ReportClaim(task_id="task-export", claim_text="Approved claim.", review_status="approved", verification_status="supported")
        session.add(approved_claim)
        session.flush()
        session.add(ClaimEvidence(claim_id=approved_claim.id, evidence_item_id=evidence.id, support_type="supporting"))
        session.add(ReviewRecord(target_type="report_claim", target_id=str(approved_claim.id), decision="approved", comment="Ready", reviewer="analyst"))
        if rejected:
            session.add(ReportClaim(task_id="task-export", claim_text="Rejected claim.", review_status="rejected"))
        if pending:
            session.add(ReportClaim(task_id="task-export", claim_text="Pending claim.", review_status="pending"))
        session.commit()


def test_export_entry_api_reports_artifacts_and_readiness(temp_db_engine, tmp_path):
    service, client = build_export_client(temp_db_engine, tmp_path)
    seed_export_task(service)

    with client:
        listed = client.get("/api/exports")
        detail = client.get("/api/exports/task-export")
        missing = client.get("/api/exports/missing-task")

    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["task_id"] == "task-export"
    assert item["artifact_count"] == 6
    assert item["review_status_counts"] == {"approved": 1}
    assert item["official_export_ready"] is True
    assert item["blocked_reasons"] == []

    assert detail.status_code == 200
    assert [artifact["artifact_type"] for artifact in detail.json()["artifacts"]] == [
        "html",
        "markdown",
        "json",
        "claims",
        "evidence",
        "verification_report",
    ]
    assert detail.json()["claims"][0]["review_status"] == "approved"
    assert missing.status_code == 404


def test_export_entry_blocks_rejected_and_pending_claims(temp_db_engine, tmp_path):
    service, client = build_export_client(temp_db_engine, tmp_path)
    seed_export_task(service, rejected=True, pending=True)

    with client:
        response = client.get("/api/exports/task-export")

    assert response.status_code == 200
    body = response.json()
    assert body["official_export_ready"] is False
    assert body["rejected_claim_count"] == 1
    assert body["pending_claim_count"] == 1
    assert body["blocked_reasons"] == ["rejected_claims_present", "pending_claim_review"]


def test_export_package_excludes_rejected_and_pending_claims(temp_db_engine, tmp_path):
    service, client = build_export_client(temp_db_engine, tmp_path)
    seed_export_task(service, rejected=True, pending=True)

    with client:
        response = client.get("/api/exports/task-export/package")

    assert response.status_code == 200
    body = response.json()
    assert set(body["formats"]) >= {"json", "markdown", "html", "claims_csv", "evidence_csv", "facts_csv", "review_csv"}
    payload = body["json"]
    assert payload["readiness"]["official_export_ready"] is False
    assert payload["readiness"]["approved_claim_count"] == 1
    assert payload["readiness"]["excluded_claim_count"] == 2
    assert [claim["claim_text"] for claim in payload["claims"]] == ["Approved claim."]
    assert {claim["claim_text"] for claim in payload["excluded_claims"]} == {"Rejected claim.", "Pending claim."}
    assert payload["evidence"][0]["evidence_id"] == "ev-export-1"
    assert payload["financial_facts"][0]["metric_name"] == "Revenue"
    assert payload["review_records"][0]["decision"] == "approved"
    assert "Approved claim." in body["markdown"]
    assert "Rejected claim." not in body["markdown"]
    assert "Approved claim." in body["csv"]["claims"]
    assert "Rejected claim." not in body["csv"]["claims"]


def test_export_package_files_are_written_and_downloadable(temp_db_engine, tmp_path):
    service, client = build_export_client(temp_db_engine, tmp_path)
    seed_export_task(service)

    with client:
        write_response = client.post("/api/exports/task-export/package/files")
        download_response = client.get("/api/exports/task-export/package/files/claims.csv")
        missing_response = client.get("/api/exports/task-export/package/files/secret.txt")

    assert write_response.status_code == 200
    body = write_response.json()
    filenames = {item["filename"] for item in body["files"]}
    assert {"package.json", "report_package.md", "report_package.html", "claims.csv", "evidence.csv", "financial_facts.csv", "review_records.csv"}.issubset(filenames)
    assert all(item["download_url"].startswith("/api/exports/task-export/package/files/") for item in body["files"])
    assert download_response.status_code == 200
    assert "Approved claim." in download_response.text
    assert missing_response.status_code == 404
