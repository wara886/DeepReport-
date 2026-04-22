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
            revenue_growth = str(row.get("revenue_growth_pct", "")).strip()
            margin = str(row.get("gross_margin_pct", "")).strip()
            net_margin = str(row.get("net_margin_pct", "")).strip()
            roe = str(row.get("roe_pct", "")).strip()
            roa = str(row.get("roa_pct", "")).strip()
            operating_cash_flow = str(row.get("operating_cash_flow_billion", "")).strip()
            free_cash_flow = str(row.get("free_cash_flow_billion", "")).strip()
            output.append(
                {
                    "symbol": str(row.get("symbol", self.symbol or "")).strip(),
                    "period": str(row.get("period", self.period or "")).strip(),
                    "title": f"{row.get('symbol', self.symbol or '')} financial snapshot".strip(),
                    "publish_time": str(row.get("publish_time", "")).strip(),
                    "content": (
                        f"Revenue {revenue}B, revenue growth {revenue_growth}%, gross margin {margin}%, "
                        f"net margin {net_margin}%, ROE {roe}%, ROA {roa}%, "
                        f"operating cash flow {operating_cash_flow}B, free cash flow {free_cash_flow}B."
                    ),
                    "source_url": str(row.get("source_url", "")).strip(),
                    "trust_level": str(row.get("trust_level", "high")).strip() or "high",
                }
            )
        return output
