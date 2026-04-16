"""Risk signal extraction from normalized evidence text."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


RISK_KEYWORDS = [
    "risk",
    "decline",
    "volatility",
    "pressure",
    "challenge",
    "loss",
    "uncertain",
]


def _risk_hits(text: str) -> int:
    lowered = (text or "").lower()
    return sum(1 for kw in RISK_KEYWORDS if kw in lowered)


def build_risk_signals(manifest_df: pd.DataFrame) -> pd.DataFrame:
    working = manifest_df.copy()
    working["risk_keyword_hits"] = working["content"].astype(str).apply(_risk_hits)
    grouped = (
        working.groupby("symbol", dropna=False)
        .agg(
            total_evidence=("sample_id", "count"),
            risk_keyword_hits=("risk_keyword_hits", "sum"),
        )
        .reset_index()
    )
    grouped["risk_ratio"] = grouped["risk_keyword_hits"] / grouped["total_evidence"].clip(lower=1)
    grouped["risk_level"] = grouped["risk_ratio"].apply(
        lambda x: "high" if x >= 1.0 else ("medium" if x >= 0.3 else "low")
    )
    return grouped


def save_risk_signals(df: pd.DataFrame, output_path: str | Path = "data/features/risk_signals.parquet") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out

