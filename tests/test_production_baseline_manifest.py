import sqlite3

from scripts.build_production_baseline_manifest import build_manifest


def test_manifest_separates_production_prefixes_from_historical_tasks(tmp_path):
    database = tmp_path / "workbench.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "create table report_tasks (task_id text, symbol text, period text, status text, "
            "current_stage text, quality_score real, created_at text)"
        )
        connection.executemany(
            "insert into report_tasks values (?, ?, ?, ?, ?, ?, ?)",
            [
                ("audit-current-msft-fy2024", "MSFT", "FY2024", "quality_failed", "quality_failed", 0.72, "2"),
                ("stage7c-msft-fy2024", "MSFT", "FY2024", "quality_failed", "quality_failed", 0.975, "1"),
                ("production-baseline-aapl-fy2024", "AAPL", "FY2024", "completed", "completed", 0.91, "3"),
            ],
        )
        connection.commit()

    manifest = build_manifest(
        database_path=database,
        repository_root=tmp_path,
        production_prefixes=("audit-current-", "production-baseline-"),
    )

    assert manifest["database"]["production_task_counts"] == {"completed": 1, "quality_failed": 1}
    assert manifest["database"]["status_counts"]["quality_failed:quality_failed"] == 2
    assert "stage7c-msft-fy2024" in {item["task_id"] for item in manifest["database"]["recent_tasks"]}


def test_manifest_is_read_only_when_database_is_missing(tmp_path):
    manifest = build_manifest(database_path=tmp_path / "missing.sqlite", repository_root=tmp_path)
    assert manifest["database"]["exists"] is False
    assert manifest["database"]["status_counts"] == {}
    assert manifest["production_path"]["runtime"] == "langgraph"
