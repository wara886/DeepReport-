"""Base fetcher abstraction for local/offline data ingestion."""

from __future__ import annotations

from abc import ABC, abstractmethod
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


class BaseFetcher(ABC):
    """Abstract fetcher supporting mock/local_file/local_file_real/future_api modes."""

    SUPPORTED_MODES = {"mock", "local_file", "local_file_real", "future_api"}

    def __init__(
        self,
        mode: str = "mock",
        local_path: str | None = None,
        real_data_root: str = "data/raw/real_data",
        symbol: str | None = None,
        period: str | None = None,
        real_file_path: str | None = None,
    ):
        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        self.mode = mode
        self.local_path = local_path
        self.real_data_root = real_data_root
        self.symbol = symbol
        self.period = period
        self.real_file_path = real_file_path

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Canonical source type name."""

    @property
    @abstractmethod
    def default_mock_path(self) -> Path:
        """Default path for mock fixture file."""

    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch records using currently configured mode."""
        if self.mode == "mock":
            return self._read_records(self.default_mock_path)
        if self.mode == "local_file":
            if not self.local_path:
                raise ValueError("local_path is required for local_file mode")
            return self._read_records(Path(self.local_path))
        if self.mode == "local_file_real":
            return self._read_real_data()
        return self._fetch_future_api()

    def _read_records(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        suffix = path.suffix.lower()
        if suffix == ".jsonl":
            items: List[Dict[str, Any]] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    items.append(json.loads(line))
            return items

        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            raise ValueError(f"JSON input must be a list: {path}")

        if suffix == ".csv":
            rows: List[Dict[str, Any]] = []
            with path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rows.append(dict(row))
            return rows

        raise ValueError(f"Unsupported input format: {path}")

    def _resolve_real_file(self, default_filename: str) -> Path:
        if self.real_file_path:
            return Path(self.real_file_path)
        if not self.symbol or not self.period:
            raise ValueError("symbol and period are required for local_file_real mode")
        return Path(self.real_data_root) / self.symbol / self.period / default_filename

    def _read_real_data(self) -> List[Dict[str, Any]]:
        raise NotImplementedError(f"{self.__class__.__name__} must implement _read_real_data")

    def _fetch_future_api(self) -> List[Dict[str, Any]]:
        # Stage 2 constraint: no online fetching yet.
        raise RuntimeError("future_api mode is reserved for later stages and is disabled in Stage 2")
