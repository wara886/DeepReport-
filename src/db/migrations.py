"""Small idempotent schema migrations for local workbench databases."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrate_schema(engine: Engine) -> list[str]:
    """Apply lightweight additive migrations needed by the current models.

    The project currently uses SQLite by default, while tests often create fresh
    schemas from metadata.  ``create_all`` will not add columns to existing
    tables, so this function repairs older local databases without dropping data.
    """

    applied: list[str] = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "documents" in tables:
        applied.extend(
            _add_missing_columns(
                engine,
                "documents",
                {
                    "content": "TEXT NOT NULL DEFAULT ''",
                },
            )
        )
    if "financial_facts" in tables:
        applied.extend(
            _add_missing_columns(
                engine,
                "financial_facts",
                {
                    "normalized_value": "FLOAT",
                    "period_basis": "VARCHAR(16)",
                    "source_period": "VARCHAR(64)",
                    "authority_level": "VARCHAR(32) NOT NULL DEFAULT 'llm_inferred'",
                    "fact_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
                    "usable_for_formal_report": "BOOLEAN NOT NULL DEFAULT 0",
                },
            )
        )
    return applied


def _add_missing_columns(engine: Engine, table_name: str, columns: dict[str, str]) -> list[str]:
    existing = {column["name"] for column in inspect(engine).get_columns(table_name)}
    statements = [
        (column_name, ddl)
        for column_name, ddl in columns.items()
        if column_name not in existing
    ]
    if not statements:
        return []

    applied: list[str] = []
    with engine.begin() as conn:
        for column_name, ddl in statements:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
            applied.append(f"{table_name}.{column_name}")
    return applied
