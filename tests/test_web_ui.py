from datetime import date
import json
import threading
from urllib import error, request

from src.app.web_ui import (
    default_engines_for_symbol,
    load_run_payload,
    render_index_html,
    run_ui_server,
    validate_period_for_report,
)


def test_load_run_payload_reads_latest_artifacts(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()
    (output_root / "run_summary.json").write_text('{"agent_count":6}', encoding="utf-8")
    (output_root / "charts.json").write_text('[{"chart_id":"c1"}]', encoding="utf-8")
    (output_root / "citations.json").write_text('[{"evidence_id":"ev1"}]', encoding="utf-8")
    (output_root / "tables.json").write_text('[{"statement":"income_statement"}]', encoding="utf-8")
    (output_root / "pdf_sections.json").write_text('[{"section_id":"pdf1"}]', encoding="utf-8")
    (output_root / "company_profile_extracted.json").write_text('{"has_profile_hints":true}', encoding="utf-8")
    (output_root / "quality_report.json").write_text('{"objective_pass":true}', encoding="utf-8")
    (output_root / "llm_quality_review.json").write_text('{"llm_review_pass":false}', encoding="utf-8")
    (output_root / "delivery_gate.json").write_text('{"delivery_pass":false}', encoding="utf-8")
    (output_root / "quality_remediation_plan.json").write_text('{"quality_feedback_used":true}', encoding="utf-8")
    (output_root / "task_trace.jsonl").write_text(json.dumps({"agent": "PlanningAgent"}) + "\n", encoding="utf-8")
    (report_root / "report.md").write_text("# Report", encoding="utf-8")
    (report_root / "report.html").write_text("<html></html>", encoding="utf-8")

    payload = load_run_payload(output_root=output_root, report_root=report_root)

    assert payload["summary"]["agent_count"] == 6
    assert payload["charts"][0]["chart_id"] == "c1"
    assert payload["citations"][0]["evidence_id"] == "ev1"
    assert payload["tables"][0]["statement"] == "income_statement"
    assert payload["pdf_sections"][0]["section_id"] == "pdf1"
    assert payload["company_profile_extracted"]["has_profile_hints"] is True
    assert payload["quality_report"]["objective_pass"] is True
    assert payload["llm_quality_review"]["llm_review_pass"] is False
    assert payload["delivery_gate"]["delivery_pass"] is False
    assert payload["quality_remediation_plan"]["quality_feedback_used"] is True
    assert payload["trace"][0]["agent"] == "PlanningAgent"
    assert payload["report_html_url"] == "/artifacts/report.html"


def test_render_index_html_contains_chat_first_controls():
    html = render_index_html()

    assert "你今天在想些什么？" in html
    assert "有问题，尽管问" in html
    assert "Thinking" in html
    assert "高级设置" in html
    assert "local_real_data,yahoo_finance,tavily,local_evidence" in html
    assert "允许 Chat 启动研报" in html
    assert "启用 memory" in html
    assert "实时数据/A股正式源" in html
    assert "PDF章节" in html
    assert "质量评测" in html
    assert "Markdown 源文" not in html


def test_period_guard_blocks_unfinished_quarter_and_suggests_prior_period():
    guard = validate_period_for_report("2026Q2", today=date(2026, 5, 16))

    assert guard["ok"] is False
    assert "2026Q2 尚未结束" in guard["message"]
    assert "2026Q1" in guard["suggested_periods"]
    assert "2025Q4" in guard["suggested_periods"]


def test_default_realtime_engines_switch_by_symbol_market():
    assert "cninfo_announcements" in default_engines_for_symbol("600519.SS", realtime=True)
    assert "eastmoney_financials" in default_engines_for_symbol("600519", realtime=True)
    assert "sec_edgar" in default_engines_for_symbol("AMD", realtime=True)
    assert default_engines_for_symbol("AMD", realtime=False) == "local_real_data,yahoo_finance,tavily,local_evidence"


def test_run_api_rejects_unfinished_period(tmp_path):
    config = _write_model_config(tmp_path)
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
        payload = json.dumps({"symbol": "600519.SS", "period": "2099Q4"}).encode("utf-8")
        req = request.Request(
            f"{url}/api/run",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        status_code = 0
        try:
            request.urlopen(req, timeout=3)
            assert False, "expected HTTP 400"
        except error.HTTPError as exc:
            status_code = exc.code
            body = json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status_code == 400
    assert body["period_guard"]["ok"] is False


def test_chat_api_returns_fallback_response_without_key(tmp_path):
    config = _write_model_config(tmp_path)
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


def test_chat_api_routes_report_run_and_returns_trace(monkeypatch, tmp_path):
    captured = {}

    class FakeOrchestrator:
        def __init__(self, output_dir, report_dir, **kwargs):
            self.output_dir = tmp_path / "outputs"
            self.report_dir = tmp_path / "reports"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.report_dir.mkdir(parents=True, exist_ok=True)

        def run(self, **kwargs):
            captured.update(kwargs)
            (self.output_dir / "citations.json").write_text("[]", encoding="utf-8")
            (self.output_dir / "run_summary.json").write_text(
                json.dumps(
                    {
                        "verification_passed": True,
                        "symbol": kwargs["symbol"],
                        "period": kwargs["period"],
                        "search_engines": kwargs["search_engines"],
                    }
                ),
                encoding="utf-8",
            )
            (self.output_dir / "verification_report.json").write_text('{"passed": true}', encoding="utf-8")
            (self.output_dir / "task_trace.jsonl").write_text('{"agent":"fake","status":"completed"}\n', encoding="utf-8")
            (self.report_dir / "report.md").write_text("# Fake report", encoding="utf-8")
            return {"verification_passed": True, "report_md": str(self.report_dir / "report.md")}

    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    config = _write_model_config(tmp_path)
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
        payload = json.dumps(
            {
                "message": "请生成贵州茅台 2025Q4 公司研报",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["mode"] == "report_run"
    assert any(item["detail"] == "start_multi_agent_report_run" for item in body["tool_trace"])
    assert any(item["stage"] == "verify" for item in body["tool_trace"])
    assert body["result"]["verification_passed"] is True
    assert "delivery_gate" in body["result"]
    assert body["latest"]["delivery_gate"]["delivery_pass"] is False
    assert body["parsed_task"]["symbol"] == "600519.SS"
    assert body["parsed_task"]["period"] == "2025Q4"
    assert captured["enable_remote_data"] is True
    assert captured["symbol"] == "600519.SS"
    assert captured["period"] == "2025Q4"
    assert "cninfo_announcements" in captured["search_engines"]
    assert body["latest"]["summary"]["symbol"] == "600519.SS"


def test_chat_api_asks_confirmation_for_underspecified_report(monkeypatch, tmp_path):
    class FakeOrchestrator:
        def __init__(self, **kwargs):
            raise AssertionError("orchestrator should not run without confirmed report params")

    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    config = _write_model_config(tmp_path)
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
        payload = json.dumps(
            {
                "message": "AMD 研报怎么看",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["mode"] == "confirm_report"
    assert body["parsed_task"]["symbol"] == "AMD"
    assert "请回复确认" in body["answer"]


def _write_model_config(tmp_path):
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
    return config
