import json

from src.runtime.run_manifest import commit_run_artifacts, validate_run_manifest


def test_run_manifest_marks_report_stale_when_claims_change(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    (outputs / "evidence.json").write_text("[]", encoding="utf-8")
    (outputs / "canonical_metrics.json").write_text("{}", encoding="utf-8")
    (outputs / "claims.json").write_text("[]", encoding="utf-8")
    (outputs / "section_evidence_packs.json").write_text("{}", encoding="utf-8")
    (outputs / "citations.json").write_text("[]", encoding="utf-8")
    (reports / "report.md").write_text("# report", encoding="utf-8")

    commit_run_artifacts(
        outputs,
        reports,
        ["evidence", "canonical_metrics", "claims", "section_evidence_packs", "citations", "report"],
    )
    (outputs / "claims.json").write_text(json.dumps([{"claim_id": "changed"}]), encoding="utf-8")

    validated = validate_run_manifest(outputs, reports)

    assert validated["status"] == "stale"
    assert "claims" in validated["stale_artifacts"]
    assert any(reason.startswith("dependency_changed:claims") for reason in validated["stale_artifacts"]["report"])


def test_recommitting_report_captures_current_dependency_versions(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    for filename, content in {
        "evidence.json": "[]",
        "canonical_metrics.json": "{}",
        "claims.json": "[]",
        "section_evidence_packs.json": "{}",
        "citations.json": "[]",
    }.items():
        (outputs / filename).write_text(content, encoding="utf-8")
    (reports / "report.md").write_text("# report", encoding="utf-8")
    commit_run_artifacts(
        outputs,
        reports,
        ["evidence", "canonical_metrics", "claims", "section_evidence_packs", "citations", "report"],
    )

    (reports / "report.md").write_text("# repaired report", encoding="utf-8")
    commit_run_artifacts(outputs, reports, ["report"])

    assert validate_run_manifest(outputs, reports)["status"] == "ready"


def test_report_presentation_html_does_not_change_semantic_report_version(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    (reports / "report.md").write_text("# report", encoding="utf-8")
    (reports / "report.html").write_text("<html>draft</html>", encoding="utf-8")
    commit_run_artifacts(outputs, reports, ["report"])

    (reports / "report.html").write_text("<html>quality blocked</html>", encoding="utf-8")

    assert validate_run_manifest(outputs, reports)["status"] == "ready"
