from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'workspace.db'}",
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


def test_workspace_api_create_list_detail_and_stock_pool(tmp_path):
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/workspaces",
            json={
                "name": "AI 投研空间",
                "slug": "ai-research",
                "market": "US",
                "keywords": ["AI", "GPU"],
                "excluded_keywords": ["rumor"],
                "focus_metrics": ["revenue", "gross_margin"],
                "risk_types": ["valuation", "supply_chain"],
                "evidence_threshold": 0.72,
                "quality_gate_threshold": 0.86,
                "default_data_sources": ["sec_edgar", "yahoo_finance"],
                "report_template": "annual_review",
            },
        )
        duplicate = client.post("/api/workspaces", json={"name": "Duplicate", "slug": "ai-research"})
        added = client.post(
            "/api/workspaces/ai-research/companies",
            json={
                "name": "NVIDIA Corporation",
                "symbol": "NVDA",
                "market": "US",
                "industry": "Semiconductors",
                "aliases": ["英伟达", "NVIDIA"],
            },
        )
        listed = client.get("/api/workspaces")
        detail = client.get("/api/workspaces/ai-research")
        companies = client.get("/api/workspaces/ai-research/companies")

    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "ai-research"
    assert body["market"] == "US"
    assert body["focus_metrics"] == ["revenue", "gross_margin"]
    assert body["default_data_sources"] == ["sec_edgar", "yahoo_finance"]

    assert duplicate.status_code == 409
    assert added.status_code == 201
    assert added.json()["symbol"] == "NVDA"
    assert "英伟达" in added.json()["aliases"]

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["active_company_count"] == 1
    assert detail.status_code == 200
    assert detail.json()["companies"][0]["symbol"] == "NVDA"
    assert companies.status_code == 200
    assert companies.json()["items"][0]["name"] == "NVIDIA Corporation"


def test_workspace_company_conflicts_and_missing_workspace(tmp_path):
    with build_client(tmp_path) as client:
        missing = client.post("/api/workspaces/missing/companies", json={"name": "Apple", "symbol": "AAPL"})
        client.post("/api/workspaces", json={"name": "默认投研空间", "slug": "default", "market": "US"})
        first = client.post("/api/workspaces/default/companies", json={"name": "Apple Inc.", "symbol": "AAPL"})
        duplicate = client.post("/api/workspaces/default/companies", json={"name": "Apple Inc.", "symbol": "AAPL"})

    assert missing.status_code == 404
    assert first.status_code == 201
    assert duplicate.status_code == 409
