from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'promptops_verifier.db'}",
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


def test_promptops_claim_verifier_test_run_uses_real_verifier_backend(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/promptops/templates",
            json={
                "prompt_key": "claim_verifier",
                "name": "主张校验",
                "module": "verifier",
                "content": "校验主张和证据：{{claims}}",
                "schema": {
                    "type": "object",
                    "required": ["passed", "error_count", "warning_count", "claim_count"],
                    "properties": {
                        "passed": {"type": "boolean"},
                        "error_count": {"type": "integer"},
                        "warning_count": {"type": "integer"},
                        "claim_count": {"type": "integer"},
                    },
                },
            },
        )
        run = client.post(
            "/api/promptops/templates/claim_verifier/test-run",
            json={
                "task_id": "task-verifier-promptops",
                "input": {
                    "expected_symbol": "AMD",
                    "claims": [
                        {
                            "claim_id": "cl_revenue",
                            "section_name": "financial_analysis",
                            "claim_text": "AMD revenue was 9.2B in 2025Q4. [filing_1]",
                            "evidence_ids": ["filing_1"],
                            "numeric_values": {"revenue_billion": 9.2},
                            "confidence": 0.8,
                        }
                    ],
                    "markdown": "# Executive Summary\n\n## Financial Analysis\n\nAMD revenue was 9.2B in 2025Q4. [filing_1]\n\n## Risk Assessment\n",
                    "evidence_records": [
                        {
                            "evidence_id": "filing_1",
                            "source_type": "filing",
                            "source_url": "https://www.sec.gov/Archives/edgar/data/amd/10-q.htm",
                            "content": "AMD revenue was 9.2B.",
                            "metadata": {"symbol": "AMD"},
                        }
                    ],
                },
            },
        )
        runs = client.get("/api/llm-runs", params={"prompt_key": "claim_verifier"})

    assert created.status_code == 201
    assert run.status_code == 200
    assert run.json()["status"] == "success"
    assert run.json()["output"]["passed"] is True
    assert run.json()["output"]["claim_count"] == 1
    assert run.json()["schema_valid"] is True
    assert runs.status_code == 200
    assert runs.json()["total"] == 1
    logged = runs.json()["items"][0]
    assert logged["model_name"] == "claim-verifier-rules"
    assert logged["metadata"]["module_binding"] == "claim_verifier"
    assert logged["metadata"]["promptops_bound"] is True
