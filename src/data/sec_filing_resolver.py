"""SEC annual filing resolver for US FY reports.

This module resolves a ticker to the target 10-K filing, fetches the primary
filing document, and returns both resolver metadata and a filing-level evidence
record.  It intentionally does not parse the full report body; section parsing
is handled by AnnualReportSectionExtractor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import re
import socket
from pathlib import Path
from typing import Any
from urllib import error, request

from src.data.company_universe import resolve_company_identifier
from src.data.independent_sources import DEFAULT_CIK_MAP
from src.data.source_quality import apply_source_quality
from src.utils.config import load_config
from src.utils.env import load_env_files


TEN_K_FORMS = {"10-K", "10-K/A"}
PROXY_FORMS = {"DEF 14A", "DEFA14A"}


@dataclass(frozen=True)
class SecAnnualFilingPayload:
    """Resolved annual filing result."""

    evidence_records: list[dict[str, Any]]
    sections_input: dict[str, Any]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_records": list(self.evidence_records),
            "sections_input": dict(self.sections_input),
            "meta": dict(self.meta),
        }


def resolve_sec_annual_filing(
    symbol: str,
    period: str,
    config_path: str = "configs/data_sources.yaml",
    raw_data_root: str = "data/raw/real_data",
    cache_dir: str | Path | None = None,
    fetch_document: bool = True,
) -> SecAnnualFilingPayload:
    """Resolve and optionally fetch the target SEC 10-K primary document.

    The resolver is only intended for US FY reports.  Non-FY or non-US periods
    should be filtered by the caller.
    """

    symbol = str(symbol or "").strip().upper()
    period = str(period or "").strip().upper()
    fiscal_year = _fiscal_year(period)
    if not symbol:
        return _payload([], {}, {"status": "failed", "failure_reason": "missing_symbol"})
    if fiscal_year is None:
        return _payload([], {}, {"status": "skipped", "failure_reason": "not_fy_period", "period": period})

    config = _load_data_source_config(config_path)
    sec_cfg = dict(config.get("independent_sources", {}).get("company", {}).get("sec_edgar", {}))
    cik = _resolve_cik(symbol=symbol, raw_data_root=raw_data_root, config=sec_cfg)
    if not cik:
        return _payload([], {}, {"status": "failed", "symbol": symbol, "period": period, "failure_reason": "missing_cik"})
    cik = cik.zfill(10)

    base_url = str(sec_cfg.get("submissions_base_url") or "https://data.sec.gov/submissions")
    timeout = float(sec_cfg.get("timeout", 20))
    headers = {"User-Agent": _sec_user_agent(sec_cfg), "Host": "data.sec.gov"}
    submissions_url = f"{base_url}/CIK{cik}.json"
    try:
        submissions = _get_json(submissions_url, headers=headers, timeout=timeout)
    except Exception as exc:
        return _payload(
            [],
            {},
            {
                "status": "failed",
                "symbol": symbol,
                "period": period,
                "cik": cik,
                "submissions_url": submissions_url,
                "failure_reason": "submissions_fetch_error",
                "error": str(exc),
            },
        )

    filing = _select_annual_filing(submissions, fiscal_year=fiscal_year)
    if not filing:
        return _payload(
            [],
            {},
            {
                "status": "failed",
                "symbol": symbol,
                "period": period,
                "cik": cik,
                "submissions_url": submissions_url,
                "failure_reason": "no_matching_10k",
            },
        )

    accession = str(filing.get("accession_number") or "")
    accession_path = accession.replace("-", "")
    primary_doc = str(filing.get("primary_document") or "")
    filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary_doc}"
    filing_title = f"{symbol} FY{fiscal_year} Form {filing.get('form') or '10-K'} annual report"
    evidence_id = f"sec_10k_{symbol.lower()}_fy{fiscal_year}"
    record = apply_source_quality(
        {
            "evidence_id": evidence_id,
            "sample_id": evidence_id,
            "source_type": "sec_10k_filing",
            "title": filing_title,
            "source_url": filing_url,
            "publish_time": str(filing.get("filing_date") or ""),
            "content": (
                f"{symbol} FY{fiscal_year} annual report filing resolved from SEC EDGAR. "
                "Use parsed Item 1, Item 1A, and Item 7 sections for business, risk, and MD&A evidence."
            ),
            "symbol": symbol,
            "period": period,
            "trust_level": "high",
            "metadata": {
                "provider": "SEC EDGAR",
                "cik": cik,
                "accession_number": accession,
                "form": filing.get("form", ""),
                "filing_date": filing.get("filing_date", ""),
                "period_of_report": filing.get("period_of_report", ""),
                "primary_document": primary_doc,
                "fiscal_year": fiscal_year,
            },
        }
    )

    html_text = ""
    cache_path = ""
    doc_error = ""
    if fetch_document:
        try:
            html_text = _get_text(
                filing_url,
                headers={"User-Agent": _sec_user_agent(sec_cfg), "Host": "www.sec.gov"},
                timeout=timeout,
            )
            if cache_dir:
                cache_root = Path(cache_dir)
                cache_root.mkdir(parents=True, exist_ok=True)
                cache_file = cache_root / f"{symbol.lower()}_fy{fiscal_year}_10k.html"
                cache_file.write_text(html_text, encoding="utf-8", errors="replace")
                cache_path = str(cache_file)
        except Exception as exc:
            doc_error = str(exc)

    meta = {
        "status": "resolved" if html_text or not fetch_document else "document_fetch_failed",
        "symbol": symbol,
        "period": period,
        "cik": cik,
        "fiscal_year": fiscal_year,
        "filing": filing,
        "filing_url": filing_url,
        "submissions_url": submissions_url,
        "cache_path": cache_path,
        "document_chars": len(html_text),
        "failure_reason": "document_fetch_error" if doc_error else "",
        "error": doc_error,
    }
    sections_input = {
        "html_text": html_text,
        "html_path": cache_path,
        "filing_url": filing_url,
        "filing_title": filing_title,
        "filing_evidence_id": evidence_id,
    }
    return _payload([record], sections_input, meta)


def resolve_sec_proxy_filing(
    symbol: str,
    period: str,
    config_path: str = "configs/data_sources.yaml",
    raw_data_root: str = "data/raw/real_data",
) -> SecAnnualFilingPayload:
    """Resolve the fiscal-year proxy statement and return bounded governance evidence."""

    symbol = str(symbol or "").strip().upper()
    period = str(period or "").strip().upper()
    fiscal_year = _fiscal_year(period)
    if not symbol or fiscal_year is None:
        return _payload([], {}, {"status": "skipped", "failure_reason": "missing_symbol_or_fiscal_year"})
    config = _load_data_source_config(config_path)
    sec_cfg = dict(config.get("independent_sources", {}).get("company", {}).get("sec_edgar", {}))
    cik = _resolve_cik(symbol=symbol, raw_data_root=raw_data_root, config=sec_cfg)
    if not cik:
        return _payload([], {}, {"status": "failed", "failure_reason": "missing_cik", "symbol": symbol})
    cik = cik.zfill(10)
    timeout = float(sec_cfg.get("timeout", 20))
    user_agent = _sec_user_agent(sec_cfg)
    submissions_url = f"{str(sec_cfg.get('submissions_base_url') or 'https://data.sec.gov/submissions')}/CIK{cik}.json"
    try:
        submissions = _get_json(submissions_url, headers={"User-Agent": user_agent, "Host": "data.sec.gov"}, timeout=timeout)
        filing = _select_filing(submissions, forms=PROXY_FORMS, fiscal_year=fiscal_year)
        if not filing:
            return _payload([], {}, {"status": "failed", "failure_reason": "no_matching_proxy", "symbol": symbol})
        accession = str(filing.get("accession_number") or "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{filing.get('primary_document')}"
        )
        html_text = _get_text(filing_url, headers={"User-Agent": user_agent, "Host": "www.sec.gov"}, timeout=timeout)
    except Exception as exc:
        return _payload([], {}, {"status": "failed", "failure_reason": "proxy_fetch_error", "error": str(exc), "symbol": symbol})

    content = _proxy_governance_excerpt(html_text)
    if not content:
        return _payload([], {}, {"status": "failed", "failure_reason": "proxy_governance_text_missing", "filing_url": filing_url})
    evidence_id = f"sec_proxy_{symbol.lower()}_fy{fiscal_year}"
    record = apply_source_quality(
        {
            "evidence_id": evidence_id,
            "sample_id": evidence_id,
            "source_type": "sec_proxy_filing",
            "title": f"{symbol} FY{fiscal_year} DEF 14A governance disclosure",
            "source_url": filing_url,
            "publish_time": str(filing.get("filing_date") or ""),
            "content": content,
            "symbol": symbol,
            "period": period,
            "trust_level": "high",
            "metadata": {
                "provider": "SEC EDGAR",
                "cik": cik,
                "accession_number": accession,
                "form": filing.get("form", ""),
                "filing_date": filing.get("filing_date", ""),
                "fiscal_year": fiscal_year,
                "section_type": "ownership_governance",
            },
        }
    )
    return _payload([record], {}, {"status": "resolved", "filing_url": filing_url, "filing": filing, "symbol": symbol, "period": period})


def _select_annual_filing(submissions: dict[str, Any], fiscal_year: int) -> dict[str, Any]:
    return _select_filing(submissions, forms=TEN_K_FORMS, fiscal_year=fiscal_year)


def _select_filing(submissions: dict[str, Any], *, forms: set[str], fiscal_year: int) -> dict[str, Any]:
    recent = submissions.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return {}
    allowed_forms = {str(value).upper() for value in forms}
    filing_forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    rows: list[dict[str, Any]] = []
    for idx, form in enumerate(filing_forms if isinstance(filing_forms, list) else []):
        form_text = str(form or "").upper()
        if form_text not in allowed_forms:
            continue
        row = {
            "form": form_text,
            "accession_number": _list_get(accessions, idx),
            "filing_date": _list_get(filing_dates, idx),
            "period_of_report": _list_get(report_dates, idx),
            "primary_document": _list_get(primary_docs, idx),
        }
        if not row["accession_number"] or not row["primary_document"]:
            continue
        rows.append(row)

    def score(row: dict[str, Any]) -> tuple[int, int, str]:
        report_year = _date_year(row.get("period_of_report"))
        filing_year = _date_year(row.get("filing_date"))
        if report_year == fiscal_year:
            year_score = 3
        elif filing_year == fiscal_year or filing_year == fiscal_year + 1:
            year_score = 2
        else:
            year_score = 0
        form_score = 2 if str(row.get("form") or "").upper() in {"10-K", "DEF 14A"} else 1
        return (year_score, form_score, str(row.get("filing_date") or ""))

    rows = [row for row in rows if score(row)[0] > 0]
    rows.sort(key=score, reverse=True)
    return rows[0] if rows else {}


def _proxy_governance_excerpt(html_text: str, *, max_chars: int = 6000) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", str(html_text or ""))
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text, flags=re.I)
    text = re.sub(r"&amp;", "&", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    terms = ("security ownership", "beneficial ownership", "board of directors", "corporate governance", "executive compensation")
    excerpts: list[str] = []
    lowered = text.lower()
    for term in terms:
        start = 0
        while len(" ".join(excerpts)) < max_chars:
            index = lowered.find(term, start)
            if index < 0:
                break
            excerpt = text[max(0, index - 250) : min(len(text), index + 950)].strip()
            if excerpt and excerpt not in excerpts:
                excerpts.append(excerpt)
            start = index + len(term)
            if len(excerpts) >= 5:
                break
    return " ".join(excerpts)[:max_chars].strip()


def _payload(records: list[dict[str, Any]], sections_input: dict[str, Any], meta: dict[str, Any]) -> SecAnnualFilingPayload:
    return SecAnnualFilingPayload(evidence_records=records, sections_input=sections_input, meta=meta)


def _fiscal_year(period: str) -> int | None:
    match = re.search(r"FY\s*(20\d{2})", str(period or "").upper())
    return int(match.group(1)) if match else None


def _date_year(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").year
    except ValueError:
        return None


def _list_get(values: Any, index: int) -> str:
    if isinstance(values, list) and index < len(values):
        return str(values[index] or "")
    return ""


def _load_data_source_config(config_path: str) -> dict[str, Any]:
    load_env_files(config_path=config_path)
    return load_config(config_path) if config_path else {}


def _resolve_cik(symbol: str, raw_data_root: str, config: dict[str, Any]) -> str:
    cik_map = dict(DEFAULT_CIK_MAP)
    configured = config.get("cik_map")
    if isinstance(configured, dict):
        cik_map.update({str(key).upper(): str(value) for key, value in configured.items()})
    profile = resolve_company_identifier(symbol, raw_data_root=raw_data_root)
    profile_cik = str(profile.get("cik") or profile.get("CIK") or "").strip()
    return profile_cik or str(cik_map.get(symbol.upper(), ""))


def _sec_user_agent(config: dict[str, Any]) -> str:
    env_name = str(config.get("user_agent_env") or "SEC_USER_AGENT")
    configured = os.environ.get(env_name, "").strip()
    return configured or str(config.get("user_agent") or "FinSight/0.1 contact@example.com")


def _get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 20) -> dict[str, Any]:
    text = _get_text(url, headers=headers, timeout=timeout)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise RuntimeError("expected object JSON response")
    return parsed


def _get_text(url: str, headers: dict[str, str] | None = None, timeout: float = 20) -> str:
    req = request.Request(url, headers=headers or {"User-Agent": "FinSight/0.1"}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("request timed out") from exc
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc
