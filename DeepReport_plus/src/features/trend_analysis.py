"""Programmatic trend feature generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_trend_features(manifest_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        manifest_df.groupby(["symbol", "period"], dropna=False)
        .agg(
            evidence_count=("sample_id", "count"),
            unique_sources=("source_type", "nunique"),
            latest_publish_time=("publish_time", "max"),
        )
        .reset_index()
    )
    return grouped


def save_trend_features(df: pd.DataFrame, output_path: str | Path = "data/features/trend_analysis.parquet") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out

