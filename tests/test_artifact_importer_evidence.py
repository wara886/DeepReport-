import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import EvidenceItem, ReportTask
from src.services.artifact_importer import ArtifactImporter


def test_artifact_importer_imports_evidence_with_missing_field_metadata(temp_db_engine, tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_dir = output_root / "runs" / "task-import-evidence" / "outputs"
    report_dir = report_root / "runs" / "task-import-evidence" / "reports"
    output_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (output_dir / "evidence.json").write_text(
        json.dumps(
            [
                {
                    "evidence_id": "ev_1",
                    "source_type": "sec_edgar",
                    "trust_level": "official",
                    "title": "10-K revenue disclosure",
                    "content": "Revenue increased in fiscal 2024.",
                    "source_url": "https://example.com/10k",
                    "page_no": 42,
                },
                {
                    "id": "legacy_ev_without_content",
                    "source_type": "legacy",
                    "metadata": {"legacy_path": "old/output"},
                },
            ]
        ),
        encoding="utf-8",
    )
    (report_dir / "report.html").write_text("<html>report</html>", encoding="utf-8")
    with Session(temp_db_engine) as session:
        session.add(
            ReportTask(
                task_id="task-import-evidence",
                symbol="NVDA",
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
    result = importer.import_for_task("task-import-evidence")

    with Session(temp_db_engine) as session:
        rows = session.scalars(select(EvidenceItem).order_by(EvidenceItem.evidence_id)).all()

        assert result.evidence_count == 2
        assert result.artifact_count == 2
        assert [row.evidence_id for row in rows] == ["ev_1", "legacy_ev_without_content"]
        assert rows[0].content == "Revenue increased in fiscal 2024."
        assert rows[0].page_no == 42
        assert rows[1].content == ""
        assert rows[1].metadata_json["legacy_path"] == "old/output"
        assert "content" in rows[1].metadata_json["missing_fields"]


def test_artifact_importer_removes_recursive_raw_artifact_payload(temp_db_engine, tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_dir = output_root / "runs" / "task-recursive-evidence" / "outputs"
    report_dir = report_root / "runs" / "task-recursive-evidence" / "reports"
    output_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    record = {
        "evidence_id": "ev_recursive",
        "title": "Recursive evidence",
        "content": "Revenue was disclosed.",
        "metadata": {
            "provider": "test",
            "raw_artifact_record": {
                "evidence_id": "ev_recursive",
                "metadata": {"raw_artifact_record": {"evidence_id": "ev_recursive"}},
            },
        },
    }
    (output_dir / "evidence.json").write_text(json.dumps([record]), encoding="utf-8")
    with Session(temp_db_engine) as session:
        session.add(
            ReportTask(
                task_id="task-recursive-evidence",
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
    ).import_for_task("task-recursive-evidence")

    with Session(temp_db_engine) as session:
        row = session.scalar(select(EvidenceItem).where(EvidenceItem.evidence_id == "ev_recursive"))
        raw = row.metadata_json["raw_artifact_record"]
        assert raw["metadata"]["provider"] == "test"
        assert "raw_artifact_record" not in raw["metadata"]
