#!/usr/bin/env python3
"""Stage 2 smoke runner: fetch mock data and write parquet manifests."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.fetch_financials import FinancialsFetcher
from src.data.fetch_filings import FilingsFetcher
from src.data.fetch_market import MarketFetcher
from src.data.fetch_news import NewsFetcher
from src.data.manifest import build_manifest, write_manifest_parquet


def main() -> int:
    fetchers = [
        MarketFetcher(mode="mock"),
        FinancialsFetcher(mode="mock"),
        NewsFetcher(mode="mock"),
        FilingsFetcher(mode="mock"),
    ]

    total = 0
    for fetcher in fetchers:
        raw = fetcher.fetch()
        manifest = build_manifest(raw, source_type=fetcher.source_type)
        out_path = write_manifest_parquet(manifest, f"data/curated/{fetcher.source_type}.parquet")
        total += len(manifest)
        print(f"[stage2] {fetcher.source_type}: {len(manifest)} rows -> {out_path}")

    print(f"[stage2] total_rows={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
