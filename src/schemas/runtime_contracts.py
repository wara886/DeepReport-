"""Versioned contracts shared by ingestion, retrieval, generation, and delivery."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.data.company_universe import canonicalize_symbol, infer_market_from_symbol
from src.data.source_authority import grade_source_authority
from src.utils.periods import period_match


RUNTIME_CONTRACT_VERSION = "runtime_contracts.v1"


def build_company_identity(
    symbol: str,
    *,
    company_name: str = "",
    company_id: int | str | None = None,
    market: str = "",
) -> dict[str, Any]:
    inferred = infer_market_from_symbol(symbol)
    market_key = _normalize_market(market) or str(inferred.get("market") or "unknown")
    canonical_symbol = canonicalize_symbol(symbol, market=market_key)
    return {
        "schema_version": RUNTIME_CONTRACT_VERSION,
        "company_id": company_id,
        "symbol": canonical_symbol,
        "company_name": str(company_name or "").strip(),
        "market": market_key,
        "exchange": str(inferred.get("exchange") or ""),
        "currency": str(inferred.get("currency") or ""),
        "country_region": str(inferred.get("country_region") or ""),
    }


def build_period_spec(
    target_period: str,
    *,
    source_period: str = "",
    report_date: str = "",
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = _normalize_period(target_period)
    source = _normalize_period(source_period)
    period_type, fiscal_year, fiscal_quarter = _period_parts(target)
    raw_values = dict(raw or {})
    explicit_match = raw_values.get("period_match")
    match: bool | None
    if isinstance(explicit_match, bool):
        match = explicit_match
    elif not target or not source and not report_date:
        match = None
    elif source and source == target:
        date_match = period_match(period=target, report_date=report_date, raw=raw_values)
        match = False if date_match is False else True
    elif source and _periods_definitely_conflict(target, source):
        match = False
    else:
        match_raw = raw_values
        if source:
            source_type, source_year, source_quarter = _period_parts(source)
            if source_year:
                match_raw.setdefault("fiscal_year", source_year)
            if source_type == "quarterly" and source_quarter:
                match_raw.setdefault("fiscal_period", source_quarter)
        match = period_match(period=target, report_date=report_date, raw=match_raw)
    return {
        "schema_version": RUNTIME_CONTRACT_VERSION,
        "target_period": target,
        "source_period": source,
        "period_type": period_type,
        "fiscal_year": fiscal_year,
        "fiscal_quarter": fiscal_quarter,
        "report_date": str(report_date or "")[:10],
        "match": match,
        "match_status": "matched" if match is True else "mismatched" if match is False else "unknown",
    }


def normalize_evidence_record(
    record: dict[str, Any],
    *,
    task_id: str = "",
    run_id: str = "",
    target_period: str = "",
) -> dict[str, Any]:
    data = dict(record)
    metadata = dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {}
    existing_company = dict(data.get("company_identity") or {}) if isinstance(data.get("company_identity"), dict) else {}
    existing_provenance = dict(data.get("provenance") or {}) if isinstance(data.get("provenance"), dict) else {}
    symbol = str(data.get("symbol") or metadata.get("symbol") or "")
    source_period = str(
        data.get("source_period")
        or data.get("period")
        or metadata.get("source_period")
        or metadata.get("report_period")
        or metadata.get("period")
        or ""
    )
    target = str(target_period or metadata.get("target_period") or source_period)
    report_date = str(data.get("report_date") or data.get("notice_date") or metadata.get("report_date") or "")
    company = build_company_identity(
        symbol,
        company_name=str(data.get("company_name") or metadata.get("company_name") or ""),
        company_id=data.get("company_id") or metadata.get("company_id") or existing_company.get("company_id"),
        market=str(data.get("market") or metadata.get("market") or metadata.get("report_market") or ""),
    )
    period = build_period_spec(target, source_period=source_period, report_date=report_date, raw={**metadata, **data})
    authority = _authority_contract(data)
    source_url = _canonical_url(str(data.get("source_url") or data.get("url") or ""))
    title = str(data.get("title") or data.get("source_title") or "").strip()
    content = str(data.get("content") or data.get("text") or "")
    content_hash = sha256(content.encode("utf-8")).hexdigest()
    source_document_id = (
        data.get("source_document_id")
        or metadata.get("source_document_id")
        or data.get("document_id")
        or metadata.get("document_id")
        or metadata.get("accession_number")
    )
    document_seed = {
        "symbol": company["symbol"],
        "source_type": str(data.get("source_type") or "").lower(),
        "source_url": source_url,
        "title": "" if source_document_id else title,
        "source_period": period["source_period"],
        "source_document_id": source_document_id,
    }
    document_key = _stable_key("doc", document_seed)
    locator = {
        "parent_evidence_id": data.get("parent_evidence_id") or data.get("parent_sample_id") or metadata.get("source_evidence_id"),
        "chunk_id": data.get("chunk_id"),
        "section_type": data.get("section_type") or metadata.get("section_type"),
        "page_no": data.get("page_no") or data.get("page") or metadata.get("page"),
        "table_id": data.get("table_id") or metadata.get("table_id"),
        "row_id": data.get("row_id") or metadata.get("row_id"),
        "content_hash": content_hash,
    }
    identity_key = _stable_key("evi", {"document_key": document_key, **locator})
    evidence_id = str(data.get("evidence_id") or data.get("sample_id") or data.get("chunk_id") or identity_key)
    resolved_task_id = str(task_id or data.get("task_id") or metadata.get("task_id") or existing_provenance.get("task_id") or "")
    resolved_run_id = str(run_id or data.get("run_id") or metadata.get("run_id") or existing_provenance.get("run_id") or resolved_task_id)

    data.update(
        {
            "schema_version": "evidence_record.v2",
            "evidence_id": evidence_id,
            "sample_id": str(data.get("sample_id") or evidence_id),
            "symbol": company["symbol"],
            "period": period["source_period"] or period["target_period"],
            "source_period": period["source_period"],
            "source_url": source_url,
            "source_authority": authority["source_authority"],
            "authority_level": authority["authority_level"],
            "authority_score": authority["authority_score"],
            "source_document_type": authority["source_document_type"],
            "identity_key": identity_key,
            "document_key": document_key,
            "content_sha256": content_hash,
            "company_identity": company,
            "period_spec": period,
            "authority": authority,
            "provenance": {
                "schema_version": RUNTIME_CONTRACT_VERSION,
                "task_id": resolved_task_id,
                "run_id": resolved_run_id,
                "source_url": source_url,
                "document_key": document_key,
                "identity_key": identity_key,
            },
        }
    )
    metadata.update(
        {
            "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
            "identity_key": identity_key,
            "document_key": document_key,
            "target_period": period["target_period"],
            "period_match": period["match"],
        }
    )
    data["metadata"] = metadata
    return data


def normalize_metric_candidate(
    row: dict[str, Any],
    *,
    symbol: str = "",
    target_period: str = "",
) -> dict[str, Any]:
    data = dict(row)
    metric_name = str(data.get("metric_name") or data.get("metric_key") or data.get("line_item") or "").strip()
    source_period = str(data.get("source_period") or data.get("period") or "")
    period = build_period_spec(
        target_period,
        source_period=source_period,
        report_date=str(data.get("report_date") or data.get("notice_date") or ""),
        raw=data,
    )
    company = build_company_identity(symbol or str(data.get("symbol") or ""))
    lineage = {
        "source_evidence_id": str(data.get("source_evidence_id") or data.get("evidence_id") or data.get("source_id") or ""),
        "source_table_id": str(data.get("source_table_id") or ""),
        "source_type": str(data.get("source_type") or "").lower(),
    }
    authority = _authority_contract(data)
    metric_id = _stable_key(
        "met",
        {
            "symbol": company["symbol"],
            "metric_name": metric_name,
            "period": period["source_period"],
            **lineage,
        },
    )
    data.update(
        {
            "schema_version": "canonical_metric_candidate.v2",
            "metric_id": metric_id,
            "metric_name": metric_name,
            "source_period": period["source_period"],
            "period_match": data.get("period_match") if data.get("period_match") is not None else period["match"],
            "company_identity": company,
            "period_spec": period,
            "lineage": lineage,
            "authority": authority,
            "value_context": {
                "raw_value": data.get("value"),
                "normalized_value": data.get("normalized_value"),
                "currency": str(data.get("currency") or "").upper(),
                "unit": str(data.get("unit") or ""),
                "scale": str(data.get("scale") or ""),
            },
        }
    )
    return data


def _authority_contract(record: dict[str, Any]) -> dict[str, Any]:
    grade = grade_source_authority(record)
    return {
        "schema_version": RUNTIME_CONTRACT_VERSION,
        "source_authority": str(record.get("source_authority") or grade.get("source_authority") or "unknown"),
        "authority_level": str(record.get("authority_level") or grade.get("authority_level") or "unknown"),
        "authority_score": float(record.get("authority_score") or grade.get("authority_score") or 0.0),
        "trust_level": str(record.get("trust_level") or grade.get("trust_level") or "low"),
        "source_document_type": str(record.get("source_document_type") or grade.get("source_document_type") or "unknown"),
        "allowed_claim_types": list(grade.get("allowed_claim_types") or []),
        "classification_reason": str(grade.get("reason") or ""),
    }


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    candidate = url if "://" in url else f"https://{url}"
    parts = urlsplit(candidate)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def _stable_key(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return f"{prefix}_{sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def _normalize_market(value: str) -> str:
    mapping = {"cn": "cn_a", "a": "cn_a", "a_share": "cn_a", "us": "us", "hk": "hk"}
    return mapping.get(str(value or "").lower().strip(), str(value or "").lower().strip())


def _normalize_period(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").upper())
    annual = re.fullmatch(r"(?:FY)?(20\d{2})(?:FY)?", text)
    if annual:
        return f"FY{annual.group(1)}"
    quarter = re.fullmatch(r"(20\d{2})Q([1-4])", text)
    if quarter:
        return f"{quarter.group(1)}Q{quarter.group(2)}"
    return text


def _period_parts(value: str) -> tuple[str, int | None, str]:
    annual = re.fullmatch(r"FY(20\d{2})", value)
    if annual:
        return "annual", int(annual.group(1)), ""
    quarter = re.fullmatch(r"(20\d{2})Q([1-4])", value)
    if quarter:
        return "quarterly", int(quarter.group(1)), f"Q{quarter.group(2)}"
    return "unknown", None, ""


def _periods_definitely_conflict(target: str, source: str) -> bool:
    target_type, target_year, target_quarter = _period_parts(target)
    source_type, source_year, source_quarter = _period_parts(source)
    if not target_year or not source_year:
        return False
    if target_year != source_year:
        return True
    return target_type == source_type == "quarterly" and target_quarter != source_quarter
