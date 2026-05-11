import json

from src.app.web_ui import load_run_payload, render_index_html


def test_load_run_payload_reads_latest_artifacts(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()
    (output_root / "run_summary.json").write_text('{"agent_count":6}', encoding="utf-8")
    (output_root / "charts.json").write_text('[{"chart_id":"c1"}]', encoding="utf-8")
    (output_root / "citations.json").write_text('[{"evidence_id":"ev1"}]', encoding="utf-8")
    (output_root / "task_trace.jsonl").write_text(json.dumps({"agent": "PlanningAgent"}) + "\n", encoding="utf-8")
    (report_root / "report.md").write_text("# Report", encoding="utf-8")
    (report_root / "report.html").write_text("<html></html>", encoding="utf-8")

    payload = load_run_payload(output_root=output_root, report_root=report_root)

    assert payload["summary"]["agent_count"] == 6
    assert payload["charts"][0]["chart_id"] == "c1"
    assert payload["citations"][0]["evidence_id"] == "ev1"
    assert payload["trace"][0]["agent"] == "PlanningAgent"
    assert payload["report_html_url"] == "/artifacts/report.html"


def test_render_index_html_contains_workbench_controls():
    html = render_index_html()

    assert "生成多智能体研究报告" in html
    assert "local_real_data,yahoo_finance,tavily,local_evidence" in html
    assert "图表" in html
    assert "引用" in html
