"""Programmatic financial ratio feature extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd


_RE_REVENUE = re.compile(r"revenue\s*([0-9]+(?:\.[0-9]+)?)\s*b", flags=re.IGNORECASE)
_RE_MARGIN = re.compile(r"gross\s*margin\s*([0-9]+(?:\.[0-9]+)?)\s*%", flags=re.IGNORECASE)


def _extract_revenue_billion(text: str) -> float | None:
    match = _RE_REVENUE.search(text or "")
    return float(match.group(1)) if match else None


def _extract_gross_margin_pct(text: str) -> float | None:
    match = _RE_MARGIN.search(text or "")
    return float(match.group(1)) if match else None


def build_financial_ratios(manifest_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, item in manifest_df.iterrows():
        content = str(item.get("content", ""))
        rows.append(
            {
                "sample_id": item.get("sample_id", ""),
                "symbol": item.get("symbol", ""),
                "period": item.get("period", ""),
                "source_type": item.get("source_type", ""),
                "revenue_billion": _extract_revenue_billion(content),
                "gross_margin_pct": _extract_gross_margin_pct(content),
            }
        )
    return pd.DataFrame(rows)


def save_financial_ratios(df: pd.DataFrame, output_path: str | Path = "data/features/financial_ratios.parquet") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out

