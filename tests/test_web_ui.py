import json
import threading
from urllib import request

from src.app.web_ui import load_run_payload, render_index_html, run_ui_server


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
    assert "研究助手" in html
    assert "启用三层记忆" in html
    assert "时间线" in html
    assert "Markdown 源文" not in html


def test_chat_api_returns_fallback_response_without_key(tmp_path):
    config = tmp_path / "model_backends.yaml"
    config.write_text(
        """
agent_model:
  provider: deepseek
  model_name: deepseek-test
  base_url: https://api.deepseek.com
  api_key: ""
  timeout: 1
  retry: 0
  max_tokens: 256
  temperature: 0.1
""".strip(),
        encoding="utf-8",
    )
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({"message": "我喜欢简洁回答", "memory_enabled": True}).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["answer"]
    assert body["mode"] == "chat"
    assert body["memory_used"]["enabled"] is True
