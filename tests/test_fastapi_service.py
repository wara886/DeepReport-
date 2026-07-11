import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app


def test_fastapi_health_and_root_expose_current_workbench(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    (outputs / "run_summary.json").write_text(json.dumps({"symbol": "TSLA", "period": "FY2024"}), encoding="utf-8")
    (reports / "report.html").write_text("<html><body>report</body></html>", encoding="utf-8")

    app = create_fastapi_app(output_dir=str(outputs), report_dir=str(reports), memory_root=str(tmp_path / "memory"))
    with TestClient(app) as client:
        health = client.get("/health")
        api_health = client.get("/api/health")
        index = client.get("/")
        workbench = client.get("/workbench")
        legacy_latest = client.get("/api/latest")
        legacy_chat = client.post("/api/chat", json={"message": "hello"})

    assert health.json()["status"] == "ok"
    assert api_health.status_code == 200
    assert api_health.json() == health.json()
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "慧研投研工作台" in index.text
    assert workbench.text == index.text
    assert legacy_latest.status_code == 404
    assert legacy_chat.status_code == 404


def test_fastapi_artifacts_resolve_user_and_dev_run_roots(tmp_path, monkeypatch):
    user_reports = tmp_path / "data" / "reports_user" / "runs" / "user-task" / "reports"
    user_outputs = tmp_path / "data" / "outputs_user" / "runs" / "user-task" / "outputs"
    dev_reports = tmp_path / "data" / "reports_dev" / "runs" / "dev-task" / "reports"
    dev_outputs = tmp_path / "data" / "outputs_dev" / "runs" / "dev-task" / "outputs"
    for directory in [user_reports, user_outputs, dev_reports, dev_outputs]:
        directory.mkdir(parents=True)
    (user_reports / "report.html").write_text("<html>user report</html>", encoding="utf-8")
    (user_outputs / "run_summary.json").write_text(json.dumps({"run": "user"}), encoding="utf-8")
    (dev_reports / "report.html").write_text("<html>dev report</html>", encoding="utf-8")
    (dev_outputs / "run_summary.json").write_text(json.dumps({"run": "dev"}), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    config_path = Path(__file__).resolve().parents[1] / "configs" / "model_backends.yaml"
    app = create_fastapi_app(mode="developer", memory_root=str(tmp_path / "memory"), config_path=str(config_path))

    with TestClient(app) as client:
        user_report = client.get("/artifacts/runs/user-task/reports/report.html")
        user_summary = client.get("/artifacts/runs/user-task/outputs/run_summary.json")
        dev_report = client.get("/artifacts/runs/dev-task/reports/report.html")
        dev_summary = client.get("/artifacts/runs/dev-task/outputs/run_summary.json")
        traversal = client.get("/artifacts/../pyproject.toml")

    assert user_report.status_code == 200
    assert "user report" in user_report.text
    assert user_summary.status_code == 200
    assert user_summary.json()["run"] == "user"
    assert dev_report.status_code == 200
    assert "dev report" in dev_report.text
    assert dev_summary.status_code == 200
    assert dev_summary.json()["run"] == "dev"
    assert traversal.status_code in {404, 502}


def test_fastapi_report_artifact_uses_delivery_gate_to_block_stale_normal_label(tmp_path, monkeypatch):
    reports = tmp_path / "data" / "reports_user" / "runs" / "blocked-task" / "reports"
    outputs = tmp_path / "data" / "outputs_user" / "runs" / "blocked-task" / "outputs"
    reports.mkdir(parents=True)
    outputs.mkdir(parents=True)
    (reports / "report.html").write_text(
        "<html><body><header>正常生成 · 88%</header><main>report body</main></body></html>",
        encoding="utf-8",
    )
    (outputs / "delivery_gate.json").write_text(
        json.dumps({"delivery_pass": False, "top_issues": [{"message": "执行摘要深度不足"}]}),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config_path = Path(__file__).resolve().parents[1] / "configs" / "model_backends.yaml"
    app = create_fastapi_app(mode="developer", memory_root=str(tmp_path / "memory"), config_path=str(config_path))

    with TestClient(app) as client:
        response = client.get("/artifacts/runs/blocked-task/reports/report.html")

    assert response.status_code == 200
    assert "草稿生成，正式交付阻塞" in response.text
    assert "正常生成" not in response.text
    assert "88%" not in response.text
