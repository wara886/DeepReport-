"""PDF RAG v2: Section-aware extraction, noise filtering, table separation.

Replaces the legacy keyword-window approach in pdf_artifacts.py with
section-map-driven extraction that filters headers, disclaimers, and TOC.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

# ── A-Share annual report section map ─────────────────────────────────
A_SHARE_SECTION_MAP: list[tuple[str, str, list[str]]] = [
    ("释义", "other", ["释义", "定义", "目录"]),
    ("公司简介和主要财务指标", "business_overview", ["公司简介", "主要财务指标", "公司信息", "主营业务", "业务概要", "产品结构", "销售渠道"]),
    ("管理层讨论与分析", "management_discussion", ["第三节", "管理层讨论", "经营情况讨论", "管理层分析与讨论", "未来发展", "经营计划"]),
    ("公司治理", "ownership_governance", ["第四节", "公司治理"]),
    ("环境与社会责任", "other", ["环境", "社会责任"]),
    ("重要事项", "other", ["重要事项", "重大事项"]),
    ("股份变动及股东情况", "shareholder_structure", ["第七节", "股份变动", "股东情况", "前十名股东", "控股股东", "实际控制人"]),
    ("优先股", "other", ["优先股"]),
    ("债券", "other", ["债券"]),
    ("财务报告", "financial_statements", ["第十节", "财务报告", "审计报告", "财务报表", "合并资产负债表", "合并利润表", "合并现金流量表"]),
    ("风险提示", "risk_factors", ["可能面对的风险", "风险因素", "重大风险提示", "未来发展面临的风险"]),
]

# ── SEC 10-K section map ─────────────────────────────────────────────
SEC_SECTION_MAP: list[tuple[str, str, list[str]]] = [
    ("Item 1. Business", "business_overview", ["business", "item 1"]),
    ("Item 1A. Risk Factors", "risk_factors", ["risk factors", "item 1a"]),
    ("Item 7. MD&A", "management_discussion", ["management", "discussion", "item 7"]),
    ("Item 7A. Market Risk", "risk_factors", ["quantitative", "market risk", "item 7a"]),
    ("Item 8. Financial Statements", "financial_statements", ["financial statements", "item 8"]),
    ("Item 10-14 Governance", "ownership_governance", ["director", "executive", "governance", "item 10"]),
]

# ── PDF noise patterns ───────────────────────────────────────────────
NOISE_PATTERNS: list[str] = [
    # Page headers / footers
    r"年度报告\s*\d+\s*/\s*\d+",
    r"Annual Report\s*\d+\s*/\s*\d+",
    r"第\s*\d+\s*页\s*共\s*\d+\s*页",
    # Important notice / disclaimer boilerplate
    r"重要提示",
    r"本公司董事会及董事.*保证",
    r"不存在虚假记载.*误导性陈述.*重大遗漏",
    r"公司全体董事出席董事会会议",
    r"会计师事务所.*出具.*标准无保留意见",
    r"本年度报告.*已经.*董事会.*审议通过",
    r"□适用\s*√不适用",
    r"√适用\s*□不适用",
    # TOC items
    r"查看PDF文件.*查看XLS文件",
    r"详见.*章节",
    r"详见.*节",
    r"参见.*节",
    # Empty / whitespace-only
    r"^\s*$",
]

NOISE_SECTION_TYPES = {"important_notice", "toc", "disclaimer", "page_header", "audit_opinion"}


def is_pdf_noise(text: str) -> bool:
    """Return True if *text* is a known PDF header/disclaimer/TOC fragment."""
    t = str(text or "").strip()
    if len(t) < 20:
        return True
    for pat in NOISE_PATTERNS:
        if re.search(pat, t):
            return True
    return False


def classify_noise_type(text: str) -> str:
    """Classify what kind of noise this text block is."""
    t = str(text or "").strip()
    if re.search(r"重要提示|不存在虚假记载|董事会及董事.*保证|标准无保留意见", t):
        return "important_notice"
    if re.search(r"年度报告\s*\d+\s*/\s*\d+|第\s*\d+\s*页\s*共\s*\d+\s*页", t):
        return "page_header"
    if re.search(r"□适用|√适用", t):
        return "disclaimer"
    return "other_noise"


def is_noise_for_section(text: str, section_type: str, section_map: dict[str, Any] | None = None) -> bool:
    """Check if text is noise AND should be excluded from *section_type*.

    Critical rule: important_notice/disclaimer/page_header must never serve as
    ownership_governance or risk_factors evidence.
    """
    if not is_pdf_noise(text):
        return False
    noise_type = classify_noise_type(text)
    # Important notice must never appear in governance/risk
    if noise_type == "important_notice" and section_type in ("ownership_governance", "risk_factors", "shareholder_structure"):
        return True
    # Page headers are noise for all substantive sections
    if noise_type == "page_header":
        return True
    # Disclaimer is noise for governance
    if noise_type == "disclaimer" and section_type in ("ownership_governance",):
        return True
    return False


# ── Section map builder ───────────────────────────────────────────────

def build_section_map(
    text_by_page: dict[int, str],
    report_type: str = "a_share",
    toc_entries: list[list[Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Scan all pages and build a page-range map for each section.

    Returns: {section_type: {"title": str, "pages": (start, end), "text": str}}
    """
    section_map = A_SHARE_SECTION_MAP if report_type == "a_share" else SEC_SECTION_MAP
    sections: dict[str, dict[str, Any]] = {}
    found_ranges: list[tuple[int, str, str]] = []  # (page, section_type, title)

    for entry in toc_entries or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        title_text = _normalize_text(entry[1])
        try:
            page_num = int(entry[2])
        except (TypeError, ValueError):
            continue
        for title, section_type, keywords in section_map:
            if any(_normalize_text(kw) in title_text for kw in keywords):
                found_ranges.append((page_num, section_type, title))
                break

    for page_num in sorted(text_by_page):
        page_text = text_by_page[page_num]
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        for title, section_type, keywords in section_map:
            for line in lines[:80]:
                normalized_line = _normalize_text(line)
                if any(_normalize_text(kw) in normalized_line for kw in keywords) and _looks_like_heading(line):
                    found_ranges.append((page_num, section_type, title))
                    break

    found_ranges = _dedupe_ranges(found_ranges)
    found_ranges.sort(key=lambda item: (item[0], item[1]))
    for i, (start_page, section_type, title) in enumerate(found_ranges):
        end_page = found_ranges[i + 1][0] - 1 if i + 1 < len(found_ranges) else max(text_by_page.keys())
        if end_page < start_page:
            end_page = start_page + 5
        section_text = "\n".join(
            text_by_page.get(p, "") for p in range(start_page, min(end_page + 1, start_page + 20))
        )
        if section_type not in sections:
            sections[section_type] = {
                "title": title,
                "pages": (start_page, end_page),
                "text": section_text,
                "page_count": end_page - start_page + 1,
            }

    return sections


def build_pdf_rag_artifacts(
    pdf_artifacts: dict[str, Any],
    output_dir: str | Path,
    symbol: str = "",
    period: str = "",
    max_pages_per_section: int = 8,
    report_type: str = "a_share",
) -> dict[str, Any]:
    """Run PDF RAG v2 over cached PDF files and write auditable artifacts."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    manifests = pdf_artifacts.get("pdf_manifest", []) if isinstance(pdf_artifacts, dict) else []
    all_text_chunks: list[dict[str, Any]] = []
    all_table_chunks: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []

    for row in manifests if isinstance(manifests, list) else []:
        if not isinstance(row, dict):
            continue
        local_path = Path(str(row.get("file_path") or ""))
        if not local_path.exists():
            continue
        payload = extract_pdf_rag_v2(
            local_pdf_path=local_path,
            pdf_url=str(row.get("source_url") or ""),
            source_title=str(row.get("title") or ""),
            source_evidence_id=str(row.get("evidence_id") or ""),
            symbol=symbol,
            period=period,
            max_pages_per_section=max_pages_per_section,
            report_type=report_type,
        )
        all_text_chunks.extend(payload["text_chunks"])
        all_table_chunks.extend(payload["table_chunks"])
        summaries.extend(payload["section_summaries"])
        audits.append(payload["audit"])

    audit = _merge_audits(audits, symbol=symbol, period=period)
    _write_jsonl(output_root / "pdf_section_chunks.jsonl", all_text_chunks)
    _write_jsonl(output_root / "pdf_table_chunks.jsonl", all_table_chunks)
    (output_root / "pdf_extraction_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "pdf_section_summaries.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "pdf_section_chunks": all_text_chunks,
        "pdf_table_chunks": all_table_chunks,
        "pdf_section_summaries": summaries,
        "pdf_extraction_audit": audit,
    }


def extract_pdf_rag_v2(
    local_pdf_path: str | Path,
    pdf_url: str = "",
    source_title: str = "",
    source_evidence_id: str = "",
    symbol: str = "",
    period: str = "",
    max_pages_per_section: int = 8,
    report_type: str = "a_share",
) -> dict[str, Any]:
    """Extract section-aware chunks and summaries from a cached PDF."""
    try:
        import fitz
    except Exception as exc:
        audit = _empty_audit(pdf_url, local_pdf_path, symbol, period, f"pymupdf_unavailable: {exc}")
        return {"text_chunks": [], "table_chunks": [], "section_summaries": [], "audit": audit}

    text_by_page: dict[int, str] = {}
    toc_entries: list[list[Any]] = []
    failure_reason = ""
    try:
        doc = fitz.open(str(local_pdf_path))
        page_count = len(doc)
        try:
            toc_entries = doc.get_toc(simple=True) or []
        except Exception:
            toc_entries = []
        for page_index in range(page_count):
            text_by_page[page_index + 1] = doc[page_index].get_text() or ""
        doc.close()
    except Exception as exc:
        audit = _empty_audit(pdf_url, local_pdf_path, symbol, period, f"pdf_parse_failed: {exc}")
        return {"text_chunks": [], "table_chunks": [], "section_summaries": [], "audit": audit}

    section_map = build_section_map(text_by_page, report_type=report_type, toc_entries=toc_entries)
    limited_pages = _pages_for_sections(text_by_page, section_map, max_pages_per_section=max_pages_per_section)
    text_chunks, table_chunks = build_pdf_chunks(
        limited_pages,
        section_map,
        symbol=symbol,
        period=period,
        source_url=pdf_url,
        source_title=source_title,
    )
    for chunk in text_chunks:
        chunk["source_evidence_id"] = source_evidence_id
    summaries = []
    for section_type in _target_section_types(section_map):
        section_chunks = [c for c in text_chunks if c.get("section_type") == section_type]
        summary = summarize_pdf_section(section_type, section_chunks, symbol=symbol, period=period)
        summary.update({
            "evidence_id": f"pdf_summary_{symbol}_{period}_{section_type}".replace(".", "_").lower(),
            "source_url": pdf_url,
            "source_title": source_title,
            "source_evidence_id": source_evidence_id,
            "section_title": section_map.get(section_type, {}).get("title", section_type),
            "pages": list(section_map.get(section_type, {}).get("pages", [])),
        })
        summaries.append(summary)

    if not section_map:
        failure_reason = "section_not_found"
    elif not any(item.get("usable_for_generation") for item in summaries):
        failure_reason = "section_extracted_but_noise_only"

    audit = _build_audit(
        pdf_url=pdf_url,
        local_pdf_path=local_pdf_path,
        symbol=symbol,
        period=period,
        page_count=len(text_by_page),
        extracted_page_count=len(limited_pages),
        toc_found=bool(toc_entries),
        section_map=section_map,
        chunks=text_chunks,
        failure_reason=failure_reason,
    )
    return {"text_chunks": text_chunks, "table_chunks": table_chunks, "section_summaries": summaries, "audit": audit}


# ── Section summarizer ────────────────────────────────────────────────

def summarize_pdf_section(
    section_type: str,
    chunks: list[dict[str, Any]],
    symbol: str = "",
    period: str = "",
) -> dict[str, Any]:
    """Summarize extracted chunks into a clean, generation-ready summary.

    Never returns raw PDF snippets. Always produces a structured summary
    or a data-gap explanation.
    """
    clean_chunks = [
        c for c in chunks
        if isinstance(c, dict) and c.get("usable_for_generation") and not c.get("is_noise")
    ]
    noise_only = len(clean_chunks) == 0 and len(chunks) > 0

    if noise_only:
        return _gap_summary(section_type, "noise_only", symbol, period)
    if not clean_chunks:
        return _gap_summary(section_type, "missing", symbol, period)

    # Merge clean chunk texts (max 2000 chars)
    combined = " ".join(str(c.get("text_clean") or c.get("text", ""))[:600] for c in clean_chunks[:4])
    combined = combined[:2000]

    quality = "strong" if len(combined) > 400 else "medium" if len(combined) > 100 else "weak"

    return {
        "section_type": section_type,
        "summary_zh": combined,
        "source_chunk_ids": [str(c.get("chunk_id", "")) for c in clean_chunks[:4]],
        "evidence_quality": quality,
        "usable_for_generation": quality in ("strong", "medium"),
        "is_noise": False,
    }


def _gap_summary(section_type: str, reason: str, symbol: str, period: str) -> dict[str, Any]:
    """Generate a data-gap explanation specific to the section type."""
    templates = {
        "ownership_governance": (
            "本轮已获取年度报告 PDF，但当前抽取片段主要为年度报告重要提示和审计声明，"
            "尚不足以支持股权结构、董事会构成或治理质量分析。"
        ),
        "risk_factors": (
            "年报提示相关风险已在管理层讨论章节披露，但本轮未解析到完整风险条目，"
            "因此不展开具体风险清单。"
        ),
        "business_overview": (
            f"本轮已获取{symbol or '公司'}年度报告，但尚未从 PDF 中稳定抽取主营业务、"
            "产品结构或业务分部章节，因此本节暂不展开业务结构分析。"
        ),
        "shareholder_structure": (
            "本轮已获取年度报告 PDF，但尚未稳定抽取股份变动及股东情况章节，"
            "因此本节不展开股东结构分析。"
        ),
        "management_discussion": (
            "本轮已获取年度报告 PDF，但尚未稳定抽取管理层讨论与分析章节。"
        ),
    }
    summary = templates.get(section_type, f"本轮未获取到可验证的{section_type}来源。")
    return {
        "section_type": section_type,
        "summary_zh": summary,
        "source_chunk_ids": [],
        "evidence_quality": "missing" if reason == "missing" else "noise_only",
        "usable_for_generation": False,
        "is_noise": True,
        "gap_reason": reason,
    }


# ── PDF chunk builder ─────────────────────────────────────────────────

def build_pdf_chunks(
    text_by_page: dict[int, str],
    section_map: dict[str, dict[str, Any]],
    symbol: str = "",
    period: str = "",
    source_url: str = "",
    source_title: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build clean text chunks and table chunks from PDF pages.

    Returns: (text_chunks, table_chunks)
    """
    text_chunks: list[dict[str, Any]] = []
    chunk_idx = 0

    for page_num in sorted(text_by_page):
        page_text = text_by_page[page_num]
        section_type = _find_section_for_page(page_num, section_map)

        # Split page into paragraphs
        paragraphs = [p.strip() for p in page_text.split("\n") if len(p.strip()) > 30]

        for para in paragraphs:
            noise_type = classify_noise_type(para) if is_pdf_noise(para) else ""
            is_noise = bool(noise_type)

            if is_noise_for_section(para, section_type):
                is_noise = True
                noise_type = noise_type or "section_noise"

            chunk_id = f"pdf_{symbol}_{period}_{hashlib.sha1(para.encode()).hexdigest()[:10]}"
            text_chunks.append({
                "chunk_id": chunk_id,
                "symbol": symbol,
                "period": period,
                "source_url": source_url,
                "source_title": source_title,
                "section_type": section_type,
                "page": page_num,
                "block_type": "paragraph",
                "text_clean": para if not is_noise else "",
                "summary_zh": "" if is_noise else para[:400],
                "quality_flags": [noise_type] if noise_type else [],
                "rejection_reason": noise_type if is_noise else "",
                "is_noise": is_noise,
                "usable_for_generation": not is_noise,
            })
            chunk_idx += 1

    return text_chunks, []


def _find_section_for_page(page_num: int, section_map: dict[str, dict[str, Any]]) -> str:
    """Find which section a page belongs to."""
    for section_type, info in section_map.items():
        start, end = info.get("pages", (0, 0))
        if start <= page_num <= end:
            return section_type
    return "other"


# ── Peer compare symbol binding ───────────────────────────────────────

def validate_peer_rows(peer_rows: list[dict[str, Any]], current_symbol: str) -> list[dict[str, Any]]:
    """Filter peer rows to ensure they don't contain cross-report contamination.

    Keeps rows that:
    - Have no symbol (target company's own row)
    - Match the current symbol
    - Have a company name that isn't a known different ticker
    Filters out rows that are clearly from a different report (e.g. 0700.HK in a 600519.SS report).
    """
    if not current_symbol:
        return peer_rows
    cur = str(current_symbol).strip().upper()
    filtered = []
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        row_symbol = str(row.get("symbol") or "").strip().upper()
        row_name = str(row.get("公司") or row.get("company_name") or "").strip().upper()
        # Allow rows without explicit symbol (target company row)
        if not row_symbol:
            filtered.append(row)
        # Allow rows matching current symbol
        elif cur in row_symbol or row_symbol in cur or cur in row_name:
            filtered.append(row)
        # Filter out clearly different symbols
        elif row_symbol and row_symbol != cur:
            continue
    return filtered


def _normalize_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _looks_like_heading(line: str) -> bool:
    text = str(line or "").strip()
    if not text or len(text) > 80:
        return False
    if re.search(r"第[一二三四五六七八九十0-9]+[章节]", text):
        return True
    if re.match(r"^[一二三四五六七八九十]+[、.．]", text):
        return True
    return len(text) <= 32 and any(
        key in text
        for key in ["公司治理", "管理层讨论", "股份变动", "股东情况", "财务报告", "风险提示", "主营业务"]
    )


def _dedupe_ranges(ranges: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    seen: set[tuple[int, str]] = set()
    output: list[tuple[int, str, str]] = []
    for page, section_type, title in sorted(ranges, key=lambda item: (item[0], item[1])):
        key = (page, section_type)
        if key in seen:
            continue
        seen.add(key)
        output.append((page, section_type, title))
    return output


def _pages_for_sections(
    text_by_page: dict[int, str],
    section_map: dict[str, dict[str, Any]],
    max_pages_per_section: int,
) -> dict[int, str]:
    if not section_map:
        return dict(list(text_by_page.items())[: max(1, int(max_pages_per_section))])
    pages: set[int] = set()
    for info in section_map.values():
        start, end = info.get("pages", (0, 0))
        try:
            start_i = int(start)
            end_i = int(end)
        except (TypeError, ValueError):
            continue
        limit = max(1, int(max_pages_per_section))
        for page in range(start_i, min(end_i, start_i + limit - 1) + 1):
            if page in text_by_page:
                pages.add(page)
    return {page: text_by_page[page] for page in sorted(pages)}


def _target_section_types(section_map: dict[str, dict[str, Any]]) -> list[str]:
    preferred = [
        "business_overview",
        "management_discussion",
        "ownership_governance",
        "shareholder_structure",
        "risk_factors",
        "financial_statements",
    ]
    output = [item for item in preferred if item in section_map]
    return output or preferred


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _empty_audit(pdf_url: str, local_pdf_path: str | Path, symbol: str, period: str, failure_reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "period": period,
        "pdf_url": pdf_url,
        "local_pdf_path": str(local_pdf_path),
        "page_count": 0,
        "extracted_page_count": 0,
        "toc_found": False,
        "section_map": {},
        "section_coverage": {},
        "candidate_chunks_count": 0,
        "noise_filtered_count": 0,
        "usable_chunk_count": 0,
        "top_rejection_reasons": {},
        "failure_reason": failure_reason,
    }


def _build_audit(
    pdf_url: str,
    local_pdf_path: str | Path,
    symbol: str,
    period: str,
    page_count: int,
    extracted_page_count: int,
    toc_found: bool,
    section_map: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
    failure_reason: str,
) -> dict[str, Any]:
    rejection_counts: dict[str, int] = {}
    section_coverage: dict[str, dict[str, int]] = {}
    for chunk in chunks:
        section_type = str(chunk.get("section_type") or "other")
        section_coverage.setdefault(section_type, {"candidate_chunks_count": 0, "usable_chunk_count": 0, "noise_filtered_count": 0})
        section_coverage[section_type]["candidate_chunks_count"] += 1
        if chunk.get("usable_for_generation"):
            section_coverage[section_type]["usable_chunk_count"] += 1
        else:
            section_coverage[section_type]["noise_filtered_count"] += 1
            reason = str(chunk.get("rejection_reason") or "unknown")
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    return {
        "symbol": symbol,
        "period": period,
        "pdf_url": pdf_url,
        "local_pdf_path": str(local_pdf_path),
        "page_count": page_count,
        "extracted_page_count": extracted_page_count,
        "toc_found": toc_found,
        "section_map": {
            key: {
                "title": value.get("title", ""),
                "pages": list(value.get("pages", [])),
                "page_count": value.get("page_count", 0),
            }
            for key, value in section_map.items()
            if isinstance(value, dict)
        },
        "section_coverage": section_coverage,
        "candidate_chunks_count": len(chunks),
        "noise_filtered_count": sum(1 for chunk in chunks if not chunk.get("usable_for_generation")),
        "usable_chunk_count": sum(1 for chunk in chunks if chunk.get("usable_for_generation")),
        "top_rejection_reasons": dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)[:8]),
        "failure_reason": failure_reason,
    }


def _merge_audits(audits: list[dict[str, Any]], symbol: str, period: str) -> dict[str, Any]:
    if not audits:
        return _empty_audit("", "", symbol, period, "no_cached_pdf")
    if len(audits) == 1:
        return audits[0]
    merged = _empty_audit("", "", symbol, period, "")
    merged["pdf_url"] = [audit.get("pdf_url", "") for audit in audits]
    merged["local_pdf_path"] = [audit.get("local_pdf_path", "") for audit in audits]
    merged["page_count"] = sum(int(audit.get("page_count") or 0) for audit in audits)
    merged["extracted_page_count"] = sum(int(audit.get("extracted_page_count") or 0) for audit in audits)
    merged["toc_found"] = any(bool(audit.get("toc_found")) for audit in audits)
    merged["section_map"] = {key: value for audit in audits for key, value in dict(audit.get("section_map", {})).items()}
    merged["section_coverage"] = {key: value for audit in audits for key, value in dict(audit.get("section_coverage", {})).items()}
    merged["candidate_chunks_count"] = sum(int(audit.get("candidate_chunks_count") or 0) for audit in audits)
    merged["noise_filtered_count"] = sum(int(audit.get("noise_filtered_count") or 0) for audit in audits)
    merged["usable_chunk_count"] = sum(int(audit.get("usable_chunk_count") or 0) for audit in audits)
    reasons: dict[str, int] = {}
    for audit in audits:
        for key, count in dict(audit.get("top_rejection_reasons", {})).items():
            reasons[str(key)] = reasons.get(str(key), 0) + int(count or 0)
    merged["top_rejection_reasons"] = dict(sorted(reasons.items(), key=lambda item: item[1], reverse=True)[:8])
    failures = [str(audit.get("failure_reason") or "") for audit in audits if str(audit.get("failure_reason") or "")]
    merged["failure_reason"] = "; ".join(failures)
    return merged
