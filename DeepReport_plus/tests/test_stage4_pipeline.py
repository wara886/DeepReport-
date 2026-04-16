import json
from pathlib import Path

from src.app.pipeline import run_pipeline


def test_stage4_pipeline_generates_required_outputs(tmp_path: Path):
    output_dir = tmp_path / "outputs"
    report_dir = tmp_path / "reports"
    result = run_pipeline(output_dir=str(output_dir), report_dir=str(report_dir))

    claim_path = Path(result["claim_table"])
    report_path = Path(result["report_markdown"])
    verify_path = Path(result["verification_report"])

    assert claim_path.exists()
    assert report_path.exists()
    assert verify_path.exists()

    claims = json.loads(claim_path.read_text(encoding="utf-8"))
    verify = json.loads(verify_path.read_text(encoding="utf-8"))
    markdown = report_path.read_text(encoding="utf-8")

    assert isinstance(claims, list)
    assert "## Financial Analysis" in markdown
    assert "passed" in verify

