from sqlalchemy import inspect

from src.db.init_db import init_db, reset_db
from src.db.models import Base
from src.db.session import configure_session, create_engine_for_url, get_database_url


def test_init_db_creates_p0_tables(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'finsight.db'}"
    engine = init_db(database_url)

    table_names = set(inspect(engine).get_table_names())

    assert table_names == set(Base.metadata.tables)
    assert {
        "companies",
        "workspaces",
        "workspace_companies",
        "documents",
        "document_processing_steps",
        "evidence_items",
        "report_tasks",
        "report_task_events",
        "report_artifacts",
        "report_claims",
        "claim_evidence",
        "review_records",
    }.issubset(table_names)


def test_reset_db_recreates_tables(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'reset.db'}"
    engine = init_db(database_url)

    with engine.begin() as conn:
        conn.exec_driver_sql("drop table review_records")

    assert "review_records" not in inspect(engine).get_table_names()

    reset_db(engine=engine)

    assert "review_records" in inspect(engine).get_table_names()


def test_configure_session_uses_explicit_sqlite_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'session.db'}"
    engine = create_engine_for_url(database_url)

    configured = configure_session(engine=engine)

    assert configured is engine
    assert get_database_url(database_url) == database_url


def test_default_database_url_is_local_sqlite(monkeypatch):
    monkeypatch.delenv("FINSIGHT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert get_database_url() == "sqlite:///data/finsight_workbench.db"
