import json

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app


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
    assert response.json()["mode"] == "chat"
    assert not (outputs / "runs").exists()
