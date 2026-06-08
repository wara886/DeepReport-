"""Official-source evidence inventory and delivery coverage assessment."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List

from src.data.company_universe import infer_market_from_symbol
OFFICIAL_SOURCE_TYPES = {
    "sec_companyfacts",
    "sec_filing",
    "cninfo_announcement",
    "exchange_announcement",
    "hkex_announcement",
    "hkex_annual_report",
    "pdf_section",
    "pdf_statement_table",
}
STATEMENT_TYPES = {"income_statement", "balance_sheet", "cash_flow_statement"}


def build_official_evidence_artifacts(
    records: Iterable[Dict[str, Any]],
    *,
    symbol: str,
    period: str,
    tables: Iterable[Dict[str, Any]] | None = None,
    pdf_manifest: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Build a run-local inventory and conservative evidence sufficiency gate."""

    market = infer_market_from_symbol(symbol).get("market", "unknown")
    records_list = [record for record in records if isinstance(record, dict)]
    official_records = [record for record in records_list if _is_official_record(record)]
    entries = [_manifest_entry(record, symbol=symbol, period=period, market=market) for record in official_records]
    page_anchor_count = sum(1 for entry in entries if entry.get("page") not in (None, ""))
    matching_official = [entry for entry in entries if entry["period_match"] is True]
    mismatched_official = [entry for entry in entries if entry["period_match"] is False]
    unverified_official = [entry for entry in entries if entry["period_match"] is None]
    matching_official_ids = {str(entry.get("evidence_id") or "") for entry in matching_official}
    matching_official_pdf_ids = {
        str(entry.get("evidence_id") or "")
        for entry in matching_official
        if entry.get("page") not in (None, "")
        and str(entry.get("source_type") or "").lower()
        in {"pdf_section", "pdf_statement_table", "hkex_annual_report", "sec_filing"}
    }
    candidate_statement_types = _statement_types(tables or [])
    statement_types = _official_pdf_statement_types(tables or [], allowed_evidence_ids=matching_official_pdf_ids)
    structured_statement_types = _structured_statement_types(tables or [])
    has_official_pdf_three_statements = STATEMENT_TYPES.issubset(statement_types)
    has_structured_three_statements = STATEMENT_TYPES.issubset(structured_statement_types)
    has_formal_delivery_lineage = bool(matching_official) and (
        has_official_pdf_three_statements or has_structured_three_statements
    )
    missing: List[str] = []

    if market in {"cn_a", "hk"}:
        if not matching_official:
            missing.append("period_matched_official_filing")
        delivery_statement_types = statement_types | structured_statement_types
        for statement in sorted(STATEMENT_TYPES - delivery_statement_types):
            missing.append(statement)
        if entries and not page_anchor_count:
            missing.append("official_pdf_page_citations")
    elif market == "us" and _is_annual(period) and not matching_official:
        missing.append("period_matched_official_filing")

    required_market = market in {"cn_a", "hk"}
    coverage_status = "sufficient" if not missing else "insufficient" if required_market else "partial"
    assessment = {
        "schema_version": "evidence_coverage.v1",
        "symbol": symbol,
        "market": market,
        "period": period,
        "period_kind": "fiscal_year" if _is_annual(period) else "quarter" if _is_quarter(period) else "latest",
        "official_record_count": len(entries),
        "period_matched_official_record_count": len(matching_official),
        "period_mismatched_official_record_count": len(mismatched_official),
        "period_unverified_official_record_count": len(unverified_official),
        "pdf_page_anchor_count": page_anchor_count,
        "candidate_statement_types": sorted(candidate_statement_types),
        "statement_types": sorted(statement_types),
        "structured_statement_types": sorted(structured_statement_types),
        "has_three_statements": has_official_pdf_three_statements or has_structured_three_statements,
        "has_official_pdf_three_statements": has_official_pdf_three_statements,
        "has_structured_three_statements": has_structured_three_statements,
        "has_formal_delivery_lineage": has_formal_delivery_lineage,
        "missing_requirements": missing,
        "coverage_status": coverage_status,
        "degrade_required": bool(required_market and missing),
        "policy": "A/H delivery claims require period-matched official evidence plus official-PDF or accepted structured three-statement lineage.",
    }
    return {
        "official_evidence_manifest": {
            "schema_version": "official_evidence_manifest.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "market": market,
            "period": period,
            "records": entries,
            "pdf_manifest": [dict(row) for row in (pdf_manifest or []) if isinstance(row, dict)],
        },
        "evidence_coverage": assessment,
    }


def archive_official_evidence_manifest(
    manifest: Dict[str, Any],
    root: str | Path = "data/evidence_archive",
    source_records: Iterable[Dict[str, Any]] | None = None,
) -> str:
    """Persist manifest and source-text snapshots under a versioned official-evidence path."""

    market = _safe_part(manifest.get("market") or "unknown")
    symbol = _safe_part(manifest.get("symbol") or "unknown")
    period = _safe_part(manifest.get("period") or "latest")
    generated_at = str(manifest.get("generated_at") or datetime.now(timezone.utc).isoformat())
    version = hashlib.sha256(
        json.dumps(manifest.get("records", []), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    target = Path(root) / market / symbol / period / f"{generated_at[:10]}_{version}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    archived_records_path = ""
    official_ids = {
        str(record.get("evidence_id") or "")
        for record in manifest.get("records", [])
        if isinstance(record, dict) and str(record.get("evidence_id") or "")
    }
    archived_records = [
        dict(record)
        for record in (source_records or [])
        if isinstance(record, dict)
        and str(record.get("evidence_id") or record.get("sample_id") or "") in official_ids
    ]
    if archived_records:
        records_target = target.with_name(f"{target.stem}_records.jsonl")
        records_target.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False, default=str) for record in archived_records) + "\n",
            encoding="utf-8",
        )
        archived_records_path = str(records_target)
    manifest["archive_version"] = version
    manifest["archived_records_path"] = archived_records_path
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(target)


def _manifest_entry(record: Dict[str, Any], *, symbol: str, period: str, market: str) -> Dict[str, Any]:
    metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
    content = str(record.get("content") or record.get("snippet") or "")
    page = metadata.get("page") or metadata.get("page_number") or record.get("page") or record.get("page_number") or ""
    source_period = str(record.get("period") or metadata.get("period") or "")
    return {
        "evidence_id": str(record.get("evidence_id") or record.get("sample_id") or ""),
        "symbol": str(record.get("symbol") or symbol),
        "market": market,
        "period": source_period,
        "requested_period": period,
        "period_match": _matches_period(source_period, period),
        "source_type": str(record.get("source_type") or ""),
        "source_url": str(record.get("source_url") or ""),
        "publish_time": str(record.get("publish_time") or ""),
        "provider": str(metadata.get("provider") or ""),
        "page": page,
        "extraction_method": str(metadata.get("extraction_method") or ""),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "parse_status": "parsed" if content else "metadata_only",
    }


def _is_official_record(record: Dict[str, Any]) -> bool:
    source_type = str(record.get("source_type") or "").lower()
    authority = str(record.get("source_authority") or "").lower()
    url = str(record.get("source_url") or "").lower()
    return (
        source_type in OFFICIAL_SOURCE_TYPES
        or authority in {"official", "official_statistics"}
        or any(domain in url for domain in ("sec.gov", "cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk"))
    )


def _statement_types(tables: Iterable[Dict[str, Any]], allowed_evidence_ids: set[str] | None = None) -> set[str]:
    found: set[str] = set()
    for table in tables:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows", []) if isinstance(table.get("rows"), list) else []
        if allowed_evidence_ids is not None and not _table_has_allowed_source(table, rows, allowed_evidence_ids):
            continue
        table_type = str(table.get("table_type") or table.get("statement") or "").lower()
        if table_type in STATEMENT_TYPES:
            found.add(table_type)
        for row in rows:
            statement = str(row.get("statement") or "").lower() if isinstance(row, dict) else ""
            if statement in STATEMENT_TYPES:
                found.add(statement)
    return found


def _table_has_allowed_source(table: Dict[str, Any], rows: List[Any], allowed_evidence_ids: set[str]) -> bool:
    source_ids = {
        str(table.get("source_evidence_id") or table.get("evidence_id") or ""),
        *{
            str(row.get("source_evidence_id") or row.get("evidence_id") or "")
            for row in rows
            if isinstance(row, dict)
        },
    }
    return bool({item for item in source_ids if item} & allowed_evidence_ids)


def _structured_statement_types(tables: Iterable[Dict[str, Any]]) -> set[str]:
    accepted_source_types = {
        "eastmoney_financials",
        "hk_financials",
        "sec_companyfacts",
        "third_party_structured",
        "financial_statement_metrics",
    }
    found: set[str] = set()
    for table in tables:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows", []) if isinstance(table.get("rows"), list) else []
        table_source = str(table.get("source_type") or "").lower()
        row_source_types = {
            str(row.get("source_type") or "").lower()
            for row in rows
            if isinstance(row, dict)
        }
        if table_source not in accepted_source_types and not (row_source_types & accepted_source_types):
            continue
        found |= _statement_types([table])
    return found


def _official_pdf_statement_types(
    tables: Iterable[Dict[str, Any]],
    allowed_evidence_ids: set[str] | None = None,
) -> set[str]:
    pdf_source_types = {"pdf_statement_table", "annual_report_pdf_table", "filing_pdf_table"}
    found: set[str] = set()
    for table in tables:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows", []) if isinstance(table.get("rows"), list) else []
        if allowed_evidence_ids is not None and not _table_has_allowed_source(table, rows, allowed_evidence_ids):
            continue
        source_types = {str(table.get("source_type") or "").lower()}
        source_types.update(
            str(row.get("source_type") or "").lower()
            for row in rows
            if isinstance(row, dict)
        )
        has_page_anchor = bool(table.get("page") or table.get("page_number")) or any(
            bool(row.get("page") or row.get("page_number"))
            for row in rows
            if isinstance(row, dict)
        )
        has_linked_pdf_anchor = allowed_evidence_ids is not None and _table_has_allowed_source(
            table, rows, allowed_evidence_ids
        )
        if not has_page_anchor and not has_linked_pdf_anchor and not (source_types & pdf_source_types):
            continue
        found |= _statement_types([table])
    return found


def _matches_period(source_period: str, target_period: str) -> bool | None:
    if not target_period or not source_period:
        return None
    if source_period.upper() == target_period.upper():
        return True
    target_key = _period_key(target_period)
    source_key = _period_key(source_period)
    if target_key is None:
        return None
    if source_key is None:
        return None
    return target_key == source_key


def _period_key(period: str) -> tuple[str, str, str] | tuple[str, str] | None:
    text = str(period or "").strip().upper()
    annual = re.search(r"(?:FY|ANNUAL)\s*(20\d{2})|(20\d{2})\s*(?:FY|ANNUAL)", text)
    if annual:
        return "fiscal_year", str(annual.group(1) or annual.group(2))
    quarter = re.search(r"(20\d{2})\s*Q([1-4])", text)
    if quarter:
        return "quarter", quarter.group(1), f"Q{quarter.group(2)}"
    return None


def _is_annual(period: str) -> bool:
    return bool(re.search(r"(?:FY|ANNUAL)\s*20\d{2}|20\d{2}\s*(?:FY|ANNUAL)", str(period).upper()))


def _is_quarter(period: str) -> bool:
    return bool(re.search(r"20\d{2}Q[1-4]", str(period).upper()))


def _safe_part(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_").lower() or "unknown"
