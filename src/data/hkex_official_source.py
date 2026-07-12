"""Direct, keyless HKEXnews announcement discovery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib import parse, request


STOCK_LIST_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"
TITLE_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
BASE_URL = "https://www1.hkexnews.hk"
HEADERS = {
    "User-Agent": "Mozilla/5.0 FinSight/0.1",
    "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
}


def fetch_hkex_official_announcements(
    *, symbol: str, period: str, topk: int = 5, timeout: float = 20.0
) -> dict[str, Any]:
    code = str(symbol or "").upper().split(".", 1)[0].zfill(5)
    year = _period_year(period)
    if not code.isdigit() or not year:
        return {"hits": [], "meta": {"mode": "hkex_official", "failure_reason": "invalid_symbol_or_period"}}
    try:
        directory = _stock_directory(timeout)
        stock = directory.get(code)
        if not stock:
            return {"hits": [], "meta": {"mode": "hkex_official", "failure_reason": "stock_code_not_found", "stock_code": code}}
        rows = _query_documents(str(stock["i"]), year, timeout)
    except Exception as exc:
        return {"hits": [], "meta": {"mode": "hkex_official", "failure_reason": "fetch_error", "error": str(exc)}}

    matched = [row for row in rows if _matches(row, code=code, year=year)]
    matched.sort(key=lambda row: str(row.get("DATE_TIME") or ""), reverse=True)
    hits = [_normalize(row, symbol=str(symbol).upper(), period=str(period), code=code) for row in matched[:topk]]
    return {
        "hits": hits,
        "meta": {
            "mode": "hkex_official",
            "stock_code": code,
            "stock_id": str(stock["i"]),
            "queried_count": len(rows),
            "result_count": len(hits),
            "failure_reason": "" if hits else "no_period_matched_official_announcement",
        },
    }


def _stock_directory(timeout: float) -> dict[str, dict[str, Any]]:
    req = request.Request(STOCK_LIST_URL, headers=HEADERS, method="GET")
    with request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    return {
        str(row.get("c") or "").zfill(5): dict(row)
        for row in payload
        if isinstance(row, dict) and str(row.get("c") or "").strip()
    }


def _query_documents(stock_id: str, year: str, timeout: float) -> list[dict[str, Any]]:
    release_year = str(int(year) + 1)
    params = {
        "sortDir": "1", "sortByOptions": "DateTime", "category": "0", "market": "SEHK",
        "stockId": stock_id, "documentType": "-1", "fromDate": f"{release_year}0101",
        "toDate": f"{release_year}1231", "title": "", "searchType": "1", "t1code": "40000",
        "t2Gcode": "-2", "t2code": "-2", "rowRange": "200", "lang": "E",
    }
    req = request.Request(f"{TITLE_SEARCH_URL}?{parse.urlencode(params)}", headers=HEADERS, method="GET")
    with request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = json.loads(str(payload.get("result") or "[]"))
    return [dict(row) for row in rows if isinstance(row, dict)]


def _matches(row: dict[str, Any], *, code: str, year: str) -> bool:
    title = _strip_html(str(row.get("TITLE") or "")).upper()
    stock_code = _strip_html(str(row.get("STOCK_CODE") or "")).replace(" ", "")
    annual = "ANNUAL REPORT" in title or "ANNUAL RESULTS" in title
    return stock_code.startswith(code) and annual and year in title and str(row.get("FILE_TYPE") or "").upper() == "PDF"


def _normalize(row: dict[str, Any], *, symbol: str, period: str, code: str) -> dict[str, Any]:
    source_url = parse.urljoin(BASE_URL, str(row.get("FILE_LINK") or ""))
    title = _strip_html(str(row.get("TITLE") or f"{code} annual report"))
    digest = hashlib.sha1(f"{code}|{period}|{source_url}".encode("utf-8")).hexdigest()[:10]
    evidence_id = f"{code}_{period}_hkex_official_{digest}"
    return {
        "evidence_id": evidence_id,
        "sample_id": evidence_id,
        "symbol": symbol,
        "period": period,
        "source_type": "hkex_announcement",
        "title": title,
        "source_url": source_url,
        "publish_time": _release_date(row.get("DATE_TIME")),
        "content": f"HKEX official disclosure for {symbol}: {title}. Official PDF: {source_url}",
        "trust_level": "high",
        "source_authority": "official",
        "authority_level": "primary",
        "authority_score": 1.0,
        "metadata": {"provider": "HKEXnews", "stock_code": code, "stock_id": str(row.get("STOCK_ID") or ""), "news_id": str(row.get("NEWS_ID") or ""), "direct_official_discovery": True},
    }


def _period_year(period: str) -> str:
    match = re.search(r"(20\d{2})", str(period or ""))
    return match.group(1) if match else ""


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).replace("&amp;", "&").strip()


def _release_date(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return datetime.now(timezone.utc).date().isoformat()
