"""Database initialization helpers."""

from __future__ import annotations

import argparse

from sqlalchemy.engine import Engine

from src.db.models import Base
from src.db.session import create_engine_for_url


def init_db(database_url: str | None = None, *, engine: Engine | None = None) -> Engine:
    """Create all P0 database tables and return the engine used."""

    target_engine = engine or create_engine_for_url(database_url)
    Base.metadata.create_all(bind=target_engine)
    return target_engine


def reset_db(database_url: str | None = None, *, engine: Engine | None = None) -> Engine:
    """Drop and recreate all P0 database tables.

    This is intended for local development and tests, not production migrations.
    """

    target_engine = engine or create_engine_for_url(database_url)
    Base.metadata.drop_all(bind=target_engine)
    Base.metadata.create_all(bind=target_engine)
    return target_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the FinSight workbench database.")
    parser.add_argument("--database-url", default=None, help="Database URL. Defaults to env configuration.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate tables before returning.")
    args = parser.parse_args()

    if args.reset:
        reset_db(args.database_url)
    else:
        init_db(args.database_url)


if __name__ == "__main__":
    main()
