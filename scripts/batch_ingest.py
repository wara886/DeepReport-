"""
批量数据入库脚本：900 家公司 × 4 周期 → ChromaDB + SQLite。

用法：
    python scripts/batch_ingest.py --market cn_a      # 只跑 A 股
    python scripts/batch_ingest.py --market us        # 只跑美股
    python scripts/batch_ingest.py --symbol 600519.SS # 只跑单家公司
    python scripts/batch_ingest.py --resume           # 断点续跑
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# ── 项目根路径 ──
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.retrieval.chroma_index import ChromaIndex
from src.retrieval.evidence_store import EvidenceRecord
from src.utils.logging import configure_logging

logger = logging.getLogger("batch_ingest")

# ── 数据库路径 ──
CHROMA_DIR = PROJECT_ROOT / "data" / "vector_db"
SQLITE_PATH = PROJECT_ROOT / "data" / "batch_ingest" / "company_financials.db"
PROGRESS_PATH = PROJECT_ROOT / "data" / "batch_ingest" / "progress.json"
PDF_CACHE_DIR = PROJECT_ROOT / "data" / "batch_ingest" / "pdf_cache"

# ── 支持的周期 ──
PERIODS = ["FY2023", "FY2024", "FY2025", "2026Q1"]


def _init_sqlite() -> sqlite3.Connection:
    """初始化 SQLite 库（结构化财务数据）。"""
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS financial_metrics (
            symbol TEXT NOT NULL,
            period TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            value REAL,
            unit TEXT,
            source TEXT,
            ingested_at TEXT,
            PRIMARY KEY (symbol, period, metric_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_profiles (
            symbol TEXT PRIMARY KEY,
            company_name TEXT,
            market TEXT,
            sector TEXT,
            industry TEXT,
            ingested_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_log (
            symbol TEXT NOT NULL,
            period TEXT NOT NULL,
            status TEXT,
            sections_count INTEGER,
            metrics_count INTEGER,
            duration_sec REAL,
            error TEXT,
            ingested_at TEXT,
            PRIMARY KEY (symbol, period)
        )
    """)
    conn.commit()
    return conn


def _load_progress() -> Dict[str, Any]:
    """加载入库进度（支持断点续跑）。"""
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            return json.load(f)
    return {"completed": []}


def _save_progress(completed: List[str]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_PATH, "w") as f:
        json.dump({"completed": completed, "updated_at": datetime.now().isoformat()}, f)


def _is_already_ingested(conn: sqlite3.Connection, symbol: str, period: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ingest_log WHERE symbol=? AND period=? AND status='done'",
        (symbol, period),
    ).fetchone()
    return row is not None


# ── 数据采集函数 ──────────────────────────────────────

def _ingest_ashare(conn: sqlite3.Connection, chroma: ChromaIndex,
                   company: Dict[str, str], period: str) -> Dict[str, Any]:
    """采集 A 股数据：东财财报 + cninfo PDF"""
    from src.search.search_manager import eastmoney_financials_search

    symbol = company["symbol"]
    result = {"financial_metrics": 0, "sections": 0, "chunks": 0}

    # 1. 东财结构化财报
    em_result = eastmoney_financials_search(
        symbol, symbol=symbol, period=period, enable_remote=True,
    )
    for hit in em_result.get("hits", []):
        from src.data.financial_statement_metrics import _eastmoney_metric_rows
        metrics = _eastmoney_metric_rows(hit)
        for m in metrics:
            conn.execute(
                "INSERT OR REPLACE INTO financial_metrics VALUES (?,?,?,?,?,?,?)",
                (symbol, period, m["metric_name"], m.get("value"),
                 m.get("unit", ""), "eastmoney", datetime.now().isoformat()),
            )
            result["financial_metrics"] += 1
        conn.commit()

    # 2. 通过 cninfo 下载年报 PDF → chunk → ChromaDB
    try:
        from src.search.search_manager import cninfo_announcement_search
        pdf_result = cninfo_announcement_search(
            symbol, symbol=symbol, period=period, enable_remote=True,
        )
        pdf_hits = pdf_result.get("hits", [])
        for pdf_hit in pdf_hits[:2]:  # 最多 2 份 PDF
            source_url = pdf_hit.get("source_url", "")
            if not source_url or not source_url.lower().endswith(".pdf"):
                continue
            result["sections"] += _ingest_pdf_chunks(
                chroma, symbol, period, source_url, pdf_hit, "cn_a",
            )
    except Exception as exc:
        logger.warning("PDF ingest failed for %s %s: %s", symbol, period, exc)

    return result


def _ingest_us(conn: sqlite3.Connection, chroma: ChromaIndex,
               company: Dict[str, str], period: str) -> Dict[str, Any]:
    """采集美股数据：SEC companyfacts + 10-K"""
    from src.search.search_manager import sec_edgar_search

    symbol = company["symbol"]
    result = {"financial_metrics": 0, "sections": 0, "chunks": 0}

    # 1. SEC companyfacts 结构化数据
    sec_result = sec_edgar_search(symbol, symbol=symbol, period=period, enable_remote=True)
    for hit in sec_result.get("hits", []):
        if hit.get("source_type") == "sec_companyfacts":
            from src.data.financial_statement_metrics import _sec_companyfacts_metric_rows
            metrics = _sec_companyfacts_metric_rows(hit)
            for m in metrics:
                conn.execute(
                    "INSERT OR REPLACE INTO financial_metrics VALUES (?,?,?,?,?,?,?)",
                    (symbol, period, m["metric_name"], m.get("value"),
                     m.get("unit", ""), "sec_edgar", datetime.now().isoformat()),
                )
                result["financial_metrics"] += 1
            conn.commit()

    # 2. SEC 10-K 章节 → chunk → ChromaDB
    try:
        from src.agents.multi_agent_orchestrator import resolve_sec_annual_filing
        payload = resolve_sec_annual_filing(
            symbol=symbol, period=period, fetch_document=True,
        )
        data = payload.to_dict() if hasattr(payload, "to_dict") else {}
        sections_map = data.get("sections", {}) if isinstance(data.get("sections"), dict) else {}
        for section_key, items in sections_map.items():
            for item in items if isinstance(items, list) else [items]:
                if isinstance(item, dict):
                    text = str(item.get("text", ""))
                    if len(text) < 100:
                        continue
                    title = f"[{section_key}] {item.get('citation_title', '')}"
                    chunk_id = f"{symbol}_{period}_{section_key}_{item.get('chunk_index', 0)}"
                    record = EvidenceRecord(
                        sample_id=chunk_id,
                        source_type="sec_10k",
                        symbol=symbol,
                        period=period,
                        title=title,
                        content=text,
                        source_url=data.get("source_url", ""),
                        publish_time="",
                        trust_level="high",
                        evidence_id=chunk_id,
                    )
                    chroma.add_records([record])
                    result["chunks"] += 1
                    result["sections"] += 1
    except Exception as exc:
        logger.warning("SEC 10-K ingest failed for %s: %s", symbol, exc)

    return result


def _ingest_hk(conn: sqlite3.Connection, chroma: ChromaIndex,
               company: Dict[str, str], period: str) -> Dict[str, Any]:
    """采集港股数据：hk_financials 结构化数据"""
    from src.search.search_manager import hk_financials_search

    symbol = company["symbol"]
    result = {"financial_metrics": 0, "sections": 0, "chunks": 0}

    hk_result = hk_financials_search(symbol, symbol=symbol, period=period, enable_remote=True)
    for hit in hk_result.get("hits", []):
        from src.data.financial_statement_metrics import _hk_financials_metric_rows
        metrics = _hk_financials_metric_rows(hit)
        for m in metrics:
            conn.execute(
                "INSERT OR REPLACE INTO financial_metrics VALUES (?,?,?,?,?,?,?)",
                (symbol, period, m["metric_name"], m.get("value"),
                 m.get("unit", ""), "hk_financials", datetime.now().isoformat()),
            )
            result["financial_metrics"] += 1
        conn.commit()

    return result


def _ingest_pdf_chunks(
    chroma: ChromaIndex, symbol: str, period: str,
    pdf_url: str, pdf_hit: Dict[str, Any], market: str,
) -> int:
    """下载 PDF → 提取章节 → 切 chunk → 入库 ChromaDB。"""
    import hashlib
    from src.retrieval.evidence_store import EvidenceRecord

    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 下载 PDF
    try:
        import urllib.request
        digest = hashlib.md5(pdf_url.encode()).hexdigest()[:10]
        local_path = PDF_CACHE_DIR / f"{symbol}_{period}_{digest}.pdf"
        if not local_path.exists():
            urllib.request.urlretrieve(pdf_url, local_path)
    except Exception as exc:
        logger.warning("PDF download failed %s: %s", pdf_url, exc)
        return 0

    # 提取文本
    try:
        import fitz
        doc = fitz.open(str(local_path))
        text_by_page = {i + 1: doc[i].get_text() or "" for i in range(len(doc))}
        doc.close()
    except Exception as exc:
        logger.warning("PDF parse failed %s: %s", local_path, exc)
        return 0

    # 用 pdf_section_detector 做章节检测
    try:
        from src.report.fact_extractors.pdf_section_detector import detect_sections
        full_text = "\n".join(text_by_page.values())
        sections = detect_sections(full_text, market=market, include_unmatched=False)
    except Exception:
        sections = {}

    # 对每个章节：标题前置 → chunk → 入库
    chunks_inserted = 0
    for section_type, section_text in sections.items():
        if len(section_text.strip()) < 100:
            continue
        # chunk 标题前置（方便召回时命中）
        title_prefix = f"[{section_type}] "
        chunk_text = title_prefix + section_text.strip()

        chunk_id = f"{symbol}_{period}_{section_type}_{digest}"

        source_title = str(pdf_hit.get("title", "")) or f"{symbol} Annual Report"
        record = EvidenceRecord(
            sample_id=chunk_id,
            source_type="cninfo_annual_report_pdf",
            symbol=symbol,
            period=period,
            title=source_title,
            content=chunk_text,
            source_url=pdf_url,
            publish_time=str(pdf_hit.get("publish_time", "")),
            trust_level="high",
            evidence_id=chunk_id,
        )
        try:
            chroma.add_records([record])
            chunks_inserted += 1
        except Exception as exc:
            logger.warning("Chroma insert failed for %s: %s", chunk_id, exc)

    return chunks_inserted


# ── 主流程 ────────────────────────────────────────────

def _market_ingest_fn(market: str):
    """返回对应市场的数据采集函数"""
    fns = {
        "cn_a": _ingest_ashare,
        "us": _ingest_us,
        "hk": _ingest_hk,
    }
    return fns.get(market)


def main():
    parser = argparse.ArgumentParser(description="Batch ingest 900 companies × 4 periods")
    parser.add_argument("--market", choices=["cn_a", "us", "hk", "all"], default="all")
    parser.add_argument("--symbol", help="Run a single company only")
    parser.add_argument("--resume", action="store_true", help="Skip already ingested")
    parser.add_argument("--periods", nargs="+", default=PERIODS, help="Periods to ingest")
    args = parser.parse_args()

    configure_logging(log_dir="logs", run_name="batch_ingest")
    logger.info("Starting batch ingest")

    # 加载公司清单
    from scripts.company_universe import get_companies_by_market, get_all_companies
    if args.symbol:
        companies = [{"symbol": args.symbol, "name": args.symbol, "sector": "", "industry": ""}]
    elif args.market == "all":
        companies = get_all_companies()
    else:
        companies = get_companies_by_market(args.market)

    periods = args.periods or PERIODS
    logger.info("Companies: %d, Periods: %s", len(companies), periods)

    # 初始化存储
    conn = _init_sqlite()
    chroma = ChromaIndex(persistent_path=str(CHROMA_DIR))
    progress = _load_progress() if args.resume else {"completed": []}
    completed = set(progress.get("completed", []))

    total = len(companies) * len(periods)
    done = 0
    start_time = time.time()

    for company in companies:
        symbol = company["symbol"]
        market = "cn_a" if symbol.endswith((".SS", ".SZ")) else "hk" if symbol.endswith(".HK") else "us"

        # 保存公司 profile
        conn.execute(
            "INSERT OR REPLACE INTO company_profiles VALUES (?,?,?,?,?,?)",
            (symbol, company.get("name", ""), market,
             company.get("sector", ""), company.get("industry", ""),
             datetime.now().isoformat()),
        )
        conn.commit()

        for period in periods:
            done += 1
            task_key = f"{symbol}_{period}"

            if args.resume and task_key in completed:
                logger.debug("Skipping %s (already done)", task_key)
                continue

            if _is_already_ingested(conn, symbol, period):
                logger.debug("Skipping %s (in SQLite)", task_key)
                if args.resume:
                    completed.add(task_key)
                continue

            t0 = time.time()
            ingest_fn = _market_ingest_fn(market)
            if not ingest_fn:
                logger.warning("No ingest fn for %s market=%s", symbol, market)
                continue

            try:
                result = ingest_fn(conn, chroma, company, period)
                status = "done"
                error = ""
                logger.info(
                    "[%d/%d] %s %s: %d metrics, %d chunks (%.1fs)",
                    done, total, symbol, period,
                    result.get("financial_metrics", 0),
                    result.get("chunks", 0),
                    time.time() - t0,
                )
            except Exception as exc:
                status = "failed"
                error = str(exc)
                logger.error("[%d/%d] %s %s FAILED: %s", done, total, symbol, period, error)

            conn.execute(
                "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?,?,?,?)",
                (symbol, period, status, result.get("sections", 0),
                 result.get("financial_metrics", 0), time.time() - t0,
                 error, datetime.now().isoformat()),
            )
            conn.commit()

            if args.resume and status == "done":
                completed.add(task_key)
                _save_progress(list(completed))

    elapsed = time.time() - start_time
    logger.info("Batch ingest completed: %d companies × %d periods in %.1fs",
                len(companies), len(periods), elapsed)
    conn.close()


if __name__ == "__main__":
    main()
