"""Programmatic trend feature generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_trend_features(manifest_df: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "period", "sample_id", "source_type", "publish_time"}
    for col in required:
        if col not in manifest_df.columns:
            manifest_df = manifest_df.copy()
            manifest_df[col] = None
    grouped = (
        manifest_df.groupby(["symbol", "period"], dropna=False)
        .agg(
            evidence_count=("sample_id", "count"),
            unique_sources=("source_type", "nunique"),
            latest_publish_time=("publish_time", "max"),
            sample_ids=("sample_id", lambda s: "|".join(sorted({str(x) for x in s.dropna().tolist()}))),
        )
        .reset_index()
    )
    return grouped


def save_trend_features(df: pd.DataFrame, output_path: str | Path = "data/features/trend_analysis.parquet") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out
