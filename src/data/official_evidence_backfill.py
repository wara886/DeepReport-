"""Execute official-evidence backfill plans against configured search engines."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.data.financial_statement_metrics import build_standard_financial_metrics, build_standard_table_artifacts
from src.data.official_evidence_archive import build_official_evidence_artifacts
from src.data.pdf_artifacts import build_pdf_artifacts
from src.search.search_manager import SearchManager


DEFAULT_ENGINE_BY_SOURCE_KEY = {
    "sec_edgar": "sec_edgar",
    "cninfo_announcements": "cninfo_announcements",
    "exchange_announcements": "exchange_announcements",
    "eastmoney_financials": "eastmoney_financials",
    "hkex_announcements": "hkex_announcements",
    "hk_financials": "hk_financials",
}


def execute_official_evidence_backfill(
    *,
    symbol: str,
    period: str,
    output_dir: str | Path,
    search_manager: SearchManager | None = None,
    existing_records: list[dict[str, Any]] | None = None,
    existing_tables: list[dict[str, Any]] | None = None,
    plan: dict[str, Any] | None = None,
    topk: int = 10,
    pdf_cache_dir: str | Path | None = None,
    max_pdfs: int = 1,
    max_pdf_pages: int = 20,
) -> dict[str, Any]:
    """Run source-specific searches and write official evidence artifacts.

    The executor is best-effort: failed sources are reported in the summary and
    never treated as evidence. Formal delivery remains controlled by the
    rebuilt evidence coverage artifact.
    """

    outputs = Path(output_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    manager = search_manager or SearchManager.with_local_sources()
    seed_records = _list_of_dicts(existing_records) or _read_list(outputs / "evidence.json")
    seed_tables = _list_of_dicts(existing_tables) or _read_list(outputs / "tables.json")
    active_plan = plan or _read_json(outputs / "official_evidence_backfill_plan.json", {})
    if not active_plan:
        active_plan = _plan_from_existing_coverage(outputs)

    attempts: list[dict[str, Any]] = []
    acquired: list[dict[str, Any]] = []
    for task in _list_of_dicts(active_plan.get("tasks")):
        for source_key in _source_keys_for_task(task):
            engine = DEFAULT_ENGINE_BY_SOURCE_KEY.get(source_key)
            if not engine:
                attempts.append(_attempt(source_key=source_key, status="skipped", error="unsupported_source_key"))
                continue
            query = str(task.get("query") or _default_query(symbol=symbol, period=period, source_key=source_key))
            try:
                payload = manager.search(
                    query=query,
                    topk=topk,
                    engines=[engine],
                    symbol=symbol,
                    period=period,
                    enable_remote=True,
                )
            except Exception as exc:
                attempts.append(_attempt(source_key=source_key, status="failed", error=str(exc)))
                continue
            hits = _extract_engine_hits(payload, engine=engine)
            meta = _engine_meta(payload, engine=engine)
            attempts.append(
                _attempt(
                    source_key=source_key,
                    status="success" if hits else "empty",
                    record_count=len(hits),
                    meta=meta,
                )
            )
            acquired.extend(_normalize_records(hits, source_key=source_key, symbol=symbol, period=period))

    merged_records = _merge_records(seed_records, acquired)
    pdf_artifacts = build_pdf_artifacts(
        merged_records,
        cache_dir=pdf_cache_dir or outputs / "pdf_cache",
        max_pdfs=max_pdfs,
        max_pages=max_pdf_pages,
    )
    pdf_records = _pdf_sections_as_evidence_records(pdf_artifacts.get("pdf_sections", []), symbol=symbol, period=period)
    pdf_records.extend(_pdf_tables_as_evidence_records(pdf_artifacts.get("pdf_tables", []), symbol=symbol, period=period))
    merged_records = _merge_records(merged_records, pdf_records)
    structured_tables = build_standard_table_artifacts(merged_records)
    tables = _merge_tables(seed_tables, structured_tables)
    financial_metrics = build_standard_financial_metrics(merged_records)
    official_artifacts = build_official_evidence_artifacts(
        merged_records,
        symbol=symbol,
        period=period,
        tables=tables,
    )
    _write_json(outputs / "evidence.json", merged_records)
    _write_json(outputs / "tables.json", tables)
    _write_json(outputs / "financial_metrics.json", financial_metrics)
    _write_json(outputs / "official_evidence_manifest.json", official_artifacts["official_evidence_manifest"])
    _write_json(outputs / "evidence_coverage.json", official_artifacts["evidence_coverage"])
    _write_json(outputs / "official_evidence_backfill_plan.json", official_artifacts["official_evidence_backfill_plan"])
    _write_json(outputs / "pdf_manifest.json", pdf_artifacts.get("pdf_manifest", []))
    _write_json(outputs / "pdf_sections.json", pdf_artifacts.get("pdf_sections", []))
    summary = {
        "schema_version": "official_evidence_backfill_run.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "period": period,
        "output_dir": str(outputs),
        "input_record_count": len(seed_records),
        "acquired_record_count": len(acquired),
        "merged_record_count": len(merged_records),
        "pdf_record_count": len(pdf_records),
        "pdf_meta": pdf_artifacts.get("meta", {}),
        "table_count": len(tables),
        "attempts": attempts,
        "coverage": official_artifacts["evidence_coverage"],
        "backfill_remaining": official_artifacts["official_evidence_backfill_plan"],
    }
    _write_json(outputs / "official_evidence_backfill_run.json", summary)
    return summary


def execute_official_evidence_backfill_for_run(
    run_dir: str | Path,
    *,
    search_manager: SearchManager | None = None,
    topk: int = 10,
    pdf_cache_dir: str | Path | None = None,
    max_pdfs: int = 1,
    max_pdf_pages: int = 20,
) -> dict[str, Any]:
    outputs = _resolve_outputs_dir(Path(run_dir))
    summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(summary.get("symbol") or summary.get("canonical_symbol") or "").strip()
    period = str(summary.get("period") or "").strip()
    if not symbol or not period:
        raise ValueError("run_summary.json must contain symbol and period")
    return execute_official_evidence_backfill(
        symbol=symbol,
        period=period,
        output_dir=outputs,
        search_manager=search_manager,
        topk=topk,
        pdf_cache_dir=pdf_cache_dir,
        max_pdfs=max_pdfs,
        max_pdf_pages=max_pdf_pages,
    )


def _resolve_outputs_dir(path: Path) -> Path:
    if path.name == "outputs":
        return path
    if (path / "outputs").exists():
        return path / "outputs"
    return path


def _plan_from_existing_coverage(outputs: Path) -> dict[str, Any]:
    coverage = _read_json(outputs / "evidence_coverage.json", {})
    plan = _read_json(outputs / "official_evidence_backfill_plan.json", {})
    return plan if plan else build_official_evidence_artifacts(
        _read_list(outputs / "evidence.json"),
        symbol=str(coverage.get("symbol") or ""),
        period=str(coverage.get("period") or ""),
        tables=_read_list(outputs / "tables.json"),
    )["official_evidence_backfill_plan"]


def _source_keys_for_task(task: dict[str, Any]) -> list[str]:
    return [str(item) for item in task.get("source_keys", []) if str(item).strip()]


def _extract_engine_hits(payload: dict[str, Any], *, engine: str) -> list[dict[str, Any]]:
    hits = payload.get("hits", []) if isinstance(payload, dict) else []
    rows = [dict(item.get("raw") or item) for item in hits if isinstance(item, dict)]
    return [row for row in rows if row]


def _engine_meta(payload: dict[str, Any], *, engine: str) -> dict[str, Any]:
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    engine_meta = meta.get("engine_meta", {}) if isinstance(meta, dict) else {}
    return dict(engine_meta.get(engine) or meta or {})


def _normalize_records(records: list[dict[str, Any]], *, source_key: str, symbol: str, period: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in records:
        row = dict(item)
        row.setdefault("symbol", symbol)
        row.setdefault("period", period)
        row.setdefault("metadata", {})
        if isinstance(row["metadata"], dict):
            row["metadata"].setdefault("source_key", source_key)
            row["metadata"].setdefault("backfilled", True)
        output.append(row)
    return output


def _merge_records(existing: list[dict[str, Any]], acquired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in existing + acquired:
        key = str(row.get("evidence_id") or row.get("sample_id") or row.get("source_url") or row.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _merge_tables(existing: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in existing + generated:
        key = str(row.get("table_id") or row.get("source_evidence_id") or row.get("table_type") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _pdf_sections_as_evidence_records(sections: Any, *, symbol: str, period: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if not isinstance(sections, list):
        return output
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or "")
        snippet = str(section.get("snippet") or "").strip()
        if not section_id or not snippet:
            continue
        evidence_id = f"pdf_section_{section_id}"
        output.append(
            {
                "evidence_id": evidence_id,
                "sample_id": evidence_id,
                "source_type": "pdf_section",
                "title": f"PDF section: {section.get('section_type') or 'unknown'}",
                "source_url": str(section.get("source_url") or ""),
                "publish_time": "",
                "content": snippet,
                "symbol": symbol,
                "period": period,
                "trust_level": "high",
                "metadata": {
                    "section_id": section_id,
                    "section_type": section.get("section_type", ""),
                    "page": section.get("page", ""),
                    "matched_keyword": section.get("matched_keyword", ""),
                    "source_evidence_id": section.get("evidence_id", ""),
                    "extraction_method": section.get("extraction_method", ""),
                },
            }
        )
    return output


def _pdf_tables_as_evidence_records(tables: Any, *, symbol: str, period: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if not isinstance(tables, list):
        return output
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("table_id") or "")
        table_type = str(table.get("table_type") or "")
        rows = table.get("rows") if isinstance(table.get("rows"), list) else []
        if not table_id or not table_type or not rows:
            continue
        evidence_id = f"pdf_table_{table_id}"
        summary = "; ".join(
            f"{row.get('line_item')}={row.get('value')}"
            for row in rows[:8]
            if isinstance(row, dict) and row.get("line_item")
        )
        output.append(
            {
                "evidence_id": evidence_id,
                "sample_id": evidence_id,
                "source_type": "pdf_statement_table",
                "title": f"PDF table: {table_type}",
                "source_url": str(table.get("source_url") or ""),
                "publish_time": "",
                "content": f"{table_type} extracted from PDF page {table.get('page')}: {summary}",
                "symbol": symbol,
                "period": period,
                "trust_level": "high",
                "metadata": {
                    "table_id": table_id,
                    "table_type": table_type,
                    "rows": rows,
                    "raw_rows": table.get("raw_rows", []),
                    "unit": table.get("unit", "raw"),
                    "currency": table.get("currency", ""),
                    "page": table.get("page", ""),
                    "source_evidence_id": table.get("evidence_id", ""),
                    "extraction_method": table.get("extraction_method", ""),
                    "confidence": table.get("confidence", 0.0),
                },
            }
        )
    return output


def _default_query(*, symbol: str, period: str, source_key: str) -> str:
    if source_key.startswith("cninfo"):
        return f"{symbol} {period} 年度报告 巨潮资讯"
    if source_key.startswith("hkex"):
        return f"{symbol} {period} annual report HKEX"
    if source_key == "eastmoney_financials":
        return f"{symbol} {period} 财务报表 东方财富"
    if source_key == "hk_financials":
        return f"{symbol} {period} financial statements"
    return f"{symbol} {period} official filing"


def _attempt(
    *,
    source_key: str,
    status: str,
    record_count: int = 0,
    error: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_key": source_key,
        "status": status,
        "record_count": record_count,
        "error": error,
        "meta": meta or {},
    }


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _read_list(path: Path) -> list[dict[str, Any]]:
    return _list_of_dicts(_read_json(path, []))


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
