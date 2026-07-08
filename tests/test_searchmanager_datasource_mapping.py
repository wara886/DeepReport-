from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DataSource
from src.search.search_manager import SearchManager
from src.services.datasource_service import DataSourceService


def test_searchmanager_registered_engines_seed_datasource_rows(temp_db_engine):
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
    assert all(row.enabled for row in rows)
    assert {row.source_key: row.trust_level for row in rows}["sec_edgar"] == "official"
    assert {row.source_key: row.source_type for row in rows}["yahoo_finance"] == "market_data"


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
