"""Lightweight PDF cache and section extraction for filing evidence."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import io
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib import error, request


SECTION_KEYWORDS = {
    "business_overview": ["主营业务", "业务概要", "公司业务", "business"],
    "management_discussion": ["管理层讨论", "经营情况讨论", "management discussion", "md&a"],
    "risk_factors": ["风险因素", "风险提示", "risk"],
    "financial_statements": ["财务报表", "合并资产负债表", "利润表", "现金流量表", "financial statements"],
    # P0.8.5: Removed "董事"/"监事"/"高级管理人员" from ownership_governance —
    # these match 重要提示 disclaimers ("本公司董事会及董事、高级管理人员保证...")
    # which are NOT governance evidence. Use 股东/股本/shareholder/governance/公司治理 only.
    "ownership_governance": ["股东", "股本", "公司治理", "shareholder", "governance"],
    "shareholder_structure": ["股份变动", "前十", "控股股东", "实际控制人"],
}


def build_pdf_artifacts(
    records: Iterable[Dict[str, Any]],
    cache_dir: str | Path,
    max_pdfs: int = 2,
    max_pages: int = 8,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Cache filing PDFs and extract section snippets when local dependencies allow."""

    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    pdf_records = [record for record in records if isinstance(record, dict) and _is_pdf_record(record)]
    manifest: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    tables: List[Dict[str, Any]] = []
    for record in pdf_records[: max(0, int(max_pdfs))]:
        row = _manifest_row(record)
        try:
            local_path, digest, size = _cache_pdf(str(record.get("source_url") or ""), cache_root=cache_root, timeout=timeout)
            row.update(
                {
                    "status": "cached",
                    "cache_status": "cached",
                    "extraction_status": "pending",
                    "file_path": str(local_path),
                    "sha256": digest,
                    "size_bytes": size,
                    "download_time": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            row.update({"status": "failed", "cache_status": "failed", "extraction_status": "not_attempted", "failure_reason": str(exc)})
            manifest.append(row)
            continue

        try:
            extracted = _extract_sections(
                path=local_path,
                evidence_id=str(record.get("evidence_id") or record.get("sample_id") or ""),
                source_url=str(record.get("source_url") or ""),
                max_pages=max_pages,
            )
            sections.extend(extracted["sections"])
            tables.extend(extracted.get("tables", []))
            row["page_count"] = extracted.get("page_count", 0)
            row["pages_read"] = extracted.get("pages_read", 0)
            row["section_count"] = len(extracted["sections"])
            row["table_count"] = len(extracted.get("tables", []))
            row["extraction_status"] = "extracted"
        except Exception as exc:
            row.update({"extraction_status": "failed", "extraction_failure_reason": str(exc), "section_count": 0})
        manifest.append(row)

    profile = extract_company_profile_from_sections(sections)
    return {
        "pdf_manifest": manifest,
        "pdf_sections": sections,
        "pdf_tables": tables,
        "company_profile_extracted": profile,
        "meta": {
            "candidate_pdf_count": len(pdf_records),
            "processed_pdf_count": len(manifest),
            "cached_pdf_count": len([row for row in manifest if row.get("cache_status") == "cached"]),
            "extracted_pdf_count": len([row for row in manifest if row.get("extraction_status") == "extracted"]),
            "section_count": len(sections),
            "table_count": len(tables),
            "statement_table_count": len([row for row in tables if row.get("table_type") in {"income_statement", "balance_sheet", "cash_flow_statement"}]),
        },
    }


def extract_company_profile_from_sections(sections: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract conservative company profile hints from section snippets."""

    output: Dict[str, Any] = {
        "business_segments": [],
        "ownership_governance": [],
        "management": [],
        "risk_factors": [],
        "source_section_ids": [],
        "extraction_method": "pdf_section_keyword_snippets_v1",
    }
    for section in [item for item in sections if isinstance(item, dict)]:
        section_type = str(section.get("section_type") or "")
        snippet = str(section.get("snippet") or "").strip()
        if not snippet:
            continue
        if section_type == "business_overview":
            output["business_segments"].append(snippet[:500])
        elif section_type == "ownership_governance":
            output["ownership_governance"].append(snippet[:500])
        elif section_type == "management_discussion":
            output["management"].append(snippet[:500])
        elif section_type == "risk_factors":
            output["risk_factors"].append(snippet[:500])
        output["source_section_ids"].append(str(section.get("section_id") or ""))
    for key in ["business_segments", "ownership_governance", "management", "risk_factors", "source_section_ids"]:
        output[key] = _dedupe(output[key])[:8]
    output["has_profile_hints"] = any(output[key] for key in ["business_segments", "ownership_governance", "management", "risk_factors"])
    return output


def _is_pdf_record(record: Dict[str, Any]) -> bool:
    source_url = str(record.get("source_url") or "").split("?", 1)[0].lower()
    source_type = str(record.get("source_type") or "").lower()
    return source_url.endswith(".pdf") or source_type in {"cninfo_announcement", "exchange_announcement", "filing_pdf"}


def _manifest_row(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "evidence_id": str(record.get("evidence_id") or record.get("sample_id") or ""),
        "source_type": str(record.get("source_type") or ""),
        "title": str(record.get("title") or ""),
        "source_url": str(record.get("source_url") or ""),
        "publish_time": str(record.get("publish_time") or ""),
        "status": "pending",
    }


def _cache_pdf(source_url: str, cache_root: Path, timeout: float) -> tuple[Path, str, int]:
    if not source_url:
        raise ValueError("missing PDF source_url")
    if source_url.startswith(("http://", "https://")):
        req = request.Request(source_url, headers={"User-Agent": "FinSight/0.1"}, method="GET")
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
        except (TimeoutError, error.URLError, error.HTTPError) as exc:
            raise RuntimeError(f"pdf_download_failed: {exc}") from exc
        digest = hashlib.sha256(data).hexdigest()
        path = cache_root / f"{digest[:16]}.pdf"
        if not path.exists():
            path.write_bytes(data)
        return path, digest, len(data)
    path = Path(source_url)
    if not path.exists():
        raise FileNotFoundError(source_url)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    cached = cache_root / f"{digest[:16]}.pdf"
    if path.resolve() != cached.resolve() and not cached.exists():
        cached.write_bytes(data)
    return cached, digest, len(data)


def _suppress_mupdf_stderr():
    """Temporarily suppress MuPDF C-core stderr noise (e.g. structure tree errors)."""
    return contextlib.redirect_stderr(io.StringIO())


def _extract_sections(path: Path, evidence_id: str, source_url: str, max_pages: int) -> Dict[str, Any]:
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError("pymupdf_unavailable") from exc

    pdfplumber_tables = _extract_pdfplumber_statement_tables(
        path=path,
        evidence_id=evidence_id,
        source_url=source_url,
        max_pages=max_pages,
    )
    pdfplumber_pages = {int(table.get("page", 0) or 0) for table in pdfplumber_tables}
    with _suppress_mupdf_stderr():
        doc = fitz.open(str(path))
        try:
            page_count = len(doc)
            pages_read = min(page_count, max(1, int(max_pages)))
            sections: List[Dict[str, Any]] = []
            tables: List[Dict[str, Any]] = list(pdfplumber_tables)
            for page_index in range(pages_read):
                page = doc[page_index]
                text = page.get_text() or ""
                normalized = " ".join(text.split())
                lowered = normalized.lower()
                for section_type, keywords in SECTION_KEYWORDS.items():
                    match = next((keyword for keyword in keywords if keyword.lower() in lowered), "")
                    if not match:
                        continue
                    snippet = _snippet_around(normalized, match)
                    # P0.8.5: Skip noise snippets (headers, disclaimers, TOC)
                    if _is_snippet_noise(snippet, section_type):
                        continue
                    section_id = hashlib.sha1(f"{evidence_id}|{page_index}|{section_type}|{snippet}".encode("utf-8")).hexdigest()[:12]
                    sections.append(
                        {
                            "section_id": section_id,
                            "evidence_id": evidence_id,
                            "source_url": source_url,
                            "page": page_index + 1,
                            "section_type": section_type,
                            "matched_keyword": match,
                            "snippet": snippet,
                            "extraction_method": "pymupdf_text_keyword_window",
                        }
                    )
                if page_index + 1 not in pdfplumber_pages:
                    tables.extend(
                        _extract_statement_tables(
                            page=page,
                            page_number=page_index + 1,
                            page_text=normalized,
                            evidence_id=evidence_id,
                            source_url=source_url,
                        )
                    )
            return {"page_count": page_count, "pages_read": pages_read, "sections": sections, "tables": tables}
        finally:
            doc.close()


def _extract_pdfplumber_statement_tables(path: Path, evidence_id: str, source_url: str, max_pages: int) -> List[Dict[str, Any]]:
    try:
        import pdfplumber
    except Exception:
        return []

    settings = [
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
        },
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
            "text_x_tolerance": 2,
            "text_y_tolerance": 3,
        },
    ]
    output: List[Dict[str, Any]] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            pages_read = min(len(pdf.pages), max(1, int(max_pages)))
            for page_index in range(pages_read):
                page = pdf.pages[page_index]
                page_text = " ".join(str(page.extract_text() or "").split())
                seen_tables: set[str] = set()
                for setting in settings:
                    try:
                        raw_tables = page.extract_tables(table_settings=setting) or []
                    except Exception:
                        continue
                    for table_index, data in enumerate(raw_tables, start=1):
                        key = hashlib.sha1(repr(data).encode("utf-8", errors="ignore")).hexdigest()[:12]
                        if key in seen_tables:
                            continue
                        seen_tables.add(key)
                        artifact = _statement_table_artifact_from_data(
                            data=data,
                            page_number=page_index + 1,
                            page_text=page_text,
                            evidence_id=evidence_id,
                            source_url=source_url,
                            table_index=table_index,
                            extraction_method="pdfplumber_extract_tables_statement_heuristic_v1",
                        )
                        if artifact:
                            output.append(artifact)
    except Exception:
        return output
    return output


def _extract_statement_tables(
    page: Any,
    page_number: int,
    page_text: str,
    evidence_id: str,
    source_url: str,
) -> List[Dict[str, Any]]:
    if not hasattr(page, "find_tables"):
        return []
    try:
        finder = page.find_tables()
    except Exception:
        return []
    raw_tables = getattr(finder, "tables", finder)
    if raw_tables is None:
        return []

    output: List[Dict[str, Any]] = []
    for table_index, table in enumerate(raw_tables, start=1):
        try:
            data = table.extract()
        except Exception:
            continue
        artifact = _statement_table_artifact_from_data(
            data=data,
            page_number=page_number,
            page_text=page_text,
            evidence_id=evidence_id,
            source_url=source_url,
            table_index=table_index,
            extraction_method="pymupdf_find_tables_statement_heuristic_v1",
        )
        if artifact:
            output.append(artifact)
    return output


def _statement_table_artifact_from_data(
    data: Any,
    page_number: int,
    page_text: str,
    evidence_id: str,
    source_url: str,
    table_index: int,
    extraction_method: str,
) -> Dict[str, Any] | None:
    if not isinstance(data, list):
        return None
    normalized = _normalize_table(data)
    if not normalized:
        return None
    table_type = _classify_statement_table(normalized, page_text)
    if not table_type:
        return None
    rows = _statement_rows_from_table(normalized, table_type=table_type)
    if not rows:
        return None
    table_id = f"pdf_tbl_{hashlib.sha1(f'{evidence_id}|{page_number}|{table_index}|{table_type}|{extraction_method}'.encode('utf-8')).hexdigest()[:12]}"
    return {
        "table_id": table_id,
        "evidence_id": evidence_id,
        "source_url": source_url,
        "page": page_number,
        "table_index": table_index,
        "table_type": table_type,
        "rows": rows,
        "raw_rows": normalized[:40],
        "unit": _infer_unit(page_text, normalized),
        "currency": _infer_currency(page_text, normalized),
        "extraction_method": extraction_method,
        "confidence": _table_confidence(table_type, rows),
    }


def _normalize_table(data: List[Any]) -> List[List[str]]:
    rows: List[List[str]] = []
    for raw_row in data:
        if not isinstance(raw_row, list):
            continue
        row = [_normalize_cell(cell) for cell in raw_row]
        if any(row):
            rows.append(row)
    return rows


def _normalize_cell(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()
    return text


def _classify_statement_table(rows: List[List[str]], page_text: str) -> str:
    joined = " ".join([" ".join(row) for row in rows[:18]] + [page_text]).lower()
    if any(term in joined for term in ["cash flow", "operating activities", "investing activities", "financing activities", "net cash"]):
        return "cash_flow_statement"
    if any(term in joined for term in ["balance sheet", "total assets", "total liabilities", "stockholders' equity", "shareholders' equity"]):
        return "balance_sheet"
    if any(term in joined for term in ["income statement", "statement of operations", "total revenues", "total revenue", "gross profit", "net income"]):
        return "income_statement"
    return ""


LINE_ITEM_ALIASES = {
    "income_statement": [
        ("revenue", ["total revenues", "total revenue", "revenues", "revenue"]),
        ("gross_profit", ["gross profit"]),
        ("operating_income", ["income from operations", "operating income"]),
        ("net_income", ["net income", "net earnings"]),
    ],
    "balance_sheet": [
        ("total_assets", ["total assets"]),
        ("total_liabilities", ["total liabilities"]),
        ("equity", ["stockholders' equity", "shareholders' equity", "total equity"]),
        ("cash_and_equivalents", ["cash and cash equivalents", "cash cash equivalents"]),
    ],
    "cash_flow_statement": [
        ("operating_cash_flow", ["net cash provided by operating activities", "net cash from operating activities", "operating cash flow"]),
        ("investing_cash_flow", ["net cash used in investing activities", "net cash provided by investing activities"]),
        ("financing_cash_flow", ["net cash provided by financing activities", "net cash used in financing activities"]),
        ("capex", ["purchases of property", "capital expenditures", "property and equipment"]),
        ("free_cash_flow", ["free cash flow"]),
    ],
}


def _statement_rows_from_table(rows: List[List[str]], table_type: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    aliases = LINE_ITEM_ALIASES.get(table_type, [])
    for raw in rows:
        label = _row_label(raw)
        if not label:
            continue
        normalized_label = label.lower()
        line_item = ""
        for candidate, terms in aliases:
            if any(term in normalized_label for term in terms):
                line_item = candidate
                break
        if not line_item:
            continue
        value = _first_numeric_from_row(raw)
        if value is None:
            continue
        output.append(
            {
                "statement": table_type,
                "line_item": line_item,
                "label": label,
                "value": value,
                "raw_row": raw,
            }
        )
    return _dedupe_statement_rows(output)


def _row_label(row: List[str]) -> str:
    for cell in row:
        if cell and not _looks_numeric(cell):
            return cell
    return ""


def _first_numeric_from_row(row: List[str]) -> float | None:
    numbers = [_parse_number(cell) for cell in row if _parse_number(cell) is not None]
    if not numbers:
        return None
    return numbers[0]


def _parse_number(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace("$", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return -abs(number) if negative else number


def _looks_numeric(value: str) -> bool:
    return _parse_number(value) is not None


def _dedupe_statement_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    output: List[Dict[str, Any]] = []
    for row in rows:
        key = str(row.get("line_item") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _infer_unit(page_text: str, rows: List[List[str]]) -> str:
    joined = " ".join([page_text] + [" ".join(row) for row in rows[:4]]).lower()
    if "in millions" in joined or "millions" in joined:
        return "millions"
    if "in thousands" in joined or "thousands" in joined:
        return "thousands"
    return "raw"


def _infer_currency(page_text: str, rows: List[List[str]]) -> str:
    joined = " ".join([page_text] + [" ".join(row) for row in rows[:4]]).lower()
    if "$" in joined or "usd" in joined or "u.s. dollars" in joined:
        return "USD"
    if "rmb" in joined or "cny" in joined:
        return "CNY"
    return ""


def _table_confidence(table_type: str, rows: List[Dict[str, Any]]) -> float:
    required = {
        "income_statement": {"revenue", "net_income"},
        "balance_sheet": {"total_assets", "total_liabilities"},
        "cash_flow_statement": {"operating_cash_flow"},
    }.get(table_type, set())
    present = {str(row.get("line_item") or "") for row in rows}
    coverage = len(required & present) / max(1, len(required))
    return round(0.62 + 0.28 * coverage, 3)


def _is_snippet_noise(snippet: str, section_type: str) -> bool:
    """Return True if snippet is a known PDF noise pattern that should be skipped."""
    t = str(snippet or "").strip()
    if len(t) < 30:
        return True
    # Page headers / important notice / disclaimer patterns
    noise_pats = [
        r"年度报告\s*\d+\s*/\s*\d+",
        r"第\s*\d+\s*页\s*共\s*\d+\s*页",
        r"重要提示",
        r"本公司董事会及董事.*保证",
        r"不存在虚假记载",
        r"□适用\s*√不适用",
        r"√适用\s*□不适用",
        r"标准无保留意见",
    ]
    for pat in noise_pats:
        if re.search(pat, t):
            return True
    # Critical: important_notice text must never serve as governance/risk evidence
    if section_type in ("ownership_governance", "shareholder_structure", "risk_factors"):
        if re.search(r"董事会.*保证|不存在虚假|标准无保留意见|全体董事出席", t):
            return True
    return False


def _snippet_around(text: str, keyword: str, radius: int = 420) -> str:
    index = text.lower().find(keyword.lower())
    if index < 0:
        return text[: radius * 2].strip()
    start = max(0, index - radius)
    end = min(len(text), index + len(keyword) + radius)
    return text[start:end].strip()


def _dedupe(values: List[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for value in values:
        key = value.strip()
        if key and key not in seen:
            output.append(key)
            seen.add(key)
    return output
