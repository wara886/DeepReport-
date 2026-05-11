from pathlib import Path

import pyarrow.parquet as pq

from src.data.fetch_market import MarketFetcher
from src.data.fetch_news import NewsFetcher
from src.data.manifest import build_manifest, write_manifest_parquet


def test_market_fetcher_local_file_mode():
    fetcher = MarketFetcher(mode="local_file", local_path="tests/fixtures/market_sample.jsonl")
    rows = fetcher.fetch()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NVDA"


def test_build_manifest_deduplicates_news():
    fetcher = NewsFetcher(mode="mock")
    rows = fetcher.fetch()
    manifest = build_manifest(rows, source_type=fetcher.source_type)
    assert len(manifest) == 2
    assert set(manifest[0].keys()) == {
        "sample_id",
        "source_type",
        "symbol",
        "period",
        "title",
        "publish_time",
        "content",
        "source_url",
        "trust_level",
    }


def test_write_manifest_parquet(tmp_path: Path):
    fetcher = MarketFetcher(mode="local_file", local_path="tests/fixtures/market_sample.jsonl")
    manifest = build_manifest(fetcher.fetch(), source_type="market")
    out = write_manifest_parquet(manifest, tmp_path / "market.parquet")
    table = pq.read_table(out)
    assert table.num_rows == 1
    assert "sample_id" in table.column_names
