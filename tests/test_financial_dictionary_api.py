from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'dictionary.db'}",
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


def test_financial_dictionary_api_create_list_get_and_resolve(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/dictionary",
            json={
                "term_type": "company",
                "canonical_name": "苹果公司",
                "symbol": "AAPL",
                "market": "US",
                "aliases": ["苹果", "Apple", "Apple Inc."],
                "description": "美国消费电子公司",
            },
        )
        listed = client.get("/api/dictionary", params={"term_type": "company", "q": "Apple"})
        detail = client.get(f"/api/dictionary/terms/{created.json()['id']}")
        resolved = client.get("/api/dictionary/resolve-company", params={"q": "Apple Inc.", "market": "US"})
        duplicate = client.post(
            "/api/dictionary",
            json={"term_type": "company", "canonical_name": "苹果公司", "market": "US"},
        )

    assert created.status_code == 201
    assert created.json()["symbol"] == "AAPL"
    assert "Apple" in created.json()["aliases"]
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["canonical_name"] == "苹果公司"
    assert resolved.status_code == 200
    assert resolved.json()["canonical_name"] == "苹果公司"
    assert resolved.json()["matched_alias"] == "Apple Inc."
    assert duplicate.status_code == 409
