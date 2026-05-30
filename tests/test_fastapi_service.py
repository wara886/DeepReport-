import json
import time
from threading import Event

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.app.chat_task_parser import ParsedChatTask


def test_fastapi_health_and_latest_preserve_workbench_contract(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    (outputs / "run_summary.json").write_text(json.dumps({"symbol": "TSLA", "period": "FY2024"}), encoding="utf-8")
    (reports / "report.html").write_text("<html><body>report</body></html>", encoding="utf-8")

    app = create_fastapi_app(output_dir=str(outputs), report_dir=str(reports), memory_root=str(tmp_path / "memory"))
    with TestClient(app) as client:
        health = client.get("/health")
        latest = client.get("/api/latest")
        index = client.get("/")

    assert health.json()["status"] == "ok"
    assert latest.status_code == 200
    assert latest.json()["summary"]["symbol"] == "TSLA"
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]


def test_fastapi_chat_does_not_create_report_run_for_general_dialogue(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    app = create_fastapi_app(output_dir=str(outputs), report_dir=str(reports), memory_root=str(tmp_path / "memory"))

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "hello", "allow_report_run": True, "memory_enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "general_chat"
    assert not (outputs / "runs").exists()


def test_fastapi_chat_background_report_returns_without_upstream_timeout(monkeypatch, tmp_path):
    release = Event()

    class FakeOrchestrator:
        def __init__(self, output_dir, report_dir, **kwargs):
            self.output_dir = output_dir
            self.report_dir = report_dir

        def run(self, **kwargs):
            release.wait(timeout=5)
            return {"verification_passed": True}

    def fake_parse(*args, **kwargs):
        return ParsedChatTask(
            symbol="TSLA",
            period="FY2024",
            period_kind="fiscal_year",
            research_topic="Generate TSLA FY2024 report",
            confidence=0.99,
            should_run=True,
            needs_confirmation=False,
            reason="test",
        )

    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    monkeypatch.setattr("src.app.web_ui.llm_parse_chat_task", fake_parse)
    monkeypatch.setattr("src.app.web_ui.run_delivery_quality_pipeline", lambda *args, **kwargs: {})
    monkeypatch.setattr("src.app.web_ui.run_delivery_rework_loop", lambda *args, **kwargs: {})
    monkeypatch.setattr("src.app.web_ui.QueryUnderstanding.intent_classify", lambda self, msg: "report_generation")

    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    app = create_fastapi_app(output_dir=str(outputs), report_dir=str(reports), memory_root=str(tmp_path / "memory"), mode="developer")

    try:
        with TestClient(app) as client:
            started = time.monotonic()
            response = client.post(
                "/api/chat",
                json={
                    "message": "generate TSLA FY2024 report",
                    "allow_report_run": True,
                    "async_report_run": True,
                    "memory_enabled": False,
                    "enable_remote_data": False,
                },
            )
            elapsed = time.monotonic() - started
    finally:
        release.set()

    body = response.json()
    assert response.status_code == 200
    assert elapsed < 3
    assert body["mode"] == "report_generation_running"
    assert body["result"]["status"] == "running"
    assert body["latest"]["active_runs"][0]["symbol"] == "TSLA"
