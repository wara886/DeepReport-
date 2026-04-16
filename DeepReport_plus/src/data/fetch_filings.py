"""Regulatory filing fetcher."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from src.data.fetch_base import BaseFetcher


class FilingsFetcher(BaseFetcher):
    @property
    def source_type(self) -> str:
        return "filings"

    @property
    def default_mock_path(self) -> Path:
        return Path("data/raw/mock/filings.jsonl")

    def _read_real_data(self) -> List[Dict[str, str]]:
        path = self._resolve_real_file("filings.jsonl")
        rows = self._read_records(path)
        output: List[Dict[str, str]] = []
        for row in rows:
            output.append(
                {
                    "symbol": str(row.get("symbol", self.symbol or "")).strip(),
                    "period": str(row.get("period", self.period or "")).strip(),
                    "title": str(row.get("title", "")).strip(),
                    "publish_time": str(row.get("publish_time", "")).strip(),
                    "content": str(row.get("content", "")).strip(),
                    "source_url": str(row.get("source_url", "")).strip(),
                    "trust_level": str(row.get("trust_level", "high")).strip() or "high",
                }
            )
        return output
