from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'promptops_api.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app)


def test_promptops_api_crud_active_version_and_test_run(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/promptops/templates",
            json={
                "prompt_key": "claim_verifier",
                "name": "主张校验",
                "module": "verifier",
                "content": "判断主张：{{claim}}",
                "schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
            },
        )
        listed = client.get("/api/promptops/templates", params={"module": "verifier"})
        version = client.post("/api/promptops/templates/claim_verifier/versions", json={"content": "新版：{{claim}}"})
        active = client.get("/api/promptops/templates/claim_verifier/active")
        test_run = client.post(
            "/api/promptops/templates/claim_verifier/test-run",
            json={"input": {"claim": "收入增长"}, "model_role": "verifier", "task_id": "task-promptops"},
        )
        llm_runs = client.get("/api/llm-runs", params={"prompt_key": "claim_verifier"})

    assert created.status_code == 201
    assert created.json()["active_version"] == 1
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert version.status_code == 201
    assert version.json()["version"] == 2
    assert active.status_code == 200
    assert active.json()["version"] == 2
    assert test_run.status_code == 200
    assert test_run.json()["prompt_version_id"] == active.json()["id"]
    assert test_run.json()["schema_valid"] is True
    assert llm_runs.status_code == 200
    assert llm_runs.json()["total"] == 1


def test_promptops_api_can_activate_version_and_disable_template(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/promptops/templates",
            json={
                "prompt_key": "fact_extractor",
                "name": "事实抽取",
                "module": "fact_extractor",
                "content": "v1 {{text}}",
                "schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
            },
        )
        version = client.post(
            "/api/promptops/templates/fact_extractor/versions",
            json={"content": "v2 {{text}}", "is_active": False},
        )
        still_v1 = client.get("/api/promptops/templates/fact_extractor/active")
        activated = client.post(f"/api/promptops/templates/fact_extractor/versions/{version.json()['id']}/activate")
        active = client.get("/api/promptops/templates/fact_extractor/active")
        disabled = client.post("/api/promptops/templates/fact_extractor/active", json={"active": False})
        active_only = client.get("/api/promptops/templates", params={"active_only": True})

    assert created.status_code == 201
    assert version.status_code == 201
    assert still_v1.json()["version"] == 1
    assert activated.status_code == 200
    assert activated.json()["active_version"] == 2
    assert active.json()["version"] == 2
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert active_only.status_code == 200
    assert active_only.json()["total"] == 0
