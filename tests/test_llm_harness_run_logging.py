from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.init_db import init_db
from src.llm.harness import LLMHarness
from src.services.report_task_service import ReportTaskService


class EchoBackend:
    name = "echo-model"

    def generate_structured(self, prompt, schema=None, **kwargs):
        return {"answer": kwargs["question"], "score": 1}


def test_llm_harness_logs_run_and_api_lists_it(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'harness_log.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    harness = LLMHarness(
        session_factory=report_service.session,
        backend=EchoBackend(),
        cost_per_1k_tokens=0.01,
    )
    result = harness.run_prompt(
        prompt_key="claim_verifier",
        input={"question": "是否有证据支持收入增长？"},
        schema={"type": "object", "required": ["answer", "score"], "properties": {"score": {"type": "integer"}}},
        model_role="verifier",
        task_id="task-llm-001",
        prompt_version_id=7,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=report_service,
    )

    with TestClient(app) as client:
        listed = client.get("/api/llm-runs", params={"task_id": "task-llm-001"})
        detail = client.get(f"/api/llm-runs/{result.run_id}")

    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["run_id"] == result.run_id
    assert item["prompt_key"] == "claim_verifier"
    assert item["prompt_version_id"] == 7
    assert item["model_name"] == "echo-model"
    assert item["status"] == "success"
    assert item["schema_valid"] is True
    assert item["total_tokens"] >= 2
    assert item["cost_usd"] > 0
    assert detail.status_code == 200
    assert detail.json()["output"]["score"] == 1
