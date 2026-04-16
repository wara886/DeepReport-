import json
from pathlib import Path

from src.templates.exporter import export_reports


def test_stage10_export_outputs_exist(tmp_path: Path):
    claim_path = tmp_path / "claim_table.json"
    chart_path = tmp_path / "chart_metadata.json"
    report_dir = tmp_path / "reports"

    claims = [
        {
            "claim_id": "cl_1",
            "section_name": "financial_analysis",
            "claim_text": "Revenue is stable.",
            "evidence_ids": ["ev_1"],
            "numeric_values": {"revenue_billion": 1.0},
            "risk_level": "low",
            "confidence": 0.8,
            "notes": "",
        }
    ]
    charts = [{"chart_id": "c1", "title": "Revenue", "output_path": "data/outputs/charts/revenue_line.png"}]
    claim_path.write_text(json.dumps(claims, indent=2), encoding="utf-8")
    chart_path.write_text(json.dumps(charts, indent=2), encoding="utf-8")

    outputs = export_reports(claim_path=claim_path, chart_meta_path=chart_path, report_dir=report_dir)

    md = Path(outputs["report_md"])
    html = Path(outputs["report_html"])
    rep_json = Path(outputs["report_json"])
    assert md.exists()
    assert html.exists()
    assert rep_json.exists()

    assert "## Financial Analysis" in md.read_text(encoding="utf-8")
    assert "<h2>Financial Analysis</h2>" in html.read_text(encoding="utf-8")
    payload = json.loads(rep_json.read_text(encoding="utf-8"))
    assert payload["claim_count"] == 1
    assert payload["chart_count"] == 1

