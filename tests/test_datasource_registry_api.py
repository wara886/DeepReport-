from fastapi.testclient import TestClient
from sqlalchemy import select

from src.app.api_fastapi import create_fastapi_app
from src.db.models import DataSource
from src.search.search_manager import SearchManager
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'datasources.db'}",
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


def test_datasource_registry_seed_list_toggle_and_health(tmp_path):
    with build_client(tmp_path) as client:
        seeded = client.post("/api/data-sources/seed", json={})
        listed = client.get("/api/data-sources")
        sec = client.get("/api/data-sources/sec_edgar")
        disabled = client.post("/api/data-sources/sec_edgar/enable", json={"enabled": False})
        health = client.post("/api/data-sources/sec_edgar/health", json={"last_status": "failed", "last_error": "rate limited"})
        enabled_filter = client.get("/api/data-sources", params={"enabled": False})

    assert seeded.status_code == 200
    assert "sec_edgar" in seeded.json()["source_keys"]
    assert listed.status_code == 200
    assert listed.json()["total"] >= 8
    sec_body = sec.json()
    assert sec_body["name"] == "美国证监会年报"
    assert sec_body["source_type"] == "official_filing"
    assert sec_body["credential_status"] == "not_required"

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert health.status_code == 200
    assert health.json()["last_status"] == "failed"
    assert health.json()["last_error"] == "rate limited"
    assert any(item["source_key"] == "sec_edgar" for item in enabled_filter.json()["items"])


def test_datasource_registry_create_workspace_scoped_source(tmp_path):
    with build_client(tmp_path) as client:
        workspace = client.post("/api/workspaces", json={"name": "港股投研", "slug": "hk-research", "market": "HK"})
        created = client.post(
            "/api/data-sources",
            json={
                "workspace_id": workspace.json()["id"],
                "name": "自定义港股公告源",
                "source_key": "custom_hk_news",
                "source_type": "official_announcement",
                "market_scope": ["HK"],
                "trust_level": "official",
                "credential_status": "configured",
                "config": {"base_url": "https://example.com"},
            },
        )
        duplicate = client.post("/api/data-sources", json={"workspace_id": workspace.json()["id"], "source_key": "custom_hk_news"})
        workspace_sources = client.get("/api/data-sources", params={"workspace_id": workspace.json()["id"]})

    assert created.status_code == 201
    body = created.json()
    assert body["workspace_name"] == "港股投研"
    assert body["market_scope"] == ["HK"]
    assert body["config"]["base_url"] == "https://example.com"
    assert duplicate.status_code == 409
    assert workspace_sources.json()["total"] == 1


def test_searchmanager_registered_sources_are_seedable():
    engine_names = SearchManager.with_local_sources().engine_names()

    assert "sec_edgar" in engine_names
    assert "yahoo_finance" in engine_names
    assert "cninfo_announcements" in engine_names
    assert "hkex_announcements" in engine_names


def test_seed_disables_sources_with_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")
    with build_client(tmp_path) as client:
        client.post("/api/data-sources/seed", json={})
        tavily = client.get("/api/data-sources/tavily").json()
        enable = client.post("/api/data-sources/tavily/enable", json={"enabled": True})
        fake_healthy = client.post("/api/data-sources/sec_edgar/health", json={"last_status": "success"})
        verified_healthy = client.post(
            "/api/data-sources/sec_edgar/health",
            json={"last_status": "success", "verified": True},
        )

    assert tavily["credential_status"] == "missing"
    assert tavily["configured"] is False
    assert tavily["enabled"] is False
    assert tavily["operational"] is False
    assert enable.status_code == 409
    assert fake_healthy.status_code == 409
    assert verified_healthy.status_code == 200


def test_seed_reconciles_legacy_enabled_source_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    with build_client(tmp_path) as client:
        client.post("/api/data-sources/seed", json={})
        service = client.app.state.datasource_service
        with service.session_factory() as session:
            tavily = session.scalar(select(DataSource).where(DataSource.source_key == "tavily"))
            tavily.enabled = True
            tavily.credential_status = "required"
            session.commit()
        reconciled = client.post("/api/data-sources/seed", json={})
        current = client.get("/api/data-sources/tavily").json()

    assert reconciled.json()["reconciled"] == 1
    assert current["credential_status"] == "missing"
    assert current["enabled"] is False


def test_verified_search_run_updates_datasource_health_without_manual_marking(tmp_path):
    with build_client(tmp_path) as client:
        client.post("/api/data-sources/seed", json={})
        service = client.app.state.datasource_service
        result = service.record_search_run(
            task_id="task-health-1",
            search_meta={
                "engine_meta": {
                    "sec_edgar": {"mode": "sec_companyfacts", "hit_count": 2, "duration_ms": 120},
                    "independent_macro": {
                        "mode": "independent_macro",
                        "record_count": 4,
                        "failure_reason": "partial_source_failures",
                        "duration_ms": 800,
                    },
                    "yahoo_finance": {"mode": "yahoo_finance", "result_count": 0, "failure_reason": "timeout"},
                }
            },
        )
        sec = client.get("/api/data-sources/sec_edgar").json()
        macro = client.get("/api/data-sources/independent_macro").json()
        yahoo = client.get("/api/data-sources/yahoo_finance").json()

    assert result["updated"] == 3
    assert sec["last_status"] == "success"
    assert sec["operational"] is True
    assert sec["metadata"]["last_verified_run"]["task_id"] == "task-health-1"
    assert macro["last_status"] == "partial"
    assert macro["last_error"] == "partial_source_failures"
    assert yahoo["last_status"] == "failed"
    assert yahoo["last_error"] == "timeout"
