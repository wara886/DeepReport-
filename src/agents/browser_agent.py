"""BrowserAgent for source extraction and evidence normalization."""

from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from urllib import error, request

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.data.source_quality import apply_source_quality
from src.models import ModelAdapter
from src.utils.config import load_config


BROWSER_SYSTEM_PROMPT = """You are BrowserAgent in a financial research multi-agent system.
Normalize source snippets into concise evidence records.
Return only valid JSON with:
{"records":[{"evidence_id":"...","title":"...","content":"...","source_url":"...","source_type":"...","key_points":["..."]}]}
Do not invent sources or numbers.
"""


class BrowserAgent(BaseAgent):
    """Extract structured evidence from search candidates."""

    def __init__(self, model: ModelAdapter | None = None, tools: Dict[str, Any] | None = None):
        super().__init__(name="BrowserAgent", model=model, tools=tools)

    def get_capabilities(self) -> List[str]:
        return [
            "normalize search hits into evidence records",
            "extract source snippets and key points",
            "prepare citation-ready source metadata for analysis",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        candidates = task.parameters.get("evidence_candidates", [])
        if not isinstance(candidates, list):
            return self.failure(task, "evidence_candidates must be a list")

        records = normalize_evidence_candidates(candidates)
        llm_notes: Dict[str, Any] = {}
        use_reader = bool(task.parameters.get("use_reader", False))
        use_playwright = bool(task.parameters.get("use_playwright", False))
        use_pdf_reader = bool(task.parameters.get("use_pdf_reader", True))
        reader_max_records = int(task.parameters.get("reader_max_records", 6) or 6)
        reader_max_chars = int(task.parameters.get("reader_max_chars", 4000) or 4000)
        pdf_max_pages = int(task.parameters.get("pdf_max_pages", 12) or 12)
        if use_reader or use_playwright:
            records, reader_meta = enrich_records_with_reader(
                records=records,
                max_records=reader_max_records,
                max_chars=reader_max_chars,
                prefer_playwright=use_playwright,
                use_pdf_reader=use_pdf_reader,
                pdf_max_pages=pdf_max_pages,
            )
            llm_notes["reader"] = reader_meta

        skip_llm = bool(task.parameters.get("skip_llm_extract", False))
        max_llm_records = int(task.parameters.get("max_llm_records", 8) or 8)
        if self.model and records and not skip_llm:
            try:
                llm_payload = self.model.generate_json(
                    prompt=_build_browser_prompt(records[:max_llm_records]),
                    system_prompt=BROWSER_SYSTEM_PROMPT,
                    extra_body={"max_tokens": 1200},
                )
                if isinstance(llm_payload.get("records"), list):
                    llm_notes = {"llm_record_count": len(llm_payload["records"])}
                    records = merge_llm_key_points(records, llm_payload["records"])
            except Exception as exc:
                llm_notes["llm_error"] = str(exc)
        elif skip_llm:
            llm_notes = {"llm_skipped": True}

        return self.success(task, {"evidence_records": records}, metadata=llm_notes)


def normalize_evidence_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else item
        evidence_id = str(
            raw.get("evidence_id")
            or raw.get("sample_id")
            or item.get("result_id")
            or f"evidence_{index:03d}"
        )
        content = str(raw.get("content") or item.get("snippet") or "")
        records.append(
            apply_source_quality(
                {
                "evidence_id": evidence_id,
                "sample_id": evidence_id,
                "symbol": str(raw.get("symbol", "")),
                "period": str(raw.get("period", "")),
                "source_type": str(raw.get("source_type") or item.get("source_type") or "unknown"),
                "title": str(raw.get("title") or item.get("title") or evidence_id),
                "source_url": str(raw.get("source_url") or item.get("url") or ""),
                "publish_time": str(raw.get("publish_time", "")),
                "content": content,
                "trust_level": str(raw.get("trust_level", "")),
                "score": float(item.get("score", raw.get("score", 0.0)) or 0.0),
                "key_points": _fallback_key_points(content),
                "metadata": dict(raw.get("metadata", {})) if isinstance(raw.get("metadata"), dict) else {},
                }
            )
        )
    return records


def enrich_records_with_reader(
    records: List[Dict[str, Any]],
    max_records: int = 6,
    max_chars: int = 4000,
    config_path: str = "configs/data_sources.yaml",
    prefer_playwright: bool = False,
    use_pdf_reader: bool = True,
    pdf_max_pages: int = 12,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    enriched = []
    meta = {
        "attempted": 0,
        "succeeded": 0,
        "errors": [],
        "engine": "playwright+jina+pdf" if prefer_playwright else "jina_reader+pdf",
    }
    for item in records:
        record = dict(item)
        source_url = str(record.get("source_url", ""))
        source_type = str(record.get("source_type", "")).lower()
        readable_source = source_url.startswith(("http://", "https://")) or (
            use_pdf_reader and bool(source_url) and _is_pdf_source(record)
        )
        should_read = (
            meta["attempted"] < max_records
            and readable_source
            and (source_type == "web_search" or (use_pdf_reader and _is_pdf_source(record)))
            and "youtube.com" not in source_url.lower()
            and "youtu.be" not in source_url.lower()
        )
        if should_read:
            meta["attempted"] += 1
            try:
                if use_pdf_reader and _is_pdf_source(record):
                    reader_payload = read_pdf_content(
                        str(record["source_url"]),
                        max_chars=max_chars,
                        max_pages=pdf_max_pages,
                        config_path=config_path,
                    )
                else:
                    reader_payload = read_url_content(
                        str(record["source_url"]),
                        max_chars=max_chars,
                        config_path=config_path,
                        prefer_playwright=prefer_playwright,
                    )
                if reader_payload["content"].strip():
                    record["content"] = reader_payload["content"]
                    record["key_points"] = _fallback_key_points(record["content"])
                    record.setdefault("metadata", {})["reader"] = {
                        "engine": reader_payload["engine"],
                        "reader_url": reader_payload["reader_url"],
                        "content_chars": len(reader_payload["content"]),
                    }
                    if reader_payload["engine"] == "pymupdf_pdf":
                        record["metadata"]["pdf"] = {
                            "page_count": reader_payload.get("page_count", 0),
                            "table_count": reader_payload.get("table_count", 0),
                            "financial_data_count": reader_payload.get("financial_data_count", 0),
                        }
                    meta["succeeded"] += 1
            except Exception as exc:
                meta["errors"].append({"url": record.get("source_url", ""), "error": str(exc)})
        enriched.append(record)
    return enriched, meta


def read_url_content(
    url: str,
    max_chars: int = 4000,
    config_path: str = "configs/data_sources.yaml",
    prefer_playwright: bool = False,
) -> Dict[str, str]:
    if _looks_like_pdf_url(url):
        return read_pdf_content(url, max_chars=max_chars, config_path=config_path)
    if prefer_playwright:
        try:
            return read_url_with_playwright(url=url, max_chars=max_chars, config_path=config_path)
        except Exception as exc:
            fallback = read_url_with_jina(url=url, max_chars=max_chars, config_path=config_path)
            fallback["engine"] = "jina_reader_after_playwright_error"
            fallback["playwright_error"] = str(exc)
            return fallback
    return read_url_with_jina(url=url, max_chars=max_chars, config_path=config_path)


def read_url_with_playwright(url: str, max_chars: int = 4000, config_path: str = "configs/data_sources.yaml") -> Dict[str, str]:
    cfg = load_config(config_path)
    browser_cfg = dict(cfg.get("search", {}).get("playwright_browser", {}))
    timeout_ms = int(browser_cfg.get("timeout_ms") or 12000)
    wait_until = str(browser_cfg.get("wait_until") or "domcontentloaded")
    max_chars = int(browser_cfg.get("max_chars") or max_chars)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && python -m playwright install chromium") from exc

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            title = page.title()
            text = page.locator("body").inner_text(timeout=timeout_ms)
            browser.close()
    except Exception as exc:
        raise RuntimeError(f"Playwright browser extraction failed: {exc}") from exc

    content = f"{title}\n\n{text}".strip() if title else text
    return {"reader_url": url, "content": content[:max_chars], "engine": "playwright_browser"}


def read_url_with_jina(url: str, max_chars: int = 4000, config_path: str = "configs/data_sources.yaml") -> Dict[str, str]:
    cfg = load_config(config_path)
    reader_cfg = dict(cfg.get("search", {}).get("jina_reader", {}))
    base_url = str(reader_cfg.get("base_url") or "https://r.jina.ai").rstrip("/")
    timeout = float(reader_cfg.get("timeout", 12))
    max_chars = int(reader_cfg.get("max_chars") or max_chars)
    reader_url = f"{base_url}/{url}"
    req = request.Request(
        reader_url,
        headers={
            "Accept": "text/plain",
            "User-Agent": "FinSight/0.1",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("Jina Reader timed out") from exc
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Jina Reader HTTP {exc.code}: {body[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Jina Reader URL error: {exc.reason}") from exc
    return {"reader_url": reader_url, "content": raw[:max_chars], "engine": "jina_reader"}


def read_pdf_content(
    pdf_path_or_url: str,
    max_chars: int = 4000,
    max_pages: int = 12,
    config_path: str = "configs/data_sources.yaml",
) -> Dict[str, Any]:
    cfg = load_config(config_path)
    pdf_cfg = dict(cfg.get("search", {}).get("pdf_reader", {}))
    timeout = float(pdf_cfg.get("timeout", 20))
    max_chars = int(pdf_cfg.get("max_chars") or max_chars)
    max_pages = int(pdf_cfg.get("max_pages") or max_pages)

    try:
        import fitz
    except Exception as exc:
        raise RuntimeError("PyMuPDF is not installed. Install the optional pdf dependency to enable PDF extraction.") from exc

    local_path = pdf_path_or_url
    temp_path = ""
    if pdf_path_or_url.startswith(("http://", "https://")):
        suffix = ".pdf" if _looks_like_pdf_url(pdf_path_or_url) else ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            temp_path = tmp.name
        req = request.Request(
            pdf_path_or_url,
            headers={"User-Agent": "FinSight/0.1"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                Path(temp_path).write_bytes(resp.read())
            local_path = temp_path
        except (TimeoutError, socket.timeout) as exc:
            _cleanup_temp_file(temp_path)
            raise RuntimeError("PDF download timed out") from exc
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            _cleanup_temp_file(temp_path)
            raise RuntimeError(f"PDF download HTTP {exc.code}: {body[:300]}") from exc
        except error.URLError as exc:
            _cleanup_temp_file(temp_path)
            raise RuntimeError(f"PDF download URL error: {exc.reason}") from exc

    doc = None
    try:
        doc = fitz.open(local_path)
        text_blocks: List[str] = []
        tables: List[Dict[str, Any]] = []
        financial_hits: List[Dict[str, Any]] = []
        page_total = len(doc)
        pages_to_read = min(page_total, max_pages)
        indicators = [
            "revenue",
            "profit",
            "cash flow",
            "assets",
            "liabilities",
            "equity",
            "gross margin",
            "net income",
            "营业收入",
            "净利润",
            "现金流",
            "资产",
            "负债",
            "股东权益",
            "毛利率",
        ]

        for page_index in range(pages_to_read):
            page = doc[page_index]
            page_text = page.get_text() or ""
            if page_text.strip():
                text_blocks.append(f"[PDF page {page_index + 1}]\n{page_text.strip()}")
            lowered = page_text.lower()
            found = [item for item in indicators if item.lower() in lowered]
            if found:
                financial_hits.append({"page": page_index + 1, "indicators": found})
            tables.extend(_extract_pdf_tables(page=page, page_number=page_index + 1))

        table_preview = _format_pdf_table_preview(tables)
        content = "\n\n".join([part for part in ["\n\n".join(text_blocks), table_preview] if part]).strip()
        return {
            "reader_url": pdf_path_or_url,
            "content": content[:max_chars],
            "engine": "pymupdf_pdf",
            "page_count": page_total,
            "pages_read": pages_to_read,
            "table_count": len(tables),
            "financial_data_count": len(financial_hits),
            "tables": tables[:10],
            "financial_data": financial_hits[:20],
        }
    finally:
        if doc is not None:
            doc.close()
        _cleanup_temp_file(temp_path)


def merge_llm_key_points(records: List[Dict[str, Any]], llm_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {str(item.get("evidence_id", "")): item for item in llm_records if isinstance(item, dict)}
    merged = []
    for record in records:
        llm_item = by_id.get(record["evidence_id"])
        if llm_item and isinstance(llm_item.get("key_points"), list):
            record = dict(record)
            record["key_points"] = [str(item) for item in llm_item["key_points"] if str(item).strip()]
        merged.append(record)
    return merged


def _is_pdf_source(record: Dict[str, Any]) -> bool:
    source_url = str(record.get("source_url") or "")
    source_type = str(record.get("source_type") or "").lower()
    return _looks_like_pdf_url(source_url) or source_type in {"pdf", "filing_pdf", "annual_report_pdf"}


def _looks_like_pdf_url(value: str) -> bool:
    cleaned = value.split("?", 1)[0].split("#", 1)[0].lower()
    return cleaned.endswith(".pdf")


def _extract_pdf_tables(page: Any, page_number: int) -> List[Dict[str, Any]]:
    if not hasattr(page, "find_tables"):
        return []
    try:
        table_finder = page.find_tables()
    except Exception:
        return []
    raw_tables = getattr(table_finder, "tables", table_finder)
    if raw_tables is None:
        return []

    output: List[Dict[str, Any]] = []
    for table in raw_tables:
        try:
            data = table.extract()
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        rows = len(data)
        cols = max((len(row) for row in data if isinstance(row, list)), default=0)
        output.append({"page": page_number, "rows": rows, "cols": cols, "data": data[:20]})
    return output


def _format_pdf_table_preview(tables: List[Dict[str, Any]], max_tables: int = 5, max_rows: int = 5) -> str:
    lines: List[str] = []
    for table_index, table in enumerate(tables[:max_tables], start=1):
        lines.append(f"[PDF table {table_index} page {table.get('page')}]")
        for row in table.get("data", [])[:max_rows]:
            if isinstance(row, list):
                cells = [str(cell).strip() for cell in row if str(cell).strip()]
                if cells:
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def _cleanup_temp_file(path: str) -> None:
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _fallback_key_points(content: str) -> List[str]:
    sentences = [part.strip() for part in content.replace("\n", " ").split(".") if part.strip()]
    return sentences[:3] or ([content[:180]] if content else [])


def _build_browser_prompt(records: List[Dict[str, Any]]) -> str:
    compact = [
        {
            "evidence_id": item["evidence_id"],
            "title": item["title"],
            "source_url": item["source_url"],
            "source_type": item["source_type"],
            "content": item["content"][:600],
        }
        for item in records
    ]
    return f"Normalize these source records for financial analysis:\n{compact}"
