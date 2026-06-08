"""Simulate real-time retrieval for three markets and archive raw products.

Creates data/market_simulation/{A_SHARE, US, HK}/ directories with raw
search engine outputs, simulating what each market's pipeline retrieves.

Run from repo root: python -m scripts.simulate_market_retrieval
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.search.search_manager import (
    local_real_data_search,
    sec_edgar_search,
    yahoo_finance_search,
    eastmoney_search,
    eastmoney_financials_search,
    cninfo_announcement_search,
    hkex_announcement_search,
    independent_macro_search,
    local_evidence_search,
)


BASE = Path("data/market_simulation")
RAW_ROOT = "data/raw/real_data"

MARKETS = {
    "A_SHARE": {
        "symbol": "600519.SS",
        "period": "FY2025",
        "engines": [
            ("local_real_data", lambda: local_real_data_search("贵州茅台", symbol="600519.SS", period="FY2025", raw_data_root=RAW_ROOT)),
            ("yahoo_finance", lambda: yahoo_finance_search("600519.SS", symbol="600519.SS", period="FY2025")),
            ("eastmoney", lambda: eastmoney_search("贵州茅台 2025年报", symbol="600519.SS", period="FY2025")),
            ("eastmoney_financials", lambda: eastmoney_financials_search("600519", symbol="600519.SS", period="FY2025")),
            ("cninfo_announcements", lambda: cninfo_announcement_search("600519 2025 年度报告", symbol="600519.SS", period="FY2025")),
        ],
    },
    "HK": {
        "symbol": "0700.HK",
        "period": "FY2025",
        "engines": [
            ("local_real_data", lambda: local_real_data_search("腾讯控股", symbol="0700.HK", period="FY2025", raw_data_root=RAW_ROOT)),
            ("yahoo_finance", lambda: yahoo_finance_search("0700.HK", symbol="0700.HK", period="FY2025")),
            ("hkex_announcements", lambda: hkex_announcement_search("Tencent 2025 annual", symbol="0700.HK", period="FY2025")),
        ],
    },
    "US": {
        "symbol": "TSLA",
        "period": "FY2025",
        "engines": [
            ("local_real_data", lambda: local_real_data_search("Tesla", symbol="TSLA", period="FY2025", raw_data_root=RAW_ROOT)),
            ("yahoo_finance", lambda: yahoo_finance_search("TSLA", symbol="TSLA", period="FY2025")),
            ("sec_edgar", lambda: sec_edgar_search("Tesla 10-K FY2025", symbol="TSLA", period="FY2025")),
            ("independent_macro", lambda: independent_macro_search("electric vehicle market 2025", symbol="TSLA", period="FY2025")),
        ],
    },
}


def run_simulation() -> None:
    for market_name, config in MARKETS.items():
        print(f"\n{'='*60}")
        print(f"Simulating {market_name} retrieval ({config['symbol']} {config['period']})")
        print(f"{'='*60}")

        out_dir = BASE / market_name
        out_dir.mkdir(parents=True, exist_ok=True)

        all_hits = []
        engine_meta = {}

        for engine_name, engine_fn in config["engines"]:
            print(f"  Engine: {engine_name}...", end=" ", flush=True)
            try:
                t0 = time.time()
                result = engine_fn()
                elapsed = round(time.time() - t0, 2)
                hits = result.get("hits", [])
                meta = result.get("meta", {})
                hit_count = len(hits)
                print(f"{hit_count} hits in {elapsed}s")
                engine_meta[engine_name] = {
                    "hit_count": hit_count,
                    "elapsed_sec": elapsed,
                    "meta": meta,
                }
                # Save raw hits per engine
                if hits:
                    engine_file = out_dir / f"engine_{engine_name}.json"
                    engine_file.write_text(
                        json.dumps({
                            "engine": engine_name,
                            "symbol": config["symbol"],
                            "period": config["period"],
                            "meta": meta,
                            "hits": hits,
                        }, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    all_hits.extend(hits)
            except Exception as exc:
                err_msg = str(exc)[:200]
                print(f"FAILED: {err_msg}")
                engine_meta[engine_name] = {"error": err_msg}

        # Write consolidated summary
        summary = {
            "market": market_name,
            "symbol": config["symbol"],
            "period": config["period"],
            "simulated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "engine_results": engine_meta,
            "total_raw_hits": len(all_hits),
        }
        summary_file = out_dir / "00_simulation_summary.json"
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        if all_hits:
            all_file = out_dir / "all_engine_hits.json"
            all_file.write_text(
                json.dumps(all_hits, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        print(f"\n  → {out_dir}/")
        print(f"    - 00_simulation_summary.json")
        print(f"    - all_engine_hits.json ({len(all_hits)} total hits)")
        for e in engine_meta:
            print(f"    - engine_{e}.json")


if __name__ == "__main__":
    run_simulation()
