from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DataSource
from src.search.search_manager import SearchManager
from src.services.datasource_service import DataSourceService


def test_searchmanager_registered_engines_seed_datasource_rows(temp_db_engine, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")
    service = DataSourceService(
        session_factory=lambda: Session(temp_db_engine),
        search_manager_factory=SearchManager.with_local_sources,
    )

    seeded = service.seed_registered_sources()
    seeded_again = service.seed_registered_sources()

    engine_names = SearchManager.with_local_sources().engine_names()
    assert seeded["source_keys"] == engine_names
    assert seeded["created"] == len(engine_names)
    assert seeded_again["created"] == 0

    with Session(temp_db_engine) as session:
        rows = session.scalars(select(DataSource).order_by(DataSource.source_key)).all()

    assert [row.source_key for row in rows] == engine_names
    assert all(row.config_json["registered_by"] == "SearchManager" for row in rows)
    missing_credentials = {row.source_key for row in rows if not row.enabled}
    assert missing_credentials == {"serper", "tavily"}
    assert all(row.credential_status == "missing" for row in rows if row.source_key in missing_credentials)
    assert {row.source_key: row.trust_level for row in rows}["sec_edgar"] == "official"
    assert {row.source_key: row.source_type for row in rows}["yahoo_finance"] == "market_data"


def test_seed_reconciles_stale_configured_credentials(temp_db_engine, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY", "")
    service = DataSourceService(
        session_factory=lambda: Session(temp_db_engine),
        search_manager_factory=SearchManager.with_local_sources,
    )
    service.seed_registered_sources()
    with Session(temp_db_engine) as session:
        tavily = session.scalar(select(DataSource).where(DataSource.source_key == "tavily"))
        tavily.credential_status = "configured"
        tavily.enabled = True
        session.commit()

    result = service.seed_registered_sources()

    with Session(temp_db_engine) as session:
        tavily = session.scalar(select(DataSource).where(DataSource.source_key == "tavily"))
        assert tavily.credential_status == "missing"
        assert tavily.enabled is False
    assert result["reconciled"] >= 1


def test_searchmanager_registered_engines_seed_workspace_scoped_sources(temp_db_engine):
    service = DataSourceService(
        session_factory=lambda: Session(temp_db_engine),
        search_manager_factory=SearchManager.with_local_sources,
    )

    from src.services.workspace_service import WorkspaceService

    workspace = WorkspaceService(session_factory=lambda: Session(temp_db_engine)).create_workspace(
        {"name": "美股投研", "slug": "us-research", "market": "US"}
    )
    seeded = service.seed_registered_sources(workspace_ref=workspace["slug"])
    global_seeded = service.seed_registered_sources()

    assert seeded["created"] == len(SearchManager.with_local_sources().engine_names())
    assert global_seeded["created"] == len(SearchManager.with_local_sources().engine_names())

    workspace_sources = service.list_sources(workspace_ref=workspace["id"])
    global_sources = service.list_sources()

    assert workspace_sources["total"] == len(SearchManager.with_local_sources().engine_names())
    assert global_sources["total"] == len(SearchManager.with_local_sources().engine_names()) * 2


def test_searchmanager_filters_unlabelled_cross_symbol_evidence():
    manager = SearchManager()

    def fixture_engine(**_):
        return {
            "hits": [
                {"evidence_id": "target", "symbol": "AAPL", "title": "Apple filing", "content": "AAPL revenue"},
                {"evidence_id": "leak", "symbol": "TSLA", "title": "Tesla filing", "content": "TSLA revenue"},
                {
                    "evidence_id": "peer",
                    "symbol": "MSFT",
                    "context_role": "peer",
                    "title": "Peer benchmark",
                    "content": "MSFT benchmark",
                },
            ],
            "meta": {},
        }

    manager.register_engine("fixture", fixture_engine)
    payload = manager.search("technology revenue", engines=["fixture"], symbol="AAPL")

    ids = {item["result_id"] for item in payload["hits"]}
    assert ids == {"target", "peer"}
    assert payload["meta"]["cross_symbol_filtered_count"] == 1
