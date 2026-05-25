"""Explicit online acquisition for the formal FY2024 frozen benchmark.

This module is deliberately separate from the formal runner. It may contact
configured public sources to prepare local evidence files; the benchmark
execution path consumes only the files subsequently frozen into a snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List
from urllib import parse, request

from src.data.independent_sources import fetch_sec_companyfacts_evidence
from src.data.source_quality import apply_source_quality
from src.evaluation.frozen_snapshot import load_formal_benchmark_config
from src.search.search_manager import cninfo_announcement_search, eastmoney_financials_search


ACQUISITION_MANIFEST_FILENAME = "acquisition_manifest.json"
_SEC_REVENUE_TAGS = {"Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"}
_SEC_CASH_FLOW_TAGS = {
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
}
_CN_TABLE_TYPES = {"income", "balance", "cashflow"}
_HKEX_STOCK_LIST_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"
_HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
_HKEX_BASE_URL = "https://www1.hkexnews.hk"


def stage_formal_evidence(
    config_path: str | Path = "configs/benchmark_formal18_fy2024.yaml",
    source_root: str | Path | None = None,
    data_source_config_path: str | Path = "configs/data_sources.yaml",
    markets: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Acquire period-verified evidence and write local formal staging files."""

    benchmark = load_formal_benchmark_config(config_path)
    period = str(benchmark["period"])
    root = Path(source_root or benchmark.get("snapshot_source_root") or "data/benchmark_sources/fy2024")
    root.mkdir(parents=True, exist_ok=True)
    selected_markets = {str(item).upper() for item in markets or []}
    case_rows: List[Dict[str, Any]] = []
    hk_stock_directory: Dict[str, Dict[str, Any]] | None = None

    for raw_case in benchmark["cases"]:
        case = dict(raw_case)
        market = str(case.get("market") or "").upper()
        if selected_markets and market not in selected_markets:
            case_rows.append(_status_row(case, period, status="not_selected", issues=["market not selected"]))
            continue
        if market == "US":
            records, issues, attempts = _acquire_us_case(case, period, str(data_source_config_path))
        elif market == "CN-A":
            records, issues, attempts = _acquire_cn_a_case(case, period, str(data_source_config_path))
        elif market == "HK":
            try:
                if hk_stock_directory is None:
                    hk_stock_directory = _fetch_hkex_stock_directory()
                records, issues, attempts = _acquire_hk_case(case, period, hk_stock_directory)
            except Exception as exc:
                records, issues, attempts = [], [f"HKEX acquisition failed: {exc}"], [{"source": "hkex_title_search", "status": "fetch_error"}]
        else:
            records, issues, attempts = [], [f"unsupported formal acquisition market: {market}"], []

        evidence_path = root / str(case["case_id"]) / "evidence.jsonl"
        if records:
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )
            status = "staged"
        else:
            status = "blocked"
        row = _status_row(case, period, status=status, issues=issues)
        row.update(
            {
                "record_count": len(records),
                "source_types": sorted({str(item.get("source_type") or "") for item in records}),
                "evidence_path": str(evidence_path) if records else "",
                "attempts": attempts,
                "existing_evidence_preserved": bool(not records and evidence_path.exists()),
            }
        )
        case_rows.append(row)

    staged_count = sum(1 for row in case_rows if row["status"] == "staged")
    manifest = {
        "schema_version": "formal_evidence_acquisition.v1",
        "benchmark_id": str(benchmark.get("id") or ""),
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "network_acquisition": True,
        "case_count": len(case_rows),
        "staged_case_count": staged_count,
        "blocked_case_count": sum(1 for row in case_rows if row["status"] == "blocked"),
        "complete": staged_count == len(case_rows),
        "cases": case_rows,
    }
    (root / ACQUISITION_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _acquire_us_case(case: Dict[str, Any], period: str, data_source_config_path: str) -> tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    symbol = str(case.get("canonical_symbol") or "")
    payload = fetch_sec_companyfacts_evidence(symbol=symbol, period=period, config_path=data_source_config_path)
    attempts = [{"source": "sec_companyfacts", **dict(payload.meta)}]
    records = [_normalize_record(item, symbol, period) for item in payload.hits if isinstance(item, dict)]
    accepted = [item for item in records if _sec_record_has_fy_core_metrics(item, period)]
    if accepted:
        return accepted, [], attempts
    failure = str(payload.meta.get("failure_reason") or "missing FY annual core metrics in SEC companyfacts")
    return [], [failure], attempts


def _acquire_cn_a_case(case: Dict[str, Any], period: str, data_source_config_path: str) -> tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    symbol = str(case.get("canonical_symbol") or "")
    query = f"{symbol} {period} annual report"
    announcement_payload = cninfo_announcement_search(
        query=query,
        symbol=symbol,
        period=period,
        topk=10,
        enable_remote=True,
        data_source_config_path=data_source_config_path,
    )
    financial_payload = eastmoney_financials_search(
        query=query,
        symbol=symbol,
        period=period,
        topk=3,
        enable_remote=True,
        data_source_config_path=data_source_config_path,
    )
    attempts = [
        {"source": "cninfo_announcements", **dict(announcement_payload.get("meta", {}))},
        {"source": "eastmoney_financials", **dict(financial_payload.get("meta", {}))},
    ]
    annual_reports = [
        _normalize_record(item, symbol, period)
        for item in announcement_payload.get("hits", [])
        if isinstance(item, dict) and _is_full_annual_report(item, period)
    ]
    financial_records = [
        _normalize_record(item, symbol, period)
        for item in financial_payload.get("hits", [])
        if isinstance(item, dict) and _is_target_cn_financial_table(item, period)
    ]
    financial_types = {
        str(item.get("metadata", {}).get("table_type") or "")
        for item in financial_records
        if isinstance(item.get("metadata"), dict)
    }
    issues: List[str] = []
    if not annual_reports:
        issues.append("no CNINFO full annual report matched the requested fiscal year")
    if not _CN_TABLE_TYPES.issubset(financial_types):
        issues.append("period-matched income, balance, and cashflow table records are required")
    if issues:
        return [], issues, attempts
    records = annual_reports[:1] + sorted(
        financial_records,
        key=lambda item: str(item.get("metadata", {}).get("table_type") or ""),
    )
    return records, [], attempts


def _acquire_hk_case(case: Dict[str, Any], period: str, stock_directory: Dict[str, Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    symbol = str(case.get("canonical_symbol") or "")
    code = symbol.split(".", 1)[0].zfill(5)
    stock = stock_directory.get(code)
    if not stock:
        return [], ["HKEX active stock code not found"], [{"source": "hkex_title_search", "stock_code": code, "status": "missing_stock_id"}]
    results = _query_hkex_documents(stock_id=str(stock["i"]), period=period)
    matching = [row for row in results if _is_hkex_annual_report(row, code=code, period=period)]
    attempts = [
        {
            "source": "hkex_title_search",
            "stock_code": code,
            "stock_id": str(stock["i"]),
            "stock_name": str(stock.get("n") or ""),
            "result_count": len(results),
            "annual_report_match_count": len(matching),
        }
    ]
    if not matching:
        return [], ["no HKEX FY2024 annual report matched company and period"], attempts
    matching.sort(key=lambda row: str(row.get("DATE_TIME") or ""), reverse=True)
    selected = matching[0]
    relative_url = str(selected.get("FILE_LINK") or "")
    source_url = parse.urljoin(_HKEX_BASE_URL, relative_url)
    extracted = _download_and_extract_hkex_pdf(source_url, period=period)
    attempts[0]["pdf_sha256"] = extracted.get("pdf_sha256", "")
    attempts[0]["extracted_page_count"] = len(extracted.get("pages", []))
    if not extracted.get("content"):
        return [], ["HKEX annual report found but no financial text could be extracted"], attempts
    title = _strip_html(str(selected.get("TITLE") or f"{code} Annual Report"))
    release_time = _hkex_release_date(selected.get("DATE_TIME"))
    digest = hashlib.sha1(f"{code}|{period}|{source_url}".encode("utf-8")).hexdigest()[:10]
    record = {
        "evidence_id": f"{code}_{period}_hkex_annual_report_{digest}",
        "sample_id": f"{code}_{period}_hkex_annual_report_{digest}",
        "symbol": symbol,
        "period": period,
        "source_type": "hkex_annual_report",
        "title": title,
        "source_url": source_url,
        "publish_time": release_time,
        "content": f"HKEX official annual report for {code}, released {release_time}. {extracted['content']}",
        "trust_level": "high",
        "metadata": {
            "provider": "HKEXnews",
            "stock_code": code,
            "stock_id": str(stock["i"]),
            "stock_name": _strip_html(str(selected.get("STOCK_NAME") or stock.get("n") or "")),
            "news_id": str(selected.get("NEWS_ID") or ""),
            "pdf_sha256": str(extracted.get("pdf_sha256") or ""),
            "pdf_page_count": int(extracted.get("page_count", 0) or 0),
            "extracted_pages": list(extracted.get("pages", [])),
            "extraction_method": "pymupdf_financial_passage_selection_v1",
        },
    }
    return [apply_source_quality(record)], [], attempts


def _sec_record_has_fy_core_metrics(record: Dict[str, Any], period: str) -> bool:
    year = _period_year(period)
    metrics = record.get("metadata", {}).get("metrics", {}) if isinstance(record.get("metadata"), dict) else {}
    if not year or not isinstance(metrics, dict):
        return False
    keys = set(metrics)
    core_present = bool(keys & _SEC_REVENUE_TAGS) and "NetIncomeLoss" in keys and bool(keys & _SEC_CASH_FLOW_TAGS)
    annual_rows = all(
        str(metric.get("fy") or "") == year
        and str(metric.get("fp") or "").upper() == "FY"
        and str(metric.get("form") or "").upper() in {"10-K", "10-K/A", "20-F", "20-F/A"}
        for metric in metrics.values()
        if isinstance(metric, dict)
    )
    return bool(metrics) and core_present and annual_rows


def _is_full_annual_report(record: Dict[str, Any], period: str) -> bool:
    title = str(record.get("title") or "")
    year = _period_year(period)
    return year in title and ("年度报告" in title or "年报" in title) and "摘要" not in title


def _is_target_cn_financial_table(record: Dict[str, Any], period: str) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    raw = metadata.get("raw") if isinstance(metadata.get("raw"), dict) else {}
    report_date = str(raw.get("REPORT_DATE") or raw.get("REPORTDATE") or "")
    return str(metadata.get("table_type") or "") in _CN_TABLE_TYPES and report_date.startswith(f"{_period_year(period)}-12-31")


def _fetch_hkex_stock_directory() -> Dict[str, Dict[str, Any]]:
    req = request.Request(_HKEX_STOCK_LIST_URL, headers={"User-Agent": "Mozilla/5.0 DeepReportPlus/0.1"}, method="GET")
    with request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    return {
        str(row.get("c") or "").zfill(5): dict(row)
        for row in payload
        if isinstance(row, dict) and str(row.get("c") or "").strip()
    }


def _query_hkex_documents(stock_id: str, period: str) -> List[Dict[str, Any]]:
    year = _period_year(period)
    query_year = str(int(year) + 1)
    params = {
        "sortDir": "1",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": stock_id,
        "documentType": "-1",
        "fromDate": f"{query_year}0101",
        "toDate": f"{query_year}0630",
        "title": "",
        "searchType": "1",
        "t1code": "40000",
        "t2Gcode": "-2",
        "t2code": "-2",
        "rowRange": "100",
        "lang": "E",
    }
    url = f"{_HKEX_SEARCH_URL}?{parse.urlencode(params)}"
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0 DeepReportPlus/0.1", "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en"}, method="GET")
    with request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = json.loads(str(payload.get("result") or "[]"))
    return [dict(row) for row in rows if isinstance(row, dict)]


def _is_hkex_annual_report(record: Dict[str, Any], code: str, period: str) -> bool:
    title = _strip_html(str(record.get("TITLE") or "")).upper()
    stock_code = _strip_html(str(record.get("STOCK_CODE") or "")).replace(" ", "")
    year = _period_year(period)
    return stock_code.startswith(code) and "ANNUAL REPORT" in title and year in title and str(record.get("FILE_TYPE") or "").upper() == "PDF"


def _download_and_extract_hkex_pdf(source_url: str, period: str, max_passages: int = 8, max_chars: int = 26000) -> Dict[str, Any]:
    req = request.Request(source_url, headers={"User-Agent": "Mozilla/5.0 DeepReportPlus/0.1"}, method="GET")
    with request.urlopen(req, timeout=90) as response:
        data = response.read()
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError("pymupdf is required to stage HKEX annual-report evidence") from exc

    year = _period_year(period)
    doc = fitz.open(stream=data, filetype="pdf")
    candidates: List[tuple[int, int, str]] = []
    try:
        for page_index, page in enumerate(doc, start=1):
            text = " ".join(str(page.get_text() or "").split())
            lowered = text.lower()
            if year not in text or len(text) < 80:
                continue
            score = 0
            for keyword, weight in [
                ("revenue", 4),
                ("profit", 2),
                ("cash flow", 4),
                ("financial position", 3),
                ("income statement", 3),
                ("management discussion", 1),
            ]:
                if keyword in lowered:
                    score += weight
            if "contents" in lowered[:80]:
                score -= 5
            if score >= 4:
                candidates.append((score, page_index, text))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        passages: List[str] = []
        selected_pages: List[int] = []
        used_chars = 0
        for _, page_number, text in candidates:
            if page_number in selected_pages:
                continue
            passage = f"[PDF page {page_number}] {text[:5000]}"
            if used_chars + len(passage) > max_chars:
                passage = passage[: max_chars - used_chars]
            if not passage:
                break
            passages.append(passage)
            selected_pages.append(page_number)
            used_chars += len(passage)
            if len(passages) >= max_passages or used_chars >= max_chars:
                break
        return {
            "content": " ".join(passages),
            "pages": selected_pages,
            "page_count": len(doc),
            "pdf_sha256": hashlib.sha256(data).hexdigest(),
        }
    finally:
        doc.close()


def _normalize_record(record: Dict[str, Any], symbol: str, period: str) -> Dict[str, Any]:
    normalized = dict(record)
    normalized["symbol"] = symbol
    normalized["period"] = period
    source_type = str(normalized.get("source_type") or "")
    timezone_offset = 8 if source_type == "cninfo_announcement" else 0
    normalized["publish_time"] = _normalize_publish_time(normalized.get("publish_time"), timezone_offset_hours=timezone_offset)
    normalized.setdefault("trust_level", "high")
    return normalized


def _normalize_publish_time(raw: Any, timezone_offset_hours: int = 0) -> str:
    text = str(raw or "")
    if text.isdigit() and len(text) >= 10:
        seconds = int(text) / (1000 if len(text) > 10 else 1)
        source_timezone = timezone(timedelta(hours=timezone_offset_hours))
        return datetime.fromtimestamp(seconds, tz=source_timezone).date().isoformat()
    return text


def _period_year(period: str) -> str:
    text = str(period or "").upper()
    for index in range(max(len(text) - 3, 0)):
        token = text[index : index + 4]
        if token.isdigit() and token.startswith("20"):
            return token
    return ""


def _hkex_release_date(raw: Any) -> str:
    text = str(raw or "").strip()
    try:
        return datetime.strptime(text[:10], "%d/%m/%Y").date().isoformat()
    except ValueError:
        return text


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", str(text or "")).replace("&amp;", "&").strip()


def _status_row(case: Dict[str, Any], period: str, status: str, issues: List[str]) -> Dict[str, Any]:
    return {
        "case_id": str(case.get("case_id") or ""),
        "market": str(case.get("market") or ""),
        "canonical_symbol": str(case.get("canonical_symbol") or ""),
        "period": period,
        "status": status,
        "issues": issues,
    }
