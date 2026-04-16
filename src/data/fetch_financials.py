"""Financial statement fetcher."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from src.data.fetch_base import BaseFetcher


class FinancialsFetcher(BaseFetcher):
    @property
    def source_type(self) -> str:
        return "financials"

    @property
    def default_mock_path(self) -> Path:
        return Path("data/raw/mock/financials.jsonl")

    def _read_real_data(self) -> List[Dict[str, str]]:
        path = self._resolve_real_file("financials.csv")
        rows = self._read_records(path)
        output: List[Dict[str, str]] = []
        for row in rows:
            revenue = str(row.get("revenue_billion", "")).strip()
            margin = str(row.get("gross_margin_pct", "")).strip()
            output.append(
                {
                    "symbol": str(row.get("symbol", self.symbol or "")).strip(),
                    "period": str(row.get("period", self.period or "")).strip(),
                    "title": f"{row.get('symbol', self.symbol or '')} financial snapshot".strip(),
                    "publish_time": str(row.get("publish_time", "")).strip(),
                    "content": f"Revenue {revenue}B, gross margin {margin}%.",
                    "source_url": str(row.get("source_url", "")).strip(),
                    "trust_level": str(row.get("trust_level", "high")).strip() or "high",
                }
            )
        return output
