"""Company profile fetcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.data.fetch_base import BaseFetcher


class CompanyProfileFetcher(BaseFetcher):
    @property
    def source_type(self) -> str:
        return "company_profile"

    @property
    def default_mock_path(self) -> Path:
        return Path("data/raw/mock/company_profile.jsonl")

    def _read_real_data(self) -> List[Dict[str, Any]]:
        path = self._resolve_real_file("company_profile.json")
        if not path.exists():
            raise FileNotFoundError(f"real data file not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        company_name = str(payload.get("company_name", "")).strip()
        industry = str(payload.get("industry", "")).strip()
        sector = str(payload.get("sector", "")).strip()
        description = str(payload.get("description", "")).strip()

        return [
            {
                "symbol": str(payload.get("symbol", self.symbol or "")).strip(),
                "period": str(payload.get("period", self.period or "")).strip(),
                "title": f"{company_name} profile".strip(),
                "publish_time": str(payload.get("as_of_date", "")).strip(),
                "content": f"Industry={industry}; Sector={sector}; Description={description}",
                "source_url": str(payload.get("source_url", "")).strip(),
                "trust_level": str(payload.get("trust_level", "high")).strip() or "high",
            }
        ]

