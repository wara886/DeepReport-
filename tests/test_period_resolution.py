"""Tests for period alias resolution in local data search."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.search.search_manager import _load_real_data_records, _resolve_period


def _make_symbol_dir(root: Path, symbol: str, periods: list[str]) -> None:
    for period in periods:
        period_dir = root / symbol / period
        period_dir.mkdir(parents=True, exist_ok=True)
        (period_dir / "company_profile.json").write_text(
            json.dumps({"description": f"{symbol} {period} profile", "source_url": "", "as_of_date": "", "trust_level": "high"}),
            encoding="utf-8",
        )


def test_resolve_period_latest_quarter_picks_most_recent():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2024Q3", "2024Q4", "2025Q1", "2025Q4"])
        symbol_dir = root / "NVDA"
        result = _resolve_period(symbol_dir, "latest_quarter")
        assert result == ["2025Q4"]


def test_resolve_period_latest_picks_most_recent():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "AAPL", ["2023Q4", "2024Q1", "2024Q4"])
        symbol_dir = root / "AAPL"
        assert _resolve_period(symbol_dir, "latest") == ["2024Q4"]


def test_resolve_period_none_picks_most_recent():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "MSFT", ["2024Q2", "2025Q1"])
        symbol_dir = root / "MSFT"
        assert _resolve_period(symbol_dir, None) == ["2025Q1"]


def test_resolve_period_exact_match():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2024Q4", "2025Q4"])
        symbol_dir = root / "NVDA"
        assert _resolve_period(symbol_dir, "2024Q4") == ["2024Q4"]


def test_resolve_period_prefix_match():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2025Q1", "2025Q4"])
        symbol_dir = root / "NVDA"
        # "2025" prefix matches "2025Q1" (first alphabetically after sort+reverse)
        result = _resolve_period(symbol_dir, "2025")
        assert len(result) == 1
        assert result[0].startswith("2025")


def test_resolve_period_no_match_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2025Q4"])
        symbol_dir = root / "NVDA"
        assert _resolve_period(symbol_dir, "1999Q1") == []


def test_resolve_period_nonexistent_dir_returns_empty():
    result = _resolve_period(Path("/nonexistent/path"), "latest_quarter")
    assert result == []


def test_load_real_data_records_latest_quarter():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2024Q4", "2025Q4"])
        records = _load_real_data_records(str(root), "NVDA", "latest_quarter")
        assert len(records) > 0
        assert all(r["period"] == "2025Q4" for r in records)


def test_load_real_data_records_exact_period():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2024Q4", "2025Q4"])
        records = _load_real_data_records(str(root), "NVDA", "2024Q4")
        assert len(records) > 0
        assert all(r["period"] == "2024Q4" for r in records)


def test_load_real_data_records_unknown_period_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2025Q4"])
        records = _load_real_data_records(str(root), "NVDA", "1999Q1")
        assert records == []


def test_load_real_data_records_missing_symbol_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_symbol_dir(root, "NVDA", ["2025Q4"])
        records = _load_real_data_records(str(root), "AAPL", "latest_quarter")
        assert records == []
