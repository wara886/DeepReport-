"""Lightweight PDF cache and section extraction for filing evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib import error, request


SECTION_KEYWORDS = {
    "business_overview": ["主营业务", "业务概要", "公司业务", "business"],
    "management_discussion": ["管理层讨论", "经营情况讨论", "management discussion", "md&a"],
    "risk_factors": ["风险因素", "风险提示", "risk"],
    "financial_statements": ["财务报表", "合并资产负债表", "利润表", "现金流量表", "financial statements"],
    "ownership_governance": ["股本", "股东", "董事", "监事", "高级管理人员", "shareholder", "governance"],
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
            row["page_count"] = extracted.get("page_count", 0)
            row["pages_read"] = extracted.get("pages_read", 0)
            row["section_count"] = len(extracted["sections"])
            row["extraction_status"] = "extracted"
        except Exception as exc:
            row.update({"extraction_status": "failed", "extraction_failure_reason": str(exc), "section_count": 0})
        manifest.append(row)

    profile = extract_company_profile_from_sections(sections)
    return {
        "pdf_manifest": manifest,
        "pdf_sections": sections,
        "company_profile_extracted": profile,
        "meta": {
            "candidate_pdf_count": len(pdf_records),
            "processed_pdf_count": len(manifest),
            "cached_pdf_count": len([row for row in manifest if row.get("cache_status") == "cached"]),
            "extracted_pdf_count": len([row for row in manifest if row.get("extraction_status") == "extracted"]),
            "section_count": len(sections),
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
        req = request.Request(source_url, headers={"User-Agent": "DeepReportPlus/0.1"}, method="GET")
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


def _extract_sections(path: Path, evidence_id: str, source_url: str, max_pages: int) -> Dict[str, Any]:
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError("pymupdf_unavailable") from exc

    doc = fitz.open(str(path))
    try:
        page_count = len(doc)
        pages_read = min(page_count, max(1, int(max_pages)))
        sections: List[Dict[str, Any]] = []
        for page_index in range(pages_read):
            text = doc[page_index].get_text() or ""
            normalized = " ".join(text.split())
            lowered = normalized.lower()
            for section_type, keywords in SECTION_KEYWORDS.items():
                match = next((keyword for keyword in keywords if keyword.lower() in lowered), "")
                if not match:
                    continue
                snippet = _snippet_around(normalized, match)
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
        return {"page_count": page_count, "pages_read": pages_read, "sections": sections}
    finally:
        doc.close()


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
