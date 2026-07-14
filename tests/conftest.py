import pytest

from src.db.init_db import init_db
from src.db.session import SessionLocal, configure_session


@pytest.fixture(autouse=True)
def isolate_test_vector_db(tmp_path, monkeypatch):
    """Keep retrieval tests from mutating the developer's persistent Chroma DB."""

    monkeypatch.setenv("FINSIGHT_VECTOR_DB_PATH", str(tmp_path / "vector_db"))


@pytest.fixture
def temp_db_engine(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'finsight_test.db'}")
    configure_session(engine=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def temp_db_session(temp_db_engine):
    with SessionLocal() as session:
        yield session
