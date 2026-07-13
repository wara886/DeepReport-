"""Write a read-only manifest describing the production runtime baseline.

This is intentionally separate from report generation.  It makes historical
SQLite rows and generated runtime artifacts visible without treating them as a
new production run or mutating the database.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Iterable


DEFAULT_PRODUCTION_PREFIXES = ("production-baseline-", "audit-current-")


def build_manifest(
    *,
    database_path: str | Path,
    repository_root: str | Path = ".",
    production_prefixes: Iterable[str] = DEFAULT_PRODUCTION_PREFIXES,
) -> dict[str, Any]:
    """Build a non-mutating manifest from the repository and SQLite database."""

    root = Path(repository_root).resolve()
    db_path = Path(database_path)
    if not db_path.is_absolute():
        db_path = root / db_path
    prefixes = [str(item) for item in production_prefixes if str(item).strip()]
    task_rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    production_counts: dict[str, int] = {}
    if db_path.is_file():
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            for row in connection.execute(
                "select status, current_stage, count(*) as count "
                "from report_tasks group by status, current_stage order by status, current_stage"
            ):
                status = str(row["status"] or "unknown")
                status_counts[f"{status}:{row['current_stage'] or 'unknown'}"] = int(row["count"])
            for row in connection.execute(
                "select task_id, symbol, period, status, current_stage, quality_score "
                "from report_tasks order by created_at desc limit 200"
            ):
                item = dict(row)
                task_rows.append(item)
                task_id = str(item.get("task_id") or "")
                if any(task_id.startswith(prefix) for prefix in prefixes):
                    key = str(item.get("status") or "unknown")
                    production_counts[key] = production_counts.get(key, 0) + 1

    return {
        "schema_version": "production_baseline_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": _git_manifest(root),
        "production_path": {
            "entrypoint": "main.py -> src.app.api_fastapi -> ReportTaskService -> LangGraphReportRuntime",
            "runtime": "langgraph",
            "database": "data/finsight_workbench.db",
            "checkpoint": "data/outputs_user/runtime_checkpoints.sqlite",
            "artifacts": ["data/outputs_user", "data/reports_user", "data/evidence_archive"],
            "vector_store": "data/vector_db",
        },
        "legacy_and_benchmark_paths": [
            "src/app/pipeline.py",
            "src/agents/orchestrator.py",
            "src/agents/collaborative_orchestrator.py",
            "scripts/run_*benchmark*.py",
            "configs/local_*.yaml",
        ],
        "database": {
            "path": str(db_path),
            "exists": db_path.is_file(),
            "status_counts": status_counts,
            "production_task_prefixes": prefixes,
            "production_task_counts": production_counts,
            "recent_tasks": task_rows[:20],
        },
        "scope_rules": {
            "production_metrics_include": "tasks whose id starts with an explicit production prefix",
            "historical_rows": "visible for audit but excluded from the current production baseline",
            "artifacts": "must be associated with task_id and run_id before entering production metrics",
        },
    }


def _git_manifest(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), *args],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(run("status", "--porcelain")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only production baseline manifest")
    parser.add_argument("--database", default="data/finsight_workbench.db")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--production-prefix", action="append", dest="prefixes")
    args = parser.parse_args()
    manifest = build_manifest(
        database_path=args.database,
        repository_root=args.repository_root,
        production_prefixes=args.prefixes or DEFAULT_PRODUCTION_PREFIXES,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "commit": manifest["repository"]["commit"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
