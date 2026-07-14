import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from src.app.api_fastapi import create_fastapi_app
from src.db.init_db import init_db
from src.services.report_task_service import ReportTaskService


def test_init_db_merges_duplicate_companies_and_backfills_legacy_task_bindings(tmp_path):
    db_path = tmp_path / "binding_repair.db"
    engine = init_db(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO companies (name, symbol, market, created_at) VALUES ('Apple old', 'AAPL', NULL, CURRENT_TIMESTAMP)")
        old_id = conn.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()
        conn.exec_driver_sql("INSERT INTO companies (name, symbol, market, created_at) VALUES ('Apple', 'AAPL', 'US', CURRENT_TIMESTAMP)")
        canonical_id = conn.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()
        conn.exec_driver_sql(
            "INSERT INTO report_tasks (task_id, symbol, period, report_type, status, company_id, created_at) "
            "VALUES ('legacy-unbound', 'AAPL', 'FY2024', 'equity_research', 'queued', NULL, CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "INSERT INTO report_tasks (task_id, symbol, period, report_type, status, company_id, created_at) "
            "VALUES ('legacy-new-company', '0700.HK', 'FY2024', 'equity_research', 'queued', NULL, CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "INSERT INTO documents (company_id, title, content, parse_status, created_at) "
            "VALUES (?, 'Legacy', '', 'parsed', CURRENT_TIMESTAMP)",
            (old_id,),
        )

    init_db(engine=engine)

    with engine.connect() as conn:
        companies = conn.exec_driver_sql("SELECT id FROM companies WHERE symbol = 'AAPL'").all()
        task = conn.exec_driver_sql("SELECT workspace_id, company_id FROM report_tasks WHERE task_id = 'legacy-unbound'").one()
        document_company = conn.exec_driver_sql("SELECT company_id FROM documents WHERE title = 'Legacy'").scalar_one()
        new_company = conn.exec_driver_sql("SELECT symbol, market FROM companies WHERE symbol = '0700.HK'").one()
    assert companies == [(canonical_id,)]
    assert task.workspace_id is not None
    assert task.company_id == canonical_id
    assert document_company == canonical_id
    assert new_company == ("0700.HK", "HK")


def test_init_db_migrates_legacy_sqlite_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_sqlite(db_path)

    engine = init_db(f"sqlite:///{db_path}")

    columns = {
        table: {column["name"] for column in inspect(engine).get_columns(table)}
        for table in ("documents", "financial_facts")
    }
    assert "content" in columns["documents"]
    assert {
        "normalized_value",
        "period_basis",
        "source_period",
        "authority_level",
        "fact_status",
        "usable_for_formal_report",
    }.issubset(columns["financial_facts"])


def test_legacy_sqlite_smoke_covers_document_fact_import_and_task_analysis(tmp_path):
    db_path = tmp_path / "legacy_smoke.db"
    _create_legacy_sqlite(db_path)
    database_url = f"sqlite:///{db_path}"
    service = ReportTaskService(
        database_url=database_url,
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

    with TestClient(app) as client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "legacy-smoke-task", "symbol": "AAPL", "period": "FY2026"},
        )
        imported = client.post(
            "/api/manual-import",
            json={
                "import_type": "text",
                "title": "Legacy smoke import",
                "symbol": "AAPL",
                "company_name": "Apple Inc.",
                "period": "FY2026",
                "content": "Apple FY2026 revenue increased 12% and operating cash flow improved.",
            },
        )
        documents = client.get("/api/documents", params={"limit": 5})
        facts = client.get("/api/financial-facts", params={"limit": 5})
        analysis = client.get("/api/report-tasks/legacy-smoke-task/analysis")

    assert created.status_code == 201
    assert imported.status_code in {200, 201}
    assert imported.json()["document"]["parse_status"] == "parsed"
    assert documents.status_code == 200
    assert facts.status_code == 200
    assert analysis.status_code == 200


def _create_legacy_sqlite(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                symbol VARCHAR(64),
                market VARCHAR(64),
                industry VARCHAR(255),
                aliases JSON,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                datasource_id INTEGER,
                batch_id VARCHAR(128),
                title VARCHAR(512) NOT NULL,
                doc_type VARCHAR(64),
                report_period VARCHAR(64),
                source_url TEXT,
                file_path TEXT,
                content_hash VARCHAR(128),
                parse_status VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE UNIQUE INDEX uq_documents_content_hash ON documents(content_hash);
            CREATE TABLE financial_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                evidence_item_id INTEGER,
                metric_name VARCHAR(255) NOT NULL,
                metric_type VARCHAR(64),
                value FLOAT NOT NULL,
                unit VARCHAR(64),
                currency VARCHAR(16),
                scale VARCHAR(32),
                period VARCHAR(64) NOT NULL,
                fiscal_year INTEGER,
                source_url TEXT,
                confidence FLOAT,
                review_status VARCHAR(32) NOT NULL,
                metadata JSON,
                created_at DATETIME NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
