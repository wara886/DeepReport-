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
        assert {link.support_type for link in links} == {"supports"}
