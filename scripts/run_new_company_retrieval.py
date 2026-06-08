"""Real-time API retrieval for 9 new companies (3 per market, not in the 15).

For each company × period, calls relevant market data source APIs and archives
the raw engine outputs for analysis.

Run: python -m scripts.run_new_company_retrieval
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.search.search_manager import (
    yahoo_finance_search,
    eastmoney_search,
    eastmoney_financials_search,
    cninfo_announcement_search,
    hkex_announcement_search,
    sec_edgar_search,
    tavily_search,
    serper_search,
    independent_macro_search,
    local_real_data_search,
)

BASE = Path("data/new_company_retrieval")
RAW_ROOT = "data/raw/real_data"

# ── 9 new companies (3 per market, none in the original 15) ──

COMPANIES = {
    "A_SHARE": [
        {
            "symbol": "000858.SZ",
            "name": "五粮液 Wuliangye",
            "periods": ["2026Q1", "FY2025", "FY2024"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("eastmoney", lambda s, p: eastmoney_search(f"{s} 财报", symbol=s, period=p)),
                ("eastmoney_financials", lambda s, p: eastmoney_financials_search("000858", symbol=s, period=p)),
                ("cninfo_announcements", lambda s, p: cninfo_announcement_search(f"{s} 年度报告", symbol=s, period=p)),
            ],
        },
        {
            "symbol": "601318.SS",
            "name": "中国平安 Ping An Insurance",
            "periods": ["2026Q1", "FY2025", "FY2024"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("eastmoney", lambda s, p: eastmoney_search(f"{s} 财报", symbol=s, period=p)),
                ("eastmoney_financials", lambda s, p: eastmoney_financials_search("601318", symbol=s, period=p)),
                ("cninfo_announcements", lambda s, p: cninfo_announcement_search(f"{s} 年度报告", symbol=s, period=p)),
            ],
        },
        {
            "symbol": "000333.SZ",
            "name": "美的集团 Midea",
            "periods": ["2026Q1", "FY2025", "FY2024"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("eastmoney", lambda s, p: eastmoney_search(f"{s} 财报", symbol=s, period=p)),
                ("eastmoney_financials", lambda s, p: eastmoney_financials_search("000333", symbol=s, period=p)),
                ("cninfo_announcements", lambda s, p: cninfo_announcement_search(f"{s} 年度报告", symbol=s, period=p)),
            ],
        },
    ],
    "HK": [
        {
            "symbol": "9988.HK",
            "name": "阿里巴巴 Alibaba",
            "periods": ["FY2025", "FY2024", "FY2023"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("hkex_announcements", lambda s, p: hkex_announcement_search(f"Alibaba {p} annual report", symbol=s)),
                ("tavily", lambda s, p: tavily_search(f"Alibaba {p} financial performance", symbol=s)),
                ("serper", lambda s, p: serper_search(f"Alibaba {p} results", symbol=s)),
            ],
        },
        {
            "symbol": "3690.HK",
            "name": "美团 Meituan",
            "periods": ["FY2025", "FY2024", "FY2023"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("hkex_announcements", lambda s, p: hkex_announcement_search(f"Meituan {p} annual report", symbol=s)),
                ("tavily", lambda s, p: tavily_search(f"Meituan {p} financial results", symbol=s)),
                ("serper", lambda s, p: serper_search(f"Meituan {p} annual results", symbol=s)),
            ],
        },
        {
            "symbol": "1810.HK",
            "name": "小米 Xiaomi",
            "periods": ["FY2025", "FY2024", "FY2023"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("hkex_announcements", lambda s, p: hkex_announcement_search(f"Xiaomi {p} annual report", symbol=s)),
                ("tavily", lambda s, p: tavily_search(f"Xiaomi {p} financial results", symbol=s)),
                ("serper", lambda s, p: serper_search(f"Xiaomi {p} annual results", symbol=s)),
            ],
        },
    ],
    "US": [
        {
            "symbol": "MSFT",
            "name": "Microsoft",
            "periods": ["2026Q3", "FY2025", "FY2024"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("sec_edgar", lambda s, p: sec_edgar_search(f"Microsoft 10-K {p}", symbol=s, period=p)),
                ("independent_macro", lambda s, p: independent_macro_search(f"technology sector {p}", period=p)),
            ],
        },
        {
            "symbol": "META",
            "name": "Meta",
            "periods": ["2026Q1", "FY2025", "FY2024"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("sec_edgar", lambda s, p: sec_edgar_search(f"Meta 10-K {p}", symbol=s, period=p)),
                ("independent_macro", lambda s, p: independent_macro_search(f"social media sector {p}", period=p)),
            ],
        },
        {
            "symbol": "AMZN",
            "name": "Amazon",
            "periods": ["2026Q1", "FY2025", "FY2024"],
            "engines": [
                ("yahoo_finance", lambda s, p: yahoo_finance_search(s, symbol=s, period=p)),
                ("sec_edgar", lambda s, p: sec_edgar_search(f"Amazon 10-K {p}", symbol=s, period=p)),
                ("independent_macro", lambda s, p: independent_macro_search(f"e-commerce sector {p}", period=p)),
            ],
        },
    ],
}


def run_engines(symbol: str, period: str, engines: list, run_dir: Path) -> dict:
    """Run all engines for one (symbol, period) combo. Returns engine_meta dict."""
    run_dir.mkdir(parents=True, exist_ok=True)
    engine_meta = {}
    all_hits = []

    for engine_name, engine_fn in engines:
        print(f"    {engine_name}...", end=" ", flush=True)
        t0 = time.time()
        try:
            result = engine_fn(symbol, period) or {}
            elapsed = round(time.time() - t0, 2)
            hits = result.get("hits", [])
            meta = result.get("meta", {})
            hit_count = len(hits)
            engine_meta[engine_name] = {
                "hit_count": hit_count,
                "elapsed_sec": elapsed,
                "status": "ok",
                "meta_keys": list(meta.keys()) if isinstance(meta, dict) else [],
            }
            print(f"{hit_count} hits in {elapsed}s")

            # Save per-engine hits
            if hits:
                (run_dir / f"engine_{engine_name}.json").write_text(
                    json.dumps({"engine": engine_name, "symbol": symbol, "period": period,
                                "hits": hits, "meta": meta},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                all_hits.extend(hits)

        except Exception as exc:
            elapsed = round(time.time() - t0, 2)
            err = str(exc)[:300]
            engine_meta[engine_name] = {"hit_count": 0, "elapsed_sec": elapsed,
                                        "status": "error", "error": err}
            print(f"FAILED ({err[:80]})")

    # Write search_meta.json (like the multi-agent pipeline does)
    search_meta = {
        "engines": [e[0] for e in engines],
        "engine_meta": engine_meta,
        "total_hits": len(all_hits),
        "symbol": symbol,
        "period": period,
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (run_dir / "search_meta.json").write_text(
        json.dumps(search_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write all hits merged
    if all_hits:
        (run_dir / "all_engine_hits.json").write_text(
            json.dumps(all_hits, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write a quick summary
    summary = _make_run_summary(symbol, period, engine_meta)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return engine_meta


def _make_run_summary(symbol: str, period: str, engine_meta: dict) -> dict:
    """Build a concise summary of what data was retrieved."""
    total_hits = sum(m.get("hit_count", 0) for m in engine_meta.values())
    engines_with_data = [k for k, v in engine_meta.items() if v.get("hit_count", 0) > 0]
    engines_failed = [k for k, v in engine_meta.items() if v.get("status") == "error"]
    return {
        "symbol": symbol,
        "period": period,
        "total_hits": total_hits,
        "engines_with_data": engines_with_data,
        "engines_failed": engines_failed,
        "data_quality": "good" if total_hits >= 5 else "sparse" if total_hits > 0 else "empty",
    }


def run_market(market_name: str, companies: list) -> dict:
    """Run retrieval for all companies in a market. Returns aggregate stats."""
    print(f"\n{'='*70}")
    print(f" {market_name} — {len(companies)} companies")
    print(f"{'='*70}")

    market_dir = BASE / market_name
    all_company_results = []

    for company in companies:
        sym = company["symbol"]
        name = company["name"]
        print(f"\n  ── {sym} ({name}) ──")

        for period in company["periods"]:
            label = f"{sym}_{period}"
            run_dir = market_dir / label
            print(f"  [{period}]")
            meta = run_engines(sym, period, company["engines"], run_dir)
            all_company_results.append({
                "symbol": sym,
                "name": name,
                "period": period,
                "engine_results": meta,
                "total_hits": sum(m.get("hit_count", 0) for m in meta.values()),
            })

    # Write market-level aggregation
    agg = _aggregate_market(market_name, all_company_results)
    (market_dir / "market_aggregate.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")

    return agg


def _aggregate_market(market_name: str, results: list) -> dict:
    """Aggregate across all companies/periods in a market."""
    total_runs = len(results)
    total_hits = sum(r["total_hits"] for r in results)

    # Per-engine aggregator
    engine_stats = defaultdict(lambda: {"calls": 0, "total_hits": 0, "errors": 0})
    for r in results:
        for engine, meta in r["engine_results"].items():
            engine_stats[engine]["calls"] += 1
            engine_stats[engine]["total_hits"] += meta.get("hit_count", 0)
            if meta.get("status") == "error":
                engine_stats[engine]["errors"] += 1

    hits_per_run = [r["total_hits"] for r in results]
    quality_good = sum(1 for r in results if r["total_hits"] >= 5)
    quality_sparse = sum(1 for r in results if r["total_hits"] > 0 and r["total_hits"] < 5)
    quality_empty = sum(1 for r in results if r["total_hits"] == 0)

    return {
        "market": market_name,
        "total_companies": len(set(r["symbol"] for r in results)),
        "total_runs": total_runs,
        "total_hits": total_hits,
        "avg_hits_per_run": round(total_hits / max(total_runs, 1), 1),
        "hits_range": [min(hits_per_run), max(hits_per_run)] if hits_per_run else [0, 0],
        "data_quality_distribution": {
            "good (>=5 hits)": quality_good,
            "sparse (1-4 hits)": quality_sparse,
            "empty (0 hits)": quality_empty,
        },
        "engine_performance": dict(engine_stats),
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def write_global_report(aggregates: dict) -> None:
    """Write a cross-market comparison report."""
    report_path = BASE / "cross_market_retrieval_report.json"
    report_path.write_text(
        json.dumps(aggregates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  → Global report: {report_path}")


if __name__ == "__main__":
    t_start = time.time()
    BASE.mkdir(parents=True, exist_ok=True)

    aggregates = {}
    for market_name, companies in COMPANIES.items():
        agg = run_market(market_name, companies)
        aggregates[market_name] = agg

    write_global_report(aggregates)

    elapsed = round(time.time() - t_start, 1)
    print(f"\n{'='*70}")
    print(f" Done in {elapsed}s")
    print(f"{'='*70}")
    for market, agg in aggregates.items():
        print(f"  {market}: {agg['total_companies']} companies × {agg['total_runs']} runs = {agg['total_hits']} total hits (avg {agg['avg_hits_per_run']}/run)")
