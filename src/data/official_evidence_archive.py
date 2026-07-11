"""Official-source evidence inventory and delivery coverage assessment."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List

from src.data.company_universe import infer_market_from_symbol
from src.data.evidence_intake_gate import evidence_ids, filter_evidence_records, rejection_record

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
    input_record_count = len(records_list)
    parent_records = [record for record in records_list if not _source_parent_evidence_id(record)]
    child_records = [record for record in records_list if _source_parent_evidence_id(record)]
    parent_records, intake_rejections = filter_evidence_records(
        parent_records,
        symbol=symbol,
        period=period,
        stage="official_evidence_manifest",
    )
    child_records, child_rejections = filter_evidence_records(
        child_records,
        symbol=symbol,
        period=period,
        stage="official_evidence_manifest",
        trusted_parent_evidence_ids=evidence_ids(parent_records),
    )
    intake_rejections.extend(child_rejections)
    records_list = parent_records + child_records
    accepted_ids = evidence_ids(records_list)
    tables_list = [dict(table) for table in (tables or []) if isinstance(table, dict)]
    tables_list, table_rejections = _filter_tables_by_accepted_evidence(
        tables_list,
        accepted_evidence_ids=accepted_ids,
        stage="official_evidence_tables",
    )
    intake_rejections.extend(table_rejections)
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
    candidate_statement_types = _statement_types(tables_list)
    statement_types = _official_pdf_statement_types(tables_list, allowed_evidence_ids=matching_official_pdf_ids)
    structured_statement_types = _structured_statement_types(tables_list)
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

    requires_formal_official_evidence = market in {"us", "cn_a", "hk"} and (
        market in {"cn_a", "hk"} or _is_annual(period)
    )
    formal_delivery_allowed = not (requires_formal_official_evidence and missing)
    coverage_status = "sufficient" if not missing else "insufficient" if requires_formal_official_evidence else "partial"
    blocking_reasons = [_requirement_label(item, market=market) for item in missing]
    recommended_actions = _recommended_actions(missing, market=market)
    assessment = {
        "schema_version": "evidence_coverage.v1",
        "symbol": symbol,
        "market": market,
        "period": period,
        "period_kind": "fiscal_year" if _is_annual(period) else "quarter" if _is_quarter(period) else "latest",
        "official_record_count": len(entries),
        "input_record_count": input_record_count,
        "intake_rejected_count": len(intake_rejections),
        "intake_rejections": intake_rejections,
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
        "required_official_sources": _required_official_sources(market, period),
        "blocking_reasons": blocking_reasons,
        "recommended_actions": recommended_actions,
        "coverage_status": coverage_status,
        "draft_generation_allowed": True,
        "formal_delivery_allowed": formal_delivery_allowed,
        "degrade_required": not formal_delivery_allowed,
        "policy": (
            "Formal delivery for US annual and A/H reports requires period-matched official filings; "
            "A/H reports also require official-PDF or accepted structured three-statement lineage. "
            "Draft generation remains allowed when official evidence is incomplete."
        ),
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
        "official_evidence_backfill_plan": build_official_evidence_backfill_plan(assessment),
    }


def build_official_evidence_backfill_plan(coverage: Dict[str, Any]) -> Dict[str, Any]:
    """Convert official evidence gaps into source-specific acquisition work."""

    market = str(coverage.get("market") or "unknown")
    symbol = str(coverage.get("symbol") or "")
    period = str(coverage.get("period") or "")
    missing = {str(item) for item in coverage.get("missing_requirements", []) if str(item)}
    source_plan = _official_source_plan(market=market, symbol=symbol, period=period)
    tasks: List[Dict[str, Any]] = []
    if "period_matched_official_filing" in missing:
        tasks.append(
            {
                "task_type": "fetch_official_filing",
                "priority": "P0",
                "source_keys": source_plan["source_keys"],
                "query": source_plan["filing_query"],
                "expected_artifacts": ["official PDF/HTML filing", "period metadata", "source_url"],
                "blocks_formal_delivery": True,
            }
        )
    statement_gap = sorted(STATEMENT_TYPES & missing)
    if statement_gap:
        tasks.append(
            {
                "task_type": "extract_financial_statements",
                "priority": "P0",
                "source_keys": source_plan["source_keys"] + source_plan["structured_source_keys"],
                "query": source_plan["statement_query"],
                "missing_statements": statement_gap,
                "expected_artifacts": ["tables.json rows", "statement source lineage", "period match"],
                "blocks_formal_delivery": True,
            }
        )
    if "official_pdf_page_citations" in missing:
        tasks.append(
            {
                "task_type": "parse_pdf_page_anchors",
                "priority": "P1",
                "source_keys": source_plan["source_keys"],
                "query": source_plan["page_anchor_query"],
                "expected_artifacts": ["page number", "section/table anchor", "content_sha256"],
                "blocks_formal_delivery": True,
            }
        )
    return {
        "schema_version": "official_evidence_backfill_plan.v1",
        "symbol": symbol,
        "market": market,
        "period": period,
        "backfill_required": bool(tasks),
        "formal_delivery_allowed_now": bool(coverage.get("formal_delivery_allowed", False)),
        "formal_delivery_allowed_after_backfill": True,
        "tasks": tasks,
        "recommended_actions": list(coverage.get("recommended_actions", [])),
        "notes": (
            "This plan is acquisition guidance only. It must create real evidence records before "
            "formal delivery gates can pass."
        ),
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


def _required_official_sources(market: str, period: str) -> List[str]:
    if market == "us" and _is_annual(period):
        return ["SEC EDGAR 10-K/10-Q or SEC Company Facts matching the requested fiscal period"]
    if market == "cn_a":
        return ["CNINFO or exchange announcement matching the requested period", "three financial statements with official or accepted structured lineage"]
    if market == "hk":
        return ["HKEX annual/interim/results announcement matching the requested period", "three financial statements with official PDF page anchors or accepted structured lineage"]
    return []


def _requirement_label(requirement: str, *, market: str) -> str:
    labels = {
        "period_matched_official_filing": "missing period-matched official filing",
        "income_statement": "missing income statement from official or accepted structured lineage",
        "balance_sheet": "missing balance sheet from official or accepted structured lineage",
        "cash_flow_statement": "missing cash flow statement from official or accepted structured lineage",
        "official_pdf_page_citations": "missing official PDF page citations",
    }
    label = labels.get(str(requirement), str(requirement))
    if market == "us" and requirement == "period_matched_official_filing":
        return "missing period-matched SEC filing or SEC Company Facts"
    return label


def _recommended_actions(missing: Iterable[str], *, market: str) -> List[str]:
    missing_set = {str(item) for item in missing}
    actions: List[str] = []
    if "period_matched_official_filing" in missing_set:
        if market == "us":
            actions.append("Fetch the matching SEC EDGAR filing or SEC Company Facts for this fiscal period.")
        elif market == "cn_a":
            actions.append("Fetch the matching CNINFO or exchange announcement for this fiscal period.")
        elif market == "hk":
            actions.append("Fetch the matching HKEX annual/interim/results announcement for this fiscal period.")
        else:
            actions.append("Fetch a period-matched official filing before formal delivery.")
    statement_gap = sorted(STATEMENT_TYPES & missing_set)
    if statement_gap:
        actions.append("Extract and link the missing financial statements to official evidence before formal delivery.")
    if "official_pdf_page_citations" in missing_set:
        actions.append("Re-parse the official PDF and retain page anchors for cited financial tables.")
    return actions


def _official_source_plan(*, market: str, symbol: str, period: str) -> Dict[str, Any]:
    if market == "hk":
        return {
            "source_keys": ["hkex_announcements", "exchange_announcements"],
            "structured_source_keys": ["hk_financials"],
            "filing_query": f"{symbol} {period} annual report results announcement HKEX",
            "statement_query": f"{symbol} {period} income statement balance sheet cash flow HKEX annual report",
            "page_anchor_query": f"{symbol} {period} HKEX annual report financial statements pages",
        }
    if market == "cn_a":
        return {
            "source_keys": ["cninfo_announcements", "exchange_announcements"],
            "structured_source_keys": ["eastmoney_financials"],
            "filing_query": f"{symbol} {period} 年报 季报 巨潮资讯 交易所公告",
            "statement_query": f"{symbol} {period} 利润表 资产负债表 现金流量表 巨潮资讯",
            "page_anchor_query": f"{symbol} {period} 年报 财务报表 页码 巨潮资讯",
        }
    if market == "us":
        return {
            "source_keys": ["sec_edgar"],
            "structured_source_keys": ["sec_companyfacts"],
            "filing_query": f"{symbol} {period} 10-K 10-Q SEC EDGAR",
            "statement_query": f"{symbol} {period} income statement balance sheet cash flow SEC",
            "page_anchor_query": f"{symbol} {period} SEC filing financial statements pages",
        }
    return {
        "source_keys": ["local_evidence", "serper", "tavily"],
        "structured_source_keys": [],
        "filing_query": f"{symbol} {period} official annual report",
        "statement_query": f"{symbol} {period} financial statements official",
        "page_anchor_query": f"{symbol} {period} annual report financial statements pages",
    }


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


def _source_parent_evidence_id(record: Dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return str(
        record.get("source_evidence_id")
        or metadata.get("source_evidence_id")
        or record.get("parent_evidence_id")
        or metadata.get("parent_evidence_id")
        or ""
    )


def _filter_tables_by_accepted_evidence(
    tables: list[Dict[str, Any]],
    *,
    accepted_evidence_ids: set[str],
    stage: str,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    accepted: list[Dict[str, Any]] = []
    rejected: list[Dict[str, Any]] = []
    for table in tables:
        rows = table.get("rows", []) if isinstance(table.get("rows"), list) else []
        source_ids = {
            str(table.get("source_evidence_id") or table.get("evidence_id") or ""),
            *{
                str(row.get("source_evidence_id") or row.get("evidence_id") or "")
                for row in rows
                if isinstance(row, dict)
            },
        }
        source_ids = {item for item in source_ids if item}
        if source_ids and not (source_ids & accepted_evidence_ids):
            rejected.append(rejection_record(table, reason="table_source_evidence_rejected", stage=stage))
            continue
        accepted.append(table)
    return accepted, rejected


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
