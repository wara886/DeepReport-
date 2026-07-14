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
    if {"companies", "report_tasks", "workspaces"}.issubset(tables):
        applied.extend(_repair_company_and_task_bindings(engine, tables))
    return applied


def _repair_company_and_task_bindings(engine: Engine, tables: set[str]) -> list[str]:
    """Merge duplicate symbols and bind legacy tasks without dropping business data."""

    applied: list[str] = []
    company_tables = [
        table for table in ("documents", "evidence_items", "financial_facts", "investment_signals", "report_tasks", "workspace_companies")
        if table in tables and "company_id" in {column["name"] for column in inspect(engine).get_columns(table)}
    ]
    with engine.begin() as conn:
        workspace_id = conn.execute(text("SELECT id FROM workspaces WHERE is_active = 1 ORDER BY id LIMIT 1")).scalar()
        unbound_task_count = int(conn.execute(text("SELECT COUNT(*) FROM report_tasks WHERE workspace_id IS NULL")).scalar() or 0)
        if workspace_id is None and unbound_task_count:
            conn.execute(text(
                "INSERT INTO workspaces (name, slug, is_active, created_at) "
                "VALUES ('默认投研空间', 'default-research', 1, CURRENT_TIMESTAMP)"
            ))
            workspace_id = conn.execute(text("SELECT id FROM workspaces WHERE slug = 'default-research'")).scalar()
            applied.append("data.default_workspace")

        rows = conn.execute(text(
            "SELECT id, symbol, market FROM companies WHERE symbol IS NOT NULL AND TRIM(symbol) <> '' "
            "ORDER BY UPPER(TRIM(symbol)), CASE WHEN market IS NULL OR TRIM(market) = '' THEN 1 ELSE 0 END, id"
        )).mappings().all()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(str(row["symbol"]).strip().upper(), []).append(dict(row))
        for symbol, group in grouped.items():
            canonical = group[0]
            canonical_id = int(canonical["id"])
            conn.execute(text("UPDATE companies SET symbol = :symbol WHERE id = :id"), {"symbol": symbol, "id": canonical_id})
            for duplicate in group[1:]:
                duplicate_id = int(duplicate["id"])
                for table in company_tables:
                    conn.execute(text(f"UPDATE {table} SET company_id = :canonical WHERE company_id = :duplicate"), {
                        "canonical": canonical_id,
                        "duplicate": duplicate_id,
                    })
                conn.execute(text("DELETE FROM companies WHERE id = :id"), {"id": duplicate_id})
                applied.append(f"data.company_merge:{duplicate_id}->{canonical_id}")

        if workspace_id is not None:
            conn.execute(text("UPDATE report_tasks SET workspace_id = :workspace WHERE workspace_id IS NULL"), {"workspace": workspace_id})
        task_rows = conn.execute(text(
            "SELECT id, symbol FROM report_tasks WHERE company_id IS NULL AND symbol IS NOT NULL"
        )).mappings().all()
        for task in task_rows:
            company_id = conn.execute(text(
                "SELECT id FROM companies WHERE UPPER(TRIM(symbol)) = UPPER(TRIM(:symbol)) ORDER BY id LIMIT 1"
            ), {"symbol": task["symbol"]}).scalar()
            if company_id is None:
                symbol = str(task["symbol"]).strip().upper()
                conn.execute(text(
                    "INSERT INTO companies (name, symbol, market, created_at) "
                    "VALUES (:name, :symbol, :market, CURRENT_TIMESTAMP)"
                ), {"name": symbol, "symbol": symbol, "market": _market_for_symbol(symbol)})
                company_id = conn.execute(text(
                    "SELECT id FROM companies WHERE UPPER(TRIM(symbol)) = :symbol ORDER BY id LIMIT 1"
                ), {"symbol": symbol}).scalar()
                applied.append(f"data.task_company_created:{symbol}")
            conn.execute(text("UPDATE report_tasks SET company_id = :company WHERE id = :id"), {
                "company": company_id,
                "id": task["id"],
            })
            applied.append(f"data.task_company:{task['id']}")
    return applied


def _market_for_symbol(symbol: str) -> str:
    value = str(symbol or "").upper()
    if value.endswith(".HK"):
        return "HK"
    if value.endswith((".SS", ".SZ", ".SH")) or value[:1] in {"0", "3", "6"} and value[:6].isdigit():
        return "CN"
    return "US"


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
