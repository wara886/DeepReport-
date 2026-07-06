"""Session and engine helpers for SQLite/PostgreSQL deployments."""

from __future__ import annotations

from collections.abc import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DATABASE_URL_ENV_VARS = ("FINSIGHT_DATABASE_URL", "DATABASE_URL")

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, class_=Session)
_engine: Engine | None = None


def get_database_url(database_url: str | None = None) -> str:
    """Resolve the database URL from an explicit value, env vars, or production default."""

    if database_url:
        return database_url
    for env_var in DATABASE_URL_ENV_VARS:
        value = os.getenv(env_var)
        if value:
            return value
    return DEFAULT_DATABASE_URL


def create_engine_for_url(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine with SQLite/PostgreSQL-friendly defaults."""

    resolved_url = get_database_url(database_url)
    url = make_url(resolved_url)
    kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": True}

    if url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}

    return create_engine(resolved_url, **kwargs)


def configure_session(database_url: str | None = None, *, engine: Engine | None = None) -> Engine:
    """Bind the process-wide session factory to an engine."""

    global _engine
    _engine = engine or create_engine_for_url(database_url)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> Engine:
    """Return the configured engine, creating it from environment configuration if needed."""

    global _engine
    if _engine is None:
        _engine = configure_session()
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Yield a request-scoped SQLAlchemy session."""

    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
