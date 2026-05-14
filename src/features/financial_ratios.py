"""Programmatic financial ratio feature extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd


_RE_REVENUE = re.compile(r"revenue\s*([0-9]+(?:\.[0-9]+)?)\s*b", flags=re.IGNORECASE)
_RE_REVENUE_GROWTH = re.compile(r"revenue\s*growth\s*([0-9]+(?:\.[0-9]+)?)\s*%", flags=re.IGNORECASE)
_RE_MARGIN = re.compile(r"gross\s*margin\s*([0-9]+(?:\.[0-9]+)?)\s*%", flags=re.IGNORECASE)
_RE_NET_MARGIN = re.compile(r"net\s*margin\s*([0-9]+(?:\.[0-9]+)?)\s*%", flags=re.IGNORECASE)
_RE_ROE = re.compile(r"roe\s*([0-9]+(?:\.[0-9]+)?)\s*%", flags=re.IGNORECASE)
_RE_ROA = re.compile(r"roa\s*([0-9]+(?:\.[0-9]+)?)\s*%", flags=re.IGNORECASE)
_RE_OPERATING_CASH_FLOW = re.compile(
    r"operating\s*cash\s*flow\s*([0-9]+(?:\.[0-9]+)?)\s*b",
    flags=re.IGNORECASE,
)
_RE_FREE_CASH_FLOW = re.compile(
    r"free\s*cash\s*flow\s*([0-9]+(?:\.[0-9]+)?)\s*b",
    flags=re.IGNORECASE,
)


def _extract_revenue_billion(text: str) -> float | None:
    match = _RE_REVENUE.search(text or "")
    return float(match.group(1)) if match else None


def _extract_gross_margin_pct(text: str) -> float | None:
    match = _RE_MARGIN.search(text or "")
    return float(match.group(1)) if match else None


def _extract_value(text: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.search(text or "")
    return float(match.group(1)) if match else None


def build_financial_ratios(manifest_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, item in manifest_df.iterrows():
        content = str(item.get("content", ""))
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        # Pass-through fields from SEC metadata (preferred over regex extraction from text)
        _meta_fcf = metadata.get("free_cash_flow_billion")
        _meta_ocf = metadata.get("operating_cash_flow_billion")
        rows.append(
            {
                "sample_id": item.get("sample_id", ""),
                "symbol": item.get("symbol", ""),
                "period": item.get("period", ""),
                "source_type": item.get("source_type", ""),
                "sector": metadata.get("sector", ""),
                "industry": metadata.get("industry", ""),
                "revenue_billion": _extract_revenue_billion(content),
                "revenue_growth_pct": _extract_value(content, _RE_REVENUE_GROWTH),
                "gross_margin_pct": _extract_gross_margin_pct(content),
                "net_margin_pct": _extract_value(content, _RE_NET_MARGIN),
                "roe_pct": _extract_value(content, _RE_ROE),
                "roa_pct": _extract_value(content, _RE_ROA),
                "operating_cash_flow_billion": _meta_ocf if _meta_ocf is not None else _extract_value(content, _RE_OPERATING_CASH_FLOW),
                "free_cash_flow_billion": _meta_fcf if _meta_fcf is not None else _extract_value(content, _RE_FREE_CASH_FLOW),
                "free_cash_flow_methodology": metadata.get("free_cash_flow_methodology"),
                "finance_lease_payments_billion": metadata.get("finance_lease_payments_billion"),
                "income_tax_billion": metadata.get("income_tax_billion"),
                "income_tax_benefit_billion": metadata.get("income_tax_benefit_billion"),
                "restructuring_charges_billion": metadata.get("restructuring_charges_billion"),
                "asset_impairment_billion": metadata.get("asset_impairment_billion"),
                "shareholder_equity_billion": metadata.get("shareholder_equity_billion"),
                "total_assets_billion": metadata.get("total_assets_billion"),
                "is_quarterly": bool(metadata.get("is_quarterly", False)),
                "annualization_factor": int(metadata.get("annualization_factor") or 1),
            }
        )
    return pd.DataFrame(rows)


def save_financial_ratios(df: pd.DataFrame, output_path: str | Path = "data/features/financial_ratios.parquet") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out
