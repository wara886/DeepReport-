from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'facts_api.db'}",
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


def test_financial_fact_importer_api_create_list_and_detail(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/financial-facts",
            json={
                "company_name": "苹果公司",
                "symbol": "AAPL",
                "metric_name": "毛利率",
                "value": 46.2,
                "unit": "%",
                "period": "FY2024",
                "confidence": 0.8,
                "source_url": "https://example.com/aapl",
            },
        )
        listed = client.get("/api/financial-facts", params={"company": "AAPL", "metric": "毛利率", "period": "FY2024"})
        detail = client.get(f"/api/financial-facts/{created.json()['id']}")

    assert created.status_code == 201
    body = created.json()
    assert body["metric_type"] == "ratio"
    assert body["company"]["symbol"] == "AAPL"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["value"] == 46.2
