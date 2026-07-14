import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import ClaimEvidence, EvidenceItem, ReportClaim, ReportTask
from src.services.artifact_importer import ArtifactImporter


def test_artifact_importer_imports_claims_and_claim_evidence_links(temp_db_engine, tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_dir = output_root / "runs" / "task-import-claims" / "outputs"
    report_dir = report_root / "runs" / "task-import-claims" / "reports"
    output_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (output_dir / "evidence.json").write_text(
        json.dumps(
            [
                {"evidence_id": "ev_revenue", "content": "Revenue was up.", "source_type": "filing"},
                {"evidence_id": "ev_margin", "content": "Margin was stable.", "source_type": "filing"},
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "claims.json").write_text(
        json.dumps(
            [
                {
                    "claim_id": "cl_revenue",
                    "section_name": "financials",
                    "claim_text": "Revenue improved.",
                    "claim_type": "financial",
                    "evidence_ids": ["ev_revenue", "ev_missing"],
                    "verification_status": "supported",
                    "confidence": 0.91,
                },
                {
                    "claim_id": "cl_margin",
                    "claim_text": "Margin remained stable.",
                    "evidence": [{"evidence_id": "ev_margin"}],
                },
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "verification_report.json").write_text(
        json.dumps({"passed": True, "claim_results": [{"claim_id": "cl_revenue", "passed": True}]}),
        encoding="utf-8",
    )
    with Session(temp_db_engine) as session:
        session.add(
            ReportTask(
                task_id="task-import-claims",
                symbol="AAPL",
                period="FY2024",
                metadata_json={"output_dir": str(output_dir), "report_dir": str(report_dir)},
            )
        )
        session.commit()

    importer = ArtifactImporter(
        session_factory=lambda: Session(temp_db_engine),
        output_root=output_root,
        report_root=report_root,
    )
    result = importer.import_for_task("task-import-claims")

    with Session(temp_db_engine) as session:
        claims = session.scalars(select(ReportClaim).order_by(ReportClaim.id)).all()
        evidence = session.scalars(select(EvidenceItem).order_by(EvidenceItem.evidence_id)).all()
        links = session.scalars(select(ClaimEvidence)).all()

        assert result.claim_count == 2
        assert result.evidence_count == 2
        assert result.claim_evidence_count == 2
        assert result.warnings == ["claim cl_revenue references missing evidence ev_missing"]
        assert [row.evidence_id for row in evidence] == ["ev_margin", "ev_revenue"]
        assert claims[0].claim_text == "Revenue improved."
        assert claims[0].confidence == 0.91
        assert claims[0].metadata_json["original_claim_id"] == "cl_revenue"
        assert claims[0].metadata_json["verification_summary"]["passed"] is True
        assert claims[0].review_status == "pending"
        assert claims[0].metadata_json["review_policy"]["reason"] == "citation_check_failed"
        assert {link.support_type for link in links} == {"supports"}


def test_artifact_importer_infers_claim_check_statuses(temp_db_engine, tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_dir = output_root / "runs" / "task-claim-status" / "outputs"
    report_dir = report_root / "runs" / "task-claim-status" / "reports"
    output_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (output_dir / "evidence.json").write_text(
        json.dumps(
            [
                {
                    "evidence_id": "ev_fin",
                    "content": "Revenue was 391.04B in FY2024.",
                    "source_type": "sec_edgar",
                    "trust_level": "official",
                }
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "claims.json").write_text(
        json.dumps(
            [
                {
                    "claim_id": "cl_supported",
                    "claim_text": "Revenue was 391.04B.",
                    "evidence_ids": ["ev_fin"],
                    "numeric_values": {"revenue": 391040000000},
                },
                {
                    "claim_id": "cl_missing_evidence",
                    "claim_text": "Capex was 12.71B.",
                    "evidence_ids": ["ev_missing"],
                    "numeric_values": {"capex": 12710000000},
                },
                {
                    "claim_id": "cl_numeric_mismatch",
                    "claim_text": "Net income was 99.99B.",
                    "evidence_ids": ["ev_fin"],
                    "numeric_values": {"net_income": 99990000000},
                },
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "verification_report.json").write_text(
        json.dumps(
            {
                "passed": False,
                "claim_results": [
                    {"claim_id": "cl_supported", "passed": True},
                    {"claim_id": "cl_missing_evidence", "passed": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    with Session(temp_db_engine) as session:
        session.add(
            ReportTask(
                task_id="task-claim-status",
                symbol="AAPL",
                period="FY2024",
                metadata_json={"output_dir": str(output_dir), "report_dir": str(report_dir)},
            )
        )
        session.commit()

    importer = ArtifactImporter(
        session_factory=lambda: Session(temp_db_engine),
        output_root=output_root,
        report_root=report_root,
    )
    result = importer.import_for_task("task-claim-status")

    with Session(temp_db_engine) as session:
        rows = {
            claim.metadata_json["original_claim_id"]: claim
            for claim in session.scalars(select(ReportClaim).order_by(ReportClaim.id)).all()
        }

    assert result.claim_count == 3
    assert rows["cl_supported"].verification_status == "supported"
    assert rows["cl_supported"].numeric_check_status == "passed"
    assert rows["cl_supported"].citation_check_status == "passed"
    assert rows["cl_supported"].review_status == "pending"
    assert rows["cl_missing_evidence"].verification_status == "failed"
    assert rows["cl_missing_evidence"].numeric_check_status == "failed"
    assert rows["cl_missing_evidence"].citation_check_status == "failed"
    assert rows["cl_numeric_mismatch"].verification_status == "failed"
    assert rows["cl_numeric_mismatch"].numeric_check_status == "failed"
    assert rows["cl_numeric_mismatch"].citation_check_status == "passed"


def test_artifact_importer_auto_approves_only_noncritical_machine_verified_claims(temp_db_engine, tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_dir = output_root / "runs" / "task-review-policy" / "outputs"
    report_dir = report_root / "runs" / "task-review-policy" / "reports"
    output_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (output_dir / "evidence.json").write_text(
        json.dumps([{"evidence_id": "ev_verified", "content": "Revenue was 100B.", "source_type": "sec_edgar"}]),
        encoding="utf-8",
    )
    (output_dir / "claims.json").write_text(
        json.dumps(
            [
                {
                    "claim_id": "cl_auto",
                    "section_name": "financial_analysis",
                    "claim_text": "Revenue was 100B.",
                    "evidence_ids": ["ev_verified"],
                    "numeric_values": {"revenue": 100},
                    "confidence": 0.91,
                    "review_status": "pending",
                },
                {
                    "claim_id": "cl_critical",
                    "claim_text": "Revenue supports the investment conclusion.",
                    "evidence_ids": ["ev_verified"],
                    "confidence": 0.93,
                    "is_critical": True,
                    "critical_claim_type": "investment_conclusion",
                },
                {
                    "claim_id": "cl_low_confidence",
                    "claim_text": "Revenue may remain resilient.",
                    "evidence_ids": ["ev_verified"],
                    "confidence": 0.62,
                },
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "verification_report.json").write_text(
        json.dumps(
            {
                "passed": True,
                "claim_results": [
                    {"claim_id": "cl_auto", "passed": True},
                    {"claim_id": "cl_critical", "passed": True},
                    {"claim_id": "cl_low_confidence", "passed": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    with Session(temp_db_engine) as session:
        session.add(
            ReportTask(
                task_id="task-review-policy",
                symbol="MSFT",
                period="FY2024",
                metadata_json={"output_dir": str(output_dir), "report_dir": str(report_dir)},
            )
        )
        session.commit()

    ArtifactImporter(
        session_factory=lambda: Session(temp_db_engine),
        output_root=output_root,
        report_root=report_root,
    ).import_for_task("task-review-policy")

    with Session(temp_db_engine) as session:
        rows = {
            claim.metadata_json["original_claim_id"]: claim
            for claim in session.scalars(select(ReportClaim).order_by(ReportClaim.id)).all()
        }

    assert rows["cl_auto"].review_status == "approved"
    assert rows["cl_auto"].metadata_json["review_policy"]["mode"] == "automatic"
    assert rows["cl_critical"].review_status == "pending"
    assert "critical_claim" in rows["cl_critical"].metadata_json["review_policy"]["reasons"]
    assert rows["cl_low_confidence"].review_status == "pending"
    assert "confidence_below_threshold" in rows["cl_low_confidence"].metadata_json["review_policy"]["reasons"]
