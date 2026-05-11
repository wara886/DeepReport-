"""Market data fetcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.data.fetch_base import BaseFetcher


class MarketFetcher(BaseFetcher):
    @property
    def source_type(self) -> str:
        return "market"

    @property
    def default_mock_path(self) -> Path:
        return Path("data/raw/mock/market.jsonl")

    def _read_real_data(self) -> List[Dict[str, Any]]:
        path = self._resolve_real_file("market.csv")
        rows = self._read_records(path)
        output: List[Dict[str, Any]] = []
        for row in rows:
            close = str(row.get("close", "")).strip()
            volume = str(row.get("volume", "")).strip()
            output.append(
                {
                    "symbol": str(row.get("symbol", self.symbol or "")).strip(),
                    "period": str(row.get("period", self.period or "")).strip(),
                    "title": f"{row.get('symbol', self.symbol or '')} market snapshot".strip(),
                    "publish_time": str(row.get("publish_time", "")).strip(),
                    "content": f"close={close}, volume={volume}",
                    "source_url": str(row.get("source_url", "")).strip(),
                    "trust_level": str(row.get("trust_level", "high")).strip() or "high",
                }
            )
        return output
